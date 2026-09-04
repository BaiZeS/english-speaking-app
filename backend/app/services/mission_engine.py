"""实战对话 (mission) + 复盘报告 + 润色的 LLM 引擎 (计划 §5.5-2/§5.3 ReviewReport/§5.7).

三件事在这里收口, 端点层 (``api/v1/course_sessions`` / ``polish`` / ``dialogue``)
只做状态机与鉴权:

1. **每轮 1 次 LLM 调用** (§四 决策表 / §5.5-2): persona 回复 + 提示 (suggestion)
   + 语法润色 + 语法/词汇判分 + 任务清单**累积式**重判, 全在一个 JSON 里;
   沿用 ``drill_grader._judge`` 的容错解析 + 校验错误回喂重试 1 次模式, 第二次仍
   坏就退回**确定性降级** (``source="heuristic"``, ``llm_source="stub"``) ——
   移动端不等第三分钟。
2. **``transcript_anchored`` 发音证据的生产者** (§5.4/§5.6): 自由产出 (实战对话/
   自由对话) 没有标准答案, 发音维度拿 **IAT 转写当 ISE 参考文本** 打分。
   讯飞没配凭据时**直接不产出** —— StubASR 面对 "ref == 它自己吐的文本" 恒给 95,
   那是回声不是证据。
3. **ReviewReport** (§5.3): 聚合 practice_steps 与 doc 里的任务/润色/词汇命中,
   highlights/improvements 走 **1 次批量 LLM 调用** (§5.5-3 同一纪律), 失败给
   诚实的确定性文案 (按最低维度排序 ≤3 条)。

判分模型**恒为服务端默认** (``LLM_DEFAULT_MODEL``, 不开放客户端选): 任务判定与
语法/词汇分要进能力画像, 口径必须稳定 (T3 先例)。人设/润色这类纯文本调用可以
跟随客户端 ``model_id`` (§5.7 ``POST /polish``)。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.course import MissionTask, SceneCourse
from app.models.db import AnnotatedDiff
from app.models.schema import WordScore
from app.scoring.read_along import score_read_along
from app.services.ability_engine import DIMENSIONS, ability_delta
from app.services.audio_input import speech_rate_from_recognition
from app.services.drill_grader import (
    AbilityEvidence,
    Dimension,
    GradeSource,
    LlmUnavailableError,
    _judge,
    _matched_terms,
    _resolve_judge_model,
    _truncate,
)
from app.services.interfaces import ASRProvider
from app.services.llm_provider import LlmMessage
from app.services.xunfei_asr import XunfeiASRProvider

# ====== 常量 ======

#: 每轮综合 JSON 的 token 预算 (reply + suggestion + polish + 任务判定要得下):
#: 比 drill 判分 (400) 宽, 但仍远低于整课生成.
TURN_MAX_TOKENS = 700

#: 复盘文案批量调用的预算 (§5.5-3 一次喂全部转写).
REVIEW_MAX_TOKENS = 500

#: LLM 降级时任务启发式: 学员话术对 ``hint_en`` 示范句的内容词覆盖率门槛.
TASK_HEURISTIC_COVERAGE = 0.5


#: 自由产出可用的讯飞 ISE 凭据口径 (与 ``XunfeiASRProvider.recognize`` 的自检等价;
#: 这里提前判断, 没凭据就**不调用** —— 回声 95 分不进画像).
def xunfei_ise_configured() -> bool:
    """讯飞 ISE 是否真的配了凭据 (决定 transcript_anchored 是否产出)."""
    return bool(settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret)


#: 生产 ISE 单例: 测试 monkeypatch 这个模块属性 (同 drill_grader 风格).
_ISE: ASRProvider = XunfeiASRProvider()

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']*")


# ====== 1) 润色 / 任务 / 判分的返回契约 ======


class Polish(BaseModel):
    """「原句 vs 更好说法」对照 (§5.7 的载荷, mission/自由对话/独立润色共用)."""

    original: str = Field(min_length=1, max_length=500)
    polished: str = Field(min_length=1, max_length=500)
    explanation_cn: str = Field(default="", max_length=500)

    @field_validator("original", "polished", "explanation_cn")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class TaskProgress(BaseModel):
    """LLM 每轮对**全部**任务的累积重判结果 (§5.5-2: 防误标后无法回退)."""

    id: str = Field(min_length=1, max_length=32)
    done: bool = False
    evidence: str = Field(default="", max_length=300)


class MissionTurnJudgement(BaseModel):
    """实战对话单轮的综合 JSON (§5.5-2 的字段清单)."""

    reply: str = Field(min_length=1, max_length=800)
    suggestion: str = Field(default="", max_length=500)
    polish: Polish | None = None
    grammar_score: float | None = Field(default=None, ge=0, le=100)
    vocabulary_score: float | None = Field(default=None, ge=0, le=100)
    task_progress: list[TaskProgress] = Field(default_factory=list, max_length=8)

    @field_validator("reply", "suggestion")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("reply")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("reply must not be blank")
        return v


class ReviewTextJudgement(BaseModel):
    """复盘报告文案的批量判级 schema (1 次调用, §5.5-3 同纪律)."""

    highlights: list[str] = Field(default_factory=list, max_length=6)
    improvements: list[str] = Field(default_factory=list, max_length=6)


class PolishJudgement(BaseModel):
    """独立润色 (``POST /polish``) 的输出. 没有可改之处时 ``polished`` 留空."""

    polished: str = Field(default="", max_length=500)
    explanation_cn: str = Field(default="", max_length=500)


class MissionTaskView(BaseModel):
    """任务清单的 API 视图 (checklist 载荷)."""

    id: str
    desc_cn: str
    hint_en: str = ""
    required: bool = True
    done: bool = False
    evidence: str = ""
    done_at_turn: int | None = None


class TranscriptPair(BaseModel):
    """「原话 vs 更好说法」行 (§5.3 transcript_pairs)."""

    original: str
    polished: str
    explanation_cn: str = ""
    #: 来源: mission (轮次润色) | translate (打基础误译) | polish (独立润色).
    source: str = "mission"


class ReviewReport(BaseModel):
    """复盘报告 (§5.3 形状, 逐字段对应).

    * ``dims``: 4 维聚合分 (可空 = 本次没有证据), 口径是**本次会话所有 practice_steps
      行的算术平均** —— 这是给学员看的体验分, 与画像的 EWMA 口径不同;
    * ``pronunciation_subs``: ISE 子维度 (pronunciation/fluency/completeness) 均值,
      只统计带 ``ise_ref_mode`` 的行;
    * ``ability_delta``: 开局基线 vs 当前画像快照 (服务端写画像前后差, §5.3),
      维度 None = 没测过 —— 别渲染成 0;
    * ``source``: ``llm`` = 文案来自模型, ``heuristic`` = 确定性降级文案。
    """

    session_id: str
    scene_id: str
    title: str
    cleared: bool
    auto_finished: bool
    turn_count: int
    max_turns: int
    overall: float | None = None
    dims: dict[str, float | None] = Field(default_factory=dict)
    pronunciation_subs: dict[str, float | None] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    checklist: list[MissionTaskView] = Field(default_factory=list)
    transcript_pairs: list[TranscriptPair] = Field(default_factory=list)
    new_tokens: list[str] = Field(default_factory=list)
    ability_delta: dict[str, float | None] = Field(default_factory=dict)
    hints_used: int = 0
    source: GradeSource = "heuristic"
    llm_source: str | None = None


# ====== 2) 任务状态: 服务端累积合并 (done 粘滞) ======


def initial_task_states(tasks: Sequence[MissionTask]) -> list[dict[str, Any]]:
    """从课程清单初始化任务状态 (全 pending)."""
    return [
        {
            "id": task.id,
            "desc_cn": task.desc_cn,
            "hint_en": task.hint_en,
            "required": bool(task.required),
            "done": False,
            "evidence": "",
            "done_at_turn": None,
        }
        for task in tasks
    ]


def merge_task_progress(
    tasks_state: list[dict[str, Any]],
    progress: Sequence[TaskProgress],
    *,
    turn_index: int,
) -> list[dict[str, Any]]:
    """LLM 每轮重判全部任务 -> **累积合并**进服务端状态 (返回 newly_done 列表).

    口径 (§5.5-2):
    * ``done`` 粘滞: 一旦判成完成, 后续轮次即便 LLM 翻供也**不回退** —— 误标的代价
      由 evidence 透明展示来兜, 学员翻来覆去不认账的代价更大;
    * LLM 报上来的未知 id (幻觉出来的任务) 直接丢弃, 服务端状态是唯一权威;
    * evidence 记第一次成功的那句话, 供 checklist / 复盘页展示。
    """
    known = {str(entry.get("id")) for entry in tasks_state}
    newly: list[dict[str, Any]] = []
    by_id = {str(entry.get("id")): entry for entry in tasks_state}
    for item in progress:
        if item.id not in known or not item.done:
            continue
        entry = by_id[item.id]
        if entry["done"]:
            continue
        entry["done"] = True
        entry["evidence"] = _truncate(item.evidence, 300)
        entry["done_at_turn"] = turn_index
        newly.append({"id": item.id, "evidence": entry["evidence"]})
    return newly


def all_required_done(tasks_state: Sequence[Mapping[str, Any]]) -> bool:
    return bool(tasks_state) and all(
        bool(entry.get("done")) for entry in tasks_state if entry.get("required")
    )


def task_views(tasks_state: Sequence[Mapping[str, Any]]) -> list[MissionTaskView]:
    views: list[MissionTaskView] = []
    for entry in tasks_state:
        views.append(
            MissionTaskView(
                id=str(entry.get("id") or ""),
                desc_cn=str(entry.get("desc_cn") or ""),
                hint_en=str(entry.get("hint_en") or ""),
                required=bool(entry.get("required")),
                done=bool(entry.get("done")),
                evidence=str(entry.get("evidence") or ""),
                done_at_turn=(
                    int(cast(int, entry.get("done_at_turn")))
                    if entry.get("done_at_turn") is not None
                    else None
                ),
            )
        )
    return views


# ====== 3) 单轮综合 LLM 调用 ======

_TURN_SYSTEM_TMPL = (
    "你是英语口语陪练「{persona}」。场景: {context}。学员扮演「{user_role}」, "
    "中文母语、能读写但开口少 (CEFR {level})。你在推进一场**有任务清单**的实战对话。"
    "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。要求: "
    "(1) reply: 以 {persona} 身份用英文说下一句 (1-2 句, A2-B1 词汇, 必须带一个"
    "追问或新信息, 把剧情往**未完成的任务**推; 别让对话提前结束); "
    "(2) suggestion: 给学员下一句可直接开口的示范英文 (贴合未完成任务); "
    "(3) polish: 仅当学员**刚才这句英文**有语法/用词问题时给出 "
    "{{original, polished, explanation_cn}} (original 必须是学员原话, polished 是"
    "能直接重说的地道版本, explanation_cn 一句简体中文解释), 没有问题就输出 null; "
    "(4) grammar_score / vocabulary_score: 对学员刚才这句的语法与用词判 0-100 分, "
    "必须有区分度 (说得过去 60-79, 自然准确 80-100, 影响理解 <60; 若这句没有"
    "可判分的英文内容, 输出 null); "
    "(5) task_progress: **重判全部任务**至今是否已由学员达成 (累积口径: 之前说过"
    "的也算), 每项 {{id, done, evidence(一句中文/英文依据)}}, id 只能用清单里给定的。"
)

_JSON_SHAPE = (
    '只输出 JSON: {"reply": "...", "suggestion": "...", '
    '"polish": {"original": "...", "polished": "...", "explanation_cn": "..."} | null, '
    '"grammar_score": number|null, "vocabulary_score": number|null, '
    '"task_progress": [{"id": "...", "done": true|false, "evidence": "..."}]}'
)


def _tasks_block(tasks_state: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for entry in tasks_state:
        status = "已完成" if entry.get("done") else ("必做" if entry.get("required") else "可选")
        hint = f" | 示范: {entry.get('hint_en')}" if entry.get("hint_en") else ""
        lines.append(f"- [{entry.get('id')}] {entry.get('desc_cn')} ({status}){hint}")
    return "\n".join(lines)


def _transcript_block(turns: Sequence[Mapping[str, Any]], *, keep: int = 8) -> str:
    """最近 N 轮的对话文本 (persona 说话 + 学员转写), 给 LLM 当上下文."""
    lines: list[str] = []
    for turn in turns[-keep:]:
        lines.append(f"Coach: {turn.get('reply') or ''}")
        lines.append(f"Learner: {turn.get('user_text') or ''}")
    return "\n".join(lines)


def turn_prompt(
    course: SceneCourse,
    tasks_state: Sequence[Mapping[str, Any]],
    turns: Sequence[Mapping[str, Any]],
    user_text: str,
) -> list[LlmMessage]:
    """§5.5-2 的单轮 prompt: 人设 + 场景 + 任务清单状态 + 已发生的对话 + 本轮输入."""
    mission = course.mission
    system = _TURN_SYSTEM_TMPL.format(
        persona=_truncate(mission.persona_cn, 300),
        context=_truncate(mission.context_cn, 800),
        user_role=_truncate(mission.user_role_cn, 200),
        level=course.level,
    )
    user = (
        f"任务清单 (按学员说的话累积判定):\n{_tasks_block(tasks_state)}\n\n"
        f"已发生的对话 (Coach=你, Learner=学员):\n{_transcript_block(turns)}\n\n"
        f"学员本轮说 (英文转写):\n{user_text}\n\n"
        f"{_JSON_SHAPE}"
    )
    return [
        LlmMessage(role="system", content=system),
        LlmMessage(role="user", content=user),
    ]


def fallback_turn(
    course: SceneCourse,
    turn_index: int,
    user_text: str,
    tasks_state: Sequence[Mapping[str, Any]],
    failure: LlmUnavailableError,
) -> tuple[MissionTurnJudgement, GradeSource, str]:
    """LLM 不可用时的**确定性降级** (honest: source=heuristic, llm_source=stub).

    * reply/suggestion: 走参考剧本的下一行 (A 说 / B 示范) —— 剧本就是 T2 人工
      校对的"应该怎么说", 拿来撑住对话不冷场, 不冒充生成;
    * 任务判定: 学员话术对未完成``required``任务 ``hint_en`` 示范句的内容词覆盖率
      >= :data:`TASK_HEURISTIC_COVERAGE` 才算完成 (词面口径, 宁缺勿滥);
    * grammar/vocabulary: 不给分 —— 词面覆盖率当"语法分"是假证据, 宁缺勿滥。
      本轮于是没有语法/词汇事件, 画像自然不动 (要出假分数才是污染)。
    """
    logger.warning("mission turn degraded to heuristic | reason={}", failure)
    lines = course.mission.exchanges
    script = lines[(turn_index - 1) % len(lines)]
    progress: list[TaskProgress] = []
    for entry in tasks_state:
        if entry.get("done"):
            continue
        hint_en = str(entry.get("hint_en") or "")
        if not hint_en:
            continue
        coverage, _ = _matched_terms(user_text, hint_en)
        if coverage >= TASK_HEURISTIC_COVERAGE:
            progress.append(
                TaskProgress(
                    id=str(entry["id"]),
                    done=True,
                    evidence="词面覆盖了任务示范用语 (启发式判定, 未经语义核对)",
                )
            )
    judgement = MissionTurnJudgement(
        reply=script.a,
        suggestion=script.b,
        polish=None,
        grammar_score=None,
        vocabulary_score=None,
        task_progress=progress,
    )
    return judgement, "heuristic", "stub"


async def judge_turn(
    course: SceneCourse,
    tasks_state: list[dict[str, Any]],
    turns: Sequence[Mapping[str, Any]],
    user_text: str,
    turn_index: int,
) -> tuple[MissionTurnJudgement, GradeSource, str | None]:
    """实战单轮的综合 LLM 调用 (1 次; 坏 JSON 回喂重试 1 次; 再坏走降级).

    返回 ``(judgement, source, llm_source)``; 判分模型 = 服务端默认
    (:func:`app.services.drill_grader._resolve_judge_model`), 不吃客户端 ``model_id``。
    """
    try:
        judgement = await _judge(
            MissionTurnJudgement,
            turn_prompt(course, tasks_state, turns, user_text),
            max_tokens=TURN_MAX_TOKENS,
        )
    except LlmUnavailableError as exc:
        return fallback_turn(course, turn_index, user_text, tasks_state, exc)
    return judgement, "llm", _resolve_judge_model()


# ====== 4) transcript_anchored 发音证据 (生产者, §5.6) ======


@dataclass(frozen=True)
class AnchoredPronunciation:
    """自由产出的转写锚定 ISE 结果 (ref == IAT 转写)."""

    pronunciation: float
    fluency: float
    completeness: float
    speech_rate_wpm: float
    word_details: list[WordScore]


async def anchored_pronunciation(
    audio_bytes: bytes,
    transcript: str,
    *,
    asr: ASRProvider | None = None,
) -> AnchoredPronunciation | None:
    """自由产出 (实战/自由对话) 的发音证据: ISE 以 **转写为参考文本** 打分.

    纪律 (§5.6 + T3 landmine):
    * 没配讯飞凭据 -> 直接 None (StubASR 拿自己吐的文本当 ref 恒 95, 是回声);
    * 配了但结果 ``source != "xunfei"`` (调用失败回退) -> None + WARNING:
      **宁可发音维度空缺, 不造假的发音证据**。
    流利度用 :func:`app.scoring.read_along.score_read_along` 的现成综合
    (ISE fluency + speech_rate_wpm), 与 drill 同一口径。
    """
    if not audio_bytes or not transcript.strip():
        return None
    if not xunfei_ise_configured():
        return None
    provider = asr or _ISE
    result = await provider.recognize(audio_bytes, transcript, category="read_sentence")
    if result.source != "xunfei":
        logger.warning("anchored ISE fell back to stub; dropping pronunciation evidence")
        return None
    wpm = speech_rate_from_recognition(result.recognized, audio_bytes)
    scored = score_read_along(ref_text=transcript, asr=result, speech_rate_wpm=wpm, pause_count=0)
    return AnchoredPronunciation(
        pronunciation=scored.pronunciation,
        fluency=scored.fluency,
        completeness=scored.completeness,
        speech_rate_wpm=round(wpm, 1),
        word_details=list(scored.word_details),
    )


def turn_ability_events(
    judgement: MissionTurnJudgement,
    anchored: AnchoredPronunciation | None,
    *,
    score_source: GradeSource,
) -> list[AbilityEvidence]:
    """一轮的维度证据 (§5.6): 语法/词汇 ← LLM 判分; 发音/流利 ← 锚定 ISE.

    启发式降级的判分 (若有) 也在 ``score_source="heuristic"`` 下被门控 (w=0)。
    """
    events: list[AbilityEvidence] = []
    stubbed = score_source in ("stub", "heuristic")
    for dimension, value in (
        ("grammar", judgement.grammar_score),
        ("vocabulary", judgement.vocabulary_score),
    ):
        if value is None:
            continue
        events.append(
            AbilityEvidence(
                dimension=cast(Dimension, dimension),
                score=value,
                source=score_source,
                weight=0.0 if stubbed else 1.0,
            )
        )
    if anchored is not None:
        events.append(
            AbilityEvidence(
                dimension="pronunciation",
                score=anchored.pronunciation,
                source="xunfei",
                weight=1.0,
                ise_ref_mode="transcript_anchored",
            )
        )
        events.append(
            AbilityEvidence(
                dimension="fluency",
                score=anchored.fluency,
                source="xunfei",
                weight=1.0,
            )
        )
    return events


# ====== 5) 独立润色 / 对话轮润色 ======

_POLISH_SYSTEM = (
    "你是英语写作润色器, 学员是中文母语的英语初学者 (A2-B1)。"
    "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。"
    "任务: 把学员的英文句子改得**语法正确且可以自然开口说出** (保持原意, 不换话题, "
    "不扩写)。explanation_cn 用一句简体中文指出关键修改 (时态/搭配/冠词/礼貌语气等), "
    "不要罗列所有改动。若句子本来就没有值得改的语法或用词问题, polished 输出空字符串。"
    '只输出 JSON: {"polished": "...", "explanation_cn": "..."}'
)


def polish_prompt(text: str) -> list[LlmMessage]:
    return [
        LlmMessage(role="system", content=_POLISH_SYSTEM),
        LlmMessage(role="user", content=f"学员原句: {text}"),
    ]


async def polish_text(
    text: str, *, model: str | None = None
) -> tuple[Polish | None, GradeSource, str | None]:
    """独立润色 (§5.7 ``POST /polish``): 1 次调用 + 重试 1 次 + 诚实缺席.

    LLM 不可用时**返回 ``None`` 而不是占位句** —— 润色没有"确定性降级"可言
    (规则改写句子容易改错意思), 让 UI 显示"暂不可用"即可。
    ``model`` 是**文本用途**的模型 (客户端可指定); 默认走服务端模型。
    """
    try:
        judgement = await _judge(
            PolishJudgement,
            polish_prompt(text),
            max_tokens=300,
            model=model,
        )
    except LlmUnavailableError as exc:
        logger.warning("polish unavailable | reason={}", exc)
        return None, ("stub" if exc.not_configured else "heuristic"), "stub"
    llm_used = model or _resolve_judge_model()
    polished = judgement.polished.strip()
    if not polished or polished.lower() == text.strip().lower():
        # 模型认为没有可改之处: 诚实返回 null (不是失败).
        return None, "llm", llm_used
    return (
        Polish(
            original=text.strip()[:500],
            polished=polished[:500],
            explanation_cn=_truncate(judgement.explanation_cn, 500),
        ),
        "llm",
        llm_used,
    )


def coerce_score(raw: Any) -> float | None:
    """宽容解析 LLM 回的 0-100 分: 非数/越界 -> ``None`` (没有证据, 不是 0)."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0 or value > 100:
        return None
    return round(value, 1)


