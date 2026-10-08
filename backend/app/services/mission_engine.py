"""实战对话 (mission) + 复盘报告 + 润色的 LLM 引擎 (计划 §5.5-2/§5.3 ReviewReport/§5.7).

三件事在这里收口, 端点层 (``api/v1/course_sessions`` / ``polish`` / ``dialogue``)
只做状态机与鉴权:

1. **实战轮一分为二** (§A1/D1: 台词独占预算、判分移出请求): 请求里只剩
   :func:`generate_turn` 这一次调用 —— 台词 ``reply`` + 双语 (``reply_cn``/
   ``suggestion``/``suggestion_cn``/``learner_cn``); 润色 + 语法/词汇分 + 任务累积
   重判 (:func:`judge_turn`) 改由后台作业在请求之外补 (p50 6.6s, 挤进请求必撞墙)。
   两个函数都过 :func:`app.services.drill_grader._judge` 的**唯一**收口 (一次调用 +
   坏 JSON 回喂一次 + ``LlmUnavailableError``), 各自报自己的预算与 schema 形状。
   台词**没有**确定性降级可言: 拿不到就抛 :class:`LlmUnavailableError`, 端点回 503
   且这一轮不落库、不前进 (D5) —— 剧本回放正是"每轮同一句"的根因 (§0)。
2. **``transcript_anchored`` 发音证据的生产者** (§5.4/§5.6): 自由产出 (实战对话/
   自由对话) 没有标准答案, 发音维度拿 **IAT 转写当 ISE 参考文本** 打分。
   讯飞没配凭据时**直接不产出** —— StubASR 面对 "ref == 它自己吐的文本" 恒给 95,
   那是回声不是证据。
3. **ReviewReport** (§5.3): 聚合 practice_steps 与 doc 里的任务/润色/词汇命中。
   §P6 起这个模块把报告**劈成两半**: :func:`build_review_skeleton` 是纯算术的数值骨架
   (同步、无网络, 收工请求当场就能给完), :func:`review_copy` 只做那四个来自模型的文案
   字段 (1 次批量调用, §5.5-3 同一纪律), 再由 :func:`merge_review_copy` 并回骨架 ——
   端点在 202 之后用后台作业慢慢补文案。任何一侧不可用都是**诚实的确定性文案**
   (按最低维度排序 ≤3 条), 不是空白。

判分模型**恒为服务端默认** (``LLM_DEFAULT_MODEL``, 不开放客户端选): 任务判定与
语法/词汇分要进能力画像, 口径必须稳定 (T3 先例)。人设/润色这类纯文本调用可以
跟随客户端 ``model_id`` (§5.7 ``POST /polish``)。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple, cast

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
    GEN_LLM_TIMEOUT_S,
    GEN_TURN_BUDGET_S,
    POLISH_BUDGET_S,
    REVIEW_LLM_BUDGET_S,
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
from app.services.llm_provider import LlmMessage, no_thinking_body, resolve_roleplay_model
from app.services.xunfei_asr import XunfeiASRProvider

# ====== 常量 ======

#: **台词生成** (实战轮 / 自由对话轮请求内**唯一**的那次 LLM) 的输出预算与温度.
#: 旧形状把台词 + 润色 + 两个分 + 任务重判塞进一个 JSON (``TURN_MAX_TOKENS=700``),
#: 实测吐 ~1000 字 / p50 22.5s —— 生产 8 轮 7 轮撞 15s 墙 (§0 根因一). 拆开后 160 就够.
GEN_MAX_TOKENS = 160
#: 台词的温度必须**显式**给: 旧 ``judge_turn`` 不传它, 于是落进 :func:`_judge` 的判分
#: 默认 0.2 —— 用判分温度写台词是"AI 反复问同一类问题"的第二个成因 (§0 第二条缺陷).
GEN_TEMPERATURE = 0.7

#: **判分** (后台作业专用: 润色 + 语法/词汇 + 任务判定) 的输出预算.
#: 只判分不吐台词, 所以比旧合并形状 (700) 小、比纯 drill 判分 (400) 略宽.
GRADE_MAX_TOKENS = 450

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
    #: 润色句的简体中文意思 (D4 双语, 与 ``a_cn``/``b_cn`` 同一口径 500).
    polished_cn: str = Field(default="", max_length=500)

    @field_validator("original", "polished", "explanation_cn", "polished_cn")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class TaskProgress(BaseModel):
    """LLM 每轮对**全部**任务的累积重判结果 (§5.5-2: 防误标后无法回退)."""

    id: str = Field(min_length=1, max_length=32)
    done: bool = False
    evidence: str = Field(default="", max_length=300)


class TurnGeneration(BaseModel):
    """请求内唯一一次 LLM 的产物: 台词 + 双语 + 学员那句的中文对照 (§A1/D4).

    与 :class:`MissionTurnJudgement` (判分侧) 是**两份** schema, 形状不共用 ——
    一次调用既写台词又判分就是撞墙的那个旧形状 (§0)。所有字段可缺省且上限照仓内
    既有 ``a_cn``/``b_cn``/``hint_cn`` 的中文口径 (500), 不自造一套; 空串表示
    "这一行不渲染" (D5: 绝不机翻占位)。
    """

    reply: str = Field(default="", max_length=500)
    reply_cn: str = Field(default="", max_length=500)
    suggestion: str = Field(default="", max_length=500)
    suggestion_cn: str = Field(default="", max_length=500)
    learner_cn: str = Field(default="", max_length=500)

    @field_validator("reply", "reply_cn", "suggestion", "suggestion_cn", "learner_cn")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class MissionTurnJudgement(BaseModel):
    """实战对话单轮的**判分**结果 (§5.5-2 的判分部分; 后台作业专用).

    ``reply``/``suggestion`` 只作**兼容读**保留 (老形状 JSON / 老快照里有它们):
    判分调用不再产出台词 (那是 :class:`TurnGeneration` 的活), 所以它们可缺省。
    """

    reply: str = Field(default="", max_length=800)
    suggestion: str = Field(default="", max_length=500)
    polish: Polish | None = None
    grammar_score: float | None = Field(default=None, ge=0, le=100)
    vocabulary_score: float | None = Field(default=None, ge=0, le=100)
    task_progress: list[TaskProgress] = Field(default_factory=list, max_length=8)

    @field_validator("reply", "suggestion")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ReviewTextJudgement(BaseModel):
    """复盘报告文案的批量判级 schema (1 次调用, §5.5-3 同纪律)."""

    highlights: list[str] = Field(default_factory=list, max_length=6)
    improvements: list[str] = Field(default_factory=list, max_length=6)


class PolishJudgement(BaseModel):
    """独立润色 (``POST /polish``) 的输出. 没有可改之处时 ``polished`` 留空."""

    polished: str = Field(default="", max_length=500)
    explanation_cn: str = Field(default="", max_length=500)
    #: 润色句的中文意思 (D4 双语; 缺省空串 = 客户端不渲染那一行).
    polished_cn: str = Field(default="", max_length=500)


class MissionTaskView(BaseModel):
    """任务清单的 API 视图 (checklist 载荷)."""

    id: str
    desc_cn: str
    hint_en: str = ""
    #: 中文提示/要点说明 (库内已有, 与 ``MissionTask.hint_cn`` 同一口径, 上限 300).
    hint_cn: str = Field(default="", max_length=300)
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
    * ``source``: ``llm`` = 文案来自模型, ``heuristic`` = 确定性降级文案。§P6 之后收工
      响应里拿到的那份**总是** ``heuristic`` (数值骨架), 后台文案作业补完才翻 ``llm``;
      判断"文案到底补没补"要看 ``doc["review_status"]``, 不要拿 ``source`` 当依据 ——
      作业正常跑完但 LLM 挂掉时, ``ready`` + ``heuristic`` 就是最终的诚实答案。
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
    #: 无可信评分证据时的**诚实标注** ("" = 有证据). ``overall is None`` 时客户端若只
    #: 渲染破折号, 学员会以为自己考了 0 分 —— 实际是这场**没有可信证据可打分**
    #: (讯飞/LLM 没配或全部降级), 那句话得由服务端说清楚, 不要让 UI 猜 (§2.6 次因)。
    evidence_note_cn: str = ""
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
            "hint_cn": task.hint_cn,
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
                # 库内值可能比视图上限长 (存量语料): 先截到 300 再进视图, 否则
                # pydantic 校验直接把 checklist / 提示卡变成 500 (T2 质量审查记的 Minor)。
                hint_cn=_truncate(str(entry.get("hint_cn") or ""), 300),
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


# ====== 3) 单轮 LLM 调用: 生成侧 (请求内) 与判分侧 (后台作业) 两份形状 ======

#: 判分侧的 system: 只判分, 不写台词 (§A1 的收缩)。
_JUDGE_RULES = (
    "你是英语口语陪练的判分器。只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。要求: "
    "(1) polish: 仅当学员**这句英文**有语法/用词问题时给出 "
    "{{original(必须是学员原话), polished(能直接重说的地道版本), "
    "polished_cn(polished 的简体中文意思), explanation_cn(一句简体中文解释)}}, "
    "没有问题就输出 null; "
    "(2) grammar_score / vocabulary_score: 对学员这句的语法与用词判 0-100 分, 必须有区分度 "
    "(说得过去 60-79, 自然准确 80-100, 影响理解 <60; 若这句没有可判分的英文内容, "
    "输出 null); "
    "(3) task_progress: **重判全部任务**至今是否已由学员达成 (累积口径: 之前说过的也算), "
    "每项 {{id, done, evidence(一句中文/英文依据)}}, id 只能用清单里给定的。"
)

#: 生成侧 JSON 形状 (TurnGeneration 五字段)。**公开**: 自由对话那条路由自己拼 prompt
#: (``dialogue._scene_messages``), 但它必须引这一份 —— 两边各写一段形状就是漂移的开始。
GENERATION_JSON_SHAPE = (
    '只输出 JSON: {"reply": "...", "reply_cn": "...", "suggestion": "...", '
    '"suggestion_cn": "...", "learner_cn": "..."}'
)

#: 生成侧的行为要求 (五件事), 同样公开给自由对话复用。
GENERATION_RULES = (
    "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。要求: "
    "(1) reply: 用英文说下一句 (1-2 句, A2-B1 词汇), 必须带一个追问或新信息, "
    "把对话往**没聊过的方向**推, 别提前结束; "
    "(2) reply_cn: reply 的简体中文意思; "
    "(3) suggestion: 给学员下一句可直接开口的示范英文; "
    "(4) suggestion_cn: suggestion 的简体中文意思; "
    "(5) learner_cn: 学员刚说的那句英文的简体中文意思。"
)

#: 判分侧 JSON 形状 (不含任何台词字段 —— 生成侧永不复用判分形状, 反之亦然)。
_JUDGE_JSON_SHAPE = (
    '只输出 JSON: {"polish": {"original": "...", "polished": "...", '
    '"polished_cn": "...", "explanation_cn": "..."} | null, '
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


def _recent_lines_block(turns: Sequence[Mapping[str, Any]], *, keep: int = 10) -> str:
    """最近 N 轮**已经说过的台词与给过的示范** —— 反重复的原料 (§A5).

    实战侧服务端有状态 (``mission.turns[]`` 里存着每轮的 ``reply``/``suggestion``), 所以
    这条清单不必客户端 echo。prompt 里配一句"不得同义复写"硬要求 —— 换新信息、换句式,
    否则就是学员报的"AI 反复问同一类问题"。
    """
    lines: list[str] = []
    for turn in turns[-keep:]:
        reply = str(turn.get("reply") or "").strip()
        suggestion = str(turn.get("suggestion") or "").strip()
        if reply:
            lines.append(f"- 你已经问过: {reply}")
        if suggestion:
            lines.append(f"- 你已经给过示范: {suggestion}")
    return "\n".join(lines)


def turn_prompt(
    course: SceneCourse,
    tasks_state: Sequence[Mapping[str, Any]],
    turns: Sequence[Mapping[str, Any]],
    user_text: str,
) -> list[LlmMessage]:
    """§5.5-2 的**台词** prompt: 人设 + 场景 + 议程 + 已发生的对话 + 禁重复清单 + 本轮输入."""
    mission = course.mission
    system = (
        f"你是英语口语陪练「{_truncate(mission.persona_cn, 300)}」。"
        f"场景: {_truncate(mission.context_cn, 800)}。"
        f"学员扮演「{_truncate(mission.user_role_cn, 200)}」, 中文母语、能读写但开口少 "
        f"(CEFR {course.level})。你在一场**有任务清单**的实战对话里推进议程。"
        f"{GENERATION_RULES}"
    )
    user = (
        f"议程 (任务清单, 按学员说过的话累积判定):\n{_tasks_block(tasks_state)}\n"
        "把剧情往**未完成的任务**推 (reply 带一个往那儿走的追问, suggestion 是学员"
        "能直接开口推进它的那句), 别让对话提前结束。\n\n"
        f"已发生的对话 (Coach=你, Learner=学员):\n"
        f"{_transcript_block(turns, keep=6) or '(还没有对话, 这是第一轮)'}\n\n"
        "你已经说过的台词与给过的示范 (**不得同义复写**: 换新信息、换角度, 句式也要换, "
        "同一句话换个说法再说一遍就是失败):\n"
        f"{_recent_lines_block(turns) or '(还没有历史台词)'}\n\n"
        f"学员本轮说 (英文转写):\n{user_text}\n\n"
        f"{GENERATION_JSON_SHAPE}"
    )
    return [
        LlmMessage(role="system", content=system),
        LlmMessage(role="user", content=user),
    ]


def judge_prompt(
    course: SceneCourse,
    tasks_state: Sequence[Mapping[str, Any]],
    user_text: str,
) -> list[LlmMessage]:
    """§5.5-2 的**判分** prompt: 只带最后一句 + 任务块 (§6: 两次调用的 prefill 成本).

    整段对话不进判分 prompt: 判分只看"这一句说得怎么样 + 任务清单到哪了", 带上历史既
    多烧 prefill 又让模型被无关上下文带偏。
    """
    system = f"学员是中文母语、能读写但开口少的英语学习者 (CEFR {course.level})。{_JUDGE_RULES}"
    user = (
        f"任务清单 (按学员说过的话累积判定):\n{_tasks_block(tasks_state)}\n\n"
        f"学员本轮说 (英文转写):\n{user_text}\n\n"
        f"{_JUDGE_JSON_SHAPE}"
    )
    return [
        LlmMessage(role="system", content=system),
        LlmMessage(role="user", content=user),
    ]


def heuristic_task_progress(
    user_text: str,
    tasks_state: Sequence[Mapping[str, Any]],
) -> list[TaskProgress]:
    """**快判** (§A3「快判先顶」): 词面覆盖率先勾一次 checklist, 零 LLM、同步可跑。

    * 口径: 学员话术对未完成任务 ``hint_en`` 示范句的**内容词**覆盖率 >=
      :data:`TASK_HEURISTIC_COVERAGE` (``_matched_terms``, 与 drill 同源);
    * 它是**词面**判定, 不是语义判定 —— 所以只动 checklist, **不发任何画像事件**
      (要出假证据才是污染; LLM 判分回写时走 :func:`merge_task_progress` 的 done 粘滞,
      只许变好不许变差);
    * 没有示范句的任务直接跳过 (宁缺勿滥)。
    """
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
                    evidence="词面覆盖了任务示范用语 (启发式快判, 未经语义核对)",
                )
            )
    return progress


def coerce_bilingual(text: str) -> str:
    """双语字段的**可信度**门 (§A4/D5): 中文侧出现 ASCII 字母就算不可信 -> 置空.

    为什么: 模型偶尔把 ``reply_cn`` 写成英文 (或中英混排), 那一行渲染出来就是"中文"标签下的
    英文 —— 比缺行更糟 (D5: 缺字段 = 那一行不渲染, 绝不机翻占位)。判定只用最朴素的字符范围
    扫 (``re`` 与 CJK 白名单都不引入: 仓里那两处 ``re`` 是 id 白名单用途)。

    收口在 :func:`generate_turn` 里 (实战轮与自由对话轮共用这一份), 所以两个页面同一条纪律,
    没有第二份可以漂移的实现。
    """
    cleaned = text.strip()
    if not cleaned:
        return ""
    if any("a" <= ch.lower() <= "z" for ch in cleaned):
        return ""
    return cleaned[:500]


def _bilingual_generation(judgement: TurnGeneration) -> TurnGeneration:
    """把五个字段里的三处中文过一遍可信度门 (台词/示范本身是英文, 不过门)."""
    return judgement.model_copy(
        update={
            "reply_cn": coerce_bilingual(judgement.reply_cn),
            "suggestion_cn": coerce_bilingual(judgement.suggestion_cn),
            "learner_cn": coerce_bilingual(judgement.learner_cn),
        }
    )


async def generate_turn(
    messages: Sequence[LlmMessage],
    *,
    model_id: str | None = None,
) -> tuple[TurnGeneration, str]:
    """**请求内唯一一次 LLM**: 台词 + 双语 (§A1/D1), 走 :func:`_judge` 的唯一收口.

    收 **messages** 而不是课程/场景对象: 实战轮与自由对话轮**共用这一份 schema 与这组
    参数**(prompt 各自拼 —— :func:`turn_prompt` 给实战轮, ``dialogue._scene_messages``
    给自由对话), 两处的温度/token/超时/schema 因此没有第二份可以漂移的副本。

    返回 ``(generation, llm_source)``。所有参数显式给:

    * ``model=resolve_roleplay_model(model_id)`` —— 生成是**纯文本**用途, 可以跟随
      客户端选的模型 (D2); 判分不吃 ``model_id``, 那是 :func:`judge_turn` 的事;
    * ``max_tokens=GEN_MAX_TOKENS`` / ``temperature=GEN_TEMPERATURE`` —— 旧调用点
      没传 ``temperature``, 落进判分默认 0.2 (§0 第二个成因), 新函数不许再犯;
    * ``timeout=GEN_LLM_TIMEOUT_S(10)`` < ``hard_budget_s=GEN_TURN_BUDGET_S(14)``:
      单次 socket 先炸, 坏 JSON 的回喂重试才真落在墙钟里 (旧形状 socket 20 > 墙钟 15,
      一次尝试就吃穿整轮);
    * ``extra_body=no_thinking_body()`` —— 关掉 Qwen3 系的隐藏思考 token (实测占掉
      一半墙钟; 开关默认 false / ``.env`` 未设时返回 None, 调用形状不变)。

    **拿不到台词就抛** :class:`LlmUnavailableError` (未配置/超时/两次都不合规/无 reply):
    D5 —— 两个端点都回 503、这一轮不落库不前进, 绝不回放剧本、绝不机翻占位。
    """
    resolved = resolve_roleplay_model(model_id)
    judgement = await _judge(
        TurnGeneration,
        messages,
        max_tokens=GEN_MAX_TOKENS,
        temperature=GEN_TEMPERATURE,
        model=resolved,
        timeout=GEN_LLM_TIMEOUT_S,
        hard_budget_s=GEN_TURN_BUDGET_S,
        extra_body=no_thinking_body(),
    )
    if not judgement.reply:
        # schema 宽容 (五个字段都可缺省), 但"没有台词"不等于"这一轮发生了" —— 端点那边
        # 一旦放行就会渲染一个空气泡, 所以在这里按不可用收口。
        raise LlmUnavailableError("台词生成结果里没有 reply")
    return _bilingual_generation(judgement), resolved


async def judge_turn(
    course: SceneCourse,
    tasks_state: Sequence[Mapping[str, Any]],
    user_text: str,
    *,
    hard_timeout_s: float | None = None,
) -> tuple[MissionTurnJudgement, GradeSource, str | None]:
    """实战单轮的**判分**调用 (后台作业专用: 1 次; 坏 JSON 回喂重试 1 次; 再坏降级).

    返回 ``(judgement, source, llm_source)``; 判分模型 = 服务端默认
    (:func:`app.services.drill_grader._resolve_judge_model`), **不吃客户端 ``model_id``**
    (D2: 判分口径必须在一门课内稳定); ``max_tokens=GRADE_MAX_TOKENS``。

    ``hard_timeout_s``: 整个调用 (含内置重试) 的硬预算 —— 作业里报
    ``GRADING_JOB_BUDGET_S`` (见 ``drill_grader`` 硬预算块)。降级 (LLM 不可用/超时/
    两次都不合规) 不抛异常: 返回 ``source="heuristic"`` 的**词面快判**结果 (没有润色、
    没有语法/词汇分) —— "判分失败 = 没有润色", 不是"这一轮不存在" (§A3)。
    """
    try:
        judgement = await _judge(
            MissionTurnJudgement,
            judge_prompt(course, tasks_state, user_text),
            max_tokens=GRADE_MAX_TOKENS,
            hard_budget_s=hard_timeout_s,
        )
    except (LlmUnavailableError, TimeoutError) as exc:
        logger.warning("mission turn grading degraded to heuristic | reason={}", exc)
        return (
            MissionTurnJudgement(task_progress=heuristic_task_progress(user_text, tasks_state)),
            "heuristic",
            "stub",
        )
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
    D1 拆调用之后**判分与 ISE 分两处落**: 作业只带 ``judgement`` (``anchored=None``),
    请求只带 ``anchored`` (见 :func:`anchored_ability_events`)。
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
    events.extend(anchored_ability_events(anchored))
    return events


def anchored_ability_events(
    anchored: AnchoredPronunciation | None,
) -> list[AbilityEvidence]:
    """转写锚定 ISE 的发音/流利证据 (§5.6 的生产者那一半).

    与判分无关 (只依赖音频 + IAT 转写), 所以请求内就能落 —— 判分那半边在后台作业里
    (D1)。``anchored is None`` = 讯飞没配/失败/超预算 -> 空列表: 宁可发音维度空缺,
    不造假证据。
    """
    if anchored is None:
        return []
    return [
        AbilityEvidence(
            dimension="pronunciation",
            score=anchored.pronunciation,
            source="xunfei",
            weight=1.0,
            ise_ref_mode="transcript_anchored",
        ),
        AbilityEvidence(
            dimension="fluency",
            score=anchored.fluency,
            source="xunfei",
            weight=1.0,
        ),
    ]


# ====== 5) 独立润色 / 对话轮润色 ======

_POLISH_SYSTEM = (
    "你是英语写作润色器, 学员是中文母语的英语初学者 (A2-B1)。"
    "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。"
    "任务: 把学员的英文句子改得**语法正确且可以自然开口说出** (保持原意, 不换话题, "
    "不扩写)。explanation_cn 用一句简体中文指出关键修改 (时态/搭配/冠词/礼貌语气等), "
    "不要罗列所有改动。若句子本来就没有值得改的语法或用词问题, polished 输出空字符串。"
    "polished_cn 给润色句的简体中文意思 (D4 双语对照卡的那一行)。"
    '只输出 JSON: {"polished": "...", "explanation_cn": "...", "polished_cn": "..."}'
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
    (规则改写句子容易改错意思), 让 UI 显示"暂不可用"即可。超时同理: 预算
    (:data:`app.services.drill_grader.POLISH_BUDGET_S`) 一到就走 ``LlmUnavailableError``,
    端点照常 200 + ``polish=null`` + 中文说明, 不 500、不拖死客户端 socket。
    ``model`` 是**文本用途**的模型 (客户端可指定); 默认走服务端模型。
    """
    try:
        judgement = await _judge(
            PolishJudgement,
            polish_prompt(text),
            max_tokens=300,
            model=model,
            hard_budget_s=POLISH_BUDGET_S,
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
            polished_cn=_truncate(judgement.polished_cn, 500),
        ),
        "llm",
        llm_used,
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
    ]
    if facts.get("evidence_note_cn"):
        # 别让模型拿"无证据"当低分去编造短板: 分数缺席是**部署没配评测**, 不是练得差。
        lines.append(f"证据说明: {facts['evidence_note_cn']}")
    lines.append("学员在实战对话里说过的话:")
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
    """无 LLM 时的诚实文案 (全部从真实数据拼, 不吹牛不编造).

    两个"不撒谎"的细节 (§2.6 / §P6 次因): ① ``dims_note_cn`` 非空 = 本场**没有可信
    评分证据**, 那它就是第一条亮点 —— 分数留空不是 0 分, 别让学员以为练砸了;
    ② ``briefing_skipped > 0`` 时不能说"全部过关", 要说"走完了, 其中 N 步跳过"。
    """
    dims = cast("Mapping[str, Any]", facts.get("dims", {}))
    highlights: list[str] = []
    note = str(facts.get("dims_note_cn") or "")
    if note:
        highlights.append(note)
    if facts.get("cleared"):
        highlights.append("实战任务全部达成 —— 沟通目的完成了, 这是最重要的。")
    elif facts.get("done_count"):
        highlights.append(f"实战里做成了 {facts['done_count']} 项沟通任务; 开口的每一轮都是进步。")
    skipped = int(facts.get("briefing_skipped") or 0)
    if facts.get("briefing_passed"):
        highlights.append("打基础清单全部走完。")
    elif skipped and facts.get("briefing_done"):
        highlights.append(f"打基础清单全部走完 (其中 {skipped} 步选择跳过, 也算推进)。")
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


