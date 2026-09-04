"""Curated scene-course read path (任务通关情景课内容层).

计划 §5.1 / §5.3 / §七 P1. 读路径分三层, P4 生成课只需在下面标了
``P4 EXTENSION POINT`` 的位置加分支:

* 文件发现 + 解析 + 60s TTL 缓存 -> :func:`load_curated_courses`
  (curated 来自 ``backend/data/scenes/*.json``, 与课本语料同一 data/ 根目录,
  测试沿用 corpus_loader 的 monkeypatch ``_CORPUS_ROOT`` 模式).
* 摘要 / 分类计数 -> :func:`list_scenes` (进度字段来自可选的 ``progress``,
  P4 的 course_progress 物化视图直接喂进来即可; P1 没有进度时为默认值, 字段
  一直在, 客户端形状稳定).
* 剧本投影 -> :func:`to_script`, 把 ``mission.exchanges`` 按位拆成 role A / B,
  形状与 ``GET /lessons/{id}/roles`` 的 LessonDetail 完全一致, 老 PlayerScreen
  可以直接播.

DB 生成课 (``scene_courses`` 表) 归属用户且无上限, 不能落盘, 因此统一读路径
由本模块收口: **id 冲突时 DB 优先** (P4 在 :func:`merge_courses` 里实现).
"""

from __future__ import annotations

import json
import logging
import time
import zlib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import AppError
from app.models.course import (
    CATEGORY_LABELS_CN,
    CATEGORY_ORDER,
    Category,
    DialogueExchange,
    SceneCourse,
)

logger = logging.getLogger(__name__)

# 与课本语料同一个 data 根目录; 测试通过 monkeypatch 这个常量换目录.
_CORPUS_ROOT: Path = Path(__file__).resolve().parent.parent.parent / "data"

#: curated 课程所在子目录 (也是 /script 响应里的 book 值).
SCENE_DIR_NAME = "scenes"

#: 情景课剧本在课本语料体系里的 book 名 (history / progress 按 (book, lesson_id) 记账).
SCRIPT_BOOK = SCENE_DIR_NAME

#: 文件缓存存活时间; P4 生成课写完可以在自己的流程里 invalidate.
CACHE_TTL_SECONDS = 60.0

#: 课程 id 即文件名, 只允许路径安全字符 (与 SceneCourse.id 同一套规则).
_SAFE_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

# /script 的 line id 形如 s1-a, 上限由 exchange 条数 (<=16) 决定, 远小于
# HistoryWriteRequest.line_id / ScoreRequest.line_id 的 64 字符约束; 该不变量由
# tests (test_scene_store + test_scenes 的内容契约用例) 把守, 不在此处重复判断.


class CourseProgress(BaseModel):
    """某个 device 对某门课的通关进度 (P4 course_progress 表的读模型)."""

    cleared: bool = False
    best_total: float = Field(default=0.0, ge=0, le=100)
    attempts: int = Field(default=0, ge=0)


class SceneSummary(BaseModel):
    """画廊卡片用的课程摘要 —— 不含词汇/剧本等大块内容."""

    id: str
    source: str
    category: Category
    title: str
    subtitle_en: str
    level: str
    est_minutes: int
    brief_cn: str
    skills: list[str] = Field(default_factory=list)
    vocab_count: int = 0
    briefing_count: int = 0
    task_count: int = 0
    required_task_count: int = 0
    max_turns: int = 0
    # P4 起由 course_progress 填; 没有进度表时保持默认值, 字段不消失.
    cleared: bool = False
    best_total: float = 0.0
    attempts: int = 0


class CategoryStat(BaseModel):
    """画廊顶部分类筛选chip: id + 中文名 + 课程数 (计数恒为全量, 不受筛选影响)."""

    id: Category
    label_cn: str
    count: int


class ScenesPage(BaseModel):
    """``GET /scenes`` 的载荷."""

    categories: list[CategoryStat]
    scenes: list[SceneSummary]
    total: int


class ScriptLine(BaseModel):
    id: str
    text: str
    translation: str | None = None
    ipa: str | None = None


class ScriptRole(BaseModel):
    name: str
    lines: list[ScriptLine]


class SceneScript(BaseModel):
    """LessonDetail 形状 + 情景课身份字段 (多出的键老客户端按 ignoreUnknownKeys 忽略).

    ``id`` / ``lesson_no`` 必须是 JSON number: Android 的 LessonDetailDto 用 Int
    接收 (kotlinx 不会把字符串强转成 Int). 取值由 scene_id 稳定散列得到, 同一门课
    每次一样, 不同门课几乎不撞 (进度/记录的真正主键是 (book, lesson_id), book 固定
    为 "scenes", 散列空间 1e8 对当前量级足够). 需要字符串主键的调用方读 ``scene_id``.
    """

    id: int
    book: str = SCRIPT_BOOK
    lesson_no: int
    title: str
    roles: list[ScriptRole]
    scene_id: str
    source: str
    level: str


