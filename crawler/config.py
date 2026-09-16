"""crawler.config — 统一配置

数据源分两类（详见 AGENTS.md）：
- **免 key**：Steam 商店 appdetails、全局成就完成率、Steam 社区成就页、
  SteamSpy —— 无需任何配置
- **需 key**：RAWG —— 密钥放项目根目录 `.env`（不入 git），读取统一走本模块

（IGDB 于 2026-09-15 放弃：它需要 Twitch OAuth2，而 Twitch 两步验证在国内
手机号上走不通；其时长/评分/题材价值已被 RAWG 覆盖，详见 learning-logs。）

缺 key 时对应采集模块自行跳过并记日志，不影响其余数据源。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env（项目根目录；文件不存在时不报错）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


# ── 限速配置 ──────────────────────────────────────────────

REQUEST_INTERVAL_SEC: float = 1.0  # 请求间隔 ≥ 1s（AGENTS.md 硬性要求）
MAX_RETRIES: int = 3               # 失败重试上限


# ── 数据路径 ──────────────────────────────────────────────

DATA_RAW: Path = _PROJECT_ROOT / "data" / "raw"
DATA_INTERIM: Path = _PROJECT_ROOT / "data" / "interim"
DATA_PROCESSED: Path = _PROJECT_ROOT / "data" / "processed"


# ── API 密钥（缺省为空字符串，调用方自行判断是否可用）────

RAWG_API_KEY: str = os.getenv("RAWG_API_KEY", "")


# ── 数据库（本地 Docker Postgres，见 docker-compose.yml）──
# 缺省值与 docker-compose.yml 一致，本机开发开箱即用；队友可用 .env 覆盖。

DB_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT: int = int(os.getenv("POSTGRES_PORT", "5433"))
DB_NAME: str = os.getenv("POSTGRES_DB", "achievement_analytics")
DB_USER: str = os.getenv("POSTGRES_USER", "analyst")
DB_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "analyst_dev_pw")


def rawg_enabled() -> bool:
    """RAWG 密钥是否已配置。"""
    return bool(RAWG_API_KEY)
