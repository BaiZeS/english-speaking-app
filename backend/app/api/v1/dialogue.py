from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["dialogue"])


# A deterministic local conversation catalog keeps the Android flow usable when
# no LLM credentials are configured. The provider can be replaced later without
# changing the mobile API contract.
_SCENES: dict[str, dict[str, str]] = {
    "daily_conversation": {
        "title": "Daily conversation",
        "opening": "Hi! How is your day going?",
        "suggestion": "My day is going well. I am practicing English.",
        "reply": "That is great to hear! What are you going to do next?",
        "next_suggestion": "I am going to finish my work and read a book tonight.",
    },
    "ordering_coffee": {
        "title": "Ordering coffee",
        "opening": "Good morning! What would you like to order?",
        "suggestion": "I would like a small coffee, please.",
        "reply": "Sure. Would you like milk or sugar with that?",
        "next_suggestion": "Milk, please, but no sugar.",
    },
    "job_interview": {
        "title": "Job interview",
        "opening": "Welcome. Could you tell me a little about yourself?",
        "suggestion": "I am a careful and hardworking person who enjoys learning.",
        "reply": "Thank you. What is one skill you are proud of?",
        "next_suggestion": "I am good at communicating clearly and solving problems.",
    },
    "travel": {
        "title": "Travel check-in",
        "opening": "Hello. May I see your passport, please?",
        "suggestion": "Of course. Here is my passport.",
        "reply": "Thank you. How many bags are you checking in today?",
        "next_suggestion": "I am checking in one suitcase.",
    },
}


def _scene_template(scene: str) -> dict[str, str]:
    return _SCENES.get(scene, _SCENES["daily_conversation"])


class DialogueGenerateRequest(BaseModel):
    scene: str = Field(min_length=1, max_length=64)
    mode: str = Field(default="k12", max_length=32)


class DialogueGenerateResponse(BaseModel):
    scene_id: str
    status: str  # "stub" | "ready"
    title: str
    lines: list[dict[str, Any]]
    suggested_reply: str


class DialogueTurnRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=64)
    history: list[dict[str, Any]] = Field(default_factory=list)
    user_audio_b64: str = ""


class DialogueTurnResponse(BaseModel):
    status: str  # "stub" | "ready"
    reply_text: str
    reply_audio_url: str | None = None
    suggested_reply: str
    recognized_text: str | None = None


@router.post("/dialogue/generate", response_model=DialogueGenerateResponse)
async def generate(req: DialogueGenerateRequest) -> DialogueGenerateResponse:
    """Create the opening turn for free conversation.

    This is intentionally deterministic until an LLM provider is configured.
    ``status=stub`` is retained for backwards compatibility with the original
    MVP clients, while the payload is now complete enough for a real practice
    session (opening line + suggested answer).
    """
    scene = _scene_template(req.scene)
    return DialogueGenerateResponse(
        scene_id=req.scene,
        status="stub",
        title=scene["title"],
        lines=[
            {
                "id": f"{req.scene}-assistant-1",
                "role": "assistant",
                "text": scene["opening"],
                "is_user": False,
            }
        ],
        suggested_reply=scene["suggestion"],
    )


@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
async def turn(req: DialogueTurnRequest) -> DialogueTurnResponse:
    """Return the next assistant turn and a model answer for the user.

    ``history`` is accepted as a list of role/text objects so a future LLM
    provider can consume it directly. The local fallback uses the turn count to
    provide a predictable but useful conversation.
    """
    scene = _scene_template(req.scene_id)
    user_turns = sum(1 for item in req.history if item.get("role") == "user")
    if user_turns <= 1:
        reply_text = scene["reply"]
        suggested_reply = scene["next_suggestion"]
    else:
        reply_text = "Thanks for sharing. Could you tell me a little more?"
        suggested_reply = "I would be happy to tell you more about it."

    return DialogueTurnResponse(
        status="stub",
        reply_text=reply_text,
        suggested_reply=suggested_reply,
        # The fallback has no ASR provider. Real deployments can fill this from
        # the same ISE/ASR service used by /score.
        recognized_text=None,
    )
