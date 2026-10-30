"""场景目录端点 (自由对话的"有哪些地方可聊") + 场景解析收口.

v3.0 大扫除之后本模块只剩这两件事: ``GET /dialogue/scenes`` 给客户端画会话列表,
:func:`_resolve_scene` 是"一个 scene_id 到底指哪场戏"的**唯一**接缝 (目录精确命中 ->
归属者的自定义场景 -> 404)。一轮对话的读写都在 ``dialogue_threads``, 这里不再管。

被删掉的是 ``POST /dialogue/turn`` 与 ``POST /dialogue/generate``: 前者无状态 (历史靠
客户端攒 ``history[]`` 回传, 于是"回到这个场景接着聊"没有实现基础), 后者的开场白职责
归了 ``POST /dialogue/threads``。两条都被线程端点取代, 不是搬到别处。
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import User
from app.models.scene_spec import row_id_from_scene_id
from app.services import dialogue_scenes, scene_spec_generator, users

router = APIRouter(tags=["dialogue"])


class SceneRoleDto(BaseModel):
    """群聊里的一个角色 —— 客户端拿它画头像、昵称, 也用它把气泡上的 ``role_id`` 翻译成人。"""

    role_id: str
    name: str
    name_en: str
    #: TTS 音色 (Mia/Chloe/Milo/Dean)。客户端不播音频时用不上, 但它是"这场戏有几个人
    #: 在说话"的一部分, 列表面要摆头像组就得知道。
    voice: str


class DialogueSceneDto(BaseModel):
    id: str
    title: str
    description: str
    #: add-only (§4 场景选择器 / D4): 卡片按「中文 + 英文并列」渲染时用的英文展示对。
    #: 自定义场景是学员自己写的中文描述, 没有英文对 -> 空串 = 那一行不渲染
    #: (D5 缺字段纪律, 绝不机翻占位)。
    title_en: str = ""
    description_en: str = ""
    #: add-only (§3 C3b): ``catalog`` = 内置目录, ``custom`` = 学员自己描的场景 (仅归属者可见).
    kind: str = "catalog"
    #: v3.0 群聊: 这一场里的 AI 角色 (2-3 个)。
    roles: list[SceneRoleDto] = Field(default_factory=list)
    #: 学员在这场的身份 (气泡与列表都要显示)。
    user_role: str = ""


class DialogueScenesResponse(BaseModel):
    scenes: list[DialogueSceneDto]
    default_scene: str


def _scene_not_found(scene_id: str) -> NoReturn:
    """未知名一律 404 —— **没有**"静默当目录第一条"的兜底 (删兜底的理由见 :func:`_resolve_scene`)."""
    raise AppError(404, f"scene {scene_id} not found", "SCENE_NOT_FOUND")


async def _resolve_scene(
    db: AsyncSession, scene_id: str, user: User | None
) -> dialogue_scenes.DialogueScene:
    """开场/轮次共用的场景解析 (§3 C3b): 目录精确命中 -> 归属者的自定义场景 -> 404。

    * catalog: ``dialogue_scenes.resolve_scene`` 精确命中。旧版对查不到的 id **静默
      回落到目录第一条**, 乱拼 id 的学员被教成「商务会议」还毫无提示 (§9-5 点名) ——
      兜底已删, ``None`` 在这里翻成 404 ``SCENE_NOT_FOUND``;
    * custom: ``custom_<row.id>`` 的可见性 = 归属, 没身份 / 别人的 id / 未就绪都
      与"不存在"同形, 不泄露存在性;
    * 其余一律 404。
    """
    scene = dialogue_scenes.resolve_scene(scene_id)
    if scene is not None:
        return scene
    if user is not None and row_id_from_scene_id(scene_id) is not None:
        custom = await scene_spec_generator.find_ready_custom_scene(db, user.id, scene_id)
        if custom is not None:
            return custom
    _scene_not_found(scene_id)


@router.get("/dialogue/scenes", response_model=DialogueScenesResponse)
async def list_dialogue_scenes(
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> DialogueScenesResponse:
    """Return every scene the client's chat list can offer.

    Public so the Android client doesn't need to hard-code scene metadata
    or ship translation files for new scenes.

    §3 C3b: 带 ``device_id``/``user_id`` 时按身份合并**归属者自己的** ``ready`` 自定义
    场景 (``kind="custom"``, 追加在目录之后; id 冲突 DB 优先 —— ``custom_`` 前缀让它
    实际不会发生)。这正是 §9-5 的轮询展示面: 作业 ``ready`` 后刷新列表就看见新场景,
    **不新增轮询端点**。不认识的身份读到的是纯目录 (读侧不建行, 别人的行不可见)。
    """
    catalog = dialogue_scenes.list_scenes()

    def dto(scene: dialogue_scenes.DialogueScene, kind: str = "catalog") -> DialogueSceneDto:
        return DialogueSceneDto(
            id=scene.id,
            title=scene.title,
            description=scene.description,
            title_en=scene.title_en,
            description_en=scene.description_en,
            kind=kind,
            roles=[
                SceneRoleDto(
                    role_id=role.role_id, name=role.name, name_en=role.name_en, voice=role.voice
                )
                for role in scene.roles
            ],
            user_role=scene.user_role,
        )

    by_id = {scene.id: dto(scene) for scene in catalog}
    if device_id or user_id:
        user = await users.lookup_user(db, device_id=device_id, user_id=user_id)
        if user is not None:
            # 两个分支走**同一份** DialogueScene 形状 (解析接缝只有 _resolve_scene 一处),
            # 所以英文展示对也只在这一处填: 自定义场景的那两格恒为空。
            for scene in await scene_spec_generator.list_ready_custom_scenes(db, user.id):
                by_id[scene.id] = dto(scene, kind="custom")
    return DialogueScenesResponse(
        scenes=list(by_id.values()),
        # default_scene 永远取**目录**第一条: 旧客户端拿它当默认场景, 不能让某个学员
        # 自己的自定义场景变成"全站默认"。
        default_scene=catalog[0].id if catalog else "",
    )
