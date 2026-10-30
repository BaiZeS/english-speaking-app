---
feature: dialogue-chat-revamp
status: delivered
updated: 2026-10-30
source: feat/dialogue-chat-revamp
---

# 对话聊天改版：单词练习全删，微信式群聊成唯一主功能（v3.0.0）

## Report

**What was built** — App 从「课本 + 单词 + 测评 + 对话」的合集重写成**只有微信式情景对话**的一件产品：

- **两屏**：会话列表（= 场景列表，头像组 / 预览 / 未读红点 / 长按删除 / 「+」一句话生成场景）→ 群聊页。底部 4 Tab 取消，23 个 route 收缩到 4 个；设置作为更新失败逃生门保留并改到列表右上角进入。
- **12 个生活场景 × 2-3 个角色**，角色各有昵称与固定音色（Mia/Chloe/Milo/Dean），头像为首字圆形色块（零新增图片资源）。
- **角色消息是语音条**：默认只有时长 + 波形，点击才播放并展开中英对照；音频在台词请求内合成（`TTS_TURN_BUDGET_S = 3.0`），**超预算软失败**为 `audio_pending` 并由客户端按需 `GET /tts` 兜底，绝不因无声而失败。
- **学员可以说中文**：语音固定走讯飞 `zh_cn`（实测原生吃中英混读），**没有语言切换控件、请求里没有 `lang` 字段**；语言由服务端从转写文本事后判定，只决定要不要跑英文逐词 ISE。也支持文字输入。角色听得懂中文，用英文继续推进议程。
- **每轮评分**（切题 / 信息量 / 得体 / 任务推进；说英文才附发音分）由后台作业异步回填，`grading_status` 水位 + 终态 CAS + 失败静默；**缺轴整行不渲染**，不是 0 分。
- **建议回答**默认折叠（「💡 建议回答 · 看提示」），复用每轮已返回的 `suggestion`/`suggestion_cn`，**开口前可看且零额外 LLM 调用**。
- **长按翻译**：自带双语的本地切换（零请求），其余走新增 `POST /translate`（6.0s 独立预算 + 方向自检，翻不出来 503，绝不回显原文）。
- **会话落库** `dialogue_threads`（迁移 `e7a2c4f0b913`），开会话幂等；**旧表一张未删**。
- **全删**：词汇 Tab、弱词专项训练、打基础四题型、跟读/影子跟读、表达库、CEFR 测评、练习记录、统计与能力画像。后端路由面 40+ → 12（`GET /scenes/jobs/{job_id}` 按裁决保留）。

**Verification** —（全部在 worktree 内跑，未 push / 未打 tag / 未部署生产）

| 命令 | 结果 |
|---|---|
| `backend: ruff check .` | PASS（All checks passed） |
| `backend: ruff format --check .` | PASS（92 files already formatted） |
| `backend: mypy app` | PASS（57 文件 strict，原 73） |
| `backend: pytest -q` | PASS **269 passed**（基线 653；差集为随功能删除的 24 个测试文件，有效契约改写迁移而非删除） |
| `backend: scripts/smoke_thread_turn.py` | PASS **真火端到端**：中文语音→`zh_cn` 逐字转写→英文台词+真实音频→建议句→评分 `pending→ready`；确认中文轮无发音轴 |
| `backend: scripts/smoke_iat_lang.py` | PASS `zh_cn` 中英混读实测（四类音频对照），是删掉语言切换控件的证据 |
| `android: scripts/ktlint.sh` | PASS（exit 0） |
| `android: testDebugUnitTest` | PASS **134 passed / 0 failed**（基线 384；含新增 `ui/chat` 22 条纯函数锁） |
| `android: detekt` | 22 issues（基线 103）；`ui/chat` 与本次新代码零贡献，唯一残留 `EnglishApi TooManyFunctions` 在改动前即存在（原 30 个方法） |
| `android: assembleDebug` | PASS |
| `git diff -- AppDatabase.kt MistakeWordEntity.kt` | **空**（Room 实体与 version=3 逐字未动） |
| 迁移 `drop_*` 检查 | 只出现在新迁移自身的 `downgrade()`；无任何旧表 drop |
| 503 事务边界 | `raise turn_generation_unavailable()` 位于任何 append/save **之前**，且有测试断言「会话不新增气泡、turn_count 不推进」 |

