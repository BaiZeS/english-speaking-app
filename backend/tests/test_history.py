from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_write_then_list_history(tmp_path, monkeypatch) -> None:
    # Use a unique device id to isolate from other test runs
    device_id = "test-device-history-001"
    write = {
        "device_id": device_id,
        "lesson_id": 1,
        "line_id": "L1",
        "audio_path": "/tmp/x.m4a",
        "score_total": 88.0,
        "score_pronunciation": 90.0,
        "score_fluency": 85.0,
        "score_completeness": 88.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post("/api/v1/history", json=write)
        assert r1.status_code == 201, r1.text
        r2 = await c.get("/api/v1/history", params={"device_id": device_id})
    assert r2.status_code == 200
    items = r2.json()
    assert len(items) >= 1
    assert items[0]["line_id"] == "L1"
    assert items[0]["score_total"] == 88.0


@pytest.mark.asyncio
async def test_history_write_returns_422_on_missing_fields() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/history", json={"device_id": "x"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_history_write_rejects_out_of_range_score() -> None:
    write = {
        "device_id": "test-device-range-001",
        "lesson_id": 1,
        "line_id": "L1",
        "audio_path": "/tmp/x.m4a",
        "score_total": 999.0,
        "score_pronunciation": 90.0,
        "score_fluency": 85.0,
        "score_completeness": 88.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/history", json=write)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_history_write_rejects_oversized_device_id() -> None:
    write = {
        "device_id": "x" * 200,
        "lesson_id": 1,
        "line_id": "L1",
        "audio_path": "/tmp/x.m4a",
        "score_total": 88.0,
        "score_pronunciation": 90.0,
        "score_fluency": 85.0,
        "score_completeness": 88.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/history", json=write)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
