# 运维与发版 SOP · english-speaking-app（v2.1.0）

部署机 = 本盒（公网 `118.89.58.84`，云防火墙当前仅映射 **TCP 5173/80/8080**）。仓库：`/home/ubuntu/mimo-workspace/english-speaking-app`，工作分支 main（origin==local）。

## 1. 运行拓扑

| 项 | 值 |
|---|---|
| 生产 API | **docker compose 发布栈**：容器 `english-api-prod`（`backend/docker-compose.prod.yml`，宿主端口 `${API_PORT:-5173}`→容器 8000；release 包内置 `http://118.89.58.84:5173/api/v1/`）|
| 生产库 | 栈内 `postgres:16-alpine`（容器 `english-postgres-prod`，卷 `english-prod-pgdata`，库 **`english_prod_5173`**；**不发布宿主端口**）。宿主 127.0.0.1:5432 = 开发栈 `english-postgres`（库 `english_dev` + 旧生产库冷备）——**运维 SQL/备份一律 `docker exec english-postgres-prod psql -U english ...`** |
| `:8000` 桥接 | **已停**（不映射公网；旧包 ≤2.0.0 内置 :8000 外网不可达，过渡=一次性 GitHub 直链装 v2.1.0）|
| 进程方式 | `docker compose up -d` + `restart: unless-stopped`（随 docker daemon 自动拉起——裸进程时代没有的增益）；由 `backend/scripts/deploy.sh` 统一管理（每条 compose 命令前自动剥离与 .env 同名的陈旧环境变量，.env 唯一事实源）。回滚逃生口 `deploy.sh start-legacy` = 旧裸 uvicorn 拓扑（nohup + `</dev/null` + disown，**勿用 setsid**——本盒杀手实证，依赖保留的 `.deploy.env`）；日志 `docker logs english-api-prod`（json-file 10m×5），旧 `backend/logs/*.log` 仅 legacy 回滚时使用 |
| 密钥 | 均在 `backend/.env`（gitignored，不入 git；发布栈的 `DATABASE_URL` 由 compose 服务名自动派生，`.deploy.env` 仅为 `start-legacy` 回滚保留）。**2026-09-07 口令已轮换**：旧默认口令（user=english）在 git 历史中公开过、现已失效，tracked 文件里仅存 CHANGE_ME 占位。实测现状（2026-09-07）：百炼 LLM 已换新 key，现役 **qwen3.8-flash**（服务端默认）+ **deepseek-v4-flash-0731**，chat 实测 200 ✓；MiMo-TTS 平台 key（`sk-`，付费线路）已启用，`/api/v1/tts` 真合成 200 ✓；讯飞 ISE/IAT key 已填；**09-08 已真火冒烟过门**（`/api/v1/score` 17s 音频 3.3s 返回 `source=xunfei` 55 词真分 + 括号脏参考回归通过 + IAT 转写通过，容器日志 `xunfei ise ok`；app 端语音轮=待用户真机复确认，观察 `mission turn perf`）|
| OTA APK | `backend/static/apk/<asset>.apk`（gitignored），`/app/version` 的 `APP_APK_URL` 指它；`/static/tts` 同挂载为 TTS 磁盘缓存。**两目录 bind 进发布容器**（`/app/static/*`），宿主路径即唯一实体——host 侧 publish_apk.sh 写完 + `deploy.sh restart`（recreate）即生效；新机器该目录空，OTA 需跑 publish_apk.sh 补种 |

## 2. 日常操作

```bash
S=backend/scripts/deploy.sh   # 仓库根目录下（底层 = docker compose -f docker-compose.prod.yml）
bash $S status     # 栈容器状态 + :5173 health
bash $S start      # up -d --build（拉新代码/新配置，含 migrate 语义——entrypoint 自动跑）
bash $S restart    # up -d --build --force-recreate api。**改 .env 后必用它**：
                   #   compose 原生 restart 不重读 env_file、不换镜像（静默失效陷阱）
bash $S stop       # 只停 api 容器（postgres 继续跑；全栈 down 请手动 compose down，勿加 -v）
bash $S migrate    # 一次性 alembic upgrade head（compose run 独立容器执行）
bash $S logs 200   # 最近 n 行服务日志（= docker logs english-api-prod）
```

改 `.env`（换密钥/模型/APP_* 三兄弟）后：`bash $S restart`，`curl -s http://localhost:5173/api/v1/health` + 看对应端点即验生效。生产库口令轮换是两步活（卷首初始化口令 + `ALTER USER`），见 §6。数据卷 `english-prod-pgdata` = 唯一生产数据，**严禁对 compose 项目 `down -v`**。

## 3. 发版 SOP（Android）

