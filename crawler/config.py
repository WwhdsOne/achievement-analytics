"""crawler.config — 统一配置与密钥读取

所有爬虫模块通过本模块获取 API key、限速参数等配置。
密钥存放在项目根目录 .env 文件中（不入 git）。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env（项目根目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


# ── API Keys ──────────────────────────────────────────────

STEAM_API_KEY: str = os.getenv("STEAM_API_KEY", "")


# ── 限速配置 ──────────────────────────────────────────────

REQUEST_INTERVAL_SEC: float = 1.0  # 请求间隔 ≥ 1s（AGENTS.md 硬性要求）
MAX_RETRIES: int = 3               # 失败重试上限


# ── 数据路径 ──────────────────────────────────────────────

DATA_RAW: Path = _PROJECT_ROOT / "data" / "raw"
DATA_INTERIM: Path = _PROJECT_ROOT / "data" / "interim"
DATA_PROCESSED: Path = _PROJECT_ROOT / "data" / "processed"


def validate_config() -> None:
    """启动时检查必要配置是否就绪。"""
    if not STEAM_API_KEY:
        raise EnvironmentError(
            "STEAM_API_KEY 未设置。请在 .env 文件中配置，参考 .env.example"
        )
