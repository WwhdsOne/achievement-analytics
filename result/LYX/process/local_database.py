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
DEFAULT_MIN_CONFIDENCE = 0.6
SCHEMA = WORKSPACE / "database" / "schema.sql"
SCHEMA_VERSION = 4
METHODS = ("deepseek", "jev", "rule", "manual")
TYPES = {
    "mainline",
    "side",
    "collection",
    "challenge",
    "multiplayer",
    "dlc",
    "other",
    "unknown",
}
TABLES = (
    "games",
    "games_details",
    "games_rate",
    "games_time",
    "achievements",
    "achievement_types",
)
COLUMNS = {
    "games": ("appid", "name_en", "name_zh"),
    "games_details": (
        "appid",
        "is_free",
        "price_cents",
        "release_date",
        "valve_genres",
    ),
    "games_rate": (
        "appid",
        "review_label",
        "review_percent",
        "review_count",
        "metacritic",
        "rating",
    ),
    "games_time": (
        "appid",
        "playtime",
        "main_hours",
        "extra_hours",
        "completionist_hours",
        "guide_difficulty",
    ),
    "achievements": (
        "appid",
        "position",
        "api_name",
        "display_name",
        "description",
        "percent",
        "status",
        "mainline_index",
    ),
    "achievement_types": (
        "appid",
        "api_name",
        "display_name",
        "type",
        "method",
        "confidence",
    ),
}
LEGACY_TIME_COLUMNS = (
    "appid",
    "playtime",
    "guide_time_hours_min",
    "guide_time_hours_max",
    "guide_difficulty",
)


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


def ensure_schema(
    con: sqlite3.Connection,
    *,
    check_methods: bool = True,
    schema_version: int = SCHEMA_VERSION,
) -> None:
    """检查六表及字段；显式迁移可读旧版2/3，日常入口要求HLTB时长版4。"""
    if schema_version not in (2, 3, SCHEMA_VERSION):
        raise ValueError("不支持此本地schema版本")
    found = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if (
        found != set(TABLES)
        or con.execute("PRAGMA user_version").fetchone()[0] != schema_version
    ):
        raise ValueError(
            "本地数据库结构版本不一致；旧版2先运行 migrate_display_names.py，旧版3需迁移HLTB时长结构至版本4（原导入脚本已移除）"
        )
    for table, expected in COLUMNS.items():
        if table == "achievement_types" and schema_version == 2:
            expected = tuple(column for column in expected if column != "display_name")
        if table == "games_time" and schema_version < 4:
            expected = LEGACY_TIME_COLUMNS
        actual = tuple(row[1] for row in con.execute(f'PRAGMA table_info("{table}")'))
        if actual != expected:
            raise ValueError(f"{table} 字段与六表结构不一致")
    if check_methods and method_values(con) != set(METHODS):
        raise ValueError(
            "method 约束不是 deepseek/jev/rule/manual，请运行 migrate_methods.py"
        )


def method_values(con: sqlite3.Connection) -> set[str]:
    """读取 method 的 CHECK 枚举，检查当前定义而非已有行的取值。"""
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='achievement_types'"
    ).fetchone()
    match = re.search(
        r"CHECK\s*\(\s*method\s+IN\s*\(([^()]*)\)\s*\)", row[0] if row else "", re.I
    )
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
    return {
        table: con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        for table in TABLES
    }


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


