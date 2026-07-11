from __future__ import annotations

from app.config import settings
from app.services.interfaces import AsrResult
from app.services.stub_providers import StubASRProvider


class XunfeiASRProvider:
    """讯飞 ASR provider. Falls back to stub when credentials are missing."""

    def __init__(self) -> None:
        self._stub = StubASRProvider()

    async def recognize(self, audio: bytes, ref_text: str) -> AsrResult:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            return await self._stub.recognize(audio, ref_text)
        # Real 讯飞 IAT WebSocket call goes here in a later phase.
        return await self._stub.recognize(audio, ref_text)
