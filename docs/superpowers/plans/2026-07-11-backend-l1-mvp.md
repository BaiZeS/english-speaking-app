# Backend L1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI backend that fully supports the L1 read-along scenario (K12 mode + 新概念英语第一册 跟读), with stable API contracts for all 9 endpoints (7 L1 implementations + 2 L2 stubs).

**Architecture:** Layered FastAPI app — `api/` (HTTP routes) → `services/` (讯飞, LLM, 评分) → `models/` (SQLAlchemy + Pydantic). Postgres 16 for persistence, Redis 7 for TTS cache, async I/O throughout. Every external dependency is wrapped behind a service interface so providers can be swapped.

**Tech Stack:** Python 3.11, FastAPI 0.115, SQLAlchemy 2.0 (async), asyncpg, Alembic, Redis, httpx, 讯飞 WebAPI, pytest, ruff, mypy.

**Spec reference:** `docs/superpowers/specs/2026-07-11-english-speaking-app-design.md` §3, §4, §5, §6, §7.

---

## File Structure (created/modified by this plan)

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                       # MODIFY: include all routers, exception handler
│   ├── config.py                     # EXISTS — keep
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── deps.py               # CREATE: common deps (db session, current device)
│   │       ├── health.py             # EXISTS — keep
│   │       ├── lessons.py            # CREATE
│   │       ├── tts.py                # CREATE
│   │       ├── score.py              # CREATE
│   │       ├── history.py            # CREATE
│   │       └── dialogue.py           # CREATE (L2 stub + dialogue_turn)
│   ├── core/
│   │   ├── __init__.py               # CREATE
│   │   ├── errors.py                 # CREATE: AppError, handler
│   │   └── logging.py                # CREATE: loguru config
│   ├── db/
│   │   ├── __init__.py               # CREATE
│   │   ├── base.py                   # CREATE: SQLAlchemy Base
│   │   ├── session.py                # CREATE: async engine + sessionmaker
│   │   └── migrations/               # CREATE: Alembic env + first migration
│   │       ├── env.py
│   │       ├── script.py.mako
│   │       └── versions/0001_init.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── db.py                     # CREATE: User, Lesson, History, TtsCache
│   │   └── schema.py                 # CREATE: Pydantic request/response models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── interfaces.py             # CREATE: ASRProvider, TTSProvider protocols
│   │   ├── xunfei_asr.py             # CREATE
│   │   ├── xunfei_tts.py             # CREATE
│   │   ├── tts_cache.py              # CREATE: Redis-backed TTS cache
│   │   ├── corpus_loader.py          # CREATE: load NCE1 lesson JSON
│   │   └── stub_providers.py         # CREATE: deterministic in-memory providers
│   └── scoring/
│       ├── __init__.py
│       └── read_along.py             # CREATE: scoring algorithm
├── data/
│   └── nce1/lesson_001.json          # CREATE: first lesson corpus
├── tests/
│   ├── __init__.py                   # EXISTS
│   ├── conftest.py                   # CREATE: fixtures (db, client, providers)
│   ├── test_health.py                # EXISTS — keep
│   ├── test_lessons.py               # CREATE
│   ├── test_tts.py                   # CREATE
│   ├── test_score.py                 # CREATE
│   ├── test_history.py               # CREATE
│   └── test_dialogue_stub.py         # CREATE
├── pyproject.toml                    # EXISTS — already has deps
└── .env.example                      # EXISTS — keep
```

---

## Conventions

- **All code has type annotations**, `mypy --strict` must pass
- **Every router has a router-level test file**
- **TDD order**: write failing test → implement → refactor → commit
- **Commit format**: `<type>(<scope>): <subject>` per Conventional Commits
- **Providers are pluggable**: every external service accessed through `interfaces.py` protocol; tests use `stub_providers`
- **Errors raise `AppError`** with HTTP code + message; main.py installs handler that converts to JSON

---

### Task 1: Verify backend dev setup runs

**Files:**
- Modify: `backend/tests/test_health.py` (already exists)
- No new files

- [ ] **Step 1: Verify pytest passes locally**

Run: `cd backend && pip install -e ".[dev]" 2>&1 | tail -5 && pytest -v`
Expected: 2 tests pass (test_health_ok, test_root)

- [ ] **Step 2: Verify ruff + mypy pass**

Run: `cd backend && ruff check . && mypy app`
Expected: `ruff` clean, `mypy` reports no issues (or only pre-existing benign ones in `app/main.py`)

- [ ] **Step 3: Commit (no code change, sanity baseline)**

```bash
cd backend
git add -A
git diff --cached --quiet || git commit -m "chore(backend): verify dev env passes lint and tests"
```

---

### Task 2: Add core error type and global handler

**Files:**
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/errors.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_errors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_errors.py
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError, install_error_handler


@pytest.mark.asyncio
async def test_app_error_returns_json_status_and_message() -> None:
    app = FastAPI()
    install_error_handler(app)

    @app.get("/boom")
    async def boom() -> None:
        raise AppError(status_code=418, message="tea pot", code="TEAPOT")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"code": "TEAPOT", "message": "tea pot"}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_errors.py -v`
Expected: ImportError — `app.core.errors` does not exist

- [ ] **Step 3: Create the package and the error module**

```python
# app/core/__init__.py
```

```python
# app/core/errors.py
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger


class AppError(Exception):
    """Base application error. Maps cleanly to a JSON HTTP response."""

    def __init__(self, status_code: int, message: str, code: str = "INTERNAL") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code


def install_error_handler(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception: {}", exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "Internal server error"}},
        )
```

- [ ] **Step 4: Wire the handler into main.py**

Replace `backend/app/main.py` with:

```python
"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from loguru import logger

from app.api.v1 import health
from app.config import settings
from app.core.errors import install_error_handler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting English Assistant API | env={}", settings.env)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="English Speaking Assistant API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.env != "production" else None,
    redoc_url="/redoc" if settings.env != "production" else None,
)

install_error_handler(app)
app.include_router(health.router, prefix="/api/v1", tags=["health"])


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "english-assistant", "version": "0.1.0"}
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `cd backend && pytest tests/test_errors.py tests/test_health.py -v`
Expected: 3 passed (test_app_error_returns_json_status_and_message, test_health_ok, test_root)

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/core app/main.py tests/test_errors.py
git commit -m "feat(backend): add AppError type and global handler"
```

---

### Task 3: Add logging configuration

