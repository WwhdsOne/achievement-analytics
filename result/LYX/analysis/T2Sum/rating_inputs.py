"""Read user-confirmed task5 score updates, preserving original SQLite values."""
from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MANUAL_PATH = ROOT / "inputs" / "manual_rating_supplements.csv"
COMMON_COHORT = "common142"
COMMON_SIZE = 142
HIGHLIGHT_APPIDS = (1903340, 1593500)


def load_supplements(catalog: list[dict[str, Any]]) -> tuple[dict[tuple[int, str], dict[str, Any]], dict[str, Any]]:
    """Validate approved identities, units, rating bounds and provenance."""
    titles = {g["appid"]: g["title"] for g in catalog}
    expected = {(i, f) for i in HIGHLIGHT_APPIDS for f in ("metacritic", "rawg_rating")}
    expected.add((1593500, "rawg_ratings_count"))
    limits = {"metacritic": (100, "score_0_100", "Metacritic"),
              "rawg_rating": (5, "score_0_5", "RAWG"),
              "rawg_ratings_count": (None, "ratings", "RAWG")}
    with MANUAL_PATH.open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    values = {}
    for record in records:
        appid, field, value = int(record["appid"]), record["field"], float(record["value"])
        if (appid, field) not in expected or titles.get(appid) != record["name_en"]:
            raise ValueError(f"评分补充身份或字段不符：{appid}/{field}")
        maximum, unit, origin = limits[field]
        if not math.isfinite(value) or value <= 0 or (maximum is not None and value > maximum):
            raise ValueError("评分补充值超出合法范围")
        if field in ("metacritic", "rawg_ratings_count") and int(value) != value:
            raise ValueError("媒体评分及评价人数必须为整数")
        if record["unit"] != unit or record["source"] != origin or not all(record[k] for k in ("provided_by", "provided_on")):
            raise ValueError("评分补充单位、来源或确认信息缺失")
        key = (appid, field)
        if key in values:
            raise ValueError("评分补充字段重复")
        values[key] = {**record, "appid": appid, "value": int(value) if field != "rawg_rating" else value}
    if set(values) != expected:
        raise ValueError("本轮需恰好两款游戏的四项评分和战神评价人数，共五个字段")
    return values, {"path": MANUAL_PATH.relative_to(ROOT.parents[1]).as_posix(),
                    "sha256": hashlib.sha256(MANUAL_PATH.read_bytes()).hexdigest(),
                    "games": 2, "fields": 5, "provided_by": "刘宇翔", "provided_on": "2026-10-20",
                    "source_kind": "user_confirmed_manual_lookup",
                    "note": "任务5叠加确认值；保留原始字段，33号远征队RAWG 4.44更新为4.42；未独立联网核验，未提供具体平台版本页面URL或源查询时间"}


def resolve_value(appid: int, field: str, original: Any,
                  values: dict[tuple[int, str], dict[str, Any]]) -> Any:
    """Apply only the explicit approved updates; callers retain original raw fields."""
    item = values.get((appid, field))
    return item["value"] if item else original


def value_source(appid: int, field: str, values: dict[tuple[int, str], dict[str, Any]]) -> str:
    """Distinguish original snapshot values from user-confirmed source updates."""
    item = values.get((appid, field))
    return "manual_confirmed:" + item["source"] if item else "snapshot:RAWG"
