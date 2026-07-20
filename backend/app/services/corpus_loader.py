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


@dataclass(frozen=True)
class CorpusBook:
    id: str
    display_name: str
    description: str
    level: str
    lesson_count: int


# 顶层默认元数据, 当 book.json 缺失或字段不全时回退. 运营侧把新书丢到
# data/<book>/ 目录就会自动出现在 /books 列表里, 不需要改代码.
_FALLBACK_BOOK_META: dict[str, dict[str, str]] = {
    "nce1": {
        "display_name": "新概念英语 第一册",
        "description": "英语初学者经典教材，覆盖日常会话与基础语法。",  # noqa: RUF001
        "level": "beginner",
    },
    "nce2": {
        "display_name": "新概念英语 第二册",
        "description": "在第一册基础上构建复合句型与中等长度对话。",
        "level": "intermediate",
    },
}


def list_books() -> list[CorpusBook]:
    """Enumerate every book directory under data/, returning metadata + lesson counts.

    Books without a ``book.json`` fall back to ``_FALLBACK_BOOK_META`` so adding a
    new directory + lesson_*.json is enough to ship a new curriculum. Unknown
    books still appear (with auto-generated display name) so the catalog never
    silently hides content.
    """
    root = _CORPUS_ROOT.resolve()
    if not root.is_dir():
        return []
    out: list[CorpusBook] = []
    for book_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        book_id = book_dir.name
        meta_path = book_dir / "book.json"
        if meta_path.is_file():
            try:
                raw = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                # 损坏的元数据不能阻塞整个列表 — 用后备值兜底, 运维从日志发现.
                raw = {}
                import logging

                logging.getLogger(__name__).warning("book.json unreadable for %s: %s", book_id, exc)
            meta = {**_FALLBACK_BOOK_META.get(book_id, {}), **raw}
            display_name = str(meta.get("display_name") or book_id)
            description = str(meta.get("description") or "")
            level = str(meta.get("level") or "beginner")
        else:
            fallback = _FALLBACK_BOOK_META.get(book_id, {})
            display_name = fallback.get("display_name", book_id)
            description = fallback.get("description", "")
            level = fallback.get("level", "beginner")
        lesson_count = sum(1 for _ in book_dir.glob("lesson_*.json"))
        out.append(
            CorpusBook(
                id=book_id,
                display_name=display_name,
                description=description,
                level=level,
                lesson_count=lesson_count,
            )
        )
    return out