**未验证 / 待办**：真机走查（本盒无设备）；发版与部署需单独授权（旧包 ≤2.3.1 在这版后端上会 404，须先定 `APP_MIN_SUPPORTED_VERSION`）；首轮评分偏严待裁决（真火实测 36 分，见 Journey log）。

## [S1] Problem

现在的 App 是「课本 + 单词 + 测评 + 对话」的合集：底部 4 Tab（首页/课程/词汇/我的，`ui/navigation/AppTabs.kt:15-20`）、23 个导航目的地（`ui/navigation/Routes.kt:13-87`），练习形态以**单词与句子级重复操练**为主（词汇 Tab `ui/vocab`、弱词专项训练 `ui/drill`、情景课打基础 `ui/scenes/Briefing*` + `DrillFeedbackCard`、跟读/影子跟读 `ui/player`、表达库 `ui/expressions`、CEFR 测评 `ui/assessment`）。真正「说话」的那条链路反而最弱：

- **对话里没有任何声音**：`/dialogue/turn` 的 `reply_audio_url` 字段存在但**从不赋值，恒 None**（`backend/app/api/v1/dialogue.py:145-171`）。
- **对话里没有任何分数**：自由对话的 `polish`/`grammar_score`/`vocabulary_score` 是**硬编码 null**（`dialogue.py:388-390`）。
- **只能用英文开口，且只能靠语音**：`/dialogue/turn` 只吃 `user_audio_b64`、**无文字入参**（`dialogue.py:130-142`）；讯飞 IAT 听写**硬编码 `language="en_us"`**（`app/services/xunfei_iat.py:80-86`），仓内无中文听写路径。中文水平还不够的学员一开口就卡死。
- **聊完就断**：`/dialogue/turn` 是无状态的，历史由客户端攒 `history[]` 回传，没有「回到这个场景接着聊」的实现基础；v2.3.1 换证书还要求存量设备卸载重装。

用户要的是：打开就是微信式聊天列表，点进去和几个角色在真实生活场景里用语音条来回聊；可以说中文、对话照样往下推进；每轮给评分和建议说法，且建议说法在开口前就能看。

## [S2] Design

### S2.1 产品形态：两屏 App

底部 Tab 整体退役，导航只剩 4 个目的地：

| 目的地 | 内容 |
|---|---|
| `ChatList`（根） | 会话列表 = 场景列表。每行：角色头像组、场景名、最后一条预览、时间、未读红点。右上「+」= 一句话自定义场景（复用 202 轮询链）；长按 = 删除会话。 |
| `Chat` | 微信式**群聊**。角色气泡在左（头像 + 昵称 + 语音条），我的气泡在右。 |
| `Settings` | **必须保留的逃生门**：v2.2.4 的教训是更新检查失败时若进不了设置（服务器地址、模型选择都在这里），用户会被弹窗锁死。 |
| `About` | 版本与备案信息；`UpdateDialog` 的「进入设置」跳转目标从 `Route.Me` 改指 `Route.Settings`。 |

删除（Android）：`ui/vocab` `ui/drill` `ui/expressions` `ui/assessment` `ui/lesson` `ui/player` `ui/home` `ui/me` `ui/history`，以及 `ui/scenes/` 下 `Briefing*` `Drill*` `Review*` `SceneDetail*` `GenerateCourse*` `Mission*` `SubScoreReadout` `FeedbackAdvancePolicy` `MissionFinishGuard` `ReviewEntryPolicy` `ReviewPollingPolicy` `ReviewStateMachine` `GeneratePollingPolicy` `GradingPollingPolicy`（**最后这个要留**，见 S2.5）。

删除（后端）：`/lessons` `/books` `/sessions/*` `/score` `/scenes/generate` `/scenes/{scene_id}` `/scenes/{scene_id}/script` `DELETE /scenes/{scene_id}` `/courses/progress` `/assessment` `/expressions` `/stats` `/ability` `/polish` `/history`。

保留（后端）：`/dialogue/*`（含改造）、`/tts`、`/translate`（新增）、`/llm/models`、`/app/version`、`/health`、**`GET /scenes/jobs/{job_id}`** —— 自定义场景骨架作业与整课生成共用这一个轮询端点（`scenes.py:213`，`generation_jobs` 表 `db.py:454`），大扫除时**只删 scenes.py 的 generate/detail/script/delete 与课程相关路由，jobs 路由必须留下**。

讯飞 ISE（英文逐词评测）**不退役**：学员主动说英文时仍出发音分（S2.5）。

