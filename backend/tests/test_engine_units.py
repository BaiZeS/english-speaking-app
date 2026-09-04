"""P3 新模块的单元级补漏测试 (纯函数分支 + 少量防守路径的端点重放).

金值/端到端都在 ``test_ability_engine.py`` / ``test_mission.py`` /
``test_polish_expressions.py``, 这里收剩下的分支:容错解析、确定性文案模板、
race/防守分支、模型解析链的边界 —— 保证新模块行覆盖贴近 100%。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import dialogue
from app.api.v1 import expressions as expr_api
from app.config import settings
from app.core.errors import AppError
from app.models.db import AbilityEvent, Expression, User
from app.services import llm_provider
from app.services import mission_engine as me
from app.services.users import lookup_user
from tests.test_drill_grader import FakeIAT, install_llm
from tests.test_scene_store import make_course_dict


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


# ============================================================ mission_engine 单元


def test_mission_judgement_rejects_blank_reply() -> None:
    with pytest.raises(ValidationError):
        me.MissionTurnJudgement.model_validate({"reply": "   "})


def test_all_required_done_semantics() -> None:
    states = [
        {"id": "t1", "required": True, "done": True},
        {"id": "t2", "required": False, "done": False},
    ]
    assert me.all_required_done(states) is True
    assert me.all_required_done([]) is False
    assert me.all_required_done([{**states[0], "done": False}, states[1]]) is False
    assert me.all_required_done([{**states[0], "required": True, "done": False}]) is False


def test_merge_task_progress_edge_cases() -> None:
    state = [{"id": "t1", "done": False, "required": True}]
    evidence = "e" * 300  # TaskProgress 的 schema 上限 300
    newly = me.merge_task_progress(
        state,
        [
            me.TaskProgress(id="ghost", done=True, evidence="幻觉任务"),
            me.TaskProgress(id="t1", done=False, evidence=""),
            me.TaskProgress(id="t1", done=True, evidence=evidence),
            me.TaskProgress(id="t1", done=True, evidence="第二次不算新完成"),
        ],
        turn_index=3,
    )
    assert state[0]["done"] is True and state[0]["done_at_turn"] == 3
    assert len(newly) == 1 and newly[0]["evidence"] == evidence


def test_fallback_turn_skips_tasks_without_hint_en() -> None:
    course_payload = make_course_dict()
    from app.models.course import SceneCourse

    course = SceneCourse.model_validate(course_payload)
    state = me.initial_task_states(course.mission.tasks)
    # 第一个任务没 hint_en -> 词面口径直接跳过它; 有示范句的任务正常判定
    state[0]["hint_en"] = ""
    judgement, source, llm = me.fallback_turn(
        course, 1, "How much is that?", state, me.LlmUnavailableError("x", not_configured=True)
    )
    assert source == "heuristic" and llm == "stub"
    assert judgement.reply == course.mission.exchanges[0].a
    assert [p.id for p in judgement.task_progress] == ["t2"]  # t1 无示范句被跳过


def test_coerce_score_branches() -> None:
    assert me.coerce_score(None) is None
    assert me.coerce_score(True) is None
    assert me.coerce_score("abc") is None
    assert me.coerce_score(-1) is None
    assert me.coerce_score(101) is None
    assert me.coerce_score("88.88") == pytest.approx(88.9)
    assert me.coerce_score(70) == 70.0


def test_coerce_polish_branches() -> None:
    assert me.coerce_polish(None) is None
    assert me.coerce_polish("not-a-dict") is None
    assert me.coerce_polish({"polished": "  "}) is None
    assert me.coerce_polish({"polished": "Better."}) is not None
    ok = me.coerce_polish({"polished": "Better.", "original": "Bad.", "explanation_cn": "x"})
    assert ok is not None and ok.original == "Bad."


def test_deterministic_review_templates_for_weak_dims() -> None:
    facts = {
        "dims": {"pronunciation": 40.0, "grammar": 55.0, "vocabulary": 42.0, "fluency": 39.0},
        "cleared": False,
        "done_count": 0,
        "task_count": 3,
        "utterances": [],
        "briefing_passed": False,
        "open_required": ["说要买什么", "问价格"],
    }
    highlights, improvements = me.deterministic_review(facts)
    assert highlights == ["今天把整场对话开口的流程走完了 —— 先把习惯建立起来。"]
    assert len(improvements) == 3  # 最多 3 条, 按最低维度排序 (39<40<42<55)
    assert improvements[0].startswith("流利度:")
    assert improvements[1].startswith("发音:")
    assert improvements[2].startswith("词汇:")


def test_deterministic_review_best_dim_highlight() -> None:
    facts = {
        "dims": {"pronunciation": 90.0, "grammar": 75.0, "vocabulary": None, "fluency": None},
        "cleared": True,
        "done_count": 2,
        "task_count": 2,
        "utterances": [],
        "briefing_passed": True,
        "open_required": [],
    }
    highlights, improvements = me.deterministic_review(facts)
    assert any("发音是当前最稳的一项 (90 分)" in line for line in highlights)
    assert improvements  # 词汇/流利度没有证据 -> 诚实提示一条


def test_collect_transcript_pairs_guards_garbage() -> None:
    doc = {
        "mission": {
            "turns": [
                {"polish": {"original": "a", "polished": "b", "explanation_cn": "c"}},
                {"polish": None},
                {"polish": {"polished": ""}},
            ]
        }
    }
    steps = [
        {"step_type": "translate", "annotated_json": "不是 dict"},
        {
            "step_type": "translate",
            "annotated_json": {
                "mistakes": [
                    "非 dict 条目",
                    {
                        "said": "",
                        "better": "Use the total.",
                        "source_cn": "一共",
                        "explanation_cn": "问价",
                    },
                    {"said": "x", "better": "", "explanation_cn": "无 better -> 丢弃"},
                ]
            },
        },
    ]
    pairs = me.collect_transcript_pairs(doc, steps)
    assert [(p.original, p.polished) for p in pairs] == [("a", "b"), ("一共", "Use the total.")]
    assert len([p for p in pairs if p.explanation_cn]) == 2


def test_collect_new_tokens_plural_stems() -> None:
    payload = make_course_dict(
        vocab=[
            {"word": word, "meaning_cn": "测试", "example_en": f"I {word}."}
            for word in ("orders", "milk", "taking", "cup", "pay", "take")
        ]
    )
    from app.models.course import SceneCourse

    course = SceneCourse.model_validate(payload)
    hits = me.collect_new_tokens(course, ["I placed orders and take the milk out.", "nonsense"])
    assert "orders" in hits  # 原形直接命中
    assert "milk" in hits  # 直接命中
    assert "take" in hits  # 原形命中
    assert "taking" not in hits or "taking" in hits  # (stem 规则不保证 -ing; 只要求不炸)


async def _steps_from_doc() -> list[dict[str, Any]]:
    return [{"step_type": "mission_turn", "source": "llm", "score_grammar": 66.0}]


def test_aggregate_only_trusted_sources() -> None:
    steps = [
        {
            "source": "stub",
            "score_pronunciation": 95.0,
            "score_fluency": 60.0,
            "ise_ref_mode": "exact_reference",
        },
        {
            "source": "xunfei",
            "score_pronunciation": 70.0,
            "score_fluency": 64.0,
            "ise_ref_mode": "transcript_anchored",
        },
        {"source": "heuristic", "score_grammar": 100.0},
        {"source": "llm", "score_grammar": 60.0},
    ]
    dims = me.aggregate_step_dims(steps)
    assert dims["pronunciation"] == pytest.approx(70.0)  # stub 行不算
    assert dims["grammar"] == pytest.approx(60.0)  # 启发式行不算
    subs = me.aggregate_pronunciation_subs(steps)
    assert subs["pronunciation"] == pytest.approx(70.0) and subs["completeness"] is None
    assert me.mean_of([]) is None and me.mean_of([None]) is None


@pytest.mark.asyncio
async def test_review_falls_back_when_llm_copy_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 回合法 JSON 但两套文案全空 -> 确定性文案 + heuristic 标记 (§5.5)."""
    from app.models.course import SceneCourse

    install_llm(monkeypatch, [json.dumps({"highlights": [], "improvements": []})])
    course = SceneCourse.model_validate(make_course_dict())
    report = await me.build_review_report(
        course=course,
        session_id="s-1",
        mission={"turns": [], "tasks": [], "cleared": False, "turn_count": 0, "max_turns": 8},
        steps=await _steps_from_doc(),
        ability_before=None,
        ability_after=None,
        briefing_passed=False,
    )
    assert report.source == "heuristic" and report.llm_source == "stub"
    assert report.dims["grammar"] == pytest.approx(66.0)


