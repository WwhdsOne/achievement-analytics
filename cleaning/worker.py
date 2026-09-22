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

**并发说明（多机并行）**：抢占是**原子**的——一条 ``UPDATE ... WHERE (appid, source)
IN (SELECT ... FOR UPDATE SKIP LOCKED) ... RETURNING`` 同时完成「选任务」与「写租约」，
所以多台机器共用一个 Postgres 同时跑不会重复抓同一条任务。租约到期（默认 5 分钟）
即自动可被重新抢占，因此 **worker 崩溃不会让任务永久卡住**，也不需要额外的僵尸清理。

多机部署的三个前提：
1. 所有机器连**同一个** Postgres（``.env`` 里改 ``POSTGRES_HOST``）
2. ``RAWG key`` 放在**共享库的密钥池**里（``cleaning/rawg_keys.py``）——RAWG 配额
   按 key 计，各机器读本地 ``.env`` 会导致额度不可协调
3. 各机器的本地缓存 ``data/raw/cache/`` **不共享**，所以跨机器会重复抓一部分。
   重复的请求不额外消耗 RAWG 配额（缓存只在本机生效，所以其实会重复消耗）。
   如需彻底避免，共用一个缓存目录（NFS/rsync）或按 appid 分片

用法::

    uv run python -m cleaning.worker --limit 20            # 跑 20 个任务看看
    uv run python -m cleaning.worker --source global_ach   # 只跑某个源
    uv run python -m cleaning.worker                       # 一直跑到抢不到任务
    uv run python -m cleaning.worker --dry-run             # 只看还要抓什么，不发请求
    uv run python -m cleaning.worker --progress            # 看各源进度后退出
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, text

from crawler import rawg as rawg_module
from crawler.http import set_call_recorder
from crawler.registry import SOURCES
from cleaning.db import ensure_ready, get_engine
from cleaning.rawg_keys import pool_size, reserve_key
from cleaning.writers import run_source

logger = logging.getLogger(__name__)

# 失败退避：base * 2^(attempts-1)，上限 cap。避免失败任务被立刻反复重试。
BACKOFF_BASE_SEC = 60
BACKOFF_CAP_SEC = 3600

# 一次从库里取多少任务（批大一点减少往返，但每条任务可能耗时数秒，别太大）
CLAIM_BATCH = 20

# 租约时长：抢到任务后独占这么久。**故意设得比单任务最长耗时长**——一条任务最坏是
# 3 次 HTTP 重试 × 指数退避，可能几十秒。租约到期即允许别的 worker 重抢，所以宁可
# 给长一点，避免两个 worker 同时抓同一条（缓存能兜底，但会白花 RAWG 配额）。
LEASE_SEC = 300

# worker 标识：多机并行时用来分辨「谁拿着这条任务的租约」。主机名 + pid。
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

# 原子抢占：把「选任务」和「占租约」合成一条语句，多台机器同时跑也不会拿到同一条。
# FOR UPDATE SKIP LOCKED 让并发 worker 跳过已被别人锁住的行而不是排队等待——
# 这是从「单 worker 轮询」升级到「多机并行」的关键。租约到期的行会被重新抢到，
# 所以 worker 崩溃不会让任务永久卡在 pending（不需要额外的僵尸清理任务）。
CLAIM_TASKS = text(
    """
    UPDATE fetch_tasks AS t
       SET claimed_by  = :worker,
           lease_until = now() + CAST(:lease_sec AS INTEGER) * interval '1 second',
           updated_at  = now()
     WHERE (t.appid, t.source) IN (
        SELECT t2.appid, t2.source
        FROM fetch_tasks t2
        JOIN sources s ON s.source = t2.source
        WHERE t2.status IN ('pending', 'error')
          AND t2.attempts < s.max_attempts
          AND (t2.next_retry_at IS NULL OR t2.next_retry_at <= now())
          AND (t2.lease_until IS NULL OR t2.lease_until <= now())
          -- CAST 不能省：参数为 NULL 时 Postgres 无法推断 $1 的类型，会报
          -- AmbiguousParameter: could not determine data type of parameter（2026-09-17 踩到）
          AND (CAST(:source AS TEXT) IS NULL OR t2.source = CAST(:source AS TEXT))
          -- 只处理指定游戏（调试单个 appid 用；替代已删除的 build_dataset 单款路径）
          AND (CAST(:appid AS INTEGER) IS NULL OR t2.appid = CAST(:appid AS INTEGER))
          -- 配额耗尽的源直接排除在抢占之外。若只在拿回来之后过滤，那些行会白占一个
          -- 租约、5 分钟内谁都抢不到，造成反复空转
          AND (CAST(:exclude AS TEXT[]) IS NULL
               OR t2.source <> ALL(CAST(:exclude AS TEXT[])))
        -- **按 appid 优先，同游戏内再按 priority**（不是先按源）。理由有三：
        --   1. 同一游戏的任务落在同一批里，「发现无成就 → 取消其余」才真正生效
        --      （只改库状态的话，已抢进内存的待办列表还会把它跑掉，2026-09-17 踩到）
        --   2. 游戏一款一款补全，而不是「等所有游戏的 appdetails 都跑完」
        --   3. 同游戏内仍保证 global_ach 先于 rawg，剔除能省下最贵的那个源
        ORDER BY t2.appid, s.priority
        LIMIT :n
        FOR UPDATE SKIP LOCKED
     )
    RETURNING t.appid, t.source
    """
)

