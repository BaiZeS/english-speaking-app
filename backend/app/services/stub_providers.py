from __future__ import annotations

import hashlib

from app.services.interfaces import AsrResult, AsrWord, TtsResult
from app.services.wav import BYTES_PER_MS, pcm16_to_wav


class StubTTSProvider:
    """Deterministic placeholder TTS: **real (silent) WAV** + ``source="stub"``.

    P8 清理: 旧实现把 audio_bytes 塞成 ``STUB_TTS::<hash>`` 假 blob —— 任何
    真去解码它的播放器只会拿到 "corrupt media" 异常, 和"服务坏了"无法区分。
    现在返回与 MiMo 主路同规格的 24kHz/mono/PCM16 **静音** WAV (可播放、时
    长真实)。(text, voice) 的哈希仍然决定 audio_url; "这是占位音频"的判定
    依旧只看 ``source="stub"`` —— 客户端的 stub 警示与影子跟读 abort 守卫
    (PlayerViewModel 按 isStub 中断) 语义不变。
    """

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        h = hashlib.sha256(f"{voice}::{text}".encode()).hexdigest()[:16]
        # >=200ms, 每字符 ~80ms: 与旧 stub 相同时长口径, 只换字节内容为静音帧。
        duration_ms = max(200, len(text) * 80)
        silent_pcm = bytes(BYTES_PER_MS * duration_ms)  # PCM16 全零 == 静音
        return TtsResult(
            audio_bytes=pcm16_to_wav(silent_pcm),
            duration_ms=duration_ms,
            audio_url=f"/static/tts/{h}.wav",
            source="stub",  # 明确标记假音频, 前端可据此跳过/告警 (DEBUG-2026-07-22-TTS-A1)
        )


class StubASRProvider:
    """Recognizes the reference text perfectly when ref_text is provided."""

    async def recognize(
        self, audio: bytes, ref_text: str, category: str = "read_sentence"
    ) -> AsrResult:
        # category (read_sentence/read_word) 对 stub 无意义, 仅为签名兼容而接受.
        del category
        words = ref_text.split()
        return AsrResult(
            recognized=ref_text,
            word_scores=[AsrWord(word=w, score=95.0, ipa=None) for w in words],
        )
