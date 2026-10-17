"""WWH分析的数据读取适配；不建表、不迁移、不读密钥、不写SQLite。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterator

TASK_ROOT = Path(__file__).resolve().parent.parent
PERSON_ROOT = TASK_ROOT.parent.parent
DEFAULT_DB = PERSON_ROOT / "NewDB" / "wwh5.sqlite3"
LEGACY_DB = PERSON_ROOT / "database" / "achievements.sqlite"


def now() -> str:
    """Return the current UTC audit timestamp."""
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    """Preserve the WWH canonical JSON format for snapshots and outputs."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def numeric_usage(value: Any) -> dict[str, int | float]:
    """Copy WWH's finite numeric usage filter without provider access."""
    if not isinstance(value, dict):
        return {}
    return {
        key: count for key, count in value.items()
        if isinstance(key, str) and not isinstance(count, bool)
        and isinstance(count, (int, float))
        and (isinstance(count, int) or math.isfinite(count))
    }


def owned_path(path: str | Path) -> Path:
    """Restrict every baseline output to analysis/T0Pre."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(TASK_ROOT):
        raise ValueError("T0Pre输出必须位于 result/LYX/analysis/T0Pre 内")
    return resolved


def database_path(path: str | Path) -> Path:
    """Resolve an existing input database within LYX, without creating it."""
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_relative_to(PERSON_ROOT) or not resolved.is_file():
        raise ValueError("只读输入数据库必须是 result/LYX 内的现有文件")
    return resolved


@contextmanager
def connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open one consistent read-only transaction; never apply schema or commit writes."""
    path = database_path(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        required = {"metadata", "games", "achievements", "game_labels", "achievement_labels", "story_labels", "model_calls", "analysis_runs"}
        actual = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= actual:
            raise ValueError("输入不是WWH第5项快照库；不能使用LYX六表库代替")
        yield conn
    finally:
        conn.rollback()
        conn.close()


def metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read WWH snapshot metadata with the existing schema unchanged."""
    return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM metadata")}


def load_games(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Read all WWH game payloads in frozen ranking order."""
    return [json.loads(r[0]) for r in conn.execute("SELECT payload FROM games ORDER BY frame_rank")]


def blocked_reason(game: dict[str, Any]) -> str | None:
    """Preserve WWH source-quality exclusions without adding semantic review gates."""
    if game.get("mapping_unresolved"):
        return "unresolved achievement mapping"
    achievements = game.get("achievements", [])
    if not achievements:
        return "no achievements"
    if any(not a.get("display_name", "").strip() for a in achievements):
        return "missing display names"
    return None


def fingerprint(path: str | Path) -> dict[str, Any]:
    """Hash an existing LYX database for before/after verification."""
    path = database_path(path)
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    stat = path.stat()
    return {"path": str(path), "sha256": sha.hexdigest(), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def write_json(path: str | Path, value: Any) -> None:
    """Write only JSON result files under the analysis output boundary."""
    path = owned_path(path)
    if path.suffix.lower() != ".json":
        raise ValueError("此输出接口仅接受JSON结果文件")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
