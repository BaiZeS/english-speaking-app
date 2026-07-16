from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_dialogue_generate_stub_returns_placeholder_scene() -> None:
    payload = {"scene": "ordering_coffee", "mode": "k12"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/generate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "lines" in data
    assert isinstance(data["lines"], list)
    assert data["status"] == "stub"


@pytest.mark.asyncio
async def test_dialogue_turn_stub_echoes_user_input() -> None:
    payload = {
        "scene_id": "ordering_coffee",
        "history": [{"role": "user", "text": "Hi"}],
        "user_audio_b64": "AAAA",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "stub"
    assert "reply_text" in data


@pytest.mark.asyncio
async def test_dialogue_generate_includes_opening_and_suggested_reply() -> None:
    payload = {"scene": "ordering_coffee", "mode": "adult"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/generate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Ordering coffee"
    assert data["lines"][0]["role"] == "assistant"
    assert data["suggested_reply"]


@pytest.mark.asyncio
async def test_dialogue_turn_returns_next_prompt_and_suggestion() -> None:
    payload = {
        "scene_id": "ordering_coffee",
        "history": [
            {"role": "assistant", "text": "Good morning!"},
            {"role": "user", "text": "I would like coffee."},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["reply_text"]
    assert data["suggested_reply"]
