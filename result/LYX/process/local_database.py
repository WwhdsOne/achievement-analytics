"""LYX 六表 SQLite 连接、来源字段转换及模型标签原子写入；不连接远端。"""

from __future__ import annotations

import csv
from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = WORKSPACE / "database" / "achievements.sqlite"
SCHEMA = WORKSPACE / "database" / "schema.sql"
SCHEMA_VERSION = 2
METHODS = ("deepseek", "jev", "rule", "manual")
TYPES = {"mainline", "side", "collection", "challenge", "multiplayer", "dlc", "other", "unknown"}
TABLES = ("games", "games_details", "games_rate", "games_time", "achievements", "achievement_types")
COLUMNS = {
    "games": ("appid", "name_en", "name_zh"),
    "games_details": ("appid", "is_free", "price_cents", "release_date", "valve_genres"),
    "games_rate": ("appid", "review_label", "review_percent", "review_count", "metacritic", "rating"),
    "games_time": ("appid", "playtime", "guide_time_hours_min", "guide_time_hours_max", "guide_difficulty"),
    "achievements": ("appid", "position", "api_name", "display_name", "description", "percent", "status", "mainline_index"),
    "achievement_types": ("appid", "api_name", "type", "method", "confidence"),
}


def workspace_path(path: Path, *, must_exist: bool = False) -> Path:
    """拒绝 LYX 外路径，解析链接后再检查边界。"""
    resolved = path.resolve()
    if not resolved.is_relative_to(WORKSPACE.resolve()):
        raise ValueError("路径必须位于 result/LYX 内")
    if must_exist and not resolved.is_file():
        raise ValueError("文件不存在")
    return resolved


def database_path(path: Path) -> Path:
    """只能连接已经存在的 LYX 数据库，防止拼错路径创建空库。"""
    return workspace_path(path, must_exist=True)


