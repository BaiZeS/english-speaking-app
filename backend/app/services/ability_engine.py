"""能力画像更新管线 (计划 §5.6, 阶段 P3).

每一次"有评分证据"的练习 (打基础步骤 / 实战对话轮 / 自由对话轮 / 测评 P4) 都会:

1. 往 ``ability_events`` **写一条/维度** —— 包括被门控的 (``weight=0``): 流水是全量
   审计 + 轨迹视图的数据源, 画像 (``ability_profiles``) 只是它的可重建物化快照;
2. 对**未被门控**的证据按维度独立 EWMA 更新画像:

   ``new = old * (1 - alpha * w) + evidence * (alpha * w)``

   * ``w = 0`` 当来源是占位家族 (``stub`` / ``heuristic`` / ``skip``) ——
     本机讯飞没 key, StubASR 恒 95 分, 不门控会把画像一路推高 (§四 决策表);
   * 各维度 ``alpha`` 见 :data:`ALPHA`;
   * 该维度首条真凭据时直接**种子化** (``new = evidence``), 不从 0 爬 ——
     从 0 爬会让第一次真实发音永远拖低画像, 也违背 "NULL = 没有证据" 的口径。

维度证据的口径 (§5.6):

* 发音 ← ISE: 有参考文本的评分 ``exact_reference``, 或**自由产出的转写锚定 ISE**
  (``transcript_anchored``, ref=IAT 转写; 生产者在 ``app.services.mission_engine``,
  讯飞没配凭据时直接不产出 —— 拿 StubASR 的"回声"打自由产出等于白送 95 分);
* 语法 / 词汇 ← LLM 判分;
* 流利度 ← ISE fluency + speech_rate_wpm 综合 —— 综合发生在
  :func:`app.scoring.read_along.score_read_along` (rate_score*0.4 + 停顿分, 再被
  发音/完整封顶), 画像直接吃这条已综合的 fluency, 不再二次加权。

本模块**从不 commit**: 事件与画像和调用方的会话快照同笔提交/回滚 —— 输掉乐观锁的
请求不能留下半条证据 (并发纪律见 ``api/v1/course_sessions.py``)。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AbilityEvent, AbilityProfile
from app.services.drill_grader import AbilityEvidence, Dimension

# ====== 口径常量 (改动会直接改画像曲线, 谨慎) ======

#: 四维权度与展示顺序 (§5.6).
DIMENSIONS: tuple[Dimension, ...] = ("pronunciation", "grammar", "vocabulary", "fluency")

#: 每维度的 EWMA 步长. 取值理由:
#:   * 发音/流利 0.25 —— ISE 是连续量测, 单条证据可信但样本间抖动大 (内容难度不同),
#:     稍快的步长让"最近练得好不好"能跟上真实练习, 又不至于一次发挥带飞 (25% 封顶);
#:   * 语法/词汇 0.20 —— LLM 判分带模型噪声, 压一档避免一次判分的偏差挂太久。
ALPHA: dict[Dimension, float] = {
    "pronunciation": 0.25,
    "fluency": 0.25,
    "grammar": 0.20,
    "vocabulary": 0.20,
}

#: 占位来源家族: 这些事件 **w 强制为 0** (画像绝不因它们移动半格).
#: 取值与 drill_grader 的 ``source`` 枚举 / ``SKIP_SOURCE`` 对齐.
GATED_SOURCES = frozenset({"stub", "heuristic", "skip"})

#: 分数落库精度.
_PRECISION = 2


def _as_utc(dt: datetime) -> datetime:
    """sqlite 会剥掉 tzinfo, 统一按 UTC 解释 (同 ``course_sessions._iso``)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return _as_utc(dt).isoformat()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _effective_weight(event: AbilityEvidence) -> float:
    """证据的最终权重: 门控来源一票否决为 0, 其余夹在 [0, 1]."""
    if event.source in GATED_SOURCES:
        return 0.0
    return max(0.0, min(1.0, float(event.weight)))


def ewma_next(
    old: float | None,
    evidence: float,
    *,
    dimension: Dimension,
    weight: float,
    alpha: float | None = None,
) -> float:
    """单步 EWMA (§5.6 公式), 纯函数.

    调用前提: 有效权重 > 0 (门控过的证据不该走到这里, 见 :func:`apply_evidence`)。
    首条证据种子化: ``old is None -> evidence``; 否则按 ``new = old*(1-alpha*w) + evidence*(alpha*w)`` 更新。

    ``alpha`` 覆写默认步长 (:data:`ALPHA`): P4 测评判级是**专程的一次性测量**,
    用 0.6 重拉 (见 ``assessment_engine.ASSESSMENT_ALPHA``); 缺省 None = 维度默认,
    既有调用方一个字不用改。
    """
    if old is None:
        return round(evidence, _PRECISION)
    step = (ALPHA[dimension] if alpha is None else float(alpha)) * max(0.0, min(1.0, weight))
    return round(old * (1.0 - step) + evidence * step, _PRECISION)


