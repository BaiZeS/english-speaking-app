from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TtsResult:
    audio_bytes: bytes
    duration_ms: int
    audio_url: str


@dataclass(frozen=True)
class AsrWord:
    word: str
    score: float
    ipa: str | None


@dataclass(frozen=True)
class AsrResult:
    recognized: str
    word_scores: list[AsrWord]


class TTSProvider(Protocol):
    async def synthesize(self, text: str, voice: str) -> TtsResult: ...


class ASRProvider(Protocol):
    async def recognize(self, audio: bytes, ref_text: str) -> AsrResult: ...