def partition_classification_types(
    tags: Any,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """校验完整标签后逐类筛选；confidence大于等于门槛的标签可入库。"""
    if (
        type(min_confidence) not in (int, float)
        or not math.isfinite(min_confidence)
        or not 0 <= min_confidence <= 1
    ):
        raise ValueError("置信度门槛必须是0～1有限数")
    if not isinstance(tags, list) or not tags:
        raise ValueError("分类类型不能为空")
    names: set[str] = set()
    for tag in tags:
        if not isinstance(tag, dict) or set(tag) != {"type", "confidence"}:
            raise ValueError("标签必须只包含type和confidence")
        name, score = tag["type"], tag["confidence"]
        if not isinstance(name, str) or name not in TYPES or name in names:
            raise ValueError("分类类型越界或重复")
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise ValueError("置信度必须是0～1有限数")
        names.add(name)
    if "unknown" in names and len(names) != 1:
        raise ValueError("unknown不能与其他类型共存")
    ordered = sorted(tags, key=lambda tag: tag["type"])
    return (
        [tag for tag in ordered if tag["confidence"] >= min_confidence],
        [tag for tag in ordered if tag["confidence"] < min_confidence],
    )


def store_classifications(
    database: Path,
    game: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    reclassify: bool = False,
    expected_input: list[dict[str, Any]] | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    merge_existing: bool = False,
) -> dict[str, int]:
    """原子写入合格标签；离线补录可补齐相容标签，冲突及人工成果保留。"""
    if merge_existing and reclassify:
        raise ValueError("补录与覆盖重判不能同时启用")
    seen: set[str] = set()
    partitions: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    for record in records:
        if record["appid"] != game["appid"] or record["api_name"] in seen:
            raise ValueError("分类游戏或成就身份重复/不一致")
        seen.add(record["api_name"])
        accepted, rejected = partition_classification_types(
            record["types"], min_confidence
        )
        partitions.append((accepted, rejected))
        for field, expected in (
            ("accepted_types", accepted),
            ("rejected_types", rejected),
        ):
            if field in record and record[field] != expected:
                raise ValueError("入库筛选与运行记录不一致")
        if record["status"] not in ("suggested", "uncertain"):
            raise ValueError("分类状态不符合约定")
        if record["types"][0]["type"] == "unknown" and record["status"] != "uncertain":
            raise ValueError("unknown必须标记为uncertain")
        if record["method"] != "deepseek":
            raise ValueError("此入口仅写入DeepSeek结果")
    counts = {
        "written": 0,
        "unchanged": 0,
        "protected": 0,
        "already_classified": 0,
        "below_threshold": 0,
    }
    if merge_existing:
        counts["conflict"] = 0
    outcomes: list[str] = []
    label_outcomes: list[dict[str, str]] = [{} for _ in records]
    with closing(connect_local(database, writable=True)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            ensure_schema(con)
            context = con.execute(
                "SELECT g.name_en,g.name_zh,d.valve_genres FROM games g "
                "LEFT JOIN games_details d USING(appid) WHERE g.appid=?",
                (game["appid"],),
            ).fetchone()
            if context is None or (
                context[0],
                context[1],
                decode_genres(context[2]),
            ) != (game["name_en"], game["name_zh"], game["valve_genres"]):
                raise ValueError("模型调用后游戏上下文改变，请重新读取")
            if expected_input is not None:
                expected = sorted(
                    (r["api_name"], r["display_name"], r["description"])
                    for r in expected_input
                )
                actual = con.execute(
                    "SELECT api_name,display_name,description FROM achievements WHERE appid=? ORDER BY api_name",
                    (game["appid"],),
                ).fetchall()
                if expected != actual:
                    raise ValueError("模型调用后整款成就集合或文本改变，停止写入")
            for index, (record, (accepted, rejected)) in enumerate(
                zip(records, partitions, strict=True)
            ):
                key = (record["appid"], record["api_name"])
                current = con.execute(
                    "SELECT display_name,description,status,mainline_index FROM achievements WHERE appid=? AND api_name=?",
                    key,
                ).fetchone()
                if current is None or current[:2] != (
                    record["display_name"],
                    record["description"],
                ):
                    raise ValueError("模型调用后成就输入改变，整批停止写入")
                existing = con.execute(
                    "SELECT type,method,confidence,display_name FROM achievement_types WHERE appid=? AND api_name=? ORDER BY type",
                    key,
                ).fetchall()
                if (
                    current[2] == "approved"
                    or current[3] is not None
                    or any(tag[1] == "manual" for tag in existing)
                ):
                    counts["protected"] += 1
                    outcomes.append("protected")
                    continue
                if merge_existing and existing:
                    target = [
                        (
                            tag["type"],
                            "deepseek",
                            tag["confidence"],
                            record["display_name"],
                        )
                        for tag in accepted
                    ]
                    if not accepted:
                        counts["below_threshold"] += 1
                        outcomes.append("below_threshold")
                        continue
                    if any(tag not in target for tag in existing):
                        counts["conflict"] += 1
                        outcomes.append("conflict")
                        label_outcomes[index] = {
                            tag[0]: "already_classified"
                            for tag in existing
                            if tag in target
                        }
                        continue
                    additions = [tag for tag in target if tag not in existing]
                    label_outcomes[index] = {
                        tag[0]: "already_classified" for tag in existing
                    }
                    if not additions:
                        counts["already_classified"] += 1
                        outcomes.append("already_classified")
                        continue
                    con.executemany(
                        "INSERT INTO achievement_types(appid,api_name,type,method,confidence,display_name) VALUES(?,?,?,?,?,?)",
                        [(*key, *tag) for tag in additions],
                    )
                    con.execute(
                        "UPDATE achievements SET status=? WHERE appid=? AND api_name=?",
                        (
                            "uncertain" if target[0][0] == "unknown" else "suggested",
                            *key,
                        ),
                    )
                    label_outcomes[index].update(
                        {tag[0]: "written" for tag in additions}
                    )
                    counts["written"] += 1
                    outcomes.append("written")
                    continue
                if (
                    not reclassify
                    and current[2] in ("suggested", "uncertain")
                    and existing
                    and all(t[1] == "deepseek" for t in existing)
                ):
                    counts["already_classified"] += 1
                    outcomes.append("already_classified")
                    continue
                if not accepted:
                    counts["below_threshold"] += 1
                    outcomes.append("below_threshold")
                    continue
                target = [
                    (tag["type"], "deepseek", tag["confidence"], record["display_name"])
                    for tag in accepted
                ]
                status = (
                    "uncertain" if accepted[0]["type"] == "unknown" else "suggested"
                )
                if existing == target and current[2] == status:
                    counts["unchanged"] += 1
                    outcomes.append("unchanged")
                    continue
                # 整体替换自动标签，避免unknown互斥触发器拒绝新旧标签交叉。
                con.execute(
                    "DELETE FROM achievement_types WHERE appid=? AND api_name=?", key
                )
                con.executemany(
                    "INSERT INTO achievement_types(appid,api_name,type,method,confidence,display_name) VALUES(?,?,?,?,?,?)",
                    [(*key, *tag) for tag in target],
                )
                con.execute(
                    "UPDATE achievements SET status=? WHERE appid=? AND api_name=?",
                    (status, *key),
                )
                counts["written"] += 1
                outcomes.append("written")
            con.commit()
        except BaseException:
            con.rollback()
            raise
    for record, outcome, (accepted, rejected), per_label in zip(
        records, outcomes, partitions, label_outcomes, strict=True
    ):
        record["sqlite_outcome"] = outcome
        record["accepted_types"], record["rejected_types"] = accepted, rejected
        record["status"] = (
            "uncertain"
            if not accepted or accepted[0]["type"] == "unknown"
            else "suggested"
        )
        record["label_sqlite_outcomes"] = {
            tag["type"]: per_label.get(tag["type"], outcome) for tag in accepted
        } | {tag["type"]: "below_threshold" for tag in rejected}
        record["written_types"] = [
            tag
            for tag in accepted
            if record["label_sqlite_outcomes"][tag["type"]] == "written"
        ]
    return counts


def execute_schema(
    con: sqlite3.Connection, *, schema_version: int = SCHEMA_VERSION
) -> None:
    """逐条恢复schema对象；旧标签迁移显式保留版本3，不隐式迁移时长结构。"""
    if schema_version not in (3, SCHEMA_VERSION):
        raise ValueError("schema执行目标只能为3或当前版本")
    pending = ""
    for line in SCHEMA.read_text(encoding="utf-8").splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            if re.fullmatch(
                r"\s*PRAGMA\s+user_version\s*=\s*\d+\s*;\s*", pending, re.I
            ):
                con.execute(f"PRAGMA user_version={schema_version}")
            else:
                con.execute(pending)
            pending = ""
    if pending.strip():
        raise ValueError("schema.sql 包含不完整 SQL")
