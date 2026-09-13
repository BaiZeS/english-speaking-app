# 运维与发版 SOP · english-speaking-app（v2.2.1）

部署机 = 本盒（公网 `118.89.58.84`，云防火墙当前仅映射 **TCP 5173/80/8080**）。仓库：`/home/ubuntu/mimo-workspace/english-speaking-app`，工作分支 main（origin==local）。

## 1. 运行拓扑

| 项 | 值 |
|---|---|
| 生产 API | **docker compose 发布栈**：容器 `english-api-prod`（`backend/docker-compose.prod.yml`，宿主端口 `${API_PORT:-5173}`→容器 8000；release 包内置 `http://118.89.58.84:5173/api/v1/`）。**容器内 8000 不是宿主端口**：宿主 8000 属开发栈（`docker-compose.yml`，现只绑 `127.0.0.1:8000`），与生产无关 |
| 生产库 | 栈内 `postgres:16-alpine`（容器 `english-postgres-prod`，卷 `english-prod-pgdata`，库 **`english_prod_5173`**；**不发布宿主端口**）。宿主 127.0.0.1:5432 = 开发栈 `english-postgres`（库 `english_dev`；**2026-09-11 起该容器已停**，需要时 `docker compose up -d postgres` 起回，卷 `backend_postgres_data` 一直在。曾同存的"切换前旧生产库冷备" `english_prod_5173` 已 drop——实测 1 user / 0 sessions / 0 history 的近空库，drop 前已 `pg_dump`，同内容既存备份见 `backend/logs/pre-compose-cutover-20260907T111032Z.dump`）——**运维 SQL/备份一律 `docker exec english-postgres-prod psql -U english ...`**。**dev 栈发布端口自 2026-09-11 收紧为 loopback-only**（postgres `127.0.0.1:5432`、api `127.0.0.1:8000`，`docker compose config` 已核）：局域网/其它机器不再可达；**v2.2.1 起 debug 包也默认指生产公网端点 `http://118.89.58.84:5173/api/v1/`**（`android/app/build.gradle.kts`，此前指 `10.0.2.2:8000`）——本地/模拟器联调 dev 栈需在 App「设置」页把 Base URL 改回宿主机地址，**真机局域网调试 dev 栈仍失效**（改用 SSH 隧道/`adb reverse` 或设置页指公网；局域网直连如今仅剩"开发机上裸跑 `uv run uvicorn --host 0.0.0.0`"这一条路，仅限开发机，见 backend/README 连接表）|
| `:8000` 桥接 | **已停**（不映射公网；旧包 ≤2.0.0 内置 :8000 外网不可达，过渡=一次性 GitHub 直链装 v2.1.0）|
| 进程方式 | **只有 docker compose 这一种跑法**。`docker compose up -d` + `restart: unless-stopped`（随 docker daemon 自动拉起——裸进程时代没有的增益）；由 `backend/scripts/deploy.sh` 统一管理（每条 compose 命令前自动剥离与 .env 同名的陈旧环境变量，.env 唯一事实源）；`start`/`restart` 都是 `up -d --build`（restart 另加 `--force-recreate`）——改 `.env` 后必须 recreate，compose 原生 restart 不重读 env_file、不换镜像；日志 `docker logs english-api-prod`（json-file 10m×5）。**回滚口径 = 源码回滚**：`git checkout v<上一版> -- backend/ && backend/scripts/deploy.sh restart`（走 compose、用**真**生产库）。⚠️ 跨迁移边界会失败：`scripts/docker-entrypoint.sh` 每次启动都跑 `alembic upgrade head`，库已在更新的 revision 上而旧代码的 `backend/app/db/migrations/versions/` 不认识它 → `Can't locate revision identified by …`。回滚前先 `git diff --name-only v<上一版>..HEAD -- backend/app/db/migrations/`，非空就必须先定 downgrade 方案（`v2.1.0..v2.2.0` 已核实未改任何迁移文件，故 2.2.0→2.1.0 安全）。已知缺口：`RELEASE_TAG` 没有任何脚本会设置 → 镜像恒为 `english-assistant-api:local`、每次 rebuild 覆盖，**今天没有基于镜像的后端回滚**。（旧 `deploy.sh start-legacy`/`stop-legacy` 裸进程逃生口已于 2026-09-11 退役删除——它依赖的 `.deploy.env` 指向 dev postgres 容器内的同名陈旧库，实测 1 user / 0 sessions / 0 history，"回滚"过去等于把生产切到空库；理由与过程见 CHANGELOG 同日条目与 §6.1。） |
| 密钥 | 均在 `backend/.env`（gitignored，不入 git；发布栈的 `DATABASE_URL` 由 compose 服务名自动派生）。**2026-09-07 口令已轮换**：旧默认口令（user=english）在 git 历史中公开过、现已失效，tracked 文件里仅存 CHANGE_ME 占位。实测现状（2026-09-07）：百炼 LLM 已换新 key，现役 **qwen3.8-flash**（服务端默认）+ **deepseek-v4-flash-0731**，chat 实测 200 ✓；MiMo-TTS 平台 key（`sk-`，付费线路）已启用，`/api/v1/tts` 真合成 200 ✓；讯飞 ISE/IAT key 已填；**09-08 已真火冒烟过门**（`/api/v1/score` 17s 音频 3.3s 返回 `source=xunfei` 55 词真分 + 括号脏参考回归通过 + IAT 转写通过，容器日志 `xunfei ise ok`；app 端语音轮=待用户真机复确认，观察 `mission turn perf`）|
| OTA APK | `backend/static/apk/<asset>.apk`（gitignored），`/app/version` 的 `APP_APK_URL` 指它；`/static/tts` 同挂载为 TTS 磁盘缓存。**两目录 bind 进发布容器**（`/app/static/*`），宿主路径即唯一实体——host 侧 publish_apk.sh 写完 + `deploy.sh restart`（recreate）即生效；新机器该目录空，OTA 需跑 publish_apk.sh 补种 |

## 2. 日常操作

