# 运维与发版 SOP · english-speaking-app（v2.1.0）

部署机 = 本盒（公网 `118.89.58.84`，云防火墙当前仅映射 **TCP 5173/80/8080**）。仓库：`/home/ubuntu/mimo-workspace/english-speaking-app`，工作分支 main（origin==local）。

## 1. 运行拓扑

| 项 | 值 |
|---|---|
| 生产 API | uvicorn `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 5173`（release 包内置 `http://118.89.58.84:5173/api/v1/`）|
| 生产库 | docker 容器 `english-postgres`（宿主 127.0.0.1:5432，user=english）→ 库 **`english_prod_5173`**（与开发库 `english_dev`、迁移链测试隔离）|
| `:8000` 桥接 | **已停**（不映射公网；旧包 ≤2.0.0 内置 :8000 外网不可达，过渡=一次性 GitHub 直链装 v2.1.0）|
| 进程方式 | 裸 uvicorn（nohup + `</dev/null` + disown，**勿用 setsid**——本盒杀手实证）；日志 `~/english-backend-5173.log`、`~/english-backend-8000.log` |
| 密钥 | 均在 `backend/.env`（gitignored，不入 git）。实测现状：百炼 LLM 已配（仅 `qwen3.8-max`/`qwen3.7-plus` 有额度，免费档 ~3 tok/s）；讯飞 ISE/IAT 与 MiMo-TTS key 留空 → 走真实占位分/stub 声链路，画像与 AI 分不受污染（门控内置）|
| OTA APK | `backend/static/apk/<asset>.apk`（gitignored），`/app/version` 的 `APP_APK_URL` 指它；`/static/tts` 同挂载为 TTS 磁盘缓存 |

## 2. 日常操作

```bash
S=/home/ubuntu/english-backend-deploy.sh
bash $S status     # :5173 UP(health)
bash $S restart    # 发配置后必重启（uvicorn 启动读一次 env）
bash $S migrate    # alembic upgrade head（生产库）
bash $S stop       # 全停
```

改 `.env`（换密钥/模型/APP_* 三兄弟）后：`bash $S restart`，`curl -s http://localhost:5173/api/v1/health` + 看对应端点即验生效。

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
| 讯飞 ISE | `XUNFEI_APP_ID/API_KEY/API_SECRET` | 跟读/影子/弱词真实逐词音素分（`source=xunfei`；日志 `xunfei ise ok` 为硬证，**单看分数不可信**）|
| 讯飞 IAT | 同上 | 实战/自由对话真实听写（无则文本输入为主路径）|
| MiMo-TTS | `MIMO_API_KEY`（本盒必须 `MIMO_TTS_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1`）| 示范声真合成 |
| 百炼 LLM | `LLM_BASE_URL/LLM_API_KEY/LLM_DEFAULT_MODEL=qwen3.8-max` | 已配 ✓ |

## 5. 冒烟与验证集（发版/迁移后跑）

```bash
BASE=http://118.89.58.84:5173
curl -s $BASE/api/v1/health                                   # {"status":"ok"}
curl -s $BASE/api/v1/app/version                              # latest=当前发布版, source=env, force=false
curl -s -r 0-1023 -o /dev/null -w '%{http_code}' $BASE/static/apk/EnglishAssistant-<ver>.apk  # 206
curl -s "$BASE/api/v1/scenes?category=workplace" | head -c200          # 含职场课
curl -s "$BASE/api/v1/stats?device_id=smoke-0906"                       # 合法 JSON（空态即可）
# 完整通关冒烟（生成一条真实练习痕迹）:
# curl 序列 POST /sessions{scene_id:scene_ordering_coffee}→ /step ×6(text) →
#   /mission ×3 → /finish-mission 看 ReviewReport dims; GET /courses/progress 应现 attempts≥1
```

后端回归：`cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app && .venv/bin/pytest`（基线 526 测试，sqlite；CI 含 PG16）。Android 回归：三连（见第 3 节①）。

## 6. 已知边界 / 坑位（血泪清单）

- **sqlite 只支持新链**（≥c9a1 两向）；整链 `d5ccd…` 含 `edb6eb8d27a1` drop-constraint 需 batch，PG16 跑整链无碍——CI/生产都是 PG。
- `lintDebug` 本地≠CI（主干净也报 `MissingPermission` 2 处，CI check-run 全绿）——只以 ktlint.sh/gradle test/assembleDebug + 远端 CI 为准；ktlint 通过 ≠ 可编译（它不查类型）。
- JUnit4 无 float 重载/assertThrows（用 Double+delta、runCatching+fail）。
- 本盒工具超时与进程杀手：长跑任务一律 `nohup ... </dev/null & disown`；`pkill -f` 一律 `zcode[-]cli`/`uvicorn.*` 方括号自匹配免疫写法。
- GitHub 直链测速：本盒→`release-assets.githubusercontent.com` 11-40KB/s，手机只会更差——OTA 永远走自托管；大文件拉取给 20-30min 耐心或 `--continue-at -` 续传。
- Room 版本冻结：新表只建在 `EnglishContentDatabase`（v1 独立 DB），`AppDatabase` 保持 v3——删旧实体不 bump 会在 v2.6 老装上炸（已在 P8 用冻壳规避）；升级 Room ≥2.7 前不要动 HistoryCacheEntity 壳。
- LLM 免费额度：单次生成两段各 240s+，全课 5-10min；判级/润色 6-60s；偶发超时全部按设计诚实降级（不卡流程）。

## 7. 文档索引

用户功能路径 `docs/usage-guide.md` · 发版历史 `CHANGELOG.md` · 大版本计划 `.mimocode/plans/1788164431817-eager-cactus.md` · 执行纪要 `.mimocode/tasks/NIGHTLY.md` + T1-T9 报告 · 原架构规格 `docs/superpowers/specs/2026-07-11-...design.md`。
