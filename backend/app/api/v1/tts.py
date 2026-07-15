from __future__ import annotations

from urllib.parse import urljoin

from fastapi import APIRouter, Query, Request

from app.core.errors import AppError
from app.models.schema import TtsResponse
from app.services.spark_tts import SparkTtsProvider

router = APIRouter(tags=["tts"])
# Spark 超拟人 provider, 缺凭据时自动 fallback 到 v2 老接口 -> stub (见 spark_tts.py).
_provider = SparkTtsProvider()


@router.get("/tts", response_model=TtsResponse)
async def tts(
    request: Request,
    text: str = Query(..., max_length=500),
    voice: str = Query("x5_EnUs_Grant_flow"),
) -> TtsResponse:
    if not text.strip():
        raise AppError(status_code=400, message="text must not be empty", code="BAD_REQUEST")
    r = await _provider.synthesize(text, voice)
    # Resolve relative audio paths (e.g. "/static/tts/x.m4a") against the
    # request's base URL so clients (ExoPlayer) get a playable absolute URL.
    audio_url = urljoin(str(request.base_url), r.audio_url)
    return TtsResponse(audio_url=audio_url, duration_ms=r.duration_ms)
