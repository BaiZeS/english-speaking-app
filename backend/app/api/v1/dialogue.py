"""Free dialogue (自由对话) endpoints.

Backend reads LLM credentials from environment (``LLM_BASE_URL`` / ``LLM_API_KEY``)
and, when configured, generates conversation turns via an OpenAI-compatible
provider (default: 阿里云百炼 Maas ``/compatible-mode/v1``).

When no credentials are configured the module falls back to a deterministic
local catalog so the Android client still produces a usable practice flow.
``status`` in the response distinguishes the two: ``stub`` = local fallback,
``ready`` = real LLM reply.

The scene catalog itself lives in :mod:`app.services.dialogue_scenes` and is
exposed via ``GET /dialogue/scenes`` so the Android picker can render it.

v2.0 P3 扩展 (§5.5-4 / §5.6 / §5.7 / §四 魔法字符串):

* ``/dialogue/turn`` 的**同一次** LLM 调用现在多带三样: 语法润色 ``polish``
  (「原句 vs 更好说法」对照) + 语法/词汇判分 —— 拆成两次调用等于双倍延迟, 计划
  明确"并入 /dialogue/turn 的单次 LLM 调用";
* 带身份 (``device_id`` / ``user_id``) 时本轮证据写 §5.6 画像管线: 语法/词汇来自
  LLM (仅当判分模型 = 服务端默认模型; 客户端自选模型的分数只回给 UI 不进画像),
  发音走**转写锚定 ISE** (讯飞没配置就没有这条证据 —— 不造假);
* 历史回填不再匹配魔法字符串: 协议层面"当前这句话 = 末尾的 user 回合 (内容待
  转写)", 老客户端的占位文本仍被接受 (向后兼容), 但服务端**不依赖**它 ——
  mission 状态机 (course_sessions) 直接服务端持有历史, 才是彻底的解法。
"""

from __future__ import annotations

import base64
import binascii
import json
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
from app.services.drill_grader import AbilityEvidence
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


