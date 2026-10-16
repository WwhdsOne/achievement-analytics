"""按 Steam 评价数固定前1000款，分批只读提取云库并迁移到 LYX 六表 SQLite。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from inspect_remote import connect_readonly, error_summary
from local_database import (
    DEFAULT_DATABASE,
    SCHEMA_VERSION,
    WORKSPACE,
    connect_local,
    database_path,
    encode_genres,
    ensure_schema,
    sqlite_percent,
    table_counts,
    workspace_path,
)

DEFAULT_APPIDS = WORKSPACE / "database" / "data" / "top1000_appids.json"
DEFAULT_MANIFEST = DEFAULT_APPIDS.with_name("top1000_selection.json")
RANKING_SQL = (
    "SELECT appid,review_count FROM store_search_games "
    "WHERE review_count IS NOT NULL "
    "ORDER BY review_count DESC,appid ASC LIMIT %s"
)
QUERIES = {
    "games": "SELECT appid,name_en,name_zh FROM games WHERE appid=ANY(%s) ORDER BY appid",
    "details": "SELECT appid,is_free,price_cents,release_date,valve_genres,fetched_at FROM steam_appdetails WHERE appid=ANY(%s) ORDER BY appid",
    "reviews": "SELECT appid,review_label,review_percent,review_count,fetched_at FROM store_search_games WHERE appid=ANY(%s) ORDER BY appid",
    "rawg": "SELECT appid,rawg_id,name,metacritic,rating,playtime,fetched_at FROM rawg_games WHERE appid=ANY(%s) ORDER BY appid",
    "achievements": "SELECT appid,position,api_name,display_name,description,percent FROM achievements WHERE appid=ANY(%s) ORDER BY appid,position",
    "mapping_issues": "SELECT appid,reason,detected_at,resolved FROM mapping_issues WHERE appid=ANY(%s) ORDER BY appid",
}


def utc_now() -> str:
    """返回带时区的UTC时间，避免混淆来源抓取时间与本地执行时间。"""
    return datetime.now(timezone.utc).isoformat()


def json_scalar(value: Any) -> str:
    """JSON文件保留Decimal精度与日期；SQLite本身不保存JSON字段。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"不支持的快照类型：{type(value).__name__}")


def save_json(path: Path, value: Any) -> str:
    """在LYX内原子保存文件，返回实际字节SHA256；断电前刷新文件缓冲。"""
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            value, ensure_ascii=False, indent=2, default=json_scalar, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return hashlib.sha256(encoded).hexdigest()


def read_remote(queries: dict[str, tuple[str, tuple[Any, ...]]]) -> dict[str, Any]:
    """短只读事务执行参数化SELECT；所有远端错误输出经过脱敏。"""
    con, attempts = connect_readonly()
    if con is None:
        raise RuntimeError(f"云库连接失败：{attempts}")
    result: dict[str, Any] = {"connection_attempts": attempts}
    try:
        with con:
            con.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            readonly = con.execute(
                "SELECT current_setting('transaction_read_only')"
            ).fetchone()[0]
            if readonly != "on":
                raise RuntimeError("远端事务未强制只读，停止")
            result["transaction_read_only"] = readonly
            result["read_at"] = utc_now()
            with con.cursor(row_factory=dict_row) as cursor:
                for name, (sql, parameters) in queries.items():
                    if not sql.lstrip().upper().startswith("SELECT "):
                        raise ValueError("远端数据查询仅允许SELECT")
                    cursor.execute(sql, parameters)
                    result[name] = cursor.fetchall()
    except psycopg.Error as exc:
        raise RuntimeError(f"云库只读查询失败：{error_summary(exc)}") from None
    return result


