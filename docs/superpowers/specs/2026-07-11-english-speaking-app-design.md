# 情境化英语口语练习 App — 设计文档

| 项目 | 内容 |
|---|---|
| 日期 | 2026-07-11 |
| 状态 | 设计稿，待用户 review |
| 范围 | MVP = K12 模式 + 新概念英语第一册 跟读（端到端）；其余 8 个场景预留页面与 API |

---

## 1. 背景与目标

### 1.1 问题
传统英语学习 App 普遍存在三个问题：
1. 内容静态，用户被动接收
2. 缺少情境化、对话式的真实练习
3. 口语反馈粗放，无法定位单词级薄弱点

### 1.2 目标
构建一款**情境化英语口语练习 Android App**：
- **预存语料 + AI 动态补足**：新概念 1-3 册课内素材；场景对话由 LLM 动态生成
- **自动切分角色**：单段录音/文本按 `A:` `B:` 等标记拆分为多角色台词
- **标准发音示范**：TTS 提供标准音；字幕或画面引导
- **自动评分**：发音、流利度、完整度、内容多维评估，输出改进建议

### 1.3 三大场景
1. **新概念英语跟读**（L1 MVP）：逐句播放标准音 → 用户跟读 → 单词级评分
2. **新概念英语对话**（L2 占位）：角色 A/B 轮替练习
3. **场景对话**（L2 占位）：选场景（点餐/面试/旅行等）→ LLM 生成角色 → 自由对话 + LLM 评分

### 1.4 三类用户模式
- **K12 启蒙**：卡通 UI、TTS 慢速、评分宽松、玩法向游戏化靠拢
- **高中/成人应试**：跟读打分严格、单词级音素反馈、对标考试口语
- **成人口语提升**：重表达流利度与内容评分，而非逐音素纠错

模式在登录/首次启动时选定，影响 UI 风格、语料筛选、评分参数。

---

## 2. 范围

### 2.1 MVP（L1 完整实现）
- K12 用户模式
- 新概念英语第一册（简称"新概念 1"）第 1 课 跟读场景
- 端到端：列表 → 角色分镜 → 播放器（TTS + 录音 + 评分）→ 历史

### 2.2 L2 占位
- 其余 8 个组合（K12 对话、K12 场景、应试 ×3、成人 ×3）= 9 个场景入口全部有页面
- 9 个 API 端点全部定义、签名稳定
- 点入未实现场景 → 占位页 + mock 数据
- 函数签名、数据库 schema、API 契约在 L1 阶段统一确定

### 2.3 L3 留扩展点
- 账号体系（当前用设备 ID 区分）
- 崩溃上报、性能监控
- 付费/会员
- 上架 Play Store

### 2.4 不在范围
- iOS 客户端
- Web 独立站
- 离线模式（仅离线缓存课文，已下载音频不算）

---

## 3. 架构

### 3.1 总体架构

```
┌─────────────────┐         ┌──────────────────┐
│  Android APP    │         │  FastAPI 后端     │
│  (Kotlin +      │ HTTPS   │  (Python 3.11)   │
│   Compose)      │◄───────►│                  │
│                 │         │  - 语料 API       │
│  - 课文列表     │         │  - 录音接收       │
│  - TTS 播放器   │         │  - 讯飞 ASR 代理  │
│  - 录音机       │         │  - 评分计算       │
│  - 评分展示     │         │  - 历史存储       │
│  - 历史记录     │         │                  │
└────────┬────────┘         └────────┬─────────┘
         │                            │
         ▼                            ▼
   ┌──────────┐                ┌────────────┐
   │真机/模拟器│                │讯飞 / OpenAI│
   │装 GH      │                │/ 阿里 LLM  │
   │Action 出的│                │            │
   │APK       │                │            │
   └──────────┘                └────────────┘
```

