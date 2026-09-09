#!/usr/bin/env python3
"""讯飞 ISE/IAT 真火冒烟脚本 (只打真实服务, 不碰 DB, 证据只落 /tmp).

目的: 拿一手 ws 响应分类根因 (权限/参数/节奏), 确认返回 XML 的分制,
对比当前参数 (asis) 与文档修正参数 (fixed) 及快发包 (fixed_fast)。
用法见 --help; 每日额度 ~500 次, 全量跑一次约 8 次会话。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import contextlib
import json
import os
import sys
import time
import wave
import xml.etree.ElementTree as ET
from array import array
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# 与 deploy.sh 同款纪律: shell 里残留/注入的同名环境变量会遮蔽 .env
# (pydantic-settings 进程 env 优先)。本会话环境恰好带着一个用于别处的
# MIMO_API_KEY, 冒烟必须以 backend/.env 为唯一事实源。
for _line in (ROOT / ".env").read_text().splitlines():
    _key = _line.split("=", 1)[0].strip()
    if _key and not _key.startswith("#"):
        os.environ.pop(_key, None)

import websockets  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.mimo_tts import MimoTtsProvider  # noqa: E402
from app.services.xunfei_asr import (  # noqa: E402
    _build_auth_url,
    _build_ssb_frame,
)

_PCM_RATE = 16000
_MAX_FRAME = 19200  # 文档上限: base64 前字节数
_BOM = "\ufeff"  # ISE 流式版: text 需 '\uFEFF'+text

_CODE_LABELS = {
    10105: "服务未授权/key 无效 (10105)",
    10163: "单帧数据过长 (10163)",
    10164: "未收到结束帧 (10164)",
    10165: "status 非法 (10165)",
    11200: "该 appid 未开通此服务 (11200)",
    22001: "请求参数异常 (22001)",
    22002: "交互过程超时 (22002)",
    23000: "引擎内部错误 (23000)",
    23001: "解码错误/音频格式 (23001)",
    23002: "获取合成音频错误 (23002)",
    23003: "无效试题 (23003)",
    23004: "合成音频失败 (23004)",
    23005: "试题内容不符合题型 (23005)",
    23006: "引擎链接失败 (23006)",
    23009: "音频采样点太少 (23009)",
}


def _label(code: object) -> str:
    try:
        c = int(code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"code={code}"
    return f"{c}: {_CODE_LABELS.get(c, '其他错误码')}"


# ====== 音频构建 ======


def _resample_linear(pcm_s16le: bytes, src_rate: int, dst_rate: int) -> bytes:
    if src_rate == dst_rate:
        return pcm_s16le
    samples = array("h")
    samples.frombytes(pcm_s16le)
    n = max(1, int(len(samples) * dst_rate / src_rate))
    out = array("h", bytes(2 * n))
    ratio = src_rate / dst_rate
    for i in range(n):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        if j + 1 < len(samples):
            out[i] = int(samples[j] * (1 - frac) + samples[j + 1] * frac)
        elif j < len(samples):
            out[i] = samples[j]
    return out.tobytes()


def tts_pcm16k(text: str, voice: str, dump_dir: Path) -> bytes:
    """MiMo TTS 真合成 → 裸 PCM L16 mono 16k (不落仓库缓存)."""
    wav_bytes = MimoTtsProvider()._synthesize_streaming(text, voice)
    if not wav_bytes:
        raise RuntimeError("mimo tts returned empty audio")
    with wave.open(BytesIO(wav_bytes), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2 or ch != 1:
        raise RuntimeError(f"unexpected tts wav: rate={rate} ch={ch} width={width}")
    (dump_dir / "tts_native.wav").write_bytes(wav_bytes)
    return _resample_linear(frames, rate, _PCM_RATE)


def silence(seconds: float) -> bytes:
    return b"\x00" * int(seconds * _PCM_RATE * 2)


# ====== ssb 变体 ======


def _ssb_business(args_text: str, category: str, variant: str) -> dict[str, object]:
    if variant == "asis":
        return dict(_build_ssb_frame(args_text, category)["business"])
    node = "[content]" if category == "read_sentence" else "[word]"
    text = args_text
    if variant.startswith("probe"):
        # probe_no_bom: 去掉 BOM; probe_inline_node: 节点不换行直接接文本
        bom = "" if variant == "probe_no_bom" else _BOM
        sep = "\n" if variant == "probe_no_bom" else ""
        text = f"{bom}{node}{sep}{args_text}"
    else:  # fixed / fixed_fast
        text = f"{_BOM}{node}\n{args_text}"
    return {
        "aue": "raw",
        "auf": "audio/L16;rate=16000",
        "category": category,
        "cmd": "ssb",
        "ent": "en_vip",
        "sub": "ise",
        "text": text,
        "tte": "utf-8",
        "ttp_skip": True,
    }


def _frame_chunks(pcm: bytes, size: int) -> list[bytes]:
    return [pcm[i : i + size] for i in range(0, len(pcm), size)] or [b""]


# ====== 原始 ISE runner (逐帧日志) ======


async def ise_run_variant(
    pcm: bytes,
    ref_text: str,
    category: str,
    variant: str,
    timeout_s: float,
    frame_log: list[dict[str, object]],
    fast_frame: int = _MAX_FRAME,
    pertick: int = 1,
) -> dict[str, object]:
    fast = variant.endswith("_fast")
    size = fast_frame if fast else 1280
    interval = 0.0 if fast else 0.04
    chunks = _frame_chunks(pcm, size)
    xml_out: list[str] = []
    err: dict[str, object] | None = None
    done = asyncio.Event()
    out: dict[str, object] = {
        "variant": variant,
        "handshake": "fail",
        "final": False,
        "xml": "",
    }
    t0 = time.monotonic()
    try:
        async with websockets.connect(_build_auth_url(), open_timeout=10) as ws:
            out["handshake"] = "ok"

            async def receiver() -> None:
                nonlocal err
                while True:
                    resp = json.loads(await ws.recv())
                    rec: dict[str, object] = {
                        "t_ms": round((time.monotonic() - t0) * 1000),
                        "code": resp.get("code"),
                        "message": resp.get("message"),
                        "status": (resp.get("data") or {}).get("status"),
                        "b64_len": len(((resp.get("data") or {}).get("data")) or ""),
                        "sid": resp.get("sid"),
                    }
                    frame_log.append(rec)
                    if resp.get("code") != 0:
                        err = {
                            "kind": "ise_code",
                            "detail": _label(resp.get("code")),
                            "message": resp.get("message"),
                        }
                        done.set()
                        return
                    data = resp.get("data") or {}
                    if dd := data.get("data"):
                        try:
                            xml_out.append(base64.b64decode(dd).decode("utf-8", "replace"))
                        except (binascii.Error, ValueError):
                            xml_out.append(str(dd))
                    if data.get("status") == 2:
                        out["final"] = True
                        done.set()
                        return

            recv_task = asyncio.create_task(receiver())
            try:
                await ws.send(
                    json.dumps(
                        {
                            "common": {"app_id": settings.xunfei_app_id},
                            "business": _ssb_business(ref_text, category, variant),
                            "data": {"status": 0},
                        },
                        ensure_ascii=False,
                    )
                )
                n = len(chunks)
                send_ms = 0.0
                for idx, chunk in enumerate(chunks):
                    if n == 1:
                        aus, status = 8, 2
                    elif idx == 0:
                        aus, status = 1, 1
                    elif idx == n - 1:
                        aus, status = 4, 2
                    else:
                        aus, status = 2, 1
                    t_io = time.monotonic()
                    await ws.send(
                        json.dumps(
                            {
                                "business": {"cmd": "auw", "aus": aus},
                                "data": {
                                    "status": status,
                                    "data": base64.b64encode(chunk).decode(),
                                },
                            }
                        )
                    )
                    send_ms += (time.monotonic() - t_io) * 1000
                    if interval:
                        await asyncio.sleep(interval / max(1, pertick))
                out["send_ms"] = round(send_ms)
                try:
                    await asyncio.wait_for(done.wait(), timeout=timeout_s)
                except TimeoutError:
                    err = err or {"kind": "timeout", "detail": f"no final frame in {timeout_s}s"}
            finally:
                recv_task.cancel()
    except Exception as e:
        sc = getattr(getattr(e, "response", None), "status_code", None)
        reason = str(e)[:120]
        cls = f"handshake_{sc or type(e).__name__}"
        if sc == 401:
            cls = "handshake_401_key_or_signature"
        elif sc == 403:
            cls = "handshake_403_ip_whitelist_or_clock"
        out["error"] = {"kind": cls, "detail": reason}
        err = err or out.get("error")
    out["total_ms"] = round((time.monotonic() - t0) * 1000)
    out["xml"] = "".join(xml_out)
    if err and "error" not in out:
        out["error"] = err
    return out


# ====== XML 分数提取 (独立于 app 的 1-5 假设) ======


def _word_scores(xml: str) -> tuple[int, list[float]]:
    if not xml.strip():
        return 0, []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return -1, []
    scores: list[float] = []
    words = 0
    for el in root.iter("word"):
        content = (el.get("content") or "").strip()
        if not content or content == "sil":
            continue
        words += 1
        with contextlib.suppress(ValueError):
            scores.append(float(el.get("total_score", "")))
    return words, scores


# ====== 主流程 ======


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--text", default="This is an example of sentence test.")
    ap.add_argument(
        "--ref",
        default=None,
        help="评测参考文本 (默认=--text); 与音频不一致即模拟 transcript 锚定脏文本",
    )
    ap.add_argument("--voice", default="Mia")
    ap.add_argument("--category", choices=("read_sentence", "read_word"), default="read_sentence")
    ap.add_argument(
        "--variants",
        default="asis,fixed,fixed_fast,silence_short,silence_long",
        help="逗号分隔; --quick = asis,fixed,silence_short",
    )
    ap.add_argument("--quick", action="store_true")
    ap.add_argument(
        "--probe",
        nargs="?",
        const="no-bom,inline-node",
        default="",
        help="附赠微探针: no-bom / inline-node / 全部",
    )
    ap.add_argument("--timeout", type=float, default=20.0, help="每变体等终帧秒数")
    ap.add_argument(
        "--fast-frame", type=int, default=_MAX_FRAME, help="_fast 变体的帧字节数 (<=19200)"
    )
    ap.add_argument("--pertick", type=int, default=1, help="realtime 变体每 tick 连发帧数")
    ap.add_argument("--pcm", type=Path, default=None, help="跳过 TTS, 复放已有 16k PCM 文件")
    ap.add_argument("--dump-dir", type=Path, default=None)
    ap.add_argument("--skip-iat", action="store_true")
    ap.add_argument("--skip-provider", action="store_true", help="跳过 asis 直通项")
    args = ap.parse_args()

    variants = (
        ["asis", "fixed", "silence_short"]
        if args.quick
        else [v.strip() for v in args.variants.split(",") if v.strip()]
    )
    for p in (args.probe or "").split(","):
        p = p.strip()
        if p == "no-bom":
            variants.append("probe_no_bom")
        elif p == "inline-node":
            variants.append("probe_inline_node")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dump_dir = args.dump_dir or Path(f"/tmp/ise-smoke-{stamp}")
    dump_dir.mkdir(parents=True, exist_ok=True)

    if not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
        print("FATAL: .env 缺 XUNFEI_* 凭据", file=sys.stderr)
        return 2

    print(f"[audio] building sample ({'pcm file' if args.pcm else 'Mimo TTS'}) ...")
    pcm = args.pcm.read_bytes() if args.pcm else tts_pcm16k(args.text, args.voice, dump_dir)
    print(f"[audio] {len(pcm)}B = {len(pcm) / 32000:.2f}s @16k/L16/mono -> {dump_dir}")
    (dump_dir / "sample_16k.pcm").write_bytes(pcm)
    ref = args.ref or args.text

    report: list[dict[str, object]] = []
    for v in variants:
        use_pcm = pcm
        if v == "silence_short":
            use_pcm = silence(0.2)
        elif v == "silence_long":
            use_pcm = silence(3.0)
        frame_log: list[dict[str, object]] = []
        print(f"[variant {v}] running ...", flush=True)
        res = await ise_run_variant(
            use_pcm,
            ref,
            args.category,
            v,
            args.timeout,
            frame_log,
            fast_frame=args.fast_frame,
            pertick=args.pertick,
        )
        res["pcm_bytes"] = len(use_pcm)
        words, scores = _word_scores(str(res["xml"]))
        xml_path = dump_dir / f"result_{v}.xml"
        xml_path.write_text(str(res.pop("xml", "")))
        (dump_dir / f"frames_{v}.jsonl").write_text("\n".join(json.dumps(x) for x in frame_log))
        scale = "n/a"
        if scores:
            scale = "percent(0-100)" if max(scores) > 5 else "1-5"
        res.update(
            {
                "xml_bytes": xml_path.stat().st_size,
                "words": words,
                "raw_min": min(scores) if scores else None,
                "raw_max": max(scores) if scores else None,
                "scale": scale,
            }
        )
        res["error"] = res.get("error")
        report.append(res)
        print(
            f"  handshake={res['handshake']} final={res['final']} words={words} "
            f"scale={scale} total_ms={res['total_ms']} error={res.get('error')}"
        )

    if not args.skip_provider:
        from app.services.xunfei_asr import XunfeiASRProvider

        print("[provider] XunfeiASRProvider.recognize (asis 代码路径) ...")
        t0 = time.monotonic()
        r = await XunfeiASRProvider().recognize(pcm, ref, category=args.category)
        report.append(
            {
                "variant": "provider_asis",
                "handshake": "see-log",
                "words": len(r.word_scores),
                "scale": "via-app-parser",
                "total_ms": round((time.monotonic() - t0) * 1000),
                "error": None if r.source == "xunfei" else "fell back to stub (see log)",
            }
        )
        print(
            f"  source={r.source} words={len(r.word_scores)} "
            f"top={[w.score for w in r.word_scores[:5]]}"
        )

    if not args.skip_iat:
        from app.services.xunfei_iat import XunfeiIatProvider

        t0 = time.monotonic()
        text = await XunfeiIatProvider().transcribe(pcm)
        ms = round((time.monotonic() - t0) * 1000)
        ok = bool(text and text.strip())
        report.append(
            {
                "variant": "iat_passthrough",
                "total_ms": ms,
                "error": None if ok else f"transcript={text!r}",
            }
        )
        print(f"[iat] {ms}ms -> {text!r}")

    print("\n===== REPORT =====")
    hdr = (
        f"{'variant':<18} {'hs':<6} {'final':<6} {'words':>5} {'scale':<15} "
        f"{'send_ms':>8} {'total_ms':>9}  error"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in report:
        print(
            f"{r.get('variant', ''):<18} {r.get('handshake', '')!s:<6} "
            f"{r.get('final', '')!s:<6} {r.get('words', '')!s:>5} "
            f"{r.get('scale', '')!s:<15} {r.get('send_ms', '')!s:>8} "
            f"{r.get('total_ms', '')!s:>9}  {r.get('error') or ''}"
        )
    (dump_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\n证据目录: {dump_dir}")

    any_words = any(isinstance(r.get("words"), int) and r["words"] > 0 for r in report)
    return 0 if any_words else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
