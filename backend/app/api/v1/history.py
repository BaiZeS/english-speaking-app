from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import History, SceneCourseRow, User
from app.models.schema import HistoryItem, HistoryWriteRequest
from app.services import corpus_loader, scene_store


def _as_utc(dt: datetime) -> datetime:
    """Coerce a datetime to aware UTC.

    Production (postgres) may return aware datetimes; tests (sqlite) return naive
    ones because the SQLite driver strips tzinfo. Treat naive values as already-UTC
    so we never compare/astimezone across naive vs aware.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


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
        book=req.book,
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
    return _to_item(h)


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
    rows = list(res.scalars().all())
    titles = await _history_titles(db, user.id, rows)
    return [_to_item(h, titles) for h in rows]


async def _history_titles(
    db: AsyncSession, user_id: str, rows: Sequence[History]
) -> dict[str, str]:
    """``{course_id: 标题}`` —— 只为情景课行查标题 (§5.7: kind/label, 历史页显示
    中文课名而不是裸 line_id)。

    生成课在 ``scene_courses`` 表: 按 device 一次拉取后在 Python 里按 ``doc.id``
    建索引 (每设备生成课量小, 且这比 JSON 路径查询更方言中立); curated 课在
    data/scenes/*.json (走 scene_store 的 60s 文件缓存)。textbook 行不查 ——
    它们的标题由客户端课本缓存负责, 这里保持读路径零额外 IO。
    """
    scene_ids = {h.audio_path for h in rows if h.book == scene_store.SCRIPT_BOOK}
    if not scene_ids:
        return {}
    titles: dict[str, str] = {}
    res = await db.execute(select(SceneCourseRow).where(SceneCourseRow.user_id == user_id))
    for row in res.scalars().all():
        doc = row.doc if isinstance(row.doc, dict) else {}
        course_id = str(doc.get("id") or "")
        title = str(doc.get("title") or "")
        if course_id in scene_ids and title:
            titles[course_id] = title
    for scene_id in scene_ids - set(titles):
        course = scene_store.get_course(scene_id)
        if course is not None:
            titles[scene_id] = course.title
    return titles


#: ``history.kind`` 的取值: 课本四模式 vs 情景课实战收工行 (P8 §5.7)。
KIND_LESSON = "lesson"
KIND_SCENE_COURSE = "scene_course"


def resolve_history_kind(h: History) -> str:
    return KIND_SCENE_COURSE if h.book == scene_store.SCRIPT_BOOK else KIND_LESSON


def _to_item(h: History, titles: Mapping[str, str] | None = None) -> HistoryItem:
    kind = resolve_history_kind(h)
    if kind == KIND_SCENE_COURSE:
        title = (titles or {}).get(h.audio_path) or "情景课"
        label = f"{title} · 实战对话"
    else:
        label = h.line_id
    return HistoryItem(
        id=h.id,
        book=h.book,
        lesson_id=h.lesson_id,
        line_id=h.line_id,
        kind=kind,
        label=label,
        score_total=h.score_total,
        score_pronunciation=h.score_pronunciation,
        score_fluency=h.score_fluency,
        score_completeness=h.score_completeness,
        created_at=_as_utc(h.created_at).isoformat(),
    )


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

    book: str = "nce1"
    lesson_id: int
    best_score: float
    avg_score: float
    attempts: int
    #: P8 顺手修: 人读标签「新概念英语 第一册 · 第3课」(书元数据来自 /books 同源),
    #: 情景课行则是课名。旧客户端继续读 book+lesson_id, 新客户端优先渲染 label。
    label: str = ""


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
    weakest_lessons: list[WeakestLesson] = []  # surface low-scoring lessons for review


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
    recent = [r for r in rows if _as_utc(r.created_at) >= seven_days_ago]

    # Build daily buckets for the last 14 days so the dashboard has a visible
    # trend even for low-frequency users. Older days are dropped to keep the
    # payload tiny.
    by_day: dict[str, list[History]] = {}
    for r in rows:
        d = _as_utc(r.created_at).date().isoformat()
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
    """Group rows by (book, lesson), drop single-attempt flukes, pick lowest best_score.

    lesson_id 是书内课号, 跨书会重复, 必须和 book 一起分组 (复合去重键)。
    """
    by_lesson: dict[tuple[str, int], list[History]] = {}
    for r in rows:
        by_lesson.setdefault((r.book, r.lesson_id), []).append(r)
    book_names = {b.id: b.display_name for b in corpus_loader.list_books()}
    scored: list[WeakestLesson] = []
    for (book, lesson_id), items in by_lesson.items():
        if len(items) < 2:
            continue
        best = max(r.score_total for r in items)
        avg = sum(r.score_total for r in items) / len(items)
        scored.append(
            WeakestLesson(
                book=book,
                lesson_id=lesson_id,
                best_score=best,
                avg_score=avg,
                attempts=len(items),
                label=_weakest_label(book, lesson_id, items[0].audio_path, book_names),
            )
        )
    scored.sort(key=lambda w: (w.best_score, -w.attempts))
    return scored[:limit]


def _weakest_label(book: str, lesson_id: int, audio_path: str, names: Mapping[str, str]) -> str:
    """复习卡的人读标题 (P8 顺手修: stats 不再 book-blind).

    课本书行用 /books 同源元数据拼「商务英语口语 · 职场场景 · 第3课」;
    情景课行 (book=="scenes") 用课名 (audio_path 存的就是 scene id)。
    元数据缺失时诚实回退裸 id, UI 照常渲染, 不为此 500。
    """
    if book == scene_store.SCRIPT_BOOK:
        try:
            course = scene_store.get_course(audio_path) if audio_path else None
        except AppError:
            course = None
        return f"{course.title} · 实战对话" if course else "情景实战课"
    display = names.get(book, book)
    return f"{display} · 第{lesson_id}课"


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    device_id: str = Query(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    """Return aggregated practice stats for the dashboard screen."""
    return await _compute_stats(db, device_id)