```bash
S=backend/scripts/deploy.sh   # 仓库根目录下（底层 = docker compose -f docker-compose.prod.yml）
# 子命令全集: {start|stop|restart|status|migrate|logs [n]}——legacy 裸进程子命令已退役删除，见 §1/§6.1
bash $S status     # 栈容器状态 + :5173 health + **生产容器的宿主 PID**（正面回答"ps 里那个 uvicorn 是谁"，勿据此杀进程，见 §6.1）
bash $S start      # up -d --build（拉新代码/新配置，含 migrate 语义——entrypoint 自动跑）
bash $S restart    # up -d --build --force-recreate api。**改 .env 后必用它**：
                   #   compose 原生 restart 不重读 env_file、不换镜像（静默失效陷阱）
bash $S stop       # 只停 api 容器（postgres 继续跑；全栈 down 请手动 compose down，勿加 -v）
bash $S migrate    # 一次性 alembic upgrade head（compose run 独立容器执行）
bash $S logs 200   # 最近 n 行服务日志（= docker logs english-api-prod）
```

改 `.env`（换密钥/模型/APP_* 三兄弟）后：`bash $S restart`，`curl -s http://localhost:5173/api/v1/health` + 看对应端点即验生效。生产库口令轮换是两步活（卷首初始化口令 + `ALTER USER`），见 §6。数据卷 `english-prod-pgdata` = 唯一生产数据，**严禁对 compose 项目 `down -v`**。

## 3. 发版 SOP（Android）

### 3.0 发布身份硬门（先读这条，它取代了过去那句"记得 bump"）

**改了 `android/app/src/main/**` 就必须同范围 bump 发布身份 —— 现在是机器检查，不再靠人记。**
判的是**事件范围**（push 的 `before..after`、PR 的 `base..head`），不是单个 commit，所以"一个 commit 改源码 + 同批另一个 commit 补版本号"合法。实现见 `.github/workflows/android-ci.yml` 的 `release-gate` job（无 JDK/SDK 依赖，纯 git + grep），`build-debug-apk` 依赖它 → 门红则产物也不出。

- 通过条件：范围内 `android/app/build.gradle.kts` 的 **versionCode 严格递增** + **CHANGELOG.md 有新增内容**（当前版本；旧版本条目不补，历史版本号永远不回头）。
  - 例外档（同一轮发布的"版本列车"）：HEAD 的 versionCode 高于**最近可达 tag** 的 versionCode，且 CHANGELOG.md 已有该 versionName 的 `##` 章节 → 允许后续 push 不再 bump（发版流程本就是"先 bump 再叠修复，最后打 tag"）；**tag 一落地这档自然关闭**，下一批源码改动又要现场 bump。代价写在 workflow 注释里：一列迟迟不发版的列车会一直放行，那归 §3.2 的发版纪律管。
- 逃生口：范围内任一 commit message 写 `[release-gate-skip: <一句话理由>]`（**必须带理由**，空理由不生效；命中的那一行会进日志与 step summary）。只该用在"确实不改变可发布产物"的改动上（真实例子：`0fc7e29` 只改了 `BriefingScreen.kt` 里一行注释）。**别**把它塞进 git 模板/alias/pre-commit——那等于删掉这道门。
- 为什么值得这么硬：`2fd067d`（hold-to-talk + 实时音量表，`android/app/src/main` 下 20 个文件）推上 main、双 CI 全绿、**从此永久躺在 main 上**——没动 versionCode，OTA 那份 APK 仍是 v2.1.0 的树（`25d05a3`，`2fd067d` 的祖先），学员报的两个症状在源码里早就修好了却一次都没到过手机。当时缺的从来不是规矩（本节原本就写着"versionCode 永远严格递增"），缺的是有人/有东西**去执行它**。

### 3.1 发版步骤

```bash
# ① 变更就绪 + 本地三连（ktlint.sh / testDebugUnitTest / assembleDebug, 见 android/README）
#    + CHANGELOG.md 新版块 + build.gradle.kts versionCode 严格递增（必须与源码改动在**同一事件范围**内, 见 §3.0）
# ② 推送后务必确认本地==origin 再打 tag（tag 与 push 分离, 防竞态：一次钉错 release 的教训）
git push origin main && git fetch -q origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && echo synced   # 必须 synced 再继续
#    ★ release-gate 是 blocking 门：本盒没装 gh，去 Actions 页面确认 Android CI 的
#    "Release Gate" job 已绿再打 tag（它不装 SDK，通常几十秒内就出结果）。
#    ★ 若门红又自认合理：git commit --amend 在 message 里补 [release-gate-skip: 理由]
#    重推（force push main 之前先想清楚 —— 见 §6 那条例子），别直接绕过。
git tag -a v2.2.1 -m "v2.2.1: ..." && git push origin v2.2.1
# ③ 等 release.yml（~14 min）: 成功且 asset=EnglishAssistant-<ver>.apk,
#    Release 名/tag 正确（workflow 用 GITHUB_REF_NAME，勿改成 git describe——已踩坑）
# ④ 【必须】OTA 自托管切换（否则手机走 GitHub 11-40KB/s 等于没有更新）：
cd backend && bash scripts/publish_apk.sh v2.2.1
# 该脚本自动：GitHub 拉 asset(慢线 ~20-25min) → static/apk → 写 .env 两变量 → restart
# → 自检 source=env + Range 探测。重复跑无害（幂等覆盖）。
# ⑤ versionCode 永远严格递增（v2.1.0=8 / v2.2.0=9 / v2.2.1=10；Android 同名 version 不比, semver 字典序）
#    —— §3.0 的门现在会在 push/PR 上强制它, 不再只靠这句话。
```

### 3.2 强制升级（可选，一条**独立于** `publish_apk.sh` 的生产配置变更）

`publish_apk.sh` 只写 `APP_LATEST_VERSION`/`APP_APK_URL`，**不碰** `APP_MIN_SUPPORTED_VERSION`。而 `/app/version` 的 `min_supported_version` 默认是 `0.0.0` 哨兵——**只有显式配置才有强更语义**（`decideUpdate` 的"跳过此版本"分支只在非强更时生效）。

