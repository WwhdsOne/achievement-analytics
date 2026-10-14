"""2–3游戏联合查询：共同IDF参考库、每种子等权均值与完整来源解释。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import heapq
import itertools
import json
import math
import re
from collections import Counter
from pathlib import Path

from .graph_recommender import GraphRecommender
from .knowledge_graph import FIELDS, GRAPHS, digest_file, json_text
from .knowledge_graph_inspector import GraphInspector
from .snapshot import SNAPSHOTS


class MultiGameRecommender:
    """复用已验证的事实索引；联合分数不改写事实边或单种子算法。"""

    def __init__(self, base: GraphRecommender) -> None:
        self.base = base
        self.binding = copy.deepcopy(base.binding)
        self.binding.update(algorithm="multi-game-equal-mean-v1", base_algorithm_version=base.algorithm_version,
                            idf_reference="eligible_candidates_excluding_all_unique_query_seeds",
                            seed_policy="validate_then_deduplicate_sort_2_or_3_eligible_integer_appids",
                            aggregation="equal_mean_over_all_unique_seeds_including_zero_scores",
                            candidate_policy="union_positive_weight_postings_no_per_seed_top_k_truncation",
                            tradeoff_policy="disjoint_nonempty_tags_or_genres_are_potential_only_no_penalty")
        self.binding["source_sha256"][Path(__file__).name] = digest_file(Path(__file__))
        self.algorithm_version = "multi-score-v1-" + hashlib.sha256(json_text(self.binding).encode("utf-8")).hexdigest()

    def _profile(self, seeds: list[int]) -> dict:
        relations, tradeoffs = {}, []
        for field in FIELDS:
            groups = {seed: self.base.relations[seed][field] for seed in seeds}
            counts = Counter(entity for group in groups.values() for entity in group)

            def describe(entity: str) -> dict:
                return {"id": entity, "name": self.base.inspector.entities[entity]["display_name"],
                        "seed_appids": [seed for seed in seeds if entity in groups[seed]]}

            relations[field] = {
                "common_all": [describe(e) for e in sorted(counts) if counts[e] == len(seeds)],
                "common_some": [describe(e) for e in sorted(counts) if 1 < counts[e] < len(seeds)],
                "unique_by_seed": {str(seed): [describe(e) for e in sorted(groups[seed]) if counts[e] == 1] for seed in seeds},
                "missing_seed_appids": [seed for seed in seeds if not groups[seed]],
            }
            if field in ("tags", "genres"):
                for left, right in itertools.combinations(seeds, 2):
                    if groups[left] and groups[right] and not groups[left] & groups[right]:
                        tradeoffs.append({"field": field, "seed_appids": [left, right],
                                          "reason": "两种子的该关系集合均非空且无交集；只是潜在取舍，不能证明玩法互斥或用户厌恶。"})
        return {"relations": relations, "potential_tradeoffs": tradeoffs,
                "evidence_note": "共同关系与特有关系均来自种子事实；缺失为证据不足。差异不额外扣分；这不是学习所得的用户画像。"}

    def recommend(self, seeds: list[int] | tuple[int, ...], top_k: int = 5) -> dict:
        """按唯一种子等权融合全候选池，返回每种子/关系/路径的原分与联合贡献。"""
        base = self.base
        base.inspector._check_unchanged()
        if (not isinstance(seeds, (list, tuple)) or any(not isinstance(s, int) or isinstance(s, bool)
                                                      or s not in base.rows for s in seeds)):
            raise ValueError("种子须为通过原候选规则的整数appid列表")
        seeds = sorted(set(seeds))
        if not 2 <= len(seeds) <= 3:
            raise ValueError("去重后须有2–3个有效游戏种子")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 100:
            raise ValueError("top-k须为1–100的整数")
        reference, seed_weight = len(base.rows) - len(seeds), 1 / len(seeds)
        excluded = {field: Counter(e for seed in seeds for e in base.relations[seed][field]) for field in FIELDS}
        cache = {}

        def frequency(field: str, entity: str) -> int:
            return base.frequency[field][entity] - excluded[field][entity]

        def idf(field: str, entity: str) -> float:
            key = field, entity
            if key not in cache:
                cache[key] = math.log((reference + 1) / (frequency(field, entity) + 1)) + 1
            return cache[key]

        pool = set()
        for seed in seeds:
            for field, weight in base.weights.items():
                if weight > 0:
                    for entity in base.relations[seed][field]:
                        pool.update(base.postings[field][entity])
        pool.difference_update(seeds)

        def ranking():
            for candidate in sorted(pool):
                scores = [math.fsum(c["weighted_score"] for c in base._components(seed, candidate, idf).values()) for seed in seeds]
                score = math.fsum(value * seed_weight for value in scores)
                if score > 0:
                    yield -score, candidate

        results = []
        for negative_score, candidate in heapq.nsmallest(top_k, ranking()):
            contributions = []
            for seed in seeds:
                components = base._components(seed, candidate, idf)
                facts = base.inspector.inspect_pair(seed, candidate)
                proofs = {(p["predicate"], p["entity"]["id"]): p for p in facts["paths"]}
                for field, component in components.items():
                    def describe(entity: str) -> dict:
                        return {"id": entity, "name": base.inspector.entities[entity]["display_name"],
                                "idf": idf(field, entity), "document_frequency": frequency(field, entity)}

                    for key, dest in (("union_ids", "union_entity_weights"), ("query_only_ids", "query_only_entities"),
                                      ("candidate_only_ids", "candidate_only_entities")):
                        component[dest] = [describe(e) for e in component.pop(key)]
                    component["joint_contribution"] = component["weighted_score"] * seed_weight
                    component["paths"] = []
                    for entity in component.pop("shared_ids"):
                        raw = base.weights[field] * idf(field, entity) / component["denominator"]
                        component["paths"].append({**proofs[FIELDS[field][2], entity], "kind": "computed_joint_scored_path",
                            "seed_appid": seed, "idf": idf(field, entity), "document_frequency": frequency(field, entity),
                            "relation_weight": base.weights[field], "seed_weight": seed_weight,
                            "used_for_score": component["used_for_score"], "contribution": raw,
                            "joint_contribution": raw * seed_weight})
                score = math.fsum(c["weighted_score"] for c in components.values())
                contributions.append({"appid": seed, "score": score, "weight": seed_weight,
                                      "contribution": score * seed_weight, "relations": components})
            supported = [s["appid"] for s in contributions if s["score"] > 0]
            unsupported = [s for s in seeds if s not in supported]
            results.append({"appid": candidate, "name": base.inspector.entities[f"game:{candidate}"]["display_name"],
                "score": -negative_score, "seed_contributions": contributions,
                "relation_contributions": {f: math.fsum(s["relations"][f]["joint_contribution"] for s in contributions) for f in FIELDS},
                "supported_seed_appids": supported, "unsupported_seed_appids": unsupported,
                "evidence_note": f"种子{supported}提供正贡献；种子{unsupported}无正贡献且保留零分份额。等权平均允许部分匹配；共同/特有关系见查询画像。同开发商或发行商不等于玩法相似；权重未经人工效果验证。",
                "relation_kind": "algorithm_similarity", "facts_unchanged": True})
        profile = self._profile(seeds)
        base.inspector._check_unchanged()
        return {"algorithm_version": self.algorithm_version, "binding": copy.deepcopy(self.binding),
                "graph_version": base.inspector.manifest["version"], "query_appids": seeds,
                "candidate_games": len(base.rows), "idf_reference_games": reference, "top_k": top_k,
                "preference_profile": profile, "results": results,
                "empty_reason": "没有其他有效候选或无共享正权重关系；不生成任意fallback。" if not results else None}


def main() -> None:
    """独立离线入口；读取冻结图谱，只允许新建或复核相同输出。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--appids", type=int, nargs="+", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--folder", type=Path, default=GRAPHS)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"kg-v1-[a-f0-9]{64}", args.version):
        parser.error("无效图谱版本")
    engine = MultiGameRecommender(GraphRecommender(GraphInspector(args.folder / args.version, snapshots=args.snapshots)))
    report = engine.recommend(args.appids, args.top_k)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            if args.output.read_text(encoding="utf-8") != payload:
                raise ValueError("已有不同内容，拒绝覆盖，请使用新输出路径")
        else:
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        print(json_text({"output": str(args.output), "algorithm_version": report["algorithm_version"],
                         "results": [{"appid": r["appid"], "score": r["score"]} for r in report["results"]]}))
    else:
        print(payload)


if __name__ == "__main__":
    main()
