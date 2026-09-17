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
- 官方限速（2026-09-17 核对 https://steamspy.com/api.php 原文）：
  只公布了 ``Allowed poll rate - 1 request per second for most requests,
  1 request per 60 seconds for the *all* requests.``
  **页面上没有任何「每天 N 次」的配额**。本项目在 ``sources.daily_quota`` 里给
  appdetails 设的 1000/天是**自设的保守上限**（防止限流窗口内反复撞墙），
  不是官方公布的额度——查限额时别把它当权威数字。
- 页面另一句值得注意：``The data is refreshed once a day, there is no reason to
  request the same information more than once every 24 hours.``
  即同一 appid 一天内不必重复请求，缓存层应至少保留 24 小时。
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
    payload = request_json(
        STEAMSPY_URL,
        {"request": "appdetails", "appid": appid},
        source="steamspy",
    )
    if not payload:
        logger.warning("SteamSpy 无数据：appid=%s", appid)
    write_cache(cache_key, payload)
    return payload
