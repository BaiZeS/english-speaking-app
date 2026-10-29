---
feature: dialogue-chat-revamp
status: designed
updated: 2026-10-29
source: feat/dialogue-chat-revamp
---

# 对话改版：微信式情景对话单页 App（v3.0.0）

## Report

## [S1] Problem

App 目前是「课本 + 单词 + 测评 + 对话」的合集：底部 4 Tab（`ui/navigation/AppTabs.kt:15-20`，`Routes.kt:13-87` 共 23 个目的地），操练主体是**单词与句子级重复练习** —— 词汇 Tab（`ui/vocab`）、弱词专项训练（`ui/drill`，跟读单词走 ISE `read_word`）、情景课「打基础」（`ui/scenes/Briefing*` + `DrillFeedbackCard`）、跟读/影子跟读（`ui/player`）、表达库（`ui/expressions`）、CEFR 测评（`ui/assessment`）。

真正「说话」的那条路反而最弱，四个断点：

1. **对话里没有声音。** `reply_audio_url` 字段存在但**从不赋值、恒 None**（`backend/app/api/v1/dialogue.py:145-171`）；自由对话的 `polish`/`grammar_score`/`vocabulary_score` 是**硬编码 null**（`:388-390`）。学员看不到也听不到任何示范。
2. **只能用英文开口。** `/dialogue/turn` 只吃 `user_audio_b64`，**没有文字入参**（`:130-142`）；讯飞 IAT 听写**硬编码 `language="en_us"`**（`app/services/xunfei_iat.py:80-86`）。中文水平不够的学员一开口就卡死，场景推不下去。
3. **每轮没有反馈。** 对话链路不评分，评分能力全绑在要废弃的单词/句子题型上。
4. **聊完就断。** `/dialogue/turn` 无状态，历史靠客户端 `history[]` 回传，没有「回到这个场景接着聊」。

目标形态：一个**微信式情景对话聊天器** —— 角色发语音条、点开看文字、长按互译、我可以说中文、每轮给我打分和参考说法。

## [S2] Design

### S2.1 两屏 App

底部 Tab 取消。导航只剩四个目的地：

| 目的地 | 内容 |
|---|---|
| `ChatList` | 会话列表 = 场景列表。每行：角色头像组、场景名、最后一条预览、时间、未读红点。右上「+」= 一句话自定义场景；右上「⋯」= 设置。 |
| `Chat` | 微信式**群聊**（一个场景 2–3 个角色）。角色气泡在左（头像 + 昵称 + 语音条），我的气泡在右。 |
| `Settings` | **必须保留的逃生门**：v2.2.4 的教训是更新检查失败时若进不了设置（服务器地址/模型选择只在这里改），用户会被弹窗锁死。`UpdateDialog` 的「进入设置」跳转目标随之改指这里。 |
| `About` | 版本与指纹信息。 |

Android 删除：`ui/vocab` `ui/drill` `ui/expressions` `ui/assessment` `ui/lesson` `ui/player` `ui/history` `ui/home` `ui/me`，以及 `ui/scenes/` 下的 `Briefing*` `DrillFeedbackCard` `Review*` `SceneDetail*` `GenerateCourse*` `Mission*` `SubScoreReadout` `FeedbackBlocks` 等打基础/复盘专用件。

后端删除见 S2.8。

### S2.2 场景目录：12 个生活场景 × 多角色

`DialogueScene`（`app/services/dialogue_scenes.py:13-58`）新增 `roles: tuple[SceneRole, ...]`：

```python
SceneRole(id: str, name: str, name_cn: str, voice: str, persona: str, persona_cn: str)
# voice ∈ {Mia, Chloe, Milo, Dean}（mimo_tts.py:35 现有四音色）
```

- 每场 **2–3 个角色**、各自固定音色与 persona；`user_role` 说明「我是谁」。
- `openings` 每条带 `speaker`（角色 id），≥2；`beats` 3–6；`suggestions` ≥2；全部中英成对。
- 12 场：点咖啡、餐厅点餐、机场值机、酒店入住、看医生、租房看房、购物、问路、接机、闲聊、开会、工作汇报。
- **自定义场景**（`models/scene_spec.py:35-79` + `scene_spec_generator.py:290`）的骨架作业必须一并产出 `roles`，否则新场景进不了群聊。
- 沿用既有纪律：dataclass **不给默认值**逼漏填；静态兜底句不得复活（有测试钉死）。

