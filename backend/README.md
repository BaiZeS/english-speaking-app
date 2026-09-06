# English Speaking Assistant · Backend

FastAPI 后端，提供语料、TTS、ISE 语音评测、历史等 API。

## 快速开始

> MiMo TTS（语音合成）与讯飞 ISE（语音评测，逐词音素评分）已接入。配 `.env` 凭据即走真实服务；
> 未配凭据时自动 fallback 到 stub，课程列表 / 录音评分 / 历史的完整闭环仍可跑通。

### 1. 起依赖（Postgres，唯一外部依赖）

```bash
# Postgres（用项目自带的 docker-compose，凭据 english/english，库 english_dev）
docker compose up -d postgres
```

> v2.0 起 Redis 依赖已移除（`tts_cache` 服务的 Redis 面从未接线到 API；
> `tts_cache` 数据库表保留但不再读写，理由见 `AppDatabase` 同类"表壳冻结"注记与
> v2.0 P8 报告）。

### 2. 安装依赖 + 跑数据库迁移

```bash
uv sync --frozen --extra dev          # 用锁定的依赖建 venv（ruff/mypy/pytest 等都在内）
uv run alembic upgrade head           # 应用迁移到最新（含 history 表等）
```

### 3. 启动后端

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- `--host 0.0.0.0` **必须**：让 Android 模拟器（`10.0.2.2`）和真机（局域网 IP）都能连上。只绑 `127.0.0.1` 的话 app 连不上。
- 看到 `Uvicorn running on http://0.0.0.0:8000` + `Application startup complete.` 即成功。
- `--reload` 改 Python 文件自动重启（开发用）；生产去掉。

### 4. 验证

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok"}  即成功
```

交互式 API 文档：http://localhost:8000/docs

### 5. Android 客户端连接

| 设备 | app 里的 Backend Base URL |
|---|---|
| 模拟器 | `http://10.0.2.2:8000/api/v1/`（APK 默认值，无需改） |
| 真机 | `http://<电脑局域网IP>:8000/api/v1/`（在 app「设置」页改，手机与电脑同 WiFi） |

### MiMo TTS + 讯飞 ISE（可选，配了走真实服务）

不配也能跑（fallback 到 stub）。要真实 TTS 发音 + ISE 逐词评分，在 `backend/.env` 填：

```
# MiMo TTS (语音合成)
MIMO_API_KEY=...                                    # MiMo 平台 API Key
MIMO_TTS_DEFAULT_VOICE=Mia                          # 默认发音人 (Mia/Chloe/Milo/Dean)
MIMO_TTS_VOICES=Mia,Chloe,Milo,Dean                 # App「设置」页可选发音人列表

# 讯飞 ISE (语音评测)
XUNFEI_APP_ID=...
XUNFEI_API_KEY=...
XUNFEI_API_SECRET=...
```

- **MiMo TTS**：OpenAI 兼容接口, 24kHz WAV, 流式 PCM16 合成, 按 (text, voice) 落盘缓存 (`static/tts/`, 同文本复用, 省配额). [文档](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5)
- **ISE 评分**：提交 PCM（16kHz L16 mono）后走语音评测，返回 0-100 的 total/pronunciation/fluency/completeness + 每词 `word_details`（含 `score` 与 `ipa` 音素）。原始评分 1-5 → 映射到 0-100。

### 备选：Docker Compose 一键起全部

```bash
docker compose up -d        # 起 postgres + api 容器
# API: http://localhost:8000   Docs: http://localhost:8000/docs
```

> 注意：`api` 服务会 `build .`（需 Dockerfile）。本地开发推荐用上面的 `uv run` 方式，更快、改代码即时生效。


### 自由对话 / AI 链路 LLM（v2.0 主引擎，强烈建议配置）

`/dialogue/*`（自由对话）、`/sessions/*/mission`（实战对话）、`/polish`（润色）、打基础三题型判分、
`/scenes/generate`（生成课两段）、`/assessment/*/complete`（测评判级）全部走 **阿里云百炼
OpenAI 兼容端点**；未配置时各处自动降级（deterministic fallback / heuristic 判分 +
`source=stub` 警示，绝不被当作真实证据）。在 `backend/.env` 填：

