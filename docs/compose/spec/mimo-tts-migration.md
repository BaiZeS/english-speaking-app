---
feature: mimo-tts-migration
status: delivered
updated: 2026-07-29
---

# MiMo-TTS Migration

## Report

**What was built** — Replaced the iFlytek Spark 超拟人 TTS provider with MiMo-V2.5-TTS (OpenAI-compatible REST API). The new provider uses the `openai` Python library for streaming PCM16 audio synthesis at 24kHz, converts to WAV, and caches on disk. The legacy iFlytek TTS files (`spark_tts.py`, `xunfei_tts.py`) and their tests were removed. iFlytek ISE (speech evaluation) is unchanged. Android voice names updated from `x5_EnUs_Grant_flow`/`x5_EnUs_Lila_flow` to `Mia`/`Chloe`/`Milo`/`Dean`.

**Verification** — `uv run pytest` passes all 130 tests (16 TTS-specific). `ruff check .` and `ruff format --check .` clean. Same error contract preserved: no silent degradation to stub when API key configured.

**Journey log** —
1. MiMo-TTS uses OpenAI-compatible API (REST + SSE) vs iFlytek's WebSocket — major simplification, no more `websockets.connect` or HMAC auth for TTS.
2. The `openai` library was already a dependency (`>=1.54`), so no new packages needed.
3. Mock structure needed `chat.completions` nesting (not flat `completions`) to match the real OpenAI client API path.
4. `_synthesize_streaming` is sync (openai SDK handles streaming internally) — test patches must use sync functions, not async.

## [S1] Problem
The app currently uses iFlytek Spark 超拟人 TTS (WebSocket-based, complex auth) for pronunciation demonstration. We need to replace it with MiMo-TTS (OpenAI-compatible REST API, simpler, free tier available) to reduce complexity and dependency on iFlytek's TTS service.

## [S2] Design

### API Contract
- **Provider**: MiMo-TTS v2.5 via OpenAI-compatible REST API
- **Base URL**: `https://api.xiaomimimo.com/v1`
- **Model**: `mimo-v2.5-tts`
- **Auth**: `api-key` header (env: `MIMO_API_KEY`)
- **Streaming**: PCM16 at 24kHz, streamed via SSE
- **Non-streaming fallback**: WAV format, returned as base64

### Voice Mapping
| Old (iFlytek) | New (MiMo) | Language | Gender |
|---|---|---|---|
| `x5_EnUs_Grant_flow` | `Mia` | English | Female (default) |
| `x5_EnUs_Lila_flow` | `Chloe` | English | Female |

Additional MiMo English voices available: `Milo` (male), `Dean` (male).

### Fallback Strategy
- MiMo-TTS only — remove all iFlytek TTS code (`spark_tts.py`, `xunfei_tts.py`)
- Keep `StubTTSProvider` for dev/testing when no `MIMO_API_KEY` configured
- iFlytek ISE (speech evaluation/ASR) is NOT being replaced — stays as-is
- Same error contract: no silent degradation to stub when credentials present

### Configuration Changes
**Remove** from `config.py` / `.env.example`:
- `XUNFEI_TTS_DEFAULT_VCN`, `XUNFEI_TTS_VOICES`
- `XUNFEI_SPARK_TTS_PASSWORD`, `XUNFEI_SPARK_TTS_URL`
- `TTS_ALLOW_V2_LEGACY`

**Add**:
- `MIMO_API_KEY` (required for real TTS)
- `MIMO_TTS_BASE_URL` (default: `https://api.xiaomimimo.com/v1`)
- `MIMO_TTS_MODEL` (default: `mimo-v2.5-tts`)
- `MIMO_TTS_DEFAULT_VOICE` (default: `Mia`)
- `MIMO_TTS_VOICES` (default: `Mia,Chloe,Milo,Dean`)

**Keep** (ISE still needs iFlytek):
- `XUNFEI_APP_ID`, `XUNFEI_API_KEY`, `XUNFEI_API_SECRET` — only for ISE/ASR
- `TTS_CACHE_TTL`, `TTS_AUDIO_DIR`

