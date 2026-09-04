from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    desc,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="k12")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", _uuid())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book: Mapped[str] = mapped_column(String(16), index=True)
    lesson_no: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(256))
    role_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)


class History(Base):
    __tablename__ = "history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    # lesson_id 是书内课号, 跨书会重复, 聚合必须和 book 一起用.
    book: Mapped[str] = mapped_column(String(32), default="nce1", index=True)
    lesson_id: Mapped[int] = mapped_column(Integer, index=True)
    line_id: Mapped[str] = mapped_column(String(64))
    audio_path: Mapped[str] = mapped_column(String(512))
    score_total: Mapped[float] = mapped_column(Float)
    score_pronunciation: Mapped[float] = mapped_column(Float)
    score_fluency: Mapped[float] = mapped_column(Float)
    score_completeness: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", _uuid())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class TtsCache(Base):
    __tablename__ = "tts_cache"

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    audio_path: Mapped[str] = mapped_column(String(512))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ============================================================ v2.0 M1 (§5.2)
#
# 三张表都是 **add-only**: 老客户端 (1.4.0) 不读它们, 老端点也不写.
#
# ``doc`` / ``annotated_json`` 用 ``sqlalchemy.JSON`` (不是 PG 专属的 JSONB):
# 测试跑 sqlite, 生产跑 PG16, 同一份 DDL 两边都要能建 —— 计划 §5.2 明确要求.
# 代价是没有 JSONB 的表达式索引 / GIN, 但 v2.0 里没人按 JSON 内部字段查询.


class SceneCourseRow(Base):
    """LLM 生成的情景课 (per-user 存储).

    curated 课走 ``backend/data/scenes/*.json`` 文件; 生成课无上限且必须归属用户,
    不能落盘, 所以进表. 读路径由 ``app.services.scene_store`` 收口 (id 冲突 DB 优先).

    ``doc`` 存完整的 ``SceneCourse`` JSON, 因此这里的行**自带可玩内容**: 生成结果
    一旦校验通过, 后续玩课不再依赖 LLM 可重放.

    P4 EXTENSION POINT (T5 负责写入路径):
      * ``status``: ``ready`` (可直接玩) / ``generating`` (job 进行中占位) /
        ``failed`` (生成失败, ``doc`` 可为空对象 + ``failure_reason``) —— 画廊只放
        ``ready``; ``scene_key`` 用于同一个学习目标去重.
      * 写完后调 ``scene_store.invalidate_cache()`` 并在
        ``scene_store.merge_courses(curated, generated)`` 里传 ``generated``.
    """

    __tablename__ = "scene_courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    #: 课程去重键 (生成链路里通常是 ``<goal_text 归一化哈希>`` 或客户端幂等键).
    scene_key: Mapped[str] = mapped_column(String(64), default="")
    #: :class:`app.models.course.SceneCourse` 的完整 dump.
    doc: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: ready | generating | failed (P4 落地取值, 这里只定契约).
    status: Mapped[str] = mapped_column(String(16), default="ready", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        # 同一个用户同一个目标只留一行 (P4 重新生成走 upsert); 覆盖按 user_id 扫课的单列用法.
        Index("ix_scene_courses_user_scene_key", "user_id", "scene_key", unique=True),
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", _uuid())
        kwargs.setdefault("created_at", _utcnow())
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)


