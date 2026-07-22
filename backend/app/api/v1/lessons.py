from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import History, User
from app.models.schema import (
    LessonDetail,
    LessonSummary,
    Line,
    Role,
)
from app.services import corpus_loader

router = APIRouter(tags=["lessons"])


@router.get("/lessons", response_model=list[LessonSummary])
async def list_lessons(book: str = Query(..., min_length=1)) -> list[LessonSummary]:
    rows = corpus_loader.list_lessons(book)
    return [
        LessonSummary(
            id=r.id,
            book=r.book,
            lesson_no=r.lesson_no,
            title=r.title,
            role_count=len(r.roles),
            duration_s=0.0,  # TODO: compute from audio
        )
        for r in rows
    ]


@router.get("/lessons/{lesson_id}/roles", response_model=LessonDetail)
async def get_lesson_roles(lesson_id: int, book: str = Query("nce1")) -> LessonDetail:
    lesson = corpus_loader.get_lesson(book, lesson_id)
    if lesson is None:
        raise AppError(
            status_code=404, message=f"Lesson {lesson_id} not found", code="LESSON_NOT_FOUND"
        )
    return LessonDetail(
        id=lesson.id,
        book=lesson.book,
        lesson_no=lesson.lesson_no,
        title=lesson.title,
        roles=[
            Role(
                name=role.name,
                lines=[
                    Line(id=ln.id, text=ln.text, translation=ln.translation, ipa=ln.ipa)
                    for ln in role.lines
                ],
            )
            for role in lesson.roles
        ],
    )


class LessonProgress(BaseModel):
    """Per-user progress for a single lesson.

    `attempt_count` is the number of History rows the device has for this
    lesson; `best_score` / `last_score` are 0 when the user has never
    practised the lesson (Android renders those as a "new" pill).
    """

    lesson_id: int
    attempt_count: int
    best_score: float
    last_score: float
    last_practiced_at: str | None = None


async def _get_or_create_user(db: AsyncSession, device_id: str) -> User:
    """Find or create the user row for this device, mirroring history.py.

    Duplicated rather than imported to keep this router self-contained —
    the cost is one short helper function.
    """
    res = await db.execute(select(User).where(User.device_id == device_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(device_id=device_id)
        db.add(user)
        await db.flush()
    return user


@router.get("/lessons/{lesson_id}/progress", response_model=LessonProgress)
async def get_lesson_progress(
    lesson_id: int,
    device_id: str = Query(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> LessonProgress:
    """Return this device's practice stats for one lesson.

    Computed in a single query so we can return attempt_count, best, last,
    and last_practiced_at without N+1 round-trips. The lesson_id is the
    lesson_no (NCE1 lesson 1 has id=1); the column on History is integer.
    """
    user = await _get_or_create_user(db, device_id)
    res = await db.execute(
        select(History).where(History.user_id == user.id, History.lesson_id == lesson_id)
    )
    rows = list(res.scalars().all())
    if not rows:
        return LessonProgress(
            lesson_id=lesson_id,
            attempt_count=0,
            best_score=0.0,
            last_score=0.0,
            last_practiced_at=None,
        )
    best = max(r.score_total for r in rows)
    # rows are ordered by History.id; the last in DB order is the most recent.
    # Sort by created_at desc to be safe in case of out-of-order inserts.
    most_recent = max(rows, key=lambda r: r.created_at)
    return LessonProgress(
        lesson_id=lesson_id,
        attempt_count=len(rows),
        best_score=best,
        last_score=most_recent.score_total,
        last_practiced_at=most_recent.created_at.isoformat(),
    )
