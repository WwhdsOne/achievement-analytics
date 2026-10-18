"""只读核验冻结分析并导出交接副本；不连接API，不写源库或既有分析产物。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
ANALYSIS = ROOT.parent
LYX = ANALYSIS.parent
CORE = ANALYSIS / "T1Core"
SUM = ANALYSIS / "T2Sum"
PACKAGE = ROOT / "package"
DBS = [LYX / "NewDB/wwh5.sqlite3", LYX / "database/achievements.sqlite"]
for folder in (CORE, SUM):
    sys.path.insert(0, str(folder))


def sha(path: Path) -> str:
    """计算文件内容指纹。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def owned(path: Path) -> Path:
    """所有导出和审计写入限于delivery，解析链接后检查。"""
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError("交接产物只能写入analysis/delivery的子路径")
    return resolved


def write_json(path: Path, value: Any) -> None:
    """写入可追溯JSON，不改源文件。"""
    path = owned(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    """空值保持空字符串，交接时不补零。"""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """导出UTF-8 CSV，字段顺序来自原表/明确的结果结构。"""
    if not rows:
        raise ValueError(f"拒绝导出无字段的空表：{path}")
    path = owned(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def protected() -> dict[str, str]:
    """保护两库、既有分析数值/图片及项目依赖锁；说明文档允许整理。"""
    paths = list(DBS) + [LYX.parents[1] / "uv.lock"]
    for task in ("T0Pre", "T1Core", "T2Sum"):
        paths += [p for p in (ANALYSIS/task).rglob("*") if p.is_file()
                  and not {"runtime", "__pycache__"} & set(p.parts)
                  and p.suffix in (".csv", ".json", ".png", ".svg")]
    paths += [LYX/"process/datacache.csv", LYX/"process/failure_data.csv"]
    return {str(p.relative_to(LYX)) if p.is_relative_to(LYX) else "../../uv.lock": sha(p) for p in paths}


def snapshot() -> dict[str, Any]:
    """删除前保存指纹与将清理目录的体量，不复制历史内容。"""
    inventory = []
    for name in ("runtime", "old", "__pycache__"):
        folder = LYX/"process"/name
        files = [p for p in folder.rglob("*") if p.is_file()]
        inventory.append({"path":str(folder.relative_to(LYX)), "files":len(files),
                          "bytes":sum(p.stat().st_size for p in files)})
    value = {"at":datetime.now(timezone.utc).isoformat(), "protected":protected(), "cleanup_inventory":inventory}
    if (ROOT/"runtime/before.json").exists():
        raise ValueError("已有清理前快照，拒绝覆盖；用build重新核查即可")
    write_json(ROOT/"runtime/before.json", value)
    return {"protected_files":len(value["protected"]), "cleanup_inventory":inventory}


def compare_rows(path: Path, expected: list[dict[str, Any]]) -> None:
    """独立比较已有CSV与内存重算，浮点允许1e-11误差。"""
    actual = read_csv(path)
    assert len(actual) == len(expected), (path, len(actual), len(expected))
    for i, (row, fresh) in enumerate(zip(actual, expected, strict=True)):
        for key, value in fresh.items():
            raw = row[key]
            if value is None:
                ok = raw == ""
            elif isinstance(value, bool):
                ok = raw == str(value).lower()
            elif isinstance(value, (int, float)):
                ok = raw != "" and math.isclose(float(raw), value, rel_tol=1e-11, abs_tol=1e-12)
            elif isinstance(value, list):
                ok = raw == "|".join(map(str, value))
            else:
                ok = raw == str(value) or raw == "'"+str(value)
            assert ok, (str(path), i, key, raw, value)


def validate_manifests() -> int:
    """核对所有既有manifest中的输出哈希，包括自选示例；原绝对路径不用于导出副本。"""
    checked = 0
    for task in (CORE, SUM):
        for path in (task/"output").rglob("manifest.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            assert doc.get("checks") and all(doc["checks"].values()), path
            base = task if task == SUM else path.parent
            for name, expected in doc["outputs_sha256"].items():
                target = (base/name.replace("\\", "/")).resolve()
                assert target.is_relative_to(ANALYSIS), target
                assert sha(target) == expected, target
                checked += 1
    return checked


def audit() -> dict[str, Any]:
    """重算指标、分组区间、过程、时长、评分与同类基线；不重绘或回写。"""
    from prepare_metrics import load_inputs, build_game
    from compare_games import load_catalog
    import analyze_types as types
    import analyze_trajectory as trajectory
    from analyze_duration import load_duration_data
    from analyze_duration_references import load_reference_data
    from reputation_data import load_data
    from benchmark_data import load_inputs as benchmark_inputs, compute
    from scipy.stats import spearmanr

    checks = {"manifest_output_hashes": validate_manifests()}
    _, inputs = load_inputs()  # 同时复算WWH原曲线，检查分类关联和冻结源指纹。
    metrics, nodes = [], []
    for item in inputs:
        row, points = build_game(item)
        metrics.append(row); nodes.extend(points)
    compare_rows(CORE/"output/game_metrics.csv", metrics)
    compare_rows(CORE/"output/checkpoints.csv", nodes)
    catalog, source = load_catalog()
    enriched = types.enrich(catalog)
    summaries = [r for scheme in ("primary", "multilabel")
                 for name, members in types.subset_games(enriched).items()
                 for r in types.summarize(members, scheme, name)]
    compare_rows(CORE/"output/type_analysis/group_summary.csv", [r for r in summaries if r["subset"] in ("main_three_point", "all_available")])
    compare_rows(CORE/"output/type_analysis/sensitivity_summary.csv", types.sensitivity_rows(summaries))
    compare_rows(CORE/"output/type_analysis/game_membership.csv", types.membership_rows(enriched))
    compare_rows(CORE/"output/type_analysis/case_pairs.csv", types.choose_cases(enriched))
    sequences = trajectory.load_sequences(catalog)
    profiles, edges = [], []
    for game in catalog:
        profile, adjacent = trajectory.describe_game(game, sequences[game["appid"]])
        profiles.append(profile); edges.extend(adjacent)
    compare_rows(CORE/"output/trajectory_analysis/game_profiles.csv", profiles)
    compare_rows(CORE/"output/trajectory_analysis/adjacent_nodes.csv", edges)
    duration, _, _ = load_duration_data()
    compare_rows(CORE/"output/duration_analysis/duration_cohort.csv", duration)
    references, _ = load_reference_data()
    compare_rows(CORE/"output/duration_references/reference_cohort.csv", references)
    scores, eligibility, _ = load_data()
    compare_rows(SUM/"output/reputation/reputation_cohort.csv", scores)
    compare_rows(SUM/"output/reputation/reputation_eligibility.csv", eligibility)
    for row in read_csv(SUM/"output/reputation/reputation_correlations.csv"):
        group = scores if row["cohort"] == "steam183" else [g for g in scores if g["three_scores_common"]]
        assert len(group) == int(row["n"]), row
        value = float(spearmanr([g[row["score"]] for g in group], [g[row["metric"]] for g in group]).statistic)
        assert math.isclose(value, float(row["spearman"]), abs_tol=1e-12), row
    games, _, _ = benchmark_inputs()
    results, membership, coverage = compute(games)
    # CSV中的列表沿用原程序的竖线分隔契约。
    for name, rows in (("peer_conditions.csv",results),("peer_membership.csv",membership),("peer_coverage.csv",coverage)):
        compare_rows(SUM/"output/benchmark"/name, rows)
    checks.update({"metric_games":len(metrics), "checkpoint_rows":len(nodes), "three_point_games":len(scores),
                   "type_summary_rows_recomputed":len(summaries), "adjacent_rows":len(edges),
                   "duration_games":len(duration), "rating_common_games":sum(g["three_scores_common"] for g in scores),
                   "peer_condition_rows":len(results), "peer_relationship_rows":len(membership),
                   "main_peer_available":sum(r["config"] == "main" and r["peer_status"] == "available" for r in results)})
    return {"checks":checks, "source":source, "catalog":[{"appid":g["appid"],"name_en":g["title"],"name_zh":g.get("name_zh")} for g in catalog]}


def export_sources(appids: list[int]) -> list[dict[str, Any]]:
    """导出固定198款相关原表；model_calls仅导出关联索引，不导出请求/响应历史。"""
    inventory = []
    specs = [("wwh",DBS[0],["games","achievements","achievement_labels","game_labels","story_labels","model_calls","metadata"]),
             ("lyx",DBS[1],["games","games_time"])]
    for label, database, tables in specs:
        con = sqlite3.connect(database.resolve().as_uri()+"?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA query_only=ON"); con.execute("BEGIN")
            for table in tables:
                columns = "id,appid,kind,model,prompt_version,input_hash,status" if table == "model_calls" else "*"
                suffix = "" if table == "metadata" else " WHERE appid IN ("+",".join("?" for _ in appids)+")"
                order = "key" if table == "metadata" else "id" if table == "model_calls" else "appid,local_id" if table in ("achievements","achievement_labels") else "appid"
                rows = [dict(r) for r in con.execute(f'SELECT {columns} FROM "{table}"'+suffix+" ORDER BY "+order, [] if table == "metadata" else appids)]
                target = PACKAGE/"sources"/label/(table+".csv")
                write_csv(target, rows)
                inventory.append({"database":label,"table":table,"rows":len(rows),"columns":"|".join(rows[0]),"path":target.relative_to(PACKAGE).as_posix(),"sha256":sha(target),"scope":"198款子集；LYX仅AppID交集"})
        finally:
            con.rollback(); con.close()
    return inventory


def build() -> dict[str, Any]:
    """审查通过后导出可单独交接的本地包；拒绝覆盖存在的包，避免混合快照。"""
    if PACKAGE.exists():
        raise ValueError("package已存在；先用verify核查，需刷新时人工更换该目录")
    before = protected()
    result = audit()
    assert before == protected(), "只读审查期间保护文件改变"
    rows = export_sources([g["appid"] for g in result["catalog"]])
    write_csv(PACKAGE/"source_tables.csv", rows)
    write_csv(PACKAGE/"game_catalog.csv", result["catalog"])
    artifacts = []
    folders = [CORE/"output", CORE/"figures", SUM/"output", SUM/"figures"]
    excluded = {"comparisons","trajectory_comparisons","selections","benchmark_selections"}
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or excluded & set(path.relative_to(folder).parts) or path.suffix not in (".csv",".json",".png",".svg",".md"):
                continue
            relative = path.relative_to(ANALYSIS)
            target = owned(PACKAGE/relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path,target)
            artifacts.append({"path":relative.as_posix(),"rows":len(read_csv(path)) if path.suffix == ".csv" else "",
                              "columns":"|".join(read_csv(path)[0]) if path.suffix == ".csv" else "",
                              "bytes":path.stat().st_size,"sha256":sha(path),"role":"result_table" if path.suffix==".csv" else "manifest" if path.name=="manifest.json" else "figure" if path.suffix in (".png",".svg") else "result_context"})
    write_csv(PACKAGE/"result_tables.csv", artifacts)
    topics = [
        {"task":1,"subject":"主线指标准备","games":198,"figures":"01","source":"WWH:games/achievements/achievement_labels/story_labels/game_labels/model_calls/metadata","detail":"T1Core/output/game_metrics.csv;checkpoints.csv","summary":"T1Core/output/manifest.json","meaning":"183完整三节点；15两节点；比值非玩家级留存"},
        {"task":2,"subject":"类型与阶段","games":183,"figures":"02-07","source":"共用指标与game_labels.payload.gameplay","detail":"T1Core/output/type_analysis/game_membership.csv","summary":"T1Core/output/type_analysis/group_summary.csv;sensitivity_summary.csv","meaning":"主类型互斥/多标签重叠；198另存补充"},
        {"task":3,"subject":"完整主线过程","games":198,"figures":"08-09","source":"共用checkpoints.csv原数组顺序","detail":"T1Core/output/trajectory_analysis/adjacent_nodes.csv","summary":"T1Core/output/trajectory_analysis/game_profiles.csv","meaning":"1741序列节点、1543相邻段；横轴不是时长"},
        {"task":4,"subject":"时长与推进","games":65,"figures":"10-15","source":"WWH:games.payload.rawg.playtime + LYX:games_time三类HLTB","detail":"T1Core/output/duration_references/reference_cohort.csv","summary":"T1Core/output/duration_analysis/time_correlations.csv;duration_references/reference_correlations.csv","meaning":"固定65；平均/参考比值不是个人完成度"},
        {"task":5,"subject":"口碑与推进","games":183,"figures":"16-18","source":"WWH:games.payload positive/negative/rawg；LYX:games_time主线时长对照","detail":"T2Sum/output/reputation/reputation_cohort.csv;rating_common.csv","summary":"T2Sum/output/reputation/reputation_correlations.csv;reputation_quadrants.csv","meaning":"Steam183、三评分共同140；观察性相关"},
        {"task":6,"subject":"同类参照基线","games":183,"figures":"19-21","source":"专题5底表+game_labels玩法+achievements节点原文","detail":"T2Sum/output/benchmark/peer_membership.csv;peer_conditions.csv","summary":"T2Sum/output/benchmark/peer_benchmark.csv;peer_coverage.csv;matched_sensitivity.csv","meaning":"主口径181可比较、2参照不足；不等于质量排名"},
    ]
    write_csv(PACKAGE/"analysis_summary.csv", topics)
    assert protected() == before, "导出修改了受保护输入/分析结果"
    files = {str(p.relative_to(PACKAGE)).replace("\\","/"):sha(p) for p in PACKAGE.rglob("*") if p.is_file()}
    receipt = {"created_at":datetime.now(timezone.utc).isoformat(),"checks":result["checks"],"source":result["source"],
               "source_databases":[{"path":str(p.relative_to(LYX)),"bytes":p.stat().st_size,"sha256":sha(p)} for p in DBS],
               "source_extracts_are_not_full_database_replacements":True,"files_sha256":files}
    write_json(PACKAGE/"delivery_manifest.json", receipt)
    write_json(ROOT/"runtime/audit.json", {"at":receipt["created_at"],"checks":result["checks"],"protected_unchanged":True,"files":len(files)})
    return {"checks":result["checks"],"files":len(files)+1,"package":str(PACKAGE),"bytes":sum(p.stat().st_size for p in PACKAGE.rglob('*') if p.is_file())}


def verify_package() -> dict[str, Any]:
    """只校验交接包，可在没有SQLite、旧缓存和删除前记录的机器上运行。"""
    manifest = json.loads((PACKAGE/"delivery_manifest.json").read_text(encoding="utf-8"))
    actual = {p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob("*") if p.is_file()}
    assert actual == set(manifest["files_sha256"]) | {"delivery_manifest.json"}, "包内出现缺失或未登记文件"
    for name, expected in manifest["files_sha256"].items():
        assert sha(owned(PACKAGE/name)) == expected, name
    return {"package_files_verified":len(manifest["files_sha256"])}


def verify() -> dict[str, Any]:
    """校验导出包及本轮保护快照；不依赖原process运行缓存。"""
    result = verify_package()
    baseline = json.loads((ROOT/"runtime/before.json").read_text(encoding="utf-8"))
    assert baseline["protected"] == protected(), "数据库/数值产物/图片/累计CSV/依赖锁发生改变"
    return {**result,"protected_files_unchanged":len(baseline["protected"])}


def main() -> int:
    """命令行：snapshot只做删除前记录，build核验并导出，verify复查。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("snapshot","build","verify","verify-package"))
    args = parser.parse_args()
    result = {"snapshot":snapshot,"build":build,"verify":verify,"verify-package":verify_package}[args.command]()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