**交付时服务层的实际收缩**（比计划删得更深，如实记在这里）：

- `mission_engine.py`（1311 行）改名 **`turn_generation.py`**（约 250 行）：只剩 `generate_turn` + `anchored_pronunciation` + `coerce_bilingual` + 生成侧常量；判分/复盘/润色随各自端点删除。
- `drill_grader.py`（1044 行）收缩到约 232 行：只剩 `_judge` 收口 + `LlmUnavailableError` + `turn_generation_unavailable` + 预算常量。
- 整删 `course_generator` `scene_store` `ability_engine` `course_progress` `corpus_loader` `assessment_engine` `models/course.py`；`GenerationError`/`scene_key_for` 搬进 `scene_spec_generator`，`CEFR_LEVELS` 搬进 `models/scene_spec`。
- `scenes.py` 从 8 条路由收缩成 1 条（只剩 jobs 轮询）。

**两条实现期挖出来的硬坑（都有回归锁）**：

- 写 `doc.messages` **必须**走 `thread_store.load_doc` / `save_doc`。浅拷贝 `dict(row.doc)` 会就地改掉 ORM 里那份旧值，写回时新旧内容相等 ⇒ SQLAlchemy 判定无变化 ⇒ **`doc` 列不进 UPDATE**，症状是"`turn_count` 写了、消息还是旧的"这种半行更新。`save_doc` 里 `flag_modified` 是保险。
- 评分回填的水位读**那颗气泡自己的 `at`**，不读 `row.updated_at` —— 后者被"标已读"刷新，等于每次打开聊天都把时钟拨回零点，进程重启后那颗 pending 永远翻不了身。

### S2.2 场景目录：12 个生活场景 × 多角色

`DialogueScene`（`app/services/dialogue_scenes.py:13-58`）从「单一 persona + user_role」扩成多角色：

```python
@dataclass(frozen=True)
class SceneRole:
    role_id: str      # "r1" —— 台词生成时 speaker 取的就是它
    name: str         # 中文昵称，如「前台 Amy」
    name_cn: str
    voice: str        # 必属 Mia|Chloe|Milo|Dean（mimo_tts.py:35 _KNOWN_VOICES）
    persona: str      # 英文，进 prompt
    persona_cn: str

@dataclass(frozen=True)
class OpeningLine:
    role_id: str
    text: str
    text_cn: str
```

- 每场 **2–3 个角色**，各自固定音色；`user_role`/`user_role_cn` 说明「我是谁」。
- `openings`（≥2，各带 role_id）、`beats`(3-6)、`suggestions`(≥2 英中对) 全部中英成对。
- 12 场：餐厅点餐、咖啡店、机场值机、酒店入住、看医生、租房看房、购物砍价、问路、接机、交朋友闲聊、团队会议、工作汇报。
- **自定义场景**（`models/scene_spec.py:35-79` + `scene_spec_generator.py:290`）同批产出 `roles`，否则新场景进不了群聊。
- 沿用既有纪律：**dataclass 不给默认值**逼漏填，静态兜底字段不得复活。

### S2.3 会话线程落库

新表 `dialogue_threads`（照 `dialogue_scenes:158` 的 `doc` JSON 形状）：

```
id, owner_key VARCHAR(64), scene_key VARCHAR(64), doc JSON,
turn_count INT, grading_status VARCHAR(16), created_at, updated_at
UNIQUE INDEX (owner_key, scene_key)     # 一个场景一条会话
```

Alembic `down_revision = "c3b7e5a91d24"`（当前 head），必须 **SQLite / PG16 双向可逆**。

**旧表全部原样保留**（`lessons` `history` `practice_sessions` `practice_steps` `scene_courses` `ability_profiles` `ability_events` `expressions` `assessment_*` `course_progress` `annotated_diffs`）：只删代码路径与端点，**不写 drop 迁移** —— 删表不可逆，而产品改动并不需要它。

端点：

| 方法 | 路径 | 语义 |
|---|---|---|
| `GET` | `/dialogue/threads` | 会话列表（预览、`updated_at`、未读数、`turn_count`） |
| `POST` | `/dialogue/threads` | `{scene_key}` 开会话；已存在则**幂等返回既有 id**，首次进入落 `openings` 成语音气泡 |
| `GET` | `/dialogue/threads/{id}` | 全量 messages + `grading_status` 水位（评分回填通道） |
| `POST` | `/dialogue/threads/{id}/turn` | 提交一轮（**取代**无状态 `/dialogue/turn`） |
| `DELETE` | `/dialogue/threads/{id}` | 删除会话 |