**关键约束**：
- 客户端**不直连**讯飞/OpenAI（密钥、计费、限流集中后端管理）
- 后端用 PostgreSQL 存语料和打分历史，Redis 缓存 TTS 音频

### 3.2 客户端模块

```
com.app.english/
├── ui/                          # 全部 Activity / Fragment / Compose
│   ├── home/                    # 主页：模式选择 + 最近学习
│   ├── mode/                    # 三种模式入口（K12/应试/成人）
│   ├── scenario/                # 三种场景入口（跟读/对话/场景对话）
│   ├── library/                 # 语料库（按册/课/角色）
│   ├── player/                  # 播放器：TTS + 字幕 + 录音 + 评分展示
│   ├── history/                 # 历史记录
│   ├── settings/                # 设置
│   └── placeholder/             # 未实现场景的统一占位页
├── domain/                      # 业务逻辑（不依赖 Android）
│   ├── model/                   # User, Lesson, Role, Score
│   ├── repository/              # 接口定义
│   └── usecase/                 # 业务用例
├── data/
│   ├── remote/                  # Retrofit API client
│   ├── local/                   # Room DB（缓存、离线历史）
│   └── repository/              # 接口实现
├── audio/                       # 录音 / TTS 播放
└── di/                          # Hilt 依赖注入
```

### 3.3 后端模块

```
backend/
├── app/
│   ├── api/v1/
│   │   ├── lessons.py           # GET /lessons?book=&lesson=
│   │   ├── tts.py               # POST /tts → 音频 URL
│   │   ├── score.py             # POST /score → 评分（核心）
│   │   ├── dialogue.py          # POST /dialogue/generate（场景对话，L2）
│   │   ├── dialogue_turn.py     # POST /dialogue/turn（多轮，L2）
│   │   ├── history.py           # GET/POST /history
│   │   └── health.py
│   ├── services/
│   │   ├── xunfei_asr.py        # 讯飞 ASR 封装
│   │   ├── xunfei_tts.py        # 讯飞 TTS 封装
│   │   ├── llm_service.py       # OpenAI/阿里 LLM 抽象
│   │   ├── scoring/
│   │   │   ├── read_along.py    # L1 跟读评分
│   │   │   ├── dialogue.py      # L2 角色对话评分
│   │   │   └── scenario.py      # L2 场景对话评分
│   │   └── corpus_loader.py     # 预存语料加载
│   ├── models/                  # Pydantic schema
│   ├── db/                      # SQLAlchemy + Alembic
│   ├── config.py                # Settings（pydantic-settings）
│   └── main.py
├── data/                        # 语料 JSON
│   └── nce1/lesson_001.json
├── tests/
└── pyproject.toml
```

### 3.4 共享契约
- OpenAPI 3.1 spec 由 FastAPI 自动生成（`/docs`）
- 客户端用 `openapi-generator-cli` 生成 Kotlin model
- 改 API → 重生成 → 不手抄

---

## 4. 数据流（L1 跟读端到端）

```
[1] APP: HomeScreen
    用户点 "K12 模式" → 跳 LessonListScreen
    GET /api/v1/lessons?book=nce1&level=k12
    → 200 [{id, title, role_count, duration_s, thumbnail}]

[2] APP: LessonListScreen
    用户点 Lesson 1 → 跳 RoleListScreen
    GET /api/v1/lessons/{id}/roles
    → 200 [{role: "A", lines: [...]}, {role: "B", lines: [...]}]

[3] APP: PlayerScreen  (K12+跟读，L1 完整实现)
    a) 加载课文 + 角色高亮
    b) TTS 播放标准音
       GET /api/v1/tts?text=...&voice=k12_female
       → 200 {audio_url, duration_ms}  (后端代理讯飞 TTS，URL 短时签名)
    c) 用户点 🔴 录音 (最长 30s)
       MediaRecorder → m4a
    d) 用户点 ⏹ 停止 → 自动调评分
       POST /api/v1/score (multipart: audio=m4a, lesson_id, line_id, ref_text, mode=k12)
       → 200 {
            total: 87,
            pronunciation: 90,
            fluency: 85,
            completeness: 88,
            word_details: [{word, score, ipa}],
            suggestion: "..."
          }
    e) 显示分数 + 单词级高亮 (绿/黄/红)
    f) 写本地 Room 历史 + 后端备份
       POST /api/v1/history (异步，失败可重试)

[4] APP: 用户继续下一句 / 重录 / 返回
```

