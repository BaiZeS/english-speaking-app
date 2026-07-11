from __future__ import annotations

import pytest

from app.services.xunfei_asr import XunfeiASRProvider


@pytest.mark.asyncio
async def test_falls_back_to_stub_when_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_app_id", "")
    p = XunfeiASRProvider()
    res = await p.recognize(audio=b"\x00", ref_text="Hello world")
    assert res.recognized == "Hello world"
    assert [w.word for w in res.word_scores] == ["Hello", "world"]
