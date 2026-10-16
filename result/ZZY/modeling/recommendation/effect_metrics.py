"""Frozen effect-v1 query-level metrics; no label generation or ranking."""

from __future__ import annotations

import math
import random
from statistics import fmean

METHODS = ("tag_jaccard", "graph_full", "graph_no_developer", "graph_no_genre")
METRICS = ("P@5", "strict_P@5", "pool_nDCG@5")


def pools(protocol: dict, rankings: dict) -> dict[str, set[int]]:
    """Validate the entire four-method layout and return each query's union."""
    if protocol["top_k"] != 5 or tuple(m["id"] for m in protocol["methods"]) != METHODS:
        raise ValueError("只支持冻结四方法Top-5")
    queries = protocol["final_queries"]
    if (
        not queries
        or len({q["id"] for q in queries}) != len(queries)
        or [q["id"] for q in queries] != [q["query_id"] for q in rankings["queries"]]
    ):
        raise ValueError("查询不一致或重复")
    result = {}
    for q, report in zip(queries, rankings["queries"]):
        if report["seed_appid"] != q["seeds"][0] or set(report["methods"]) != set(
            METHODS
        ):
            raise ValueError("种子或方法不一致")
        union = set()
        for method in METHODS:
            rows = report["methods"][method]["results"]
            ids = [row["appid"] for row in rows]
            if (
                len(rows) > 5
                or len(set(ids)) != len(ids)
                or any(
                    type(i) is not int or i <= 0 or i == report["seed_appid"]
                    for i in ids
                )
                or any(
                    type(row["score"]) not in (int, float)
                    or not math.isfinite(row["score"])
                    or row["score"] <= 0
                    for row in rows
                )
                or rows != sorted(rows, key=lambda row: (-row["score"], row["appid"]))
            ):
                raise ValueError("排名重复/非法/次序错误")
            union.update(ids)
        result[q["id"]] = union
    return result


def bootstrap(differences: list[float]) -> dict:
    """Exactly 2000 paired-query draws using stdlib Random(42), linear quantiles."""
    if not differences:
        return {
            "queries": 0,
            "mean_difference": None,
            "query_bootstrap_descriptive_interval95": [None, None],
            "degenerate_n1": False,
        }
    rng = random.Random(42)
    n = len(differences)
    samples = sorted(
        sum(differences[rng.randrange(n)] for _ in range(n)) / n for _ in range(2000)
    )
    bounds = []
    for p in (0.025, 0.975):
        position = (len(samples) - 1) * p
        lo, hi = math.floor(position), math.ceil(position)
        bounds.append(samples[lo] + (samples[hi] - samples[lo]) * (position - lo))
    return {
        "queries": n,
        "mean_difference": fmean(differences),
        "query_bootstrap_descriptive_interval95": bounds,
        "degenerate_n1": n == 1,
    }


def calculate(
    protocol: dict, rankings: dict, labels: dict[tuple[str, int], int | str]
) -> dict:
    """Compute only after all unique pairs have valid labels, including unknown."""
    union = pools(protocol, rankings)
    keys = {(q, i) for q, ids in union.items() for i in ids}
    if not labels:
        raise ValueError("没有真实人工标签，不能计算效果成绩")
    if keys != set(labels) or any(
        not (type(v) is int and v in (0, 1, 2) or v == "unknown")
        for v in labels.values()
    ):
        raise ValueError("缺少/多余/非法或空白标签，拒绝计算")
    per_query = []
    for q, ranking in zip(protocol["final_queries"], rankings["queries"]):
        qid = q["id"]
        values = [labels[qid, i] for i in sorted(union[qid])]
        complete = "unknown" not in values
        ideal = sorted(values, reverse=True)[:5] if complete else []
        idcg = (
            sum((2**v - 1) / math.log2(i + 2) for i, v in enumerate(ideal))
            if complete
            else None
        )
        methods = {}
        for method in METHODS:
            rel = [
                labels[qid, row["appid"]]
                for row in ranking["methods"][method]["results"]
            ]
            lower = sum(type(v) is int and v >= 1 for v in rel) / 5
            strict = sum(v == 2 for v in rel) / 5
            unknown = rel.count("unknown") / 5
            dcg = (
                sum((2**v - 1) / math.log2(i + 2) for i, v in enumerate(rel))
                if complete
                else None
            )
            methods[method] = {
                "returned_slots": len(rel),
                "empty_slots": 5 - len(rel),
                "P@5": lower if complete else None,
                "strict_P@5": strict if complete else None,
                "pool_nDCG@5": (dcg / idcg if idcg else 0.0) if complete else None,
                "P@5_bounds": [lower, lower + unknown],
                "strict_P@5_bounds": [strict, strict + unknown],
            }
        per_query.append(
            {
                "query_id": qid,
                "stratum": q["genre_bucket"] + "/" + q["tag_density"],
                "complete": complete,
                "unique_pairs": len(values),
                "unknown_pairs": values.count("unknown"),
                "idcg": idcg,
                "methods": methods,
            }
        )

    def summarize(group: list[dict]) -> dict:
        complete = [q for q in group if q["complete"]]
        methods = {}
        for method in METHODS:
            slots = sum(q["methods"][method]["returned_slots"] for q in group)
            methods[method] = {
                name: fmean(q["methods"][method][name] for q in complete)
                if complete
                else None
                for name in METRICS
            }
            methods[method].update(
                returned_slots=slots,
                available_slots=5 * len(group),
                return_rate=slots / (5 * len(group)),
                empty_slot_rate=1 - slots / (5 * len(group)),
            )
            for name in ("P@5", "strict_P@5"):
                methods[method]["all_query_" + name + "_bounds"] = [
                    fmean(q["methods"][method][name + "_bounds"][side] for q in group)
                    for side in (0, 1)
                ]
        comparisons = {}
        for other in (METHODS[0], *METHODS[2:]):
            name = "graph_full-" + other
            differences = {
                metric: [
                    q["methods"]["graph_full"][metric] - q["methods"][other][metric]
                    for q in complete
                ]
                for metric in METRICS
            }
            comparisons[name] = {
                metric: bootstrap(values) for metric, values in differences.items()
            }
            comparisons[name]["per_query_differences"] = [
                {
                    "query_id": q["query_id"],
                    **{metric: differences[metric][i] for metric in METRICS},
                }
                for i, q in enumerate(complete)
            ]
        return {
            "total_queries": len(group),
            "complete_queries": len(complete),
            "complete_fraction": len(complete) / len(group),
            "methods": methods,
            "comparisons": comparisons,
        }

    summary = summarize(per_query)
    strata = {
        name: summarize([q for q in per_query if q["stratum"] == name])
        for name in sorted({q["stratum"] for q in per_query})
    }
    summary.update(
        schema_version="effect-metrics-v1",
        complete_query_ids=[q["query_id"] for q in per_query if q["complete"]],
        per_query=per_query,
        strata=strata,
        coverage={
            "total_queries": len(per_query),
            "unique_pairs": len(labels),
            "graded_pairs": sum(type(v) is int for v in labels.values()),
            "unknown_pairs": list(labels.values()).count("unknown"),
            "unknown_rate": list(labels.values()).count("unknown") / len(labels),
            "zero_idcg_queries": sum(q["idcg"] == 0 for q in per_query),
            "empty_pool_queries": sum(not union[q["query_id"]] for q in per_query),
        },
        incomplete_strata=[
            name for name, group in strata.items() if group["complete_queries"] < 2
        ],
        interpretation="小型分层查询的探索性人工相关性；非用户满意度或总体推广证明。上下界不是置信区间。",
    )
    return summary
