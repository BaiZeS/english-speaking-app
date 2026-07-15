from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# conftest 的 autouse _init_db (pytest_asyncio fixture) 在 sync test 下 hang event loop.
# /tts 端点本身不依赖 db, 这里覆盖掉.
@pytest.fixture(autouse=True)
def _init_db() -> None:
    """覆盖 conftest 的 autouse _init_db."""


@pytest.fixture(autouse=True)
def _force_stub_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 TTS 走 stub: 本测试只校验 /tts 端点接线, 不依赖真实讯飞凭证/网络.

    Spark TTS 与 v2 老接口都要清空凭据, 这样 SparkTtsProvider 会 fallback 到 v2,
    v2 再 fallback 到 stub. 不清空的话, 本地有真实 .env 时会真调讯飞, 断言会抖动.
    """
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_spark_tts_password", "")
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_api_key", "")
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_api_secret", "")


@pytest.mark.asyncio
async def test_tts_returns_audio_url_and_duration() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})
    assert r.status_code == 200
    data = r.json()
    assert data["audio_url"].endswith(".m4a")
    assert data["duration_ms"] > 0


@pytest.mark.asyncio
async def test_tts_rejects_empty_text() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "", "voice": "x5_EnUs_Grant_flow"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_tts_is_deterministic_across_calls() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})
        r2 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})
    assert r1.json()["audio_url"] == r2.json()["audio_url"]
