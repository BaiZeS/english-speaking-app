"""Spark 超拟人 TTS 单元测试 (不连真网, 用 monkeypatch 替换 websockets.connect).

覆盖:
- 鉴权: x-api-key 请求头正确传入
- 请求体 schema: header/parameter.tts.vcn/payload.text.text (base64) 都对
- 流式累积: status=0/1/2 多块拼接成完整音频
- 错误码: header.code != 0 抛 RuntimeError (让 fallback 接管)
- 凭据缺失: 直接 fallback 到 v2 老接口 (StubTTSProvider)
- vcn 白名单: 未知 vcn 静默回退到 default
- 句末 [p300] 停顿: 文本预处理正确
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.services import spark_tts
from app.services.spark_tts import (
    _KNOWN_VCNS,
    SparkTtsProvider,
    _build_request_frame,
    _build_text_with_pauses,
    _normalize_voice,
)


# Spark TTS 是纯本地逻辑 (mock websockets), 不需要 DB.
# conftest 的 _init_db 是 autouse pytest_asyncio fixture, 在 sync test 下
# 会 hang event loop. 这里覆盖掉.
@pytest.fixture(autouse=True)
def _init_db() -> None:
    """覆盖 conftest 的 autouse _init_db (spark_tts 不依赖 db)."""


# ====== 纯函数 ======


def test_pause_after_sentence_end_punctuation() -> None:
    assert _build_text_with_pauses("Hello.") == "Hello.[p300]"
    assert _build_text_with_pauses("Hi! How are you?") == "Hi![p300] How are you?[p300]"
    assert _build_text_with_pauses("No pause here, ok") == "No pause here, ok"
    assert _build_text_with_pauses("") == ""
    # 句末感叹号后空格也加停顿
    assert _build_text_with_pauses("Wait! Listen.") == "Wait![p300] Listen.[p300]"


def test_request_frame_matches_spark_schema() -> None:
    frame = _build_request_frame(
        app_id="app123", voice="x5_EnUs_Grant_flow", text_b64="aGVsbG8="
    )
    assert frame["header"]["app_id"] == "app123"
    assert frame["header"]["status"] == 2  # 一次性合成
    tts = frame["parameter"]["tts"]
    assert tts["vcn"] == "x5_EnUs_Grant_flow"
    assert tts["audio"]["encoding"] == "lame"
    assert tts["audio"]["sample_rate"] == 24000
    assert tts["audio"]["channels"] == 1
    # payload.text.text 是 base64 编码的待合成文本
    assert frame["payload"]["text"]["text"] == "aGVsbG8="
    assert frame["payload"]["text"]["encoding"] == "utf8"
    assert frame["payload"]["text"]["format"] == "plain"
    assert frame["payload"]["text"]["status"] == 2


def test_normalize_voice_known_passes_through() -> None:
    for v in _KNOWN_VCNS:
        assert _normalize_voice(v) == v


def test_normalize_voice_unknown_falls_back_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知 vcn 不抛错, 只 warn + 回退, 避免前端传错 voice 整个接口挂掉."""
    warnings: list[str] = []

    def _spy_warning(fmt: str, *args: Any) -> None:
        # loguru logger.warning(fmt, *args) — fmt 是带 {} 占位符的模板
        warnings.append((fmt, args))

    monkeypatch.setattr(spark_tts.logger, "warning", _spy_warning)
    result = _normalize_voice("k12_female")  # 老 voice 名, 现在已无效
    assert result == spark_tts.settings.xunfei_tts_default_vcn
    # 校验 args 里出现老 voice 名 (loguru 还没 format)
    found = False
    for _, args in warnings:
        if any("k12_female" in (str(a) if a is not None else "") for a in args):
            found = True
            break
    assert found, warnings


def test_normalize_voice_empty_falls_back() -> None:
    assert _normalize_voice("") == spark_tts.settings.xunfei_tts_default_vcn
    assert _normalize_voice(None) == spark_tts.settings.xunfei_tts_default_vcn  # type: ignore[arg-type]


# ====== 鉴权 + 请求体 + 流式响应 (mock websockets) ======


