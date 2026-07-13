"""讯飞 ISE 语音评测 v2 provider.

协议文档: https://www.xfyun.cn/doc/Ise/IseAPI.html
端点 wss://ise-api.xfyun.cn/v2/open-ise, 全双工: 边发音频帧边收结果.

输入 audio 须为 PCM L16 16kHz 单声道裸字节 (Android AudioRecord 直录).
缺凭证或调用失败时回退 StubASRProvider.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import urlencode

import websockets
from loguru import logger

from app.config import settings
from app.services.interfaces import AsrResult
from app.services.ise_xml import parse_ise_xml
from app.services.stub_providers import StubASRProvider

# 讯飞 ISE v2 (https://www.xfyun.cn/doc/Ise/IseAPI.html)
_ISE_HOST = "ise-api.xfyun.cn"
_ISE_PATH = "/v2/open-ise"
_ISE_URL = f"wss://{_ISE_HOST}{_ISE_PATH}"

# 1280B = 40ms @ 16kHz 16bit mono (文档推荐)
_FRAME_BYTES = 1280


def _build_auth_url() -> str:
    """按文档生成带鉴权参数的 wss 握手 URL (与 TTS 同样的 hmac-sha256 方案)."""
    date = format_datetime(datetime.now(UTC), usegmt=True)
    signature_origin = f"host: {_ISE_HOST}\ndate: {date}\nGET {_ISE_PATH} HTTP/1.1"
    signature_sha = hmac.new(
        settings.xunfei_api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")
    authorization_origin = (
        f'api_key="{settings.xunfei_api_key}", '
        'algorithm="hmac-sha256", '
        'headers="host date request-line", '
        f'signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
    params = urlencode({"host": _ISE_HOST, "date": date, "authorization": authorization})
    return f"{_ISE_URL}?{params}"


def _build_ssb_frame(ref_text: str) -> dict[str, object]:
    """第一帧: 建会话 (cmd=ssb), 不含音频."""
    return {
        "common": {"app_id": settings.xunfei_app_id},
        "business": {
            "aue": "raw",
            "auf": "audio/L16;rate=16000",
            "category": "read_sentence",
            "cmd": "ssb",
            "ent": "en",
            "sub": "ise",
            "text": ref_text,
            "ttp_skip": True,
        },
        "data": {"status": 0},
    }


def _audio_frames(pcm: bytes) -> list[bytes]:
    """PCM 切成 1280B 帧."""
    return [pcm[i : i + _FRAME_BYTES] for i in range(0, len(pcm), _FRAME_BYTES)]


class XunfeiASRProvider:
    """讯飞 ISE 语音评测 provider. 缺凭证时 fallback 到 stub."""

    def __init__(self) -> None:
        self._stub = StubASRProvider()

    async def recognize(self, audio: bytes, ref_text: str) -> AsrResult:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            return await self._stub.recognize(audio, ref_text)
        if not audio:
            return await self._stub.recognize(audio, ref_text)

        try:
            xml = await self._evaluate(audio, ref_text)
        except Exception as e:
            logger.error("xunfei ise call failed, falling back to stub: {}", e)
            return await self._stub.recognize(audio, ref_text)

        recognized, word_scores = parse_ise_xml(xml)
        if not word_scores:
            logger.warning(
                "xunfei ise returned no word scores, falling back to stub | xml_len={}",
                len(xml),
            )
            return await self._stub.recognize(audio, ref_text)
        logger.info("xunfei ise ok words={} recognized={!r}", len(word_scores), recognized[:60])
        return AsrResult(recognized=recognized, word_scores=word_scores)

    async def _evaluate(self, pcm: bytes, ref_text: str) -> str:
        """流式发送 PCM 到 ISE, 返回累加后的结果 XML 字符串."""
        frames = _audio_frames(pcm)
        if not frames:
            return ""

        result_xml = ""
        error: str | None = None
        done = asyncio.Event()

        async with websockets.connect(_build_auth_url()) as ws:

            async def receiver() -> None:
                nonlocal result_xml, error
                try:
                    while True:
                        resp = json.loads(await ws.recv())
                        code = resp.get("code")
                        if code != 0:
                            error = f"ise code={code} msg={resp.get('message')}"
                            done.set()
                            return
                        data = resp.get("data") or {}
                        if dd := data.get("data"):
                            try:
                                result_xml += base64.b64decode(dd).decode("utf-8", errors="replace")
                            except Exception:
                                result_xml += dd
                        if data.get("status") == 2:
                            done.set()
                            return
                except Exception as e:
                    error = f"ise receiver exc: {e}"
                    done.set()

            recv_task = asyncio.create_task(receiver())

            # 1. ssb 建会话 (无音频)
            await ws.send(json.dumps(_build_ssb_frame(ref_text)))
            # 2. auw 音频帧: aus 1=首, 2=中, 4=末; data.status 1=中, 2=末
            for idx, chunk in enumerate(frames):
                if idx == 0:
                    aus, status = 1, 1
                elif idx == len(frames) - 1:
                    aus, status = 4, 2
                else:
                    aus, status = 2, 1
                await ws.send(
                    json.dumps(
                        {
                            "business": {"cmd": "auw", "aus": aus},
                            "data": {
                                "status": status,
                                "data": base64.b64encode(chunk).decode("utf-8"),
                            },
                        }
                    )
                )
                await asyncio.sleep(0.04)  # 40ms pacing (文档建议)

            await asyncio.wait_for(done.wait(), timeout=30)
            recv_task.cancel()

        if error:
            raise RuntimeError(error)
        return result_xml
