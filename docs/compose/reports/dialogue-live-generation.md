# 对话升级：LLM 实时台词 + 双语参考 + 判分异步 + 自定义场景 — Final Report

- **Feature**: 自定义/情景对话从「静态剧本回放」升级为 LLM 按场景实时生成；对话两页中英双语；判分移出请求转后台作业；用户可自描场景。
- **Status**: 开发完成、已审查、后端已部署本机生产（:5173）；**Android 未发版**（versionCode/versionName 未动）。
- **Plan**: `.mimocode/plans/1791437201155-proud-island.md`（批准版，含全部实测修订与实施期裁决）
- **Chain**: 本地 main `4fe76e4..6c4b9e1`（25 commits，未 push）

## What Was Built

**根因驱动的三件实事**（生产日志实测定位，见计划 §0/§5）：

1. **台词独占请求预算**：实战轮与自由对话轮各自只剩**一次** LLM 调用（新 `TurnGeneration` 五字段：`reply/reply_cn/suggestion/suggestion_cn/learner_cn`，缺项默认 `""`、上限 500 照 `a_cn/b_cn` 纪律）。`generate_turn` 走 `drill_grader._judge` 唯一收口（坏 JSON 回喂一次、`LlmUnavailableError`），显式 `GEN_TEMPERATURE=0.7`（旧调用点漏传温度落进判分默认 0.2 是「同义反复」第二成因）、socket `10s < 墙钟 14s`（不复刻「单次 socket>墙钟」反转，旧反例入注释）。全链求和 `IAT 8 + max(ISE 8, GEN 14) = 22 ≤ 25` 由 `tests/test_latency_budget.py` 求和表钉死，自由对话轮首次入表。
2. **判分移出请求**：润色/语法/词汇/任务判定/逐词分转后台作业 `run_mission_grading_job`（照仓内 §P6 作业形状：模块级持 task/幂等门/自建 session/必落终态/重启水位重派）。逐轮 `mission.turns[].grading={status,at}` 是**唯一**状态位（顶层再挂轻量指针）；**终态 CAS 门**（事务内复读 + 谓词 + `_save_doc` 乐观锁，输家的 `record_step_evidence` 随回滚作废——判分重放不双计画像）；作业失败**静默**（`failed`=没有润色，不是这一轮不存在），过一轮水位可翻身 `ready`。响应与 `SessionView` 新增 add-only `grading_status`（`""|pending|ready|failed`），回填走既有 `GET /sessions/{id}`+`restore()`，不新增端点。
3. **D5 报错不前进**：台词拿不到 = 503 `TURN_GENERATION_UNAVAILABLE`（工厂收口两处共用），本轮不落库、不返回 fabricated 气泡；旧「剧本回放 + 写死两句」降级路径整体删除，并有测试钉死「不得复活」。
4. **双语面（只对话两页）**：`Polish.polished_cn`；库内既有中文（`hint_cn/a_cn/b_cn/opening_a_cn`）经 API 边界透出（A7'）；反重复 prompt（`_recent_lines_block` 最近 10 轮 Coach 台词+示范句 + `ANTI_REPEAT_RULES`/`LINE_MAX_CHARS` 两侧共用；自由对话 `shown_suggestions`≤8 客户端 echo，服务器前 8/客户端最近 8 差异已文档化）。
5. **自定义场景（D3，进 DB）**：新表 `dialogue_scenes`（scene_key 指纹唯一索引 upsert 幂等、doc JSON、ready-only）+ 迁移 `c3b7e5a91d24`（`generation_jobs` 加 `kind`，**生产已 auto-upgrade**）；`POST /dialogue/scenes/custom` 202 → 既有 `GET /scenes/jobs/{id}` 轮询 → `GET /dialogue/scenes` 合并 `kind="custom"`（其英文展示对**设计性恒空**=按学员语言展示）；`CustomDialogueScene` 十字段照计划原文；场景骨架作业显式 `hard_budget_s=SCENE_BRIEF_JOB_BUDGET_S`（AST 门点名、请求内零 LLM 看门狗）；别人的/未知的 scene_id 一律 404 `SCENE_NOT_FOUND`（静默回落已删）。
6. **关思考管线**：`Settings.llm_disable_thinking`（默认 false——未知 body 参数有网关会 400，实测 `thinking_budget=0` 即被拒）→ `chat(extra_body=…)` 显式给了才转发 → 只挂新链路。本机 `.env` 已设 `true`；`.env.example` 有文档。实测（真 key 真模型）：台词路 thinking-on p50 11-25s → **off 1.9-2.9s**；判分路 ~4.4s。

