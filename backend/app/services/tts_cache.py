from __future__ import annotations

import base64
import hashlib
import json
from typing import Protocol

from app.services.interfaces import TtsResult


class _RedisLike(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ex: int | None = None) -> None: ...


class TtsCache:
    def __init__(self, redis: _RedisLike, ttl: int = 86400) -> None:
        self._redis = redis
        self._ttl = ttl

    @staticmethod
    def _key(text: str, voice: str) -> str:
        return "tts:" + hashlib.sha256(f"{voice}::{text}".encode()).hexdigest()[:32]

    async def get(self, text: str, voice: str) -> TtsResult | None:
        raw = await self._redis.get(self._key(text, voice))
        if raw is None:
            return None
        d = json.loads(raw)
        return TtsResult(
            audio_bytes=base64.b64decode(d["audio_b64"]),
            duration_ms=d["duration_ms"],
            audio_url=d["audio_url"],
        )

    async def set(self, text: str, voice: str, result: TtsResult) -> None:
        payload = json.dumps(
            {
                "audio_b64": base64.b64encode(result.audio_bytes).decode("ascii"),
                "duration_ms": result.duration_ms,
                "audio_url": result.audio_url,
            }
        ).encode()
        await self._redis.set(self._key(text, voice), payload, ex=self._ttl)
