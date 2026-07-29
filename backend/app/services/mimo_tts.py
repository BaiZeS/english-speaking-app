"""MiMo-V2.5-TTS 语音合成 provider.

文档: https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5
接口: OpenAI 兼容 REST API (https://api.xiaomimimo.com/v1/chat/completions)
模型: mimo-v2.5-tts
鉴权: api-key 请求头 (MIMO_API_KEY)
流式: SSE 返回 base64 PCM16 24kHz 音频块
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct

from loguru import logger
from openai import OpenAI

from app.config import settings
from app.services.interfaces import TtsResult
from app.services.stub_providers import StubTTSProvider

_KNOWN_VOICES: set[str] = {"Mia", "Chloe", "Milo", "Dean"}


def _normalize_voice(voice: str | None) -> str:
    v = (voice or "").strip()
    if v in _KNOWN_VOICES:
        return v
    if v:
        logger.warning("unknown mimo tts voice {!r}, fallback to default", v)
    return settings.mimo_tts_default_voice


def _audio_cache_path(text: str, voice: str) -> tuple[str, str]:
    h = hashlib.sha256(f"mimo::{voice}::{text}".encode()).hexdigest()[:16]
    audio_dir = settings.tts_audio_dir
    os.makedirs(audio_dir, exist_ok=True)
    return os.path.join(audio_dir, f"{h}.mp3"), f"/static/tts/{h}.mp3"


def _pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
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


class MimoTtsProvider:
    """MiMo-V2.5-TTS provider via OpenAI-compatible API.

    行为契约:
    - mimo_api_key 配置: 强制走 MiMo TTS. 失败抛错, 不静默降级 stub.
    - mimo_api_key 缺失: fallback 到 stub (开发期占位).
    """

    def __init__(self) -> None:
        self._stub = StubTTSProvider()

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        voice_norm = _normalize_voice(voice)

        if not settings.mimo_api_key:
            logger.debug("mimo api key missing, fallback to stub: {!r}", text[:30])
            return await self._stub.synthesize(text, voice_norm)

        # 命中磁盘缓存
        disk_path, url_path = _audio_cache_path(text, voice_norm)
        if os.path.exists(disk_path):
            with open(disk_path, "rb") as f:
                audio_bytes = f.read()
            duration_ms = max(200, len(audio_bytes) // 48)
            return TtsResult(
                audio_bytes=audio_bytes,
                duration_ms=duration_ms,
                audio_url=url_path,
                source="mimo",
            )

        try:
            audio_bytes = self._synthesize_streaming(text, voice_norm)
        except Exception as e:
            logger.error("mimo tts call failed (no silent fallback): {}", e)
            raise

        if not audio_bytes:
            logger.error("mimo tts returned no audio payload (no silent fallback)")
            raise RuntimeError("mimo tts returned no audio")

        with open(disk_path, "wb") as f:
            f.write(audio_bytes)
        duration_ms = max(200, len(audio_bytes) // 48)
        logger.info("mimo tts ok voice={} bytes={} -> {}", voice_norm, len(audio_bytes), url_path)
        return TtsResult(
            audio_bytes=audio_bytes,
            duration_ms=duration_ms,
            audio_url=url_path,
            source="mimo",
        )

    def _synthesize_streaming(self, text: str, voice: str) -> bytes:
        """Call MiMo TTS with streaming PCM16, convert to WAV."""
        client = OpenAI(
            api_key=settings.mimo_api_key,
            base_url=settings.mimo_tts_base_url,
        )

        collected_pcm = bytearray()

        stream = client.chat.completions.create(
            model=settings.mimo_tts_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Read the following text clearly with natural pacing "
                        "and a warm, engaging tone."
                    ),
                },
                {"role": "assistant", "content": text},
            ],
            audio={"format": "pcm16", "voice": voice},
            stream=True,
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            audio = getattr(delta, "audio", None)
            if audio is not None and isinstance(audio, dict):
                pcm_bytes = base64.b64decode(audio["data"])
                collected_pcm.extend(pcm_bytes)

        if not collected_pcm:
            return b""

        return _pcm16_to_wav(bytes(collected_pcm))