def coerce_polish(raw: Any) -> Polish | None:
    """从 (可能不合规的) LLM JSON 里挖出 polish 对照; 缺件/空件 -> None."""
    if not isinstance(raw, Mapping):
        return None
    original = str(raw.get("original") or "").strip()
    polished = str(raw.get("polished") or "").strip()
    if not polished:
        return None
    # 各字段先截到 max_length 再构造: 宽容路径不再可能因长度炸掉
    return Polish(
        original=(original or polished)[:500],
        polished=polished[:500],
        explanation_cn=str(raw.get("explanation_cn") or "").strip()[:500],
    )


def record_annotated_diff(
    db: AsyncSession,
    user_id: str,
    *,
    polish: Polish,
    origin: str,
    session_id: str = "",
    step_id: str = "",
    scene_id: str = "",
    llm_source: str | None = None,
) -> AnnotatedDiff:
    """每次真产出过润色对照, ``annotated_diffs`` 记一行跨会话流水 (§5.2 M2 表).

    只 ``db.add`` 不 flush/commit —— 与调用方的会话快照同一事务 (同 §5.6 纪律)。
    实战轮 / 自由对话轮 / 独立 ``/polish`` 收藏之外的**原始对照记录**都从这进。
    """
    row = AnnotatedDiff(
        user_id=user_id,
        original=polish.original,
        polished=polish.polished,
        explanation_cn=polish.explanation_cn,
        origin=origin,
        session_id=session_id,
        step_id=step_id,
        scene_id=scene_id,
        llm_source=llm_source,
    )
    db.add(row)
    return row


