"""MiMo TTS 单元测试 (不连真网, mock openai client).

覆盖:
- 凭据缺失: fallback 到 stub
- 流式合成: PCM16 音频块拼接 → WAV
- 错误处理: API 失败抛 RuntimeError (不静默降级)
- 磁盘缓存: 同 (text, voice) 命中缓存不发请求
- voice 规范化: 未知 voice 回退到 default
"""

from __future__ import annotations

import base64
import struct
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import mimo_tts
from app.services.mimo_tts import (
    MimoTtsProvider,
    _normalize_voice,
    _pcm16_to_wav,
)


@pytest.fixture(autouse=True)
def _init_db() -> None:
    """覆盖 conftest 的 autouse _init_db (mimo_tts 不依赖 db)."""


# ====== 纯函数 ======


def test_normalize_voice_known_passes_through() -> None:
    for v in ("Mia", "Chloe", "Milo", "Dean"):
        assert _normalize_voice(v) == v


def test_normalize_voice_unknown_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []

    def _spy_warning(fmt: str, *args: Any) -> None:
        warnings.append(fmt.format(*args))

    monkeypatch.setattr(mimo_tts.logger, "warning", _spy_warning)
    result = _normalize_voice("UnknownVoice")
    assert result == mimo_tts.settings.mimo_tts_default_voice
    assert any("UnknownVoice" in w for w in warnings)


def test_normalize_voice_empty_falls_back() -> None:
    assert _normalize_voice("") == mimo_tts.settings.mimo_tts_default_voice
    assert _normalize_voice(None) == mimo_tts.settings.mimo_tts_default_voice  # type: ignore[arg-type]


def test_pcm16_to_wav_header() -> None:
    pcm = b"\x00\x00" * 100  # 100 samples of silence
    wav = _pcm16_to_wav(pcm, sample_rate=24000, channels=1)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert wav[36:40] == b"data"
    # data size field should match PCM length
    data_size = struct.unpack_from("<I", wav, 40)[0]
    assert data_size == len(pcm)
    assert len(wav) == 44 + len(pcm)


# ====== Provider tests (mock openai) ======


def _make_mock_chunk(audio_data_b64: str | None) -> Any:
    """Create a fake SSE chunk with optional audio data."""
    if audio_data_b64 is None:
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(audio=None))])
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(audio={"data": audio_data_b64}))]
    )


class _FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __iter__(self) -> _FakeStream:
        return self

    def __next__(self) -> Any:
        if not self._chunks:
            raise StopIteration
        return self._chunks.pop(0)


class _FakeCompletions:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _FakeStream:
        self.last_kwargs = kwargs
        return _FakeStream(list(self._chunks))


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, chunks: list[Any]) -> None:
        self.chat = _FakeChat(_FakeCompletions(chunks))


@pytest.mark.asyncio
async def test_synthesize_fallback_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mimo_tts.settings, "mimo_api_key", "")

    result = await MimoTtsProvider().synthesize("Hello", "Mia")
    assert result.audio_bytes.startswith(b"STUB_TTS::")
    assert result.source == "stub"


@pytest.mark.asyncio
async def test_synthesize_streaming_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(mimo_tts.settings, "mimo_api_key", "test-key")
    monkeypatch.setattr(mimo_tts.settings, "tts_audio_dir", str(tmp_path))

    # Create fake PCM16 data (2 bytes per sample)
    pcm_chunk = b"\x01\x02" * 50
    chunks = [
        _make_mock_chunk(base64.b64encode(pcm_chunk).decode()),
        _make_mock_chunk(base64.b64encode(pcm_chunk).decode()),
        _make_mock_chunk(None),  # chunk without audio
    ]

    fake_client = _FakeClient(chunks)

    def _fake_openai(**kwargs: Any) -> _FakeClient:
        return fake_client

    monkeypatch.setattr(mimo_tts, "OpenAI", _fake_openai)

    result = await MimoTtsProvider().synthesize("Hello world", "Mia")

    assert result.source == "mimo"
    assert len(result.audio_bytes) > 0
    # Should be valid WAV (starts with RIFF)
    assert result.audio_bytes[:4] == b"RIFF"
    assert result.duration_ms > 0
    # Verify correct API call parameters
    assert fake_client.chat.completions.last_kwargs["model"] == mimo_tts.settings.mimo_tts_model
    assert fake_client.chat.completions.last_kwargs["audio"]["voice"] == "Mia"
    assert fake_client.chat.completions.last_kwargs["audio"]["format"] == "pcm16"
    assert fake_client.chat.completions.last_kwargs["stream"] is True