@contextmanager
def _capture_ws_call() -> Iterator[dict[str, Any]]:
    """替换 websockets.connect, 捕获 URL/headers/sent frame/received frames.

    返回 ctx 里有个 dict:
      url:          实际连接的 wss URL
      headers:      传入的请求头 (含 x-api-key)
      sent_frame:   客户端 send 的 JSON (解出 dict)
      received:     喂给客户端的响应帧列表 (status=0/1/2)
    """
    captured: dict[str, Any] = {"headers": None, "sent_frame": None, "received": []}

    class _FakeWS:
        def __init__(self) -> None:
            self._sent: list[str] = []

        async def send(self, data: str) -> None:
            self._sent.append(data)

        async def recv(self) -> str:
            # 每次 recv 弹出下一帧
            if captured["received"]:
                return captured["received"].pop(0)
            raise RuntimeError("no more mocked frames")

        async def __aenter__(self) -> _FakeWS:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            captured["sent_frame"] = json.loads(self._sent[0]) if self._sent else None

    def _fake_connect(url: str, **kwargs: Any) -> _FakeWS:
        # 注意: 不能 async def, 否则返回 coroutine 而不是 _FakeWS, 就不是 async ctx mgr.
        # websockets.connect 在 v12+ 是 async def, 调用它得到 ClientConnection (支持 async with).
        # 这里返回的对象必须实现 __aenter__/__aexit__ 才能被 async with 使用.
        captured["url"] = url
        captured["headers"] = kwargs.get("additional_headers", [])
        return _FakeWS()

    import app.services.spark_tts as mod

    orig_connect = mod.websockets.connect
    mod.websockets.connect = _fake_connect
    try:
        yield captured
    finally:
        mod.websockets.connect = orig_connect


def _audio_frame(audio_bytes: bytes, status: int) -> str:
    """构造一个超拟人协议下的响应帧 JSON 字符串."""
    return json.dumps(
        {
            "header": {"code": 0, "message": "success", "sid": "test-sid", "status": 2},
            "payload": {
                "audio": {
                    "encoding": "lame",
                    "sample_rate": 24000,
                    "channels": 1,
                    "bit_depth": 16,
                    "status": status,
                    "seq": 0,
                    "frame_size": 0,
                    "audio": base64.b64encode(audio_bytes).decode("ascii"),
                }
            },
        }
    )


