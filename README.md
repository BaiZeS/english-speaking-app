# English Speaking Assistant · 情境化英语口语练习 App

预存语料 + AI 动态生成场景，标准发音示范，APP 自动评分。**当前版本 v2.2.1**（见 [CHANGELOG.md](CHANGELOG.md)；生产部署与发版 SOP 见 [docs/operations.md](docs/operations.md)，App 使用指南见 [docs/usage-guide.md](docs/usage-guide.md)）。

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
| 录音可视化 | ✅ 实时声量脉冲条 `RecordingPulseMeter`（← `AudioRecorder.levelFlow` VU 包络，v2.2.1 起替换滚动波形）+ 评分反馈卡中性化（ScoreRing 分数环 / 子分进度条 / 染色逐词芯片）|
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
| **v2.0.0 收尾（P8）** | ✅ 全链验证：alembic 空库 SQLite/PG16 双向可逆、双 CI 绿、500+ 后端测试 + 168 JVM 测试（**该口径止于 v2.0.0**，当前基线见下一行与 android/README.md）；死代码清除、协议去魔法字符串、OTA 非强更语义固化 |
| **v2.1.0 生产中继（OTA 通道）** | ✅ release 包内置地址切 `:5173`（versionCode 8）；`/static/apk` 自托管分发 + `publish_apk.sh` 一条命令完成发版收尾（GitHub 出口仅 ~10-40KB/s，自托管走服务器出口）；`:8000` 桥退役；运维护栏脚本 + 双实例日志 + 冒烟命令全套（docs/operations.md）|
| **v2.2.1 两个样式真机反馈** | ✅ 录音条改实时声量脉冲条（5 根随当前音量跳动、松手定格峰值）+ 打基础/跟读/自由对话评分反馈卡中性化重做（分数环 + 子分进度条 + 染色逐词芯片）；删除滚动波形管线（RecordingWaveform/WaveformHistory，编译器强制迁移）。非强更、后端零改动。基线：Android **318** JVM 单测全绿；⏳ v2.2.1 真机验收尚未执行 |
| **v2.2.0 五个真机症状 + 交付闭环** | ✅ 长按/点按两种录音手势按取句长短分派（共享件 `HoldToTalkRow`/`TapToTalkRow`）+ **真滚动波形**（`RecordingWaveform` / 纯环形缓冲 `WaveformHistory`）+ 打基础逐题**完整即时反馈**（五维子分/逐词 IPA/转写/建议，≥85 停留 5s 自动前进）+ 收工改 **202 + `review_status` 轮询**（总评不再超时）+ 复盘报告回得去（「查看上次复盘」/「最近复盘」）+ 中文错误码表。后端**零迁移**、新增同步 LLM 时延契约表与 `test_latency_budget.py`；CI 新增 **`release-gate`**：改 `android/app/src/main/**` 却不同范围 bump `versionCode` + `CHANGELOG.md` 直接红（`2fd067d` 那批修复卡在 main 上从没上过手机，就是这条要防的病）。基线：Android **327** JVM 单测 / 后端 **573** 测试全绿；⏳ **v2.2.0 真机验收尚未执行** |

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
- **AI 服务**：MiMo TTS（语音合成，已启用真合成）+ 讯飞 ISE（语音评测，逐词音素评分）+ 讯飞 IAT（英文听写）+ 阿里云百炼 OpenAI 兼容端点（LLM：实战对话/判分/课程生成/测评判级，本机现役模型 `qwen3.8-flash`，详见 backend README「LLM」节与 [docs/operations.md](docs/operations.md)）
- **CI**：GitHub Actions（backend-ci + android-ci + release.yml 打 tag 自动出 APK）。`android-ci` 的四个 job：`release-gate`（**改了 `android/app/src/main/**` 就必须同范围 bump `versionCode` + 写 `CHANGELOG.md`**，否则红且挡住产物构建）→ ktlint → detekt(软) → testDebugUnitTest → assembleDebug。本部署机已装 Android SDK（`~/Android/Sdk`），改 Android 前本地跑 `./android/scripts/ktlint.sh` + `./gradlew testDebugUnitTest --no-daemon` 预验，CI 为最终权威。

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
> **仅限本机开发机**：这样的裸 uvicorn 不要在服务器（生产机）上跑——那台机器唯一的后端跑法是
> 发布栈容器（见下与 `docs/operations.md` §1；`deploy.sh` 的 legacy 裸进程子命令已于 2026-09-11
> 退役），宿主 `ps` 里"看起来像裸跑的 uvicorn"先按 §6.1 判别归属再动手。
> 另注意 dev compose 栈的宿主 8000/5432 已收紧为 `127.0.0.1:` 绑定，真机局域网直连只在
> 这条裸跑路上可用（见 backend/README）。
> MiMo TTS + 讯飞 ISE 已接入：配 `.env` 凭据后走真实合成 + 逐词评分；未配则自动 fallback 到 stub，仍可跑通跟读闭环。
>
> **发布版（任意服务器一键起）**：`cd backend && cp .env.example .env`（填口令/密钥）
> `&& mkdir -p static/tts static/apk && docker compose -f docker-compose.prod.yml up -d --build`
> ——api + postgres 全栈、空库自动全链迁移。详见 [`backend/README.md`](backend/README.md)「生产部署」与
> [`docs/operations.md`](docs/operations.md)。