`doc.messages[]` 是客户端渲染的唯一真相：

```json
{"id":"m_7", "kind":"line|hint|grade|user", "role_id":"r1",
 "text":"…", "text_cn":"…",
 "audio_url":"/static/tts/b1727be5b385693b.wav", "audio_ms":2880, "audio_pending":false,
 "spoke":"en|zh", "recognized_text":"…", "local_recording":"rec_…",
 "grade":{"status":"pending|ready|failed","score":82,
          "axes":{"relevance":90,"informativeness":76,"appropriateness":85,
                  "beat_progress":1,"pronunciation":88},
          "comment_cn":"…"},
 "beat":"b2", "at":"2026-10-29T13:20:11Z"}
```

- `id` 必须**单调且唯一**：v2.3.0 实战页 `LazyColumn` 用内容当 key 撞过重复 key 崩溃（`6fae05d`），失败也落气泡会放大这类假设，这条不能回退。
- 服务端**不存学员音频**：语音轮只存听写结果，原始录音留本机 `RecordingStore`（48kHz 已上采样），回放走本地文件。
- 未知 / 别人的 id 一律 `404 THREAD_NOT_FOUND`（沿用 v2.3.0 删掉静默回落的口径）。

### S2.4 一轮的输入：一条中英混读听写路 + 文字

```json
{"mode":"voice|text", "audio_b64":"…|null", "text":"…|null", "model_id":"…|null"}
```

**语音固定走 `language="zh_cn"`，不设「中/EN」切换**（2026-10-30 真火实测，`backend/scripts/smoke_iat_lang.py`，四组用例 × 两种语言参数）：

| 音频内容 | `zh_cn` 转写 | `en_us` 转写 |
|---|---|---|
| 纯英文长句 | `'The q 3 spend came in about 12% under forecast.'` | 同文 |
| 纯英文短句 | `'Sure, I can send you the revised deck.'` | `'Sure. I can send you the revised deck.'`（仅标点差异） |
| 纯中文 | `'不好意思，这份报告我还需要再核对一下数据。'` | `'But call is these amazing.'`（**乱码**） |
| 中英混读 | `'这个report the deadline是下周三。'` | `'Take the report the deadline.'`（**中文丢失**） |

⇒ 讯飞 IAT 的 `zh_cn` + `accent=mandarin` **本身就吃中英混读**，英文音频的转写质量与 `en_us` 实质等价。学员说哪种语言都走同一条听写路，**输入通路不需要学员先声明语言**。

| mode | 链路 | ISE 逐词发音分 |
|---|---|---|
| voice | IAT(`zh_cn`) → `recognized_text` → **按转写文本判语言** | 转写**不含汉字**（学员说了英文）才跑，与台词生成并行 |
| text | 直接用 `text`，不经 IAT | **不跑**（打字没有发音可评） |

422：`mode=voice` 而 `audio_b64` 空；`mode=text` 而 `text` 空。

**语言判定事后从转写文本做**（`contains CJK(recognized_text)`），不是事前从音频猜：IAT 已经返回文本，这步零成本零时延。判定结果只影响一件事 —— 要不要跑 ISE。

IAT 改造面：`_build_first_frame(first_chunk, *, last, language)` + `XunfeiIatProvider.transcribe(pcm, *, language="zh_cn")`，把 `xunfei_iat.py:80-86` 的 `business` 三元组从模块常量变成参数，对话链路默认传 `zh_cn`。

**已知副作用（接受）**：`zh_cn` 会规范化英文里的数字（`Q3` → `q 3`、`twelve percent` → `12%`）。送给 LLM 的语义不受影响；作 ISE `read_sentence` 参考文本时与 `en_us` 实质相同（两组英文用例转写一致）。

角色**听得懂中文**：prompt 明确「学员可用中文回答，理解其意图后用英文继续推进 beats，不要求说英文、不纠错」。

### S2.5 台词、语音条、评分、建议

**台词生成**：复用 `mission_engine.generate_turn`（`services/mission_engine.py:528`），`TurnGeneration`（`:126-145`）从五字段扩到**七字段**：新增 `speaker`（取 `role_id`）与 `next_beat`（本轮推进到的 beat，可空）。`temperature=0.7`、socket 10s < 墙钟 14s 不动。prompt 带 roles 清单 + 当前 beats 进度 + 最近 10 轮（`_recent_lines_block`）+ 反重复规则。