```bash
# ① 变更就绪 + 本地三连（ktlint.sh / testDebugUnitTest / assembleDebug, 见 android/README）
# ② 推送后务必确认本地==origin 再打 tag（tag 与 push 分离, 防竞态：一次钉错 release 的教训）
git push origin main && git fetch -q origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && echo synced   # 必须 synced 再继续
git tag -a v2.1.1 -m "v2.1.1: ..." && git push origin v2.1.1
# ③ 等 release.yml（~14 min）: 成功且 asset=EnglishAssistant-<ver>.apk,
#    Release 名/tag 正确（workflow 用 GITHUB_REF_NAME，勿改成 git describe——已踩坑）
# ④ 【必须】OTA 自托管切换（否则手机走 GitHub 11-40KB/s 等于没有更新）：
cd backend && bash scripts/publish_apk.sh v2.1.1
# 该脚本自动：GitHub 拉 asset(慢线 ~20-25min) → static/apk → 写 .env 两变量 → restart
# → 自检 source=env + Range 探测。重复跑无害（幂等覆盖）。
# ⑤ versionCode 永远严格递增（v2.1.0=8；Android 同名 version 不比, semver 字典序）
```

回滚：`scripts/publish_apk.sh v<上一个好版本>`（秒切，GitHub/GCP 双源自动降级）；或临时 `APP_LATEST_VERSION` 回旧值 + restart。

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
curl -s $BASE/api/v1/app/version                              # latest=当前发布版, source=env, force=false
curl -s -r 0-1023 -o /dev/null -w '%{http_code}' $BASE/static/apk/EnglishAssistant-<ver>.apk  # 206
curl -s "$BASE/api/v1/scenes?category=workplace" | head -c200          # 含职场课
curl -s "$BASE/api/v1/stats?device_id=smoke-0906"                       # 合法 JSON（空态即可）
curl -s "$BASE/api/v1/llm/models"                                       # models 含 .env 白名单两模型 + default_model
curl -s "$BASE/api/v1/tts?text=Hello&voice=Mia" -o /tmp/t.out -w '%{http_code} %{size_download}B\n'  # 200 + wav 头（RIFF）= TTS 真合成通
# key 排查对照组（区分"调用姿势错"vs"key 无效"——09-07 实测：两线路 512 种姿势的 401 与假 key 逐字节一致）:
# curl -s https://api.xiaomimimo.com/v1/models -H 'api-key: tp-fakekey000' | head -c 60
# 完整通关冒烟（生成一条真实练习痕迹）:
# curl 序列 POST /sessions{scene_id:scene_ordering_coffee}→ /step ×6(text) →
#   /mission ×3 → /finish-mission 看 ReviewReport dims; GET /courses/progress 应现 attempts≥1
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

后端回归：`cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app && .venv/bin/pytest`（基线 **528 全绿**，sqlite；CI 含 PG16）。套件清盒由 `tests/conftest.py::_hermetic_settings` autouse 保证：凭据 + 部署调优字段（env-first OTA、LLM 白名单/目录等，清单**只增不减**）逐用例强制回代码默认值——生产机带 `.env` 亦全绿；若出现「只有 .env 在场才红」的测试，先查该清单是否漏了新字段，勿改产品代码迁就。Android 回归：三连（见第 3 节①）。

## 6. 已知边界 / 坑位（血泪清单）

