from __future__ import annotations

from urllib.parse import urljoin

from fastapi import APIRouter, Query, Request

from app.config import settings
from app.core.errors import AppError
from app.models.schema import TtsResponse
from app.services.mimo_tts import MimoTtsProvider

router = APIRouter(tags=["tts"])
_provider = MimoTtsProvider()


@router.get("/tts", response_model=TtsResponse)
async def tts(
    request: Request,
    text: str = Query(..., max_length=500),
    voice: str = Query(""),
) -> TtsResponse:
    if not text.strip():
        raise AppError(status_code=400, message="text must not be empty", code="BAD_REQUEST")
    if not voice:
        voice = settings.mimo_tts_default_voice
    try:
        r = await _provider.synthesize(text, voice)
    except Exception as e:
        raise AppError(
            status_code=503,
            message=f"TTS service unavailable: {e}",
            code="TTS_UNAVAILABLE",
        ) from e
    audio_url = urljoin(str(request.base_url), r.audio_url)
    return TtsResponse(audio_url=audio_url, duration_ms=r.duration_ms, source=r.source)
