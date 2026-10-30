"""v3.0 会话线程端点: 微信式「一个场景一条会话」的服务端落点.

方案 S2.3。为什么要有这张表: 旧的 ``/dialogue/turn`` 无状态, 历史由客户端攒
``history[]`` 回传 —— 于是"回到这个场景接着聊"根本没有实现基础, 而 v2.3.1 换了签名
证书、要求存量设备**卸载重装**, 装回来聊天就断了。

归属口径与 ``dialogue_scenes``/``scene_courses`` 一致: **信任声明 device 即所有权**
(本仓 ``/dialogue/*`` 从来没有鉴权, 这不是本批引入的)。别人的行与不存在的行给同一个
404, 不泄露存在性。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any, NoReturn
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.api.v1.dialogue import _resolve_scene
from app.core.errors import AppError
from app.models.db import DialogueThread, User
from app.services import (
    mission_engine,
    thread_audio,
    thread_grading,
    thread_store,
    thread_turn,
)
from app.services import users as users_service
from app.services.dialogue_scenes import DialogueScene
from app.services.drill_grader import LlmUnavailableError, turn_generation_unavailable
from app.services.xunfei_iat import XunfeiIatProvider

router = APIRouter(tags=["dialogue"])

#: 听写只走这一条路: 讯飞 ``zh_cn`` 原生吃中英混读 (实测见方案 S2.4)。
_IAT_LANGUAGE = "zh_cn"
_iat = XunfeiIatProvider()

# ====== 时延预算 (与 tests/test_latency_budget.py 的求和表同批改) ======
#
# 这条请求里唯一的一次 LLM 是台词生成; 判分在后台作业 (S2.6), 发音分与它并行。
# 求和: IAT 8.0 + max(ISE 8.5, GEN 14.0) + TTS 3.0 = 25.0, 客户端 readTimeout 30
# 减 5.0 余量 = 25.0 —— **顶格零余量**, 任何一处放宽都必须同步削减他处。
IAT_TURN_BUDGET_S = 8.0
ISE_TURN_BUDGET_S = 8.5


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
    user = await users_service.lookup_user(db, device_id=device_id, user_id=user_id, create=True)
    if user is None:
        raise AppError(
            status_code=404, message=f"unknown user_id: {user_id}", code="USER_NOT_FOUND"
        )
    return user


async def _transcribe(audio_bytes: bytes) -> str:
    """语音 -> 文本; 超时/没配凭据/空结果一律回空串 (调用方据此 422, 不硬编一句)."""
    try:
        recognized = await asyncio.wait_for(
            _iat.transcribe(audio_bytes, language=_IAT_LANGUAGE), timeout=IAT_TURN_BUDGET_S
        )
    except TimeoutError:
        logger.warning("thread iat budget exceeded | budget_s={}", IAT_TURN_BUDGET_S)
        return ""
    return (recognized or "").strip()


async def _collect_pronunciation(task: asyncio.Task[Any] | None) -> Any:
    """收发音分的账: 没起跑就 None, 超时/失败也 None —— **没有发音证据 ≠ 0 分**."""
    if task is None:
        return None
    try:
        return await asyncio.wait_for(task, timeout=ISE_TURN_BUDGET_S)
    except TimeoutError:
        logger.warning("thread anchored ise budget exceeded | budget_s={}", ISE_TURN_BUDGET_S)
        task.cancel()
        return None
    except Exception as exc:
        logger.warning("thread anchored ise failed: {}: {}", type(exc).__name__, exc)
        return None


def _spawn_grading(thread_id: str, user_id: str) -> None:
    """把这一轮的判分交给后台作业 (S2.6) —— 请求内不等它。"""
    thread_grading.spawn_thread_grading(thread_id, user_id)


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
    last_seq = thread_store.last_seq(doc)
    if last_seq != int(doc.get("last_read_seq") or 0):
        doc["last_read_seq"] = last_seq
        await thread_store.save_doc(db, row, doc)
    _redispatch_if_stale(row, doc, user.id)
    return _view(row, request)


def _redispatch_if_stale(row: DialogueThread, doc: dict[str, Any], user_id: str) -> None:
    """挂着 ``pending`` 又没有作业在跑、且已过水位 -> 重派一次。

    进程重启后作业句柄 (活在进程内存里) 全没了, 而没有作业来翻这颗气泡, 它会永远停在
    「评分生成中…」。

    水位读**那颗评分卡自己的** ``at``, 不是 ``row.updated_at`` —— 后者会被"标已读"这类
    与内容无关的写刷新, 于是每打开一次聊天就把时钟拨回零点, 永远够不到水位。
    """
    if row.grading_status != thread_store.GRADING_PENDING or thread_grading.in_flight(row.id):
        return
    age = thread_store.pending_grade_age_s(doc)
    if age is None or age < thread_grading.REDISPATCH_AFTER_S:
        return
    logger.info("thread grading redispatch after watermark | thread={} age_s={:.0f}", row.id, age)
    thread_grading.spawn_thread_grading(row.id, user_id)


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


# ====== 一轮 ======


class TurnRequest(BaseModel):
    """学员这一句: 语音或文字二选一.

    **没有 ``lang`` 字段** —— 语音一律走讯飞 ``zh_cn`` 中英混读听写 (实测见方案 S2.4),
    学员说了中文还是英文由服务端**事后**从转写文本判, 判出来只决定一件事: 要不要跑
    英文逐词发音分。让学员在开口前先声明语言, 是把一个系统能自己做的事推给用户。
    """

    mode: str = Field(pattern="^(voice|text)$")
    audio_b64: str = ""
    text: str = Field(default="", max_length=1000)
    #: 本机录音文件名, 服务端**不存音频**、只回显, 供气泡回放本地文件。
    recording_ref: str = Field(default="", max_length=128)
    model_id: str | None = Field(default=None, max_length=64)


class TurnResponse(BaseModel):
    """这一轮写进会话的全部气泡 (学员那颗 + 台词 + 建议 + 评分占位)。"""

    thread_id: str
    turn_count: int
    grading_status: str
    beat_index: int
    #: 本轮新增的气泡, 顺序即上屏顺序。
    messages: list[ThreadMessage] = Field(default_factory=list)


def _decode_audio(b64: str) -> bytes:
    if not b64:
        return b""
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(
            status_code=422, message="audio_b64 is not valid base64", code="BAD_AUDIO"
        ) from exc


@router.post("/dialogue/threads/{thread_id}/turn", response_model=TurnResponse)
async def submit_turn(
    thread_id: str,
    req: TurnRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> TurnResponse:
    """提交一轮: 听写 -> 台词 (请求内合成语音条) -> 建议回答 -> 评分占位.

    三条不能含糊的口径:

    * **听不出来说话 = 不前进**: 语音模式转写为空 (没配讯飞 / 超时 / 真的没听清) 一律
      422 ``VOICE_TRANSCRIPTION_FAILED``, 会话一个气泡都不多 —— 让教练"回应一句不知道
      是什么的话"就是编造学员说过什么 (D5 同族)。文字模式是这里的逃生门。
    * **拿不到台词 = 503, 整轮不落库** (v2.3.0 的裁决): 不回放目录句、不写兜底气泡。
    * **语音条是快路**: 请求内合成不出来就 ``audio_pending=true``, 客户端按需 ``GET /tts``
      兜底 —— 台词都已经生成了, 绝不能因为没声音而失败。
    """
    user = await _require_user(db, device_id, user_id)
    row = await _load(db, thread_id, user)
    scene = await _resolve_scene(db, row.scene_key, user)

    if req.mode == "voice":
        audio_bytes = _decode_audio(req.audio_b64)
        if not audio_bytes:
            raise AppError(
                status_code=422, message="voice turn needs audio_b64", code="BAD_REQUEST"
            )
        recognized = await _transcribe(audio_bytes)
        if not recognized:
            raise AppError(
                status_code=422,
                message="speech could not be transcribed",
                code="VOICE_TRANSCRIPTION_FAILED",
            )
        learner_text = recognized
        spoke = thread_turn.detect_spoke(recognized)
    else:
        learner_text = req.text.strip()
        if not learner_text:
            raise AppError(status_code=422, message="text turn needs text", code="BAD_REQUEST")
        # 打字没有发音可评, 这一轮永远不出发音轴 (不是 0 分, 是整轴不渲染)。
        spoke = "zh" if thread_turn.contains_cjk(learner_text) else thread_turn.SPOKE_EN
        audio_bytes = b""

    # 发音分与台词生成互不依赖 -> 并行抢出来的只有 ISE 那 8.5s (求和见文件头)。
    ise_task: asyncio.Task[Any] | None = None
    if audio_bytes and spoke == thread_turn.SPOKE_EN:
        ise_task = asyncio.create_task(
            mission_engine.anchored_pronunciation(audio_bytes, learner_text)
        )

    doc = thread_store.load_doc(row)
    try:
        generation, _model = await mission_engine.generate_turn(
            thread_turn.turn_messages(scene, doc, learner_text), model_id=req.model_id
        )
    except LlmUnavailableError as exc:
        if ise_task is not None:
            ise_task.cancel()
        # D5: 这一轮**什么都没发生** —— 不 append、不 save, 会话回到提交前。
        raise turn_generation_unavailable() from exc

    role = thread_turn.resolve_speaker(scene, generation.speaker)
    audio = await thread_audio.synthesize_line(generation.reply, role.voice)
    pronunciation = await _collect_pronunciation(ise_task)

    added = thread_store.append_round(
        doc,
        scene,
        learner_text=learner_text,
        spoke=spoke,
        recording_ref=req.recording_ref,
        reply=generation.reply,
        reply_cn=generation.reply_cn,
        suggestion=generation.suggestion,
        suggestion_cn=generation.suggestion_cn,
        role_id=role.role_id,
        audio_url=audio.audio_url,
        audio_ms=audio.audio_ms,
        audio_pending=audio.audio_pending,
        pronunciation=pronunciation.pronunciation if pronunciation is not None else None,
    )
    doc["beat_index"] = thread_turn.beat_cursor_after(
        int(doc.get("beat_index") or 0), scene, generation.next_beat
    )
    doc["grading_status"] = thread_store.GRADING_PENDING

    row = await _persist_round(db, row, user.id, doc, added)
    _spawn_grading(row.id, user.id)

    return TurnResponse(
        thread_id=row.id,
        turn_count=row.turn_count,
        grading_status=thread_store.GRADING_PENDING,
        beat_index=int((row.doc or {}).get("beat_index") or 0),
        messages=[_message_dto(m, request) for m in added],
    )


async def _persist_round(
    db: AsyncSession,
    row: DialogueThread,
    user_id: str,
    doc: dict[str, Any],
    added: list[dict[str, Any]],
) -> DialogueThread:
    """写回这一轮; 撞乐观锁就**重读后只补自己那几颗气泡**, 绝不覆盖别人的回填.

    会撞车的另一方是评分作业: 它改的是**上一轮**那颗 grade 气泡。版本校验输掉说明
    我手上这份 doc 已经旧了, 拿它整份写回会把刚回填好的分数抹掉 —— 所以重试必须
    从新读出来的 doc 出发, 只追加本轮新增的气泡。
    """
    if await thread_store.save_doc(
        db, row, doc, turn_count=row.turn_count + 1, grading_status=thread_store.GRADING_PENDING
    ):
        return row

    fresh = await thread_store.get_thread(db, row.id, user_id)
    if fresh is None:
        _thread_not_found(row.id)
    merged = thread_store.load_doc(fresh)
    merged.setdefault("messages", []).extend(added)
    merged["beat_index"] = doc.get("beat_index") or 0
    merged["grading_status"] = thread_store.GRADING_PENDING
    if not await thread_store.save_doc(
        db,
        fresh,
        merged,
        turn_count=fresh.turn_count + 1,
        grading_status=thread_store.GRADING_PENDING,
    ):
        raise AppError(
            status_code=409,
            message="dialogue thread changed under this turn, retry",
            code="THREAD_CONCURRENT_UPDATE",
        )
    return fresh
