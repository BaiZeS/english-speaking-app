# Changelog

## 运维拓扑收敛 — 2026-09-11（无客户端版本变更，真机无需重新下载）

### 工程摘要（代码/脚本侧改动已落在 `8757dda`；本条记录它 + 同批文档对账；**未发生任何部署**）

- **退役 legacy 裸进程回滚路径（决定性实测）**：`backend/scripts/deploy.sh` 删除 `start-legacy` / `stop-legacy` / `legacy_alive()` 与旧 `status` 里那条只认 5173 的 WARN，usage 收敛为 `{start|stop|restart|status|migrate|logs [n]}`。这不是顺手清理——`docs/operations.md` 一直把 `start-legacy` 写成「回滚逃生口」，而实测它依赖的 `.deploy.env` 里 `PROD_DB_URL` 指向 `postgresql+asyncpg://…@127.0.0.1:5432/english_prod_5173`，即 **dev postgres 容器（`english-postgres`）里的同名库**，内容实测 **1 user / 0 sessions / 0 history**；真生产库（`english-postgres-prod` 内、卷 `english-prod-pgdata`、不发布宿主端口）为 **4 users / 2 sessions / 1 history**（最新会话 2026-09-10 00:20:54+00）。照旧文案「回滚」过去等于把生产切到空库，学员进度、历史、能力画像全失——**它是数据丢失陷阱，不是安全网**。
- **后端回滚改为源码口径**：`git checkout v<上一版> -- backend/ && backend/scripts/deploy.sh restart`（compose 从工作树重建，用**真**生产库）。⚠️ 同批写进 operations.md 的警示：`scripts/docker-entrypoint.sh` 每次启动跑 `alembic upgrade head`，**跨迁移边界的源码回滚会失败**——库已在更新的 revision 上，旧代码的 `backend/app/db/migrations/versions/` 不认识它，alembic 报 `Can't locate revision identified by …`；回滚前先 `git diff --name-only v<上一版>..HEAD -- backend/app/db/migrations/`，非空就必须先有 downgrade 方案（本轮核实 `v2.1.0..v2.2.0` **未改任何迁移文件**，故 2.2.0→2.1.0 安全）。一并入账的已知缺口：`RELEASE_TAG` 没有任何脚本会设置，镜像恒为 `english-assistant-api:local`、每次 rebuild 覆盖——**今天没有基于镜像的后端回滚**。
- **删除的文件**：`backend/scripts/cutover_to_compose.sh`（其 :89 的 `pkill -f "uvicorn app.main:app…"` 是仓库最后一处按模式杀 uvicorn 的代码；且陈旧库 drop 后它的第一步 `pg_dump` 必然失败、脚本永久失效——git 历史即记录）；`backend/.deploy.env`（gitignored，唯一键 `PROD_DB_URL`——明文 DSN 指向陈旧库，唯一消费者是 `start-legacy`；`.gitignore` / `backend/.dockerignore` 条目同步清除）；`backend/logs/english-backend-5173.log` 与 `english-backend-8000.log`（按精确文件名删）。**刻意保留**：`backend/logs/pre-compose-cutover-20260907T111032Z.dump`——已验为有效的 `PostgreSQL custom database dump v1.15-0`、35357 字节、Sep 7 19:10，是那份陈旧库内容的**唯一既存备份**。**留档史实**：被删的 `english-backend-8000.log` 里含 `Uvicorn running on http://0.0.0.0:8000`，是旧裸进程曾绑宿主 8000 的实证（今天的宿主 8000 属 dev 栈）。
- **`deploy.sh status` 现在正面回答归属**：用 `docker inspect -f '{{.State.Pid}}' english-api-prod` 打印生产容器的宿主 PID，并注明「这是容器进程，勿 kill/pkill/fuser，权威判据 `docker top english-api-prod`」；保留的唯一 WARN 是真正要紧的那一种——**API_PORT 有应答而容器没在跑**（应答方是别的东西）。旧实现只 pgrep `--port 5173` 的裸进程，对容器的 `--port 8000` argv 完全盲，两头都不准。动因见下条与 operations.md §6.1。
- **进程归属判别入档（operations.md 新增 §6.1，含三种 uvicorn 指纹表）**：生产容器的 uvicorn 在宿主 `ps` 里是 root 所有的 `/usr/local/bin/python3.11 /usr/local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`、cwd `/app`、**没有任何宿主监听**（宿主端口的监听在 docker-proxy 上）——形状与"滞留的裸进程"无法肉眼区分。实测校准：非 root 对它 `kill -0` 得 **EPERM**，`pkill -f uvicorn` 杀不掉生产（但那是**静默无效**，不是安全），真实杀向量只有**免密 sudo**（本盒有）与 **docker 组**；权威归属判据 = `docker top <容器>` 或 `.State.Pid` 配 `/proc/<pid>/cgroup`（`docker-<id>.scope`）与父进程 `containerd-shim-runc-v2` 双证。**史案更正**：项目记忆里那个「root 僵尸 uvicorn app:app，无监听，杀不动」的 **PID 2117 不是本项目的**——它的宿主 PID 与 `docker inspect -f '{{.State.Pid}}' bill-recognition-bill-recognition-1` 完全一致、cgroup 与该容器的 shim（PPID 2024）吻合、State 是 `S`（10 线程）**不是 Z**；它是另一项目（bill-recognition）健康的容器 init 进程，`app:app` 与 `--port 8000` 是那个项目自己的模块路径与容器内端口，杀它会打掉别的项目。
- **dev 栈绑定收紧（`backend/docker-compose.yml`，纯定义改动，下次显式起 dev 栈才生效）**：两个发布端口改 `127.0.0.1:8000:8000` + `127.0.0.1:5432:5432`（`docker compose config` 已核两条均渲染 `host_ip: 127.0.0.1`；**生产栈 `docker-compose.prod.yml` 未动**）。影响：Android **模拟器不受影响**（debug 包内置 `http://10.0.2.2:8000/api/v1/`，`android/app/build.gradle.kts:39`，`10.0.2.2` NAT 到宿主 loopback，照常可达）；**真机局域网调试 dev 栈失效**——改 SSH 隧道 / `adb reverse` 或用模拟器（开发机上裸跑 `uv run uvicorn --host 0.0.0.0` 仍是局域网直连的唯一路径，该跑法本条保留但边界钉死为「仅开发机，生产机禁止」）。收益：彻底消除「在生产机上误起 dev 栈 = 抢占 `0.0.0.0:8000` + 多出一个与生产容器 argv 只差 `--reload` 的进程」这第三重歧义，并关掉 5432 的局域网暴露。
- **修正危险指引（operations.md 原 :203）**：旧条目「`pkill -f` 一律 `zcode[-]cli`/`uvicorn.*` 方括号自匹配免疫写法」里的 `uvicorn.*` 模式，sudo 下命中的正是生产容器。已改写为：**本项目不再存在任何按模式杀 uvicorn 的合法场景**，要停 API 只有 `deploy.sh stop` 或 `docker stop english-api-prod`；方括号自匹配规则保留但限定于非 uvicorn 模式（如 `zcode[-]cli`），`nohup … </dev/null & disown` 对宿主长跑任务的纪律照旧。
- **文档对账**：`docs/operations.md` §1 三行表格（进程方式/生产库/密钥）换成上述真实口径并记明 loopback 绑定后果；§2 cheatsheet 与新 usage 对齐、注明 `status` 打印容器宿主 PID；§6 的 start-legacy 提及与 pkill 指引改写；**§6.1 新增加为 §6 的子节，未重编号任何既有章节**（`backend/app/config.py`、`backend/README.md`、CHANGELOG 引用的 "operations.md §6" 锚点保持原指向）。`backend/README.md`：legacy 逃生口句删除、cutover 脚本条目改史实、日志条目改写、真机连机地址按 loopback 绑定改写、裸机 `uv run uvicorn` 指引**保留**但加"仅开发机"边界注（其 `--host 0.0.0.0` 必须的理由属裸进程，容器侧的理由属 DNAT，两条不许互换——见 §6.1）。`backend/.env.example` :74 的 `cutover_to_compose.sh` 改过去时；**:91「上方 `DATABASE_URL` 仅裸进程开发时用」保留**——退役的是服务器上那条指向空库的回滚路径，不是本机裸跑开发。README :101-102 的 `:8000` 桥退役史实保留并补"曾绑宿主 8000 的是裸进程、今天宿主 8000 只属 dev 栈"一句以防再次对号错位。
- **验证边界（诚实）**：本条为文档改动，未跑测试套件（无产品代码改动；运行时收敛由另一会话另行推进）；自身只做了 `bash -n backend/scripts/deploy.sh` 与全文 grep 对账。**未部署**：生产容器 `english-api-prod` 未动、未重启，仍 healthy 服务 v2.2.0。

