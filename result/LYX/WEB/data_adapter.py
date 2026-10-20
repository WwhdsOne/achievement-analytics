"""Read-only CSV adaptation for the LYX interactive project presentation.

The adapter uses only the standard library. It never opens a database, calls an
API, writes a cache, or reruns a statistical analysis. Ratios retain 0--1 units;
fields ending in _pp already contain percentage points.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

METRICS = ("p_s", "p_m", "p_f", "early_progress_ratio", "late_progress_ratio", "overall_progress_ratio")
PROGRESS = METRICS[3:]
INT_FIELDS = set("""
appid appid_a appid_b peer_appid local_id first_local_id middle_local_id end_local_id
source_checkpoint_index source_checkpoint_order sequence_position
first_source_checkpoint_index middle_source_checkpoint_index end_source_checkpoint_index
middle_sequence_position edge_position from_local_id to_local_id from_sequence_position
to_sequence_position from_source_checkpoint_index to_source_checkpoint_index
node_count node_count_a node_count_b node_count_gap edge_count common_checkpoint_count
end_candidate_count end_max_tie_count start_label_count bootstrap bootstrap_replicates
valid_bootstrap_replicates requested_bootstrap_replicates random_state n base reference_n
group_n tag_n background_n background_tag_n outside_n outside_tag_n score_unique
x_unique_values y_unique_values ratio_below_one ratio_at_least_one positive negative
review_count rawg_ratings_count rawg_ratings_count_raw peer_n known_issue_peer_n at_least10_peers selected_pair
candidate_rank pair frame_rank valid_ratio_count reverse_jump_count max_relative_tie_count
max_relative_edge_position max_coverage_gap_tie_count max_coverage_gap_edge_position
""".split())
FLOAT_FIELDS = set("""
confidence story_confidence from_confidence to_confidence rate from_rate to_rate
adjacent_progress_ratio relative_drop coverage_gap_pp gap_relative_to_first
from_node_fraction to_node_fraction interval_midpoint_fraction wwh_baseline_rate
wwh_completion_ratio median q1 q3 minimum maximum interval_low interval_high
cohort_median delta_to_cohort_pp reference_median delta_to_main_pp main_hours playtime original_main_hours original_playtime
time_ratio extra_hours extra_hours_ratio completionist_hours completionist_hours_ratio
lower_exclusive upper_inclusive spearman steam_positive_ratio metacritic_raw metacritic
rawg_rating_raw rawg_rating hltb_main_hours coverage steam_median overall_median
share background_share difference_pp lift_vs_background outside_share steam_min late_min
puzzle_share puzzle_lift main_hours_a main_hours_b hours_ratio steam_a steam_b overall_a
overall_b steam_gap_pp overall_gap_pp discordance_product jaccard median_peer_n
overall_ratio_a overall_ratio_b max_relative_position_gap concentration_gap
stage_absolute_difference_sum_pp adjacent_ratio_product max_gap_share
""".split()) | set(METRICS)
FLOAT_FIELDS.update(
    metric + suffix for metric in PROGRESS
    for suffix in ("_reference_q1", "_reference_median", "_reference_q3", "_delta", "_peer_percentile", "_a", "_b")
)
FLOAT_FIELDS.update(
    prefix + suffix for prefix in ("max_relative_", "max_coverage_gap_")
    for suffix in ("relative_drop", "coverage_gap_pp", "interval_midpoint_fraction")
)
BOOL_FIELDS = set("""
three_point_available model_all_later_requires_start is_in_sequence is_first is_middle
is_end requires_start to_requires_start is_max_relative_drop is_max_coverage_gap
eligible_main_plot time_order_anomaly reference_order_anomaly included complete_three_point
three_scores_common descriptive_support discordant product_consistent case_eligible
""".split())
LIST_FIELDS = {"gameplay_labels", "similarity_labels", "quality_flags", "manual_fields"}


def _sha(path: Path) -> str:
    """Read a digest without changing the file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _typed(row: dict[str, str]) -> dict[str, Any]:
    """Parse declared numeric columns without guessing string identifiers."""
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key in LIST_FIELDS:
            result[key] = value.split("|") if value else []
        elif key == "appids":
            result[key] = [int(item) for item in value.split("|")] if value else []
        elif value == "":
            result[key] = None
        elif key in BOOL_FIELDS:
            if value.lower() not in {"true", "false"}:
                raise ValueError(f"Invalid boolean: {key}={value!r}")
            result[key] = value.lower() == "true"
        elif key in INT_FIELDS or ((key.startswith("n_") or key.endswith("_n")) and key not in FLOAT_FIELDS):
            result[key] = int(value)
        elif key in FLOAT_FIELDS:
            parsed = float(value)
            if not math.isfinite(parsed):
                raise ValueError(f"Non-finite value: {key}={value!r}")
            result[key] = parsed
        else:
            result[key] = value
    return result


