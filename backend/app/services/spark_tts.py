"""讯飞超拟人语音合成 API (Spark 超拟人 TTS).

文档: https://www.xfyun.cn/doc/spark/super%20smart-tts.html
端点: wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6 (固定)
鉴权: APIPassword 通过请求头 x-api-key 传入 (比 v2 老接口的 URL hmac-sha256 简单)
请求体 schema (与 v2 不同):
  {
    "header":   {"app_id": "...", "status": 2},
    "parameter": {
      "tts": {
        "vcn": "x5_EnUs_Grant_flow",
        "speed": 50, "volume": 50, "pitch": 50,
        "bgs": 0, "reg": 0, "rdn": 0, "rhy": 0,
        "audio": {"encoding": "lame", "sample_rate": 24000, ...}
      }
    },
    "payload": {"text": {"encoding": "utf8", "compress": "raw",
                          "format": "plain", "status": 2, "seq": 0, "text": "<base64>"}}
  }
响应是流式 base64 音频块, 累积到 status=2 (结束) 为完整音频.

超拟人相对 v2 老接口的优势: 模拟呼吸/叹气/语速变化等副语言现象, 英文更自然.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

import websockets
from loguru import logger

from app.config import settings
from app.services.interfaces import TtsResult
from app.services.stub_providers import StubTTSProvider
from app.services.xunfei_tts import XunfeiTTSProvider

# 有效 vcn 白名单 (目前文档列出的英文发音人; 中文 x5/x6 系列未列)
# 客户端传不在此名单的 voice 时, 静默回退到 default (会产生看似能用但音色不一致的怪事)
_KNOWN_VCNS: set[str] = {
    "x5_EnUs_Grant_flow",  # 成年女 美式英文 交互聊天 (默认)
    "x5_EnUs_Lila_flow",  # 成年女 美式英文 交互聊天 (备选)
}


def _normalize_voice(voice: str | None) -> str:
    """校验 vcn 合法性, 未知或缺失时回退到 default. 避免静默回退产生的不一致音色."""
    v = (voice or "").strip()
    if v in _KNOWN_VCNS:
        return v
    if v:
        logger.warning("unknown spark tts vcn {!r}, fallback to default", v)
    return settings.xunfei_tts_default_vcn


def _audio_cache_path(text: str, voice: str) -> tuple[str, str]:
    """同 (text, voice) 命中同文件. voice 在缓存前已规范化."""
    h = hashlib.sha256(f"spark::{voice}::{text}".encode()).hexdigest()[:16]
    audio_dir = settings.tts_audio_dir
    os.makedirs(audio_dir, exist_ok=True)
    return os.path.join(audio_dir, f"{h}.mp3"), f"/static/tts/{h}.mp3"


def _build_text_with_pauses(text: str) -> str:
    """句末标点后插 [p300] 静音停顿, 让句间节奏更自然 (超拟人的隐性优势之一).

    [p300] = 300ms 静音 (跟读场景需要更明显的句间停顿, 默认标点停顿偏短).
    """
    out: list[str] = []
    for _i, ch in enumerate(text):
        out.append(ch)
        if ch in ".?!":
            out.append("[p300]")
    return "".join(out)


def _build_request_frame(app_id: str, voice: str, text_b64: str) -> dict[str, object]:
    """按文档组装一次性合成 (status=2) 请求体."""
    return {
        "header": {"app_id": app_id, "status": 2},
        "parameter": {
            "tts": {
                "vcn": voice,
                "speed": 50,
                "volume": 50,
                "pitch": 50,
                "bgs": 0,
                "reg": 0,
                "rdn": 0,
                "rhy": 0,
                "audio": {
                    "encoding": "lame",  # mp3
                    "sample_rate": 24000,  # 比 v2 的 16k 更高, 听感更细腻
                    "channels": 1,
                    "bit_depth": 16,
                    "frame_size": 0,
                },
            }
        },
        "payload": {
            "text": {
                "encoding": "utf8",
                "compress": "raw",
                "format": "plain",
                "status": 2,
                "seq": 0,
                "text": text_b64,
            }
        },
    }


class SparkTtsProvider:
    """讯飞 Spark 超拟人合成 provider.

    缺 APIPassword / app_id 时 fallback 到 v2 老接口 (XunfeiTTSProvider),
    再降级到 stub. 这样部署期/降级期不影响本地开发跑通.
    """

    def __init__(self) -> None:
        self._stub = StubTTSProvider()
        self._legacy = XunfeiTTSProvider()

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        voice_norm = _normalize_voice(voice)

        # 无 Spark 凭据 → 退到 v2 老接口 (兼容未升级控制台的环境)
        if not (
            settings.xunfei_spark_tts_password
            and settings.xunfei_app_id
        ):
            logger.debug("spark tts creds missing, fallback to v2: {!r}", text[:30])
            return await self._legacy.synthesize(text, voice_norm)

        # 命中磁盘缓存
        disk_path, url_path = _audio_cache_path(text, voice_norm)
        if os.path.exists(disk_path):
            with open(disk_path, "rb") as f:
                audio_bytes = f.read()
            duration_ms = max(200, len(audio_bytes) // 48)  # mp3@24k 约 48B/ms
            return TtsResult(
                audio_bytes=audio_bytes, duration_ms=duration_ms, audio_url=url_path
            )

        try:
            audio_bytes = await self._synthesize(text, voice_norm)
        except Exception as e:
            logger.error("spark tts call failed, fallback to v2: {}", e)
            return await self._legacy.synthesize(text, voice_norm)

        if not audio_bytes:
            logger.warning("spark tts returned no audio, fallback to v2")
            return await self._legacy.synthesize(text, voice_norm)

        with open(disk_path, "wb") as f:
            f.write(audio_bytes)
        duration_ms = max(200, len(audio_bytes) // 48)
        logger.info(
            "spark tts ok vcn={} bytes={} -> {}", voice_norm, len(audio_bytes), url_path
        )
        return TtsResult(
            audio_bytes=audio_bytes, duration_ms=duration_ms, audio_url=url_path
        )

    async def _synthesize(self, text: str, voice_norm: str) -> bytes:
        """连接 wss, 一次性发送 status=2 请求, 累积流式返回的音频块."""
        text_with_pauses = _build_text_with_pauses(text)
        text_b64 = base64.b64encode(text_with_pauses.encode("utf-8")).decode("utf-8")
        frame = _build_request_frame(
            app_id=settings.xunfei_app_id, voice=voice_norm, text_b64=text_b64
        )

        # x-api-key 请求头鉴权 (文档"鉴权方式一").
        extra_headers = [("x-api-key", settings.xunfei_spark_tts_password)]
        url = settings.xunfei_spark_tts_url

        audio_chunks: list[bytes] = []

        async with websockets.connect(url, additional_headers=extra_headers) as ws:
            await ws.send(json.dumps(frame))
            while True:
                resp_raw = await ws.recv()
                resp = json.loads(resp_raw)
                header = resp.get("header") or {}
                code = header.get("code", 0)
                if code != 0:
                    sid = header.get("sid", "")
                    msg = header.get("message", "unknown")
                    raise RuntimeError(
                        f"spark tts code={code} sid={sid} msg={msg}"
                    )
                payload = resp.get("payload") or {}
                audio = payload.get("audio") or {}
                audio_b64 = audio.get("audio")
                if audio_b64:
                    audio_chunks.append(base64.b64decode(audio_b64))
                status = audio.get("status", 0)
                # status: 0=开始 1=中间 2=结束
                if status == 2:
                    break

        return b"".join(audio_chunks)
