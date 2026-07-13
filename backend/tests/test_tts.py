from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def _force_stub_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 TTS 走 stub: 本测试只校验 /tts 端点接线, 不依赖真实讯飞凭证/网络.

    与 tests/test_xunfei_asr.py 同样的 monkeypatch 风格. 否则本地有 .env 真实凭证时,
    provider 会真的调用讯飞返回 .mp3 (而非 stub 的 .m4a), 断言会随环境抖动.
    """
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_api_key", "")
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_api_secret", "")


@pytest.mark.asyncio
async def test_tts_returns_audio_url_and_duration() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "k12_female"})
    assert r.status_code == 200
    data = r.json()
    assert data["audio_url"].endswith(".m4a")
    assert data["duration_ms"] > 0


@pytest.mark.asyncio
async def test_tts_rejects_empty_text() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "", "voice": "k12_female"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_tts_is_deterministic_across_calls() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "k12_female"})
        r2 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "k12_female"})
    assert r1.json()["audio_url"] == r2.json()["audio_url"]
