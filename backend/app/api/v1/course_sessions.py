"""通关会话状态机端点 (计划 §5.3「通关会话状态机」+ §5.4, 阶段 P2).

情景课的学习闭环是 **打基础 (briefing) -> 实战对话 (mission) -> 复盘 (review)**.
本模块负责第一段的会话状态与 4 种题型的评分接线; 第二段的 ``/mission``、``/hint``、
``/finish-mission`` 归 P3 (T4), 接缝写在文件末尾的 EXTENSION POINT 注释里.

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
``GET  /sessions/{id}``           崩溃恢复快照
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
from app.models.db import PracticeSession, PracticeStep, User
from app.services import scene_store
from app.services.audio_input import decode_audio
from app.services.drill_grader import (
    ANSWER_MAX_CHARS,
    PASS_SCORE,
    SKIP_SOURCE,
    AbilityEvidence,
    DrillGrade,
    ability_evidence,
    grade_step,
    record_step_evidence,
)

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
    #: P3 起写内容 (turns / tasks_done / polish); P2 恒为空 dict, 字段先给出去.
    mission: dict[str, Any] = Field(default_factory=dict)
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
    #: §5.6 维度证据 (P2 只算不写: ability_events 表在 M2, EWMA 管线归 T4).
    ability_events: list[AbilityEvidence] = Field(default_factory=list)


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
#     "mission": { P3 写 },
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


def _initial_doc(course: SceneCourse, kind: str) -> dict[str, Any]:
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

    doc = _initial_doc(course, req.kind)
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
    revision = await _save_doc(db, row, doc)
    events = ability_evidence(grade)
    record_step_evidence(
        db, user_id=row.user_id, session_id=row.id, step_id=step.id, evidence=events
    )  # P3 的画像落库钩子 (T4 填实现); P2 什么都不写
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


# P3 EXTENSION POINT (T4 负责, 别再往别的 router 塞):
#   ``POST /sessions/{id}/mission`` + ``/hint`` + ``/finish-mission`` 挂本文件.
#   实战每轮的状态 (turns / tasks_done / polish 历史) 写进同一个 doc 的
#   ``doc["mission"]``, 复用 ``_load_owned_session(for_update=True)`` + ``_save_doc``
#   这套序列, 并发纪律不用重写; ``/step`` 在 stage 不是 briefing 时会自己 409
#   ``WRONG_STAGE``. ReviewReport 落 ``doc["review"]``, 并把 ``stage`` 推到 "review"、
#   ``status`` 收成 "completed" (之后的提交会被 ``SESSION_NOT_ACTIVE`` 挡住).
#   画像 EWMA 落库填 ``drill_grader.record_step_evidence()`` 这个空钩子.
