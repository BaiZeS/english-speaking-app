#!/usr/bin/env bash
# english-speaking-app 生产后端运维脚本（docker compose 发布栈版，本机=公网 118.89.58.84）
#   栈定义: backend/docker-compose.prod.yml（api=english-api-prod, db=english-postgres-prod）
#   主实例 :5173 = 生产 API（云防火墙映射端口，v2.1.0+ 客户端内置该地址；
#            对外端口由 .env 的 API_PORT 可配，默认 5173）
#   生产库 = 容器 english-postgres-prod 内 ${POSTGRES_DB:-english_prod_5173}，
#            数据卷 english-prod-pgdata（严禁 down -v），不发布宿主端口——
#            psql 走 `docker exec english-postgres-prod psql -U english ...`
#   用法: backend/scripts/deploy.sh {start|stop|restart|status|migrate|logs}
#   语义要点:
#     - start/restart 均为 `up -d --build`（restart 另加 --force-recreate）：
#       compose 原生 restart 不重读 env_file、不换镜像——改 .env（publish_apk.sh
#       改写 APP_* 三兄弟）后必须 recreate 才生效，统一走 up -d 消灭静默失效。
#     - **只有 compose 栈这一种跑法**。曾经的 start-legacy/stop-legacy（裸 uvicorn +
#       `.deploy.env` 指向 dev 容器里的旧生产库）已退役：那个旧库实测 1 user /
#       0 sessions / 0 history，"回滚"过去等于把生产切到空库、学员进度全失——它是
#       陷阱不是安全网。后端回滚改走源码口径（`git checkout v<上一版> -- backend/`
#       + 本脚本 restart），注意事项见 docs/operations.md。
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

#: 生产 API 容器名。`status` 用它正面回答"宿主 ps 里那个 uvicorn 到底是谁"。
CONTAINER="english-api-prod"

#: 容器 init 进程在**宿主**上的 PID（容器未跑时为空/0）。
container_pid() { docker inspect -f '{{.State.Pid}}' "$CONTAINER" 2>/dev/null; }

case "${1:-status}" in
  start)   compose up -d --build --wait \
             && echo ":${API_PORT} started (see '$SELF logs')" ;;
  stop)    compose stop api ;;
  restart) compose up -d --build --force-recreate api \
             && (wait_healthy 60 && echo ":${API_PORT} OK" || { echo ":${API_PORT} NOT healthy"; compose ps; exit 1; }) ;;
  status)
    compose ps
    # 生产 API 就是**容器进程**: 宿主 ps 里看得到它的 PID 与 argv(`--port 8000` 是
    # 容器内端口), 但它**不持有宿主监听**(宿主 :${API_PORT} 的监听在 docker-proxy 上)。
    # 这个组合极像"无监听的僵尸裸进程", 曾据此误判过 —— 所以这里把归属直接打出来。
    cpid="$(container_pid)"
    if [ -n "$cpid" ] && [ "$cpid" != "0" ]; then
      echo "容器 ${CONTAINER} 的宿主 PID = ${cpid} —— 这是容器进程, 勿 kill/pkill/fuser; 权威判据 'docker top ${CONTAINER}'"
    else
      echo "容器 ${CONTAINER} 未在运行"
    fi
    if health_ok; then
      echo ":${API_PORT} health $(timeout 5 curl -fsS http://127.0.0.1:${API_PORT}/api/v1/health)"
      # 端口有应答、但发布栈没在跑 => 应答方是别的东西(裸进程/其它栈), 这才值得告警。
      # 旧实现只 pgrep "--port ${API_PORT}" 的裸进程, 对容器 argv 完全盲, 两头都不准。
      if [ -z "$cpid" ] || [ "$cpid" = "0" ]; then
        echo "WARN: :${API_PORT} 有应答但 ${CONTAINER} 没在跑 —— 应答方不是发布栈, 用 'ss -ltnp' 查归属"
      fi
    else
      echo ":${API_PORT} health n/a"
    fi ;;
  migrate) compose run --rm --entrypoint alembic api upgrade head \
             && compose run --rm --entrypoint alembic api current | tail -1 ;;
  logs)    compose logs --tail="${2:-100}" api ;;

  *) echo "usage: $0 {start|stop|restart|status|migrate|logs [n]}"; exit 2 ;;
esac