def load_selection(
    appids_path: Path = DEFAULT_APPIDS,
) -> tuple[list[int], dict[str, Any]]:
    """读取冻结的排名清单和指纹，续跑时不重新选择人群。"""
    path = workspace_path(appids_path, must_exist=True)
    manifest_path = path.with_name(
        path.stem.removesuffix("_appids") + "_selection.json"
    )
    manifest = json.loads(
        workspace_path(manifest_path, must_exist=True).read_text(encoding="utf-8")
    )
    raw = path.read_bytes()
    appids = json.loads(raw)
    if (
        not isinstance(appids, list)
        or len(appids) != 1000
        or any(type(a) is not int or a <= 0 for a in appids)
        or len(set(appids)) != 1000
    ):
        raise ValueError("AppID清单必须是1000个不重复的正整数")
    if manifest.get("appids_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("排名清单指纹不一致，停止")
    ranking = manifest.get("ranking")
    if not isinstance(ranking, list) or [r["appid"] for r in ranking] != appids:
        raise ValueError("排名明细与AppID清单不一致")
    if ranking != sorted(ranking, key=lambda r: (-r["review_count"], r["appid"])):
        raise ValueError("排名未按review_count DESC、appid ASC排序")
    return appids, manifest


def select_top1000(
    appids_path: Path = DEFAULT_APPIDS,
) -> tuple[list[int], dict[str, Any]]:
    """先将前1000名AppID保存为独立JSON数组，再保存排名与来源说明。"""
    path = workspace_path(appids_path)
    if path.exists():
        return load_selection(path)
    selected = read_remote({"ranking": (RANKING_SQL, (1000,))})
    ranking = selected["ranking"]
    if len(ranking) != 1000:
        raise ValueError(f"远端有效评价记录不足1000：实际{len(ranking)}")
    appids = [row["appid"] for row in ranking]
    digest = save_json(path, appids)
    manifest = {
        "selected_at": selected["read_at"],
        "selection_sql": RANKING_SQL,
        "selection_parameters": [1000],
        "selection_count": 1000,
        "appids_file": str(path),
        "appids_sha256": digest,
        "ranking": ranking,
        "transaction_read_only": selected["transaction_read_only"],
        "connection_attempts": selected["connection_attempts"],
        "filters": "仅review_count非NULL；无年份、类型、成就数或主线筛选；同评价数按appid升序",
    }
    manifest_path = path.with_name(
        path.stem.removesuffix("_appids") + "_selection.json"
    )
    save_json(manifest_path, manifest)
    return load_selection(path)


def snapshot_indexes(snapshot: dict[str, Any], appids: list[int]) -> dict[str, Any]:
    """验证批次身份与成就类型，按AppID建立索引；异常不当作无数据。"""
    if (
        snapshot.get("transaction_read_only") != "on"
        or snapshot.get("appids") != appids
    ):
        raise ValueError("快照的只读声明或批次AppID不一致")
    allowed = set(appids)
    indexes: dict[str, Any] = {}
    for source in QUERIES:
        rows = snapshot.get(source)
        if not isinstance(rows, list):
            raise ValueError(f"{source} 快照不是列表")
        if any(
            not isinstance(row, dict)
            or type(row.get("appid")) is not int
            or row["appid"] not in allowed
            for row in rows
        ):
            raise ValueError(f"{source} 存在批次之外或无效的AppID")
        if source == "achievements":
            grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                if type(row.get("position")) is not int or row["position"] < 1:
                    raise ValueError("成就position无效")
                if any(
                    not isinstance(row.get(key), str) or not row[key].strip()
                    for key in ("api_name", "display_name")
                ):
                    raise ValueError("成就身份或展示名无效")
                if row.get("description") is not None and not isinstance(
                    row["description"], str
                ):
                    raise ValueError("成就描述类型无效")
                row["percent"] = sqlite_percent(row.get("percent"))
                grouped[row["appid"]].append(row)
            for records in grouped.values():
                if len({r["api_name"] for r in records}) != len(records) or len(
                    {r["position"] for r in records}
                ) != len(records):
                    raise ValueError("成就身份或position重复")
                records.sort(key=lambda r: r["position"])
            indexes[source] = grouped
        else:
            if len({r["appid"] for r in rows}) != len(rows):
                raise ValueError(f"{source} 身份重复")
            indexes[source] = {r["appid"]: r for r in rows}
    if set(indexes["games"]) != allowed:
        raise ValueError("批次存在games身份缺失，不导入部分游戏")
    return indexes


def fetch_snapshot(appids: list[int]) -> dict[str, Any]:
    """每批独立只读一致性事务，抓取成功后完整保存；短暂失败退避重试。"""
    for attempt in range(3):
        try:
            snapshot = read_remote(
                {name: (sql, (appids,)) for name, sql in QUERIES.items()}
            )
            snapshot["appids"] = appids
            snapshot_indexes(snapshot, appids)
            return snapshot
        except RuntimeError:
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("无法获取批次快照")


def expected_background(indexes: dict[str, Any], appid: int) -> dict[str, Any]:
    """映射六表背景属性；已知RAWG版本疑点排除并记录，不改远端原值。"""
    identity = indexes["games"][appid]
    details = indexes["details"].get(appid, {})
    reviews = indexes["reviews"].get(appid, {})
    rawg = indexes["rawg"].get(appid, {})
    excluded = appid == 1462040 and rawg.get("name") == "Final Fantasy VII"
    usable_rawg = {} if excluded else rawg
    return {
        "games": (appid, identity["name_en"], identity.get("name_zh")),
        "games_details": (
            appid,
            int(details["is_free"]) if details.get("is_free") is not None else None,
            details.get("price_cents"),
            str(details["release_date"]) if details.get("release_date") else None,
            encode_genres(details.get("valve_genres")),
        ),
        "games_rate": (
            appid,
            reviews.get("review_label"),
            reviews.get("review_percent"),
            reviews.get("review_count"),
            usable_rawg.get("metacritic"),
            float(usable_rawg["rating"])
            if usable_rawg.get("rating") is not None
            else None,
        ),
        "playtime": usable_rawg.get("playtime"),
        "rawg_excluded": excluded,
        "rawg_present": bool(rawg),
        "details_present": bool(details),
        "reviews_present": bool(reviews),
    }


def raw_achievement(row: dict[str, Any]) -> tuple[Any, ...]:
    """取得与远端保持一致的六个原始成就字段。"""
    return tuple(
        row[key]
        for key in (
            "appid",
            "position",
            "api_name",
            "display_name",
            "description",
            "percent",
        )
    )


def import_game(
    con: sqlite3.Connection, indexes: dict[str, Any], appid: int
) -> dict[str, Any]:
    """单游戏事务迁移；保留分类/审核/排序，分类输入冲突时保留原成就并报告。"""
    background = expected_background(indexes, appid)
    source_records = indexes["achievements"].get(appid, [])
    source_by_name = {r["api_name"]: r for r in source_records}
    try:
        con.execute("BEGIN IMMEDIATE")
        con.row_factory = sqlite3.Row
        old_records = {
            r["api_name"]: dict(r)
            for r in con.execute(
                "SELECT * FROM achievements WHERE appid=? ORDER BY position",
                (appid,),
            )
        }
        old_types = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM achievement_types WHERE appid=? ORDER BY api_name,type",
                (appid,),
            )
        ]
        con.row_factory = None
        classified = {r["api_name"] for r in old_types}
        changed_protected = []
        for name, old in old_records.items():
            source = source_by_name.get(name)
            changed = (
                source is None
                or source["display_name"] != old["display_name"]
                or source["description"] != old["description"]
            )
            protected = (
                name in classified
                or old["status"] != "pending"
                or old["mainline_index"] is not None
            )
            if changed and protected:
                changed_protected.append(name)
        con.execute(
            "INSERT INTO games VALUES (?,?,?) ON CONFLICT(appid) DO UPDATE SET name_en=excluded.name_en,name_zh=excluded.name_zh",
            background["games"],
        )
        con.execute(
            "INSERT INTO games_details VALUES (?,?,?,?,?) ON CONFLICT(appid) DO UPDATE SET "
            "is_free=excluded.is_free,price_cents=excluded.price_cents,release_date=excluded.release_date,valve_genres=excluded.valve_genres",
            background["games_details"],
        )
        con.execute(
            "INSERT INTO games_rate VALUES (?,?,?,?,?,?) ON CONFLICT(appid) DO UPDATE SET "
            "review_label=excluded.review_label,review_percent=excluded.review_percent,review_count=excluded.review_count,"
            "metacritic=excluded.metacritic,rating=excluded.rating",
            background["games_rate"],
        )
        # 攻略字段没有远端对应来源，也不覆盖已经人工填入的攻略估计。
        con.execute(
            "INSERT INTO games_time(appid,playtime) VALUES (?,?) ON CONFLICT(appid) DO UPDATE SET playtime=excluded.playtime",
            (appid, background["playtime"]),
        )
        if not changed_protected:
            expected_raw = [raw_achievement(row) for row in source_records]
            old_raw = [raw_achievement(row) for row in old_records.values()]
            if old_raw != expected_raw:
                # 先清空同游戏再重建，可安全处理position重排产生的唯一约束冲突。
                con.execute("DELETE FROM achievements WHERE appid=?", (appid,))
                con.executemany(
                    "INSERT INTO achievements(appid,position,api_name,display_name,description,percent,status) VALUES (?,?,?,?,?,?,?)",
                    [
                        raw_achievement(row)
                        + (
                            old_records.get(row["api_name"], {}).get(
                                "status", "pending"
                            ),
                        )
                        for row in source_records
                    ],
                )
                retained = [r for r in old_types if r["api_name"] in source_by_name]
                con.executemany(
                    "INSERT INTO achievement_types(appid,api_name,display_name,type,method,confidence) VALUES (?,?,?,?,?,?)",
                    [
                        (
                            r["appid"],
                            r["api_name"],
                            source_by_name[r["api_name"]]["display_name"],
                            r["type"],
                            r["method"],
                            r["confidence"],
                        )
                        for r in retained
                    ],
                )
                for name, old in old_records.items():
                    if name in source_by_name and old["mainline_index"] is not None:
                        con.execute(
                            "UPDATE achievements SET mainline_index=? WHERE appid=? AND api_name=?",
                            (old["mainline_index"], appid, name),
                        )
        actual_count = con.execute(
            "SELECT count(*) FROM achievements WHERE appid=?", (appid,)
        ).fetchone()[0]
        if not changed_protected and actual_count != len(source_records):
            raise ValueError("成就迁移行数不一致")
        con.commit()
    except Exception:
        con.row_factory = None
        con.rollback()
        raise
    return {
        "appid": appid,
        "source_achievements": len(source_records),
        "local_achievements": actual_count,
        "classified_input_conflicts": changed_protected,
        "rawg_present": background["rawg_present"],
        "rawg_excluded": background["rawg_excluded"],
        "details_present": background["details_present"],
        "reviews_present": background["reviews_present"],
    }


