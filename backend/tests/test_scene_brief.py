"""§3 C2/C3b 服务层 —— 自定义场景骨架的作业链路与归属隔离 (端点面在 test_dialogue_custom_scenes.py).

覆盖:

* **job 骨架** (照 ``course_generator._run_job`` 的形状): ``run_scene_brief_job`` 自开会话、
  推进 ``progress``/``stage_text``、一次 ``_judge`` 出骨架 JSON、坏输出回喂重试 1 次、
  再坏 ``job=failed``; 未配置/挂死也都收敛成终态 (轮询永远等得到答案)。
* **预算口径**: 墙钟 ``SCENE_BRIEF_JOB_BUDGET_S`` 在调用点显式传 (AST 门点名); 挂死 LLM
  在墙内降级成 ``failed``。socket 沿用 ``_judge`` 默认。
* **scene_key 指纹 upsert 幂等**: 同人同描述重复提交不产生第二行, 对外 id 稳定。
* **可信度门**: ``opener_cn`` 不可信 (混英文) -> 置空 (D5, 复用 ``coerce_bilingual``);
  CEFR ``level`` 非法 -> 由回喂重试修正。
* **归属隔离** (§3 C3b, 照 ``scene_store.find_generated_course`` 先例): 别人的行 / 非
  ready / doc 坏掉 全当不存在 (``None``), 视图投影逐字段可断。
* **kind 隔离**: ``scene_brief``  runner 不许碰 ``course`` 作业 (两任务同居一张表)。

手法: conftest autouse 已把 ``spawn_scene_brief_job`` 换成 no-op, 作业一律由用例自己
``await run_scene_brief_job(job_id)`` 驱动终态 (同 ``test_grading_async``); LLM 用共享
``install_llm(scene=[...])`` 按 **prompt JSON 形状** (``"opener_cn"`` 键) 路由, 不依赖调用顺序。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import DialogueSceneRow, GenerationJob
from app.models.scene_spec import CustomDialogueScene, custom_scene_id, row_id_from_scene_id
from app.services import llm_provider
from app.services import scene_spec_generator as sg
from app.services.users import lookup_user
from tests.test_drill_grader import install_llm
from tests.test_latency_budget import _hanging

DEV = "dev-brief"
OTHER = "dev-other-brief"

#: 预算改小用的打点墙 (同 test_latency_budget 的 TINY_BUDGET_S 口径).
TINY_WALL_S = 0.3


@pytest.fixture(autouse=True)
def _reset_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


def scene_spec_payload(**over: Any) -> dict[str, Any]:
    """一份合规的 :class:`CustomDialogueScene` dump (§3 C2 的十个字段, 一个不多一个不少)."""
    payload: dict[str, Any] = {
        "title": "和外教聊周末",
        "description": "和外国教练聊聊你这周末做了什么。",
        "persona_cn": "你的外国教练",
        "user_role_cn": "分享周末生活的学员",
        "context_cn": "周一课间, 教练想知道你周末去哪玩了。",
        "goal": "自然地聊自己的周末活动, 能接住追问",
        "beats": ["说说去了哪", "回应教练自己的周末", "约下周一起训练"],
        "opener": "Hey! How was your weekend?",
        "opener_cn": "嘿! 你周末过得怎么样?",
        "level": "A2",
    }
    payload.update(over)
    return payload


def scene_spec_json(**over: Any) -> str:
    return json.dumps(scene_spec_payload(**over), ensure_ascii=False)


async def _user_id(db: AsyncSession, device_id: str) -> str:
    user = await lookup_user(db, device_id=device_id, create=True)
    assert user is not None
    await db.commit()
    return user.id


async def _seed_job(db: AsyncSession, user_id: str, brief: str, kind: str = "scene_brief") -> str:
    job = GenerationJob(
        user_id=user_id,
        kind=kind,
        goal_text=brief,
        status="running",
        progress=0.0,
        stage_text="排队中…",
    )
    db.add(job)
    await db.commit()
    return job.id


async def _reload_job(db: AsyncSession, job_id: str) -> GenerationJob:
    """读 job: 异步 session 里过期属性访问 = 隐式 IO (MissingGreenlet), 显式 refresh 再读.

    刻意**不 rollback**: rollback 会把测试里别的已加载实例一起过期 (job 与 rows 交替读
    时必踩)。refresh 只对目标行重发 SELECT, 不动别人。
    """
    job = await db.get(GenerationJob, job_id)
    assert job is not None
    await db.refresh(job)
    return job


async def _rows_of(db: AsyncSession, user_id: str) -> list[DialogueSceneRow]:
    res = await db.execute(select(DialogueSceneRow).where(DialogueSceneRow.user_id == user_id))
    rows = list(res.scalars().all())
    for row in rows:
        await db.refresh(row)
    return rows


# ============================================================ prompt 与 schema


def test_spec_messages_put_brief_and_shape_into_prompt() -> None:
    msgs = sg.spec_messages("我想练和邻居闲聊花园")
    joined = "\n".join(m.content for m in msgs)
    assert "我想练和邻居闲聊花园" in joined
    # JSON 形状把字段名钉死 (与 install_llm 的形状路由同一锚点), 中文侧要求也在 prompt 里.
    for key in ("persona_cn", "user_role_cn", "beats", "opener_cn", "level"):
        assert f'"{key}"' in joined
    assert "3-6" in joined  # 议程条数硬约束
    assert "只输出一个 JSON 对象" in joined


def test_custom_dialogue_scene_requires_three_beats_and_cefr_level() -> None:
    with pytest.raises(ValueError):
        CustomDialogueScene.model_validate({**scene_spec_payload(), "beats": ["太少", "不够"]})
    with pytest.raises(ValueError):
        CustomDialogueScene.model_validate({**scene_spec_payload(), "level": "B9"})


# ============================================================ 一次调用 + 回喂


@pytest.mark.asyncio
async def test_generate_scene_spec_coerces_untrusted_opener_cn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``opener_cn`` 混英文 = 中文标签下的英文 -> 可信度门置空 (D5, coerce_bilingual 复用)."""
    install_llm(
        monkeypatch,
        scene=[
            scene_spec_json(
                opener="How was your weekend?",
                opener_cn="Wonderful weekend!",  # 纯英文对照: 不可信
            )
        ],
    )
    spec = await sg.generate_scene_spec("和外教聊我的周末")
    assert spec.opener_cn == ""
    assert spec.opener == "How was your weekend?"
    assert spec.persona_cn == "你的外国教练"


