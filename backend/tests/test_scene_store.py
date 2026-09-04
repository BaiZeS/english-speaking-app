from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.models.course import SceneCourse
from app.models.schema import LessonDetail
from app.services import scene_store

# ------------------------------------------------------------- 测试载荷与夹具


def make_course_dict(scene_id: str = "scene_alpha", category: str = "daily", **over: Any) -> dict:
    """最小可过的 SceneCourse 载荷 (测试用); ``over`` 覆盖顶层字段."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "id": scene_id,
        "source": "curated",
        "category": category,
        "title": "测试课程",
        "subtitle_en": "I can order a coffee",
        "goal_text": "能用英语点一杯咖啡",
        "level": "A2",
        "est_minutes": 6,
        "brief_cn": "这是一门用来验证读路径的测试课。",
        "vocab": [
            {
                "word": word,
                "ipa": "/təˈst/",  # noqa: RUF001
                "meaning_cn": "v. 测试",
                "example_en": f"I {word} the coffee.",
            }
            for word in ("order", "milk", "sugar", "cup", "pay", "take")
        ],
        "briefing": [
            {
                "type": "read_along",
                "cn_prompt": "跟读这句话。",
                "ref_text": "I would like a small coffee.",
                "translation_cn": "我要一杯小咖啡。",
            },
            {
                "type": "retell",
                "cn_prompt": "用自己的话说一遍。",
                "ref_text": "The coffee is hot. I take it to go.",
                "translation_cn": "咖啡很烫，我带走。",  # noqa: RUF001
                "reference_answer": "Coffee is hot, take away.",
            },
            {
                "type": "translate",
                "cn_prompt": "请把这句说成英文：不加糖。",  # noqa: RUF001
                "reference_answer": "No sugar, please.",
            },
            {
                "type": "make_sentence",
                "cn_prompt": "用 milk 说一句话。",
                "target_word": "milk",
                "reference_answer": "Some milk, please.",
            },
        ],
        "mission": {
            "persona_cn": "咖啡店店员",
            "user_role_cn": "顾客",
            "context_cn": "在咖啡店柜台点单。",
            "opening_a": "Hi, what can I get you?",
            "opening_a_cn": "你好，要点什么？",  # noqa: RUF001
            "exchanges": [
                {
                    "a": "Hi, what can I get you?",
                    "b": "A small coffee, please.",
                    "a_cn": "你好，要点什么？",  # noqa: RUF001
                    "b_cn": "一杯小咖啡，谢谢。",  # noqa: RUF001
                },
                {
                    "a": "Anything else?",
                    "b": "No, that's all.",
                    "a_cn": "还要别的吗？",  # noqa: RUF001
                    "b_cn": "不用了，谢谢。",  # noqa: RUF001
                },
            ],
            "tasks": [
                {"desc_cn": "说要买什么", "hint_en": "A small coffee, please.", "required": True},
                {"desc_cn": "问价格", "hint_en": "How much is that?", "required": True},
                {"desc_cn": "道别", "hint_en": "Thanks, have a good day.", "required": False},
            ],
            "max_turns": 8,
        },
        "skills": ["pronunciation", "communication"],
    }
    payload.update(over)
    return payload


def write_course(
    root: Path, scene_id: str = "scene_alpha", category: str = "daily", **over: Any
) -> Path:
    """把课程载荷写到 ``root/scenes/<scene_id>.json``."""
    scene_dir = root / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    path = scene_dir / f"{scene_id}.json"
    payload = make_course_dict(scene_id, category, **over)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_raw(root: Path, filename: str, payload: dict[str, Any]) -> Path:
    """写一个原始 (可能不合法的) 课程文件, 文件名与 id 可故意不一致."""
    scene_dir = root / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    path = scene_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def scene_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """空的 data/ 根目录 (含 scenes/ 子目录) + 前后各清一次 TTL 缓存.

    对应 ``tests/test_lessons.py`` 的 ``fake_corpus_dir`` 模式: 只换 root.
    """
    (tmp_path / "scenes").mkdir()
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    yield tmp_path
    scene_store.invalidate_cache()


@pytest.fixture
def two_courses(scene_root: Path) -> Path:
    write_course(scene_root, "scene_alpha", "daily")
    write_course(scene_root, "scene_beta", "workplace", title="工作汇报")
    scene_store.invalidate_cache()
    return scene_root


# ---------------------------------------------------------------- 文件发现


def test_loads_curated_courses_sorted_by_id(two_courses: Path) -> None:
    courses = scene_store.load_curated_courses()
    assert [c.id for c in courses] == ["scene_alpha", "scene_beta"]
    assert isinstance(courses[0], SceneCourse)
    assert courses[1].title == "工作汇报"


def test_load_returns_empty_when_dir_missing(scene_root: Path) -> None:
    shutil.rmtree(scene_root / "scenes")
    assert scene_store.load_curated_courses() == []


def test_broken_json_is_skipped_not_fatal(
    scene_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_course(scene_root, "scene_good", "daily")
    (scene_root / "scenes" / "scene_broken.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level("WARNING", logger="app.services.scene_store"):
        courses = scene_store.load_curated_courses()
    assert [c.id for c in courses] == ["scene_good"]
    assert "scene_broken.json" in caplog.text


def test_schema_invalid_file_is_skipped(scene_root: Path) -> None:
    payload = make_course_dict("scene_few_vocab")
    payload["vocab"] = payload["vocab"][:3]  # 少于 6 个 -> pydantic 拒绝
    write_raw(scene_root, "scene_few_vocab.json", payload)
    assert scene_store.load_curated_courses() == []


def test_top_level_array_is_skipped(scene_root: Path) -> None:
    path = scene_root / "scenes" / "scene_array.json"
    path.write_text("[]", encoding="utf-8")
    assert scene_store.load_curated_courses() == []


def test_filename_must_match_course_id(scene_root: Path) -> None:
    """文件名与 id 不一致会让画廊与 /scenes/{id} 指向不同内容, 直接拒收."""
    write_raw(scene_root, "scene_wrong_name.json", make_course_dict("scene_other"))
    assert scene_store.load_curated_courses() == []
    assert scene_store.get_course("scene_wrong_name") is None


def test_unsupported_schema_version_is_skipped(scene_root: Path) -> None:
    payload = make_course_dict("scene_future")
    payload["schema_version"] = 99
    write_raw(scene_root, "scene_future.json", payload)
    assert scene_store.load_curated_courses() == []


def test_id_uniqueness_is_enforced_by_filename(scene_root: Path) -> None:
    """第二篇想复用同一个 id 就必须同名, 而同名文件会互相覆盖; 异名的被判 文件名!=id 跳过."""
    write_raw(scene_root, "scene_dup.json", {**make_course_dict("scene_dup"), "title": "keeper"})
    write_raw(scene_root, "a_other.json", {**make_course_dict("scene_dup"), "title": "skipped"})
    courses = scene_store.load_curated_courses()
    assert [c.title for c in courses] == ["keeper"]


def test_get_course_falls_back_to_disk(two_courses: Path) -> None:
    """文件在缓存成形之后才落地: 显式 get 仍读得到 (get 有落盘回退)."""
    write_course(two_courses, "scene_late", "travel")
    assert scene_store.get_course("scene_late") is not None


def test_get_course_returns_none_for_unknown(two_courses: Path) -> None:
    assert scene_store.get_course("scene_nope") is None


def test_get_course_rejects_unreadable_file(scene_root: Path) -> None:
    write_raw(scene_root, "scene_bad.json", {"id": "scene_bad"})  # 结构不合法
    assert scene_store.get_course("scene_bad") is None


# ---------------------------------------------------------------- TTL 缓存


def test_cache_holds_within_ttl(scene_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_course(scene_root, "scene_alpha", "daily")
    assert [c.id for c in scene_store.load_curated_courses()] == ["scene_alpha"]
    calls = {"n": 0}
    real = scene_store._load_from_disk

    def spy() -> list[SceneCourse]:
        calls["n"] += 1
        return real()

    monkeypatch.setattr(scene_store, "_load_from_disk", spy)
    write_course(scene_root, "scene_new", "travel")
    assert [c.id for c in scene_store.load_curated_courses()] == ["scene_alpha"]
    assert calls["n"] == 0, "TTL 内不应再读盘"


def test_cache_expires_after_ttl_and_invalidate_is_immediate(
    scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_course(scene_root, "scene_alpha", "daily")
    clock = {"t": 1_000.0}
    monkeypatch.setattr(scene_store, "_now", lambda: clock["t"])
    assert len(scene_store.load_curated_courses()) == 1
    write_course(scene_root, "scene_new", "travel")
    assert len(scene_store.load_curated_courses()) == 1, "TTL 内保持旧值"
    clock["t"] += scene_store.CACHE_TTL_SECONDS + 1
    assert {c.id for c in scene_store.load_curated_courses()} == {"scene_alpha", "scene_new"}
    write_course(scene_root, "scene_now", "exam")
    scene_store.invalidate_cache()
    assert len(scene_store.load_curated_courses()) == 3


def test_cache_is_scoped_to_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """换 root (测试之间/未来多目录) 不能命中上一个 root 的缓存."""
    for name in ("one", "two"):
        root = tmp_path / name
        (root / "scenes").mkdir(parents=True)
        write_course(root, f"scene_{name}", "daily")
        monkeypatch.setattr(scene_store, "_CORPUS_ROOT", root)
        # 不手动 invalidate: 上一个 root 的缓存不能命中这个 root (缓存键含目录).
        assert [c.id for c in scene_store.load_curated_courses()] == [f"scene_{name}"]


# ------------------------------------------------------------ 列表与摘要


def test_list_scenes_lists_every_category(two_courses: Path) -> None:
    page = scene_store.list_scenes()
    assert [c.id for c in page.categories] == ["daily", "workplace", "exam", "travel"]
    assert [c.count for c in page.categories] == [1, 1, 0, 0]
    assert [c.label_cn for c in page.categories] == ["日常交流", "职场商务", "考试面试", "旅行出国"]
    assert page.total == 2
    assert [s.id for s in page.scenes] == ["scene_alpha", "scene_beta"]


def test_list_scenes_filter_keeps_full_counts(two_courses: Path) -> None:
    page = scene_store.list_scenes(category="workplace")
    assert [s.id for s in page.scenes] == ["scene_beta"]
    assert page.total == 1
    assert [c.count for c in page.categories] == [1, 1, 0, 0], "分类计数恒为全量"


def test_summary_shape(two_courses: Path) -> None:
    summary = scene_store.list_scenes(category="daily").scenes[0]
    assert summary.model_dump() == {
        "id": "scene_alpha",
        "source": "curated",
        "category": "daily",
        "title": "测试课程",
        "subtitle_en": "I can order a coffee",
        "level": "A2",
        "est_minutes": 6,
        "brief_cn": "这是一门用来验证读路径的测试课。",
        "skills": ["pronunciation", "communication"],
        "vocab_count": 6,
        "briefing_count": 4,
        "task_count": 3,
        "required_task_count": 2,
        "max_turns": 8,
        "cleared": False,
        "best_total": 0.0,
        "attempts": 0,
    }


def test_summary_picks_up_progress(two_courses: Path) -> None:
    progress = {
        "scene_alpha": scene_store.CourseProgress(cleared=True, best_total=88.5, attempts=3),
    }
    page = scene_store.list_scenes(progress=progress)
    alpha = next(s for s in page.scenes if s.id == "scene_alpha")
    beta = next(s for s in page.scenes if s.id == "scene_beta")
    assert (alpha.cleared, alpha.best_total, alpha.attempts) == (True, 88.5, 3)
    assert (beta.cleared, beta.best_total, beta.attempts) == (False, 0.0, 0)


def test_list_scenes_accepts_premerged_courses(two_courses: Path) -> None:
    """P4 把 merge_courses 的结果直接喂进来, 摘要/计数都按合并后的池子算."""
    extra = SceneCourse.model_validate(make_course_dict("scene_gamma", "exam"))
    merged = scene_store.merge_courses(scene_store.load_curated_courses(), [extra])
    page = scene_store.list_scenes(courses=merged)
    assert [s.id for s in page.scenes] == ["scene_alpha", "scene_beta", "scene_gamma"]
    assert [c.count for c in page.categories] == [1, 1, 1, 0]


def test_merge_courses_generated_wins_on_id_conflict() -> None:
    curated = SceneCourse.model_validate(make_course_dict("scene_x", title="文件版"))
    generated = SceneCourse.model_validate(
        make_course_dict("scene_x", title="生成版", source="generated")
    )
    merged = scene_store.merge_courses([curated], [generated])
    assert [c.title for c in merged] == ["生成版"]
    assert merged[0].source == "generated"


def test_device_id_is_accepted_and_inert(scene_root: Path) -> None:
    """P1 还没有 course_progress; 传 device_id 不影响结果, 只是形状先稳定."""
    write_course(scene_root, "scene_alpha", "daily")
    scene_store.invalidate_cache()
    page = scene_store.list_scenes(device_id="device-123")
    assert [s.id for s in page.scenes] == ["scene_alpha"]
    assert page.scenes[0].cleared is False


# --------------------------------------------------------------------- 剧本


def test_script_shape_matches_lesson_detail(two_courses: Path) -> None:
    course = scene_store.get_course("scene_alpha")
    assert course is not None
    script = scene_store.to_script(course)
    assert isinstance(script, scene_store.SceneScript)
    # LessonDetail 能完整吃下 script -> 老 PlayerScreen 复用; 多出的键被忽略.
    lesson = LessonDetail.model_validate(script.model_dump())
    assert lesson.book == "scenes"
    assert lesson.title == "测试课程"
    assert [r.name for r in lesson.roles] == ["A", "B"]
    assert [ln.text for ln in lesson.roles[0].lines] == [
        "Hi, what can I get you?",
        "Anything else?",
    ]
    assert [ln.text for ln in lesson.roles[1].lines] == [
        "A small coffee, please.",
        "No, that's all.",
    ]
    assert [ln.translation for ln in lesson.roles[1].lines] == [
        "一杯小咖啡，谢谢。",  # noqa: RUF001
        "不用了，谢谢。",  # noqa: RUF001
    ]
    assert len(lesson.roles[0].lines) == len(lesson.roles[1].lines)


def test_script_lesson_no_is_stable_positive_int(two_courses: Path) -> None:
    first = scene_store.script_lesson_no("scene_alpha")
    assert first == scene_store.script_lesson_no("scene_alpha")
    assert 0 <= first < 100_000_000
    assert first != scene_store.script_lesson_no("scene_beta")
    course = scene_store.get_course("scene_alpha")
    assert course is not None
    script = scene_store.to_script(course)
    assert script.id == script.lesson_no == first


def test_script_line_ids_short_and_unique(scene_root: Path) -> None:
    payload = make_course_dict("scene_many_lines")
    payload["mission"]["exchanges"] = [{"a": f"Line {i}?", "b": f"Line {i}."} for i in range(1, 17)]
    write_raw(scene_root, "scene_many_lines.json", payload)
    scene_store.invalidate_cache()
    course = scene_store.get_course("scene_many_lines")
    assert course is not None
    script = scene_store.to_script(course)
    ids = [ln.id for role in script.roles for ln in role.lines]
    assert len(ids) == len(set(ids)) == 32
    assert all(0 < len(i) <= 64 for i in ids)
    # 分角色存, 按下标交错 (Android 侧 A[0],B[0],A[1],B[1]...)
    assert [ln.id for ln in script.roles[0].lines[:3]] == ["s1-a", "s2-a", "s3-a"]
    assert [ln.id for ln in script.roles[1].lines[:3]] == ["s1-b", "s2-b", "s3-b"]


def test_script_lines_without_translation_are_none(scene_root: Path) -> None:
    payload = make_course_dict("scene_no_cn")
    payload["mission"]["exchanges"] = [
        {"a": "Hello?", "b": "Hi there."},
        {"a": "Bye.", "b": "Bye."},
    ]
    write_raw(scene_root, "scene_no_cn.json", payload)
    scene_store.invalidate_cache()
    course = scene_store.get_course("scene_no_cn")
    assert course is not None
    script = scene_store.to_script(course)
    assert script.roles[0].lines[0].translation is None
    assert script.roles[1].lines[0].translation is None
    assert script.roles[0].lines[0].ipa is None


# ------------------------------------------------------------- 路径遍历守卫


@pytest.mark.parametrize(
    "bad_id",
    [
        "../scene_alpha",
        "../../etc/passwd",
        "scenes/scene_alpha",
        "/etc/passwd",
        "..",
        "",
        "scene alpha",
        "scene%2E%2Ex",
        "scene.json",
        "a" * 65,
    ],
)
def test_illegal_scene_id_rejected(scene_root: Path, bad_id: str) -> None:
    with pytest.raises(AppError) as exc:
        scene_store.get_course(bad_id)
    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_SCENE_ID"


def test_traversal_blocked_even_if_char_allowlist_bypassed(
    scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """纵深防御: 白名单被绕过时, 解析后的路径仍必须落在目录内."""
    monkeypatch.setattr(scene_store, "_check_scene_id", lambda scene_id: None)
    with pytest.raises(AppError) as exc:
        scene_store._scene_file("../../../etc/passwd")
    assert exc.value.code == "INVALID_SCENE_ID"


def test_scenes_root_escape_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """scenes/ 被 symlink 指到 root 外时拒绝服务 (防运维误配/软链投毒)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "data"
    root.mkdir()
    (root / "scenes").symlink_to(outside)
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", root)
    with pytest.raises(AppError) as exc:
        scene_store._scenes_root()
    assert exc.value.code == "INVALID_SCENE_ID"