# ---------------------------------------------------------------- 时间 / 缓存


def _now() -> float:
    return time.monotonic()


_cache: tuple[str, float, list[SceneCourse]] | None = None


def invalidate_cache() -> None:
    """丢掉 TTL 缓存 (测试, 以及 P4 写完生成课后调用)."""
    global _cache
    _cache = None


def _scenes_root() -> Path:
    """curated 目录; 不在外部 root 之外游走 (路径遍历守卫)."""
    root = _CORPUS_ROOT.resolve()
    resolved = (_CORPUS_ROOT / SCENE_DIR_NAME).resolve()
    if not resolved.is_relative_to(root):
        raise AppError(400, "invalid scene root", "INVALID_SCENE_ID")
    return resolved


def _check_scene_id(scene_id: str) -> None:
    """拒绝任何可能越出目录的 id: 空、带路径分隔符、``..``、非白名单字符."""
    if not scene_id or len(scene_id) > 64:
        raise AppError(400, "invalid scene id", "INVALID_SCENE_ID")
    if any(ch not in _SAFE_ID_CHARS for ch in scene_id):
        raise AppError(400, "invalid scene id", "INVALID_SCENE_ID")


def _scene_file(scene_id: str) -> Path:
    """``scene_id`` -> 目录内的 ``<id>.json``, 拒绝解析到目录外."""
    _check_scene_id(scene_id)
    root = _scenes_root()
    candidate = (root / f"{scene_id}.json").resolve()
    if not candidate.is_relative_to(root):
        raise AppError(400, "invalid scene id", "INVALID_SCENE_ID")
    return candidate


def _parse_course(path: Path) -> SceneCourse:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("scene file must contain a JSON object")
    # schema_version 由 SceneCourse 自己把关 (不在 SUPPORTED_SCHEMA_VERSIONS 里就抛)
    course = SceneCourse.model_validate(raw)
    # 文件名 == 课程 id: 否则画廊与 /scenes/{id} 会指到不同内容.
    if path.stem != course.id:
        raise ValueError(f"file name {path.stem!r} != course id {course.id!r}")
    return course


def _load_from_disk() -> list[SceneCourse]:
    """发现并解析全部 curated 课程, 按 id 排序.

    单个文件坏掉 (JSON 语法/模型不合法/文件名与 id 不符) 只让这一篇消失 + 一条
    warning, 不影响整个画廊 —— 与 corpus_loader 对 book.json 的处理一致.
    """
    root = _scenes_root()
    if not root.is_dir():
        return []
    # id == 文件名 (见 _parse_course), 所以一个目录里的 id 天然唯一, 跨来源去重留给
    # merge_courses (P4 生成课走 DB, 与文件 curated 可能同 id, 那时 DB 优先).
    out: dict[str, SceneCourse] = {}
    for path in sorted(root.glob("*.json")):
        try:
            course = _parse_course(path)
        except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning("scene course file skipped (%s): %s", path.name, exc)
            continue
        out[course.id] = course
    return [out[key] for key in sorted(out)]


def load_curated_courses() -> list[SceneCourse]:
    """全部 curated 情景课 (60s TTL 缓存; 换目录即缓存失效)."""
    global _cache
    key = str(_scenes_root())
    now = _now()
    if _cache is not None and _cache[0] == key and now - _cache[1] < CACHE_TTL_SECONDS:
        return list(_cache[2])
    courses = _load_from_disk()
    _cache = (key, now, courses)
    return list(courses)


def get_course(scene_id: str) -> SceneCourse | None:
    """按 id 取一门课, 找不到返回 None (id 非法则 AppError 400).

    P1 只有文件里的 curated 课. P4 EXTENSION POINT: 生成课落在 ``scene_courses``
    表里, 在那个函数里先查 DB (归属这个 device 才算可见) 再回落到本函数即可 ——
    端点不用改, 所以这里保持同步签名 + 只吃 scene_id.
    """
    path = _scene_file(scene_id)
    # 先走缓存; 缓存里没有再看文件是否存在 (新落地/刚被别的过程写入的文件).
    for course in load_curated_courses():
        if course.id == scene_id:
            return course
    if not path.is_file():
        return None
    try:
        return _parse_course(path)
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("scene course %s unreadable: %s", scene_id, exc)
        return None


# ------------------------------------------------------------------ P4 扩展口


def merge_courses(
    curated: Sequence[SceneCourse], generated: Iterable[SceneCourse]
) -> list[SceneCourse]:
    """P4 EXTENSION POINT —— 文件 curated + DB 生成课合并, **id 冲突 DB 优先**.

    P1 只喂 curated; P4 从 ``scene_courses`` 表读这个 device 的生成课后传
    ``generated``. 返回值恒按 id 排序, 保证画廊顺序稳定.
    """
    by_id: dict[str, SceneCourse] = {course.id: course for course in curated}
    for course in generated:
        by_id[course.id] = course
    return [by_id[key] for key in sorted(by_id)]


