"""通关会话状态机端点 (计划 §5.3「通关会话状态机」+ §5.4/§5.5-2, 阶段 P2+P3).

情景课的学习闭环是 **打基础 (briefing) -> 实战对话 (mission) -> 复盘 (review)**.
本模块持有整个状态机: briefing 步骤评分接线在 P2 (T3), mission 轮 / hint /
finish-mission (ReviewReport) 与 §5.6 画像落库在 P3 (T4)。

为什么状态放在服务端 (计划 §四 决策表): 客户端只发音频/文本, 不回传 history ——
省流量、防篡改、App 崩了也能用 ``GET /sessions/{id}`` 恢复到原处.
``practice_sessions.doc`` 是这个状态机的**唯一快照**; 列上的 ``stage`` / ``status``
只是它的冗余投影, 好让「继续学习」列表走索引而不必解析 JSON.

端点
----
================================  ==================================================
``POST /sessions``                开场: 建会话 + 课程快照 + 打基础清单 (201)
``POST /sessions/{id}/step``      逐步评分并推进 (4 种题型 -> DrillGrade)
``POST /sessions/{id}/skip-step`` 跳过一步 (每场最多 2 次, 第 3 次 409)
``POST /sessions/{id}/mission``   实战对话每轮 (1 次综合 LLM 调用, §5.5-2)
``POST /sessions/{id}/hint``      要提示 (不消耗判定, 标记 costs_score, 不调 LLM)
``POST /sessions/{id}/finish-mission`` 主动收工 -> ReviewReport (§5.3)
``GET  /sessions/{id}``           崩溃恢复快照 (含 mission / review 视图)
``GET  /sessions``                最近会话列表 (首页「继续学习」)
================================  ==================================================

并发纪律
--------
所有 doc 变更都走 :func:`_save_doc`. 读快照时带 ``with_for_update()`` (PG 上是真的行
锁), 写回时由 ``PracticeSession.revision`` 这张 **version_id_col 乐观锁**把关: 两个并发
``/step`` 里后落库的那个 UPDATE 匹配 0 行 -> ``StaleDataError`` -> 409
``SESSION_CONCURRENT_UPDATE``, 它刚插入的评分行也随事务一起回滚, 所以**同一步绝不会被推
进两次**. 重复提交已完成的 step 更早就被 ``STEP_ALREADY_DONE`` 挡下 (幂等门).

归属判定
--------
v2.0 仍是 device_id 账号体系 (计划 §十二), 所以每个端点都要带身份 (``device_id`` 或
``user_id``, 二选一). 会话归属看 ``user_id``: 别的账号访问 -> 403, 设备 A 恢复不了设备
B 的局.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.course import FoundationStep, SceneCourse
from app.models.db import History, PracticeSession, PracticeStep, User
from app.models.schema import WordScore
from app.services import ability_engine, mission_engine, scene_store
from app.services.ability_engine import record_step_evidence
from app.services.audio_input import decode_audio
from app.services.drill_grader import (
    ANSWER_MAX_CHARS,
    PASS_SCORE,
    SKIP_SOURCE,
    AbilityEvidence,
    DrillGrade,
    ability_evidence,
    grade_step,
    transcribe_audio,
)
from app.services.mission_engine import MissionTaskView, Polish, ReviewReport

router = APIRouter(tags=["course-sessions"])

# ====== 状态机常量 ======

SessionKind = Literal["scene_course", "lesson", "free_dialogue", "assessment"]
SessionStage = Literal["briefing", "mission", "review", "done"]
SessionStatus = Literal["active", "completed", "abandoned"]
StepStatus = Literal["pending", "passed", "skipped"]

#: P2 只实现情景课闭环; 其余 kind 的会话分别归 P3 (自由对话) / P4 (测评) 的端点创建.
SUPPORTED_KINDS: tuple[str, ...] = ("scene_course",)

#: 一场会话可以人工跳过的步数 (计划 §5.3: 上限 2 次, 第 3 次 409).
SKIP_LIMIT = 2

#: 事件日志只留最近 N 条, 防 doc 无限膨胀 (整份快照存在 JSON 列里).
_EVENTS_KEPT = 40

#: ``doc`` 的 schema 版本 —— 恢复老快照时按这个字段做兼容读.
DOC_VERSION = 1

#: ``audio_b64`` 的字符上限: base64 之后的 10 MB PCM, 与 ``ScoreRequest.audio`` 同量级.
_MAX_AUDIO_B64_CHARS = 14_000_000


# ====== 请求 / 响应模型 ======


class _Identity(BaseModel):
    """会话端点共用的身份字段: ``device_id`` 与 ``user_id`` 至少给一个."""

    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=36)


class CreateSessionRequest(_Identity):
    kind: SessionKind = "scene_course"
    #: kind=scene_course 必填; id 是 T2 的稳定契约 (curated ``scene_*`` + P4 生成课).
    scene_id: str | None = Field(default=None, min_length=1, max_length=64)


class StepProgress(BaseModel):
    """清单里一步的当前位置与结果 (客户端渲染进度点 + 重做提示)."""

    id: str
    index: int
    type: str
    status: StepStatus
    attempts: int = 0
    best_score: float | None = None
    last_score: float | None = None
    #: 这次分数的来源: xunfei | stub | llm | heuristic (UI 据此打"非真实评测"警示).
    last_source: str | None = None
    #: 最近一次完整评分结果 (含 feedback_cn / 逐词染色), 恢复页面时不必重算.
    last_grade: dict[str, Any] | None = None


class BriefingProgress(BaseModel):
    """打基础阶段的进度汇总."""

    total: int
    done: int
    passed: int
    skipped: int
    skips_used: int
    skip_limit: int
    skips_remaining: int
    next_step_id: str | None = None
    unlocked_mission: bool
    steps: list[StepProgress] = Field(default_factory=list)


class SessionView(BaseModel):
    """``POST /sessions`` 与 ``GET /sessions/{id}`` 的载荷 (同一形状, 客户端一套模型)."""

    session_id: str
    kind: str
    scene_id: str
    stage: str
    status: str
    revision: int
    created_at: str
    last_active_at: str
    briefing: BriefingProgress
    #: 实战对话状态机分区 (§5.3 P3): ``turns`` / ``tasks`` (累积清单) / ``turn_count`` /
    #: ``max_turns`` / ``cleared`` / ``auto_finished`` / ``finished`` / ``hints_used`` /
    #: ``opening``. 首轮 ``/mission`` 之前是空 dict; 恢复页面直接按它重绘气泡与清单.
    mission: dict[str, Any] = Field(default_factory=dict)
    #: 收工后的复盘报告 (``doc["review"]``); 未收工为 null. 崩溃恢复复盘页不必重算.
    review: dict[str, Any] | None = None
    #: 整课内容: 开场与恢复都要回, 客户端画词汇卡/题干不必再打一次 /scenes/{id}.
    course: SceneCourse | None = None


class SessionSummary(BaseModel):
    """``GET /sessions`` 列表项 (首页「继续学习」卡片)."""

    session_id: str
    kind: str
    scene_id: str
    stage: str
    status: str
    title: str = ""
    level: str = ""
    done_steps: int = 0
    total_steps: int = 0
    unlocked_mission: bool = False
    last_active_at: str = ""


class StepAttemptRequest(_Identity):
    step_id: str = Field(min_length=1, max_length=32)
    #: PCM L16 16kHz mono 的 base64 (与 ``ScoreRequest.audio`` 同一套口径: pydantic v2
    #: 对 ``bytes`` 字段存的是 base64 文本自身的字节, 统一由 decode_audio 解).
    audio_b64: bytes | None = Field(default=None, max_length=_MAX_AUDIO_B64_CHARS)
    #: 复述/翻译/造句的文本作答 (P2 主路径); 只给音频时走讯飞 IAT 转写.
    text: str | None = Field(default=None, max_length=ANSWER_MAX_CHARS)


class SkipStepRequest(_Identity):
    step_id: str = Field(min_length=1, max_length=32)


class StepAttemptResponse(BaseModel):
    """``/step`` 与 ``/skip-step`` 的返回: 这次评分 + 清单进度 + 是否解锁实战."""

    session_id: str
    revision: int
    stage: str
    status: str
    grade: DrillGrade
    briefing: BriefingProgress
    unlocked_mission: bool
    #: §5.6 维度证据 (P3 起同一份证据已经写进 ``ability_events`` 并推动画像).
    ability_events: list[AbilityEvidence] = Field(default_factory=list)


# ====== P3: 实战对话 (mission) 的请求 / 响应模型 ======


class MissionTurnRequest(_Identity):
    """实战单轮输入: 只给音频 (IAT 转写) 或只给文本, 至少一个."""

    audio_b64: bytes | None = Field(default=None, max_length=_MAX_AUDIO_B64_CHARS)
    text: str | None = Field(default=None, max_length=ANSWER_MAX_CHARS)


class NewlyDoneTask(BaseModel):
    """本轮**新**完成的任务 (checklist 弹勾动画的原料)."""

    id: str
    evidence: str = ""


class MissionTurnResponse(BaseModel):
    """``POST /sessions/{id}/mission`` 的返回 (§5.3 形状: 含 newly_done + checklist)."""

    session_id: str
    revision: int
    stage: str
    status: str
    #: 本次是第几轮 (1 起).
    turn_index: int
    #: 学员这轮说的话 (文本作答原样; 音频作答为 IAT 转写).
    transcript: str
    #: persona 的下一句英文 (客户端播 TTS).
    reply: str
    #: 给学员的下一句示范.
    suggestion: str
    #: 「原句 vs 更好说法」对照; 没问题 / 不可用时为 null.
    polish: Polish | None = None
    #: 4 维子分 (null = 本轮该维度没有证据, §5.3 sub_scores).
    sub_scores: dict[str, float | None] = Field(default_factory=dict)
    #: 锚定 ISE 的逐词染色 (自由产出; 讯飞没配时为 []).
    word_details: list[WordScore] = Field(default_factory=list)
    speech_rate_wpm: float | None = None
    newly_done: list[NewlyDoneTask] = Field(default_factory=list)
    #: 任务清单的**服务端累积全景** (done 粘滞).
    checklist: list[MissionTaskView] = Field(default_factory=list)
    #: 全部必做任务已达成 (通关).
    cleared: bool
    turn_count: int
    max_turns: int
    #: 本轮到达 ``max_turns`` 上限 -> 服务端自动收工 (report 一并返回).
    auto_finished: bool
    #: 会话是否已结束 (auto-finish 或 finish-mission 之后 true).
    finished: bool
    #: 本轮写进 §5.6 管线的维度证据 (stub/heuristic 为 weight=0).
    ability_events: list[AbilityEvidence] = Field(default_factory=list)
    #: 评分侧来源: llm | heuristic (UI 按 heuristic 打"非真实评测"警示).
    source: str
    #: 判分 LLM 的 provenance: 模型 id | "stub".
    llm_source: str | None = None
    #: 本轮是否因之前"要提示"被标记 (提示过的回合分数可信度打折, §5.3).
    costs_score: bool = False
    #: 仅 ``auto_finished`` 时有值: 服务端已生成的复盘报告 (§5.3 ReviewReport).
    review: ReviewReport | None = None


class HintRequest(_Identity):
    """``POST /sessions/{id}/hint``: 无参数动作 (调的是"现在的卡点")."""


class MissionHintPayload(BaseModel):
    """提示内容: 优先给未完成的必做任务示范, 任务全给了就回落到参考剧本."""

    task_id: str | None = None
    desc_cn: str = ""
    hint_en: str = ""
    #: 参考剧本里学员的下一句 (没有未完成任务时的兜底素材).
    script_line: str = ""
    #: 中文说明 ("先把价格问出来" 之类).
    note_cn: str = ""


class HintResponse(BaseModel):
    session_id: str
    revision: int
    stage: str
    status: str
    hint: MissionHintPayload
    #: 提示不调 LLM、不改变任务判定; 只是**标记**下一个判定回合 (costs_score).
    costs_score: bool = True
    hints_used: int


class FinishMissionRequest(_Identity):
    """主动收工."""


class FinishMissionResponse(BaseModel):
    session_id: str
    revision: int
    stage: str
    status: str
    #: §5.3 复盘报告 (持久化在 ``doc["review"]``, ``GET /sessions/{id}`` 亦返回).
    report: ReviewReport


# ====== doc 快照 schema ======
#
# ``practice_sessions.doc`` 的形状 (v1):
#
#   {
#     "v": 1, "kind": "scene_course",
#     "course": { SceneCourse.model_dump() },     # 课程快照: 内容改了也不影响已开局的进度
#     "steps": [ {"id","index","type","status","attempts","best_score",
#                 "last_score","last_source","last_grade"} ],
#     "next_index": int,                          # 指针: 下一步的下标 (门禁读它)
#     "skips_used": int, "skip_limit": 2,
#     "unlocked_mission": bool,
#     "events": [ {"at","kind","step_id","score"} ],   # 最近 40 条
#     "ability_before": {4 维画像分快照 | None},        # P3: 开局基线 (§5.3 ability_delta)
#     "mission": { P3: v / turns / tasks(累积状态) / turn_count / max_turns /
#                  cleared / auto_finished / finished / hints_used / pending_costs
#                  / opening },   首轮 /mission 时才初始化
#     "review": { ReviewReport.model_dump() },    # P3: 收工后写入 (此前不存在)
#     "stage": ..., "status": ..., "created_at": ..., "updated_at": ...
#   }


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    """DB 列的 datetime -> ISO 串.

    sqlite 不存 tzinfo (驱动会剥掉), PG 会存, 所以 naive 一律按 UTC 解释, API 表面
    永远吐 offset-aware 时间戳 (口径同 ``lessons.py`` / ``history.py``).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status_of(value: Any) -> StepStatus:
    """把快照里的 status 收敛到字面量 —— 读老/脏数据时不把脏值透给客户端."""
    text = str(value or "pending")
    return cast(StepStatus, text if text in ("pending", "passed", "skipped") else "pending")