def _review_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    """喂给 LLM 前收敛一下列表 (prompt 大小可控), 存的也就是这一份."""
    clipped = dict(facts)
    clipped["utterances"] = [
        _truncate(str(item), 200) for item in cast("list[str]", facts.get("utterances") or [])[:12]
    ]
    return clipped


#: 四维与总分**全无可信证据**时给学员的那句话 (§2.6 次因). 破折号 "—" 会被读成"考了
#: 0 分", 而事实是这场**没有可信的评分来源** (讯飞/LLM 未配置或全部降级) —— 缺席要按
#: 缺席说, 别让它长成一个数字的形状。
NO_EVIDENCE_NOTE_CN = (
    "本场没有可信评分证据 (外部评测 / LLM 判分未参与), 总分与四维留空 —— 不是练得差。"
)


@dataclass(frozen=True)
class ReviewSkeleton:
    """确定性骨架 + 喂给文案作业的**已裁剪** prompt 输入.

    ``facts`` 是给 :func:`review_copy` 的料: 骨架阶段已经把转写列表裁到 12 条 x 200 字
    (整场不设限会把 prompt 吹大, 而文案质量根本吃不下那么多)。端点把它落到
    ``doc["review_facts"]``, 这样进程重启后**重派**的作业拿得到同一份输入, 不必再查一次
    ``practice_steps`` —— 也别落未裁剪的那份, doc 是整场会话都要带着的快照。
    """

    report: ReviewReport
    facts: dict[str, Any]


