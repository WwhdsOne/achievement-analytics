#!/usr/bin/env bash
# Independent Rust deployment; the original Python deployment is untouched.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null || { echo '缺少 uv'; exit 1; }
exec uv run --project "$HERE/../../.." python "$HERE/deploy.py" "$@"
