"""Read-only PostgreSQL export and isolated, versioned SQLite persistence."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from . import config

TASK_ROOT = config.TASK_ROOT
DEFAULT_DB = TASK_ROOT / "data" / "wwh5.sqlite3"  # 本地缓存，见 5/data/（Git 忽略）
SCHEMA = TASK_ROOT / "schema.sql"
EXPORT_VERSION = "wwh5-export-v1"
RANK_SQL = """
SELECT g.appid, g.name_en, g.name_zh, a.type, a.release_date,
       a.price_cents, a.is_free, a.valve_genres, a.valve_categories,
       a.developers, a.publishers, a.fetched_at AS appdetails_fetched_at,
       s.positive, s.negative, (s.positive::bigint+s.negative::bigint) AS review_count,
       s.fetched_at AS steamspy_fetched_at
FROM games g JOIN steam_appdetails a USING(appid) JOIN steamspy_games s USING(appid)
WHERE a.type='game' AND a.release_date < DATE '2026-01-01'
  AND s.positive IS NOT NULL AND s.negative IS NOT NULL
  AND s.positive >= 0 AND s.negative >= 0
ORDER BY review_count DESC, g.appid ASC LIMIT :limit
"""


def now() -> str:
    """UTC timestamp for local audit records."""
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    """Serialize reproducibly without losing source timestamps/decimals."""

    def convert(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        raise TypeError(f"Unsupported snapshot type: {type(obj).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=convert,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    """SHA256 of a canonical input payload."""
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def numeric_usage(value: Any) -> dict[str, int | float]:
    """Normalize optional provider usage to finite numeric fields, rejecting booleans."""
    if not isinstance(value, dict):
        return {}
    return {
        key: count
        for key, count in value.items()
        if isinstance(key, str)
        and not isinstance(count, bool)
        and isinstance(count, (int, float))
        and (isinstance(count, int) or math.isfinite(count))
    }


def rank_games(rows: list[dict], limit: int = 1000) -> list[dict]:
    """Rank eligible games BEFORE mapping or RAWG quality filtering."""
    if limit < 1:
        raise ValueError("limit must be positive")
    valid = []
    for row in rows:
        p, n = row.get("positive"), row.get("negative")
        release = row.get("release_date")
        if (
            row.get("type") != "game"
            or not release
            or str(release)[:10] >= "2026-01-01"
        ):
            continue
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float, Decimal))
            or not math.isfinite(float(v))
            or v < 0
            for v in (p, n)
        ):
            continue
        valid.append({**row, "review_count": int(p + n)})
    return sorted(valid, key=lambda r: (-r["review_count"], r["appid"]))[:limit]


def owned_path(path: str | Path) -> Path:
    """Reject persistent WWH outputs outside the personal directory, including symlinks."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(config.PERSON_ROOT):
        raise ValueError("WWH outputs must stay under result/WWH")
    return resolved


@contextmanager
def connect(
    path: str | Path, *, check_same_thread: bool = True
) -> Iterator[sqlite3.Connection]:
    """Open SQLite using the single local schema; commit/rollback atomically.

    ``check_same_thread=False`` 供标注阶段的多线程使用：那种场景下**所有**数据库访问
    都由调用方的锁串行化（见 ``deepseek.run_labeling`` 的 ``db_lock``），所以关掉
    sqlite3「连接只能在本线程用」的检查是安全的。默认 True，其他调用方行为不变。

    ⚠️ 关掉之后约束转移到调用方：**每次持锁必须 commit 或 rollback**，
    不能把未提交的事务带出临界区——否则别的线程提交时会连带提交它。
    """
    path = owned_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def metadata(conn: sqlite3.Connection) -> dict:
    """Read JSON metadata without any external connection."""
    return {
        r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM metadata")
    }