class _Sources:
    """Verify consumed CSV receipts and collect portable source fingerprints."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: dict[str, dict[str, Any]] = {}
        self.expected: dict[Path, str] = {}
        self.warnings: list[dict[str, Any]] = []
        self.verified = 0

    def inside(self, path: Path) -> Path:
        """Reject accidental reads outside the LYX workspace."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"Source escapes the LYX workspace: {path}")
        return resolved

    def record(self, path: Path, rows: int | None = None) -> None:
        """Capture actual path, digest and bytes, with optional CSV row count."""
        path = self.inside(path)
        relative = path.relative_to(self.root).as_posix()
        entry: dict[str, Any] = {"path": relative, "sha256": _sha(path), "bytes": path.stat().st_size}
        if rows is not None:
            entry["rows"] = rows
        self.records[relative] = entry

    def manifest(self, relative: str) -> dict[str, Any]:
        """Index only a manifest's own outputs, excluding protected history."""
        path = self.inside(self.root / relative)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.record(path)
        unit = next(parent for parent in path.parents if parent.name in {"T1Core", "T2Sum"})
        for raw, expected in data.get("outputs_sha256", {}).items():
            normal = raw.replace("\\", "/")
            candidates = (path.parent / normal, unit / normal)
            target = next((self.inside(item) for item in candidates if item.is_file()), None)
            if target is None:
                self.warnings.append({"kind": "unavailable_manifest_output", "manifest": relative, "output": normal})
                continue
            if target in self.expected and self.expected[target] != expected:
                raise ValueError(f"Conflicting output receipts: {target}")
            self.expected[target] = expected
        return data

    def table(self, relative: str) -> list[dict[str, Any]]:
        """Load a CSV only when its owning output receipt agrees with its bytes."""
        path = self.inside(self.root / relative)
        if path not in self.expected:
            raise ValueError(f"No owning output receipt for {relative}")
        if _sha(path) != self.expected[path]:
            raise ValueError(f"Consumed result hash mismatch: {relative}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [_typed(row) for row in csv.DictReader(handle)]
        self.record(path, len(rows))
        self.verified += 1
        return rows

    def parent(self, owner: str, key: str, recorded: str | None, target: str) -> None:
        """Expose historical parent-manifest drift without silently repairing it."""
        actual = self.records[target]["sha256"]
        if recorded is not None and recorded != actual:
            self.warnings.append({
                "kind": "parent_manifest_fingerprint_drift", "manifest": owner, "field": key,
                "target": target, "recorded": recorded, "actual": actual,
                "meaning": "父级清单指纹发生变化；本页实际消费的 CSV 已独立核验输出哈希与数值关系。",
            })


def _index(rows: list[dict[str, Any]], label: str) -> dict[int, dict[str, Any]]:
    """Index by AppID, rejecting silent duplicate replacement."""
    result = {row["appid"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate AppID in {label}")
    return result


def _same(actual: Any, expected: Any, label: str) -> None:
    """Verify a stored relationship while respecting null values."""
    if actual is None or expected is None:
        if actual is not None or expected is not None:
            raise ValueError(f"Missingness mismatch: {label}")
    elif not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError(f"Inconsistent result: {label}: {actual} != {expected}")


def _medians(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, float | None]:
    """Compute transparent game-level medians, without statistical refitting."""
    return {
        field: median(values) if (values := [row[field] for row in rows if row.get(field) is not None]) else None
        for field in fields
    }


def load_dashboard_data(lyx_root: Path) -> dict[str, Any]:
    """Return a validated compact presentation payload using frozen CSV results.

    The 198/183/69/142/181 sample contract is deliberate. A different data version
    requires review before a build can silently change the page's scope.
    No database, source file, analysis artifact or upstream manifest is written.
    """
    sources = _Sources(Path(lyx_root).resolve())
    t1, t2 = "analysis/T1Core/output", "analysis/T2Sum/output"
    paths = {
        "core": f"{t1}/manifest.json", "types": f"{t1}/type_analysis/manifest.json",
        "trajectory": f"{t1}/trajectory_analysis/manifest.json",
        "duration": f"{t1}/duration_analysis/manifest.json",
        "references": f"{t1}/duration_references/manifest.json",
        "reputation": f"{t2}/reputation/manifest.json", "peers": f"{t2}/benchmark/manifest.json",
    }
    manifests = {name: sources.manifest(path) for name, path in paths.items()}
    read = sources.table
    core = read(f"{t1}/game_metrics.csv")
    cohort = read(f"{t1}/cohort.csv")
    checkpoint_rows = read(f"{t1}/checkpoints.csv")
    edges = read(f"{t1}/trajectory_analysis/adjacent_nodes.csv")
    profiles = read(f"{t1}/trajectory_analysis/game_profiles.csv")
    selected_pairs = [row for row in read(f"{t1}/trajectory_analysis/case_candidates.csv") if row["selected_pair"] is not None]
    types = read(f"{t1}/type_analysis/group_summary.csv")
    sensitivity = read(f"{t1}/type_analysis/sensitivity_summary.csv")
    durations = read(f"{t1}/duration_references/reference_cohort.csv")
    duration_eligibility = read(f"{t1}/duration_analysis/duration_eligibility.csv")
    duration_correlations = read(f"{t1}/duration_analysis/time_correlations.csv")
    reference_correlations = read(f"{t1}/duration_references/reference_correlations.csv")
    duration_groups = read(f"{t1}/duration_analysis/duration_groups.csv")
    reputation = read(f"{t2}/reputation/reputation_cohort.csv")
    names = read(f"{t2}/reputation/reputation_eligibility.csv")
    common = read(f"{t2}/reputation/rating_common.csv")
    correlations = read(f"{t2}/reputation/reputation_correlations.csv")
    coverage = read(f"{t2}/reputation/score_coverage.csv")
    quadrants = read(f"{t2}/reputation/reputation_quadrants.csv")
    multilabel = read(f"{t2}/reputation/exploration_multilabel.csv")
    boundaries = read(f"{t2}/reputation/exploration_region_boundaries.csv")
    matched = read(f"{t2}/reputation/matched_cases.csv")
    conditions = read(f"{t2}/benchmark/peer_conditions.csv")
    peer_coverage = read(f"{t2}/benchmark/peer_coverage.csv")
    membership = read(f"{t2}/benchmark/peer_membership.csv")
    peer_cases = read(f"{t2}/benchmark/benchmark_cases.csv")

    for name in ("types", "trajectory", "duration", "reputation", "peers"):
        sources.parent(paths[name], "source.manifest_sha256", manifests[name].get("source", {}).get("manifest_sha256"), paths["core"])
    reference_source = manifests["references"]["source"]
    sources.parent(paths["references"], "source.base_manifest_sha256", reference_source.get("base_manifest_sha256"), paths["duration"])
    sources.parent(paths["references"], "source.base_source.manifest_sha256", reference_source.get("base_source", {}).get("manifest_sha256"), paths["core"])
    sources.parent(paths["peers"], "source.upstream_manifest_sha256", manifests["peers"]["source"].get("upstream_manifest_sha256"), paths["reputation"])

    core_by_id = _index(core, "game_metrics")
    names_by_id = _index(names, "reputation_eligibility")
    reputation_by_id = _index(reputation, "reputation_cohort")
    duration_by_id = _index(durations, "reference_cohort")
    manual = manifests["duration"]["source"]["manual_supplements"]
    manual_path = sources.inside(sources.root / manual["path"])
    if _sha(manual_path) != manual["sha256"]:
        raise ValueError("Manual duration input hash differs from the analysis receipt")
    with manual_path.open(encoding="utf-8-sig", newline="") as handle:
        manual_rows = list(csv.DictReader(handle))
    if len(manual_rows) != 10 or {int(r["appid"]) for r in manual_rows} != {812140, 1903340, 1593500, 1245620}:
        raise ValueError("Manual duration supplement scope differs from the approved ten fields")
    for item in manual_rows:
        row = duration_by_id[int(item["appid"])]
        _same(row[item["field"]], float(item["value"]), "manual duration " + item["field"])
        if not row[item["field"] + "_source"].startswith("manual_confirmed:"):
            raise ValueError("Manual duration value lost its origin")
    sources.record(manual_path, len(manual_rows))
    rating_manual = manifests["reputation"]["source"]["manual_supplements"]
    rating_path = sources.inside(sources.root / rating_manual["path"])
    if _sha(rating_path) != rating_manual["sha256"]:
        raise ValueError("Manual score input hash differs from the task5 receipt")
    with rating_path.open(encoding="utf-8-sig", newline="") as handle:
        rating_rows = list(csv.DictReader(handle))
    if len(rating_rows) != 5 or {(int(r["appid"]), r["field"]) for r in rating_rows} != {
        (1903340, "metacritic"), (1903340, "rawg_rating"), (1593500, "metacritic"),
        (1593500, "rawg_rating"), (1593500, "rawg_ratings_count")}:
        raise ValueError("Manual score supplement scope differs from the approved five fields")
    for item in rating_rows:
        row = reputation_by_id[int(item["appid"])]
        _same(row[item["field"]], float(item["value"]), "manual rating " + item["field"])
        if not row[item["field"] + "_source"].startswith("manual_confirmed:"):
            raise ValueError("Manual score value lost its origin")
    sources.record(rating_path, len(rating_rows))
    eligibility_by_id = _index(duration_eligibility, "duration_eligibility")
    profile_by_id = _index(profiles, "game_profiles")
    main_conditions_by_id = _index(
        [row for row in conditions if row["config"] == "main"], "main peer_conditions",
    )
    nodes_by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    edges_by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    peers_by_id: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    members: dict[str, dict[str, list[dict[str, Any]]]] = {row["config"]: {} for row in peer_coverage}
    for row in checkpoint_rows:
        if row["is_in_sequence"]:
            nodes_by_id[row["appid"]].append({key: value for key, value in row.items() if key not in {"appid", "title", "is_in_sequence"}})
    for row in edges:
        edges_by_id[row["appid"]].append({
            key: value for key, value in row.items()
            if key not in {"appid", "title", "primary_gameplay", "ending_type", "node_count", "quality_flags"}
        })
    for row in conditions:
        compact = {
            key: value for key, value in row.items()
            if key in {"config", "peer_status", "peer_n", "known_issue_peer_n", "known_caveat", "semantic_review_status"}
            or any(key.startswith(metric + "_") for metric in PROGRESS)
        }
        if row["config"] in peers_by_id[row["appid"]]:
            raise ValueError("Duplicate peer configuration / AppID summary")
        peers_by_id[row["appid"]][row["config"]] = compact
    seen: set[tuple[str, int, int]] = set()
    for row in membership:
        key = (row["config"], row["appid"], row["peer_appid"])
        if key in seen or row["appid"] == row["peer_appid"]:
            raise ValueError("Duplicate or self-referential peer membership")
        seen.add(key)
        members[row["config"]].setdefault(str(row["appid"]), []).append({"appid": row["peer_appid"], "similarity": row["jaccard"]})

    complete = [row for row in core if row["three_point_available"]]
    counts = {
        "curves": len(core), "complete_three_point": len(complete), "duration": len(durations),
        "common_ratings": len(common),
        "main_available_peers": next(row["available_n"] for row in peer_coverage if row["config"] == "main"),
        "sequence_nodes": sum(map(len, nodes_by_id.values())), "adjacent_edges": len(edges),
    }
    expected = {"curves": 198, "complete_three_point": 183, "duration": 69, "common_ratings": 142, "main_available_peers": 181, "sequence_nodes": 1741, "adjacent_edges": 1543}
    if counts != expected:
        raise ValueError(f"Frozen sample changed: {counts}")
    ids, complete_ids = set(core_by_id), {row["appid"] for row in complete}
    if {row["appid"] for row in cohort} != ids or set(names_by_id) != ids:
        raise ValueError("Core cohort / game-name coverage mismatch")
    if set(reputation_by_id) != complete_ids or not set(duration_by_id) <= complete_ids:
        raise ValueError("Reputation or duration cohort mismatch")
    if {row["appid"] for row in duration_eligibility if row["included"]} != set(duration_by_id):
        raise ValueError("Duration eligibility differs from its cohort")
    if {row["appid"] for row in common} != {row["appid"] for row in reputation if row["three_scores_common"]}:
        raise ValueError("Common three-score cohort mismatch")
    partition = [appid for row in quadrants for appid in row["appids"]]
    if len(partition) != 183 or set(partition) != complete_ids:
        raise ValueError("Quadrants do not partition all 183 games")
    for item in peer_coverage:
        config = item["config"]
        rows = [row for row in conditions if row["config"] == config]
        if len(rows) != 183 or {row["appid"] for row in rows} != complete_ids:
            raise ValueError(f"Incomplete peer configuration: {config}")
        if sum(row["peer_status"] == "available" for row in rows) != item["available_n"]:
            raise ValueError(f"Inconsistent peer coverage: {config}")
        for row in rows:
            if len(members[config].get(str(row["appid"]), [])) != row["peer_n"]:
                raise ValueError(f"Peer membership count mismatch: {config}/{row['appid']}")

    games: list[dict[str, Any]] = []
    for row in core:
        appid = row["appid"]
        sequence = sorted(nodes_by_id[appid], key=lambda item: item["sequence_position"])
        adjacent = sorted(edges_by_id[appid], key=lambda item: item["edge_position"])
        # Original descriptions exist only for the three role nodes exported
        # in main peer_conditions. Never infer text for other sequence nodes.
        main_condition = main_conditions_by_id.get(appid)
        descriptions = {
            role + "_description": main_condition.get(role + "_description") if main_condition else None
            for role in ("first", "middle", "end")
        }
        for node in sequence:
            node["description"] = None
            if main_condition:
                for role in ("first", "middle", "end"):
                    if node["local_id"] == row[role + "_local_id"]:
                        node["description"] = descriptions[role + "_description"]
        if len(sequence) != row["node_count"] or len(adjacent) != len(sequence) - 1:
            raise ValueError(f"Node / edge count mismatch: {appid}")
        if [node["sequence_position"] for node in sequence] != list(range(1, len(sequence) + 1)):
            raise ValueError(f"Non-contiguous sequence positions: {appid}")
        _same(sequence[0]["rate"], row["p_s"], f"{appid} first node")
        _same(sequence[-1]["rate"], row["p_f"], f"{appid} end node")
        middle = sequence[(len(sequence) - 1) // 2]["rate"] if len(sequence) >= 3 else None
        _same(row["p_m"], middle, f"{appid} positional middle")
        _same(row["overall_progress_ratio"], row["p_f"] / row["p_s"], f"{appid} overall")
        if row["three_point_available"]:
            _same(row["early_progress_ratio"], row["p_m"] / row["p_s"], f"{appid} early")
            _same(row["late_progress_ratio"], row["p_f"] / row["p_m"], f"{appid} late")
            _same(row["early_progress_ratio"] * row["late_progress_ratio"], row["overall_progress_ratio"], f"{appid} product")
        elif row["early_progress_ratio"] is not None or row["late_progress_ratio"] is not None:
            raise ValueError(f"Two-node game has fabricated stage ratios: {appid}")
        for edge, first, last in zip(adjacent, sequence, sequence[1:]):
            _same(edge["from_rate"], first["rate"], f"{appid} edge start")
            _same(edge["to_rate"], last["rate"], f"{appid} edge end")
            _same(edge["adjacent_progress_ratio"], last["rate"] / first["rate"], f"{appid} adjacent")
            _same(edge["relative_drop"], 1 - edge["adjacent_progress_ratio"], f"{appid} drop")
            _same(edge["coverage_gap_pp"], 100 * (first["rate"] - last["rate"]), f"{appid} pp")
        duration, rep = duration_by_id.get(appid), reputation_by_id.get(appid)
        for extra in (duration, rep):
            if extra:
                for field in METRICS:
                    _same(extra[field], row[field], f"{appid} joined {field}")
        if duration:
            for denominator, ratio in (("main_hours", "time_ratio"), ("extra_hours", "extra_hours_ratio"), ("completionist_hours", "completionist_hours_ratio")):
                _same(duration[ratio], duration["playtime"] / duration[denominator], f"{appid} {ratio}")
        games.append({
            **row, **descriptions, "name_en": names_by_id[appid]["name_en"] or row["title"],
            "name_zh": names_by_id[appid]["name_zh"] or "", "nodes": sequence, "edges": adjacent,
            "duration": duration, "duration_eligibility": eligibility_by_id[appid],
            "duration_exclusion_reason": eligibility_by_id[appid]["exclusion_reason"],
            "reputation": rep, "peers": peers_by_id.get(appid, {}), "trajectory": profile_by_id[appid],
        })
    counts.update({
        "frame": 1000, "two_node_games": len(core) - len(complete), "reputation": len(reputation),
        "peer_memberships": len(membership), "peer_configurations": len(peer_coverage),
        "raw_checkpoint_candidates": len(checkpoint_rows),
    })
    cohort_receipts = {row["cohort_sha256"] for row in cohort}
    if len(cohort_receipts) != 1:
        raise ValueError("Inconsistent cohort receipts")
    checks = [
        {"name": name, "passed": True} for name in (
            "frozen_sample_counts", "consumed_csv_manifest_hashes", "cohort_joins_and_quadrants",
            "stage_ratios_and_middle_identity", "sequence_nodes_and_adjacent_intervals",
            "duration_ratios", "peer_membership_counts_no_self_or_duplicates",
        )
    ]
    return {
        "meta": {
            "schema_version": "lyx-web-dashboard-v1",
            "dataset_version": manifests["core"]["source"]["baseline_metadata"]["dataset_version"],
            "counts": counts, "medians": _medians(complete, METRICS),
            "all_curve_medians": _medians(core, METRICS),
            "duration_medians": _medians(durations, ("main_hours", "playtime", "time_ratio", "extra_hours", "extra_hours_ratio", "completionist_hours", "completionist_hours_ratio")),
            "duration_manual_supplements": manual,
            "rating_manual_supplements": rating_manual,
            "source_cohort_sha256": next(iter(cohort_receipts)),
            "source_checks": {
                "status": "passed_with_manifest_warnings" if sources.warnings else "passed",
                "checks": checks, "warnings": sources.warnings,
                "consumed_csv_hashes_verified": sources.verified,
                "scope": "本页消费的 CSV 与关系核验；未打开 SQLite 或重跑统计。",
            },
            "review": {
                "status": "key_cases_reviewed", "scope": "重点案例", "confirmed_by": "刘宇翔",
                "confirmation_date": "2026-10-17", "source": "项目对话中的明确确认",
                "note": "重点案例审核已完成；不扩大为198款逐项审核。CSV中的审核状态保留冻结历史记录。",
            },
            "units": {"rates_and_progress": "0_to_1", "hours": "hours", "suffix_pp": "percentage_points", "spearman": "minus1_to1"},
        },
        "games": games,
        "types": {"summary": types, "sensitivity": sensitivity},
        "duration": {"cohort": durations, "eligibility": duration_eligibility, "correlations": duration_correlations, "reference_correlations": reference_correlations, "groups": duration_groups},
        "reputation": {"cohort": reputation, "common": common, "correlations": correlations, "coverage": coverage, "quadrants": quadrants, "exploration_multilabel": multilabel, "region_boundaries": boundaries, "matched_cases": matched},
        "peers": {"coverage": peer_coverage, "members": members, "parameters": manifests["peers"]["parameters"]},
        "highlights": {
            "opening_appids": [235600, 588650], "default_appids": [367520, 812140, 1903340, 1593500, 1245620],
            "trajectory_pairs": selected_pairs, "reputation_matched_cases": matched,
            "peer_cases": peer_cases,
            "missing_examples": {"two_nodes": 379720, "rawg_missing": next(r["appid"] for r in duration_eligibility if r["exclusion_reason"] == "rawg_null"), "insufficient_peers": 397950, "no_peers": 861650},
        },
        "sources": sorted(sources.records.values(), key=lambda item: item["path"]),
    }
