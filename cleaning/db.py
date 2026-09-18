"""cleaning.db — PostgreSQL 连接、schema 应用与就绪校验

连的是**共享云库**（`.env` 里的 ``POSTGRES_*``）：任务队列、配额账本与 RAWG
密钥池都在那里，多台机器的 worker 靠这个库协调抢占。

**DDL 只在这里发生，而且只在显式命令里**（2026-09-17 定的规矩）::

    uv run python -m cleaning.db init     # 唯一的建表入口，幂等

``worker`` / ``seed`` / ``rawg_keys`` 一律**不再**隐式执行 ``schema.sql``——
它们启动时只**校验**表在不在，不在就报明确错误。理由是 ``schema.sql`` 含
``DROP VIEW`` / ``CREATE VIEW``，隐式执行等于给了每个命令一个改共享库结构的机会，
而「加个参数就行」挡不住习惯性带上参数的人。

⚠️ 改 schema 前先在别处验证：直接对共享库试错会影响正在跑的队友。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import Engine, create_engine, text

from crawler.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_SSLMODE,
    DB_USER,
)

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

# 判定「库已初始化」的关键对象：核心表 + 靠 schema.sql 建出来的关键视图。
# 少一个就说明还没 init 过（或 init 失败）。
_REQUIRED_OBJECTS = ("games", "fetch_tasks", "sources", "ingest_progress")


def get_dsn() -> str:
    """构造 SQLAlchemy DSN（psycopg3 驱动）。

    ``POSTGRES_SSLMODE`` 有值时作为 query 参数附上——云数据库（如腾讯云 PG）
    通常强制 SSL，本机自建库可留空。

    Returns:
        形如 ``postgresql+psycopg://user:pw@host:port/db``，设置了 sslmode 时
        再追加 ``?sslmode=...``。
    """
    dsn = (
        f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    if DB_SSLMODE:
        dsn += f"?sslmode={DB_SSLMODE}"
    return dsn


def get_engine() -> Engine:
    """建 SQLAlchemy Engine。

    多机并行时各机器都连同一个库，所以连接池要能容忍连接被中间设备掐断
    （``pool_pre_ping``），并限制单机连接数避免 N 台机器把云库的连接数用满。

    建模时可直接 ::

        pd.read_sql("SELECT * FROM games_full", get_engine())
    """
    return create_engine(
        get_dsn(),
        future=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


def missing_objects(engine: Engine) -> list[str]:
    """返回缺失的关键表/视图名（空列表 = 库已就绪）。"""
    sql = text(
        """
        SELECT n FROM (
            SELECT table_name AS n FROM information_schema.tables
             WHERE table_schema = 'public'
            UNION ALL
            SELECT table_name AS n FROM information_schema.views
             WHERE table_schema = 'public'
        ) o WHERE n = ANY(:names)
        """
    )
    with engine.connect() as conn:
        found = {r[0] for r in conn.execute(sql, {"names": list(_REQUIRED_OBJECTS)})}
    return [n for n in _REQUIRED_OBJECTS if n not in found]


def ensure_ready(engine: Engine) -> None:
    """校验库已初始化；没初始化就报明确的错，而不是让后续语句零散地失败。

    Raises:
        RuntimeError: 有缺失的表/视图，错误信息里直接给出该跑哪条命令。
    """
    missing = missing_objects(engine)
    if missing:
        raise RuntimeError(
            f"数据库还没初始化（缺少 {', '.join(missing)}）。"
            f"请先执行一次：uv run python -m cleaning.db init"
        )


def apply_schema(engine: Engine) -> None:
    """执行 cleaning/schema.sql（全部语句幂等，可反复跑）。

    ⚠️ **只应由 ``python -m cleaning.db init`` 调用**，不要在 worker/seed 启动时
    隐式调用——理由见模块 docstring。

    用**原始 DBAPI 连接**执行，不走 SQLAlchemy 的参数绑定——否则 psycopg 的
    pyformat 会把 DDL 注释里的字面 ``%``（如「100% 完成」）当成占位符，报
    ``incomplete placeholder``（2026-09-15 实测踩到）。

    Raises:
        sqlalchemy.exc.SQLAlchemyError: 连不上库或 DDL 出错。
    """
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(sql)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    logger.info("schema 已应用：%s", SCHEMA_FILE.name)


def main() -> None:
    """CLI：``init`` 建表（唯一改 DDL 的入口）/ ``status`` 看库是否就绪。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="数据库初始化与就绪校验")
    parser.add_argument(
        "cmd", choices=("init", "status"),
        help="init=应用 schema.sql（幂等）；status=只检查是否已初始化",
    )
    args = parser.parse_args()

    engine = get_engine()
    if args.cmd == "init":
        apply_schema(engine)
        missing = missing_objects(engine)
        if missing:
            print(f"⚠ init 跑完了但仍缺少 {missing}，请检查 schema.sql")
            sys.exit(1)
        print("✓ 数据库已初始化（schema.sql 已应用，幂等）")
        return

    missing = missing_objects(engine)
    if missing:
        print(f"✗ 未初始化：缺少 {', '.join(missing)}")
        print("  请执行：uv run python -m cleaning.db init")
        sys.exit(1)
    print("✓ 数据库已就绪")


if __name__ == "__main__":
    main()
