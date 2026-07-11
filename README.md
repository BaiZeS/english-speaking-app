# English Speaking Assistant · 情境化英语口语练习 App

预存语料 + AI 动态生成场景，标准发音示范，APP 自动评分。

## 项目状态

| 阶段 | 状态 |
|---|---|
| 设计 | ✅ Spec 已定（见 `docs/superpowers/specs/2026-07-11-english-speaking-app-design.md`）|
| 仓库初始化 | 🚧 进行中 |
| Phase 1 基建 | ⏳ |
| Phase 2 L1 MVP（K12 + 新概念 1 跟读）| ⏳ |
| Phase 3 L2 场景填位 | ⏳ |

## 仓库结构

```
.
├── docs/                # 设计文档、规范
├── backend/             # Python FastAPI 后端（待建）
├── android/             # Android Kotlin 客户端（待建）
└── .github/workflows/   # CI 配置（待建）
```

## 技术栈

- **客户端**：Kotlin 2.0 + Jetpack Compose + Hilt + Retrofit + Room
- **后端**：Python 3.11 + FastAPI + PostgreSQL 16 + Redis 7
- **AI 服务**：讯飞（主，ASR/TTS）+ OpenAI/阿里（备选 LLM）
- **CI**：GitHub Actions（零环境开发，本机不装 Android SDK）

## 快速开始

### 1. 克隆仓库
```bash
git clone git@github.com:BaiZeS/english-speaking-app.git
cd english-speaking-app
```

### 2. 后端（待 Phase 1 完善后）
```bash
cd backend
docker compose up -d
```

### 3. Android 客户端
APK 由 GitHub Actions 自动构建，下载路径：
> Actions → 选择 workflow run → Artifacts → `app-debug.apk`

## 文档

- [设计文档](docs/superpowers/specs/2026-07-11-english-speaking-app-design.md)
