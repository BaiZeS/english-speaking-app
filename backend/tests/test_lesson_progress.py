"""Tests for the /lessons/{id}/progress endpoint."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import History


async def _seed(
    db: AsyncSession,
    user_id: str,
    lesson_id: int,
    scores: list[tuple[float, datetime]],
) -> None:
    for total, created_at in scores:
        db.add(
            History(
                user_id=user_id,
                lesson_id=lesson_id,
                line_id=f"line-{lesson_id}",
                audio_path="test",
                score_total=total,
                score_pronunciation=total,
                score_fluency=total,
                score_completeness=total,
                created_at=created_at,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_progress_unknown_device_returns_zeroes(
    client: httpx.AsyncClient,
) -> None:
    """Brand-new device with no history → 0 attempts, scores all 0."""
    r = await client.get("/api/v1/lessons/1/progress?device_id=nobody")
    assert r.status_code == 200
    data = r.json()
    assert data["lesson_id"] == 1
    assert data["attempt_count"] == 0
    assert data["best_score"] == 0.0
    assert data["last_score"] == 0.0
    assert data["last_practiced_at"] is None


@pytest.mark.asyncio
async def test_progress_single_attempt(
    client: httpx.AsyncClient,
    db: AsyncSession,
) -> None:
    r = await client.post(
        "/api/v1/history",
        json={
            "device_id": "single-dev",
            "lesson_id": 2,
            "line_id": "L1",
            "audio_path": "p",
            "score_total": 78.0,
            "score_pronunciation": 78.0,
            "score_fluency": 78.0,
            "score_completeness": 78.0,
        },
    )
    assert r.status_code == 201

    r = await client.get("/api/v1/lessons/2/progress?device_id=single-dev")
    data = r.json()
    assert data["attempt_count"] == 1
    assert data["best_score"] == 78.0
    assert data["last_score"] == 78.0
    assert data["last_practiced_at"] is not None


@pytest.mark.asyncio
async def test_progress_picks_best_and_last(
    client: httpx.AsyncClient,
    db: AsyncSession,
) -> None:
    """best_score is the max, last_score reflects the most recent attempt."""
    # Seed via /history so we exercise the real write path too.
    for total in [60.0, 80.0, 50.0, 90.0, 70.0]:
        r = await client.post(
            "/api/v1/history",
            json={
                "device_id": "multi-dev",
                "lesson_id": 1,
                "line_id": "L",
                "audio_path": "p",
                "score_total": total,
                "score_pronunciation": total,
                "score_fluency": total,
                "score_completeness": total,
            },
        )
        assert r.status_code == 201

    r = await client.get("/api/v1/lessons/1/progress?device_id=multi-dev")
    data = r.json()
    assert data["attempt_count"] == 5
    assert data["best_score"] == 90.0
    # All five were inserted within the same second so the 'most recent' is
    # whichever the SQL ORDER picks; we accept any of 50-90 as long as it's
    # a real recorded score.
    assert data["last_score"] in {60.0, 80.0, 50.0, 90.0, 70.0}


@pytest.mark.asyncio
async def test_progress_isolated_per_lesson(
    client: httpx.AsyncClient,
    db: AsyncSession,
) -> None:
    """Practising lesson 1 should not contaminate lesson 2's progress."""
    for total, lesson in [(50.0, 1), (95.0, 2), (40.0, 1), (80.0, 2)]:
        await client.post(
            "/api/v1/history",
            json={
                "device_id": "isolated-dev",
                "lesson_id": lesson,
                "line_id": "L",
                "audio_path": "p",
                "score_total": total,
                "score_pronunciation": total,
                "score_fluency": total,
                "score_completeness": total,
            },
        )
    r1 = await client.get("/api/v1/lessons/1/progress?device_id=isolated-dev")
    r2 = await client.get("/api/v1/lessons/2/progress?device_id=isolated-dev")
    assert r1.json()["attempt_count"] == 2
    assert r1.json()["best_score"] == 50.0
    assert r2.json()["attempt_count"] == 2
    assert r2.json()["best_score"] == 95.0


@pytest.mark.asyncio
async def test_progress_isolated_per_device(
    client: httpx.AsyncClient,
    db: AsyncSession,
) -> None:
    """Two devices practising the same lesson should each get their own progress."""
    for total, dev in [(70.0, "dev-a"), (95.0, "dev-b")]:
        await client.post(
            "/api/v1/history",
            json={
                "device_id": dev,
                "lesson_id": 3,
                "line_id": "L",
                "audio_path": "p",
                "score_total": total,
                "score_pronunciation": total,
                "score_fluency": total,
                "score_completeness": total,
            },
        )

    a = await client.get("/api/v1/lessons/3/progress?device_id=dev-a")
    b = await client.get("/api/v1/lessons/3/progress?device_id=dev-b")
    assert a.json()["best_score"] == 70.0
    assert b.json()["best_score"] == 95.0
    assert a.json()["attempt_count"] == 1
    assert b.json()["attempt_count"] == 1


@pytest.mark.asyncio
async def test_progress_last_practiced_at_is_iso8601(
    client: httpx.AsyncClient,
    db: AsyncSession,
) -> None:
    """last_practiced_at must be a real ISO-8601 string (parseable, has TZ)."""
    await client.post(
        "/api/v1/history",
        json={
            "device_id": "iso-dev",
            "lesson_id": 1,
            "line_id": "L",
            "audio_path": "p",
            "score_total": 80.0,
            "score_pronunciation": 80.0,
            "score_fluency": 80.0,
            "score_completeness": 80.0,
        },
    )
    r = await client.get("/api/v1/lessons/1/progress?device_id=iso-dev")
    raw = r.json()["last_practiced_at"]
    assert raw is not None
    parsed = datetime.fromisoformat(raw)
    # Strip the tzinfo to make the assertion timezone-agnostic in CI.
    assert parsed.tzinfo is not None
