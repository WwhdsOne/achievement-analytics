"""冻结评估协议后执行离线研究；默认推荐器保持原样。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .baseline import candidate_rows, tag_set
from .research_metrics import coverage_audit, query_diagnostics, reconstruction_summary, tag_stratum
from .snapshot import ROOT, SNAPSHOTS, load_snapshot

ANCHORS = [1245620, 413150, 646570, 367520, 632470, 255710, 620, 227300]
TAG_QUERIES = [
    ["RPG", "Open World"], ["Rogue-like", "Deckbuilding"], ["Souls-like", "Difficult"],
    ["Puzzle", "Co-op"], ["Simulation", "Driving"], ["Farming Sim", "Relaxing"],
    ["Strategy", "City Builder"], ["Casual", "Singleplayer"], ["__UNKNOWN_WEEK1__"],
]
STUDY = ROOT / "data/processed/recommendation/research/study-v1"


class TagIndex:
    """一次构造倒排索引，检索结果与固定Jaccard基线相同。"""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = {row["appid"]: row for row in candidate_rows(rows)}
        self.labels = {appid: set(tag_set(row)) for appid, row in self.rows.items()}
        self.postings: dict[str, set[int]] = defaultdict(set)
        self.frequency: Counter = Counter()
        for appid, labels in self.labels.items():
            self.frequency.update(labels)
            for tag in labels:
                self.postings[tag].add(appid)

    def neighbors(self, query: set[str], exclude: int | None = None, k: int = 5) -> list[dict]:
        """返回正交集候选，保持app id同分排序并排除种子。"""
        candidates = set().union(*(self.postings.get(tag, set()) for tag in query))
        candidates.discard(exclude)
        results = []
        for appid in candidates:
            labels = self.labels[appid]
            shared = query & labels
            union = query | labels
            results.append({"appid": appid, "name": self.rows[appid].get("name_zh") or self.rows[appid]["name_en"],
                            "score": len(shared) / len(union), "intersection_count": len(shared),
                            "union_count": len(union), "shared_tags": sorted(shared)})
        return heapq.nsmallest(k, results, key=lambda row: (-row["score"], row["appid"]))


def build_protocol(rows: list[dict], metadata: dict, per_stratum: int = 100,
                   anchors: list[int] | None = None) -> dict:
    """在观察实验结果前确定查询与隐藏标签；输入行顺序不影响抽样。"""
    if per_stratum <= 0:
        raise ValueError("每层样本数必须为正")
    rng = random.Random(42)
    pool: dict[str, list[dict]] = defaultdict(list)
    candidates = sorted(candidate_rows(rows), key=lambda row: row["appid"])
    for row in candidates:
        pool[tag_stratum(len(tag_set(row)))].append(row)
    cases = []
    selected_anchors = list(ANCHORS if anchors is None else anchors)
    queries = [{"appid": appid, "group": "famous_convenience"} for appid in selected_anchors]
    known_ids = {row["appid"] for row in candidates}
    if not set(selected_anchors) <= known_ids:
        raise ValueError("预设名作种子不在候选集中，不自动替换")
    for stratum in ("2-5", "6-10", "11-19", "20+"):
        sample = rng.sample(pool[stratum], min(per_stratum, len(pool[stratum])))
        for row in sample:
            hidden = rng.choice(sorted(tag_set(row)))
            cases.append({"appid": row["appid"], "hidden_tag": hidden, "stratum": stratum})
        sample_ids = [row["appid"] for row in sample if row["appid"] not in selected_anchors][:3]
        queries += [{"appid": appid, "group": f"random_{stratum}"} for appid in sample_ids]
    return {
        "schema_version": 1, "snapshot_version": metadata["version"], "snapshot_sha256": metadata["sha256"],
        "random_state": 42, "per_stratum": per_stratum, "neighbor_k": 5,
        "prediction_cutoff": 5, "mrr_cutoff": 10,
        "baseline_source_sha256": hashlib.sha256((Path(__file__).parent / "baseline.py").read_bytes()).hexdigest(),
        "reconstruction_cases": cases, "game_queries": queries,
        "tag_queries": [{"tags": tags, "group": "unknown_stress" if i == 8 else "preference"}
                        for i, tags in enumerate(TAG_QUERIES)],
        "label_policy": "one uniform hidden known tag, query removes it, seed excluded from all reference counts",
        "relevance_rubric": {"2": "核心玩法循环及独特机制相近", "1": "部分类型或题材相关，玩法差异明显",
                             "0": "核心玩法明显不相关", "unknown": "官方资料不足，不能判断"},
        "judgment_status": "AI-assisted provisional desk audit; independent human labels pending",
    }


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def freeze_protocol(protocol: dict, folder: Path) -> str:
    """首次独占写入；内容变化必须另起研究目录，禁止静默重选样本。"""
    folder = Path(folder)
    _protect_snapshot(folder)
    raw = _canonical(protocol)
    digest = hashlib.sha256(raw).hexdigest()
    path = folder / "protocol.json"
    if path.exists():
        _, previous = load_protocol(folder)
        if previous != digest:
            raise ValueError("协议已冻结且内容不同；请使用新研究目录")
        return previous
    folder.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
    (folder / "protocol.sha256").write_text(digest + "\n", encoding="utf-8")
    return digest


def load_protocol(folder: Path) -> tuple[dict, str]:
    """校验协议内容摘要；协议与数据的版本匹配在run时额外验证。"""
    folder = Path(folder)
    raw = (folder / "protocol.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != (folder / "protocol.sha256").read_text(encoding="utf-8").strip():
        raise ValueError("冻结协议SHA256不一致")
    return json.loads(raw), digest


def _protect_snapshot(path: Path) -> None:
    if path.resolve().is_relative_to(SNAPSHOTS.resolve()):
        raise ValueError("研究输出不能写入快照目录")


def reconstruct_case(index: TagIndex, case: dict) -> dict:
    """隐藏标签从种子查询及频率贡献中移除，预测只允许未知标签。"""
    appid, hidden = case["appid"], case["hidden_tag"]
    original = index.labels[appid]
    if hidden not in original or len(original) < 2:
        raise ValueError("隐藏标签必须存在且种子至少有两个标签")
    observed = original - {hidden}
    neighbors = index.neighbors(observed, exclude=appid, k=5)
    votes = Counter()
    for row in neighbors:
        for tag in index.labels[row["appid"]] - observed:
            votes[tag] += row["score"]
    predicted = [tag for tag, _ in sorted(votes.items(), key=lambda pair: (-pair[1], pair[0]))[:10]]
    # 全局对照同样排除种子全部贡献；不能让隐藏标签靠种子本身进入候选。
    popular = [tag for tag, count in sorted(index.frequency.items(), key=lambda pair: (
        -(pair[1] - int(pair[0] in original)), pair[0]
    )) if tag not in observed and count - int(tag in original) > 0][:10]

    def reciprocal_rank(labels: list[str]) -> float:
        return 1 / (labels.index(hidden) + 1) if hidden in labels else 0.0

    return {**case, "observed_tags": sorted(observed), "neighbors": [r["appid"] for r in neighbors],
            "neighbor_predictions": predicted, "popular_predictions": popular,
            "neighbor_hit5": int(hidden in predicted[:5]), "popular_hit5": int(hidden in popular[:5]),
            "neighbor_mrr10": reciprocal_rank(predicted), "popular_mrr10": reciprocal_rank(popular)}


def run_study(rows: list[dict], metadata: dict, protocol: dict, protocol_hash: str) -> dict:
    """在固定协议下运行结构诊断与标签重建，不访问数据库。"""
    baseline_hash = hashlib.sha256((Path(__file__).parent / "baseline.py").read_bytes()).hexdigest()
    if (protocol["snapshot_version"] != metadata["version"]
            or protocol["snapshot_sha256"] != metadata["sha256"]
            or protocol["baseline_source_sha256"] != baseline_hash):
        raise ValueError("冻结协议与当前快照或基线代码不匹配")
    if any(protocol.get(key) != value for key, value in (
        ("schema_version", 1), ("neighbor_k", 5), ("prediction_cutoff", 5), ("mrr_cutoff", 10)
    )):
        raise ValueError("当前实现仅支持已声明的固定评估参数")
    index = TagIndex(rows)
    game_results, tag_results = [], []
    for item in protocol["game_queries"]:
        appid = item["appid"]
        query = index.labels[appid]
        # 多取一条，以判断第5项是否在相同分数的边界上。
        found = index.neighbors(query, exclude=appid, k=6)
        game_results.append({**item, "name": index.rows[appid]["name_en"], "results": found[:5],
                             "diagnostics": query_diagnostics(query, found, index.labels),
                             "tie_at_cutoff": len(found) > 5 and found[4]["score"] == found[5]["score"]})
    for item in protocol["tag_queries"]:
        query = {tag.strip().casefold() for tag in item["tags"]}
        found = index.neighbors(query, k=6)
        tag_results.append({**item, "results": found[:5],
                            "diagnostics": query_diagnostics(query, found, index.labels),
                            "tie_at_cutoff": len(found) > 5 and found[4]["score"] == found[5]["score"]})
    cases = [reconstruct_case(index, case) for case in protocol["reconstruction_cases"]]
    return {"snapshot_version": metadata["version"], "snapshot_sha256": metadata["sha256"],
            "protocol_sha256": protocol_hash, "built_at": datetime.now(timezone.utc).isoformat(),
            "evaluation_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "metrics_source_sha256": hashlib.sha256((Path(__file__).parent / "research_metrics.py").read_bytes()).hexdigest(),
            "coverage": coverage_audit(rows), "game_queries": game_results, "tag_queries": tag_results,
            "reconstruction_cases": cases, "reconstruction": reconstruction_summary(cases),
            "human_relevance_metrics": None, "human_relevance_status": "未取得独立人工标注，不能报告人工Precision@5"}


def write_review_template(report: dict, path: Path) -> None:
    """导出匿名次序的逐对人工复核表；标签留空，不能当作已标注。"""
    pairs = []
    for query in report["game_queries"]:
        if query["group"] == "famous_convenience":
            for result in query["results"]:
                pairs.append({"seed_appid": query["appid"], "seed_name": query["name"],
                              "candidate_appid": result["appid"], "candidate_name": result["name"],
                              "label_0_1_2_unknown": "", "rationale": "", "reviewer": ""})
    random.Random(42).shuffle(pairs)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairs[0]) if pairs else ["seed_appid"])
        writer.writeheader()
        writer.writerows(pairs)


def main(argv: list[str] | None = None) -> int:
    """freeze先于run；输出及人工复核模板都保留在独立研究目录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "run"])
    parser.add_argument("--version", required=True)
    parser.add_argument("--study-dir", type=Path, default=STUDY)
    args = parser.parse_args(argv)
    try:
        _protect_snapshot(args.study_dir)
        rows, metadata = load_snapshot(args.version)
        if args.command == "freeze":
            protocol = build_protocol(rows, metadata)
            digest = freeze_protocol(protocol, args.study_dir)
            result = {"protocol_sha256": digest, "cases": len(protocol["reconstruction_cases"]),
                      "game_queries": len(protocol["game_queries"]), "study_dir": str(args.study_dir)}
        else:
            protocol, digest = load_protocol(args.study_dir)
            report = run_study(rows, metadata, protocol, digest)
            (args.study_dir / "evaluation.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            template = args.study_dir / "human-review-template.csv"
            if not template.exists():
                write_review_template(report, template)
            result = {"study_dir": str(args.study_dir), "protocol_sha256": digest,
                      "reconstruction": report["reconstruction"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"评估失败（{type(exc).__name__}）；请检查协议、版本与输出路径。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