## v2.2.0 — 2026-09-11 · 五个真机症状，外加把「发版」从人的记忆里取出来

versionCode 9 / versionName 2.2.0。**与旧版不兼容**（`finish-mission` 契约变更），本版按强制升级发布，见下「发版与升级」。

> **本版第一件该说的事**：commit `2fd067d`（长按录音 + 实时麦克风音量表，改了 `android/app/src/main/` 下 **20 个文件**，其中 17 个是实质改动）自 2026-09-09 起就躺在 `main` 上、双 CI 全绿，但它没动 `versionCode`——于是 OTA 通道上那份 APK 仍是 v2.1.0 的树（`25d05a3`，`2fd067d` 的**祖先**）。用户报告的 5 个症状里有两个（「还是点按、不是长按」「录音条固定不动」）源码早就动过了，学员手机上一次都没拿到。**这两项修复随本版第一次到达设备。**
> v2.1.0 之后 `CHANGELOG.md` 确有三个新章节，但它们都显式标注「无客户端版本变更」——所以「v2.1.0 起没有任何客户端改动上过手机」这句话是准确的。真正的缺陷不是"忘了 bump"，而是系统里没有任何东西在问「HEAD 可发布吗」；本版把这个问题交给机器（见工程摘要第一条）。

### 用户可感知（这一版打开 App 能看到什么不一样）