class ReviewCopy(NamedTuple):
    """报告里**唯一**来自 LLM 的四个字段 (§P6 拆分后, 文案作业的全部产物).

    命名成元组是为了把"整份复盘报告只有这四件是问模型才知道的"这件事写进签名; 消费方一律
    按字段名取用, 合并只走 :func:`merge_review_copy`。
    """

    highlights: list[str]
    improvements: list[str]
    source: GradeSource
    llm_source: str | None


def _dim_evidence_note(dims: Mapping[str, Any]) -> str:
    """四维里**一个数都没有** -> 给学员的诚实标注; 只要有任何一个可信数就留空."""
    return "" if any(value is not None for value in dims.values()) else NO_EVIDENCE_NOTE_CN


async def build_review_report(
    *,
    course: SceneCourse,
    session_id: str,
    mission: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    ability_before: Mapping[str, float | None] | None,
    ability_after: Mapping[str, float | None] | None,
    briefing_passed: bool,
    briefing_skipped: int = 0,
    hints_used: int = 0,
) -> ReviewReport:
    """**同步**出一份完整复盘报告 = :func:`build_review_skeleton` + :func:`review_copy`.

    §P6 之后**端点不再用它**: 收工路径改成"请求里只算数值骨架, 文案交给后台作业"
    (``app.api.v1.course_sessions._finish_mission_state`` /
    ``run_review_copy_job``) —— 这条组合的墙钟含一次 LLM 调用 (``REVIEW_LLM_BUDGET_S``),
    留在同步 handler 里就是把学员报的超时原样留下。它仍是"给脚本/测试一次拿全量报告"
    的公开入口, 也是 :func:`review_copy` 同步预算 (20s) 的唯一使用者。
    """
    skeleton = build_review_skeleton(
        course=course,
        session_id=session_id,
        mission=mission,
        steps=steps,
        ability_before=ability_before,
        ability_after=ability_after,
        briefing_passed=briefing_passed,
        briefing_skipped=briefing_skipped,
        hints_used=hints_used,
    )
    text = await review_copy(
        course,
        skeleton.facts,
        hard_budget_s=REVIEW_LLM_BUDGET_S,
    )
    return merge_review_copy(skeleton.report, text)


