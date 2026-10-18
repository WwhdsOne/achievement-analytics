"""推荐容器探活：只有完整准备后可读取元数据才算就绪。"""

from __future__ import annotations

import json
import os
from urllib.request import urlopen


def main() -> int:
    """检查运行中服务，不读库、不生成缓存或修改数据。"""
    host = os.environ.get("RECOMMENDATION_BIND_HOST", "127.0.0.1")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    authority = f"[{host}]" if ":" in host else host
    port = os.environ.get("RECOMMENDATION_PORT", "8605")
    try:
        with urlopen(f"http://{authority}:{port}/api/meta", timeout=8) as response:
            data = json.load(response)
        return (
            0
            if data.get("algorithm_version") and data.get("candidate_games", 0) > 0
            else 1
        )
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