@pytest.mark.asyncio
async def test_generate_scene_spec_returns_llm_unavailable_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置 -> GenerationError (由 job runner 收敛成 failed, 不裸抛进轮询)."""
    with pytest.raises(sg.GenerationError):
        await sg.generate_scene_spec("任何描述")


# ============================================================ job 状态机


@pytest.mark.asyncio
async def test_run_scene_brief_job_ready_writes_row_and_returns_scene_id(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    brief = "和外教聊我的周末"
    uid = await _user_id(db, DEV)
    job_id = await _seed_job(db, uid, brief)
    client = install_llm(monkeypatch, scene=[scene_spec_json()])

    await sg.run_scene_brief_job(job_id)

    job = await _reload_job(db, job_id)
    assert job.status == "ready"
    assert job.progress == 1.0
    assert job.stage_text == "场景已就绪"
    assert job.scene_id.startswith("custom_")
    assert job.error is None
    rows = await _rows_of(db, uid)
    assert len(rows) == 1
    row = rows[0]
    assert job.scene_id == custom_scene_id(row.id)
    assert row_id_from_scene_id(job.scene_id) == row.id
    assert row.status == "ready"
    assert row.source == "generated"
    assert row.scene_key == sg.scene_key_for(brief)
    doc = CustomDialogueScene.model_validate(row.doc)
    assert doc.title == "和外教聊周末"
    assert len(doc.beats) == 3
    # 一次调用恰好发生一次 (不是顺序脚本的猜谜): 形状路由到 scene 队列。
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_run_scene_brief_job_feeds_back_bad_output_once(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    brief = "第一次坏 JSON, 回喂重试一次就好"
    uid = await _user_id(db, DEV)
    job_id = await _seed_job(db, uid, brief)
    # 坏 -> 好: 合法 JSON 但 beats 只有 2 条 (pydantic 不过) -> 重试吐合规.
    bad = json.dumps(scene_spec_payload(beats=["太少", "不够"]), ensure_ascii=False)
    client = install_llm(monkeypatch, scene=[bad, scene_spec_json()])

    await sg.run_scene_brief_job(job_id)

    job = await _reload_job(db, job_id)
    assert job.status == "ready"
    assert len(client.requests) == 2
    assert len(await _rows_of(db, uid)) == 1


@pytest.mark.asyncio
async def test_run_scene_brief_job_fails_honestly_after_second_bad(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两次都不合规 -> ``failed`` + 诚实原因; 不产生任何半坏的行."""
    brief = "两次都坏就不硬造场景"
    uid = await _user_id(db, DEV)
    job_id = await _seed_job(db, uid, brief)
    install_llm(monkeypatch, scene=["不是JSON", "还不是JSON"])

    await sg.run_scene_brief_job(job_id)

    job = await _reload_job(db, job_id)
    assert job.status == "failed"
    assert job.error
    assert job.scene_id == ""
    assert await _rows_of(db, uid) == []


