"""两段式课程生成 (P4) 的测试: 端点 202 -> 后台任务 -> job 状态机 -> scene_courses.

覆盖 (任务书 §范围 2 + §范围 5):
* 两段生成 happy path: POST /scenes/generate 202 -> ``run_generation_job`` ->
  job=ready + ``scene_courses`` 行 (source=generated, status=ready) -> 画廊/详情可见;
* 坏 JSON -> 回喂重试 1 次 -> 再坏 job=failed + failure_reason (诚实报错);
* LLM 未配置 -> job=failed (不静默);
* 两段推进 (LLM 恰好被调 2 次) + T2 硬约束写死在 prompt;
* 同 (user, goal) 重生成 = upsert 复用旧行与旧 id (不堆课);
* 入口校验: goal_text 4..200、category/level 白名单 400; job 归属隔离 403/404。

Mock 手法沿用 test_mission (``install_llm`` 换 AsyncOpenAI); 本文件自带 autouse
provider 复位 + ``spawn_job`` no-op (测试直接 await runner)。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import SceneCourseRow, User
from app.services import course_generator, scene_store
from app.services.drill_grader import _resolve_judge_model
from app.services.llm_provider import get_llm_provider
from tests.test_drill_grader import install_llm

DEV = "dev-gen"
OTHER = "dev-other"

#: autouse 夹具会把模块属性 ``spawn_job`` 换成 no-op; 导入期抓住原身供真身测试用.
ORIGINAL_SPAWN = course_generator.spawn_job


@pytest.fixture(autouse=True)
def _reset_provider_and_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """provider 单例复位 + ``spawn_job`` no-op (测试直接 await runner, 不真开任务)."""
    from app.services import llm_provider

    llm_provider.reset_llm_provider_for_tests()
    monkeypatch.setattr(course_generator, "spawn_job", lambda job_id: None)
    scene_store.invalidate_cache()
    yield
    llm_provider.reset_llm_provider_for_tests()
    scene_store.invalidate_cache()


async def _generate(client: AsyncClient, **over: Any) -> Any:
    payload: dict[str, Any] = {
        "device_id": DEV,
        "goal_text": "下周要用英文主持一次项目会议",
    }
    payload.update(over)
    return await client.post("/api/v1/scenes/generate", json=payload)


async def _job(client: AsyncClient, job_id: str, device: str | None = DEV) -> Any:
    params = {"device_id": device} if device else {}
    return await client.get(f"/api/v1/scenes/jobs/{job_id}", params=params)


async def _user_id(db: AsyncSession, device_id: str) -> str:
    return str(
        ((await db.execute(select(User).where(User.device_id == device_id))).scalar_one()).id
    )


async def _course_rows(db: AsyncSession, device_id: str) -> list[SceneCourseRow]:
    uid = await _user_id(db, device_id)
    return list(
        (await db.execute(select(SceneCourseRow).where(SceneCourseRow.user_id == uid))).scalars()
    )


def skeleton_json(**over: Any) -> str:
    """段1 (骨架) 的合规 JSON: 词汇 6 个、任务 3 条、难度 B1."""
    words = ("team", "plan", "update", "schedule", "client", "goal")
    payload: dict[str, Any] = {
        "title": "主持项目启动会",
        "subtitle_en": "Let's kick off the project.",
        "category": "workplace",
        "level": "B1",
        "est_minutes": 8,
        "brief_cn": "一门用来验证生成链路的职场课。",
        "skills": ["vocabulary", "communication"],
        "vocab": [
            {
                "word": word,
                "ipa": "/ti:m/",
                "meaning_cn": "n. 团队/计划",
                "example_en": f"Our {word} is ready.",
            }
            for word in words
        ],
        "persona_cn": "项目经理",
        "user_role_cn": "团队成员",
        "context_cn": "在项目启动会上对齐目标与时间安排。",
        "opening_a": "Hi everyone, shall we kick off the project?",
        "opening_a_cn": "大家好, 我们开始项目吧?",
        "tasks": [
            {
                "id": "t1",
                "desc_cn": "接住开场并确认目标",
                "hint_en": "Sure, let's start with the goal.",
                "hint_cn": "先接住开场。",
                "required": True,
            },
            {
                "id": "t2",
                "desc_cn": "说出时间安排",
                "hint_en": "The plan takes two weeks.",
                "hint_cn": "说清时间。",
                "required": True,
            },
            {
                "id": "t3",
                "desc_cn": "确认下一步",
                "hint_en": "I'll send the update today.",
                "hint_cn": "收尾确认。",
                "required": False,
            },
        ],
        "max_turns": 8,
    }
    payload.update(over)
    return json.dumps(payload, ensure_ascii=False)


def detail_json(**over: Any) -> str:
    """段2 (步骤 + 剧本) 的合规 JSON: 4 步覆盖四题型、5 对 exchanges."""
    payload: dict[str, Any] = {
        "briefing": [
            {
                "type": "read_along",
                "cn_prompt": "跟读这句开场。",
                "ref_text": "Our team is ready for the client update.",
                "translation_cn": "我们团队准备好客户汇报了。",
                "accept_notes": "team 重读, 语速平稳。",
            },
            {
                "type": "retell",
                "cn_prompt": "用自己的话复述材料。",
                "ref_text": "The schedule is tight. The client wants the plan on Monday.",
                "translation_cn": "时间很紧, 客户要周一看到计划。",
                "reference_answer": "Tight schedule; the client wants the plan on Monday.",
                "accept_notes": "说出 tight schedule 与 Monday。",
            },
            {
                "type": "translate",
                "cn_prompt": "说成英文：目标很清楚。",  # noqa: RUF001
                "ref_text": "目标很清楚。",
                "reference_answer": "The goal is clear.",
                "accept_notes": "goal is clear 即可。",
            },
            {
                "type": "make_sentence",
                "cn_prompt": "用 update 说一句你要做的事。",
                "target_word": "update",
                "reference_answer": "I'll send the update today.",
                "accept_notes": "含 update 并说出动作。",
            },
        ],
        "exchanges": [
            {
                "a": "Hi everyone, shall we kick off the project?",
                "b": "Sure, let's start. The team agrees with the goal.",
                "a_cn": "大家好, 我们开始项目吧?",
                "b_cn": "好, 开始吧。团队都认同这个目标。",
            },
            {
                "a": "Great. What does the schedule look like?",
                "b": "The plan takes two weeks.",
                "a_cn": "好。时间安排是怎样的?",
                "b_cn": "计划要两周。",
            },
            {
                "a": "And what about the client update?",
                "b": "I'll send the update today.",
                "a_cn": "客户的汇报呢?",
                "b_cn": "我今天发出去。",
            },
            {
                "a": "Any risks I should know about?",
                "b": "The schedule is tight, but the goal is clear.",
                "a_cn": "有什么风险吗?",
                "b_cn": "时间紧, 但目标清楚。",
            },
            {
                "a": "Good. Then let's begin today.",
                "b": "Thank you. See you at the meeting.",
                "a_cn": "好, 那今天开始。",
                "b_cn": "谢谢, 会上见。",
            },
        ],
    }
    payload.update(over)
    return json.dumps(payload, ensure_ascii=False)


# ============================================================ happy path


@pytest.mark.asyncio
async def test_generate_two_stage_happy_path(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_llm(monkeypatch, [skeleton_json(), detail_json()])

    res = await _generate(client)
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["polling_url"] == f"/api/v1/scenes/jobs/{body['job_id']}"

    await course_generator.run_generation_job(str(body["job_id"]))

    job = await _job(client, str(body["job_id"]))
    assert job.status_code == 200, job.text
    view = job.json()
    assert view["status"] == "ready" and view["progress"] == 1.0
    assert view["stage_text"] == "生成完成"
    assert view["scene_id"] and view["error"] is None

    # 恰好两段 = 两次 LLM 调用, 模型恒服务端默认, goal_text 传进段1
    assert len(fake.requests) == 2
    assert fake.requests[0]["model"] == "qwen3.8-max"
    assert "项目会议" in str(fake.requests[0]["messages"][1]["content"])

    rows = await _course_rows(db, DEV)
    assert len(rows) == 1
    course_row = rows[0]
    assert course_row.status == "ready"
    doc = dict(course_row.doc)
    assert doc["source"] == "generated" and doc["id"] == view["scene_id"]
    assert len(doc["briefing"]) == 4 and len(doc["mission"]["exchanges"]) == 5
    assert doc["mission"]["tasks"][0]["id"] == "t1"  # 任务 id 统一重编号

    # 详情/剧本经 DB 读 (带归属); 生成课也进画廊
    detail = await client.get(f"/api/v1/scenes/{view['scene_id']}", params={"device_id": DEV})
    assert detail.status_code == 200
    assert detail.json()["source"] == "generated"
    script = await client.get(
        f"/api/v1/scenes/{view['scene_id']}/script", params={"device_id": DEV}
    )
    assert script.status_code == 200
    roles = script.json()["roles"]
    assert [len(r["lines"]) for r in roles] == [5, 5]

    page = (await client.get("/api/v1/scenes", params={"device_id": DEV})).json()
    assert view["scene_id"] in [s["id"] for s in page["scenes"]]


# ============================================================ 失败语义


@pytest.mark.asyncio
async def test_bad_json_retries_once_then_fails(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, ["这绝对不是 JSON", "还是不是 JSON 对象"])
    res = await _generate(client)
    job_id = str(res.json()["job_id"])
    await course_generator.run_generation_job(job_id)

    view = (await _job(client, job_id)).json()
    assert view["status"] == "failed"
    assert view["error"] and "不可用" in str(view["error"])
    assert view["scene_id"] is None
    assert await _course_rows(db, DEV) == []  # 失败不留半成品课


@pytest.mark.asyncio
async def test_validation_retry_succeeds_on_second_call(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """段1 第一把坏 (category 非法), 校验错误回喂后第二把好 -> 仍然 ready."""
    bad = skeleton_json(category="nope")
    fake = install_llm(monkeypatch, [bad, skeleton_json(), detail_json()])
    res = await _generate(client)
    job_id = str(res.json()["job_id"])
    await course_generator.run_generation_job(job_id)
    assert (await _job(client, job_id)).json()["status"] == "ready"
    assert len(fake.requests) == 3
    retry_user = str(fake.requests[1]["messages"][-1]["content"])
    assert "category" in retry_user and "不合格" in retry_user


@pytest.mark.asyncio
async def test_whole_course_validation_failure_fails_job(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两段各自合法但拼不成整课 (跟读缺 ref_text) -> job=failed + 明确原因."""
    briefing = json.loads(detail_json())["briefing"]
    briefing[0]["ref_text"] = ""  # BriefingStepDraft 放行, SceneCourse 整课把关才拦下
    bad_detail = json.dumps(
        {"briefing": briefing, "exchanges": json.loads(detail_json())["exchanges"]},
        ensure_ascii=False,
    )
    install_llm(monkeypatch, [skeleton_json(), bad_detail])
    res = await _generate(client)
    job_id = str(res.json()["job_id"])
    await course_generator.run_generation_job(job_id)
    view = (await _job(client, job_id)).json()
    assert view["status"] == "failed"
    assert "整课内容校验未通过" in str(view["error"])


