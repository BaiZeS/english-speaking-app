# English Speaking Assistant · Android Client

Kotlin + Jetpack Compose 原生 Android 客户端。

## 状态

✅ **v2.2.0（versionCode 9）**：对标可栗的四 Tab 信息架构 —— 首页（今日推荐/继续学习/场景画廊/5 分钟 CEFR 测评引导）、课程（情景课 + 课本）、词汇（表达库 + 弱词训练）、我的（能力画像雷达/轨迹、历史、设置）。**情景实战课**全流程：打基础四题型（跟读 / 复述 / 翻译 / 造句）→ 任务制实战对话（聊天气泡 + 任务清单通关 + 润色气泡收藏）→ 复盘报告；另有 AI 生成课（说出目标→两段生成）、测评三屏、影子跟读、OTA 自托管更新通道。327 个 JVM 单测，release 包内置生产地址 `:5173`。

录音侧本轮重做（用户报告的 5 个真机症状全在客户端这一侧，逐条根因见 `CHANGELOG.md` v2.2.0）：

- **两种手势按取句长短分派**，共用一套行组件 `ui/components/HoldToTalkRow.kt`（`HoldToTalkRow` 长按 / `TapToTalkRow` 点按 / `TakeElapsedText` 计时）：长按面 = 打基础、实战、跟读练课、角色对话、弱词本、测评朗读题；点按面 = 影子跟读（整段连续、无 30s 上限）与自由对话（30s 到点自动发送）——点按面一律配诚实话术 + `mm:ss` 已录计时，**不允许任何一屏的文案承诺它没实现的手势**。
- **真滚动波形** `ui/components/RecordingWaveform.kt`（Canvas + 单个 `Animatable` 驱动子条滑移）← `AudioRecorder.waveformFlow`（**未平滑**的逐帧峰值：`AudioLevelMapping.smooth` 的衰减约 440ms 才落到位，拿它画会把音节糊成一片；该映射与其 9 个单测未动）← 纯环形缓冲 `audio/WaveformHistory.kt`（40 条 ≈ 1.6s @ ~25Hz）。取句结束时**保留形状不清空**，评分期间仍在屏上；阈值电平表旧件 `RecordingLevelIndicator.kt` 已删除（让编译器强制 5 个调用点同批迁移）。自由对话与测评页此前**没有**录音条，本轮新增。
- **每环节即时反馈** `ui/scenes/DrillFeedbackCard.kt`：总分 + 五维子分（null = 无证据，跳过不渲染）+ 逐词芯片含 IPA + 引擎实际听到的转写 + 中文建议；≥85 停留 5s 自动前进（`ui/scenes/FeedbackAdvancePolicy.kt`），滚动/点按即取消。渲染门键在独立槽位 `pendingGrade` 上，不再键在"被这次评分自己作废的步身份"上（那是过关时卡片永不组合的根因）。
- **收工不再同步等总评 LLM**：202 + `doc["review_status"]` 轮询（`ui/scenes/ReviewPollingPolicy.kt` 2s→6s、5min 放弃；三态判定在纯 Kotlin `ReviewStateMachine`），先画数值骨架、文案区写「AI 正在写总评…」；收工重复提交守卫在 `MissionFinishGuard`。**breaking**：旧包配新后端会在收工时拿到空 `review`，故 v2.2.0 按强制升级发布（见 docs/operations.md 第 3 节）。

`ScoreSessionHolder` 那份成绩聚合已落盘（`ui/score/ScoreSessionStore.kt`，JSON in `filesDir`，编解码抽成纯 `ScoreSessionCodec`）—— **刻意没建 Room 实体**：`5556851` 是有意删掉 `HistoryCacheDao` 的，而 `history_cache` 至今作为**冻结实体**留在 `AppDatabase` 里只为钉住 Room 2.6.1 的 v3 身份哈希（不 bump 版本就删 `@Entity` 会让存量装在 `checkIdentity` 崩），那个壳不要动。从后端重建也**已核实不可行**：`history` 表每行只有逐句 total/pronunciation/fluency/completeness，没有逐词分、建议、角色名，也没有 `session_id`。

