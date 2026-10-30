"""v3.0 语音条的合成: **请求内快路 + 软失败**.

方案 S2.5 的落点。为什么不是"合成失败就报错": 台词已经由 LLM 生成好了、已经落库了,
没有声音只是这一条气泡暂时放不出声, 把它翻成 503 等于**让学员为一次 TTS 抖动重答
一遍** —— 而重答会再烧一次 LLM、还会让会话里出现两颗一样的用户气泡。

所以这里的契约是: **拿到音频就给 URL, 拿不到就说"还没有"**, 由客户端按需
``GET /tts`` 兜底 (那条路本来就在, 是跟读/示范音的现成端点)。

预算 :data:`TTS_TURN_BUDGET_S` 被 ``tests/test_latency_budget.py`` 的求和表点名,
改它必须同批改那张表 —— 那条链的总额已经顶格 (25.0 ≤ 25.0), 没有余量。
"""

from __future__ import annotations

import asyncio

from loguru import logger

from app.services.mimo_tts import MimoTtsProvider

#: 一颗气泡在请求内等 TTS 的墙钟上限。实测冷合成 1.41-1.96s、磁盘缓存命中 ~0s,
#: 3.0s 覆盖 p95; 超了就软失败, 绝不为声音拖长整轮。
TTS_TURN_BUDGET_S = 3.0

_provider = MimoTtsProvider()


class LineAudio:
    """一次合成的结果: 有 URL 就能播, 没有就 ``pending`` 让客户端自己拉。"""

    __slots__ = ("audio_ms", "audio_pending", "audio_url")

    def __init__(self, audio_url: str | None, audio_ms: int, audio_pending: bool) -> None:
        self.audio_url = audio_url
        self.audio_ms = audio_ms
        self.audio_pending = audio_pending


async def synthesize_line(text: str, voice: str) -> LineAudio:
    """合成一句台词; **任何**失败 (未配置/超时/异常) 都只让 ``audio_pending=True``.

    未配置凭据时 ``MimoTtsProvider`` 会回落 stub —— stub 的假音频时长是算出来的,
    语音条画出来是真的但听着是电子音, 这是仓内既有的"占位可见"口径 (``source``
    字段透出), 本函数不额外拦它。
    """
    if not text.strip():
        return LineAudio(None, 0, False)
    try:
        result = await asyncio.wait_for(
            _provider.synthesize(text, voice), timeout=TTS_TURN_BUDGET_S
        )
    except TimeoutError:
        logger.warning("thread tts budget exceeded ({}s): {!r}", TTS_TURN_BUDGET_S, text[:40])
        return LineAudio(None, 0, True)
    except Exception as exc:
        logger.warning("thread tts soft-failed: {}: {}", type(exc).__name__, exc)
        return LineAudio(None, 0, True)
    return LineAudio(result.audio_url, result.duration_ms, False)
