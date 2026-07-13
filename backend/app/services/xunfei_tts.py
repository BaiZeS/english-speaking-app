from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import urlencode

import websockets
from loguru import logger

from app.config import settings
from app.services.interfaces import TtsResult
from app.services.stub_providers import StubTTSProvider

# 讯飞在线语音合成 v2 接口 (https://www.xfyun.cn/doc/tts/online_tts/API.html)
_TTS_HOST = "tts-api.xfyun.cn"
_TTS_PATH = "/v2/tts"
_TTS_URL = f"wss://{_TTS_HOST}{_TTS_PATH}"


def _build_auth_url() -> str:
    """按文档生成带鉴权参数的 wss 握手 URL.

    signature_origin = "host: {host}\\ndate: {date}\\nGET {path} HTTP/1.1"
    signature = base64(hmac_sha256(signature_origin, api_secret))
    authorization = base64(api_key="...", algorithm="hmac-sha256",
                           headers="host date request-line", signature="...")
    """
    # UTC RFC1123 格式, 时钟偏移超 300s 会被拒
    date = format_datetime(datetime.now(UTC), usegmt=True)
    signature_origin = f"host: {_TTS_HOST}\ndate: {date}\nGET {_TTS_PATH} HTTP/1.1"
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
    # 拼接鉴权参数 (host/date/authorization 需 url-encode, websockets 库会处理 query)
    params = urlencode({"host": _TTS_HOST, "date": date, "authorization": authorization})
    return f"{_TTS_URL}?{params}"


def _audio_cache_path(text: str, voice: str) -> tuple[str, str]:
    """返回 (磁盘绝对路径, /static 相对 URL 路径). 同 (text, voice) 命中同文件."""
    h = hashlib.sha256(f"{voice}::{text}".encode()).hexdigest()[:16]
    audio_dir = settings.tts_audio_dir
    os.makedirs(audio_dir, exist_ok=True)
    return os.path.join(audio_dir, f"{h}.mp3"), f"/static/tts/{h}.mp3"


class XunfeiTTSProvider:
    """讯飞在线语音合成 v2 provider. 缺凭证时 fallback 到 stub."""

    def __init__(self) -> None:
        self._stub = StubTTSProvider()

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            return await self._stub.synthesize(text, voice)

        # 命中磁盘缓存则直接返回 (同 text+voice 复用)
        disk_path, url_path = _audio_cache_path(text, voice)
        if os.path.exists(disk_path):
            duration_ms = max(200, len(text) * 80)
            with open(disk_path, "rb") as f:
                audio_bytes = f.read()
            return TtsResult(audio_bytes=audio_bytes, duration_ms=duration_ms, audio_url=url_path)

        vcn = voice or settings.xunfei_tts_default_vcn
        auth_url = _build_auth_url()
        frame = {
            "common": {"app_id": settings.xunfei_app_id},
            "business": {
                "aue": "lame",  # mp3
                "sfl": 1,
                "auf": "audio/L16;rate=16000",
                "vcn": vcn,
                "speed": 50,
                "volume": 50,
                "pitch": 50,
                "tte": "UTF8",
            },
            "data": {
                "status": 2,  # 一次性发完
                "text": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
            },
        }

        audio_chunks: list[bytes] = []
        try:
            async with websockets.connect(auth_url) as ws:
                await ws.send(json.dumps(frame))
                while True:
                    resp = json.loads(await ws.recv())
                    code = resp.get("code")
                    if code != 0:
                        msg = resp.get("message", "unknown")
                        logger.error("xunfei tts error code={} msg={}", code, msg)
                        raise RuntimeError(f"xunfei tts failed: {code} {msg}")
                    data = resp.get("data", {})
                    if audio_b64 := data.get("audio"):
                        audio_chunks.append(base64.b64decode(audio_b64))
                    if data.get("status") == 2:
                        break
        except Exception as e:
            logger.error("xunfei tts call failed, falling back to stub: {}", e)
            return await self._stub.synthesize(text, voice)

        if not audio_chunks:
            logger.warning("xunfei tts returned no audio, falling back to stub")
            return await self._stub.synthesize(text, voice)

        audio_bytes = b"".join(audio_chunks)
        with open(disk_path, "wb") as f:
            f.write(audio_bytes)
        duration_ms = max(200, len(text) * 80)
        logger.info("xunfei tts ok vcn={} bytes={} -> {}", vcn, len(audio_bytes), url_path)
        return TtsResult(audio_bytes=audio_bytes, duration_ms=duration_ms, audio_url=url_path)
