# Changelog

## v2.1.0 — 2026-09-06 · 生产 :5173 通道

### 用户视角
- 直连新部署的生产后端（端口 5173）：v2.1.0 起安装即用，不再需要在设置里手工改服务器地址。

### 工程摘要
- `BACKEND_BASE_URL`（release）→ `http://118.89.58.84:5173/api/v1/`；debug 仍指模拟器回环 `10.0.2.2:8000`。
- `release.yml`：发行说明由「取提交标题」改为 `git describe` 的纯 tag（防止标题含版本号词致 `EnglishAssistant-<版本>.apk` 改名漂移）。
- 版本号 → versionCode 8 / versionName 2.1.0；生产主实例 `:5173` + 桥接 `:8000` 并行，旧包远程 OTA 的公网 8000 映射/手动装包过渡见 README「发布通道」。

## v2.0.0 — 2026-07-19 · 大版本：对标可栗口语的情景实战闭环

### 用户视角（这次更新你能玩到什么）

- **情景实战课**：从「咖啡店点单」到「英文项目汇报」，先过打基础四题型
  （跟读 / 复述 / 翻译 / 造句），再进入任务制实战对话——聊天气泡、任务清单逐项
  打勾、随时「要提示」，通关后生成复盘报告：总分 + 语法/词汇/流利/发音四维 +
  本轮能力增量。
- **AI 生成专属课**：输入一句你的真实场景需求，后端两级生成（大纲→剧本），
  几分钟后画廊里出现一门只属于你的课（仅本人可见，可删除）。
- **CEFR 能力测评**：约 5 分钟、7 题（跟读题要录真音），得到 A1–C2 定级与
  四维雷达；定级会锁进能力画像，画像只允许 ±1 档漂移，逐步练习再验证。
- **能力画像与轨迹**：「我的」页四维雷达 + 近 7/30/90 天曲线。没配 AI 凭据的
  机器会自动降级为占位评分——占位分**不会**被算进画像，图表诚实留空。
- **句子润色 + 表达库**：任何一句英语都能一键「原句 vs 更地道说法」对照；
  实战对话里的润色金句可收进表达库，随时翻阅复习。
- **练课四模式仍在且更顺**：跟读 / 角色对话 / 影子跟读 / 自由对话，多本书
  （新概念一/二册、商务英语）全部按书隔离；自由对话没有参考回答也能直接开口。
- **弱词专项训练**照旧：低于 70 分的词自动入本，示范→跟读单词→≥85 分毕业。
- **历史页更认得路**：情景课的收工记录显示中文课名（如「点一杯拿铁 · 实战对话」），
  不再是一串内部行号；复习建议卡同样给出「书 · 第 N 课」人读标题。
- **升级说明**：v2.0.0 通过应用内 OTA 检查提示更新（GitHub Releases 下载），
  提示可「稍后再说」，不强制；1.4.x 老用户升级后练习历史与弱词本完好保留。

### Engineering notes (EN)

- Backend: scene-course content layer (8 curated JSON courses, `scene_store` with
  60s file cache), practice-session state machine with crash-resume, 4 drill
  graders (deterministic + LLM-judged), mission engine with single-call LLM
  review report, two-stage course generation jobs (`/scenes/generate` + polling),
  CEFR assessment bank & grading, EWMA ability-profile pipeline with `stub`
  evidence gating, `/polish`, `/expressions` CRUD (normalized dedupe),
  `/courses/progress`, `GET /history` add-only `kind`/`label`, `/stats` readable
  weakest-lesson labels, deterministic `duration_s` estimation.
- Protocol: free-dialogue user turns are structural (trailing empty user turn +
  server-side IAT backfill); legacy Chinese placeholder kept server-side for
  old clients only, never produced by the v2.0 client.
- Releases: `/app/version` defaults `min_supported_version` to a `0.0.0`
  sentinel — forced-update semantics only when `APP_MIN_SUPPORTED_VERSION` is
  explicitly configured; Android `decideUpdate` respects "skip this version".
- Migrations: full alembic chain round-trips on both SQLite (batch mode) and
  PostgreSQL 16; in-process migration runs no longer silence app loggers.
- Android: Jetpack Compose 4-tab IA (Home / Courses / Vocabulary / Me), scene
  gallery + briefing + mission + review + generate screens, assessment flow,
  Canvas radar + trajectory chart, expression library, OTA update UI;
  versionCode 6 / versionName 2.0.0.
- Cleanup: removed dead `LineCard`, Room history-cache entity/DAO, backend
  `tts_cache` service surface + Redis config/dependency; stub TTS now emits a
  real (silent) WAV so clients never decode garbage bytes.

## v1.4.x 及更早

历史版本无独立 changelog：跟读/角色/影子/自由对话、多书语料、讯飞 ISE 评分、
MiMo TTS、统计与弱词训练在 1.x 迭代中陆续上线，详见 git 历史。