- **sqlite 只支持新链**（≥c9a1 两向）；整链 `d5ccd…` 含 `edb6eb8d27a1` drop-constraint 需 batch，PG16 跑整链无碍——CI/生产都是 PG。
- `lintDebug` 本地≠CI（主干净也报 `MissingPermission` 2 处，CI check-run 全绿）——只以 ktlint.sh/gradle test/assembleDebug + 远端 CI 为准；ktlint 通过 ≠ 可编译（它不查类型）。
- JUnit4 无 float 重载/assertThrows（用 Double+delta、runCatching+fail）。
- 本盒工具超时与进程杀手：长跑任务一律 `nohup ... </dev/null & disown`；`pkill -f` 一律 `zcode[-]cli`/`uvicorn.*` 方括号自匹配免疫写法。
- GitHub 直链测速：本盒→`release-assets.githubusercontent.com` 11-40KB/s，手机只会更差——OTA 永远走自托管；大文件拉取给 20-30min 耐心或 `--continue-at -` 续传。
- Room 版本冻结：新表只建在 `EnglishContentDatabase`（v1 独立 DB），`AppDatabase` 保持 v3——删旧实体不 bump 会在 v2.6 老装上炸（已在 P8 用冻壳规避）；升级 Room ≥2.7 前不要动 HistoryCacheEntity 壳。
- LLM 额度与降级：全课生成 5-10min / 判级润色 6-60s 属预期；偶发超时全部按设计诚实降级（不卡流程）。换 key/换模型后必做：`/llm/models` 若返回空列表 = 新模型不在代码内置目录且 `LLM_EXTRA_MODELS_JSON` 未填——判分不受影响（恒用 `LLM_DEFAULT_MODEL`），但客户端下拉框会空。
- **陈旧环境变量遮蔽 `.env`**（09-07 血案，耗 1h+）：pydantic-settings 优先级 = 进程 env > `.env`。本机曾长期在 `~/.bashrc:172` export 旧 `MIMO_API_KEY`，用户更新 `.env` 换 key 后被 bashrc 旧值静默遮蔽——表现酷似"上游拒 valid key"。已修复：`deploy.sh` 启动前自动剥离与 `.env` 同名变量（`.env` 唯一事实源）；轮换任何被 shell export 过的 key 时，记得同步改 `~/.bashrc`。
- **MiMo key 分线路且互不通用**：`tp-`=token-plan 订阅（只认 `token-plan-cn.xiaomimimo.com`），`sk-`=平台 REST API（只认 `api.xiaomimimo.com`）。key 被上游作废前会先从 429(欠费/额度) 变 401(吊销)——401 别先怀疑代码。
- **冒烟/临时脚本会被会话环境变量遮蔽 `.env`**（09-08 复现）：本 agent 会话 env 自带一个 `MIMO_API_KEY`（用于别处），直接 `python scripts/smoke_xunfei_ise.py` 报 401 invalid key——deploy.sh 早已免疫，裸跑脚本不行。冒烟脚本已内置「启动时剥离与 `.env` 同名 env 键」（唯一事实源纪律的脚本级复制），自己写一次性脚本时记得同招。
- **讯飞流式版三个静默坑**（09-08 真火实测，证据 /tmp/ise-smoke-*）：① 40ms/1280B "建议"节奏 = 上传耗时≈语音时长，实战对话整链 IAT+ISE+LLM 串行必爆手机 30s——预录音频可大步帧快发（≤19200B，超了报 `$.data.data ≤26000` 拒连），3200B/10ms 实测安全；② 参考文本含 `( ) [ ] {` → 引擎**不报错不出终帧**挂到超时（`sanitize_ref_text` 已剔）；③ read_word 裸文本报 48195 SRecWrite，必须 `'\uFEFF'+[word]/[content]\n` 节点包装 + `ent=en_vip` + `tte`。另：word 分 1-5 制（×20 映射正确）；失败一律静默回退 stub（日志 `fell back to stub` 是判据，`xunfei ise ok`/`xunfei iat ok` 才是真分硬证）。
- **（09-07 容器化后新增）`docker compose restart` 不重读 .env、不换镜像**：改配置后手动 `compose restart` = 白改，必须走 `deploy.sh restart`（内部 `up -d --build --force-recreate`）或直接 `compose up -d --force-recreate`。
- **宿主 5432 上也有一个同名 `english_prod_5173`**（切换前的冻结冷备）：直连 127.0.0.1:5432 查/改会命中过时副本毫无察觉。一切生产 DB 操作钉死 `docker exec english-postgres-prod ...`。
- **`POSTGRES_PASSWORD` 只在数据卷首次初始化生效**：改 `.env` + restart 不改库口令。轮换 = 容器内 `ALTER USER` + 改 `.env` 两步（少一步 = 应用连不上或假象生效）。
- **`down -v` 禁区**：`english-prod-pgdata` = 唯一生产数据卷。`compose down` 安全（数据留存），`down -v` 删库；仅允许在切换前的金丝雀阶段用 -v 清测试卷。
- **`/docs`、`/redoc` 随 `ENV=production` 关闭**（`/openapi.json` 仍在）；接口契约以 CI 与 openapi 为准。回退 start-legacy 时宿主 `.env` 若仍 development 会重新暴露——注意环境差异别误判"功能回归"。
- **开发/发布共用一份 `backend/.env`**：release 栈把它当进程 env 全表注入。翻 `ENV=production` 会同时关掉本机裸开发实例的 /docs、改 `LLM_DEFAULT_MODEL` 两边同时生效——本机已以生产为先，开发临时用 `docker compose -f docker-compose.yml up` 或当场覆盖。

## 7. 文档索引

用户功能路径 `docs/usage-guide.md` · 发版历史 `CHANGELOG.md` · 大版本计划 `.mimocode/plans/1788164431817-eager-cactus.md` · 执行纪要 `.mimocode/tasks/NIGHTLY.md` + T1-T9 报告 · 原架构规格 `docs/superpowers/specs/2026-07-11-...design.md`。
