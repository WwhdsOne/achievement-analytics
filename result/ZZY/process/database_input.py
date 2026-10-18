"""从小组 PostgreSQL 只读提取，自动在个人 runtime 内缓存版本。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from time import monotonic

from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

REPOSITORY = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedInput:
    data_root: Path
    snapshot_version: str
    graph_version: str | None
    provenance: dict


def readonly_engine(env_file: Path | None = None):
    """只读加载现有 POSTGRES_*；环境变量优先，不写配置或打印 DSN。"""
    file = Path(env_file) if env_file is not None else REPOSITORY / ".env"
    if env_file is not None and not file.is_file():
        raise ValueError("--env-file 指定的配置文件不存在")
    try:
        config = dotenv_values(file, interpolate=False) if file.is_file() else {}
    except (OSError, UnicodeError):
        raise ValueError("无法读取数据库配置文件，请检查权限与 UTF-8 编码") from None

    def value(name: str) -> str:
        return os.environ.get(name, config.get(name) or "")

    required = (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    missing = [name for name in required if not value(name).strip()]
    if missing:
        raise ValueError(
            "缺少数据库配置："
            + ", ".join(missing)
            + "。请使用小组仓库根 .env 或 --env-file；凭据不上传 GitHub"
        )
    try:
        port = int(value("POSTGRES_PORT"))
    except ValueError:
        raise ValueError("POSTGRES_PORT 必须是 1–65535 的整数") from None
    if not 1 <= port <= 65535:
        raise ValueError("POSTGRES_PORT 必须是 1–65535 的整数")
    sslmode = value("POSTGRES_SSLMODE").strip()
    if sslmode not in (
        "",
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    ):
        raise ValueError("POSTGRES_SSLMODE 配置无效")
    url = URL.create(
        "postgresql+psycopg",
        username=value("POSTGRES_USER"),
        password=value("POSTGRES_PASSWORD"),
        host=value("POSTGRES_HOST"),
        port=port,
        database=value("POSTGRES_DB"),
        query={"sslmode": sslmode} if sslmode else {},
    )
    return create_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 10,
            "options": "-c default_transaction_read_only=on",
        },
    )


def prepare_database(
    cache_root: Path, *, env_file: Path | None = None, with_graph: bool = True
) -> PreparedInput:
    """每次启动重新读库；内容相同可复用已核验图谱，读库失败绝不回退旧缓存。"""
    from modeling.recommendation.snapshot import extract_rows, save_snapshot
    from modeling.recommendation.knowledge_graph import build_graph, validate_appids

    started = monotonic()
    logger.info("正在从小组数据库只读提取；不会写数据库，也不会自动使用旧缓存")
    engine = readonly_engine(env_file)
    try:
        rows, extraction = extract_rows(engine)
    except SQLAlchemyError:
        raise ValueError(
            "数据库只读提取失败：请检查网络、POSTGRES_* 配置、只读查询权限及表结构；未使用旧缓存"
        ) from None
    finally:
        engine.dispose()
    if not rows:
        raise ValueError("数据库未返回符合发售日期口径的游戏，停止启动；未使用旧缓存")
    validate_appids(rows)
    root = Path(cache_root)
    metadata = save_snapshot(rows, extraction, root / "snapshots")
    snapshot_version = metadata["version"]
    graph_version = None
    if with_graph:
        logger.info("正在构建或完整核验本次数据的图谱缓存")
        graph = build_graph(
            snapshot_version, snapshots=root / "snapshots", folder=root / "kg"
        )
        graph_version = graph["version"]
    provenance = {
        "source": "group_database",
        "database_access": True,
        "refresh_policy": "read_once_at_startup_restart_to_refresh",
        "started_at": extraction["started_at"],
        "finished_at": extraction["finished_at"],
        "database_settings": extraction["database_settings"],
        "query_sha256": extraction["query_sha256"],
        "snapshot_games": len(rows),
        "snapshot_version": snapshot_version,
        "graph_version": graph_version,
        "preparation_seconds": round(monotonic() - started, 3),
        "fallback_to_old_cache": False,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "latest-startup.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    logger.info("只读提取及本地准备完成：%s 款游戏；数据库连接已释放", len(rows))
    return PreparedInput(root, snapshot_version, graph_version, provenance)
