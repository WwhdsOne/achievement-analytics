"""备份后为LYX标签表添加并回填display_name；仅操作本地SQLite。"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from local_database import (
    COLUMNS, DEFAULT_DATABASE, SCHEMA_VERSION, TABLES, WORKSPACE, connect_local,
    ensure_schema, execute_schema, table_counts, workspace_path,
)

MIGRATION = WORKSPACE / "database" / "migrate_display_names.sql"


def data_digest(con: sqlite3.Connection, *, original_only: bool = False) -> str:
    """逐表稳定核对数据；original_only排除本次新增的展示名以比较迁移前后。"""
    sha = hashlib.sha256()
    for table in TABLES:
        actual = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
        columns = [name for name in COLUMNS[table] if name in actual and not (
            original_only and table == "achievement_types" and name == "display_name"
        )]
        fields = ",".join('"' + name + '"' for name in columns)
        sha.update(table.encode("utf-8"))
        for row in con.execute(f'SELECT {fields} FROM "{table}" ORDER BY {fields}'):
            sha.update((json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
    return sha.hexdigest()


def name_issues(con: sqlite3.Connection, *, has_display_name: bool) -> tuple[int, int]:
    """统计缺失来源名称和需要回填/修正的标签行，按完整复合键关联。"""
    missing = con.execute(
        "SELECT count(*) FROM achievement_types t LEFT JOIN achievements a USING(appid,api_name) "
        "WHERE a.display_name IS NULL OR length(trim(a.display_name))=0"
    ).fetchone()[0]
    if has_display_name:
        mismatched = con.execute(
            "SELECT count(*) FROM achievement_types t JOIN achievements a USING(appid,api_name) "
            "WHERE t.display_name IS NOT a.display_name"
        ).fetchone()[0]
    else:
        mismatched = con.execute("SELECT count(*) FROM achievement_types").fetchone()[0]
    return missing, mismatched


def migrate(database: Path) -> dict[str, Any]:
    """备份后原子迁移或修复名称；验证旧字段/约束，失败回滚，重复运行不改库。"""
    with closing(connect_local(database)) as source:
        version = source.execute("PRAGMA user_version").fetchone()[0]
        ensure_schema(source, schema_version=version)
        missing, changed = name_issues(source, has_display_name=version == SCHEMA_VERSION)
        if missing:
            raise ValueError("标签缺少对应的非空成就展示名，停止迁移")
        if version == SCHEMA_VERSION and changed == 0:
            return {"already_migrated": True, "schema_version": SCHEMA_VERSION,
                    "backfilled_rows": 0, "counts": table_counts(source)}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = workspace_path(WORKSPACE / "database" / "backups" / (stamp + "-display-names"))
        directory.mkdir(parents=True, exist_ok=False)
        backup = directory / "achievements.sqlite"
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
            before = data_digest(destination, original_only=True)
            snapshot = data_digest(destination)
    with closing(connect_local(database, writable=True)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            ensure_schema(con, schema_version=version)
            if data_digest(con) != snapshot:
                raise ValueError("备份后本地数据发生变化，停止迁移，请重跑")
            counts = table_counts(con)
            missing, changed = name_issues(con, has_display_name=version == SCHEMA_VERSION)
            if missing:
                raise ValueError("来源展示名缺失，停止迁移")
            triggers = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            indexes = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
            if version == 2:
                pending = ""
                for line in MIGRATION.read_text(encoding="utf-8").splitlines(keepends=True):
                    pending += line
                    if sqlite3.complete_statement(pending):
                        con.execute(pending)
                        pending = ""
                if pending.strip():
                    raise ValueError("展示名迁移SQL不完整")
            else:
                con.execute(
                    "UPDATE achievement_types SET display_name=(SELECT a.display_name FROM achievements a "
                    "WHERE a.appid=achievement_types.appid AND a.api_name=achievement_types.api_name) "
                    "WHERE display_name IS NOT (SELECT a.display_name FROM achievements a "
                    "WHERE a.appid=achievement_types.appid AND a.api_name=achievement_types.api_name)"
                )
            execute_schema(con)
            ensure_schema(con)
            after = data_digest(con, original_only=True)
            if before != after or counts != table_counts(con) or name_issues(con, has_display_name=True) != (0, 0):
                raise ValueError("展示名回填或原始记录保留检查失败，回滚")
            if not triggers <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}:
                raise ValueError("原有触发器没有完整保留，回滚")
            if not indexes <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}:
                raise ValueError("原有索引没有完整保留，回滚")
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise ValueError("数据库完整性或外键检查失败，回滚")
            con.commit()
        except BaseException:
            con.rollback()
            raise
    report = {"already_migrated": False, "schema_version_before": version, "schema_version": SCHEMA_VERSION,
              "database": str(database.resolve()), "backup": str(backup), "backfilled_rows": changed,
              "counts": counts, "original_data_sha256_before": before, "original_data_sha256_after": after,
              "original_data_unchanged": before == after, "integrity": integrity, "foreign_key_issues": len(foreign_keys)}
    (directory / "migration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """显式执行本地展示名迁移，错误时保留备份并返回失败。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.database), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(f"本地展示名迁移失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
