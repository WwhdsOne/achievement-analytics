"""crawler.steam_api — Steam 数据采集模块

数据源分两类：
- 免 key：appdetails（商店元数据，**单 appid 请求**，实测多 appid 批量返回
  400）、GetGlobalAchievementPercentagesForApp（全局成就完成率，
  Q1 难度 b 的代理指标）
- 需 key（.env 的 STEAM_API_KEY）：GetSchemaForGame（成就架构
  name -> displayName，名称映射的唯一完整来源——appdetails 只有 10 个
  highlighted 展示名，不敷映射使用）、GetOwnedGames、GetPlayerAchievements

硬性规范（AGENTS.md）：
- 请求间隔 >= 1s；失败重试 <= 3 次，失败记日志不中断整体任务
- 缓存层 data/raw/cache/，已爬不重爬（断点续爬）
- 只采公开数据，不碰需登录态的页面
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import httpx

from crawler.config import (
    DATA_RAW,
    MAX_RETRIES,
    REQUEST_INTERVAL_SEC,
    STEAM_API_KEY,
)

logger = logging.getLogger(__name__)

STORE_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
WEB_API_BASE = "https://api.steampowered.com"

CACHE_DIR = DATA_RAW / "cache"


# ── 限速与请求 ────────────────────────────────────────────

_last_request_ts = 0.0


def _throttle() -> None:
    """全局限速：保证相邻两次请求间隔 >= REQUEST_INTERVAL_SEC。"""
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    if elapsed < REQUEST_INTERVAL_SEC:
        time.sleep(REQUEST_INTERVAL_SEC - elapsed)
    _last_request_ts = time.monotonic()


def _request(url: str, params: dict[str, Any]) -> Any:
    """GET 并解析 JSON：全局限速 + 失败重试 <= MAX_RETRIES。

    不含缓存（由调用方按业务键缓存）。

    Raises:
        RuntimeError: 重试耗尽仍失败。
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _throttle()
            resp = httpx.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_exc = exc
            logger.warning(
                "请求失败（%d/%d）%s %s：%s", attempt, MAX_RETRIES, url, params, exc
            )
    raise RuntimeError(f"重试耗尽：{url} {params}") from last_exc


# ── 缓存层（断点续爬依据）─────────────────────────────────


def _cache_path(key: str) -> "Any":
    """缓存键 -> data/raw/cache/ 下文件路径。键须为合法文件名字符。"""
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> Any | None:
    """命中返回缓存内容，未命中或文件损坏返回 None。"""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("缓存损坏，忽略并重爬：%s", path.name)
        return None


