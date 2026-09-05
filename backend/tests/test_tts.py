from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def _init_db() -> None:
    """覆盖 conftest 的 autouse _init_db."""


@pytest.fixture(autouse=True)
def _force_stub_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 TTS 走 stub: 本测试只校验 /tts 端点接线, 不依赖真实 MiMo 凭据/网络."""
    monkeypatch.setattr("app.services.mimo_tts.settings.mimo_api_key", "")


@pytest.mark.asyncio
async def test_tts_returns_audio_url_and_duration() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "Mia"})
    assert r.status_code == 200
    data = r.json()
    assert data["audio_url"].endswith(".wav")
    assert data["duration_ms"] > 0
    assert data["source"] == "stub"


@pytest.mark.asyncio
async def test_tts_rejects_empty_text() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "", "voice": "Mia"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_tts_is_deterministic_across_calls() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "Mia"})
        r2 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "Mia"})
    assert r1.json()["audio_url"] == r2.json()["audio_url"]


@pytest.mark.asyncio
async def test_tts_returns_503_when_mimo_fails_with_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """配齐 MiMo API key 时, 调用失败必须被端点映射为 503 + TTS_UNAVAILABLE."""
    monkeypatch.setattr("app.services.mimo_tts.settings.mimo_api_key", "test-key")
    monkeypatch.setattr("app.services.mimo_tts.settings.tts_audio_dir", str(tmp_path))

    def _boom(self, _t: str, _v: str) -> bytes:
        raise RuntimeError("simulated mimo failure: rate limit")

    from app.services import mimo_tts as mimo_mod

    monkeypatch.setattr(mimo_mod.MimoTtsProvider, "_synthesize_streaming", _boom)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "Mia"})

    assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"]["code"] == "TTS_UNAVAILABLE"
    assert "simulated mimo failure" in body["error"]["message"]
    assert "audio_url" not in body


@pytest.mark.asyncio
async def test_tts_returns_503_on_network_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """网络层错误 (ConnectionError 等) 也必须走 503+TTS_UNAVAILABLE."""
    monkeypatch.setattr("app.services.mimo_tts.settings.mimo_api_key", "test-key")
    monkeypatch.setattr("app.services.mimo_tts.settings.tts_audio_dir", str(tmp_path))

    def _boom(self, _t: str, _v: str) -> bytes:
        raise ConnectionError("simulated network failure")

    from app.services import mimo_tts as mimo_mod

    monkeypatch.setattr(mimo_mod.MimoTtsProvider, "_synthesize_streaming", _boom)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "Mia"})

    assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"]["code"] == "TTS_UNAVAILABLE"
    assert "audio_url" not in body


@pytest.mark.asyncio
async def test_tts_uses_default_voice_when_empty() -> None:
    """空 voice 参数应使用配置的默认发音人."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello"})
    assert r.status_code == 200
