"""已验收图谱的只读质量及原始事实来源检查，不计算推荐分数。"""

from __future__ import annotations

import copy
import json
import logging
from collections import defaultdict
from pathlib import Path

from .knowledge_graph import FIELDS, edge_id, entity_id, make_evidence, parse_field, verify_graph
from .snapshot import SNAPSHOTS, load_snapshot

logger = logging.getLogger(__name__)
FIELD_LABELS = {"tags": "SteamSpy主题标签", "genres": "Steam官方类型", "developers": "开发商名称", "publishers": "发行商名称"}
RANKING_NOTE = "此页核查共同关系，不给推荐分数。现有推荐排序仍只使用标签；类型、开发商和发行商路径不表示已参与排序，也不证明玩法相似。"


class GraphInspector:
    """一次完整验证并建立字节位置索引，请求按需读取两款游戏的事实边。"""

    def __init__(self, directory: Path, *, snapshots: Path = SNAPSHOTS) -> None:
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        binding = self.manifest["binding"]
        snapshot_dir = Path(snapshots) / binding["snapshot_version"]
        self._files = [self.directory / name for name in ("entities.jsonl", "relations.jsonl", "quality.json", "manifest.json")]
        self._files += [snapshot_dir / name for name in ("games.json.gz", "manifest.json")]
        self._fingerprints = self._file_state()
        rows, metadata = load_snapshot(binding["snapshot_version"], snapshots)
        if metadata["sha256"] != binding["snapshot_sha256"]:
            raise ValueError("图谱与冻结快照SHA256不一致")
        logger.info("正在完整回查图谱事实来源与质量台账")
        self.validation = verify_graph(self.directory, rows=rows)
        self._rows = {row["appid"]: row for row in rows}
        self.quality = json.loads((self.directory / "quality.json").read_text(encoding="utf-8"))
        self.entities = {}
        with (self.directory / "entities.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                entity = json.loads(line)
                self.entities[entity["id"]] = entity
        self._offsets = defaultdict(list)
        logger.info("正在建立只读关系位置索引")
        with (self.directory / "relations.jsonl").open("rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                relation = json.loads(line)
                appid = int(relation["subject"].removeprefix("game:"))
                self._offsets[appid].append((offset, relation["id"]))
        self._check_unchanged()
        self.missing_examples = {}
        for field in FIELDS:
            examples = []
            for appid, row in sorted(self._rows.items()):
                if not parse_field(row, field)[0]:
                    examples.append({"appid": appid, "name": self.entities[f"game:{appid}"]["display_name"], "raw_value": row.get(field)})
                    if len(examples) == 3:
                        break
            self.missing_examples[field] = examples

    def _file_state(self) -> tuple:
        try:
            return tuple((path.stat().st_size, path.stat().st_mtime_ns) for path in self._files)
        except OSError as exc:
            raise ValueError("图谱或快照文件已变化，请重新启动核查服务") from exc

    def _check_unchanged(self) -> None:
        if self._file_state() != self._fingerprints:
            raise ValueError("图谱或快照文件已变化，请重新启动核查服务")

    def summary(self) -> dict:
        """提供完整质量记录，分别保留全快照与推荐候选分母。"""
        self._check_unchanged()
        return copy.deepcopy({"version": self.manifest["version"], "binding": self.manifest["binding"],
                              "statistics": self.manifest["statistics"], "quality": self.quality,
                              "validation": self.validation, "field_labels": FIELD_LABELS,
                              "missing_examples": self.missing_examples,
                              "relation_kinds": {"source_fact": "原始字段事实", "computed_shared_path": "查询计算的共同路径"},
                              "ranking_note": RANKING_NOTE})

    def _game_edges(self, appid: int) -> dict:
        result = {}
        row = self._rows[appid]
        expected = defaultdict(list)
        for field, spec in FIELDS.items():
            for item in parse_field(row, field)[0]:
                key = (spec[2], entity_id(field, item["raw"]))
                expected[key].append(make_evidence(row, field, item))
        with (self.directory / "relations.jsonl").open("rb") as handle:
            for offset, expected_id in self._offsets[appid]:
                handle.seek(offset)
                relation = json.loads(handle.readline())
                if relation["id"] != expected_id or relation["subject"] != f"game:{appid}":
                    raise ValueError("关系索引与原始事实不一致")
                if relation["id"] != edge_id(relation["subject"], relation["predicate"], relation["object"]):
                    raise ValueError("事实边标识不一致")
                key = (relation["predicate"], relation["object"])
                if relation.get("relation_kind") != "source_fact" or "score" in relation:
                    raise ValueError("计算相似度不能作为原始事实边")
                if any(relation.get(key) != self.manifest["binding"][key] for key in ("snapshot_version", "snapshot_sha256")):
                    raise ValueError("事实边的快照绑定不一致")
                if key not in expected or relation["evidence"] != expected[key]:
                    raise ValueError("关系证据不完整或无法回查冻结快照")
                relation["source_verified"] = True
                result[key] = relation
        if result.keys() != expected.keys():
            raise ValueError("游戏关系未完整覆盖冻结字段")
        return result

    def inspect_pair(self, left: int, right: int) -> dict:
        """返回全部共同路径及两端事实证据，明确无关系和缺失。"""
        self._check_unchanged()
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value not in self._rows for value in (left, right)) or left == right:
            raise ValueError("请输入两款不同且存在于冻结快照中的正整数appid")
        first, second = self._game_edges(left), self._game_edges(right)
        shared = first.keys() & second.keys()
        order = {spec[2]: index for index, spec in enumerate(FIELDS.values())}
        paths = [{"kind": "computed_shared_path", "predicate": predicate, "entity": self.entities[target],
                  "left_edge": first[(predicate, target)], "right_edge": second[(predicate, target)]}
                 for predicate, target in sorted(shared, key=lambda item: (order[item[0]], self.entities[item[1]]["display_name"], item[1]))]

        def details(appid: int, edges: dict) -> dict:
            entity = copy.deepcopy(self.entities[f"game:{appid}"])
            entity["missing_fields"] = [field for field, spec in FIELDS.items() if not any(key[0] == spec[2] for key in edges)]
            entity["unshared"] = {field: [self.entities[target]["display_name"] for predicate, target in sorted(edges.keys() - shared) if predicate == spec[2]]
                                  for field, spec in FIELDS.items()}
            return entity

        self._check_unchanged()
        return {"version": self.manifest["version"], "snapshot_version": self.manifest["binding"]["snapshot_version"],
                "kind": "computed_shared_paths", "left": details(left, first), "right": details(right, second),
                "paths": copy.deepcopy(paths), "ranking_note": RANKING_NOTE,
                "empty_reason": "没有共同关系路径；缺失不等于不存在此关系。" if not paths else None}
