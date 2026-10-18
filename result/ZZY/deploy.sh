#!/usr/bin/env bash
# 在本机执行，单独部署推荐服务；默认只读 dashboard/.env。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null || { echo "缺少 uv，请先安装项目的 Python 环境管理工具"; exit 1; }
exec uv run --project "$HERE/deploy" --frozen python "$HERE/deploy/deploy.py" "$@"