### S2.3 会话线程落库

新表 `dialogue_threads`（照 `models/db.py:158` `dialogue_scenes` 的 `doc` JSON 形状）：

```
id, owner_device_id, owner_user_id, scene_key, doc JSON,
turn_count, grading_status, created_at, updated_at
unique(owner, scene_key)          # 一个场景一条会话
```

`doc.messages[i]` 是客户端渲染的唯一真相：

```
id（单调，做 LazyColumn key）, kind ∈ {line, hint, grade, user},
role_id, text, text_cn, audio_url, audio_ms, audio_pending,
lang, recognized_text, local_recording, beat, grade{...}, at
```

端点：

| 方法 | 路径 | 语义 |
|---|---|---|
| `GET` | `/dialogue/threads` | 会话列表（预览、`updated_at`、未读数） |
| `POST` | `/dialogue/threads` | 开会话；已存在则幂等返回既有（**取代** `/dialogue/generate` 的开场白职责，开场两条直接带 `audio_url`） |
| `GET` | `/dialogue/threads/{id}` | 全量消息 + `grading_status` 水位（评分回填通道） |
| `POST` | `/dialogue/threads/{id}/turn` | 提交一轮（**取代**无状态 `/dialogue/turn`） |
| `DELETE` | `/dialogue/threads/{id}` | 删除会话（微信长按删除） |

越权/未知 id → `404 THREAD_NOT_FOUND`（沿用 v2.3.0 删掉静默回落的口径）。归属隔离仍是「信任声明 device 即所有权」（仓内统一口径，本批不引入鉴权）。

**旧表一律不删**：`lessons`/`history`/`practice_sessions`/`practice_steps`/`scene_courses`/`ability_profiles`/`ability_events`/`expressions`/`assessment_*`/`course_progress`/`annotated_diffs` 只删代码路径，**不写 drop 迁移**（删表不可逆，且本批不部署生产）。

客户端 Room 同理且更硬：`AppDatabase` **冻结在 version 3**，`MistakeWordEntity`（和早已闲置的 `HistoryCacheEntity`）必须**继续留在 `entities` 里**，只删 `MistakeWordDao` 的调用方与 `ui/vocab`/`ui/drill` 两个 ViewModel（`AppDatabase.kt:7-19` 注释写死了原因：Room 2.6.1 在 version 不变时改动实体列表，schema 身份哈希会让 `RoomOpenHelper.checkIdentity` **无条件 throw**，`fallbackToDestructiveMigration()` 不覆盖该路径 ⇒ 存量安装直接崩）。表体冻结、无代码读写，是这里想要的状态而不是遗留垃圾。

### S2.4 一轮的输入

```python
{ mode: "voice" | "text", lang: "zh" | "en", audio_b64: str = "", text: str = "" }
```

- `mode=voice` 必须有 `audio_b64`；`mode=text` 必须有 `text`；`lang` 只接受 `zh`/`en` —— 否则 422。
- `xunfei_iat` 的 `language` 由 `lang` 决定。**已实测**（2026-10-29 真火）：`language="zh_cn" + accent="mandarin"` 用**现有凭证**逐字转写正确（`'不好意思，这份报告我还需要再核对一下数据。'`），同一段音频走 `en_us` 返回空串。所以这是**参数化**，不是待验证的能力。
- `lang=en` 才并行跑 ISE 逐词发音分；`lang=zh` 不跑（中文音频对英文 ISE 无意义）。
- **`lang` 由用户在录音前自己切**（输入栏「中/EN」，默认「中」）。事后从音频判别语言要串行两次听写（最坏 8+8=16s），撑爆预算，故否决。
- 角色**听得懂中文**：prompt 明确「学员可用中文回答，理解其意图后用英文继续推进 beats，不要求说英文、不纠错」。

### S2.5 台词、语音条、时延门

**台词**：复用 `mission_engine.generate_turn`（`services/mission_engine.py:528`），`TurnGeneration`（`:126-145`）由五字段扩到**六字段**，新增 `speaker`（本轮开口的角色 id）。拿不到台词仍 `503 TURN_GENERATION_UNAVAILABLE`，本轮不落库不前进。