def put_metadata(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Write metadata within the caller's SQLite transaction."""
    conn.execute(
        "INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, canonical(value))
    )


def blocked_reason(game: dict) -> str | None:
    """Keep bad-quality games in the frame, but prevent unsafe model prompts."""
    if game.get("mapping_unresolved"):
        return "unresolved achievement mapping"
    achievements = game.get("achievements", [])
    if not achievements:
        return "no achievements"
    if any(not a.get("display_name", "").strip() for a in achievements):
        return "missing display names"
    return None


def import_snapshot(path: str | Path, games: list[dict], meta: dict) -> dict:
    """Atomically import a fixed frame, rejecting all overwrites of an existing version."""
    frozen = json.loads(canonical(games))
    built = {
        **meta,
        "input_sha256": digest(frozen),
        "export_version": EXPORT_VERSION,
        "exported_at": now(),
        "frame_count": len(frozen),
        "ranking_rule": "type=game; release<2026; positive+negative DESC, appid ASC",
    }
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if (
            metadata(conn).get("dataset_version")
            or conn.execute("SELECT count(*) FROM games").fetchone()[0]
        ):
            raise RuntimeError(
                "Snapshot already exists; choose a new --db for a new version"
            )
        for rank, game in enumerate(frozen, 1):
            count = game.get("review_count", game["positive"] + game["negative"])
            conn.execute(
                "INSERT INTO games VALUES (?,?,?,?,?)",
                (game["appid"], rank, count, blocked_reason(game), canonical(game)),
            )
            for a in game.get("achievements", []):
                conn.execute(
                    "INSERT INTO achievements VALUES (?,?,?,?,?)",
                    (
                        game["appid"],
                        str(a["local_id"]),
                        a["display_name"],
                        a.get("description"),
                        a["percent"],
                    ),
                )
        for key, value in built.items():
            put_metadata(conn, key, value)
    return built


def load_games(conn: sqlite3.Connection) -> list[dict]:
    """Return frozen source payloads in original frame ranking."""
    return [
        json.loads(row[0])
        for row in conn.execute("SELECT payload FROM games ORDER BY frame_rank")
    ]


def export_snapshot(
    path: str | Path = DEFAULT_DB, limit: int = 1000, dataset_version: str | None = None
) -> dict:
    """Export in one read-only repeatable-read PG transaction; never execute cloud DDL."""
    if limit < 1:
        raise ValueError("limit must be positive")
    with connect(path) as local:
        if metadata(local).get("dataset_version"):
            raise RuntimeError("Snapshot already exists; choose a new --db")
    url = URL.create(
        "postgresql+psycopg",
        username=config.DB_USER,
        password=config.DB_PASSWORD,
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
        query={"sslmode": config.DB_SSLMODE} if config.DB_SSLMODE else {},
    )
    engine = create_engine(
        url, connect_args={"connect_timeout": 10}, pool_pre_ping=True
    )
    queries = {"ranking": RANK_SQL}
    try:
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = '120s'"))
                games = [
                    dict(r)
                    for r in conn.execute(text(RANK_SQL), {"limit": limit}).mappings()
                ]
                if not games:
                    raise RuntimeError("No eligible games found")
                ids = [g["appid"] for g in games]
                by_id = {g["appid"]: g for g in games}
                for g in games:
                    g.update(
                        achievements=[],
                        tags=[],
                        rawg=None,
                        mapping_unresolved=False,
                        mapping_issue=None,
                        source_success_times={},
                    )
                sqls = {
                    "achievements": "SELECT appid, position, display_name, description, percent FROM achievements WHERE appid=ANY(:ids) ORDER BY appid,position",
                    "tags": "SELECT appid,source,tag,votes,kind FROM game_tags WHERE appid=ANY(:ids) ORDER BY appid,source,tag",
                    "rawg": "SELECT * FROM rawg_games WHERE appid=ANY(:ids)",
                    "mapping": "SELECT appid,reason,resolved,detected_at FROM mapping_issues WHERE appid=ANY(:ids)",
                    "success_times": "SELECT appid,source,max(fetched_at) AS fetched_at FROM ingest_log WHERE appid=ANY(:ids) AND status='ok' GROUP BY appid,source",
                }
                queries.update(sqls)
                for kind, sql in sqls.items():
                    for row in conn.execute(text(sql), {"ids": ids}).mappings():
                        item = dict(row)
                        g = by_id[item.pop("appid")]
                        if kind == "achievements":
                            item["local_id"] = str(item.pop("position"))
                            g["achievements"].append(item)
                        elif kind == "tags":
                            g["tags"].append(item)
                        elif kind == "rawg":
                            g["rawg"] = item
                        elif kind == "mapping":
                            g["mapping_issue"] = item
                            g["mapping_unresolved"] = not item["resolved"]
                        else:
                            g["source_success_times"][item["source"]] = item[
                                "fetched_at"
                            ]
    finally:
        engine.dispose()
    return import_snapshot(
        path,
        games,
        {
            "dataset_version": dataset_version or "wwh5-" + now(),
            "sql": queries,
            "requested_limit": limit,
            "source": "PostgreSQL read-only repeatable-read",
            "source_database": config.DB_NAME,
            "transaction_snapshot": "repeatable-read",
        },
    )


def status(path: str | Path = DEFAULT_DB) -> dict:
    """Summarize frame and local processing coverage without making network calls."""
    with connect(path) as conn:
        counts = {
            "frame": conn.execute("SELECT count(*) FROM games").fetchone()[0],
            "blocked": conn.execute(
                "SELECT count(*) FROM games WHERE blocked_reason IS NOT NULL"
            ).fetchone()[0],
            "labeled": conn.execute("SELECT count(*) FROM story_labels").fetchone()[0],
        }
        counts["pending"] = counts["frame"] - counts["blocked"] - counts["labeled"]
        counts["call_status"] = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT status,count(*) FROM model_calls GROUP BY status"
            )
        }
        counts["metadata"] = metadata(conn)
        return counts
