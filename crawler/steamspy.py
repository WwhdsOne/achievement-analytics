"""crawler.steamspy — SteamSpy 数据采集模块

公开接口，免 key：``https://steamspy.com/api.php?request=appdetails&appid=<appid>``

拿到：``tags``（用户自定义标签 + 票数）、``genre``、``price``、``owners``、
``ccu``、``developer``、``publisher``、``languages``、``positive`` / ``negative``。

实测注意（2026-09-15，appid=374320 黑魂3）：
- ``tags`` 就是 Steam 商店页的「**用户自定义标签**」（玩家投票产生，不是
  Valve 官方分类），与商店页 HTML 同源同序，只给 top 20；票数可用于加权。
- ``average_forever`` / ``median_forever`` **已失效，恒为 0**，不要当游玩
  时长用。
- SteamSpy 数据有缓存延迟（可能滞后数天到数周），入库必须记录抓取时间。
- 官方限速：appdetails 1 req/s、每天 1000 次。
"""

from __future__ import annotations

import logging
from typing import Any

from crawler.http import read_cache, request_json, write_cache

logger = logging.getLogger(__name__)

STEAMSPY_URL = "https://steamspy.com/api.php"


def fetch_app_details(appid: int) -> dict[str, Any]:
    """拉取 SteamSpy 的游戏详情（免 key，已缓存不重爬）。

    Returns:
        SteamSpy 原始字段 dict；该 appid 在 SteamSpy 查不到时返回 ``{}``。
    """
    cache_key = f"steamspy_{appid}"
    cached = read_cache(cache_key)
    if cached is not None:
        return cached
    payload = request_json(STEAMSPY_URL, {"request": "appdetails", "appid": appid})
    if not payload:
        logger.warning("SteamSpy 无数据：appid=%s", appid)
    write_cache(cache_key, payload)
    return payload