### 4.1 错误流

| 触发 | 处理 |
|---|---|
| 网络断 | 录音暂存本地，恢复后重试评分 |
| ASR 超时（讯飞 5s 没回）| "未听清，请重试" + 重录按钮 |
| 评分 < 60 | 标记"需重读"，限制跳到下一句前必须重录一次 |
| API 4xx/5xx | Snackbar 提示 + 不阻塞 UI；写日志 |
| 录音权限拒绝 | 引导到系统设置 |

### 4.2 L2 场景占位流
- **NCE 对话**：A→用户→B→用户 轮转，UI 显示头像气泡；`POST /dialogue/turn` 暂返回 mock 文案
- **场景对话**：选场景 → LLM 生成角色 → 自由对话；`POST /dialogue/generate` + `POST /dialogue/turn` 调 LLM 流式

---

## 5. 评分设计

### 5.1 三套评分

| 场景 | 输入 | 维度 | 实现 |
|---|---|---|---|
| 跟读 (L1) | 用户音频 + 参考文本 | pronunciation / fluency / completeness / word-level | 讯飞 ASR 拿词级置信度 + 字符串相似度加权 |
| NCE 对话 (L2) | 用户音频 + 期望角色台词 | pronunciation + content match | 跟读基础上加 LLM 判定内容匹配度 |
| 场景对话 (L2) | 用户音频 + 上下文 | pronunciation + fluency + semantic relevance | LLM 评分（GPT-4 / 豆包） |

### 5.2 跟读评分算法（L1 重点）
```
total = 0.5 * pronunciation
      + 0.3 * fluency
      + 0.2 * completeness

pronunciation = mean(word_scores from 讯飞)   # 0-100
fluency       = speech_rate * 0.4 + pause_penalty * 0.6
completeness  = len(recognized_words) / len(ref_words) * 100
```

### 5.3 反馈
- 单词级高亮（绿 ≥85、黄 60-84、红 <60）
- 整体建议（"注意 th 的咬舌音" / "流利度不错，继续"）— 后期 LLM 生成

---

## 6. 数据模型

### 6.1 语料（JSON 文件 + DB 索引）
```json
{
  "book": "nce1",
  "lesson": 1,
  "title": "A Private Conversation",
  "roles": [
    {
      "name": "A",
      "lines": [
        {"id": "L1-001-A", "text": "Excuse me, is this your handbag?", "translation": "..."}
      ]
    }
  ]
}
```

### 6.2 数据库表（PostgreSQL）

| 表 | 字段 |
|---|---|
| `users` | id (uuid), device_id, mode (k12/exam/adult), created_at |
| `lessons` | id, book, lesson_no, title, role_count, duration_s |
| `history` | id, user_id, lesson_id, line_id, audio_path, score_total, score_pronunciation, score_fluency, score_completeness, created_at |
| `tts_cache` | cache_key (text+voice+version), audio_path, hit_count, expires_at |

### 6.3 客户端 Room 缓存
- `lessons`, `history`（离线可看）
- `tts_cache`（同后端，URL 签名短时有效）

---

## 7. API 设计

