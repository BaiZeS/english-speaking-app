"""v3.0 会话线程端点: 微信式「一个场景一条会话」的服务端落点.

方案 S2.3。为什么要有这张表: 旧的 ``/dialogue/turn`` 无状态, 历史由客户端攒
``history[]`` 回传 —— 于是"回到这个场景接着聊"根本没有实现基础, 而 v2.3.1 换了签名
证书、要求存量设备**卸载重装**, 装回来聊天就断了。

归属口径与 ``dialogue_scenes``/``scene_courses`` 一致: **信任声明 device 即所有权**
(本仓 ``/dialogue/*`` 从来没有鉴权, 这不是本批引入的)。别人的行与不存在的行给同一个
404, 不泄露存在性。
"""

from __future__ import annotations

from typing import Any, NoReturn
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.api.v1.dialogue import _resolve_scene
from app.core.errors import AppError
from app.models.db import DialogueThread, User
from app.services import thread_audio, thread_store, users
from app.services.dialogue_scenes import DialogueScene

router = APIRouter(tags=["dialogue"])


# ====== DTO ======


class ThreadGrade(BaseModel):
    """一颗评分卡的内容; ``status=pending`` 时其余字段是占位。"""

    status: str = ""
    score: int = 0
    #: 四维 (切题/信息量/得体/推进) + 说英文时的 pronunciation。**缺轴 = 这一轮没这个证据**,
    #: 客户端整行不渲染 —— 不许用 0 分冒充"没测到" (同 ``practice_steps`` 的分数列口径)。
    axes: dict[str, float] = Field(default_factory=dict)
    comment: str = ""
    comment_cn: str = ""


class ThreadMessage(BaseModel):
    id: str
    #: line | hint | grade | user
    kind: str
    role_id: str = ""
    text: str = ""
    text_cn: str = ""
    #: **绝对 URL** (与 ``/tts`` 一致): 客户端 Retrofit base 是 ``/api/v1/``,
    #: 相对 ``/static/...`` 会拼错。
    audio_url: str | None = None
    audio_ms: int = 0
    #: true = 请求内没合成出来, 客户端自己按需 ``GET /tts`` 兜底 (S2.5 软失败)。
    audio_pending: bool = False
    #: 学员这句是中文还是英文 (服务端从转写文本判, 不是学员声明的)。
    spoke: str = ""
    recognized_text: str = ""
    #: 本机录音文件名; 服务端**不存学员音频**, 回放走本地。
    local_recording: str = ""
    beat: str = ""
    grade: ThreadGrade | None = None
    at: str = ""


class ThreadView(BaseModel):
    id: str
    scene_id: str
    turn_count: int = 0
    grading_status: str = ""
    beat_index: int = 0
    messages: list[ThreadMessage] = Field(default_factory=list)


class ThreadSummary(BaseModel):
    """会话列表的一行 (头像/标题由客户端拿 ``GET /dialogue/scenes`` 的目录 join)。"""

    id: str
    scene_id: str
    preview: str = ""
    last_at: str = ""
    turn_count: int = 0
    unread: int = 0
    grading_status: str = ""


class ThreadCreateRequest(BaseModel):
    scene_key: str = Field(min_length=1, max_length=64)


class ThreadDeleted(BaseModel):
    deleted: bool = True
    id: str


# ====== 身份 ======


async def _require_user(
    db: AsyncSession,
    device_id: str | None,
    user_id: str | None,
) -> User:
    """线程一律要身份 (会话是个人数据, 没有"匿名共享一条聊天"这种东西)。"""
    if not device_id and not user_id:
        raise AppError(
            status_code=400,
            message="device_id or user_id is required for dialogue threads",
            code="IDENTITY_REQUIRED",
        )
    user = await users.lookup_user(db, device_id=device_id, user_id=user_id, create=True)
    if user is None:
        raise AppError(
            status_code=404, message=f"unknown user_id: {user_id}", code="USER_NOT_FOUND"
        )
    return user


def _thread_not_found(thread_id: str) -> NoReturn:
    raise AppError(
        status_code=404,
        message=f"dialogue thread {thread_id} not found",
        code="THREAD_NOT_FOUND",
    )


# ====== doc -> DTO ======


def _abs_audio(url: str | None, request: Request) -> str | None:
    return urljoin(str(request.base_url), url) if url else None


def _message_dto(raw: dict[str, Any], request: Request) -> ThreadMessage:
    grade_raw = raw.get("grade")
    grade = ThreadGrade(**grade_raw) if isinstance(grade_raw, dict) else None
    return ThreadMessage(
        id=str(raw.get("id") or ""),
        kind=str(raw.get("kind") or ""),
        role_id=str(raw.get("role_id") or ""),
        text=str(raw.get("text") or ""),
        text_cn=str(raw.get("text_cn") or ""),
        audio_url=_abs_audio(raw.get("audio_url"), request),
        audio_ms=int(raw.get("audio_ms") or 0),
        audio_pending=bool(raw.get("audio_pending")),
        spoke=str(raw.get("spoke") or ""),
        recognized_text=str(raw.get("recognized_text") or ""),
        local_recording=str(raw.get("local_recording") or ""),
        beat=str(raw.get("beat") or ""),
        grade=grade,
        at=str(raw.get("at") or ""),
    )


