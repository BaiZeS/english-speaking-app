"""``POST /polish`` 与 ``/expressions`` CRUD 测试 (§5.7, 阶段 P3).

覆盖:

* 无凭据 (本机等价): ``polish`` 必须 ``null`` + ``source=stub`` + 中文说明 ——
  **不编造占位句子** (与发音维度"没有凭据就没有证据"同一纪律);
* mock LLM: 正常对照 / "句子本来没问题" -> 也是 ``null`` (但 ``source=llm``);
* ``collect=true`` 收藏进表达库 (去重命中返回既有条目); 没身份时诚实不收藏;
* 表达库 GET/POST/DELETE 全链路 + normalized 去重 (大小写/标点不敏感) +
  归属隔离 (别人的条目 403, 不存在的 404);
* ``/polish`` 是人设/文本用途: 客户端 ``model_id`` 在白名单内被跟随 (§5.7)。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnnotatedDiff, Expression, User
from app.services import llm_provider
from tests.test_drill_grader import install_llm

DEV = "dev-polish"


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


# ============================================================ /polish


@pytest.mark.asyncio
async def test_polish_without_creds_is_honest_null(client: AsyncClient) -> None:
    res = await client.post("/api/v1/polish", json={"text": "He go to meeting yesterday."})
    assert res.status_code == 200
    body = res.json()
    assert body["polish"] is None
    assert body["source"] == "stub" and body["llm_source"] == "stub"
    assert "LLM 未配置" in body["note_cn"]


@pytest.mark.asyncio
async def test_polish_returns_original_vs_polished_with_explanation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_llm(
        monkeypatch,
        [
            json.dumps(
                {
                    "polished": "He went to the meeting yesterday.",
                    "explanation_cn": "过去时 went, 且 meeting 前要加 the。",
                },
                ensure_ascii=False,
            )
        ],
    )
    res = await client.post("/api/v1/polish", json={"text": "He go to meeting yesterday."})
    body = res.json()
    assert body["polish"] == {
        "original": "He go to meeting yesterday.",
        "polished": "He went to the meeting yesterday.",
        "explanation_cn": "过去时 went, 且 meeting 前要加 the。",
    }
    assert body["source"] == "llm" and body["llm_source"] == "qwen3.8-max"
    assert fake.requests[0]["model"] == "qwen3.8-max"  # 未给 model_id -> 服务端默认


@pytest.mark.asyncio
async def test_polish_reports_null_when_the_sentence_is_fine(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, [json.dumps({"polished": "", "explanation_cn": ""})])
    body = (await client.post("/api/v1/polish", json={"text": "A coffee, please."})).json()
    assert body["polish"] is None and body["source"] == "llm"
    assert "没有值得改" in body["note_cn"]


@pytest.mark.asyncio
async def test_polish_bad_json_retries_once_then_marks_stub(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_llm(monkeypatch, ["garbage", "still garbage"])
    body = (await client.post("/api/v1/polish", json={"text": "I very like it."})).json()
    assert len(fake.requests) == 2  # 重试一次, 不做第三次
    assert body["polish"] is None and body["source"] == "heuristic"
    assert body["llm_source"] == "stub"


@pytest.mark.asyncio
async def test_polish_honors_allowlisted_model_id_for_text(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "llm_allowed_models", "qwen-turbo")
    # 注意: ``install_llm`` 会把 default 设为 qwen3.8-max —— 白名单只约束客户端

    fake = install_llm(monkeypatch, [json.dumps({"polished": "Better.", "explanation_cn": "x"})])
    ok = (
        await client.post(
            "/api/v1/polish", json={"text": "bad sentance.", "model_id": "qwen-turbo"}
        )
    ).json()
    assert ok["llm_source"] == "qwen-turbo" and fake.requests[-1]["model"] == "qwen-turbo"
    off = (
        await client.post("/api/v1/polish", json={"text": "bad sentance.", "model_id": "gpt-99"})
    ).json()
    assert off["llm_source"] == "qwen3.8-max"  # 白名单外 -> 回落服务端默认, 不照单全收


@pytest.mark.asyncio
async def test_polish_collect_creates_and_dedupes_expression(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    replies = [
        json.dumps(
            {"polished": "How much is that in total?", "explanation_cn": "问总价的说法。"},
            ensure_ascii=False,
        )
    ]
    install_llm(monkeypatch, list(replies))
    first = (
        await client.post(
            "/api/v1/polish",
            json={
                "text": "How much money total?",
                "device_id": DEV,
                "collect": True,
                "scene_id": "scene_alpha",
            },
        )
    ).json()
    assert first["expression_id"] and "收藏" in first["note_cn"]
    rows1 = (await db.execute(select(Expression))).scalars().all()
    assert (
        len(rows1) == 1 and rows1[0].source_label == "polish" and rows1[0].scene_id == "scene_alpha"
    )
    # 再润一次同一句 + collect: 去重命中, 不产生第二行
    res_again = await client.post(
        "/api/v1/polish", json={"text": "How much is total?", "device_id": DEV, "collect": True}
    )
    second = res_again.json()
    assert second["expression_id"] == first["expression_id"]
    rows2 = (await db.execute(select(Expression))).scalars().all()
    assert len(rows2) == 1


@pytest.mark.asyncio
async def test_polish_collect_without_identity_is_silent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    install_llm(monkeypatch, [json.dumps({"polished": "Nice.", "explanation_cn": "ok"})])
    body = (
        await client.post("/api/v1/polish", json={"text": "I very like it.", "collect": True})
    ).json()
    assert body["polish"] is not None and body["expression_id"] is None
    assert "未给身份" in body["note_cn"]
    assert (await db.execute(select(Expression))).scalars().all() == []


@pytest.mark.asyncio
async def test_polish_requires_text(client: AsyncClient) -> None:
    short = await client.post("/api/v1/polish", json={"text": ""})
    assert short.status_code == 422  # pydantic min_length 挡住, 不进 LLM 分支


# ============================================================ /expressions


async def _seed_user(db: AsyncSession, device: str) -> User:
    user = User(device_id=device)
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_expression_crud_roundtrip_with_dedupe(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_user(db, DEV)
    created = await client.post(
        "/api/v1/expressions",
        json={
            "device_id": DEV,
            "polished": "Could I get the check, please?",
            "original": "Give me money bill.",
            "explanation_cn": "买单说 could I get the check。",
            "source_label": "manual",
            "scene_id": "scene_alpha",
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["created"] is True
    expression_id = payload["expression"]["id"]
    assert payload["expression"]["source_label"] == "manual"

    dup = await client.post(
        "/api/v1/expressions",
        json={"device_id": DEV, "polished": " COULD I GET THE CHECK PLEASE?!  "},
    )
    assert dup.status_code == 200  # 归一化 (大小写/标点/空白) 命中既有条目
    assert dup.json()["created"] is False
    assert dup.json()["expression"]["id"] == expression_id

    items = (await client.get("/api/v1/expressions", params={"device_id": DEV})).json()
    assert len(items) == 1 and items[0]["id"] == expression_id
    assert items[0]["created_at"].endswith("+00:00")

    deleted = await client.delete(f"/api/v1/expressions/{expression_id}", params={"device_id": DEV})
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/expressions", params={"device_id": DEV})).json() == []


@pytest.mark.asyncio
async def test_expression_isolation_and_errors(client: AsyncClient, db: AsyncSession) -> None:
    mine = await _seed_user(db, DEV)
    theirs = await _seed_user(db, "dev-other-polish")
    made = await client.post(
        "/api/v1/expressions",
        json={"user_id": theirs.id, "polished": "Their sentence.", "source_label": "dialogue"},
    )
    assert made.status_code == 201
    foreign_id = made.json()["expression"]["id"]
    # 用别人的 user_id 收藏是被允许的调用方错误防护之外的行 (API 信任 user_id),
    # 但用错身份去删必须 403; 拿不存在的 device 收藏则 404 (不悄悄注册).
    thief = await client.delete(f"/api/v1/expressions/{foreign_id}", params={"device_id": DEV})
    assert thief.status_code == 403 and thief.json()["error"]["code"] == "FORBIDDEN_EXPRESSION"
    ghost = await client.post(
        "/api/v1/expressions",
        json={"user_id": "00000000-0000-0000-0000-000000000000", "polished": "nobody"},
    )
    assert ghost.status_code == 404 and ghost.json()["error"]["code"] == "USER_NOT_FOUND"
    missing = await client.delete(
        "/api/v1/expressions/does-not-exist", params={"device_id": mine.device_id}
    )
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "EXPRESSION_NOT_FOUND"
    no_id = await client.get("/api/v1/expressions")
    assert no_id.status_code == 400 and no_id.json()["error"]["code"] == "IDENTITY_REQUIRED"
    # 陌生 device 列表为空 (不建用户), 但允许 200 (骨架渲染)
    stranger = await client.get("/api/v1/expressions", params={"device_id": "dev-stranger"})
    assert stranger.status_code == 200 and stranger.json() == []


@pytest.mark.asyncio
async def test_expression_created_by_device_id_registers_like_history(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST 收藏沿用 ``POST /history`` 口径: device_id 找不到用户时注册 (写侧)."""
    res = await client.post(
        "/api/v1/expressions",
        json={"device_id": "dev-fresh-polish", "polished": "Sounds good to me."},
    )
    assert res.status_code == 201
    users = (
        (await db.execute(select(User).where(User.device_id == "dev-fresh-polish"))).scalars().all()
    )
    assert len(users) == 1