**语音条 = 请求内合成 + 软失败**：`MimoTtsProvider.synthesize(reply, role.voice)` → `audio_url`。
实测（2026-10-29，本盒真凭证，3 条真实台词冷/热各一轮）：**冷合成 1.41s / 1.46s / 1.96s，磁盘缓存命中 0.00s**。
预算 `TTS_TURN_BUDGET_S = 3.0`。**超预算或异常一律软失败**：`audio_url=None` + `audio_pending=true`、仍返 200 —— 台词已经生成好了，绝不能因为没声音而 503。客户端见 `audio_pending` 退化为按需 `GET /tts?text=&voice=` 兜底（这条兜底路必须留着，因为请求内只给了 3s）。
`audio_ms` 取 `wav_duration_ms`（后端已读 WAV 头，避免 v2.3.1 修过的「1s 算成 2s」旧坑）。

**台词拿不到**（未配凭据/超时/不合规）→ `503 TURN_GENERATION_UNAVAILABLE`，本轮不落库、不前进（v2.3.0 的 D5 裁决不变）。

**每轮评分 = 异步回填**。新作业 `run_thread_grading_job`，形状照 `run_mission_grading_job`（`api/v1/course_sessions.py:2199` → `_run_grading_job:2226` → `_publish_grading:2287`）：模块级持 task、会话级幂等门 × 逐轮进度、自建 session、必落终态、**终态 CAS 防画像双计**、重启水位重派、失败静默。

| 维度 | 含义 |
|---|---|
| `relevance` | 切题度：这回应符不符合场景与当前拍点 |
| `informativeness` | 信息量：有没有真的给出内容 |
| `appropriateness` | 得体度：语气/礼节 |
| `beat_progress` | 任务推进：beats 有没有往前走 |
| `pronunciation` | 发音：**仅本轮 `mode=voice` 且转写文本不含汉字**（学员说了英文）时带 ISE 逐词分 |

中文轮**不报** `pronunciation` —— 是**整轴不渲染**，不是 0 分（沿用 `BilingualText`「次级语言空白 ⇒ 整行不渲染，不机翻占位」口径）。结果写 `doc.messages[i].grade`，顶层挂 `grading_status ∈ {"", pending, ready, failed}`；作业失败**静默**（`failed` = 没有点评，不是这一轮不存在），过一轮水位可翻身 `ready`。

为什么不放进请求内：判分实测 4.2–6.7s，`IAT 8 + GEN 14 + 判分 7 + TTS 3 = 32s` 直接超客户端 30s `readTimeout`。

**建议回答（可提前获取）**：`suggestion`/`suggestion_cn` 本来就在每轮生成结果里，落成一条 `kind="hint"` 气泡、**默认折叠**（只显示「💡 建议回答 · 看提示」），点开显示英文 + 中文。**零额外 LLM 调用**。`shown_suggestions`（≤8）反重复 echo 沿用。

**客户端回填复用现成件**：`ui/scenes/GradingPollingPolicy.kt:24`（`isPending:32` / `isAwaiting:40` / `shouldKeepPolling:53` / `MAX_CONSECUTIVE_POLL_FAILURES:29`）—— 它是纯函数、与 session 无关，新聊天屏直接搬；搬不走就把 `ui/scenes/GradingPollingPolicy.kt` + `GradingPollingPolicyTest.kt` 移到 `ui/chat/`。

### S2.6 时延预算：25.0s 正好顶格，零余量

`tests/test_latency_budget.py:666` 的门是 `worst + MARGIN_S(5.0) ≤ CLIENT_READ_TIMEOUT_S(30.0)`（`:58/:60`）。本链路求和：

```
IAT 8.0 + max(ISE 8.5, GEN 14.0) + TTS 3.0 = 25.0 ≤ 25.0   ✓ 余量 0
```

该文件有**三把锁**，改预算必须同 PR，否则是「绿着的假安全」：① 求和表读 `(模块, 常量名)` 字符串清单；② `test_budgets_are_named_constants_at_the_call_sites` 靠源码里出现 `hard_budget_s=NAME`，内联成字面量即红；③ `shrink_budget` monkeypatch 的是**消费侧模块**的常量名。`NetworkModule.readTimeout(30)` 与 `MARGIN_S` 不动（沿用 2026-10-08 用户裁决）。