**Files:**
- Create: `backend/app/core/logging.py`
- Modify: `backend/app/main.py`
- Test: manual smoke

- [ ] **Step 1: Create logging module**

```python
# app/core/logging.py
from __future__ import annotations

import sys

from loguru import logger


def configure_logging(level: str = "INFO") -> None:
    """Replace default loguru handler with a structured stderr sink."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
    )
```

- [ ] **Step 2: Call configure_logging in main.py**

Modify `backend/app/main.py` — add `from app.core.logging import configure_logging` and call `configure_logging("INFO")` as the first line of `lifespan` function body.

- [ ] **Step 3: Verify server starts and logs appear**

Run: `cd backend && uvicorn app.main:app --port 8765 &` (in background), `sleep 2 && curl -s http://localhost:8765/api/v1/health && kill %1`
Expected: `{"status":"ok"}` returned; stderr shows structured log line `Starting English Assistant API | env=development`

- [ ] **Step 4: Commit**

```bash
cd backend
git add app/core/logging.py app/main.py
git commit -m "feat(backend): add structured logging configuration"
```

---

### Task 4: Add SQLAlchemy Base and async session

**Files:**
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
from __future__ import annotations

import pytest

from app.db.session import get_engine, get_sessionmaker


@pytest.mark.asyncio
async def test_engine_and_sessionmaker_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    get_engine.cache_clear()  # type: ignore[attr-defined]
    get_sessionmaker.cache_clear()  # type: ignore[attr-defined]
    eng = get_engine()
    sm = get_sessionmaker()
    assert eng is not None
    assert sm is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_db.py -v`
Expected: ModuleNotFoundError on `app.db.session`

- [ ] **Step 3: Create db package and modules**

```python
# app/db/__init__.py
```

```python
# app/db/base.py
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
# app/db/session.py
from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, future=True, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_db.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/db tests/test_db.py
git commit -m "feat(backend): add SQLAlchemy async engine and sessionmaker"
```

---

### Task 5: Add ORM models (User, Lesson, History, TtsCache)

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/db.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from __future__ import annotations

from datetime import datetime, timezone

from app.models.db import History, Lesson, TtsCache, User


def test_user_columns() -> None:
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "device_id", "mode", "created_at"} <= cols


def test_lesson_columns() -> None:
    cols = {c.name for c in Lesson.__table__.columns}
    assert {"id", "book", "lesson_no", "title", "role_count", "duration_s"} <= cols


def test_history_columns() -> None:
    cols = {c.name for c in History.__table__.columns}
    assert {
        "id",
        "user_id",
        "lesson_id",
        "line_id",
        "audio_path",
        "score_total",
        "score_pronunciation",
        "score_fluency",
        "score_completeness",
        "created_at",
    } <= cols


def test_tts_cache_columns() -> None:
    cols = {c.name for c in TtsCache.__table__.columns}
    assert {"cache_key", "audio_path", "hit_count", "expires_at"} <= cols


def test_history_default_created_at_is_utc() -> None:
    h = History(
        user_id="00000000-0000-0000-0000-000000000000",
        lesson_id=1,
        line_id="L1",
        audio_path="x.m4a",
        score_total=80,
        score_pronunciation=80,
        score_fluency=80,
        score_completeness=80,
    )
    assert isinstance(h.created_at, datetime)
    assert h.created_at.tzinfo is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_models.py -v`
Expected: ModuleNotFoundError on `app.models.db`

- [ ] **Step 3: Create models package and db module**

```python
# app/models/__init__.py
```

```python
# app/models/db.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="k12")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book: Mapped[str] = mapped_column(String(16), index=True)
    lesson_no: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(256))
    role_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)

    history: Mapped[list["History"]] = relationship(back_populates="lesson")  # type: ignore[name-defined]


class History(Base):
    __tablename__ = "history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(Integer, ForeignKey("lessons.id"), index=True)
    line_id: Mapped[str] = mapped_column(String(64))
    audio_path: Mapped[str] = mapped_column(String(512))
    score_total: Mapped[float] = mapped_column(Float)
    score_pronunciation: Mapped[float] = mapped_column(Float)
    score_fluency: Mapped[float] = mapped_column(Float)
    score_completeness: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    lesson: Mapped["Lesson"] = relationship(back_populates="history")  # type: ignore[name-defined]


class TtsCache(Base):
    __tablename__ = "tts_cache"

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    audio_path: Mapped[str] = mapped_column(String(512))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/models tests/test_models.py
git commit -m "feat(backend): add SQLAlchemy ORM models for users, lessons, history, tts_cache"
```

---

### Task 6: Configure Alembic and create initial migration

**Files:**
- Create: `backend/app/db/migrations/env.py`
- Create: `backend/app/db/migrations/script.py.mako`
- Create: `backend/app/db/migrations/versions/0001_init.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic.sh` (helper)

- [ ] **Step 1: Initialize alembic in the package directory**

Run:
```bash
cd backend
mkdir -p app/db/migrations/versions
# create alembic.ini
cat > alembic.ini <<'EOF'
[alembic]
script_location = app/db/migrations
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
EOF
```

- [ ] **Step 2: Create env.py**

```python
# app/db/migrations/env.py
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db.base import Base
from app.models import db as _db_models  # noqa: F401  (register tables)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+asyncpg", ""))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create script.py.mako**

```python
# app/db/migrations/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Generate the initial migration**

Run:
```bash
cd backend
alembic revision --autogenerate -m "init: users, lessons, history, tts_cache"
```
Expected: file created at `app/db/migrations/versions/0001_init.py` (or similar hash). Inspect it — must contain `create_table` for `users`, `lessons`, `history`, `tts_cache`.

- [ ] **Step 5: Test migration round-trip against a throwaway database**

Run:
```bash
cd backend
docker compose up -d postgres
sleep 3
DATABASE_URL=postgresql+asyncpg://english:english@localhost:5432/english_dev alembic upgrade head
DATABASE_URL=postgresql+asyncpg://english:english@localhost:5432/english_dev alembic downgrade base
DATABASE_URL=postgresql+asyncpg://english:english@localhost:5432/english_dev alembic upgrade head
```
Expected: upgrade and downgrade both succeed; no errors.

- [ ] **Step 6: Commit**

```bash
cd backend
git add alembic.ini app/db/migrations
git commit -m "feat(backend): configure alembic and add initial migration"
```

---