**语音条 = 请求内合成 + 软失败**：`MimoTtsProvider.synthesize(reply, role.voice)` → `reply_audio_url`。
实测（2026-10-29，3 条真实台词）：冷合成 **1.41 / 1.46 / 1.96s**，磁盘缓存命中 **0.00s**。
新预算 `TTS_TURN_BUDGET_S = 3.0`。**超预算或失败一律软失败**：`reply_audio_url=None` + `audio_pending=true`，客户端退化为按需 `GET /tts` 兜底 —— 台词已经生成，**绝不能因为没声音而 503**。

**时延门**（`tests/test_latency_budget.py:666`，算式 `worst + MARGIN_S(5.0) <= CLIENT_READ_TIMEOUT_S(30.0)`）：

```
IAT 8.0 + max(ISE 8.5, GEN 14.0) + TTS 3.0 = 25.0 ≤ 25.0     # 刚好压平，零余量
```

该文件的**三把锁**必须与新预算常量同 PR：① 逐路径求和表（读 `(模块, 常量名)` 字符串清单，改名不改表 = 绿着的假安全）；② AST 门要求调用点出现 `hard_budget_s=NAME` 具名常量；③ `shrink_budget` 打在**消费侧**模块常量名上。`NetworkModule.readTimeout(30)` 与 `MARGIN_S` 不动（沿用 2026-10-08 用户裁决）。

### S2.6 每轮评分 = 异步回填

判分实测 4.2–6.7s。同步进请求即 `8+14+7+3 = 32s`，直接撞客户端 30s readTimeout，故走后台作业 `run_turn_grading_job`，形状照 `run_mission_grading_job`（`course_sessions.py:2199-2287`）：模块级持 task / 幂等门 / 自建 session / 必落终态 / 重启水位重派 / **终态 CAS 防画像双计** / 失败静默。

写回 `doc.messages[i].grade`：

| 轴 | 含义 |
|---|---|
| `relevance` | 切题度：回应符不符合当前场景与拍点 |
| `informativeness` | 信息量：有没有真的给出内容 |
| `appropriateness` | 得体度：语气/礼节 |
| `beat_progress` | 任务推进：beats 有没有往前走 |
| `pronunciation` | 发音：**仅 `lang=en`** 时带 ISE 逐词分；说中文时该轴**整行不渲染**（不是显示 0 分） |

响应与 `GET /dialogue/threads/{id}` 带 add-only `grading_status ∈ {"", pending, ready, failed}`，客户端复用 `GradingPollingPolicy.kt`。作业失败 = 没有点评，不是这一轮不存在（静默，且过一轮水位可翻身）。

**建议回答（可提前获取）**：每轮响应已含 `suggestion`/`suggestion_cn`，落库成 `kind="hint"` 气泡，**默认折叠**（只显示「💡 建议回答 · 看提示」），点开显示英文+中文。**零额外 LLM 调用** —— 字段本来就在 turn 响应里，改的只是「答完才看」→「答前可看」。

### S2.7 长按翻译

- 角色台词长按 = 客户端本地切换 `reply` ⇄ `reply_cn`（数据已在，**不调网络**）。
- 我的消息、建议句等没有现成对照的文本 → 新端点 `POST /translate {text, target: "zh"|"en"}` → `{translated, source}`。
- `/translate` 是**独立请求**，自带 hard budget `TRANSLATE_BUDGET_S = 6.0`，不占 turn 预算；失败给可读中文提示。
- 沿用 D5 口径：**翻译失败不许机翻占位糊上屏**，宁可只显示原文。
- 事实依据：仓内此前**没有任何翻译端点**，只有 `/polish`（EN→EN + `polished_cn`）。

### S2.8 后端删除清单（含一个必须留的共用件）

删除路由：`/lessons` `/books` `/sessions/*`（整条 course_sessions 状态机：打基础/实战/复盘） `/score` `/assessment` `/expressions` `/stats` `/ability` `/polish` `/history`，以及 `scenes.py` 的 `/scenes/generate` `/scenes/{scene_id}` `/scenes/{scene_id}/script` `DELETE /scenes/{scene_id}` `/courses/progress`。