def _view(row: DialogueThread, request: Request) -> ThreadView:
    doc = thread_store.load_doc(row)
    return ThreadView(
        id=row.id,
        scene_id=row.scene_key,
        turn_count=row.turn_count,
        grading_status=row.grading_status,
        beat_index=int(doc.get("beat_index") or 0),
        messages=[_message_dto(m, request) for m in thread_store.messages_of(doc)],
    )


async def _load(db: AsyncSession, thread_id: str, user: User) -> DialogueThread:
    row = await thread_store.get_thread(db, thread_id, user.id)
    if row is None:
        _thread_not_found(thread_id)
    return row


# ====== Routes ======


@router.get("/dialogue/threads", response_model=list[ThreadSummary])
async def list_threads(
    request: Request,
    db: AsyncSession = Depends(get_db),
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> list[ThreadSummary]:
    """会话列表 (微信首页那一列), 最近活跃倒序。"""
    user = await _require_user(db, device_id, user_id)
    rows = await thread_store.list_threads(db, user.id)
    out: list[ThreadSummary] = []
    for row in rows:
        doc = thread_store.load_doc(row)
        messages = thread_store.messages_of(doc)
        out.append(
            ThreadSummary(
                id=row.id,
                scene_id=row.scene_key,
                preview=thread_store.last_message_preview(doc),
                last_at=str(messages[-1].get("at")) if messages else "",
                turn_count=row.turn_count,
                unread=thread_store.unread_role_lines(
                    doc, seen_seq=int(doc.get("last_read_seq") or 0)
                ),
                grading_status=row.grading_status,
            )
        )
    return out


@router.post("/dialogue/threads", response_model=ThreadView, status_code=201)
async def open_thread(
    req: ThreadCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> ThreadView:
    """打开一个场景的会话; **已存在就幂等返回既有那条**。

    首次进入把 ``openings`` 落成语音气泡并就地合成 (这一条请求里没有 LLM 调用,
    只有 TTS, 所以 25s 预算整条都归它)。合成不出来照样 201 —— 开场白没声音不是错误
    (S2.5 的软失败口径), 客户端按需 ``GET /tts`` 补。
    """
    user = await _require_user(db, device_id, user_id)
    scene = await _resolve_scene(db, req.scene_key, user)
    row, created = await thread_store.open_thread(db, user, scene)
    if created:
        doc = thread_store.load_doc(row)
        await _attach_opening_audio(doc, scene, request)
        await thread_store.save_doc(db, row, doc)
    return _view(row, request)


async def _attach_opening_audio(
    doc: dict[str, Any], scene: DialogueScene, request: Request
) -> None:
    """给开场白逐条补音频 URL (就地改传入的 doc; 失败只留 ``audio_pending``)。"""
    messages = doc.get("messages") or []
    for message in messages:
        if message.get("kind") != thread_store.KIND_LINE:
            continue
        role = scene.role_of(str(message.get("role_id") or ""))
        if role is None:
            continue
        audio = await thread_audio.synthesize_line(str(message.get("text") or ""), role.voice)
        message["audio_url"] = audio.audio_url
        message["audio_ms"] = audio.audio_ms
        message["audio_pending"] = audio.audio_pending


@router.get("/dialogue/threads/{thread_id}", response_model=ThreadView)
async def get_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> ThreadView:
    """全量消息 —— 也是**评分回填的读取面** (``grading_status`` 在顶层, 逐轮态在气泡里)。

    打开即把 ``last_read_seq`` 推到当前末尾: 红点的语义是"你没看过的角色台词",
    看了就该灭。
    """
    user = await _require_user(db, device_id, user_id)
    row = await _load(db, thread_id, user)
    doc = thread_store.load_doc(row)
    messages = doc.get("messages") or []
    last_seq = (
        int(messages[-1].get("id")[1:])
        if messages and str(messages[-1].get("id", ""))[1:].isdigit()
        else 0
    )
    if last_seq != int(doc.get("last_read_seq") or 0):
        doc["last_read_seq"] = last_seq
        await thread_store.save_doc(db, row, doc)
    return _view(row, request)


@router.delete("/dialogue/threads/{thread_id}", response_model=ThreadDeleted)
async def delete_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> ThreadDeleted:
    """删除会话 (微信长按删除)。只删这一条会话, 不动场景目录与自定义场景行。"""
    user = await _require_user(db, device_id, user_id)
    row = await _load(db, thread_id, user)
    await db.delete(row)
    await db.commit()
    return ThreadDeleted(id=thread_id)
