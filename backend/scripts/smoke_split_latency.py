#!/usr/bin/env python3
"""实战/自由对话拆调用前的**真实时延冒烟** (只打 LLM, 不碰 DB, 证据只落 /tmp).

要回答的问题 (计划 §7 第 0 步): 一次调用吐 700 token 的综合 JSON 到底多慢, 拆成
「只出台词 + 双语」(~160 token) 与「只判分」(~450 token) 之后各自多慢 —— 预算数字
``GEN_LLM_TIMEOUT_S`` / ``GEN_TURN_BUDGET_S`` 必须由这里量出来的 p50/p95 定, 不能拍。

用法::

    cd backend && uv run python scripts/smoke_split_latency.py --runs 5
    cd backend && uv run python scripts/smoke_split_latency.py --runs 3 --modes combined,generate

输出: 每种模式的每次尝试耗时、成功/坏 JSON 次数、p50/p95, 以及 JSON 的实际长度。
凭证一律从 backend/.env 读 (与 deploy.sh 同款纪律: 先清掉 shell 里残留的同名环境变量),
**绝不**把 key 打进日志。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

for _line in (ROOT / ".env").read_text().splitlines():
    _key = _line.split("=", 1)[0].strip()
    if _key and not _key.startswith("#"):
        os.environ.pop(_key, None)

from app.config import settings  # noqa: E402
from app.services.llm_provider import LlmMessage, get_llm_provider  # noqa: E402

# ====== 三种模式的 prompt (贴近生产, 但用的是写死的样例对话) ======

_PERSONA = {
    "persona_cn": "项目经理 Dana",
    "user_role_cn": "项目组成员",
    "context_cn": "每周项目站会: 同步进度、抛出风险、确认下一步。",
    "level": "A2",
}

_TASKS = (
    "- [t1] 说明当前进度 (必做) | 示范: We have finished the first phase.\n"
    "- [t2] 说出主要风险 (必做) | 示范: The main risk is late vendor feedback.\n"
    "- [t3] 确认下一步与时间 (必做) | 示范: Let's review again on Thursday."
)

_TURNS = (
    ("We have finished the first phase, and we are on schedule.", "Great. What is the main risk right now?"),
    ("The main risk is late vendor feedback.", "Thanks. When do you expect an answer?"),
    ("I am not sure yet. Maybe Friday.", "Okay. Who will follow up with the vendor?"),
    ("I will ask Tom to call them today.", "Got it. Anything else for today?"),
    ("No, that is all for now.", "Thanks for the update. See you next week."),
)

_USER_TEXT = "We are plan to launch next friday but the vendor is late."

_COMBINED_SYSTEM = (
    "你是英语口语陪练「{persona}」。场景: {context}。学员扮演「{role}」, 中文母语 (CEFR {level})。"
    "只输出一个 JSON 对象。要求: (1) reply: 英文下一句 (1-2 句, 带一个追问); "
    "(2) suggestion: 学员下一句的示范英文; (3) polish: 学员这句有错就给 "
    "{{original, polished, explanation_cn}}, 否则 null; (4) grammar_score / "
    "vocabulary_score: 0-100; (5) task_progress: 重判全部任务 {{id, done, evidence}}。"
).format(
    persona=_PERSONA["persona_cn"],
    context=_PERSONA["context_cn"],
    role=_PERSONA["user_role_cn"],
    level=_PERSONA["level"],
)

_COMBINED_SHAPE = (
    '只输出 JSON: {"reply": "...", "suggestion": "...", '
    '"polish": {"original": "...", "polished": "...", "explanation_cn": "..."} | null, '
    '"grammar_score": number|null, "vocabulary_score": number|null, '
    '"task_progress": [{"id": "...", "done": true|false, "evidence": "..."}]}'
)

_GENERATE_SYSTEM = (
    "你是英语口语陪练「{persona}」。场景: {context}。学员扮演「{role}」, 中文母语 (CEFR {level})。"
    "只输出一个 JSON 对象。要求: (1) reply: 以 {persona} 身份用英文说下一句 (1-2 句, "
    "A2-B1, 必须推进议程且不重复已问过的); (2) reply_cn: reply 的简体中文意思; "
    "(3) suggestion: 学员下一句可直接开口的示范英文; (4) suggestion_cn: 它的简体中文意思; "
    "(5) learner_cn: 学员本轮那句英文的简体中文意思。"
).format(
    persona=_PERSONA["persona_cn"],
    context=_PERSONA["context_cn"],
    role=_PERSONA["user_role_cn"],
    level=_PERSONA["level"],
)

_GENERATE_SHAPE = (
    '只输出 JSON: {"reply": "...", "reply_cn": "...", "suggestion": "...", '
    '"suggestion_cn": "...", "learner_cn": "..."}。全部字段必填, 三个 *_cn 必须是简体中文。'
)

_GRADE_SYSTEM = (
    "你是英语口语评分器, 学员中文母语。只输出一个 JSON 对象。要求: "
    "(1) polish: 学员这句有语法/用词问题就给 {{original, polished, explanation_cn}} "
    "(original 必须是学员原话, explanation_cn 一句简体中文), 没有问题就输出 null; "
    "(2) grammar_score / vocabulary_score: 0-100, 必须有区分度; "
    "(3) task_progress: 重判下列任务至今是否达成 {{id, done, evidence}}。"
)

_GRADE_SHAPE = (
    '只输出 JSON: {"polish": {"original": "...", "polished": "...", "explanation_cn": "..."} '
    '| null, "grammar_score": number|null, "vocabulary_score": number|null, '
    '"task_progress": [{"id": "...", "done": true|false, "evidence": "..."}]}'
)


def _transcript_block() -> str:
    lines: list[str] = []
    for learner, coach in _TURNS:
        lines.append(f"Coach: {coach}")
        lines.append(f"Learner: {learner}")
    return "\n".join(lines)


def build_messages(mode: str) -> tuple[list[LlmMessage], int]:
    """三种模式的 prompt 与 max_tokens (与生产调用点一一对应)."""
    history = _transcript_block()
    if mode == "combined":
        user = (
            f"任务清单 (按学员说的话累积判定):\n{_TASKS}\n\n"
            f"已发生的对话 (Coach=你, Learner=学员):\n{history}\n\n"
            f"学员本轮说 (英文转写):\n{_USER_TEXT}\n\n{_COMBINED_SHAPE}"
        )
        messages = [
            LlmMessage(role="system", content=_COMBINED_SYSTEM),
            LlmMessage(role="user", content=user),
        ]
        return messages, 700
    if mode == "generate":
        user = (
            "议程 (每轮推进一项, 不得重复已问过的):\n"
            "1. 开场问进度\n2. 追问风险\n3. 确认时间点与责任人\n4. 收尾\n\n"
            f"已发生的对话 (Coach=你, Learner=学员):\n{history}\n\n"
            f"学员本轮说 (英文转写):\n{_USER_TEXT}\n\n{_GENERATE_SHAPE}"
        )
        messages = [
            LlmMessage(role="system", content=_GENERATE_SYSTEM),
            LlmMessage(role="user", content=user),
        ]
        return messages, 160
    if mode == "grade":
        user = (
            f"任务清单:\n{_TASKS}\n\n"
            f"对话记录 (只用于判定任务达成):\n{history}\n\n"
            f"学员本轮说 (英文转写):\n{_USER_TEXT}\n\n{_GRADE_SHAPE}"
        )
        system = f"{_GRADE_SYSTEM} 学员水平: CEFR {_PERSONA['level']}。"
        messages = [
            LlmMessage(role="system", content=system),
            LlmMessage(role="user", content=user),
        ]
        return messages, 450
    raise ValueError(f"unknown mode: {mode}")


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


async def one_run(mode: str, model: str, timeout_s: float, no_think: bool = False) -> dict[str, Any]:
    provider = get_llm_provider()
    messages, max_tokens = build_messages(mode)
    if no_think:
        # qwen3 系默认开启思考 (实测 reasoning_tokens ~100/次), 墙钟被隐藏 token 吃掉;
        # provider.chat() 没有透传 extra_body 的口子, 冒烟直接用底层 SDK 打同一份 payload。
        return await _one_run_raw(messages, model, max_tokens, timeout_s, mode, no_think)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    record: dict[str, Any] = {"mode": mode, "model": model, "max_tokens": max_tokens}
    try:
        completion = await provider.chat(
            model=model,
            messages=messages,
            temperature=0.7 if mode == "generate" else 0.2,
            max_tokens=max_tokens,
            timeout=timeout_s,
        )
        record["ms"] = round((loop.time() - t0) * 1000)
        content = (completion.content or "").strip()
        record["chars"] = len(content)
        body = content
        if body.startswith("```"):
            body = body.strip("`")
            body = body.split("\n", 1)[1] if "\n" in body else body
        body = body.rstrip("`").strip()
        try:
            data = json.loads(body)
            record["json_ok"] = isinstance(data, dict)
            record["keys"] = sorted(data) if isinstance(data, dict) else []
        except json.JSONDecodeError:
            record["json_ok"] = False
            record["keys"] = []
    except Exception as exc:
        record["ms"] = round((loop.time() - t0) * 1000)
        record["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        record["json_ok"] = False
    return record


async def _one_run_raw(
    messages: list[LlmMessage], model: str, max_tokens: int, timeout_s: float, mode: str,
    no_think: bool,
) -> dict[str, Any]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=timeout_s, max_retries=0
    )
    payload = [{"role": m.role, "content": m.content} for m in messages]
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    record: dict[str, Any] = {"mode": mode, "model": model, "max_tokens": max_tokens}
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=payload,
            temperature=0.7 if mode == "generate" else 0.2,
            max_tokens=max_tokens,
            extra_body={"enable_thinking": False},
        )
        msg = resp.choices[0].message
        content = (msg.content or "").strip()
        usage = getattr(resp, "usage", None)
        record.update(
            {
                "ms": round((loop.time() - t0) * 1000),
                "chars": len(content),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "reasoning_tokens": (getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None)),
                "json_ok": _looks_like_json(content),
            }
        )
    except Exception as exc:
        record["ms"] = round((loop.time() - t0) * 1000)
        record["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        record["json_ok"] = False
    await client.close()
    return record


def _looks_like_json(content: str) -> bool:
    """宽容判定 (与 ``drill_grader._parse_llm_json`` 同口径: 先剥围栏, 再取首尾花括号)."""
    body = content.strip()
    if body.startswith("```"):
        body = body.strip("`").strip()
        body = body.split("\n", 1)[1] if "\n" in body else body
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return False
    try:
        return isinstance(json.loads(body[start : end + 1]), dict)
    except Exception:
        return False


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modes", default="combined,generate,grade", help="逗号分隔: combined|generate|grade")
    ap.add_argument("--runs", type=int, default=5, help="每种模式跑几次")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--model", default=None, help="默认用 LLM_DEFAULT_MODEL / 白名单首项")
    ap.add_argument("--dump-dir", type=Path, default=None)
    ap.add_argument("--no-think", action="store_true", help="带 extra_body={enable_thinking: False} 重测")
    args = ap.parse_args()

    if not (settings.llm_api_key and settings.llm_base_url):
        print("FATAL: backend/.env 缺 LLM_API_KEY / LLM_BASE_URL", file=sys.stderr)
        return 2

    model = args.model or settings.llm_default_model.strip()
    if not model:
        from app.services.llm_provider import allowed_model_ids

        allowed = allowed_model_ids()
        model = allowed[0] if allowed else ""
    if not model:
        print("FATAL: 解析不出模型 id (LLM_DEFAULT_MODEL 与 LLM_ALLOWED_MODELS 都空)", file=sys.stderr)
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dump = args.dump_dir or Path(f"/tmp/split-latency-{stamp}")
    dump.mkdir(parents=True, exist_ok=True)

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    records: list[dict[str, Any]] = []
    for mode in modes:
        tokens = build_messages(mode)[1]
        print(f"[{mode}] {args.runs} runs on model={model} (max_tokens={tokens})", flush=True)
        for i in range(args.runs):
            rec = await one_run(mode, model, args.timeout, no_think=args.no_think)
            records.append(rec)
            print(
                f"  #{i + 1}: {rec.get('ms')}ms json_ok={rec.get('json_ok')} "
                f"chars={rec.get('chars', '-')} ct={rec.get('completion_tokens', '-')} "
                f"rt={rec.get('reasoning_tokens', '-')} err={rec.get('error', '')}"
            )

    print("\n===== SUMMARY =====")
    print(f"{'mode':<12} {'n':>3} {'ok':>3} {'p50_s':>7} {'p95_s':>7} {'max_s':>7} {'avg_chr':>8}")
    for mode in modes:
        rows = [r for r in records if r["mode"] == mode]
        times = [float(r["ms"]) / 1000 for r in rows if "ms" in r]
        ok = sum(1 for r in rows if r.get("json_ok"))
        chars = [int(str(r.get("chars", 0))) for r in rows if r.get("chars")]
        if not times:
            print(f"{mode:<12} {len(rows):>3} {ok:>3}  (no timing)")
            continue
        avg_chars = sum(chars) / len(chars) if chars else 0
        print(
            f"{mode:<12} {len(rows):>3} {ok:>3} {_pct(times, 0.5):>7.2f} "
            f"{_pct(times, 0.95):>7.2f} {max(times):>7.2f} {avg_chars:>8.0f}"
        )
    all_times = [float(r["ms"]) / 1000 for r in records if "ms" in r]
    if all_times:
        print(f"\noverall median: {statistics.median(all_times):.2f}s")
    (dump / "records.json").write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"证据: {dump}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
