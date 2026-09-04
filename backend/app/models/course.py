"""任务通关情景课 (scene course) content models.

对应计划 §5.1. 这是一个**纯模型模块**: 只做结构定义与内容契约校验, 不读文件、
不查数据库、不依赖 FastAPI —— 读路径在 ``app.services.scene_store``, 端点在
``app.api.v1.scenes``.

课程结构对标可栗口语的学习闭环 (§一): 选场景 → 打基础 (``briefing``) → 带任务
清单的实战对话 (``mission``) → 复盘. 三块内容契约:

* ``VocabItem``   —— 词汇卡 (word/ipa/meaning_cn/example_en), 详情页横向滑动卡.
* ``FoundationStep`` —— 打基础一步, 4 种题型 ``StepType`` 各带自己的必填料
  (跟读要 ``ref_text``, 复述要 ``ref_text`` + ``reference_answer``, 翻译要
  ``cn_prompt`` + ``reference_answer``, 造句要 ``target_word``); 校验器保证
  "题型缺料" 的课根本加载不进来.
* ``MissionSpec`` —— 实战对话: AI 人设 + 参考剧本 (``exchanges``) + 通关任务
  (``tasks``). ``exchanges`` 用 ``DialogueExchange`` **成对**表达 (a=AI 说,
  b=学员说), 服务端按位拆成 role A / role B, 从构造上保证两角色句数相等
  (语料不变量: Android 按索引交错 A[0],B[0],A[1],B[1]..., 学员恒演 B).

``schema_version`` 给后续不兼容演进留门: 读路径 (scene_store) 只接受
``SUPPORTED_SCHEMA_VERSIONS`` 里的课程.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ====== 枚举 / 常量 ======

#: 课程来源. curated = 仓库内手工精编 (data/scenes/*.json);
#: generated = LLM 按学习目标生成 (P4 起落 Postgres); template = 生成失败/占位课.
CourseSource = Literal["curated", "generated", "template"]

#: 场景分类 (计划 §5.1: daily/workplace/exam/travel).
Category = Literal["daily", "workplace", "exam", "travel"]

#: 画廊分类固定顺序 + 中文名 (首页/课程页 2 列卡片网格直接用).
CATEGORY_ORDER: tuple[Category, ...] = ("daily", "workplace", "exam", "travel")

CATEGORY_LABELS_CN: dict[Category, str] = {
    "daily": "日常交流",
    "workplace": "职场商务",
    "exam": "考试面试",
    "travel": "旅行出国",
}

CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

Level = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

#: 打基础题型 (计划 §5.4 评分引擎一一对应).
StepType = Literal["read_along", "retell", "translate", "make_sentence"]

STEP_TYPE_LABELS_CN: dict[StepType, str] = {
    "read_along": "跟读",
    "retell": "复述",
    "translate": "翻译",
    "make_sentence": "造句",
}

#: 课程训练的能力维度, 与画像四维 (§5.6) 对齐; "communication" 表示任务达成,
#: 首页「今日推荐」用 最低维度 x 课程 skills 做匹配.
Skill = Literal["pronunciation", "grammar", "vocabulary", "fluency", "communication"]

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})

#: SceneCourse.schema_version 当前写出的版本.
SCENE_COURSE_SCHEMA_VERSION = 1

#: 课程 id 同时也是文件名与 URL 路径片段 —— 只允许路径安全字符, 杜绝 ".." / "/" 等
#: (读路径另有独立 traversal 守卫, 这里是第二道).
_SCENE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def _is_blank(value: str) -> bool:
    return not value.strip()


# ====== 词汇卡 ======


class VocabItem(BaseModel):
    """课程核心词汇卡: 单词 + 音标 + 中文释义 + 例句."""

    word: str = Field(min_length=1, max_length=64)
    ipa: str = Field(default="", max_length=64)
    meaning_cn: str = Field(min_length=1, max_length=200)
    example_en: str = Field(min_length=1, max_length=300)

    @field_validator("word", "meaning_cn", "example_en")
    @classmethod
    def _reject_blank(cls, v: str) -> str:
        if _is_blank(v):
            raise ValueError("must not be blank")
        return v.strip()


# ====== 打基础 ======


class FoundationStep(BaseModel):
    """打基础的一步 (跟读 / 复述 / 翻译 / 造句).

    字段按题型可选, 必填料由 :class:`SceneCourse` 的校验器统一把关
    (见 :meth:`SceneCourse._check_content`), 这样单步也能被 P2 的 drill
    评分器直接消费而不用再做一次空值判断.

    **题型 -> 字段契约** (curated 内容按此填, P2 评分器按此读; 见
    ``tests/test_scenes.py`` 的 ``test_curated_courses_cover_all_four_drill_types``)::

        read_along     ref_text = 英文原句 (送 ISE), translation_cn = 中文对照,
                       reference_answer / target_word 留空
        retell         ref_text = 2-3 句英文材料, translation_cn = 中文对照,
                       reference_answer = 参考要点 (英文), target_word 留空
        translate      ref_text = **中文原句** (题目本身), reference_answer = 参考英文译文,
                       translation_cn 留空 (否则与 ref_text 重复), target_word 可选=必用词
        make_sentence  target_word = 必填目标词, reference_answer = 参考例句,
                       ref_text / translation_cn 留空

    ``accept_notes`` 每型都填: 中文评分要点, 给 LLM 判分器当 rubric, 也是学员看完题
    就知道"说到什么算过"的地方.
    """

    id: str = Field(default="", max_length=32)
    type: StepType
    #: 给学员看的中文题目说明 (所有题型都有).
    cn_prompt: str = Field(min_length=1, max_length=500)
    #: read_along / retell = 英文原句; translate = 要译的中文原句; make_sentence 留空.
    ref_text: str = Field(default="", max_length=2000)
    #: ref_text 的中文对照 (跟读/复述页显示; translate 型留空).
    translation_cn: str = Field(default="", max_length=1000)
    #: retell 的参考要点 / translate 的参考译文 / make_sentence 的参考句.
    reference_answer: str = Field(default="", max_length=2000)
    #: make_sentence 的目标词 (也用于 translate 的必用词提示).
    target_word: str = Field(default="", max_length=64)
    #: 评分要点提示, 给 LLM 判分器当 rubric (中文).
    accept_notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check_step_fields(self) -> FoundationStep:
        if self.id and not _SAFE_TOKEN_RE.match(self.id):
            raise ValueError("step id must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
        if _is_blank(self.cn_prompt):
            raise ValueError("cn_prompt must not be blank")
        return self


# ====== 实战对话 ======


class DialogueExchange(BaseModel):
    """参考剧本里的一对往来: ``a`` = AI 角色, ``b`` = 学员要说的话.

    成对表达是刻意的 (计划 §四): 服务端按位置拆 roles A/B, 两角色句数天然相等,
    LLM 无法破坏语料不变量. 剧本只作为「参考说法」在复盘页展示/播放, 不参与
    通关门禁.
    """

    a: str = Field(min_length=1, max_length=500)
    b: str = Field(min_length=1, max_length=500)
    a_cn: str = Field(default="", max_length=500)
    b_cn: str = Field(default="", max_length=500)

    @field_validator("a", "b")
    @classmethod
    def _reject_blank_line(cls, v: str) -> str:
        if _is_blank(v):
            raise ValueError("exchange lines must not be blank")
        return v.strip()


class MissionTask(BaseModel):
    """通关任务: 说清楚要达成的**沟通目标**, 完成才计分.

    ``id`` 是 P3 实战循环里 LLM 每轮回传的 ``tasks_done`` 标识, 必须稳定唯一;
    留空时由 :class:`SceneCourse` 按顺序补 ``t1..tN``.
    """

    id: str = Field(default="", max_length=32)
    desc_cn: str = Field(min_length=1, max_length=300)
    #: 可直接开口用的示范英文短句 (A2-B1 水平).
    hint_en: str = Field(default="", max_length=500)
    #: 中文提示/要点说明 (要提示按钮用).
    hint_cn: str = Field(default="", max_length=300)
    required: bool = True

    @model_validator(mode="after")
    def _check_task_fields(self) -> MissionTask:
        if self.id and not _SAFE_TOKEN_RE.match(self.id):
            raise ValueError("task id must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
        if _is_blank(self.desc_cn):
            raise ValueError("desc_cn must not be blank")
        return self


class MissionSpec(BaseModel):
    """实战对话配置 (计划 §5.1 / §5.5-2)."""

    persona_cn: str = Field(min_length=1, max_length=300)
    user_role_cn: str = Field(min_length=1, max_length=300)
    context_cn: str = Field(min_length=1, max_length=1000)
    #: AI 开场白 (英文), 第一轮由服务端直接说出, 不消耗 LLM.
    opening_a: str = Field(min_length=1, max_length=500)
    #: 开场白的中文对照.
    opening_a_cn: str = Field(default="", max_length=500)
    exchanges: list[DialogueExchange] = Field(min_length=2, max_length=16)
    tasks: list[MissionTask] = Field(min_length=3, max_length=6)
    #: 回合上限; 到顶仍未集齐必选任务则按未通关收工.
    max_turns: int = Field(default=12, ge=4, le=40)

    @field_validator("persona_cn", "user_role_cn", "context_cn", "opening_a")
    @classmethod
    def _reject_blank(cls, v: str) -> str:
        if _is_blank(v):
            raise ValueError("mission text fields must not be blank")
        return v.strip()


# ====== 课程 ======


class SceneCourse(BaseModel):
    """一门情景课 (curated 文件与 generated DB 行的统一读模型)."""

    schema_version: int = SCENE_COURSE_SCHEMA_VERSION
    #: 带前缀的稳定 id: curated 用 ``scene_<slug>``, generated 用 ``scene_<uuid>``.
    id: str = Field(min_length=1, max_length=64)
    source: CourseSource = "curated"
    category: Category
    #: 中文标题 (列表/详情页主标题).
    title: str = Field(min_length=1, max_length=120)
    #: 英文副标题 (让学员先看到要练的说法长什么样).
    subtitle_en: str = Field(default="", max_length=200)
    #: 学习目标原文: curated 是编辑写的目标, generated 是用户输入的那句话.
    goal_text: str = Field(default="", max_length=500)
    level: Level = "A2"
    est_minutes: int = Field(default=8, ge=1, le=60)
    #: 中文简介 (详情页头图区下方段落).
    brief_cn: str = Field(default="", max_length=2000)
    vocab: list[VocabItem] = Field(min_length=6, max_length=12)
    briefing: list[FoundationStep] = Field(min_length=4, max_length=7)
    mission: MissionSpec
    #: 本课主要训练的能力维度 (今日推荐匹配用).
    skills: list[Skill] = Field(min_length=1, max_length=5)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _SCENE_ID_RE.match(v):
            raise ValueError("scene id must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
        return v

    @field_validator("skills")
    @classmethod
    def _check_skills_unique(cls, v: list[Skill]) -> list[Skill]:
        if len(set(v)) != len(v):
            raise ValueError("skills must be unique")
        return v

    @model_validator(mode="after")
    def _check_content(self) -> SceneCourse:
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported schema_version {self.schema_version}")

        # 步骤 / 任务 id: 缺失按序补齐, 重复直接拒绝 —— P2/P3 的会话状态机
        # 以 id 为主键记录进度, 不能靠下标.
        for index, step in enumerate(self.briefing, start=1):
            if not step.id:
                step.id = f"f{index}"
        for index, task in enumerate(self.mission.tasks, start=1):
            if not task.id:
                task.id = f"t{index}"
        step_ids = [s.id for s in self.briefing]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("briefing step ids must be unique")
        task_ids = [t.id for t in self.mission.tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("mission task ids must be unique")

        # 每种题型的必填料 (P2 drill 评分器的输入契约).
        for step in self.briefing:
            match step.type:
                case "read_along" | "retell":
                    if _is_blank(step.ref_text):
                        raise ValueError(f"{step.type} step {step.id} needs ref_text")
                case "translate":
                    if _is_blank(step.reference_answer):
                        raise ValueError(f"translate step {step.id} needs reference_answer")
                case "make_sentence":
                    if _is_blank(step.target_word):
                        raise ValueError(f"make_sentence step {step.id} needs target_word")

        # 词汇至少不重复 (同一词出现两次没意义).
        words = [v.word.strip().lower() for v in self.vocab]
        if len(set(words)) != len(words):
            raise ValueError("vocab words must be unique")
        return self

    # ---- 只读派生属性 (供画廊摘要复用, 无副作用) ----

    @property
    def step_types(self) -> list[StepType]:
        return [step.type for step in self.briefing]

    @property
    def required_task_count(self) -> int:
        return sum(1 for task in self.mission.tasks if task.required)
