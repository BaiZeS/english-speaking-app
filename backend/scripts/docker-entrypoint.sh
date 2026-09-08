#!/usr/bin/env bash
# 发布容器入口：启动即跑 alembic upgrade head（空库自动建全链；已到 head 则
# no-op，幂等），再 exec 真正的服务命令（uvicorn 顶替 shell 成为 PID 1，
# SIGTERM 优雅退出）。compose exec 不走此脚本；compose run 覆盖 CMD 时参数透传。
set -euo pipefail
cd /app
alembic upgrade head
exec "$@"
