"""Tests for /api/v1/stats aggregation logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import History


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
    assert data["recent_sessions"] == 2


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
