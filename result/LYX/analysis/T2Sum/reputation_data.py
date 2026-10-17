"""任务5只读输入：复用完整三节点底表，读取冻结快照的评分字段。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
CORE = ROOT.parent / "T1Core"
sys.path.insert(0, str(CORE))
from compare_games import load_catalog, select_games
from prepare_metrics import csv_text, digest, source

Json = dict[str, Any]
VERSION = "lyx-reputation-three-point-v1"
PROGRESS = ("early_progress_ratio", "late_progress_ratio", "overall_progress_ratio")
SCORES = ("steam_positive_ratio", "metacritic", "rawg_rating")
LABELS = {"steam_positive_ratio": "Steam好评率", "metacritic": "Metacritic媒体评分",
          "rawg_rating": "RAWG玩家评分", "early_progress_ratio": "前段推进比：中 / 首",
          "late_progress_ratio": "后段推进比：末 / 中", "overall_progress_ratio": "全程推进比：末 / 首"}


def owned(path: str | Path) -> Path:
    """Constrain every output to this stage, following symlinks before checking."""
    result = Path(path).resolve()
    if not result.is_relative_to(ROOT):
        raise ValueError("任务5输出必须位于LYX/analysis/T2Sum内")
    return result


def write(path: Path, text: str) -> None:
    """Write UTF-8 artifacts; CSV uses a BOM for local spreadsheet readers."""
    path = owned(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig" if path.suffix == ".csv" else "utf-8", newline="")


def protected() -> Json:
    """Fingerprint databases, all earlier analysis files and the existing dependency lock."""
    files = {}
    for folder in (ROOT.parent / "T0Pre", CORE):
        for p in sorted(folder.rglob("*")):
            if p.is_file() and not {"runtime", "__pycache__"} & set(p.relative_to(folder).parts):
                files[str(p.relative_to(ROOT.parent))] = hashlib.sha256(p.read_bytes()).hexdigest()
    lock = ROOT.parents[3] / "uv.lock"
    return {"databases": [source.fingerprint(p) for p in (source.DEFAULT_DB, source.LEGACY_DB)],
            "earlier_analysis": files, "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()}


def finite(value: Any) -> bool:
    """Accept finite real numbers, excluding booleans and absent/string values."""
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)


def score_status(value: Any, maximum: float) -> str:
    """Keep NULL, zero, invalid and valid scores distinguishable in the audit."""
    if value is None:
        return "null"
    if not finite(value) or not 0 <= value <= maximum:
        return "invalid"
    return "zero" if value == 0 else "valid"


def load_data() -> tuple[list[Json], list[Json], Json]:
    """Verify earlier CSV hashes, then build the 183-game cohort without changing sources."""
    catalog, audit = load_catalog()
    appids = [g["appid"] for g in catalog]
    placeholders = ",".join("?" for _ in appids)
    with source.connect(source.DEFAULT_DB) as conn:
        payloads = {r[0]: json.loads(r[1]) for r in conn.execute(
            f"SELECT appid,payload FROM games WHERE appid IN ({placeholders})", appids)}
    conn = sqlite3.connect(source.database_path(source.LEGACY_DB).as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        hours = dict(conn.execute(f"SELECT appid,main_hours FROM games_time WHERE appid IN ({placeholders})", appids))
    finally:
        conn.rollback()
        conn.close()
    rows = []
    for g in catalog:
        p = payloads[g["appid"]]
        rawg = p.get("rawg") or {}
        positive, negative = p.get("positive"), p.get("negative")
        counts_ok = all(finite(v) and v >= 0 and int(v) == v for v in (positive, negative))
        denominator = positive + negative if counts_ok else None
        if denominator != p.get("review_count"):
            raise ValueError(f"appid={g['appid']}评论数与正负评价数不一致")
        complete = g["three_point_available"] and all(finite(g[k]) for k in ("p_s", "p_m", "p_f", *PROGRESS))
        complete = complete and g["p_s"] > 0 and g["p_m"] > 0
        if complete and len({g[k] for k in ("first_local_id", "middle_local_id", "end_local_id")}) != 3:
            raise ValueError("三节点身份不独立")
        media, rating = rawg.get("metacritic"), rawg.get("rating")
        media_status, rawg_status = score_status(media, 100), score_status(rating, 5)
        steam_status = "valid" if counts_ok and denominator > 0 else "invalid_denominator"
        main = hours.get(g["appid"])
        row = {"appid": g["appid"], "name_en": g["title"], "name_zh": g.get("name_zh"),
               "primary_gameplay": g["primary_gameplay"], "ending_type": g["ending_type"],
               "start_label_count": int(g["start_label_count"]), "quality_flags": g["quality_flags"],
               "complete_three_point": complete, "exclusion_reason": "" if complete else "incomplete_three_point",
               **{k: g[k] for k in ("p_s", "p_m", "p_f", *PROGRESS)},
               "positive": positive, "negative": negative, "review_count": p.get("review_count"),
               "steam_positive_ratio": positive / denominator if steam_status == "valid" else None,
               "steam_status": steam_status, "steamspy_fetched_at": p.get("steamspy_fetched_at"),
               "metacritic_raw": media, "metacritic": media if media_status == "valid" else None,
               "metacritic_status": media_status, "rawg_rating_raw": rating,
               "rawg_rating": rating if rawg_status == "valid" else None, "rawg_status": rawg_status,
               "rawg_ratings_count": rawg.get("ratings_count"), "rawg_fetched_at": rawg.get("fetched_at"),
               "hltb_main_hours": main if finite(main) and main > 0 else None,
               "three_scores_common": complete and all(s == "valid" for s in (steam_status, media_status, rawg_status))}
        rows.append(row)
    games = [r for r in rows if r["complete_three_point"]]
    common = [g for g in games if g["three_scores_common"]]
    counts = {"base": len(rows), "three_point": len(games), "excluded": len(rows)-len(games),
              "steam": sum(g["steam_status"] == "valid" for g in games),
              "metacritic": sum(g["metacritic_status"] == "valid" for g in games),
              "rawg": sum(g["rawg_status"] == "valid" for g in games), "common": len(common),
              "rawg_null": sum(g["rawg_status"] == "null" for g in games),
              "rawg_zero": sum(g["rawg_status"] == "zero" for g in games),
              "hltb": sum(g["hltb_main_hours"] is not None for g in games),
              "common_hltb": sum(g["hltb_main_hours"] is not None for g in common)}
    if counts != {"base":198,"three_point":183,"excluded":15,"steam":183,"metacritic":140,
                  "rawg":173,"common":140,"rawg_null":5,"rawg_zero":5,"hltb":68,"common_hltb":61}:
        raise ValueError(f"冻结样本覆盖改变，请先核验：{counts}")
    audit.update({"counts": counts, "three_point_appids_sha256": digest([g["appid"] for g in games]),
                  "common_appids_sha256": digest([g["appid"] for g in common])})
    return games, rows, audit


def query_reputation(selectors: list[str] | None = None, kind: str = "mixed") -> Json:
    """Return fixed background and optional 1–5 name/AppID selections, without file writes."""
    games, eligibility, audit = load_data()
    selected = []
    if selectors is not None:
        catalog, _ = load_catalog()
        ids = [g["appid"] for g in select_games(catalog, selectors, kind)]
        by_id = {g["appid"]: g for g in eligibility}
        selected = [{**by_id[i],
                     "selection_status": "incomplete_three_point" if not by_id[i]["complete_three_point"] else
                         "available_all_panels" if by_id[i]["three_scores_common"] else "available_steam_only",
                     "unavailable_scores": [f for f in SCORES if by_id[i][f] is None]} for i in ids]
    return {"version": VERSION, "source": audit, "background": games,
            "common_background": [g for g in games if g["three_scores_common"]], "selected": selected,
            "selection_changes_global_statistics": False,
            "units": {"steam_positive_ratio":"0_to_1", "metacritic":"0_to_100", "rawg_rating":"0_to_5",
                      **{k:"ratio" for k in PROGRESS}},
            "label_definitions": LABELS}
