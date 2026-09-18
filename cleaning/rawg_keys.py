"""cleaning.rawg_keys — RAWG 密钥池：注册、查余额、按 key 原子取用

**为什么需要它**：RAWG 的 20,000 次/月是**绑定 API key** 的配额，不是按机器、也不是
按 IP。所以「加机器」对 RAWG 一点用都没有——要扩容只能增加 key。多个 key 放在
**共享库**里（而不是各机器本地 `.env`），才能让所有机器看到同一份余额并协调取用；
否则 N 台机器会各自以为额度是满的。

用法::

    # 注册（每人注册自己的 RAWG 账号后，把 key 交给一个人统一入库）
    uv run python -m cleaning.rawg_keys add --key <KEY> --label 张三

    # 看每个 key 的本月余额（不暴露 key 明文）
    uv run python -m cleaning.rawg_keys list

    # 停用某个已超额的 key
    uv run python -m cleaning.rawg_keys disable --key-id 3

取用接口是 :func:`reserve_key`：worker 把 ``crawler.rawg.set_key_provider`` 指向它，
每次真实请求前**原子地**挑一个有余额的 key 并把计数 +1。

⚠️ RAWG 条款提醒（<https://rawg.io/apidocs>）：免费档限**非商业用途**，
且要求在使用数据的页面加 RAWG 回链。本项目是课程项目，符合非商业；回链要求在
最终报告/展示页里要落实。
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy import Engine, text

from cleaning.db import ensure_ready, get_engine

logger = logging.getLogger(__name__)

UPSERT_KEY = text(
    """
    INSERT INTO rawg_keys (api_key, label, monthly_quota, note)
    VALUES (:api_key, :label, :quota, :note)
    ON CONFLICT (api_key) DO UPDATE SET
        label         = COALESCE(EXCLUDED.label, rawg_keys.label),
        monthly_quota = EXCLUDED.monthly_quota,
        note          = COALESCE(EXCLUDED.note, rawg_keys.note),
        enabled       = true
    RETURNING key_id
    """
)

# 原子取用：挑一个「本月余额 > 0」的 key 并把当日计数 +1，一步完成。
# 不追求「锁住 key 直到请求结束」——多机并发下两台机器偶尔拿到同一个 key 也无害
# （各自 +1 计数仍正确），只有在余额恰好剩 1 时可能轻微超出，可接受。
RESERVE_KEY = text(
    """
    WITH usage AS (
        SELECT key_id, sum(requests) AS used
        FROM rawg_key_usage
        WHERE date_trunc('month', day) = date_trunc('month', current_date)
        GROUP BY key_id
    ),
    picked AS (
        SELECT k.key_id
        FROM rawg_keys k
        LEFT JOIN usage u ON u.key_id = k.key_id
        WHERE k.enabled
          AND k.monthly_quota - coalesce(u.used, 0) > 0
        ORDER BY k.monthly_quota - coalesce(u.used, 0) DESC, k.key_id
        LIMIT 1
    )
    INSERT INTO rawg_key_usage (key_id, day, requests)
    SELECT key_id, current_date, 1 FROM picked
    ON CONFLICT (key_id, day) DO UPDATE
       SET requests = rawg_key_usage.requests + 1
    RETURNING key_id
    """
)

SELECT_KEY_BY_ID = text("SELECT api_key FROM rawg_keys WHERE key_id = :key_id")
SELECT_STATUS = text(
    """
    SELECT key_id, label, enabled, key_hint, monthly_quota,
           used_this_month, remaining_this_month, used_today
    FROM rawg_key_status ORDER BY key_id
    """
)
DISABLE_KEY = text("UPDATE rawg_keys SET enabled = false WHERE key_id = :key_id")
ENABLE_KEY = text("UPDATE rawg_keys SET enabled = true WHERE key_id = :key_id")


def register_key(
    engine: Engine,
    api_key: str,
    label: str | None = None,
    quota: int = 20000,
    note: str | None = None,
) -> int:
    """注册（或更新）一个 RAWG key，返回 key_id。

    同一个 key 重复注册不会报错，只会更新标签/配额并重新启用。

    Args:
        engine: SQLAlchemy Engine。
        api_key: RAWG API key 明文。
        label: 归属标识，如「张三的 key」。
        quota: 该 key 的月配额，默认 20000（RAWG 免费档官方口径）。
        note: 备注（注册邮箱等）。
    """
    ensure_ready(engine)
    with engine.begin() as conn:
        return int(
            conn.execute(
                UPSERT_KEY,
                {"api_key": api_key.strip(), "label": label, "quota": quota, "note": note},
            ).scalar_one()
        )


def pool_size(engine: Engine) -> int:
    """密钥池里的 key 总数（含已停用的）。

    worker 用它决定「是否启用密钥池模式」：池子为空时应当回落到 ``.env`` 的
    单 key，而不是把 RAWG 整个停掉（2026-09-17 踩到：无条件注入 provider 会让
    ``reserve_key`` 在空池上返回 None，于是连 .env 的单 key 都用不了）。
    """
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM rawg_keys")).scalar() or 0)


def total_remaining(engine: Engine) -> int:
    """密钥池本月剩余额度合计（所有 enabled 的 key）。"""
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT coalesce(sum(remaining_this_month), 0)"
                    " FROM rawg_key_status WHERE enabled"
                )
            ).scalar()
            or 0
        )


def reserve_key(engine: Engine) -> str | None:
    """原子取一个还有本月余额的 key 并计数 +1；池子用尽返回 None。

    worker 把本函数包成 ``crawler.rawg.set_key_provider(provider)`` 的 provider。
    用**独立的短事务**（不共用 worker 处理任务的那个事务）：这样即使外层任务事务
    回滚，配额也已经记账——对配额而言保守取用比漏记更安全。

    Returns:
        API key 明文；池子里没有可用 key（全用满 / 全停用）时返回 None。
    """
    with engine.begin() as conn:
        row = conn.execute(RESERVE_KEY).first()
        if row is None:
            return None
        return conn.execute(
            SELECT_KEY_BY_ID, {"key_id": row[0]}
        ).scalar_one()


def list_keys(engine: Engine) -> list[dict[str, Any]]:
    """列出密钥池状态（**不含 key 明文**，只有尾 4 位）。"""
    with engine.connect() as conn:
        rows = conn.execute(SELECT_STATUS).all()
        keys = [
            "key_id", "label", "enabled", "key_hint", "monthly_quota",
            "used_this_month", "remaining_this_month", "used_today",
        ]
        return [dict(zip(keys, r)) for r in rows]


def set_enabled(engine: Engine, key_id: int, enabled: bool) -> int:
    """启用/停用某个 key，返回受影响行数。"""
    with engine.begin() as conn:
        stmt = ENABLE_KEY if enabled else DISABLE_KEY
        return int(conn.execute(stmt, {"key_id": key_id}).rowcount or 0)


def main() -> None:
    """CLI：add / list / enable / disable。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="RAWG 密钥池管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="注册或更新一个 key")
    p_add.add_argument("--key", required=True, help="RAWG API key 明文")
    p_add.add_argument("--label", default=None, help="归属标识，如「张三的 key」")
    p_add.add_argument("--quota", type=int, default=20000, help="月配额，默认 20000")
    p_add.add_argument("--note", default=None, help="备注（注册邮箱等）")

    sub.add_parser("list", help="列出密钥池状态与余额")

    for name in ("enable", "disable"):
        p = sub.add_parser(name, help=f"{name} 某个 key")
        p.add_argument("--key-id", type=int, required=True)

    args = parser.parse_args()
    engine = get_engine()

    if args.cmd == "add":
        kid = register_key(engine, args.key, args.label, args.quota, args.note)
        print(f"已注册 key_id={kid}（label={args.label}，配额 {args.quota}/月）")
        print(f"密钥池本月剩余合计：{total_remaining(engine)}")
        return

    if args.cmd == "list":
        rows = list_keys(engine)
        if not rows:
            print("密钥池为空。用 `add --key <KEY> --label <人>` 注册。")
            return
        header = f"{'id':>3}  {'标识':<14}{'启用':<6}{'密钥':<8}{'配额':>7}{'本月已用':>9}{'剩余':>8}{'今日':>6}"
        print(header)
        print("-" * len(header))
        for r in rows:
            print(
                f"{r['key_id']:>3}  {str(r['label'] or '-'):<14}"
                f"{('是' if r['enabled'] else '否'):<6}{r['key_hint']:<8}"
                f"{r['monthly_quota']:>7}{r['used_this_month']:>9}"
                f"{r['remaining_this_month']:>8}{r['used_today']:>6}"
            )
        print(f"\n本月剩余合计（仅启用中的 key）：{total_remaining(engine)}")
        return

    changed = set_enabled(engine, args.key_id, args.cmd == "enable")
    print(f"{args.cmd} key_id={args.key_id}：影响 {changed} 行" if changed else "没找到该 key_id")


if __name__ == "__main__":
    main()
