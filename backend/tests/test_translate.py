"""``POST /translate`` (T6): 双向翻译 + 失败不冒充成功.

钉三件事:

1. 两个方向都能翻, 且输出**只有译文**;
2. 翻不出来是 503, 不是空串、更不是把原文回显成"译文" —— 学员会把回显的原文当成
   "这句的英文说法"照着念, 那比报错伤得多;
3. 预算是 ``drill_grader.TRANSLATE_BUDGET_S`` 这个具名常量, 且真的传进了 ``_judge``
   (``test_latency_budget`` 的 AST 门点名它)。
"""

from __future__ import annotations

import inspect
import json

import pytest
from httpx import AsyncClient

from app.services import drill_grader as dg
from app.services import translate as service
from tests.test_drill_grader import install_llm


def translation_json(translated: str) -> str:
    return json.dumps({"translated": translated})


async def _post(client: AsyncClient, text: str, target: str):
    return await client.post("/api/v1/translate", json={"text": text, "target_lang": target})


@pytest.mark.asyncio
async def test_zh_to_en(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    install_llm(
        monkeypatch, replies=[translation_json("I'd like the beef noodles, no cilantro please.")]
    )
    resp = await _post(client, "我想要牛肉面, 汤里不要放香菜。", "en")
    assert resp.status_code == 200, resp.text
    assert resp.json()["translated"] == "I'd like the beef noodles, no cilantro please."
    assert resp.json()["source"] == "llm"


@pytest.mark.asyncio
async def test_en_to_zh(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    install_llm(monkeypatch, replies=[translation_json("麻烦给我一杯中杯燕麦奶拿铁。")])
    resp = await _post(client, "A medium oat milk latte, please.", "zh")
    assert resp.status_code == 200, resp.text
    assert "拿铁" in resp.json()["translated"]


@pytest.mark.asyncio
async def test_missing_credentials_is_503_not_an_echo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没配 LLM 凭据 -> 503. 不许把原文当译文回显 (那会被当成"这句英文这么说")."""
    from app.config import settings
    from app.services import llm_provider

    monkeypatch.setattr(settings, "llm_api_key", "")
    # provider 是缓存的单例: 不 reset 就会拿上一个用例装好的假客户端 (踩过, 症状是
    # "没配凭据却 200", 而且吐的是别的用例的罐头译文)。
    llm_provider.reset_llm_provider_for_tests()
    resp = await _post(client, "这句话翻不出来", "en")
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "TRANSLATION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_blank_output_is_503(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    install_llm(monkeypatch, replies=[translation_json("")])
    resp = await _post(client, "随便一句", "en")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "TRANSLATION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_english_target_returning_only_chinese_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型把原文当译文吐回来 = "看起来成功"的失败, 按不可用收口."""
    install_llm(monkeypatch, replies=[translation_json("我想要牛肉面")])
    resp = await _post(client, "我想要牛肉面", "en")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_chinese_target_without_any_hanzi_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, replies=[translation_json("I want noodles")])
    resp = await _post(client, "I want noodles", "zh")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_bad_target_and_blank_text_are_422(client: AsyncClient) -> None:
    assert (await _post(client, "hi", "fr")).status_code == 422
    assert (await _post(client, "   ", "en")).status_code == 422


def test_budget_is_a_named_constant_passed_into_judge() -> None:
    """AST 门只认调用点上的**具名常量**: 内联成字面量就等于把这条链放出去裸奔。"""
    assert dg.TRANSLATE_BUDGET_S == 6.0
    assert "hard_budget_s=TRANSLATE_BUDGET_S" in inspect.getsource(service.translate_text)


def test_prompt_demands_translation_only() -> None:
    msgs = service.translate_messages("你好", "en")
    assert "只翻" in msgs[0].content
    assert '{"translated": "..."}' in msgs[0].content
    assert msgs[1].content == "你好"
