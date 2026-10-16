#!/usr/bin/env bash
# 【在本机跑】把面板部署到服务器。dashboard/ 是自包含的，本脚本只读同目录的 .env。
#
#   bash dashboard/deploy.sh          # 或在 dashboard/ 里 `bash deploy.sh`
#
# 做四件事：
#   1. 交叉编译 linux/amd64 静态二进制（面板不需要 CGO）
#   2. 从 .env 抽出 POSTGRES_* 与推荐服务 HOST/PORT，值原样照搬
#   3. 把二进制 / Dockerfile / compose / 抽出的 env / 分析报告打包传到服务器固定目录
#   4. 远端 `docker compose up -d --build` → 远端探活 → 本机探公网 → 确认写接口不存在
#
# 凭据都在 dashboard/.env（不入 git）。.env 里两段各自独立填写：
#   DEPLOY_HOST   服务器地址（只给本脚本登录用）
#   POSTGRES_HOST 数据库地址（面板连库用，原样传给容器；面板与库同机所以是 127.0.0.1）
# SSH 部署凭据留在本机；传上去的 env 只有 POSTGRES_* 与推荐连接 HOST/PORT。
#
# 登录用账号密码（sshpass 在 macOS 上默认没有，所以用 expect 应答）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

BINARY="build/achievement-dashboard"
STAGE="build/stage"
ARCHIVE="build/upload.tar.gz"
CONTAINER_ENV="build/container.env"
REPORT="../data/processed/analysis-report.json"

# ── 读本目录的 .env（不覆盖已导出的环境变量）──────────────────────────────
[ -f .env ] || { echo "✗ 缺少 $HERE/.env——它保存数据库与部署凭据，不入 git"; exit 1; }
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  key="${line%%=*}"; val="${line#*=}"
  key="$(printf '%s' "$key" | tr -d '[:space:]')"
  [ -z "$key" ] && continue
  if [ -z "${!key+x}" ]; then val="${val%\"}"; val="${val#\"}"; export "$key=$val"; fi
done < .env

: "${DEPLOY_HOST:?dashboard/.env 里缺少 DEPLOY_HOST}"
: "${DEPLOY_USER:?dashboard/.env 里缺少 DEPLOY_USER}"
: "${DEPLOY_PASSWORD:?dashboard/.env 里缺少 DEPLOY_PASSWORD}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/achievement-dashboard}"
DEPLOY_PORT="${DEPLOY_PORT:-8600}"
TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"

# ── expect 免交互应答密码 ────────────────────────────────────────────────
# 两个 helper 都把「远端命令是否成功」的退出码透传出来，set -e 才能生效。
# 远端命令通过环境变量传入，避免拼进 Tcl 源码后再处理一层转义。
remote_run() {  # $1 = 要在服务器上执行的命令
  REMOTE_CMD="$1" SSH_PASSWORD="$DEPLOY_PASSWORD" SSH_TARGET="$TARGET" \
  expect -c '
    set timeout 900
    spawn ssh -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no \
              -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 \
              $env(SSH_TARGET) $env(REMOTE_CMD)
    expect {
      -re "(?i)password:" { send "$env(SSH_PASSWORD)\r"; exp_continue }
      "Permission denied" { puts stderr "\n✗ SSH 认证失败（检查 .env 里的 DEPLOY_PASSWORD）"; exit 1 }
      timeout             { puts stderr "\n✗ SSH 超时"; exit 1 }
      eof
    }
    catch wait result
    exit [lindex $result 3]
  '
}

remote_put() {  # $1 = 本地文件，$2 = 远端目录（只传单个文件：Expect 的 spawn 不会把
                # Tcl 列表展开成多个参数，多文件 scp 会被当成一个带空格的文件名）
  local local_file="$1" remote_dir="$2"
  LOCAL_FILE="$local_file" REMOTE_DIR="$remote_dir" \
  SSH_PASSWORD="$DEPLOY_PASSWORD" SSH_TARGET="$TARGET" \
  expect -c '
    set timeout 900
    spawn scp -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no \
              -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 \
              $env(LOCAL_FILE) $env(SSH_TARGET):$env(REMOTE_DIR)/
    expect {
      -re "(?i)password:" { send "$env(SSH_PASSWORD)\r"; exp_continue }
      "Permission denied" { puts stderr "\n✗ SCP 认证失败"; exit 1 }
      timeout             { puts stderr "\n✗ SCP 超时"; exit 1 }
      eof
    }
    catch wait result
    exit [lindex $result 3]
  '
}

# ── 0. 前置检查 ──────────────────────────────────────────────────────────
echo "==> 0/4 前置检查"
command -v go >/dev/null     || { echo "    ✗ 本机没有 go"; exit 1; }
command -v expect >/dev/null || { echo "    ✗ 本机没有 expect（macOS 自带；Linux 需 apt install expect）"; exit 1; }
[ -f "$REPORT" ] || {
  echo "    ✗ 缺少 $REPORT——分析页的数据源，生成方式见 docs/commands.md §8"; exit 1; }
