"""Read explicitly approved manual duration supplements without writing SQLite."""
from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from typing import Any

from prepare_metrics import ROOT

MANUAL_PATH = ROOT / "inputs" / "manual_duration_supplements.csv"
BASELINE_SIZE = 65
BASELINE_SHA256 = "41aed4f5c6cfff37d0032fc3bfb3812a8d30b48e3ef0058cab7865cf90a42271"
ADDED_APPIDS = frozenset({812140, 1903340, 1593500, 1245620})
COHORT_SIZE = 69
COHORT_SHA256 = "48d3f0600fbbb2cbaff4e1ffe3df9d330af35ab6ec70e384906a9161ff82e4a9"
FIELDS = {"playtime", "main_hours", "extra_hours", "completionist_hours"}


def load_supplements(catalog: list[dict[str, Any]]) -> tuple[dict[tuple[int, str], dict[str, Any]], dict[str, Any]]:
    """Validate the ten user-confirmed fields and record their local provenance."""
    titles = {g["appid"]: g["title"] for g in catalog}
    with MANUAL_PATH.open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    values: dict[tuple[int, str], dict[str, Any]] = {}
    for record in records:
        appid, field = int(record["appid"]), record["field"]
        value = float(record["value"])
        if appid not in ADDED_APPIDS or titles.get(appid) != record["name_en"]:
            raise ValueError(f"人工补充游戏身份不一致：{appid}")
        if field not in FIELDS or not math.isfinite(value) or value <= 0 or record["unit"] != "hours":
            raise ValueError(f"人工补充字段、单位或数值不合规：{appid}/{field}")
        expected_source = "RAWG" if field == "playtime" else "HLTB"
        if record["source"] != expected_source or not record["provided_by"] or not record["provided_on"]:
            raise ValueError(f"人工补充缺少确认来源：{appid}/{field}")
        key = (appid, field)
        if key in values:
            raise ValueError(f"人工补充字段重复：{appid}/{field}")
        values[key] = {**record, "appid": appid, "value": value}
    expected = {(a, f) for a in ADDED_APPIDS - {1593500}
                for f in FIELDS - {"playtime"}} | {(1593500, "playtime")}
    if set(values) != expected:
        raise ValueError("人工补充范围必须为已确认的三款HLTB三字段和God of War游玩时长")
    audit = {"path": MANUAL_PATH.relative_to(ROOT.parent.parent).as_posix(),
             "sha256": hashlib.sha256(MANUAL_PATH.read_bytes()).hexdigest(),
             "fields": len(values), "games": len(ADDED_APPIDS),
             "provided_by": "刘宇翔", "provided_on": "2026-10-20",
             "source_kind": "user_confirmed_manual_lookup", "unit": "hours",
             "note": "仅补分析输入空值，原SQLite只读；未独立联网核验，未提供页面URL或查询时间"}
    return values, audit


def resolve_value(appid: int, field: str, original: Any,
                  supplements: dict[tuple[int, str], dict[str, Any]]) -> Any:
    """Fill an absent snapshot value; refuse conflicts with non-null source data."""
    record = supplements.get((appid, field))
    if record is None:
        return original
    if original is not None and original != record["value"]:
        raise ValueError(f"人工补充与源非空值冲突，拒绝覆盖：{appid}/{field}")
    return record["value"]


def value_source(appid: int, field: str, supplements: dict[tuple[int, str], dict[str, Any]]) -> str:
    """Return a stable per-field origin suitable for CSV and webpage display."""
    if (appid, field) in supplements:
        return "manual_confirmed:" + supplements[appid, field]["source"]
    return "snapshot:" + ("RAWG" if field == "playtime" else "HLTB")
