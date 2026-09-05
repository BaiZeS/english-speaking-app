"""Tests for /api/v1/stats aggregation logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import History
from app.services import corpus_loader, scene_store


async def _seed_history(
    db: AsyncSession, user_id: str, scores: list[tuple[int, datetime, float]]
) -> None:
    """Insert (lesson_id, created_at, total_score) rows for a user."""
    for lesson_id, created_at, total in scores:
        db.add(
            History(
                user_id=user_id,
                lesson_id=lesson_id,
                line_id=f"line-{lesson_id}",
                audio_path="test",
                score_total=total,
                score_pronunciation=total + 1,
                score_fluency=total - 1,
                score_completeness=total,
                created_at=created_at,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_stats_for_unknown_device_returns_zeroed_payload(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/api/v1/stats?device_id=nobody-here")
    data = r.json()
    assert data["total_sessions"] == 0
    assert data["avg_total"] == 0.0
    assert data["recent_sessions"] == 0
    assert data["streak_days"] == 0
    assert data["daily"] == []
    assert data["lessons_attempted"] == []
    assert data["weakest_lessons"] == []


@pytest.mark.asyncio
async def test_stats_aggregates_overall_and_per_sub_skill(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    # Trigger /history POST to create the user, then write directly.
    r = await client.post(
        "/api/v1/history",
        json={
            "device_id": "test-dev",
            "lesson_id": 1,
            "line_id": "L1",
            "audio_path": "p",
            "score_total": 80,
            "score_pronunciation": 85,
            "score_fluency": 75,
            "score_completeness": 80,
        },
    )
    assert r.status_code == 201

    user_id_row = await db.execute(select(History.user_id).order_by(History.id.desc()).limit(1))
    user_id = user_id_row.scalar_one()

    now = datetime.now(UTC)
    await _seed_history(
        db,
        user_id,
        [
            (2, now, 90.0),
            (3, now - timedelta(days=2), 70.0),
        ],
    )

    r = await client.get("/api/v1/stats?device_id=test-dev")
    data = r.json()
    assert data["total_sessions"] == 3
    assert abs(data["avg_total"] - (80 + 90 + 70) / 3) < 0.5
    assert data["best_total"] == 90.0
    assert data["lessons_attempted"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_streak_counts_consecutive_days_ending_today(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    r = await client.post(
        "/api/v1/history",
        json={
            "device_id": "streak-dev",
            "lesson_id": 1,
            "line_id": "L1",
            "audio_path": "p",
            "score_total": 80,
            "score_pronunciation": 80,
            "score_fluency": 80,
            "score_completeness": 80,
        },
    )
    assert r.status_code == 201
    user_id_row = await db.execute(select(History.user_id).order_by(History.id.desc()).limit(1))
    user_id = user_id_row.scalar_one()

    today = datetime.now(UTC)
    await _seed_history(
        db,
        user_id,
        [
            (1, today, 80.0),
            (1, today - timedelta(days=1), 70.0),
            (1, today - timedelta(days=2), 75.0),
            (1, today - timedelta(days=4), 60.0),
        ],
    )
    r = await client.get("/api/v1/stats?device_id=streak-dev")
    data = r.json()
    assert data["streak_days"] == 3


@pytest.mark.asyncio
async def test_daily_buckets_skip_empty_days(db: AsyncSession, client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/history",
        json={
            "device_id": "daily-dev",
            "lesson_id": 1,
            "line_id": "L1",
            "audio_path": "p",
            "score_total": 80,
            "score_pronunciation": 80,
            "score_fluency": 80,
            "score_completeness": 80,
        },
    )
    user_id_row = await db.execute(select(History.user_id).order_by(History.id.desc()).limit(1))
    user_id = user_id_row.scalar_one()

    today = datetime.now(UTC)
    await _seed_history(
        db,
        user_id,
        [
            (1, today, 88.0),
            (1, today - timedelta(days=5), 70.0),
            (1, today - timedelta(days=13), 60.0),
            (1, today - timedelta(days=20), 50.0),
        ],
    )
    r = await client.get("/api/v1/stats?device_id=daily-dev")
    data = r.json()
    dates = {entry["date"] for entry in data["daily"]}
    assert today.date().isoformat() in dates
    assert (today - timedelta(days=5)).date().isoformat() in dates
    assert (today - timedelta(days=13)).date().isoformat() in dates
    assert (today - timedelta(days=20)).date().isoformat() not in dates
    # recent_sessions counts all rows in the last 7 days for this device. The
    # earlier POST /api/v1/history call (L131-143) inserts one today row, and
    # _seed_history adds two more within 7 days (today + 5 days ago). The
    # 13d and 20d rows fall outside the 7-day window.
    assert data["recent_sessions"] == 3


@pytest.mark.asyncio
async def test_weakest_lessons_picks_lowest_scored(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    async def post(lesson_id: int, total: float) -> None:
        r = await client.post(
            "/api/v1/history",
            json={
                "device_id": "weak-dev",
                "lesson_id": lesson_id,
                "line_id": "L",
                "audio_path": "p",
                "score_total": total,
                "score_pronunciation": total,
                "score_fluency": total,
                "score_completeness": total,
            },
        )
        assert r.status_code == 201

    # Two attempts on lesson 1 (best 60), one on lesson 2 (single 95),
    # two on lesson 3 (best 75). Expect weakest = [1, 3] (lesson 2
    # dropped because single attempts aren't statistically meaningful).
    await post(1, 40.0)
    await post(1, 60.0)
    await post(2, 95.0)
    await post(3, 65.0)
    await post(3, 75.0)

    r = await client.get("/api/v1/stats?device_id=weak-dev")
    weakest = r.json()["weakest_lessons"]
    ids = [w["lesson_id"] for w in weakest]
    assert 1 in ids
    assert 3 in ids
    assert 2 not in ids
    assert ids.index(1) < ids.index(3)


@pytest.mark.asyncio
async def test_weakest_lessons_empty_for_new_device(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/api/v1/stats?device_id=fresh-user")
    assert r.json()["weakest_lessons"] == []


@pytest.mark.asyncio
async def test_weakest_lessons_carry_human_label(
    db: AsyncSession,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """P8 顺手修 (2b): weakest 行带上人读 label, 前端不再拿裸 book id 渲染.

    - 课本书行: 「<display_name> · 第N课」, display_name 与 /books 同源
      (book.json 缺失时诚实回退裸 book id, 这里用真 nce1 语料断言前缀非空)。
    - 情景课行 (book=="scenes"): 用课名; curated 未命中 -> 「情景实战课」(不 500)。
    - 跨书同课号 (nce1#4 vs nce2#4) 是**不同**组, 各自独立进榜。
    """
    # 隔离 scene_store: 空 scenes 目录, 让 scene 行走兜底分支且不受 data/ 真实内容影响。
    (tmp_path / "scenes").mkdir()
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    try:

        async def post(
            device: str, book: str, lesson_id: int, audio_path: str, total: float
        ) -> None:
            r = await client.post(
                "/api/v1/history",
                json={
                    "device_id": device,
                    "book": book,
                    "lesson_id": lesson_id,
                    "line_id": "L",
                    "audio_path": audio_path,
                    "score_total": total,
                    "score_pronunciation": total,
                    "score_fluency": total,
                    "score_completeness": total,
                },
            )
            assert r.status_code == 201, r.text

        dev = "weak-label-dev"
        for total in (40.0, 60.0):
            await post(dev, "nce1", 4, "p1", total)
        for total in (50.0, 55.0):
            await post(dev, "nce2", 4, "p2", total)
        for total in (30.0, 35.0):
            await post(dev, "scenes", 0, "scene_missing_xx", total)

        r = await client.get(f"/api/v1/stats?device_id={dev}")
        weakest = r.json()["weakest_lessons"]
        by_key = {(w["book"], w["lesson_id"]): w for w in weakest}
        assert ("nce1", 4) in by_key and ("nce2", 4) in by_key, (
            f"book-blind 分组被合并: {list(by_key)}"
        )
        names = {b.id: b.display_name for b in corpus_loader.list_books()}
        assert by_key[("nce1", 4)]["label"] == f"{names.get('nce1', 'nce1')} · 第4课"
        assert by_key[("nce2", 4)]["label"] != by_key[("nce1", 4)]["label"]
        scene_row = by_key[("scenes", 0)]
        assert scene_row["label"] == "情景实战课"  # curated 未命中的诚实兜底
        assert scene_row["best_score"] == 35.0
    finally:
        scene_store.invalidate_cache()
