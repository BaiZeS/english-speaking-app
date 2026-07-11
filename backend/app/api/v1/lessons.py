from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.errors import AppError
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
