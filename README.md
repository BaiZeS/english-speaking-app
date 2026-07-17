# English Speaking Assistant · 情境化英语口语练习 App

预存语料 + AI 动态生成场景，标准发音示范，APP 自动评分。

## 项目状态

| 阶段 | 状态 |
|---|---|
| 设计 | ✅ Spec 已定（见 `docs/superpowers/specs/2026-07-11-english-speaking-app-design.md`）|
| Phase 1 基建 | ✅ 后端脚手架 + CI（backend-ci 全绿）|
| Phase 2 L1 MVP（K12 + 新概念 1 跟读）| ✅ 后端 9 端点 + 真实讯飞 TTS/ISE 评分 + Android 客户端完成，APK 由 CI 构建（android-ci 全绿）；⏳ 真机联调 |
| 三模式重构 | ✅ 跟读 / 角色对话 / 自由对话 Android 流程完成；自由对话无 LLM 凭据时使用确定性 fallback |
| LLM 自由对话 | ✅ 后端接入百炼 OpenAI 兼容端点 + `/llm/models` 目录端点；客户端设置页可选模型，未配置时自动降级 |
| 自动更新 | ✅ 后端 `/app/version` 元数据 + Android 启动拉取、版本对比、APK 流式下载 + FileProvider 安装（强升门槛支持）|

## 仓库结构

```
.
├── docs/                # 设计文档、规范
├── backend/             # Python FastAPI 后端
├── android/             # Android Kotlin 客户端
└── .github/workflows/   # CI（backend-ci + android-ci）
```

## 技术栈

- **客户端**：Kotlin 2.0 + Jetpack Compose + Hilt + Retrofit + Room
- **后端**：Python 3.11 + FastAPI + PostgreSQL 16 + Redis 7
- **AI 服务**：讯飞（主，TTS 在线合成 + ISE 语音评测，逐词音素评分）+ OpenAI/阿里（备选 LLM）
- **CI**：GitHub Actions（零环境开发，本机不装 Android SDK）

## 快速开始

### 1. 克隆仓库
```bash
git clone git@github.com:BaiZeS/english-speaking-app.git
cd english-speaking-app
```

### 2. 后端
详见 [`backend/README.md`](backend/README.md)。简要：
```bash
cd backend
docker compose up -d postgres          # 起 Postgres（Redis 需本机 6379）
uv sync --frozen --extra dev           # 装依赖（用锁定的 uv.lock）
uv run alembic upgrade head            # 跑数据库迁移
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
> `--host 0.0.0.0` 必须加，模拟器（`10.0.2.2`）/ 真机（局域网 IP）才能连上。
> 讯飞 TTS/ISE 已接入：配 `.env` 凭据后走真实合成 + 逐词评分；未配则自动 fallback 到 stub，仍可跑通跟读闭环。

### 3. Android 客户端
APK 由 GitHub Actions 自动构建（最新绿色 run 见 Actions 页），下载路径：
> Actions → 选择 workflow run → Artifacts → `app-debug`

也可直接用仓库内本地副本 `apk/app-debug.apk`（gitignored，需手动同步到最新 run）。

装机后：**模拟器**保持默认后端 URL `http://10.0.2.2:8000/api/v1/`；**真机**进 App「设置」页改成 `http://<电脑局域网IP>:8000/api/v1/`（支持运行时改，无需重新打包）。客户端直接录 PCM L16 16kHz，提交后端走真实 ISE 逐词评分。

## 文档

- [设计文档](docs/superpowers/specs/2026-07-11-english-speaking-app-design.md)