def merge_review_copy(report: ReviewReport, text: ReviewCopy) -> ReviewReport:
    """把文案四件套并进数值骨架 (§P6: 同步组合与后台作业**共用**同一个合并点).

    只覆盖 ``highlights`` / ``improvements`` / ``source`` / ``llm_source`` —— 四个字段是
    报告里**唯一**来自 LLM 的部分, 数值 (dims / overall / checklist / 逐词 …) 一律不动,
    所以后台作业重跑或失败都不会改动学员已经看到的分数。
    """
    return report.model_copy(
        update={
            "highlights": list(text.highlights),
            "improvements": list(text.improvements),
            "source": text.source,
            "llm_source": text.llm_source,
        }
    )


async def review_copy(
    course: SceneCourse,
    facts: Mapping[str, Any],
    *,
    hard_budget_s: float,
) -> ReviewCopy:
    """复盘**文案** (§5.5-3 一次批量调用); 任何不可用都诚实退回确定性文案.

    永不抛 ``LlmUnavailableError`` —— 降级就是它的正常出口 (``source="heuristic"``,
    ``llm_source="stub"``, 复盘页已有的降级横幅)。``hard_budget_s`` **故意没有默认值**:
    同步组合 (:func:`build_review_report`) 报 ``REVIEW_LLM_BUDGET_S``, 后台作业
    (:func:`app.api.v1.course_sessions.run_review_copy_job`) 报
    ``REVIEW_COPY_JOB_BUDGET_S``, 谁也别想拿"默认预算"蒙过
    ``tests/test_latency_budget.py`` 的求和与 AST 扫描。

    ``facts`` 收**已裁剪**的那份 (:func:`_review_facts`): prompt 大小是这条调用的成本主项,
    骨架期裁一次就够了, 后台作业直接复用落库的那份。
    """
    try:
        judgement = await _judge(
            ReviewTextJudgement,
            review_prompt(course, facts),
            max_tokens=REVIEW_MAX_TOKENS,
            hard_budget_s=hard_budget_s,
        )
        highlights = [_truncate(item, 300) for item in judgement.highlights if item.strip()][:3]
        improvements = [_truncate(item, 300) for item in judgement.improvements if item.strip()][:3]
        if not highlights and not improvements:
            raise LlmUnavailableError("复盘文案为空")
        return ReviewCopy(highlights, improvements, "llm", _resolve_judge_model())
    except LlmUnavailableError as exc:
        # _judge 自身已消化解析/校验错误 + 超硬预算; 这里同时兜 "合法 JSON 但两套文案全空".
        fallback_high, fallback_improve = deterministic_review(facts)
        logger.warning("review copy degraded to deterministic | reason={}", exc)
        return ReviewCopy(fallback_high, fallback_improve, "heuristic", "stub")