@pytest.mark.asyncio
async def test_expression_normalizer_and_labels(client: AsyncClient, db: AsyncSession) -> None:
    from app.api.v1.expressions import normalize_text

    assert normalize_text("  Can-I  go?? ") == "can i go"  # 标点折成空格 (连字符写法不另起一条)
    assert normalize_text("It's fine.") == "it's fine"  # 撇号保留
    user = await _seed_user(db, "dev-norm")
    res = await client.post(
        "/api/v1/expressions",
        json={"user_id": user.id, "polished": "Hi there!", "source_label": "bogus-label"},
    )
    assert res.status_code == 201
    row = (await db.execute(select(Expression))).scalar_one()
    assert row.source_label == "manual"  # 未知标签收敛, 不炸
    assert row.normalized == "hi there"
    assert (await db.execute(select(AnnotatedDiff))).scalars().all() == []  # 收藏≠润色流水


@pytest.mark.asyncio
async def test_dialogue_turn_records_annotated_diff_only_when_polished(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    """自由对话轮出的润色对照也进 ``annotated_diffs`` (跨会话审计流, §5.2)."""
    user = await _seed_user(db, DEV)
    install_llm(
        monkeypatch,
        [
            json.dumps(
                {
                    "reply": "Nice!",
                    "suggestion": "s",
                    "polish": None,
                    "grammar_score": None,
                    "vocabulary_score": None,
                }
            )
        ],
    )
    await client.post(
        "/api/v1/dialogue/turn",
        json={"scene_id": "daily_conversation", "history": [], "user_id": user.id},
    )
    assert (await db.execute(select(AnnotatedDiff))).scalars().all() == []
