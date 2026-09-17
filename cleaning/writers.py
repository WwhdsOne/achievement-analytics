"""cleaning.writers — 单个数据源的抓取 + 入库（一次性路径与队列共用的写入层）

**设计原则：raw 是不可变事实源，DB 是可重建的派生层。**

本模块的职责边界：
- 从 ``crawler.*`` 取数（那些函数自带缓存，爬过的直接命中）
- 解析 / 规范化后**幂等**写库（upsert 或先删后插），可以反复重跑
- 返回该源本次的状态，**不决定**调度（调度在 ``cleaning.worker``）

统一入口是 :func:`run_source`：给 (appid, source) 就完成「抓 + 写 + 记审计」。
``cleaning.build_dataset`` 的一次性批量路径与 ``cleaning.worker`` 的队列路径
都走它，避免两套写入逻辑漂移。

写入顺序的硬约束（2026-09-15 踩到）：所有源表都有 ``appid REFERENCES games(appid)``，
所以 **``games`` 那行必须先存在**。种子（``cleaning.seed``）已保证这一点；
一次性路径里则由 ``build()`` 先 upsert ``games``。

成就的特例：``achievements`` 表需要 ``global_ach`` 与 ``community_ach`` **两个源
都存在**才能按位对齐生成（单源缺一个就映射不了）。因此这两个源各自只管抓取落缓存，
**任何一个抓完都会尝试重建一次 achievements**，两边齐了就写成功——见
:func:`rebuild_achievements`。这样无需在调度层引入依赖关系。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text

from crawler.config import rawg_enabled
from crawler.http import cache_fetched_at
from crawler.steam_api import (
    fetch_appdetails,
    fetch_community_achievements,
    fetch_global_achievement_percentages,
)
from crawler.steamspy import fetch_app_details as fetch_steamspy

logger = logging.getLogger(__name__)


# ── 幂等写入语句 ──────────────────────────────────────────

UPSERT_GAME = text(
    """
    INSERT INTO games (appid, name_en, name_zh, source_title)
    VALUES (:appid, :name_en, :name_zh, :source_title)
    ON CONFLICT (appid) DO UPDATE SET
        name_en      = COALESCE(EXCLUDED.name_en, games.name_en),
        name_zh      = COALESCE(EXCLUDED.name_zh, games.name_zh),
        source_title = COALESCE(EXCLUDED.source_title, games.source_title),
        updated_at   = now()
    """
)

# 只改既有行、不插入。理由同 upsert_game 的 docstring：NOT NULL 在 ON CONFLICT
# 之前校验，所以「只补一个字段」不能用 upsert 表达。
UPDATE_GAME_FIELDS = text(
    """
    UPDATE games
       SET name_zh      = COALESCE(:name_zh, name_zh),
           source_title = COALESCE(:source_title, source_title),
           updated_at   = now()
     WHERE appid = :appid
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

