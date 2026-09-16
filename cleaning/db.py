"""cleaning.db — PostgreSQL 连接与 schema 应用

本地开发库跑在 Docker（见项目根的 ``docker-compose.yml``）。连接参数优先读
``.env``，缺省值与 docker-compose.yml 的默认值保持一致，开箱即用。

用法::

    from cleaning.db import get_engine, apply_schema
    engine = get_engine()
    apply_schema(engine)
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine

from crawler.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def get_dsn() -> str:
    """构造 SQLAlchemy DSN（psycopg3 驱动）。

    Returns:
        形如 ``postgresql+psycopg://user:pw@host:port/db``。
    """
    return (
        f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


def get_engine() -> Engine:
    """建 SQLAlchemy Engine。

    建模时可直接 ::

        pd.read_sql("SELECT * FROM games_full", get_engine())
    """
    return create_engine(get_dsn(), future=True, pool_pre_ping=True)


def apply_schema(engine: Engine) -> None:
    """执行 cleaning/schema.sql（全部语句幂等，可反复跑）。

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