```
# 阿里云百炼 MaaS（OpenAI 兼容 /compatible-mode/v1）
LLM_BASE_URL=https://ws-xxxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-...
LLM_DEFAULT_MODEL=                # 留空=走白名单序; 本机生产填 qwen3.8-max
                                  # (2026-08 实测 qwen-plus/turbo/max/deepseek-v3 免费额度耗尽 403,
                                  #  仅 qwen3.8-max / qwen3.7-plus 可用; 免费档 ~3 tok/s,
                                  #  两段全量生成 5-10 分钟属预期)
LLM_ALLOWED_MODELS=               # 逗号分隔白名单 (限定客户端可选范围)
LLM_EXTRA_MODELS_JSON=            # JSON 数组, 追加自建代理模型
```

> 判分/生成/画像证据恒用服务端默认模型（不对客户端开放，保证口径一致）；自由对话/润色
> 文本允许在上面的模型白名单内由客户端指定。`GET /api/v1/llm/models` 拉清单，设置页选择。

### 生产部署（部署机 = 本仓运行机）

- 主实例：**端口 5173**（云防火墙唯一映射口）；release 包内置 `http://118.89.58.84:5173/api/v1/`。
- 生产库：docker postgres 容器内 `english_prod_5173`（与开发库 `english_dev` 隔离，`DATABASE_URL` env 覆盖切换）。
- 起停/迁移：`/home/ubuntu/english-backend-deploy.sh {start|stop|restart|status|migrate}`（prod 连接串内置）；日志 `~/english-backend-5173.log`。
- OTA/发版：见仓库根 README「发布通道」+ `docs/operations.md`（push tag → GitHub Release → `scripts/publish_apk.sh <tag>` 自托管直发）。

### App 自动更新

App 启动时会拉取 ``GET /api/v1/app/version`` 比较版本号, 有新版本弹更新对话框
(强制升级时强制弹窗). 服务端按优先级回源:

  1) **环境变量直给** — 自托管或灰度场景: 显式设 ``APP_APK_URL`` 即覆盖.
  2) **GitHub Releases 自动回源** (推荐) — 设 ``APP_GITHUB_REPO=owner/name``, 后端
     调 GitHub Releases API 拿 latest release 的 tag + APK asset URL, 走 5 分钟
     TTL 缓存避免触发 60 req/h 限流. Asset 选择规则: 先按精确文件名匹配
     (``APP_GITHUB_ASSET_NAME``), 再按 glob 通配 (``APP_GITHUB_ASSET_GLOB``,
     默认 ``EnglishAssistant-*.apk``), 最后回退任意 .apk.
  3) **占位返回** — 都不设时返回 ``APP_LATEST_VERSION`` 但 ``apk_url=""``,
     弹窗能渲染但下载按钮禁用, 适合纯 dev 环境.

**GitHub 自动出包** — 配合 ``.github/workflows/release.yml`` (push tag 触发):

```bash
# 打 tag + push, CI 自动构建并上传 GitHub Release (asset 命名
# EnglishAssistant-{version}.apk, 与默认 glob 匹配), 客户端下次启动即可弹更新.
git tag v1.2.0
git push --tags
# 也可 Actions 页 "Run workflow" 手动指定 tag.
```

强制升级门槛: ``APP_MIN_SUPPORTED_VERSION=1.0.0`` 表示低于 1.0.0 的客户端必须升级,
弹窗无法关闭; 留空表示不强制.



## 项目结构

