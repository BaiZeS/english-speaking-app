from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["dialogue"])


class DialogueGenerateRequest(BaseModel):
    scene: str
    mode: str = "k12"


class DialogueGenerateResponse(BaseModel):
    scene_id: str
    status: str  # "stub" | "ready"
    lines: list[dict[str, Any]]


class DialogueTurnRequest(BaseModel):
    scene_id: str
    history: list[dict[str, Any]]
    user_audio_b64: str = ""


class DialogueTurnResponse(BaseModel):
    status: str  # "stub"
    reply_text: str
    reply_audio_url: str | None = None


@router.post("/dialogue/generate", response_model=DialogueGenerateResponse)
async def generate(req: DialogueGenerateRequest) -> DialogueGenerateResponse:
    return DialogueGenerateResponse(
        scene_id=req.scene,
        status="stub",
        lines=[{"role": "system", "text": f"[STUB] scene '{req.scene}' not yet implemented"}],
    )


@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
async def turn(req: DialogueTurnRequest) -> DialogueTurnResponse:
    return DialogueTurnResponse(
        status="stub",
        reply_text=f"[STUB] dialogue turn for scene {req.scene_id} not yet implemented",
    )
