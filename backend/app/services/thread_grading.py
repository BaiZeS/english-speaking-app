"""v3.0 每轮评分的后台作业 (方案 S2.6).

判分**不进请求**: 实测判分路 4.2-6.7s, 而台词那条链已经顶格 (25.0 ≤ 25.0, 零余量)。
所以请求先把评分卡以 ``pending`` 落一颗气泡, 这里在请求之外把它翻成 ``ready``。

形状照 ``course_sessions`` 的实战判分作业抄, 四条纪律一条不少:
模块级持 task 防 GC、**会话级在途门 x 逐轮进度**、自建 session、必落终态、
**终态 CAS 门** (写一次算一次, 输家回滚不双计)、崩了也收敛成 ``failed``。

与实战判分的两处实质差别: 评的是"回应质量 + 任务推进"而不是语法/词汇分 (学员可能
根本说的是中文); 发音分不在这里 —— 它在请求里由 ISE 现算, 已经写进那颗气泡了。
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.models.db import DialogueThread
from app.services import dialogue_scenes, scene_spec_generator, thread_store, turn_generation
from app.services.drill_grader import GRADING_TURN_BUDGET_S, LlmUnavailableError, _judge
from app.services.llm_provider import LlmMessage, no_thinking_body

#: 一个作业最多连判几轮 (在途门会吞掉作业期间新派的那一次, 所以要把新落的轮子也判掉)。
_MAX_ROUNDS = 3
#: 写回撞乐观锁的重试次数 (对手是学员的下一轮提交)。
_WRITE_ATTEMPTS = 3
#: 判分失败后的"翻身"水位: 超过这个时长还挂着 pending, GET 会重派一次作业。
REDISPATCH_AFTER_S = GRADING_TURN_BUDGET_S * 2

#: 模块级持有 task 引用: asyncio 只弱引用任务, 不留句柄会被 GC 掉而永远不跑。
_JOBS: set[asyncio.Task[None]] = set()
#: 会话级在途门: 同一条线程同时只跑一个判分作业。
_IN_FLIGHT: set[str] = set()

_JSON_SHAPE = (
    '只输出 JSON: {"relevance": number, "informativeness": number, '
    '"appropriateness": number, "beat_progress": true|false, '
    '"comment": "...", "comment_cn": "..."}'
)


class ThreadGradeJudgement(BaseModel):
    """一轮回应的质量判词 (0-100 三轴 + 是否推进议程)。"""

    relevance: int = Field(ge=0, le=100)
    informativeness: int = Field(ge=0, le=100)
    appropriateness: int = Field(ge=0, le=100)
    beat_progress: bool = False
    comment: str = Field(default="", max_length=300)
    comment_cn: str = Field(default="", max_length=300)

    @field_validator("comment", "comment_cn")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def score(self) -> int:
        """综合分 = 三轴均值 (推进议程 +5, 封顶 100)。

        三轴等权是有意的: 这一轮没有"更重的维度" —— 说得切题、说得有内容、说得得体,
        对初学者就是同一件事的三个面。真要拉开权重, 得先有证据说明某一轴更能预测开口。
        """
        base = (self.relevance + self.informativeness + self.appropriateness) / 3.0
        return int(min(100.0, base + (5.0 if self.beat_progress else 0.0)))


def grade_messages(
    scene: dialogue_scenes.DialogueScene,
    learner_text: str,
    *,
    beat_index: int,
    recent: list[str],
) -> list[LlmMessage]:
    """判分 prompt: 场景 + 议程位置 + 学员这句 (中文英文都照原样判内容, 不判语法)."""
    beat_line = ""
    if scene.beats and beat_index < len(scene.beats):
        beat_line = f"当前议程条目: {scene.beats[beat_index]}。"
    history = "\n".join(f"- {line}" for line in recent[-6:])
    system = (
        "你是口语陪练的教练, 在评判学员在情景对话里**这一句回应**的质量。"
        f"场景: 「{scene.title}」 —— {scene.description}。学员扮演: {scene.user_role}。"
        f"{beat_line}\n"
        + (f"之前聊过的:\n{history}\n" if history else "")
        + "学员这句可能是中文也可能是英文: **只判内容, 不判语法、不判发音**。要求:\n"
        "(1) relevance 切题度 0-100: 这句回应符不符合当前场景与正在聊的条目;\n"
        "(2) informativeness 信息量 0-100: 有没有真的给出内容, 而不是一个词糊过去;\n"
        "(3) appropriateness 得体度 0-100: 语气与礼节合不合这场对话;\n"
        "(4) beat_progress: 这句是否让议程**实质往前走了**一步;\n"
        "(5) comment: 一句英文点评 (≤25 词, 说清好在哪/可以怎么补);\n"
        "(6) comment_cn: 它的简体中文意思。\n" + _JSON_SHAPE
    )
    return [
        LlmMessage(role="system", content=system),
        LlmMessage(role="user", content=f"学员这句: {learner_text}"),
    ]


async def grade_turn(
    scene: dialogue_scenes.DialogueScene,
    learner_text: str,
    *,
    beat_index: int,
    recent: list[str],
) -> ThreadGradeJudgement | None:
    """一次判分; LLM 不可用/两次都不合规 -> ``None`` (调用方落 ``failed``, 静默)。"""
    try:
        return await _judge(
            ThreadGradeJudgement,
            grade_messages(scene, learner_text, beat_index=beat_index, recent=recent),
            max_tokens=300,
            temperature=0.2,
            hard_budget_s=GRADING_TURN_BUDGET_S,
            extra_body=no_thinking_body(),
        )
    except LlmUnavailableError as exc:
        logger.warning("thread grading unavailable: {}", exc)
        return None


# ====== 作业 ======


def spawn_thread_grading(thread_id: str, user_id: str) -> None:
    """派生判分作业; 同一条线程在途时**直接跳过** (幂等门)。"""
    if thread_id in _IN_FLIGHT:
        return
    task = asyncio.create_task(run_thread_grading_job(thread_id, user_id))
    _JOBS.add(task)
    _IN_FLIGHT.add(thread_id)

    def _done(finished: asyncio.Task[None]) -> None:
        _JOBS.discard(finished)
        _IN_FLIGHT.discard(thread_id)
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            logger.error("thread grading job raised | thread={} {}", thread_id, exc)

    task.add_done_callback(_done)


def in_flight(thread_id: str) -> bool:
    """GET 的水位重派要用它判断"是不是真有一个作业在跑"。"""
    return thread_id in _IN_FLIGHT


async def run_thread_grading_job(thread_id: str, user_id: str) -> None:
    """后台把 pending 的评分卡补成 ready/failed. 三条出口都要落**终态**。"""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        try:
            await _run(db, thread_id, user_id)
        except Exception:
            logger.exception("thread grading job crashed | thread={}", thread_id)
            await _fail_all(db, thread_id)


async def _run(db: AsyncSession, thread_id: str, user_id: str) -> None:
    """作业主体: **每判完一轮就复读一次待判清单**。

    在途门是线程级的, 进度却是逐颗气泡的 —— 作业跑着的时候学员又说了下一句, 那一次
    ``spawn`` 会被门挡掉。复读 todo 让它在本作业里就被判掉, 不用等水位。
    """
    graded_any = False
    for _round in range(_MAX_ROUNDS):
        row = await thread_store.get_thread(db, thread_id, user_id)
        if row is None:
            logger.info("thread grading skipped | thread={} row gone", thread_id)
            return
        doc = thread_store.load_doc(row)
        scene = await _resolve_scene(db, doc, user_id)
        if scene is None:
            logger.warning("thread grading skipped | thread={} scene gone", thread_id)
            return
        todo = _pending_grades(doc)
        if not todo:
            if not graded_any:
                _heal_pointer(doc)
                await thread_store.save_doc(db, row, doc, grading_status=_pointer_of(doc))
            return
        for message in todo:
            judgement = await grade_turn(
                scene,
                _learner_text_for(doc, message),
                beat_index=int(doc.get("beat_index") or 0),
                recent=_recent_lines(doc),
            )
            if not await _publish(db, thread_id, user_id, str(message["id"]), judgement):
                return
        graded_any = True
    logger.warning("thread grading hit round cap | thread={}", thread_id)


async def _resolve_scene(db: AsyncSession, doc: dict[str, Any], user_id: str) -> Any:
    scene_id = str(doc.get("scene_id") or "")
    scene = dialogue_scenes.resolve_scene(scene_id)
    if scene is not None:
        return scene
    return await scene_spec_generator.find_ready_custom_scene(db, user_id, scene_id)


def _pending_grades(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        message
        for message in thread_store.messages_of(doc)
        if message.get("kind") == thread_store.KIND_GRADE
        and isinstance(message.get("grade"), dict)
        and message["grade"].get("status") == thread_store.GRADING_PENDING
    ]


def _learner_text_for(doc: dict[str, Any], grade_message: dict[str, Any]) -> str:
    """评分卡**前面**最近的那颗 user 气泡 —— 就是它要被评。"""
    index = thread_store.messages_of(doc).index(grade_message)
    for message in reversed(thread_store.messages_of(doc)[:index]):
        if message.get("kind") == thread_store.KIND_USER:
            return str(message.get("recognized_text") or message.get("text") or "")
    return ""


def _recent_lines(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for message in thread_store.messages_of(doc):
        if message.get("kind") == thread_store.KIND_LINE:
            out.append(str(message.get("text") or ""))
        elif message.get("kind") == thread_store.KIND_USER:
            out.append(str(message.get("recognized_text") or message.get("text") or ""))
    return [line for line in out if line.strip()]


def _pointer_of(doc: dict[str, Any]) -> str:
    """顶层指针 = 最后那颗评分卡的态 (逐轮态才是真相, 这里只给列表一个免解析的读法)。"""
    for message in reversed(thread_store.messages_of(doc)):
        grade = message.get("grade")
        if isinstance(grade, dict) and grade.get("status"):
            return str(grade["status"])
    return thread_store.GRADING_EMPTY


def _heal_pointer(doc: dict[str, Any]) -> None:
    doc["grading_status"] = _pointer_of(doc)


def _grade_payload(judgement: ThreadGradeJudgement | None) -> dict[str, Any]:
    if judgement is None:
        return {"status": thread_store.GRADING_FAILED, "score": 0, "axes": {}, "comment_cn": ""}
    axes = {
        "relevance": float(judgement.relevance),
        "informativeness": float(judgement.informativeness),
        "appropriateness": float(judgement.appropriateness),
        "beat_progress": 1.0 if judgement.beat_progress else 0.0,
    }
    return {
        "status": thread_store.GRADING_READY,
        "score": judgement.score,
        "axes": axes,
        "comment": judgement.comment,
        "comment_cn": turn_generation.coerce_bilingual(judgement.comment_cn),
    }


async def _publish(
    db: AsyncSession, thread_id: str, user_id: str, message_id: str, judgement: Any
) -> bool:
    """终态 CAS 门: 事务内**重读**、只认还在 ``pending`` 的那颗、改完整体换对象写回。

    输掉乐观锁的一方必须作废重来, 而不是硬写 —— 对面可能是学员刚提交的下一轮。
    重复判同一颗气泡在这里也被这道门挡掉 (重读时它已经不是 pending 了)。
    """
    for _attempt in range(_WRITE_ATTEMPTS):
        row = await thread_store.get_thread(db, thread_id, user_id)
        if row is None:
            return False
        doc = thread_store.load_doc(row)
        target = next(
            (m for m in thread_store.messages_of(doc) if str(m.get("id")) == message_id), None
        )
        if not isinstance(target, dict) or not isinstance(target.get("grade"), dict):
            return False
        if target["grade"].get("status") != thread_store.GRADING_PENDING:
            return True  # 别人已经把它推到终态了, 本作业到此为止
        target["grade"] = _grade_payload(judgement)
        _heal_pointer(doc)
        if await thread_store.save_doc(db, row, doc, grading_status=doc["grading_status"]):
            return True
    logger.warning("thread grading write lost the lock | thread={}", thread_id)
    return False


async def _fail_all(db: AsyncSession, thread_id: str) -> None:
    """作业崩了: 尽力把所有 pending 收成 ``failed``, 绝不留悬挂态。

    留 pending 的后果不是"少个分数"而是**水位永远够、作业反复重派** —— 每开一次聊天
    都白烧一次 LLM。这里自己再抛错就只能记日志 (总得有个地方停)。
    """
    try:
        row = await db.get(DialogueThread, thread_id)
        if row is None:
            return
        doc = thread_store.load_doc(row)
        changed = False
        for message in thread_store.messages_of(doc):
            grade = message.get("grade")
            if isinstance(grade, dict) and grade.get("status") == thread_store.GRADING_PENDING:
                grade["status"] = thread_store.GRADING_FAILED
                changed = True
        if changed:
            _heal_pointer(doc)
            await thread_store.save_doc(db, row, doc, grading_status=doc["grading_status"])
    except Exception as exc:  # pragma: no cover - 兜底的兜底
        logger.error("thread grading fail-all crashed | thread={} {}", thread_id, exc)