### Task 7: Add Pydantic schemas for API contracts

**Files:**
- Create: `backend/app/models/schema.py`
- Test: `backend/tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py
from __future__ import annotations

from app.models.schema import (
    HistoryItem,
    HistoryWriteRequest,
    LessonSummary,
    Line,
    Role,
    ScoreRequest,
    ScoreResponse,
    TtsResponse,
    WordScore,
)


def test_lesson_summary_fields() -> None:
    ls = LessonSummary(id=1, book="nce1", lesson_no=1, title="t", role_count=2, duration_s=10.0)
    assert ls.model_dump()["id"] == 1


def test_role_and_line() -> None:
    role = Role(name="A", lines=[Line(id="L1", text="hi", translation="嗨")])
    assert role.lines[0].id == "L1"


def test_score_request_accepts_audio_bytes() -> None:
    req = ScoreRequest(lesson_id=1, line_id="L1", ref_text="hi", mode="k12", audio=b"\x00\x01")
    assert req.audio[:2] == b"\x00\x01"


def test_score_response_includes_word_details() -> None:
    r = ScoreResponse(
        total=80.0,
        pronunciation=82.0,
        fluency=78.0,
        completeness=80.0,
        word_details=[WordScore(word="hi", score=80, ipa="haɪ")],
        suggestion="ok",
    )
    assert r.word_details[0].word == "hi"


def test_tts_response_has_url_and_duration() -> None:
    t = TtsResponse(audio_url="https://x", duration_ms=1234)
    assert t.duration_ms == 1234


def test_history_write_request_round_trip() -> None:
    req = HistoryWriteRequest(
        device_id="dev",
        lesson_id=1,
        line_id="L1",
        audio_path="x.m4a",
        score_total=80,
        score_pronunciation=80,
        score_fluency=80,
        score_completeness=80,
    )
    assert req.model_dump()["device_id"] == "dev"


def test_history_item() -> None:
    h = HistoryItem(
        id="abc",
        lesson_id=1,
        line_id="L1",
        score_total=80.0,
        score_pronunciation=80.0,
        score_fluency=80.0,
        score_completeness=80.0,
        created_at="2026-07-11T00:00:00Z",
    )
    assert h.line_id == "L1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_schema.py -v`
Expected: ImportError on `app.models.schema`

- [ ] **Step 3: Create the schema module**

```python
# app/models/schema.py
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ====== Lessons ======

class LessonSummary(BaseModel):
    id: int
    book: str
    lesson_no: int
    title: str
    role_count: int
    duration_s: float


class Line(BaseModel):
    id: str
    text: str
    translation: Optional[str] = None
    ipa: Optional[str] = None


class Role(BaseModel):
    name: str
    lines: list[Line]


class LessonDetail(BaseModel):
    id: int
    book: str
    lesson_no: int
    title: str
    roles: list[Role]


# ====== TTS ======

class TtsResponse(BaseModel):
    audio_url: str
    duration_ms: int


# ====== Score ======

class WordScore(BaseModel):
    word: str
    score: float = Field(ge=0, le=100)
    ipa: Optional[str] = None


class ScoreRequest(BaseModel):
    lesson_id: int
    line_id: str
    ref_text: str
    mode: str = "k12"
    audio: bytes


class ScoreResponse(BaseModel):
    total: float = Field(ge=0, le=100)
    pronunciation: float = Field(ge=0, le=100)
    fluency: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=100)
    word_details: list[WordScore]
    suggestion: Optional[str] = None


# ====== History ======

class HistoryWriteRequest(BaseModel):
    device_id: str
    lesson_id: int
    line_id: str
    audio_path: str
    score_total: float
    score_pronunciation: float
    score_fluency: float
    score_completeness: float


class HistoryItem(BaseModel):
    id: str
    lesson_id: int
    line_id: str
    score_total: float
    score_pronunciation: float
    score_fluency: float
    score_completeness: float
    created_at: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_schema.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/models/schema.py tests/test_schema.py
git commit -m "feat(backend): add Pydantic schemas for API contracts"
```

---

### Task 8: Add first lesson corpus (NCE 1 Lesson 1)

**Files:**
- Create: `backend/data/nce1/lesson_001.json`

- [ ] **Step 1: Create the corpus JSON file**

```json
{
  "book": "nce1",
  "lesson": 1,
  "title": "A Private Conversation",
  "roles": [
    {
      "name": "A",
      "lines": [
        {"id": "nce1-L1-A1", "text": "Excuse me, is this your handbag?", "translation": "打扰一下，这是您的手提包吗？"},
        {"id": "nce1-L1-A2", "text": "Yes, it is.", "translation": "是的，是我的。"},
        {"id": "nce1-L1-A3", "text": "Thank you very much.", "translation": "非常感谢。"}
      ]
    },
    {
      "name": "B",
      "lines": [
        {"id": "nce1-L1-B1", "text": "Pardon?", "translation": "什么？"},
        {"id": "nce1-L1-B2", "text": "Is this your handbag?", "translation": "这是您的手提包吗？"},
        {"id": "nce1-L1-B3", "text": "Oh, yes, it is. Thank you.", "translation": "哦，是的，是我的。谢谢。"}
      ]
    }
  ]
}
```

- [ ] **Step 2: Validate JSON parses**

Run: `cd backend && python -c "import json; print(len(json.load(open('data/nce1/lesson_001.json'))['roles']))"`
Expected: `2`

- [ ] **Step 3: Commit**

```bash
cd backend
git add data/nce1/lesson_001.json
git commit -m "feat(backend): add NCE 1 Lesson 1 corpus data"
```

---

### Task 9: Implement corpus loader and lessons endpoints

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/corpus_loader.py`
- Create: `backend/app/api/v1/deps.py`
- Create: `backend/app/api/v1/lessons.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_lessons.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lessons.py
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import corpus_loader