def _truncate(value: str, limit: int = 300) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


def _initial_doc(
    course: SceneCourse, kind: str, ability_before: dict[str, float | None] | None = None
) -> dict[str, Any]:
    now = _iso(_now())
    return {
        "v": DOC_VERSION,
        "kind": kind,
        "course": course.model_dump(mode="json"),
        "steps": [
            {
                "id": step.id,
                "index": index,
                "type": step.type,
                "status": "pending",
                "attempts": 0,
                "best_score": None,
                "last_score": None,
                "last_source": None,
                "last_grade": None,
            }
            for index, step in enumerate(course.briefing)
        ],
        "next_index": 0,
        "skips_used": 0,
        "skip_limit": SKIP_LIMIT,
        "unlocked_mission": False,
        "events": [],
        # P3: §5.3 ability_delta 的"前"快照 (复盘时与画像现值做差).
        "ability_before": dict(ability_before) if ability_before else None,
        "mission": {},
        "stage": "briefing",
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


def _doc_of(row: PracticeSession) -> dict[str, Any]:
    """读出快照的**私有深拷贝**, 并保证最小骨架 (坏快照 = 500, 不拿默认值继续跑).

    为什么非 deepcopy 不可: ``JSON`` 列没有就地变更追踪, 而 SQLAlchemy 赋值时会用 ``==``
    比较新旧值 —— 直接改 ``row.doc`` 内部再把等值内容塞回去, 变更历史是空的, UPDATE 根本
    不会带上 doc 列 (踩过: revision 涨了, 快照却还是旧的). 所以纪律是**读时拷一份、
    改完由 :func:`_save_doc` 整体写回**.
    """
    raw: Any = row.doc
    doc: dict[str, Any] = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        logger.error("session doc snapshot unusable | session={} keys={}", row.id, sorted(doc))
        raise AppError(500, f"session {row.id} has no briefing snapshot", "SESSION_DOC_CORRUPT")
    doc["steps"] = [step for step in steps if isinstance(step, dict)]
    doc.setdefault("skip_limit", SKIP_LIMIT)
    return doc


def _peek_doc(row: PracticeSession) -> dict[str, Any]:
    """只读取快照 (不校验、不抛): 列表摘要这种"能给多少给多少"的场景用."""
    raw: Any = row.doc
    return cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}


