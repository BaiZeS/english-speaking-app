"""Tests for /api/v1/stats aggregation logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
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


async def test_stats_for_unknown_device_returns_zeroed_payload(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    r = await client.get("/api/v1/stats?device_id=nobody-here")
    data = r.json()
    assert data["total_sessions"] == 0
    assert data["avg_total"] == 0.0
    assert data["recent_sessions"] == 0
    assert data["streak_days"] == 0
    assert data["daily"] == []
    assert data["lessons_attempted"] == []


async def test_stats_aggregates_overall_and_per_sub_skill(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    # Inject 3 rows directly so we control the timestamps precisely.
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
    user_id = user_id_row.scalar_one()  # UUID string

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
    assert data["total_sessions"] == 3  # 1 POST + 2 seed rows
    assert abs(data["avg_total"] - (80 + 90 + 70) / 3) < 0.5
    assert data["best_total"] == 90.0
    # Lessons touched (deduped + sorted).
    assert data["lessons_attempted"] == [1, 2, 3]


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
    user_id = user_id_row.scalar_one()  # UUID string

    today = datetime.now(UTC)
    await _seed_history(
        db,
        user_id,
        [
            # Three days in a row, ending today.
            (1, today, 80.0),
            (1, today - timedelta(days=1), 70.0),
            (1, today - timedelta(days=2), 75.0),
            # Gap on day-3 breaks the streak before today.
            (1, today - timedelta(days=4), 60.0),
        ],
    )
    r = await client.get("/api/v1/stats?device_id=streak-dev")
    data = r.json()
    assert data["streak_days"] == 3


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
    user_id = user_id_row.scalar_one()  # UUID string

    today = datetime.now(UTC)
    await _seed_history(
        db,
        user_id,
        [
            (1, today, 88.0),
            (1, today - timedelta(days=5), 70.0),
            (1, today - timedelta(days=13), 60.0),
            (1, today - timedelta(days=20), 50.0),  # outside 14-day window
        ],
    )
    r = await client.get("/api/v1/stats?device_id=daily-dev")
    data = r.json()
    # daily should include today, day-5, day-13 (within 14-day window), but not day-20.
    dates = {entry["date"] for entry in data["daily"]}
    assert today.date().isoformat() in dates
    assert (today - timedelta(days=5)).date().isoformat() in dates
    assert (today - timedelta(days=13)).date().isoformat() in dates
    assert (today - timedelta(days=20)).date().isoformat() not in dates
    # Sessions within the past 7 days = today + day-5 = 2 (excluding day-13).
    assert data["recent_sessions"] == 2
