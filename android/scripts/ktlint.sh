#!/usr/bin/env bash
# Local ktlint self-check gate for the Android app.
#
# Mirrors the "Run ktlint" step of .github/workflows/android-ci.yml exactly:
# same ktlint 1.3.1, same source globs, run from the android/ root so that
# android/.editorconfig applies (ktlint_code_style=android_studio,
# standard:function-naming disabled for Composable PascalCase).
#
# Jar source: the Aliyun Maven mirror instead of the GitHub release binary the
# workflow downloads, because github.com release downloads are unreachable
# from this dev box while maven.aliyun.com is. ktlint-cli-1.3.1-all.jar is the
# same 1.3.1 rule engine as the release binary, so local findings == CI
# findings. Note it is NOT self-executing: run it via `java -jar`, not
# chmod+exec.
#
# Usage:
#   ./scripts/ktlint.sh          # check only (CI equivalent)
#   ./scripts/ktlint.sh -F       # auto-fix formatting violations
set -euo pipefail

VERSION="1.3.1"
JAR="/tmp/ktlint-${VERSION}.jar"
URL="https://maven.aliyun.com/repository/public/com/pinterest/ktlint/ktlint-cli/${VERSION}/ktlint-cli-${VERSION}-all.jar"

if [ ! -f "$JAR" ]; then
  echo "Downloading ktlint ${VERSION} fat jar from Aliyun Maven mirror (~80MB)..." >&2
  curl -sL "$URL" -o "$JAR"
fi

cd "$(dirname "$0")/.." # android/ root so .editorconfig is picked up
exec java -jar "$JAR" "$@" 'app/src/main/**/*.kt' 'app/src/test/**/*.kt'
