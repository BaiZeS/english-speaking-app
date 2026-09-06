#!/usr/bin/env bash
# 发布自托管 OTA APK（在部署机上执行；见 README「发布通道」）
#   用法: publish_apk.sh [tag]     # 缺省取 GitHub latest release 的 tag
#   动作: 从 GitHub Release 拉 EnglishAssistant-<ver>.apk 到 static/apk/ →
#         写 .env 的 APP_LATEST_VERSION / APP_APK_URL（resolver 优先级 1，覆盖
#         GitHub 直链）→ 重启生产实例 → 验证 /app/version 与静态直链。
#   为什么: 服务器到 release-assets.githubusercontent.com 实测仅 ~10-40KB/s,
#   21MB 的 APK 让手机走 GitHub 下载 OTA 基本不可用; 自托管走服务器出口。
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # backend/
cd "$REPO_DIR"
REPO="${APP_GITHUB_REPO:-BaiZeS/english-speaking-app}"
BASE="${PUBLISH_APK_BASE_URL:-http://118.89.58.84:5173}"   # 对外可达地址(可 env 覆盖)

TAG="${1:-$(curl -fsS --max-time 30 "https://api.github.com/repos/${REPO}/releases/latest" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tag_name"])')}"
VER="${TAG#v}"
ASSET="EnglishAssistant-${VER}.apk"
echo ">> tag=${TAG} asset=${ASSET}"

URL=$(curl -fsS --max-time 30 "https://api.github.com/repos/${REPO}/releases/tags/${TAG}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for a in d.get('assets',[]):
    if a['name']=='${ASSET}': print(a['browser_download_url']); break
else: raise SystemExit('asset ${ASSET} not found in release ${TAG}')")

mkdir -p static/apk
echo ">> downloading (GitHub 出口慢, 20MB 可能要 10-30 分钟, 期间旧版仍可用)..."
curl -fSL --retry 3 --max-time 3600 -o "static/apk/${ASSET}.part" "$URL"
mv -f "static/apk/${ASSET}.part" "static/apk/${ASSET}"
ls -lh "static/apk/${ASSET}"

touch .env
set_env() { # key value
  local k=$1 v=$2
  grep -q "^${k}=" .env && sed -i "s|^${k}=.*|${k}=${v}|" .env || printf '%s=%s\n' "$k" "$v" >> .env
}
set_env APP_LATEST_VERSION "${VER}"
set_env APP_APK_URL "${BASE}/static/apk/${ASSET}"

echo ">> restarting prod backend..."
DEPLOY_SCRIPT="${DEPLOY_SCRIPT:-/home/ubuntu/english-backend-deploy.sh}"
bash "$DEPLOY_SCRIPT" restart
sleep 2

echo ">> verify /app/version:"
curl -fsS --max-time 20 "${BASE}/api/v1/app/version" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['latest_version']=='${VER}', d
assert d['source']=='env', d
assert d['apk_url'].endswith('/static/apk/${ASSET}'), d
print('  latest=%s source=%s url=%s' % (d['latest_version'], d['source'], d['apk_url']))"
curl -fsS --max-time 30 -r 0-1023 -o /dev/null -w '>> apk range probe: http=%{http_code} bytes=%{size_download} speed=%{speed_download}B/s\n' "${BASE}/static/apk/${ASSET}"
echo ">> published ${TAG} (hosted)"
