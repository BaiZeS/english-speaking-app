#!/usr/bin/env bash
# english-speaking-app 生产后端运维脚本（docker compose 发布栈版，本机=公网 118.89.58.84）
#   栈定义: backend/docker-compose.prod.yml（api=english-api-prod, db=english-postgres-prod）
#   主实例 :5173 = 生产 API（云防火墙映射端口，v2.1.0+ 客户端内置该地址；
#            对外端口由 .env 的 API_PORT 可配，默认 5173）
#   生产库 = 容器 english-postgres-prod 内 ${POSTGRES_DB:-english_prod_5173}，
#            数据卷 english-prod-pgdata（严禁 down -v），不发布宿主端口——
#            psql 走 `docker exec english-postgres-prod psql -U english ...`
#   用法: backend/scripts/deploy.sh {start|stop|restart|status|migrate|logs|start-legacy|stop-legacy}
#   语义要点:
#     - start/restart 均为 `up -d --build`（restart 另加 --force-recreate）：
#       compose 原生 restart 不重读 env_file、不换镜像——改 .env（publish_apk.sh
#       改写 APP_* 三兄弟）后必须 recreate 才生效，统一走 up -d 消灭静默失效。
#     - start-legacy/stop-legacy = 回滚逃生口，复活旧"裸 uvicorn + 旧库"拓扑。
#   日志: docker logs（json-file, 10m x5 轮转）；本脚本 logs 子命令是顺手入口。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
SELF="$SCRIPT_DIR/$(basename "$0")"   # 脚本会 cd，自我调用必须用绝对路径
cd "$BACKEND_DIR"

COMPOSE_FILE="docker-compose.prod.yml"
API_PORT="${API_PORT:-}"

# 环境消毒（旧脚本 30-33 行同款做法，勿改成 shell 内 unset——那会连本脚本
# 自己的 API_PORT 等变量一起清掉）: 把与 .env 同名的环境变量只对子进程剥离。
# pydantic-settings 优先级 进程env > .env；compose 插值同样 shell-env 优先，
# shell 里的陈旧 export 会遮蔽新配置——09-07 血案，见 docs/operations.md §6。
DOTENV_UNSETS=()
while IFS='=' read -r k _; do
  [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && DOTENV_UNSETS+=("-u" "$k")
done < <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env 2>/dev/null)

compose() { env ${DOTENV_UNSETS[@]:+"${DOTENV_UNSETS[@]}"} docker compose -f "$COMPOSE_FILE" "$@"; }

# API_PORT 供 compose 插值：shell 未导出时从 .env 取（部署冒烟/status 用同一口径）
if [ -z "$API_PORT" ]; then
  API_PORT="$(grep -m1 '^API_PORT=' .env 2>/dev/null | cut -d= -f2-)"
fi
API_PORT="${API_PORT:-5173}"

health_ok() { timeout 5 curl -fsS "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null 2>&1; }

wait_healthy() { # 最多等 n 秒
  local n=${1:-60} i=0
  for ((i=0; i<n; i++)); do health_ok && return 0; sleep 1; done
  return 1
}

legacy_alive() { pgrep -f "u[v]icorn app.main:app.*--port ${API_PORT}$" >/dev/null 2>&1; }

case "${1:-status}" in
  start)   compose up -d --build --wait \
             && echo ":${API_PORT} started (see '$SELF logs')" ;;
  stop)    compose stop api ;;
  restart) compose up -d --build --force-recreate api \
             && (wait_healthy 60 && echo ":${API_PORT} OK" || { echo ":${API_PORT} NOT healthy"; compose ps; exit 1; }) ;;
  status)
    compose ps
    legacy_alive && echo "WARN: 裸进程 uvicorn 仍在运行 (port ${API_PORT}) — 与 compose 栈端口互斥，确认归属后停掉一个"
    if health_ok; then echo ":${API_PORT} health $(timeout 5 curl -fsS http://127.0.0.1:${API_PORT}/api/v1/health)"; else echo ":${API_PORT} health n/a"; fi ;;
  migrate) compose run --rm --entrypoint alembic api upgrade head \
             && compose run --rm --entrypoint alembic api current | tail -1 ;;
  logs)    compose logs --tail="${2:-100}" api ;;

  start-legacy) # 回滚逃生口：旧拓扑 = 裸 uvicorn + dev 容器里的旧生产库
    # 前置：先释放端口（compose 在跑的话停掉 api），且 backend/.deploy.env 仍存在
    PROD_DB_URL="${PROD_DB_URL:-}"
    if [ -z "$PROD_DB_URL" ] && [ -f "$BACKEND_DIR/.deploy.env" ]; then
      PROD_DB_URL="$(grep -m1 '^PROD_DB_URL=' "$BACKEND_DIR/.deploy.env" | cut -d= -f2-)"
    fi
    [ -z "$PROD_DB_URL" ] && { echo "FATAL: PROD_DB_URL 未配置（.deploy.env 缺失且无环境变量）"; exit 1; }
    legacy_alive && { echo ":${API_PORT} legacy already up"; exit 0; }
    health_ok && { echo "FATAL: :${API_PORT} 已被占用（compose 栈在跑?）— 先 '$SELF stop' 或 'docker compose -f ${COMPOSE_FILE} stop api'"; exit 1; }
    mkdir -p "$BACKEND_DIR/logs"
    echo "launching legacy :${API_PORT} ..."
    # nohup+</dev/null+disown 保证跨工具会话存活（本盒对进程组杀手敏感，勿用 setsid）
    # .env 同名陈旧变量只对子进程剥离（与 compose 路径同口径）
    nohup env ${DOTENV_UNSETS[@]:+"${DOTENV_UNSETS[@]}"} DATABASE_URL="${PROD_DB_URL}" .venv/bin/uvicorn app.main:app \
      --host 0.0.0.0 --port "${API_PORT}" >> "$BACKEND_DIR/logs/english-backend-${API_PORT}.log" 2>&1 < /dev/null & disown
    wait_healthy 10 && echo ":${API_PORT} OK (legacy)" || { echo ":${API_PORT} FAILED; see logs/english-backend-${API_PORT}.log"; exit 1; } ;;

  stop-legacy)
    pkill -f "u[v]icorn app.main:app.*--port ${API_PORT}" || true; echo "legacy :${API_PORT} stopped" ;;

  *) echo "usage: $0 {start|stop|restart|status|migrate|logs [n]|start-legacy|stop-legacy}"; exit 2 ;;
esac
