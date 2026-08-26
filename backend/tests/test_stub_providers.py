from __future__ import annotations

import pytest

from app.services.interfaces import AsrWord
from app.services.stub_providers import StubASRProvider, StubTTSProvider


@pytest.mark.asyncio
async def test_stub_tts_returns_audio_url_with_deterministic_hash() -> None:
    p = StubTTSProvider()
    r1 = await p.synthesize("hi", voice="k12_female")
    r2 = await p.synthesize("hi", voice="k12_female")
    assert r1.audio_bytes == r2.audio_bytes
    assert r1.duration_ms > 0
    assert r1.audio_url.endswith(".m4a")


@pytest.mark.asyncio
async def test_stub_tts_different_voice_produces_different_audio() -> None:
    p = StubTTSProvider()
    a = await p.synthesize("hi", voice="k12_female")
    b = await p.synthesize("hi", voice="k12_male")
    assert a.audio_bytes != b.audio_bytes


@pytest.mark.asyncio
async def test_stub_asr_recognizes_reference_exactly() -> None:
    p = StubASRProvider()
    res = await p.recognize(audio=b"\x00\x00", ref_text="Hello world")
    assert res.recognized == "Hello world"
    assert res.word_scores == [
        AsrWord(word="Hello", score=95.0, ipa=None),
        AsrWord(word="world", score=95.0, ipa=None),
    ]


@pytest.mark.asyncio
async def test_stub_asr_accepts_and_ignores_category_kwarg() -> None:
    """签名兼容: 单词重练的 category 参数须被接受 (忽略), 与 XunfeiASRProvider 对齐."""
    p = StubASRProvider()
    res = await p.recognize(audio=b"\x00\x00", ref_text="schedule", category="read_word")
    assert res.recognized == "schedule"
    assert res.source == "stub"