def build_review_skeleton(
    *,
    course: SceneCourse,
    session_id: str,
    mission: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    ability_before: Mapping[str, float | None] | None,
    ability_after: Mapping[str, float | None] | None,
    briefing_passed: bool,
    briefing_skipped: int = 0,
    hints_used: int = 0,
) -> ReviewSkeleton:
    """复盘报告的**确定性骨架** (§P6: 同步、无网络、无 LLM, 因此不会超时).

    除了 ``highlights`` / ``improvements`` / ``source`` / ``llm_source`` 这四件文案,
    报告里没有一个是"必须问了模型才知道"的: 四维聚合、ISE 子维度、任务清单、通关判定、
    总分 (= 四维均值)、原话对照、生词命中、画像增量全是 ``practice_steps`` 行与 doc
    快照的算术。所以收工请求可以立刻给学员一份**数值完整**的报告, 文案慢慢后台补
    (``doc["review_status"]``), 而不是让学员对着 30s 的 socket 干等一次 LLM 写作。

    文案先按 :func:`deterministic_review` **填实**: 骨架本身就是一份可渲染的完整报告
    (复盘页已有的降级横幅), 后台作业成功就覆盖成 LLM 文案, 失败/超时也是
    ``review_status="ready"`` —— 学员永远不会拿到空白。

    返回的 :class:`ReviewSkeleton` 里带着**已裁剪**的 prompt 输入 (``facts``), 落进
    ``doc["review_facts"]`` 供后台作业复用: 骨架阶段已经把转写列表裁到 12 条 x 200 字,
    重算一遍既费代码又要再查一次 step 行。
    """
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
        "briefing_skipped": int(briefing_skipped),
        # 跳过也算"走完清单" —— 门禁 (_reconcile_stage) 认 passed|skipped, 文案口径必须
        # 一致, 否则一次正当跳过就把"清单走完了"这句话静默吃掉了 (§2.6 次因二)。
        "briefing_done": bool(briefing_passed) or int(briefing_skipped) > 0,
        "open_required": [view.desc_cn for view in checklist if view.required and not view.done],
        "evidence_note_cn": _dim_evidence_note(dims),
    }
    facts = _review_facts(facts)
    highlights, improvements = deterministic_review(facts)
    delta = ability_delta(
        dict(ability_before) if ability_before else None,
        dict(ability_after) if ability_after else None,
    )
    report = ReviewReport(
        session_id=session_id,
        scene_id=course.id,
        title=course.title,
        cleared=cleared,
        auto_finished=bool(mission.get("auto_finished")),
        turn_count=int(mission.get("turn_count") or 0),
        max_turns=int(mission.get("max_turns") or course.mission.max_turns),
        overall=mean_of(list(dims.values())),
        dims=dims,
        pronunciation_subs=subs,
        evidence_note_cn=str(facts["evidence_note_cn"]),
        highlights=highlights,
        improvements=improvements,
        checklist=checklist,
        transcript_pairs=collect_transcript_pairs({"mission": dict(mission)}, steps),
        new_tokens=collect_new_tokens(course, utterances),  # 语料用未裁剪的那份
        ability_delta=delta,
        hints_used=hints_used,
        source="heuristic",
        llm_source="stub",
    )
    return ReviewSkeleton(report=report, facts=facts)


__all__ = sorted(
    [
        "AnchoredPronunciation",
        "GEN_MAX_TOKENS",
        "GEN_TEMPERATURE",
        "GRADE_MAX_TOKENS",
        "MissionTaskView",
        "MissionTurnJudgement",
        "Polish",
        "REVIEW_MAX_TOKENS",
        "ReviewCopy",
        "ReviewReport",
        "ReviewSkeleton",
        "TASK_HEURISTIC_COVERAGE",
        "TranscriptPair",
        "TurnGeneration",
        "aggregate_pronunciation_subs",
        "aggregate_step_dims",
        "all_required_done",
        "anchored_ability_events",
        "anchored_pronunciation",
        "build_review_report",
        "build_review_skeleton",
        "collect_new_tokens",
        "collect_transcript_pairs",
        "deterministic_review",
        "generate_turn",
        "heuristic_task_progress",
        "initial_task_states",
        "judge_prompt",
        "judge_turn",
        "merge_review_copy",
        "merge_task_progress",
        "polish_prompt",
        "polish_text",
        "review_copy",
        "task_views",
        "turn_ability_events",
        "turn_prompt",
        "xunfei_ise_configured",
    ]
)