# ------------------------------------------------------- SceneCourse 内容契约
# 读路径把坏文件静默跳过, 所以"坏在哪"必须由模型层说清楚 —— 这里的用例就是
# P4 LLM 生成课校验失败重试时要回喂给模型的那批错误.


def _valid_dict() -> dict:
    return make_course_dict("scene_model_probe")


def test_step_ids_and_task_ids_are_derived_by_position() -> None:
    course = SceneCourse.model_validate(_valid_dict())
    assert [s.id for s in course.briefing] == ["f1", "f2", "f3", "f4"]
    assert [t.id for t in course.mission.tasks] == ["t1", "t2", "t3"]
    assert course.required_task_count == 2
    assert course.step_types == ["read_along", "retell", "translate", "make_sentence"]


def test_explicit_ids_are_respected() -> None:
    payload = _valid_dict()
    payload["briefing"][0]["id"] = "pron-latte"
    payload["mission"]["tasks"][0]["id"] = "order"
    course = SceneCourse.model_validate(payload)
    assert course.briefing[0].id == "pron-latte"
    assert course.mission.tasks[0].id == "order"
    assert course.briefing[1].id == "f2", "补号只填空位, 不打乱已有 id"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.update(id="../escape"), "scene id must match"),
        (lambda p: p.update(id="has space"), "scene id must match"),
        (lambda p: p.update(category="food"), "category"),
        (lambda p: p.update(source="scraped"), "source"),
        (lambda p: p.update(level="C3"), "level"),  # CEFR 只到 C2
        (lambda p: p.update(vocab=p["vocab"][:5]), "at least 6"),
        (lambda p: p.update(briefing=p["briefing"][:3]), "at least 4"),
        (lambda p: p.update(skills=["pronunciation"] * 2), "unique"),
        (lambda p: p["mission"].update(exchanges=[]), "exchange"),
        (lambda p: p.update(schema_version=7), "schema_version"),
    ],
)
def test_scene_course_rejects_out_of_contract_payload(mutate: Any, message: str) -> None:
    payload = _valid_dict()
    mutate(payload)
    with pytest.raises(ValidationError) as exc:
        SceneCourse.model_validate(payload)
    assert message.lower() in str(exc.value).lower()


