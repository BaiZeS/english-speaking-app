"""v3.0 会话线程: ``dialogue_threads.doc`` 的 schema 与读写收口.

设计口径 (方案 S2.3): **doc 是客户端渲染的唯一真相**。角色台词、学员那句话、
建议回答、评分卡全部是同一条消息流里的四种气泡 (``kind``), 客户端不需要为评分
另开一条数据面 —— 回填只是把同一颗气泡从 ``pending`` 重绘成 ``ready``。

本模块只做**纯数据形状 + DB 读写**, 不碰 LLM、不碰 TTS、不碰路由: 台词生成在
``mission_engine``, 编排在 ``api/v1/dialogue``。这样"消息长什么样"这件事只有一处定义。
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import StaleDataError

from app.models.db import DialogueThread, User
from app.services import dialogue_scenes

#: 角色台词气泡 (带语音条).
KIND_LINE = "line"
#: 「建议回答」气泡: 默认折叠, 开口前就能看.
KIND_HINT = "hint"
#: 评分卡气泡: 异步回填, pending 时占位.
KIND_GRADE = "grade"
#: 学员自己那句 (语音或文字).
KIND_USER = "user"

MESSAGE_KINDS: tuple[str, ...] = (KIND_LINE, KIND_HINT, KIND_GRADE, KIND_USER)

#: 顶层评分指针态. "" = 这一条线程从来没判过分.
GRADING_EMPTY = ""
GRADING_PENDING = "pending"
GRADING_READY = "ready"
GRADING_FAILED = "failed"
GRADING_STATUSES: tuple[str, ...] = (GRADING_EMPTY, GRADING_PENDING, GRADING_READY, GRADING_FAILED)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_doc(scene: dialogue_scenes.DialogueScene) -> dict[str, Any]:
    """开场文档: 把场景的开场白落成语音气泡.

    开场白**不合成音频**: 音频是 ``POST /dialogue/threads`` 在库里落行之后才做的事
    (合成要花钱花时间, 不能占着建会话这个事务)。这里只把文本与 ``audio_pending``
    摆好, 由开线程的那次请求补上 URL。
    """
    messages: list[dict[str, Any]] = []
    for line in scene.opening_lines:
        append_message(
            messages,
            scene,
            kind=KIND_LINE,
            role_id=line.role_id,
            text=line.text,
            text_cn=line.text_cn,
        )
    return {
        "scene_id": scene.id,
        #: 下一条消息的序号 —— 气泡 id 的单调来源 (v2.3.0 的重复 key 崩溃教训).
        "seq": len(messages),
        "messages": messages,
        #: 已经聊到的议程下标 (``scene.beats`` 的游标, 由台词生成的 next_beat 推进).
        "beat_index": 0,
    }


def append_message(
    messages: list[dict[str, Any]],
    scene: dialogue_scenes.DialogueScene,
    *,
    kind: str,
    role_id: str = "",
    text: str = "",
    text_cn: str = "",
    audio_url: str | None = None,
    audio_ms: int = 0,
    audio_pending: bool = False,
    spoke: str = "",
    recognized_text: str = "",
    local_recording: str = "",
    beat: str = "",
    grade: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """**就地追加**一颗气泡并返回它 —— 调用方不要再 ``append`` 返回值。

    (这里曾经同时做过两件事: ``new_doc`` 把返回值又 append 一遍, 于是开场白变成
    ``['m1','m1','m3','m3']`` —— 两颗 id 相同的气泡。列表 key 撞重复在 v2.3.0 崩过一次,
    所以"谁负责加进列表"必须只有一处。)

    ``role_id`` 只在 :data:`KIND_LINE` 上有意义, 且**必须**能在场景 roles 里命中 ——
    命中不了就是 bug (会画出一个没有头像没有音色的气泡), 这里直接抛, 不静默回落。
    """
    if kind == KIND_LINE and role_id and scene.role_of(role_id) is None:
        raise ValueError(f"unknown role_id {role_id!r} for scene {scene.id!r}")
    message: dict[str, Any] = {
        "id": f"m{len(messages) + 1}",
        "kind": kind,
        "role_id": role_id,
        "text": text,
        "text_cn": text_cn,
        "audio_url": audio_url,
        "audio_ms": audio_ms,
        "audio_pending": audio_pending,
        "spoke": spoke,
        "recognized_text": recognized_text,
        "local_recording": local_recording,
        "beat": beat,
        "grade": grade,
        "at": _now_iso(),
    }
    messages.append(message)
    return message


def messages_of(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return list(doc.get("messages") or [])


def last_message_preview(doc: dict[str, Any]) -> str:
    """会话列表那一行显示的文本 (微信取最后一条, 语音条也显示转写/原文)."""
    for message in reversed(messages_of(doc)):
        text = (
            str(message.get("recognized_text") or "").strip()
            or str(message.get("text") or "").strip()
        )
        if text:
            return text[:60]
    return ""


def unread_role_lines(doc: dict[str, Any], *, seen_seq: int) -> int:
    """``seen_seq`` 之后新增的角色台词条数 (会话列表红点)."""
    return sum(
        1
        for message in messages_of(doc)
        if message.get("kind") == KIND_LINE and _seq_of(message) > seen_seq
    )


def _seq_of(message: dict[str, Any]) -> int:
    raw = str(message.get("id") or "")
    return int(raw[1:]) if raw[1:].isdigit() else 0


def grading_status_of(doc: dict[str, Any]) -> str:
    return str(doc.get("grading_status") or GRADING_EMPTY)


def pending_grade_message(doc: dict[str, Any]) -> dict[str, Any] | None:
    """最后一条仍是 ``pending`` 的评分卡 (回填的目标), 没有就 ``None``."""
    for message in reversed(messages_of(doc)):
        grade = message.get("grade")
        if isinstance(grade, dict) and grade.get("status") == GRADING_PENDING:
            return message
    return None


# ====== DB ======


async def get_thread(db: AsyncSession, thread_id: str, user_id: str) -> DialogueThread | None:
    """按 id + 归属取线程; **别人的行与不存在的行给同一个答案** (None -> 404)."""
    row = await db.get(DialogueThread, thread_id)
    if row is None or row.user_id != user_id:
        return None
    return row


async def find_by_scene(db: AsyncSession, user_id: str, scene_key: str) -> DialogueThread | None:
    result = await db.execute(
        select(DialogueThread).where(
            DialogueThread.user_id == user_id, DialogueThread.scene_key == scene_key
        )
    )
    return result.scalar_one_or_none()


async def list_threads(db: AsyncSession, user_id: str) -> list[DialogueThread]:
    """会话列表: 最近活跃倒序. 空 doc 的行不显示预览但**不隐藏** (开过就该看得见)."""
    result = await db.execute(
        select(DialogueThread)
        .where(DialogueThread.user_id == user_id)
        .order_by(DialogueThread.updated_at.desc())
    )
    return list(result.scalars().all())


async def open_thread(
    db: AsyncSession, user: User, scene: dialogue_scenes.DialogueScene
) -> tuple[DialogueThread, bool]:
    """幂等开会话: 已存在返回既有行 (``created=False``), 不存在建一条.

    撞 ``(user_id, scene_key)`` 唯一索引 (同一用户并发点开同一场景) 时**回滚后重读**,
    不建第二行 —— 建了就有两条会话, 而"一个场景一条"正是这张表唯一索引的前提。
    """
    existing = await find_by_scene(db, user.id, scene.id)
    if existing is not None:
        return existing, False
    row = DialogueThread(
        user_id=user.id,
        scene_key=scene.id,
        doc=new_doc(scene),
        turn_count=0,
        grading_status=GRADING_EMPTY,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:  # 并发插入撞唯一索引
        await db.rollback()
        raced = await find_by_scene(db, user.id, scene.id)
        if raced is None:
            raise
        return raced, False
    await db.refresh(row)
    return row, True


def load_doc(row: DialogueThread) -> dict[str, Any]:
    """读 doc 的**唯一正确姿势**: 深拷贝出来再改.

    浅拷贝 (``dict(row.doc)``) 会让调用方就地改掉 ORM 里那份"旧值", 于是写回时
    新旧内容相等、SQLAlchemy 判定无变化、``doc`` 列**根本不进 UPDATE** —— 症状是
    "``turn_count`` 写进去了、消息却还是旧的", 半行更新比整行失败更难查。
    (同 ``models/db.py`` 里 ``dialogue_scenes.doc`` 那句"读要 deepcopy、写要整体换对象"
    是同一条坑, 这里把它做成不可绕过的入口。)
    """
    return copy.deepcopy(row.doc or {})


async def save_doc(
    db: AsyncSession,
    row: DialogueThread,
    doc: dict[str, Any],
    *,
    turn_count: int | None = None,
    grading_status: str | None = None,
) -> bool:
    """整体换对象写回 (配 :func:`load_doc` 用).

    返回 ``False`` = 乐观锁输了 (``revision`` 对不上, 别的事务已经改过这条线程)。
    调用方**必须**把它当"这一轮不生效"处理并重读, 不许静默覆盖: 评分作业回填与
    学员下一次提交会在同一行上撞车。
    """
    row.doc = copy.deepcopy(doc)
    # 显式标脏: 调用方若拿浅拷贝就地改了 ORM 里那份旧值, 新旧内容会相等而被跳过。
    flag_modified(row, "doc")
    row.updated_at = datetime.now(UTC)
    if turn_count is not None:
        row.turn_count = turn_count
    if grading_status is not None:
        row.grading_status = grading_status
    try:
        await db.commit()
    except StaleDataError:
        await db.rollback()
        return False
    return True