@pytest.fixture
def fake_corpus_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "nce1"
    d.mkdir()
    (d / "lesson_001.json").write_text(
        """{
        "book": "nce1", "lesson": 1, "title": "T", "roles": [
            {"name": "A", "lines": [{"id": "L1", "text": "hi", "translation": "嗨"}]}
        ]}
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_loader, "_CORPUS_ROOT", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_list_lessons_empty_when_no_dir(fake_corpus_dir: Path) -> None:
    (fake_corpus_dir / "nce1").rmdir()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/lessons?book=nce1")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_lessons_returns_one(fake_corpus_dir: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/lessons?book=nce1")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["book"] == "nce1"
    assert data[0]["lesson_no"] == 1
    assert data[0]["role_count"] == 1


@pytest.mark.asyncio
async def test_get_lesson_roles(fake_corpus_dir: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/lessons/1/roles")
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "T"
    assert data["roles"][0]["name"] == "A"
    assert data["roles"][0]["lines"][0]["text"] == "hi"


@pytest.mark.asyncio
async def test_get_lesson_roles_404_when_missing(fake_corpus_dir: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/lessons/999/roles")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "LESSON_NOT_FOUND"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_lessons.py -v`
Expected: ModuleNotFoundError on `app.services` and `app.api.v1.lessons`

- [ ] **Step 3: Create services package**

```python
# app/services/__init__.py
```

- [ ] **Step 4: Implement corpus loader**

```python
# app/services/corpus_loader.py
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
```

- [ ] **Step 5: Add API dependencies (placeholder for now)**

```python
# app/api/v1/deps.py
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session
```

- [ ] **Step 6: Implement lessons router**

```python
# app/api/v1/lessons.py
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
            duration_s=0.0,
        )
        for r in rows
    ]


@router.get("/lessons/{lesson_id}/roles", response_model=LessonDetail)
async def get_lesson_roles(
    lesson_id: int, book: str = Query("nce1")
) -> LessonDetail:
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
```

- [ ] **Step 7: Wire router into main.py**

Modify `backend/app/main.py` — add `from app.api.v1 import health, lessons` and `app.include_router(lessons.router, prefix="/api/v1")`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_lessons.py -v`
Expected: 4 passed

- [ ] **Step 9: Commit**

```bash
cd backend
git add app/services app/api/v1/lessons.py app/api/v1/deps.py app/main.py tests/test_lessons.py
git commit -m "feat(backend): implement /lessons and /lessons/{id}/roles with corpus loader"
```

---

### Task 10: Add provider interfaces and stub providers

**Files:**
- Create: `backend/app/services/interfaces.py`
- Create: `backend/app/services/stub_providers.py`
- Test: `backend/tests/test_stub_providers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stub_providers.py
from __future__ import annotations

import pytest

from app.services.stub_providers import StubASRProvider, StubTTSProvider


@pytest.mark.asyncio
async def test_stub_tts_returns_audio_url_with_deterministic_hash() -> None:
    p = StubTTSProvider()
    r1 = await p.synthesize("hi", voice="k12_female")
    r2 = await p.synthesize("hi", voice="k12_female")
    assert r1.audio_bytes == r2.audio_bytes
    assert r1.duration_ms > 0
    assert r1.audio_url.endswith(".m4a")


@pytest.mark.asyncio
async def test_stub_tts_different_voice_produces_different_audio() -> None:
    p = StubTTSProvider()
    a = await p.synthesize("hi", voice="k12_female")
    b = await p.synthesize("hi", voice="k12_male")
    assert a.audio_bytes != b.audio_bytes


@pytest.mark.asyncio
async def test_stub_asr_recognizes_reference_exactly() -> None:
    p = StubASRProvider()
    res = await p.recognize(audio=b"\x00\x00", ref_text="Hello world")
    assert res.recognized == "Hello world"
    assert res.word_scores == [
        {"word": "Hello", "score": 95.0, "ipa": None},
        {"word": "world", "score": 95.0, "ipa": None},
    ]


@pytest.mark.asyncio
async def test_stub_asr_with_garbage_words_lowers_score() -> None:
    p = StubASRProvider()
    res = await p.recognize(audio=b"\x00\x00", ref_text="Hello world")
    # simulate partial misrecognition by tampering after the fact:
    res.recognized = "Hello there"
    bad = [w for w in res.word_scores if w["word"] not in res.recognized.split()]
    assert len(bad) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_stub_providers.py -v`
Expected: ModuleNotFoundError on `app.services.stub_providers`

- [ ] **Step 3: Create interfaces module**

```python
# app/services/interfaces.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TtsResult:
    audio_bytes: bytes
    duration_ms: int
    audio_url: str


@dataclass(frozen=True)
class AsrWord:
    word: str
    score: float
    ipa: str | None


@dataclass(frozen=True)
class AsrResult:
    recognized: str
    word_scores: list[AsrWord]


class TTSProvider(Protocol):
    async def synthesize(self, text: str, voice: str) -> TtsResult: ...


class ASRProvider(Protocol):
    async def recognize(self, audio: bytes, ref_text: str) -> AsrResult: ...
```

- [ ] **Step 4: Implement stub providers**

```python
# app/services/stub_providers.py
from __future__ import annotations

import hashlib

from app.services.interfaces import AsrResult, AsrWord, TtsResult


class StubTTSProvider:
    """Deterministic TTS that hashes (text, voice) to produce a fake audio blob."""

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        h = hashlib.sha256(f"{voice}::{text}".encode("utf-8")).hexdigest()[:16]
        # 200ms of fake audio per char
        duration_ms = max(200, len(text) * 80)
        return TtsResult(
            audio_bytes=f"STUB_TTS::{h}".encode("utf-8"),
            duration_ms=duration_ms,
            audio_url=f"/static/tts/{h}.m4a",
        )


class StubASRProvider:
    """Recognizes the reference text perfectly when ref_text is provided."""

    async def recognize(self, audio: bytes, ref_text: str) -> AsrResult:
        words = ref_text.split()
        return AsrResult(
            recognized=ref_text,
            word_scores=[AsrWord(word=w, score=95.0, ipa=None) for w in words],
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_stub_providers.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/interfaces.py app/services/stub_providers.py tests/test_stub_providers.py
git commit -m "feat(backend): add TTS/ASR provider interfaces and stub implementations"
```

---

### Task 11: Add 讯飞 TTS provider and TTS cache

**Files:**
- Create: `backend/app/services/xunfei_tts.py`
- Create: `backend/app/services/tts_cache.py`
- Test: `backend/tests/test_tts_cache.py`

- [ ] **Step 1: Write the failing test for tts_cache**

```python
# tests/test_tts_cache.py
from __future__ import annotations

import pytest

from app.services.interfaces import TtsResult
from app.services.tts_cache import TtsCache


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self.store[key] = value


@pytest.mark.asyncio
async def test_cache_miss_returns_none() -> None:
    c = TtsCache(redis=FakeRedis())  # type: ignore[arg-type]
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_cache_set_then_get_roundtrip() -> None:
    c = TtsCache(redis=FakeRedis())  # type: ignore[arg-type]
    await c.set("k", TtsResult(audio_bytes=b"abc", duration_ms=100, audio_url="x"))
    r = await c.get("k")
    assert r is not None
    assert r.audio_bytes == b"abc"
    assert r.duration_ms == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tts_cache.py -v`
Expected: ModuleNotFoundError on `app.services.tts_cache`

- [ ] **Step 3: Implement tts_cache**

```python
# app/services/tts_cache.py
from __future__ import annotations

import json
from typing import Protocol

from app.services.interfaces import TtsResult


class _RedisLike(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ex: int | None = None) -> None: ...


class TtsCache:
    def __init__(self, redis: _RedisLike, ttl: int = 86400) -> None:
        self._redis = redis
        self._ttl = ttl

    @staticmethod
    def _key(text: str, voice: str) -> str:
        import hashlib
        return "tts:" + hashlib.sha256(f"{voice}::{text}".encode("utf-8")).hexdigest()[:32]

    async def get(self, text: str, voice: str) -> TtsResult | None:
        raw = await self._redis.get(self._key(text, voice))
        if raw is None:
            return None
        d = json.loads(raw)
        return TtsResult(audio_bytes=d["audio_b64"].encode(), duration_ms=d["duration_ms"], audio_url=d["audio_url"])

    async def set(self, text: str, voice: str, result: TtsResult) -> None:
        import base64
        payload = json.dumps(
            {
                "audio_b64": base64.b64encode(result.audio_bytes).decode("ascii"),
                "duration_ms": result.duration_ms,
                "audio_url": result.audio_url,
            }
        ).encode("utf-8")
        await self._redis.set(self._key(text, voice), payload, ex=self._ttl)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_tts_cache.py -v`
Expected: 2 passed

- [ ] **Step 5: Implement 讯飞 TTS provider (skeleton — real call in Phase 3)**

```python
# app/services/xunfei_tts.py
from __future__ import annotations

from app.config import settings
from app.services.interfaces import TtsResult
from app.services.stub_providers import StubTTSProvider


class XunfeiTTSProvider:
    """讯飞 TTS provider. Falls back to stub when credentials are missing."""

    def __init__(self) -> None:
        self._stub = StubTTSProvider()

    async def synthesize(self, text: str, voice: str) -> TtsResult:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            return await self._stub.synthesize(text, voice)
        # Real 讯飞 WebSocket TTS call goes here in a later phase.
        # For L1 MVP we ship the stub path; integration is gated on credentials.
        return await self._stub.synthesize(text, voice)
```

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/tts_cache.py app/services/xunfei_tts.py tests/test_tts_cache.py
git commit -m "feat(backend): add TTS cache and 讯飞 TTS provider (stub fallback)"
```

---

### Task 12: Implement /tts endpoint

**Files:**
- Create: `backend/app/api/v1/tts.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_tts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tts.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_tts_returns_audio_url_and_duration() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "k12_female"})
    assert r.status_code == 200
    data = r.json()
    assert data["audio_url"].endswith(".m4a")
    assert data["duration_ms"] > 0


@pytest.mark.asyncio
async def test_tts_rejects_empty_text() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "", "voice": "k12_female"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_tts_is_deterministic_across_calls() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "k12_female"})
        r2 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "k12_female"})
    assert r1.json()["audio_url"] == r2.json()["audio_url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tts.py -v`
Expected: 404 — endpoint not registered

- [ ] **Step 3: Implement /tts router**

```python
# app/api/v1/tts.py
from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.errors import AppError
from app.models.schema import TtsResponse
from app.services.xunfei_tts import XunfeiTTSProvider

router = APIRouter(tags=["tts"])
_provider = XunfeiTTSProvider()


@router.get("/tts", response_model=TtsResponse)
async def tts(text: str = Query(..., min_length=1), voice: str = Query("k12_female")) -> TtsResponse:
    if not text.strip():
        raise AppError(status_code=400, message="text must not be empty", code="BAD_REQUEST")
    r = await _provider.synthesize(text, voice)
    return TtsResponse(audio_url=r.audio_url, duration_ms=r.duration_ms)
```

- [ ] **Step 4: Wire router in main.py**

Modify `backend/app/main.py` — add `from app.api.v1 import health, lessons, tts` and `app.include_router(tts.router, prefix="/api/v1")`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_tts.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/api/v1/tts.py app/main.py tests/test_tts.py
git commit -m "feat(backend): implement GET /tts with 讯飞 provider (stub fallback)"
```

---

### Task 13: Add 讯飞 ASR provider

**Files:**
- Create: `backend/app/services/xunfei_asr.py`
- Test: `backend/tests/test_xunfei_asr.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_xunfei_asr.py
from __future__ import annotations

import pytest

from app.services.xunfei_asr import XunfeiASRProvider


@pytest.mark.asyncio
async def test_falls_back_to_stub_when_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.xunfei_asr.settings.xunfei_app_id", "")
    p = XunfeiASRProvider()
    res = await p.recognize(audio=b"\x00", ref_text="Hello world")
    assert res.recognized == "Hello world"
    assert [w.word for w in res.word_scores] == ["Hello", "world"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_xunfei_asr.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Implement 讯飞 ASR provider**

```python
# app/services/xunfei_asr.py
from __future__ import annotations

from app.config import settings
from app.services.interfaces import AsrResult
from app.services.stub_providers import StubASRProvider


class XunfeiASRProvider:
    """讯飞 ASR provider. Falls back to stub when credentials are missing."""

    def __init__(self) -> None:
        self._stub = StubASRProvider()

    async def recognize(self, audio: bytes, ref_text: str) -> AsrResult:
        if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
            return await self._stub.recognize(audio, ref_text)
        # Real 讯飞 IAT WebSocket call goes here in a later phase.
        return await self._stub.recognize(audio, ref_text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_xunfei_asr.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/xunfei_asr.py tests/test_xunfei_asr.py
git commit -m "feat(backend): add 讯飞 ASR provider (stub fallback)"
```

---

### Task 14: Implement read-along scoring algorithm

**Files:**
- Create: `backend/app/scoring/__init__.py`
- Create: `backend/app/scoring/read_along.py`
- Test: `backend/tests/test_read_along_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_read_along_scoring.py
from __future__ import annotations

import pytest

from app.scoring.read_along import score_read_along
from app.services.interfaces import AsrResult, AsrWord


def _asr(recognized: str, word_scores: list[AsrWord]) -> AsrResult:
    return AsrResult(recognized=recognized, word_scores=word_scores)


def test_perfect_reading_is_95() -> None:
    ref = "Hello world"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 95.0, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert res.total == pytest.approx(95.0, abs=0.5)
    assert res.pronunciation == 95.0
    assert res.fluency > 80
    assert res.completeness == 100.0


def test_completeness_drops_on_missing_words() -> None:
    ref = "Hello world friend"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(recognized="Hello world", word_scores=[AsrWord("Hello", 90, None), AsrWord("world", 90, None)]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert res.completeness == pytest.approx(200 / 3, abs=0.5)
    assert res.total < 80


def test_low_pronunciation_words_drag_total_down() -> None:
    ref = "Hello world"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord("Hello", 30, None), AsrWord("world", 30, None)]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert res.pronunciation == 30.0
    assert res.total < 60


def test_pause_count_penalizes_fluency() -> None:
    ref = "Hello world"
    clean = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 90, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    paused = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 90, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=5,
    )
    assert paused.fluency < clean.fluency


def test_word_details_preserve_order() -> None:
    ref = "Good morning everyone"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 80, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert [w.word for w in res.word_details] == ref.split()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_read_along_scoring.py -v`
Expected: ModuleNotFoundError on `app.scoring`

- [ ] **Step 3: Create scoring package**

```python
# app/scoring/__init__.py
```

- [ ] **Step 4: Implement scoring algorithm**

```python
# app/scoring/read_along.py
from __future__ import annotations

from dataclasses import dataclass

from app.services.interfaces import AsrResult
from app.models.schema import WordScore


@dataclass(frozen=True)
class ScoreResult:
    total: float
    pronunciation: float
    fluency: float
    completeness: float
    word_details: list[WordScore]
    suggestion: str | None = None


def score_read_along(
    ref_text: str,
    asr: AsrResult,
    speech_rate_wpm: float,
    pause_count: int,
) -> ScoreResult:
    """Read-along scoring per spec §5.3.

    total = 0.5 * pronunciation + 0.3 * fluency + 0.2 * completeness
    """
    ref_words = ref_text.split()
    rec_words = asr.recognized.split()

    if asr.word_scores:
        pronunciation = sum(w.score for w in asr.word_scores) / len(asr.word_scores)
    else:
        pronunciation = 0.0

    # Completeness: ratio of recognized to reference word count, capped at 100
    completeness = min(100.0, len(rec_words) / max(1, len(ref_words)) * 100.0)

    # Fluency: 0.4 rate component + 0.6 pause component
    # Ideal rate ~120 wpm; clamp to [0, 100]
    rate_score = max(0.0, min(100.0, 100.0 - abs(120.0 - speech_rate_wpm) * 0.5))
    pause_penalty = max(0.0, 100.0 - pause_count * 15.0)
    fluency = rate_score * 0.4 + pause_penalty * 0.6

    total = pronunciation * 0.5 + fluency * 0.3 + completeness * 0.2

    # Word-level details: align by position; missing words get score 0
    details: list[WordScore] = []
    asr_by_idx = {i: w for i, w in enumerate(asr.word_scores)}
    for i, ref_w in enumerate(ref_words):
        w = asr_by_idx.get(i)
        if w is not None and w.word.lower() == ref_w.lower():
            details.append(WordScore(word=ref_w, score=w.score, ipa=w.ipa))
        else:
            details.append(WordScore(word=ref_w, score=0.0, ipa=None))

    suggestion = _build_suggestion(pronunciation, fluency, completeness, pause_count)
    return ScoreResult(
        total=round(total, 1),
        pronunciation=round(pronunciation, 1),
        fluency=round(fluency, 1),
        completeness=round(completeness, 1),
        word_details=details,
        suggestion=suggestion,
    )


def _build_suggestion(pron: float, fluency: float, comp: float, pauses: int) -> str | None:
    tips: list[str] = []
    if pron < 70:
        tips.append("注意单词发音")
    if comp < 80:
        tips.append("不要漏读单词")
    if pauses > 3:
        tips.append("减少停顿会更流利")
    if fluency < 60:
        tips.append("试着保持稳定语速")
    return "；".join(tips) if tips else None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_read_along_scoring.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/scoring tests/test_read_along_scoring.py
git commit -m "feat(backend): implement read-along scoring algorithm (spec §5.3)"
```

---

### Task 15: Implement /score endpoint

**Files:**
- Create: `backend/app/api/v1/score.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_score.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_score.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_score_returns_full_breakdown() -> None:
    payload = {
        "lesson_id": 1,
        "line_id": "nce1-L1-A1",
        "ref_text": "Excuse me",
        "mode": "k12",
        # tiny fake m4a header
        "audio": "AAAAGGZ0eXBpc29tAAAAAGlzbzZtcDQy",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data
    for k in ("pronunciation", "fluency", "completeness"):
        assert 0 <= data[k] <= 100
    assert isinstance(data["word_details"], list)
    assert data["word_details"][0]["word"] == "Excuse"


@pytest.mark.asyncio
async def test_score_rejects_empty_audio() -> None:
    payload = {
        "lesson_id": 1,
        "line_id": "L1",
        "ref_text": "hi",
        "mode": "k12",
        "audio": "",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/score", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_score.py -v`
Expected: 404 — endpoint missing

- [ ] **Step 3: Implement /score router**

```python
# app/api/v1/score.py
from __future__ import annotations

import base64
import os

from fastapi import APIRouter

from app.core.errors import AppError
from app.models.schema import ScoreRequest, ScoreResponse
from app.scoring.read_along import score_read_along
from app.services.xunfei_asr import XunfeiASRProvider

router = APIRouter(tags=["score"])
_asr = XunfeiASRProvider()


@router.post("/score", response_model=ScoreResponse)
async def score(req: ScoreRequest) -> ScoreResponse:
    if not req.audio:
        raise AppError(status_code=400, message="audio is required", code="BAD_REQUEST")

    # 1. Persist audio to a tmp path (real impl: object storage)
    audio_path = _save_audio(req.audio)

    # 2. Run ASR
    asr_result = await _asr.recognize(audio=req.audio, ref_text=req.ref_text)

    # 3. Estimate speech rate (rough: ASR recognized words over a 4s budget window)
    word_count = max(1, len(asr_result.recognized.split()))
    speech_rate_wpm = (word_count / 4.0) * 60.0

    # 4. Score
    scored = score_read_along(
        ref_text=req.ref_text,
        asr=asr_result,
        speech_rate_wpm=speech_rate_wpm,
        pause_count=0,
    )
    # best-effort cleanup; ignore failures
    try:
        os.unlink(audio_path)
    except OSError:
        pass
    return ScoreResponse(
        total=scored.total,
        pronunciation=scored.pronunciation,
        fluency=scored.fluency,
        completeness=scored.completeness,
        word_details=scored.word_details,
        suggestion=scored.suggestion,
    )


def _save_audio(audio: bytes) -> str:
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".m4a")
    with os.fdopen(fd, "wb") as f:
        f.write(audio)
    return path
```

> NOTE: For real 讯飞 integration the audio must be a valid m4a/opus/pcm blob. L1 MVP uses stub ASR which ignores audio content, so any non-empty bytes suffice for the test path. Real audio validation belongs in Phase 3.

- [ ] **Step 4: Wire router in main.py**

Modify `backend/app/main.py` — add `from app.api.v1 import health, lessons, tts, score` and `app.include_router(score.router, prefix="/api/v1")`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_score.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/api/v1/score.py app/main.py tests/test_score.py
git commit -m "feat(backend): implement POST /score with read-along algorithm"
```

---

### Task 16: Implement /history endpoints

**Files:**
- Create: `backend/app/api/v1/history.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_history.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_write_then_list_history(tmp_path, monkeypatch) -> None:
    # Use a unique device id to isolate from other test runs
    device_id = "test-device-history-001"
    write = {
        "device_id": device_id,
        "lesson_id": 1,
        "line_id": "L1",
        "audio_path": "/tmp/x.m4a",
        "score_total": 88.0,
        "score_pronunciation": 90.0,
        "score_fluency": 85.0,
        "score_completeness": 88.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post("/api/v1/history", json=write)
        assert r1.status_code == 201, r1.text
        r2 = await c.get("/api/v1/history", params={"device_id": device_id})
    assert r2.status_code == 200
    items = r2.json()
    assert len(items) >= 1
    assert items[0]["line_id"] == "L1"
    assert items[0]["score_total"] == 88.0


@pytest.mark.asyncio
async def test_history_writes_returns_400_on_missing_fields() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/history", json={"device_id": "x"})
    assert r.status_code == 422  # Pydantic validation error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_history.py -v`
Expected: 404 on POST and GET

- [ ] **Step 3: Implement /history router**

```python
# app/api/v1/history.py
from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.v1.deps import get_db
from app.db.session import get_sessionmaker
from app.models.db import History, User
from app.models.schema import HistoryItem, HistoryWriteRequest
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["history"])


async def _get_or_create_user(db: AsyncSession, device_id: str) -> User:
    res = await db.execute(select(User).where(User.device_id == device_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(device_id=device_id)
        db.add(user)
        await db.flush()
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
```

- [ ] **Step 4: Wire router in main.py**

Modify `backend/app/main.py` — add `from app.api.v1 import health, lessons, tts, score, history` and `app.include_router(history.router, prefix="/api/v1")`.

- [ ] **Step 5: Wire the test conftest to use a temp sqlite-or-skip pattern**

> NOTE: The full test path uses Postgres; for local fast tests we will use sqlite. To keep this plan focused, the test for history uses an env-overridden DB URL pointing at a `sqlite+aiosqlite:///:memory:` instance OR marks the test as integration-only. The simpler path: require Postgres for this test and run it via `docker compose up -d postgres` before pytest.

Add the dependency to `pyproject.toml` `[project.optional-dependencies] dev` list:

```toml
aiosqlite>=0.20
```

Run: `cd backend && pip install aiosqlite`

Update `app/db/session.py` to swap URL when sqlite:

Modify the file — replace the body of `get_engine()` with:

```python
@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_async_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
```

Also update `app/db/migrations/env.py` so autogenerate works on sqlite — replace:

```python
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+asyncpg", ""))
```

with:

```python
db_url = settings.database_url
if db_url.startswith("sqlite+"):
    db_url = db_url.replace("sqlite+aiosqlite", "sqlite")
elif db_url.startswith("postgresql+asyncpg"):
    db_url = db_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", db_url)
```

- [ ] **Step 6: Add conftest.py that uses sqlite in-memory for unit tests**

```python
# tests/conftest.py
from __future__ import annotations

import os
from collections.abc import AsyncIterator

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.session import get_engine, get_sessionmaker
from app.api.v1.deps import get_db
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _init_db() -> AsyncIterator[None]:
    """Create all tables in fresh in-memory sqlite for each test."""
    get_engine.cache_clear()  # type: ignore[attr-defined]
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await eng.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    sm = get_sessionmaker()

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with sm() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
```

> NOTE: The `_override_db` is a generator; for ASGITransport we use the context-managed session directly. Adjust if needed.

- [ ] **Step 7: Run history tests**

Run: `cd backend && pytest tests/test_history.py -v`
Expected: 2 passed (one Pydantic 422 for missing fields, one round-trip)

- [ ] **Step 8: Commit**

```bash
cd backend
git add app/api/v1/history.py app/main.py app/db/session.py app/db/migrations/env.py pyproject.toml tests/conftest.py tests/test_history.py
git commit -m "feat(backend): implement /history GET+POST with sqlite test fixture"
```

---

### Task 17: Implement L2 stub dialogue endpoints

**Files:**
- Create: `backend/app/api/v1/dialogue.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_dialogue_stub.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dialogue_stub.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_dialogue_generate_stub_returns_placeholder_scene() -> None:
    payload = {"scene": "ordering_coffee", "mode": "k12"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/generate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "lines" in data
    assert isinstance(data["lines"], list)
    assert data["status"] == "stub"


@pytest.mark.asyncio
async def test_dialogue_turn_stub_echoes_user_input() -> None:
    payload = {
        "scene_id": "ordering_coffee",
        "history": [{"role": "user", "text": "Hi"}],
        "user_audio_b64": "AAAA",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "stub"
    assert "reply_text" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_dialogue_stub.py -v`
Expected: 404 on both

- [ ] **Step 3: Implement stub endpoints**

```python
# app/api/v1/dialogue.py
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["dialogue"])


class DialogueGenerateRequest(BaseModel):
    scene: str
    mode: str = "k12"


class DialogueGenerateResponse(BaseModel):
    scene_id: str
    status: str  # "stub" | "ready"
    lines: list[dict]


class DialogueTurnRequest(BaseModel):
    scene_id: str
    history: list[dict]
    user_audio_b64: str = ""


class DialogueTurnResponse(BaseModel):
    status: str  # "stub"
    reply_text: str
    reply_audio_url: str | None = None


@router.post("/dialogue/generate", response_model=DialogueGenerateResponse)
async def generate(req: DialogueGenerateRequest) -> DialogueGenerateResponse:
    return DialogueGenerateResponse(
        scene_id=req.scene,
        status="stub",
        lines=[{"role": "system", "text": f"[STUB] scene '{req.scene}' not yet implemented"}],
    )


@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
async def turn(req: DialogueTurnRequest) -> DialogueTurnResponse:
    return DialogueTurnResponse(
        status="stub",
        reply_text=f"[STUB] dialogue turn for scene {req.scene_id} not yet implemented",
    )
```

- [ ] **Step 4: Wire router in main.py**

Modify `backend/app/main.py` — add `from app.api.v1 import health, lessons, tts, score, history, dialogue` and `app.include_router(dialogue.router, prefix="/api/v1")`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_dialogue_stub.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/api/v1/dialogue.py app/main.py tests/test_dialogue_stub.py
git commit -m "feat(backend): add L2 stub /dialogue/generate and /dialogue/turn"
```

---

### Task 18: Full L1 integration test

**Files:**
- Create: `backend/tests/test_l1_flow.py`

- [ ] **Step 1: Write the end-to-end L1 happy-path test**

```python
# tests/test_l1_flow.py
from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_full_l1_read_along_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # 1. list lessons
        r = await c.get("/api/v1/lessons", params={"book": "nce1"})
        assert r.status_code == 200
        lessons = r.json()
        assert len(lessons) >= 1
        lesson_id = lessons[0]["id"]

        # 2. get roles for that lesson
        r = await c.get(f"/api/v1/lessons/{lesson_id}/roles")
        assert r.status_code == 200
        detail = r.json()
        first_line = detail["roles"][0]["lines"][0]
        ref_text = first_line["text"]
        line_id = first_line["id"]

        # 3. fetch TTS
        r = await c.get("/api/v1/tts", params={"text": ref_text, "voice": "k12_female"})
        assert r.status_code == 200
        assert r.json()["audio_url"]

        # 4. submit score
        fake_audio = base64.b64decode("AAAAGGZ0eXBpc29tAAAAAGlzbzZtcDQy")
        r = await c.post(
            "/api/v1/score",
            json={
                "lesson_id": lesson_id,
                "line_id": line_id,
                "ref_text": ref_text,
                "mode": "k12",
                "audio": base64.b64encode(fake_audio).decode("ascii"),
            },
        )
        assert r.status_code == 200, r.text
        score = r.json()
        assert 0 <= score["total"] <= 100
        assert score["word_details"], "should have word-level details"

        # 5. write history
        r = await c.post(
            "/api/v1/history",
            json={
                "device_id": "integration-test-device",
                "lesson_id": lesson_id,
                "line_id": line_id,
                "audio_path": "/tmp/x.m4a",
                "score_total": score["total"],
                "score_pronunciation": score["pronunciation"],
                "score_fluency": score["fluency"],
                "score_completeness": score["completeness"],
            },
        )
        assert r.status_code == 201

        # 6. read it back
        r = await c.get("/api/v1/history", params={"device_id": "integration-test-device"})
        assert r.status_code == 200
        assert len(r.json()) >= 1
```

- [ ] **Step 2: Run the integration test**

Run: `cd backend && pytest tests/test_l1_flow.py -v`
Expected: 1 passed (covers list → roles → tts → score → history round-trip)

- [ ] **Step 3: Run the full suite to confirm no regressions**

Run: `cd backend && pytest -v`
Expected: all tests pass (target: 30+ tests across 9 files)

- [ ] **Step 4: Commit**

```bash
cd backend
git add tests/test_l1_flow.py
git commit -m "test(backend): add full L1 read-along integration test"
```

---

### Task 19: Final lint + type + coverage gate

**Files:**
- Modify: `backend/app/main.py` if lint complains

- [ ] **Step 1: Run ruff and mypy, fix any issues**

Run: `cd backend && ruff check . && ruff format --check . && mypy app`
Expected: clean. If mypy complains, narrow the import or add a `# type: ignore[xxx]` comment with a reason.

- [ ] **Step 2: Run pytest with coverage gate**

Run: `cd backend && pytest --cov=app --cov-fail-under=85`
Expected: coverage ≥ 85%; all tests pass

- [ ] **Step 3: Manually curl the running server to confirm /docs works**

Run: `cd backend && uvicorn app.main:app --port 8765 &` (in background), `sleep 2 && curl -sS http://localhost:8765/docs | head -3 && kill %1`
Expected: HTML response from FastAPI Swagger UI

- [ ] **Step 4: Commit any formatting fixes**

```bash
cd backend
git add -A
git diff --cached --quiet || git commit -m "style(backend): apply ruff formatting"
```

- [ ] **Step 5: Push to GitHub**

```bash
cd backend
cd ..
git add backend/
git push origin main
```
Expected: GitHub Actions runs `backend-ci.yml` and `android-ci.yml` (android will fail because no android/ project yet — that's expected and not blocking for backend L1).

---

## Self-Review Checklist (run before declaring done)

- [ ] All 9 spec §7 endpoints exist (`/health`, `/lessons`, `/lessons/{id}/roles`, `/tts`, `/score`, `/history` GET, `/history` POST, `/dialogue/generate`, `/dialogue/turn`)
- [ ] 7 endpoints are L1 implemented; 2 (`/dialogue/*`) are stubs that return `status: "stub"`
- [ ] Read-along scoring matches spec §5.3 formula `0.5*p + 0.3*f + 0.2*c`
- [ ] DB tables from spec §6.2 (users, lessons, history, tts_cache) all created by Alembic
- [ ] No real 讯飞 credentials required to run (graceful fallback to stub)
- [ ] `mypy --strict` clean
- [ ] `ruff check` + `ruff format --check` clean
- [ ] Coverage ≥ 85%
- [ ] L1 integration test passes end-to-end
- [ ] Spec §10 Phase 2 backend step 1 + 2 complete