def test_duplicate_vocab_words_rejected() -> None:
    payload = _valid_dict()
    payload["vocab"][1]["word"] = payload["vocab"][0]["word"]
    with pytest.raises(ValidationError, match="vocab words must be unique"):
        SceneCourse.model_validate(payload)


def test_blank_vocab_word_rejected() -> None:
    payload = _valid_dict()
    payload["vocab"][0]["word"] = "   "
    with pytest.raises(ValidationError):
        SceneCourse.model_validate(payload)


def test_duplicate_step_ids_rejected() -> None:
    payload = _valid_dict()
    payload["briefing"][1]["id"] = payload["briefing"][0]["id"] = "same"
    with pytest.raises(ValidationError, match="step ids must be unique"):
        SceneCourse.model_validate(payload)


def test_duplicate_task_ids_rejected() -> None:
    payload = _valid_dict()
    for task in payload["mission"]["tasks"]:
        task["id"] = "same"
    with pytest.raises(ValidationError, match="task ids must be unique"):
        SceneCourse.model_validate(payload)


@pytest.mark.parametrize(
    ("step_type", "strip_field", "message"),
    [
        ("read_along", "ref_text", "read_along step .* needs ref_text"),
        ("retell", "ref_text", "retell step .* needs ref_text"),
        ("translate", "reference_answer", "translate step .* needs reference_answer"),
        ("make_sentence", "target_word", "make_sentence step .* needs target_word"),
    ],
)
def test_drill_type_required_fields(step_type: str, strip_field: str, message: str) -> None:
    """4 种题型的必填料: P2 drill 评分引擎直接吃这些字段, 缺料必须在校验期挡下."""
    payload = _valid_dict()
    for step in payload["briefing"]:
        if step["type"] == step_type:
            step[strip_field] = "   "
    with pytest.raises(ValidationError, match=message):
        SceneCourse.model_validate(payload)