需要强更时（例：v2.2.0 改了 `finish-mission` 的 202 契约，旧包会拿到空 `review`）：

```bash
# backend/.env  (gitignored; 开发与发布共用这一份——见 §6 最后一条)
cp backend/.env backend/.env.bak-$(date -u +%F-%H%M)
grep -q '^APP_MIN_SUPPORTED_VERSION=' backend/.env \
  && sed -i 's/^APP_MIN_SUPPORTED_VERSION=.*/APP_MIN_SUPPORTED_VERSION=2.2.0/' backend/.env \
  || printf 'APP_MIN_SUPPORTED_VERSION=2.2.0\n' >> backend/.env
bash backend/scripts/deploy.sh restart      # 必须 restart（compose restart 不重读 env_file）
curl -s http://118.89.58.84:5173/api/v1/app/version   # 核对 min_supported_version=2.2.0 + force=true
```

- **影响存量每一位用户**，执行前单独确认；没看到 `force=true` 就是没生效（十有八九是 §2 那条 `restart` 陷阱）。
- **回滚必须同步**：`publish_apk.sh v<旧版>` 之后要把 `APP_MIN_SUPPORTED_VERSION` **改回 `0.0.0` 哨兵**并再 restart，否则用户被钉在一个已经下架的版本要求上——升级提示指向一个 OTA 再也发不出的包，等于自己制造一台砖机。
- 只回滚 APK 不打算回滚要求时（例如旧包有严重缺陷、宁可让人卡在提示上也不放回去），必须**在下一次成功发版前**把要求改回哨兵并留个提醒给未来的运维。

回滚：`scripts/publish_apk.sh v<上一个好版本>`（秒切，GitHub/GCP 双源自动降级）；或临时 `APP_LATEST_VERSION` 回旧值 + restart；强更要求见上一条的同步回滚。

## 4. 密钥启用清单（当前环境 → 真机全功能）

| 服务 | 填 env 键 | 解锁 |
|---|---|---|
| 讯飞 ISE | `XUNFEI_APP_ID/API_KEY/API_SECRET`（09-07 填；**09-08 真火冒烟过门**：`source=xunfei` + `xunfei ise ok` 硬证，逐词分 1-5×20）| 跟读/影子/弱词真实逐词音素分（`source=xunfei`；日志 `xunfei ise ok` 为硬证，**单看分数不可信**）。协议硬要求见 §6 讯飞坑位 |
| 讯飞 IAT | 同上 | 实战/自由对话真实听写（09-08 真机听写转写实测通过；无则文本输入为主路径）|
| MiMo-TTS | `MIMO_API_KEY`（**线路绑定，域名不互换**：`sk-` 平台 key ⇄ `https://api.xiaomimimo.com/v1`；`tp-` token-plan key ⇄ `https://token-plan-cn.xiaomimimo.com/v1`；本盒现为 sk-/api 线路）| 示范声真合成 ✓（09-07 实测 200）|
| 百炼 LLM | `LLM_BASE_URL/LLM_API_KEY`；现役 `LLM_DEFAULT_MODEL=qwen3.8-flash` + `LLM_ALLOWED_MODELS=qwen3.8-flash,deepseek-v4-flash-0731` | 已配 ✓（09-07 实测两模型 chat 200；模型下拉经 `LLM_EXTRA_MODELS_JSON` 下发恢复）|

## 5. 冒烟与验证集（发版/迁移后跑）

```bash
BASE=http://118.89.58.84:5173
curl -s $BASE/api/v1/health                                   # {"status":"ok"}
curl -s $BASE/api/v1/app/version                              # latest=当前发布版, source=env；未配强更时 force=false；配了 §3.2 则 min_supported_version=发布版 + force=true
curl -s -r 0-1023 -o /dev/null -w '%{http_code}' $BASE/static/apk/EnglishAssistant-<ver>.apk  # 206
curl -s "$BASE/api/v1/scenes?category=workplace" | head -c200          # 含职场课
curl -s "$BASE/api/v1/stats?device_id=smoke-0906"                       # 合法 JSON（空态即可）
curl -s "$BASE/api/v1/llm/models"                                       # models 含 .env 白名单两模型 + default_model
curl -s "$BASE/api/v1/tts?text=Hello&voice=Mia" -o /tmp/t.out -w '%{http_code} %{size_download}B\n'  # 200 + wav 头（RIFF）= TTS 真合成通
# key 排查对照组（区分"调用姿势错"vs"key 无效"——09-07 实测：两线路 512 种姿势的 401 与假 key 逐字节一致）:
# curl -s https://api.xiaomimimo.com/v1/models -H 'api-key: tp-fakekey000' | head -c 60
# 完整通关冒烟（生成一条真实练习痕迹 + ★ v2.2.0 的异步总评断言）:
#   POST /sessions{scene_id:scene_ordering_coffee} → /step ×6(text) → /mission ×3 →
#   ① POST /finish-mission 必须**亚秒级**返回 **202**，body = {session_id, revision,
#      stage, status, review_status} 且 review_status=="generating"、**没有 report 字段**
#      （200 或带 report = 契约回退；十几秒才回 = 有人在请求里又塞了 LLM，见 §6）
#   ② **立刻** GET /sessions/{id} → review 数值骨架已在（overall/dims/checklist/pairs），
#      review_status 仍是 generating —— 这一步证明"数字不用等文案"
#   ③ 每 2-6s 轮询 GET /sessions/{id} 直到 review_status ∈ {ready, failed}（后台作业预算
#      45s，正常几十秒内必到终态；超过 ~90s 还没动 = 重派水位没生效，查 §6 作业那两条）
#   ④ 终态断言：review_status=="ready" 且 (review.overall != null **或**
#      review.evidence_note_cn != "") —— 不许出现"总分是破折号而无解释"
#      注意判据是 review_status，**不是** report.source：LLM 挂着而作业正常跑完 =
#      ready + source=="heuristic"，那已是诚实终态
#   ⑤ 二次 POST /finish-mission 仍须 409 MISSION_FINISHED（幂等门没被异步化绕过）
#   ⑥ 自动收工同治：/mission 打到 max_turns 那一轮，响应应带 review_status=="generating"
#      且该请求总时长 <= 23s（不再叠加一次总评 LLM；旧行为是 23+20=43s 结构性必超时）
#   ⑦ GET /courses/progress 应现 attempts≥1
# 讯飞真火冒烟（消耗 ISE/IAT 日额度 ~10 会话，不碰 DB，证据落 /tmp/ise-smoke-*）:
# cd backend && .venv/bin/python scripts/smoke_xunfei_ise.py --quick     # 期望全行 final=True、source=xunfei、退出码 0
# 线上语音轮真声验证（PCM 用冒烟产物；pronunciation/fluency 应为 source=xunfei, w=1.0）:
# python: base64 封 body → curl $BASE/api/v1/score（跟读）与 /api/v1/dialogue/turn（带 device_id+user_audio_b64,
#   历史 1 个 user 回合）→ 日志应见 "xunfei ise/iat ok"；实战语音轮另见 "mission turn perf iat_ms= pair_ms= anchored="
```

