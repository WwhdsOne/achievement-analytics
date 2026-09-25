"""cleaning.writers — 单个数据源的抓取 + 入库（一次性路径与队列共用的写入层）

**设计原则：raw 是不可变事实源，DB 是可重建的派生层。**

本模块的职责边界：
- 从 ``crawler.*`` 取数（那些函数自带缓存，爬过的直接命中）
- 解析 / 规范化后**幂等**写库（upsert 或先删后插），可以反复重跑
- 返回该源本次的状态，**不决定**调度（调度在 ``cleaning.worker``）

统一入口是 :func:`run_source`：给 (appid, source) 就完成「抓 + 写 + 记审计」。
``cleaning.worker`` 的 gap 驱动队列路径（唯一路径）走它，所以不存在「两套写入逻辑
漂移」的问题；调试单个游戏用 ``worker --appid <N>``。

写入顺序的硬约束（2026-09-15 踩到）：所有源表都有 ``appid REFERENCES games(appid)``，
所以 **``games`` 那行必须先存在**。种子（``cleaning.seed``）已保证这一点。

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

from crawler import http
from crawler.http import SourceChallenge
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

# 成就名映射质量台账（见 schema.sql 的 mapping_issues 注释）
UPSERT_MAPPING_ISSUE = text(
    """
    INSERT INTO mapping_issues (appid, reason)
    VALUES (:appid, :reason)
    ON CONFLICT (appid) DO UPDATE SET
        reason      = EXCLUDED.reason,
        detected_at = now(),
        resolved    = false
    """
)

RESOLVE_MAPPING_ISSUE = text(
    "UPDATE mapping_issues SET resolved = true WHERE appid = :appid"
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
    INSERT INTO ingest_log (appid, source, status, error, fetched_at)
    VALUES (:appid, :source, :status, :error, COALESCE(:fetched_at, now()))
    """
)

SELECT_GAME_NAMES = text(
    "SELECT name_en, name_zh FROM games WHERE appid = :appid"
)


# ── 工具 ──────────────────────────────────────────────────

# appdetails 返回的是 "Apr 11, 2016" 这类展示格式，还可能是 "Coming soon"
_DATE_FORMATS = ("%b %d, %Y", "%d %b, %Y", "%Y-%m-%d", "%b %Y", "%Y")


# 商店/接口里表示「还没发售」的已知取值 —— 它们解析不出日期是**正确行为**，
# 不该按告警刷屏（实测一次枚举会打印上万行，把真正的异常淹没）
_KNOWN_NON_DATES = {
    "coming soon", "to be announced", "tba", "tbd", "待定", "即将推出",
    "wishlist now", "not yet announced",
}


def parse_release_date(raw: str | None) -> str | None:
    """把展示格式的日期字符串转成 ISO；无法解析返回 None。

    appdetails 给的是 ``"Apr 11, 2016"`` 这类**展示格式**（还可能是
    ``"Coming soon"`` / ``"Q1 2024"``），直接塞进 ``DATE`` 列不可靠。
    商店搜索给的 ``"Sep 10, 2026"`` 是同一套 ``%b %d, %Y`` 格式，共用本函数。

    ``Coming soon`` / ``To be announced`` 这类**已知的非日期值**只记 DEBUG，
    其余解析失败才告警——否则一次全量枚举会刷出上万行噪音。

    Returns:
        形如 ``"2016-04-11"``；解析不了返回 None。
    """
    if not raw:
        return None
    text_value = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text_value, fmt).date().isoformat()
        except ValueError:
            continue
    if text_value.lower() in _KNOWN_NON_DATES:
        logger.debug("未发售日期，按无日期处理：%r", raw)
    else:
        logger.warning("无法解析日期：%r", raw)
    return None