### 3. Android 客户端

发布通道（诚实版，v2.0.0 起）：

- **正式 OTA**：push `v*` tag → `release.yml` 自动构建并发布 GitHub Release
  （`EnglishAssistant-<ver>.apk`，如 v2.2.0）。**发布后必须再在部署机跑一次
  `backend/scripts/publish_apk.sh <tag>`**：把 APK 拉到服务器 `static/apk/` 自托管
  并写 `.env` 的 `APP_LATEST_VERSION`/`APP_APK_URL`（`/app/version` 优先级 1）——
  服务器到 GitHub 资源站实测仅 ~10-40KB/s，不切自托管时手机 OTA 下载这 20 余 MB
  要约 10-30 分钟。旧客户端打开 App 即可检测到新版本并下载安装；
  提示可「稍后再说」，**不强制**（仅当显式配置 `APP_MIN_SUPPORTED_VERSION`
  才进入不可跳过分支）。
- **v2.2.0 是一次强制升级**：`POST /sessions/{id}/finish-mission` 在本版改成了
  **202 + `review_status`**、响应里的 `report` 字段**移除**（刻意不为旧包做兼容，见
  CHANGELOG v2.2.0）。因此发版时 `publish_apk.sh` 之外**还要**在 `backend/.env` 里
  显式设 `APP_MIN_SUPPORTED_VERSION=2.2.0`（`publish_apk.sh` 不写它，而 `/app/version`
  默认把 `min_supported_version` 停在 `0.0.0` 哨兵），否则未升级的 v2.1.0 包在新后端上
  收工会拿到空 `review`、要再点一次吃 409 才进复盘页。回滚 APK 时**必须同步**把它降回
  `0.0.0`。步骤与门禁见 [docs/operations.md](docs/operations.md) 第 3 节。
- **生产后端部署**：主实例公网 `http://118.89.58.84:5173/api/v1/`，运行于
  `backend/docker-compose.prod.yml` 发布栈（容器 `english-api-prod` +
  `english-postgres-prod`，库 `english_prod_5173`@独立卷 `english-prod-pgdata`；
  起停/迁移/日志见 `backend/scripts/deploy.sh`）。v2.1.0 起 release 包内置 URL
  即指 :5173，真机开箱即用。
  `:8000` 桥接已停止（云防火墙未映射公网，旧包外网不可达、也无必要）——
  （史实备查：当年真正绑宿主 8000 的是裸进程实例；今天的宿主 8000 只属 dev 栈的
  `127.0.0.1` 发布口，与公网、与生产容器都无关——证据与来龙去脉见 CHANGELOG 2026-09-11
  「运维拓扑收敛」条与 docs/operations.md §6.1。）
  旧包（≤2.0.0，内置 :8000）过渡 = 从 GitHub Release 直链手动安装 v2.1.0
  一次，此后其自身经 :5173 全自动 OTA：
  `https://github.com/BaiZeS/english-speaking-app/releases/download/v2.1.0/EnglishAssistant-2.1.0.apk`
- **调试包**：Actions → 最新绿色 `Android CI` run → Artifacts → `app-debug`
  （仅 debug 签名，过期 90 天，别当分发渠道）。
- 仓库里的 `apk/` 目录只是本机临时副本位（`*.apk` 已 gitignore、**无提交内容**），
  不是下载入口。

装机后：debug 与 release 包**自 v2.2.1 起都默认内置** `http://118.89.58.84:5173/api/v1/`（生产，开箱即用）；**本地联调**在 App「设置」页把 Base URL 改成开发机地址（模拟器 `http://10.0.2.2:8000/api/v1/`——dev 栈绑 `127.0.0.1` 也照样可达；真机仅在开发机裸跑 `uv run uvicorn --host 0.0.0.0` 时用局域网 IP，dev compose 栈的 8000 已只绑 `127.0.0.1`，见 backend/README）。客户端直接录 PCM L16 16kHz，提交后端走真实 ISE 逐词评分（未配凭据时返回带 `source=stub` 的占位分并在界面警示）。

## 文档

- [**用户使用指南**（领导向：测评→日常练习循环→生成课→表达库）](docs/usage-guide.md)
- [**运维与发版 SOP**（部署拓扑 / deploy 脚本 / tag+publish 流程 / 密钥启用 / 冒烟命令）](docs/operations.md)
- [CHANGELOG](CHANGELOG.md) · [后端 README](backend/README.md) · [Android README](android/README.md)
- [设计文档（2026-07-11 历史稿，文末附 v2.1.0 实现增补）](docs/superpowers/specs/2026-07-11-english-speaking-app-design.md)
- [L1 MVP 实施计划（已归档）](docs/superpowers/plans/2026-07-11-backend-l1-mvp.md) · [MiMo-TTS 迁移交付报告](docs/compose/spec/mimo-tts-migration.md)
- v2.0 大版本计划与九阶段执行纪要：`.mimocode/plans/1788164431817-eager-cactus.md` + `.mimocode/tasks/`（本仓开发过程中的计划/报告留档，gitignored，不随仓库分发）
