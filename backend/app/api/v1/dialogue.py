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
"""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel, Field

from app.config import settings
from app.services.dialogue_scenes import DialogueScene, get_scene, list_scenes
from app.services.llm_provider import (
    LlmMessage,
    get_llm_provider,
    get_model_catalog,
)

router = APIRouter(tags=["dialogue"])


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


class DialogueTurnResponse(BaseModel):
    status: str  # "stub" | "ready"
    reply_text: str
    reply_audio_url: str | None = None
    suggested_reply: str
    recognized_text: str | None = None
    model_id: str | None = None


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
async def turn(req: DialogueTurnRequest) -> DialogueTurnResponse:
    """Return the next assistant turn and a model answer for the user.

    With LLM configured we send the conversation history and parse a JSON
    ``{reply, suggestion}`` payload back. With no credentials we fall back to
    a deterministic rotating catalog so the UI never breaks.
    """
    scene = get_scene(req.scene_id)
    provider = get_llm_provider()
    if cast(bool, getattr(provider, "is_configured", False)):
        try:
            model = _resolve_model(req.model_id)
            messages = [
                LlmMessage(role="system", content=_OPENING_SYSTEM),
                LlmMessage(role="user", content=_scene_context(req.scene_id, req.history)),
            ]
            completion = await provider.chat(
                model=model,
                messages=messages,
                temperature=0.6,
                max_tokens=300,
                timeout=25.0,
            )
            parsed = _parse_llm_json(completion.content)
            return DialogueTurnResponse(
                status="ready",
                reply_text=parsed["reply"],
                suggested_reply=parsed["suggestion"] or scene.next_suggestion,
                recognized_text=None,
                model_id=model,
            )
        except Exception as exc:
            logger.warning("LLM turn failed; using stub. scene={} err={}", req.scene_id, exc)

    user_turns = sum(1 for item in req.history if item.get("role") == "user")
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
        recognized_text=None,
        model_id=None,
    )


# ====== Shared helpers ======


_OPENING_SYSTEM = (
    "You are a friendly English-speaking coach helping a learner practice "
    "everyday conversation. Reply in natural, simple American English "
    "(CEFR A2-B1). Keep each turn to 1-2 short sentences. Never break character."
)


def _resolve_model(model_id: str | None) -> str:
    """Pick a concrete model id, honoring the operator allow-list."""
    catalog = {info.id for info in get_model_catalog()}
    if model_id and model_id in catalog:
        return model_id
    allowed = settings.llm_allowed_models.strip()
    if allowed:
        for item in allowed.split(","):
            item = item.strip()
            if item:
                return item
    return settings.llm_default_model or (next(iter(catalog)) if catalog else "qwen-plus")


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
        "Conversation so far:\n" + "\n".join(lines) + "\n\n"
        "Reply as Coach with ONE short follow-up question (1-2 sentences) and "
        "after a blank line, propose a model answer for the learner to copy or "
        "adapt. Format your reply as JSON exactly like this:\n"
        '{"reply": "<your question>", "suggestion": "<model answer>"}'
    )


def _parse_llm_json(text: str) -> dict[str, str]:
    """Tolerantly parse the JSON object the LLM is instructed to emit."""
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
    reply = str(data.get("reply", "")).strip()
    suggestion = str(data.get("suggestion", "")).strip()
    if not reply:
        reply = text.split("\n", 1)[0].strip() or "Could you tell me more?"
    return {"reply": reply, "suggestion": suggestion}