class PracticeSession(Base):
    """通关会话状态机快照 (计划 §5.3「通关会话状态机」).

    **服务端是唯一事实来源**: 客户端只发音频/文本, 不回传 history. 省流量、防篡改、
    崩溃后可用 ``GET /sessions/{id}`` 恢复 (计划 §四 决策表).

    状态机的全部可变状态都在 ``doc`` 里 (见 ``app.api.v1.course_sessions`` 的 doc
    schema); ``stage`` / ``status`` 是 ``doc`` 里同名字段的**冗余列**, 只为让
    「继续学习」和列表查询能走索引而不必解析 JSON. 两者由
    ``course_sessions`` 在同一笔 UPDATE 里写, 不允许别处单独改列.

    乐观锁: ``revision`` 是 SQLAlchemy 的 ``version_id_col``. 并发 ``/step`` 后到者
    的 UPDATE 会匹配 0 行 -> ``StaleDataError`` -> 端点翻成 409
    ``SESSION_CONCURRENT_UPDATE`` (PG 侧另有 ``SELECT ... FOR UPDATE`` 兜底).
    """

    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    #: scene_course | lesson | free_dialogue | assessment (P2 只写 scene_course)
    kind: Mapped[str] = mapped_column(String(32), default="scene_course")
    #: kind=scene_course 时的课程 id; 其它 kind 留空串 (PG 上 NULL 不参与唯一).
    scene_id: Mapped[str] = mapped_column(String(64), default="")
    #: briefing | mission | review | done
    stage: Mapped[str] = mapped_column(String(16), default="briefing")
    #: active | completed | abandoned
    status: Mapped[str] = mapped_column(String(16), default="active")
    doc: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    #: **开场那次请求的 device_id** (审计用). 归属判定看 ``user_id`` —— v2.0 一个
    #: device 就是一个账号, 所以"别人的 device 拿这个 id 来恢复" 一律 403.
    owner_device_id: Mapped[str] = mapped_column(String(128), default="")
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # RUF012: SQLAlchemy 把 __mapper_args__ 当类级配置, 不是可变实例属性.
    __mapper_args__ = {"version_id_col": revision}  # noqa: RUF012

    __table_args__ = (
        # 「继续学习」/ 会话列表: 某用户名下按状态过滤 + 最近活跃倒序取头几条.
        Index(
            "ix_practice_sessions_user_status_recency",
            "user_id",
            "status",
            desc("last_active_at"),
        ),
        # 按课汇总通关记录 (P4 course_progress 物化视图的原料).
        Index("ix_practice_sessions_user_scene", "user_id", "scene_id"),
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", _uuid())
        kwargs.setdefault("created_at", _utcnow())
        kwargs.setdefault("updated_at", _utcnow())
        kwargs.setdefault("last_active_at", _utcnow())
        # revision 由 version_id_col 机制在 INSERT 时置 1, 不在此处给默认值.
        super().__init__(**kwargs)


class PracticeStep(Base):
    """打基础 / 实战每一步的**逐条证据** (plan §5.2 M1 "per-step evidence").

    一次评分尝试 = 一行 (同 ``step_id`` 重试会追加行, ``attempt`` 递增). 现有
    ``history`` 表只留会话级聚合, 逐句明细从来没落过地 —— 复盘报告
    (P3 ReviewReport)、原话 vs 更好说法对照、P4 的弱词表都必须读这张表.

    **分数列可空 = 该维度本次没有证据** (§5.6 门控的前提): 跟读只给发音/流利/完整,
    翻译只给语法/词汇, 谁也不许拿 0 分冒充"没测". P3 画像是按"非 NULL 且有 source"
    的证据更新的.
    """

    __tablename__ = "practice_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("practice_sessions.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    #: 课程里的步骤 id (``f1..fN``), 与 ``SceneCourse.briefing[].id`` 对齐.
    step_id: Mapped[str] = mapped_column(String(32), default="")
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    #: read_along | retell | translate | make_sentence
    step_type: Mapped[str] = mapped_column(String(32), default="")
    #: 第几次尝试 (1 起).
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    #: ISE 认出的文本 / IAT 转写 / 学员输入的英文.
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_pronunciation: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_fluency: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_grammar: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_vocabulary: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: exact_reference | transcript_anchored (§5.6: 自由产出的发音分只能拿转写当 ref)
    ise_ref_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 逐词染色 / LLM mistakes / key_points_hit (复盘页原料).
    annotated_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    speech_rate_wpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: 评分引擎来源: xunfei | stub | llm | heuristic.
    source: Mapped[str] = mapped_column(String(16), default="stub")
    #: 判分 LLM 来源: 模型 id | ``stub`` (未配置或降级) | NULL (本题型没用 LLM).
    llm_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 本次尝试是否达标 (score >= 60 或人工 skip). 跳过行 score 全 NULL 但 ok=True,
    #: 因为它已经不再阻塞流程 —— ``source="skip"`` 就是"别拿它当证据"的标记.
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        # 复盘报告/通关汇总按会话取全部步骤.
        Index("ix_practice_steps_session_step", "session_id", "step_index"),
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", _uuid())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