def log_ingest(
    conn: Any,
    appid: int,
    source: str,
    status: str,
    error: str | None = None,
) -> None:
    """写一条抓取审计记录（断点续爬 / 增量判断 / 覆盖率的依据）。

    ``fetched_at`` 由 HTTP 层记录：每个源最近一次**成功拿到响应**的时刻
    （见 ``crawler.http.last_fetched_at``）。它是「数据何时获取」，而不是
    「本次入库时间」——没有缓存文件 mtime 可用之后，这个语义由请求本身延续。
    """
    conn.execute(
        INSERT_INGEST,
        {
            "appid": appid,
            "source": source,
            "status": status,
            "error": error,
            "fetched_at": http.last_fetched_at(source),
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


def write_achievement_pairs(
    conn: Any, appid: int, pairs: list[dict[str, Any]]
) -> None:
    """把配好对的成就行写入 ``achievements``（先删后插，position 从 1 连续编号）。

    供 :func:`rebuild_achievements`（按位对齐）与 ``cleaning.repair_mapping``
    （percent 重对齐）共用，保证两条路径的落库方式完全一致。

    Args:
        conn: 已开启事务的连接。
        appid: 游戏appid。
        pairs: ``[{api_name, display_name, description, percent}, ...]``，
            顺序即最终 position 顺序。
    """
    conn.execute(text("DELETE FROM achievements WHERE appid = :a"), {"a": appid})
    conn.execute(
        INSERT_ACHIEVEMENT,
        [
            {
                "appid": appid,
                "position": i + 1,
                **pair,
            }
            for i, pair in enumerate(pairs)
        ],
    )


def sequences_within_tolerance(
    valve_pct: list[float], page_pct: list[float], tol: float = 0.5
) -> bool:
    """两源 percent 序列**逐位**差异是否都在容差内（等长才可比）。

    为什么不能精确比较（2026-09-22 实测）：社区页与全局接口的 percent 存在
    ≤0.1 的舍入/缓存差（抽样 5 款全部逐位差 ≤0.1），精确比较会把这些
    「顺序其实一致」的游戏误标为不一致——台账一度积累 37 款假阳性。
    真正的乱序会让某些位置的差距拉大到个位数百分点，0.5 的容差挡得住；
    相邻成就 percent 本来就接近时即使互换也对分析无实质影响（难度近似）。
    """
    if len(valve_pct) != len(page_pct):
        return False
    return all(abs(a - b) <= tol for a, b in zip(valve_pct, page_pct))


def rebuild_achievements(
    conn: Any,
    appid: int,
    *,
    valve: list[dict[str, Any]] | None = None,
    community: list[dict[str, Any]] | None = None,
) -> int:
    """按位对齐两个成就源，**重建**该游戏的 ``achievements``。返回条数。

    两个源顺序一致（2026-09-15 实测）才敢按位 zip；不一致时只对齐到较短的一方
    并告警——正式流程应把差异写入差集报告。

    任何一方没拿到就返回 0（另一方的任务稍后完成时会再调一次本函数）。
    先删后插：游戏更新会让 position 变动，upsert 会撞 UNIQUE(appid, position)。

    Args:
        valve: 已取到的全局完成率数据。**传进来可以省一次请求**——调用方若刚
            抓过就直接给，缺省时才自己取。这个参数存在的意义：缓存曾掩盖了
            「任务分支与 rebuild 各取一次」的重复，去掉缓存后不修这里就会
            每款游戏多 2 次请求（2026-09-17 发现）。
        community: 已取到的社区成就页数据，同上。
    """
    if valve is None:
        valve = fetch_global_achievement_percentages(appid)
    if community is None:
        community = fetch_community_achievements(appid)
    if not valve or not community:
        return 0

    valve_pct = [float(a["percent"]) for a in valve]
    page_pct = [r["percent"] for r in community]
    if not sequences_within_tolerance(valve_pct, page_pct):
        # 按位对齐的根基被动摇：长度不同，或某些位置 percent 差距超出容差
        #（疑似排序不同）。落台账（repair_mapping 之后会尝试重对齐），
        # 建模侧过滤 resolved=false 的游戏。
        logger.warning(
            "成就两源不一致：appid=%s 全局接口 %d 项 / 社区页 %d 项，逐位容差内=%s",
            appid,
            len(valve),
            len(community),
            sequences_within_tolerance(valve_pct, page_pct),
        )
        conn.execute(
            UPSERT_MAPPING_ISSUE,
            {
                "appid": appid,
                "reason": (
                    f"两源percent逐位差异超容差（全局 {len(valve)} 项 / 社区 {len(community)} 项）"
                ),
            },
        )
    else:
        # 之前标记过、这次两源一致了（如修复脚本重抓后）→ 销账
        conn.execute(RESOLVE_MAPPING_ISSUE, {"appid": appid})
    n = min(len(valve), len(community))
    write_achievement_pairs(
        conn,
        appid,
        [
            {
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
    # 判据是「有 key 来源」：共享密钥池（worker 启动时注入了 provider）**或**本地
    # .env 的单 key。历史教训（2026-09-23）：这里曾用 config.rawg_enabled()（只看
    # 本地 .env），在多机场景下把任务烧成终态 skipped；该函数已删除。
    from crawler.rawg import key_available, match_by_appid, split_tags

    if not key_available():
        return "skipped", "既无本地 RAWG_API_KEY，也无可用共享密钥池"
    if not names:
        return "empty", "games 表里没有可用名字（需先跑 appdetails 或 seed）"

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
    log_ingest(conn, appid, "rawg", "ok")
    return "ok", None


# ── 统一入口 ──────────────────────────────────────────────


def run_source(conn: Any, appid: int, source: str) -> tuple[str, str | None]:
    """执行**单个源**的抓取与入库（幂等），并写一条 ``ingest_log``。

    这是 ``worker``（gap 驱动队列）用的唯一入口，保证写入语义只有一套。

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
    except SourceChallenge:
        # 反爬挑战**原样上抛**：它不是任务的错，也不该在这里被记成 error
        # 并消耗重试预算。worker 会把它当「源级临时不可用」处理——任务放回
        # pending、本轮挂起该源（2026-09-24：SteamSpy 间歇 403 曾烧掉 23 条任务）。
        raise
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
        # achievements，两边齐了才算真写完（见模块 docstring）。
        # 已抓到的那份直接传给 rebuild，避免它内部再取一遍。
        valve: list[dict[str, Any]] | None = None
        community: list[dict[str, Any]] | None = None
        if source == "global_ach":
            valve = fetch_global_achievement_percentages(appid)
            got = valve
        else:
            community = fetch_community_achievements(appid)
            got = community
        log_ingest(conn, appid, source, "ok" if got else "empty")
        if got:
            rebuild_achievements(conn, appid, valve=valve, community=community)
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
