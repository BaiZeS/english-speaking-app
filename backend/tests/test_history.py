from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import scene_store

from .test_scene_store import write_course


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


@pytest.mark.asyncio
async def test_history_kind_and_label_for_scene_and_textbook_rows(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P8 §5.7 / T9-2f: 情景课收工行在 /history 里必须给出可读标题, 不再是裸 line_id.

    kind: scene_course (book=="scenes") vs lesson (课本行); label:
    curated 课名命中 -> 「课名 · 实战对话」, 未命中 -> 诚实兜底「情景课 · 实战对话」,
    课本行沿用 line_id (旧客户端零破坏, 新字段 add-only)。
    """
    write_course(tmp_path, "scene_latte", "daily", title="点一杯拿铁")
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    try:
        device_id = "test-device-scene-kind-001"

        async def post(c: AsyncClient, book: str, line_id: str, audio_path: str) -> None:
            r = await c.post(
                "/api/v1/history",
                json={
                    "device_id": device_id,
                    "book": book,
                    "lesson_id": 0,
                    "line_id": line_id,
                    "audio_path": audio_path,
                    "score_total": 80.0,
                    "score_pronunciation": 80.0,
                    "score_fluency": 80.0,
                    "score_completeness": 80.0,
                },
            )
            assert r.status_code == 201, r.text

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await post(c, "scenes", "s1-a", "scene_latte")
            await post(c, "scenes", "s2-a", "scene_ghost")
            await post(c, "nce1", "L1", "/tmp/x.m4a")
            r = await c.get("/api/v1/history", params={"device_id": device_id})
        items = {i["line_id"]: i for i in r.json()}
        assert items["s1-a"]["kind"] == "scene_course"
        assert items["s1-a"]["label"] == "点一杯拿铁 · 实战对话"
        assert items["s2-a"]["kind"] == "scene_course"
        assert items["s2-a"]["label"] == "情景课 · 实战对话"
        assert items["L1"]["kind"] == "lesson"
        assert items["L1"]["label"] == "L1"
    finally:
        scene_store.invalidate_cache()