def _sub_doc(doc: dict[str, Any], key: str) -> dict[str, Any]:
    raw: Any = doc.get(key)
    return cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}


def _sub_docs(doc: dict[str, Any], key: str) -> list[Any]:
    raw = doc.get(key)
    return raw if isinstance(raw, list) else []


def _reconcile_stage(doc: dict[str, Any]) -> dict[str, Any]:
    """幂等地把 ``stage`` / ``next_index`` / ``unlocked_mission`` 与步骤清单对齐.

    P2 的通关口径 (计划 §5.4, 刻意保持简单): **清单里每一步都 passed 或 skipped 就解锁
    实战**; 单步只有 60 分门槛 + 最多 2 次人工跳过, 没有别的门禁. 做成幂等自愈是因为崩溃
    可能卡在"steps 写进去了、stage 没写"的中间态 —— 下次读快照就会算对.
    """
    steps = cast("list[dict[str, Any]]", doc["steps"])
    for step in steps:
        step["status"] = _status_of(step.get("status"))
    doc["unlocked_mission"] = bool(steps) and all(step["status"] != "pending" for step in steps)
    doc["next_index"] = next(
        (int(step["index"]) for step in steps if step["status"] == "pending"),
        len(steps),
    )
    if doc["unlocked_mission"] and doc.get("stage") == "briefing":
        doc["stage"] = "mission"
    return doc


def _briefing_progress(doc: dict[str, Any]) -> BriefingProgress:
    steps = cast("list[dict[str, Any]]", doc["steps"])
    passed = sum(1 for step in steps if step["status"] == "passed")
    skipped = sum(1 for step in steps if step["status"] == "skipped")
    skip_limit = _as_int(doc.get("skip_limit")) or SKIP_LIMIT
    skips_used = _as_int(doc.get("skips_used"))
    next_step = next((step for step in steps if step["status"] == "pending"), None)
    return BriefingProgress(
        total=len(steps),
        done=passed + skipped,
        passed=passed,
        skipped=skipped,
        skips_used=skips_used,
        skip_limit=skip_limit,
        skips_remaining=max(0, skip_limit - skips_used),
        next_step_id=str(next_step["id"]) if next_step else None,
        unlocked_mission=bool(doc.get("unlocked_mission")),
        steps=[
            StepProgress(
                id=str(step["id"]),
                index=_as_int(step.get("index")),
                type=str(step["type"]),
                status=_status_of(step.get("status")),
                attempts=_as_int(step.get("attempts")),
                best_score=_as_float(step.get("best_score")),
                last_score=_as_float(step.get("last_score")),
                last_source=step.get("last_source"),
                last_grade=step.get("last_grade")
                if isinstance(step.get("last_grade"), dict)
                else None,
            )
            for step in steps
        ],
    )


def _course_of(doc: dict[str, Any]) -> SceneCourse:
    """从快照取整课内容 (``course`` 存的是 model_dump, 反解一次即可)."""
    raw = doc.get("course")
    if not isinstance(raw, dict):
        raise AppError(500, "session snapshot has no course", "SESSION_DOC_CORRUPT")
    try:
        return SceneCourse.model_validate(raw)
    except ValidationError as exc:
        logger.error("session course snapshot invalid | err={}", _truncate(str(exc)))
        raise AppError(500, "session course snapshot is invalid", "SESSION_DOC_CORRUPT") from exc


def _push_event(doc: dict[str, Any], kind: str, step_id: str, score: float | None) -> None:
    events = doc.get("events")
    if not isinstance(events, list):
        events = []
    events.append({"at": _iso(_now()), "kind": kind, "step_id": step_id, "score": score})
    doc["events"] = events[-_EVENTS_KEPT:]


# ====== 载入 / 归属 / 提交 ======


async def _get_or_create_user(db: AsyncSession, device_id: str) -> User:
    """Find or create the user row for this device (history.py / lessons.py 同款).

    并发下同一 device_id 可能被两个请求同时判成"不存在", 后写者撞唯一索引 -> 回滚后
    重读 (``history.py`` 已经踩过这个坑, 这里带上同样的兜底).
    """
    res = await db.execute(select(User).where(User.device_id == device_id))
    user = res.scalar_one_or_none()
    if user is None:
        candidate = User(device_id=device_id)
        db.add(candidate)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            res = await db.execute(select(User).where(User.device_id == device_id))
            user = res.scalar_one()
        else:
            user = candidate
    return user


async def _lookup_user(db: AsyncSession, identity: _Identity) -> User | None:
    """定位调用者, **不注册**: 找不到就是 ``None`` (由调用方决定 403 还是空列表).

    除 ``POST /sessions`` 外所有端点走这里 —— 不能让陌生人拿个新 device_id 来 GET
    一下就在库里生出用户行 (那等于给会话 id 枚举者发了张门票).
    """
    if not identity.device_id and not identity.user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    if identity.user_id:
        res = await db.execute(select(User).where(User.id == identity.user_id))
    else:
        res = await db.execute(select(User).where(User.device_id == cast(str, identity.device_id)))
    return res.scalar_one_or_none()


