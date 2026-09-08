#!/usr/bin/env bash
# 一次性切换：裸进程 :5173（+ dev 容器内旧生产库）→ docker compose 发布栈
#   用法: backend/scripts/cutover_to_compose.sh [--yes]
#   顺序刻意"停服在前、权威 dump 在后"——杜绝"备份后到停服前"的写入丢失窗口。
#   任一中断可重跑：restore 前检测到非空目标库会 DROP(FORCE)+CREATE 重建。
#   失败回滚: docker compose -f docker-compose.prod.yml down && scripts/deploy.sh start-legacy
#   （旧库/english-postgres 容器/.deploy.env 本脚本全程不删不改，仅只读 dump。）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BACKEND_DIR"

COMPOSE=(docker compose -f docker-compose.prod.yml)
OLD_PG=english-postgres
NEW_PG=english-postgres-prod
API_CTR=english-api-prod
EXPECTED_DB=english_prod_5173

die() { echo "FATAL: $*" >&2; exit 1; }
step() { echo; echo "==== $* ===="; }

env_var() { # key default —— 一律以 .env 文件为准（shell export 已在顶部剥离）
  local v
  v="$(grep -m1 "^$1=" .env 2>/dev/null | cut -d= -f2-)"
  echo "${v:-$2}"
}

# 环境消毒（与 deploy.sh 同一口径: .env = 唯一事实源）
while IFS='=' read -r k _; do
  [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && unset "$k"
done < <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env 2>/dev/null)

DB="$(env_var POSTGRES_DB "$EXPECTED_DB")"
API_PORT="$(env_var API_PORT 5173)"
PGPASS="$(env_var POSTGRES_PASSWORD '')"
[ "$DB" = "$EXPECTED_DB" ] || die "POSTGRES_DB=$DB ≠ $EXPECTED_DB（切换目标库名必须与生产一致）"
[[ "$API_PORT" =~ ^[0-9]+$ ]] || die "API_PORT=$API_PORT 非数字"
[[ "$DB" =~ ^[A-Za-z0-9_]+$ ]] || die "POSTGRES_DB 含特殊字符: $DB"
[ -n "$PGPASS" ] && [ "$PGPASS" != CHANGE_ME ] || die ".env 的 POSTGRES_PASSWORD 未设置/仍是占位符"
AUTO_YES="${1:-}"

health_ok() { timeout 5 curl -fsS "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null 2>&1; }

# ---------- 0. 幂等守卫 ----------
if docker inspect "$API_CTR" >/dev/null 2>&1 && health_ok; then
  echo ":${API_PORT} 已由 compose 栈在对外服务（${API_CTR} healthy）——看起来已切换过。"
  echo "如需重迁数据请人工决定（会 DROP/重建 ${DB}），本脚本不再自动执行。"
  exit 0
fi

# ---------- 1. 预检（无停机） ----------
step "1/9 预检 + 镜像预热"
"${COMPOSE[@]}" config -q || die "compose config 校验失败"
pgrep -af "u[v]icorn app.main:app.*--port ${API_PORT}" || echo "（未发现裸进程，将直接确认端口占用方）"
docker ps --format '{{.Names}}' | grep -qx "$OLD_PG" || die "旧容器 ${OLD_PG} 不在运行——找不到迁移源"
timeout 5 docker exec "$OLD_PG" psql -U english -d "$DB" -tAc 'SELECT 1' >/dev/null || die "旧容器里没有可读的 ${DB}"
echo ">> 旧库 alembic 版本: $(docker exec "$OLD_PG" psql -U english -d "$DB" -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null || echo n/a)"
"${COMPOSE[@]}" build api || die "镜像构建失败（旧服务未受影响，修复后重跑）"

# ---------- 2. 起 postgres（新卷首初始化即建库；金丝雀未清卷则手动补建） ----------
step "2/9 启动 postgres-prod"
"${COMPOSE[@]}" up -d postgres || die "postgres 起不来"
for i in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$NEW_PG" 2>/dev/null)" = healthy ] && break
  sleep 1
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$NEW_PG")" = healthy ] || die "${NEW_PG} 未达 healthy"
if ! docker exec "$NEW_PG" psql -U english -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB}'" | grep -q 1; then
  echo ">> 卷已存在但库缺失（如金丝雀未清卷），createdb 补建"
  docker exec "$NEW_PG" createdb -U english "$DB" || die "createdb 失败"