```bash
# DB 层核查与备份（发布栈库在 english-postgres-prod 容器，不发布宿主端口——127.0.0.1:5432 是开发库）:
docker exec english-postgres-prod psql -U english -d english_prod_5173 -c 'SELECT version_num FROM alembic_version'
docker exec english-postgres-prod pg_dump -U english -d english_prod_5173 -Fc -f /tmp/bk.dump \
  && docker cp english-postgres-prod:/tmp/bk.dump backend/logs/backup-$(date -u +%F).dump
```

后端回归：`cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app && .venv/bin/pytest`（基线 **573 全绿**，sqlite；CI 含 PG16 + `--cov-fail-under=85`，本机整轮覆盖率 89.89%）。套件清盒由 `tests/conftest.py::_hermetic_settings` autouse 保证：凭据 + 部署调优字段（env-first OTA、LLM 白名单/目录等，清单**只增不减**）逐用例强制回代码默认值——生产机带 `.env` 亦全绿；若出现「只有 .env 在场才红」的测试，先查该清单是否漏了新字段，勿改产品代码迁就。Android 回归：三连（见第 3 节①），基线 **318 个 JVM 单测**（v2.2.1 实测；开工时实清点 328——旧口径 327 在开工前就已过期；更早"从 168 校正到 327/开工 176"的史实见 CHANGELOG v2.2.0 条）。**外加 CI 新增的 `release-gate`（§3.0）——它是 blocking 门，红了就别打 tag。**

**发版状态与验收状态（写文档时点 2026-09-13，诚实记录）**：**v2.2.1 已发布并已上线 OTA**——commit `3b5813f`（tag `v2.2.1`，versionCode 10）推送 main 后双 CI 绿（Backend ✅ / Android ✅ 含 `release-gate`）；APK 因 **Release 工作流的 Create GitHub Release 步骤失败**（构建本身成功；GitHub Release 未建成，疑 API 瞬时错误，且 `backend/.env` 的 `APP_GITHUB_TOKEN` 实测 401 已失效、无法代为重跑）改走**本地复刻 CI 链路**：工作树 == tag 提交（干净树核实）、`./gradlew assembleDebug` 产物直拷 `static/apk/EnglishAssistant-2.2.1.apk`（sha256 前缀 `2c708ffb8061875a`）+ `.env` 写 `APP_LATEST_VERSION=2.2.1`/`APP_APK_URL` + restart——与 `publish_apk.sh` 的落地动作逐行等价，只是少了 GitHub 中转。**实测 `/app/version`：`latest_version=2.2.1` / `min_supported_version=2.2.0` / `force_update=true` / `source=env`；APK range 探测 206 ✓**。强更补设同日生效：`APP_MIN_SUPPORTED_VERSION=2.2.0`（sed 命令见 §3.2）——低于 2.2.0 的旧包收到不可跳过升级（v2.2.0 发布时该配置从未实际生效、暴露面于今日关闭）；v2.2.0+ 对 2.2.1 仍可「稍后再说」。**待办两条**：① ~~GitHub Release 产物补上~~ **已补（2026-09-13）**——重触发方式为删除并原样重推 tag `v2.2.1`（recreate 即重新点火 workflow，run #13 成功；与初跑失败的 step 完全相同，坐实初跑是 GitHub API 瞬时错误）；实测 Release「English Assistant 2.2.1」+ 资产 `EnglishAssistant-2.2.1.apk`（21,815,251 字节）已在、`/releases/latest` 现指向 `v2.2.1`、资产直链 range 探测 206 ✓；② `APP_GITHUB_TOKEN` 已失效需轮换（影响 resolver 的 GitHub 回源 fallback，主路径 env 优先不受影响；轮换时注意 §1.4 密钥卫生与 env 遮蔽纪律）。上面第 5 节冒烟集（尤其 ①-⑥ 那条异步总评链）在 v2.2.1 部署后应实跑留证，若尚无实跑记录则**必须补跑**；本文件里更早的真机/部署结果条目都是历次发布留下的实况记录，保持原样不动。

同样尚未执行的是**真机验收**：v2.2.0 那批（逐条对应用户报告的 5 个症状 + E2/E3/E4/E5 + 升级提示的装机走查）脚本还挂着（发布计划 §5.3），v2.2.1 的脉冲条手感与反馈卡观感同样待验，所以两版所有客户端行为的现有证据只有"源码 + 318 个 JVM 单测 + 后端集成测试 + DEBUG APK 能构建"，**没有任何一条被真机确认过**。别把本节或 CHANGELOG 里的描述当验收结论用。

## 5.5 时延预算表（同步 LLM 调用契约）

**这是契约，不是观测记录。** 权威副本只有一处：`backend/app/services/drill_grader.py` 顶部的「硬预算块」注释（`*_BUDGET_S` 常量与求和表），加上 `backend/tests/test_latency_budget.py` 把这张表钉成测试。本节是它的运维口径 —— **改任何一处都要同批改另两处**（求和只许变小，涨上去测试就红）。

