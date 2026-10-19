#!/usr/bin/env bash
# 断言 APK 的签名证书 SHA-256 与期望值一致 —— 发布链路的最后一道门。
# 成因: release.yml 曾跑 assembleDebug, CI 临时 runner 每次新生成 debug.keystore,
# 在役 7 个包实测 5 种证书, 手机端报「更新包与已安装应用的签名不一致」(装不上但
# 下载成功, 而 CI 全绿)。
# 用法: check_apk_cert.sh <apk> <expected-sha256>
#   exit 0 指纹相符 | exit 1 不符 (拒绝发布) | exit 2 环境缺 apksigner
set -euo pipefail
APK="${1:-}"
EXPECT="${2:-}"
if [ -z "$APK" ] || [ ! -f "$APK" ]; then
  echo "用法: $0 <apk> <expected-sha256> (apk 不存在: ${APK:-<空>})" >&2
  exit 2
fi
if [ -z "$EXPECT" ]; then
  echo "expected-sha256 不能为空" >&2
  exit 2
fi

APKSIGNER="${APKSIGNER:-}"
if [ -z "$APKSIGNER" ]; then
  APKSIGNER="$(command -v apksigner || true)"
fi
if [ -z "$APKSIGNER" ]; then
  APKSIGNER="$(ls "${ANDROID_HOME:-$HOME/Android/Sdk}"/build-tools/*/apksigner 2>/dev/null | sort -V | tail -1 || true)"
fi
if [ -z "$APKSIGNER" ]; then
  echo "apksigner 未找到: 设 APKSIGNER 或 ANDROID_HOME" >&2
  exit 2
fi

ACTUAL="$("$APKSIGNER" verify --print-certs "$APK" | sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | head -1 | tr 'A-F' 'a-f')"
if [ -z "$ACTUAL" ]; then
  echo "$APK 读不出签名证书 (未签名或多 signer?)" >&2
  exit 1
fi
EXPECTED_NORM="$(printf '%s' "$EXPECT" | tr -d ':' | tr -d ' ' | tr 'A-F' 'a-f')"

if [ "$ACTUAL" != "$EXPECTED_NORM" ]; then
  echo "签名证书不符: $APK" >&2
  echo "  actual   = $ACTUAL" >&2
  echo "  expected = $EXPECTED_NORM" >&2
  echo "  装到手机上必然是「更新包与已安装应用的签名不一致」。拒绝发布。" >&2
  exit 1
fi
echo "cert ok: $ACTUAL ($APK)"