# ------------------------------------------------------------------ 摘要 / 列表


def build_summary(course: SceneCourse, progress: CourseProgress | None = None) -> SceneSummary:
    """课程 -> 画廊摘要. ``progress`` 缺省时 cleared/best_total/attempts 给默认值."""
    prog = progress or CourseProgress()
    return SceneSummary(
        id=course.id,
        source=course.source,
        category=course.category,
        title=course.title,
        subtitle_en=course.subtitle_en,
        level=course.level,
        est_minutes=course.est_minutes,
        brief_cn=course.brief_cn,
        skills=list(course.skills),
        vocab_count=len(course.vocab),
        briefing_count=len(course.briefing),
        task_count=len(course.mission.tasks),
        required_task_count=course.required_task_count,
        max_turns=course.mission.max_turns,
        cleared=prog.cleared,
        best_total=prog.best_total,
        attempts=prog.attempts,
    )


def category_stats(courses: Iterable[SceneCourse]) -> list[CategoryStat]:
    """四个固定分类 + 各自课程数 (分类即使 0 篇也出现, 客户端筛选 chip 不用补位)."""
    counts: dict[str, int] = {}
    for course in courses:
        counts[course.category] = counts.get(course.category, 0) + 1
    return [
        CategoryStat(id=cat, label_cn=CATEGORY_LABELS_CN[cat], count=counts.get(cat, 0))
        for cat in CATEGORY_ORDER
    ]


def list_scenes(
    category: str | None = None,
    device_id: str | None = None,
    progress: Mapping[str, CourseProgress] | None = None,
    courses: Sequence[SceneCourse] | None = None,
) -> ScenesPage:
    """画廊列表: 分类计数 (全量) + 摘要列表 (可按 category 过滤).

    ``device_id`` 在 P1 尚未参与逻辑 —— P4 用它查 ``course_progress`` 和归属自己的
    生成课, 然后把结果传进 ``progress``. ``courses`` 让 P4 能把合并后的
    (curated + generated) 列表喂进来, 而不必重复读盘.
    """
    pool = list(courses) if courses is not None else load_curated_courses()
    stats = category_stats(pool)
    summaries = [
        build_summary(course, (progress or {}).get(course.id))
        for course in pool
        if category is None or course.category == category
    ]
    return ScenesPage(categories=stats, scenes=summaries, total=len(summaries))


# --------------------------------------------------------------------- 剧本


def script_lesson_no(scene_id: str) -> int:
    """scene_id -> 稳定的正整数课号 (见 :class:`SceneScript` 的说明)."""
    return zlib.crc32(scene_id.encode("utf-8")) % 100_000_000


def _line_id(index: int, side: str) -> str:
    """``s1-a`` / ``s1-b`` —— 短到不可能碰上线 id 长度上限."""
    return f"s{index}-{side}"


def script_lines(
    exchanges: Sequence[DialogueExchange],
) -> tuple[list[ScriptLine], list[ScriptLine]]:
    """成对 exchange -> (A 行, B 行), 两列长度恒相等 (语料不变量)."""
    role_a: list[ScriptLine] = []
    role_b: list[ScriptLine] = []
    for index, exchange in enumerate(exchanges, start=1):
        role_a.append(
            ScriptLine(
                id=_line_id(index, "a"),
                text=exchange.a,
                translation=exchange.a_cn or None,
            )
        )
        role_b.append(
            ScriptLine(
                id=_line_id(index, "b"),
                text=exchange.b,
                translation=exchange.b_cn or None,
            )
        )
    return role_a, role_b


def to_script(course: SceneCourse) -> SceneScript:
    """把实战对话参考剧本投影成 LessonDetail 形状, 供老 PlayerScreen 复用.

    role A = ``mission.exchanges[].a`` (AI 角色), role B = ``.b`` (学员恒演 B,
    与课本语料的下标交错规则一致). 跟读/角色对话/影子跟读三种模式都能直接跑.
    """
    role_a_lines, role_b_lines = script_lines(course.mission.exchanges)
    lesson_no = script_lesson_no(course.id)
    return SceneScript(
        id=lesson_no,
        book=SCRIPT_BOOK,
        lesson_no=lesson_no,
        title=course.title,
        roles=[
            ScriptRole(name="A", lines=role_a_lines),
            ScriptRole(name="B", lines=role_b_lines),
        ],
        scene_id=course.id,
        source=course.source,
        level=course.level,
    )


__all__ = [
    "CACHE_TTL_SECONDS",
    "CategoryStat",
    "CourseProgress",
    "SceneScript",
    "SceneSummary",
    "ScenesPage",
    "ScriptLine",
    "ScriptRole",
    "build_summary",
    "category_stats",
    "get_course",
    "invalidate_cache",
    "list_scenes",
    "load_curated_courses",
    "merge_courses",
    "script_lesson_no",
    "script_lines",
    "to_script",
]
