from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.models.db import History, User
from app.models.schema import HistoryItem, HistoryWriteRequest

router = APIRouter(tags=["history"])


async def _get_or_create_user(db: AsyncSession, device_id: str) -> User:
    res = await db.execute(select(User).where(User.device_id == device_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(device_id=device_id)
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # Concurrent insert raced us; the user now exists - re-fetch.
            await db.rollback()
            res = await db.execute(select(User).where(User.device_id == device_id))
            user = res.scalar_one()
    return user


@router.post("/history", status_code=status.HTTP_201_CREATED, response_model=HistoryItem)
async def write_history(
    req: HistoryWriteRequest, db: AsyncSession = Depends(get_db)
) -> HistoryItem:
    user = await _get_or_create_user(db, req.device_id)
    h = History(
        user_id=user.id,
        lesson_id=req.lesson_id,
        line_id=req.line_id,
        audio_path=req.audio_path,
        score_total=req.score_total,
        score_pronunciation=req.score_pronunciation,
        score_fluency=req.score_fluency,
        score_completeness=req.score_completeness,
    )
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return HistoryItem(
        id=h.id,
        lesson_id=h.lesson_id,
        line_id=h.line_id,
        score_total=h.score_total,
        score_pronunciation=h.score_pronunciation,
        score_fluency=h.score_fluency,
        score_completeness=h.score_completeness,
        created_at=h.created_at.isoformat(),
    )


@router.get("/history", response_model=list[HistoryItem])
async def list_history(
    device_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[HistoryItem]:
    user_res = await db.execute(select(User).where(User.device_id == device_id))
    user = user_res.scalar_one_or_none()
    if user is None:
        return []
    res = await db.execute(
        select(History)
        .where(History.user_id == user.id)
        .order_by(History.created_at.desc())
        .limit(limit)
    )
    rows = res.scalars().all()
    return [
        HistoryItem(
            id=h.id,
            lesson_id=h.lesson_id,
            line_id=h.line_id,
            score_total=h.score_total,
            score_pronunciation=h.score_pronunciation,
            score_fluency=h.score_fluency,
            score_completeness=h.score_completeness,
            created_at=h.created_at.isoformat(),
        )
        for h in rows
    ]


class DailyScore(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    avg_total: float
    avg_pronunciation: float
    avg_fluency: float
    avg_completeness: float
    sessions: int


class WeakestLesson(BaseModel):
    """A lesson the user has practised but where the average score is low.
    Used by the dashboard "推荐复习" block to surface weak spots."""

    lesson_id: int
    best_score: float
    avg_score: float
    attempts: int


class StatsResponse(BaseModel):
    total_sessions: int
    avg_total: float
    avg_pronunciation: float
    avg_fluency: float
    avg_completeness: float
    best_total: float
    recent_sessions: int  # last 7 days
    streak_days: int
    daily: list[DailyScore]
    lessons_attempted: list[int]


async def _compute_stats(db: AsyncSession, device_id: str) -> StatsResponse:
    """Aggregate per-device history rows into the dashboard payload.

    The query pulls everything the device has ever recorded; aggregations
    are done in Python so the same code paths work on sqlite (tests) and
    postgres (prod) without dialect-specific date_trunc gymnastics.
    """
    user = await _get_or_create_user(db, device_id)
    res = await db.execute(
        select(History).where(History.user_id == user.id).order_by(History.created_at.desc())
    )
    rows = list(res.scalars().all())
    if not rows:
        return StatsResponse(
            total_sessions=0,
            avg_total=0.0,
            avg_pronunciation=0.0,
            avg_fluency=0.0,
            avg_completeness=0.0,
            best_total=0.0,
            recent_sessions=0,
            streak_days=0,
            daily=[],
            lessons_attempted=[],
        )

    n = len(rows)
    avg_total = sum(r.score_total for r in rows) / n
    avg_pron = sum(r.score_pronunciation for r in rows) / n
    avg_flu = sum(r.score_fluency for r in rows) / n
    avg_comp = sum(r.score_completeness for r in rows) / n
    best = max(r.score_total for r in rows)

    seven_days_ago = datetime.now(UTC) - timedelta(days=7)
    recent = [r for r in rows if r.created_at >= seven_days_ago]

    # Build daily buckets for the last 14 days so the dashboard has a visible
    # trend even for low-frequency users. Older days are dropped to keep the
    # payload tiny.
    by_day: dict[str, list[History]] = {}
    for r in rows:
        d = r.created_at.astimezone(UTC).date().isoformat()
        by_day.setdefault(d, []).append(r)
    today = datetime.now(UTC).date()
    daily: list[DailyScore] = []
    for offset in range(13, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        bucket = by_day.get(day, [])
        if not bucket:
            continue
        m = len(bucket)
        daily.append(
            DailyScore(
                date=day,
                avg_total=sum(b.score_total for b in bucket) / m,
                avg_pronunciation=sum(b.score_pronunciation for b in bucket) / m,
                avg_fluency=sum(b.score_fluency for b in bucket) / m,
                avg_completeness=sum(b.score_completeness for b in bucket) / m,
                sessions=m,
            )
        )

    # Streak: consecutive UTC days ending today with at least one session.
    streak = 0
    cursor = today
    days_with_sessions = {datetime.fromisoformat(d).date() for d in by_day}
    while cursor in days_with_sessions:
        streak += 1
        cursor -= timedelta(days=1)

    lessons_attempted = sorted({r.lesson_id for r in rows})

    # Pick the three lessons where the user is weakest — i.e. practised at
    # least twice (one attempt can be a fluke) and has the lowest best_score.
    # Used by the Dashboard "推荐复习" card.
    weakest = _weakest_lessons(rows, limit=3)

    return StatsResponse(
        total_sessions=n,
        avg_total=avg_total,
        avg_pronunciation=avg_pron,
        avg_fluency=avg_flu,
        avg_completeness=avg_comp,
        best_total=best,
        recent_sessions=len(recent),
        streak_days=streak,
        daily=daily,
        lessons_attempted=lessons_attempted,
        weakest_lessons=weakest,
    )


def _weakest_lessons(rows: list[History], limit: int = 3) -> list[WeakestLesson]:
    """Group rows by lesson, drop single-attempt flukes, pick lowest best_score."""
    by_lesson: dict[int, list[History]] = {}
    for r in rows:
        by_lesson.setdefault(r.lesson_id, []).append(r)
    scored: list[WeakestLesson] = []
    for lesson_id, items in by_lesson.items():
        if len(items) < 2:
            continue
        best = max(r.score_total for r in items)
        avg = sum(r.score_total for r in items) / len(items)
        scored.append(
            WeakestLesson(
                lesson_id=lesson_id,
                best_score=best,
                avg_score=avg,
                attempts=len(items),
            )
        )
    scored.sort(key=lambda w: (w.best_score, -w.attempts))
    return scored[:limit]


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    device_id: str = Query(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    """Return aggregated practice stats for the dashboard screen."""
    return await _compute_stats(db, device_id)
