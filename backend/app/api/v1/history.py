from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
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
