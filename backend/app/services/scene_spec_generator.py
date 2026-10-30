"""自定义场景骨架生成 (计划 §3 C2) —— 学员自己描场景 -> 一次 ``_judge`` 出骨架 JSON.

形状抄 :mod:`app.services.course_generator` 的 job 骨架 (模块级持 task / 任务内自建
session / 每次推进即 commit / 终态必落), 但**只有一步**: 产出的是轻量场景骨架
(:class:`~app.models.scene_spec.CustomDialogueScene`: 人设 + 议程 beats + 开场白),
不是整门课 —— 与 ``scene_courses`` 的全课管线解耦, 各自一张表。

* ``POST /dialogue/scenes/custom`` 建 ``generation_jobs`` 行 (``kind="scene_brief"``)
  + ``asyncio.create_task`` 派生 :func:`run_scene_brief_job`, 立即 202 回轮询地址;
* 一次 ``_judge`` 出 JSON, 坏输出回喂重试 1 次 (§5.5 统一模式, 收口在 ``drill_grader``);
* **预算**: 异步作业不吃 25s 同步契约, 但墙钟仍要封顶 —— ``hard_budget_s=SCENE_BRIEF_JOB_BUDGET_S``
  在调用点显式传 (AST 门只豁免 ``course_generator.py`` 文件名; "稍慢但一定成功" 的取值
  与理由见 drill_grader 硬预算块)。**socket 沿用 ``_judge`` 默认** (``LLM_TIMEOUT_S=20``),
  不为这一条路动全局;
* **拆+关思考口径**: ``extra_body=no_thinking_body()`` (与台词/判分那三条新调用同一
  纪律); 生成可跟随客户端模型 (D2: 场景 spec 是生成类), 但 job 表没有承载 model id 的
  列, 所以这里恒走服务端默认 —— 课程生成作业的既有口径;
* ``opener_cn`` (开场白的中文对照) 过 :func:`turn_generation.coerce_bilingual` 可信度门;
  persona/context 这类**定义性中文素材**不过门 (同 MissionSpec 的待遇)。

**JSON 列纪律** (T3 钉死): ``doc`` 读要 deepcopy、写要整体换对象。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import re
from datetime import UTC, datetime

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.models.db import DialogueSceneRow, GenerationJob
from app.models.scene_spec import (
    CustomDialogueScene,
    custom_scene_id,
    row_id_from_scene_id,
)
from app.services import turn_generation
from app.services.dialogue_scenes import VOICES, DialogueScene, OpeningLine, SceneRole
from app.services.drill_grader import (
    SCENE_BRIEF_JOB_BUDGET_S,
    LlmUnavailableError,
    _judge,
    _truncate,
)
from app.services.llm_provider import LlmMessage, no_thinking_body

# ====== 常量 ======

#: 场景骨架 JSON 的输出预算: 比整课骨架 (1600) 小一个量级 —— 这正是它与
#: scene_courses 全课管线的分界, 别把它涨回去。
SCENE_BRIEF_MAX_TOKENS = 1200
#: 结构化生成 (定人设/排议程) 的温度 = 课程骨架同一档 (0.4); 台词的 0.7 是另一回事。
SCENE_BRIEF_TEMPERATURE = 0.4


class GenerationError(Exception):
    """生成链路失败 (LLM 不可用 / 输出两次都不合规 / 内容校验不过)."""


#: ``scene_key`` 的列宽与指纹长度 (同一用户同一段描述复用同一行, upsert 不堆场景).
_SCENE_KEY_LEN = 40


def scene_key_for(goal_text: str) -> str:
    """goal_text -> 去重键 (同一用户同一目标复用同一行, upsert 不堆场景)."""
    normalized = re.sub(r"\s+", " ", goal_text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:_SCENE_KEY_LEN]


_JOBS: set[asyncio.Task[None]] = set()

# ====== prompt ======

_SPEC_JSON_SHAPE = (
    '只输出 JSON: {"title": "...", "description": "...", "persona_cn": "...", '
    '"user_role_cn": "...", "context_cn": "...", "goal": "...", '
    '"roles": [{"role_id": "r1", "name_cn": "...", "persona_cn": "...", "voice": "..."}], '
    '"beats": ["..."], '
    '"opener": "...", "opener_cn": "...", "level": "..."}'
)


def spec_messages(brief: str) -> list[LlmMessage]:
    """学员的场景描述 -> 骨架生成 prompt (硬约束风格同 course_generator 的段1)."""
    system = (
        "你是口语陪练的场景策划, 学员是中文母语、能读写但开口少的英语初学者 (CEFR A2-B1)。"
        "学员自己描述了想练的自由对话场景, 把它补成**一页轻量场景骨架** —— "
        "角色 + 议程 + 开场白; 不要词表, 不要完整剧本。\n"
        "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。\n"
        "硬约束 (违反任何一条都算不合格):\n"
        "- title ≤20 个中文字; description 一句中文 (≤60 字), 选择器卡片直接展示\n"
        "- persona_cn = AI 侧总体人设 (中文), user_role_cn = 学员扮演的身份 (中文), "
        "context_cn = 这场对话的情境 (中文), goal = 这一场聊下来要练成什么 (中文)\n"
        f"- roles: **2-3 个** AI 角色, 每个是 {{role_id, name_cn, persona_cn, voice}}; "
        "role_id 依次用 r1/r2/r3; name_cn 是气泡上的称呼 (≤10 个中文字, 如「前台 Amy」); "
        "voice 只能从 "
        f"{list(VOICES)} 里选, 且**同一场内不得重复** (两个角色同一个音就听不出是谁在说)\n"
        "- beats: 议程 3-6 条, 每条一句中文 (对话按这些方向推进, 不跑题不重复)\n"
        "- opener 是**第一个角色**的英文开场白 (一句, ≤20 词, 锚定学员水平, 自然引出第一条议程); "
        "opener_cn 是它的简体中文意思 (出现英文单词视为不合格)\n"
        "- level ∈ A1|A2|B1|B2|C1|C2 (按学员水平取, 拿不准用 A2/B1)\n" + _SPEC_JSON_SHAPE
    )
    return [
        LlmMessage(role="system", content=system),
        LlmMessage(role="user", content=f"学员描述的场景: {brief.strip()}"),
    ]


# ====== 生成 ======


async def generate_scene_spec(brief: str) -> CustomDialogueScene:
    """一次 ``_judge``: 合规骨架 / LLM 不可用或两次都不合规 -> :class:`GenerationError`.

    ``_judge`` 自带"坏 JSON/pydantic 不合规则回喂校验错误重试 1 次"的收口, 这里不另起
    第二次裸 ``provider.chat``。可信度门只过展示性中文 (``opener_cn``) —— 定义性素材
    被置空 = 场景坏掉, 那种输出应该由校验回喂修, 而不是悄悄缺一块。
    """
    try:
        spec = await _judge(
            CustomDialogueScene,
            spec_messages(brief),
            max_tokens=SCENE_BRIEF_MAX_TOKENS,
            temperature=SCENE_BRIEF_TEMPERATURE,
            hard_budget_s=SCENE_BRIEF_JOB_BUDGET_S,
            extra_body=no_thinking_body(),
        )
    except LlmUnavailableError as exc:
        raise GenerationError(str(exc)) from exc
    return spec.model_copy(update={"opener_cn": turn_generation.coerce_bilingual(spec.opener_cn)})


# ====== job runner (照 course_generator 的骨架) ======


async def _load_job(db: AsyncSession, job_id: str) -> GenerationJob | None:
    res = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    return res.scalar_one_or_none()


async def _bump(db: AsyncSession, job: GenerationJob, progress: float, stage_text: str) -> None:
    """段推进立即 commit —— 轮询端点在另一个会话里读 (与课程生成同一纪律)."""
    job.progress = progress
    job.stage_text = stage_text
    job.updated_at = _utcnow()
    await db.commit()


async def _fail(db: AsyncSession, job_id: str, reason: str) -> None:
    """rollback 后单独落 ``failed`` 行 (失败原因诚实给到客户端, 可重试)."""
    await db.rollback()
    job = await _load_job(db, job_id)
    if job is None or job.status != "running":
        return
    job.status = "failed"
    job.error = _truncate(reason, 500)
    job.stage_text = "场景生成失败, 可重试"
    job.updated_at = _utcnow()
    await db.commit()
    logger.warning("scene brief job failed | job={} reason={}", job_id, _truncate(reason, 200))


async def run_scene_brief_job(job_id: str) -> None:
    """后台任务主体: 自开会话生成场景骨架并 upsert 场景行.

    ``spawn_scene_brief_job`` 的测试替身直接 ``await`` 本函数 (conftest 已 autouse no-op
    真派生); 任何异常都收敛成 ``job=failed`` —— 轮询端永远等得到一个终态。
    ``kind`` 再验一遍: 两种 job 同居一张表 (C3), docstring 里"不碰 course"的隔离就靠它。
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        job = await _load_job(db, job_id)
        if job is None or job.status != "running" or job.kind != "scene_brief":
            return
        try:
            await _run_job(db, job)
        except Exception as exc:
            logger.exception("scene brief job crashed | job={}", job_id)
            await _fail(db, job_id, f"场景生成失败: {exc}")


