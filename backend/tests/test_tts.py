from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# conftest 的 autouse _init_db (pytest_asyncio fixture) 在 sync test 下 hang event loop.
# /tts 端点本身不依赖 db, 这里覆盖掉.
@pytest.fixture(autouse=True)
def _init_db() -> None:
    """覆盖 conftest 的 autouse _init_db."""


@pytest.fixture(autouse=True)
def _force_stub_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 TTS 走 stub: 本测试只校验 /tts 端点接线, 不依赖真实讯飞凭证/网络.

    DEV-2026-07-22-TTS-A1: 既清空 Spark 凭据, 也清空 v2 凭据 + opt-in 标志,
    确保 SparkTtsProvider 走 ''完全无凭据' → stub' 分支, 不会因本地 .env
    配置的凭证而真调讯飞网络 (断言会抖动 / 烧钱).
    """
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_spark_tts_password", "")
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.spark_tts.settings.tts_allow_v2_legacy", False)
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_app_id", "")
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_api_key", "")
    monkeypatch.setattr("app.services.xunfei_tts.settings.xunfei_api_secret", "")


@pytest.mark.asyncio
async def test_tts_returns_audio_url_and_duration() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})
    assert r.status_code == 200
    data = r.json()
    assert data["audio_url"].endswith(".m4a")
    assert data["duration_ms"] > 0
    # DEV-2026-07-22-TTS-A1: 端点必须透传 source, 让前端能识别音频类型.
    # _force_stub_tts 清空了所有凭据 + opt-in, 所以这里是 stub.
    assert data["source"] == "stub"


@pytest.mark.asyncio
async def test_tts_rejects_empty_text() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "", "voice": "x5_EnUs_Grant_flow"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_tts_is_deterministic_across_calls() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})
        r2 = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})
    assert r1.json()["audio_url"] == r2.json()["audio_url"]


# ====== DEV-2026-07-22-TTS-A1: 503 + TTS_UNAVAILABLE 契约 ======


@pytest.mark.asyncio
async def test_tts_returns_503_when_spark_fails_with_creds(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """配齐 Spark 凭据时, Spark 调用失败必须被端点映射为 503 + TTS_UNAVAILABLE,
    不返假音频 (audio_url 不指向 stub 的 .m4a).

    这是修复的关键验收: 之前静默降级, 前端无感知; 现在 endpoint 透明报告失败.
    """
    # 启用 Spark 凭据, 模拟 '用户已配齐' 场景
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_app_id", "fake_app_id")
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_spark_tts_password", "ak-x")
    monkeypatch.setattr("app.services.spark_tts.settings.tts_audio_dir", str(tmp_path))
    # 即便 v2 凭据齐全 + opt-in 开启, 也不允许降级 (这是契约核心)
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_api_key", "v2_key")
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_api_secret", "v2_secret")
    monkeypatch.setattr("app.services.spark_tts.settings.tts_allow_v2_legacy", True)

    # 把 Spark 内部 _synthesize 替换成抛错 — 模拟任意类型的 Spark 故障
    # (网络/鉴权/超拟人控制台未开通, 等)
    async def _boom(self, _t: str, _v: str) -> bytes:
        raise RuntimeError("simulated spark failure: code=11200")

    from app.services import spark_tts as spark_mod

    monkeypatch.setattr(spark_mod.SparkTtsProvider, "_synthesize", _boom)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})

    assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"]["code"] == "TTS_UNAVAILABLE"
    assert "simulated spark failure" in body["error"]["message"]
    # 关键: 响应不包含任何音频 URL, 前端不会被诱导播放假音频.
    assert "audio_url" not in body, f"503 response must not include audio_url: {body}"


@pytest.mark.asyncio
async def test_tts_returns_503_on_websockets_transport_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """DEV-2026-07-22-TTS-A3: 生产最常见的失败模式 — websockets.connect 拒绝 / DNS /
    TLS / 超时 — 抛的是 websockets.exceptions.WebSocketException (或其子类
    InvalidStatus / InvalidURI / ConnectionClosed) 或 OSError, 都不是 RuntimeError.

    旧实现 `except RuntimeError` 漏掉这些, 端点会冒泡到 FastAPI 默认 500,
    前端拿不到 TTS_UNAVAILABLE, 无法重试/告警. 本测试断言改 except Exception 后,
    websockets transport 失败也走 503+TTS_UNAVAILABLE 分支.

    模拟方案: 配齐 Spark 凭据让 _synthesize 进入 Spark 分支 (不是 stub 兜底),
    monkeypatch SparkTtsProvider._synthesize 抛 websockets.exceptions.WebSocketException
    (基类, 覆盖所有子类 — InvalidStatus / InvalidURI / ConnectionClosed 等).
    """
    import websockets.exceptions

    # 启用 Spark 凭据, 模拟 '用户已配齐' 场景 — 保证走 Spark 分支而非 stub.
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_app_id", "fake_app_id")
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_spark_tts_password", "ak-x")
    monkeypatch.setattr("app.services.spark_tts.settings.tts_audio_dir", str(tmp_path))
    # 即便 v2 凭据齐全 + opt-in 开启, 也不允许降级 (契约核心)
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_api_key", "v2_key")
    monkeypatch.setattr("app.services.spark_tts.settings.xunfei_api_secret", "v2_secret")
    monkeypatch.setattr("app.services.spark_tts.settings.tts_allow_v2_legacy", True)

    # 模拟 websockets.connect 失败 — 用基类 WebSocketException, 覆盖所有子类.
    # 之所以选 WebSocketException 而非 OSError: 任务示例明确点名 websockets 库,
    # 且该基类覆盖 InvalidStatus / InvalidURI / ConnectionClosed 等子类,
    # 也间接覆盖更底层的 transport 错误 (握手失败/TLS/超时 等).
    async def _boom(self, _t: str, _v: str) -> bytes:
        raise websockets.exceptions.WebSocketException("simulated websockets.connect failure")

    from app.services import spark_tts as spark_mod

    monkeypatch.setattr(spark_mod.SparkTtsProvider, "_synthesize", _boom)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tts", params={"text": "Hello", "voice": "x5_EnUs_Grant_flow"})

    # 关键验收: 旧实现此处会返 500 (FastAPI 未处理异常), 修复后必须 503.
    assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"]["code"] == "TTS_UNAVAILABLE"
    assert "simulated websockets.connect failure" in body["error"]["message"]
    # 响应不包含任何音频 URL, 前端不会被诱导播放假音频.
    assert "audio_url" not in body, f"503 response must not include audio_url: {body}"