# ====== 6) ReviewReport ======

_REVIEW_SYSTEM = (
    "你是英语口语教练, 正在给学员写**课后复盘**。学员: 中文母语的企业管理者。"
    '只输出一个 JSON 对象: {"highlights": ["中文亮点句..."], '
    '"improvements": ["中文改进建议(每条先说问题再说怎么改)..."]}。'
    "highlights 1-3 条, 必须基于材料里真实做到的事, 引用学员原话时保留英文; "
    "improvements 最多 3 条, 按最影响沟通的短板排序; 不写空话 (「继续加油」这种)。"
    "分数低的维度优先提。"
)


def review_prompt(course: SceneCourse, facts: Mapping[str, Any]) -> list[LlmMessage]:
    lines = [
        f"课程: {course.title} (目标: {course.goal_text or course.subtitle_en})",
        f"实战任务: {facts.get('done_count')}/{facts.get('task_count')} 完成"
        f"{' (已通关)' if facts.get('cleared') else ' (未通关)'}",
        f"维度分: {_fmt_dims(facts.get('dims', {}))}",
        "学员在实战对话里说过的话:",
    ]
    for utterance in cast("list[str]", facts.get("utterances", []))[:12]:
        lines.append(f"- {utterance}")
    return [
        LlmMessage(role="system", content=_REVIEW_SYSTEM),
        LlmMessage(role="user", content="\n".join(lines)),
    ]


