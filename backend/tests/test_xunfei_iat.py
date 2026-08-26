from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest

from app.services.xunfei_iat import (
    XunfeiIatProvider,
    finalize_wpgs,
    merge_wpgs_chunk,
)


def _chunk(
    sn: int,
    words: list[str],
    *,
    pgs: str | None = None,
    rg: list[int] | None = None,
    last: bool = False,
) -> dict[str, object]:
    """构造一个 IAT 结果块 (data.result 的 JSON 形状)."""
    result: dict[str, object] = {
        "sn": sn,
        "ls": last,
        "ws": [{"bg": 0, "cw": [{"w": w, "sc": 0} for w in words]}],
    }
    if pgs is not None:
        result["pgs"] = pgs
    if rg is not None:
        result["rg"] = rg
    return result


def _iat_response(status: int, result: dict[str, object] | None = None) -> str:
    """构造一个 IAT websocket 响应 (官方协议: data.result 为明文 JSON)."""
    data: dict[str, object] = {"status": status}
    if result is not None:
        data["result"] = result
    return json.dumps({"code": 0, "message": "success", "data": data})


# ====== wpgs 合并逻辑 ======


def test_wpgs_merge_apd_appends_segments() -> None:
    segments: dict[int, str] = {}
    merge_wpgs_chunk(segments, _chunk(1, ["hello "], pgs="apd"))
    merge_wpgs_chunk(segments, _chunk(2, ["world"], pgs="apd", last=True))
    assert finalize_wpgs(segments) == "hello world"


def test_wpgs_merge_rpl_replaces_single_segment() -> None:
    segments: dict[int, str] = {}
    merge_wpgs_chunk(segments, _chunk(1, ["good "], pgs="apd"))
    merge_wpgs_chunk(segments, _chunk(2, ["morning"], pgs="apd"))
    # 动态修正: sn=2 被 sn=3 替换
    merge_wpgs_chunk(segments, _chunk(3, ["afternoon"], pgs="rpl", rg=[2, 2], last=True))
    assert finalize_wpgs(segments) == "good afternoon"


def test_wpgs_merge_rpl_replaces_sn_range() -> None:
    segments: dict[int, str] = {}
    merge_wpgs_chunk(segments, _chunk(1, ["one "], pgs="apd"))
    merge_wpgs_chunk(segments, _chunk(2, ["too "], pgs="apd"))
    merge_wpgs_chunk(segments, _chunk(3, ["tree "], pgs="apd"))
    # 一次替换 sn 2..3 两个片段, 之后再追加
    merge_wpgs_chunk(segments, _chunk(4, ["two three "], pgs="rpl", rg=[2, 3]))
    merge_wpgs_chunk(segments, _chunk(5, ["four"], pgs="apd", last=True))
    assert finalize_wpgs(segments) == "one two three four"


def test_wpgs_merge_without_pgs_appends() -> None:
    segments: dict[int, str] = {}
    merge_wpgs_chunk(segments, _chunk(1, ["plain"]))
    assert finalize_wpgs(segments) == "plain"


# ====== 凭证/空音频守卫 ======


@pytest.mark.asyncio
async def test_transcribe_returns_none_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_key", "")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_secret", "")
    assert await XunfeiIatProvider().transcribe(b"\x00" * 3200) is None


@pytest.mark.asyncio
async def test_transcribe_returns_none_for_empty_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_app_id", "f15f995b")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_key", "fake_key")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_secret", "fake_secret")
    assert await XunfeiIatProvider().transcribe(b"") is None


# ====== 全链路 (假 websocket) ======


class _FakeWS:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        if not self._responses:
            raise RuntimeError("fake ws: no scripted responses left")
        return self._responses.pop(0)

    async def __aenter__(self) -> _FakeWS:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _make_fake_connect(
    responses: list[str],
) -> tuple[Callable[[str], AsyncIterator[_FakeWS]], list[_FakeWS]]:
    opened: list[_FakeWS] = []

    @asynccontextmanager
    async def fake_connect(_url: str) -> AsyncIterator[_FakeWS]:
        ws = _FakeWS(responses)
        opened.append(ws)
        yield ws

    return fake_connect, opened


def _set_fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_app_id", "f15f995b")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_key", "fake_key")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_secret", "fake_secret")


@pytest.mark.asyncio
async def test_transcribe_streams_frames_and_merges_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """凭证齐全时走真实 IAT 路径 (websockets 被 monkeypatch 成假连接)."""
    responses = [
        _iat_response(1, _chunk(1, ["I would "])),
        _iat_response(1, _chunk(2, ["like tea"])),
        # 防御性: 即使出现 rpl 形状 (中文场景/协议演进) 也能正确合并
        _iat_response(2, _chunk(3, ["like coffee"], pgs="rpl", rg=[2, 2], last=True)),
    ]
    fake_connect, opened = _make_fake_connect(responses)
    monkeypatch.setattr("app.services.xunfei_iat.websockets.connect", fake_connect)
    _set_fake_credentials(monkeypatch)

    pcm = b"\x00" * 5120  # 4 帧
    text = await XunfeiIatProvider().transcribe(pcm)

    assert text == "I would like coffee"

    # 帧协议: 首帧带 status=0 + 首块音频, 之后 3 个音频帧, 末帧 status=2
    ws = opened[0]
    assert len(ws.sent) == 4
    first = json.loads(ws.sent[0])
    assert first["common"]["app_id"] == "f15f995b"
    assert first["business"]["domain"] == "iat"
    assert first["business"]["language"] == "en_us"
    assert first["business"]["accent"] == "mandarin"
    assert "dwa" not in first["business"]  # 动态修正仅中文支持, 英文不开
    assert first["data"]["status"] == 0
    assert first["data"]["format"] == "audio/L16;rate=16000"
    assert first["data"]["encoding"] == "raw"
    assert base64.b64decode(first["data"]["audio"]) == pcm[0:1280]
    for idx in range(1, 4):
        frame = json.loads(ws.sent[idx])
        assert "business" not in frame  # IAT 音频帧不带 business
        expected_status = 2 if idx == 3 else 1
        assert frame["data"]["status"] == expected_status
        assert frame["data"]["format"] == "audio/L16;rate=16000"
        assert frame["data"]["encoding"] == "raw"
        assert base64.b64decode(frame["data"]["audio"]) == pcm[idx * 1280 : (idx + 1) * 1280]


@pytest.mark.asyncio
async def test_transcribe_single_frame_audio_sends_status_2_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """音频不足一帧以上时, 首帧即末帧 (status=2), 否则服务端等不到结束标识."""
    responses = [_iat_response(2, _chunk(1, ["hi"], last=True))]
    fake_connect, opened = _make_fake_connect(responses)
    monkeypatch.setattr("app.services.xunfei_iat.websockets.connect", fake_connect)
    _set_fake_credentials(monkeypatch)

    text = await XunfeiIatProvider().transcribe(b"\x00" * 640)

    assert text == "hi"
    ws = opened[0]
    assert len(ws.sent) == 1
    only = json.loads(ws.sent[0])
    assert only["data"]["status"] == 2


@pytest.mark.asyncio
async def test_transcribe_returns_none_on_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [json.dumps({"code": 1001, "message": "auth failed", "data": {"status": 1}})]
    fake_connect, _opened = _make_fake_connect(responses)
    monkeypatch.setattr("app.services.xunfei_iat.websockets.connect", fake_connect)
    _set_fake_credentials(monkeypatch)

    assert await XunfeiIatProvider().transcribe(b"\x00" * 2560) is None
