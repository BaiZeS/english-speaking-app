# Changelog

## 讯飞发音评测链路上线 — 2026-09-08（无客户端版本变更，真机无需重新下载）

### 用户可感知
- **发音评测真分上线**：实战/自由对话语音轮不再「超时」或发音被跳过——ISE 语音评测与 IAT 听写全链路真火冒烟通过（日志硬证 `xunfei ise ok` / `xunfei iat ok`）。单词重练（弱词，read_word）此前因协议节点头缺失被引擎 48195 静默拒掉，本次一并修复。

### 工程摘要（真火证据 `/tmp/ise-smoke-*`；冒烟脚本 `backend/scripts/smoke_xunfei_ise.py`）
- **根因（全部实测定位）**：① ISE/IAT 按 40ms/1280B 实时节奏发音频 → 整链 ≈ 语音时长×2 + LLM（最坏 2×20s 重试）> 手机 30s readTimeout（=「超时」）；② `read_word` 裸文本报 48195 SRecWrite，需 `ent=en_vip/tte=utf-8/'\uFEFF'+[content]|[word] 节点头`（流式版新口径）；③ 参考文本含 `( ) [ ] {` 引擎不出终帧挂到超时；④ 失败静默回退 stub → 发音证据丢弃（=「跳过」）。
- 修复：3200B/10ms 快速节奏（18s 音频 19.1s→2.4s）；`settings.xunfei_{ise,iat}_timeout_s`（8s）服务层硬顶 + `recv_task` finally 收口；单帧音频 `aus=8`（旧代码永不结束的真 bug）；`sanitize_ref_text` 剔括号；回退日志带上讯飞 code/message/category/字节数。
- 端点预算：mission 轮 ISE(证据)∥LLM(判分) 并行 gather + `judge_turn(hard_timeout_s=15)`（超时走既有 heuristic 降级）；dialogue 轮 anchored ISE 与 chat 并行、chat 25→12s；mission 每轮 `mission turn perf iat_ms=/pair_ms=/anchored=` 一行业绩日志。最坏 8+15 < 30s。
- 分制澄清：实测 word 分 1-5（×20 映射**正确**，流式版仍是 5 分制，`ise_xml.py` 不动）。
- 测试 +3（节点包装/括号剔除/单帧收口）；全量 514 passed；仅剩 14 个既有无关失败（app_version 9 / llm 4 / dialogue_polish 模型环境 1，改动前后一致红，另案处理）。

## 运维与凭据变更 — 2026-09-07（无客户端版本变更，真机无需重新下载）

### 用户可感知
- **TTS 真声上线**：示范朗读走 MiMo-V2.5-TTS 真合成（此前为 stub 占位/静音链路）；LLM 现役模型为 `qwen3.8-flash`（服务端默认）+ `deepseek-v4-flash-0731`，App 设置页模型下拉框已恢复可选（经 `/llm/models` 动态下发，重装无需）。
- 讯飞 ISE/IAT key 已配置；真机逐词评分冒烟待验收（未过门前仍走诚实占位分，不入画像）。

### 工程摘要
- 运维脚本 `~/english-backend-deploy.sh` → **`backend/scripts/deploy.sh`**（docs 全量改口）；日志迁 `backend/logs/`；修相对 `$0` 内部 `cd` 后 restart 必炸的 bug。
- **环境消毒**：deploy.sh 启动前剥离与 `.env` 同名的进程环境变量——pydantic-settings 优先级为 进程 env > `.env`，`~/.bashrc` 的陈旧 `MIMO_API_KEY` export 曾静默遮蔽用户换好的 key 1h+。
- **安全轮换**：postgres `english` 角色口令已换并全链路验证；tracked 文件默认凭证清除（config 默认值 / compose / `.env.example` / 归档计划文档 → `CHANGE_ME` 占位）；生产 DSN 移入 gitignored `backend/.deploy.env`。git 历史中旧口令保持不动（已失效）。
- MiMo key 线路教训入档：`tp-`/`sk-` 两线路域名不互换；401 排查用假 key 对照（docs/operations.md §5/§6）。

## v2.1.0 — 2026-09-06 · 生产 :5173 通道 + 自托管 OTA

### 用户视角
- 直连新部署的生产后端（端口 5173）：v2.1.0 起安装即用，不再需要在设置里手工改服务器地址。
- App 内更新的下载安装改走服务器自托管直链（GitHub 资源站在国内实测仅 ~10-40KB/s，21MB 更新包等不起），OTA 速度到服务器公网出口水平。

### 工程摘要（生产链 commit `25d05a3` + 运维链 `0444e47`，均双 CI 绿）
- `BACKEND_BASE_URL`（release）→ `http://118.89.58.84:5173/api/v1/`；debug 仍指模拟器回环 `10.0.2.2:8000`。
- 版本号 → versionCode 8 / versionName 2.1.0；`:8000` 桥接退役（云防火墙仅映射 5173，旧包过渡 = 一次性 GitHub 直链装 v2.1.0，见 README「发布通道」）。
- `release.yml` 保持 `GITHUB_REF_NAME` 纯 tag 派生 asset 名（防提交标题污染资产命名——本次发版实锤的竞态教训见 docs/operations.md「发版 SOP」）。
- `/static/apk` 挂载 + `backend/scripts/publish_apk.sh <tag>`：拉 GitHub asset → 自托管 → 写 `.env` 的 `APP_LATEST_VERSION`/`APP_APK_URL`（resolver 优先级 1）→ 重启 → source=env 自检。
- 运维护栏脚本 `~/english-backend-deploy.sh {start|stop|restart|status|migrate}`（生产库 `english_prod_5173`，与 dev 库隔离）。

## v2.0.0 — 2026-09-06 · 大版本：对标可栗口语的情景实战闭环

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
