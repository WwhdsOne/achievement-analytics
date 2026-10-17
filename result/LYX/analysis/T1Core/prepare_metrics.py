"""以T0Pre的198款WWH有效曲线为固定范围，构建首/中/末主线指标。"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
ANALYSIS_ROOT = ROOT.parent
T0_ROOT = ANALYSIS_ROOT / "T0Pre"
LYX_ROOT = ANALYSIS_ROOT.parent
DEFAULT_OUTPUT = ROOT / "output"
EXPECTED_GAMES = 198
VERSION = "lyx-mainline-position-v1"
MIDDLE_RULE = "lower_middle_of_common_non_end_plus_representative_end"

sys.path.insert(0, str(T0_ROOT))
from wwh_replay import analysis as baseline
from wwh_replay import params as baseline_params
from wwh_replay import storage as source

Json = dict[str, Any]


def canonical(value: Any) -> str:
    """Serialize reproducibly, rejecting nonfinite JSON values."""
    return source.canonical(value)


def digest(value: Any) -> str:
    """Return a canonical JSON SHA256 for cohort and metric comparisons."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def owned_path(path: str | Path) -> Path:
    """Keep all generated files inside T1Core, including resolved symlinks."""
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("T1Core输出必须位于result/LYX/analysis/T1Core内")
    return path


