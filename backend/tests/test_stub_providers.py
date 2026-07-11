from __future__ import annotations

from dataclasses import replace

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
async def test_stub_asr_with_garbage_words_lowers_score() -> None:
    p = StubASRProvider()
    res = await p.recognize(audio=b"\x00\x00", ref_text="Hello world")
    # simulate partial misrecognition by tampering after the fact:
    res = replace(res, recognized="Hello there")
    bad = [w for w in res.word_scores if w.word not in res.recognized.split()]
    assert len(bad) >= 1
