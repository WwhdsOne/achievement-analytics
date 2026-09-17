"""cleaning.worker — gap 驱动回填：反复「取缺口 → 抓 → 回填」

这是 gap 驱动架构的**第二步**（第一步是 ``cleaning.seed``）。核心循环：

1. 从 ``fetch_tasks`` 取一批**可执行**的任务
   （status 为 pending/error，attempts 未达上限，退避已到期）
2. 逐个调 ``cleaning.writers.run_source`` 抓取并幂等入库
3. 回填 ``fetch_tasks`` 的状态、attempts 与下次重试时间
4. 记账 ``api_usage``（只记真实网络请求，缓存命中不计）

与「一个大脚本顺序跑完 8 万款」相比，本设计的关键性质：
- **可中断**：随时 Ctrl-C，重跑会自动跳过已完成的
- **可观测**：进度查 ``ingest_progress`` 视图
- **有终止条件**：``empty`` 是确定性终态（不重试），``error`` 退避重试到
  ``sources.max_attempts`` 后转 ``exhausted``。因此 ``ingest_gaps`` 单调收敛，
  不会因为「某游戏本来就没成就」而无限重爬
- **可编排优先级**：先给一小批物化任务跑通验收，再扩量（seed 的 --sample）

**并发说明**：当前按单 worker 设计，claim 不加锁、每个任务一个短事务。
好处是不持有长事务（网络请求可能耗时数秒）；代价是两个 worker 并行时会重复抓同一
任务——但缓存层会让第二个直接命中，不会重复打网络。真要并行再引入租约列
（claim 时置 running + 过期时间），不要在没需求时提前加。

用法::

    uv run python -m cleaning.worker --limit 20            # 跑 20 个任务看看
    uv run python -m cleaning.worker --source global_ach   # 只跑某个源
    uv run python -m cleaning.worker                       # 一直跑到没有可执行任务
    uv run python -m cleaning.worker --dry-run             # 只看还要抓什么，不发请求
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, text

from crawler.http import set_call_recorder
from cleaning.db import apply_schema, get_engine
from cleaning.writers import run_source

logger = logging.getLogger(__name__)

# 失败退避：base * 2^(attempts-1)，上限 cap。避免失败任务被立刻反复重试。
BACKOFF_BASE_SEC = 60
BACKOFF_CAP_SEC = 3600

# 一次从库里取多少任务（批大一点减少往返，但每条任务可能耗时数秒，别太大）
CLAIM_BATCH = 20

# 可执行任务：状态还能推进、尝试次数没到上限、退避已到期
SELECT_CLAIMABLE = text(
    """
    SELECT t.appid, t.source
    FROM fetch_tasks t
    JOIN sources s ON s.source = t.source
    WHERE t.status IN ('pending', 'error')
      AND t.attempts < s.max_attempts
      AND (t.next_retry_at IS NULL OR t.next_retry_at <= now())
      -- CAST 不能省：参数为 NULL 时 Postgres 无法推断 $1 的类型，会报
      -- AmbiguousParameter: could not determine data type of parameter（2026-09-17 踩到）
      AND (CAST(:source AS TEXT) IS NULL OR t.source = CAST(:source AS TEXT))
    ORDER BY t.source, t.appid
    LIMIT :n
    """
)

UPDATE_TASK = text(
    """
    UPDATE fetch_tasks
       SET status        = :status,
           attempts      = attempts + 1,
           last_error    = :error,
           next_retry_at = :next_retry_at,
           updated_at    = now()
     WHERE appid = :appid AND source = :source
    """
)

# 配额已耗尽的源：日限或月限任一用满，本次运行就不再给它派活
SELECT_EXHAUSTED_QUOTA = text(
    """
    SELECT source FROM quota_status
    WHERE (daily_quota   IS NOT NULL AND remaining_today        <= 0)
       OR (monthly_quota IS NOT NULL AND remaining_this_month   <= 0)
    """
)

UPSERT_USAGE = text(
    """
    INSERT INTO api_usage (source, day, requests)
    VALUES (:source, current_date, :requests)
    ON CONFLICT (source, day) DO UPDATE SET
        requests = api_usage.requests + EXCLUDED.requests
    """
)

SELECT_PROGRESS = text(
    """
    SELECT source, total, ok, empty, skipped, error, exhausted, pending, actionable
    FROM ingest_progress
    WHERE total > 0
    ORDER BY source
    """
)


class UsageRecorder:
    """累计真实网络请求数，按源分桶，之后一次性刷进 ``api_usage``。

    HTTP 层（``crawler.http``）不碰数据库，只在真正发出请求时回调这里；
    缓存命中不经过 HTTP 层，因此天然不计入配额。
    """

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def __call__(self, source: str) -> None:
        self.counts[source] += 1

    def drain(self) -> dict[str, int]:
        """取走当前累计值并清零。"""
        taken = dict(self.counts)
        self.counts.clear()
        return taken


def next_retry_at(attempts: int, now: datetime | None = None) -> datetime:
    """按尝试次数算下次重试时间（指数退避，封顶）。

    Args:
        attempts: **已完成的**尝试次数（即本次失败后的 attempts 值）。
        now: 基准时间，默认当前 UTC。

    Returns:
        下次可重试时间。
    """
    base = now or datetime.now(timezone.utc)
    delay = min(BACKOFF_BASE_SEC * (2 ** max(attempts - 1, 0)), BACKOFF_CAP_SEC)
    return base + timedelta(seconds=delay)


def claimable(conn: Any, source: str | None = None, limit: int = CLAIM_BATCH) -> list[tuple[int, str]]:
    """取一批可执行任务（不加锁，见模块 docstring 的并发说明）。"""
    rows = conn.execute(SELECT_CLAIMABLE, {"source": source, "n": limit}).all()
    return [(int(r[0]), str(r[1])) for r in rows]


def quota_exhausted(conn: Any) -> set[str]:
    """配额已耗尽的源集合（日限或月限用满）。"""
    return {str(r[0]) for r in conn.execute(SELECT_EXHAUSTED_QUOTA).all()}


def complete(
    conn: Any,
    appid: int,
    source: str,
    status: str,
    error: str | None,
    attempts_after: int,
) -> None:
    """回填任务状态。

    ``ok`` / ``empty`` / ``skipped`` 是**终态**，不再重试（这是循环能终止的关键）；
    ``error`` 按退避重试，``attempts_after`` 到上限时改判 ``exhausted``。
    """
    nxt: datetime | None = None
    final = status
    if status == "error":
        spec_max = _max_attempts(conn, source)
        if attempts_after >= spec_max:
            final = "exhausted"
        else:
            nxt = next_retry_at(attempts_after)
    conn.execute(
        UPDATE_TASK,
        {
            "appid": appid,
            "source": source,
            "status": final,
            "error": error,
            "next_retry_at": nxt,
        },
    )


def _max_attempts(conn: Any, source: str) -> int:
    """查某源的重试上限。"""
    row = conn.execute(
        text("SELECT max_attempts FROM sources WHERE source = :s"), {"s": source}
    ).first()
    return int(row[0]) if row else 3


def flush_usage(conn: Any, recorder: UsageRecorder) -> None:
    """把累计的真实请求数写进 ``api_usage``。"""
    for source, n in recorder.drain().items():
        conn.execute(UPSERT_USAGE, {"source": source, "requests": n})


def run(
    engine: Engine,
    *,
    source: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """主循环：反复取缺口并回填，直到没有可执行任务（或达到 limit）。

    Args:
        engine: SQLAlchemy Engine。
        source: 只跑某个源；None 表示所有源。
        limit: 最多处理多少个任务；None 表示不限（跑到没有可执行任务）。
        dry_run: 只报告还要抓什么，不发请求、不写库。

    Returns:
        各状态计数 ``{"ok": n, "empty": n, ...}``。
    """
    apply_schema(engine)
    recorder = UsageRecorder()
    set_call_recorder(recorder)
    stats: Counter[str] = Counter()

    done = 0
    try:
        while True:
            if limit is not None and done >= limit:
                break
            batch_size = CLAIM_BATCH if limit is None else min(
                CLAIM_BATCH, limit - done
            )
            with engine.begin() as conn:
                blocked = quota_exhausted(conn)
                rows = [
                    (a, s)
                    for a, s in claimable(conn, source, batch_size)
                    if s not in blocked
                ]
            if not rows:
                if blocked:
                    logger.warning(
                        "配额耗尽的源已跳过：%s（今日/本月额度用满）",
                        ", ".join(sorted(blocked)),
                    )
                logger.info("没有可执行任务了，结束")
                break

            for appid, src in rows:
                if dry_run:
                    logger.info("[dry-run] 待抓 appid=%s source=%s", appid, src)
                    stats["dry_run"] += 1
                    done += 1
                    continue
                # 每个任务一个短事务：网络请求可能耗时数秒，不该握着事务等
                with engine.begin() as conn:
                    # 护栏：run_source 本应自己吞掉异常并返回 ('error', msg)，
                    # 但万一它抛出来了，绝不能让整个 worker 崩掉——那会让任务永远
                    # 停在 pending、进度无法解释。这里兜成 error 走正常退避。
                    try:
                        with conn.begin_nested():
                            task_status, err = run_source(conn, appid, src)
                    except Exception as exc:  # noqa: BLE001
                        task_status, err = "error", f"未捕获异常：{exc}"[:500]
                        logger.exception(
                            "run_source 抛出未捕获异常：appid=%s source=%s",
                            appid,
                            src,
                        )
                    attempts_after = (
                        conn.execute(
                            text(
                                "SELECT attempts + 1 FROM fetch_tasks"
                                " WHERE appid = :a AND source = :s"
                            ),
                            {"a": appid, "s": src},
                        ).scalar()
                        or 1
                    )
                    complete(conn, appid, src, task_status, err, int(attempts_after))
                    flush_usage(conn, recorder)
                stats[task_status] += 1
                done += 1
                logger.info(
                    "[%d] appid=%s %s -> %s%s",
                    done,
                    appid,
                    src,
                    task_status,
                    f"（{err}）" if err else "",
                )
                if limit is not None and done >= limit:
                    break
    finally:
        set_call_recorder(None)
        if not dry_run:
            with engine.begin() as conn:
                flush_usage(conn, recorder)

    return dict(stats)


def print_progress(engine: Engine) -> None:
    """打印各源的队列进度（来自 ingest_progress 视图）。"""
    with engine.connect() as conn:
        rows = conn.execute(SELECT_PROGRESS).all()
    if not rows:
        print("（队列为空：还没 seed 过，或所有游戏都已处理完）")
        return
    header = (
        f"{'源':<16}{'总数':>8}{'ok':>8}{'empty':>7}{'skip':>6}"
        f"{'err':>6}{'exh':>6}{'待抓':>8}{'可执行':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r[0]:<16}{r[1]:>8}{r[2]:>8}{r[3]:>7}{r[4]:>6}"
            f"{r[5]:>6}{r[6]:>6}{r[7]:>8}{r[8]:>8}"
        )


def main() -> None:
    """CLI 入口。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="gap 驱动回填：反复取缺口 → 抓 → 回填"
    )
    parser.add_argument("--source", default=None, help="只跑某个源")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少个任务")
    parser.add_argument(
        "--dry-run", action="store_true", help="只看还要抓什么，不发请求不写库"
    )
    parser.add_argument(
        "--progress", action="store_true", help="打印进度后退出"
    )
    args = parser.parse_args()

    engine = get_engine()
    if args.progress:
        print_progress(engine)
        sys.exit(0)

    try:
        stats = run(
            engine, source=args.source, limit=args.limit, dry_run=args.dry_run
        )
    except KeyboardInterrupt:
        print("\n已中断（进度已入库，直接重跑即可续）")
        print_progress(engine)
        sys.exit(130)

    print()
    print("=" * 52)
    for k, v in sorted(stats.items()):
        print(f"  {k:<10} {v}")
    print("=" * 52)
    print_progress(engine)


if __name__ == "__main__":
    main()
