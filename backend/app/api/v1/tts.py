from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.errors import AppError
from app.models.schema import TtsResponse
from app.services.xunfei_tts import XunfeiTTSProvider

router = APIRouter(tags=["tts"])
_provider = XunfeiTTSProvider()


@router.get("/tts", response_model=TtsResponse)
async def tts(
    text: str = Query(..., max_length=500), voice: str = Query("k12_female")
) -> TtsResponse:
    if not text.strip():
        raise AppError(status_code=400, message="text must not be empty", code="BAD_REQUEST")
    r = await _provider.synthesize(text, voice)
    return TtsResponse(audio_url=r.audio_url, duration_ms=r.duration_ms)