def protected_snapshot() -> Json:
    """Fingerprint both databases and baseline/stage files without changing them."""
    files = {}
    for folder in (T0_ROOT, ANALYSIS_ROOT / "T2Sum", ANALYSIS_ROOT / "T3Sum"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not {"runtime", "__pycache__"} & set(path.relative_to(folder).parts):
                files[str(path.relative_to(LYX_ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    databases = [source.fingerprint(p) for p in (source.DEFAULT_DB, source.LEGACY_DB) if p.is_file()]
    return {"databases": databases, "protected_files": files}


def load_inputs() -> tuple[Json, list[Json]]:
    """Verify the fixed baseline and read only the selected games from WWH SQLite."""
    cached = json.loads((T0_ROOT / "metrics.json").read_text(encoding="utf-8"))
    verification = json.loads((T0_ROOT / "verification.json").read_text(encoding="utf-8"))
    source_path = source.DEFAULT_DB.resolve()
    pinned = [p for p in verification["database_fingerprints_after"] if Path(p["path"]).resolve() == source_path]
    if len(pinned) != 1 or source.fingerprint(source_path)["sha256"] != pinned[0]["sha256"]:
        raise ValueError("WWH数据库文件与T0Pre已核验快照不同，请先核对数据版本")
    meta, metrics = cached["metadata"], cached["metrics"]
    if meta["analysis_parameters"]["CURVE_BASELINE"] != "highest":
        raise ValueError("T0Pre不是highest基线，请先重跑T0Pre默认口径；不自动缩小198款范围")
    if canonical(meta["analysis_parameters"]) != canonical(baseline_params.snapshot()):
        raise ValueError("T0Pre参数文件与已生成指标不一致，请先核对基线")
    selected = [g for g in metrics["per_game"] if g["curve"]["completion"] is not None]
    appids = [g["appid"] for g in selected]
    if len(appids) != EXPECTED_GAMES or len(set(appids)) != EXPECTED_GAMES:
        raise ValueError("基线有效游戏范围不再是198个唯一AppID，停止避免静默换样本")
    placeholders = ",".join("?" for _ in appids)
    inputs = []
    with source.connect(source.DEFAULT_DB) as conn:
        db_meta = source.metadata(conn)
        for key in ("dataset_version", "input_sha256", "active_annotation"):
            if db_meta.get(key) != meta.get(key):
                raise ValueError(f"借用数据库与T0Pre来源不一致：{key}")
        games = {
            r["appid"]: (r["frame_rank"], json.loads(r["payload"]))
            for r in conn.execute(f"SELECT appid,frame_rank,payload FROM games WHERE appid IN ({placeholders})", appids)
        }
        stories = {r[0]: json.loads(r[1]) for r in conn.execute(
            f"SELECT appid,payload FROM story_labels WHERE appid IN ({placeholders})", appids)}
        dimensions = {r[0]: json.loads(r[1]) for r in conn.execute(
            f"SELECT appid,payload FROM game_labels WHERE appid IN ({placeholders})", appids)}
        labels: dict[int, list[Json]] = {i: [] for i in appids}
        for row in conn.execute(
            f"SELECT a.appid,a.local_id,a.payload,m.status,m.kind FROM achievement_labels a "
            f"JOIN model_calls m ON m.id=a.call_id WHERE a.appid IN ({placeholders})", appids
        ):
            item = json.loads(row[2])
            if item.get("id") != row[1] or row[3] != "success" or row[4] != "classification":
                raise ValueError("源分类身份或成功调用关联异常")
            labels[row[0]].append(item)
        originals: dict[int, dict[str, tuple[Any, ...]]] = {i: {} for i in appids}
        for row in conn.execute(
            f"SELECT appid,local_id,display_name,description,percent FROM achievements WHERE appid IN ({placeholders})", appids
        ):
            originals[row[0]][row[1]] = tuple(row)[2:]
        if set(games) != set(appids) or set(stories) != set(appids) or set(dimensions) != set(appids):
            raise ValueError("固定198款的游戏、剧情或游戏类型记录缺失")
        for old in selected:
            appid = old["appid"]
            rank, game = games[appid]
            expected = {a["local_id"]: (a["display_name"], a.get("description"), a["percent"]) for a in game["achievements"]}
            if originals[appid] != expected or len(labels[appid]) != len(expected):
                raise ValueError(f"appid={appid}原始快照或分类覆盖改变")
            fresh = baseline.story_curve(game, labels[appid], stories[appid])
            fresh["primary_gameplay"] = dimensions[appid].get("gameplay", ["uncertain"])[0]
            if fresh != old["curve"] or game["name_en"] != old["title"]:
                raise ValueError(f"appid={appid}重算曲线与T0Pre不同，停止而不替换样本")
            inputs.append({"appid": appid, "frame_rank": rank, "game": game,
                           "dimensions": dimensions[appid], "story": stories[appid], "curve": fresh})
    audit = {"baseline_metadata": meta, "database_metadata": {k: db_meta[k] for k in
             ("dataset_version", "input_sha256", "active_annotation")}, "appids": appids,
             "cohort_sha256": digest(appids), "baseline_curves_recomputed_equal": True,
             "source_database_sha256": pinned[0]["sha256"], "source_database_matches_baseline_fingerprint": True}
    return audit, inputs


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Keep valid zero numerators; absent or nonpositive denominators yield missing."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        raise ValueError("比例输入必须是有限数")
    return numerator / denominator


def node_fields(role: str, node: Json | None) -> Json:
    """Expose selected node identity and original array position without fabricating one."""
    return {f"{role}_local_id": node["id"] if node else None,
            f"{role}_display_name": node["display_name"] if node else None,
            f"{role}_source_checkpoint_index": node["source_checkpoint_index"] if node else None,
            f"{role}_stage": node["stage"] if node else None}


def build_game(item: Json) -> tuple[Json, list[Json]]:
    """Select the lower positional middle after collapsing alternative end candidates."""
    curve = item["curve"]
    points = curve["points"]
    inner = [p for p in points if p["stage"] != "end"]
    endings = [p for p in points if p["stage"] == "end"]
    if not inner or not endings:
        raise ValueError("有效WWH曲线缺少前置或结局节点")
    # Python max preserves the first array occurrence when end rates tie, as in WWH.
    end = max(endings, key=lambda p: p["rate"])
    sequence = inner + [end]
    indexes = [p["source_checkpoint_index"] for p in sequence]
    if indexes != sorted(set(indexes)):
        raise ValueError("选择后序列违反原数组顺序，禁止通过重排修正")
    first = sequence[0]
    middle_position = (len(sequence) - 1) // 2 if len(sequence) >= 3 else None
    middle = sequence[middle_position] if middle_position is not None else None
    ps, pm, pf = first["rate"], middle["rate"] if middle else None, end["rate"]
    start_count = sum(p["stage"] == "start" for p in points)
    ties = sum(p["rate"] == end["rate"] for p in endings)
    flags = []
    if not middle:
        flags.append("two_points_only")
    if not start_count:
        flags.append("no_explicit_start")
    elif start_count > 1:
        flags.append("multiple_start_labels")
    if curve["ending_type"] == "multi":
        flags.append("multi_ending_proxy")
    if ties > 1:
        flags.append("end_max_tie")
    if ps <= 0:
        flags.append("nonpositive_first_rate")
    if pm == 0:
        flags.append("zero_middle_rate")
    ratios = {"early_progress_ratio": safe_ratio(pm, ps),
              "late_progress_ratio": safe_ratio(pf, pm),
              "overall_progress_ratio": safe_ratio(pf, ps)}
    if any(v is not None and not 0 <= v <= 1 for v in ratios.values()):
        flags.append("ratio_out_of_range")
    if not math.isclose(safe_ratio(pf, curve["baseline"]), curve["completion"], abs_tol=1e-12):
        raise ValueError("代表结局与WWH已有结局/基准比例不一致")
    if all(v is not None for v in ratios.values()) and not math.isclose(
        ratios["early_progress_ratio"] * ratios["late_progress_ratio"],
        ratios["overall_progress_ratio"], abs_tol=1e-12
    ):
        raise ValueError("阶段乘积与全程推进比不一致")
    row = {"appid": item["appid"], "title": item["game"]["name_en"],
           "primary_gameplay": curve["primary_gameplay"],
           "gameplay_labels": "|".join(item["dimensions"]["gameplay"]),
           "story_confidence": item["story"]["confidence"],
           "common_checkpoint_count": len(points), "node_count": len(sequence),
           "ending_type": curve["ending_type"], "end_candidate_count": len(endings),
           "end_max_tie_count": ties, "start_label_count": start_count,
           "three_point_available": middle is not None,
           "middle_sequence_position": middle_position + 1 if middle_position is not None else None,
           "middle_selection_rule": MIDDLE_RULE,
           **node_fields("first", first), **node_fields("middle", middle), **node_fields("end", end),
           "p_s": ps, "p_m": pm, "p_f": pf, **ratios,
           "wwh_baseline_rate": curve["baseline"], "wwh_completion_ratio": curve["completion"],
           "model_all_later_requires_start": all(p.get("requires_start") is True for p in sequence[1:]),
           "metric_status": "complete_three_point" if middle else "two_point_only",
           "quality_flags": "|".join(flags)}
    positions = {p["id"]: i + 1 for i, p in enumerate(sequence)}
    nodes = [{"appid": item["appid"], "title": item["game"]["name_en"],
              "local_id": p["id"], "display_name": p["display_name"],
              "source_checkpoint_index": p["source_checkpoint_index"],
              "source_checkpoint_order": p["source_checkpoint_order"],
              "stage": p["stage"], "route": p["route"], "confidence": p["confidence"],
              "requires_start": p["requires_start"], "rate": p["rate"],
              "sequence_position": positions.get(p["id"]), "is_in_sequence": p["id"] in positions,
              "is_first": p["id"] == first["id"],
              "is_middle": middle is not None and p["id"] == middle["id"],
              "is_end": p["id"] == end["id"]} for p in points]
    return row, nodes


def csv_text(rows: list[Json]) -> str:
    """Serialize reproducible Excel-friendly rows with missing values left empty."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        escaped = {}
        for key, value in row.items():
            if value is None:
                value = ""
            elif isinstance(value, bool):
                value = "true" if value else "false"
            elif isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                value = "'" + value
            escaped[key] = value
        writer.writerow(escaped)
    return stream.getvalue()


def write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write only a T1Core result path, checking the final resolved target."""
    path = owned_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding, newline="")


def coverage(rows: list[Json], nodes: list[Json]) -> Json:
    """Summarize availability without removing incomplete games from the cohort."""
    return {"games": len(rows), "three_point_games": sum(r["three_point_available"] for r in rows),
            "two_point_games": sum(not r["three_point_available"] for r in rows),
            "unified_games": sum(r["ending_type"] == "unified" for r in rows),
            "multi_games": sum(r["ending_type"] == "multi" for r in rows),
            "no_start_games": sum(r["start_label_count"] == 0 for r in rows),
            "multiple_start_games": sum(r["start_label_count"] > 1 for r in rows),
            "tied_end_games": sum(r["end_max_tie_count"] > 1 for r in rows),
            "common_checkpoint_rows": len(nodes), "sequence_node_rows": sum(r["node_count"] for r in rows),
            "unique_start_three_point_games": sum(r["start_label_count"] == 1 and r["first_stage"] == "start" and r["three_point_available"] for r in rows),
            "model_start_chain_games": sum(r["model_all_later_requires_start"] for r in rows),
            "ratio_anomaly_games": sum("ratio_out_of_range" in r["quality_flags"] for r in rows)}


def report_text(audit: Json, rows: list[Json], summary: Json) -> str:
    """Explain the metric contract and measured coverage without retention claims."""
    meta = audit["database_metadata"]
    lines = ["# T1Core：主线首、中、末指标准备", "",
             f"数据版本：`{meta['dataset_version']}`。范围为T0Pre最高解锁率基准下的固定198款，清单SHA256：`{audit['cohort_sha256']}`。",
             "WWH分类、节点数组顺序、阶段和游戏类型直接复用；仅只读数据库，不重新分类、不改T0Pre、不写数据库。", "",
             "## 节点口径", "",
             "使用WWH已筛选的公共主线节点。非结局节点保持原数组顺序；多个结局只保留解锁率最高者，最高值并列取原数组最先出现者，与T0Pre结局计算一致。",
             "在上述有效序列中取首节点、位置中位节点、代表结局。n>=3时，中位节点的1基位置为ceil(n/2)，偶数取靠前者；不按解锁率或stage=middle选点。",
             "仅两个节点的游戏保留在198款底表中，中点与两段推进比留空，首到末推进比保留。原数组下标、阶段及所有候选结局均保存在checkpoints.csv，未选结局不参与序列。", "",
             "## 覆盖", "", "| 项目 | 数量 |", "|---|---:|",
             *[f"| {name} | {summary[key]} |" for name, key in (
                 ("固定游戏", "games"), ("完整三节点", "three_point_games"), ("仅首末两节点", "two_point_games"),
                 ("模型统一结局", "unified_games"), ("多结局代理", "multi_games"),
                 ("无start标识", "no_start_games"), ("多个start标识", "multiple_start_games"),
                 ("唯一首位start且三节点齐全（对照子集）", "unique_start_three_point_games"),
                 ("最高结局解锁率并列", "tied_end_games"), ("WWH有效公共节点", "common_checkpoint_rows"),
                 ("合并代表结局后的序列节点", "sequence_node_rows"), ("比值越界异常", "ratio_anomaly_games"))],
             "", "## 字段与公式", "",
             "p_s、p_m、p_f分别为首、中、代表结局节点的原始解锁率，内部统一0～1。前段=p_m/p_s，后段=p_f/p_m，全程=p_f/p_s；分母<=0或缺失时留空，分子为0时保留有效零。",
             "同时保留wwh_baseline_rate及wwh_completion_ratio=p_f/wwh_baseline_rate。三节点比值的分母是首节点，不是最高解锁率；这不改变固定198款范围。", "",
             "| 指标 | 可计算游戏数 | 游戏级中位数 |", "|---|---:|---:|"]
    for field in ("p_s", "p_m", "p_f", "early_progress_ratio", "late_progress_ratio", "overall_progress_ratio", "wwh_completion_ratio"):
        values = [r[field] for r in rows if r[field] is not None]
        median = f"{statistics.median(values):.2%}" if values else "不可计算"
        lines.append(f"| {field} | {len(values)} | {median} |")
    lines += ["", "## 样例", ""]
    example = next((r for r in rows if r["appid"] == 1593500), None)
    if example:
        lines += [f"{example['title']}：有效序列{example['node_count']}个节点，中位位置{example['middle_sequence_position']}。",
                  f"首节点：{example['first_display_name']}（{example['p_s']:.2%}）；中位：{example['middle_display_name']}（{example['p_m']:.2%}）；结局：{example['end_display_name']}（{example['p_f']:.2%}）。",
                  f"前段{example['early_progress_ratio']:.2%}，后段{example['late_progress_ratio']:.2%}，全程{example['overall_progress_ratio']:.2%}。", ""]
    lines += ["## 结果边界", "",
              "这些是模型标注节点上的聚合覆盖比，不是日留存或弃坑率。中位位置不代表一半游玩时间；首节点不保证是启动游戏的门槛。多结局保留代理标记，不解释为全部结局玩家的精确通关比例。",
              f"只有{summary['model_start_chain_games']}款的所有后续选中节点被模型标记requires_start=true；该标记本身仍不是人工证明，其他游戏不因此移出范围。",
              "本次只建立指标底表，不执行类型差异、时长、价格或口碑专题，不将观察关联解释成因果。", "",
              "输出：[cohort.csv](cohort.csv)、[checkpoints.csv](checkpoints.csv)、[game_metrics.csv](game_metrics.csv)、[manifest.json](manifest.json)。"]
    return "\n".join(lines) + "\n"


def prepare(output: str | Path = DEFAULT_OUTPUT) -> Json:
    """Build and validate fixed-cohort metric files while keeping all inputs unchanged."""
    output = owned_path(output)
    before = protected_snapshot()
    audit, inputs = load_inputs()
    rows, nodes, cohort = [], [], []
    for item in inputs:
        row, selected_nodes = build_game(item)
        rows.append(row)
        nodes.extend(selected_nodes)
        cohort.append({"appid": row["appid"], "title": row["title"], "frame_rank": item["frame_rank"],
                       "primary_gameplay": row["primary_gameplay"], "gameplay_labels": row["gameplay_labels"],
                       "dataset_version": audit["database_metadata"]["dataset_version"],
                       "cohort_sha256": audit["cohort_sha256"]})
    if [r["appid"] for r in rows] != audit["appids"]:
        raise ValueError("游戏底表范围或顺序改变")
    checks = {"fixed_198_appids_same_order": len(rows) == EXPECTED_GAMES,
              "baseline_curves_recomputed_equal": audit["baseline_curves_recomputed_equal"],
              "source_database_matches_baseline_fingerprint": audit["source_database_matches_baseline_fingerprint"],
              "node_keys_unique": len(nodes) == len({(r["appid"], r["local_id"]) for r in nodes}),
              "middle_nodes_distinct_when_present": all(not r["three_point_available"] or
                  len({r["first_local_id"], r["middle_local_id"], r["end_local_id"]}) == 3 for r in rows),
              "missing_middle_not_zero_filled": all(r["three_point_available"] or
                  all(r[k] is None for k in ("p_m", "middle_local_id", "early_progress_ratio", "late_progress_ratio")) for r in rows)}
    if not all(checks.values()):
        raise ValueError("底表核验失败，未写入输出")
    summary = coverage(rows, nodes)
    outputs = {"cohort.csv": csv_text(cohort), "checkpoints.csv": csv_text(nodes),
               "game_metrics.csv": csv_text(rows), "report.md": report_text(audit, rows, summary)}
    for name, text in outputs.items():
        write_text(output / name, text, "utf-8-sig" if name.endswith(".csv") else "utf-8")
    after = protected_snapshot()
    checks["databases_and_protected_files_unchanged"] = before == after
    manifest = {"prepared_at": source.now(), "version": VERSION,
                "scope": "T0Pre highest eligible curves; fixed 198 games", "middle_rule": MIDDLE_RULE,
                "end_rule": "highest end rate; first original array occurrence breaks ties",
                "rate_unit": "0_to_1", "source": audit, "summary": summary, "checks": checks,
                "metric_rows_sha256": digest(rows), "checkpoint_rows_sha256": digest(nodes),
                "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (ROOT / "run.py", ROOT / "prepare_metrics.py")},
                "protected_before": before, "protected_after": after,
                "outputs_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in outputs}}
    write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if not all(checks.values()):
        raise RuntimeError("运行期间输入指纹变化，请查看manifest；本程序未写数据库或T0Pre")
    return {**summary, "cohort_sha256": audit["cohort_sha256"], "checks": checks,
            "report": str(output / "report.md"), "manifest": str(output / "manifest.json")}
