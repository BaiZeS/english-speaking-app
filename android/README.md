# English Speaking Assistant · Android Client

Kotlin + Jetpack Compose 原生 Android 客户端。

## 状态

🚧 **Phase 1 骨架搭建中** — 实际项目结构在 Phase 2 由 writing-plans 输出计划后正式生成。

## 计划架构

```
android/
├── app/                          # 主 module
│   ├── src/main/
│   │   ├── java/com/app/english/
│   │   │   ├── ui/              # Compose 屏幕
│   │   │   ├── domain/          # 业务逻辑
│   │   │   ├── data/            # 网络 + 本地存储
│   │   │   ├── audio/           # 录音 + TTS 播放
│   │   │   └── di/              # Hilt
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

## 关键依赖（待装）

| 类别 | 库 | 版本 |
|---|---|---|
| UI | Jetpack Compose | BOM 2024.10 |
| 架构 | Hilt | 2.51 |
| 网络 | Retrofit + OkHttp | 2.11 / 4.12 |
| 异步 | Coroutines + Flow | 1.8 |
| 存储 | Room | 2.6 |
| 播放 | ExoPlayer | 1.4 |
| 序列化 | kotlinx.serialization | 1.7 |

## 本机构建

设计为**零环境开发** — 通过 GitHub Actions 出 APK：

> https://github.com/BaiZeS/english-speaking-app/actions → 选 workflow run → Artifacts → `app-debug`

调试阶段也可在本机安装 Android Studio + SDK 后用 `./gradlew assembleDebug`。
