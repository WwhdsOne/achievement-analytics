"""Gamer Guides 难度的本地 SQLite 读写；HLTB 时长由独立同步入口维护。"""

from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import sqlite3
from typing import Any

from local_database import connect_local, database_path, ensure_schema, workspace_path

GUIDE_COLUMNS = ("guide_difficulty",)


def _appid(value: Any) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError("appid 必须是 SQLite 可表示的正整数，不能是布尔值")
    return value


def _values(values: Any) -> dict[str, float | None]:
    if not isinstance(values, dict) or any(field not in values for field in GUIDE_COLUMNS):
        raise ValueError("values 必须包含 guide_difficulty；缺失值请显式提供 NULL")
    result: dict[str, float | None] = {}
    for field in GUIDE_COLUMNS:
        value = values[field]
        if value is None:
            result[field] = None
            continue
        if type(value) not in (int, float):
            raise ValueError(f"{field} 必须是有限数或 NULL，不能是布尔值")
        try:
            number = float(value)
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"{field} 必须是有限数") from exc
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{field} 必须是非负有限数")
        if field == "guide_difficulty" and number > 10:
            raise ValueError("guide_difficulty 必须位于 0～10")
        result[field] = number
    return result


def _outcome(
    appid: int, state: str, before: dict[str, Any], after: dict[str, Any], *,
    changed_fields: list[str] | None = None, conflict_fields: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "appid": appid, "state": state, "changed_fields": changed_fields or [],
        "before": before, "after": after,
    }
    if conflict_fields:
        outcome["conflict_fields"] = conflict_fields
    if reason:
        outcome["reason"] = reason
    return outcome


def read_games(database: Path, appids: list[int] | None = None) -> list[dict[str, Any]]:
    """只读返回已有 games_time 行的身份、攻略难度和 playtime；空清单返回空结果。"""
    selected = None if appids is None else sorted({_appid(value) for value in appids})
    fields = ("appid", "name_en", "name_zh", *GUIDE_COLUMNS, "playtime")
    sql = (
        "SELECT g.appid,g.name_en,g.name_zh,t.guide_difficulty,t.playtime "
        "FROM games g JOIN games_time t ON t.appid=g.appid"
    )
    rows: list[tuple[Any, ...]] = []
    with closing(connect_local(database)) as con:
        con.execute("PRAGMA query_only=ON")
        ensure_schema(con)
        if selected is None:
            rows = con.execute(sql + " ORDER BY g.appid").fetchall()
        else:
            # 兼容 SQLite 较低的绑定参数上限，同时避免拼接 AppID 值到 SQL。
            for start in range(0, len(selected), 900):
                chunk = selected[start:start + 900]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(con.execute(
                    sql + f" WHERE g.appid IN ({placeholders}) ORDER BY g.appid", chunk,
                ).fetchall())
    return [dict(zip(fields, row, strict=True)) for row in rows]


def backup_database(database: Path, target: Path) -> None:
    """使用 SQLite 在线备份完整现有六表库；目标限定在 LYX 内且禁止覆盖文件。"""
    source_path = database_path(database)
    target_path = workspace_path(target)
    if target_path == source_path:
        raise ValueError("备份目标不能与源数据库相同")
    with closing(connect_local(source_path)) as source:
        source.execute("PRAGMA query_only=ON")
        ensure_schema(source)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        # 独占创建目标文件，避免 exists 检查后另一进程创建同名文件的覆盖竞态。
        with target_path.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(target_path.as_uri() + "?mode=rw", uri=True)) as destination:
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("SQLite 备份完整性检查失败")
                ensure_schema(destination)
        except BaseException:
            # 仅删除由本函数独占创建的失败备份，保留任何已存在的同名文件。
            target_path.unlink(missing_ok=True)
            raise


def write_guide_values(
    database: Path, record: dict[str, Any], *, overwrite: bool = False,
) -> dict[str, Any]:
    """短事务只更新难度；历史来源中的时长仅供审计，不写 HLTB 或旧时长字段。"""
    if not isinstance(record, dict):
        raise ValueError("record 必须是字典")
    appid = _appid(record.get("appid"))
    name_en = record.get("name_en")
    if not isinstance(name_en, str) or not name_en.strip():
        raise ValueError("name_en 必须是读取本地 games 表得到的非空字符串")
    if type(overwrite) is not bool:
        raise ValueError("overwrite 必须是布尔值")
    incoming = _values(record.get("values"))
    with closing(connect_local(database, writable=True)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            ensure_schema(con)
            current_name = con.execute("SELECT name_en FROM games WHERE appid=?", (appid,)).fetchone()
            if current_name is None:
                con.rollback()
                return _outcome(appid, "missing", {}, {}, reason="missing_game")
            current = con.execute(
                "SELECT guide_difficulty "
                "FROM games_time WHERE appid=?", (appid,),
            ).fetchone()
            if current is None:
                con.rollback()
                return _outcome(appid, "missing", {}, {}, reason="missing_games_time")
            before = dict(zip(GUIDE_COLUMNS, current, strict=True))
            if current_name[0] != name_en:
                con.rollback()
                return _outcome(
                    appid, "conflict", before, before.copy(), conflict_fields=["name_en"],
                    reason="game_name_changed",
                )
            conflicts = [field for field in GUIDE_COLUMNS if (
                not overwrite and before[field] is not None and incoming[field] is not None
                and before[field] != incoming[field]
            )]
            if conflicts:
                con.rollback()
                return _outcome(appid, "conflict", before, before.copy(), conflict_fields=conflicts,
                                reason="existing_values_differ")
            after = {field: before[field] if incoming[field] is None else incoming[field]
                     for field in GUIDE_COLUMNS}
            changed = [field for field in GUIDE_COLUMNS if before[field] != after[field]]
            if not changed:
                con.rollback()
                return _outcome(appid, "unchanged", before, after)
            con.execute(
                "UPDATE games_time SET guide_difficulty=? WHERE appid=?",
                (*[after[field] for field in GUIDE_COLUMNS], appid),
            )
            con.commit()
            return _outcome(appid, "written", before, after, changed_fields=changed)
        except BaseException:
            con.rollback()
            raise
