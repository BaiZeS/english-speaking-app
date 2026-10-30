import asyncio
import io
import sys
import wave

sys.path.insert(0, ".")
from app.config import settings
from app.services import xunfei_iat
from app.services.mimo_tts import MimoTtsProvider

ORIG = xunfei_iat._build_first_frame


def make_frame(language):
    def build(first_chunk, *, last):
        frame = ORIG(first_chunk, last=last)
        frame["business"] = {"language": language, "domain": "iat", "accent": "mandarin"}
        return frame

    return build


async def pcm_of(text):
    result = await MimoTtsProvider().synthesize(text, settings.mimo_tts_default_voice)
    raw = result.audio_bytes
    with wave.open(io.BytesIO(raw), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        pcm = w.readframes(n)
    if ch == 2:
        pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 4))
    if sr == 48000:
        pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 6))
    return pcm


CASES = [
    ("纯英文", "The Q3 spend came in about twelve percent under forecast."),
    ("纯英文短", "Sure, I can send you the revised deck."),
    ("纯中文", "不好意思，这份报告我还需要再核对一下数据。"),
    ("中英混读", "这个 report 的 deadline 是下周三。"),
]


async def main():
    for label, text in CASES:
        pcm = await pcm_of(text)
        line = f"{label} | 源文={text!r} | "
        for lang in ("zh_cn", "en_us"):
            xunfei_iat._build_first_frame = make_frame(lang)
            try:
                got = await asyncio.wait_for(xunfei_iat.XunfeiIatProvider()._transcribe(pcm), 15)
                line += f"[{lang}]={got!r}  "
            except Exception as exc:
                line += f"[{lang}]=ERR {type(exc).__name__}  "
        print(line, flush=True)


asyncio.run(main())
