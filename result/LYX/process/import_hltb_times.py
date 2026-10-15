"""按冻结1000 AppID只读提取HLTB时长，备份后原子迁移本地games_time到v4。"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
from uuid import uuid4

from import_snapshot import DEFAULT_APPIDS, load_selection, read_remote, save_json, utc_now
from local_database import (
    DEFAULT_DATABASE, SCHEMA, TABLES, WORKSPACE, connect_local, database_path,
    ensure_schema, table_counts, workspace_path,
)

TIME_FIELDS = ("main_hours", "extra_hours", "completionist_hours")
SOURCE_TABLE = "public.hltb_games"
SNAPSHOT_FORMAT = "lyx-hltb-time-snapshot-v1"
DEFAULT_RUNTIME = WORKSPACE / "process" / "runtime" / "hltb_import"
TIME_QUERY = (
    "SELECT appid,main_hours,extra_hours,completionist_hours FROM public.hltb_games "
    "WHERE appid=ANY(%s) ORDER BY appid"
)
COLUMN_QUERY = (
    "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
    "WHERE table_schema='public' AND table_name='hltb_games' ORDER BY ordinal_position"
)


def finite_hours(value: Any) -> float | None:
    """将来源NUMERIC转为非负有限SQLite REAL；保留NULL和有效零值。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("HLTB时长类型无效")
    try:
        number = Decimal(str(value))
        converted = float(number)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError("HLTB时长不是有效数值") from None
    if not number.is_finite() or number < 0 or not math.isfinite(converted):
        raise ValueError("HLTB时长必须是非负有限数")
    if number != 0 and converted == 0:
        raise ValueError("HLTB时长低于SQLite REAL可表达的精度")
    return converted


def validate_local(con: sqlite3.Connection, appids: list[int]) -> int:
    """只接受v3/v4六表库，且games与games_time精确覆盖冻结的1000 AppID。"""
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version not in (3, 4):
        raise ValueError("时长迁移仅接受本地schema版本3或4")
    ensure_schema(con, schema_version=version)
    expected = set(appids)
    for table in ("games", "games_time"):
        actual = {row[0] for row in con.execute(f'SELECT appid FROM "{table}"')}
        if actual != expected:
            raise ValueError(f"{table}的AppID集合与冻结1000清单不一致")
    return version


