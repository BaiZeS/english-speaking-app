from __future__ import annotations

import base64
import binascii
import contextlib
import os
import tempfile

from fastapi import APIRouter

from app.core.errors import AppError
from app.models.schema import ScoreRequest, ScoreResponse
from app.scoring.read_along import score_read_along
from app.services.xunfei_asr import XunfeiASRProvider

router = APIRouter(tags=["score"])
_asr = XunfeiASRProvider()


@router.post("/score", response_model=ScoreResponse)
async def score(req: ScoreRequest) -> ScoreResponse:
    if not req.audio:
        raise AppError(status_code=400, message="audio is required", code="BAD_REQUEST")

    # 1. Decode audio to raw PCM bytes
    audio_bytes = _decode_audio(req.audio)

    # 2. Persist audio to a tmp path (real impl: object storage)
    audio_path = _save_audio(audio_bytes)

    try:
        # 3. Run ASR (ISE speech evaluation)
        asr_result = await _asr.recognize(audio=audio_bytes, ref_text=req.ref_text)

        # 4. Estimate speech rate (rough: ASR recognized words over a 4s budget window)
        word_count = max(1, len(asr_result.recognized.split()))
        speech_rate_wpm = (word_count / 4.0) * 60.0

        # 5. Score
        scored = score_read_along(
            ref_text=req.ref_text,
            asr=asr_result,
            speech_rate_wpm=speech_rate_wpm,
            pause_count=0,
        )
        return ScoreResponse(
            total=scored.total,
            pronunciation=scored.pronunciation,
            fluency=scored.fluency,
            completeness=scored.completeness,
            word_details=scored.word_details,
            suggestion=scored.suggestion,
        )
    finally:
        # best-effort cleanup; ignore failures
        with contextlib.suppress(OSError):
            os.unlink(audio_path)


def _decode_audio(audio: bytes) -> bytes:
    """Decode the request audio to raw PCM bytes.

    The Android client sends audio as a base64 string in the JSON body. Pydantic v2
    loads a JSON ``bytes`` field as the base64 string's own bytes (not decoded), so we
    detect and decode base64 here. Falls back to raw bytes if not valid base64.
    """
    try:
        return base64.b64decode(audio, validate=True)
    except (binascii.Error, ValueError):
        return bytes(audio)


def _save_audio(audio: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".pcm")
    with os.fdopen(fd, "wb") as f:
        f.write(audio)
    return path