async def _resolve_user(db: AsyncSession, identity: _Identity) -> User:
    """**注册**入口 (只有 ``POST /sessions`` 用): 按 ``user_id`` 精确定位或按
    ``device_id`` 找/建. 建会话是 v2.0 里唯一会悄悄 upsert user 行的地方
    (与 ``POST /history`` 同口径); 两个身份都不给 = 400.
    """
    if not identity.device_id and not identity.user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    if identity.user_id:
        res = await db.execute(select(User).where(User.id == identity.user_id))
        user = res.scalar_one_or_none()
        if user is None:
            raise AppError(404, f"unknown user_id: {identity.user_id}", "USER_NOT_FOUND")
        return user
    return await _get_or_create_user(db, cast(str, identity.device_id))


def _check_owner(row: PracticeSession, user: User) -> None:
    """会话归属 = ``user_id``; 不同账号访问 -> 403 (设备 A 恢复不了设备 B 的局)."""
    if row.user_id != user.id:
        raise AppError(403, "this session belongs to another learner", "FORBIDDEN_SESSION")


async def _load_owned_session(
    db: AsyncSession,
    session_id: str,
    identity: _Identity,
    *,
    for_update: bool,
) -> PracticeSession:
    """按 id 取会话 + 验归属; ``for_update`` 时锁住这一行 (PG; sqlite 由乐观锁兜).

    ``.execution_options(populate_existing=True)`` 是乐观锁语义的一部分: 同一条请求里
    若身份缓存了旧快照, 重试时读到的还是内存里那份旧 doc, 第二次照样输掉竞争.
    """
    stmt: Select[tuple[PracticeSession]] = (
        select(PracticeSession)
        .where(PracticeSession.id == session_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError(404, f"session {session_id} not found", "SESSION_NOT_FOUND")
    user = await _lookup_user(db, identity)
    if user is None:
        # 没注册过的调用者一律 403 (而不是顺手建个用户), 归属判定才是可信的
        raise AppError(403, "this session belongs to another learner", "FORBIDDEN_SESSION")
    _check_owner(row, user)
    return row


async def _save_doc(db: AsyncSession, row: PracticeSession, doc: dict[str, Any]) -> int:
    """写回快照 (乐观锁 + 冗余列同步), 返回落库后的 ``revision``.

    JSON 列必须整体换新对象, SQLAlchemy 才会把它算成脏数据进 UPDATE —— 原地改
    ``row.doc[...]`` 是静默无效的经典坑, 所以这里 deepcopy 与调用方的局部 dict 隔离.
    """
    # 先把身份与状态捕获成普通值: commit 失败回滚后 ORM 对象会过期, 那时再读 row.id
    # 会触发一次同步刷新 -> async 上下文里直接 MissingGreenlet (踩过).
    session_id = str(row.id)
    fallback_stage, fallback_status = row.stage, row.status
    doc["updated_at"] = _iso(_now())
    row.doc = copy.deepcopy(doc)
    row.stage = str(doc.get("stage") or fallback_stage)
    row.status = str(doc.get("status") or fallback_status)
    row.last_active_at = _now()
    row.updated_at = _now()
    try:
        await db.commit()
    except StaleDataError as exc:
        # 后落库者: 本次插入的 practice_steps 行随事务一起回滚 -> 不会出现双推进.
        await db.rollback()
        logger.warning("session doc write lost the race | session={} err={}", session_id, exc)
        raise AppError(
            409,
            "this session was updated by another request; reload it via GET /sessions/{id}",
            "SESSION_CONCURRENT_UPDATE",
        ) from exc
    return row.revision


# ====== 状态机内部: 门禁 / 记分 / 落库 ======


def _require_actionable_step(
    row: PracticeSession,
    doc: dict[str, Any],
    step_id: str,
) -> dict[str, Any]:
    """这一步现在能不能提交? 不能就给**可区分**的 404/409.

    依次挡住: 会话已结束 (409 SESSION_NOT_ACTIVE) / 打基础已打完 (409 WRONG_STAGE) /
    清单里没这个 step (404 STEP_NOT_FOUND) / 已经做过或跳过 (409 STEP_ALREADY_DONE,
    这条同时是并发双提交的幂等门) / 跳步提交 (409 STEP_OUT_OF_ORDER).
    """
    if row.status != "active":
        raise AppError(409, f"session is {row.status}", "SESSION_NOT_ACTIVE")
    if str(doc.get("stage") or "briefing") != "briefing":
        raise AppError(
            409,
            "briefing is already finished; continue with the mission",
            "WRONG_STAGE",
        )
    steps = cast("list[dict[str, Any]]", doc["steps"])
    entry = next((step for step in steps if step["id"] == step_id), None)
    if entry is None:
        raise AppError(404, f"unknown step_id {step_id} for this session", "STEP_NOT_FOUND")
    if entry["status"] != "pending":
        raise AppError(409, f"step {step_id} is already {entry['status']}", "STEP_ALREADY_DONE")
    next_index = _as_int(doc.get("next_index"))
    if _as_int(entry["index"]) != next_index:
        expected = steps[next_index]["id"] if next_index < len(steps) else None
        raise AppError(
            409,
            f"step order violated: finish step {expected} before {step_id}",
            "STEP_OUT_OF_ORDER",
        )
    return entry


def _step_content(course: SceneCourse, entry: dict[str, Any]) -> FoundationStep:
    """清单条目 -> 课程内容里的 :class:`FoundationStep` (按 id 找, 不按下标)."""
    for step in course.briefing:
        if step.id == entry["id"]:
            return step
    raise AppError(404, f"step {entry['id']} is missing from the course", "STEP_NOT_FOUND")


def _apply_grade(
    doc: dict[str, Any],
    entry: dict[str, Any],
    grade: DrillGrade,
    attempt: int,
) -> None:
    """把一次评分作用到内存 doc 上 (提交失败整体回滚 -> 不会出现半推进)."""
    entry["attempts"] = attempt
    entry["last_score"] = grade.score
    entry["last_source"] = grade.source
    best = _as_float(entry.get("best_score"))
    entry["best_score"] = grade.score if best is None else max(best, grade.score)
    entry["last_grade"] = grade.model_dump(mode="json")
    if grade.passed:
        entry["status"] = "passed"
        _push_event(doc, "step_passed", grade.step_id, grade.score)
    else:
        # 没达标: 保持 pending, 学员可以再录一次 (attempts 已记下这次失败尝试).
        _push_event(doc, "step_failed", grade.step_id, grade.score)


def _add_step_row(
    db: AsyncSession,
    row: PracticeSession,
    entry: dict[str, Any],
    step: FoundationStep,
    grade: DrillGrade | None,
) -> None:
    """一次尝试 = ``practice_steps`` 一行 (与 doc 更新同一事务, 一起提交/回滚).

    ``grade=None`` 是人工跳过: 没有分数也没有转写, 只有 ``source="skip"`` + ``ok=True``.
    """
    common: dict[str, Any] = {
        "session_id": row.id,
        "user_id": row.user_id,
        "step_id": step.id,
        "step_index": _as_int(entry.get("index")),
        "step_type": step.type,
        "attempt": _as_int(entry.get("attempts")) or 1,
    }
    if grade is None:
        db.add(PracticeStep(**common, source=SKIP_SOURCE, ok=True))
        return
    db.add(
        PracticeStep(
            **common,
            transcript=grade.transcript,
            score_total=grade.score,
            score_pronunciation=grade.pronunciation,
            score_fluency=grade.fluency,
            score_completeness=grade.completeness,
            score_grammar=grade.grammar,
            score_vocabulary=grade.vocabulary,
            ise_ref_mode=grade.ise_ref_mode,
            annotated_json={
                "word_details": [w.model_dump(mode="json") for w in grade.word_details],
                "key_points_hit": grade.key_points_hit,
                "mistakes": [m.model_dump(mode="json") for m in grade.mistakes],
                "feedback_cn": grade.feedback_cn,
                "pass_score": grade.pass_score,
            },
            speech_rate_wpm=grade.speech_rate_wpm,
            source=grade.source,
            llm_source=grade.llm_source,
            ok=grade.passed,
        )
    )


def _skipped_grade(step: FoundationStep) -> DrillGrade:
    """``/skip-step`` 的返回体: 分数无意 (0 + ``source="stub"``), 事实是清单里 skipped."""
    return DrillGrade(
        step_id=step.id,
        step_type=step.type,
        score=0.0,
        passed=True,
        pass_score=PASS_SCORE,
        feedback_cn="已跳过这一步 (每场最多跳 2 步)。",
        source="stub",
        llm_source=SKIP_SOURCE,
    )


def _response(
    row: PracticeSession,
    revision: int,
    doc: dict[str, Any],
    grade: DrillGrade,
    events: list[AbilityEvidence],
) -> StepAttemptResponse:
    return StepAttemptResponse(
        session_id=row.id,
        revision=revision,
        stage=row.stage,
        status=row.status,
        grade=grade,
        briefing=_briefing_progress(doc),
        unlocked_mission=bool(doc.get("unlocked_mission")),
        ability_events=events,
    )


def _view(row: PracticeSession, course: SceneCourse) -> SessionView:
    doc = _reconcile_stage(_doc_of(row))
    review = doc.get("review")
    return SessionView(
        session_id=row.id,
        kind=row.kind,
        scene_id=row.scene_id,
        stage=row.stage,
        status=row.status,
        revision=row.revision,
        created_at=_iso(row.created_at),
        last_active_at=_iso(row.last_active_at),
        briefing=_briefing_progress(doc),
        mission=dict(doc.get("mission") or {}),
        review=dict(review) if isinstance(review, dict) else None,
        course=course,
    )


def _summary(row: PracticeSession) -> SessionSummary:
    """列表项: 只从快照里摘标题与进度, 不反解整课 (列表要轻)."""
    doc = _peek_doc(row)
    course = _sub_doc(doc, "course")
    steps = [step for step in _sub_docs(doc, "steps") if isinstance(step, dict)]
    return SessionSummary(
        session_id=row.id,
        kind=row.kind,
        scene_id=row.scene_id,
        stage=row.stage,
        status=row.status,
        title=str(course.get("title") or ""),
        level=str(course.get("level") or ""),
        done_steps=sum(1 for step in steps if step.get("status") in ("passed", "skipped")),
        total_steps=len(steps),
        unlocked_mission=bool(doc.get("unlocked_mission")),
        last_active_at=_iso(row.last_active_at),
    )


# ====== 端点 ======


@router.post("/sessions", status_code=201, response_model=SessionView)
async def create_session(
    req: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionView:
    """开场: 建会话, 把整课内容快照进 doc, 返回打基础清单.

    P2 只支持 ``kind="scene_course"``: 课本模式仍走既有 ``/lessons`` + ``/score``,
    自由对话走 ``/dialogue``, 测评会话归 P4 —— 那些 kind 现在明确 400 拒掉, 免得客户端
    误以为已经能开.
    """
    if req.kind not in SUPPORTED_KINDS:
        raise AppError(
            400,
            f"kind {req.kind!r} is not supported yet (supported: {', '.join(SUPPORTED_KINDS)})",
            "SESSION_KIND_UNSUPPORTED",
        )
    if not req.scene_id:
        raise AppError(400, "scene_id is required for a scene_course session", "SCENE_ID_REQUIRED")
    user = await _resolve_user(db, req)
    course = scene_store.get_course(req.scene_id)
    if course is None:
        raise AppError(404, f"scene {req.scene_id} not found", "SCENE_NOT_FOUND")

    # §5.3 ability_delta 的"前"快照: 开局就把画像现状钉进 doc, 复盘时与现值做差.
    ability_before = (await ability_engine.get_snapshot(db, user.id)).snapshot()
    doc = _initial_doc(course, req.kind, ability_before)
    row = PracticeSession(
        user_id=user.id,
        kind=req.kind,
        scene_id=course.id,
        stage="briefing",
        status="active",
        owner_device_id=req.device_id or user.device_id,
        doc=doc,
    )
    db.add(row)
    await db.commit()
    logger.info(
        "practice session opened | session={} user={} scene={} steps={}",
        row.id,
        user.id,
        course.id,
        len(doc["steps"]),
    )
    return _view(row, course)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    status: str = Query(default="", max_length=16),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[SessionSummary]:
    """最近会话列表 (首页「继续学习」): 按 ``last_active_at`` 倒序, 走 M1 那个复合索引.

    ``status`` 可选过滤 (``active`` = 还没打完的那场). 只回摘要 —— 整课内容留给
    ``GET /sessions/{id}``.
    """
    user = await _lookup_user(db, _Identity(device_id=device_id, user_id=user_id))
    if user is None:  # 没注册过的 device: 一场都没有 (顺手建用户是 POST /sessions 的事)
        return []
    stmt: Select[tuple[PracticeSession]] = (
        select(PracticeSession)
        .where(PracticeSession.user_id == user.id)
        .order_by(PracticeSession.last_active_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(PracticeSession.status == status)
    rows = list((await db.execute(stmt)).scalars().all())
    return [_summary(row) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(
    session_id: str,
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> SessionView:
    """崩溃恢复快照: 进页先 GET, 按服务端状态机渲染, 客户端不自己推断进度.

    顺带做一次**投影自愈**: 快照派生出的 stage/status 与冗余列不一致时 (崩在两步之间),
    把列修回与 doc 一致再返回 —— 客户端永远看不到"清单打完了但 stage 还是 briefing"。
    """
    row = await _load_owned_session(
        db,
        session_id,
        _Identity(device_id=device_id, user_id=user_id),
        for_update=False,
    )
    doc = _reconcile_stage(_doc_of(row))
    if doc.get("stage") != row.stage or doc.get("status") != row.status:
        logger.warning(
            "session projection drifted, self-healing | session={} column_stage={} doc_stage={}",
            row.id,
            row.stage,
            doc.get("stage"),
        )
        await _save_doc(db, row, doc)
    return _view(row, _course_of(doc))


@router.post("/sessions/{session_id}/step", response_model=StepAttemptResponse)
async def submit_step(
    session_id: str,
    req: StepAttemptRequest,
    db: AsyncSession = Depends(get_db),
) -> StepAttemptResponse:
    """评一步并推进清单 (题型 -> 评分方式见 :mod:`app.services.drill_grader`).

    输入契约: ``read_along`` 必须带 ``audio_b64`` (送 ISE); 复述/翻译/造句给 ``text``,
    只给音频则走讯飞 IAT 转写 —— 缺 IAT 凭据时明确 400, 因为**没有转写就没有证据**,
    不拿占位分冒充一次口语作答.
    """
    row = await _load_owned_session(db, session_id, req, for_update=True)
    doc = _reconcile_stage(_doc_of(row))
    entry = _require_actionable_step(row, doc, req.step_id)
    step = _step_content(_course_of(doc), entry)

    # 取材交给评分器: 手敲文本优先, 只有音频则走 IAT 转写, 都没有 -> 400.
    grade = await grade_step(
        step=step,
        audio_bytes=decode_audio(req.audio_b64 or b""),
        answer_text=(req.text or "").strip(),
    )
    _apply_grade(doc, entry, grade, _as_int(entry.get("attempts")) + 1)
    _add_step_row(db, row, entry, step, grade)
    _reconcile_stage(doc)
    events = ability_evidence(grade)
    # §5.6 管线: 事件流水 + EWMA 画像与 doc/step 行**同一事务**提交 (输掉乐观锁
    # 时一起回滚, 不会留下半条证据).
    await record_step_evidence(
        db, user_id=row.user_id, session_id=row.id, step_id=step.id, evidence=events
    )
    revision = await _save_doc(db, row, doc)
    logger.info(
        "drill graded | session={} step={} type={} score={} passed={} source={} llm={}",
        row.id,
        step.id,
        step.type,
        grade.score,
        grade.passed,
        grade.source,
        grade.llm_source,
    )
    return _response(row, revision, doc, grade, events)


@router.post("/sessions/{session_id}/skip-step", response_model=StepAttemptResponse)
async def skip_step(
    session_id: str,
    req: SkipStepRequest,
    db: AsyncSession = Depends(get_db),
) -> StepAttemptResponse:
    """人工跳过一步 (每场最多 2 次): 给"这题今天就是开不了口"的学员一条出路.

    跳过同样落一行 ``practice_steps`` (``source="skip"``, ``ok=True``, 分数全 NULL):
    它是"这一步不再阻塞"的审计记录, **不是评分证据** —— 画像管线按 source 门控它.
    """
    row = await _load_owned_session(db, session_id, req, for_update=True)
    doc = _reconcile_stage(_doc_of(row))
    entry = _require_actionable_step(row, doc, req.step_id)
    limit = _as_int(doc.get("skip_limit")) or SKIP_LIMIT
    used = _as_int(doc.get("skips_used"))
    if used >= limit:
        raise AppError(
            409,
            f"skip budget exhausted ({used}/{limit}); finish the remaining steps",
            "SKIP_LIMIT_REACHED",
        )
    step = _step_content(_course_of(doc), entry)

    entry["status"] = "skipped"
    entry["last_source"] = SKIP_SOURCE
    doc["skips_used"] = used + 1
    _push_event(doc, "step_skipped", step.id, None)
    _add_step_row(db, row, entry, step, None)
    _reconcile_stage(doc)
    revision = await _save_doc(db, row, doc)
    logger.info(
        "drill skipped | session={} step={} skips={}/{}",
        row.id,
        step.id,
        _as_int(doc.get("skips_used")),
        limit,
    )
    return _response(row, revision, doc, _skipped_grade(step), [])


# ============================================================ P3: 实战对话 (mission)
#
# 状态全部长在 doc["mission"] 里 (首轮懒初始化), 复用
# ``_load_owned_session(for_update=True)`` + ``_save_doc`` 这套序列 —— 乐观锁与
# 回滚纪律和 /step 完全一致。每轮**恰好一次** LLM 综合调用 (§5.5-2: 人设回复 +
# 提示 + 润色 + 语法/词汇判分 + 任务累积重判一个 JSON), 判分模型为服务端默认,
# 客户端不能选 (§四 决策表 / T3 先例); LLM 不可用退回剧本回放的确定性降级,
# ``source="heuristic"`` + ``llm_source="stub"``, 画像按 §5.6 门控不吃降级证据。


def _initial_mission(course: SceneCourse) -> dict[str, Any]:
    """首轮 `/mission` 时的 mission 分区 (清单状态全 pending, 开场白直接回剧本)."""
    return {
        "v": 1,
        "opening": {"a": course.mission.opening_a, "a_cn": course.mission.opening_a_cn},
        "turns": [],
        "tasks": mission_engine.initial_task_states(course.mission.tasks),
        "turn_count": 0,
        "max_turns": course.mission.max_turns,
        "cleared": False,
        "auto_finished": False,
        "finished": False,
        "hints_used": 0,
        "pending_costs": 0,
        "started_at": _iso(_now()),
    }


def _require_mission_actionable(row: PracticeSession, doc: dict[str, Any]) -> None:
    """实战门禁 (与 /step 的门禁**可区分**): 打完基础才能开局, 收工后一律 409.

    ``_reconcile_stage`` 已保证: briefing 清单跑完 -> ``stage`` 自动翻 ``mission``,
    所以这里 stage 还是 briefing 就意味着清单没走完 (409 WRONG_STAGE)。
    """
    if row.status != "active":
        raise AppError(409, f"session is {row.status}", "SESSION_NOT_ACTIVE")
    stage = str(doc.get("stage") or "briefing")
    if stage == "briefing":
        raise AppError(
            409,
            "finish the briefing checklist before starting the mission",
            "WRONG_STAGE",
        )
    if stage in ("review", "done"):
        raise AppError(409, "this session already went to review", "MISSION_FINISHED")
    mission = _sub_doc(doc, "mission")
    if bool(mission.get("finished")):
        raise AppError(409, "the mission was already finished", "MISSION_FINISHED")


def _add_mission_step_row(
    db: AsyncSession,
    row: PracticeSession,
    entry: dict[str, Any],
    turn_index: int,
) -> None:
    """实战一轮 = 一行 ``practice_steps`` (step_type=``mission_turn``).

    分数列按维度**稀疏**落: 没证据的维度留 NULL (§5.6 前提). ``ok`` 记"本轮是否
    新完成了任务" —— 实战轮的"达标"事实是沟通推进, 不是分数。
    """
    sub = entry.get("sub_scores") or {}
    total = [v for v in sub.values() if isinstance(v, (int, float))]
    db.add(
        PracticeStep(
            session_id=row.id,
            user_id=row.user_id,
            step_id=f"m{turn_index}",
            step_index=turn_index,
            step_type="mission_turn",
            attempt=1,
            transcript=entry.get("user_text"),
            score_total=round(sum(total) / len(total), 1) if total else None,
            score_pronunciation=sub.get("pronunciation"),
            score_fluency=sub.get("fluency"),
            score_grammar=sub.get("grammar"),
            score_vocabulary=sub.get("vocabulary"),
            ise_ref_mode=entry.get("ise_ref_mode"),
            annotated_json={
                "reply": entry.get("reply"),
                "suggestion": entry.get("suggestion"),
                "polish": entry.get("polish"),
                "newly_done": entry.get("newly_done"),
                "tasks_done": entry.get("tasks_done"),
                "word_details": entry.get("word_details"),
                "costs_score": entry.get("costs_score"),
                "hinted": entry.get("costs_score"),
                "ise_source": entry.get("ise_source"),
            },
            speech_rate_wpm=entry.get("speech_rate_wpm"),
            source=str(entry.get("source") or "heuristic"),
            llm_source=entry.get("llm_source"),
            ok=bool(entry.get("newly_done")),
        )
    )


async def _finish_mission_state(
    db: AsyncSession,
    row: PracticeSession,
    doc: dict[str, Any],
    course: SceneCourse,
    mission: dict[str, Any],
    *,
    auto: bool,
) -> ReviewReport:
    """收工: 生成 ReviewReport、落 ``doc["review"]``、投影 ``review/completed``、写历史行.

    调用方负责 ``_save_doc`` 提交; 这里所有 ``db.add`` / flush 都留在同一事务里
    (报告聚合需要刚写入的 step/事件行, 所以先 flush 再 SELECT)。
    """
    mission["finished"] = True
    if auto:
        mission["auto_finished"] = True
    await db.flush()
    step_rows = (
        (
            await db.execute(
                select(PracticeStep)
                .where(PracticeStep.session_id == row.id)
                .order_by(PracticeStep.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    steps: list[dict[str, Any]] = [
        {
            "step_id": step.step_id,
            "step_type": step.step_type,
            "transcript": step.transcript,
            "score_total": step.score_total,
            "score_pronunciation": step.score_pronunciation,
            "score_fluency": step.score_fluency,
            "score_completeness": step.score_completeness,
            "score_grammar": step.score_grammar,
            "score_vocabulary": step.score_vocabulary,
            "ise_ref_mode": step.ise_ref_mode,
            "annotated_json": step.annotated_json,
            "source": step.source,
            "llm_source": step.llm_source,
            "ok": step.ok,
        }
        for step in step_rows
    ]
    after = await ability_engine.get_snapshot(db, row.user_id)
    before_raw = doc.get("ability_before")
    briefing_done = all(
        str(step.get("status")) == "passed" for step in cast("list[dict[str, Any]]", doc["steps"])
    ) and bool(doc["steps"])
    report = await mission_engine.build_review_report(
        course=course,
        session_id=row.id,
        mission=mission,
        steps=steps,
        ability_before=cast("dict[str, float | None] | None", before_raw)
        if isinstance(before_raw, dict)
        else None,
        ability_after=after.snapshot(),
        briefing_passed=briefing_done,
        hints_used=_as_int(mission.get("hints_used")),
    )
    doc["review"] = report.model_dump(mode="json")
    doc["stage"] = "review"
    doc["status"] = "completed"
    _push_event(doc, "mission_review" + ("_auto" if auto else ""), "", report.overall)
    _add_history_row(db, row, course, report)
    return report


def _add_history_row(
    db: AsyncSession, row: PracticeSession, course: SceneCourse, report: ReviewReport
) -> None:
    """通关总结落 ``history`` (kind=scene_course): 老历史页零改动也能渲染.

    形状与 ``HistoryWriteRequest`` 完全同构: 分数列 NOT NULL, 没测的维度补 0.0
    (UI 不显示该维度即可, 别当成真分数); ``lesson_id`` 复用 ``scene_store`` 的稳定
    散列 —— 与 /scenes/{id}/script 的课号同源, 同一门课的多场收工在老界面里按
    (book="scenes", lesson_id) 聚合成"多次尝试"。P8 的 kind/label 化改造拿
    book + line_id (=session id) 反解标题。
    """
    dims = report.dims
    subs = report.pronunciation_subs
    db.add(
        History(
            user_id=row.user_id,
            book=scene_store.SCRIPT_BOOK,
            lesson_id=scene_store.script_lesson_no(course.id),
            line_id=row.id,
            audio_path=course.id,
            score_total=report.overall or 0.0,
            score_pronunciation=subs.get("pronunciation") or dims.get("pronunciation") or 0.0,
            score_fluency=subs.get("fluency") or dims.get("fluency") or 0.0,
            score_completeness=subs.get("completeness") or 0.0,
        )
    )


@router.post("/sessions/{session_id}/mission", response_model=MissionTurnResponse)
async def submit_mission_turn(
    session_id: str,
    req: MissionTurnRequest,
    db: AsyncSession = Depends(get_db),
) -> MissionTurnResponse:
    """实战对话的一轮 (§5.3: 客户端发 ``audio_b64`` 或 ``text``, 状态在服务端).

    流程: 门禁 -> (音频则 IAT 转写, 转不出 = 400 TRANSCRIPT_UNAVAILABLE: 没有转写
    就没有证据) -> (有真音频且讯飞已配置则**转写锚定 ISE**, 产出
    ``transcript_anchored`` 发音/流利证据) -> **单次**综合 LLM 调用 (回复/提示/
    润色/语法词汇/任务累积重判) -> 服务端累积合并任务状态 -> 落 step 行 + §5.6
    维度证据 -> 到 ``max_turns`` 自动收工 (报告随本响应返回) -> 一次提交.
    """
    row = await _load_owned_session(db, session_id, req, for_update=True)
    doc = _reconcile_stage(_doc_of(row))
    _require_mission_actionable(row, doc)
    course = _course_of(doc)
    mission_raw = doc.get("mission")
    mission: dict[str, Any] = (
        mission_raw if isinstance(mission_raw, dict) and mission_raw else _initial_mission(course)
    )
    doc["mission"] = mission  # 懒初始化也要回到快照 (整体写回的老纪律)

    audio_bytes = decode_audio(req.audio_b64 or b"")
    user_text = (req.text or "").strip()
    input_kind = "text"
    if not user_text:
        if not audio_bytes:
            raise AppError(
                400,
                "mission turn needs audio_b64 or text",
                "MISSION_INPUT_REQUIRED",
            )
        transcript = (await transcribe_audio(audio_bytes) or "").strip()
        if not transcript:
            raise AppError(
                400,
                "音频无法转写 (讯飞 IAT 未配置), 请改用 text 作答",
                "TRANSCRIPT_UNAVAILABLE",
            )
        user_text = transcript[:ANSWER_MAX_CHARS]
        input_kind = "iat"

    tasks_state = cast("list[dict[str, Any]]", mission.get("tasks") or [])
    turns = cast("list[dict[str, Any]]", mission.get("turns") or [])
    turn_index = _as_int(mission.get("turn_count")) + 1

    # 自由产出的发音证据 (转写锚定 ISE; 没配讯飞 -> None, 绝不拿回声 95 分冒充):
    anchored = await mission_engine.anchored_pronunciation(audio_bytes, user_text)
    judgement, score_source, llm_source = await mission_engine.judge_turn(
        course, tasks_state, turns, user_text, turn_index
    )
    newly_done_raw = mission_engine.merge_task_progress(
        tasks_state, judgement.task_progress, turn_index=turn_index
    )
    mission["cleared"] = mission_engine.all_required_done(tasks_state)
    costs_score = _as_int(mission.get("pending_costs")) > 0
    if costs_score:
        mission["pending_costs"] = _as_int(mission.get("pending_costs")) - 1

    events = mission_engine.turn_ability_events(judgement, anchored, score_source=score_source)
    sub_scores: dict[str, float | None] = {
        "pronunciation": anchored.pronunciation if anchored else None,
        "grammar": judgement.grammar_score,
        "vocabulary": judgement.vocabulary_score,
        "fluency": anchored.fluency if anchored else None,
    }
    turn_entry: dict[str, Any] = {
        "index": turn_index,
        "at": _iso(_now()),
        "user_text": user_text,
        "input": input_kind,
        "reply": judgement.reply,
        "suggestion": judgement.suggestion,
        "polish": judgement.polish.model_dump(mode="json") if judgement.polish else None,
        "sub_scores": sub_scores,
        "grammar_score": judgement.grammar_score,
        "vocabulary_score": judgement.vocabulary_score,
        "ise_ref_mode": "transcript_anchored" if anchored else None,
        "ise_source": "xunfei" if anchored else None,
        "speech_rate_wpm": anchored.speech_rate_wpm if anchored else None,
        "word_details": (
            [w.model_dump(mode="json") for w in anchored.word_details] if anchored else []
        ),
        "newly_done": newly_done_raw,
        "tasks_done": [str(t["id"]) for t in tasks_state if t.get("done")],
        "source": score_source,
        "llm_source": llm_source,
        "costs_score": costs_score,
    }
    mission["turns"] = [*turns, turn_entry]
    mission["turn_count"] = turn_index
    _push_event(doc, "mission_turn", f"m{turn_index}", judgement.grammar_score)
    if judgement.polish is not None:
        mission_engine.record_annotated_diff(
            db,
            row.user_id,
            polish=judgement.polish,
            origin="mission",
            session_id=row.id,
            step_id=f"m{turn_index}",
            scene_id=course.id,
            llm_source=llm_source,
        )
    _add_mission_step_row(db, row, turn_entry, turn_index)
    await record_step_evidence(
        db,
        user_id=row.user_id,
        session_id=row.id,
        step_id=f"m{turn_index}",
        evidence=events,
    )

    report: ReviewReport | None = None
    # 到回合上限 -> 服务端自动收工 (§5.1 max_turns: "到顶仍未集齐必选任务则按未通关
    # 收口"), 报告随本响应一并返回, 客户端不用再打一次 finish-mission.
    if turn_index >= _as_int(mission.get("max_turns")):
        report = await _finish_mission_state(db, row, doc, course, mission, auto=True)
    revision = await _save_doc(db, row, doc)
    logger.info(
        "mission turn graded | session={} turn={} source={} llm={} newly_done={} cleared={}",
        row.id,
        turn_index,
        score_source,
        llm_source,
        len(newly_done_raw),
        bool(mission["cleared"]),
    )
    return MissionTurnResponse(
        session_id=row.id,
        revision=revision,
        stage=row.stage,
        status=row.status,
        turn_index=turn_index,
        transcript=user_text,
        reply=judgement.reply,
        suggestion=judgement.suggestion,
        polish=judgement.polish,
        sub_scores=sub_scores,
        word_details=list(anchored.word_details) if anchored else [],
        speech_rate_wpm=anchored.speech_rate_wpm if anchored else None,
        newly_done=[NewlyDoneTask.model_validate(item) for item in newly_done_raw],
        checklist=mission_engine.task_views(tasks_state),
        cleared=bool(mission["cleared"]),
        turn_count=turn_index,
        max_turns=_as_int(mission.get("max_turns")),
        auto_finished=bool(mission.get("auto_finished")),
        finished=bool(mission.get("finished")),
        ability_events=events,
        source=score_source,
        llm_source=llm_source,
        costs_score=costs_score,
        review=report,
    )


@router.post("/sessions/{session_id}/hint", response_model=HintResponse)
async def request_hint(
    session_id: str,
    req: HintRequest,
    db: AsyncSession = Depends(get_db),
) -> HintResponse:
    """要提示 (§5.3): 不调 LLM、不改变任务判定, 只是**标记下一个判定回合**."""
    row = await _load_owned_session(db, session_id, req, for_update=True)
    doc = _reconcile_stage(_doc_of(row))
    _require_mission_actionable(row, doc)
    course = _course_of(doc)
    mission = _sub_doc(doc, "mission")
    if not mission:
        mission = _initial_mission(course)
    tasks_state = cast("list[dict[str, Any]]", mission.get("tasks") or [])
    open_tasks = [entry for entry in tasks_state if not entry.get("done")]
    required_first = [entry for entry in open_tasks if entry.get("required")] or open_tasks
    if required_first:
        first = required_first[0]
        hint = MissionHintPayload(
            task_id=str(first["id"]),
            desc_cn=str(first.get("desc_cn") or ""),
            hint_en=str(first.get("hint_en") or ""),
            note_cn="先把这个沟通任务说出来。",
        )
    else:
        turns = cast("list[dict[str, Any]]", mission.get("turns") or [])
        script = course.mission.exchanges[len(turns) % len(course.mission.exchanges)]
        hint = MissionHintPayload(
            script_line=script.b,
            note_cn="任务都推进完了, 把对话自然收尾就行。",
        )
    mission["hints_used"] = _as_int(mission.get("hints_used")) + 1
    mission["pending_costs"] = _as_int(mission.get("pending_costs")) + 1
    doc["mission"] = mission
    _push_event(doc, "mission_hint", "", None)
    revision = await _save_doc(db, row, doc)
    return HintResponse(
        session_id=row.id,
        revision=revision,
        stage=row.stage,
        status=row.status,
        hint=hint,
        costs_score=True,
        hints_used=_as_int(mission.get("hints_used")),
    )


@router.post("/sessions/{session_id}/finish-mission", response_model=FinishMissionResponse)
async def finish_mission(
    session_id: str,
    req: FinishMissionRequest,
    db: AsyncSession = Depends(get_db),
) -> FinishMissionResponse:
    """主动收工 -> ReviewReport (§5.3)."""
    row = await _load_owned_session(db, session_id, req, for_update=True)
    doc = _reconcile_stage(_doc_of(row))
    _require_mission_actionable(row, doc)
    course = _course_of(doc)
    mission_raw = doc.get("mission")
    mission: dict[str, Any] = (
        mission_raw if isinstance(mission_raw, dict) and mission_raw else _initial_mission(course)
    )
    report = await _finish_mission_state(db, row, doc, course, mission, auto=False)
    revision = await _save_doc(db, row, doc)
    logger.info(
        "mission finished | session={} cleared={} overall={} source={}",
        row.id,
        report.cleared,
        report.overall,
        report.source,
    )
    return FinishMissionResponse(
        session_id=row.id,
        revision=revision,
        stage=row.stage,
        status=row.status,
        report=report,
    )