# 回填状态时**一并清掉租约**，否则这条任务在租约到期前不会被任何人再抢
UPDATE_TASK = text(
    """
    UPDATE fetch_tasks
       SET status        = :status,
           attempts      = attempts + 1,
           last_error    = :error,
           next_retry_at = :next_retry_at,
           claimed_by    = NULL,
           lease_until   = NULL,
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

# RAWG 的真实约束在**密钥池**（配额按 key 计，不是按机器/源），所以要单独看池子
SELECT_POOL = text(
    """
    SELECT count(*) AS keys,
           coalesce(sum(remaining_this_month) FILTER (WHERE enabled), 0) AS remaining
    FROM rawg_key_status
    """
)

# 卡住的任务：租约到期但状态未推进——用于诊断「是不是有 worker 崩了」
SELECT_STALE_LEASES = text(
    """
    SELECT claimed_by, count(*)
    FROM fetch_tasks
    WHERE claimed_by IS NOT NULL AND lease_until <= now()
    GROUP BY claimed_by ORDER BY 2 DESC
    """
)

# 释放本 worker 尚未回填的租约（dry-run 后收尾用）
RELEASE_LEASE = text(
    """
    UPDATE fetch_tasks
       SET claimed_by = NULL, lease_until = NULL, updated_at = now()
     WHERE claimed_by = :worker
    """
)

# 剔除「无成就」游戏的剩余任务。
# 为什么需要：项目的总体是「**带 Steam 成就的**游戏」，而商店搜索的
# category2=22 过滤存在误放（实测把 Train Simulator 的涂装包、Friend's Pass
# 这类无成就条目也放进来）。而 appdetails.type 分不出来（它们全是 'game'）——
# 唯一可靠的判据是**有没有成就数据**：global_ach 对无成就 appid 返回 403，
# 我们把它归一成 empty（见 crawler/steam_api.py）。
# 一旦确认无成就，其余 5 个源的任务就没有意义了，继续抓纯属浪费——
# 尤其是 RAWG，每次匹配要花掉 2~5 次月度配额。
PRUNE_NO_ACHIEVEMENT = text(
    """
    WITH victims AS (
        SELECT t.appid, t.source
        FROM fetch_tasks t
        WHERE t.source <> 'global_ach'
          AND t.status IN ('pending', 'error')
          AND EXISTS (
              SELECT 1 FROM fetch_tasks q
              WHERE q.appid = t.appid
                AND q.source = 'global_ach'
                AND q.status = 'empty'
          )
        LIMIT :limit
    )
    UPDATE fetch_tasks f
       SET status        = 'skipped',
           last_error    = :reason,
           claimed_by    = NULL,
           lease_until   = NULL,
           updated_at    = now()
      FROM victims v
     WHERE f.appid = v.appid AND f.source = v.source
    RETURNING f.appid
    """
)

PRUNE_REASON = "该游戏无成就数据（global_ach 403），按「带成就的游戏」总体口径剔除"

# 单个游戏：确认无成就后立刻取消它的兄弟任务
PRUNE_SIBLINGS = text(
    """
    UPDATE fetch_tasks
       SET status        = 'skipped',
           last_error    = :reason,
           claimed_by    = NULL,
           lease_until   = NULL,
           updated_at    = now()
     WHERE appid = :appid
       AND source <> 'global_ach'
       AND status IN ('pending', 'error')
    RETURNING appid
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


def _priority_of(source: str) -> int:
    """源的抓取优先级（来自 registry，已由 tests/test_registry.py 断言与库里一致）。"""
    spec = SOURCES.get(source)
    return spec.priority if spec else 100


def claim(
    conn: Any,
    source: str | None = None,
    limit: int = CLAIM_BATCH,
    exclude: set[str] | None = None,
    appid: int | None = None,
    worker: str = WORKER_ID,
    lease_sec: int = LEASE_SEC,
) -> list[tuple[int, str]]:
    """**原子抢占**一批任务并写上租约，返回 (appid, source) 列表（已按处理顺序排好）。

    选任务与占租约在一条语句里完成，配 ``FOR UPDATE SKIP LOCKED``，所以多台机器
    同时调用不会拿到同一条。抢不到就返回空列表（说明没活干了或全被别人抢走）。

    ⚠️ **返回顺序必须在 Python 侧再排一次**：SQL 里 ``UPDATE ... WHERE ... IN (SELECT
    ... ORDER BY ...) ... RETURNING`` 的那个 ``ORDER BY`` 只决定**选哪几行**（配合
    LIMIT），**不决定 RETURNING 吐出的顺序**——PostgreSQL 不保证它，实测按物理顺序
    返回（也就是物化时的插入顺序）。曾经因此让「无成就就剔除其余」的优化失效过一次：
    任务按字母序跑，``rawg`` 在 ``global_ach`` 之前就被跑了（2026-09-17）。

    Args:
        conn: 已开启事务的连接。
        source: 只抢某个源；None 表示所有源。
        limit: 本次最多抢多少条。
        exclude: 要跳过的源集合（如配额已耗尽的源），在 SQL 里就排除掉。
        appid: 只抢这一款游戏的任务（调试单个游戏用）。
        worker: worker 标识，写进 ``claimed_by`` 便于排查。
        lease_sec: 租约时长（秒），到期后别的 worker 可重新抢。
    """
    rows = conn.execute(
        CLAIM_TASKS,
        {
            "source": source,
            "n": limit,
            "worker": worker,
            "lease_sec": lease_sec,
            "appid": appid,
            "exclude": sorted(exclude) if exclude else None,
        },
    ).all()
    claimed = [(int(r[0]), str(r[1])) for r in rows]
    # 同游戏内按优先级跑：global_ach 早于 rawg，才能靠剔除省下最贵的源
    claimed.sort(key=lambda pair: (pair[0], _priority_of(pair[1])))
    return claimed


def quota_exhausted(conn: Any) -> set[str]:
    """配额已耗尽的源集合。

    两个判断来源：
    - ``sources`` 表的日限/月限（如 SteamSpy 自设的 1000/天）
    - **RAWG 的密钥池**：它的真实约束是「所有 key 的月余额合计」，不是
      ``sources.monthly_quota`` 那个 20000（那是**单个 key** 的额度）。
      池子里有 key 时以池子为准；池子为空（还没注册 key，走 .env 单 key 模式）
      则不作干预，回落到 ``sources`` 的判断。
    """
    blocked = {str(r[0]) for r in conn.execute(SELECT_EXHAUSTED_QUOTA).all()}
    pool = conn.execute(SELECT_POOL).first()
    if pool and int(pool[0]) > 0:
        if int(pool[1]) > 0:
            blocked.discard("rawg")
        else:
            blocked.add("rawg")
            logger.warning("RAWG 密钥池本月额度已用尽，本轮跳过该源")
    return blocked


def prune_no_achievement_siblings(conn: Any, appid: int) -> int:
    """取消某游戏剩余的任务（确认它无成就之后）。返回取消的行数。

    在 ``global_ach`` 判为 ``empty`` 后立刻调用：既然这游戏根本没有成就，它不可能
    进 Q1/Q2（依赖成就完成率），继续抓其余源纯属浪费——RAWG 尤其贵。
    """
    rows = conn.execute(
        PRUNE_SIBLINGS, {"appid": appid, "reason": PRUNE_REASON}
    ).all()
    return len(rows)


def prune_no_achievement_batch(engine: Engine, limit: int = 20000) -> int:
    """批量剔除：把所有「global_ach 已判 empty」游戏的剩余任务取消。返回行数。

    用于「appdetails/global_ach 已经跑过一轮、才补上这条规则」的历史数据清理。
    分批 UPDATE，避免对共享云库一次性锁太多行。

    Args:
        engine: SQLAlchemy Engine。
        limit: 单次最多处理多少行；多跑几次即可清完。
    """
    total = 0
    while True:
        with engine.begin() as conn:
            rows = conn.execute(
                PRUNE_NO_ACHIEVEMENT, {"limit": limit, "reason": PRUNE_REASON}
            ).all()
        if not rows:
            return total
        total += len(rows)
        logger.info("本轮剔除 %d 行，累计 %d", len(rows), total)
        if len(rows) < limit:
            return total


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
    appid: int | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    exclude: set[str] | None = None,
) -> dict[str, int]:
    """主循环：反复抢占任务并回填，直到没得抢（或达到 limit）。

    **多机并行安全**：抢占是原子的（见 :func:`claim`），同一台或多台机器同时跑这个
    函数不会重复抓同一条任务。配合共享 Postgres，加机器就能线性提高吞吐。

    **不碰 DDL**：启动时只校验库已初始化（``ensure_ready``），不会执行
    ``schema.sql``。要建表请显式跑 ``uv run python -m cleaning.db init``。
    这样多机同时启动不会争 ``DROP VIEW`` / ``CREATE VIEW`` 的锁，也不会有哪个
    命令有机会顺手改掉共享库的结构。

    Args:
        engine: SQLAlchemy Engine（多机时指向同一个共享库）。
        source: 只跑某个源；None 表示所有源。
        appid: 只跑这一款游戏的所有源（调试用，看单个游戏的全流程）。
        limit: 最多处理多少个任务；None 表示不限（跑到抢不到为止）。
        dry_run: 只报告还要抓什么，不发请求、不写库。
        exclude: 跳过的源集合（CLI ``--exclude steamspy``）。用在源**临时不可用**时
            （如实测 2026-09-22 SteamSpy 整站开 Cloudflare challenge），先把该源
            挂起跑其他源，恢复后去掉参数即可，任务不会丢。

    Returns:
        各状态计数 ``{"ok": n, "empty": n, ...}``。
    """
    ensure_ready(engine)
    extra_exclude = set(exclude or ())
    if extra_exclude:
        logger.warning("本轮跳过源：%s", ", ".join(sorted(extra_exclude)))
    recorder = UsageRecorder()
    set_call_recorder(recorder)
    # RAWG 的 key 来源分两种模式，**必须按池子是否为空来选**：
    #   池子非空 → 从共享池原子取用（每次真实请求消耗一次并记账）
    #   池子为空 → 不注入 provider，回落到 .env 的单 key（单机开发场景）
    # 无条件注入会让空池上的 reserve_key 返回 None，把 .env 的 key 一起废掉。
    pool = pool_size(engine)
    if pool:
        rawg_module.set_key_provider(lambda: reserve_key(engine))
        logger.info("RAWG 使用共享密钥池（%d 个 key）", pool)
    else:
        logger.info("RAWG 密钥池为空，回落到 .env 的单 key")
    stats: Counter[str] = Counter()
    logger.info("worker=%s 启动（lease=%ss）", WORKER_ID, LEASE_SEC)

    done = 0
    try:
        while True:
            if limit is not None and done >= limit:
                break
            batch_size = CLAIM_BATCH if limit is None else min(
                CLAIM_BATCH, limit - done
            )
            # 抢占在一个独立短事务里提交：租约必须先落库，别的机器才会让开
            with engine.begin() as conn:
                blocked = quota_exhausted(conn) | extra_exclude
                rows = claim(conn, source, batch_size, exclude=blocked, appid=appid)
            if not rows:
                if blocked:
                    logger.warning(
                        "以下源配额已用尽、已跳过：%s", ", ".join(sorted(blocked))
                    )
                logger.info("抢不到任务了，结束")
                break

            pruned_in_batch: set[int] = set()
            # ⚠️ 循环变量**不能**叫 appid/source——那会遮蔽本函数的同名参数，
            # 下一轮 claim(conn, ..., appid=appid) 就会拿着「上一批最后一个任务的
            # appid」当过滤器，worker 表现为「每批 20 个之后永远抢不到」（2026-09-18
            # 在 100 款试跑时踩到：claim 拿数 20→4→0，实为 appid 过滤越缩越窄）。
            for task_appid, task_source in rows:
                if dry_run:
                    logger.info("[dry-run] 待抓 appid=%s source=%s", task_appid, task_source)
                    stats["dry_run"] += 1
                    done += 1
                    continue
                # 同一批里如果前面已判定该游戏无成就，剩下的任务就别跑了。
                # 光改库里的 status 不够——这批任务是**开始前一次性抢下**的，
                # 内存里的待办列表不会自动跟着变（2026-09-17 踩到：rawg 照样跑了）。
                if task_appid in pruned_in_batch:
                    logger.debug("跳过已被剔除的游戏：appid=%s source=%s", task_appid, task_source)
                    continue
                # 每个任务一个短事务：网络请求可能耗时数秒，不该握着事务等
                with engine.begin() as conn:
                    # 护栏：run_source 本应自己吞掉异常并返回 ('error', msg)，
                    # 但万一它抛出来了，绝不能让整个 worker 崩掉——那会让任务永远
                    # 停在 pending、进度无法解释。这里兜成 error 走正常退避。
                    try:
                        with conn.begin_nested():
                            task_status, err = run_source(conn, task_appid, task_source)
                    except Exception as exc:  # noqa: BLE001
                        task_status, err = "error", f"未捕获异常：{exc}"[:500]
                        logger.exception(
                            "run_source 抛出未捕获异常：appid=%s source=%s",
                            task_appid,
                            task_source,
                        )
                    attempts_after = (
                        conn.execute(
                            text(
                                "SELECT attempts + 1 FROM fetch_tasks"
                                " WHERE appid = :a AND source = :s"
                            ),
                            {"a": task_appid, "s": task_source},
                        ).scalar()
                        or 1
                    )
                    complete(conn, task_appid, task_source, task_status, err, int(attempts_after))
                    # 一旦确认这个游戏没有成就，立刻取消它剩下的任务——
                    # 它进不了 Q1/Q2（两者都依赖成就完成率），继续抓纯属浪费配额
                    if task_source == "global_ach" and task_status == "empty":
                        pruned = prune_no_achievement_siblings(conn, task_appid)
                        if pruned:
                            pruned_in_batch.add(task_appid)
                            stats["pruned"] += pruned
                            logger.info(
                                "appid=%s 无成就 → 取消其余 %d 个任务", task_appid, pruned
                            )
                    flush_usage(conn, recorder)
                stats[task_status] += 1
                done += 1
                logger.info(
                    "[%d] appid=%s %s -> %s%s",
                    done,
                    task_appid,
                    task_source,
                    task_status,
                    f"（{err}）" if err else "",
                )
                if limit is not None and done >= limit:
                    break
    finally:
        set_call_recorder(None)
        rawg_module.set_key_provider(None)
        if not dry_run:
            with engine.begin() as conn:
                flush_usage(conn, recorder)
        else:
            # dry-run 只是为了看「还要抓什么」，不该把租约留在库里 5 分钟、
            # 让真正的 worker 干等——所以立刻释放本次抢到的租约
            with engine.begin() as conn:
                conn.execute(
                    RELEASE_LEASE, {"worker": WORKER_ID}
                )

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
    parser.add_argument(
        "--appid", type=int, default=None,
        help="只跑这一款游戏的所有源（调试单个游戏的全流程）",
    )
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少个任务")
    parser.add_argument(
        "--exclude", default=None,
        help="跳过的源，逗号分隔（如 --exclude steamspy）。"
             "用于源临时不可用时挂起它跑其他源，任务不丢、不耗重试次数",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只看还要抓什么，不发请求不写库"
    )
    parser.add_argument(
        "--progress", action="store_true", help="打印进度后退出"
    )
    parser.add_argument(
        "--prune", action="store_true",
        help="批量剔除：取消所有「global_ach 已判无成就」游戏的剩余任务，然后退出。"
             "用于 global_ach 已经跑过一轮、才补上这条规则的历史数据清理",
    )
    args = parser.parse_args()

    engine = get_engine()
    if args.progress:
        print_progress(engine)
        sys.exit(0)
    if args.prune:
        ensure_ready(engine)
        n = prune_no_achievement_batch(engine)
        print(f"已取消「无成就」游戏的剩余任务 {n:,} 行")
        print_progress(engine)
        sys.exit(0)

    try:
        stats = run(
            engine,
            source=args.source,
            appid=args.appid,
            limit=args.limit,
            dry_run=args.dry_run,
            exclude={s.strip() for s in args.exclude.split(",")} if args.exclude else None,
        )
    except RuntimeError as exc:
        # ensure_ready 的报错要原样透出——它会直接告诉你该跑哪条命令
        print(f"\n✗ {exc}", file=sys.stderr)
        sys.exit(1)
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