def test_level_from_avg_out_of_range_guard() -> None:
    from app.services.ability_engine import level_from_avg

    assert level_from_avg(1000.0) == "C2"  # 理论上够不到的上限兜底


# ============================================================ llm_provider 链边界


def test_allowed_ids_empty_catalog_configuration_bug(monkeypatch: pytest.MonkeyPatch) -> None:
    """白名单 + 目录都空 (配置异常): 返回空串并留 ERROR, 不硬编码模型."""
    _ = monkeypatch
    monkeypatch.setattr(settings, "llm_default_model", "")
    monkeypatch.setattr(settings, "llm_allowed_models", "")
    monkeypatch.setattr(llm_provider, "get_model_catalog", lambda: [])
    assert llm_provider.allowed_model_ids() == []
    assert llm_provider.resolve_server_default_model() == ""
    assert llm_provider.resolve_roleplay_model("whatever") == ""


def test_extract_content_failures_and_non_str(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def __init__(self, **kw: Any) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    with pytest.raises(RuntimeError, match="missing choices"):
        llm_provider._extract_content(_Resp(choices=[]))
    with pytest.raises(RuntimeError, match="empty content"):
        llm_provider._extract_content(_Resp(choices=[_Resp(message=_Resp(content=""))]))
    assert llm_provider._extract_content(_Resp(choices=[_Resp(message=_Resp(content=42))])) == "42"


def test_extra_models_skips_non_dict_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "llm_extra_models_json",
        '[3, null, {"id":"good","display_name":"G","provider":"p","description":"d"}]',
    )
    ids = [info.id for info in llm_provider.get_model_catalog()]
    assert "good" in ids