def _write_cache(key: str, payload: Any) -> None:
    """写入缓存。键唯一即文件唯一，不覆盖其他条目。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _hashed_steamid(steamid: str | int) -> str:
    """玩家 ID 哈希（12 位），避免明文 steamid 出现在缓存文件名。"""
    return hashlib.sha256(str(steamid).encode()).hexdigest()[:12]


# ── 免 key 接口 ───────────────────────────────────────────


def fetch_appdetails(appids: list[int]) -> dict[str, dict[str, Any]]:
    """逐个拉取商店 appdetails（游戏元数据 + 成就概览，免 key）。

    实测 appdetails 不支持多 appid 批量（返回 400），只能单 appid 请求；
    已缓存的 appid 直接命中，不重复请求。

    Returns:
        {appid_str: data}，仅含 success 条目；失败 appid 记日志并跳过。
    """
    result: dict[str, dict[str, Any]] = {}
    for appid in appids:
        cached = _read_cache(f"appdetails_{appid}")
        if cached is not None:
            result[str(appid)] = cached
            continue
        try:
            payload = _request(
                STORE_APPDETAILS_URL, {"appids": appid, "l": "english"}
            )
        except RuntimeError as exc:
            logger.error("appdetails 失败，跳过 appid=%s：%s", appid, exc)
            continue
        entry = payload.get(str(appid)) or {}
        if not entry.get("success"):
            logger.warning("appdetails 无数据：appid=%s", appid)
            continue
        _write_cache(f"appdetails_{appid}", entry["data"])
        result[str(appid)] = entry["data"]
    return result


def fetch_global_achievement_percentages(appid: int) -> list[dict[str, Any]]:
    """拉取某游戏的全局成就完成率（免 key，Q1 难度 b 代理）。

    Returns:
        [{"name": API 内部名, "percent": 全局完成率}, ...]。
        注意 name 是内部名（如 NEW_ACHIEVEMENT_1_1），须映射成 displayName
        后才能进正式分析与报告（AGENTS.md 硬性）。
    """
    cache_key = f"global_ach_{appid}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    payload = _request(
        f"{WEB_API_BASE}/ISteamUserStats/"
        f"GetGlobalAchievementPercentagesForApp/v2/",
        {"gameid": appid, "format": "json"},
    )
    achievements = (payload.get("achievementpercentages") or {}).get(
        "achievements"
    ) or []
    if not achievements:
        logger.warning("全局完成率为空：appid=%s", appid)
    _write_cache(cache_key, achievements)
    return achievements


# ── 需 key 接口 ───────────────────────────────────────────


def fetch_achievement_schema(appid: int) -> list[dict[str, Any]]:
    """拉取成就架构（需 key）：name -> displayName 映射的权威来源。

    Returns:
        [{"name": 内部名, "displayName": 显示名, "description": ..., ...}, ...]。
        空列表表示游戏无成就或接口无数据。
    """
    if not STEAM_API_KEY:
        raise EnvironmentError("STEAM_API_KEY 未配置（见 .env.example）")
    cache_key = f"schema_{appid}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    payload = _request(
        f"{WEB_API_BASE}/ISteamUserStats/GetSchemaForGame/v2/",
        {"key": STEAM_API_KEY, "appid": appid, "format": "json"},
    )
    game = payload.get("game") or {}
    achievements = (game.get("availableGameStats") or {}).get("achievements") or []
    _write_cache(cache_key, achievements)
    return achievements


def fetch_owned_games(steamid: str | int) -> list[dict[str, Any]]:
    """拉取玩家公开游戏库（需 key）：playtime_forever 等参与度字段。

    Returns:
        游戏列表（空列表 = 档案非公开或库为空，调用方按缺样本处理）。
    """
    if not STEAM_API_KEY:
        raise EnvironmentError("STEAM_API_KEY 未配置（见 .env.example）")
    cache_key = f"owned_{_hashed_steamid(steamid)}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    payload = _request(
        f"{WEB_API_BASE}/IPlayerService/GetOwnedGames/v1/",
        {
            "key": STEAM_API_KEY,
            "steamid": steamid,
            "include_played_free_games": True,
            "format": "json",
        },
    )
    games = (payload.get("response") or {}).get("games") or []
    _write_cache(cache_key, games)
    return games


def fetch_player_achievements(
    steamid: str | int, appid: int
) -> dict[str, Any]:
    """拉取玩家在某游戏的成就解锁状态（需 key）。

    Returns:
        接口 response 原文；success=False 表示档案非公开或游戏无成就。
    """
    if not STEAM_API_KEY:
        raise EnvironmentError("STEAM_API_KEY 未配置（见 .env.example）")
    cache_key = f"player_ach_{_hashed_steamid(steamid)}_{appid}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    payload = _request(
        f"{WEB_API_BASE}/ISteamUserStats/GetPlayerAchievements/v1/",
        {"key": STEAM_API_KEY, "steamid": steamid, "appid": appid, "format": "json"},
    )
    response = payload.get("response") or {}
    _write_cache(cache_key, response)
    return response


# ── W1 冒烟测试：5 款 FromSoftware 游戏 ────────────────────

SMOKE_GAMES: dict[int, str] = {
    570940: "黑暗之魂：重制版",
    335300: "黑暗之魂2：原罪学者",
    374320: "黑暗之魂3",
    814380: "只狼：影逝二度",
    1245620: "艾尔登法环",
}


def smoke_test() -> None:
    """冒烟测试：跑通免 key 接口 + 检验名称映射可行性。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=" * 62)
    print("1) appdetails 批量（免 key）")
    details = fetch_appdetails(list(SMOKE_GAMES))
    for appid, cn in SMOKE_GAMES.items():
        d = details.get(str(appid)) or {}
        ach = d.get("achievements") or {}
        print(
            f"  [{appid}] {d.get('name', '?')}（{cn}）"
            f" 成就总数={ach.get('total', '?')}"
            f" highlighted={len(ach.get('highlighted') or [])}"
        )

    print("=" * 62)
    print("2) 全局成就完成率（免 key，Q1 难度代理）")
    globals_by_appid: dict[int, list[dict[str, Any]]] = {}
    for appid, cn in SMOKE_GAMES.items():
        achs = fetch_global_achievement_percentages(appid)
        globals_by_appid[appid] = achs
        if achs:
            easiest = max(achs, key=lambda a: a["percent"])
            hardest = min(achs, key=lambda a: a["percent"])
            print(
                f"  [{appid}] {cn}：{len(achs)} 项成就，"
                f"最易 {easier_name(easiest)}={easiest['percent']}%，"
                f"最难 {easier_name(hardest)}={hardest['percent']}%"
            )

    print("=" * 62)
    print("3) 名称映射可行性：appdetails 的 highlighted 是内部名还是显示名？")
    for appid, cn in SMOKE_GAMES.items():
        d = details.get(str(appid)) or {}
        highlighted = [
            a["name"] for a in (d.get("achievements") or {}).get("highlighted") or []
        ]
        internal_names = {g["name"] for g in globals_by_appid[appid]}
        overlap = [n for n in highlighted if n in internal_names]
        print(
            f"  [{appid}] {cn}：highlighted {len(highlighted)} 项，"
            f"其中 {len(overlap)} 项与全局完成率的内部名匹配"
        )
    print("结论已实测：highlighted 是显示名（如 The Dark Soul）且仅 ~10 项，")
    print("完整 name->displayName 映射必须走 fetch_achievement_schema（需 key）。")


def easier_name(ach: dict[str, Any]) -> str:
    """打印用：截短成就内部名。"""
    return ach["name"][:28]


if __name__ == "__main__":
    smoke_test()