### File Changes

**Backend — New/Replace**:
1. `backend/app/services/mimo_tts.py` — New MiMo-TTS provider using `openai` library (streaming PCM16 → WAV, disk cache, voice normalization)
2. `backend/app/api/v1/tts.py` — Use `MimoTtsProvider`, update default voice to `Mia`
3. `backend/app/config.py` — Replace iFlytek TTS settings with MiMo settings
4. `backend/.env.example` — Replace iFlytek TTS vars with MiMo vars

**Backend — Delete**:
5. `backend/app/services/spark_tts.py`
6. `backend/app/services/xunfei_tts.py`

**Backend — Update**:
7. `backend/app/services/interfaces.py` — Update source comment
8. `backend/app/models/schema.py` — Update source comment

**Backend — Tests**:
9. `backend/tests/test_mimo_tts.py` — New tests for MiMo provider (mock openai client)
10. `backend/tests/test_spark_tts.py` — DELETE
11. `backend/tests/test_tts.py` — Update to use MiMo provider references

**Android**:
12. `EnglishApi.kt` — Default voice `Mia`
13. `SettingsStore.kt` — `DEFAULT_VOICE = "Mia"`
14. `SettingsViewModel.kt` — Voice list `Mia,Chloe,Milo,Dean`
15. `AboutScreen.kt` — Update "讯飞 ISE / TTS" → "讯飞 ISE · MiMo TTS"

**Documentation**:
16. `README.md` — Update tech stack references
17. `backend/README.md` — Update credential setup instructions

## [S3] Out of Scope
- iFlytek ISE/ASR replacement (stays as-is)
- Voice design / voice clone features (only preset voices)
- Chinese TTS voices (app is English-only)
- Audio format changes (keep mp3 for caching/compatibility)

## Tasks
- [x] T1: Create `mimo_tts.py` provider with streaming support — acceptance: unit tests pass with mock openai client (covers: S2)
- [x] T2: Update config.py and .env.example with MiMo settings — acceptance: settings load correctly (covers: S2)
- [x] T3: Update tts.py endpoint to use MimoTtsProvider — acceptance: endpoint returns audio with MiMo source (covers: S2)
- [x] T4: Delete spark_tts.py and xunfei_tts.py, update imports — acceptance: no import errors, tests pass (covers: S2)
- [x] T5: Update interfaces.py and schema.py source comments — acceptance: comments reference MiMo (covers: S2)
- [x] T6: Write test_mimo_tts.py with mocked openai client — acceptance: all test cases pass (covers: S2)
- [x] T7: Update test_tts.py for MiMo provider — acceptance: endpoint tests pass (covers: S2)
- [x] T8: Update Android default voice and About screen — acceptance: Mia is default, About says MiMo TTS (covers: S2)
- [x] T9: Update README.md and backend/README.md — acceptance: docs reference MiMo TTS setup (covers: S2)

## 后续增补（v2.1.0，2026-09-06 归档于此）

1. **stub 音频修复**：无 `MIMO_API_KEY` 时原 stub 返回 `STUB_TTS::` 伪字节 + 不存在的 `.m4a` URL（客户端播放 404 无响应）；v2.1.0 起改返回**真实 400ms 静音 WAV**（新增 `app/services/wav.py`），`source=stub` 标记与「未配凭据」警示、影子跟读 stub 守卫全部保留 → 无凭据环境可完整联调。
2. **自托管 OTA**：本机至 `release-assets.githubusercontent.com` 实测 11-40KB/s，21MB APK 走 GitHub 对大陆手机不可用 → `/static/apk` 挂载 + `scripts/publish_apk.sh <tag>`（拉包 → 自托管 → 写 `.env` `APP_LATEST_VERSION`/`APP_APK_URL` → 重启自检 source=env）。**push tag 后必须跑此脚本**。
3. 拓扑/SOP 见 `docs/operations.md`，使用路径见 `docs/usage-guide.md`。
