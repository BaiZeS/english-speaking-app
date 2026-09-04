from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.audio_input import decode_audio, estimate_speech_rate_wpm
from app.services.interfaces import AsrResult, AsrWord


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
    """Pydantic v2 存的是 base64 文本的 bytes, decode_audio 须还原成原始 PCM."""
    pcm = b"\x00\x01\x02\x03" * 10
    b64_bytes = base64.b64encode(pcm).decode().encode()  # 模拟 req.audio
    assert decode_audio(b64_bytes) == pcm


def test_decode_audio_passes_through_non_base64() -> None:
    """非 base64 字节 (含 0x00) 应原样返回, 不抛错."""
    raw = b"\x00\x01\x02raw\x00"
    assert decode_audio(raw) == raw


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
    # stub 路径下来源恒为 "stub" (前端据此提示非真实评测)
    assert data["source"] == "stub"


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


@pytest.mark.asyncio
async def test_score_source_is_xunfei_when_provider_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provider 返回 source='xunfei' 时, 响应透传该来源 (P0 source 字段覆盖)."""

    async def fake_recognize(
        audio: bytes, ref_text: str, category: str = "read_sentence"
    ) -> AsrResult:
        return AsrResult(
            recognized=ref_text,
            word_scores=[AsrWord(word=w, score=90.0, ipa=None) for w in ref_text.split()],
            source="xunfei",
        )

    monkeypatch.setattr("app.api.v1.score._asr.recognize", fake_recognize)
    payload = {
        "lesson_id": 1,
        "line_id": "nce1-L1-A1",
        "ref_text": "Excuse me",
        "audio": base64.b64encode(b"\x00" * 640).decode(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "xunfei"


@pytest.mark.asyncio
async def test_score_forwards_read_word_category_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """category=read_word 被接受并原样转发给 ASR provider."""
    captured: dict[str, object] = {}

    async def fake_recognize(
        audio: bytes, ref_text: str, category: str = "read_sentence"
    ) -> AsrResult:
        captured["ref_text"] = ref_text
        captured["category"] = category
        return AsrResult(
            recognized=ref_text,
            word_scores=[AsrWord(word=ref_text, score=90.0, ipa=None)],
            source="stub",
        )

    monkeypatch.setattr("app.api.v1.score._asr.recognize", fake_recognize)
    payload = {
        "ref_text": "schedule",
        "category": "read_word",
        "audio": base64.b64encode(b"\x00" * 640).decode(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 200, r.text
    assert captured["category"] == "read_word"
    assert captured["ref_text"] == "schedule"


@pytest.mark.asyncio
async def test_score_rejects_invalid_category() -> None:
    payload = {
        "lesson_id": 1,
        "line_id": "L1",
        "ref_text": "hi",
        "category": "read_paragraph",
        "audio": base64.b64encode(b"\x00" * 640).decode(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_score_accepts_word_drill_without_lesson_context() -> None:
    """错词重练请求不带 lesson_id/line_id 也应合法 (P4 单词 drill 形状)."""
    payload = {
        "ref_text": "schedule",
        "category": "read_word",
        "audio": base64.b64encode(b"\x00" * 640).decode(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["word_details"][0]["word"] == "schedule"
    assert data["source"] == "stub"


def test_estimate_speech_rate_uses_real_duration() -> None:
    """32000B = 1s PCM (L16 16kHz mono) -> 1 词 = 60 wpm, 而非旧 4s 窗口的 15 wpm."""
    assert estimate_speech_rate_wpm(1, b"\x00" * 32000) == pytest.approx(60.0)
    # 4 词 / 2s = 120 wpm
    assert estimate_speech_rate_wpm(4, b"\x00" * 64000) == pytest.approx(120.0)


def test_estimate_speech_rate_falls_back_for_short_audio() -> None:
    """<0.3s 的音频回退到旧 4s 预算窗口, 避免除零/极端语速."""
    assert estimate_speech_rate_wpm(1, b"") == pytest.approx(15.0)
    assert estimate_speech_rate_wpm(2, b"\x00" * 100) == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_score_fluency_reflects_real_audio_duration() -> None:
    """1s PCM + 1 词 (stub 全对): 语速 60wpm -> fluency 88; 旧 4s 公式会得 79."""
    payload = {
        "ref_text": "schedule",
        "category": "read_word",
        # 32000B = 1s of PCM L16 16kHz mono
        "audio": base64.b64encode(b"\x00" * 32000).decode(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 200, r.text
    # rate_score=100-|120-60|*0.5=70; pacing=70*0.4+100*0.6=88;
    # fluency=min(88, pron=95, comp=100)=88. 旧固定 4s 窗口会得 79.
    assert r.json()["fluency"] == pytest.approx(88.0)
