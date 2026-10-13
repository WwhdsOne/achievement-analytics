"""cleaning.requeue_empty — 把终态 ``empty`` 的任务放回队列，重新核验一遍

**为什么需要**：``empty`` 是**终态**（不再重试），它同时承载两种完全不同的含义：

1. 「这个游戏确实没有这份数据」——真结论，重验也还是 empty；
2. 「这一次请求被软拒绝了」——**假空**，重验就能拿到数据。

2026-09-27 实测第 2 种占了绝大多数：7,402 条 appdetails 的 ``empty`` 里，
抽样重抓 **93% 恢复正常**（Steam 在 HTTP 200 下返回 ``success: false`` 的随机
软拒绝）。因为 empty 是终态，这部分数据原本**永远不会再试**。

所以这个脚本是「**终态可复核**」的操作入口：怀疑某源有假空时跑一次，
它把 empty 放回 pending，worker 下一轮自然重验（真空的会再次落回 empty）。

用法::

    uv run python -m cleaning.requeue_empty                      # 全部源（只看，dry-run）
    uv run python -m cleaning.requeue_empty --apply              # 全部源，真的重置
    uv run python -m cleaning.requeue_empty --source appdetails_en --apply
    uv run python -m cleaning.requeue_empty --source appdetails_en,appdetails_zh --apply
    uv run python -m cleaning.requeue_empty --limit 100 --apply  # 每源最多重置 100 条

⚠️ 重验**要花真实请求**：appdetails_en + appdetails_zh 各 7,400 条 ≈ 1.5 万次请求
（免 key，但按 1s 限速约 4 小时）。建议在队列空、机器空闲时跑。
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import text

from cleaning.db import get_engine

logger = logging.getLogger(__name__)

# 每源各取前 N 条（同一游戏的中英文任务都重置，避免半拉子状态）
SELECT_EMPTY = text(
    """
    SELECT source, appid FROM fetch_tasks
     WHERE status = ANY(CAST(:statuses AS TEXT[]))
       AND (CAST(:sources AS TEXT[]) IS NULL OR source = ANY(CAST(:sources AS TEXT[])))
     ORDER BY source, appid
    """
)

REQUEUE = text(
    """
    UPDATE fetch_tasks
       SET status = 'pending', attempts = 0, last_error = NULL,
           next_retry_at = NULL, claimed_by = NULL, lease_until = NULL,
           updated_at = now()
     WHERE source = :source AND appid = :appid
       AND status = ANY(CAST(:statuses AS TEXT[]))
    """
)


def main() -> None:
    parser = argparse.ArgumentParser(description="把终态任务放回队列重新核验")
    parser.add_argument(
        "--source", default=None,
        help="只处理这些源（逗号分隔）；默认全部源",
    )
    parser.add_argument(
        "--status", default="empty",
        help="要复核的终态（逗号分隔），默认 empty；"
             "exhausted 也可一起传——那类「重试耗尽」同样是可复核的终态",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="每个源最多重置多少条；默认不限",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="真的写库；不加这个参数只统计（dry-run）",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sources = [s.strip() for s in args.source.split(",")] if args.source else None
    statuses = [s.strip() for s in args.status.split(",")]

    engine = get_engine()
    params = {"sources": sources, "statuses": statuses}
    with engine.connect() as conn:
        rows = conn.execute(SELECT_EMPTY, params).all()

    # 按源分桶 + 应用每源上限
    by_source: dict[str, list[int]] = {}
    for source, appid in rows:
        bucket = by_source.setdefault(source, [])
        if args.limit is None or len(bucket) < args.limit:
            bucket.append(appid)

    print("=" * 56)
    print(f"  复核终态: {', '.join(statuses)}")
    for source in sorted(by_source):
        print(f"  {source:<18}{len(by_source[source]):>7,} 条")
    print(f"  {'合计':<18}{sum(len(v) for v in by_source.values()):>7,} 条")
    print("=" * 56)

    if not args.apply:
        print("\n[dry-run] 没有写库。加 --apply 才会真的重置为 pending。")
        return

    moved = 0
    with engine.begin() as conn:
        for source, appids in by_source.items():
            for appid in appids:
                moved += conn.execute(
                    REQUEUE,
                    {"source": source, "appid": appid, "statuses": statuses},
                ).rowcount
    logger.info("已把 %d 条终态任务放回队列（worker 下一轮会自动重验）", moved)
    print(f"\n✓ 已重置 {moved:,} 条。启动 worker 即可重验：uv run python -m cleaning.worker")


if __name__ == "__main__":
    main()
