#!/usr/bin/env bash
# english-speaking-app 生产后端运维脚本（本机即公网 118.89.58.84）
#   主实例 :5173 = 生产 API。云防火墙当前唯一映射端口；
#          v2.1.0+ 客户端内置 http://118.89.58.84:5173/api/v1/（开箱即用）。
#   桥接实例 :8000 = 已退役（2026-09-06），如需临时复活: 手动执行 start_one 8000。
#   生产 DB = english_prod_5173（docker 容器 english-postgres，宿主 127.0.0.1:5432）。
#   用法: backend/scripts/deploy.sh {start|stop|restart|status|migrate}
#   日志: backend/logs/（gitignored）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
SELF="$SCRIPT_DIR/$(basename "$0")"   # 脚本会 cd，自我调用必须用绝对路径
cd "$BACKEND_DIR"

LOG_DIR="$BACKEND_DIR/logs"
mkdir -p "$LOG_DIR"
LOG5173="$LOG_DIR/english-backend-5173.log"
LOG8000="$LOG_DIR/english-backend-8000.log"
PROD_DB_URL="postgresql+asyncpg://english:english@127.0.0.1:5432/english_prod_5173"

# 环境消毒: .env 是配置唯一事实源。启动前把与 .env 同名的环境变量从子进程
# 剥离（pydantic-settings 优先级 进程env > .env，shell 里的陈旧 export 会遮蔽新配置）。
DOTENV_UNSETS=()
while IFS='=' read -r k _; do
  [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && DOTENV_UNSETS+=("-u" "$k")
done < <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env 2>/dev/null)

start_one() { # port logfile
  local port=$1 log=$2
  pgrep -f "uvicorn app.main:app.*--port ${port}$" >/dev/null 2>&1 && { echo ":${port} already up"; return 0; }
  echo "launching :${port} ..."
  # nohup+</dev/null+disown 保证跨工具会话存活（本盒对进程组杀手敏感，勿用 setsid）
  nohup env "${DOTENV_UNSETS[@]}" DATABASE_URL="${PROD_DB_URL}" .venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 --port "${port}" >> "${log}" 2>&1 < /dev/null & disown
  for _ in 1 2 3 4 5 6 7 8 9 10; do sleep 1; timeout 5 curl -fsS "http://127.0.0.1:${port}/api/v1/health" >/dev/null 2>&1 && { echo ":${port} OK"; return 0; }; done
  echo ":${port} FAILED to become healthy; see ${log}"; return 1
}

case "${1:-status}" in
  start)   start_one 5173 "$LOG5173" ;;
  stop)    pkill -f 'uvicorn app.main:app.*--port 5173' || true; pkill -f 'uvicorn app.main:app.*--port 8000' || true; echo stopped ;;
  restart) "$SELF" stop; sleep 2; "$SELF" start ;;
  status)
    for p in 5173 8000; do
      if pgrep -f "uvicorn app.main:app.*--port ${p}$" >/dev/null 2>&1; then s=UP; else s=DOWN; fi
      echo ":${p} ${s} (health $(timeout 5 curl -fsS http://127.0.0.1:${p}/api/v1/health 2>/dev/null || echo n/a))"
    done ;;
  migrate) DATABASE_URL="${PROD_DB_URL}" .venv/bin/alembic upgrade head && echo "migrated: $(DATABASE_URL=${PROD_DB_URL} .venv/bin/alembic current | tail -1)" ;;
  *) echo "usage: $0 {start|stop|restart|status|migrate}"; exit 2 ;;
esac