- **长按就是长按**：打基础、实战对话、跟读练课、角色对话、弱词本、测评朗读题——短句面一律**按住说话 · 松开发送**，按住即录（键变红 + Stop 图标），松手即停并提交；按住期间不松手不会出现"既已开始又已结束"的错乱。
- **点按的面不再谎称长按**：影子跟读（整篇连读，没人能按住不松手几十秒、且它没有 30 秒上限）与自由对话（一轮回答可以很长，30 秒到点自动发送）**保留点按开关**，但文案改口成「点一下开始 / 点一下结束并发送」，并且旁边给出**已录 `mm:ss` 计时**——自由对话在离上限 5 秒时追加「即将自动发送」。全 App 不再有"文案承诺长按、控件其实是点按"的屏幕。
- **录音条真的会滚了**：说话时波形从右往左推，每根条按自己那一帧的音量取高（不再是整块等高、也不再是阈值电平表），约 1.6 秒的历史在屏上滚过；**松手后这一条的形状会留在屏上**直到评分回来，不再是"一松手界面就空了"。自由对话与 CEFR 测评页此前**根本没有**录音条，现在也有了。
- **评分环节不再骗人**：松手进入评分时，屏幕底部显示「评分中…」，而不是"跳过额度已用完"（此前同一个布尔把"额度用完 / 没有待做步 / 请求在途"三件事压成一句话，于是评分那 8–30 秒里底部一直在喊额度用完了，而同屏右上角还印着"跳过额度 2/2"）。额度真的用完才说用完（并报出每场几次），全部步骤做完说做完，没有清单可跳时这一行整个不出现；快照加载失败给的是**可重试**的错误页，而不是永远亮着的"正在恢复会话…"。
- **每个环节练完立刻有反馈**：跟读/复述/翻译/造句每一题答完就直接看到反馈卡——总分 + **五个维度子分**（发音/流利/完整/语法/词汇；服务端说"这一维没有证据"的那些**不画**，不会被算成 0 分）+ **逐词芯片带音标** + 引擎实际听到的转写原文 + 中文建议 + 要点与错误。打到 **85 分以上**停留 5 秒后自动进下一题（小字低透明度倒计时），**滚一下或点一下就取消**，改成你自己掌握节奏；85 分以下必须手动点「继续」，因为那正是最该把中文建议读完的分数带。退出重进这节课，已答步骤的反馈**还在**（服务端一直在下发每步的最近评分，此前被客户端丢掉了）；进度点上也直接印分数。
- **每日练习收工不再超时**：点「收工」后**立刻**进复盘页——总分圆环、四维条、任务清单、逐句对照、生词，这些数字在收工那一刻就已经算完落库；只有那两句 AI 评语的位置写着「AI 正在写总评…」，几十秒后补齐，不用干等一个转圈的进度条，也不会再看到裸英文红字 `timeout`。**聊到轮次上限自动收工**（每日练习最常见的结束方式）走完全一样的路径。
- **复盘报告回得去了**：练完退出后重进课程详情，会看到明确的「**查看上次复盘**」（另一颗键、另一句话），直达复盘页；首页也有「**最近复盘**」。修好之前这里只有一颗「开始学习」，而它查不到已完成的会话，于是点下去是**新开一局并悄悄丢掉刚写好的那份报告**。现在那颗主按钮在这种场合自己写「再练一次（新开一局）」。
- **失败与降级都用人话说**：后端错误码走一张共享中文表（含此前**完全没有映射**的 `SKIP_LIMIT_REACHED`），表里没有就采纳后端已经写了中文的消息，**绝不把英文原文递到学员眼前**；读超时的文案也老实说明"服务器可能仍在处理，稍后从最近复盘或历史里看结果"，而不是只喊一句失败让人反复重发。
- **总分不许是"—"**：一场练习没有任何可信评分证据时（外部评测与 LLM 判分都没参与），复盘页给一句解释——「本场没有可信评分证据 (外部评测 / LLM 判分未参与), 总分与四维留空 —— 不是练得差」，不再用一个破折号让人以为自己考了零分。
- **杀进程不再丢成绩页**：课本练课的成绩聚合页以前只存在内存里，进程被回收就全没了；现在落一份 JSON 在应用私有目录，重开还在。