def snapshot_index(
    snapshot: dict[str, Any], appids: list[int], manifest_sha256: str,
) -> dict[int, tuple[float | None, float | None, float | None]]:
    """核验快照身份及全部来源数值；失败不被转换成缺数据或NULL。"""
    if not isinstance(snapshot, dict) or snapshot.get("format") != SNAPSHOT_FORMAT:
        raise ValueError("HLTB快照格式无效")
    if (snapshot.get("source_table") != SOURCE_TABLE
            or snapshot.get("transaction_read_only") != "on"
            or snapshot.get("appids") != appids
            or snapshot.get("manifest_sha256") != manifest_sha256):
        raise ValueError("HLTB快照来源、只读声明或冻结清单不一致")
    try:
        captured_at = datetime.fromisoformat(snapshot["read_at"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("HLTB快照读取时间无效") from None
    if captured_at.tzinfo is None:
        raise ValueError("HLTB快照读取时间必须包含时区")
    columns = snapshot.get("source_columns")
    if not isinstance(columns, list) or any(not isinstance(column, dict) for column in columns):
        raise ValueError("HLTB来源字段元数据无效")
    column_types = {column.get("column_name"): column.get("data_type") for column in columns}
    if len(column_types) != len(columns):
        raise ValueError("HLTB来源字段元数据重复")
    if column_types.get("appid") != "integer" or any(column_types.get(field) != "numeric" for field in TIME_FIELDS):
        raise ValueError("hltb_games缺少所需INTEGER/NUMERIC来源字段")
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("HLTB快照rows不是列表")
    allowed = set(appids)
    index: dict[int, tuple[float | None, float | None, float | None]] = {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"appid", *TIME_FIELDS}
                or type(row.get("appid")) is not int or row["appid"] not in allowed
                or row["appid"] in index):
            raise ValueError("HLTB来源AppID重复、越界或字段集合无效")
        index[row["appid"]] = tuple(finite_hours(row[field]) for field in TIME_FIELDS)
    expected_missing = [appid for appid in appids if appid not in index]
    if snapshot.get("missing_appids") != expected_missing:
        raise ValueError("HLTB快照的缺行清单与实际rows不一致")
    return index


def source_coverage(
    appids: list[int], index: dict[int, tuple[float | None, float | None, float | None]],
) -> dict[str, Any]:
    """分别统计匹配行、来源NULL、来源零值与完全缺行，不混淆缺失原因。"""
    return {
        "requested": len(appids), "matched_rows": len(index),
        "missing_rows": len(appids) - len(index),
        "missing_appids": [appid for appid in appids if appid not in index],
        "matched_all_times_null": sum(all(value is None for value in values) for values in index.values()),
        "fields": {
            field: {
                "non_null": sum(values[position] is not None for values in index.values()),
                "zero": sum(values[position] == 0 for values in index.values()),
                "source_null": sum(values[position] is None for values in index.values()),
                "missing_row_null": len(appids) - len(index),
                "local_null": sum(values[position] is None for values in index.values()) + len(appids) - len(index),
            }
            for position, field in enumerate(TIME_FIELDS)
        },
    }


def fetch_snapshot(database: Path, appids_path: Path = DEFAULT_APPIDS) -> dict[str, Any]:
    """在一个远端一致只读事务中读取字段元数据与1000 AppID，不按名称猜测。"""
    appids, manifest = load_selection(appids_path)
    with closing(connect_local(database)) as con:
        validate_local(con, appids)
    remote = read_remote({
        "source_columns": (COLUMN_QUERY, ()),
        "rows": (TIME_QUERY, (appids,)),
    })
    present = {row["appid"] for row in remote["rows"]}
    snapshot = {
        "format": SNAPSHOT_FORMAT, "source_table": SOURCE_TABLE,
        "manifest_sha256": manifest["appids_sha256"], "appids": appids,
        "source_query": TIME_QUERY, "source_columns": remote["source_columns"],
        "transaction_read_only": remote["transaction_read_only"],
        "read_at": remote["read_at"], "connection_attempts": remote["connection_attempts"],
        "rows": remote["rows"], "missing_appids": [appid for appid in appids if appid not in present],
    }
    snapshot_index(snapshot, appids, manifest["appids_sha256"])
    return snapshot


def _new_run(folder: Path | None) -> Path:
    target = workspace_path(folder or DEFAULT_RUNTIME / (utc_now().replace(":", "").replace("+", "_") + "-" + uuid4().hex[:8]))
    target.mkdir(parents=True, exist_ok=False)
    return target


def _table_digest(con: sqlite3.Connection, table: str, fields: str = "*") -> str:
    columns = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    primary = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
    order = ",".join(f'"{column}"' for column in primary) or "rowid"
    digest = hashlib.sha256()
    for row in con.execute(f'SELECT {fields} FROM "{table}" ORDER BY {order}'):
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest.update(encoded + b"\n")
    return digest.hexdigest()


def _state(con: sqlite3.Connection) -> dict[str, Any]:
    return {
        "schema_version": con.execute("PRAGMA user_version").fetchone()[0],
        "schema": con.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall(),
        "rows": table_counts(con),
        "table_sha256": {table: _table_digest(con, table) for table in TABLES},
        "preserved_time_sha256": _table_digest(con, "games_time", "appid,playtime,guide_difficulty"),
    }


def _backup(database: Path, target: Path, appids: list[int]) -> dict[str, Any]:
    if target.exists():
        raise ValueError("备份文件已存在，拒绝覆盖")
    with closing(connect_local(database)) as source, closing(sqlite3.connect(target)) as backup:
        validate_local(source, appids)
        source.backup(backup)
        validate_local(backup, appids)
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or backup.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("导入前SQLite备份完整性或外键检查失败")
        return _state(backup)


def _new_time_definition() -> str:
    pending = ""
    for line in SCHEMA.read_text(encoding="utf-8").splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            if re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+games_time\s*\(", pending, re.I):
                return re.sub(
                    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+games_time\s*\(",
                    "CREATE TABLE games_time_hltb_new (", pending, count=1, flags=re.I,
                )
            pending = ""
    raise ValueError("schema.sql没有games_time的当前定义")


def _migrate_and_write(
    con: sqlite3.Connection, appids: list[int], index: dict[int, tuple[float | None, float | None, float | None]],
    version: int,
) -> int:
    desired = {appid: index.get(appid, (None, None, None)) for appid in appids}
    if version == 3:
        dependencies = con.execute(
            "SELECT type,name FROM sqlite_master WHERE tbl_name='games_time' AND type IN ('trigger','index') "
            "AND name NOT LIKE 'sqlite_autoindex_%'"
        ).fetchall()
        if dependencies:
            raise ValueError("games_time存在额外触发器或索引，停止以避免丢失")
        dependent_sql = con.execute(
            "SELECT name,sql FROM sqlite_master WHERE type IN ('view','trigger') AND sql IS NOT NULL"
        ).fetchall()
        if any(re.search(r"\bgames_time\b", sql, re.I) for _, sql in dependent_sql):
            raise ValueError("额外视图或触发器引用games_time，请先更新相关结构")
        for table in TABLES:
            if any(row[2] == "games_time" for row in con.execute(f'PRAGMA foreign_key_list("{table}")')):
                raise ValueError("games_time被其他表引用，停止以避免破坏外键")
        preserved = con.execute("SELECT appid,playtime,guide_difficulty FROM games_time ORDER BY appid").fetchall()
        con.execute(_new_time_definition())
        con.executemany(
            "INSERT INTO games_time_hltb_new(appid,playtime,main_hours,extra_hours,completionist_hours,guide_difficulty) "
            "VALUES (?,?,?,?,?,?)",
            [(appid, playtime, *desired[appid], difficulty) for appid, playtime, difficulty in preserved],
        )
        con.execute("DROP TABLE games_time")
        con.execute("ALTER TABLE games_time_hltb_new RENAME TO games_time")
        con.execute("PRAGMA user_version=4")
        return len(preserved)
    before = {row[0]: row[1:] for row in con.execute(
        "SELECT appid,main_hours,extra_hours,completionist_hours FROM games_time"
    )}
    changed = [appid for appid in appids if before[appid] != desired[appid]]
    con.executemany(
        "UPDATE games_time SET main_hours=?,extra_hours=?,completionist_hours=? WHERE appid=?",
        [(*desired[appid], appid) for appid in changed],
    )
    return len(changed)


def apply_snapshot(
    database: Path, snapshot_path: Path, appids_path: Path = DEFAULT_APPIDS, folder: Path | None = None,
) -> dict[str, Any]:
    """在线完整备份后，以单事务迁移及导入；任何校验异常回滚全部本地变更。"""
    appids, manifest = load_selection(appids_path)
    source_path = workspace_path(snapshot_path, must_exist=True)
    raw = source_path.read_bytes()
    snapshot = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("快照包含非有限JSON数值")))
    index = snapshot_index(snapshot, appids, manifest["appids_sha256"])
    database = database_path(database)
    with closing(connect_local(database)) as readonly:
        validate_local(readonly, appids)
    folder = _new_run(folder)
    copied_snapshot = folder / "source_snapshot.json"
    with copied_snapshot.open("xb") as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())
    snapshot_sha256 = hashlib.sha256(raw).hexdigest()
    backup_path = folder / "before_import.sqlite"
    before = _backup(database, backup_path, appids)
    report: dict[str, Any] = {
        "status": "prepared", "started_at": utc_now(), "database": str(database),
        "source_snapshot": str(copied_snapshot), "source_snapshot_sha256": snapshot_sha256,
        "source_read_at": snapshot["read_at"], "source_table": SOURCE_TABLE,
        "remote_readonly": snapshot["transaction_read_only"], "manifest_sha256": manifest["appids_sha256"],
        "backup": str(backup_path), "before_rows": before["rows"],
        "source_coverage": source_coverage(appids, index), "run_dir": str(folder),
    }
    save_json(folder / "report.json", report)
    with closing(connect_local(database, writable=True)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            version = validate_local(con, appids)
            if _state(con) != before:
                raise ValueError("备份后本地库内容发生改变，请使用新运行目录重试")
            changed = _migrate_and_write(con, appids, index, version)
            ensure_schema(con, schema_version=4)
            after = _state(con)
            preserved = {
                table: after["table_sha256"][table] == before["table_sha256"][table]
                for table in TABLES if table != "games_time"
            }
            time_preserved = after["preserved_time_sha256"] == before["preserved_time_sha256"]
            before_schema = [row for row in before["schema"] if row[2] != "games_time"]
            after_schema = [row for row in after["schema"] if row[2] != "games_time"]
            if before_schema != after_schema:
                raise ValueError("迁移中其他表、索引或触发器定义发生改变")
            if not all(preserved.values()) or not time_preserved or after["rows"] != before["rows"]:
                raise ValueError("本地原五表或games_time的appid/playtime/difficulty发生非预期变化")
            for appid, main, extra, completion in con.execute(
                "SELECT appid,main_hours,extra_hours,completionist_hours FROM games_time ORDER BY appid"
            ):
                if (main, extra, completion) != index.get(appid, (None, None, None)):
                    raise ValueError("导入值与冻结HLTB快照不一致")
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise ValueError("迁移后SQLite完整性或外键检查失败")
            con.commit()
        except BaseException as exc:
            con.rollback()
            report.update(status="failed_rolled_back", error_class=type(exc).__name__, error=str(exc), completed_at=utc_now())
            save_json(folder / "report.json", report)
            raise
    report.update(
        status="complete", completed_at=utc_now(), schema_version_before=version, schema_version_after=4,
        migrated=version == 3, changed_rows=changed, after_rows=after["rows"],
        preserved_tables=preserved, preserved_appid_playtime_difficulty=time_preserved,
        preserved_time_sha256=after["preserved_time_sha256"],
        preserved_table_sha256={table: after["table_sha256"][table] for table in preserved},
        integrity_check=integrity, foreign_key_check=foreign_keys,
        importer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        schema_sha256=hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
        report=str(folder / "report.json"),
    )
    save_json(folder / "report.json", report)
    return report


def save_remote_snapshot(
    database: Path, appids_path: Path = DEFAULT_APPIDS, folder: Path | None = None,
) -> dict[str, Any]:
    """仅抓取和保存远端只读快照，绝不迁移或写入本地SQLite。"""
    snapshot = fetch_snapshot(database, appids_path)
    folder = _new_run(folder)
    target = folder / "source_snapshot.json"
    digest = save_json(target, snapshot)
    appids, manifest = load_selection(appids_path)
    index = snapshot_index(snapshot, appids, manifest["appids_sha256"])
    result = {
        "status": "fetched", "snapshot": str(target), "snapshot_sha256": digest,
        "source_read_at": snapshot["read_at"], "source_table": SOURCE_TABLE,
        "remote_readonly": snapshot["transaction_read_only"], "run_dir": str(folder),
        "manifest_sha256": manifest["appids_sha256"], "source_coverage": source_coverage(appids, index),
    }
    save_json(folder / "fetch_report.json", result)
    return result


def main() -> None:
    """CLI提供只读fetch、离线快照apply，以及先fetch再apply的import入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "apply", "import"))
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--appids", type=Path, default=DEFAULT_APPIDS)
    parser.add_argument("--snapshot", type=Path, help="apply使用已冻结的HLTB来源快照")
    parser.add_argument("--run-dir", type=Path, help="新的LYX运行目录；拒绝覆盖已有目录")
    args = parser.parse_args()
    if args.command == "apply" and args.snapshot is None:
        parser.error("apply必须提供--snapshot")
    if args.command != "apply" and args.snapshot is not None:
        parser.error("--snapshot仅供apply使用")
    try:
        if args.command == "fetch":
            result = save_remote_snapshot(args.database, args.appids, args.run_dir)
        elif args.command == "apply":
            result = apply_snapshot(args.database, args.snapshot, args.appids, args.run_dir)
        else:
            fetched = save_remote_snapshot(args.database, args.appids)
            result = apply_snapshot(args.database, Path(fetched["snapshot"]), args.appids, args.run_dir)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"HLTB时长导入停止：{exc}\n")
    printable = dict(result)
    printable["source_coverage"] = {
        key: value for key, value in result["source_coverage"].items() if key != "missing_appids"
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
