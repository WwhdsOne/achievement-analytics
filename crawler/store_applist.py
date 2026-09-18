"""crawler.store_applist — Steam 商店全量 appid 列表（**需 key**，bulk 源）

这是本项目**唯一无漂移**的全量枚举入口，用来拿到「商店上到底有哪些游戏」的
精确全集。它解决的问题是：商店搜索（``crawler/store_search.py``）虽然免 key 且
自带发售日/好评数，但默认排序会在翻页期间漂移，实测一轮 819 页只覆盖 84.9%，
而**漏项无法自知**。

接口：``IStoreService/GetAppList/v1``（官方文档
<https://partner.steamgames.com/doc/webapi/IStoreService>）

为什么它没有漂移：
- 文档原文：``The results are returned in order of appid, subsequent requests should
  pass the last appid returned by the previous request as the last_appid parameter.``
  —— **按 appid 升序**，且续页用 ``last_appid`` 游标而不是偏移量，所以翻页期间
  商店增删不会影响已翻过的区间，**完整性可证明**
- 单页 ``max_results`` **最大 50,000** → 17.7 万款游戏约 **4 次请求**就能全部拿到
  （对比商店搜索要 819 次）

代价与缺口（**它单独用不了**）：
- **不返回发售日**。而「只看 2026 年以前」这个范围只能靠发售日 → 仍需商店搜索
  或逐款 appdetails 来补
- **不返回成就信息** → 无法直接判断哪些游戏带 Steam 成就
- **需 key**：``.env`` 的 ``STEAM_API_KEY``。注意与「逐玩家数据」无关——这里只是
  读公开商店条目，不涉及任何用户数据

返回条目形如::

    {"appid": 10, "name": "Counter-Strike",
     "last_modified": 1745368572, "price_change_number": 37149137}
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from crawler.config import STEAM_API_KEY
from crawler.http import request_json

logger = logging.getLogger(__name__)

APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"

# 官方文档：max_results 默认 10k，**最大 50k**
MAX_RESULTS = 50000


def applist_enabled() -> bool:
    """是否配置了 Steam Web API key。"""
    return bool(STEAM_API_KEY)


def _params(
    *,
    max_results: int,
    last_appid: int | None,
    include_dlc: bool,
    include_software: bool,
) -> dict[str, Any]:
    """构造 query 参数。默认只要游戏本体，排除 DLC / 软体 / 视频 / 硬件。"""
    params: dict[str, Any] = {
        "key": STEAM_API_KEY,
        "include_games": "true",
        "include_dlc": str(include_dlc).lower(),
        "include_software": str(include_software).lower(),
        "include_videos": "false",
        "include_hardware": "false",
        "max_results": min(max_results, MAX_RESULTS),
    }
    if last_appid is not None:
        params["last_appid"] = last_appid
    return params


def fetch_page(
    *,
    last_appid: int | None = None,
    max_results: int = MAX_RESULTS,
    include_dlc: bool = False,
    include_software: bool = False,
) -> dict[str, Any]:
    """取一页 appid 列表。

    Returns:
        ``{"apps": [...], "last_appid": int|None, "have_more_results": bool}``。
    """
    if not applist_enabled():
        raise EnvironmentError(
            "STEAM_API_KEY 未配置（见 .env.example）；"
            "store_applist 是唯一需要 key 的 Steam 源"
        )
    payload = request_json(
        APP_LIST_URL,
        _params(
            max_results=max_results,
            last_appid=last_appid,
            include_dlc=include_dlc,
            include_software=include_software,
        ),
        source="store_applist",
    )
    resp = payload.get("response") or {}
    return {
        "apps": resp.get("apps") or [],
        "last_appid": resp.get("last_appid"),
        "have_more_results": bool(resp.get("have_more_results")),
    }


def iter_apps(
    *,
    max_results: int = MAX_RESULTS,
    include_dlc: bool = False,
    include_software: bool = False,
) -> Iterator[dict[str, Any]]:
    """按 appid 顺序枚举商店上的全部条目（**无漂移，可证明完整**）。

    翻页用 ``last_appid`` 游标而非偏移量，所以中途商店增删不会导致漏项或重复。
    仍然按 appid 去重一次作为防御（理论上不该有重复）。

    Yields:
        ``{"appid": int, "name": str, "last_modified": int, ...}``。
    """
    last_appid: int | None = None
    seen: set[int] = set()
    pages = 0
    while True:
        page = fetch_page(
            last_appid=last_appid,
            max_results=max_results,
            include_dlc=include_dlc,
            include_software=include_software,
        )
        apps = page["apps"]
        pages += 1
        logger.info(
            "applist 第 %d 页：%d 条（last_appid=%s，还有更多=%s）",
            pages,
            len(apps),
            page["last_appid"],
            page["have_more_results"],
        )
        for app in apps:
            appid = app.get("appid")
            if not appid or appid in seen:
                continue
            seen.add(appid)
            yield app

        next_cursor = page["last_appid"]
        if not page["have_more_results"] or not apps:
            logger.info("applist 枚举结束：共 %d 条 / %d 页", len(seen), pages)
            return
        if next_cursor is None or next_cursor == last_appid:
            # 游标没前进就不再翻页，否则会死循环打爆配额
            logger.error(
                "applist 游标未前进（last_appid=%s），提前结束以免死循环", next_cursor
            )
            return
        last_appid = int(next_cursor)


def count_apps(
    *, include_dlc: bool = False, include_software: bool = False
) -> int:
    """枚举并返回总条数（会翻完全部页）。用于核对总体规模。"""
    return sum(1 for _ in iter_apps(include_dlc=include_dlc, include_software=include_software))
