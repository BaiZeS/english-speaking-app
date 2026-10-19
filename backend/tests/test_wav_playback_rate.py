"""播放侧采样率的回归测试。

华为/鸿蒙折叠屏实测「所有声音都不出声」: ExoPlayer 在 16k/24k 上起不了
AudioTrack (PlaybackException 5001 ERROR_CODE_AUDIO_TRACK_INIT_FAILED)。
Android 只强制设备支持 44.1k/48k 播放, 所以落盘统一到 48k。
"""

from __future__ import annotations

import struct
from array import array

import pytest

from app.services.wav import (
    BYTES_PER_MS,
    PLAYBACK_SAMPLE_RATE,
    SYNTH_SAMPLE_RATE,
    pcm16_to_wav,
    upsample_to_playback,
    wav_duration_ms,
)


def _header_rate(wav: bytes) -> int:
    return struct.unpack("<I", wav[24:28])[0]


def test_playback_rate_is_a_mandatory_supported_one() -> None:
    assert PLAYBACK_SAMPLE_RATE == 48000


def test_default_wav_header_is_written_at_playback_rate() -> None:
    wav = pcm16_to_wav(array("h", [0, 1, -1]).tobytes())
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert _header_rate(wav) == PLAYBACK_SAMPLE_RATE


def test_upsample_double_preserves_endpoints_and_interpolates() -> None:
    pcm = array("h", [100, 200, 300]).tobytes()
    out = array("h")
    out.frombytes(upsample_to_playback(pcm, src_rate=24000))
    assert len(out) == 6  # 2x
    assert list(out) == [100, 150, 200, 250, 300, 300]  # 尾样本保持


def test_upsample_triple_from_capture_rate() -> None:
    pcm = array("h", [0, 1000]).tobytes()
    out = array("h")
    out.frombytes(upsample_to_playback(pcm, src_rate=16000))
    assert len(out) == 6
    assert out[0] == 0 and out[3] == 1000


def test_upsample_rejects_non_integer_ratio_and_odd_bytes() -> None:
    with pytest.raises(ValueError):
        upsample_to_playback(b"\x00\x01", src_rate=22050)
    with pytest.raises(ValueError):
        upsample_to_playback(b"\x00", src_rate=24000)


def test_upsample_is_noop_when_rates_match() -> None:
    assert upsample_to_playback(b"\x01\x02", src_rate=PLAYBACK_SAMPLE_RATE) == b"\x01\x02"


def test_duration_from_header_does_not_double_count_upsampled_audio() -> None:
    # 1 s @24k -> 上采样成 1 s @48k: 时长必须还是 1000 ms, 不能变 2000。
    one_sec_24k = array("h", [0] * SYNTH_SAMPLE_RATE).tobytes()
    wav = pcm16_to_wav(upsample_to_playback(one_sec_24k))
    assert wav_duration_ms(wav) == 1000
    assert BYTES_PER_MS == 96
    # 旧算法 (按 24k 的 48 B/ms 去除 48k 字节数) 会把 1 s 说成 2 s:
    assert len(wav) // (SYNTH_SAMPLE_RATE * 2 // 1000) == 2000


def test_duration_zero_on_non_canonical_blob() -> None:
    assert wav_duration_ms(b"nope") == 0


@pytest.mark.asyncio
async def test_stub_placeholder_audio_is_at_playback_rate() -> None:
    """无 key 时降级给的静音桩同样要能解码 —— 采样率别停在 24k。"""
    from app.services.stub_providers import StubTTSProvider

    result = await StubTTSProvider().synthesize("Hello world", "Mia")
    assert result.audio_bytes[:4] == b"RIFF"
    assert _header_rate(result.audio_bytes) == PLAYBACK_SAMPLE_RATE