## Verification

- **四道 CI 门 @ HEAD 全绿**：`ruff check`/`ruff format --check`/`mypy app`（65 文件 strict）/**pytest 644**（后端基线 586→644）；测试重写而非删除（503 面从「200+stub」改为「503+零副作用+重发不重计」）。
- Android：ktlint **0**、JVM 单测 **374/374**（+37：气泡单调 id 判据、场景切换令牌、判分合并纯函数、DTO 加性旧样本 decode、码表逐码含中文+两新码）；detekt 103（基线 100+4 体积类已逐条对账，属发版前拆分议题）。
- 双轮审查链：T3 spec（11 断言逐条硬证，conftest 是替身非掏空、CAS 输家回滚探针、model_id 不偷吃）+ 质量（0 Critical、3 Important 全修）；T4 spec（迁移链头/归属隔离/删兜底/截断 step_id[:32] 跨方言坑等）+ 质量（generate 身份注册漏 commit——探针复现坐实，已修+先红后绿用例）；T5 spec 10/10 + 质量修复轮（LazyColumn 重复 key 崩溃→单调 id；弱词入账时序；协程取消/竞态令牌）→ 复审 8/8 PASS 无新伤。
- **生产冒烟（deploy.sh restart 后）**:健康 200;`/dialogue/generate` 2.6s；`/dialogue/turn` 200 `gen_ms≈2.0-2.1s`、双语回传；自定义场景 202→job ready→目录出现 `kind=custom`；未知/越权 scene 404 ~5-40ms;`:5173` 迁移已升 `c3b7e5a91d24`。

## Open / 移交发版批（非缺陷）

1. **真机走查**（无 Compose UI 测试底座，8 项清单在 T5 报告）：双语各渲染位、判分三态出现/消失、failed 静默、气泡保命实机、快速切场景高亮一致、连挂两次语音不再崩。
2. **release-gate**：改过 `android/app/src/main/**` 而 versionCode(13) 与 v2.2.4 tag 相等——合并/推送批需 bump + CHANGELOG 定稿（未用 skip 逃生口，是刻意留的闸）。
3. **既有债（本批未扩大，登记不修）**：`/dialogue/generate` 仍裸 `provider.chat`（无 hard budget/不关思考/失败回 `status="stub"` 目录开场白，有 `test_bare_provider_chat_calls_pass_an_explicit_timeout` 兜底）；作业族拆 `session_jobs.py`；`source` 字面量常量化；`GRADE_*`/`GRADING_*` 命名统一。
4. `/dialogue/*` 无鉴权——owner 隔离=「信任声明 device 即所有权」（仓内统一口径，非本批引入）。

## Lessons（写给下一位）

- **时延结论必须实测**：「拆小输出就快」被自家冒烟证伪，真根因是隐藏 reasoning token（`smoke_split_latency.py` 可复用，含 thinking 对照）。
- **「解释超过证据」是惯性事故**：本链四次自纠（外推预算、截断窗口行号、注释先于实现的假设）。改 file:line 前 grep 现算；断言「不存在」前 grep 全文。
- **抄作业形状会漏「会话级幂等门 × 逐轮进度」这一条**：跑完复读 todo 再判，比末尾再派生可靠（派生点被在途门自吞）。
- **失败也落气泡放大一切内容相等性假设**：列表 key 必须带外单调 id，「译」展开态随之存活；审查两轮各逮到一张此类脸。
- 本盒生产操作全程留痕：只按用户书面授权动 `.env`/restart；`deploy.sh` 自动跑 alembic——源码回滚跨迁移边界要先看 `git diff --name-only <tag>..HEAD -- backend/app/db/migrations/`。