@pytest.mark.asyncio
async def test_run_scene_brief_job_hanging_llm_fails_within_wall(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """墙钟在挂死的 LLM 上真的封顶: 0.3s 级预算 -> ``failed``, 整作业 < 3s。

    这条是 AST 门的**行为面**: 调用点写了 ``hard_budget_s=SCENE_BRIEF_JOB_BUDGET_S``,
    这里改小命名空间里的那个名字再验证降级路径真被走到。
    """
    uid = await _user_id(db, DEV)
    job_id = await _seed_job(db, uid, "挂死的外科医生场景")
    monkeypatch.setattr(sg, "SCENE_BRIEF_JOB_BUDGET_S", TINY_WALL_S)
    _hanging(monkeypatch)

    started = time.monotonic()
    await sg.run_scene_brief_job(job_id)
    elapsed = time.monotonic() - started

    job = await _reload_job(db, job_id)
    assert job.status == "failed"
    assert elapsed < 3.0, f"作业墙没封顶 (实际 {elapsed:.1f}s)"


@pytest.mark.asyncio
async def test_scene_key_upsert_reuses_the_row_and_stays_one_row(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**同人同描述重复提交不产生第二行** (scene_key 指纹幂等, 行 id 稳定)."""
    brief = "和外教聊我的周末"
    uid = await _user_id(db, DEV)
    first_job = await _seed_job(db, uid, brief)
    install_llm(monkeypatch, scene=[scene_spec_json()])
    await sg.run_scene_brief_job(first_job)
    original = (await _rows_of(db, uid))[0]

    second_job = await _seed_job(db, uid, brief)
    install_llm(monkeypatch, scene=[scene_spec_json(title="第二次生成的标题")])
    await sg.run_scene_brief_job(second_job)

    rows = await _rows_of(db, uid)
    assert len(rows) == 1
    row = await db.get(DialogueSceneRow, original.id)
    assert row is not None and row.doc["title"] == "第二次生成的标题"
    reloaded = await _reload_job(db, second_job)
    assert reloaded.status == "ready"
    assert reloaded.scene_id == custom_scene_id(original.id)


@pytest.mark.asyncio
async def test_scene_brief_concurrent_duplicate_loses_cleanly(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**输家分支真被执行**: 同 (user, scene_key) 的第二个作业撞 ``IntegrityError`` ->
    ``GenerationError("同一场景已在生成中 (并发去重)")`` -> ``job=failed``, 赢家行零污染。

    sqlite 测试跑在单连接池上, 真并发不可造 —— 打点手法照仓内既有的输家先例
    (``test_engine_units.test_expression_upsert_race_returns_winner`` /
    ``test_course_sessions`` 的 racing_flush): 在 ``_persist_scene`` 的 select 与 INSERT
    之间的 race 窗口里让对手 session 先提交同 key 的行, 输家 flush 撞唯一索引。
    唯一索引建得对不对由 ``test_migrations_sqlite`` 钉; 这条钉的是撞了之后的语义:
    输家的 add 随 ``_fail`` 的 rollback 一起丢弃 (不覆盖赢家 doc), job 落 failed。
    """
    brief = "并发去重场景"
    uid = await _user_id(db, DEV)
    job_id = await _seed_job(db, uid, brief)
    install_llm(monkeypatch, scene=[scene_spec_json()])

    real_flush = AsyncSession.flush
    armed = {"n": 0}

    async def racing_flush(self: AsyncSession, *args: Any, **kw: Any) -> None:
        # 单次打点: runner 内第一条 await flush 就是 _persist_scene 的 INSERT
        # (进度推进全走 commit, 不经 AsyncSession.flush 这条 python 方法)。
        if armed["n"] == 0:
            armed["n"] += 1
            async with sg.get_sessionmaker()() as winner_db:
                winner_db.add(
                    DialogueSceneRow(
                        user_id=uid,
                        scene_key=sg.scene_key_for(brief),
                        doc=scene_spec_payload(title="赢家先落库"),
                        status="ready",
                    )
                )
                await winner_db.commit()
            raise IntegrityError("INSERT INTO dialogue_scenes", {}, RuntimeError("UNIQUE"))
        await real_flush(self, *args, **kw)

    monkeypatch.setattr(AsyncSession, "flush", racing_flush)
    await sg.run_scene_brief_job(job_id)

    job = await _reload_job(db, job_id)
    assert job.status == "failed"
    assert "同一场景已在生成中" in (job.error or ""), job.error
    rows = await _rows_of(db, uid)
    assert len(rows) == 1, "输家的半截 INSERT 必须随 rollback 一起消失"
    assert rows[0].doc["title"] == "赢家先落库"
    assert rows[0].status == "ready"
    assert armed["n"] == 1, "打点确实落在 _persist_scene 的 flush 上"


@pytest.mark.asyncio
async def test_scene_brief_runner_refuses_foreign_kind(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``course`` 作业不归 scene runner 跑 (同居一张表靠 kind 隔离, 不碰整课链路)."""
    uid = await _user_id(db, DEV)
    job_id = await _seed_job(db, uid, "这是一条整课作业", kind="course")
    client = install_llm(monkeypatch, scene=[scene_spec_json()])

    await sg.run_scene_brief_job(job_id)

    refreshed = await _reload_job(db, job_id)
    assert refreshed.status == "running"  # 没被错表认领
    await db.rollback()
    assert client.requests == []
    assert await _rows_of(db, uid) == []


# ============================================================ 读路径 (归属隔离)


@pytest.mark.asyncio
async def test_custom_scene_spec_never_visible_to_other_users(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """场景行按 owner 隔离 (§3 C3b): ``find_ready_custom_scene`` 对别人 = 不存在."""
    brief = "只有我看得见的秘密场景"
    uid = await _user_id(db, DEV)
    job_id = await _seed_job(db, uid, brief)
    install_llm(monkeypatch, scene=[scene_spec_json()])
    await sg.run_scene_brief_job(job_id)
    rows = await _rows_of(db, uid)
    scene_id = custom_scene_id(rows[0].id)

    other_uid = await _user_id(db, OTHER)
    assert await sg.find_ready_custom_scene(db, other_uid, scene_id) is None

    mine = await sg.find_ready_custom_scene(db, uid, scene_id)
    assert mine is not None
    assert mine.id == scene_id
    # prompt 素材逐字段投影 (B6 的同一条纪律: 人设/议程/开场都是素材形状, 不是展示行).
    assert mine.title == "和外教聊周末"
    assert mine.persona == "你的外国教练"
    assert mine.user_role == "分享周末生活的学员"
    assert mine.beats and len(mine.beats) == 3
    assert mine.openings == (rows[0].doc["opener"],)
    assert mine.id.startswith("custom_")  # 43 字符 < scene_id max 64
    assert len(mine.id) <= 64


@pytest.mark.asyncio
async def test_find_ready_custom_scene_rejects_states_and_broken_doc(
    db: AsyncSession,
) -> None:
    """未就绪 / doc 坏掉 / 非 custom 前缀, 一律与"不存在"同形 (None)."""
    uid = await _user_id(db, DEV)
    row = DialogueSceneRow(
        user_id=uid, scene_key="k-generating", doc=scene_spec_payload(), status="generating"
    )
    db.add(row)
    broken = DialogueSceneRow(
        user_id=uid, scene_key="k-broken", doc={"not": "a spec"}, status="ready"
    )
    db.add(broken)
    await db.commit()

    assert await sg.find_ready_custom_scene(db, uid, custom_scene_id(row.id)) is None
    assert await sg.find_ready_custom_scene(db, uid, custom_scene_id(broken.id)) is None
    assert await sg.find_ready_custom_scene(db, uid, "coffee_shop") is None
    assert await sg.find_ready_custom_scene(db, uid, "custom_") is None