**记给后来人**：这条路零余量。上游任何一处放宽预算，必须同步削减他处或改全局超时（后者会连 `/tts`、`/translate` 一起放宽，且必须配强更才对存量包有效）。

### S2.7 长按翻译：已有双语本地切，其余真翻

仓内此前**没有任何翻译端点**（只有 `/polish` EN→EN + `polished_cn`）。

- 角色台词、建议回答：`text`/`text_cn` 都在消息体里 → 长按**本地切换**，零调用零延迟；
- 学员自己的中文回答（`recognized_text`）、其他无对照文本 → `POST /translate {"text":"…","target_lang":"en|zh"}` → `{"translated":"…","source":"llm|stub"}`；
- `TRANSLATE_BUDGET_S = 6.0`，独立请求、不占 turn 预算；缺凭据/超时 → `503 TRANSLATION_UNAVAILABLE`，客户端给可读中文提示，**不机翻占位、不静默显示原文**。

### S2.8 微信式聊天 UI（Android）

新包 `ui/chat/`：`ThreadListScreen` + `ChatScreen` + `ChatViewModel` + `VoiceBubble`。

- **语音条**（新造 —— `MissionScreen.kt:382` 的 `SpeechStripRow` 是**评分维度条**不是语音条，不可复用）：气泡内 = 时长文字 + N 根波形条；未播放时红点提示；播放中波形逐段点亮。
- **点击展开文字**：未播放的角色气泡**只显示语音条**，点击后播放并在下方展开 `BilingualText`（`ui/components/BilingualText.kt`，保留），再点收起。
- **长按**：`combinedClickable` 的 `onLongClick` → 翻译（本地切 or `/translate`）。
- **我的气泡**：语音轮 = 语音条（本机 `RecordingStore` 回放，非 TTS）；文字轮 = 直接显示文字。
- **hint 气泡**：折叠卡「💡 建议回答」；**grade 气泡**：`📊 82 · 切题 90 / 信息 76 / 得体 85 / 推进 ✓`，`pending` 时「评分生成中…」。
- **输入栏**：中「按住说话」（复用 `ui/components/HoldToTalkRow.kt:56` `HoldToTalkRow(row: HoldToTalkRowUi, modifier)`；`RecordingPulseMeter` 保留）· 右「⌨」文字输入。**没有语言切换控件** —— 语音一律走 `zh_cn` 中英混读听写（S2.4 实测），学员说中文还是英文由服务端从转写文本判。
- **播放**：`audio/AudioPlayer.kt:46` `play(url, onError, onCompletion)`（Media3/ExoPlayer，48kHz 链路 v2.3.1 已修好，不动）。
- **头像**：角色名首字圆形色块（Compose `Box`），**不新增 drawable 资源**。
- **配色**：背景 `#EDEDED`、角色气泡 `#FFFFFF`、我的 `#95EC69`、昵称 `#576B95`。

### S2.9 Room：表体冻结，只断读写

`data/local/AppDatabase.kt:7-20` 有明确记载的硬约束：**Room 2.6.1 的 schema 身份哈希在 version 不变时一改就崩存量安装**（`RoomOpenHelper.checkIdentity` 无条件 throw，`fallbackToDestructiveMigration()` 不覆盖该路径）。

所以弱词表**留体删用**：`MistakeWordEntity` / `MistakeWordDao` / `HistoryCacheEntity` 与 `version = 3` **一字不动**，只删读写路径 —— 即 `MistakeWordRepository`（`data/repository/MistakeWordRepository.kt:15,23`，阈值 70 在 `:57`）及其全部注入点（`PlayerViewModel.kt:131`、`FreeDialogueViewModel.kt:112`、`VocabHubViewModel.kt:33`、`MistakeDrillViewModel.kt:50`）。`EnglishContentDatabase`（`CourseCacheEntity`/`ExpressionCacheEntity` 及两个 DAO）随课程/表达库整体退役 —— 它是独立数据库，删掉不影响 `AppDatabase` 的身份哈希。

### S2.10 版本与发布身份

`android/app/build.gradle.kts:43-44`：`versionCode = 15 → 16`、`versionName = "2.3.1" → "3.0.0"`（大改走 major），同批增 `CHANGELOG.md` 条目 —— CI 的 `release-gate`（`.github/workflows/android-ci.yml:34-`）要求改 `android/app/src/main/**` 必须同范围满足两者，**不使用 `release-gate-skip` 逃生口**。