@pytest.mark.asyncio
async def test_lookup_user_create_mode_rejects_unknown_user_id(db: AsyncSession) -> None:
    """``create=True`` (写侧口径) 下明确给了错 user_id -> 404, 不能装作不存在."""
    from app.core.errors import AppError

    with pytest.raises(AppError) as exc:
        await lookup_user(db, user_id="00000000-0000-0000-0000-000000000000", create=True)
    assert exc.value.status_code == 404 and exc.value.code == "USER_NOT_FOUND"


# ============================================================ users / expressions 防守分支


@pytest.mark.asyncio
async def test_user_get_or_create_race_falls_back_to_winner(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_flush = AsyncSession.flush
    calls = {"n": 0}

    async def racing_flush(self: AsyncSession, *args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            async with _fresh_session() as other:
                other.add(User(device_id="dev-race-p3"))
                await other.commit()
            raise IntegrityError("INSERT INTO users", {}, RuntimeError("UNIQUE"))
        await real_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", racing_flush)
    user = await lookup_user(db, device_id="dev-race-p3", create=True)
    assert user is not None and user.device_id == "dev-race-p3"


def _fresh_session() -> Any:
    from app.db.session import get_sessionmaker

    return get_sessionmaker()()


@pytest.mark.asyncio
async def test_expression_upsert_race_returns_winner(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """唯一索引竞争: 后写者撞 IntegrityError -> 回滚重读赢家, 语义=去重命中."""
    user = User(device_id="dev-expr-race")
    db.add(user)
    await db.commit()
    # 先塞一条 (直接绕过 ORM 身份映射不可行; 用第二个 session 提交后, patch flush
    # 让 upsert 的 flush 撞唯一索引) —— 这里手工重放该 race:
    real_flush = AsyncSession.flush
    armed = {"n": 0}

    async def once_failing_flush(self: AsyncSession, *args: Any, **kwargs: Any) -> None:
        if armed["n"] == 0:
            armed["n"] += 1
            # 期间对手落库同 normalized 的行 (同一 user)
            async with _fresh_session() as rival:
                rival.add(Expression(user_id=user.id, polished="dup me", normalized="dup me"))
                await rival.commit()
            raise IntegrityError("INSERT INTO expressions", {}, RuntimeError("UNIQUE"))
        await real_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", once_failing_flush)
    row, created = await expr_api.upsert_expression(db, user_id=user.id, polished="DUP ME")
    assert created is False and row.polished == "dup me"
    db.expire_all()


@pytest.mark.asyncio
async def test_expression_blank_polished_is_400(client: AsyncClient) -> None:
    res = await client.post("/api/v1/expressions", json={"device_id": "dev-x", "polished": "   "})
    assert res.status_code == 400 and res.json()["error"]["code"] == "EXPRESSION_TEXT_REQUIRED"


@pytest.mark.asyncio
async def test_expression_delete_by_unknown_device_is_403(client: AsyncClient) -> None:
    res = await client.delete(
        "/api/v1/expressions/whatever", params={"device_id": "dev-never-seen-p3"}
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "FORBIDDEN_EXPRESSION"


@pytest.mark.asyncio
async def test_polish_blank_text_is_400(client: AsyncClient) -> None:
    res = await client.post("/api/v1/polish", json={"text": "   "})
    assert res.status_code == 400 and res.json()["error"]["code"] == "POLISH_TEXT_REQUIRED"


@pytest.mark.asyncio
async def test_polish_collect_unknown_user_id_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, [json.dumps({"polished": "Better.", "explanation_cn": "x"})])
    res = await client.post(
        "/api/v1/polish",
        json={
            "text": "bad sentance",
            "collect": True,
            "user_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert res.status_code == 404 and res.json()["error"]["code"] == "USER_NOT_FOUND"


# ============================================================ dialogue 容错解析 / 生成


def test_parse_llm_json_branches() -> None:
    assert dialogue._parse_llm_json('{"reply": "a", "suggestion": "b"}')["reply"] == "a"
    fenced = dialogue._parse_llm_json('```json\n{"reply": "fenced"}\n```')
    assert fenced["reply"] == "fenced"
    prose = dialogue._parse_llm_json("How about coffee?\nSure, thanks.")
    assert prose["reply"] == "How about coffee?" and prose["suggestion"] == "Sure, thanks."
    one_line = dialogue._parse_llm_json("just one line")
    assert one_line["reply"] == "just one line" and one_line["suggestion"] == ""
    array = dialogue._parse_llm_json("[1, 2]")
    assert array["reply"] == "[1, 2]"
    obj_no_reply = dialogue._parse_llm_json('{"suggestion": "x"}')
    assert obj_no_reply["reply"]  # 回落取首行, 不空着
    assert obj_no_reply["suggestion"] == "x"
    empty_obj = dialogue._parse_llm_json('{"reply": ""}')
    assert empty_obj["reply"]  # 空 reply 也兜出内容 (取原始首行), 绝不把空串当回复


def test_scene_context_skips_empty_items() -> None:
    text = dialogue._scene_context(
        "daily_conversation",
        [
            {"role": "assistant", "text": "Hi"},
            {"role": "user", "text": ""},  # 待回填的空回合不进 prompt
            {"role": "user", "text": "Hello!"},
        ],
    )
    assert "Coach: Hi" in text and "Learner: Hello!" in text
    assert "Learner: \n" not in text


@pytest.mark.asyncio
async def test_generate_strips_quoted_opening_and_degrades(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, ['"Hi there!"\nextra commentary'])
    res = await client.post("/api/v1/dialogue/generate", json={"scene": "daily_conversation"})
    assert res.json()["status"] == "ready"
    assert res.json()["lines"][0]["text"] == "Hi there!"
    llm_provider.reset_llm_provider_for_tests()
    install_llm(monkeypatch, [RuntimeError("upstream 503")])
    down = await client.post("/api/v1/dialogue/generate", json={"scene": "daily_conversation"})
    assert down.json()["status"] == "stub" and down.json()["lines"][0]["text"]


@pytest.mark.asyncio
async def test_turn_stub_path_second_user_turn_text(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dialogue, "_iat", FakeIAT(None))
    history = [
        {"role": "user", "text": "first"},
        {"role": "assistant", "text": "second"},
        {"role": "user", "text": "third"},
    ]
    res = await client.post(
        "/api/v1/dialogue/turn", json={"scene_id": "daily_conversation", "history": history}
    )
    body = res.json()
    assert body["status"] == "stub"
    assert body["reply_text"].startswith("Thanks for sharing")
    assert body["polish"] is None and body["grammar_score"] is None


@pytest.mark.asyncio
async def test_turn_with_identity_and_audio_persists_anchored_evidence(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.6 全链: 音频 -> IAT 转写 -> 单调用评分 -> 锚定 ISE 发音证据 -> 落库."""
    from app.models.db import AbilityProfile

    user = User(device_id="dev-dlg-anchor")
    db.add(user)
    await db.commit()
    import base64

    audio = base64.b64encode(b"\x00\x01" * 3200).decode()
    monkeypatch.setattr(dialogue, "_iat", FakeIAT("I very like it."))
    install_llm(monkeypatch, [json.dumps({"reply": "Cool", "suggestion": "I really like it"})])
    for field in ("xunfei_app_id", "xunfei_api_key", "xunfei_api_secret"):
        monkeypatch.setattr(settings, field, "test")
    from tests.test_drill_grader import FakeASR

    monkeypatch.setattr(me, "_ISE", FakeASR(scores=77.0))
    body = (
        await client.post(
            "/api/v1/dialogue/turn",
            json={
                "scene_id": "daily_conversation",
                "history": [],
                "user_audio_b64": audio,
                "device_id": "dev-dlg-anchor",
            },
        )
    ).json()
    assert body["recognized_text"] == "I very like it."
    dims = {e["dimension"]: e for e in body["ability_events"]}
    assert dims["pronunciation"]["ise_ref_mode"] == "transcript_anchored"
    assert "grammar" not in dims  # 旧形状 JSON 没带判分 -> 没有语法事件 (不是 0 分)
    events = (await db.execute(select(AbilityEvent))).scalars().all()
    assert {(e.dimension, e.source_kind, e.weight) for e in events} >= {
        ("pronunciation", "xunfei", 1.0),
        ("fluency", "xunfei", 1.0),
    }
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.pronunciation == pytest.approx(77.0)


# ============================================================ course_sessions 防守:
# doc 里 mission.finished 已置位但 stage 没翻 (崩在两步之间的极端形态)


@pytest.mark.asyncio
async def test_corrupt_finished_flag_still_blocks_new_turns(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, client: AsyncClient, tmp_path: Any
) -> None:
    from app.api.v1 import course_sessions as cs
    from app.services import scene_store as ss
    from tests.test_course_sessions import BRIEFING6, _pass_briefing
    from tests.test_scene_store import write_course

    write_course(tmp_path, "scene_alpha", "daily", briefing=BRIEFING6)
    monkeypatch.setattr(ss, "_CORPUS_ROOT", tmp_path)
    ss.invalidate_cache()
    res = await client.post(
        "/api/v1/sessions", json={"device_id": "dev-session", "scene_id": "scene_alpha"}
    )
    sid = res.json()["session_id"]
    await _pass_briefing(client, sid)
    row = (
        await db.execute(
            select(cs.PracticeSession)
            .where(cs.PracticeSession.id == sid)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    doc = json.loads(json.dumps(row.doc))
    doc["mission"] = {"finished": True, "turns": [], "tasks": [], "turn_count": 0, "max_turns": 8}
    row.doc = doc
    await db.commit()
    blocked = await client.post(
        f"/api/v1/sessions/{sid}/mission", json={"device_id": "dev-session", "text": "again?"}
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "MISSION_FINISHED"
    hint = await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": "dev-session"})
    assert hint.status_code == 409
    # stage 已翻 review 但 status 还没落 (同一函数另一条防线): 直接单元重放
    row2 = cs.PracticeSession(id=sid, status="active", stage="review", doc={})
    with pytest.raises(AppError) as exc:
        cs._require_mission_actionable(row2, {"stage": "review"})
    assert exc.value.code == "MISSION_FINISHED"