| Method | Path | 用途 | L1 状态 |
|---|---|---|---|
| GET | `/api/v1/lessons` | 课文列表 | 实现 |
| GET | `/api/v1/lessons/{id}/roles` | 角色台词 | 实现 |
| GET | `/api/v1/tts` | TTS 合成 | 实现 |
| POST | `/api/v1/score` | 评分 | **实现（核心）** |
| GET | `/api/v1/history` | 历史 | 实现 |
| POST | `/api/v1/history` | 写历史 | 实现 |
| POST | `/api/v1/dialogue/generate` | 场景生成 | stub |
| POST | `/api/v1/dialogue/turn` | 多轮对话 | stub |
| GET | `/api/v1/health` | 健康检查 | 实现 |

---

## 8. 技术栈

### 8.1 客户端（Android）

| 类别 | 选型 | 版本 |
|---|---|---|
| 语言 | Kotlin | 2.0 |
| UI | Jetpack Compose | BOM 2024.10 |
| 最低 SDK | 26 (Android 8.0) | - |
| 目标 SDK | 34 (Android 14) | - |
| 架构 | MVVM + Clean | - |
| DI | Hilt | 2.51 |
| 网络 | Retrofit + OkHttp | 2.11 / 4.12 |
| 序列化 | kotlinx.serialization | 1.7 |
| 异步 | Kotlin Coroutines + Flow | 1.8 |
| 本地存储 | Room | 2.6 |
| 音频录制 | MediaRecorder | - |
| 音频播放 | ExoPlayer | 1.4 |
| 导航 | Navigation Compose | 2.8 |
| 权限 | Accompanist Permissions | 0.34 |
| 日志 | Timber | 5.0 |

**包大小预估**：L1 完整 ≈ 8-12 MB；L2 全部接上 ≈ 30-50 MB

### 8.2 后端（Python）

| 类别 | 选型 | 版本 |
|---|---|---|
| 语言 | Python | 3.11 |
| Web 框架 | FastAPI | 0.115 |
| ASGI 服务器 | Uvicorn | 0.32 |
| 校验 | Pydantic | 2.9 |
| 配置 | pydantic-settings | 2.6 |
| ORM | SQLAlchemy 2.0 (async) | 2.0.36 |
| DB 驱动 | asyncpg | 0.30 |
| 迁移 | Alembic | 1.13 |
| DB | PostgreSQL | 16 |
| 缓存 | Redis | 7 |
| HTTP 客户端 | httpx | 0.27 |
| LLM 客户端 | openai-python | 1.54 |
| 测试 | pytest + httpx.AsyncClient | 8.3 |
| 容器 | Docker + docker-compose | - |
| 日志 | loguru | 0.7 |

### 8.3 开发工具链

| 用途 | 工具 |
|---|---|
| 代码 | VS Code / Android Studio（远程） |
| 版本控制 | Git + GitHub |
| CI | GitHub Actions（Android 出 APK + Python lint/test）|
| API 契约 | OpenAPI 3.1 → openapi-generator → Kotlin model |
| **设计稿** | **web-design-engineer 出 HTML 原型 → review → 移植 Compose** |

### 8.4 环境变量（后端 `.env`）

```
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://localhost:6379/0
XUNFEI_APP_ID=...
XUNFEI_API_KEY=...
XUNFEI_API_SECRET=...
OPENAI_API_KEY=...           # 备选
ALIYUN_DASHSCOPE_KEY=...     # 备选
TTS_CACHE_TTL=86400
```

---

## 9. 测试与质量

### 9.1 客户端

| 层级 | 工具 | 覆盖目标 |
|---|---|---|
| 单元 | JUnit 5 + MockK | domain/usecase ≥ 90% |
| ViewModel | Turbine + Coroutines Test | state 流转 |
| Compose UI | Compose UI Test | 关键页面 |
| API mock | MockWebServer | 离线测客户端逻辑 |

**关键 L1 用例**：
- 录音 → mock API 200 → 分数正确显示
- 录音 → mock API 超时 → 友好错误
- 权限拒绝 → 引导页跳转
- 离线 → 历史可看、API 自动重试

### 9.2 后端

