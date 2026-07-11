from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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


def _file_for(book: str, lesson_no: int) -> Path:
    return _CORPUS_ROOT / book / f"lesson_{lesson_no:03d}.json"


def list_lessons(book: str) -> list[CorpusLesson]:
    out: list[CorpusLesson] = []
    book_dir = _CORPUS_ROOT / book
    if not book_dir.is_dir():
        return out
    for i, path in enumerate(sorted(book_dir.glob("lesson_*.json")), start=1):
        out.append(_parse(path, synthetic_id=i, book=book))
    return out


def get_lesson(book: str, lesson_no: int) -> CorpusLesson | None:
    path = _file_for(book, lesson_no)
    if not path.is_file():
        return None
    return _parse(path, synthetic_id=lesson_no, book=book)


def _parse(path: Path, synthetic_id: int, book: str) -> CorpusLesson:
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
        id=synthetic_id,
        book=book,
        lesson_no=raw["lesson"],
        title=raw["title"],
        roles=roles,
    )
