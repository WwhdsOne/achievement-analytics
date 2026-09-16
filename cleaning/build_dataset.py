"""cleaning.build_dataset — 原始缓存 → PostgreSQL

把 ``data/raw/cache/`` 里各数据源的原始响应组装成**游戏级记录**，幂等写入
PostgreSQL（见 ``cleaning/schema.sql``）。

设计原则：**raw 是不可变事实源，DB 是可重建的派生层**。
- 采集走 ``crawler.*`` 的函数，它们自带缓存：爬过的直接命中，没爬过的才发请求
- 写入全部幂等（upsert / 先删后插），可以反复重跑
- 每个源都写 ``ingest_log``，且**细粒度到真实请求**（appdetails 中英文分开、
  两个成就源分开），这样"哪个源没拿到"才能一眼看出
- ``ingest_log.fetched_at`` 取**缓存文件的 mtime**（真实抓取时间），不是入库时间
- **写入顺序必须是「父表 → 子表」**：所有源表都有 ``appid REFERENCES games(appid)``，
  先把 ``games`` 那行写好，否则外键报错（2026-09-15 实测踩到）

用法::

    uv run python -m cleaning.build_dataset              # 全部（含 appid 的条目）
    uv run python -m cleaning.build_dataset 374320       # 只跑指定 appid（调试）
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from cleaning.db import apply_schema, get_engine
from crawler.config import rawg_enabled
from crawler.http import cache_fetched_at
from crawler.steam_api import (
    fetch_appdetails,
    fetch_community_achievements,
    fetch_global_achievement_percentages,
)
from crawler.steamspy import fetch_app_details as fetch_steamspy

logger = logging.getLogger(__name__)

TARGET_GAMES = Path(__file__).resolve().parent.parent / "crawler" / "target_games.json"

# appdetails 返回的是 "Apr 11, 2016" 这类展示格式，还可能是 "Coming soon"
_DATE_FORMATS = ("%b %d, %Y", "%d %b, %Y", "%Y-%m-%d", "%b %Y", "%Y")


# ── 幂等写入语句 ──────────────────────────────────────────

UPSERT_GAME = text(
    """
    INSERT INTO games (appid, name_en, name_zh, source_title)
    VALUES (:appid, :name_en, :name_zh, :source_title)
    ON CONFLICT (appid) DO UPDATE SET
        name_en      = EXCLUDED.name_en,
        name_zh      = EXCLUDED.name_zh,
        source_title = COALESCE(EXCLUDED.source_title, games.source_title),
        updated_at   = now()
    """
)

UPSERT_APPDETAILS = text(
    """
    INSERT INTO steam_appdetails (
        appid, type, is_free, price_cents, release_date, developers, publishers,
        valve_genres, valve_categories, recommendations
    ) VALUES (
        :appid, :type, :is_free, :price_cents, :release_date, :developers, :publishers,
        :valve_genres, :valve_categories, :recommendations
    )
    ON CONFLICT (appid) DO UPDATE SET
        type = EXCLUDED.type, is_free = EXCLUDED.is_free,
        price_cents = EXCLUDED.price_cents, release_date = EXCLUDED.release_date,
        developers = EXCLUDED.developers, publishers = EXCLUDED.publishers,
        valve_genres = EXCLUDED.valve_genres,
        valve_categories = EXCLUDED.valve_categories,
        recommendations = EXCLUDED.recommendations,
        fetched_at = now()
    """
)

UPSERT_STEAMSPY = text(
    """
    INSERT INTO steamspy_games (
        appid, owners, ccu, positive, negative, average_forever, median_forever
    ) VALUES (
        :appid, :owners, :ccu, :positive, :negative, :average_forever, :median_forever
    )
    ON CONFLICT (appid) DO UPDATE SET
        owners = EXCLUDED.owners, ccu = EXCLUDED.ccu,
        positive = EXCLUDED.positive, negative = EXCLUDED.negative,
        average_forever = EXCLUDED.average_forever,
        median_forever = EXCLUDED.median_forever,
        fetched_at = now()
    """
)

UPSERT_RAWG = text(
    """
    INSERT INTO rawg_games (
        appid, rawg_id, name, released, metacritic, rating, ratings_count, genres,
        playtime, added_count,
        status_yet, status_owned, status_beaten,
        status_toplay, status_dropped, status_playing
    ) VALUES (
        :appid, :rawg_id, :name, :released, :metacritic, :rating, :ratings_count, :genres,
        :playtime, :added_count,
        :status_yet, :status_owned, :status_beaten,
        :status_toplay, :status_dropped, :status_playing
    )
    ON CONFLICT (appid) DO UPDATE SET
        rawg_id = EXCLUDED.rawg_id, name = EXCLUDED.name,
        released = EXCLUDED.released, metacritic = EXCLUDED.metacritic,
        rating = EXCLUDED.rating, ratings_count = EXCLUDED.ratings_count,
        genres = EXCLUDED.genres,
        playtime = EXCLUDED.playtime, added_count = EXCLUDED.added_count,
        status_yet = EXCLUDED.status_yet, status_owned = EXCLUDED.status_owned,
        status_beaten = EXCLUDED.status_beaten, status_toplay = EXCLUDED.status_toplay,
        status_dropped = EXCLUDED.status_dropped, status_playing = EXCLUDED.status_playing,
        fetched_at = now()
    """
)

INSERT_ACHIEVEMENT = text(
    """
    INSERT INTO achievements (appid, position, api_name, display_name, description, percent)
    VALUES (:appid, :position, :api_name, :display_name, :description, :percent)
    """
)

INSERT_TAG = text(
    """
    INSERT INTO game_tags (appid, source, tag, votes, kind)
    VALUES (:appid, :source, :tag, :votes, :kind)
    ON CONFLICT (appid, source, tag) DO UPDATE SET
        votes = EXCLUDED.votes, kind = EXCLUDED.kind
    """
)

INSERT_INGEST = text(
    """
    INSERT INTO ingest_log (appid, source, status, cache_key, error, fetched_at)
    VALUES (:appid, :source, :status, :cache_key, :error, COALESCE(:fetched_at, now()))
    """
)


# ── 工具 ──────────────────────────────────────────────────

# 各源的缓存键模板；取不到真实抓取时间时也能给出准确的 cache_key。
# rawg 的缓存键含 rawg_id，运行时才知道，走 override。
_CACHE_KEY_TEMPLATES = {
    "appdetails_en": "appdetails_english_{appid}",
    "appdetails_zh": "appdetails_schinese_{appid}",
    "global_ach": "global_ach_{appid}",
    "community_ach": "community_ach_{appid}",
    "steamspy": "steamspy_{appid}",
}


def parse_release_date(raw: str | None) -> str | None:
    """把展示格式的日期字符串转成 ISO；无法解析返回 None。

    appdetails 给的是 ``"Apr 11, 2016"`` 这类**展示格式**（还可能是
    ``"Coming soon"`` / ``"Q1 2024"``），直接塞进 ``DATE`` 列不可靠。

    Returns:
        形如 ``"2016-04-11"``；解析不了返回 None 并告警。
    """
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    logger.warning("无法解析日期：%r", raw)
    return None


def load_targets() -> list[dict[str, Any]]:
    """读 crawler/target_games.json，只返回**有 steam_appid** 的条目。

    缺 appid 的条目（157 条里占 76 条）需要先做「名称 → appid」回填，这里
    直接跳过并记日志。
    """
    entries = json.loads(TARGET_GAMES.read_text(encoding="utf-8"))
    with_id = [e for e in entries if e.get("steam_appid")]
    missing = len(entries) - len(with_id)
    if missing:
        logger.warning(
            "target_games.json 有 %d/%d 条缺 steam_appid，本次跳过（需先回填）",
            missing,
            len(entries),
        )
    return with_id


def _cache_key_for(source: str, appid: int, override: str | None = None) -> str | None:
    """按源推出缓存键；rawg 等运行时才确定的用 override 显式给。"""
    if override:
        return override
    template = _CACHE_KEY_TEMPLATES.get(source)
    return template.format(appid=appid) if template else None


def _log_ingest(
    conn: Any,
    appid: int,
    source: str,
    status: str,
    error: str | None = None,
    cache_key: str | None = None,
) -> None:
    """写一条抓取审计记录（断点续爬 / 增量判断 / 覆盖率的依据）。

    ``cache_key`` 记真实文件名，``fetched_at`` 取该缓存文件的 mtime —— 即数据
    真实的抓取时间，而不是本次入库时间。
    """
    ck = _cache_key_for(source, appid, cache_key)
    conn.execute(
        INSERT_INGEST,
        {
            "appid": appid,
            "source": source,
            "status": status,
            "cache_key": ck,
            "error": error,
            "fetched_at": cache_fetched_at(ck) if ck else None,
        },
    )


# ── 各源：先取数（走缓存），再写库 ────────────────────────


def fetch_official(appid: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """拉取 Valve 官方元数据的英文/中文两个版本（走缓存）。"""
    en = fetch_appdetails([appid], lang="english").get(str(appid)) or {}
    zh = fetch_appdetails([appid], lang="schinese").get(str(appid)) or {}
    return en, zh


def write_appdetails(conn: Any, appid: int, en: dict[str, Any]) -> None:
    """写 steam_appdetails（**调用前 games 那行必须已存在**）。"""
    price = en.get("price_overview") or {}
    conn.execute(
        UPSERT_APPDETAILS,
        {
            "appid": appid,
            "type": en.get("type"),
            "is_free": en.get("is_free"),
            "price_cents": price.get("final"),
            "release_date": parse_release_date(
                (en.get("release_date") or {}).get("date")
            ),
            "developers": en.get("developers") or [],
            "publishers": en.get("publishers") or [],
            "valve_genres": [g["description"] for g in en.get("genres") or []],
            "valve_categories": [c["description"] for c in en.get("categories") or []],
            "recommendations": (en.get("recommendations") or {}).get("total"),
        },
    )


def write_achievements(conn: Any, appid: int) -> int:
    """拉取两个成就源、按位对齐，重建该游戏的 achievements。返回条数。

    两个源**分开记 ingest_log**：按位对齐要求两源都存在，缺一个就映射不了，
    所以必须能看出是哪一个没拿到。

    两源顺序一致（2026-09-15 实测）才敢按位 zip；不一致时只对齐到较短的一方
    并告警——正式流程应把差异写入差集报告。
    """
    valve = fetch_global_achievement_percentages(appid)
    community = fetch_community_achievements(appid)
    _log_ingest(conn, appid, "global_ach", "ok" if valve else "empty")
    _log_ingest(conn, appid, "community_ach", "ok" if community else "empty")
    if not valve or not community:
        return 0

    valve_pct = [float(a["percent"]) for a in valve]
    page_pct = [r["percent"] for r in community]
    if len(valve) != len(community) or valve_pct != page_pct:
        logger.warning(
            "成就两源不一致：appid=%s 全局接口 %d 项 / 社区页 %d 项，顺序一致=%s",
            appid,
            len(valve),
            len(community),
            valve_pct == page_pct,
        )
    n = min(len(valve), len(community))
    # 先删后插：游戏更新会让 position 变动，upsert 会撞 UNIQUE(appid, position)
    conn.execute(text("DELETE FROM achievements WHERE appid = :a"), {"a": appid})
    conn.execute(
        INSERT_ACHIEVEMENT,
        [
            {
                "appid": appid,
                "position": i + 1,
                "api_name": valve[i]["name"],
                "display_name": community[i]["display_name"],
                "description": community[i]["description"] or None,
                "percent": valve_pct[i],
            }
            for i in range(n)
        ],
    )
    return n


def write_steamspy(conn: Any, appid: int) -> None:
    """拉取并写入 SteamSpy 字段 + 用户标签。"""
    spy = fetch_steamspy(appid)
    if not spy:
        _log_ingest(conn, appid, "steamspy", "empty")
        return
    conn.execute(
        UPSERT_STEAMSPY,
        {
            "appid": appid,
            "owners": spy.get("owners"),
            "ccu": spy.get("ccu"),
            "positive": spy.get("positive"),
            "negative": spy.get("negative"),
            "average_forever": spy.get("average_forever"),
            "median_forever": spy.get("median_forever"),
        },
    )
    tags = spy.get("tags") or {}
    if tags:
        conn.execute(
            INSERT_TAG,
            [
                {
                    "appid": appid,
                    "source": "steamspy",
                    "tag": tag,
                    "votes": votes,
                    "kind": "theme",
                }
                for tag, votes in tags.items()
            ],
        )
    _log_ingest(conn, appid, "steamspy", "ok")


def write_rawg(conn: Any, appid: int, names: list[str]) -> None:
    """按名搜 + appid 校验匹配 RAWG，写入评分与题材标签。"""
    if not rawg_enabled():
        _log_ingest(conn, appid, "rawg", "skipped", "RAWG_API_KEY 未配置")
        return
    from crawler.rawg import match_by_appid, split_tags

    detail = match_by_appid(appid, names)
    if not detail:
        _log_ingest(conn, appid, "rawg", "empty", "按名搜 + appid 校验未命中")
        return
    rawg_id = detail.get("id")
    # added_by_status 是 RAWG 用户的进度自标记，玩家弃坑/通关比例的来源；
    # 缺字段时给 None，不要用 0 顶替（0 会让"没数据"看起来像"没人弃坑"）。
    status = detail.get("added_by_status") or {}
    conn.execute(
        UPSERT_RAWG,
        {
            "appid": appid,
            "rawg_id": rawg_id,
            "name": detail.get("name"),
            "released": parse_release_date(detail.get("released")),
            "metacritic": detail.get("metacritic"),
            "rating": detail.get("rating"),
            "ratings_count": detail.get("ratings_count"),
            "genres": [g["name"] for g in detail.get("genres") or []],
            "playtime": detail.get("playtime"),
            "added_count": detail.get("added"),
            "status_yet": status.get("yet"),
            "status_owned": status.get("owned"),
            "status_beaten": status.get("beaten"),
            "status_toplay": status.get("toplay"),
            "status_dropped": status.get("dropped"),
            "status_playing": status.get("playing"),
        },
    )
    themes, platform = split_tags(detail.get("tags") or [])
    rows = [
        {"appid": appid, "source": "rawg", "tag": t, "votes": None, "kind": "theme"}
        for t in themes
    ] + [
        {"appid": appid, "source": "rawg", "tag": t, "votes": None, "kind": "platform"}
        for t in platform
    ]
    if rows:
        conn.execute(INSERT_TAG, rows)
    _log_ingest(
        conn, appid, "rawg", "ok", cache_key=f"rawg_game_{rawg_id}" if rawg_id else None
    )


# ── 主流程 ────────────────────────────────────────────────


def build(engine: Engine, appids: list[int] | None = None) -> dict[str, int]:
    """把 raw 缓存组装进库。返回计数统计。

    Args:
        engine: SQLAlchemy Engine。
        appids: 指定要处理的 appid；None 表示处理 target_games.json 里全部
            有 appid 的条目。
    """
    apply_schema(engine)

    if appids is None:
        targets = {e["steam_appid"]: e.get("clean_game_name") for e in load_targets()}
    else:
        targets = {a: None for a in appids}

    stats = {"games": 0, "achievements": 0, "errors": 0}
    for appid, source_title in targets.items():
        try:
            en, zh = fetch_official(appid)
            name_en = en.get("name") or ""
            name_zh = zh.get("name") or name_en
            with engine.begin() as conn:
                # appdetails 中英文是两次独立请求，分开记，任一失败另一不受影响
                _log_ingest(conn, appid, "appdetails_en", "ok" if en else "empty")
                _log_ingest(conn, appid, "appdetails_zh", "ok" if zh else "empty")
                if not name_en:
                    stats["errors"] += 1
                    continue
                # 顺序要紧：games 是父表，其余源表都 REFERENCES 它
                conn.execute(
                    UPSERT_GAME,
                    {
                        "appid": appid,
                        "name_en": name_en,
                        "name_zh": name_zh,
                        "source_title": source_title,
                    },
                )
                write_appdetails(conn, appid, en)
                stats["achievements"] += write_achievements(conn, appid)
                write_steamspy(conn, appid)
                write_rawg(conn, appid, [name_en, name_zh])
            stats["games"] += 1
            logger.info("已入库 appid=%s %s", appid, name_en)
        except Exception as exc:  # noqa: BLE001 — 单个游戏失败不该中断整批
            stats["errors"] += 1
            logger.error("入库失败 appid=%s：%s", appid, exc)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = sys.argv[1:]
    appids = [int(a) for a in args] if args else None
    engine = get_engine()
    stats = build(engine, appids)
    print()
    print("=" * 52)
    print(
        f"入库游戏 {stats['games']} 款，成就 {stats['achievements']} 条，"
        f"失败 {stats['errors']} 款"
    )
    print("=" * 52)


if __name__ == "__main__":
    main()
