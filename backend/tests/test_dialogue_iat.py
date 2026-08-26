from __future__ import annotations

import base64
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import dialogue
from app.api.v1.dialogue import _PLACEHOLDER_USER_TEXT, _apply_recognized_text
from app.main import app


def _clear_xunfei_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_key", "")
    monkeypatch.setattr("app.services.xunfei_iat.settings.xunfei_api_secret", "")


# ====== 占位符替换 helper ======


def test_apply_recognized_text_replaces_placeholder() -> None:
    history: list[dict[str, Any]] = [
        {"role": "assistant", "text": "What would you like to drink?"},
        {"role": "user", "text": _PLACEHOLDER_USER_TEXT},
    ]
    updated = _apply_recognized_text(history, "I would like a latte.")
    assert updated[-1]["text"] == "I would like a latte."
    assert updated[0]["text"] == "What would you like to drink?"
    # 原 history 不被改动
    assert history[-1]["text"] == _PLACEHOLDER_USER_TEXT


def test_apply_recognized_text_none_keeps_placeholder() -> None:
    history: list[dict[str, Any]] = [{"role": "user", "text": _PLACEHOLDER_USER_TEXT}]
    assert _apply_recognized_text(history, None) is history
    assert _apply_recognized_text(history, "") is history


def test_apply_recognized_text_only_replaces_placeholder_user_turn() -> None:
    history: list[dict[str, Any]] = [
        {"role": "user", "text": "My real earlier answer"},
        {"role": "assistant", "text": f"echo {_PLACEHOLDER_USER_TEXT}"},
        {"role": "user", "text": _PLACEHOLDER_USER_TEXT},
    ]
    updated = _apply_recognized_text(history, "Yes please.")
    assert updated[0]["text"] == "My real earlier answer"
    assert updated[1]["text"] == f"echo {_PLACEHOLDER_USER_TEXT}"
    assert updated[2]["text"] == "Yes please."


# ====== /dialogue/turn 端点 ======


@pytest.mark.asyncio
async def test_turn_without_credentials_returns_200_and_no_recognized_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_xunfei_credentials(monkeypatch)
    payload = {
        "scene_id": "ordering_coffee",
        "history": [
            {"role": "assistant", "text": "Good morning!"},
            {"role": "user", "text": _PLACEHOLDER_USER_TEXT},
        ],
        "user_audio_b64": base64.b64encode(b"\x00" * 3200).decode(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "stub"
    assert data["recognized_text"] is None
    assert data["reply_text"]


@pytest.mark.asyncio
async def test_turn_with_invalid_audio_b64_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_xunfei_credentials(monkeypatch)
    payload = {
        "scene_id": "ordering_coffee",
        "history": [{"role": "user", "text": _PLACEHOLDER_USER_TEXT}],
        "user_audio_b64": "!!!not-base64!!!",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200
    assert r.json()["recognized_text"] is None


class _FakeIatProvider:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.calls: list[bytes] = []

    async def transcribe(self, pcm: bytes) -> str | None:
        self.calls.append(pcm)
        return self.text


@pytest.mark.asyncio
async def test_turn_returns_recognized_text_when_transcription_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeIatProvider("I would like a cappuccino.")
    monkeypatch.setattr(dialogue, "_iat", fake)
    audio = b"\x01" * 1600
    payload = {
        "scene_id": "ordering_coffee",
        "history": [
            {"role": "assistant", "text": "What would you like?"},
            {"role": "user", "text": _PLACEHOLDER_USER_TEXT},
        ],
        "user_audio_b64": base64.b64encode(audio).decode(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["recognized_text"] == "I would like a cappuccino."
    assert fake.calls == [audio]
