"""离线四关系事实图谱；不改变标签推荐或连接共享数据库。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import baseline, snapshot
from .baseline import candidate_rows
from .snapshot import ROOT, SNAPSHOTS, load_snapshot

GRAPHS = ROOT / "data/processed/recommendation/kg"
SCHEMA_VERSION = "game-kg-schema-v1"
NAME_RULES_VERSION = "kg-name-rules-v1"
FIELDS = {
    "tags": ("Tag", "tag:steamspy:theme", "has_tag", "game_tags", "tag"),
    "genres": ("Genre", "genre:steam", "has_genre", "steam_appdetails", "valve_genres"),
    "developers": (
        "DeveloperName",
        "developer:steam-name",
        "developed_by",
        "steam_appdetails",
        "developers",
    ),
    "publishers": (
        "PublisherName",
        "publisher:steam-name",
        "published_by",
        "steam_appdetails",
        "publishers",
    ),
}
logger = logging.getLogger(__name__)


def json_text(value: Any) -> str:
    """稳定JSON；拒绝NaN，保持Unicode原值。"""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_file(path: Path) -> str:
    """流式计算文件SHA256，不把大型关系文件读入内存。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_name(field: str, value: str) -> str:
    """标签沿用基线，其他名称只strip和NFC。"""
    return (
        value.strip().casefold()
        if field == "tags"
        else unicodedata.normalize("NFC", value.strip())
    )


def entity_id(field: str, value: str) -> str:
    """返回不同关系命名空间中的稳定名称实体ID。"""
    key = canonical_name(field, value)
    return FIELDS[field][1] + ":" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def edge_id(subject: str, predicate: str, target: str) -> str:
    """对约定三元组数组计算关系ID。"""
    return (
        "edge:"
        + hashlib.sha256(
            json_text([subject, predicate, target]).encode("utf-8")
        ).hexdigest()
    )


def validate_appids(rows: list[dict]) -> None:
    """在任何构图输出前拒绝非法和重复appid。"""
    seen = set()
    for row in rows:
        value = row.get("appid")
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            or value in seen
        ):
            raise ValueError(f"非法或重复appid: {value!r}")
        seen.add(value)


def parse_field(row: dict, field: str) -> tuple[list[dict], dict[str, int], list[dict]]:
    """返回有效项、分类计数及全部异常位置；无效票数保留证据但标记。"""
    stats = Counter()
    issues = []
    values = row.get(field)
    if field not in row:
        stats["missing_field_rows"] += 1
    if values is None:
        stats["null_rows"] += 1
        values = []
    elif not isinstance(values, list):
        stats["invalid_container_rows"] += 1
        issues.append(
            {"appid": row["appid"], "issue": "invalid_container", "raw_value": values}
        )
        values = []
    elif not values:
        stats["empty_array_rows"] += 1
    items = []
    for index, raw_item in enumerate(values):
        stats["array_items"] += 1
        reason = None
        if field == "tags" and isinstance(raw_item, dict):
            if raw_item.get("source") != "steamspy" or raw_item.get("kind") != "theme":
                reason = "out_of_scope_items"
            raw = raw_item.get("tag")
            votes = raw_item.get("votes")
            if reason is None and (
                not isinstance(votes, int) or isinstance(votes, bool) or votes < 0
            ):
                stats["invalid_votes"] += 1
                issues.append(
                    {
                        "appid": row["appid"],
                        "array_index": index,
                        "issue": "invalid_votes",
                        "raw_value": raw_item,
                    }
                )
        else:
            raw = raw_item if field != "tags" else None
        if reason is None and not isinstance(raw, str):
            reason = "invalid_items"
        if reason is None and not canonical_name(field, raw):
            reason = "blank_items"
        if reason:
            stats[reason] += 1
            issues.append(
                {
                    "appid": row["appid"],
                    "array_index": index,
                    "issue": reason,
                    "raw_value": raw_item,
                }
            )
            continue
        key = canonical_name(field, raw)
        stats["changed_items"] += key != raw
        items.append({"index": index, "raw": raw, "key": key, "raw_item": raw_item})
    distinct = {item["key"] for item in items}
    stats.update(
        valid_items=len(items),
        unique_edges=len(distinct),
        covered_rows=int(bool(distinct)),
        duplicate_edge_items=len(items) - len(distinct),
    )
    return items, dict(stats), issues