保留：`/dialogue/*`（除被线程取代的 `/dialogue/turn`、`/dialogue/generate`） `/tts` `/translate` `/llm/models` `/app/version` `/health`，以及 **`GET /scenes/jobs/{job_id}`** —— 它是整课生成与**自定义场景骨架**共用的轮询端点（`scenes.py:213`；客户端 `EnglishApi.kt:103`、`SceneGenDtos.kt:97`），整删 `scenes.py` 会连带打死自定义场景。

服务层：`xunfei_asr`（ISE）**保留**（学员主动说英文要出发音分）；`xunfei_iat` 参数化；`mimo_tts`/`wav` 不动；`drill_grader` 的题型判分/整课生成部分删除，`_judge` 收口保留（台词与评分共用）。

### S2.9 微信式聊天 UI（Android）

- **语音条**：气泡内 = 时长文字 + N 根波形条；未播时红点，播放中波形逐段点亮。时长读后端 WAV 头（`wav_duration_ms`，避开「1s 算成 2s」旧坑）。**这是新 composable**：现有 `MissionScreen.kt:380-412` 的 `SpeechStripRow` 名字像但内容是**发音维度条**（`dims`/`rateLabel`/`没读准：…`），不是微信语音条，不可复用；播放动作复用 `audio/AudioPlayer.kt:46` 的 `play(url, onError, onCompletion)`（v2.3.1 已把 12 处播放调用点的失败原因上屏，新气泡必须接这个 `onError`，不许只写日志）。
- **点击展开文字**：语音条默认**不显示文字**，点击后气泡下方展开 `BilingualText`（既有组件；次级语言空白 ⇒ 整行不渲染，不机翻）。
- **长按**：`combinedClickable(onLongClick)` → 本地切双语 或 调 `/translate`。
- **我的气泡**：语音输入 → 本机录音回放（`RecordingStore`，48kHz 已上采样）；文字输入 → 直接显示文字。
- **头像**：角色名首字圆形色块（Compose 绘制，**不新增图片资源**）。
- **气泡 key 必须用单调 id**（v2.3.0 的 `6fae05d` 崩溃教训：列表 key 不能依赖内容相等性）。
- **输入栏**：左「中/EN」切换 · 中「按住说话」（复用 `HoldToTalkRow`/`HoldToTalkButton` + `RecordingPulseMeter`）· 右「文字输入」弹键盘。
- **配色**：背景 `#EDEDED`、我 `#95EC69`、角色 `#FFFFFF`、昵称 `#576B95`。

### S2.10 版本与发布身份

`versionCode 15 → 16`、`versionName 2.3.1 → 3.0.0`（大改走 major）。CI 的 `release-gate` 要求改 `android/app/src/main/**` 必须同范围 bump + 增 CHANGELOG 内容，**同一批内完成**，不用 `release-gate-skip` 逃生口。

交付边界 = **代码全绿 + 本地验收**：不 push、不打 tag、不部署生产、不动 `backend/.env`、不 `deploy.sh restart`。

## [S3] Out of Scope

- **发版链一切**：不 push、不 tag、不跑 `release.yml`、不跑 `publish_apk.sh`、不切 OTA、不动 `APP_MIN_SUPPORTED_VERSION`。
- **生产一切**：本盒即生产机（`:5173`）。不 restart 容器、不改 `.env`、不跑迁移到生产库。大扫除后的后端只存在于 worktree。
- **不删数据库表**：旧表与历史数据全留，只删代码路径。
- **不做真机走查**：本盒无设备。语音条播放、长按手势、录音、中文听写效果待人工验收。
- **不动全局网络超时**：`NetworkModule.readTimeout(30)` 与 `MARGIN_S` 不改。
- **不做账号体系与多设备会话合并**（表已按 owner 存，合并策略不在本批）。
- **不处理旧包（≤2.3.1）兼容**：后端大扫除会让它们调被删端点时 404 —— 这是「同步大扫除」已裁决的代价，因本批不部署而不影响现网。
- **不做微信的非核心能力**：表情、撤回、引用、@、转账、语音输入转文字流式动效。

## Tasks