@pytest.mark.asyncio
async def test_llm_unconfigured_fails_honestly(client: AsyncClient) -> None:
    """无凭据 (CI 默认) -> job=failed + 失败原因, 轮询端看得到终态."""
    assert get_llm_provider().is_configured is False
    res = await _generate(client)
    job_id = str(res.json()["job_id"])
    await course_generator.run_generation_job(job_id)
    view = (await _job(client, job_id)).json()
    assert view["status"] == "failed"
    assert "LLM" in str(view["error"])


# ============================================================ upsert / 校验门


@pytest.mark.asyncio
async def test_same_goal_regenerates_in_place(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两轮完整生成 (各自 skeleton+detail) -> 同 (user, goal) 覆盖且旧 id 复用."""
    install_llm(
        monkeypatch,
        [skeleton_json(), detail_json(), skeleton_json(), detail_json()],
    )
    first = await _generate(client)
    await course_generator.run_generation_job(str(first.json()["job_id"]))
    old_id = str((await _job(client, str(first.json()["job_id"]))).json()["scene_id"])
    assert old_id

    second = await _generate(client)  # 同一个目标
    await course_generator.run_generation_job(str(second.json()["job_id"]))
    assert (await _job(client, str(second.json()["job_id"]))).json()["status"] == "ready"

    rows = await _course_rows(db, DEV)
    assert len(rows) == 1  # 同 (user, goal) 覆盖, 不堆行
    assert rows[0].doc["id"] == old_id  # 旧 id 复用 (进度/历史不断链)


def test_skeleton_field_validation_rejects_bad_level_and_skills() -> None:
    """level/skills 的字段校验在段1就把非法值挡下 (回喂重试的原料)."""
    from pydantic import ValidationError

    from app.services.course_generator import SkeletonCourse

    base = json.loads(skeleton_json())
    with pytest.raises(ValidationError, match="level"):
        SkeletonCourse.model_validate({**base, "level": "Z9"})
    with pytest.raises(ValidationError, match="skills"):
        SkeletonCourse.model_validate({**base, "skills": ["grammar", "grammar"]})


@pytest.mark.asyncio
async def test_runner_ignores_unknown_and_finished_jobs(db: AsyncSession) -> None:
    """runner 对不存在的 job 是 no-op; ``_fail`` 对查无此 job 同样安全返回."""
    from sqlalchemy import func, select

    from app.models.db import GenerationJob, SceneCourseRow
    from app.services.course_generator import _fail

    await course_generator.run_generation_job("no-such-job")  # 不抛
    await _fail(db, "no-such-job", "x")  # 不抛
    assert (await db.execute(select(func.count()).select_from(SceneCourseRow))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(GenerationJob))).scalar_one() == 0


@pytest.mark.asyncio
async def test_generate_input_validation(client: AsyncClient) -> None:
    assert (await _generate(client, goal_text="短")).status_code == 422
    res = await _generate(client, category="nope")
    assert res.status_code == 400 and res.json()["error"]["code"] == "INVALID_CATEGORY"
    res = await _generate(client, level="Z9")
    assert res.status_code == 400 and res.json()["error"]["code"] == "INVALID_LEVEL"


@pytest.mark.asyncio
async def test_jobs_ownership_isolation(client: AsyncClient) -> None:
    res = await _generate(client)
    job_id = str(res.json()["job_id"])
    assert (await _job(client, job_id, device=OTHER)).status_code == 403
    assert (await _job(client, job_id, device=None)).status_code == 400  # 没身份
    assert (await _job(client, "no-such-job")).status_code == 404


@pytest.mark.asyncio
async def test_prompt_carries_t2_hard_constraints(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T2 教训的硬约束必须写死在 system prompt 里 (防回归删减)."""
    fake = install_llm(monkeypatch, [skeleton_json(), detail_json()])
    res = await _generate(client)
    await course_generator.run_generation_job(str(res.json()["job_id"]))
    stage1 = str(fake.requests[0]["messages"][0]["content"])
    stage2 = str(fake.requests[1]["messages"][0]["content"])
    assert "14 个英文单词" in stage2  # 学员行 ≤14 词 (段2: 剧本)
    assert "一个" in stage1 and "可听判定目标" in stage1  # 任务单一判定目标 (段1: 任务清单)
    assert "接住" in stage2  # b 行接住 a 行
    assert "真出现在" in stage2  # 词汇必须真出现在对话里
    assert "只输出一个 JSON" in stage1 and "只输出一个 JSON" in stage2
    assert _resolve_judge_model() == "qwen3.8-max"


@pytest.mark.asyncio
async def test_spawn_job_schedules_background_task() -> None:
    """spawn_job 真身: create_task 跑 runner (对不存在的 job 是 no-op) 并自清理."""
    import asyncio

    await asyncio.sleep(0)
    ORIGINAL_SPAWN("no-such-job")  # autouse 夹具把模块属性换成 no-op, 这里用导入期原身
    pending = list(course_generator._JOBS)
    assert pending
    await asyncio.gather(*pending, return_exceptions=True)  # runner 需要真实 I/O 轮次
    assert all(task.done() for task in pending)