**不变量**：同步 HTTP handler 里的每一次 LLM 调用都必须有**显式**硬预算，且

```
budget <= 30s - (同一请求内其它 await) - 5s 余量
```

- **30s 从哪来**：客户端全站共用**一个** OkHttp client，`readTimeout=30s`、**没有 `callTimeout`**（`android/app/src/main/java/com/app/english/di/NetworkModule.kt`）。超出 30s 的部分客户端**永远收不到**：服务端只是白占一条连接 + 一次 `FOR UPDATE` 行锁，学员看到一句 `timeout`。
- **生产实锤**（session `719833d1-6e30-4499-896f-6ed18d1501a8`，2026-09-10）：总评 LLM 烧了 ~68s 才降级，`POST …/finish-mission 200 OK` 那行**从未打印**——业务成功、报告落库，学员却永远看不到，之后猛点「收工」又收了 4 个 409。**降级本身是有效的，只是晚了 2 倍**，这就是本契约存在的全部理由。

| 常量 | 值 | 管谁 | 备注 |
|---|---|---|---|
| `LLM_TIMEOUT_S` | 20.0 s | **单次尝试**的 socket 超时（`drill_grader.py`）| 不是墙钟封顶，别拿它当上限 |
| provider 客户端 `timeout` / `max_retries` | 30.0 s / **0** | `llm_provider.py` | `max_retries` 必须是 0：SDK 的重试乘在 `timeout` 上（20s×3+退避 ≈ 62s），有它在，任何 `timeout=` 都不是真实上限 |
| `STEP_LLM_BUDGET_S` | 20.0 s | 文本步判分（retell / translate / make_sentence）| 坏 JSON 的回喂重试落在**同一堵墙内** |
| `REVIEW_LLM_BUDGET_S` | 20.0 s | **同步组合** `build_review_report` | **HTTP 端点已不再调它**（只剩脚本/测试）。计划 §P5 建议的 45s 只在"文案不在请求里"时成立 |
| `REVIEW_COPY_JOB_BUDGET_S` | 45.0 s | 后台总评文案作业 `run_review_copy_job` | **故意大于 30s**：收工已用 202 + 数值骨架答复，没人在 socket 上等它。但仍必须封顶 —— 挂死的 LLM 会让会话永远停在 `generating`。**别把它塞进任何同步 handler，也别反过来把 45 改成 20**（那等于总评文案永远在超时边缘降级）|
| `POLISH_BUDGET_S` | 10.0 s | `POST /polish` | 润色**没有**确定性降级（规则改写容易改错意思），超时 = 诚实返回 `polish=null`，不是 500 |
| `ASSESSMENT_JUDGE_BUDGET_S` | 20.0 s | `POST /assessment/{id}/complete` **同步路径**（7 题**一次**批量调用；仅老客户端/不传 `async_judge`）| 逐题判会被 7×20s 拖爆；超时 = 诚实空态（`cefr=null`，零画像写入）|
| `ASSESSMENT_JUDGE_JOB_BUDGET_S` | 120.0 s | 后台判级作业 `run_assessment_judge_job`（v2.2.2 起：新客户端 `async_judge=true` → 202 + 轮询 `GET /assessment/{id}/result`）| 与 `REVIEW_COPY_JOB_BUDGET_S` 同款：在请求之外跑，**故意大于 30s**，但仍必须封顶——挂死的 LLM 会把 attempt 永远留在 `judging`。动机是生产实锤：免费额度限速把同步判级两次都在 20s 撞墙（stub 又被幂等回放固化，学员只见发音维）。stub 结果可经新客户端「重新判级」翻案；日志关键字 `assessment judging accepted` / `assessment judge job published` / `lost the race` |
| `ISE_TURN_BUDGET_S` / `IAT_TURN_BUDGET_S` / `LLM_TURN_BUDGET_S` | 8 / 8 / 15 s | 实战语音轮（`course_sessions.py`）| 契约的**另一半**，与上表同一次求和；改任何一边都要重算 |
| `REVIEW_REDISPATCH_AFTER_S` | 45 × 2 = **90 s** | 重启兜底水位 | `GET /sessions/{id}` 读到 `generating` 且快照老过 90s 就就地**幂等重派**（`asyncio.create_task` 不持久）。取 2 倍是因为单 `_judge` 最坏 ≈ 40s（两次 20s 尝试）+ 排队/并发挤占，水位低于一整个周期会把**还在跑**的作业判死再烧一次 LLM |
| `GEN_TIMEOUT_S` | 240 s/段 | 整课生成 | **故意在本契约之外**：那是 202 + 轮询的后台作业，给它加 30s 硬预算 = 骨架段必然降级。豁免在测试里是**显式**的（`ASYNC_JOB_MODULES`），不是漏网 |
| `xunfei_ise_timeout_s` / `xunfei_iat_timeout_s` | 8 / 8 s | 讯飞服务层自己的硬顶 | `.env` 可覆盖；调用点上再包一层才是本表那些数 |

**最坏求和**（同 `drill_grader.py` 的表；契约要求 `< 30s`，`test_latency_budget.py` 里按「其它 await + budget + 5s ≤ 30s」逐条断言）：

| 路径 | 最坏组成 | 秒 |
|---|---|---|
| `POST /sessions/{id}/step`（文本回答）| 0 + STEP 20 | **20** |
| `POST /sessions/{id}/step`（read_along，只有 ISE）| ISE 服务层 8 | **8** |
| `POST /sessions/{id}/step`（**音频回答**）| IAT ≤13（服务层 8 + ws `open_timeout` 5）+ STEP 20 | **33 ← 已知超预算，见下** |
| `POST /sessions/{id}/mission`（一轮）| iat 8 + max(ise 8, llm 15) | **23** |
| `POST /sessions/{id}/finish-mission` | DB + 数值骨架（**零 LLM**）| **DB** |
| `POST /mission` 到轮次上限**自动收工** | 那一轮本身 23 + 数值骨架（零 LLM）| **23** |
| `POST /polish` | DB + POLISH 10 | **10** |
| `POST /assessment/{id}/complete` | DB + ASSESSMENT 20 | **20** |
| `POST /dialogue/turn`（语音轮）| iat 8 + max(chat 12, ise 8.5) + 落库 | **≈20.5** |

