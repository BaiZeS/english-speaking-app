from __future__ import annotations

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

    # 1. Persist audio to a tmp path (real impl: object storage)
    audio_path = _save_audio(req.audio)

    # 2. Run ASR
    asr_result = await _asr.recognize(audio=req.audio, ref_text=req.ref_text)

    # 3. Estimate speech rate (rough: ASR recognized words over a 4s budget window)
    word_count = max(1, len(asr_result.recognized.split()))
    speech_rate_wpm = (word_count / 4.0) * 60.0

    # 4. Score
    scored = score_read_along(
        ref_text=req.ref_text,
        asr=asr_result,
        speech_rate_wpm=speech_rate_wpm,
        pause_count=0,
    )
    # best-effort cleanup; ignore failures
    with contextlib.suppress(OSError):
        os.unlink(audio_path)
    return ScoreResponse(
        total=scored.total,
        pronunciation=scored.pronunciation,
        fluency=scored.fluency,
        completeness=scored.completeness,
        word_details=scored.word_details,
        suggestion=scored.suggestion,
    )


def _save_audio(audio: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".m4a")
    with os.fdopen(fd, "wb") as f:
        f.write(audio)
    return path
