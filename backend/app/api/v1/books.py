"""Curriculum book catalog.

The Android client uses this to render the book picker on the lessons
screen and to seed the ``book`` query parameter for ``/lessons`` calls.
Each book corresponds to a directory under ``backend/data/<book>/``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import corpus_loader

router = APIRouter(tags=["books"])


class BookDto(BaseModel):
    id: str
    display_name: str
    description: str
    level: str
    lesson_count: int


class BooksResponse(BaseModel):
    books: list[BookDto]
    default_book: str


@router.get("/books", response_model=BooksResponse)
async def list_books() -> BooksResponse:
    """Return every book present on disk plus its lesson count.

    ``default_book`` is the first book in lexical order, which is what the
    Android client shows on first launch before the user picks anything.
    """
    catalog = corpus_loader.list_books()
    payload = [
        BookDto(
            id=b.id,
            display_name=b.display_name,
            description=b.description,
            level=b.level,
            lesson_count=b.lesson_count,
        )
        for b in catalog
    ]
    default = payload[0].id if payload else ""
    return BooksResponse(books=payload, default_book=default)
