from __future__ import annotations

from app.config import settings
from app.services.interfaces import TtsResult
from app.services.stub_providers import StubTTSProvider


class XunfeiTTSProvider:
    """讯飞 TTS provider. Falls back to stub when credentials are missing."""

    def __init__(self) -> None:
        self._stub = StubTTSProvider()

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            return await self._stub.synthesize(text, voice)
        # Real 讯飞 WebSocket TTS call goes here in a later phase.
        # For L1 MVP we ship the stub path; integration is gated on credentials.
        return await self._stub.synthesize(text, voice)
