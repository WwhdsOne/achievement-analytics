"""分类 CSV 导出与去重累计缓存；只访问 LYX 工作空间，不连接数据库或 API。"""

from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import datetime
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator

from local_database import TYPES, WORKSPACE, workspace_path

DEFAULT_DATACACHE = WORKSPACE / "process" / "datacache.csv"
CLASSIFICATION_CSV_FIELDS = (
    "appid", "name_en", "api_name", "display_name", "description", "type", "method", "confidence",
    "status", "sqlite_outcome", "confidence_passed", "label_sqlite_outcome",
    "knowledge_used", "evidence", "reason", "uncertainty", "request_hash",
)
DATACACHE_FIELDS = CLASSIFICATION_CSV_FIELDS + (
    "min_confidence", "confidence_comparison", "source_csv", "first_seen_at", "last_seen_at",
)
_KEY_FIELDS = ("appid", "api_name", "type", "request_hash")
_LOCK_TIMEOUT_SECONDS = 30.0


def classification_csv_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将已校验的分类记录展开成每标签一行，保留原文且不修改输入记录。"""
    rows: list[dict[str, Any]] = []
    for item in records:
        accepted_names = {tag["type"] for tag in item["accepted_types"]}
        label_outcomes = item.get("label_sqlite_outcomes", {})
        for tag in item["types"]:
            passed = tag["type"] in accepted_names
            outcome = label_outcomes.get(
                tag["type"], item["sqlite_outcome"] if passed else "below_threshold",
            )
            row = {key: "" if item.get(key) is None else item[key] for key in CLASSIFICATION_CSV_FIELDS}
            row.update(type=tag["type"], confidence=tag["confidence"],
                       evidence=" | ".join(item["evidence"]), confidence_passed=passed,
                       label_sqlite_outcome=outcome)
            rows.append(row)
    return rows


def _spreadsheet_safe(row: dict[str, Any]) -> dict[str, Any]:
    # Existing CSV rows are already escaped: apply this only to fresh raw records.
    return {key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value
            for key, value in row.items()}


def _atomic_write(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    target = workspace_path(path)
    workspace_path(target.parent).mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", delete=False,
                                         dir=target.parent, prefix=target.name + ".", suffix=".tmp") as handle:
            temporary = workspace_path(Path(handle.name), must_exist=True)
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_classification_csv(path: Path, records: list[dict[str, Any]]) -> None:
    """以 UTF-8 BOM 原子导出当轮标签，并保留原有表格公式转义规则。"""
    rows = [_spreadsheet_safe(row) for row in classification_csv_rows(records)]
    _atomic_write(path, rows, CLASSIFICATION_CSV_FIELDS)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    lock_path = workspace_path(path.with_suffix(path.suffix + ".lock"))
    workspace_path(lock_path.parent).mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        # msvcrt locks a byte range; create one byte even for a new lock file.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            def acquire() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"等待 datacache 文件锁超过 {_LOCK_TIMEOUT_SECONDS:g} 秒：{lock_path}") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            release()


def _validate_threshold(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("min_confidence 必须是 0～1 有限数")
    return float(value)


def _validate_timestamp(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} 必须是非空 ISO 时间戳")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须是 ISO 时间戳") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")


def _validate_cache_row(row: dict[str, Any], *, line: int) -> None:
    if set(row) != set(DATACACHE_FIELDS) or any(value is None for value in row.values()):
        raise ValueError(f"datacache 第 {line} 行缺少字段或含多余字段")
    try:
        appid = int(row["appid"])
        confidence = float(row["confidence"])
        threshold = float(row["min_confidence"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"datacache 第 {line} 行数值字段无效") from exc
    if appid <= 0 or not str(appid) == str(row["appid"]):
        raise ValueError(f"datacache 第 {line} 行 appid 无效")
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError(f"datacache 第 {line} 行 confidence 无效")
    _validate_threshold(threshold)
    if row["type"] not in TYPES or not row["api_name"] or not row["request_hash"]:
        raise ValueError(f"datacache 第 {line} 行标签或成就身份无效")
    if row["confidence_comparison"] != ">=":
        raise ValueError(f"datacache 第 {line} 行置信度比较规则不是 >=")
    if str(row["confidence_passed"]) != str(confidence >= threshold):
        raise ValueError(f"datacache 第 {line} 行置信度筛选结果与门槛不一致")
    if not row["source_csv"] or not row["label_sqlite_outcome"]:
        raise ValueError(f"datacache 第 {line} 行缺少来源或写库结果")
    if str(row["knowledge_used"]) not in ("True", "False"):
        raise ValueError(f"datacache 第 {line} 行 knowledge_used 无效")
    for field in ("first_seen_at", "last_seen_at"):
        _validate_timestamp(row[field], field=f"datacache 第 {line} 行 {field}")


def _read_cache(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    workspace_path(path, must_exist=True)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if tuple(reader.fieldnames or ()) != DATACACHE_FIELDS:
                raise ValueError("datacache CSV 表头与当前累计缓存结构不一致")
            rows: list[dict[str, Any]] = []
            identities: set[tuple[str, ...]] = set()
            for row in reader:
                _validate_cache_row(row, line=reader.line_num)
                identity = tuple(str(row[key]) for key in _KEY_FIELDS)
                if identity in identities:
                    raise ValueError(f"datacache 第 {reader.line_num} 行主键重复")
                identities.add(identity)
                rows.append(row)
            return rows
    except (csv.Error, UnicodeError) as exc:
        raise ValueError(f"无法完整解析 datacache CSV：{exc}") from exc


def update_datacache(path: Path, records: list[dict[str, Any]], *, source_csv: str,
                     min_confidence: float, seen_at: str) -> dict[str, int]:
    """带文件锁合并全部已校验标签，按成就、标签、请求哈希去重并保留首次出现时间。"""
    target = workspace_path(path)
    source = str(workspace_path(Path(source_csv)))
    threshold = _validate_threshold(min_confidence)
    _validate_timestamp(seen_at, field="seen_at")
    fresh: list[dict[str, Any]] = []
    fresh_keys: set[tuple[str, ...]] = set()
    for row in classification_csv_rows(records):
        passed = row["confidence"] >= threshold
        row.update(confidence_passed=passed, min_confidence=threshold, confidence_comparison=">=",
                   source_csv=source, first_seen_at=seen_at, last_seen_at=seen_at)
        if not passed:
            row["label_sqlite_outcome"] = "below_threshold"
        row = _spreadsheet_safe(row)
        _validate_cache_row(row, line=len(fresh) + 2)
        identity = tuple(str(row[key]) for key in _KEY_FIELDS)
        if identity in fresh_keys:
            raise ValueError(f"本次 datacache 输入主键重复：{identity}")
        fresh_keys.add(identity)
        fresh.append(row)
    with _file_lock(target):
        old_rows = _read_cache(target)
        merged = {tuple(str(row[key]) for key in _KEY_FIELDS): row for row in old_rows}
        inserted = updated = 0
        for row in fresh:
            identity = tuple(str(row[key]) for key in _KEY_FIELDS)
            if identity in merged:
                row["first_seen_at"] = merged[identity]["first_seen_at"]
                updated += 1
            else:
                inserted += 1
            merged[identity] = row
        rows = list(merged.values())
        _atomic_write(target, rows, DATACACHE_FIELDS)
    accepted = sum(str(row["confidence_passed"]) == "True" for row in rows)
    return {"row_count": len(rows), "accepted_label_count": accepted,
            "rejected_label_count": len(rows) - accepted, "inserted_count": inserted,
            "updated_count": updated}
