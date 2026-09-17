"""cleaning.seed — 种子：把「最公开的信息」灌成全量游戏，并物化任务队列

这是 gap 驱动架构的**第一步**。两步走：

1. **灌游戏身份（帧）**：用 ``crawler.store_search`` 枚举目标总体（默认 81,849 款
   带 Steam 成就的游戏），幂等写 ``games`` + ``store_search_games``。
   成本极低：一次请求 100 款，全量约 819 次请求、1s 间隔约 14 分钟。
2. **物化任务队列**：把 (游戏 × 逐款源) 展开写进 ``fetch_tasks``（初始 pending）。
   之后 ``cleaning.worker`` 反复「取缺口 → 抓 → 回填」。

第 2 步的规模是**运行参数**而非架构承诺：先只物化很小的一批跑通验收，再逐步扩到
全量。这是本项目「先 baseline / 先小样本」原则在数据侧的对应做法——管道有 bug 时
别让它在第 30 小时才暴露。

抽样口径必须记录，因为**「前 N 款」不是随机样本**：商店搜索的默认排序偏向热门与
新作，直接取前 N 会得到严重有偏的子集。本模块提供 ``--order random``（在已枚举
的完整帧上随机抽样），只在帧已完整时才无偏。

用法::

    # 冒烟：只枚举 300 款，看看数据形态（非随机，别当分析样本）
    uv run python -m cleaning.seed --limit 300

    # 完整帧（81,849 款，约 14 分钟），然后随机抽 5,000 款物化成任务
    uv run python -m cleaning.seed --materialize --sample 5000 --order random

    # 帧已经在库里，只重新物化任务（如换了抽样口径）
    uv run python -m cleaning.seed --no-enumerate --materialize --sample 5000
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy import Engine, text

from crawler.store_search import iter_games, total_count
from cleaning.db import apply_schema, get_engine
from cleaning.writers import parse_release_date

logger = logging.getLogger(__name__)

UPSERT_GAME_MIN = text(
    """
    INSERT INTO games (appid, name_en)
    VALUES (:appid, :name_en)
    ON CONFLICT (appid) DO UPDATE SET
        name_en    = COALESCE(EXCLUDED.name_en, games.name_en),
        updated_at = now()
    """
)

UPSERT_STORE_SEARCH = text(
    """
    INSERT INTO store_search_games (
        appid, release_date, review_label, review_percent, review_count,
        price_cents, tag_ids
    ) VALUES (
        :appid, :release_date, :review_label, :review_percent, :review_count,
        :price_cents, :tag_ids
    )
    ON CONFLICT (appid) DO UPDATE SET
        release_date   = EXCLUDED.release_date,
        review_label   = EXCLUDED.review_label,
        review_percent = EXCLUDED.review_percent,
        review_count   = EXCLUDED.review_count,
        price_cents    = EXCLUDED.price_cents,
        tag_ids        = EXCLUDED.tag_ids,
        fetched_at     = now()
    """
)

# 物化 (游戏 × 逐款源) 的任务全集。
# **只物化 kind='per_game' 的源**：bulk 源（商店搜索、SteamSpy all）一次请求覆盖
# 上百上千款，逐条入队是反优化，它们走独立的「全量刷新」路径。
INSERT_TASKS = text(
    """
    INSERT INTO fetch_tasks (appid, source)
    SELECT g.appid, s.source
    FROM games g
    CROSS JOIN sources s
    WHERE s.kind = 'per_game'
      -- CAST 不能省：参数为 NULL 时 Postgres 推断不出类型（AmbiguousParameter）
      AND (CAST(:appids AS INTEGER[]) IS NULL
           OR g.appid = ANY(CAST(:appids AS INTEGER[])))
    ON CONFLICT (appid, source) DO NOTHING
    """
)

SELECT_APPIDS_RANDOM = text(
    "SELECT appid FROM games ORDER BY random() LIMIT :n"
)
SELECT_APPIDS_BY_REVIEWS = text(
    """
    SELECT g.appid
    FROM games g
    LEFT JOIN store_search_games s USING (appid)
    ORDER BY s.review_count DESC NULLS LAST
    LIMIT :n
    """
)
SELECT_APPIDS_BY_APPID = text("SELECT appid FROM games ORDER BY appid LIMIT :n")

_ORDER_SQL = {
    "random": SELECT_APPIDS_RANDOM,
    "review_count": SELECT_APPIDS_BY_REVIEWS,
    "appid": SELECT_APPIDS_BY_APPID,
}


def seed_games(
    engine: Engine,
    *,
    limit: int | None = None,
    games_only: bool = True,
    has_achievements: bool = True,
) -> dict[str, int]:
    """枚举商店搜索并把游戏身份与公开信息幂等入库。返回计数。

    Args:
        engine: SQLAlchemy Engine。
        limit: 只枚举前 N 款（冒烟测试用）。**非随机**，见模块 docstring。
        games_only: 只枚举游戏（排除 DLC / 软体 / 原声带）。
        has_achievements: 只枚举带 Steam 成就的游戏（默认，这才是 Q1/Q2 的总体）。
    """
    apply_schema(engine)
    stats = {"enumerated": 0, "games": 0, "errors": 0, "holes": 0}
    batch: list[dict[str, Any]] = []
    holes: list[int] = []

    def flush(conn: Any, rows: list[dict[str, Any]]) -> int:
        written = 0
        for row in rows:
            # 空标题的行直接丢：games.name_en 是 NOT NULL，但空字符串能插入，
            # 会留下一个查不到名字的僵尸行（RAWG 匹配也依赖它）
            if not row["name_en"]:
                logger.warning("跳过空标题的行：appid=%s", row["appid"])
                continue
            conn.execute(
                UPSERT_GAME_MIN,
                {"appid": row["appid"], "name_en": row["name_en"]},
            )
            conn.execute(
                UPSERT_STORE_SEARCH,
                {
                    "appid": row["appid"],
                    "release_date": parse_release_date(row["release_date"]),
                    "review_label": row["review_label"],
                    "review_percent": row["review_percent"],
                    "review_count": row["review_count"],
                    "price_cents": row["price_cents"],
                    "tag_ids": row["tag_ids"] or None,
                },
            )
            written += 1
        return written

    # 分批提交：整批 8 万条放一个事务里，失败就得全部重来
    try:
        for row in iter_games(
            total=limit,
            games_only=games_only,
            has_achievements=has_achievements,
            holes=holes,
        ):
            batch.append(row)
            stats["enumerated"] += 1
            if len(batch) >= 500:
                try:
                    with engine.begin() as conn:
                        stats["games"] += flush(conn, batch)
                except Exception as exc:  # noqa: BLE001 — 一批失败不中断整体
                    stats["errors"] += len(batch)
                    logger.error("本批入库失败（%d 条）：%s", len(batch), exc)
                batch = []
    finally:
        # 末批必须在 finally 里落库：枚举中途抛错时，已经抓到的数据不能跟着丢
        if batch:
            try:
                with engine.begin() as conn:
                    stats["games"] += flush(conn, batch)
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += len(batch)
                logger.error("末批入库失败（%d 条）：%s", len(batch), exc)
            batch = []

    stats["holes"] = len(holes)
    if holes:
        logger.error(
            "枚举有 %d 个偏移取数失败（空洞）：%s%s",
            len(holes),
            holes[:10],
            " …" if len(holes) > 10 else "",
        )
    return stats


def sample_appids(engine: Engine, limit: int, order: str = "random") -> list[int]:
    """从已入库的**完整帧**里挑出要跑逐款源的那批 appid。

    Args:
        engine: SQLAlchemy Engine。
        limit: 取多少款。
        order: ``random``（无偏抽样，**帧必须已完整**）/ ``review_count``
            （按评价数取热门，偏向已发售的大作）/ ``appid``（稳定但同样有偏）。

    Returns:
        appid 列表。
    """
    sql = _ORDER_SQL.get(order)
    if sql is None:
        raise ValueError(f"未知排序口径：{order}（可选 {sorted(_ORDER_SQL)}）")
    with engine.connect() as conn:
        return [int(r[0]) for r in conn.execute(sql, {"n": limit})]


def materialize_tasks(engine: Engine, appids: list[int] | None = None) -> int:
    """把 (游戏 × 逐款源) 展开写进 fetch_tasks（已存在的行不动）。返回新增行数。

    Args:
        engine: SQLAlchemy Engine。
        appids: 只给这些游戏建任务；None 表示库里全部游戏。

    Returns:
        本次新增的任务行数。
    """
    with engine.begin() as conn:
        result = conn.execute(INSERT_TASKS, {"appids": appids})
        return int(result.rowcount or 0)


def main() -> None:
    """CLI 入口。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="种子：枚举全量游戏身份并物化 gap 驱动任务队列"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="只枚举前 N 款（冒烟测试用；**非随机**，见模块 docstring）",
    )
    parser.add_argument(
        "--all-games", action="store_true",
        help="不筛 Steam 成就，枚举全部游戏（176,932 款，含无成就的）",
    )
    parser.add_argument(
        "--no-enumerate", action="store_true",
        help="跳过枚举，只用库里已有的帧（帧已完整时用，省 14 分钟）",
    )
    parser.add_argument(
        "--materialize", action="store_true", help="物化 fetch_tasks 任务队列",
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        help="物化时只给 N 款建任务（不填=全部游戏）",
    )
    parser.add_argument(
        "--order", default="random", choices=sorted(_ORDER_SQL),
        help="抽样口径；random 仅在帧完整时无偏",
    )
    args = parser.parse_args()

    engine = get_engine()
    frame_total = total_count(
        games_only=True, has_achievements=not args.all_games
    )
    print(f"目标总体（当前探测）：{frame_total} 款")

    if not args.no_enumerate:
        stats = seed_games(
            engine,
            limit=args.limit,
            games_only=True,
            has_achievements=not args.all_games,
        )
        print(
            f"枚举 {stats['enumerated']} 款，入库 {stats['games']} 款，"
            f"失败 {stats['errors']} 款"
        )
        if stats["holes"]:
            print(
                f"⚠ 有 {stats['holes']} 个偏移取数失败（空洞）：**帧不完整**，"
                f"重跑本命令会命中缓存、只补这些洞"
            )
        else:
            print("✓ 无空洞，帧完整")
        if args.limit and args.limit < frame_total:
            print(
                f"⚠ 只枚举了前 {args.limit} 款（商店默认排序，明显偏向热门/新作），"
                f"**不要**把它当分析样本"
            )

    if args.materialize:
        appids = None
        if args.sample:
            appids = sample_appids(engine, args.sample, order=args.order)
            print(f"按 {args.order} 口径抽出 {len(appids)} 款")
        added = materialize_tasks(engine, appids)
        print(f"新增任务 {added} 行")


if __name__ == "__main__":
    main()