def _fmt_dims(dims: Mapping[str, Any]) -> str:
    parts = []
    for dim in DIMENSIONS:
        value = dims.get(dim)
        parts.append(f"{dim}={'无证据' if value is None else value}")
    return ", ".join(parts)


def deterministic_review(
    facts: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    """无 LLM 时的诚实文案 (全部从真实数据拼, 不吹牛不编造)."""
    dims = cast("Mapping[str, Any]", facts.get("dims", {}))
    highlights: list[str] = []
    if facts.get("cleared"):
        highlights.append("实战任务全部达成 —— 沟通目的完成了, 这是最重要的。")
    elif facts.get("done_count"):
        highlights.append(f"实战里做成了 {facts['done_count']} 项沟通任务; 开口的每一轮都是进步。")
    if facts.get("briefing_passed"):
        highlights.append("打基础清单全部走完。")
    scored = {dim: float(value) for dim, value in dims.items() if isinstance(value, (int, float))}
    if len(scored) >= 2 and min(scored.values()) >= 60:
        best = max(scored, key=lambda d: scored[d])
        highlights.append(f"{_cn_dim(best)}是当前最稳的一项 ({scored[best]:.0f} 分)。")
    if not highlights:
        highlights.append("今天把整场对话开口的流程走完了 —— 先把习惯建立起来。")

    improvements: list[str] = []
    templates = {
        "pronunciation": "发音: 挑本课跟读句, 每天慢速 3 遍再常速 3 遍, 重点听词尾辅音。",
        "fluency": "流利度: 回答前允许 2 秒停顿, 但停顿里先把主语说出来 (I / We...), 别整句重想。",
        "grammar": "语法: 把润色对照卡里的「原句 -> 更好说法」朗读各 2 遍, 下次开口直接复用。",
        "vocabulary": "词汇: 本课核心词先造 3 个自己用得上的句子, 再进实战复用。",
    }
    for dim, value in sorted(scored.items(), key=lambda item: item[1]):
        if value < 60 and len(improvements) < 3:
            improvements.append(templates.get(dim, f"{_cn_dim(dim)}偏低, 针对本课内容加练。"))
    missing = [dim for dim in dims if dim not in scored]
    if len(improvements) < 3 and missing:
        improvements.append(
            f"{', '.join(_cn_dim(str(dim)) for dim in missing[:2])}本次没有可信证据 "
            "(外部评测未配置), 分数不刷新, 配好讯飞/LLM 后自然会有。"
        )
    if len(improvements) < 3 and not facts.get("cleared") and facts.get("open_required"):
        improvements.append(
            "还差必做沟通任务: 下一场先开口把 "
            + "、".join(cast("list[str]", facts.get("open_required", []))[:2])
            + " 说成英文。"
        )
    return highlights[:3], improvements[:3]


_CN_DIMS = {
    "pronunciation": "发音",
    "grammar": "语法",
    "vocabulary": "词汇",
    "fluency": "流利度",
}


def _cn_dim(dim: str) -> str:
    return _CN_DIMS.get(dim, dim)


def mean_of(values: Sequence[float | None]) -> float | None:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 1) if nums else None


