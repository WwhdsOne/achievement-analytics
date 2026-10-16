"""图谱JSONL的有界排序、完整校验和不覆盖版本发布。"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

logger = logging.getLogger(__name__)
DATA_FILES = ("entities.jsonl", "relations.jsonl", "quality.json")
COUNT_KEYS = (
    "missing_field_rows",
    "null_rows",
    "empty_array_rows",
    "invalid_container_rows",
    "array_items",
    "invalid_items",
    "out_of_scope_items",
    "invalid_votes",
    "blank_items",
    "changed_items",
    "covered_rows",
    "valid_items",
    "unique_edges",
    "duplicate_edge_items",
)


def _validate_binding(binding: dict) -> None:
    required = {
        "snapshot_version",
        "snapshot_sha256",
        "schema_version",
        "name_rules_version",
        "python_version",
        "unicode_version",
        "builder_sha256",
        "candidate_rules_sha256",
        "snapshot_loader_sha256",
    }
    if not isinstance(binding, dict) or not required <= binding.keys():
        raise ValueError("manifest缺少必需来源绑定字段")
    for key in ("snapshot_sha256", "candidate_rules_sha256", "snapshot_loader_sha256"):
        if not isinstance(binding[key], str) or not re.fullmatch(
            r"[a-f0-9]{64}", binding[key]
        ):
            raise ValueError("manifest来源SHA256格式错误")
    if (
        binding["snapshot_version"]
        != "recommendation-v1-" + binding["snapshot_sha256"][:16]
    ):
        raise ValueError("manifest快照版本与SHA256不一致")
    for key in (
        "schema_version",
        "name_rules_version",
        "python_version",
        "unicode_version",
    ):
        if not isinstance(binding[key], str) or not binding[key].strip():
            raise ValueError("manifest缺少模式/规范/运行环境版本")
    sources = binding["builder_sha256"]
    if (
        not isinstance(sources, dict)
        or not {"knowledge_graph.py", "knowledge_graph_store.py"} <= sources.keys()
    ):
        raise ValueError("manifest缺少构建源码SHA256")
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
        for value in sources.values()
    ):
        raise ValueError("manifest构建源码SHA256格式错误")


def _write_json(path: Path, value: dict) -> None:
    from .knowledge_graph import json_text

    path.write_bytes((json_text(value) + "\n").encode("utf-8"))


def _summary(
    counts: Counter, nodes: list[dict], rows: int, *, candidate: bool = False
) -> dict:
    names_key = "_candidate_raw_names" if candidate else "raw_names"
    games_key = "_candidate_games" if candidate else "_games"
    selected = [node for node in nodes if node[games_key]]
    groups = defaultdict(list)
    import unicodedata

    for node in sorted(selected, key=lambda node: node["canonical_key"]):
        groups[
            " ".join(
                unicodedata.normalize("NFC", node["canonical_key"]).split()
            ).casefold()
        ].append(node["canonical_key"])
    return {
        **{key: counts[key] for key in COUNT_KEYS},
        "rows": rows,
        "missing_relation_rows": rows - counts["covered_rows"],
        "coverage_pct": round(100 * counts["covered_rows"] / rows, 4) if rows else None,
        "distinct_entity_keys": len(selected),
        "raw_distinct_names": sum(len(node[names_key]) for node in selected),
        "keys_with_multiple_raw_names": sum(
            len(node[names_key]) > 1 for node in selected
        ),
        "keys_used_by_multiple_games": sum(node[games_key] > 1 for node in selected),
        "review_only_variant_groups": [
            {"review_key": key, "names": names}
            for key, names in sorted(groups.items())
            if len(names) > 1
        ],
    }


def write_sorted(stage: Path, rows: list[dict], binding: dict) -> dict:
    """逐款生成证据，以临时SQLite排序JSONL；返回完整质量台账。"""
    from .knowledge_graph import (
        FIELDS,
        candidate_rows,
        edge_id,
        entity_id,
        game_entity,
        json_text,
        make_evidence,
        parse_field,
    )

    candidates = {row["appid"] for row in candidate_rows(rows)}
    vocab = {field: {} for field in FIELDS}
    counts = {field: Counter() for field in FIELDS}
    candidate_counts = {field: Counter() for field in FIELDS}
    quality = {
        "fields": {},
        "candidate_fields": {},
        "issues": {field: [] for field in FIELDS},
        "cleaning_examples": {field: [] for field in FIELDS},
        "duplicates": {field: [] for field in FIELDS},
        "games": len(rows),
        "candidates": len(candidates),
        "similarity_edges": 0,
        "snapshot_version": binding["snapshot_version"],
        "snapshot_sha256": binding["snapshot_sha256"],
    }
    db_path = stage / ".sort.sqlite"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("CREATE TABLE entities (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        conn.execute("CREATE TABLE relations (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        for ordinal, row in enumerate(sorted(rows, key=lambda row: row["appid"]), 1):
            game = game_entity(row, candidates)
            conn.execute(
                "INSERT INTO entities VALUES (?,?)", (game["id"], json_text(game))
            )
            for field, (kind, _, predicate, _, _) in FIELDS.items():
                items, stats, issues = parse_field(row, field)
                counts[field].update(stats)
                if row["appid"] in candidates:
                    candidate_counts[field].update(stats)
                quality["issues"][field].extend(issues)
                grouped = defaultdict(list)
                for item in items:
                    node_id = entity_id(field, item["raw"])
                    node = vocab[field].setdefault(
                        node_id,
                        {
                            "id": node_id,
                            "entity_type": kind,
                            "canonical_key": item["key"],
                            "raw_names": set(),
                            "_candidate_raw_names": set(),
                            "_games": 0,
                            "_candidate_games": 0,
                        },
                    )
                    if node["canonical_key"] != item["key"]:
                        raise ValueError("实体ID哈希冲突")
                    node["raw_names"].add(item["raw"])
                    if row["appid"] in candidates:
                        node["_candidate_raw_names"].add(item["raw"])
                    grouped[node_id].append(make_evidence(row, field, item))
                    if (
                        item["key"] != item["raw"]
                        and len(quality["cleaning_examples"][field]) < 8
                    ):
                        quality["cleaning_examples"][field].append(
                            {
                                "appid": row["appid"],
                                "array_index": item["index"],
                                "raw_value": item["raw"],
                                "canonical_key": item["key"],
                            }
                        )
                batch = []
                for target, evidence in grouped.items():
                    node = vocab[field][target]
                    node["_games"] += 1
                    node["_candidate_games"] += row["appid"] in candidates
                    if len(evidence) > 1:
                        quality["duplicates"][field].append(
                            {
                                "appid": row["appid"],
                                "object": target,
                                "array_indices": [
                                    proof["array_index"] for proof in evidence
                                ],
                            }
                        )
                    relation = {
                        "id": edge_id(game["id"], predicate, target),
                        "subject": game["id"],
                        "predicate": predicate,
                        "object": target,
                        "relation_kind": "source_fact",
                        "evidence": evidence,
                        "snapshot_version": binding["snapshot_version"],
                        "snapshot_sha256": binding["snapshot_sha256"],
                    }
                    batch.append((relation["id"], json_text(relation)))
                conn.executemany("INSERT INTO relations VALUES (?,?)", batch)
            if ordinal % 5000 == 0:
                logger.info("已生成 %s/%s 款游戏的事实关系", ordinal, len(rows))
        all_node_ids = set()
        for field, nodes in vocab.items():
            quality["fields"][field] = _summary(
                counts[field], list(nodes.values()), len(rows)
            )
            quality["candidate_fields"][field] = _summary(
                candidate_counts[field],
                list(nodes.values()),
                len(candidates),
                candidate=True,
            )
            for node in nodes.values():
                if node["id"] in all_node_ids:
                    raise ValueError("跨命名空间实体ID冲突")
                all_node_ids.add(node["id"])
                public = {
                    key: value for key, value in node.items() if not key.startswith("_")
                }
                public["raw_names"] = sorted(public["raw_names"])
                public["display_name"] = min(
                    value.strip() for value in public["raw_names"]
                )
                conn.execute(
                    "INSERT INTO entities VALUES (?,?)", (node["id"], json_text(public))
                )
        conn.commit()
        for table in ("entities", "relations"):
            with (stage / f"{table}.jsonl").open("wb") as handle:
                for (body,) in conn.execute(f"SELECT body FROM {table} ORDER BY id"):
                    handle.write((body + "\n").encode("utf-8"))
    db_path.unlink()
    _write_json(stage / "quality.json", quality)
    return quality


def _records(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        previous = ""
        for line in handle:
            item = json.loads(line)
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or item["id"] <= previous
            ):
                raise ValueError(f"实体/边ID重复或未排序: {path.name}")
            previous = item["id"]
            yield item


def _source_quality(
    rows: list[dict], candidates: set[int], binding: dict
) -> tuple[dict, dict]:
    """直接重放源字段的全部质量分类及原名集合，不读取已写统计。"""
    from .knowledge_graph import FIELDS, entity_id, parse_field

    counts = {field: Counter() for field in FIELDS}
    candidate_counts = {field: Counter() for field in FIELDS}
    vocab = {field: {} for field in FIELDS}
    expected = {
        "fields": {},
        "candidate_fields": {},
        "issues": {field: [] for field in FIELDS},
        "cleaning_examples": {field: [] for field in FIELDS},
        "duplicates": {field: [] for field in FIELDS},
        "games": len(rows),
        "candidates": len(candidates),
        "similarity_edges": 0,
        "snapshot_version": binding["snapshot_version"],
        "snapshot_sha256": binding["snapshot_sha256"],
    }
    aliases = {}
    for row in sorted(rows, key=lambda row: row["appid"]):
        is_candidate = row["appid"] in candidates
        for field in FIELDS:
            items, stats, issues = parse_field(row, field)
            counts[field].update(stats)
            if is_candidate:
                candidate_counts[field].update(stats)
            expected["issues"][field].extend(issues)
            grouped = defaultdict(list)
            for item in items:
                target = entity_id(field, item["raw"])
                node = vocab[field].setdefault(
                    target,
                    {
                        "canonical_key": item["key"],
                        "raw_names": set(),
                        "_candidate_raw_names": set(),
                        "_games": 0,
                        "_candidate_games": 0,
                    },
                )
                node["raw_names"].add(item["raw"])
                if is_candidate:
                    node["_candidate_raw_names"].add(item["raw"])
                grouped[target].append(item["index"])
                if (
                    item["key"] != item["raw"]
                    and len(expected["cleaning_examples"][field]) < 8
                ):
                    expected["cleaning_examples"][field].append(
                        {
                            "appid": row["appid"],
                            "array_index": item["index"],
                            "raw_value": item["raw"],
                            "canonical_key": item["key"],
                        }
                    )
            for target, indices in grouped.items():
                vocab[field][target]["_games"] += 1
                vocab[field][target]["_candidate_games"] += is_candidate
                if len(indices) > 1:
                    expected["duplicates"][field].append(
                        {
                            "appid": row["appid"],
                            "object": target,
                            "array_indices": indices,
                        }
                    )
    for field, nodes in vocab.items():
        expected["fields"][field] = _summary(
            counts[field], list(nodes.values()), len(rows)
        )
        expected["candidate_fields"][field] = _summary(
            candidate_counts[field],
            list(nodes.values()),
            len(candidates),
            candidate=True,
        )
        aliases.update({key: sorted(node["raw_names"]) for key, node in nodes.items()})
    return expected, aliases


def verify_graph(directory: Path, *, rows: list[dict] | None = None) -> dict:
    """流式校验哈希、ID/类型/端点、统计；快照可用时验证全部位置与覆盖。"""
    from .knowledge_graph import (
        FIELDS,
        candidate_rows,
        canonical_name,
        digest_file,
        edge_id,
        entity_id,
        game_entity,
        graph_version,
        make_evidence,
        parse_field,
        validate_appids,
    )

    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        binding = manifest["binding"]
        _validate_binding(binding)
        if manifest["version"] != graph_version(binding) or set(
            manifest["files"]
        ) != set(DATA_FILES):
            raise ValueError("manifest版本/文件契约不一致")
        if (
            directory.name.startswith("kg-v1-")
            and directory.name != manifest["version"]
        ):
            raise ValueError("图谱目录与版本不一致")
        for name in DATA_FILES:
            if digest_file(directory / name) != manifest["files"][name]["sha256"]:
                raise ValueError(f"图谱文件SHA256不一致: {name}")
        quality = json.loads((directory / "quality.json").read_text(encoding="utf-8"))
        by_appid = None
        candidates = set()
        expected_items = Counter()
        expected_aliases = None
        if rows is not None:
            validate_appids(rows)
            by_appid = {row["appid"]: row for row in rows}
            candidates = {row["appid"] for row in candidate_rows(rows)}
            expected_quality, expected_aliases = _source_quality(
                rows, candidates, binding
            )
            if expected_quality != quality:
                raise ValueError("质量台账/候选统计/原始位置与快照不一致")
            expected_items = Counter(
                {
                    field: value["valid_items"]
                    for field, value in expected_quality["fields"].items()
                }
            )
        nodes = {}
        types = Counter(
            {kind: 0 for kind in ["Game", *(spec[0] for spec in FIELDS.values())]}
        )
        candidate_count = 0
        for node in _records(directory / "entities.jsonl"):
            kind = node["entity_type"]
            types[kind] += 1
            if kind == "Game":
                appid = node["appid"]
                if (
                    not isinstance(appid, int)
                    or isinstance(appid, bool)
                    or appid <= 0
                    or node["id"] != f"game:{appid}"
                ):
                    raise ValueError("游戏ID不合法")
                candidate_count += bool(node["recommendation_eligible"])
                if by_appid is not None and (
                    appid not in by_appid
                    or node != game_entity(by_appid[appid], candidates)
                ):
                    raise ValueError("游戏属性/候选规则与快照不一致")
                nodes[node["id"]] = (kind, appid, node["canonical_key"])
            else:
                field = next(
                    (key for key, value in FIELDS.items() if value[0] == kind), None
                )
                if (
                    field is None
                    or node["id"] != entity_id(field, node["canonical_key"])
                    or not node["canonical_key"]
                ):
                    raise ValueError("名称实体ID或类型不一致")
                if not node["raw_names"] or any(
                    canonical_name(field, value) != node["canonical_key"]
                    for value in node["raw_names"]
                ):
                    raise ValueError("名称实体原名不一致")
                if node["display_name"] != min(
                    value.strip() for value in node["raw_names"]
                ):
                    raise ValueError("名称实体展示名不一致")
                if expected_aliases is not None and node[
                    "raw_names"
                ] != expected_aliases.get(node["id"]):
                    raise ValueError("名称实体原名集合未完整保留快照")
                nodes[node["id"]] = (kind, None, node["canonical_key"])
        predicates = Counter({spec[2]: 0 for spec in FIELDS.values()})
        covered = {field: set() for field in FIELDS}
        evidence_count = Counter()
        for ordinal, relation in enumerate(_records(directory / "relations.jsonl"), 1):
            subject, predicate, target = (
                relation[key] for key in ("subject", "predicate", "object")
            )
            field = next(
                (key for key, value in FIELDS.items() if value[2] == predicate), None
            )
            if field is None or subject not in nodes or target not in nodes:
                raise ValueError("未知关系或悬空边")
            if nodes[subject][0] != "Game" or nodes[target][0] != FIELDS[field][0]:
                raise ValueError("关系方向/端点类型错误")
            if (
                relation["id"] != edge_id(subject, predicate, target)
                or relation.get("relation_kind") != "source_fact"
                or "score" in relation
            ):
                raise ValueError("边ID/事实关系不一致")
            if any(
                relation[key] != binding[key]
                for key in ("snapshot_version", "snapshot_sha256")
            ):
                raise ValueError("关系快照绑定不一致")
            proofs = relation["evidence"]
            if not proofs or [p["array_index"] for p in proofs] != sorted(
                {p["array_index"] for p in proofs}
            ):
                raise ValueError("证据为空/重复位置/未排序")
            appid = nodes[subject][1]
            for proof in proofs:
                if (
                    proof["appid"] != appid
                    or proof["snapshot_field"] != field
                    or proof["source_event_time"] is not None
                ):
                    raise ValueError("证据身份/来源时间不一致")
                if by_appid is not None:
                    row = by_appid[appid]
                    index = proof["array_index"]
                    if (
                        not isinstance(index, int)
                        or isinstance(index, bool)
                        or index < 0
                    ):
                        raise ValueError("非法证据位置")
                    original = row[field][index]
                    if field == "tags" and (
                        not isinstance(original, dict)
                        or original.get("source") != "steamspy"
                        or original.get("kind") != "theme"
                    ):
                        raise ValueError("越界标签来源不能生成事实边")
                    raw = original["tag"] if field == "tags" else original
                    if (
                        not isinstance(raw, str)
                        or not canonical_name(field, raw)
                        or entity_id(field, raw) != target
                        or proof
                        != make_evidence(
                            row,
                            field,
                            {"index": index, "raw": raw, "raw_item": original},
                        )
                    ):
                        raise ValueError("证据原值/字段无法回查快照")
                evidence_count[field] += 1
            predicates[predicate] += 1
            covered[field].add(appid)
            if ordinal % 200000 == 0:
                logger.info("已完整核验 %s 条事实关系", ordinal)
        stats = {
            "entities": sum(types.values()),
            "entities_by_type": dict(sorted(types.items())),
            "relations": sum(predicates.values()),
            "relations_by_type": dict(sorted(predicates.items())),
            "candidates": candidate_count,
            "evidence_items": sum(evidence_count.values()),
        }
        if stats != manifest["statistics"]:
            raise ValueError("manifest统计与文件不一致")
        if (
            quality["games"] != types["Game"]
            or quality["candidates"] != candidate_count
        ):
            raise ValueError("质量报告游戏/候选计数不一致")
        for field, spec in FIELDS.items():
            saved = quality["fields"][field]
            if (
                saved["covered_rows"] != len(covered[field])
                or saved["unique_edges"] != predicates[spec[2]]
                or saved["valid_items"] != evidence_count[field]
                or saved["distinct_entity_keys"] != types[spec[0]]
            ):
                raise ValueError("质量报告关系计数不一致")
        if by_appid is not None and (
            evidence_count != expected_items
            or types["Game"] != len(rows)
            or candidate_count != len(candidates)
        ):
            raise ValueError("图谱未完整覆盖快照有效关系")
        if expected_aliases is not None and set(nodes) != set(expected_aliases) | {
            f"game:{appid}" for appid in by_appid
        }:
            raise ValueError("名称实体/游戏集合未完整覆盖快照")
        return {
            "version": manifest["version"],
            "statistics": stats,
            "verified_files": len(DATA_FILES),
            "source_replayed": rows is not None,
            "dangling_edges": 0,
            "duplicate_edges": 0,
        }
    except (
        OSError,
        KeyError,
        TypeError,
        IndexError,
        StopIteration,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(f"图谱数据/manifest损坏: {exc}") from exc


def publish_graph(rows: list[dict], binding: dict, folder: Path) -> dict:
    """在同盘临时目录构建并验收，拒绝覆盖任意旧版本内容。"""
    from .knowledge_graph import FIELDS, digest_file, graph_version

    version = graph_version(binding)
    destination = folder / version
    if destination.exists():
        verify_graph(destination, rows=rows)
        manifest = json.loads(
            (destination / "manifest.json").read_text(encoding="utf-8")
        )
        if manifest["binding"] != binding:
            raise ValueError("图谱版本绑定冲突，拒绝覆盖")
        return manifest
    folder.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=folder, prefix=".staging-") as temporary:
        stage = Path(temporary)
        quality = write_sorted(stage, rows, binding)
        fields = quality["fields"]
        types = {
            "Game": len(rows),
            **{
                spec[0]: fields[field]["distinct_entity_keys"]
                for field, spec in FIELDS.items()
            },
        }
        predicates = {
            spec[2]: fields[field]["unique_edges"] for field, spec in FIELDS.items()
        }
        manifest = {
            "version": version,
            "binding": binding,
            "files": {
                name: {"sha256": digest_file(stage / name)} for name in DATA_FILES
            },
            "statistics": {
                "entities": sum(types.values()),
                "entities_by_type": dict(sorted(types.items())),
                "relations": sum(predicates.values()),
                "relations_by_type": dict(sorted(predicates.items())),
                "candidates": quality["candidates"],
                "evidence_items": sum(f["valid_items"] for f in fields.values()),
            },
        }
        _write_json(stage / "manifest.json", manifest)
        verify_graph(stage, rows=rows)
        try:
            os.rename(stage, destination)
        except FileExistsError:
            verify_graph(destination, rows=rows)
            existing = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            if existing != manifest:
                raise ValueError("并发发布的版本内容不同，拒绝覆盖")
            return existing
    return manifest
