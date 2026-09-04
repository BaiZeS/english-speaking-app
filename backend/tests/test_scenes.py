from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.course import CATEGORY_ORDER, SceneCourse
from app.models.schema import LessonDetail
from app.services import scene_store
from tests.test_scene_store import write_course

REAL_DATA_ROOT = Path(scene_store.__file__).resolve().parent.parent.parent / "data"


@pytest.fixture
def scene_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """两篇假课 (daily / workplace) + 缓存清理, 端点行为与真内容解耦."""
    write_course(tmp_path, "scene_alpha", "daily")
    write_course(tmp_path, "scene_beta", "workplace", title="工作汇报")
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    yield tmp_path
    scene_store.invalidate_cache()


@pytest.fixture
def real_curated_root(monkeypatch: pytest.MonkeyPatch) -> Any:
    """把读路径指回仓库里真正 ship 的 data/ 目录 (内容契约测试用)."""
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", REAL_DATA_ROOT)
    scene_store.invalidate_cache()
    yield REAL_DATA_ROOT
    scene_store.invalidate_cache()


# ------------------------------------------------------------- GET /scenes


@pytest.mark.asyncio
async def test_list_scenes_returns_categories_and_summaries(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes")
    assert r.status_code == 200
    body = r.json()
    assert [cat["id"] for cat in body["categories"]] == list(CATEGORY_ORDER)
    assert [cat["count"] for cat in body["categories"]] == [1, 1, 0, 0]
    assert body["total"] == 2
    summary = body["scenes"][0]
    assert summary["id"] == "scene_alpha"
    assert summary["category"] == "daily"
    assert summary["cleared"] is False
    assert summary["best_total"] == 0.0
    assert summary["attempts"] == 0
    # 摘要不带大块内容 (剧本/词汇要进详情页)
    assert "vocab" not in summary
    assert "mission" not in summary
    assert "briefing" not in summary


@pytest.mark.asyncio
async def test_list_scenes_filter_by_category(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes", params={"category": "workplace"})
    assert r.status_code == 200
    body = r.json()
    assert [s["id"] for s in body["scenes"]] == ["scene_beta"]
    assert body["total"] == 1
    assert [cat["count"] for cat in body["categories"]] == [1, 1, 0, 0]


@pytest.mark.asyncio
async def test_list_scenes_empty_category_returns_empty_list(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes", params={"category": "exam"})
    assert r.status_code == 200
    assert r.json()["scenes"] == []
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_scenes_accepts_device_id(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes", params={"device_id": "dev-1"})
    assert r.status_code == 200
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_scenes_rejects_unknown_category(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes", params={"category": "kitchen"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_CATEGORY"


# -------------------------------------------------------- GET /scenes/{id}


@pytest.mark.asyncio
async def test_get_scene_detail(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes/scene_alpha")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "scene_alpha"
    assert body["source"] == "curated"
    assert body["schema_version"] == 1
    assert len(body["vocab"]) == 6
    assert [s["type"] for s in body["briefing"]] == [
        "read_along",
        "retell",
        "translate",
        "make_sentence",
    ]
    # 步骤 id 由模型按序补齐 (P2 的状态机要靠它记进度)
    assert [s["id"] for s in body["briefing"]] == ["f1", "f2", "f3", "f4"]
    assert [t["id"] for t in body["mission"]["tasks"]] == ["t1", "t2", "t3"]
    assert body["mission"]["exchanges"][0]["b"] == "A small coffee, please."


@pytest.mark.asyncio
async def test_get_scene_404(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes/scene_missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SCENE_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_scene_rejects_traversal(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for bad in ("..", "../../etc/passwd", "scene%2E%2E%2F..", "a/b"):
            r = await c.get(f"/api/v1/scenes/{bad}")
            assert r.status_code in (400, 404), bad
            if r.status_code == 400:
                assert r.json()["error"]["code"] == "INVALID_SCENE_ID"


# ----------------------------------------------------- GET /scenes/{id}/script


@pytest.mark.asyncio
async def test_script_matches_lesson_detail_shape(scene_root: Path) -> None:
    """旧客户端只认 LessonDetail 的键; script 必须完整覆盖它们且 roles 形状一致."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes/scene_alpha/script")
    assert r.status_code == 200
    body = r.json()
    assert set(LessonDetail.model_fields) <= set(body)
    assert isinstance(body["id"], int)
    assert isinstance(body["lesson_no"], int)
    assert body["book"] == "scenes"
    assert body["title"] == "测试课程"
    assert body["scene_id"] == "scene_alpha"
    assert [key for key in body if key not in LessonDetail.model_fields] == [
        "scene_id",
        "source",
        "level",
    ]
    assert [role["name"] for role in body["roles"]] == ["A", "B"]
    for role in body["roles"]:
        for line in role["lines"]:
            assert set(line) == {"id", "text", "translation", "ipa"}
    a_lines, b_lines = body["roles"][0]["lines"], body["roles"][1]["lines"]
    assert len(a_lines) == len(b_lines) == 2
    assert [ln["id"] for ln in a_lines] == ["s1-a", "s2-a"]
    assert [ln["id"] for ln in b_lines] == ["s1-b", "s2-b"]
    assert a_lines[0]["text"] == "Hi, what can I get you?"
    assert b_lines[0]["text"] == "A small coffee, please."
    assert b_lines[0]["translation"] == "一杯小咖啡，谢谢。"  # noqa: RUF001


@pytest.mark.asyncio
async def test_script_404_and_traversal(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes/scene_missing/script")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "SCENE_NOT_FOUND"
        r = await c.get("/api/v1/scenes/..%2F..%2Fetc%2Fpasswd/script")
        assert r.status_code in (400, 404)


# ------------------------------------------------- 真实 curated 内容契约 (8 篇)


def _real_courses() -> list[SceneCourse]:
    assert REAL_DATA_ROOT.is_dir(), REAL_DATA_ROOT
    paths = sorted((REAL_DATA_ROOT / "scenes").glob("*.json"))
    assert len(paths) == 8, [p.name for p in paths]
    courses: list[SceneCourse] = []
    for path in paths:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        course = SceneCourse.model_validate(raw)
        assert path.stem == course.id, path.name
        assert course.source == "curated"
        courses.append(course)
    return courses


def test_all_eight_curated_files_validate() -> None:
    courses = _real_courses()
    assert len(courses) == 8


def test_curated_categories_have_two_each() -> None:
    counts: dict[str, int] = {}
    for course in _real_courses():
        counts[course.category] = counts.get(course.category, 0) + 1
    assert counts == dict.fromkeys(CATEGORY_ORDER, 2)


def test_curated_ids_are_prefixed_and_unique() -> None:
    ids = [course.id for course in _real_courses()]
    assert len(set(ids)) == 8
    assert all(i.startswith("scene_") for i in ids)


def test_curated_courses_cover_all_four_drill_types() -> None:
    """打基础要真的把 4 种题型都练到, 不然 P2 的 drill 引擎没物料可测."""
    expected = {"read_along", "retell", "translate", "make_sentence"}
    for course in _real_courses():
        assert set(course.step_types) == expected, course.id
        for step in course.briefing:
            assert step.cn_prompt.strip(), course.id
            assert step.accept_notes.strip(), f"{course.id}/{step.id}"
            if step.type == "read_along":
                # 跟读只需要原句: 不要塞参考答案, 免得 P2 用错字段
                assert step.translation_cn.strip(), f"{course.id}/{step.id}"
                assert not step.reference_answer, f"{course.id}/{step.id}"
                assert len(step.ref_text.split()) <= 16, f"{course.id}/{step.id}"
            if step.type == "retell":
                assert step.translation_cn.strip(), f"{course.id}/{step.id}"
                assert step.reference_answer.isascii(), f"{course.id}/{step.id}"
                assert 8 <= len(step.ref_text.split()) <= 40, f"{course.id}/{step.id}"
            if step.type == "translate":
                # ref_text = 中文原句, reference_answer = 参考英文, 不重复填 translation_cn
                assert not step.translation_cn, f"{course.id}/{step.id}"
                assert any("\u4e00" <= ch <= "\u9fff" for ch in step.ref_text), (
                    f"{course.id}/{step.id}"
                )
                assert step.reference_answer.isascii(), f"{course.id}/{step.id}"
                if step.target_word:
                    assert step.target_word in step.reference_answer, f"{course.id}/{step.id}"
            if step.type == "make_sentence":
                assert not step.ref_text and not step.translation_cn, f"{course.id}/{step.id}"
                assert step.target_word in step.reference_answer, f"{course.id}/{step.id}"


def test_curated_scripts_hold_the_corpus_invariant(real_curated_root: Path) -> None:
    """两角色句数相等 + line id 唯一且 ≤64 + 每行都带中文对照.

    读路径走真目录, 顺带确认 8 篇文件都能被 scene_store 认下 (坏文件会被跳过).
    """
    page = scene_store.list_scenes()
    assert page.total == 8
    for course in _real_courses():
        script = scene_store.to_script(course)
        a_lines, b_lines = script.roles[0].lines, script.roles[1].lines
        assert len(a_lines) == len(b_lines) == len(course.mission.exchanges)
        assert len(a_lines) >= 5, course.id
        ids = [ln.id for ln in a_lines + b_lines]
        assert len(set(ids)) == len(ids)
        assert all(0 < len(i) <= 64 for i in ids)
        assert all(ln.text.strip() for ln in a_lines + b_lines)
        assert all(ln.translation for ln in a_lines + b_lines), course.id
        for line in a_lines + b_lines:
            assert len(line.text.split()) <= 22, f"{course.id} {line.id}: {line.text}"


def test_curated_briefing_and_task_ids_follow_convention() -> None:
    """步骤 id 必须按序 f1..fN, 任务 id t1..tN —— P2/P3 的会话状态机照这个记进度."""
    for course in _real_courses():
        assert [s.id for s in course.briefing] == [
            f"f{i}" for i in range(1, len(course.briefing) + 1)
        ]
        assert [t.id for t in course.mission.tasks] == [
            f"t{i}" for i in range(1, len(course.mission.tasks) + 1)
        ]


def test_curated_exchanges_are_paired_with_chinese() -> None:
    """exchange 必须成对且带中文; 第一对 a 就是开场白 (剧本与 opening 对齐)."""
    for course in _real_courses():
        mission = course.mission
        assert mission.opening_a == mission.exchanges[0].a, course.id
        assert mission.opening_a_cn == mission.exchanges[0].a_cn, course.id
        for i, ex in enumerate(mission.exchanges, start=1):
            assert ex.a.strip() and ex.b.strip(), f"{course.id}/x{i}"
            assert ex.a.isascii(), f"{course.id}/x{i}a"
            assert ex.b.isascii(), f"{course.id}/x{i}b"
            assert ex.a_cn and ex.b_cn, f"{course.id}/x{i}"
            assert not ex.a_cn.isascii() and not ex.b_cn.isascii(), f"{course.id}/x{i}"
            assert len(ex.b.split()) <= 16, f"{course.id}/x{i}b: {ex.b}"


def test_curated_missions_are_clearable_in_the_turn_budget() -> None:
    """回合预算要现实: max_turns 至少够照着参考剧本走完, 又不至于无限拖."""
    for course in _real_courses():
        mission = course.mission
        assert 3 <= len(mission.tasks) <= 5, course.id
        # 回合预算: 至少够照着参考剧本走一遍, 又不给到无限拖.
        assert len(mission.exchanges) <= mission.max_turns <= 2 * len(mission.exchanges), course.id
        assert course.required_task_count <= len(mission.exchanges), course.id
        assert course.required_task_count >= 3, course.id
        for task in mission.tasks:
            assert task.hint_en.strip(), f"{course.id}/{task.id}"
            assert task.hint_en.isascii(), f"{course.id}/{task.id}"
            assert task.hint_cn.strip(), f"{course.id}/{task.id}"
        assert mission.opening_a.endswith(("?", ".", "!")), course.id


def test_curated_vocab_examples_use_the_word() -> None:
    for course in _real_courses():
        assert 6 <= len(course.vocab) <= 12, course.id
        for item in course.vocab:
            stem = item.word.lower().rstrip("s")
            assert stem in item.example_en.lower(), f"{course.id}: {item.word}"
            assert item.ipa.startswith("/") and item.ipa.endswith("/"), item.word
            assert item.meaning_cn.strip() and not item.meaning_cn.isascii(), item.word


def test_curated_metadata_is_learner_facing() -> None:
    for course in _real_courses():
        assert course.level in ("A2", "B1"), course.id
        assert 5 <= course.est_minutes <= 12, course.id
        assert not course.title.isascii() and len(course.title) <= 12, course.id
        assert course.subtitle_en.isascii(), course.id
        assert course.brief_cn and not course.brief_cn.isascii(), course.id
        assert course.goal_text and not course.goal_text.isascii(), course.id
        assert course.skills and len(set(course.skills)) == len(course.skills), course.id


@pytest.mark.asyncio
async def test_real_courses_serve_all_three_endpoints(real_curated_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes")
        assert r.status_code == 200
        ids = [s["id"] for s in r.json()["scenes"]]
        assert len(ids) == 8
        for scene_id in ids:
            detail = await c.get(f"/api/v1/scenes/{scene_id}")
            assert detail.status_code == 200, scene_id
            assert SceneCourse.model_validate(detail.json()).id == scene_id
            script = await c.get(f"/api/v1/scenes/{scene_id}/script")
            assert script.status_code == 200, scene_id
            LessonDetail.model_validate(script.json())


@pytest.mark.asyncio
async def test_scene_router_is_mounted_under_api_v1(real_curated_root: Path) -> None:
    # include_router 后的 _IncludedRouter 没有 .path, 用 OpenAPI 路径表最直接.
    paths = set(app.openapi()["paths"])
    assert {
        "/api/v1/scenes",
        "/api/v1/scenes/{scene_id}",
        "/api/v1/scenes/{scene_id}/script",
    } <= paths


@pytest.mark.asyncio
async def test_get_scene_unknown_in_real_catalog(real_curated_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/scenes/scene_not_here")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SCENE_NOT_FOUND"