**还有一行明知装不下**（本次不修，但钉了天花板不许它继续变差）：音频作答的 `/step` 最坏 **33s**。成因不是 LLM —— 是那一处的 IAT **调用点没有预算**，只有服务层自己的 8s + `open_timeout=5s`（mission 轮则另外包了 `IAT_TURN_BUDGET_S`）。常规（IAT ≤8s）下 28s 仍在 30s 内，只有**讯飞 IAT 挂死**这个角落会吃穿余量。闭合办法：把 `grade_step` 里的转写也包进 `IAT_TURN_BUDGET_S`（属于讯飞侧调用点的活，本次刻意没做）。测试里这条列在 `over_budget`，从 33s 涨上去就红。

**新增一条同步 LLM 路径时的硬性要求**（这就是"没有默认值可躲"）：
1. 取一个**具名** `*_BUDGET_S` 常量（不许就地写字面量 —— 求和测试读的是常量名），传给 `_judge(hard_budget_s=...)` 或包 `asyncio.wait_for`；
2. 在 `drill_grader.py` 硬预算块的最坏求和表里**加一行**（含"同请求内其它 await"）；
3. 在 `test_latency_budget.py::test_worst_case_sum_of_each_sync_path_fits_under_30s` 的 `fits` 里加同一条数；
4. 装不下就只有两个选择：改走 202 + 轮询（照 `run_review_copy_job`），或写进 `over_budget` 并给 ceiling 与归属 —— **不许**默默留下。
   机器侧的锁：AST 扫全 `app/`，未传 `hard_budget_s` 的 `_judge` 调用点直接红；绕开 `_judge` 的裸 `provider.chat(...)` 未写 `timeout=` 也直接红。
5. 超时**必须**在服务层翻成既有的降级异常（`_judge` 里 `TimeoutError → LlmUnavailableError`）。这是承重的：`_graded_text_step` / `build_review_report` / `polish_text` / `judge_level` 四个调用点只 `except LlmUnavailableError`，让裸 `TimeoutError` 逃逸就是把"诚实降级"变成 500，**比不加预算更糟**。

## 6. 已知边界 / 坑位（血泪清单）

