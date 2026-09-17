"""cleaning.build_dataset — 一次性批量路径：目标清单 → PostgreSQL

把指定的一批 appid 从各数据源抓齐并入库。**这是「一次性跑一批」的便捷入口**；
要「先灌全量游戏再逐个补缺」请用 ``cleaning.seed``（灌种子）+ ``cleaning.worker``
（gap 驱动回填），两者更耐中断、进度可查。

两条路径的写入语义完全一致——都走 ``cleaning.writers.run_source``，
所以不存在「批量脚本和队列写出来的数据不一样」这种漂移。

设计原则：**raw 是不可变事实源，DB 是可重建的派生层**。
- 采集走 ``crawler.*``，自带缓存：爬过的直接命中，没爬过的才发请求
- 写入全部幂等（upsert / 先删后插），可以反复重跑
- 每个源都写 ``ingest_log``，且**细粒度到真实请求**（appdetails 中英文分开、
  两个成就源分开），这样"哪个源没拿到"才能一眼看出
- ``ingest_log.fetched_at`` 取**缓存文件的 mtime**（真实抓取时间），不是入库时间

用法::

    uv run python -m cleaning.build_dataset              # 全部（含 appid 的条目）
    uv run python -m cleaning.build_dataset 374320       # 只跑指定 appid（调试）
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from cleaning.db import apply_schema, get_engine
from cleaning.writers import run_source, update_game_fields

logger = logging.getLogger(__name__)

TARGET_GAMES = Path(__file__).resolve().parent.parent / "crawler" / "target_games.json"

# 除 appdetails_en 之外的逐款源；appdetails_en 必须最先跑（它负责建立 games 行
# 并提供官方名），所以单独列在前面。
_SOURCES_AFTER_GAME = (
    "appdetails_zh",
    "global_ach",
    "community_ach",
    "steamspy",
    "rawg",
)


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


def build(engine: Engine, appids: list[int] | None = None) -> dict[str, int]:
    """把指定的一批游戏从各源抓齐并入库。返回计数统计。

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
            with engine.begin() as conn:
                # 顺序要紧：appdetails_en 建 games 行（父表），其余源表都 REFERENCES 它
                status, _ = run_source(conn, appid, "appdetails_en")
                if status != "ok":
                    logger.warning("appdetails_en 没拿到，跳过该游戏：appid=%s", appid)
                    stats["errors"] += 1
                    continue
                # games 行已由上面那步建好；source_title 只是补一个既有字段，
                # 走 UPDATE-only（name_en 是 NOT NULL，upsert 传 None 会违约束）
                if source_title:
                    update_game_fields(conn, appid, source_title=source_title)
                for source in _SOURCES_AFTER_GAME:
                    run_source(conn, appid, source)
                n = conn.execute(
                    text("SELECT count(*) FROM achievements WHERE appid = :a"),
                    {"a": appid},
                ).scalar()
            stats["games"] += 1
            stats["achievements"] += int(n or 0)
            logger.info("已入库 appid=%s（成就 %s 条）", appid, n)
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
