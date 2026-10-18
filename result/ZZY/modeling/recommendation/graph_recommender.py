"""固定权重的多关系IDF-Jaccard；仅离线单游戏查询，不替换标签基线。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import heapq
import json
import logging
import math
import re
from collections import defaultdict
from pathlib import Path
from types import MappingProxyType

from . import (
    baseline,
    knowledge_graph,
    knowledge_graph_inspector,
    knowledge_graph_store,
    snapshot,
)
from .baseline import candidate_rows
from .knowledge_graph import FIELDS, GRAPHS, digest_file, json_text
from .knowledge_graph_inspector import FIELD_LABELS, GraphInspector

ALGORITHM = "multi-relation-idf-jaccard-v1"
DEFAULT_WEIGHTS = MappingProxyType(
    dict(tags=0.75, genres=0.15, developers=0.10, publishers=0.0)
)


def validate_weights(weights: dict | None) -> dict:
    """所有关系显式赋权，拒绝负数、非有限值和非单位权重和。"""
    selected = dict(DEFAULT_WEIGHTS) if weights is None else dict(weights)
    if set(selected) != set(FIELDS) or any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
        for value in selected.values()
    ):
        raise ValueError("四类关系权重必须是有限非负数")
    if not math.isclose(math.fsum(selected.values()), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("关系权重之和必须为1")
    return {field: float(selected[field]) for field in FIELDS}


class GraphRecommender:
    """从已验证事实图谱建立候选倒排索引，返回分数与完整路径证据。"""

    def __init__(self, inspector: GraphInspector, weights: dict | None = None) -> None:
        self.weights = MappingProxyType(validate_weights(weights))
        self.inspector = inspector
        inspector._check_unchanged()
        self.rows = {
            row["appid"]: row for row in candidate_rows(list(inspector._rows.values()))
        }
        flagged = {
            node["appid"]
            for node in inspector.entities.values()
            if node["entity_type"] == "Game" and node["recommendation_eligible"]
        }
        if flagged != self.rows.keys():
            raise ValueError("候选规则与图谱标记不一致")
        self.relations = {
            appid: {field: set() for field in FIELDS} for appid in self.rows
        }
        by_predicate = {spec[2]: field for field, spec in FIELDS.items()}
        relation_digest = hashlib.sha256()
        with (inspector.directory / "relations.jsonl").open("rb") as handle:
            for line in handle:
                relation_digest.update(line)
                edge = json.loads(line)
                appid = int(edge["subject"].removeprefix("game:"))
                if appid in self.rows:
                    field = by_predicate[edge["predicate"]]
                    target = inspector.entities[edge["object"]]["id"]
                    self.relations[appid][field].add(target)
        if (
            relation_digest.hexdigest()
            != inspector.manifest["files"]["relations.jsonl"]["sha256"]
        ):
            raise ValueError("图谱关系文件SHA256变化，拒绝建立评分频率索引")
        self.postings = {field: defaultdict(set) for field in FIELDS}
        for appid, relations in self.relations.items():
            for field, entities in relations.items():
                for entity in entities:
                    self.postings[field][entity].add(appid)
        self.frequency = {
            field: {entity: len(games) for entity, games in postings.items()}
            for field, postings in self.postings.items()
        }
        self.binding = {
            "algorithm": ALGORITHM,
            "graph_version": inspector.manifest["version"],
            "graph_manifest_sha256": digest_file(inspector.directory / "manifest.json"),
            "snapshot_version": inspector.manifest["binding"]["snapshot_version"],
            "snapshot_sha256": inspector.manifest["binding"]["snapshot_sha256"],
            "weights": dict(self.weights),
            "idf_reference": "eligible_candidates_excluding_query_seed",
            "missing_policy": "fixed_weights_zero_missing_no_renormalization",
            "tie_break": "score_desc_appid_asc",
            "weight_evidence": "heuristic_initial_not_effect_validated",
            "source_sha256": {
                "graph_recommender.py": digest_file(Path(__file__)),
                **{
                    Path(module.__file__).name: digest_file(Path(module.__file__))
                    for module in (
                        baseline,
                        knowledge_graph,
                        knowledge_graph_store,
                        knowledge_graph_inspector,
                        snapshot,
                    )
                },
            },
        }
        self.algorithm_version = (
            "graph-score-v1-"
            + hashlib.sha256(json_text(self.binding).encode("utf-8")).hexdigest()
        )
        inspector._check_unchanged()

    def _components(self, appid: int, candidate: int, idf) -> dict:
        components = {}
        for field in FIELDS:
            query = self.relations[appid][field]
            target = self.relations[candidate][field]
            shared, union = sorted(query & target), sorted(query | target)
            numerator = math.fsum(idf(field, entity) for entity in shared)
            denominator = math.fsum(idf(field, entity) for entity in union)
            similarity = numerator / denominator if denominator else 0.0
            status = (
                "both_missing"
                if not query and not target
                else "seed_missing"
                if not query
                else "candidate_missing"
                if not target
                else "no_shared"
                if not shared
                else "matched"
            )
            components[field] = {
                "weight": self.weights[field],
                "status": status,
                "used_for_score": self.weights[field] > 0,
                "seed_entity_count": len(query),
                "candidate_entity_count": len(target),
                "shared_entity_count": len(shared),
                "numerator": numerator,
                "denominator": denominator,
                "similarity": similarity,
                "weighted_score": self.weights[field] * similarity,
                "shared_ids": shared,
                "union_ids": union,
                "query_only_ids": sorted(query - target),
                "candidate_only_ids": sorted(target - query),
            }
        return components

    def recommend(self, appid: int, top_k: int = 5) -> dict:
        """单种子Top-k；正贡献排序、自身排除、全部关系及路径可独立复算。"""
        self.inspector._check_unchanged()
        if (
            not isinstance(appid, int)
            or isinstance(appid, bool)
            or appid not in self.rows
            or not isinstance(top_k, int)
            or isinstance(top_k, bool)
            or not 1 <= top_k <= 100
        ):
            raise ValueError("种子须通过原候选规则，top-k须为1–100的整数")
        reference = len(self.rows) - 1
        cache = {}

        def idf(field: str, entity: str) -> float:
            key = (field, entity)
            if key not in cache:
                df = self.frequency[field][entity] - int(
                    entity in self.relations[appid][field]
                )
                cache[key] = math.log((reference + 1) / (df + 1)) + 1
            return cache[key]

        pool = set()
        for field, weight in self.weights.items():
            if weight > 0:
                for entity in self.relations[appid][field]:
                    pool.update(self.postings[field][entity])
        pool.discard(appid)

        def ranking():
            for candidate in sorted(pool):
                components = self._components(appid, candidate, idf)
                score = math.fsum(
                    component["weighted_score"] for component in components.values()
                )
                if score > 0:
                    yield -score, candidate

        results = []
        for negative_score, candidate in heapq.nsmallest(top_k, ranking()):
            components = self._components(appid, candidate, idf)
            facts = self.inspector.inspect_pair(appid, candidate)
            proofs = {
                (path["predicate"], path["entity"]["id"]): path
                for path in facts["paths"]
            }
            for field, component in components.items():

                def describe(entity: str) -> dict:
                    return {
                        "id": entity,
                        "name": self.inspector.entities[entity]["display_name"],
                        "idf": idf(field, entity),
                        "document_frequency": self.frequency[field][entity]
                        - int(entity in self.relations[appid][field]),
                    }

                component["union_entity_weights"] = [
                    describe(entity) for entity in component.pop("union_ids")
                ]
                component["query_only_entities"] = [
                    describe(entity) for entity in component.pop("query_only_ids")
                ]
                component["candidate_only_entities"] = [
                    describe(entity) for entity in component.pop("candidate_only_ids")
                ]
                component["paths"] = []
                for entity in component.pop("shared_ids"):
                    proof = proofs[(FIELDS[field][2], entity)]
                    component["paths"].append(
                        {
                            **proof,
                            "kind": "computed_scored_path",
                            "idf": idf(field, entity),
                            "document_frequency": self.frequency[field][entity] - 1,
                            "relation_weight": self.weights[field],
                            "used_for_score": component["used_for_score"],
                            "contribution": self.weights[field]
                            * idf(field, entity)
                            / component["denominator"],
                        }
                    )
            shared_tags = components["tags"]["shared_entity_count"]
            support = "、".join(
                f"{FIELD_LABELS[field]}(权重{component['weight']:g}，贡献{component['weighted_score']:.6g})"
                for field, component in components.items()
                if component["weighted_score"] > 0
            )
            note = (
                ("没有共同标签；" if not shared_tags else "")
                + "本次正贡献："
                + support
                + "。同开发商或同发行商不等于玩法相似；权重为人为配置，尚未通过人工效果验证。"
            )
            results.append(
                {
                    "appid": candidate,
                    "name": self.inspector.entities[f"game:{candidate}"][
                        "display_name"
                    ],
                    "score": -negative_score,
                    "relations": components,
                    "shared_tag_count": shared_tags,
                    "evidence_note": note,
                    "relation_kind": "algorithm_similarity",
                    "facts_unchanged": True,
                }
            )
        self.inspector._check_unchanged()
        return {
            "algorithm_version": self.algorithm_version,
            "binding": copy.deepcopy(self.binding),
            "graph_version": self.inspector.manifest["version"],
            "query_appid": appid,
            "candidate_games": len(self.rows),
            "idf_reference_games": reference,
            "top_k": top_k,
            "results": results,
            "empty_reason": "无共享的正权重关系，或没有其他有效候选；不生成任意fallback。"
            if not results
            else None,
        }


def main() -> None:
    """独立CLI；只读取指定图谱和快照，可将完整解释保存为新证据文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--appid", type=int, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--folder", type=Path, default=GRAPHS)
    parser.add_argument("--snapshots", type=Path, default=snapshot.SNAPSHOTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"kg-v1-[a-f0-9]{64}", args.version):
        parser.error("无效图谱版本")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = GraphRecommender(
        GraphInspector(args.folder / args.version, snapshots=args.snapshots)
    )
    report = engine.recommend(args.appid, args.top_k)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            if args.output.read_text(encoding="utf-8") != payload:
                raise ValueError("已有不同内容，拒绝覆盖，请使用新输出路径")
        else:
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "algorithm_version": report["algorithm_version"],
                    "results": [
                        {"appid": result["appid"], "score": result["score"]}
                        for result in report["results"]
                    ],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(payload)


if __name__ == "__main__":
    main()
