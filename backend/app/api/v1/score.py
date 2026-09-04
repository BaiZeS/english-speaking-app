from __future__ import annotations

import contextlib
import os
import tempfile

from fastapi import APIRouter

from app.core.errors import AppError
from app.models.schema import ScoreRequest, ScoreResponse
from app.scoring.read_along import score_read_along
from app.services.audio_input import decode_audio, estimate_speech_rate_wpm
from app.services.xunfei_asr import XunfeiASRProvider

router = APIRouter(tags=["score"])
_asr = XunfeiASRProvider()

# ISE 评测类型白名单 (单词重练用 read_word, 句子跟读用 read_sentence)
_VALID_CATEGORIES = ("read_sentence", "read_word")


@router.post("/score", response_model=ScoreResponse)
async def score(req: ScoreRequest) -> ScoreResponse:
    if not req.audio:
        raise AppError(status_code=400, message="audio is required", code="BAD_REQUEST")
    if req.category not in _VALID_CATEGORIES:
        raise AppError(
            status_code=400,
            message="category must be one of: read_sentence, read_word",
            code="BAD_REQUEST",
        )

    # 1. Decode audio to raw PCM bytes
    audio_bytes = decode_audio(req.audio)

    # 2. Persist audio to a tmp path (real impl: object storage)
    audio_path = _save_audio(audio_bytes)

    try:
        # 3. Run ASR (ISE speech evaluation)
        asr_result = await _asr.recognize(
            audio=audio_bytes, ref_text=req.ref_text, category=req.category
        )

        # 4. Estimate speech rate from the real audio duration (PCM L16 16kHz mono)
        word_count = max(1, len(asr_result.recognized.split()))
        speech_rate_wpm = estimate_speech_rate_wpm(word_count, audio_bytes)

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
            source=asr_result.source,
        )
    finally:
        # best-effort cleanup; ignore failures
        with contextlib.suppress(OSError):
            os.unlink(audio_path)


# PCM L16 16kHz mono 的解码与语速估算已上移到 ``app.services.audio_input``
# (drill 评分服务要复用同一套数值口径, 不能让 service 反向依赖 api).


def _save_audio(audio: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".pcm")
    with os.fdopen(fd, "wb") as f:
        f.write(audio)
    return path
