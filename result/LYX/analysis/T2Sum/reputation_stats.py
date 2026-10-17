"""任务5游戏级统计：平均秩Spearman、成对重采样、透明的案例筛选。"""

from __future__ import annotations

from itertools import combinations
import statistics
from typing import Any

import numpy as np
from scipy.stats import rankdata

from reputation_data import Json, PROGRESS, SCORES, digest, finite

BOOTSTRAP = 2000
SEED = 42


def correlations(games: list[Json], scores: tuple[str, ...], cohort: str) -> tuple[list[Json], dict[tuple[str, str], Any]]:
    """Resample whole game rows jointly, reranking ties within each bootstrap sample."""
    fields = (*scores, *PROGRESS)
    matrix = np.array([[g[f] for f in fields] for g in games], dtype=float)
    if len(games) < 3 or not np.isfinite(matrix).all():
        raise ValueError("相关分析需要至少3款且字段全部有效")
    ranks = rankdata(matrix, axis=0)
    centered = ranks-ranks.mean(axis=0)
    indexes = np.random.default_rng(SEED).integers(0, len(games), size=(BOOTSTRAP, len(games)))
    sampled = rankdata(matrix[indexes], axis=1)
    sampled -= sampled.mean(axis=1, keepdims=True)
    results, draws = [], {}
    for score in scores:
        for metric in PROGRESS:
            i, j = fields.index(score), fields.index(metric)
            denom = np.sqrt((centered[:, i]**2).sum()*(centered[:, j]**2).sum())
            rho = float((centered[:, i]*centered[:, j]).sum()/denom) if denom > 0 else None
            a, b = sampled[:, :, i], sampled[:, :, j]
            d = np.sqrt((a*a).sum(axis=1)*(b*b).sum(axis=1))
            values = np.divide((a*b).sum(axis=1), d, out=np.full(BOOTSTRAP, np.nan), where=d > 0)
            valid = values[np.isfinite(values)]
            lo, hi = map(float, np.quantile(valid, [.025, .975])) if len(valid) else (None, None)
            results.append({"cohort": cohort, "score": score, "metric": metric, "n": len(games),
                            "spearman": rho, "interval_low": lo, "interval_high": hi,
                            "score_unique": len(set(g[score] for g in games)),
                            "valid_bootstrap_replicates": len(valid), "bootstrap": BOOTSTRAP, "random_state": SEED,
                            "appids_sha256": digest([g["appid"] for g in games])})
            draws[score, metric] = values
    return results, draws


def correlation_differences(rows: list[Json], draws: dict[tuple[str, str], Any]) -> list[Json]:
    """Compare coefficients only on the common games, pairing identical bootstrap draws."""
    lookup = {(r["score"], r["metric"]): r for r in rows}
    results = []
    for a, b in combinations(SCORES, 2):
        for metric in PROGRESS:
            delta = draws[a, metric]-draws[b, metric]
            valid = delta[np.isfinite(delta)]
            lo, hi = map(float, np.quantile(valid, [.025, .975])) if len(valid) else (None, None)
            rho_a, rho_b = lookup[a, metric]["spearman"], lookup[b, metric]["spearman"]
            results.append({"score_a": a, "score_b": b, "metric": metric, "n": lookup[a, metric]["n"],
                            "rho_a_minus_b": rho_a-rho_b if rho_a is not None and rho_b is not None else None,
                            "interval_low": lo, "interval_high": hi,
                            "valid_bootstrap_replicates": len(valid), "bootstrap": BOOTSTRAP, "random_state": SEED})
    return results


def quadrants(games: list[Json]) -> tuple[list[Json], list[Json], Json]:
    """Use frozen-cohort medians, including equality on the high side; select extreme cases transparently."""
    sx = statistics.median(g["steam_positive_ratio"] for g in games)
    sy = statistics.median(g["overall_progress_ratio"] for g in games)
    percentile_ranks = {field: (rankdata([g[field] for g in games])-.5)/len(games)
                        for field in (SCORES[0], PROGRESS[2])}
    case_scores = {g["appid"]: abs(percentile_ranks[SCORES[0]][i]-.5)*abs(percentile_ranks[PROGRESS[2]][i]-.5)
                   for i,g in enumerate(games)}
    summaries, cases = [], []
    for high_x, high_y in ((True,True),(True,False),(False,True),(False,False)):
        label = f"口碑{'≥' if high_x else '<'}样本中位数、推进{'≥' if high_y else '<'}样本中位数"
        members = [g for g in games if (g["steam_positive_ratio"] >= sx) == high_x
                   and (g["overall_progress_ratio"] >= sy) == high_y]
        summaries.append({"quadrant": label, "n": len(members), "steam_median": sx, "overall_median": sy,
                          "equality_rule": ">= belongs to high side", "appids": "|".join(str(g["appid"]) for g in members)})
        if members:
            # Product of within-cohort percentile distances prevents the two units dominating selection.
            ranked = sorted(members, key=lambda g: (-case_scores[g["appid"]], g["appid"]))
            cases.append({"case": chr(65+len(cases)), "quadrant": label,
                          "case_selection_score":float(case_scores[ranked[0]["appid"]]), **ranked[0]})
    return summaries, cases, {"steam_median": sx, "overall_median": sy}


def matched_cases(games: list[Json]) -> tuple[list[Json], list[Json]]:
    """Find all same-primary-type/same-ending pairs within a 1.25 main-hour ratio; rank by discordance."""
    pool = [g for g in games if g["hltb_main_hours"] is not None]
    candidates = []
    for a, b in combinations(pool, 2):
        ratio = max(a["hltb_main_hours"],b["hltb_main_hours"])/min(a["hltb_main_hours"],b["hltb_main_hours"])
        if a["primary_gameplay"] != b["primary_gameplay"] or a["ending_type"] != b["ending_type"] or ratio > 1.25:
            continue
        ds = a["steam_positive_ratio"]-b["steam_positive_ratio"]
        dp = a["overall_progress_ratio"]-b["overall_progress_ratio"]
        candidates.append({"appid_a": a["appid"], "name_a": a["name_en"], "appid_b": b["appid"], "name_b": b["name_en"],
                           "primary_gameplay": a["primary_gameplay"], "ending_type": a["ending_type"],
                           "main_hours_a":a["hltb_main_hours"], "main_hours_b":b["hltb_main_hours"], "hours_ratio":ratio,
                           "steam_a":a["steam_positive_ratio"],"steam_b":b["steam_positive_ratio"],
                           "overall_a":a["overall_progress_ratio"],"overall_b":b["overall_progress_ratio"],
                           "steam_gap_pp":abs(ds)*100,"overall_gap_pp":abs(dp)*100,
                           "discordant":ds*dp < 0, "discordance_product":max(0.,-ds*dp)})
    candidates.sort(key=lambda p: (-p["discordance_product"], -p["overall_gap_pp"], p["appid_a"], p["appid_b"]))
    chosen, used = [], set()
    for pair in candidates:
        ids = {pair["appid_a"], pair["appid_b"]}
        if pair["discordant"] and not ids & used and len(chosen) < 3:
            chosen.append(pair); used |= ids
    return candidates, chosen