| 层级 | 工具 | 覆盖目标 |
|---|---|---|
| 单元 | pytest | services ≥ 90% |
| API 集成 | pytest + httpx.AsyncClient | 全部端点 |
| 评分算法 | pytest + 样例音频 | 关键 case 100% |
| 合约 | schemathesis | CI 跑 |

**关键 L1 用例**：
- `/score` 正常：完美发音 → 95+；明显错误 → < 60
- `/score` 异常：空音频 / 超长 / 乱码文本
- `/tts` 缓存命中 vs miss
- 讯飞 mock 失败 → 500 + 日志完整

### 9.3 CI 矩阵

| Job | 触发 | 内容 |
|---|---|---|
| `android-lint` | push | ktlint + detekt |
| `android-test` | push | unit + UI test + assembleDebug |
| `android-apk` | main | build release APK + 上传 artifact |
| `backend-lint` | push | ruff + mypy |
| `backend-test` | push | pytest + coverage |
| `contract-test` | push | OpenAPI 一致性 + schemathesis |

### 9.4 质量门
- Lint 不过 → 不能 merge
- 单测覆盖率：客户端 ≥ 70%、后端 ≥ 85%
- APK > 15MB → 告警

### 9.5 手动验收
- 3 模式切换正常
- 9 场景入口都能进（占位页"敬请期待"）
- L1 跟读真机跑通
- 弱网/无网降级
- 杀进程后历史还在

---

## 10. 实施分期

### Phase 1 — 基建（MVP 启动前 1-2 天）
1. 初始化 GitHub repo
2. GitHub Actions workflow（Android lint + test + APK）
3. 后端 docker-compose（Postgres + Redis + FastAPI）
4. OpenAPI 自动生成 → Kotlin model 跑通

### Phase 2 — L1 跟读 MVP
1. 后端：DB 迁移、语料 loader、9 个端点骨架（其中 7 个 L1 实现：lessons / roles / tts / score / history GET+POST / health；2 个 L2 stub：dialogue/generate + dialogue/turn）
2. 后端：讯飞 ASR/TTS 接入 + 跟读评分算法
3. 客户端：用 web-design-engineer 出 HTML 原型（9 个核心页面：Home / ModeSelect / LessonList / RoleList / Player / History / Settings / Placeholder / Onboarding）→ review
4. 客户端：移植到 Compose + 实现 L1 跟读闭环
5. 联调：真机/模拟器完整跑通

### Phase 3 — L2 填场景
- 按优先级接 NCE 2/3、对话、场景对话
- 评分算法分场景补全

### Phase 4 — L3 收口
- 账号、付费、上架

---

## 11. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 讯飞 API 配额/费用超限 | 中 | L1 阶段本地缓存 + 用量监控；L2 评估按需扩容 |
| 评分算法主观性（用户对分数不满）| 中 | 初期给区间而非精确数字；收集反馈调权重 |
| 新概念语料版权 | 高 | 用户需提供正版资源；先做语料结构 + 1 课验证，版权问题留给用户 |
| LLM 场景对话不可控 | 中 | 后端用 prompt 模板 + 输出校验；前端给"重说"按钮 |
| GitHub Actions 构建时间 | 低 | 缓存 gradle/SDK；增量构建 |
| Android SDK 缺失 | 已解决 | 走 CI 零环境开发 |
| 网络不稳定（用户侧）| 中 | 客户端录音暂存 + 离线缓存课文；后端重试 |

---

## 12. 待用户确认事项

1. **新概念语料来源**：MVP 仅 1 课，用户需提供该课的文本 + 音频（或仅文本，TTS 生成）
2. **讯飞 API 凭据**：用户需注册讯飞开放平台并提供 APP_ID / API_KEY / API_SECRET
3. **GitHub repo 名称/位置**：约定在哪儿建仓
4. **首期目标时间窗**：用户期望 MVP 何时可用（影响 Phase 1-2 排期）