@pytest.mark.asyncio
async def test_synthesize_raises_on_empty_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(mimo_tts.settings, "mimo_api_key", "test-key")
    monkeypatch.setattr(mimo_tts.settings, "tts_audio_dir", str(tmp_path))

    # All chunks have no audio data
    chunks = [_make_mock_chunk(None), _make_mock_chunk(None)]
    fake_client = _FakeClient(chunks)
    monkeypatch.setattr(mimo_tts, "OpenAI", lambda **kw: fake_client)

    with pytest.raises(RuntimeError, match="no audio"):
        await MimoTtsProvider().synthesize("Hello", "Mia")


@pytest.mark.asyncio
async def test_synthesize_raises_on_api_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(mimo_tts.settings, "mimo_api_key", "test-key")
    monkeypatch.setattr(mimo_tts.settings, "tts_audio_dir", str(tmp_path))

    def _boom(**kwargs: Any) -> Any:
        raise RuntimeError("API rate limit exceeded")

    monkeypatch.setattr(mimo_tts, "OpenAI", _boom)

    with pytest.raises(RuntimeError, match="rate limit"):
        await MimoTtsProvider().synthesize("Hello", "Mia")


@pytest.mark.asyncio
async def test_synthesize_uses_disk_cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(mimo_tts.settings, "mimo_api_key", "test-key")
    monkeypatch.setattr(mimo_tts.settings, "tts_audio_dir", str(tmp_path))

    call_count = {"n": 0}
    pcm_data = b"\x01\x02" * 10

    class CountingCompletions:
        def create(self, **kwargs: Any) -> _FakeStream:
            call_count["n"] += 1
            return _FakeStream([_make_mock_chunk(base64.b64encode(pcm_data).decode())])

    class CountingClient:
        def __init__(self) -> None:
            self.chat = _FakeChat(CountingCompletions())

    monkeypatch.setattr(mimo_tts, "OpenAI", lambda **kw: CountingClient())

    # First call: triggers API
    r1 = await MimoTtsProvider().synthesize("Cache me", "Mia")
    assert call_count["n"] == 1
    assert r1.source == "mimo"

    # Second call: hits disk cache, no API call
    r2 = await MimoTtsProvider().synthesize("Cache me", "Mia")
    assert call_count["n"] == 1, "should not call API on cache hit"
    assert r2.audio_bytes == r1.audio_bytes
    assert r2.audio_url == r1.audio_url


@pytest.mark.asyncio
async def test_synthesize_normalizes_voice(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(mimo_tts.settings, "mimo_api_key", "test-key")
    monkeypatch.setattr(mimo_tts.settings, "tts_audio_dir", str(tmp_path))

    captured_voice = {}

    class VoiceCapturingCompletions:
        def create(self, **kwargs: Any) -> _FakeStream:
            captured_voice["v"] = kwargs["audio"]["voice"]
            pcm = b"\x00\x00" * 10
            return _FakeStream([_make_mock_chunk(base64.b64encode(pcm).decode())])

    class VoiceCapturingClient:
        def __init__(self) -> None:
            self.chat = _FakeChat(VoiceCapturingCompletions())

    monkeypatch.setattr(mimo_tts, "OpenAI", lambda **kw: VoiceCapturingClient())

    # Unknown voice should fall back to default
    await MimoTtsProvider().synthesize("Hi", "unknown_voice")
    assert captured_voice["v"] == mimo_tts.settings.mimo_tts_default_voice