@contextmanager
def run_lock(folder: Path) -> Iterator[None]:
    """用系统文件锁保护续跑状态；进程退出后自动释放，不产生僵尸锁。"""
    path = workspace_path(folder / ".run.lock")
    with path.open("a+b") as file:
        if path.stat().st_size == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError("该迁移目录已有运行中的进程") from None
            try:
                yield
            finally:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def start_run(
    database: Path,
    appids_path: Path,
    appids: list[int],
    manifest: dict[str, Any],
    folder: Path,
    batch_size: int,
) -> dict[str, Any]:
    """先完整备份当前库，固定清单指纹和分批参数，记录续跑状态。"""
    db = database_path(database)
    backup = workspace_path(folder / "before_import.sqlite")
    if backup.exists() or (folder / "checkpoint.json").exists():
        raise ValueError("运行目录已有备份或状态，请使用--resume")
    with closing(connect_local(db)) as source:
        ensure_schema(source)
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
            before_rows = table_counts(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("导入前备份完整性检查失败")
    state = {
        "started_at": utc_now(),
        "status": "running",
        "database": str(db),
        "appids_file": str(appids_path.resolve()),
        "appids_sha256": manifest["appids_sha256"],
        "selected_appids": appids,
        "batch_size": batch_size,
        "schema_version": SCHEMA_VERSION,
        "backup": str(backup),
        "before_rows": before_rows,
        "processed_appids": [],
        "snapshots": {},
        "results": {},
        "failures": {},
    }
    save_json(folder / "checkpoint.json", state)
    return state


def verify_run(folder: Path, state: dict[str, Any]) -> dict[str, Any]:
    """按冻结批次快照逐字段核对1000款，不把缺数据、冲突或NULL当迁移成功。"""
    appids = state["selected_appids"]
    if state["failures"] or set(state["processed_appids"]) != set(appids):
        raise ValueError("还有未完成或失败的AppID，不能通过最终验收")
    quality: dict[str, Any] = {
        "no_achievements": [],
        "missing_rawg": [],
        "rawg_excluded": [],
        "unresolved_mapping_issues": [],
        "missing_release_date": [],
        "released_2026_or_later": [],
        "classified_input_conflicts": {},
    }
    expected_total = 0
    source_description_missing = 0
    verified = 0
    with closing(connect_local(Path(state["database"]))) as con:
        ensure_schema(con)
        for key in sorted(state["snapshots"], key=int):
            entry = state["snapshots"][key]
            path = workspace_path(folder / entry["file"], must_exist=True)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("冻结批次快照指纹不一致")
            snapshot = json.loads(raw)
            indexes = snapshot_indexes(snapshot, snapshot["appids"])
            for appid in snapshot["appids"]:
                expected = expected_background(indexes, appid)
                for table in ("games", "games_details", "games_rate"):
                    actual = con.execute(
                        f"SELECT * FROM {table} WHERE appid=?", (appid,)
                    ).fetchone()
                    if actual != expected[table]:
                        raise ValueError(f"{appid}: {table}字段与来源快照不同")
                if con.execute(
                    "SELECT playtime FROM games_time WHERE appid=?", (appid,)
                ).fetchone() != (expected["playtime"],):
                    raise ValueError(f"{appid}: playtime与来源快照不同")
                records = indexes["achievements"].get(appid, [])
                expected_total += len(records)
                source_description_missing += sum(
                    row.get("description") is None or not row["description"].strip()
                    for row in records
                )
                conflicts = state["results"][str(appid)]["classified_input_conflicts"]
                if conflicts:
                    quality["classified_input_conflicts"][str(appid)] = conflicts
                else:
                    actual = con.execute(
                        "SELECT appid,position,api_name,display_name,description,percent FROM achievements WHERE appid=? ORDER BY position",
                        (appid,),
                    ).fetchall()
                    if actual != [raw_achievement(row) for row in records]:
                        raise ValueError(f"{appid}: 成就字段与来源快照不同")
                if not records:
                    quality["no_achievements"].append(appid)
                if not expected["rawg_present"]:
                    quality["missing_rawg"].append(appid)
                if expected["rawg_excluded"]:
                    quality["rawg_excluded"].append(appid)
                details = indexes["details"].get(appid, {})
                release_date = details.get("release_date")
                if not release_date:
                    quality["missing_release_date"].append(appid)
                elif release_date[:4] >= "2026":
                    quality["released_2026_or_later"].append(appid)
                issue = indexes["mapping_issues"].get(appid)
                if issue and not issue["resolved"]:
                    quality["unresolved_mapping_issues"].append(issue)
                verified += 1
        if verified != 1000:
            raise ValueError("最终核对游戏数不是1000")
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise ValueError("最终数据库完整性或外键检查失败")
        counts = table_counts(con)
        status_counts = dict(
            con.execute("SELECT status,count(*) FROM achievements GROUP BY status")
        )
        annotated_order = con.execute(
            "SELECT count(*) FROM achievements WHERE mainline_index IS NOT NULL"
        ).fetchone()[0]
        description_missing = con.execute(
            "SELECT count(*) FROM achievements WHERE description IS NULL OR trim(description)=''"
        ).fetchone()[0]
        playtime_positive = con.execute(
            "SELECT count(*) FROM games_time WHERE playtime>0"
        ).fetchone()[0]
        playtime_zero = con.execute(
            "SELECT count(*) FROM games_time WHERE playtime=0"
        ).fetchone()[0]
        playtime_null = con.execute(
            "SELECT count(*) FROM games_time WHERE playtime IS NULL"
        ).fetchone()[0]
        imported_rows = con.execute(
            "SELECT count(*) FROM achievements WHERE appid IN ("
            + ",".join("?" for _ in appids)
            + ")",
            appids,
        ).fetchone()[0]
        baseline = Path(state["backup"])
        with closing(connect_local(baseline)) as old:
            for appid in quality["classified_input_conflicts"]:
                fields = "appid,position,api_name,display_name,description,percent"
                current = con.execute(
                    f"SELECT {fields} FROM achievements WHERE appid=? ORDER BY position",
                    (int(appid),),
                ).fetchall()
                previous = old.execute(
                    f"SELECT {fields} FROM achievements WHERE appid=? ORDER BY position",
                    (int(appid),),
                ).fetchall()
                if current != previous:
                    raise ValueError("发生分类输入冲突的原成就没有完整保留")
            old_types = old.execute(
                "SELECT appid,api_name,type,method,confidence FROM achievement_types ORDER BY appid,api_name,type"
            ).fetchall()
            for row in old_types:
                if (
                    con.execute(
                        "SELECT appid,api_name,type,method,confidence FROM achievement_types WHERE appid=? AND api_name=? AND type=?",
                        row[:3],
                    ).fetchone()
                    != row
                ):
                    raise ValueError("导入前已有分类未完整保留")
            protected_rows = old.execute(
                "SELECT appid,api_name,status,mainline_index FROM achievements WHERE status<>'pending' OR mainline_index IS NOT NULL"
            ).fetchall()
            for row in protected_rows:
                if (
                    con.execute(
                        "SELECT appid,api_name,status,mainline_index FROM achievements WHERE appid=? AND api_name=?",
                        row[:2],
                    ).fetchone()
                    != row
                ):
                    raise ValueError("导入前审核状态或主线排序未完整保留")
    return {
        "verified_at": utc_now(),
        "verified_games": verified,
        "source_achievements": expected_total,
        "selected_local_achievements": imported_rows,
        "rows": counts,
        "status_counts": status_counts,
        "source_description_missing": source_description_missing,
        "local_description_missing": description_missing,
        "playtime_coverage": {
            "positive": playtime_positive,
            "zero": playtime_zero,
            "null": playtime_null,
        },
        "non_null_mainline_index": annotated_order,
        "quality": quality,
        "integrity_check": integrity,
        "foreign_key_check": foreign_keys,
        "preserved_existing_types": len(old_types),
        "preserved_existing_reviewed_or_suggested": len(protected_rows),
        "selection_file": state["appids_file"],
        "selection_sha256": state["appids_sha256"],
        "backup": state["backup"],
        "database": state["database"],
        "remote_readonly": "on for selection and every independently captured batch",
        "sqlite_version": sqlite3.sqlite_version,
        "importer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(
            (WORKSPACE / "database/schema.sql").read_bytes()
        ).hexdigest(),
        "database_bytes": Path(state["database"]).stat().st_size,
    }


