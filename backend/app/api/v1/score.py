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
    audio_bytes = _decode_audio(req.audio)

    # 2. Persist audio to a tmp path (real impl: object storage)
    audio_path = _save_audio(audio_bytes)

    try:
        # 3. Run ASR (ISE speech evaluation)
        asr_result = await _asr.recognize(
            audio=audio_bytes, ref_text=req.ref_text, category=req.category
        )

        # 4. Estimate speech rate from the real audio duration (PCM L16 16kHz mono)
        word_count = max(1, len(asr_result.recognized.split()))
        speech_rate_wpm = _estimate_speech_rate_wpm(word_count, audio_bytes)

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


# PCM L16 16kHz mono: 16000 samples/s * 2 bytes/sample
_PCM_BYTES_PER_SECOND = 32000.0
# 音频过短 (<0.3s) 时回退到旧的 4s 预算窗口, 避免除零/不合理语速
_FALLBACK_DURATION_S = 4.0
_MIN_DURATION_S = 0.3


def _estimate_speech_rate_wpm(word_count: int, audio_bytes: bytes) -> float:
    """Estimate speech rate (words/min) from the real audio duration.

    Audio is raw PCM L16 16kHz mono, so duration = len / 32000 seconds.
    Falls back to the old fixed 4s budget window for very short clips.
    """
    duration_s = len(audio_bytes) / _PCM_BYTES_PER_SECOND
    if duration_s < _MIN_DURATION_S:
        duration_s = _FALLBACK_DURATION_S
    return word_count / duration_s * 60.0


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
