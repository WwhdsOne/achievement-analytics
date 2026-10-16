"""独立只读提取器；所有版本登记在本地，不写共享数据库。"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "data/processed/recommendation/snapshots"
SCHEMA_VERSION = 1
CUTOFF = "2026-01-01"
logger = logging.getLogger(__name__)
QUERY = """
WITH ach AS (
    SELECT appid, count(*) AS ach_count,
           min(percent)::float AS min_percent,
           max(percent)::float AS max_percent,
           avg(percent)::float AS mean_percent,
           percentile_cont(.5) WITHIN GROUP (ORDER BY percent) AS median_percent
    FROM achievements GROUP BY appid
), tags AS (
    SELECT appid, jsonb_agg(jsonb_build_array(tag, votes)
        ORDER BY tag) AS steamspy_tag_pairs
    FROM game_tags WHERE source='steamspy' AND kind='theme' GROUP BY appid
)
SELECT g.appid, g.name_en, g.name_zh,
       a.release_date::text, a.is_free, a.price_cents,
       a.developers, a.publishers, a.valve_genres AS genres,
       a.valve_categories AS categories,
       a.fetched_at::text AS store_fetched_at,
       s.positive, s.negative, s.owners, s.ccu,
       s.fetched_at::text AS spy_fetched_at,
       coalesce(d.ach_count, 0) AS ach_count,
       d.min_percent, d.max_percent, d.mean_percent, d.median_percent,
       coalesce(t.steamspy_tag_pairs, '[]'::jsonb) AS steamspy_tag_pairs,
       EXISTS (SELECT 1 FROM mapping_issues m
               WHERE m.appid=g.appid AND NOT m.resolved) AS mapping_unresolved
FROM games g
JOIN steam_appdetails a USING (appid)
LEFT JOIN steamspy_games s USING (appid)
LEFT JOIN ach d USING (appid)
LEFT JOIN tags t USING (appid)
WHERE a.release_date < CAST(:cutoff AS date)
ORDER BY g.appid
"""
SCOPE_QUERY = """
SELECT count(*) AS warehouse_games,
       count(*) FILTER (WHERE a.release_date IS NULL) AS excluded_missing_release,
       count(*) FILTER (WHERE a.release_date >= CAST(:cutoff AS date)) AS excluded_newer_release
FROM games g LEFT JOIN steam_appdetails a USING (appid)
"""


def extract_rows(engine: Engine | None = None) -> tuple[list[dict], dict[str, Any]]:
    """同一只读一致性事务提取数据与审计计数；包括失败路径都释放连接。"""
    if engine is None:
        from cleaning.db import get_dsn

        engine = create_engine(
            get_dsn(),
            connect_args={
                "connect_timeout": 10,
                "options": "-c default_transaction_read_only=on",
            },
        )
    started = datetime.now(timezone.utc).isoformat()
    try:
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="REPEATABLE READ")
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = '120s'"))
                settings = dict(
                    conn.execute(
                        text(
                            "SELECT current_setting('transaction_read_only') AS read_only, "
                            "current_setting('transaction_isolation') AS isolation"
                        )
                    )
                    .mappings()
                    .one()
                )
                if settings != {"read_only": "on", "isolation": "repeatable read"}:
                    raise ValueError("数据库事务未达到只读一致性要求")
                logger.info("只读一致性事务已建立；每批读取 500 款游戏")
                rows = []
                result = conn.execute(
                    text(QUERY).execution_options(stream_results=True, yield_per=500),
                    {"cutoff": CUTOFF},
                )
                try:
                    for entry in result.mappings():
                        row = dict(entry)
                        # 网络上用紧凑数组；冻结输入仍保留明确来源与字段。
                        row["tags"] = [
                            dict(source="steamspy", kind="theme", tag=tag, votes=votes)
                            for tag, votes in row.pop("steamspy_tag_pairs")
                        ]
                        rows.append(row)
                        if len(rows) % 5000 == 0:
                            logger.info("已只读提取 %s 款游戏", len(rows))
                finally:
                    result.close()
                scope = dict(
                    conn.execute(text(SCOPE_QUERY), {"cutoff": CUTOFF}).mappings().one()
                )
                source_times = [
                    dict(row)
                    for row in conn.execute(
                        text(
                            "SELECT source, min(fetched_at)::text AS first_fetch, "
                            "max(fetched_at)::text AS last_fetch FROM ingest_log "
                            "WHERE status='ok' GROUP BY source ORDER BY source"
                        )
                    ).mappings()
                ]
        return rows, {
            **scope,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "transaction": "REPEATABLE READ / READ ONLY",
            "database_settings": settings,
            "query_sha256": hashlib.sha256((QUERY + SCOPE_QUERY).encode()).hexdigest(),
            "source_history_times": source_times,
            "source_history_note": "整个仓库成功采集的历史范围，不代表逐款数据同日抓取",
        }
    finally:
        engine.dispose()


def save_snapshot(rows: list[dict], extraction: dict, folder: Path = SNAPSHOTS) -> dict:
    """按内容生成版本，原子发布；同内容复用已验证的版本，拒绝覆盖坏快照。"""
    folder = Path(folder)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "release_before": CUTOFF,
        "games": sorted(rows, key=lambda row: row["appid"]),
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    version = f"recommendation-v1-{digest[:16]}"
    destination = folder / version
    if destination.exists():
        _, existing = load_snapshot(version, folder)
        if existing["sha256"] != digest:
            raise ValueError("版本冲突，拒绝覆盖")
        return existing
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "sha256": digest,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "release_before": CUTOFF,
        "games": len(rows),
        "fields": sorted({key for row in rows for key in row}),
        "extraction": extraction,
        "sources": [
            "Steam appdetails",
            "SteamSpy",
            "Steam achievements",
            "game_tags (SteamSpy theme only)",
        ],
    }
    folder.mkdir(parents=True, exist_ok=True)
    # 临时目录和最终目录同盘；中断时不会发布半份快照。
    with TemporaryDirectory(dir=folder, prefix=".staging-") as staging:
        stage = Path(staging)
        (stage / "games.json.gz").write_bytes(gzip.compress(raw, mtime=0))
        (stage / "manifest.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        try:
            os.rename(stage, destination)
        except FileExistsError:
            _, existing = load_snapshot(version, folder)
            if existing["sha256"] != digest:
                raise ValueError("版本冲突，拒绝覆盖")
            return existing
    return metadata


def load_snapshot(version: str, folder: Path = SNAPSHOTS) -> tuple[list[dict], dict]:
    """仅访问本地，校验版本、SHA256、格式和行数后重放。"""
    if not re.fullmatch(r"recommendation-v1-[a-f0-9]{16}", version):
        raise ValueError("无效的推荐数据版本")
    directory = Path(folder) / version
    metadata = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    try:
        raw = gzip.decompress((directory / "games.json.gz").read_bytes())
    except (OSError, EOFError) as exc:
        raise ValueError("快照 gzip 损坏") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if (
        digest != metadata.get("sha256")
        or version != f"recommendation-v1-{digest[:16]}"
    ):
        raise ValueError("数据快照 SHA256 不一致")
    payload = json.loads(raw)
    rows = payload.get("games")
    if (
        metadata.get("version") != version
        or metadata.get("schema_version") != SCHEMA_VERSION
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("release_before") != CUTOFF
        or metadata.get("release_before") != CUTOFF
        or not isinstance(rows, list)
        or len(rows) != metadata.get("games")
    ):
        raise ValueError("快照清单与数据契约不一致")
    return rows, metadata