- **sqlite 只支持新链**（≥c9a1 两向）；整链 `d5ccd…` 含 `edb6eb8d27a1` drop-constraint 需 batch，PG16 跑整链无碍——CI/生产都是 PG。
- `lintDebug` 本地≠CI（主干净也报 `MissingPermission` 2 处，CI check-run 全绿）——只以 ktlint.sh/gradle test/assembleDebug + 远端 CI 为准；ktlint 通过 ≠ 可编译（它不查类型）。
- JUnit4 无 float 重载/assertThrows（用 Double+delta、runCatching+fail）。
- 本盒工具超时与进程杀手：长跑任务一律 `nohup ... </dev/null & disown`（勿用 setsid——本盒杀手实证）。`pkill -f` 的方括号自匹配免疫写法（如 `zcode[-]cli`）今后**只适用于非 uvicorn 模式**：**本项目已不存在任何按模式杀 uvicorn 的合法场景**——生产 API 本身就是容器里的 uvicorn，`pkill -f uvicorn.*` 在非 root 下只是被 EPERM 静默挡掉（容器进程 root 所有），而这台机器带免密 sudo，sudo 一穿就是直接打死生产；`fuser -k <宿主端口>/tcp` 也碰不到它——容器进程不持宿主监听（宿主 5173 的监听在 docker-proxy 上）。要停 API 只有 `bash backend/scripts/deploy.sh stop` 或 `docker stop english-api-prod`；宿主 ps 里看到"像是裸跑的 uvicorn"先按 §6.1 判别归属。
- GitHub 直链测速：本盒→`release-assets.githubusercontent.com` 11-40KB/s，手机只会更差——OTA 永远走自托管；大文件拉取给 20-30min 耐心或 `--continue-at -` 续传。
- Room 版本冻结：新表只建在 `EnglishContentDatabase`（v1 独立 DB），`AppDatabase` 保持 v3——删旧实体不 bump 会在 v2.6 老装上炸（已在 P8 用冻壳规避）；升级 Room ≥2.7 前不要动 HistoryCacheEntity 壳。
- LLM 额度与降级：**全课生成 5-10min 仍属预期**（202 + 轮询的后台作业，`GEN_TIMEOUT_S=240s`/段，不受 30s 契约约束）；但「**判级 6-60s / 润色 6-60s 属预期**」这句**自 v2.2.0 起作废** —— 判级现在 20s 封顶（超时=诚实空态）、润色 10s 封顶（超时=`polish=null` + 一句「未做润色」）、文本步判分 20s 封顶、总评文案改由 45s 的后台作业慢慢写（请求本身亚秒级返回 202）。同步路径的时延一律按 §5.5 那张表算，不再用"6-60s 属预期"糊过去。偶发超时全部按设计诚实降级（不卡流程、不 500）。换 key/换模型后必做：`/llm/models` 若返回空列表 = 新模型不在代码内置目录且 `LLM_EXTRA_MODELS_JSON` 未填——判分不受影响（恒用 `LLM_DEFAULT_MODEL`），但客户端下拉框会空。
- **v2.2.0 是 breaking 的（刻意为之，不做旧包兼容）**：`POST /sessions/{id}/finish-mission` 由 200 改 **202**、响应体改成 `{session_id, revision, stage, status, review_status}`、**`report` 字段直接移除**（不是置 nullable）。因此**必须**与 §3.2 的强更配置同批上线；只发 APK 不设强更 = 旧包收工时拿到没有 `review` 的响应、要再点一次吃 409 才进复盘页；只设强更不发 APK = 老用户被要求升到一个还没发布的版本。`SessionView` 与 mission 轮响应新增 `review_status: str | None`（`generating`/`ready`/`failed`，未收工为 null），`ReviewReport` 新增 `evidence_note_cn`；状态住在 `doc` 这个普通 JSON 列里 → **零 alembic 迁移、零新表、零新端点**（轮询复用既有 `GET /sessions/{id}`）。
- **判断"AI 文案到了没有"只许读 `review_status`，不许读 `report.source`**：作业正常跑完而 LLM 挂着时的终态就是 `ready` + `source=="heuristic"`，那已是诚实的最终答案（页面上另有降级横幅）。把 `source=="heuristic"` 当成"还在生成"会把复盘页永久挂住。`review_status` 是 `str | None` 而不是字面量枚举，也是同一个道理：JSON 列里的脏旧值必须降级成"不可知、别再等"，而不是让 GET 500。
- **后台作业会随进程重启被丢**（`asyncio.create_task` 不持久）：兜底是 GET 的 90s 就地重派（§5.5）。**数值骨架在 202 之前就已 commit**，所以丢的只有那两句文案，报告本身不会丢。若看到某条会话长期停在 `generating`，先确认重派门 `_REVIEW_IN_FLIGHT` / 水位没被改坏，再看日志里作业有没有落 `failed`（作业任何异常都必须收敛成 `review_status="failed"`，**禁止静默死掉**）。
- **总评 `overall` 为空不是 bug**：只平均 `source ∈ {xunfei, llm}` 的可信分，整场降级或全跳过时 `dims` 全 None → `overall=null`，此时客户端渲染的是 `evidence_note_cn` 那句解释（「本场没有可信评分证据…不是练得差」），而不是一根破折号。看到破折号才是回归。
- **Room 的 `history_cache` 冻壳仍不许动**：`5556851` 删过 `HistoryCacheDao`，但 `history_cache` 至今作为**冻结实体**留在 `AppDatabase` 里，唯一作用是钉住 Room 2.6.1 的 v3 身份哈希——不 bump 版本就删 `@Entity` 会让存量装在 `checkIdentity` 崩（E5 的落盘方案因此刻意用 `filesDir` 里一份 JSON，不新建 Room 实体/DAO）。升级 Room ≥2.7 之前别碰这个壳。
- **发版别再靠人记版本号**：`android/app/src/main/**` 有改动而同一事件范围内没 bump `versionCode` / 没写 CHANGELOG → CI 的 `release-gate` 直接红（§3.0）。历史上这条门该红的那一次是 `2fd067d`（20 个文件，全绿，永久没上过手机）。
- **`/sessions` 列表默认只看 `active` 是旧行为**：v2.2.0 客户端额外查 `status=completed` 来摆「查看上次复盘」/「最近复盘」（后端 `GET /sessions?status=completed` 早就支持，本次无后端改动）。**历史详情页故意没有"回看复盘"入口**：`history` 表没有 `session_id` 列，加它要迁移，而本版刻意零迁移。
- **陈旧环境变量遮蔽 `.env`**（09-07 血案，耗 1h+）：pydantic-settings 优先级 = 进程 env > `.env`。本机曾长期在 `~/.bashrc:172` export 旧 `MIMO_API_KEY`，用户更新 `.env` 换 key 后被 bashrc 旧值静默遮蔽——表现酷似"上游拒 valid key"。已修复：`deploy.sh` 启动前自动剥离与 `.env` 同名变量（`.env` 唯一事实源）；轮换任何被 shell export 过的 key 时，记得同步改 `~/.bashrc`。
- **MiMo key 分线路且互不通用**：`tp-`=token-plan 订阅（只认 `token-plan-cn.xiaomimimo.com`），`sk-`=平台 REST API（只认 `api.xiaomimimo.com`）。key 被上游作废前会先从 429(欠费/额度) 变 401(吊销)——401 别先怀疑代码。
- **冒烟/临时脚本会被会话环境变量遮蔽 `.env`**（09-08 复现）：本 agent 会话 env 自带一个 `MIMO_API_KEY`（用于别处），直接 `python scripts/smoke_xunfei_ise.py` 报 401 invalid key——deploy.sh 早已免疫，裸跑脚本不行。冒烟脚本已内置「启动时剥离与 `.env` 同名 env 键」（唯一事实源纪律的脚本级复制），自己写一次性脚本时记得同招。
- **讯飞流式版三个静默坑**（09-08 真火实测，证据 /tmp/ise-smoke-*）：① 40ms/1280B "建议"节奏 = 上传耗时≈语音时长，实战对话整链 IAT+ISE+LLM 串行必爆手机 30s——预录音频可大步帧快发（≤19200B，超了报 `$.data.data ≤26000` 拒连），3200B/10ms 实测安全；② 参考文本含 `( ) [ ] {` → 引擎**不报错不出终帧**挂到超时（`sanitize_ref_text` 已剔）；③ read_word 裸文本报 48195 SRecWrite，必须 `'\uFEFF'+[word]/[content]\n` 节点包装 + `ent=en_vip` + `tte`。另：word 分 1-5 制（×20 映射正确）；失败一律静默回退 stub（日志 `fell back to stub` 是判据，`xunfei ise ok`/`xunfei iat ok` 才是真分硬证）。
- **（09-07 容器化后新增）`docker compose restart` 不重读 .env、不换镜像**：改配置后手动 `compose restart` = 白改，必须走 `deploy.sh restart`（内部 `up -d --build --force-recreate`）或直接 `compose up -d --force-recreate`。
- **宿主 5432 上曾有一个同名 `english_prod_5173`**（切换前的冻结冷备）：直连 127.0.0.1:5432 查/改会命中过时副本而毫无察觉。**该诱饵库已于 2026-09-11 drop**（drop 前实测 1 user / 0 sessions / 0 history，且已 `pg_dump` 留底；同内容的既存备份是 `backend/logs/pre-compose-cutover-20260907T111032Z.dump`），dev 库容器 `english-postgres` 同时停掉，这个陷阱随之消失。但纪律保留：一切生产 DB 操作钉死 `docker exec english-postgres-prod ...`——dev 容器停着时直连 5432 会直接失败，那反而是个有用的信号。需要开发库时 `cd backend && docker compose up -d postgres`（卷 `backend_postgres_data` 一直在，起回即原样）。
- **`POSTGRES_PASSWORD` 只在数据卷首次初始化生效**：改 `.env` + restart 不改库口令。轮换 = 容器内 `ALTER USER` + 改 `.env` 两步（少一步 = 应用连不上或假象生效）。
- **`down -v` 禁区**：`english-prod-pgdata` = 唯一生产数据卷。`compose down` 安全（数据留存），`down -v` 删库；仅允许在切换前的金丝雀阶段用 -v 清测试卷。
- **`/docs`、`/redoc` 随 `ENV=production` 关闭**（`/openapi.json` 仍在）；接口契约以 CI 与 openapi 为准。本机若以 `ENV=development` 跑（dev 栈或开发机裸跑）会看得到 /docs——那是环境差异，不是"生产功能回归"。
- **开发/发布共用一份 `backend/.env`**：release 栈把它当进程 env 全表注入。翻 `ENV=production` 会同时关掉本机裸开发实例的 /docs、改 `LLM_DEFAULT_MODEL` 两边同时生效——本机已以生产为先，开发临时用 `docker compose -f docker-compose.yml up` 或当场覆盖。

