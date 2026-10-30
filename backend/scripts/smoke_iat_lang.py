"""真火冒烟: 讯飞 IAT 的 `zh_cn` 到底吃不吃英文/混读音频.

跑法 (需要 backend/.env 里的真凭据, 否则讯飞签名会拿 401、TTS 会静默退 stub):

    cd backend && ./.venv/bin/python scripts/smoke_iat_lang.py

结论 (2026-10-30 实测, 已写进方案 S2.4): `zh_cn` + `accent=mandarin` **原生支持中英
混读** —— 纯英文音频的转写与 `en_us` 实质等价, 而 `en_us` 对中文音频出乱码、对混读
丢中文。所以对话链路一条 `zh_cn` 通路就够, 学员不需要先声明自己要说哪种语言。

T2 把 `language` 变成 `transcribe()` 的真参数之后, 这个脚本不再需要 monkeypatch 首帧
构造器 —— 它现在就是那条改动的验收现场。
"""

from __future__ import annotations

import asyncio
import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.mimo_tts import MimoTtsProvider
from app.services.xunfei_iat import XunfeiIatProvider

CASES: list[tuple[str, str]] = [
    ("纯英文长句", "The Q3 spend came in about twelve percent under forecast."),
    ("纯英文短句", "Sure, I can send you the revised deck."),
    ("纯中文", "不好意思, 这份报告我还需要再核对一下数据。"),
    ("中英混读", "这个 report 的 deadline 是下周三。"),
]


async def pcm_of(text: str) -> bytes:
    """合成一句话 -> IAT 要的 16k 单声道 PCM (TTS 落盘是 48k, 整数比抽取)."""
    result = await MimoTtsProvider().synthesize(text, settings.mimo_tts_default_voice)
    with wave.open(io.BytesIO(result.audio_bytes), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        pcm = w.readframes(n)
    if ch == 2:
        pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 4))
    if sr == 48000:
        pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 6))
    return pcm


async def main() -> None:
    print(f"iat creds: {bool(settings.xunfei_app_id and settings.xunfei_api_key)}")
    for label, text in CASES:
        pcm = await pcm_of(text)
        row = f"{label:<10} 源文={text!r}\n"
        for lang in ("zh_cn", "en_us"):
            try:
                got = await asyncio.wait_for(XunfeiIatProvider().transcribe(pcm, language=lang), 20)
                row += f"    [{lang}] -> {got!r}\n"
            except Exception as exc:
                row += f"    [{lang}] FAIL {type(exc).__name__}: {exc}\n"
        print(row, flush=True)


asyncio.run(main())
