# English Speaking Assistant · Android Client

Kotlin + Jetpack Compose 原生 Android 客户端。

## 状态

✅ **v2.1.0（versionCode 8）**：对标可栗的四 Tab 信息架构 —— 首页（今日推荐/继续学习/场景画廊/5 分钟 CEFR 测评引导）、课程（情景课 + 课本）、词汇（表达库 + 弱词训练）、我的（能力画像雷达/轨迹、历史、设置）。**情景实战课**全流程：打基础四题型（跟读 / 复述 / 翻译 / 造句）→ 任务制实战对话（聊天气泡 + 任务清单通关 + 润色气泡收藏）→ 复盘报告；另有 AI 生成课（说出目标→两段生成）、测评三屏、影子跟读、OTA 自托管更新通道。168 个 JVM 单测，release 包内置生产地址 `:5173`。

录音 `AudioRecord` 直采 PCM L16 16kHz → 后端讯飞 ISE 逐词音素评分/ IAT 听写（未配凭据时 stub 分带「占位」警示，不污染画像）；示范音 MiMo TTS。

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
./gradlew testDebugUnitTest --no-daemon # 168 JVM 单测
./gradlew assembleDebug --no-daemon     # debug 包（产物在 app/build/outputs/apk/debug/）
```

注意：`lintDebug` 本地与 CI 存在系统性偏差（主分支干净树本地也会报 lint 问题），**勿作反馈信号**；权威验收入口仍是 GitHub Actions（`Android CI`: ktlint → detekt(软) → testDebugUnitTest → assembleDebug；`Release APK`：push `v*` tag 自动出 `EnglishAssistant-<ver>.apk`）。ktlint 通过 ≠ 能编译（它不做类型检查）——签名折叠类风格与幻影参数类错误只会在编译/CI 暴露，务必本地先跑上面的三连再推。其他机器仍可「零环境开发」只靠 CI 出 APK：

> https://github.com/BaiZeS/english-speaking-app/actions → 选 workflow run → Artifacts → `app-debug`
