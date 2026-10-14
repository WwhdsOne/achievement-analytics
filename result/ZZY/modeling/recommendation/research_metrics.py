"""研究诊断指标；偏好匹配与标签重建均不等于用户满意度。"""

from __future__ import annotations

from collections import Counter
from statistics import median

import numpy as np

from .baseline import candidate_rows, tag_set


def review_count(row: dict) -> int | None:
    """只有两个评价计数都存在且非负时才计算总数。"""
    values = [row.get("positive"), row.get("negative")]
    return sum(values) if all(isinstance(v, int) and v >= 0 for v in values) else None


def tag_stratum(count: int) -> str:
    """分开无标签、单标签与可进行隐藏标签实验的四层。"""
    if count <= 1:
        return str(count)
    if count <= 5:
        return "2-5"
    if count <= 10:
        return "6-10"
    if count <= 19:
        return "11-19"
    return "20+"


def coverage_audit(rows: list[dict]) -> dict:
    """按快照全样本分组，保留各组分母与评价缺失。"""
    candidates = {row["appid"] for row in candidate_rows(rows)}
    tagged = {row["appid"] for row in rows if tag_set(row)}

    def summarize(selected: list[dict]) -> dict:
        reviews = [value for row in selected if (value := review_count(row)) is not None]
        count = len(selected)
        available = sum(row["appid"] in candidates for row in selected)
        return {"games": count, "candidates": available,
                "candidate_coverage": available / count if count else None,
                "tagged_games": sum(row["appid"] in tagged for row in selected),
                "known_review_games": len(reviews),
                "median_known_reviews": median(reviews) if reviews else None}

    def review_bin(row: dict) -> str:
        count = review_count(row)
        return "missing" if count is None else "0-99" if count < 100 else "100-999" if count < 1000 else "1000+"

    def era(row: dict) -> str:
        try:
            year = int(row["release_date"][:4])
            return "<=2014" if year <= 2014 else "2015-2019" if year <= 2019 else "2020-2025"
        except (TypeError, ValueError, KeyError):
            return "missing"

    result = {"all": summarize(rows), "included": summarize([r for r in rows if r["appid"] in candidates]),
              "excluded": summarize([r for r in rows if r["appid"] not in candidates])}
    for name, keys, classifier in (
        ("review_bins", ["missing", "0-99", "100-999", "1000+"], review_bin),
        ("release_eras", ["<=2014", "2015-2019", "2020-2025", "missing"], era),
        ("tag_count_bins", ["0", "1", "2-5", "6-10", "11-19", "20+"],
         lambda row: tag_stratum(len(tag_set(row)))),
    ):
        groups = {key: [] for key in keys}
        for row in rows:
            groups[classifier(row)].append(row)
        result[name] = {key: summarize(group) for key, group in groups.items()}
    missing_tags = [r for r in rows if not tag_set(r)]
    result["missing_tags_overlap"] = {
        "games": len(missing_tags),
        "missing_spy_timestamp": sum(not r.get("spy_fetched_at") for r in missing_tags),
        "missing_reviews": sum(review_count(r) is None for r in missing_tags),
        "no_achievements": sum(not r.get("ach_count") for r in missing_tags),
        "unresolved_mapping": sum(r.get("mapping_unresolved") is not False for r in missing_tags),
    }
    result["limits"] = ["评价量分组是当前快照热度代理，不是销量或历史热度。",
                        "标签缺失与年代/评价量关联不能证明原因。", "快照没有产品type字段，无法完整识别DLC/工具等非游戏条目。"]
    return result


def query_diagnostics(query: set[str], results: list[dict], labels: dict[int, set[str]], k: int = 5) -> dict:
    """只衡量返回结构与标签偏好满足；不产生推荐相关性Precision。"""
    top = results[:k]
    coverage = [len(query & labels[row["appid"]]) / len(query) for row in top] if query else []
    matched = sum(query <= labels[row["appid"]] for row in top) if query else 0
    return {"returned": len(top), "unique_returned": len({row["appid"] for row in top}),
            "all_requested_tags_count": matched, "all_requested_tags_at5": matched / k,
            "mean_query_tag_coverage": sum(coverage) / len(coverage) if coverage else None,
            "candidate_tag_counts": [len(labels[row["appid"]]) for row in top],
            "denominator_note": "all_requested_tags_at5固定除以5，短列表不自动提高分数"}


def paired_bootstrap(left: list[float], right: list[float], iterations: int = 2000,
                     strata: list[str] | None = None) -> dict:
    """配对重采样，给定层时保持各层样本数；区间仅用于本次样本诊断。"""
    if len(left) != len(right) or (strata is not None and len(strata) != len(left)):
        raise ValueError("配对样本长度不一致")
    if not left:
        return {"difference": None, "ci95": [None, None]}
    if iterations <= 0:
        raise ValueError("bootstrap次数必须为正")
    difference = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
    groups = [np.arange(len(left))] if strata is None else [
        np.array([i for i, value in enumerate(strata) if value == name]) for name in sorted(set(strata))
    ]
    rng = np.random.default_rng(42)
    samples = [float(np.concatenate([difference[rng.choice(group, len(group), replace=True)]
                                     for group in groups]).mean()) for _ in range(iterations)]
    return {"difference": float(difference.mean()),
            "ci95": [float(value) for value in np.quantile(samples, [.025, .975])]}


def reconstruction_summary(cases: list[dict]) -> dict:
    """汇总单隐藏标签Hit与截断MRR，不包装为推荐准确率。"""
    def summarize(group: list[dict]) -> dict:
        return {"n": len(group), **{key: sum(row[key] for row in group) / len(group) if group else None
                                   for key in ("neighbor_hit5", "popular_hit5", "neighbor_mrr10", "popular_mrr10")}}
    result = {"balanced_sample": summarize(cases), "by_stratum": {
        name: summarize([row for row in cases if row["stratum"] == name])
        for name in sorted({row["stratum"] for row in cases})}}
    result["paired_hit5_difference"] = paired_bootstrap(
        [r["neighbor_hit5"] for r in cases], [r["popular_hit5"] for r in cases],
        strata=[r["stratum"] for r in cases],
    )
    result["limits"] = ["每款只隐藏一个已有标签，Hit@5是标签重建命中，不是推荐Precision@5。",
                        "各标签量层等额抽样，整体均值不代表全库自然分布。",
                        "不同游戏可能同系列/同开发商；bootstrap未按系列聚类，区间可能偏窄。",
                        "剩余已知标签和其他游戏的完整标签可用；不测试未来新增游戏或真实用户行为。"]
    return result
