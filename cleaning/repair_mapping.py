"""cleaning.repair_mapping — 成就名映射修复：对两源顺序不一致的游戏按 percent 重对齐

背景：``writers.rebuild_achievements`` 靠「全局接口与社区页顺序一致」按位配对
成就的内部名与展示名（2026-09-15 实测多数游戏成立）。个别游戏两源排序不同，
按位 zip 会把展示名贴到错误的成就上——这类游戏被抓取时记入 ``mapping_issues``
台账（resolved=false）。

本脚本在**全量抓取结束后**离线跑一次（两源均免费，不花 RAWG 配额）：

1. 圈出待处理名单（三种来源可叠加）：
   - ``--from-issues``：台账里 resolved=false 的游戏
   - ``--before <ISO时刻>``：标记功能部署**前**处理的老游戏——从不可变审计表
     ``ingest_log`` 按时间切出（它们当时无法落标记，只能全量复验）
   - ``--appid``：单款调试
2. 逐个重抓两源并核验：
   - percent 序列**逐位差在容差内**（≤0.5，舍入/缓存噪声）→ 原映射本来就对，销账
   - 超容差但**量化后多重集相同** → 按 percent 重对齐回写（确定性正确）
   - 有同分成就（多个成就 percent 相同）→ 组内配对不可证，**保持原状**并记原因
   - 多重集也对不上（疑似真乱序）→ 保持原状并记原因，留人工
3. 每次修复的真实请求照常记入 ``api_usage``

用法::

    uv run python -m cleaning.repair_mapping --from-issues --before "2026-09-22T12:00:00Z"
    uv run python -m cleaning.repair_mapping --appid 300 --dry-run
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from typing import Any

from sqlalchemy import Engine, text

from crawler.http import set_call_recorder
from crawler.steam_api import (
    fetch_community_achievements,
    fetch_global_achievement_percentages,
)
from cleaning.db import ensure_ready, get_engine
from cleaning.writers import (
    sequences_within_tolerance,
    write_achievement_pairs,
)
from cleaning.worker import UsageRecorder, flush_usage

logger = logging.getLogger(__name__)

# percent 量化精度：两源都保留 1 位小数，但浮点误差可能出现 84.30000001 vs 84.3，
# 统一 round 到 1 位再比对
QUANTIZE = 1

# 对齐结果状态
ALIGNED = "aligned"            # 量化多重集相同且无同分歧义，重对齐确定性正确
AMBIGUOUS = "ambiguous"        # 有同分成就，组内配对不可证，保持原状
INCOMPATIBLE = "incompatible"  # 量化多重集都对不上，无法自动修复

# 台账读写（与 writers.py 的同名常量保持同一 SQL 语义）
UPSERT_ISSUE = text(
    """
    INSERT INTO mapping_issues (appid, reason)
    VALUES (:appid, :reason)
    ON CONFLICT (appid) DO UPDATE SET
        reason = EXCLUDED.reason, detected_at = now(), resolved = false
    """
)
RESOLVE_ISSUE = text("UPDATE mapping_issues SET resolved = true WHERE appid = :appid")

SELECT_OPEN_ISSUES = text(
    "SELECT appid FROM mapping_issues WHERE NOT resolved ORDER BY appid"
)

# 部署标记前的老游戏：从不可变审计表按时间切出（有成就数据的才有修复意义）
SELECT_COHORT_BEFORE = text(
    """
    SELECT DISTINCT l.appid
    FROM ingest_log l
    JOIN achievements a ON a.appid = l.appid
    WHERE l.source = 'community_ach' AND l.fetched_at < CAST(:t AS TIMESTAMPTZ)
    ORDER BY 1
    """
)


def align_by_percent(
    valve: list[dict[str, Any]], community: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, str]:
    """把两源按量化 percent 对齐，返回 ``(pairs, status)``。

    Args:
        valve: 全局接口数据 ``[{name, percent}, ...]``（其顺序即目标顺序）。
        community: 社区页数据 ``[{display_name, description, percent}, ...]``。

    Returns:
        pairs 为 ``[{api_name, display_name, description, percent}, ...]``（按
        valve 顺序）；status 为 ALIGNED / AMBIGUOUS / INCOMPATIBLE。
        INCOMPATIBLE 时 pairs 为 None。
    """
    if len(valve) != len(community):
        return None, INCOMPATIBLE
    v_keys = [round(float(a["percent"]), QUANTIZE) for a in valve]
    c_keys = [round(float(r["percent"]), QUANTIZE) for r in community]
    if sorted(v_keys) != sorted(c_keys):
        return None, INCOMPATIBLE

    used: set[int] = set()
    pairs: list[dict[str, Any]] = []
    ambiguous = False
    for i, key in enumerate(v_keys):
        # 同分即歧义：组内配对只能按相对顺序猜，结果不可证
        if v_keys.count(key) > 1:
            ambiguous = True
        # 贪心取第一个未使用的同分社区条目（顺序稳定，可复现）
        for j, c_key in enumerate(c_keys):
            if j not in used and c_key == key:
                used.add(j)
                pairs.append(
                    {
                        "api_name": valve[i]["name"],
                        "display_name": community[j]["display_name"],
                        "description": community[j]["description"] or None,
                        "percent": float(valve[i]["percent"]),
                    }
                )
                break
    return pairs, (AMBIGUOUS if ambiguous else ALIGNED)


def judge_and_write(
    conn: Any,
    appid: int,
    valve: list[dict[str, Any]],
    community: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> str:
    """核验单款游戏并写库（fetch 应在事务外完成后传入）。返回处理结果状态。

    ok=原映射正确 / repaired=已重对齐回写 / ambiguous=同分歧义保持原状 /
    incompatible=percent 集合不一致保持原状 / empty_now=现在两源为空。
    """
    if not valve or not community:
        logger.warning(
            "appid=%s 修复时源返回空（valve=%d / community=%d）",
            appid, len(valve), len(community),
        )
        if not dry_run:
            conn.execute(UPSERT_ISSUE, {"appid": appid, "reason": "修复时源返回空，无法核验"})
        return "empty_now"

    valve_pct = [round(float(a["percent"]), QUANTIZE) for a in valve]
    page_pct = [round(float(r["percent"]), QUANTIZE) for r in community]
    if sequences_within_tolerance(valve_pct, page_pct):
        # 逐位都在容差内 → 按位对齐本来就正确（≤0.1 的舍入差不算），只销账不动数据
        if not dry_run:
            conn.execute(RESOLVE_ISSUE, {"appid": appid})
        return "ok"

    pairs, status = align_by_percent(valve, community)
    if dry_run:
        return status
    if status == ALIGNED:
        write_achievement_pairs(conn, appid, pairs)
        conn.execute(RESOLVE_ISSUE, {"appid": appid})
        return "repaired"
    # ambiguous / incompatible：保持原状，把原因记进台账
    conn.execute(
        UPSERT_ISSUE,
        {
            "appid": appid,
            "reason": (
                "同分成就多，percent 对齐存在歧义"
                if status == AMBIGUOUS
                else "两源percent逐位差异超容差且多重集不匹配，疑似排序不同，留人工核验"
            ),
        },
    )
    return status


def gather_appids(
    engine: Engine,
    *,
    from_issues: bool,
    before: str | None,
    appid: int | None,
) -> list[int]:
    """合并三种名单来源并去重排序。"""
    appids: set[int] = set()
    with engine.connect() as conn:
        if from_issues:
            appids.update(int(r[0]) for r in conn.execute(SELECT_OPEN_ISSUES))
        if before:
            appids.update(int(r[0]) for r in conn.execute(SELECT_COHORT_BEFORE, {"t": before}))
        if appid is not None:
            appids.add(appid)
    return sorted(appids)


def main() -> None:
    """CLI 入口。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="成就名映射修复：对两源顺序不一致的游戏按 percent 重对齐"
    )
    parser.add_argument(
        "--from-issues", action="store_true",
        help="处理 mapping_issues 里 resolved=false 的游戏",
    )
    parser.add_argument(
        "--before", default=None,
        help="复验该 ISO 时刻之前处理的所有游戏（部署标记前完成的老数据用）",
    )
    parser.add_argument("--appid", type=int, default=None, help="只处理这一款（调试）")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少款")
    parser.add_argument("--dry-run", action="store_true", help="只核验和报告，不写库")
    args = parser.parse_args()

    if not (args.from_issues or args.before or args.appid):
        parser.error("至少给一种名单来源：--from-issues / --before / --appid")

    engine = get_engine()
    ensure_ready(engine)
    appids = gather_appids(
        engine, from_issues=args.from_issues, before=args.before, appid=args.appid
    )
    if args.limit:
        appids = appids[: args.limit]
    if not appids:
        print("名单为空，无事可做")
        return
    print(f"待处理 {len(appids)} 款游戏（dry_run={args.dry_run}）")

    recorder = UsageRecorder()
    set_call_recorder(recorder)
    counts: Counter[str] = Counter()
    try:
        for i, aid in enumerate(appids, 1):
            # 抓取在事务外（网络慢，不该握着事务等）；写库用独立短事务
            valve = fetch_global_achievement_percentages(aid)
            community = fetch_community_achievements(aid)
            with engine.begin() as conn:
                status = judge_and_write(
                    conn, aid, valve, community, dry_run=args.dry_run
                )
            counts[status] += 1
            if i % 100 == 0 or i == len(appids):
                with engine.begin() as conn:
                    flush_usage(conn, recorder)
                logger.info("进度 %d/%d %s", i, len(appids), dict(counts))
    finally:
        set_call_recorder(None)
        if not args.dry_run:
            with engine.begin() as conn:
                flush_usage(conn, recorder)

    print("=" * 52)
    for k, v in sorted(counts.items()):
        print(f"  {k:<14}{v}")
    with engine.connect() as conn:
        left = conn.execute(
            text("SELECT count(*) FROM mapping_issues WHERE NOT resolved")
        ).scalar()
    print(f"  台账剩余未解决：{left}")


if __name__ == "__main__":
    main()
