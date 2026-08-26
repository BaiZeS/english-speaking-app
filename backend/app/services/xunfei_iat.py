"""讯飞 IAT 语音听写 v2 provider (自由对话的真实转写).

协议文档: https://www.xfyun.cn/doc/asr/voicedictation/API.html
端点 wss://iat-api.xfyun.cn/v2/iat, 全双工: 边发音频帧边收结果.

输入 audio 须为 PCM L16 16kHz 单声道裸字节 (Android AudioRecord 直录).
与 ISE (app/services/xunfei_asr.py) 共用同一套 app_id/api_key/api_secret,
鉴权 URL 的 hmac-sha256 request-line 签名方案也完全一致, 仅 host/path 不同.

协议要点 (与 ISE 的差异, 均出自官方文档):
- 首帧 = common + business + data(status=0, format, encoding, audio=首块),
  第一块音频必须随首帧以 status=0 上传, 否则报 10165;
- 音频在 data.audio 字段 (不是 ISE 的 data.data), 每帧都要带
  status/format/encoding;
- 响应里结果是 data.result 明文 JSON (不是 ISE 的 base64 data.data),
  按 sn 累积 ws[].cw[].w;
- dwa=wpgs 动态修正仅中文支持, 英文不开; 合并函数仍兼容 pgs/rpl 形状
  作防御 (中文场景或协议演进).
缺凭证或调用失败时返回 None, 绝不抛异常, 由调用方保留占位行为.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlencode

import websockets
from loguru import logger

from app.config import settings

# 讯飞 IAT v2 (https://www.xfyun.cn/doc/asr/voicedictation/API.html)
_IAT_HOST = "iat-api.xfyun.cn"
_IAT_PATH = "/v2/iat"
_IAT_URL = f"wss://{_IAT_HOST}{_IAT_PATH}"

# 1280B = 40ms @ 16kHz 16bit mono (文档推荐)
_FRAME_BYTES = 1280


def _build_auth_url() -> str:
    """按文档生成带鉴权参数的 wss 握手 URL (与 ISE 同样的 hmac-sha256 方案)."""
    date = format_datetime(datetime.now(UTC), usegmt=True)
    signature_origin = f"host: {_IAT_HOST}\ndate: {date}\nGET {_IAT_PATH} HTTP/1.1"
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
    params = urlencode({"host": _IAT_HOST, "date": date, "authorization": authorization})
    return f"{_IAT_URL}?{params}"


def _build_first_frame(first_chunk: bytes, *, last: bool) -> dict[str, object]:
    """第一帧: 建会话 + 首块音频.

    文档要求第一块音频必须随首帧上传且带 format/encoding (否则 10165
    status 非法). accent 为必传字段, 非中文统一 mandarin. 音频只有一帧时
    首帧即末帧, status 直接给 2.
    """
    return {
        "common": {"app_id": settings.xunfei_app_id},
        "business": {
            "language": "en_us",
            "domain": "iat",
            "accent": "mandarin",
        },
        "data": {
            "status": 2 if last else 0,
            "format": "audio/L16;rate=16000",
            "encoding": "raw",
            "audio": base64.b64encode(first_chunk).decode("utf-8"),
        },
    }


def _audio_frames(pcm: bytes) -> list[bytes]:
    """PCM 切成 1280B 帧."""
    return [pcm[i : i + _FRAME_BYTES] for i in range(0, len(pcm), _FRAME_BYTES)]


def _result_text(result: dict[str, Any]) -> str:
    """把单个结果块的 ws[] -> cw[] -> w 拼成文本."""
    parts: list[str] = []
    for ws_block in result.get("ws") or []:
        for cw in ws_block.get("cw") or []:
            word = cw.get("w")
            if word:
                parts.append(str(word))
    return "".join(parts)


def merge_wpgs_chunk(segments: dict[int, str], result: dict[str, Any]) -> None:
    """把一个 wpgs 动态修正结果块并入按 sn 索引的片段表.

    pgs="apd": 直接追加 (写入当前 sn).
    pgs="rpl": 先删除 rg=[start,end] 闭区间内的旧片段, 再写入当前 sn.
    无 pgs 字段时按追加处理 (未开 dwa 时的普通结果).
    """
    sn = result.get("sn")
    if not isinstance(sn, int):
        return
    if result.get("pgs") == "rpl":
        rg = result.get("rg")
        if isinstance(rg, list) and len(rg) == 2:
            start, end = int(rg[0]), int(rg[1])
            for old_sn in range(start, end + 1):
                segments.pop(old_sn, None)
    segments[sn] = _result_text(result)


def finalize_wpgs(segments: dict[int, str]) -> str:
    """按 sn 升序拼接全部片段, 得到最终转写文本."""
    return "".join(segments[sn] for sn in sorted(segments)).strip()


class XunfeiIatProvider:
    """讯飞 IAT 语音听写 provider. 缺凭证/空音频/任何失败一律返回 None."""

    async def transcribe(self, pcm: bytes) -> str | None:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            logger.debug("xunfei iat skipped: credentials not configured")
            return None
        if not pcm:
            return None

        try:
            text = await self._transcribe(pcm)
        except Exception as e:
            logger.error("xunfei iat call failed: {}", e)
            return None

        if not text:
            logger.warning("xunfei iat returned empty result | audio_len={}", len(pcm))
            return None
        logger.info("xunfei iat ok text={!r}", text[:60])
        return text

    async def _transcribe(self, pcm: bytes) -> str:
        """流式发送 PCM 到 IAT, 用 wpgs 规则累积并返回最终文本."""
        frames = _audio_frames(pcm)
        if not frames:
            return ""

        segments: dict[int, str] = {}
        error: str | None = None
        done = asyncio.Event()

        async with websockets.connect(_build_auth_url()) as ws:

            async def receiver() -> None:
                nonlocal error
                try:
                    while True:
                        resp = json.loads(await ws.recv())
                        code = resp.get("code")
                        if code != 0:
                            error = f"iat code={code} msg={resp.get('message')}"
                            done.set()
                            return
                        data = resp.get("data") or {}
                        # IAT 结果是 data.result 明文 JSON (区别于 ISE 的 base64)
                        result = data.get("result")
                        if isinstance(result, dict):
                            merge_wpgs_chunk(segments, result)
                        if data.get("status") == 2:
                            done.set()
                            return
                except Exception as e:
                    error = f"iat receiver exc: {e}"
                    done.set()

            recv_task = asyncio.create_task(receiver())

            # 1. 首帧: 建会话 + 首块音频 (status=0; 单帧音频直接 status=2)
            await ws.send(json.dumps(_build_first_frame(frames[0], last=len(frames) == 1)))
            await asyncio.sleep(0.04)  # 40ms pacing (文档建议)
            # 2. 后续音频帧: data.status 1=中间帧, 2=末帧; 每帧必带 format/encoding
            for idx, chunk in enumerate(frames[1:], start=1):
                status = 2 if idx == len(frames) - 1 else 1
                await ws.send(
                    json.dumps(
                        {
                            "data": {
                                "status": status,
                                "format": "audio/L16;rate=16000",
                                "encoding": "raw",
                                "audio": base64.b64encode(chunk).decode("utf-8"),
                            }
                        }
                    )
                )
                await asyncio.sleep(0.04)  # 40ms pacing (文档建议)

            await asyncio.wait_for(done.wait(), timeout=30)
            recv_task.cancel()

        if error:
            raise RuntimeError(error)
        return finalize_wpgs(segments)
