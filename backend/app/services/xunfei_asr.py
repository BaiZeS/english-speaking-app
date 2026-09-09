"""讯飞 ISE 语音评测 v2 provider.

协议文档: https://www.xfyun.cn/doc/Ise/IseAPI.html
端点 wss://ise-api.xfyun.cn/v2/open-ise, 全双工: 边发音频帧边收结果.

输入 audio 须为 PCM L16 16kHz 单声道裸字节 (Android AudioRecord 直录).
缺凭证或调用失败时回退 StubASRProvider.

参数与节奏以 scripts/smoke_xunfei_ise.py 的实火冒烟为准 (2026-09-08):
- streaming 版要求 ent=en_vip / tte=utf-8 / '\ufeff' BOM + [content]/[word]
  节点头, 且节点头对 read_word 是功能性的 (裸文本 read_word 实测报 48195
  SRecWrite error, 节点包装后正常);
- read_sentence 参考文本含 ( ) [ ] 时引擎不报错也不出终帧 (实测挂到
  server read timeout), 必须预先剔除;
- 帧 ≤19200B (base64 后 ≤26000, 20000B 实测被协议层拒), 预录音频可远快于
  实时发送: 3200B/10ms 下 17.9s 音频 2.6s 发完并拿到终帧, 逐词分不受影响.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
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

# 3200B = 100ms 音频 @ 16kHz 16bit mono; 实测远快于实时发包安全 (上限 19200B).
_FRAME_BYTES = 3200
_FRAME_PACE_S = 0.01

# 实测 ( ) [ ] 会让句子引擎静默挂死 (不出终帧), 只能剔除兜底.
_REF_FORBIDDEN_RE = re.compile(r"[()\[\]{}]")


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


def sanitize_ref_text(ref_text: str) -> str:
    """剔除 ISE 句子引擎不接受的括号类字符 (替换为空格, 不粘连单词)."""
    return _REF_FORBIDDEN_RE.sub(" ", ref_text)


def _ssb_text(ref_text: str, category: str) -> str:
    """流式版 text 字段: '\ufeff'+ 必要节点 + 换行 + 参考文本 (剔除禁用字符)."""
    node = "[word]" if category == "read_word" else "[content]"
    return f"﻿{node}\n{sanitize_ref_text(ref_text)}"


def _build_ssb_frame(ref_text: str, category: str) -> dict[str, object]:
    """第一帧: 建会话 (cmd=ssb), 不含音频.

    category: ISE 评测类型, "read_sentence" (句子) 或 "read_word" (单词).
    """
    return {
        "common": {"app_id": settings.xunfei_app_id},
        "business": {
            "aue": "raw",
            "auf": "audio/L16;rate=16000",
            "category": category,
            "cmd": "ssb",
            "ent": "en_vip",
            "sub": "ise",
            "text": _ssb_text(ref_text, category),
            "tte": "utf-8",
            "ttp_skip": True,
        },
        "data": {"status": 0},
    }


def _audio_frames(pcm: bytes) -> list[bytes]:
    """PCM 切成 _FRAME_BYTES 帧."""
    return [pcm[i : i + _FRAME_BYTES] for i in range(0, len(pcm), _FRAME_BYTES)]


class XunfeiASRProvider:
    """讯飞 ISE 语音评测 provider. 缺凭证时 fallback 到 stub."""

    def __init__(self) -> None:
        self._stub = StubASRProvider()

    async def recognize(
        self, audio: bytes, ref_text: str, category: str = "read_sentence"
    ) -> AsrResult:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            return await self._stub.recognize(audio, ref_text, category=category)
        if not audio:
            return await self._stub.recognize(audio, ref_text, category=category)

        try:
            xml = await asyncio.wait_for(
                self._evaluate(audio, ref_text, category),
                timeout=settings.xunfei_ise_timeout_s,
            )
        except Exception as e:
            logger.error(
                "xunfei ise call failed, falling back to stub | category={} pcm_bytes={} err={}",
                category,
                len(audio),
                e,
            )
            return await self._stub.recognize(audio, ref_text, category=category)

        recognized, word_scores = parse_ise_xml(xml)
        if not word_scores:
            logger.warning(
                "xunfei ise returned no word scores, falling back to stub | xml_len={}",
                len(xml),
            )
            return await self._stub.recognize(audio, ref_text, category=category)
        logger.info("xunfei ise ok words={} recognized={!r}", len(word_scores), recognized[:60])
        return AsrResult(recognized=recognized, word_scores=word_scores, source="xunfei")

    async def _evaluate(self, pcm: bytes, ref_text: str, category: str) -> str:
        """流式发送 PCM 到 ISE, 返回累加后的结果 XML 字符串.

        整体时长由 recognize 外层的 settings.xunfei_ise_timeout_s 硬顶;
        这里只负责建会话、发帧、收结果.
        """
        frames = _audio_frames(pcm)
        if not frames:
            return ""

        result_xml = ""
        error: str | None = None
        done = asyncio.Event()

        async with websockets.connect(_build_auth_url(), open_timeout=5.0) as ws:

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
            try:
                # 1. ssb 建会话 (无音频)
                await ws.send(json.dumps(_build_ssb_frame(ref_text, category), ensure_ascii=False))
                # 2. auw 音频帧: aus 8=一次性 (单帧), 1=首, 2=中, 4=末;
                #    data.status 1=中, 2=末
                n = len(frames)
                for idx, chunk in enumerate(frames):
                    if n == 1:
                        aus, status = 8, 2
                    elif idx == 0:
                        aus, status = 1, 1
                    elif idx == n - 1:
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
                    if idx != n - 1:
                        await asyncio.sleep(_FRAME_PACE_S)
                await done.wait()
            finally:
                recv_task.cancel()

        if error:
            raise RuntimeError(error)
        return result_xml