判定逻辑照旧走"抽出纯 Kotlin + JVM 单测"这条路：**没有 `androidTest` 源集，也不引 Robolectric / Compose UI 测试栈**（本轮沿用了这个既有约定，新增的接缝是 `WaveformHistory` / `RecordingTakeClock` / `WaveformGeometry` / `BackendErrorText` / `ReviewPollingPolicy` / `FeedbackAdvancePolicy` / `ReviewStateMachine` / `MissionFinishGuard` / `ReviewEntryPolicy` / `SubScoreReadout` / `ScoreSessionCodec`）。⏳ **v2.2.0 的真机验收尚未执行**——以上客户端行为目前的证据只有源码与 JVM 单测。

## 目录结构

```
android/
├── app/                          # 主 module
│   ├── src/main/
│   │   ├── java/com/app/english/
│   │   │   ├── ui/              # Compose 屏: home/courses/vocab/me 四 Tab + scenes(实战五屏)/assessment(测评)/player/components…）
│   │   │   ├── domain/          # 业务模型 + 评分映射
│   │   │   ├── data/            # remote(Retrofit) + local(Room/Settings) + repository
│   │   │   ├── audio/           # AudioRecord(PCM) 录音 + ExoPlayer 播放
│   │   │   └── di/              # Hilt 模块
│   │   ├── res/
│   │   └── AndroidManifest.xml
│   ├── build.gradle.kts
│   └── proguard-rules.pro
├── gradle/
│   ├── libs.versions.toml       # 依赖版本目录
│   └── wrapper/
├── build.gradle.kts
├── settings.gradle.kts
└── gradle.properties
```

## 关键依赖

| 类别 | 库 | 版本 |
|---|---|---|
| 构建 | AGP / Kotlin | 8.7.3 / 2.0.21 |
| UI | Jetpack Compose | BOM 2024.10.01 |
| 架构 | Hilt | 2.51.1 |
| 网络 | Retrofit + OkHttp | 2.11.0 / 4.12.0 |
| 异步 | Coroutines + Flow | 1.8.1 |
| 存储 | Room | 2.6.1 |
| 播放 | Media3 ExoPlayer | 1.4.1 |
| 序列化 | kotlinx.serialization | 1.7.3 |
| 录音 | AudioRecord（PCM L16 16kHz）| 平台 API |

## 本机构建与 CI

**本部署机已装 Android SDK**（`~/Android/Sdk`，`local.properties` 已配、gitignored）——改 Android 前先本地预验三连：

```bash
./scripts/ktlint.sh                    # == CI 的 ktlint 硬门（同版本经阿里云镜像）
./gradlew testDebugUnitTest --no-daemon # 327 JVM 单测
./gradlew assembleDebug --no-daemon     # debug 包（产物在 app/build/outputs/apk/debug/，当前约 22.1 MB）
```

注意：`lintDebug` 本地与 CI 存在系统性偏差（主分支干净树本地也会报 lint 问题），**勿作反馈信号**；权威验收入口仍是 GitHub Actions（`Android CI`: release-gate（版本门，只判 git 范围，不装 SDK）→ ktlint → detekt(软) → testDebugUnitTest → assembleDebug；`Release APK`：push `v*` tag 自动出 `EnglishAssistant-<ver>.apk`）。**detekt 是软门**（`continue-on-error: true`，本仓维持 ~99 findings 的既有画像），ktlint 通过 ≠ 能编译（它不做类型检查）——签名折叠类风格与幻影参数类错误只会在编译/CI 暴露，务必本地先跑上面的三连再推。

`release-gate` 是本轮新加的**硬门**，也是唯一一条"红得跟你有关"的检查：一次 push/PR 的整个范围改了 `app/src/main/**`，却同范围内没让 `versionCode` 严格递增、没给 `CHANGELOG.md` 加内容 → 直接红，且 `build-debug-apk` 一起被挡住。理由是一条真实事故：`2fd067d`（hold-to-talk + 实时音量表，main 下 20 个文件）CI 全绿、永久躺在 `main` 上，而 OTA 那份 APK 还是它祖先 v2.1.0 的树——**代码修好了，学员从来没拿到**。逃生口 `[release-gate-skip: <理由>]` 写在 commit message 里（必须带理由，命中行进日志）；未发布的同一版本列车（versionCode 高于最近可达 tag 且 CHANGELOG 已有该版本章节）允许不再 bump。规则细节与例外都注释在 `.github/workflows/android-ci.yml` 里。其他机器仍可「零环境开发」只靠 CI 出 APK：

> https://github.com/BaiZeS/english-speaking-app/actions → 选 workflow run → Artifacts → `app-debug`
