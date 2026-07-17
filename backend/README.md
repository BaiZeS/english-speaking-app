# English Speaking Assistant · Backend

FastAPI 后端，提供语料、TTS、ISE 语音评测、历史等 API。

## 快速开始

> 讯飞 TTS（在线合成）与 ISE（语音评测，逐词音素评分）已接入。配 `.env` 凭据即走真实服务；
> 未配凭据时自动 fallback 到 stub，课程列表 / 录音评分 / 历史的完整闭环仍可跑通。

### 1. 起依赖（Postgres + Redis）

```bash
# Postgres（用项目自带的 docker-compose，凭据 english/english，库 english_dev）
docker compose up -d postgres

# Redis：需本机有 redis-server 监听 6379
#   检查：redis-cli ping  ->  PONG
#   没有则装一个：apt install redis-server && systemctl start redis
```

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

### 讯飞凭据（可选，配了走真实服务）

不配也能跑（fallback 到 stub）。要真实 TTS 发音 + ISE 逐词评分，在 `backend/.env` 填：

```
XUNFEI_APP_ID=...
XUNFEI_API_KEY=...
XUNFEI_API_SECRET=...
# 可选（覆盖默认值）
XUNFEI_TTS_DEFAULT_VCN=x5_EnUs_Grant_flow      # 默认发音人 (美式英文女, 超拟人)
XUNFEI_TTS_VOICES=x5_EnUs_Grant_flow,x5_EnUs_Lila_flow  # App「设置」页可选发音人列表
XUNFEI_SPARK_TTS_PASSWORD=ak-xxx                   # 超拟人控制台拿 APIPassword
```

- **超拟人 TTS (主)**：Spark 大模型合成, 24kHz mp3, 自动句末 [p300] 停顿, 按 (text, voice) 落盘缓存 (`static/tts/`, 同文本复用, 省配额).
- **v2 老接口 (fallback)**：仅在 Spark 凭据缺失或调用失败时启用, 音色机械不推荐.
- **ISE 评分**：提交 PCM（16kHz L16 mono）后走语音评测，返回 0-100 的 total/pronunciation/fluency/completeness + 每词 `word_details`（含 `score` 与 `ipa` 音素）。原始评分 1-5 → 映射到 0-100。

### 备选：Docker Compose 一键起全部

```bash
docker compose up -d        # 起 postgres + redis + api 容器
# API: http://localhost:8000   Docs: http://localhost:8000/docs
```

> 注意：`api` 服务会 `build .`（需 Dockerfile）。本地开发推荐用上面的 `uv run` 方式，更快、改代码即时生效。


### 自由对话 LLM（可选，配了走真实生成）

未配置 LLM 时, /dialogue/* 走内置 deterministic fallback (4 个场景的开场白 + 建议回答);
配置后会自动调用 OpenAI 兼容端点生成开场与每一轮回答. 默认指向阿里云百炼 Maas:



前端会从 GET /api/v1/llm/models 拉取模型清单, 用户在设置页选择具体 model_id,
下次自由对话请求会透传到后端. 后端调用失败会自动降级回 stub, 不会让 APK 流程中断.

### App 自动更新

App 启动时会拉取 GET /api/v1/app/version 比较版本号, 有新版本弹更新对话框
(强制升级时强制弹窗). 服务端配置:



## 项目结构

```
backend/
├── app/
│   ├── api/v1/           # 路由
│   ├── services/         # 讯飞 / LLM / 评分
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
| GET | /api/v1/app/version | App 自动更新元数据（最新版本、APK URL、是否强制升级）| ✓ |


## 测试

```bash
pytest                          # 全跑
pytest --cov=app --cov-fail-under=85
ruff check . && ruff format --check .
mypy app
```


## 三种练习流程

- **跟读模式**：后端课程台词按角色轮次交错后，客户端去掉角色标签，逐句展示最近五句；每句沿用 `/tts` + `/score`。
- **对话模式**：客户端将课程的角色 A/B 交错成完整对话，仅把角色 B 设为用户目标；点击「播放角色 A」后录制并评分角色 B。
- **自由对话模式**：先调用 `/dialogue/generate` 获得 AI 开场和建议回答；用户自由录音后用建议回答作为评分参考，再调用 `/dialogue/turn` 获取下一轮。未配置 LLM 时使用内置场景 fallback，保证 APK 流程可联调。