fi

# ---------- 3. 冷备预 dump（只读操作，与旧服务共存无损） ----------
step "3/9 旧库冷备 dump（非权威，供带回滚箱）"
COLD="logs/pre-compose-cutover-$(date -u +%Y%m%dT%H%M%SZ).dump"
mkdir -p logs
docker exec "$OLD_PG" pg_dump -U english -d "$DB" -Fc -f /tmp/pre.dump || die "冷备 pg_dump 失败（未停机，直接修）"
docker cp "${OLD_PG}:/tmp/pre.dump" "$COLD" || die "docker cp 冷备失败"
docker exec "$OLD_PG" rm -f /tmp/pre.dump
ls -lh "$COLD"

# ---------- 4. 停裸进程：停机窗口开始 ----------
if [ "$AUTO_YES" != "--yes" ]; then
  echo
  printf '>>> 下一步起 :%s 进入停机窗口（预计 20-60s）。确认继续? [y/N] ' "$API_PORT"
  read -r ans; [ "$ans" = y ] || [ "$ans" = Y ] || die "用户取消（此时未对生产做任何变更）"
fi
step "4/9 停裸进程 u[v]icorn"
pkill -f "u[v]icorn app.main:app.*--port ${API_PORT}" || true
for i in $(seq 1 20); do
  pgrep -f "u[v]icorn app.main:app.*--port ${API_PORT}$" >/dev/null || break
  sleep 0.5
done
pgrep -f "u[v]icorn app.main:app.*--port ${API_PORT}$" >/dev/null && die "裸进程没停干净"
health_ok && die ":${API_PORT} 仍有服务响应——占用方不是预期裸进程，人工排查后再重跑"
echo ">> 停机窗口开始（${API_PORT} 已释放）"

# ---------- 5. 权威 dump + restore（空库或半截库都能走） ----------
step "5/9 权威 dump（旧库此刻无写入）+ restore"
docker exec "$OLD_PG" pg_dump -U english -d "$DB" -Fc -f /tmp/cut.dump || { docker exec "$OLD_PG" rm -f /tmp/cut.dump; die "权威 pg_dump 失败——立即回滚: bash scripts/deploy.sh start-legacy"; }
docker cp "${OLD_PG}:/tmp/cut.dump" /tmp/eng-cut.dump && docker exec "$OLD_PG" rm -f /tmp/cut.dump
NUTABLES="$(docker exec "$NEW_PG" psql -U english -d "$DB" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [ "${NUTABLES:-0}" -gt 0 ]; then
  echo ">> 目标库非空（${NUTABLES} 张表，疑为上次中断残留），DROP(WITH FORCE)+CREATE 重建"
  docker exec "$NEW_PG" psql -U english -d postgres -c "DROP DATABASE \"${DB}\" WITH (FORCE)" \
    && docker exec "$NEW_PG" psql -U english -d postgres -c "CREATE DATABASE \"${DB}\" OWNER english" || die "重建库失败"
fi
docker cp /tmp/eng-cut.dump "${NEW_PG}:/tmp/cut.dump" && rm -f /tmp/eng-cut.dump
docker exec "$NEW_PG" pg_restore -U english -d "$DB" --no-owner --exit-on-error /tmp/cut.dump \
  || die "pg_restore 失败——排查后可重跑本脚本；救急回滚: bash scripts/deploy.sh start-legacy"
docker exec "$NEW_PG" rm -f /tmp/cut.dump