class DialogueTurnResponse(BaseModel):
    status: str  # "stub" | "ready"
    reply_text: str
    reply_audio_url: str | None = None
    suggested_reply: str
    recognized_text: str | None = None
    model_id: str | None = None
    # ---- v2.0 P3 add-only (旧客户端 ignoreUnknownKeys, 不受影响) ----
    #: 「原句 vs 更好说法」对照; 没问题 / 不可用时为 null.
    polish: Polish | None = None
    #: 本轮语法/词汇判分 (null = 没有可判分的英文内容).
    grammar_score: float | None = None
    vocabulary_score: float | None = None
    #: 本轮写进画像管线的维度证据 (未带身份时为空列表).
    ability_events: list[AbilityEvidence] = Field(default_factory=list)
    #: 证据/润色来源: ready 时为模型 id, 降级为 "stub".
    llm_source: str | None = None


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

    With LLM configured we send the conversation history and parse a JSON
    ``{reply, suggestion, polish, grammar_score, vocabulary_score}`` payload
    back (ONE call — 润色与判分并入同一 JSON 是 §5.5-4 的明确决策, 双倍调用会
    顶爆移动端延迟预算). 解析保持**宽容**: reply 是唯一关键字段, 缺了才降级;
    polish/分数缺件不影响 "ready" (旧模型 / 旧 prompt 回 `{reply,suggestion}`
    也照样通过, add-only 兼容)。With no credentials we fall back to a
    deterministic rotating catalog so the UI never breaks.

    When the request carries the user's recorded reply (``user_audio_b64``)
    we transcribe it via 讯飞 IAT and swap the client's placeholder user turn
    for the recognized text, so the LLM responds to what was actually said.
    Without IAT credentials (or on any failure) behavior is unchanged.

    P3: 带 ``device_id`` / ``user_id`` 时, 本轮的语法/词汇判分与**转写锚定 ISE**
    发音证据 (讯飞已配置且有音频时才有) 走 §5.6 管线入库; 润色对照另记
    ``annotated_diffs`` 一行。不带身份 = 纯无状态旧行为。
    """
    scene = get_scene(req.scene_id)
    # 身份在调用 LLM **之前**解析: 错误的 user_id 要 404, 不能被下面的降级兜成 200.
    user = await _identity_user(db, req)
    audio_bytes = _decode_user_audio(req.user_audio_b64)
    recognized_text = await _iat.transcribe(audio_bytes)
    history = _apply_recognized_text(req.history, recognized_text)
    provider = get_llm_provider()
    if cast(bool, getattr(provider, "is_configured", False)):
        try:
            model = _resolve_model(req.model_id)
            messages = [
                LlmMessage(role="system", content=_OPENING_SYSTEM),
                LlmMessage(role="user", content=_scene_context(req.scene_id, history)),
            ]
            completion = await provider.chat(
                model=model,
                messages=messages,
                temperature=0.6,
                max_tokens=400,
                timeout=25.0,
            )
            parsed = _parse_llm_json(completion.content)
            # ``_parse_llm_json`` 保证 reply/suggestion 键存在; reply 兜底在解析器里
            reply = str(parsed.get("reply") or "").strip() or "Could you tell me more?"
            suggestion = str(parsed.get("suggestion") or "").strip() or scene.next_suggestion
            polish = mission_engine.coerce_polish(parsed.get("polish"))
            grammar = mission_engine.coerce_score(parsed.get("grammar_score"))
            vocabulary = mission_engine.coerce_score(parsed.get("vocabulary_score"))
            events = await _persist_turn_evidence(
                db,
                user=user,
                scene_id=scene.id,
                model=model,
                grammar=grammar,
                vocabulary=vocabulary,
                audio_bytes=audio_bytes,
                recognized=recognized_text,
                polish=polish,
            )
            return DialogueTurnResponse(
                status="ready",
                reply_text=reply,
                suggested_reply=suggestion,
                recognized_text=recognized_text,
                model_id=model,
                polish=polish,
                grammar_score=grammar,
                vocabulary_score=vocabulary,
                ability_events=events,
                llm_source=model,
            )
        except Exception as exc:
            logger.warning("LLM turn failed; using stub. scene={} err={}", req.scene_id, exc)

    user_turns = sum(1 for item in history if item.get("role") == "user")
    if user_turns <= 1:
        reply_text = scene.fallback_reply
        suggested_reply = scene.next_suggestion
    else:
        reply_text = "Thanks for sharing. Could you tell me a little more?"
        suggested_reply = "I would be happy to tell you more about it."

    return DialogueTurnResponse(
        status="stub",
        reply_text=reply_text,
        suggested_reply=suggested_reply,
        recognized_text=recognized_text,
        model_id=None,
        llm_source="stub",
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
    model: str,
    grammar: float | None,
    vocabulary: float | None,
    audio_bytes: bytes,
    recognized: str | None,
    polish: Polish | None,
) -> list[AbilityEvidence]:
    """带身份时把自由对话轮写进 §5.6 画像管线; 不带身份 = 直接回空列表.

    判分完整性 (§5.7 + T3 先例): **客户端自选模型不等于可选判分口径** —— 只有当
    本轮走的就是服务端默认模型时, 语法/词汇分才进画像 (别的模型来的分只回给 UI,
    不进 EWMA)。发音/流利证据来自转写锚定 ISE (讯飞未配置 = 不产出)。
    """
    if user is None:
        return []
    events: list[AbilityEvidence] = []
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
    anchored = None
    if audio_bytes and recognized:
        anchored = await mission_engine.anchored_pronunciation(audio_bytes, recognized)
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


def _scene_context(scene_id: str, history: list[dict[str, Any]]) -> str:
    """Render the dialogue history into a compact transcript for the LLM."""
    lines = []
    for item in history[-12:]:
        role = item.get("role", "user")
        text = item.get("text", "")
        if not text:
            continue
        speaker = "Learner" if role == "user" else "Coach"
        lines.append(f"{speaker}: {text}")
    scene: DialogueScene = get_scene(scene_id)
    return (
        f"Scene: {scene.title}.\n"
        "Conversation so far: (learner utterances in parentheses are awaiting "
        "transcription, ignore them)\n" + "\n".join(lines) + "\n\n"
        "Reply as Coach with ONE short follow-up question (1-2 sentences) and a "
        "model answer for the learner. Also look at the learner's LAST real "
        "English message: if it has grammar or wording mistakes worth fixing, "
        "return a polish object (original = the learner's exact words, polished = "
        "a natural sentence they can say out loud, explanation_cn = one short "
        "Chinese sentence); otherwise polish must be null. Grade that last "
        "message 0-100 on grammar and vocabulary (use null when there is no "
        "English content to grade). Format your reply as JSON exactly like this:\n"
        '{"reply": "<your question>", "suggestion": "<model answer>", '
        '"polish": {"original": "...", "polished": "...", "explanation_cn": "..."} '
        'or null, "grammar_score": number|null, "vocabulary_score": number|null}'
    )


def _parse_llm_json(text: str) -> dict[str, Any]:
    """Tolerantly parse the JSON object the LLM is instructed to emit.

    P3: 返回**原始 dict** (polish/分数等新字段由调用方宽容取值); reply/suggestion
    缺失或整体不是 JSON 时的兜底行为与旧版一致 (add-only 兼容)。
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
        text = text.rstrip("`").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        parts = text.split("\n", 1)
        reply = parts[0].strip()
        suggestion = parts[1].strip() if len(parts) > 1 else ""
        return {"reply": reply or "Could you tell me more?", "suggestion": suggestion}
    if not isinstance(data, dict):
        return {"reply": text, "suggestion": ""}
    result: dict[str, Any] = dict(data)
    reply = str(result.get("reply") or "").strip()
    if not reply:
        result["reply"] = text.split("\n", 1)[0].strip() or "Could you tell me more?"
    else:
        result["reply"] = reply
    result.setdefault("suggestion", "")
    return result
