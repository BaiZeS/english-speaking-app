# English Speaking Assistant · Android Client

Kotlin + Jetpack Compose 原生 Android 客户端。

## 状态

✅ **三种练习模式已接入** — 跟读（句子序列 + 最近五句）、角色对话（A 播放 / B 录音评分）、自由对话（AI 建议回答 + 每轮评分）。APK 由 `android-ci` 构建，最新绿色 run 见 Actions 页。

录音用 `AudioRecord` 直接采 PCM L16 16kHz mono，提交后端走真实讯飞 ISE 逐词音素评分（不再经 AAC/M4A 转码）。

## 目录结构

```
android/
├── app/                          # 主 module
│   ├── src/main/
│   │   ├── java/com/app/english/
│   │   │   ├── ui/              # Compose 屏幕（lessons/player/score/history/settings …）
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

## 本机构建

设计为**零环境开发** — 通过 GitHub Actions 出 APK：

> https://github.com/BaiZeS/english-speaking-app/actions → 选 workflow run → Artifacts → `app-debug`

调试阶段也可在本机安装 Android Studio + SDK 后用 `./gradlew assembleDebug`。
