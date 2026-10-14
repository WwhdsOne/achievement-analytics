"""备份并更新 LYX SQLite 的 method CHECK；不连接远端、不调用模型。"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from local_database import (
    DEFAULT_DATABASE, METHODS, SCHEMA_VERSION, WORKSPACE, connect_local,
    ensure_schema, execute_schema, method_values, table_counts, workspace_path,
)
from migrate_display_names import data_digest, migrate as migrate_display_names, name_issues

MIGRATION = WORKSPACE / "database" / "migrate_methods.sql"
LEGACY_METHODS = {"rule", "jev", "manual", "hybrid"}


def migrate(database: Path) -> dict[str, Any]:
    """备份后短事务重建类型表；失败回滚，重复运行不改库。"""
    with closing(connect_local(database)) as source:
        version = source.execute("PRAGMA user_version").fetchone()[0]
        ensure_schema(source, check_methods=False, schema_version=version)
        existing = method_values(source)
        if existing == set(METHODS):
            return {**migrate_display_names(database), "methods": list(METHODS)}
        if existing != LEGACY_METHODS:
            raise ValueError("现有method定义不是预期旧结构，停止")
        if source.execute("SELECT 1 FROM achievement_types WHERE method='hybrid' LIMIT 1").fetchone():
            raise ValueError("存在hybrid记录，不能自动猜测其来源并转换")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = workspace_path(WORKSPACE / "database" / "backups" / (stamp + "-methods"))
        directory.mkdir(parents=True, exist_ok=False)
        backup = workspace_path(directory / "achievements.sqlite")
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
            before = data_digest(destination, original_only=True)
            snapshot = data_digest(destination)
    with closing(connect_local(database, writable=True)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            ensure_schema(con, check_methods=False, schema_version=version)
            if method_values(con) != existing or data_digest(con) != snapshot:
                raise ValueError("备份后原库发生变化，停止迁移，请重跑")
            counts = table_counts(con)
            triggers = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            pending = ""
            for line in MIGRATION.read_text(encoding="utf-8").splitlines(keepends=True):
                pending += line
                if sqlite3.complete_statement(pending):
                    con.execute(pending)
                    pending = ""
            if pending.strip():
                raise ValueError("迁移SQL不完整")
            execute_schema(con)  # 恢复索引/触发器；旧版同时回填展示名并升级版本。
            ensure_schema(con)
            after = data_digest(con, original_only=True)
            if after != before or table_counts(con) != counts or name_issues(con, has_display_name=True) != (0, 0):
                raise ValueError("迁移前后业务记录不一致，回滚")
            if {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")} != triggers | {"achievements_display_name_sync"}:
                raise ValueError("触发器没有完整保留，回滚")
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise ValueError("数据库完整性或外键检查失败，回滚")
            con.commit()
        except BaseException:
            con.rollback()
            raise
    report = {"already_migrated": False, "methods": list(METHODS), "schema_version": SCHEMA_VERSION,
              "database": str(database.resolve()), "backup": str(backup), "counts": counts,
              "data_sha256_before": before, "data_sha256_after": after,
              "data_unchanged": before == after, "integrity": integrity, "foreign_key_issues": len(foreign_keys)}
    (directory / "migration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """运行一次受控本地约束迁移，错误时保留备份并返回失败。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.database), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(f"本地method迁移失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
