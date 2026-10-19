"""WAV 容器与播放侧采样率 helper.

两条采样率, 别混: MiMo 流式回 24 kHz PCM(``SYNTH_SAMPLE_RATE``, 时长换算基准),
落盘统一到 48 kHz(``PLAYBACK_SAMPLE_RATE``)。原因是 Android CDD 只强制设备支持
44.1k/48k 播放, 实测华为/鸿蒙折叠屏在 16k/24k 起不了 AudioTrack -- ExoPlayer 抛
5001 ERROR_CODE_AUDIO_TRACK_INIT_FAILED, 用户侧表现是「所有声音都不出声」。48k 又是
16k/24k 的整数倍, 整数比插值即可, 不引第三方重采样库。

单独成模块的原因: ``stub_providers`` 若反向 import ``mimo_tts`` 会形成循环依赖
(mimo_tts 本就要 import StubTTSProvider 作为无凭据降级)。
"""

from __future__ import annotations

import struct
from array import array

#: 合成侧 (MiMo 流式 PCM) 采样率。
SYNTH_SAMPLE_RATE = 24000
#: 播放器实际拿到的采样率 —— 播放无声的病灶就在这里。
PLAYBACK_SAMPLE_RATE = 48000

#: 播放侧字节密度 (48 kHz mono PCM16) => 96 B == 1 ms。stub 按 ms 造静音即用此值。
BYTES_PER_MS = PLAYBACK_SAMPLE_RATE * 2 // 1000
BITS_PER_SAMPLE = 16

_HEADER_BYTES = 44


def upsample_to_playback(pcm_data: bytes, src_rate: int = SYNTH_SAMPLE_RATE) -> bytes:
    """整数比线性插值上采样 mono PCM16 到 ``PLAYBACK_SAMPLE_RATE``.

    只接受整数倍 (16k/24k -> 48k 都满足): 整数比才不需要滤波器, 代价只是高频插值
    近似, 对语音示范音听感无损。尾段平推最后一个采样值, 不外推。
    """
    if src_rate == PLAYBACK_SAMPLE_RATE:
        return pcm_data
    if src_rate <= 0 or PLAYBACK_SAMPLE_RATE % src_rate != 0:
        raise ValueError(f"只支持整数倍上采样: {src_rate} -> {PLAYBACK_SAMPLE_RATE}")
    if len(pcm_data) % 2:
        raise ValueError("PCM16 长度必须为偶数字节")
    factor = PLAYBACK_SAMPLE_RATE // src_rate
    samples: array[int] = array("h")
    samples.frombytes(pcm_data)
    n = len(samples)
    if n == 0:
        return b""
    out: array[int] = array("h", bytes(2 * n * factor))
    for i in range(len(out)):
        base = i // factor
        frac = i % factor
        a = samples[base]
        b = samples[base + 1] if base + 1 < n else a
        out[i] = a if frac == 0 else a + (b - a) * frac // factor
    return out.tobytes()


def pcm16_to_wav(
    pcm_data: bytes, sample_rate: int = PLAYBACK_SAMPLE_RATE, channels: int = 1
) -> bytes:
    """Wrap raw PCM16 bytes in a canonical 44-byte RIFF/WAVE header."""
    byte_rate = sample_rate * channels * BITS_PER_SAMPLE // 8
    block_align = channels * BITS_PER_SAMPLE // 8
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # chunk size
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        BITS_PER_SAMPLE,
        b"data",
        data_size,
    )
    return header + pcm_data


def wav_duration_ms(wav_bytes: bytes) -> int:
    """读自己的 44 字节头换算毫秒 (磁盘缓存命中时不能再按字节数瞎除).

    上采样后字节密度与合成侧差 integer factor 倍, 用错基准就把 1 s 报成 2 s,
    客户端进度条/跟读节拍会跟着错位 -- 所以时长只信 header。
    """
    if len(wav_bytes) < _HEADER_BYTES or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return 0
    byte_rate = int.from_bytes(wav_bytes[28:32], "little")  # fmt chunk 的 byteRate
    data_size = int.from_bytes(wav_bytes[40:44], "little")  # data chunk 的 DataSize
    if byte_rate <= 0 or data_size <= 0:
        return 0
    return data_size * 1000 // byte_rate
