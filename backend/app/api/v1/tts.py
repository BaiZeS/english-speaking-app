from __future__ import annotations

from urllib.parse import urljoin

from fastapi import APIRouter, Query, Request

from app.core.errors import AppError
from app.models.schema import TtsResponse
from app.services.spark_tts import SparkTtsProvider

router = APIRouter(tags=["tts"])
# Spark 超拟人 provider; 凭据齐全时强制走 Spark, 失败抛错由 endpoint 转 503.
# 仅完全无凭据走 stub (source=stub) — 详见 spark_tts.py 文档及 DEV-2026-07-22-TTS-A1.
_provider = SparkTtsProvider()


@router.get("/tts", response_model=TtsResponse)
async def tts(
    request: Request,
    text: str = Query(..., max_length=500),
    voice: str = Query("x5_EnUs_Grant_flow"),
) -> TtsResponse:
    if not text.strip():
        raise AppError(status_code=400, message="text must not be empty", code="BAD_REQUEST")
    try:
        r = await _provider.synthesize(text, voice)
    except Exception as e:
        # 任一 provider 失败 (RuntimeError / websockets.exceptions.* / OSError / 等)
        # 都映射为 503+TTS_UNAVAILABLE, 让前端拿到明确错误码可重试/告警.
        # DEV-2026-07-22-TTS-A3: 收紧到 except RuntimeError 会漏掉 websockets
        # transport 层错误 (连接拒绝/DNS/TLS/超时), 那时 FastAPI 返 500,
        # 前端拿不到 TTS_UNAVAILABLE, 是生产最常见的失败模式.
        # 保留 `from e` 链方便排障.
        raise AppError(
            status_code=503,
            message=f"TTS service unavailable: {e}",
            code="TTS_UNAVAILABLE",
        ) from e
    # Resolve relative audio paths (e.g. "/static/tts/x.m4a") against the
    # request's base URL so clients (ExoPlayer) get a playable absolute URL.
    audio_url = urljoin(str(request.base_url), r.audio_url)
    return TtsResponse(audio_url=audio_url, duration_ms=r.duration_ms, source=r.source)
