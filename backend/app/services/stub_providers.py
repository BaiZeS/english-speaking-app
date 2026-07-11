from __future__ import annotations

import hashlib

from app.services.interfaces import AsrResult, AsrWord, TtsResult


class StubTTSProvider:
    """Deterministic TTS that hashes (text, voice) to produce a fake audio blob."""

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        h = hashlib.sha256(f"{voice}::{text}".encode()).hexdigest()[:16]
        # 200ms of fake audio per char
        duration_ms = max(200, len(text) * 80)
        return TtsResult(
            audio_bytes=f"STUB_TTS::{h}".encode(),
            duration_ms=duration_ms,
            audio_url=f"/static/tts/{h}.m4a",
        )


class StubASRProvider:
    """Recognizes the reference text perfectly when ref_text is provided."""

    async def recognize(self, audio: bytes, ref_text: str) -> AsrResult:
        words = ref_text.split()
        return AsrResult(
            recognized=ref_text,
            word_scores=[AsrWord(word=w, score=95.0, ipa=None) for w in words],
        )