def migrate(
    database: Path,
    appids_path: Path,
    folder: Path | None = None,
    *,
    batch_size: int = 50,
    resume: bool = False,
    max_batches: int | None = None,
) -> dict[str, Any]:
    """保存冻结输入，分批/单游戏事务迁移，支持中断重跑而不重新排序。"""
    if not 1 <= batch_size <= 100 or (max_batches is not None and max_batches < 1):
        raise ValueError("batch_size须在1～100之间，max_batches须为正整数")
    appids, manifest = select_top1000(appids_path)
    if folder is None:
        folder = (
            WORKSPACE
            / "process"
            / "runtime"
            / "remote_import"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
    folder = workspace_path(folder)
    if resume:
        if not folder.is_dir():
            raise ValueError("续跑目录不存在")
    else:
        folder.mkdir(parents=True, exist_ok=False)
    with run_lock(folder):
        if resume:
            state = json.loads(
                workspace_path(folder / "checkpoint.json", must_exist=True).read_text(
                    encoding="utf-8"
                )
            )
            if (
                state["database"] != str(database_path(database))
                or state["appids_sha256"] != manifest["appids_sha256"]
                or state["selected_appids"] != appids
            ):
                raise ValueError("续跑的数据库或冻结AppID清单不一致")
            if state["schema_version"] != SCHEMA_VERSION:
                raise ValueError("续跑schema版本不一致")
            batch_size = state["batch_size"]
        else:
            state = start_run(
                database, appids_path, appids, manifest, folder, batch_size
            )
        executed = 0
        batches = [
            appids[i : i + batch_size] for i in range(0, len(appids), batch_size)
        ]
        for number, batch in enumerate(batches, 1):
            pending = [
                appid for appid in batch if appid not in state["processed_appids"]
            ]
            if not pending:
                continue
            entry = state["snapshots"].get(str(number))
            snapshot_path = workspace_path(folder / f"batch_{number:04d}.json")
            if entry is None:
                snapshot = fetch_snapshot(batch)
                sha = save_json(snapshot_path, snapshot)
                state["snapshots"][str(number)] = {
                    "file": snapshot_path.name,
                    "sha256": sha,
                    "read_at": snapshot["read_at"],
                }
                save_json(folder / "checkpoint.json", state)
            raw = snapshot_path.read_bytes()
            if (
                hashlib.sha256(raw).hexdigest()
                != state["snapshots"][str(number)]["sha256"]
            ):
                raise ValueError("批次快照指纹不一致，停止")
            snapshot = json.loads(raw)
            indexes = snapshot_indexes(snapshot, batch)
            with closing(connect_local(Path(state["database"]), writable=True)) as con:
                ensure_schema(con)
                for appid in pending:
                    try:
                        state["results"][str(appid)] = import_game(con, indexes, appid)
                        state["processed_appids"].append(appid)
                        state["failures"].pop(str(appid), None)
                    except (ValueError, sqlite3.Error) as exc:
                        state["failures"][str(appid)] = {
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                        }
            state["updated_at"] = utc_now()
            state["status"] = "running"
            save_json(folder / "checkpoint.json", state)
            executed += 1
            print(
                json.dumps(
                    {
                        "batch": number,
                        "batches": len(batches),
                        "processed": len(state["processed_appids"]),
                        "selected": 1000,
                        "failures": len(state["failures"]),
                        "run_dir": str(folder),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if max_batches is not None and executed >= max_batches:
                break
        if state["failures"] or len(state["processed_appids"]) < 1000:
            state["status"] = "partial"
            save_json(folder / "checkpoint.json", state)
            return {
                "status": "partial",
                "processed": len(state["processed_appids"]),
                "failures": state["failures"],
                "run_dir": str(folder),
            }
        report = verify_run(folder, state)
        save_json(folder / "report.json", report)
        state["status"] = (
            "complete"
            if not report["quality"]["classified_input_conflicts"]
            else "complete_with_conflicts"
        )
        state["completed_at"] = utc_now()
        save_json(folder / "checkpoint.json", state)
        return {
            "status": state["status"],
            "run_dir": str(folder),
            "report": str(folder / "report.json"),
            "rows": report["rows"],
            "verified_games": report["verified_games"],
            "source_achievements": report["source_achievements"],
            "quality_counts": {
                key: len(value) for key, value in report["quality"].items()
            },
        }


def main() -> None:
    """CLI：冻结排名、开始迁移或使用原运行目录续跑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appids", type=Path, default=DEFAULT_APPIDS)
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--max-batches", type=int, help="控制小批验收后暂停，续跑沿用冻结快照"
    )
    args = parser.parse_args()
    try:
        if args.select_only:
            appids, manifest = select_top1000(args.appids)
            result = {
                "appids_file": str(args.appids.resolve()),
                "selected": len(appids),
                "highest_review_count": manifest["ranking"][0]["review_count"],
                "lowest_review_count": manifest["ranking"][-1]["review_count"],
                "transaction_read_only": manifest["transaction_read_only"],
                "connection_route": manifest["connection_attempts"][-1]["route"],
            }
        else:
            if args.resume and args.run_dir is None:
                parser.error("--resume必须指定--run-dir")
            result = migrate(
                args.database,
                args.appids,
                args.run_dir,
                batch_size=args.batch_size,
                resume=args.resume,
                max_batches=args.max_batches,
            )
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"迁移停止：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("failures"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