### 工程摘要

- **R1 交付闭环：把版本号递增变成机器门（本版真正想根治的东西）**。`.github/workflows/android-ci.yml` 新增 `release-gate` job：一个 push/PR 的**整个事件范围**（`github.event.before..after`，PR 用 base..head，而不是只看 HEAD commit）改了 `android/app/src/main/**`，就必须同时 (a) 让 `android/app/build.gradle.kts` 的 `versionCode` 严格递增、(b) 让 `CHANGELOG.md` 增加内容，否则**红**——不是 warning（warning 就是那条已经失败过一次的人记 SOP：`docs/operations.md` 第 3 节写着"versionCode 永远严格递增"）。`build-debug-apk` 也 `needs` 它。一条受控例外：尚未发布的"版本列车"（HEAD 的 versionCode 高于最近可达 tag、且 CHANGELOG 已有该版本章节）允许不重复 bump，否则 P0 先 bump、P1–P6 继续叠在同一版上的发版方式会被逼着给同一轮发布刷多个版本号。逃生口是 commit message 里的 `[release-gate-skip: <理由>]`（空理由不生效，命中行进日志与 step summary）。
- **文档对账（同一病灶的另一处表现）**：`android/README.md` 一直写着"168 个 JVM 单测"，本次开工前实清点是 176，现在是 **327**；`README.md` 把课文位置进度条列为"录音可视化"（录音期间它按定义不可能动——这正是"录音条固定显示"观感的一半来源），已改口并给进度条加了语义标签。
- **问题 2 为什么"结构上不可能滚动"**：发版构建里电平是写死的常量（`level = if (isRecording) 0.7f else 0f`），而振幅高度画在透明盒子上、可见盒子恒满高；即便在 HEAD 上，旧组件也是无状态阈值电平表（28 个固定槽位、所有点亮条共用一个高度），无历史缓冲、无动画。现在是真滚动波形：`ui/components/RecordingWaveform.kt`（Canvas + **一个** `Animatable` 驱动子条滑移，不做 N 个值的动画）← `AudioRecorder.waveformFlow` ← 纯环形缓冲 `audio/WaveformHistory.kt`（40 条 ≈ 1.6 s @ 录音机 ~25 Hz 帧率）。喂的是**平滑前**的逐帧峰值：`AudioLevelMapping.smooth` 的 DECAY=0.25/帧需要约 440 ms 才能从 1.0 落到 0.05，用它画波形会把 3–5 音节/秒糊成一片（该映射及其 9 个单测**一律未动**）。`finalizeTake()` 刻意**保留**历史而不是清空，于是评分期间形状仍在。旧组件 `RecordingLevelIndicator.kt` 被**删除**，让编译器强制 5 个调用点在同一提交内迁移。
- **问题 4 的根因不是"没做卡片"，是渲染门键在自我作废的身份上**：卡片门在 `answeredStepId == spec.id`，而 `Graded` 事件**在同一次归约里**重算 `currentIndex` → 产生评分的事件同时销毁了卡片要读的键，过关时卡片永不组合；最后一步过关时 `|| currentStep == null` 那半句又是死代码（提前 return 到不了）。现在门只读独立槽位 `pendingGrade`，并区分 `displayedStepId`（屏上是哪题）与 `answerableStepId`（服务端还允许答哪题）——反馈停留期间这两个问题不再是同一个答案。新组件 `ui/scenes/DrillFeedbackCard.kt`；`step.last_grade` 开始被映射（崩溃恢复后逐题反馈不丢）；实战气泡补了逐轮紧凑发音条。
- **问题 5 的根因不是"LLM 太慢"，是同步 HTTP 里挂了一次没有预算的 LLM 调用**：生产日志（session `719833d1-6e30-4499-896f-6ed18d1501a8`，2026-09-10）显示 `finish-mission` 烧了 ~68 s 才降级，而 `200 OK` 那行从未打印——手机的 30 s `readTimeout` 早就把 socket 关了；报告其实已落库，学员随后猛点四次「收工」收四次 409。现在 `ReviewReport` 只有 `highlights` / `improvements` / `source` / `llm_source` 四个字段来自 LLM，其余全是确定性聚合：请求内算完并 commit 数值骨架、置 `doc["review_status"]="generating"`、**释放行锁**、返回 **202**；后台任务 `run_review_copy_job` 只补文案。客户端立刻跳转并按 `ReviewPollingPolicy`（2 s 起、6 s 封顶、5 min 放弃）轮**已有的** `GET /sessions/{id}`。
- **时延契约（R2，防复发的另一半）**：不变量是「同步 HTTP handler 里的每一次 LLM 调用都必须有显式硬预算，且 `budget ≤ 30s − 同请求内其它 await − 5s 余量`」。权威表在 `backend/app/services/drill_grader.py` 的硬预算块注释里，并由 `backend/tests/test_latency_budget.py` 钉死（含"新增 `_judge` 调用点不写预算就直接红"的 AST 扫描）；文档口径见 `docs/operations.md`「时延预算表」。两个静默放大机制被关掉：`AsyncOpenAI(max_retries=2)` 会把每次"20 s 超时"变成 ~62 s（`with_options(timeout=...)` **保留**构造期的 `max_retries`），现改为 `max_retries=0`；`_judge` 坏 JSON 的第二次尝试现在落在同一堵 `asyncio.wait_for` 墙内。`_judge` 内部把 `TimeoutError` 翻成 `LlmUnavailableError` 是承重的——四个调用点只 `except LlmUnavailableError`，逃逸就是 500。**还有一行明知超预算并在测试里钉了上限**：音频作答的 `/step` 若讯飞 IAT 挂死是 33 s 天花板（该调用点只有服务层 8 s + `open_timeout` 5 s，没有调用点预算），闭合办法写在那段注释里。
- **额外发现的 4 个同区域缺陷（复核时顺手，全部本次修掉）**：**E2**「收工」可重复提交——`finishAndReview` 只守卫 `finished` 不守卫在途位，每次重 tap 再发一个 ~60 s 请求（就是那 4 连 409 的直接成因）；现在守卫在 `launch` **之前同步**翻在途位（在协程内翻是同一帧竞态，两次点按都过得去），收工弹窗确认键在途禁用，失败给显式重试出口。**E3** 打基础页把"加载 / 失败 / 已完成"三态混成一个 `steps.isEmpty()`，与症状 3 同形状，单拆 `canSkip` 修不掉。**E4** 测评页从来就没有录音条（新增，不是修复）。**E5** `ScoreSessionHolder` 无持久化——改成 `filesDir` 里一份 JSON（编解码抽成纯 Kotlin `ScoreSessionCodec`）；**确认过无法从后端重建**：`history` 表每行只有逐句 total/pronunciation/fluency/completeness，没有逐词分、没有建议、没有角色名、也没有 `session_id`。刻意**不用 Room**：`5556851` 是故意删掉 `HistoryCacheDao` 的，而 `history_cache` 至今仍作为**冻结实体**留在 `AppDatabase` 里，只为钉住 Room 2.6.1 的 v3 身份哈希（不 bump 版本就删 `@Entity` 会让存量装在 `checkIdentity` 崩）——那个冻结实体不许动。
- **一条初判缺陷经复核不成立，记录以免被人"顺手修好"**：所谓 `PlayerShadowView` 里 `state.micLevel / 2f` 把电平砍半——全仓 grep 找不到任何电平缩放，命中的 `/ 2f` 全在雷达图与统计卡的几何计算里。**没有这个 bug。**
- **可测试性沿用既有约定**：仍然**没有** `androidTest` 源集，仍不引 Robolectric/Compose 测试栈；判定逻辑一律抽成纯 Kotlin 再 JVM 单测。本次新增的接缝：`audio/WaveformHistory`、`audio/RecordingTakeClock`、`data/remote/BackendErrorText`、`ui/components/WaveformGeometry`、`ui/scenes/ReviewPollingPolicy`、`ui/scenes/FeedbackAdvancePolicy`、`ui/scenes/ReviewStateMachine`、`ui/scenes/MissionFinishGuard`、`ui/scenes/ReviewEntryPolicy`、`ui/scenes/SubScoreReadout`、`ui/score/ScoreSessionCodec`（每个都有对应 JVM 测试）。
- **自动前进阈值取 85 不是 60**：60 是通过线（`MIN_SCORE_TO_ADVANCE`，语义只是"不拦"），85 是本 App 已有的优秀线（`ScoreColorMapper.GREEN_THRESHOLD`、弱词毕业线同值）。60–84 恰是最需要读中文建议的分数带。取消语义：滚动 + 点按任意处即取消（「继续」「再试一次」两颗动作键除外，它们本来就前进）；倒计时自然到期不算"取消"。
- **API 契约变更（breaking，刻意为之）**：`POST /sessions/{id}/finish-mission` 由 200 改 **202**，响应体变成 `{session_id, revision, stage, status, review_status}`，**`report` 字段直接移除**（不是置 nullable）——本次发布按强更走，不同旧客户端做兼容。`SessionView`（`GET /sessions/{id}`）与 mission 轮响应新增 `review_status: str | None`（`generating` / `ready` / `failed`；从未收工为 null）。它**故意**不写成 Literal：值住在 JSON 列里，一条脏的旧数据应当降级成"不可知"而不是让 GET 500。`ReviewReport` 新增 `evidence_note_cn: str = ""`。`doc` JSON 列新增 `review_status` / `review_facts` 两个键——**零 alembic 迁移、零新表、零新端点**。语义坑值得写清：判断"AI 文案到了没有"要读 `review_status`，**不要**读 `report.source`——作业正常跑完而 LLM 挂着时的终态就是 `ready` + `source="heuristic"`，那已是诚实的最终答案。
- **测试基线**：Android JVM 单测 **327 passed / 0 failed**（本轮开工时 176；文档写的 168 在开工前就已过期）；后端 **573 passed / 0 failed**（开工时 528），`ruff check` / `ruff format --check`（110 个文件）/ `mypy app`（61 个文件）全干净，整轮覆盖率 89.89%，稳在 CI `--cov-fail-under=85` 门内。`assembleDebug` 产物 22.1 MB，ktlint 干净，detekt 维持既有的 ~99 findings 软门画像。
- **发版与升级**：本版按**强制升级**发布，这需要**另行**在 `backend/.env` 设 `APP_MIN_SUPPORTED_VERSION=2.2.0` 并 `deploy.sh restart`——`publish_apk.sh` 不写它，而 `/app/version` 的 `min_supported_version` 默认是个 `0.0.0` 哨兵，只有显式配置才产生 `force=true`。回滚 APK 时必须同步把它降回 `0.0.0`，否则会把用户钉在一个已下架的版本要求上。
- **本版没有做、也没有声称做过的事**：**真机验收尚未执行**（`docs/operations.md` 记的是历次发布的真机结果，本版暂无新条目）——上面所有客户端行为都以"源码 + JVM 单测 + 后端集成测试"为据，屏幕上的观感待按验收脚本逐条走一遍。也要诚实说明：现在这台机器现役的是免费额度的模型，一次 500 token 的总评调用**常常仍会**落到确定性文案（`source="heuristic"` + 降级横幅），本次换来的是"在预算内落地"而不是"晚 68 秒再落地"。

## 测试基线归零 — 2026-09-08（无客户端版本变更，真机无需重新下载）

### 工程摘要
- 既有 14 个「基线红」（`test_app_version_resolver`×9 / `test_llm_provider`×2 / `test_llm_endpoints`×2 / `test_dialogue_polish`×1）确诊为**部署配置泄漏**，非代码缺陷：生产机 `backend/.env` 经 `Settings(env_file=".env")` 把 env-first OTA 与 LLM 白名单/目录等调优字段灌进测试共享的 settings 单例（同码在无 .env 的 CI 全绿、stash 隔离前后同红为证）。
- 修复 = `tests/conftest.py` 清盒 fixture 升级为 `_hermetic_settings`：凭据之外，再把 12 个调优字段逐用例强制回代码默认值（清单只增不减，见文件内注释约定）。零产品代码改动。
- 基线：**528 passed / 0 failed**——本机带 .env、shell 故意投毒（`APP_LATEST_VERSION=9.9.9` + LLM 白名单全量注入）均全绿；operations.md「基线 526 测试」口径同步更新。

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
