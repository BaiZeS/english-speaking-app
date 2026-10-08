"""自定义自由对话场景骨架 (计划 §3 C2) —— ``dialogue_scenes.doc`` 列的存储契约.

与 ``SceneCourse`` (整门情景课) 是**两个东西**: 这是学员自己描场景补出来的**轻量
骨架** —— 人设 (AI 演谁 / 学员演谁) + 情境 + 议程 (beats) + 开场白, 正好是自由对话
实时生成 (:func:`app.services.dialogue._scene_messages`) 缺的那几样场景素材。
词表 / 打基础 / 剧本属于 scene_courses 的整课管线, 与这张表解耦 (已批准裁决)。

字段清单按 §3 C2 原文: ``title / description / persona_cn / user_role_cn /
context_cn / goal / beats / opener / opener_cn / level``。命名与天花板抄
``MissionSpec`` (persona_cn/user_role_cn/context_cn = 300/300/1000, 开场白
500) —— §6: 新增字段必须照抄仓内已有口径, 不自造一套。

``title/description/persona_cn/user_role_cn/context_cn/goal/beats`` 由 prompt 要求
用中文写; 唯一的中英对照对是 ``opener`` (英文开场白) 与 ``opener_cn`` (它的中文
意思) —— 展示行的中文才过可信度门 (``mission_engine.coerce_bilingual``), 定义性
素材不过门 (同 ``MissionSpec.persona_cn`` 的待遇)。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.course import CEFR_LEVELS

#: 自定义场景对外的 id 前缀 (§3 C3b): ``custom_<DialogueSceneRow.id>``。
#: 43 字符 < ``DialogueTurnRequest.scene_id`` 的 max 64, 且不会撞静态目录 id。
CUSTOM_SCENE_PREFIX = "custom_"

#: beats 议程条数 (§3 C2: 轻量场景的议程深度, 同 MissionSpec tasks 的 3-6 先例).
SCENE_BEATS_MIN = 3
SCENE_BEATS_MAX = 6


class CustomDialogueScene(BaseModel):
    """学员自己描述的场景补全成的骨架 (后台作业一次 ``_judge`` 的产物形状)."""

    #: 场景卡片标题 (目录/选择器直接展示).
    title: str = Field(min_length=1, max_length=60)
    #: 场景一句话说明 (§3 C3: 轮询列表里的**展示面**素材).
    description: str = Field(min_length=1, max_length=300)
    #: AI 扮演谁 (中文人设, prompt 素材 —— 同 MissionSpec.persona_cn, 不过双语门).
    persona_cn: str = Field(min_length=1, max_length=300)
    #: 学员演谁.
    user_role_cn: str = Field(min_length=1, max_length=300)
    #: 情境.
    context_cn: str = Field(min_length=1, max_length=1000)
    #: 这一场要聊成什么 (学习目标).
    goal: str = Field(min_length=1, max_length=200)
    #: 议程: 对话按什么方向推进 (§A5 的议程素材; 3-6 条, 同 mission tasks 的跨度).
    beats: list[str] = Field(min_length=SCENE_BEATS_MIN, max_length=SCENE_BEATS_MAX)
    #: AI 的英文开场白 (≤ 整课开场白同宽 500).
    opener: str = Field(min_length=1, max_length=500)
    #: 开场白的中文对照 (展示双语, 过可信度门: 不可信 -> "" 整行不渲染, 绝不机翻).
    opener_cn: str = Field(default="", max_length=500)
    #: CEFR 难度锚 (默认同 SceneCourse)。
    level: str = Field(default="A2", max_length=8)

    @field_validator("title", "description", "persona_cn", "user_role_cn")
    @classmethod
    def _reject_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("custom scene text fields must not be blank")
        return cleaned

    @field_validator("beats")
    @classmethod
    def _check_beats(cls, v: list[str]) -> list[str]:
        # 坏议程由 _judge 的回喂重试修正 (同 course_generator 的 skills 校验先例).
        cleaned = [item.strip() for item in v]
        if any(not item or len(item) > 160 for item in cleaned):
            raise ValueError("every beat must be 1..160 chars after strip")
        return cleaned

    @field_validator("level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        if v not in CEFR_LEVELS:
            raise ValueError(f"level must be one of {list(CEFR_LEVELS)}")
        return v


def custom_scene_id(row_id: str) -> str:
    """``DialogueSceneRow.id`` -> 对外的自定义场景 id (§3 C3b)."""
    return f"{CUSTOM_SCENE_PREFIX}{row_id}"


def row_id_from_scene_id(scene_id: str) -> str | None:
    """custom id 拆回行 id; 非 custom 前缀返回 ``None`` (调用方当"不是自定义"处理)."""
    if not scene_id.startswith(CUSTOM_SCENE_PREFIX):
        return None
    tail = scene_id[len(CUSTOM_SCENE_PREFIX) :]
    return tail or None