def connect_local(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    """使用显式 ro/rw 模式连接现有库；调用方负责关闭连接。"""
    db = database_path(path)
    mode = "rw" if writable else "ro"
    con = sqlite3.connect(db.as_uri() + f"?mode={mode}", uri=True, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def ensure_schema(con: sqlite3.Connection, *, check_methods: bool = True) -> None:
    """检查六表及字段完全匹配；导入程序不自动修改结构。"""
    found = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if found != set(TABLES) or con.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise ValueError("本地数据库不是用户确认的六表结构，请先重建")
    for table, expected in COLUMNS.items():
        actual = tuple(row[1] for row in con.execute(f'PRAGMA table_info("{table}")'))
        if actual != expected:
            raise ValueError(f"{table} 字段与六表结构不一致")
    if check_methods and method_values(con) != set(METHODS):
        raise ValueError("method 约束不是 deepseek/jev/rule/manual，请运行 migrate_methods.py")


def method_values(con: sqlite3.Connection) -> set[str]:
    """读取 method 的 CHECK 枚举，检查当前定义而非已有行的取值。"""
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='achievement_types'").fetchone()
    match = re.search(r"CHECK\s*\(\s*method\s+IN\s*\(([^()]*)\)\s*\)", row[0] if row else "", re.I)
    return set(re.findall(r"'([^']*)'", match.group(1))) if match else set()


def encode_genres(values: list[str] | None) -> str | None:
    """TEXT[] 转为 | 分隔文本；用 CSV 引号转义保留分隔符和换行。"""
    if values is None:
        return None
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ValueError("valve_genres 必须是字符串列表或 NULL")
    buffer = io.StringIO(newline="")
    csv.writer(buffer, delimiter="|", lineterminator="\r\n").writerow(values)
    return buffer.getvalue()[:-2]


def decode_genres(value: str | None) -> list[str] | None:
    """读取同一文本契约；NULL 表示缺失，空文本表示空数组。"""
    if value is None:
        return None
    if value == "":
        return []
    return next(csv.reader(io.StringIO(value, newline=""), delimiter="|", strict=True))


def table_counts(con: sqlite3.Connection) -> dict[str, int]:
    """返回六张业务表的实际行数。"""
    return {table: con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in TABLES}


def sqlite_percent(value: Any) -> float:
    """保留有效零值，将来源完成率按 Decimal 四舍五入到两位。"""
    if isinstance(value, bool) or value is None:
        raise ValueError("成就完成率缺失或类型无效")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("成就完成率无效") from exc
    if not number.is_finite() or not 0 <= number <= 100:
        raise ValueError("成就完成率必须位于0～100")
    return float(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def store_classifications(database: Path, game: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, int]:
    """整批原子写入模型标签；核对输入，保护人工结果，不修改原始属性。"""
    seen: set[str] = set()
    for record in records:
        if record["appid"] != game["appid"] or record["api_name"] in seen:
            raise ValueError("分类游戏或成就身份重复/不一致")
        seen.add(record["api_name"])
        tags = record["types"]
        if not isinstance(tags, list) or not tags:
            raise ValueError("分类类型不能为空")
        names: set[str] = set()
        for tag in tags:
            name, score = tag["type"], tag["confidence"]
            if not isinstance(name, str) or name not in TYPES or name in names:
                raise ValueError("分类类型越界或重复")
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("置信度必须是0～1有限数")
            names.add(name)
        if ("unknown" in names and len(names) != 1) or record["status"] not in ("suggested", "uncertain"):
            raise ValueError("分类状态或unknown互斥不符合约定")
        if names == {"unknown"} and record["status"] != "uncertain":
            raise ValueError("unknown必须标记为uncertain")
        if record["method"] != "deepseek":
            raise ValueError("此入口仅写入DeepSeek结果")
    counts = {"written": 0, "unchanged": 0, "protected": 0}
    outcomes: list[str] = []
    with closing(connect_local(database, writable=True)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            ensure_schema(con)
            context = con.execute(
                "SELECT g.name_en,g.name_zh,d.valve_genres FROM games g "
                "LEFT JOIN games_details d USING(appid) WHERE g.appid=?", (game["appid"],)
            ).fetchone()
            if context is None or (context[0], context[1], decode_genres(context[2])) != (
                    game["name_en"], game["name_zh"], game["valve_genres"]):
                raise ValueError("模型调用后游戏上下文改变，请重新读取")
            for record in records:
                key = (record["appid"], record["api_name"])
                current = con.execute(
                    "SELECT display_name,description,status,mainline_index FROM achievements WHERE appid=? AND api_name=?", key
                ).fetchone()
                if current is None or current[:2] != (record["display_name"], record["description"]):
                    raise ValueError("模型调用后成就输入改变，整批停止写入")
                existing = con.execute(
                    "SELECT type,method,confidence FROM achievement_types WHERE appid=? AND api_name=? ORDER BY type", key
                ).fetchall()
                if current[2] == "approved" or current[3] is not None or any(tag[1] == "manual" for tag in existing):
                    counts["protected"] += 1
                    outcomes.append("protected")
                    continue
                target = sorted((tag["type"], "deepseek", tag["confidence"]) for tag in record["types"])
                if existing == target and current[2] == record["status"]:
                    counts["unchanged"] += 1
                    outcomes.append("unchanged")
                    continue
                # 整体替换自动标签，避免unknown互斥触发器拒绝新旧标签交叉。
                con.execute("DELETE FROM achievement_types WHERE appid=? AND api_name=?", key)
                con.executemany(
                    "INSERT INTO achievement_types(appid,api_name,type,method,confidence) VALUES(?,?,?,?,?)",
                    [(*key, *tag) for tag in target]
                )
                con.execute("UPDATE achievements SET status=? WHERE appid=? AND api_name=?", (record["status"], *key))
                counts["written"] += 1
                outcomes.append("written")
            con.commit()
        except BaseException:
            con.rollback()
            raise
    for record, outcome in zip(records, outcomes, strict=True):
        record["sqlite_outcome"] = outcome
    return counts


def execute_schema(con: sqlite3.Connection) -> None:
    """逐条执行 SQL，保留调用方事务；避免 executescript 隐式提交。"""
    pending = ""
    for line in SCHEMA.read_text(encoding="utf-8").splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            con.execute(pending)
            pending = ""
    if pending.strip():
        raise ValueError("schema.sql 包含不完整 SQL")
