from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.services.interfaces import AsrResult
from app.services.xunfei_asr import XunfeiASRProvider

# 精简的 ISE 结果 XML (hello + sil + world)
_FAKE_XML = (
    '<rec_paper><read_chapter total_score="4.0">'
    '<sentence><word content="hello" total_score="2.88">'
    '<syll content="hh ax"><phone content="hh"/></syll>'
    "</word>"
    '<word content="sil"/>'
    '<word content="world" total_score="3.89">'
    '<syll content="w er l d"><phone content="w"/></syll>'
    "</word></sentence></read_chapter></rec_paper>"
)


class _FakeRecv:
    """按调用序返回伪造的 ISE 响应: 若干 ack (code=0,status=1) + 终帧 (status=2, 含 base64 XML)."""

    def __init__(self) -> None:
        self._calls = 0

    async def recv(self) -> str:
        self._calls += 1
        # 模拟: 前 5 个是音频 ack, 第 6 个是终帧带结果
        if self._calls < 6:
            return '{"code":0,"data":{"status":1}}'
        xml_b64 = base64.b64encode(_FAKE_XML.encode()).decode()
        return f'{{"code":0,"data":{{"status":2,"data":"{xml_b64}"}}}}'


class _FakeWS:
    def __init__(self) -> None:
        self._recv = _FakeRecv()
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return await self._recv.recv()

    async def __aenter__(self) -> _FakeWS:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


@asynccontextmanager
async def _fake_connect(_url: str) -> AsyncIterator[_FakeWS]:
    ws = _FakeWS()
    yield ws


@pytest.mark.asyncio
async def test_falls_back_to_stub_when_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_app_id", "")
    p = XunfeiASRProvider()
    res = await p.recognize(audio=b"\x00", ref_text="Hello world")
    assert res.recognized == "Hello world"
    assert [w.word for w in res.word_scores] == ["Hello", "world"]


@pytest.mark.asyncio
async def test_recognize_parses_real_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """凭证齐全时走真实 ISE 路径 (websockets 被 monkeypatch 成假连接), 验证 XML 解析."""
    monkeypatch.setattr("app.services.xunfei_asr.websockets.connect", _fake_connect)
    # 确保 not-fallback 分支 (凭证非空). .env 里已有真实凭证, 这里显式 set 保证.
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_app_id", "f15f995b")
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_api_key", "fake_key")
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_api_secret", "fake_secret")

    p = XunfeiASRProvider()
    # PCM 字节内容无关 (假连接不解析), 但须非空且足够多帧触发 aus=1/2/4 路径.
    pcm = b"\x00" * 5120  # 4 帧
    res: AsrResult = await p.recognize(audio=pcm, ref_text="hello world")

    assert res.recognized == "hello world"
    assert [w.word for w in res.word_scores] == ["hello", "world"]
    # 2.88 * 20 = 57.6
    assert res.word_scores[0].score == pytest.approx(57.6)
    assert res.word_scores[0].ipa == "hh ax"