SELECT_GAME_NAMES = text(
    "SELECT name_en, name_zh FROM games WHERE appid = :appid"
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

# appdetails 返回的是 "Apr 11, 2016" 这类展示格式，还可能是 "Coming soon"
_DATE_FORMATS = ("%b %d, %Y", "%d %b, %Y", "%Y-%m-%d", "%b %Y", "%Y")


def parse_release_date(raw: str | None) -> str | None:
    """把展示格式的日期字符串转成 ISO；无法解析返回 None。

    appdetails 给的是 ``"Apr 11, 2016"`` 这类**展示格式**（还可能是
    ``"Coming soon"`` / ``"Q1 2024"``），直接塞进 ``DATE`` 列不可靠。
    商店搜索给的 ``"Sep 10, 2026"`` 是同一套 ``%b %d, %Y`` 格式，共用本函数。

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


def _cache_key_for(source: str, appid: int, override: str | None = None) -> str | None:
    """按源推出缓存键；rawg 等运行时才确定的用 override 显式给。"""
    if override:
        return override
    template = _CACHE_KEY_TEMPLATES.get(source)
    return template.format(appid=appid) if template else None


def log_ingest(
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


# ── 写 games（父表）────────────────────────────────────────


def upsert_game(
    conn: Any,
    appid: int,
    name_en: str,
    name_zh: str | None = None,
    source_title: str | None = None,
) -> None:
    """幂等写 ``games``（**任何源表写入前必须先有这一行**）。

    Args:
        name_en: 官方英文名，**必填**。``games.name_en`` 是 NOT NULL，而
            PostgreSQL 在 ON CONFLICT 判定**之前**就会校验 NOT NULL ——
            所以「传 None 靠 ``COALESCE(EXCLUDED.name_en, games.name_en)`` 保住
            原值」是不成立的，插入路径会直接报约束错误（2026-09-17 踩到两次）。
            只改别的字段请用 :func:`update_game_fields`。

    Raises:
        ValueError: ``name_en`` 为空。
    """
    if not name_en:
        raise ValueError(
            f"upsert_game 需要非空 name_en（appid={appid}）；"
            f"只更新其它字段请用 update_game_fields"
        )
    conn.execute(
        UPSERT_GAME,
        {
            "appid": appid,
            "name_en": name_en,
            "name_zh": name_zh,
            "source_title": source_title,
        },
    )


def update_game_fields(
    conn: Any,
    appid: int,
    *,
    name_zh: str | None = None,
    source_title: str | None = None,
) -> int:
    """只更新 ``games`` 的既有行（不插入）。返回受影响行数。

    用于「games 行已由别处建立、这里只补一个字段」的场景（如 seed 已给英文名，
    事后补中文名或来源标题）。返回 0 说明该行不存在——调用方应据此判断前置缺失。
    """
    result = conn.execute(
        UPDATE_GAME_FIELDS,
        {"appid": appid, "name_zh": name_zh, "source_title": source_title},
    )
    return int(result.rowcount or 0)


def game_names(conn: Any, appid: int) -> list[str]:
    """读该游戏已知的官方名（英文优先），供 RAWG 按名搜索用。

    这是「压平依赖」的关键：RAWG 从 ``games`` 读名字，而不是依赖 appdetails
    的本次返回值——于是两个源之间**没有执行顺序要求**，任意顺序都能跑。
    """
    row = conn.execute(SELECT_GAME_NAMES, {"appid": appid}).first()
    if not row:
        return []
    names = [n for n in (row[0], row[1]) if n]
    return names


# ── 各源：先取数（走缓存），再写库 ────────────────────────


def write_appdetails(conn: Any, appid: int, en: dict[str, Any]) -> None:
    """写 ``steam_appdetails``（**调用前 games 那行必须已存在**）。"""
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


def rebuild_achievements(conn: Any, appid: int) -> int:
    """按位对齐两个成就源，**重建**该游戏的 ``achievements``。返回条数。

    两个源顺序一致（2026-09-15 实测）才敢按位 zip；不一致时只对齐到较短的一方
    并告警——正式流程应把差异写入差集报告。

    任何一方没拿到就返回 0（另一方的任务稍后完成时会再调一次本函数）。
    先删后插：游戏更新会让 position 变动，upsert 会撞 UNIQUE(appid, position)。
    """
    valve = fetch_global_achievement_percentages(appid)
    community = fetch_community_achievements(appid)
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


def write_steamspy(conn: Any, appid: int) -> str:
    """拉取并写入 SteamSpy 字段 + 用户标签。返回该源状态。"""
    spy = fetch_steamspy(appid)
    if not spy:
        return "empty"
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
    return "ok"


def write_rawg(conn: Any, appid: int, names: list[str]) -> tuple[str, str | None]:
    """按名搜 + appid 校验匹配 RAWG，写入评分与题材标签。返回 (状态, 失败原因)。"""
    if not rawg_enabled():
        return "skipped", "RAWG_API_KEY 未配置"
    if not names:
        return "empty", "games 表里没有可用名字（需先跑 appdetails 或 seed）"

    from crawler.rawg import match_by_appid, split_tags

    detail = match_by_appid(appid, names)
    if not detail:
        return "empty", "按名搜 + appid 校验未命中"
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
    log_ingest(
        conn,
        appid,
        "rawg",
        "ok",
        cache_key=f"rawg_game_{rawg_id}" if rawg_id else None,
    )
    return "ok", None


# ── 统一入口 ──────────────────────────────────────────────


def run_source(conn: Any, appid: int, source: str) -> tuple[str, str | None]:
    """执行**单个源**的抓取与入库（幂等），并写一条 ``ingest_log``。

    这是 ``build_dataset``（一次性批量）与 ``worker``（gap 驱动队列）共用的
    唯一入口，保证两条路径的写入语义一致。

    实现要点：内部用 **SAVEPOINT**（``conn.begin_nested()``）包住单个源的写入。
    否则任一条 SQL 失败会让整个事务进入 aborted 状态，**连出错后要写的审计日志都
    写不进去**，真实错误被 ``InFailedSqlTransaction`` 盖住（2026-09-17 踩到）。

    Args:
        conn: 已开启事务的 SQLAlchemy connection。**调用方负责事务边界**。
        appid: 目标 Steam AppID。
        source: ``crawler.registry`` 里的源标识。

    Returns:
        ``(status, error)``，status 取 ``ok`` / ``empty`` / ``skipped`` / ``error``
        （与 ``ingest_log.status`` 同口径）。
    """
    try:
        with conn.begin_nested():
            return _run_source_inner(conn, appid, source)
    except Exception as exc:  # noqa: BLE001 — 单源失败不该中断整批
        logger.error("源执行失败 appid=%s source=%s：%s", appid, source, exc)
        msg = str(exc)[:500]
        try:
            log_ingest(conn, appid, source, "error", msg)
        except Exception:  # noqa: BLE001 — 审计日志再失败也不能吞掉原始异常
            logger.exception("审计日志写入也失败：appid=%s source=%s", appid, source)
        return "error", msg


def _run_source_inner(conn: Any, appid: int, source: str) -> tuple[str, str | None]:
    """``run_source`` 的实际分支逻辑（在 SAVEPOINT 内执行）。"""
    if source == "appdetails_en":
        # 只拉英文版：两个语言各是一个独立任务，若这里把两边都拉了，
        # 请求数会翻倍（2026-09-17 实测到）
        en = fetch_appdetails([appid], lang="english").get(str(appid)) or {}
        if not en or not en.get("name"):
            log_ingest(conn, appid, source, "empty")
            return "empty", None
        upsert_game(conn, appid, name_en=en.get("name"))
        write_appdetails(conn, appid, en)
        log_ingest(conn, appid, source, "ok")
        return "ok", None

    if source == "appdetails_zh":
        zh = fetch_appdetails([appid], lang="schinese").get(str(appid)) or {}
        name_zh = zh.get("name")
        if not name_zh:
            log_ingest(conn, appid, source, "empty")
            return "empty", None
        # **只 UPDATE，不 INSERT**：games.name_en 是 NOT NULL，中文名填不进英文列，
        # 而 NOT NULL 在 ON CONFLICT 之前就校验，所以 upsert 表达不了「只补一个字段」。
        # 建 games 行是 appdetails_en 的职责（种子也保证了它）。
        updated = update_game_fields(conn, appid, name_zh=name_zh)
        if not updated:
            # games 行还不存在 = 前置（appdetails_en / seed）没成功。这不是
            # 「该游戏没有中文名」那种确定性终态，所以要 error 走退避重试。
            msg = "games 行尚不存在（需先成功跑到 appdetails_en），无法写 name_zh"
            log_ingest(conn, appid, source, "error", msg)
            return "error", msg
        log_ingest(conn, appid, source, "ok")
        return "ok", None

    if source in ("global_ach", "community_ach"):
        # 两个源各自只负责抓取落缓存；任一方到位后都尝试重建一次
        # achievements，两边齐了才算真写完（见模块 docstring）
        if source == "global_ach":
            got = fetch_global_achievement_percentages(appid)
        else:
            got = fetch_community_achievements(appid)
        log_ingest(conn, appid, source, "ok" if got else "empty")
        if got:
            rebuild_achievements(conn, appid)
        return ("ok" if got else "empty"), None

    if source == "steamspy":
        status = write_steamspy(conn, appid)
        log_ingest(conn, appid, source, status)
        return status, None

    if source == "rawg":
        status, err = write_rawg(conn, appid, game_names(conn, appid))
        if status == "skipped":
            log_ingest(conn, appid, source, "skipped", err)
        elif status == "empty":
            log_ingest(conn, appid, source, "empty", err)
        return status, err

    raise ValueError(f"未知数据源：{source}")