本批交付边界（已裁决）：**代码全绿 + 本地验收**；不 push、不打 tag、不部署生产、不动 `backend/.env`、不 restart 容器。

## [S3] Out of Scope

- **不删任何数据库表**（含生产库 `english_prod_5173`）：旧表与历史数据原样保留，只删代码路径。
- **不发版、不部署**：不 push、不打 tag、不跑 `release.yml`、不跑 `publish_apk.sh`、不切 OTA、不动 `APP_LATEST_VERSION`/`APP_MIN_SUPPORTED_VERSION`、不 `deploy.sh restart`。本盒即生产机（`:5173`），大扫除后的后端**只存在于 worktree**。
- **不处理旧包兼容**：后端大扫除后 ≤v2.3.1 的包调 `/lessons`、`/sessions`、`/score` 会 404 —— 这是「同步大扫除」已裁决的代价，因不部署而暂不影响存量真机。
- **不做真机走查**（本盒无 Android/鸿蒙设备）：语音条播放、长按手势、按住说话、中文听写的真机手感只有 JVM 单测证据。
- **不动全局网络超时**：`NetworkModule.readTimeout(30)`、`MARGIN_S`、采样率链路不改。
- 不做账号体系与多设备会话同步（owner 隔离仍是「信任声明 device 即所有权」）。
- 不做图片/表情消息、撤回、@ 提及、已读回执等微信非核心能力；不新增 TTS 音色。

## Tasks

- [x] T1: 后端场景目录重做 —— 12 个生活场景 + `SceneRole`/`OpeningLine` 多角色，自定义场景骨架同批产出 roles — acceptance: `GET /dialogue/scenes` 返回 12 场，静态校验逐场断言 roles≥2（voice ∈ 四音色、persona 中英齐）、beats 3-6、openings≥2（各带 role_id）、suggestions≥2 英中对，漏填即红 (covers: S2.2)
- [x] T2: IAT 语言参数化 — acceptance: `transcribe(pcm, *, language=…)` 落地；`zh_cn` 与 `en_us` 各有测试；既有 `test_dialogue_iat.py` 6 条英文用例**一字不改**仍绿 (covers: S2.4)
- [x] T3: `dialogue_threads` 表 + Alembic 迁移 + 线程端点 — acceptance: 迁移在 SQLite 与 PG16 双向可逆；同 owner+scene 二次 `POST /dialogue/threads` 返回同 id 且不重复落 openings；未知/越权 id 一律 404 `THREAD_NOT_FOUND` (covers: S2.3) (depends: T1)
- [x] T4: `POST /dialogue/threads/{id}/turn` —— 输入分派(voice/text) + 七字段台词（含 speaker/next_beat）+ 请求内 TTS 软失败 — acceptance: 语音轮一律走 `zh_cn` 听写；**转写含汉字则不跑 ISE、纯英文则跑 ISE**（各一条用例）；text 不跑 IAT；TTS 超预算 → 仍 200 + `audio_pending=true`；LLM 不可用 → 503 且本轮不落库不前进 (covers: S2.4, S2.5) (depends: T2, T3)
- [x] T5: 每轮评分后台作业 + `grading_status` 水位回填 — acceptance: `pending→ready` 翻转、终态 CAS 不双计、作业失败静默且过水位可翻身、重启水位重派 —— 各一条测试；中文轮不产出 `pronunciation` 轴 (covers: S2.5) (depends: T4)
- [x] T6: `POST /translate` — acceptance: `zh→en`、`en→zh` 各一例；缺凭据 → 503 `TRANSLATION_UNAVAILABLE`；预算是具名常量且被 AST 门点名 (covers: S2.7)
- [x] T7: 时延求和表纳入 TTS 并同批过门 — acceptance: `test_latency_budget.py` 求和式含 `TTS_TURN_BUDGET_S`，算式 `8 + max(8.5,14) + 3 = 25 ≤ 25` 全绿，三把锁均指向新常量名 (depends: T4, T6; covers: S2.6)
- [x] T8: 后端大扫除 —— 删课程/词汇/测评/统计端点及其服务层与测试 — acceptance: 保留清单（`/dialogue/*` `/tts` `/translate` `/scenes/jobs/{job_id}` `/llm/models` `/app/version` `/health`）之外一律不再注册，**`GET /scenes/jobs/{job_id}` 明确留在路由里**；`ruff check` / `ruff format --check` / `mypy app` / `pytest` 全绿；被删用例逐条登记在报告里 (covers: S2.1) (depends: T5, T6, T7)
- [x] T9: Android 导航收缩 + 会话列表屏 — acceptance: 根为会话列表、`Routes.kt` 只剩 4 个目的地、底部栏删除；更新失败弹窗「进入设置」仍能落到 Settings；`AppTabsTest` 按新导航重写并绿 (covers: S2.1) (depends: T8)
- [x] T10: Android 微信式群聊屏 —— 语音条 / 点击展开文字 / 长按翻译 / 建议折叠 / 评分卡 / 按住说话 + 文字输入（无语言切换控件） — acceptance: 气泡纯函数各有 JVM 单测（单调 key、时长格式化、双语空白不渲染、`audio_pending` 走 `/tts` 兜底、翻译本地切 vs 端点分派、grade 三态渲染）；`assembleDebug` 成功 (covers: S2.3, S2.5, S2.7, S2.8) (depends: T9)
- [x] T11: Android 删除单词/课程/跟读/测评/统计屏 + Room 留体删用 — acceptance: `ui/vocab` `ui/drill` `ui/expressions` `ui/assessment` `ui/lesson` `ui/player` `ui/home` `ui/me` `ui/history` 与 `ui/scenes/{Briefing,Drill,Review,SceneDetail,Generate,Mission}*` 不再存在；`AppDatabase.kt` 的 entities/version **逐字不变**；ktlint exit 0；detekt 相对基线 103 零新增 (covers: S2.9) (depends: T9)
- [x] T12: 版本身份 + 文档定版 — acceptance: `versionCode=16` / `versionName="3.0.0"` / CHANGELOG 新条目三者同范围；README、`docs/usage-guide.md`、`docs/operations.md` 对账并明确标注「未部署、未发版」 (covers: S2.10) (depends: T8, T10, T11)