# ---------- 6. 起 api ----------
step "6/9 启动 api（entrypoint 自动 alembic，已到 head 则 no-op）"
"${COMPOSE[@]}" up -d --wait api || { "${COMPOSE[@]}" ps; die "api 未达 healthy——回滚: bash scripts/deploy.sh start-legacy"; }
echo ">> :${API_PORT} health 通过（--wait 已含 healthy 判定）；停机窗口结束"

# ---------- 7. 新旧对账 ----------
step "7/9 对账（alembic 版本 + 逐表行数）"
OLD_V="$(docker exec "$OLD_PG" psql -U english -d "$DB" -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null)"
NEW_V="$(docker exec "$NEW_PG" psql -U english -d "$DB" -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null)"
echo ">> alembic: old=${OLD_V} new=${NEW_V}"
[ "$OLD_V" = "$NEW_V" ] || echo "!! 版本不一致，检查 restore 完整性"
printf '%-32s %8s %8s\n' TABLE OLD NEW
TBLS="$(docker exec "$NEW_PG" psql -U english -d "$DB" -tAc "SELECT relname FROM pg_stat_user_tables ORDER BY relname")"
MISMATCH=0
for t in $TBLS; do
  n=$(docker exec "$NEW_PG" psql -U english -d "$DB" -tAc "SELECT count(*) FROM public.\"$t\"")
  o=$(docker exec "$OLD_PG" psql -U english -d "$DB" -tAc "SELECT count(*) FROM public.\"$t\"" 2>/dev/null || echo '?')
  [ "$o" = "$n" ] || MISMATCH=$((MISMATCH+1))
  printf '%-32s %8s %8s\n' "$t" "$o" "$n"
done
[ "$MISMATCH" = 0 ] && echo ">> 行数全对齐 ✓" || echo "!! ${MISMATCH} 张表行数不一致（dump 与 restore 间若有旧进程写入则应重跑 5-6 步）"

# ---------- 8. 冒烟 ----------
step "8/9 冒烟（operations.md §5 精简版；完整 TTS/外部链路人工补跑）"
BASE="http://127.0.0.1:${API_PORT}"
for ep in "/api/v1/health" "/api/v1/app/version" "/api/v1/scenes?category=workplace" "/api/v1/stats?device_id=cutover-check" "/api/v1/llm/models"; do
  code=$(timeout 10 curl -s -o /dev/null -w '%{http_code}' "${BASE}${ep}")
  printf '%-56s %s\n' "$ep" "$code"
done
APKF="$(ls -1 static/apk/*.apk 2>/dev/null | head -1 || true)"
if [ -n "$APKF" ]; then
  code=$(timeout 10 curl -s -o /dev/null -w '%{http_code}' -r 0-1023 "${BASE}/static/apk/$(basename "$APKF")")
  printf '%-56s %s\n' "static/apk/$(basename "$APKF") (Range)" "$code"
else
  echo "!! static/apk 为空——OTA 直链未带外迁移（下次 publish_apk.sh 会补）"
fi
docs_code=$(timeout 5 curl -s -o /dev/null -w '%{http_code}' "${BASE}/docs" || echo err)
echo ">> /docs = ${docs_code}（404 = ENV=production 生效；200 = .env 仍是 development，release 该在 .env 翻 ENV/DEBUG）"

# ---------- 9. 收尾提示 ----------
step "9/9 完成"
cat <<EOF
收尾清单（人工）：
  1. 外部探活（云 NAT 回环不可信，换手机/其他机器）:
       curl -s http://118.89.58.84:5173/api/v1/health
  2. 旧资源保留：${OLD_PG} 容器（含旧 ${DB}）与 backend/.deploy.env
     —— 都别删，回滚 start-legacy 依赖它们；稳定一周后再议退役。
  3. 本卷 = 唯一生产数据：严禁对 compose 项目 down -v。
  4. 口令轮换：改 .env POSTGRES_PASSWORD + docker exec ${NEW_PG}
     psql -U english -d postgres -c "ALTER USER english PASSWORD '...'" + deploy.sh restart。
EOF