def make_evidence(row: dict, field: str, item: dict) -> dict:
    """记录原始数组位置和值；源表更新时间不冒充事实采集事件时间。"""
    proof = {
        "appid": row["appid"],
        "snapshot_field": field,
        "array_index": item["index"],
        "raw_value": item["raw"],
        "source_table": FIELDS[field][3],
        "source_field": FIELDS[field][4],
        "source_filter": {"source": "steamspy", "kind": "theme"}
        if field == "tags"
        else {},
        "source_event_time": None,
        "warehouse_record_time": row.get(
            "spy_fetched_at" if field == "tags" else "store_fetched_at"
        ),
        "warehouse_time_field": "steamspy_games.fetched_at"
        if field == "tags"
        else "steam_appdetails.fetched_at",
        "time_semantics": "associated_game_row_update_not_tag_event"
        if field == "tags"
        else "warehouse_row_insert_or_update",
    }
    if field == "tags":
        proof.update(votes=item["raw_item"].get("votes"), raw_item=item["raw_item"])
    else:
        proof["extraction_source"] = "appdetails_en"
    return proof


def game_entity(row: dict, candidates: set[int]) -> dict:
    """保留所有游戏事实与原候选标记，不按关系缺失删游戏。"""
    names = [
        row.get(field)
        for field in ("name_zh", "name_en")
        if isinstance(row.get(field), str) and row[field].strip()
    ]
    return {
        "id": f"game:{row['appid']}",
        "entity_type": "Game",
        "canonical_key": str(row["appid"]),
        "appid": row["appid"],
        "name_en": row.get("name_en"),
        "name_zh": row.get("name_zh"),
        "display_name": names[0].strip() if names else str(row["appid"]),
        "raw_names": sorted(set(names)),
        "release_date": row.get("release_date"),
        "recommendation_eligible": row["appid"] in candidates,
        "source_table": "games",
        "source_fields": ["appid", "name_en", "name_zh"],
    }


def build_binding(metadata: dict) -> dict:
    """绑定输入、所有构建源码和候选规范；不绑定运行时刻或路径。"""
    from . import knowledge_graph_store as store

    return {
        "snapshot_version": metadata["version"],
        "snapshot_sha256": metadata["sha256"],
        "schema_version": SCHEMA_VERSION,
        "name_rules_version": NAME_RULES_VERSION,
        "python_version": platform.python_version(),
        "unicode_version": unicodedata.unidata_version,
        "builder_sha256": {
            "knowledge_graph.py": digest_file(Path(__file__)),
            "knowledge_graph_store.py": digest_file(Path(store.__file__)),
        },
        "candidate_rules_sha256": digest_file(Path(baseline.__file__)),
        "snapshot_loader_sha256": digest_file(Path(snapshot.__file__)),
    }


def graph_version(binding: dict) -> str:
    """生成包含完整绑定摘要的安全版本目录名。"""
    return "kg-v1-" + hashlib.sha256(json_text(binding).encode("utf-8")).hexdigest()


def build_graph(
    snapshot_version: str, *, snapshots: Path = SNAPSHOTS, folder: Path = GRAPHS
) -> dict:
    """验证快照后流式构图，完整验证staging，再发布或验证复用旧版本。"""
    from .knowledge_graph_store import publish_graph

    rows, metadata = load_snapshot(snapshot_version, snapshots)
    validate_appids(rows)
    binding = build_binding(metadata)
    return publish_graph(rows, binding, Path(folder))


def verify_graph(directory: Path, *, rows: list[dict] | None = None) -> dict:
    """检查文件与结构；有快照输入时完整回查事实证据和覆盖。"""
    from .knowledge_graph_store import verify_graph as verify

    return verify(Path(directory), rows=rows)


def main() -> None:
    """命令行仅构建/验证本地图谱，不启动服务或改变排序。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--folder", type=Path, default=GRAPHS)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "build":
        result = build_graph(args.version, snapshots=args.snapshots, folder=args.folder)
    else:
        if not re.fullmatch(r"kg-v1-[a-f0-9]{64}", args.version):
            parser.error("无效图谱版本")
        path = args.folder / args.version
        metadata = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        rows, snapshot_meta = load_snapshot(
            metadata["binding"]["snapshot_version"], args.snapshots
        )
        if snapshot_meta["sha256"] != metadata["binding"]["snapshot_sha256"]:
            raise ValueError("图谱与快照SHA256不一致")
        result = verify_graph(path, rows=rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
