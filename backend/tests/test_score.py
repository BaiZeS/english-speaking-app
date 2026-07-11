from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_score_returns_full_breakdown() -> None:
    payload = {
        "lesson_id": 1,
        "line_id": "nce1-L1-A1",
        "ref_text": "Excuse me",
        "mode": "k12",
        # tiny fake m4a header
        "audio": "AAAAGGZ0eXBpc29tAAAAAGlzbzZtcDQy",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data
    for k in ("pronunciation", "fluency", "completeness"):
        assert 0 <= data[k] <= 100
    assert isinstance(data["word_details"], list)
    assert data["word_details"][0]["word"] == "Excuse"


@pytest.mark.asyncio
async def test_score_rejects_empty_audio() -> None:
    payload = {
        "lesson_id": 1,
        "line_id": "L1",
        "ref_text": "hi",
        "mode": "k12",
        "audio": "",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"