@dataclass(frozen=True)
class DimensionUpdate:
    """一条证据作用到画像上的结果 (给测试与日志用, 不入库)."""

    dimension: Dimension
    before: float | None
    after: float | None
    weighted: bool


def apply_evidence(
    values: dict[str, float | None],
    counts: dict[str, int],
    event: AbilityEvidence,
    *,
    alpha: float | None = None,
) -> DimensionUpdate:
    """把一条证据作用到内存画像上 (原地更新 ``values`` / ``counts``).

    被门控 (w=0) 的证据: 画像与 n 都不动 —— 返回 ``weighted=False``。
    ``alpha`` 覆写默认步长 (P4 测评用 0.6), 缺省 = 维度默认。
    """
    dim = event.dimension
    weight = _effective_weight(event)
    before = values.get(dim)
    if weight <= 0.0:
        return DimensionUpdate(dimension=dim, before=before, after=before, weighted=False)
    after = ewma_next(before, event.score, dimension=dim, weight=weight, alpha=alpha)
    values[dim] = after
    counts[dim] = counts.get(dim, 0) + 1
    return DimensionUpdate(dimension=dim, before=before, after=after, weighted=True)


# ====== 画像读写 ======


def _blank_dims() -> dict[str, float | None]:
    return dict.fromkeys(DIMENSIONS, None)


@dataclass(frozen=True)
class ProfileSnapshot:
    """画像的普通 dict 视图 (落 doc 快照 / API 载荷都吃它)."""

    dims: dict[str, float | None]
    counts: dict[str, int]
    cefr_level: str | None
    assessment_cefr: str | None
    band_locked: bool
    updated_at: str | None

    def snapshot(self) -> dict[str, float | None]:
        """4 维分 (开局时落进会话 doc 作 ability_delta 基线)."""
        return dict(self.dims)


def profile_to_snapshot(profile: AbilityProfile | None) -> ProfileSnapshot:
    """ORM 行 -> 视图; ``None`` (还没画像) 给出全 NULL + 全 0 的空画像."""
    if profile is None:
        return ProfileSnapshot(
            dims=_blank_dims(),
            counts=dict.fromkeys(DIMENSIONS, 0),
            cefr_level=None,
            assessment_cefr=None,
            band_locked=False,
            updated_at=None,
        )
    return ProfileSnapshot(
        dims={
            "pronunciation": profile.pronunciation,
            "grammar": profile.grammar,
            "vocabulary": profile.vocabulary,
            "fluency": profile.fluency,
        },
        counts={
            "pronunciation": int(profile.pronunciation_n),
            "grammar": int(profile.grammar_n),
            "vocabulary": int(profile.vocabulary_n),
            "fluency": int(profile.fluency_n),
        },
        cefr_level=profile.cefr_level,
        assessment_cefr=profile.assessment_cefr,
        band_locked=bool(profile.band_locked),
        updated_at=_iso(profile.updated_at),
    )


async def get_profile(db: AsyncSession, user_id: str) -> AbilityProfile | None:
    res = await db.execute(select(AbilityProfile).where(AbilityProfile.user_id == user_id))
    return res.scalar_one_or_none()


async def get_snapshot(db: AsyncSession, user_id: str) -> ProfileSnapshot:
    return profile_to_snapshot(await get_profile(db, user_id))


