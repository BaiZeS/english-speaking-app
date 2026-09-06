# docs 索引

**当前版本 v2.1.0（生产：`http://118.89.58.84:5173/api/v1/`）**

| 文档 | 内容 | 读者 |
|---|---|---|
| [usage-guide.md](usage-guide.md) | App 使用指南（安装/CEFR 测评/任务通关实战/生成课/表达库/能力画像） | 用户（领导向）|
| [operations.md](operations.md) | 生产拓扑、deploy 脚本、发版 SOP（tag→Release→publish_apk 自托管 OTA）、密钥启用、冒烟命令、坑位清单 | 运维/开发 |
| [../CHANGELOG.md](../CHANGELOG.md) | 版本历史（用户语言 + 工程摘要） | 所有人 |

## 历史档案（v1.x 阶段，正文保留原貌 + 归档注记）

| 文档 | 说明 |
|---|---|
| [superpowers/specs/2026-07-11-...design.md](superpowers/specs/2026-07-11-english-speaking-app-design.md) | v1 MVP 设计稿；**文末附录「v2.1.0 实现增补」**对照列出与现状差异 |
| [superpowers/plans/2026-07-11-backend-l1-mvp.md](superpowers/plans/2026-07-11-backend-l1-mvp.md) | L1 后端实施计划（已执行完毕，checkbox 未回填，进度以 git 历史为准）|
| [compose/spec/mimo-tts-migration.md](compose/spec/mimo-tts-migration.md) | MiMo-TTS 替换讯飞 TTS 交付报告 + 文末 v2.1.0 增补（stub 静音 WAV、自托管 OTA）|

v2.0/v2.1 大版本的过程文档（计划九阶段拆解、执行纪要、CI 核验记录）在仓库工作区 `.mimocode/`（gitignored，随仓开发过程档，不在发布产物内）。端点契约权威：后端源码 `backend/app/api/v1/*.py` + 在线 `http://118.89.58.84:5173/docs`。