- [ ] T1: 场景目录重做 —— 12 个生活场景 × `roles`(2-3, 固定音色) + `beats`(3-6) + `openings`(≥2, 带 speaker) + `suggestions`(≥2)，中英成对；自定义场景骨架作业同批产出 `roles` — acceptance: `GET /dialogue/scenes` 返回 12 场，静态校验测试逐场断言字段齐全、音色 ∈ {Mia,Chloe,Milo,Dean}、无 dataclass 默认值可依赖 (covers: S2.2)
- [ ] T2: IAT 语言参数化（`zh_cn` / `en_us`）— acceptance: 新增中文听写用例绿；既有 `test_dialogue_iat.py` 6 条英文用例一字不改仍绿；`language` 不再硬编码在 `xunfei_iat.py:80-86` (covers: S2.4)
- [ ] T3: `dialogue_threads` 表 + Alembic 迁移 + 五个线程端点（含幂等开会话与开场白带音频）— acceptance: 迁移在 SQLite 与 PG16 双向可逆；同 owner+scene 二次 `POST` 返回同一 id 且不重复落开场白；越权/未知 id 404 `THREAD_NOT_FOUND` (depends: T1, T2; covers: S2.3)
- [ ] T4: `POST /dialogue/threads/{id}/turn` —— 输入分派(voice/text × zh/en) + 六字段台词生成(含 speaker) + 请求内 TTS 软失败 — acceptance: 中文语音轮 200、`recognized_text` 为中文、`reply_audio_url` 非空、`audio_pending=false`；TTS 超预算 → `reply_audio_url=None` + `audio_pending=true` **且仍 200**；LLM 不可用 → 503 且线程不落库不前进；`lang=en` 才跑 ISE (depends: T3; covers: S2.4, S2.5)
- [ ] T5: 每轮评分后台作业 + `grading_status` 回填 — acceptance: 成功 → 该轮 `grade` 四维齐、`grading_status=ready`；失败 → `failed` 且静默（不报错、气泡不消失）；终态 CAS 输家不双计画像；重启后按水位重派 (depends: T4; covers: S2.6)
- [ ] T6: `POST /translate` — acceptance: `zh→en` 与 `en→zh` 各一例；超 6.0s 预算 → 可读错误而非空串；调用点带命名常量预算（过 AST 门） (covers: S2.7)
- [ ] T7: 时延门与预算同批改 — acceptance: `test_latency_budget.py` 求和表含 `TTS_TURN_BUDGET_S`，算式 `8 + max(8.5,14) + 3 = 25 ≤ 25` 绿；三把锁全部指向新常量名，无「改名后假绿」 (depends: T4, T6; covers: S2.5)
- [ ] T8: 后端大扫除 —— 删 S2.8 清单里的路由/服务/模型用例，**保留 `GET /scenes/jobs/{job_id}` 与所有 DB 表** — acceptance: `main.py` 注册表只剩保留清单；被删端点不在路由里；`ruff check` / `ruff format --check` / `mypy app` / `pytest` 全绿，并记录测试数相对基线 653 的差集与被删用例清单 (depends: T5, T7)
- [ ] T9: Android 会话列表 + 微信式群聊屏 —— 语音条、点击展开文字、长按翻译、折叠建议、异步评分卡、中/EN 切换 + 按住说话 + 文字输入 — acceptance: JVM 单测覆盖纯函数（气泡单调 key、语音条时长格式化、双语空白不渲染、翻译分派「已有双语本地切 vs 走 /translate」、`audio_pending` 退化路径、评分三态出现/消失）；`assembleDebug` 成功 (depends: T4, T5, T6)
- [ ] T10: Android 导航收缩 + 删除单词/课程/跟读/测评/统计屏 — acceptance: `Routes.kt` 只剩 ChatList/Chat/Settings/About；`AppTabsTest` 按新导航重写并通过；`UpdateDialog`「进入设置」仍能落到 Settings（逃生门不丢）；**`AppDatabase` 仍 `version = 3` 且 `entities` 仍含 `MistakeWordEntity`/`HistoryCacheEntity`**（只删调用方，见 S2.3）；ktlint exit 0；detekt 相对基线 103 零新增 (depends: T9)
- [ ] T11: 版本身份 + 文档定版 — acceptance: `versionCode = 16` / `versionName = "3.0.0"`；CHANGELOG.md 新增 v3.0.0 条目；README / backend README / usage-guide / operations 对账并明确标注「未部署、未发版」 (depends: T8, T10)

## Journey log