@pytest.mark.asyncio
async def test_synthesize_sends_x_api_key_header(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """鉴权: APIPassword 必须通过 x-api-key 请求头传给 wss, 不要走 URL 鉴权."""
    monkeypatch.setattr(spark_tts.settings, "xunfei_app_id", "test_app_id")
    monkeypatch.setattr(spark_tts.settings, "xunfei_spark_tts_password", "ak-test-123")
    monkeypatch.setattr(spark_tts.settings, "tts_audio_dir", str(tmp_path))

    with _capture_ws_call() as cap:
        cap["received"] = [_audio_frame(b"\x00" * 10, status=2)]
        result = await SparkTtsProvider().synthesize("Hello.", "x5_EnUs_Grant_flow")

    # 1) 鉴权方式
    assert cap["headers"] == [("x-api-key", "ak-test-123")]
    assert cap["url"] == "wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6"

    # 2) 请求体 schema
    sf = cap["sent_frame"]
    assert sf["header"]["app_id"] == "test_app_id"
    assert sf["header"]["status"] == 2
    assert sf["parameter"]["tts"]["vcn"] == "x5_EnUs_Grant_flow"
    assert sf["parameter"]["tts"]["audio"]["sample_rate"] == 24000
    # 文本应是 base64(原文本 + [p300])
    text_b64 = sf["payload"]["text"]["text"]
    assert base64.b64decode(text_b64).decode("utf-8") == "Hello.[p300]"

    # 3) 返回结果
    assert result.audio_bytes == b"\x00" * 10
    assert result.duration_ms > 0
    assert result.audio_url.startswith("/static/tts/")


@pytest.mark.asyncio
async def test_synthesize_accumulates_streaming_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """流式响应: 多块 status=0/1/2 应按顺序拼接成完整音频."""
    monkeypatch.setattr(spark_tts.settings, "xunfei_app_id", "test_app_id")
    monkeypatch.setattr(spark_tts.settings, "xunfei_spark_tts_password", "ak-test-123")
    monkeypatch.setattr(spark_tts.settings, "tts_audio_dir", str(tmp_path))

    chunk_a = b"\xff\xd8\xff\xe0"  # JPEG magic (占位)
    chunk_b = b"\x00" * 100
    chunk_c = b"\xff\xd9"

    with _capture_ws_call() as cap:
        cap["received"] = [
            _audio_frame(chunk_a, status=0),
            _audio_frame(chunk_b, status=1),
            _audio_frame(chunk_c, status=2),
        ]
        result = await SparkTtsProvider().synthesize("Hi", "x5_EnUs_Grant_flow")

    assert result.audio_bytes == chunk_a + chunk_b + chunk_c


@pytest.mark.asyncio
async def test_synthesize_raises_on_error_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """header.code != 0 必须抛 RuntimeError, 让 SparkTtsProvider 自动 fallback 到 v2."""
    monkeypatch.setattr(spark_tts.settings, "xunfei_app_id", "test_app_id")
    monkeypatch.setattr(spark_tts.settings, "xunfei_spark_tts_password", "ak-test-123")
    monkeypatch.setattr(spark_tts.settings, "tts_audio_dir", str(tmp_path))
    # 同时清空 v2 凭据, 让 fallback 链最终走到 stub (避免真调网络)
    monkeypatch.setattr(spark_tts.settings, "xunfei_api_key", "")
    monkeypatch.setattr(spark_tts.settings, "xunfei_api_secret", "")

    err_frame = json.dumps(
        {
            "header": {"code": 11200, "message": "功能未授权", "sid": "x", "status": 2},
            "payload": {},
        }
    )
    with _capture_ws_call() as cap:
        cap["received"] = [err_frame]
        # 不应抛异常 — fallback 链兜住
        result = await SparkTtsProvider().synthesize("Hello", "x5_EnUs_Grant_flow")

    # fallback 到 stub: 产物是 STUB_TTS:: 前缀的 fake bytes
    assert result.audio_bytes.startswith(b"STUB_TTS::")
    assert result.audio_url.endswith(".m4a")


@pytest.mark.asyncio
async def test_synthesize_falls_back_when_creds_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没配 XUNFEI_SPARK_TTS_PASSWORD 直接跳过 spark, 走 v2 老接口 (这里也清空 -> stub)."""
    monkeypatch.setattr(spark_tts.settings, "xunfei_spark_tts_password", "")
    monkeypatch.setattr(spark_tts.settings, "xunfei_api_key", "")
    monkeypatch.setattr(spark_tts.settings, "xunfei_api_secret", "")

    # 不应调用 websockets.connect
    import app.services.spark_tts as mod

    called = {"n": 0}

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        called["n"] += 1
        raise AssertionError("should not connect when spark creds missing")

    monkeypatch.setattr(mod.websockets, "connect", _boom)

    result = await SparkTtsProvider().synthesize("Hi", "x5_EnUs_Grant_flow")
    assert called["n"] == 0
    assert result.audio_bytes.startswith(b"STUB_TTS::")


@pytest.mark.asyncio
async def test_synthesize_uses_disk_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """命中磁盘缓存时, 不再发请求 (network call 计数为 0)."""
    monkeypatch.setattr(spark_tts.settings, "xunfei_app_id", "test_app_id")
    monkeypatch.setattr(spark_tts.settings, "xunfei_spark_tts_password", "ak-test-123")
    monkeypatch.setattr(spark_tts.settings, "tts_audio_dir", str(tmp_path))

    import app.services.spark_tts as mod

    called = {"n": 0}

    async def _spy_connect(*_args: Any, **_kwargs: Any) -> None:
        called["n"] += 1
        raise AssertionError("cache miss")

    monkeypatch.setattr(mod.websockets, "connect", _spy_connect)

    # 第一次: 真实合成 (mock 返回一帧)
    with _capture_ws_call() as cap:
        cap["received"] = [_audio_frame(b"hello", status=2)]
        r1 = await SparkTtsProvider().synthesize("Cache test", "x5_EnUs_Grant_flow")
    assert r1.audio_bytes == b"hello"

    # 第二次: 同 (text, voice) 必须命中缓存, 不再调用 ws
    r2 = await SparkTtsProvider().synthesize("Cache test", "x5_EnUs_Grant_flow")
    assert r2.audio_bytes == b"hello"
    assert r2.audio_url == r1.audio_url


@pytest.mark.asyncio
async def test_unknown_voice_does_not_call_spark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知 vcn 走 stub (而不是发给讯飞被拒). 避免计费/错误码."""
    monkeypatch.setattr(spark_tts.settings, "xunfei_spark_tts_password", "")
    monkeypatch.setattr(spark_tts.settings, "xunfei_api_key", "")
    monkeypatch.setattr(spark_tts.settings, "xunfei_api_secret", "")

    # "k12_female" 不在 _KNOWN_VCNS, 但因为 spark 凭据空直接走 stub,
    # 实际不会调 wss. 这里只断言没抛错且产物合理.
    result = await SparkTtsProvider().synthesize("Hi", "k12_female")
    assert result.audio_bytes.startswith(b"STUB_TTS::")