async def record_step_evidence(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str | None = "",
    step_id: str = "",
    evidence: Sequence[AbilityEvidence],
    alpha: float | None = None,
) -> int:
    """§5.6 管线的写入口 (也是 T3 在 ``/step`` 里留的钩子 ``record_step_evidence`` 的真身).

    T4 起从"空钩子"变成实现: 每次评分尝试 (含全 stub 的尝试) 都会落全量事件流水,
    但只有未门控证据会推动画像。**不 commit** —— 事件、画像更新与调用方的 doc /
    practice_steps 行同一事务, 输掉乐观锁时一起回滚. 空 ``evidence`` (如跳过步) 是
    纯 no-op, 返回落库的事件条数。

    ``alpha`` 覆写默认 EWMA 步长 (P4 测评 complete 用 0.6, 见
    ``assessment_engine.ASSESSMENT_ALPHA``); 缺省 None = 既有口径不变。
    """
    if not evidence:
        return 0
    events = list(evidence)
    for event in events:
        db.add(
            AbilityEvent(
                user_id=user_id,
                dimension=str(event.dimension),
                score=float(event.score),
                weight=_effective_weight(event),
                source_kind=str(event.source),
                ise_ref_mode=event.ise_ref_mode,
                session_id=session_id or None,
                step_id=step_id,
            )
        )
    moving = [event for event in events if _effective_weight(event) > 0.0]
    if not moving:
        # 全被门控: 只留流水, 连画像行都不建 (空画像 = 没证据, 语义更诚实).
        return len(events)
    profile = await get_profile(db, user_id)
    if profile is None:
        profile = AbilityProfile(user_id=user_id)
        db.add(profile)
        await db.flush()
    values: dict[str, float | None] = {
        "pronunciation": profile.pronunciation,
        "grammar": profile.grammar,
        "vocabulary": profile.vocabulary,
        "fluency": profile.fluency,
    }
    counts: dict[str, int] = {
        "pronunciation": int(profile.pronunciation_n),
        "grammar": int(profile.grammar_n),
        "vocabulary": int(profile.vocabulary_n),
        "fluency": int(profile.fluency_n),
    }
    for event in moving:
        update = apply_evidence(values, counts, event, alpha=alpha)
        logger.bind(ability=True).debug(
            "ability ewma | user={} dim={} w={} before={} after={}",
            user_id,
            update.dimension,
            _effective_weight(event),
            update.before,
            update.after,
        )
    profile.pronunciation = values["pronunciation"]
    profile.grammar = values["grammar"]
    profile.vocabulary = values["vocabulary"]
    profile.fluency = values["fluency"]
    profile.pronunciation_n = counts["pronunciation"]
    profile.grammar_n = counts["grammar"]
    profile.vocabulary_n = counts["vocabulary"]
    profile.fluency_n = counts["fluency"]
    profile.updated_at = _utcnow()
    return len(events)


# ====== 画像重建 (快照丢失/口径改动时的逃生门, §5.2: "可重建") ======


def rebuild_dims(rows: Sequence[tuple[str, float, float]]) -> dict[str, float | None]:
    """按时间顺序重放 ``(dimension, score, weight)`` -> 4 维快照.

    纯函数: 画像表只是物化快照, 任何时候都能从 ``ability_events`` 整表重放还原 —
    测试拿它对照 EWMA 结果, 运维口径改动后可用它 rebuild profiles.
    """
    values = _blank_dims()
    for dimension, score, weight in rows:
        dim = cast(Dimension, dimension)
        if dim not in values or weight <= 0.0:
            continue
        values[dim] = ewma_next(values[dim], score, dimension=dim, weight=weight)
    return values


def ability_delta(
    before: dict[str, float | None] | None,
    after: dict[str, float | None] | None,
) -> dict[str, float | None]:
    """本次练习对 4 维的**实际拉动** (§5.3 ReviewReport.ability_delta).

    逐维 ``after - before``; 任一侧为 ``None`` (该维没有过可信证据) 该维即 ``None``
    —— "没测过" 不是 "拉动了 0", 别拿 0 冒充 (与分数列可空同一套口径)。
    """
    left = before or _blank_dims()
    right = after or _blank_dims()
    delta: dict[str, float | None] = {}
    for dim in DIMENSIONS:
        a, b = left.get(dim), right.get(dim)
        delta[dim] = None if (a is None or b is None) else round(b - a, _PRECISION)
    return delta


# ====== CEFR 映射 (§5.6; P4 测评写入 assessment_cefr) ======

#: CEFR 顺序 (band 索引 = 元组下标).
CEFR_ORDER: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

#: 4 维均分 -> 等级的映射门槛 (取第一个 ``avg < 上限`` 的等级).
#: 口径与评分直觉一致: <40 够不着日常交流 (A1), 40-54 (A2), 55-69 (B1: 能应付
#: 多数场景 — 与 drill 的 60 及格线对齐), 70-84 (B2), 85-94 (C1), >=95 (C2).
CEFR_UPPER_BOUNDS: tuple[tuple[float, str], ...] = (
    (40.0, "A1"),
    (55.0, "A2"),
    (70.0, "B1"),
    (85.0, "B2"),
    (95.0, "C1"),
    (101.0, "C2"),
)


def level_from_avg(avg: float) -> str:
    """均分 -> CEFR 档 (映射表见 :data:`CEFR_UPPER_BOUNDS`)."""
    for bound, level in CEFR_UPPER_BOUNDS:
        if avg < bound:
            return level
    return "C2"


