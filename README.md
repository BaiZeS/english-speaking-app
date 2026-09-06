# English Speaking Assistant · 情境化英语口语练习 App

预存语料 + AI 动态生成场景，标准发音示范，APP 自动评分。**当前版本 v2.0.0**（见 [CHANGELOG.md](CHANGELOG.md)）。

## 项目状态

| 阶段 | 状态 |
|---|---|
| 设计 | ✅ Spec 已定（见 `docs/superpowers/specs/2026-07-11-english-speaking-app-design.md`）|
| Phase 1 基建 | ✅ 后端脚手架 + CI（backend-ci 全绿）|
| Phase 2 L1 MVP（K12 + 新概念 1 跟读）| ✅ 后端 9 端点 + 真实讯飞 TTS/ISE 评分 + Android 客户端完成，APK 由 CI 构建（android-ci 全绿）；⏳ 真机联调 |
| 三模式重构 | ✅ 跟读 / 角色对话 / 自由对话 Android 流程完成；自由对话无 LLM 凭据时使用确定性 fallback |
| LLM 自由对话 | ✅ 后端接入百炼 OpenAI 兼容端点 + `/llm/models` 目录端点；客户端设置页可选模型，未配置时自动降级 |
| 自动更新 | ✅ 后端 `/app/version` 元数据 + Android 启动拉取、版本对比、APK 流式下载 + FileProvider 安装（强升门槛支持）|
| 多本书籍 | ✅ `/books` 目录端点 + Android 首页下拉切换；`/dialogue/scenes` 暴露自由对话场景 |
| Dashboard | ✅ `/stats` 汇总接口 + Android 概览页：总练习 / 平均分 / 最高分 / 连续天数 / 14 天趋势图 / 分项平均 |
| 录音可视化 | ✅ AudioRecorder 暴露实时音量流 + 跟读页 LinearProgressIndicator 进度条 + 音量条 |
| 课前预览 + 错词高亮 | ✅ LessonDetail 加课文预览（首 3 句 + 角色分布柱）+ ScoreResult 每词按分数染色 chip |
| History 筛选 | ✅ 全部 / 练过 / 85+ / 60 以下 四种 filter chip |
| 模块化 PlayerScreen | ✅ 551 行单体拆为 Screen + Controls + ReadAlongView + DialogueView + ScorePanel 5 个文件 |
| 商务英语语料 | ✅ `data/business/` 6 课（会议/汇报/谈判/接待宴请/电话会议/风险沟通），默认书籍 |
| 多书隔离 | ✅ 路由/历史/进度按 (book, lesson) 隔离（history 表加 book 列，Alembic 迁移）；Android 全链路贯通 |
| 商务自由对话场景 | ✅ 商务会议/工作汇报/商务谈判 3 个场景（共 9 个），选择器默认商务会议 |
| 评分真假可辨 | ✅ /score 与 /tts 返回 `source` 字段；未配凭据时客户端显示"占位假分/假音频"警示 |
| 影子跟读 | ✅ 整段连续影子跟读：全文音频连播 + 全程录音（AEC/VOICE_COMMUNICATION）+ 按句切片逐句评分聚合；录音保留可回放对比（听我的/对比听） |
| 自由对话真实转写 | ✅ 讯飞 IAT 听写接入 `/dialogue/turn`：识别用户实际说的话，替换占位符并喂给 LLM（无凭据自动回退占位行为） |
| 弱词专项训练 | ✅ 评分 <70 词自动入弱词本（Room），训练页：示范→跟读单词（ISE read_word）→≥85 毕业 |
| 评分语速修复 | ✅ 语速按真实音频时长计算（原固定 4s 窗口）；/score 支持 category=read_word |
| **v2.0 后端（P1–P4）** | ✅ 情景课内容层（8 门人工剧本 + 文件缓存读路径）、会话状态机（崩溃可恢复）、打基础四题型评分、任务制实战 + 单次 LLM 复盘报告、两级 AI 生成课（jobs 轮询）、CEFR 测评、EWMA 能力画像（stub 证据门控）、/polish、/expressions、/courses/progress |
| **v2.0 Android（P5–P7）** | ✅ 四 Tab 信息架构（首页/课程/词汇/我的）重构、情景课全流程屏（画廊→打基础→实战→复盘→生成）、测评流程、能力雷达 + 轨迹（Canvas）、表达库、今日推荐联动画像 |
| **v2.0.0 收尾（P8）** | ✅ 全链验证：alembic 空库 SQLite/PG16 双向可逆、双 CI 绿、500+ 后端测试 + 168 JVM 测试；死代码清除、协议去魔法字符串、OTA 非强更语义固化 |

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
- **后端**：Python 3.11 + FastAPI + PostgreSQL 16（Redis 已随 v2.0 清理移除——TTS 走磁盘缓存）
- **AI 服务**：MiMo TTS（语音合成）+ 讯飞 ISE（语音评测，逐词音素评分）+ OpenAI/阿里（备选 LLM）
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
docker compose up -d postgres          # 起 Postgres（唯一外部依赖）
uv sync --frozen --extra dev           # 装依赖（用锁定的 uv.lock）
uv run alembic upgrade head            # 跑数据库迁移
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
> `--host 0.0.0.0` 必须加，模拟器（`10.0.2.2`）/ 真机（局域网 IP）才能连上。
> MiMo TTS + 讯飞 ISE 已接入：配 `.env` 凭据后走真实合成 + 逐词评分；未配则自动 fallback 到 stub，仍可跑通跟读闭环。

### 3. Android 客户端

发布通道（诚实版，v2.0.0 起）：

- **正式 OTA**：在 GitHub 上发 **Release**（tag `v2.0.0`，挂 APK asset）后，
  旧客户端打开 App 即可经 `/app/version` 检测到新版本并应用内下载安装；
  提示可「稍后再说」，**不强制**（仅当服务端显式配置 `APP_MIN_SUPPORTED_VERSION`
  才会进入不可跳过分支）。
- **生产后端部署**：主实例公网 `http://118.89.58.84:5173/api/v1/`（库为本机
  docker postgres 的专用库 `english_prod_5173`，起停见 `~/english-backend-deploy.sh`）。
  v2.1.0 起 release 包内置 URL 即指 :5173，真机开箱即用。
  同机另有 `:8000` 桥接实例（同码同库，服务 ≤2.0.0 旧包内置地址），但云防火墙
  当前未映射 8000——旧包若要远程 OTA，需二选一：① 在防火墙控制台加 TCP:8000
  映射到本机；② 直接给旧设备装一次 v2.1.0 APK（GitHub Releases 直链），此后
  升级走 :5173 全自动。
- **调试包**：Actions → 最新绿色 `Android CI` run → Artifacts → `app-debug`
  （仅 debug 签名，过期 90 天，别当分发渠道）。
- 仓库里的 `apk/` 目录只是本机临时副本位（`*.apk` 已 gitignore、**无提交内容**），
  不是下载入口。

装机后：**模拟器**保持默认后端 URL `http://10.0.2.2:8000/api/v1/`；**真机**进 App「设置」页改成 `http://<电脑局域网IP>:8000/api/v1/`（支持运行时改，无需重新打包）。客户端直接录 PCM L16 16kHz，提交后端走真实 ISE 逐词评分。

## 文档

- [设计文档](docs/superpowers/specs/2026-07-11-english-speaking-app-design.md)
