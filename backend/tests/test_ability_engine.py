"""能力画像管线测试 (§5.6, 阶段 P3) —— EWMA 金值 + 门控 + 画像重建 + 轨迹.

三类证据各钉一块:

1. **金值算术**: 固定事件序列 -> 手算的 EWMA 结果逐一对照 (种子化 / 单步 / 批内多步);
   浮点用 ``pytest.approx``, 落库精度 2 位小数。
2. **门控 (§四 决策表)**: ``stub``/``heuristic``/``skip`` 来源的事件 w=0 ——
   画像一格都不动、n 不加、连画像行都不该被创建; 流水仍全量记录 (审计 + 重建)。
   "本机永不动画像"这条在 ``test_mission.py`` 有端到端版, 这里钉单元层。
3. **重建不变量**: profiles 是 events 的可重建物化 —— 把落库后的流水用
   ``rebuild_dims`` 重放, 必须逐项还原 profile 的列值。

另含 CEFR 映射/锁带口径 (测评前 cefr 恒 None; band_locked 只允许 ±1 漂移) 和
``ability_delta`` 的 "None != 0" 语义 (§5.3)。异步落库用 ``db`` fixture 直连
conftest 的内存 sqlite (``Base.metadata.create_all`` 含全部表)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AbilityEvent, AbilityProfile, User
from app.services.ability_engine import (
    ALPHA,
    DIMENSIONS,
    ability_delta,
    apply_evidence,
    band_clamp,
    bucket_events,
    derived_level,
    ewma_next,
    get_profile,
    get_snapshot,
    level_from_avg,
    profile_to_snapshot,
    rebuild_dims,
    record_step_evidence,
    resolve_level,
)
from app.services.drill_grader import AbilityEvidence


def ev(dimension: str, score: float, *, source: str = "llm", weight: float = 1.0, **kw: object):
    return AbilityEvidence.model_validate(
        {"dimension": dimension, "score": score, "source": source, "weight": weight, **kw}
    )


# ============================================================ EWMA 金值


def test_ewma_seed_and_step_golden_values() -> None:
    # 首条证据: 种子化 (不从 0 爬)
    assert ewma_next(None, 62.5, dimension="pronunciation", weight=1.0) == 62.5
    # 80 + 0.25*(60-80) = 75.0 (发音 alpha=0.25)
    assert ewma_next(80.0, 60.0, dimension="pronunciation", weight=1.0) == 75.0
    # 语法 alpha=0.20: 90 + 0.2*(50-90) = 82.0
    assert ewma_next(90.0, 50.0, dimension="grammar", weight=1.0) == 82.0
    # 半权重: 步长减半 → 90 + 0.2*0.5*(50-90) = 86.0
    assert ewma_next(90.0, 50.0, dimension="vocabulary", weight=0.5) == 86.0
    # 权重 0: 数学上等于原地 (管线会在更外层直接跳过, 见 apply_evidence)
    assert ewma_next(77.7, 10.0, dimension="fluency", weight=0.0) == 77.7


def test_apply_evidence_gating_contract() -> None:
    for source in ("stub", "heuristic", "skip"):
        values, counts = {"grammar": 70.0}, {"grammar": 3}
        update = apply_evidence(values, counts, ev("grammar", 95.0, source=source))
        assert update.weighted is False and update.after == 70.0
        assert values == {"grammar": 70.0} and counts == {"grammar": 3}  # 一格不动
    values, counts = {"grammar": None}, {"grammar": 0}
    update = apply_evidence(values, counts, ev("grammar", 95.0, source="llm"))
    assert update.weighted is True and values == {"grammar": 95.0}  # 首样本种子化
    assert counts == {"grammar": 1}


def test_llm_weight_1_stub_weight_0_even_if_caller_lies_about_weight() -> None:
    """source 是一票否决: 谁也别拿 stub 事件传 weight=1 骗过门控."""
    values, counts = {"pronunciation": 60.0}, {"pronunciation": 2}
    apply_evidence(values, counts, ev("pronunciation", 95.0, source="stub", weight=1.0))
    assert values["pronunciation"] == 60.0 and counts["pronunciation"] == 2


def test_weights_are_clamped_into_unit_interval() -> None:
    """绕过 pydantic 的脏 weight (9.0) 也要被夹回 1.0 —— 防御纵深."""
    dirty = AbilityEvidence.model_construct(
        dimension="grammar", score=100.0, source="llm", weight=9.0, ise_ref_mode=None
    )
    values, counts = {"grammar": 50.0}, {"grammar": 1}
    apply_evidence(values, counts, dirty)
    # clamp 到 1.0: 50 + 0.2*(100-50) = 60
    assert values["grammar"] == pytest.approx(60.0)


# ============================================================ 落库管线


@pytest.mark.asyncio
async def test_record_writes_events_and_updates_profile(db: AsyncSession) -> None:
    user = User(device_id="dev-ability")
    db.add(user)
    await db.commit()
    batch = [
        ev("grammar", 66.0, source="llm"),
        ev("vocabulary", 70.0, source="llm"),
        ev("pronunciation", 95.0, source="stub", weight=0.0, ise_ref_mode="exact_reference"),
    ]
    written = await record_step_evidence(
        db, user_id=user.id, session_id="sess-1", step_id="f1", evidence=batch
    )
    await db.commit()
    assert written == 3
    rows = (
        (await db.execute(select(AbilityEvent).order_by(AbilityEvent.created_at))).scalars().all()
    )
    assert len(rows) == 3  # 全量流水 (含被门控的一条)
    stub_row = next(r for r in rows if r.dimension == "pronunciation")
    assert stub_row.weight == 0.0 and stub_row.ise_ref_mode == "exact_reference"
    assert stub_row.source_kind == "stub" and stub_row.session_id == "sess-1"
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.grammar == pytest.approx(66.0) and profile.grammar_n == 1
    assert profile.vocabulary == pytest.approx(70.0) and profile.vocabulary_n == 1
    assert profile.pronunciation is None and profile.pronunciation_n == 0  # stub 没种子化它


@pytest.mark.asyncio
async def test_gated_batch_alone_never_creates_a_profile_row(db: AsyncSession) -> None:
    user = User(device_id="dev-gated")
    db.add(user)
    await db.commit()
    n = await record_step_evidence(
        db,
        user_id=user.id,
        step_id="f2",
        evidence=[ev("pronunciation", 95.0, source="stub", weight=0.0)],
    )
    await db.commit()
    assert n == 1
    assert (await db.execute(select(AbilityEvent))).scalars().all()
    assert (await db.execute(select(AbilityProfile))).scalars().all() == []
    snap = await get_snapshot(db, user.id)
    assert snap.dims == dict.fromkeys(DIMENSIONS, None)  # 空画像视图 (全 null)
    assert snap.counts == dict.fromkeys(DIMENSIONS, 0)


@pytest.mark.asyncio
async def test_empty_evidence_is_pure_noop(db: AsyncSession) -> None:
    assert (await record_step_evidence(db, user_id="ghost", evidence=[])) == 0


@pytest.mark.asyncio
async def test_multiple_weighted_events_in_one_batch_apply_in_order(db: AsyncSession) -> None:
    user = User(device_id="dev-order")
    db.add(user)
    await db.commit()
    await record_step_evidence(
        db,
        user_id=user.id,
        evidence=[ev("grammar", 80.0), ev("grammar", 60.0)],  # 80 种子, 然后 80+0.2*(60-80)=76
    )
    await db.commit()
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.grammar == pytest.approx(76.0) and profile.grammar_n == 2


@pytest.mark.asyncio
async def test_rebuilt_profile_equals_recorded_one(db: AsyncSession) -> None:
    """§5.2 的"可重建"不变量: 重放流水 == 物化快照 (两批混合门控证据)."""
    user = User(device_id="dev-rebuild")
    db.add(user)
    await db.commit()
    await record_step_evidence(
        db,
        user_id=user.id,
        evidence=[
            ev("pronunciation", 90.0, source="xunfei", ise_ref_mode="exact_reference"),
            ev("grammar", 70.0),
            ev("fluency", 50.0, source="heuristic", weight=0.0),
        ],
    )
    await record_step_evidence(
        db,
        user_id=user.id,
        evidence=[ev("pronunciation", 60.0, source="xunfei"), ev("vocabulary", 80.0)],
    )
    await db.commit()
    rows = (
        await db.execute(
            select(AbilityEvent.dimension, AbilityEvent.score, AbilityEvent.weight).order_by(
                AbilityEvent.created_at.asc(), AbilityEvent.id.asc()
            )
        )
    ).all()
    rebuilt = rebuild_dims([(r[0], float(r[1]), float(r[2])) for r in rows])
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert rebuilt["pronunciation"] == pytest.approx(profile.pronunciation or 0.0)
    assert rebuilt["grammar"] == pytest.approx(profile.grammar or 0.0)
    assert rebuilt["vocabulary"] == pytest.approx(profile.vocabulary or 0.0)
    assert rebuilt["fluency"] == profile.fluency is None


# ============================================================ ability_delta


def test_ability_delta_none_semantics() -> None:
    before = {"pronunciation": None, "grammar": 60.0, "vocabulary": 80.0, "fluency": 50.0}
    after = {"pronunciation": 70.0, "grammar": 66.0, "vocabulary": 80.0, "fluency": 45.5}
    delta = ability_delta(before, after)
    assert delta["pronunciation"] is None  # 没有基线 != 拉动了 70
    assert delta["grammar"] == pytest.approx(6.0)
    assert delta["vocabulary"] == 0.0
    assert delta["fluency"] == pytest.approx(-4.5)
    assert ability_delta(None, after)["grammar"] is None  # 无基线 -> 拉动未知, 不冒充
    assert ability_delta(None, None) == dict.fromkeys(DIMENSIONS, None)
    flipped = ability_delta(after, before)
    assert flipped["grammar"] == pytest.approx(-6.0)


# ============================================================ CEFR 口径


def test_level_from_avg_bands() -> None:
    assert level_from_avg(10.0) == "A1"
    assert level_from_avg(39.9) == "A1"
    assert level_from_avg(40.0) == "A2"
    assert level_from_avg(55.0) == "B1"
    assert level_from_avg(70.0) == "B2"
    assert level_from_avg(85.0) == "C1"
    assert level_from_avg(95.0) == "C2"
    assert level_from_avg(100.0) == "C2"


def test_derived_level_ignores_missing_dims() -> None:
    assert derived_level(dict.fromkeys(DIMENSIONS, None)) is None
    assert (
        derived_level({"grammar": 60.0, "vocabulary": 60.0, "pronunciation": None, "fluency": None})
        == "B1"
    )
    assert (
        derived_level(
            {"grammar": 100.0, "vocabulary": 60.0, "fluency": 80.0, "pronunciation": 86.0}
        )
        == "B2"
    )


def test_band_clamp_and_resolve_level() -> None:
    assert band_clamp("C1", "A2") == "B1"  # 最多 +1 band
    assert band_clamp("A1", "C1") == "B2"  # 最多 -1 band
    assert band_clamp("B2", "B1") == "B2"  # 合法漂移保留
    assert band_clamp("weird", "B1") == "B1"  # 脏值回锚点
    assert band_clamp("C2", "nope") == "C2"  # 没锚不夹
    # 官方等级 = 测评结论; 测评前恒 None (null pre-assessment)
    assert resolve_level(assessment=None, derived="B1") is None
    assert resolve_level(assessment=None, derived=None) is None
    assert resolve_level(assessment="B1", derived="C2", band_locked=True) == "B2"  # 只许 +1 band
    assert resolve_level(assessment="B1", derived="A1", band_locked=True) == "A2"  # 只许 -1 band
    assert resolve_level(assessment="B1", derived=None, band_locked=True) == "B1"
    assert resolve_level(assessment="B1", derived="C2", band_locked=False) == "B1"


# ============================================================ 轨迹桶


def test_bucket_events_only_trusted_and_in_window() -> None:
    now = datetime.now(UTC)
    rows = [
        (now - timedelta(hours=3), "grammar", 60.0, 1.0),
        (now - timedelta(hours=4), "grammar", 80.0, 1.0),
        (now - timedelta(hours=5), "pronunciation", 95.0, 0.0),  # stub -> 不入轨迹
        (now - timedelta(days=1, hours=1), "vocabulary", 70.0, 1.0),
        (now - timedelta(days=40), "grammar", 50.0, 1.0),  # 90d 窗口内/7d 外
    ]
    points = bucket_events(rows, days=7)
    assert len(points) == 2
    today = next(p for p in points if p.date == now.date().isoformat())
    assert today.grammar == pytest.approx(70.0) and today.events == 2
    assert today.pronunciation is None and today.vocabulary is None
    wide = bucket_events(rows, days=90)
    assert len(wide) == 3 and wide[0].grammar == pytest.approx(50.0)


def test_bucket_events_handles_naive_datetimes() -> None:
    naive = datetime.now(UTC).replace(tzinfo=None)  # sqlite 取回的裸 UTC
    points = bucket_events([(naive, "fluency", 66.0, 1.0)], days=7)
    assert points and points[0].date == naive.date().isoformat()


# ============================================================ 快照投影


def test_profile_to_snapshot_none_row() -> None:
    snap = profile_to_snapshot(None)
    assert snap.dims == dict.fromkeys(DIMENSIONS, None)
    assert snap.cefr_level is None and snap.updated_at is None
    assert snap.snapshot() == dict.fromkeys(DIMENSIONS, None)


@pytest.mark.asyncio
async def test_snapshot_reflects_persisted_state(db: AsyncSession) -> None:
    user = User(device_id="dev-view")
    db.add(user)
    await db.commit()
    assert (await get_profile(db, user.id)) is None
    await record_step_evidence(db, user_id=user.id, evidence=[ev("grammar", 88.0)])
    await db.commit()
    snap = await get_snapshot(db, user.id)
    assert snap.dims["grammar"] == pytest.approx(88.0) and snap.counts["grammar"] == 1
    assert snap.cefr_level is None and snap.band_locked is False


# ============================================================ 常量契约


def test_alpha_table_and_dimension_order_are_stable() -> None:
    assert set(ALPHA) == set(DIMENSIONS)
    assert all(0.05 <= a <= 0.3 for a in ALPHA.values())  # sane 区间的护栏
    assert DIMENSIONS == ("pronunciation", "grammar", "vocabulary", "fluency")


@pytest.mark.asyncio
async def test_sequential_batches_replay_in_chronological_order(db: AsyncSession) -> None:
    """两次独立尝试 (批间隔 commit) 重放后 == 物化值 (created_at 微秒序, 金值可复现)."""
    user = User(device_id="dev-tie")
    db.add(user)
    await db.commit()
    for score in (80.0, 60.0):
        await record_step_evidence(db, user_id=user.id, evidence=[ev("grammar", score)])
        await db.commit()
    rows = (
        await db.execute(
            select(AbilityEvent.dimension, AbilityEvent.score, AbilityEvent.weight).order_by(
                AbilityEvent.created_at.asc()
            )
        )
    ).all()
    rebuilt = rebuild_dims([(r[0], float(r[1]), float(r[2])) for r in rows])
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert rebuilt["grammar"] == pytest.approx(profile.grammar)
    assert rebuilt["grammar"] == pytest.approx(76.0)
