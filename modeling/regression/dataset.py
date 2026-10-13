"""从唯一事实源提取固定的游戏级建模快照；不修改数据库结构。"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from cleaning.db import get_engine

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
REPORT_PATH = PROCESSED / "analysis-report.json"
TEXT_RULES = {
    "剧情推进": r"chapter|story|campaign|ending|章节|剧情|结局",
    "收集": r"collect|collection|all items|收集|收藏",
    "重复刷取": r"[0-9,]+ times|[0-9,]+ enemies|[0-9,]+ kills|击杀.*[0-9]+|累计",
    "技术挑战": r"without dying|no damage|hard mode|hardest|nightmare|不死|无伤|最高难度",
    "多人协作": r"co.op|multiplayer|online|teammate|多人|联机|队友",
}


def owners_midpoint(value: str | None) -> float:
    """解析拥有量估算区间中点；不可解析的记录保持缺失。"""
    if not isinstance(value, str):
        return float("nan")
    match = re.fullmatch(r"\s*([\d,]+)\s*\.\.\s*([\d,]+)\s*", value)
    if not match:
        return float("nan")
    low, high = (int(v.replace(",", "")) for v in match.groups())
    return (low + high) / 2 if 0 <= low <= high else float("nan")


def derive_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """派生目标；缺失计数、零分母、零时长不伪装成有效观测。"""
    frame = frame.copy()
    frame["resolved_total"] = frame[["beaten", "dropped"]].sum(axis=1, min_count=2)
    denominator = frame["resolved_total"].where(frame["resolved_total"] > 0)
    frame["drop_ratio"] = frame["dropped"] / denominator
    frame["reviews"] = frame[["positive", "negative"]].sum(axis=1, min_count=2)
    frame["approval"] = frame["positive"] / frame["reviews"].where(frame["reviews"] > 0)
    frame["log_hours"] = np.log1p(frame["playtime"].where(frame["playtime"] > 0))
    if {"owned", "playing"} <= set(frame.columns):
        total = frame[["owned", "playing", "beaten", "dropped"]].sum(
            axis=1, min_count=4
        )
        frame["all_status_drop"] = frame["dropped"] / total.where(total > 0)
    if "release_date" in frame:
        frame["year"] = pd.to_datetime(frame["release_date"], errors="coerce").dt.year
    return frame


def extract_snapshot() -> tuple[pd.DataFrame, dict[str, Any]]:
    """以一致性快照提取聚合量并登记内容指纹；仅写已有版本表。"""
    engine = get_engine()
    text_columns = ",\n".join(
        f"avg((coalesce(description, '') ~* :rule{i})::int)::float AS text_{i}"
        for i in range(len(TEXT_RULES))
    )
    query = f"""
    WITH difficulty AS (
        SELECT appid, count(*) AS ach_count,
          percentile_cont(.5) WITHIN GROUP (ORDER BY percent) AS median_percent,
          percentile_cont(.1) WITHIN GROUP (ORDER BY percent) AS p10_percent,
          percentile_cont(.9) WITHIN GROUP (ORDER BY percent)
            - percentile_cont(.1) WITHIN GROUP (ORDER BY percent) AS spread,
          avg((percent < 5)::int)::float AS hard_ratio,
          avg((percent < 1)::int)::float AS ultra_ratio,
          avg((percent >= 90)::int)::float AS common_ratio,
          avg(percent)::float AS mean_percent,
          avg((description IS NOT NULL AND description <> '')::int)::float AS description_coverage,
          {text_columns}
        FROM achievements GROUP BY appid
    ), tags AS (
        SELECT appid, array_agg(tag ORDER BY tag) AS tags
        FROM game_tags WHERE source='steamspy' AND kind='theme' GROUP BY appid
    )
    SELECT g.appid, g.name_en, g.name_zh, a.release_date, a.is_free, a.price_cents,
      a.valve_genres AS genres, s.owners, s.positive, s.negative, s.ccu,
      r.rawg_id, r.playtime, r.rating, r.ratings_count, r.added_count,
      r.status_beaten AS beaten, r.status_dropped AS dropped,
      r.status_owned AS owned, r.status_playing AS playing,
      r.fetched_at::text AS rawg_fetched_at, a.fetched_at::text AS store_fetched_at,
      s.fetched_at::text AS spy_fetched_at, d.*, t.tags,
      task.status AS rawg_task_status
    FROM games g
    LEFT JOIN steam_appdetails a USING(appid)
    LEFT JOIN steamspy_games s USING(appid)
    LEFT JOIN rawg_games r USING(appid)
    LEFT JOIN difficulty d USING(appid)
    LEFT JOIN tags t USING(appid)
    LEFT JOIN fetch_tasks task ON task.appid=g.appid AND task.source='rawg'
    WHERE NOT EXISTS (SELECT 1 FROM mapping_issues mi WHERE mi.appid=g.appid AND NOT mi.resolved)
      AND a.release_date < DATE '2026-01-01'
    ORDER BY g.appid
    """
    params = {f"rule{i}": rule for i, rule in enumerate(TEXT_RULES.values())}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            # d.appid 会与 g.appid 重名，SQL 后端统一消除其重复列。
            frame = pd.read_sql(text(query), conn, params=params)
            frame = frame.loc[:, ~frame.columns.duplicated()]
            excluded = int(
                conn.execute(
                    text("SELECT count(*) FROM mapping_issues WHERE NOT resolved")
                ).scalar()
            )
            source_times = [
                dict(row)
                for row in conn.execute(
                    text(
                        "SELECT source, min(fetched_at)::text AS first_fetch, max(fetched_at)::text AS last_fetch "
                        "FROM ingest_log WHERE status='ok' GROUP BY source ORDER BY source"
                    )
                ).mappings()
            ]
            examples = [
                dict(row)
                for row in conn.execute(
                    text(
                        "SELECT g.name_en AS game, a.display_name, a.description "
                        "FROM achievements a JOIN games g USING(appid) "
                        "WHERE a.description IS NOT NULL AND a.description <> '' "
                        "AND NOT EXISTS (SELECT 1 FROM mapping_issues m WHERE m.appid=a.appid AND NOT m.resolved) "
                        "ORDER BY md5(a.appid::text || a.display_name) LIMIT 40"
                    )
                ).mappings()
            ]
    frame = derive_metrics(frame)
    for col in ("genres", "tags"):
        frame[col] = frame[col].apply(
            lambda v: list(v) if isinstance(v, (list, np.ndarray)) else []
        )
    snapshot = frame.to_json(
        orient="table", force_ascii=False, date_format="iso"
    ).encode()
    digest = hashlib.sha256(snapshot).hexdigest()
    version = f"engagement-20261001-{digest[:12]}"
    folder = PROCESSED / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{version}.json.gz"
    path.write_bytes(gzip.compress(snapshot, mtime=0))
    metadata = {
        "version": version,
        "sha256": digest,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": str(path.relative_to(ROOT)),
        "games": len(frame),
        "excluded_mapping": excluded,
        "source_times": source_times,
        "text_examples": examples,
    }
    path.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO dataset_versions (version, note) VALUES (:v, :n) ON CONFLICT DO NOTHING"
            ),
            {
                "v": version,
                "n": json.dumps(
                    {k: v for k, v in metadata.items() if k != "text_examples"},
                    ensure_ascii=False,
                ),
            },
        )
    engine.dispose()
    return frame, metadata


def load_snapshot(version: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """按版本重放固定输入并校验 SHA256，不重新读取源表。"""
    if not re.fullmatch(r"engagement-20261001-[a-f0-9]{12}", version):
        raise ValueError("无效的数据版本")
    path = PROCESSED / "snapshots" / f"{version}.json.gz"
    metadata = json.loads(path.with_suffix(".metadata.json").read_text())
    raw = gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError("数据快照指纹不一致")
    from io import StringIO

    return pd.read_json(StringIO(raw.decode()), orient="table"), metadata
