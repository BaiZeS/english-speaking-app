from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import AppError

# Tests can monkeypatch this
_CORPUS_ROOT: Path = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass(frozen=True)
class CorpusLine:
    id: str
    text: str
    translation: str | None
    ipa: str | None


@dataclass(frozen=True)
class CorpusRole:
    name: str
    lines: list[CorpusLine]


@dataclass(frozen=True)
class CorpusLesson:
    id: int
    book: str
    lesson_no: int
    title: str
    roles: list[CorpusRole]


def _book_dir(book: str) -> Path:
    """Resolve book to a directory, rejecting path traversal outside the corpus root."""
    root = _CORPUS_ROOT.resolve()
    resolved = (_CORPUS_ROOT / book).resolve()
    if not resolved.is_relative_to(root):
        raise AppError(400, "invalid book", "INVALID_BOOK")
    return resolved


def list_lessons(book: str) -> list[CorpusLesson]:
    out: list[CorpusLesson] = []
    book_dir = _book_dir(book)
    if not book_dir.is_dir():
        return out
    for path in sorted(book_dir.glob("lesson_*.json")):
        out.append(_parse(path, book=book))
    return out


def get_lesson(book: str, lesson_no: int) -> CorpusLesson | None:
    path = _book_dir(book) / f"lesson_{lesson_no:03d}.json"
    if not path.is_file():
        return None
    return _parse(path, book=book)


def _parse(path: Path, book: str) -> CorpusLesson:
    raw = json.loads(path.read_text(encoding="utf-8"))
    roles = [
        CorpusRole(
            name=r["name"],
            lines=[
                CorpusLine(
                    id=ln["id"],
                    text=ln["text"],
                    translation=ln.get("translation"),
                    ipa=ln.get("ipa"),
                )
                for ln in r["lines"]
            ],
        )
        for r in raw["roles"]
    ]
    return CorpusLesson(
        id=raw["lesson"],
        book=book,
        lesson_no=raw["lesson"],
        title=raw["title"],
        roles=roles,
    )
