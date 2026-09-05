from __future__ import annotations

import struct

import pytest

from app.services.interfaces import AsrWord
from app.services.stub_providers import StubASRProvider, StubTTSProvider


@pytest.mark.asyncio
async def test_stub_tts_returns_playable_silent_wav_with_deterministic_hash() -> None:
    p = StubTTSProvider()
    r1 = await p.synthesize("hi", voice="k12_female")
    r2 = await p.synthesize("hi", voice="k12_female")
    assert r1.audio_bytes == r2.audio_bytes
    assert r1.duration_ms > 0
    assert r1.audio_url.endswith(".wav")
    # P8 清理: 占位音频是**真实可解码**的 WAV (不再是 STUB_TTS:: 假 blob)。
    assert r1.audio_bytes[:4] == b"RIFF"
    assert r1.audio_bytes[8:12] == b"WAVE"
    fmt = struct.unpack("<4sIHHIIHH", r1.audio_bytes[12:36])
    assert fmt[1] == 16  # fmt chunk size
    assert fmt[2] == 1  # PCM
    assert fmt[3] == 1  # mono
    assert fmt[4] == 24000  # 与 MiMo 主路同采样率
    assert fmt[7] == 16  # bits per sample
    assert r1.audio_bytes[36:40] == b"data"
    data_size = struct.unpack("<I", r1.audio_bytes[40:44])[0]
    assert data_size == r1.duration_ms * 48  # 24kHz*2B => 48B/ms, 时长真实
    assert set(r1.audio_bytes[44:]) <= {0}  # 全零 PCM == 静音


@pytest.mark.asyncio
async def test_stub_tts_different_voice_produces_different_audio_url() -> None:
    p = StubTTSProvider()
    a = await p.synthesize("hi", voice="k12_female")
    b = await p.synthesize("hi", voice="k12_male")
    # 静音字节按定义与 voice 无关 (长度只跟 text 走); 身份由 hash url 承载,
    # "是占位" 由 source=stub 承载 —— 二者都不许撞车。
    assert a.audio_url != b.audio_url
    assert a.source == b.source == "stub"


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
