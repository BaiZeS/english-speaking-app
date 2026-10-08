"""Free dialogue (自由对话) endpoints.

Backend reads LLM credentials from environment (``LLM_BASE_URL`` / ``LLM_API_KEY``)
and, when configured, generates conversation turns via an OpenAI-compatible
provider (default: 阿里云百炼 Maas ``/compatible-mode/v1``).

The scene catalog itself lives in :mod:`app.services.dialogue_scenes` and is
exposed via ``GET /dialogue/scenes`` so the Android picker can render it.

v2.0 P3 扩展 (§5.5-4 / §5.6 / §5.7 / §四 魔法字符串):

* ``/dialogue/turn`` 的同一次调用带语法润色与判分;
* 带身份 (``device_id`` / ``user_id``) 时本轮证据写 §5.6 画像管线;
* 历史回填不再匹配魔法字符串: 协议层面"当前这句话 = 末尾的 user 回合 (内容待
  转写)", 老客户端的占位文本仍被接受 (向后兼容)。

§A4 (D1/D4/D5) 起这条路由**只做生成** —— 它与实战轮共用 :class:`TurnGeneration`
这一份五字段 schema (台词 + 双语 + 学员句的中文对照), 走
``mission_engine.generate_turn`` (即 ``drill_grader._judge`` 的唯一收口: 一次调用 +
坏 JSON 回喂一次 + ``LlmUnavailableError``; 温度 0.7 / 160 token / 关思考)。润色与
分数**不在**这里了 (那是请求内第二次调用, 12s + 14s 装不进 25s 契约): 学员要润色走
现成的 ``POST /polish`` (纯文本工具, 不进画像)。

拿不到台词 -> ``503 TURN_GENERATION_UNAVAILABLE`` (D5: 报错不前进)。**不再**有
"降级到目录里的下一句"那条路 —— 它连同 ``DialogueScene`` 上的两个兜底字段一起删了: 它们正是
"两轮之后永远同一句"的根因, 而且冒充了一次不存在的生成。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import time
from collections.abc import Sequence
from typing import Any, cast

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import User
from app.services import mission_engine, users
from app.services.ability_engine import record_step_evidence as ability_record
from app.services.dialogue_scenes import DialogueScene, get_scene, list_scenes
from app.services.drill_grader import (
    AbilityEvidence,
    LlmUnavailableError,
    turn_generation_unavailable,
)
from app.services.llm_provider import (
    LlmMessage,
    get_llm_provider,
    resolve_roleplay_model,
    resolve_server_default_model,
)
from app.services.mission_engine import Polish
from app.services.xunfei_iat import XunfeiIatProvider

router = APIRouter(tags=["dialogue"])
_iat = XunfeiIatProvider()

#: 语音轮硬预算 (OkHttp readTimeout=30s, android di/NetworkModule.kt:40): 每次语音
#: 调用服务层已由 settings.xunfei_{ise,iat}_timeout_s (8s) 硬顶, 这里再包一层防发帧
#: 走偏; 发音证据 (转写锚定 ISE) 与台词生成并行 (只依赖 transcript, 互不相干),
#: 最坏 iat(8) + max(ise 8.5, GEN 14) = 22 < 25 —— 台词那一半走
#: ``mission_engine.generate_turn`` (墙 ``drill_grader.GEN_TURN_BUDGET_S``), 求和由
#: ``tests/test_latency_budget.py`` 钉死 (本路由 §A4 起也在那张表里)。
#: 2026-09-08 冒烟 (scripts/smoke_xunfei_ise.py): 3200B 快速节奏下 18s 语音 ~2.5s 发完.
_VOICE_CALL_BUDGET_S = 8.0
_ISE_TASK_BUDGET_S = 8.5

#: §A4: 生成侧不再自己写死温度/token/超时 —— 与实战轮共用
#: ``mission_engine.generate_turn`` 的 ``GEN_*`` 常量 (15 行内那份 schema 才不会漂移)。
#: 这里**不给**一个本地 ``_LLM_TURN_BUDGET_S``: 抄一份数字正是两者慢慢跑偏的开始。

#: **LEGACY (v1.4.0 协议)**: 旧客户端把"当前这句话"的 user 回合填成这个占位文本.
#: P3 起服务端不再依赖它做任何判断 (结构规则: 末尾 user 回合 = 当前输入), 这里只
#: 保留为**兼容识别**的一部分 —— 老包发的占位文本仍会被替换掉 (add-only 兼容).
#: 新客户端 (P6/P7) 该位置发空串即可; 彻底删除在 P8 的协议清理窗口.
_PLACEHOLDER_USER_TEXT = "（本轮自由回答）"  # noqa: RUF001 (intentional Chinese punctuation)
_LEGACY_EMPTY_MARKERS = frozenset({"", _PLACEHOLDER_USER_TEXT})


# ====== Schemas ======


class DialogueSceneDto(BaseModel):
    id: str
    title: str
    description: str


class DialogueScenesResponse(BaseModel):
    scenes: list[DialogueSceneDto]
    default_scene: str


class DialogueGenerateRequest(BaseModel):
    scene: str = Field(min_length=1, max_length=64)
    mode: str = Field(default="k12", max_length=32)
    model_id: str | None = Field(default=None, max_length=128)


class DialogueGenerateResponse(BaseModel):
    scene_id: str
    status: str  # "stub" | "ready"
    title: str
    lines: list[dict[str, Any]]
    suggested_reply: str
    model_id: str | None = None


class DialogueTurnRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=64)
    history: list[dict[str, Any]] = Field(default_factory=list)
    user_audio_b64: str = ""
    model_id: str | None = Field(default=None, max_length=128)
    #: v2.0 P3: 带身份则本轮证据进能力画像 (§5.6); 不带身份行为与旧版完全一致.
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=36)
    #: §A4/A5 add-only: 客户端 echo 回**最近已经展示过的参考句** (D5 裁决)。
    #: 服务端有状态的那半 (实战轮) 从 ``mission.turns`` 拿; 自由对话没有会话表, 而
    #: ``suggestedReply`` 每轮被覆盖, 所以只能由客户端把"给过的那几句"带回来 ——
    #: 不带也能跑 (退化成"只从 assistant 回合取 Coach 台词"), 带了才真正防复写。
    shown_suggestions: list[str] = Field(default_factory=list)


class DialogueTurnResponse(BaseModel):
    status: str  # "ready" (生成成功; 拿不到就是 503, 不再有 stub 降级)
    reply_text: str
    reply_audio_url: str | None = None
    suggested_reply: str
    recognized_text: str | None = None
    model_id: str | None = None
    # ---- v2.0 P3 add-only (旧客户端 ignoreUnknownKeys, 不受影响) ----
    #: 「原句 vs 更好说法」对照; §A4 起**恒为 null** —— 判分/润色不在本条请求里,
    #: 学员要润色走 ``POST /polish`` (纯文本工具)。字段保留: 线上 APK 在解析这份 DTO.
    polish: Polish | None = None
    #: 本轮语法/词汇判分; §A4 起**恒为 null** (同上, 判分不再由本路由产出).
    grammar_score: float | None = None
    vocabulary_score: float | None = None
    #: 本轮写进画像管线的维度证据: 只有**转写锚定 ISE** 的发音/流利 (未带身份/没音频/
    #: 讯飞没配时为空列表).
    ability_events: list[AbilityEvidence] = Field(default_factory=list)
    #: 生成 provenance: 模型 id (失败走 503, 不再有 "stub" 占位).
    llm_source: str | None = None
    # ---- §A4 (D4 双语) add-only: 空串 = 这一行不渲染, 绝不机翻占位 ----
    #: 台词的简体中文意思.
    reply_cn: str = ""
    #: 示范句的简体中文意思 (要求学员开口的那句默认双语).
    suggestion_cn: str = ""
    #: 学员刚那句英文的简体中文意思 (「我」气泡的「译」).
    learner_cn: str = ""


# ====== Routes ======


@router.get("/dialogue/scenes", response_model=DialogueScenesResponse)
async def list_dialogue_scenes() -> DialogueScenesResponse:
    """Return every scene the free-dialogue picker can offer.

    Public so the Android client doesn't need to hard-code scene metadata
    or ship translation files for new scenes.
    """
    scenes = list_scenes()
    payload = [DialogueSceneDto(id=s.id, title=s.title, description=s.description) for s in scenes]
    return DialogueScenesResponse(scenes=payload, default_scene=scenes[0].id if scenes else "")


@router.post("/dialogue/generate", response_model=DialogueGenerateResponse)
async def generate(req: DialogueGenerateRequest) -> DialogueGenerateResponse:
    """Create the opening turn for free conversation.

    If the backend has LLM credentials configured we ask the model to write a
    warm opening line; otherwise we fall back to the local deterministic
    catalog so the practice flow keeps working without secrets.
    """
    scene = get_scene(req.scene)
    provider = get_llm_provider()
    if cast(bool, getattr(provider, "is_configured", False)):
        try:
            model = _resolve_model(req.model_id)
            completion = await provider.chat(
                model=model,
                messages=_opening_prompt(req.scene, scene.title),
                temperature=0.7,
                max_tokens=200,
                timeout=20.0,
            )
            opening_text = completion.content.strip().split("\n", 1)[0]
            if opening_text.startswith('"'):
                opening_text = opening_text.strip('"')
            return DialogueGenerateResponse(
                scene_id=req.scene,
                status="ready",
                title=scene.title,
                lines=[
                    {
                        "id": f"{req.scene}-assistant-1",
                        "role": "assistant",
                        "text": opening_text or scene.opening,
                        "is_user": False,
                    }
                ],
                suggested_reply=scene.suggestion,
                model_id=model,
            )
        except Exception as exc:
            logger.warning("LLM generate failed; using stub. scene={} err={}", req.scene, exc)

    return DialogueGenerateResponse(
        scene_id=req.scene,
        status="stub",
        title=scene.title,
        lines=[
            {
                "id": f"{req.scene}-assistant-1",
                "role": "assistant",
                "text": scene.opening,
                "is_user": False,
            }
        ],
        suggested_reply=scene.suggestion,
        model_id=None,
    )


@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
async def turn(
    req: DialogueTurnRequest, db: AsyncSession = Depends(get_db)
) -> DialogueTurnResponse:
    """Return the next assistant turn and a model answer for the user.

    §A4/D1: 这条请求里**只有一次 LLM 调用** —— ``mission_engine.generate_turn``
    (复用 :class:`TurnGeneration` 五字段: 台词 + 双语 + 学员句中文), 与实战轮同一份
    schema / 同一个 ``_judge`` 收口 / 同一组 ``GEN_*`` 常量, 所以两处不会漂移。

    润色与分数**不再**塞进这里 (拆两次调用仍然是一次 12s+14s, 装不进 25s 契约):
    学员要润色走现成的 ``POST /polish``。响应里那些字段保留但恒为 null/空 (add-only)。

    带 ``user_audio_b64`` 时先走讯飞 IAT 转写, 并把客户端 history **末尾**那条 user
    回合换成真实转写 (协议见 :func:`_apply_recognized_text`), 让模型回应学员真说的话。

    P3: 带 ``device_id`` / ``user_id`` 时, **转写锚定 ISE** 的发音/流利证据 (讯飞已
    配置且有音频时才有) 走 §5.6 管线入库。不带身份 = 纯无状态旧行为。

    D5: 拿不到台词 (未配置 / 超时 / 两次都不合规) -> ``503 TURN_GENERATION_UNAVAILABLE``,
    **不返回 fabricated 气泡**: 旧版那个"回落到目录里的下一句 / 写死的两句"正是
    "两轮之后永远是同一句"的根因。
    """
    scene = get_scene(req.scene_id)
    # 身份在调用 LLM **之前**解析: 错误的 user_id 要 404, 不能被下面的生成失败兜成 503。
    user = await _identity_user(db, req)
    audio_bytes = _decode_user_audio(req.user_audio_b64)
    _t_iat = time.monotonic()
    try:
        recognized_text = await asyncio.wait_for(
            _iat.transcribe(audio_bytes), timeout=_VOICE_CALL_BUDGET_S
        )
    except TimeoutError:
        logger.warning("dialogue iat budget exceeded | budget_s={}", _VOICE_CALL_BUDGET_S)
        recognized_text = None
    iat_ms = round((time.monotonic() - _t_iat) * 1000)
    history = _apply_recognized_text(req.history, recognized_text)

    # 发音证据只依赖转写文本, 与台词生成无依赖 -> 提前起跑, 落库前收账 (并行省一段延迟)。
    anchored_task: asyncio.Task[mission_engine.AnchoredPronunciation | None] | None = None
    if user is not None and audio_bytes and recognized_text:
        anchored_task = asyncio.create_task(
            mission_engine.anchored_pronunciation(audio_bytes, recognized_text)
        )
    _t_gen = time.monotonic()
    try:
        generation, model = await mission_engine.generate_turn(
            _scene_messages(req.scene_id, history, req.shown_suggestions),
            model_id=req.model_id,
        )
    except LlmUnavailableError as exc:
        if anchored_task is not None and not anchored_task.done():
            anchored_task.cancel()  # 本轮作废时不再要发音证据
        logger.warning("dialogue turn generation unavailable | scene={} err={}", req.scene_id, exc)
        # 503 的码与文案与实战轮**同一份** (``drill_grader``), 免得同一种故障两种说法。
        raise turn_generation_unavailable() from exc
    except Exception:
        if anchored_task is not None and not anchored_task.done():
            anchored_task.cancel()
        raise
    gen_ms = round((time.monotonic() - _t_gen) * 1000)
    anchored: mission_engine.AnchoredPronunciation | None = None
    if anchored_task is not None:
        try:
            anchored = await asyncio.wait_for(anchored_task, timeout=_ISE_TASK_BUDGET_S)
        except TimeoutError:
            logger.warning(
                "dialogue anchored ise budget exceeded | budget_s={}", _ISE_TASK_BUDGET_S
            )
    events = await _persist_turn_evidence(
        db,
        user=user,
        scene_id=scene.id,
        anchored=anchored,
    )
    logger.info(
        "dialogue turn perf | scene={} iat_ms={} gen_ms={} anchored={}",
        req.scene_id,
        iat_ms,
        gen_ms,
        anchored is not None,
    )
    return DialogueTurnResponse(
        status="ready",
        reply_text=generation.reply,
        suggested_reply=generation.suggestion,
        recognized_text=recognized_text,
        model_id=model,
        # 润色/分数不在本条请求里 (§A4): 字段保留, 值诚实缺席 (要润色走 POST /polish)。
        polish=None,
        grammar_score=None,
        vocabulary_score=None,
        ability_events=events,
        llm_source=model,
        # 三处中文已在 :func:`mission_engine.generate_turn` 里过了可信度门 (§A4/D5):
        # 那一行不可信就是 "" (客户端不渲染), 绝不机翻占位。
        reply_cn=generation.reply_cn,
        suggestion_cn=generation.suggestion_cn,
        learner_cn=generation.learner_cn,
    )


# ====== Shared helpers ======


def _decode_user_audio(b64: str) -> bytes:
    """Decode the client's base64 PCM payload.

    Empty or invalid input yields ``b""`` so the caller simply skips
    transcription instead of failing the whole turn.
    """
    if not b64:
        return b""
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        logger.debug("dialogue turn: invalid user_audio_b64, skipping transcription")
        return b""


def _apply_recognized_text(
    history: list[dict[str, Any]], recognized_text: str | None
) -> list[dict[str, Any]]:
    """Swap the client's "current utterance" user turn for the real transcription.

    协议 (v2.0): 带 ``user_audio_b64`` 的请求, 其 history **末尾**的 user 回合就是
    "当前这句话" (客户端要么留空待服务端回填转写, 要么还按 v1.4.0 的约定填占位文本).
    服务端只看**结构** (末尾 user 回合 + 待回填标记), 不再依赖魔法字符串本身 ——
    占位文本仅作为旧客户端的兼容分支保留 (§四: 客户端侧的彻底改造在 P6/P7)。

    Without a transcription the history is returned unchanged (same object, 旧断言
    钉的正是这个 identity). 末尾是 assistant 或没有 user 回合时不动历史 (旧行为同样
    不追加 —— 不替客户端编造它没发的回合)。
    """
    if not recognized_text:
        return history
    updated = [dict(item) for item in history]
    for item in reversed(updated):
        role = str(item.get("role") or "")
        if role == "user":
            text = str(item.get("text") or "").strip()
            if text in _LEGACY_EMPTY_MARKERS:
                # 空串 = v2.0 协议"这句待回填"; 占位文本 = v1.4.0 兼容分支.
                item["text"] = recognized_text
            break
    return updated


async def _identity_user(db: AsyncSession, req: DialogueTurnRequest) -> User | None:
    """解析轮次身份; 未知 ``user_id`` -> 404 (device_id 按 ``POST /history`` 口径注册)."""
    if not req.device_id and not req.user_id:
        return None  # 旧客户端: 纯无状态行为, 零落库
    if req.user_id:
        user = await users.lookup_user(db, user_id=req.user_id)
        if user is None:
            raise AppError(404, f"unknown user_id: {req.user_id}", "USER_NOT_FOUND")
        return user
    created = await users.lookup_user(db, device_id=str(req.device_id), create=True)
    return created


async def _persist_turn_evidence(
    db: AsyncSession,
    *,
    user: User | None,
    scene_id: str,
    anchored: mission_engine.AnchoredPronunciation | None,
    model: str | None = None,
    grammar: float | None = None,
    vocabulary: float | None = None,
    polish: Polish | None = None,
) -> list[AbilityEvidence]:
    """带身份时把自由对话轮写进 §5.6 画像管线; 不带身份 = 直接回空列表.

    判分完整性 (§5.7 + T3 先例): **客户端自选模型不等于可选判分口径** —— 只有当
    本轮走的就是服务端默认模型时, 语法/词汇分才进画像 (别的模型来的分只回给 UI,
    不进 EWMA)。发音/流利证据来自转写锚定 ISE, 由调用方与生成并行算好后传入
    (讯飞未配置 / 失败 / 超预算 = None, 宁缺勿滥)。

    §A4 之后本条路由**不再产出**语法/词汇/润色 (它们搬出请求了: 润色走
    ``POST /polish``), 所以调用点不传 ``grammar``/``vocabulary``/``polish`` —— 三个
    参数与那道门控**留着**: 它们是本模块对"带分的调用"的纪律 (D2), 而且单测直接调它
    验证门控, 不该因为今天没有生产者就把规矩删掉。
    """
    if user is None:
        return []
    events: list[AbilityEvidence] = []
    if grammar is not None or vocabulary is not None:
        server_default = resolve_server_default_model()
        if model == server_default:
            for dimension, value in (("grammar", grammar), ("vocabulary", vocabulary)):
                if value is None:
                    continue
                events.append(
                    AbilityEvidence(
                        dimension=cast("Any", dimension),
                        score=value,
                        source="llm",
                        weight=1.0,
                    )
                )
        else:
            logger.debug(
                "dialogue grading from client-chosen model {} (not server default); "
                "scores stay out of the ability profile",
                model,
            )
    events.extend(mission_engine.anchored_ability_events(anchored))
    if polish is not None:
        mission_engine.record_annotated_diff(
            db,
            user.id,
            polish=polish,
            origin="dialogue",
            scene_id=scene_id,
            llm_source=model,
        )
    if events:
        await ability_record(db, user_id=user.id, session_id="", step_id=scene_id, evidence=events)
    await db.commit()  # 事件/画像/对照流水(只落了 annotated_diffs 时也要落盘)一起收尾
    return events


_OPENING_SYSTEM = (
    "You are a friendly English-speaking coach helping a learner practice "
    "everyday conversation. Reply in natural, simple American English "
    "(CEFR A2-B1). Keep each turn to 1-2 short sentences. Never break character."
)


def _resolve_model(model_id: str | None) -> str:
    """Pick a concrete model id, honoring the operator allow-list.

    P3 修正 (T2 发现的缺陷): 链条收口到 ``llm_provider.resolve_roleplay_model`` ——
    客户端 id 只在白名单内被接受, 服务端回退是 ``LLM_DEFAULT_MODEL -> 首个 ALLOWED
    条目`` 的**确定性**链, 不再有硬编码的 qwen-plus / set 随机序。
    此函数只用于**文本用途** (人设回复 / 润色); 判分口径见
    ``drill_grader._resolve_judge_model``。
    """
    return resolve_roleplay_model(model_id)


def _opening_prompt(scene: str, title: str) -> list[LlmMessage]:
    return [
        LlmMessage(role="system", content=_OPENING_SYSTEM),
        LlmMessage(
            role="user",
            content=(
                f"Start a practice scene titled '{title}'. The learner is about to "
                "reply, so ask exactly one warm, easy question."
            ),
        ),
    ]


#: 客户端 echo 回来的"已展示参考句"上限 (§A4/D5: add-only 的 list[str], 别让它无界).
_SHOWN_SUGGESTIONS_MAX = 8
#: 单条参考句/台词进 prompt 的字符上限: **引 mission_engine 那一份** (实战侧的
#: ``_recent_lines_block`` 用同一个数, 两处各写一个字面量就会漂)。
_LINE_MAX_CHARS = mission_engine.LINE_MAX_CHARS
#: 带进 prompt 的历史回合数 (最近 N 条; 更早的对话对"下一句"没有增量).
_HISTORY_KEEP = 12


def _shown_suggestions(raw: Sequence[str]) -> list[str]:
    """客户端 echo 的已展示参考句 -> 去空、截断、最多 :data:`_SHOWN_SUGGESTIONS_MAX` 条."""
    kept: list[str] = []
    for item in raw[:_SHOWN_SUGGESTIONS_MAX]:
        text = str(item or "").strip()[:_LINE_MAX_CHARS]
        if text:
            kept.append(text)
    return kept


def _repeat_block(history: list[dict[str, Any]], shown_suggestions: Sequence[str]) -> str:
    """**反重复清单** (§A5): 历史里的 Coach 台词 + 客户端 echo 回来的已给参考句.

    自由对话没有会话表, 所以 Coach 台词从历史 assistant 回合取 (无需新字段),
    参考句只能靠 ``shown_suggestions`` —— ``suggestedReply`` 每轮被客户端覆盖, 服务端
    自己没有留档。两样都不写死在 prompt 里: 清单为空就明说"还没说过"。
    """
    lines: list[str] = []
    for item in history[-_HISTORY_KEEP:]:
        if str(item.get("role") or "") != "assistant":
            continue
        text = str(item.get("text") or "").strip()[:_LINE_MAX_CHARS]
        if text:
            lines.append(f"- 你已经说过: {text}")
    for text in _shown_suggestions(shown_suggestions):
        lines.append(f"- 你已经给过参考句: {text}")
    return "\n".join(lines)


def _history_messages(history: list[dict[str, Any]]) -> list[LlmMessage]:
    """客户端 history -> **原生 messages 数组** (§A4 的第二处修复).

    旧版把整段历史压成一段文本塞进一条 user 消息 (``_scene_context`` 的字符串拼接),
    模型因此拿不到"谁说的哪句"的结构 —— 现在按 role 原样交替传下去 (空回合并入下一条时
    跳过: 待回填的末尾 user 回合已被 :func:`_apply_recognized_text` 换掉)。
    """
    messages: list[LlmMessage] = []
    for item in history[-_HISTORY_KEEP:]:
        role = str(item.get("role") or "user")
        text = str(item.get("text") or "").strip()
        if not text or role not in ("user", "assistant"):
            continue
        messages.append(LlmMessage(role=role, content=text))
    return messages


def _append_instruction(messages: list[LlmMessage], tail: str) -> list[LlmMessage]:
    """把末尾指令并进 messages: 上一条已是 user 就并进去 (保持严格交替).

    有些 OpenAI 兼容网关不接受连续两条同 role 的消息; 而"当前这句话"本来就应该是
    同一条 user 回合的一部分 (它是学员这一轮说的), 合并比硬插一条更贴语义。
    """
    if messages and messages[-1].role == "user":
        merged = LlmMessage(role="user", content=f"{messages[-1].content}\n\n{tail}")
        return [*messages[:-1], merged]
    return [*messages, LlmMessage(role="user", content=tail)]


def _scene_messages(
    scene_id: str,
    history: list[dict[str, Any]],
    shown_suggestions: Sequence[str] = (),
) -> list[LlmMessage]:
    """自由对话的台词 prompt -> 原生 messages (§A4).

    §0 第二条缺陷的两处修复都在这里:

    * ``scene.description`` 与人设真正进 prompt (旧版只给 ``scene.title``);
    * 句式指令**不再**硬写 "ONE short follow-up question" —— 那句 prompt 自己要求的
      固定形状正是"AI 反复问同一类问题"的第三个成因, 现在换成"没聊过的方向 + 禁重复
      清单" (:func:`_repeat_block`)。
    """
    scene: DialogueScene = get_scene(scene_id)
    system = (
        "You are a friendly English-speaking coach helping a learner practice "
        "everyday conversation. Never break character. "
        f"场景: 「{scene.title}」 —— {scene.description}。"
        "学员是中文母语、能读写但开口少的英语初学者 (CEFR A2-B1)。"
        f"{mission_engine.GENERATION_RULES}"
    )
    history_messages = _history_messages(history)
    said = _repeat_block(history, shown_suggestions)
    learner_spoke = any(message.role == "user" for message in history_messages)
    tail = (
        f"## 已经说过的话\n{mission_engine.ANTI_REPEAT_RULES}\n"
        f"{said or '(还没有历史台词, 这是第一轮)'}\n\n"
        f"## 议程\n把「{scene.title}」这场聊下去: 追问一个**没问过**的细节, 给学员一个"
        "新的可接话点; 别提前结束, 也别把话题绕回你已经问过的地方。\n\n"
        "## 本轮输入\n"
        + (
            "学员刚说的那句 = 上面最后一条 Learner 消息 (learner_cn 译它)。"
            if learner_spoke
            else "学员这一轮还没说话: learner_cn 输出空字符串。"
        )
        + f"\n\n{mission_engine.GENERATION_JSON_SHAPE}"
    )
    return [
        LlmMessage(role="system", content=system),
        *_append_instruction(history_messages, tail),
    ]
