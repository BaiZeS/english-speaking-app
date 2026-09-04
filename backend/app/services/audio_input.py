"""客户端上传音频的解码与派生指标 (``/score`` 与 drill 评分共用).

两个评分入口 (``POST /score`` 的 ``ScoreRequest.audio`` 和 P2 的
``POST /sessions/{id}/step``) 收的都是 base64 字符串. 这里收口两件事:

* :func:`decode_audio` —— pydantic v2 把 JSON body 里的 ``bytes`` 字段解成
  "base64 文本自身的字节" (而不是解码后的字节), 所以要再 base64 解一次才是裸 PCM;
  不是合法 base64 时按原始字节透传.
* :func:`estimate_speech_rate_wpm` —— 由 PCM 长度推音频时长, 再推语速.
  语速是流利度维度 (``app.scoring.read_along``) 与能力画像 §5.6 的输入之一,
  必须和分数同源, 所以两处评分都走这一个实现.

放在 service 层而不是 ``api/v1/score.py``, 是为了让 ``app.services.drill_grader``
复用时不出现 service → api 的反向依赖.
"""

from __future__ import annotations

import base64
import binascii

# PCM L16 16kHz mono: 16000 samples/s * 2 bytes/sample
_PCM_BYTES_PER_SECOND = 32000.0
# 音频过短 (<0.3s) 时回退到旧的 4s 预算窗口, 避免除零/不合理语速
_FALLBACK_DURATION_S = 4.0
_MIN_DURATION_S = 0.3


def decode_audio(audio: bytes) -> bytes:
    """Decode the request audio to raw PCM bytes.

    The Android client sends audio as a base64 string in the JSON body. Pydantic v2
    loads a JSON ``bytes`` field as the base64 string's own bytes (not decoded), so we
    detect and decode base64 here. Falls back to raw bytes if not valid base64.
    """
    try:
        return base64.b64decode(audio, validate=True)
    except (binascii.Error, ValueError):
        return bytes(audio)


def pcm_duration_s(audio_bytes: bytes) -> float:
    """音频时长 (秒): PCM L16 16kHz mono -> 32000 B/s."""
    return len(audio_bytes) / _PCM_BYTES_PER_SECOND


def estimate_speech_rate_wpm(word_count: int, audio_bytes: bytes) -> float:
    """Estimate speech rate (words/min) from the real audio duration.

    Audio is raw PCM L16 16kHz mono, so duration = len / 32000 seconds.
    Falls back to the old fixed 4s budget window for very short clips.
    """
    duration_s = pcm_duration_s(audio_bytes)
    if duration_s < _MIN_DURATION_S:
        duration_s = _FALLBACK_DURATION_S
    return word_count / duration_s * 60.0


def speech_rate_from_recognition(recognized: str, audio_bytes: bytes) -> float:
    """按 ISE/IAT 识别出的词数 + 真实音频时长推语速 (空识别按 1 词, 与 /score 一致)."""
    word_count = max(1, len(recognized.split()))
    return estimate_speech_rate_wpm(word_count, audio_bytes)
