# English Speaking Assistant · Backend

FastAPI 后端，提供语料、TTS、ASR 评分、历史等 API。

## 快速开始

### 1. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入讯飞等凭据
```

### 2. 起服务（Docker Compose）
```bash
docker compose up -d
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 3. 本地开发（无 Docker）
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 需本机起 postgres + redis（或只跑 health 端点）
uvicorn app.main:app --reload
```

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
| POST | `/api/v1/score` | 评分 | ✓ |
| GET | `/api/v1/history` | 历史 | ✓ |
| POST | `/api/v1/history` | 写历史 | ✓ |
| POST | `/api/v1/dialogue/generate` | 场景生成 | stub |
| POST | `/api/v1/dialogue/turn` | 多轮对话 | stub |

## 测试

```bash
pytest                          # 全跑
pytest --cov=app --cov-fail-under=85
ruff check . && ruff format --check .
mypy app
```
