"""情景课画廊 / 详情 / 剧本端点 (计划 §5.3 「目录与画廊」).

P1 只提供只读三件套:

* ``GET /scenes?category=&device_id=`` -> :class:`scene_store.ScenesPage`
  (分类计数 + 摘要列表)
* ``GET /scenes/{scene_id}``           -> :class:`SceneCourse` 全量
* ``GET /scenes/{scene_id}/script``    -> :class:`scene_store.SceneScript`
  (= LessonDetail 形状, 老 PlayerScreen 直接播)

进度字段 (``cleared`` / ``best_total`` / ``attempts``) 目前恒为默认值 ——
``course_progress`` 表在 P4 落地; 字段先给出去, 客户端形状从 P1 起就稳定.

P4 EXTENSION POINT (同样的活儿别再找别的 router):
  ``POST /scenes/generate`` + ``GET /scenes/jobs/{job_id}`` + ``DELETE /scenes/{id}``
  挂在这个文件里; 从 ``scene_courses`` 表读出该 device 的生成课后用
  ``scene_store.merge_courses(curated, generated)`` 合并 (id 冲突 DB 优先),
  再把 ``{scene_id: CourseProgress}`` 作为 ``progress=`` 传给
  ``scene_store.list_scenes``. 详情端点同理: 先 DB 后文件.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.errors import AppError
from app.models.course import CATEGORY_ORDER, Category, SceneCourse
from app.services import scene_store
from app.services.scene_store import SceneScript, ScenesPage

router = APIRouter(tags=["scenes"])


def _require_category(category: str | None) -> Category | None:
    """未传 = 全部; 传了非法值 = 400 —— 不让拼错的筛选条件静默返回空列表."""
    if category is None:
        return None
    if category not in CATEGORY_ORDER:
        raise AppError(400, f"unknown category: {category}", "INVALID_CATEGORY")
    return category


@router.get("/scenes", response_model=ScenesPage)
async def list_scenes(
    category: str | None = Query(default=None, min_length=1, max_length=32),
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
) -> ScenesPage:
    """按分类返回情景课摘要.

    ``categories`` 的计数恒为全量 (四个分类都出现, 0 篇也列出, 客户端筛选 chip
    不用补位); ``scenes`` 受 ``category`` 过滤; ``total`` 是过滤后的篇数.
    ``device_id`` 现在只接收不使用 —— P4 用它查通关进度与归属本人的生成课.
    """
    return scene_store.list_scenes(category=_require_category(category), device_id=device_id)


@router.get("/scenes/{scene_id}", response_model=SceneCourse)
async def get_scene(scene_id: str) -> SceneCourse:
    """一门课的完整内容: 词汇卡 + 打基础步骤 + 实战剧本与通关任务清单."""
    course = scene_store.get_course(scene_id)
    if course is None:
        raise AppError(404, f"scene {scene_id} not found", "SCENE_NOT_FOUND")
    return course


@router.get("/scenes/{scene_id}/script", response_model=SceneScript)
async def get_scene_script(scene_id: str) -> SceneScript:
    """实战对话参考剧本, 形状等同 ``GET /lessons/{lesson_id}/roles`` 的 LessonDetail.

    老 PlayerScreen 的跟读 / 角色对话 / 影子跟读不改一行即可播这里返回的 roles:
    role A = AI 台词, role B = 学员台词, 两角色句数由 exchange 成对结构保证相等.
    多出的 ``scene_id`` / ``source`` / ``level`` 键由旧客户端按未知字段忽略
    (Android Json { ignoreUnknownKeys = true }).
    """
    course = scene_store.get_course(scene_id)
    if course is None:
        raise AppError(404, f"scene {scene_id} not found", "SCENE_NOT_FOUND")
    return scene_store.to_script(course)