```
backend/
├── app/
│   ├── api/v1/           # 路由
│   ├── services/         # MiMo TTS / 讯飞 ISE / LLM / 评分
│   ├── models/           # Pydantic schema
│   ├── db/               # SQLAlchemy + Alembic
│   ├── config.py
│   └── main.py
├── tests/
├── data/                 # 语料 JSON
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

## API 端点

| Method | Path | 用途 | L1 |
|---|---|---|---|
| GET | `/api/v1/health` | 健康检查 | ✓ |
| GET | `/api/v1/lessons` | 课文列表 | ✓ |
| GET | `/api/v1/lessons/{id}/roles` | 角色台词 | ✓ |
| GET | `/api/v1/tts` | TTS 合成 | ✓ |
| POST | `/api/v1/score` | 评分（真实 ISE 逐词音素，输入 base64 PCM L16 16kHz）| ✓ |
| GET | `/api/v1/history` | 历史 | ✓ |
| POST | `/api/v1/history` | 写历史 | ✓ |
| POST | `/api/v1/dialogue/generate` | 自由对话开场 + 建议回答 | stub fallback / ready provider |
| POST | `/api/v1/dialogue/turn` | 多轮对话下一轮 + 建议回答 | stub fallback / ready provider |
| GET | /api/v1/llm/models | 自由对话可选模型目录（由后端 LLM 配置决定）| ✓ |
| GET | /api/v1/app/version | App 自动更新元数据 (latest/min 版本 + APK URL + 是否强制 + source=env\|github\|default) | ✓ |

**v2.0 新增**（明细契约见各 router 源码与 `.mimocode/tasks/T*/` 报告，示例 curl 见 docs/operations.md 冒烟清单）：

| Method | Path | 用途 |
|---|---|---|
| GET | `/scenes` `/scenes/{id}` `/scenes/{id}/script` | 情景课画廊/详情/剧本（8 门人工 + DB 生成课合并，DB 优先） |
| GET/DELETE | `/scenes/{id}` 生成物 · POST `/scenes/generate` · GET `/scenes/jobs/{job}` | 目标一句话→两段生成任务（jobs 轮询）/ 删除自产课 |
| POST | `/sessions` · `/sessions/{id}/step` `/skip-step` `/mission` `/hint` `/finish-mission` · GET `/sessions` `/sessions/{id}` | 任务通关闭环状态机（崩溃恢复、幂等、乐观锁） |
| GET | `/ability?days=7\|30\|90` | 能力画像（EWMA + 雷达 + 轨迹；stub 证据零写入） |
| GET/POST | `/assessment` `/assessment/{id}/start` `/answer` `/complete` | CEFR 7 题测评（批量 LLM 判级，题库 `data/assessment/bank.json`） |
| POST/GET/DELETE | `/polish` · `/expressions` | 语法润色 + 个人表达库（去重/TOCTOU/`source` 全保留） |
| GET | `/courses/progress` | 通关进度物化视图（attempts/cleared/best_total） |


## 测试

```bash
pytest                          # 全跑
pytest --cov=app --cov-fail-under=85
ruff check . && ruff format --check .
mypy app
```


## 练习流程一览（v2.1.0）

- **跟读模式**：后端课程台词按角色轮次交错后，客户端去掉角色标签，逐句展示最近五句；每句沿用 `/tts` + `/score`（≥60 过关）。
- **对话模式**：客户端将课程的角色 A/B 交错成完整对话，仅把角色 B 设为用户目标；点击「播放角色 A」后录制并评分角色 B。
- **影子跟读**：整课连播 + 全程录音（回声消除），按句切片逐句评分聚合成整课报告；录音可回放对比。
- **自由对话模式**（旧入口，保留）：`/dialogue/generate` 开场 + 建议回答；`/dialogue/turn` 下一轮 + 润色对照（v2.0 起同一次 LLM 调用返回判分与润色，识别文本直喂上下文）。未配置 LLM 时内置场景 fallback 保证 APK 流程可跑。
- **任务通关情景课**（v2.0 主打）：`/sessions` 状态机驱动「打基础四题型（跟读/复述/翻译/造句）→ 实战对话（任务清单：required 全达成才通关，AI 人设追问、提示可开关但计入代价）→ 复盘报告（总分+四维+亮点/改进+原话 vs 更好说法+能力增量）」。无凭据环境按诚实降级链路走通（source 标记 + 画像零写入）。
- **AI 生成课 / CEFR 测评 / 表达库 / 弱词训练**：见上方端点表；生成课走两段式 jobs，测评判级单次批量 LLM。
