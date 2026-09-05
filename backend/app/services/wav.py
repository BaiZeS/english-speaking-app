"""WAV container helper (MiMo TTS 主路与 stub 静默占位共用).

MiMo 流式返回 PCM16 24kHz mono; 落盘/占位音频都要包同一个 RIFF/WAVE 头。
单独成模块的原因: ``stub_providers`` 若反向 import ``mimo_tts`` 会形成循环依赖
(mimo_tts 本就要 import StubTTSProvider 作为无凭据降级)。
"""

from __future__ import annotations

import struct

#: stub 与 MiMo 主路一致的合成参数 (24 kHz / 16 bit / mono) => 48 字节 == 1 ms。
WAV_SAMPLE_RATE = 24000
BYTES_PER_MS = WAV_SAMPLE_RATE * 2 // 1000


def pcm16_to_wav(pcm_data: bytes, sample_rate: int = WAV_SAMPLE_RATE, channels: int = 1) -> bytes:
    """Wrap raw PCM16 bytes in a WAV header."""
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
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
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_data