async def _run_job(db: AsyncSession, job: GenerationJob) -> None:
    await _bump(db, job, 0.05, "理解你描述的场景…")
    spec = await generate_scene_spec(job.goal_text)
    await _bump(db, job, 0.8, "校验内容并保存…")
    scene_id = await _persist_scene(db, job, spec)
    job.status = "ready"
    job.progress = 1.0
    job.stage_text = "场景已就绪"
    job.scene_id = scene_id
    job.updated_at = _utcnow()
    await db.commit()
    logger.info(
        "custom scene generated | job={} scene={} title={} beats={}",
        job.id,
        scene_id,
        spec.title,
        len(spec.beats),
    )


async def _persist_scene(db: AsyncSession, job: GenerationJob, spec: CustomDialogueScene) -> str:
    """写 ``dialogue_scenes``: 同 (user, scene_key) **复用旧行与旧 id** (重新生成 = 覆盖).

    ``scene_key`` 与整课生成用同一个指纹纪律 (归一化 + 截断哈希, 直接复用
    ``course_generator.scene_key_for`` —— 两处各写一份归一化就是漂移的开始):
    同一个人把同一段描述提交两次, 只会有一行。
    """
    doc = spec.model_dump(mode="json")
    key = scene_key_for(job.goal_text)
    row = (
        await db.execute(
            select(DialogueSceneRow).where(
                DialogueSceneRow.user_id == job.user_id,
                DialogueSceneRow.scene_key == key,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        # JSON 列整体换对象 (原地改不会被 UPDATE, T3 钉死的坑); 行 id 不动 -> 对外
        # custom_<row.id> 在重生成时保持稳定 (§3 C1 docstring 的契约)。
        # 并发重生成 = 后写者赢 (质量审查 M-2 已接受): 同 (user, scene_key) 的两个作业
        # 各自 select-不到-则-INSERT 时唯一索引挡第二个; 都 select-到-时后 commit 覆盖前者 doc,
        # 两个 job 都报 ready —— 重生成语义本就是「覆盖旧行」(§3 C1), 不在 JSON 列上补 CAS。
        row.doc = doc
        row.status = "ready"
        row.updated_at = _utcnow()
    else:
        row = DialogueSceneRow(
            user_id=job.user_id,
            scene_key=key,
            doc=doc,
            status="ready",
            source="generated",
        )
        db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise GenerationError("同一场景已在生成中 (并发去重)") from exc
    return custom_scene_id(row.id)


# ====== 读路径 (归属隔离; §3 C3b) ======


def scene_view_for_row(row: DialogueSceneRow) -> DialogueScene | None:
    """一行 -> 目录同款视图; doc 坏掉/非 dict -> ``None`` (读侧逐行宽容, 同 T2 策略)."""
    raw = row.doc
    if not isinstance(raw, dict):
        logger.warning("custom scene doc skipped (not a dict) | row={}", row.id)
        return None
    try:
        # JSON 列读纪律: deepcopy 一份再校验 (不信任列里的旧数据).
        spec = CustomDialogueScene.model_validate(copy.deepcopy(raw))
    except ValidationError as exc:
        logger.warning("custom scene doc skipped | row={} err={}", row.id, exc)
        return None
    return dialogue_scene_view(custom_scene_id(row.id), spec)


async def find_ready_custom_scene(
    db: AsyncSession, user_id: str, scene_id: str
) -> DialogueScene | None:
    """按 ``custom_<row.id>`` 取归属 ``user_id`` 的**就绪**场景骨架, 投影成目录同款视图.

    隔离形状照 ``scene_store.find_generated_course``: 不是本人的行 / 未就绪 / doc 坏掉
    都返回 ``None`` —— 与"不存在"同形 (404 不泄露存在性)。自定义场景没有静态 id,
    拆前缀即可拿行 id, 不必像课程那样遍历 doc["id"]。
    """
    row_id = row_id_from_scene_id(scene_id)
    if row_id is None:
        return None
    row = (
        await db.execute(
            select(DialogueSceneRow).where(
                DialogueSceneRow.id == row_id,
                DialogueSceneRow.user_id == user_id,
                DialogueSceneRow.status == "ready",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return scene_view_for_row(row)


async def list_ready_custom_scenes(db: AsyncSession, user_id: str) -> list[DialogueScene]:
    """该用户全部 ``ready`` 自定义场景 (目录合并的读侧; 提交顺序稳定排列)."""
    rows = (
        (
            await db.execute(
                select(DialogueSceneRow)
                .where(DialogueSceneRow.user_id == user_id, DialogueSceneRow.status == "ready")
                .order_by(DialogueSceneRow.created_at, DialogueSceneRow.id)
            )
        )
        .scalars()
        .all()
    )
    return [scene for row in rows if (scene := scene_view_for_row(row)) is not None]


def dialogue_scene_view(scene_id: str, spec: CustomDialogueScene) -> DialogueScene:
    """骨架 -> 目录同款视图 (``_scene_messages``/``_opening_prompt`` 的统一素材形状).

    自定义场景**没有**双语展示对 (选择器卡片就按学员描述的语言展示), 所以
    ``title_en``/``description_en`` 留空 (D5: 缺字段 = 那一行不渲染);
    ``suggestion_lines`` 留空是纪律而非省事 —— 它是"参考回答素材位", 静态兜底句正是
    "每轮同一句"的根因 (T3 删死兜底时立的规), 生成器没有资格造一句新的。

    ``roles`` 为空 = **存量行** (v3.0 才加的字段, 落在 DB 里的旧 doc 不会回填),
    用 ``persona_cn`` 合成一个角色让老自定义场景还能开聊; 新作业一律产出 1-3 个角色。
    """
    roles = tuple(
        SceneRole(
            role_id=role.role_id,
            name=role.name_cn,
            name_en="",
            voice=role.voice,
            persona="",
            persona_cn=role.persona_cn,
        )
        for role in spec.roles
    ) or (
        SceneRole(
            role_id="r1",
            name=spec.persona_cn,
            name_en="",
            voice=VOICES[0],
            persona="",
            persona_cn=spec.persona_cn,
        ),
    )
    return DialogueScene(
        id=scene_id,
        title=spec.title,
        description=spec.description,
        title_en="",
        description_en="",
        roles=roles,
        user_role=spec.user_role_cn,
        user_role_en="",
        opening_lines=(
            OpeningLine(role_id=roles[0].role_id, text=spec.opener, text_cn=spec.opener_cn),
        ),
        suggestion_lines=(),
        beats=tuple(spec.beats),
        # ``goal`` 也是 prompt 素材, 而 DialogueScene 只有一格情境位: 情境与目标拼成一行
        # 进 ``context`` (目录场景没有独立 goal, 不占这一格)。
        context=f"{spec.context_cn}(本场目标:{spec.goal})",
    )


def spawn_scene_brief_job(job_id: str) -> None:
    """``asyncio.create_task`` 后台跑; 模块级集合防任务被 GC (与 ``spawn_job`` 同形)。

    **没有会话级在途门** (同整课生成 ``spawn_job`` 的既有口径, 质量审查 M-3): 同人同
    描述连点两次 = 两个作业两次 LLM, 后完成者覆盖 ``doc`` (upsert 语义) —— 客户端按钮
    防连点属安卓侧 (T5), 服务端不挡。
    """
    task = asyncio.create_task(run_scene_brief_job(job_id))
    _JOBS.add(task)
    task.add_done_callback(_JOBS.discard)


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "SCENE_BRIEF_MAX_TOKENS",
    "GenerationError",
    "dialogue_scene_view",
    "find_ready_custom_scene",
    "generate_scene_spec",
    "list_ready_custom_scenes",
    "run_scene_brief_job",
    "scene_view_for_row",
    "spawn_scene_brief_job",
    "spec_messages",
]
