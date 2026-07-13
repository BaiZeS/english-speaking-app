from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.score import _decode_audio
from app.main import app


@pytest.fixture(autouse=True)
def _force_stub_asr(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 /score 走 stub ASR: 本测试只校验端点接线, 不依赖真实讯飞凭证/网络.

    与 tests/test_tts.py 同样的 monkeypatch 风格. 否则本地有 .env 真实凭证时,
    provider 会真的调用 ISE (假 m4a 音频评测失败), 断言会随环境抖动.
    """
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_api_key", "")
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_api_secret", "")


def test_decode_audio_unwraps_base64() -> None:
    """Pydantic v2 存的是 base64 文本的 bytes, _decode_audio 须还原成原始 PCM."""
    pcm = b"\x00\x01\x02\x03" * 10
    b64_bytes = base64.b64encode(pcm).decode().encode()  # 模拟 req.audio
    assert _decode_audio(b64_bytes) == pcm


def test_decode_audio_passes_through_non_base64() -> None:
    """非 base64 字节 (含 0x00) 应原样返回, 不抛错."""
    raw = b"\x00\x01\x02raw\x00"
    assert _decode_audio(raw) == raw


@pytest.mark.asyncio
async def test_score_returns_full_breakdown() -> None:
    payload = {
        "lesson_id": 1,
        "line_id": "nce1-L1-A1",
        "ref_text": "Excuse me",
        "mode": "k12",
        # tiny fake audio header (stub 不解析内容)
        "audio": "AAAAGGZ0eXBpc29tAAAAAGlzbzZtcDQy",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data
    for k in ("pronunciation", "fluency", "completeness"):
        assert 0 <= data[k] <= 100
    assert isinstance(data["word_details"], list)
    assert data["word_details"][0]["word"] == "Excuse"


@pytest.mark.asyncio
async def test_score_rejects_empty_audio() -> None:
    payload = {
        "lesson_id": 1,
        "line_id": "L1",
        "ref_text": "hi",
        "mode": "k12",
        "audio": "",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"
