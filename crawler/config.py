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
# 重试之间的指数退避基准（秒）：第 1 次失败等 2s，第 2 次等 4s。
# 不加真退避时，3 次尝试会挤在 ~1s 的节流窗口里全部撞墙——实测把一次 819 页的
# 枚举在第 32 页整轮打断（2026-09-17）。退避要能跨过站点的限流窗口。
RETRY_BACKOFF_SEC: float = 2.0


# ── 数据路径 ──────────────────────────────────────────────

DATA_RAW: Path = _PROJECT_ROOT / "data" / "raw"
DATA_INTERIM: Path = _PROJECT_ROOT / "data" / "interim"
DATA_PROCESSED: Path = _PROJECT_ROOT / "data" / "processed"


# ── API 密钥（缺省为空字符串，调用方自行判断是否可用）────

RAWG_API_KEY: str = os.getenv("RAWG_API_KEY", "")

# Steam Web API key：**只用于 IStoreService/GetAppList**（读公开商店条目，拿无漂移的
# 全量 appid 全集）。与「逐玩家数据」无关——项目不需要任何用户数据，所以这个 key
# 不违反「只用公开数据源」的约束。
STEAM_API_KEY: str = os.getenv("STEAM_API_KEY", "")


# ── 数据库（**必填**：.env 里配云库，2026-09-17 起不再有本地 Docker 缺省）──
# 所有机器连**同一个**云库：任务队列、配额账本、RAWG 密钥池都在那里，
# worker 的原子抢占（FOR UPDATE SKIP LOCKED）也依赖这个共享库。
#
# 下面的缺省值只是「没配 .env 时的兜底」，实际部署必须显式配置——
# 否则会静默连到 localhost 上一个不存在的库。
# 云数据库通常强制 SSL，设 POSTGRES_SSLMODE=require。注意云库端口一般是 5432。

DB_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME: str = os.getenv("POSTGRES_DB", "achievement_analytics")
DB_USER: str = os.getenv("POSTGRES_USER", "analyst")
DB_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
# 留空表示不传 sslmode。云库一般要 "require"。
DB_SSLMODE: str = os.getenv("POSTGRES_SSLMODE", "")


def rawg_enabled() -> bool:
    """RAWG 密钥是否已配置。"""
    return bool(RAWG_API_KEY)
