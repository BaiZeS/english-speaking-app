from __future__ import annotations

import shutil
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
    shutil.rmtree(fake_corpus_dir / "nce1")
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


@pytest.mark.asyncio
async def test_path_traversal_rejected(fake_corpus_dir: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for bad_book in ("../something", "../../../../tmp"):
            r = await c.get("/api/v1/lessons", params={"book": bad_book})
            assert r.status_code == 400, bad_book
            assert r.json()["error"]["code"] == "INVALID_BOOK"
            r = await c.get("/api/v1/lessons/1/roles", params={"book": bad_book})
            assert r.status_code == 400, bad_book
            assert r.json()["error"]["code"] == "INVALID_BOOK"


@pytest.mark.asyncio
async def test_gapped_corpus_id_consistency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "nce1"
    d.mkdir()
    (d / "lesson_001.json").write_text(
        """{
        "book": "nce1", "lesson": 1, "title": "T1", "roles": [
            {"name": "A", "lines": [{"id": "L1", "text": "hi", "translation": "嗨"}]}
        ]}
        """,
        encoding="utf-8",
    )
    (d / "lesson_003.json").write_text(
        """{
        "book": "nce1", "lesson": 3, "title": "T3", "roles": [
            {"name": "B", "lines": [{"id": "L3", "text": "yo", "translation": "哟"}]}
        ]}
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_loader, "_CORPUS_ROOT", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/lessons?book=nce1")
        assert r.status_code == 200
        data = r.json()
        assert [item["id"] for item in data] == [1, 3]

        r = await c.get("/api/v1/lessons/3/roles?book=nce1")
        assert r.status_code == 200

        r = await c.get("/api/v1/lessons/2/roles?book=nce1")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LESSON_NOT_FOUND"