def derived_level(dims: dict[str, float | None]) -> str | None:
    """从 4 维分映射的**参考**等级 (全 NULL -> None).

    这不是权威定级: 权威是 ``cefr_level`` (测评驱动, null pre-assessment)。放这里
    是为了画像页在测评前也能给"按当前四维大概是 B1"级别的中性提示, 也是 P4 判级
    后 ±1 band 锁带 (:func:`resolve_level`) 的输入。
    """
    scores = [value for value in dims.values() if value is not None]
    if not scores:
        return None
    return level_from_avg(sum(scores) / len(scores))


def band_clamp(candidate: str, anchor: str, *, max_drift: int = 1) -> str:
    """把 ``candidate`` 收进 ``anchor`` ±``max_drift`` 个 band 的范围 (§5.2 锁带)."""
    if anchor not in CEFR_ORDER:
        return candidate
    if candidate not in CEFR_ORDER:
        return anchor
    lo = max(0, CEFR_ORDER.index(anchor) - max_drift)
    hi = min(len(CEFR_ORDER) - 1, CEFR_ORDER.index(anchor) + max_drift)
    return CEFR_ORDER[max(lo, min(hi, CEFR_ORDER.index(candidate)))]


def resolve_level(
    *,
    assessment: str | None,
    derived: str | None,
    band_locked: bool = False,
) -> str | None:
    """画像页 CEFR 徽章口径 (§5.6: profile_cefr 由 4 维映射, band_locked 只 ±1 漂移).

    * 有测评结论: 以测评为准; ``band_locked`` 时允许四维映射把它拉开, 但最多
      ±1 band (一次发挥失常/超常不能把徽章直接打到 A1/C2);
    * 没有测评结论: 返回 ``None`` —— **未测评就是未测评**, 系统映射只作为
      :func:`derived_level` 的独立辅助字段出现, 不冒充官方等级。
    """
    if assessment is None:
        return None
    if not band_locked or derived is None:
        return assessment
    return band_clamp(derived, assessment)


# ====== 轨迹聚合 (GET /ability 的原料) ======


@dataclass(frozen=True)
class TrajectoryPoint:
    """一天的 4 维证据均值 (无证据的维度是 ``None``)."""

    date: str
    pronunciation: float | None
    grammar: float | None
    vocabulary: float | None
    fluency: float | None
    events: int


def bucket_events(
    rows: Sequence[tuple[datetime, str, float, float]],
    *,
    days: int,
) -> list[TrajectoryPoint]:
    """``(created_at, dimension, score, weight)`` 流水 -> 逐日均值序列 (升序).

    * 只聚合 ``weight > 0`` 的证据 (stub 不入轨迹 —— 否则本机的曲线是一条 95 直线,
      比没有曲线更骗人);
    * 只产出窗口内**有证据的天**; 空白天不补零 (客户端按日期连线), 窗口外丢弃。
    """
    buckets: dict[str, dict[str, list[float]]] = {}
    for created_at, dimension, score, weight in rows:
        if weight <= 0.0 or dimension not in DIMENSIONS:
            continue
        day = _as_utc(created_at).date().isoformat()
        buckets.setdefault(day, {}).setdefault(dimension, []).append(float(score))
    today = _utcnow().date()
    window = {(today - timedelta(days=offset)).isoformat() for offset in range(days)}
    points: list[TrajectoryPoint] = []
    for day in sorted(buckets):
        if day not in window:
            continue
        per_dim = buckets[day]
        averages: dict[str, Any] = dict(_blank_dims())
        averages |= {
            dim: round(sum(vals) / len(vals), _PRECISION) for dim, vals in per_dim.items() if vals
        }
        points.append(
            TrajectoryPoint(
                date=day,
                pronunciation=cast("float | None", averages["pronunciation"]),
                grammar=cast("float | None", averages["grammar"]),
                vocabulary=cast("float | None", averages["vocabulary"]),
                fluency=cast("float | None", averages["fluency"]),
                events=sum(len(vals) for vals in per_dim.values()),
            )
        )
    return points


__all__ = sorted(
    [
        "ALPHA",
        "CEFR_ORDER",
        "DIMENSIONS",
        "GATED_SOURCES",
        "ProfileSnapshot",
        "TrajectoryPoint",
        "ability_delta",
        "apply_evidence",
        "band_clamp",
        "bucket_events",
        "derived_level",
        "ewma_next",
        "get_profile",
        "get_snapshot",
        "level_from_avg",
        "profile_to_snapshot",
        "rebuild_dims",
        "record_step_evidence",
        "resolve_level",
    ]
)