#: "可信来源"家族: 真实评测 (ISE) 或真实 LLM 判分. ``stub``/``heuristic`` 的行
#: 只进流水与步骤明细 (带警示), **不进复盘报告的四维聚合** —— 报告维度与画像用
#: 同一道门, 否则本机 (讯飞没 key) 会出现 "发音 95" 的假报告。
TRUSTED_SOURCES = frozenset({"xunfei", "llm"})


def _trusted(steps: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [step for step in steps if str(step.get("source") or "") in TRUSTED_SOURCES]


def aggregate_step_dims(steps: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """维度聚合 = **可信来源行**的各维度非 NULL 分数算术平均.

    与画像同一道门 (§5.6): stub/heuristic 行留在 ``practice_steps`` 与 doc 里
    (步骤明细照常按行内 ``source`` 打"非真实评测"警示), 但**不掺进报告维度** ——
    报告说"发音 95"而它是 StubASR 恒 95, 比只字不提更有害。
    """
    columns = {
        "pronunciation": "score_pronunciation",
        "grammar": "score_grammar",
        "vocabulary": "score_vocabulary",
        "fluency": "score_fluency",
    }
    trusted = _trusted(steps)
    return {
        dim: mean_of([cast("float | None", step.get(column)) for step in trusted])
        for dim, column in columns.items()
    }


def aggregate_pronunciation_subs(steps: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """ISE 子维度均值 (pronunciation/fluency/completeness), 只看带 ``ise_ref_mode`` 的行."""
    ise_rows = [step for step in _trusted(steps) if step.get("ise_ref_mode")]
    return {
        "pronunciation": mean_of([_num(step.get("score_pronunciation")) for step in ise_rows]),
        "fluency": mean_of([_num(step.get("score_fluency")) for step in ise_rows]),
        "completeness": mean_of([_num(step.get("score_completeness")) for step in ise_rows]),
    }


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def collect_transcript_pairs(
    doc: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
) -> list[TranscriptPair]:
    """原话 vs 更好说法 (从存储的标注来: mission 轮润色 + translate 题误译)."""
    pairs: list[TranscriptPair] = []
    for turn in cast("list[dict[str, Any]]", (doc.get("mission") or {}).get("turns") or []):
        polish = turn.get("polish")
        if isinstance(polish, dict) and polish.get("polished"):
            pairs.append(
                TranscriptPair(
                    original=str(polish.get("original") or ""),
                    polished=str(polish.get("polished") or ""),
                    explanation_cn=str(polish.get("explanation_cn") or ""),
                    source="mission",
                )
            )
    for step in steps:
        annotated = step.get("annotated_json")
        if not isinstance(annotated, dict):
            continue
        for mistake in annotated.get("mistakes") or []:
            if not isinstance(mistake, dict):
                continue
            said = str(mistake.get("said") or "").strip()
            better = str(mistake.get("better") or "").strip()
            if better:
                pairs.append(
                    TranscriptPair(
                        original=said or str(mistake.get("source_cn") or ""),
                        polished=better,
                        explanation_cn=str(mistake.get("explanation_cn") or ""),
                        source=str(step.get("step_type") or "translate"),
                    )
                )
    return pairs[:12]


def collect_new_tokens(course: SceneCourse, utterances: Sequence[str]) -> list[str]:
    """本课核心词汇里**学员真的说过**的词 (词汇表 x 转写语料)."""
    spoken: set[str] = set()
    for text in utterances:
        for match in _TOKEN_RE.finditer(text or ""):
            spoken.add(match.group(0).lower())
    hits: list[str] = []
    for item in course.vocab:
        word = item.word.strip().lower()  # VocabItem 保证非空 (min_length + strip)
        stem = word.rstrip("s")
        if word in spoken or stem in spoken:
            hits.append(item.word)
    return hits[:12]


async def build_review_report(
    *,
    course: SceneCourse,
    session_id: str,
    mission: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    ability_before: Mapping[str, float | None] | None,
    ability_after: Mapping[str, float | None] | None,
    briefing_passed: bool,
    hints_used: int = 0,
) -> ReviewReport:
    """汇总一份复盘报告 (§5.3); 文案走**一次**批量 LLM 调用, 失败诚实降级."""
    dims = aggregate_step_dims(steps)
    subs = aggregate_pronunciation_subs(steps)
    checklist = task_views(cast("list[dict[str, Any]]", mission.get("tasks") or []))
    cleared = bool(mission.get("cleared"))
    utterances = [
        str(turn.get("user_text"))
        for turn in cast("list[dict[str, Any]]", mission.get("turns") or [])
        if turn.get("user_text")
    ]
    # 打基础各题的转写/文本作答也算"本次真的用过的词" (new_tokens 的语料).
    utterances += [str(step.get("transcript") or "") for step in steps]
    facts: dict[str, Any] = {
        "dims": dims,
        "cleared": cleared,
        "done_count": sum(1 for view in checklist if view.done),
        "task_count": len(checklist),
        "utterances": utterances,
        "briefing_passed": bool(briefing_passed),
        "open_required": [view.desc_cn for view in checklist if view.required and not view.done],
    }
    delta = ability_delta(
        dict(ability_before) if ability_before else None,
        dict(ability_after) if ability_after else None,
    )
    source: GradeSource
    llm_source: str | None
    try:
        judgement = await _judge(
            ReviewTextJudgement,
            review_prompt(course, _review_facts(facts)),
            max_tokens=REVIEW_MAX_TOKENS,
        )
        highlights = [_truncate(item, 300) for item in judgement.highlights if item.strip()][:3]
        improvements = [_truncate(item, 300) for item in judgement.improvements if item.strip()][:3]
        if not highlights and not improvements:
            raise LlmUnavailableError("复盘文案为空")
        source, llm_source = "llm", _resolve_judge_model()
    except LlmUnavailableError as exc:
        # _judge 自身已消化解析/校验错误; 这里同时兜 "合法 JSON 但两套文案全空".
        fallback_high, fallback_improve = deterministic_review(facts)
        highlights, improvements = fallback_high, fallback_improve
        source, llm_source = "heuristic", "stub"
        logger.warning("review copy degraded to deterministic | reason={}", exc)
    overall = mean_of(list(dims.values()))
    return ReviewReport(
        session_id=session_id,
        scene_id=course.id,
        title=course.title,
        cleared=cleared,
        auto_finished=bool(mission.get("auto_finished")),
        turn_count=int(mission.get("turn_count") or 0),
        max_turns=int(mission.get("max_turns") or course.mission.max_turns),
        overall=overall,
        dims=dims,
        pronunciation_subs=subs,
        highlights=highlights,
        improvements=improvements,
        checklist=checklist,
        transcript_pairs=collect_transcript_pairs({"mission": dict(mission)}, steps),
        new_tokens=collect_new_tokens(course, utterances),
        ability_delta=delta,
        hints_used=hints_used,
        source=source,
        llm_source=llm_source,
    )


def _review_facts(facts: Mapping[str, Any]) -> Mapping[str, Any]:
    """喂给 LLM 前收敛一下列表 (prompt 大小可控)."""
    clipped = dict(facts)
    clipped["utterances"] = [
        _truncate(str(item), 200) for item in cast("list[str]", facts.get("utterances") or [])[:12]
    ]
    return clipped


__all__ = sorted(
    [
        "AnnotatedPronunciation",
        "MissionTaskView",
        "MissionTurnJudgement",
        "Polish",
        "REVIEW_MAX_TOKENS",
        "ReviewReport",
        "TASK_HEURISTIC_COVERAGE",
        "TURN_MAX_TOKENS",
        "TranscriptPair",
        "aggregate_pronunciation_subs",
        "aggregate_step_dims",
        "all_required_done",
        "anchored_pronunciation",
        "build_review_report",
        "coerce_polish",
        "coerce_score",
        "collect_new_tokens",
        "collect_transcript_pairs",
        "deterministic_review",
        "fallback_turn",
        "initial_task_states",
        "judge_turn",
        "merge_task_progress",
        "polish_prompt",
        "polish_text",
        "task_views",
        "turn_ability_events",
        "turn_prompt",
        "xunfei_ise_configured",
    ]
)
