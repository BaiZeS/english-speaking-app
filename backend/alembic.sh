#!/usr/bin/env bash
# Alembic helper - runs alembic from the backend/ directory with the project config.
# Usage:
#   ./alembic.sh upgrade head
#   ./alembic.sh downgrade base
#   ./alembic.sh revision --autogenerate -m "describe change"
#   ./alembic.sh current
#   ./alembic.sh history
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec alembic "$@"