echo "    目标 ${TARGET}:${DEPLOY_PATH}  端口 ${DEPLOY_PORT}"

# ── 1. 交叉编译 ─────────────────────────────────────────────────────────
echo "==> 1/4 交叉编译 linux/amd64 静态二进制"
mkdir -p build
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
  go build -trimpath -ldflags='-s -w' -o "$BINARY" .
printf '    %s\n' "$(ls -lh "$BINARY" | awk '{print $5}')"

# ── 2. 抽出容器连库需要的配置 ───────────────────────────────────────────
echo "==> 2/4 抽出容器连库配置（原样，不改写）"
{
  echo "# 由 dashboard/deploy.sh 从本机 dashboard/.env 抽出，**不要手改**。"
  echo "# 只含 POSTGRES_* 与 RECOMMENDATION_HOST/PORT，值原样照搬。"
  echo "# 只读面板不需要任何 API key，所以 STEAM/RAWG 之类不会传上来。"
  awk -F= '/^POSTGRES_[A-Z_]*=|^RECOMMENDATION_(HOST|PORT)=/{print}' .env
} > "$CONTAINER_ENV"
chmod 600 "$CONTAINER_ENV"
awk -F= '/^[A-Z_]+=/{print "    "$1}' "$CONTAINER_ENV"

# ── 3. 打包上传 ─────────────────────────────────────────────────────────
# 打成一个 tar 再传：只需一次 scp，也就只需应答一次密码，而且不会踩
# 「spawn 不展开文件列表」那个坑。stage 里的布局就是服务器部署目录的最终布局。
echo "==> 3/4 打包上传"
rm -rf "$STAGE"
mkdir -p "$STAGE/data/processed"
cp "$BINARY" "$STAGE/achievement-dashboard"
cp Dockerfile docker-compose.yml .dockerignore "$STAGE/"
cp "$CONTAINER_ENV" "$STAGE/.env"          # 落地即 .env，省掉一次远端改名
cp "$REPORT" "$STAGE/data/processed/analysis-report.json"
# COPYFILE_DISABLE=1：macOS 的 tar 默认会给带扩展属性的文件附带 ._* 的 AppleDouble
# 文件，传到服务器上就是一堆垃圾（实测会在部署目录里多出 ._achievement-dashboard）
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" -C "$STAGE" .

remote_run "mkdir -p '$DEPLOY_PATH/data/processed'"
remote_put "$ARCHIVE" "$DEPLOY_PATH"
remote_run "cd '$DEPLOY_PATH' && tar -xzf upload.tar.gz && rm -f upload.tar.gz && chmod 600 .env"
echo "    已上传并解包：$(printf '%s' "$(ls -lh "$ARCHIVE" | awk '{print $5}')")"

echo "==> 4/4 远端重建并启动"
remote_run "cd '$DEPLOY_PATH' && docker compose up -d --build && docker compose ps"

# 远端探活：先确认进程真的在服务
if remote_run "
  for i in \$(seq 1 30); do
    curl -fsS 'http://127.0.0.1:${DEPLOY_PORT}/' >/dev/null 2>&1 && exit 0
    sleep 2
  done
  echo '    远端健康检查失败，最近日志：'
  cd '${DEPLOY_PATH}' && docker compose logs --tail 40 dashboard
  exit 1
"; then
  echo "    服务已就绪（服务器本机 127.0.0.1:${DEPLOY_PORT}）"
else
  exit 1
fi

# 本机探公网：这一步才验证得了安全组放行与 host 网络的端口暴露
if curl -fsS --retry 5 --retry-delay 3 --max-time 20 \
    "http://${DEPLOY_HOST}:${DEPLOY_PORT}/api/progress" >/dev/null; then
  echo "    公网可达 http://${DEPLOY_HOST}:${DEPLOY_PORT}"
else
  echo "    ⚠️ 公网不可达。服务本身大概率正常，先查腾讯云控制台是否放行了入站 TCP ${DEPLOY_PORT}"
  echo "      （踩过的坑：没放行时 curl 报「Connected 然后 Empty reply」，很像服务端故障）"
  exit 1
fi

# 写接口应当彻底不存在：面板只读，补抓路由已删
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' -d '{"appid":0}' \
  "http://${DEPLOY_HOST}:${DEPLOY_PORT}/api/game/crawl")"
if [ "$code" = "404" ]; then
  echo "    补抓接口已不存在（404），符合预期"
else
  echo "    ⚠️ POST /api/game/crawl 返回 $code，预期 404"
fi

echo "==> 部署完成：http://${DEPLOY_HOST}:${DEPLOY_PORT}"