def test_step_rejects_illegal_id_and_blank_prompt() -> None:
    payload = _valid_dict()
    payload["briefing"][0]["id"] = "../../x"
    with pytest.raises(ValidationError, match="step id must match"):
        SceneCourse.model_validate(payload)
    payload = _valid_dict()
    payload["briefing"][0]["cn_prompt"] = " "
    with pytest.raises(ValidationError, match="cn_prompt"):
        SceneCourse.model_validate(payload)


def test_task_rejects_illegal_id_and_blank_prompt() -> None:
    payload = _valid_dict()
    payload["mission"]["tasks"][0]["id"] = "bad id"
    with pytest.raises(ValidationError, match="task id must match"):
        SceneCourse.model_validate(payload)
    payload = _valid_dict()
    payload["mission"]["tasks"][0]["desc_cn"] = "  "
    with pytest.raises(ValidationError, match="desc_cn"):
        SceneCourse.model_validate(payload)


def test_exchange_rejects_blank_lines() -> None:
    payload = _valid_dict()
    payload["mission"]["exchanges"][0]["b"] = "   "
    with pytest.raises(ValidationError, match="exchange lines must not be blank"):
        SceneCourse.model_validate(payload)


def test_mission_rejects_blank_persona_and_short_max_turns() -> None:
    payload = _valid_dict()
    payload["mission"]["persona_cn"] = " "
    with pytest.raises(ValidationError, match="mission text"):
        SceneCourse.model_validate(payload)
    payload = _valid_dict()
    payload["mission"]["max_turns"] = 2
    with pytest.raises(ValidationError, match="max_turns"):
        SceneCourse.model_validate(payload)


def test_generated_course_shape_is_accepted() -> None:
    """P4 生成课走同一个模型: uuid 风格 id + source=generated 要能过."""
    payload = _valid_dict()
    payload["id"] = "scene_3f2a1b0c"
    payload["source"] = "generated"
    payload["goal_text"] = "两周后用英语主持站会"
    course = SceneCourse.model_validate(payload)
    assert course.source == "generated"
    assert scene_store.build_summary(course).source == "generated"