## Journey log

1. **一次用户澄清改掉了整个输入设计**。我原方案里加了「录音前中/EN 切换」，理由是讯飞 `language` 必须在送音频前定死。用户澄清"不需要中文语音，只是用户可能会说中文，系统能识别转写就行"之后去实测，发现 `zh_cn` **原生支持中英混读**（纯英文音频转写与 `en_us` 实质等价，反之 `en_us` 对中文出乱码）。于是切换控件、请求里的 `lang` 字段全部删除，语言改为事后从转写文本判定。**教训：我把它当成"约束"的东西，其实只是我没验证过的假设。**

2. **worktree 缺 `.env` 会让实测全线骗人**。讯飞签名用空密钥报 HTTP 401、MiMo TTS **静默**退化成 stub 假音频（只打一行 DEBUG，日志上看着像合成成功）。第一次中英对照探针全部失败就是这个原因，不是服务不支持。同理，复用主检出的 `.venv` 是另一个陷阱：`_editable_impl_*.pth` 写死主检出绝对路径，直接复制会让测试**静默加载 main 的代码**。

3. **两个"半更新"形状**。① `dict(row.doc)` 浅拷贝与 ORM 共享内层 list，调用方就地改掉了"旧值"，写回时新旧内容相等 ⇒ `doc` 列根本不进 UPDATE，症状是 `turn_count` 写了、消息还是旧的 —— 比整行失败难查得多。② 评分水位最初读 `row.updated_at`，而 GET 标已读就会刷新它 ⇒ 每次打开聊天都把时钟清零，挂死的 pending 永远够不到水位。两者都加了回归锁。

4. **首轮评分偏严是一个需要裁决的产品问题，不是 bug**。真火首轮：学员第一句就正确点单，模型却给 36 分并说"未回应当前议程（处理错误或结账）"—— 它自行把议程推前了再回头打学员。修法要先定"议程游标以谁为准"，**把分数调高是错的**。已记入待办，本批未擅自改动。

5. **独立审查连续 5 次因基础设施故障未产出**（`APIError` / SQLite `database is locked`，均发生在**回传**阶段而非执行阶段）。最终改为自审 + 逐条取证（AppDatabase 零 diff、无旧表 drop、503 在写库前、翻译无回显路径、T5 四条测试存在）。**代价是这次缺少第二双眼睛**，尤其值得人工复核的是并发段：`dialogue_threads` 的乐观锁在"评分回填"与"学员提交"撞车时的重试路径。