### 6.1 进程归属判别（宿主 `ps` 里那个 uvicorn 到底是谁）

生产 API 在宿主视角**长得就像一个滞留的裸进程**：`root /usr/local/bin/python3.11 /usr/local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`，cwd `/app`，而**宿主没有任何对应监听**（宿主 5173 的监听在 docker-proxy 上，容器有自己的网络命名空间）。不认识这个形状，就会把它误判成"僵尸裸进程"而动杀心——项目记忆里那条误判（见下方史案）正是这个形状造成的，也因此才会有 `deploy.sh status` 现在打印的归属行。三种 uvicorn 的指纹对照：

| | 生产容器 | dev 容器 | 旧裸进程（**已退役**，2026-09-11） |
|---|---|---|---|
| 解释器 | `/usr/local/bin/python3.11` | `/usr/local/bin/python3.11` | `<repo>/backend/.venv/bin/python` |
| argv | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | 同上 **+ `--reload`** | `uvicorn app.main:app --host 0.0.0.0 --port 5173` |
| cwd | `/app` | `/app` | `<repo>/backend` |
| 宿主监听 | 无（docker-proxy 持 5173） | 无（docker-proxy 持 127.0.0.1:8000） | 曾持有 5173 |
| 权威判据 | `docker top english-api-prod` | `docker top english-api` | 没了 |

- **权威归属判别只有正道**：`docker top <容器>`；或 `docker inspect -f '{{.State.Pid}}' <容器>` 取宿主 PID，再与 `/proc/<pid>/cgroup`（应见 `docker-<id>.scope`）和父进程（`containerd-shim-runc-v2`）双证。`deploy.sh status` 现在直接打印生产容器的宿主 PID 并附"勿 kill/pkill/fuser"提示，就是为了不让人靠肉眼猜。
- **杀得动它的向量**只有两条：容器进程 **root 所有**，非 root 用户连 `kill -0` 都得 **EPERM**——所以普通 `pkill -f uvicorn` 杀不掉生产，但那是**静默无效**而非安全，这台机器有**免密 sudo**（`sudo pkill -f` 成立），且操作者在 **docker 组**（`docker stop english-api-prod` 可行）。
- **史案（对号入座用）**：PID 2117 曾被项目记忆记为「root 僵尸 uvicorn app:app，无监听，杀不动」。实测**那不是本项目的**：它的宿主 PID 与 `docker inspect -f '{{.State.Pid}}' bill-recognition-bill-recognition-1` 完全一致，cgroup 与该容器的 containerd-shim（PPID 2024）吻合，State 是 `S`（睡眠、10 线程）**不是 Z**——它是**另一个项目（bill-recognition）健康的容器 init 进程**，`app:app` 与 `--port 8000` 是那个项目自己的模块路径与容器内端口。杀它 = 打掉别的项目。"杀不动"恰恰是它是别的容器 init 的信号，不是该强杀的理由。
- **别"顺手加固"容器内的 `--host 0.0.0.0`——它是必须的**：Docker 发布端口靠 DNAT 把包送到容器 **eth0 地址**，永远不会是它的 loopback。把 uvicorn 改绑 `127.0.0.1` 会让宿主 `${API_PORT:-5173}` 直接不可达，而容器内的 `HEALTHCHECK curl localhost:8000`（`backend/Dockerfile.prod:38`）**照样通过**——`docker ps` 显示 healthy、`deploy.sh start --wait` 也过，只有从宿主 curl 才发现挂了：**假绿陷阱**。（注意这与 `backend/README.md` 裸机开发里"`0.0.0.0` 必须"是两条不同的理由：裸进程绑 `0.0.0.0` 是为了模拟器/真机可达，那是宿主网络栈上的真监听。）
- 端口对号：容器内 8000 **不是**宿主端口；宿主 8000 属 dev 栈且已收紧 `127.0.0.1:8000`（Android debug 包自 v2.2.1 起与 release 同指公网 `http://118.89.58.84:5173/api/v1/`，本地联调在 App「设置」页覆盖 Base URL）；生产发布的是宿主 `${API_PORT:-5173}` → 容器 8000（`docker-compose.prod.yml:46`），`0.0.0.0` 绑定是刻意的（公开契约，烧进 release 包），云防火墙仅映射 TCP 5173/80/8080。


## 7. 文档索引

用户功能路径 `docs/usage-guide.md` · 发版历史 `CHANGELOG.md` · 大版本计划 `.mimocode/plans/1788164431817-eager-cactus.md` · 执行纪要 `.mimocode/tasks/NIGHTLY.md` + T1-T9 报告 · 原架构规格 `docs/superpowers/specs/2026-07-11-...design.md`。
