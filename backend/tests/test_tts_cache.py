from __future__ import annotations

import pytest

from app.services.interfaces import TtsResult
from app.services.tts_cache import TtsCache


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self.store[key] = value


@pytest.mark.asyncio
async def test_cache_miss_returns_none() -> None:
    c = TtsCache(redis=FakeRedis())  # type: ignore[arg-type]
    assert await c.get("hi", "k12_female") is None


@pytest.mark.asyncio
async def test_cache_set_then_get_roundtrip() -> None:
    c = TtsCache(redis=FakeRedis())  # type: ignore[arg-type]
    await c.set("hi", "k12_female", TtsResult(audio_bytes=b"abc", duration_ms=100, audio_url="x"))
    r = await c.get("hi", "k12_female")
    assert r is not None
    assert r.audio_bytes == b"abc"
    assert r.duration_ms == 100
