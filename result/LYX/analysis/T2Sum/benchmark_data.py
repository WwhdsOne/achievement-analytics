"""任务6：冻结输入、按背景属性构建留一同类参照，不改任何源数据。"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from reputation_data import ROOT, CORE, Json, PROGRESS, digest, owned, protected, source
from compare_games import load_catalog

VERSION = "lyx-multilabel-peer-benchmark-v1"
DEFAULT_OUTPUT = ROOT / "output" / "benchmark"
MIN_PEERS = 5
MIN_CASE_PEERS = 10
CONFIGS = {
    "main": {"jaccard_min":.5,"steam_gap_max":None,"hours_ratio_max":None},
    "jaccard04": {"jaccard_min":.4,"steam_gap_max":None,"hours_ratio_max":None},
    "jaccard06": {"jaccard_min":.6,"steam_gap_max":None,"hours_ratio_max":None},
    "score_close": {"jaccard_min":.5,"steam_gap_max":.10,"hours_ratio_max":None},
    "length_close": {"jaccard_min":.5,"steam_gap_max":None,"hours_ratio_max":2.0},
}
# These are documented local text ambiguities, not a new classification or an exhaustive review.
KNOWN_CAVEATS = {
    794260:"末节点要求全部3条任务线，不能直接等同完成任一条主线。",
    238090:"末节点要求100%完成战役，与普通结局是否等价待核验。",
    2054970:"末节点原文注明Casual Mode不可用，存在模式限制。",
    2379780:"末节点是赢得一局，是对局进程代理，非传统剧情结局。",
    1874880:"首末为特定战役，中位节点为教程；前后包含关系待核验。",
    1113000:"中、末节点描述缺失，普通剧情必经性待核验。",
}


def prior_snapshot() -> Json:
    """Protect both databases, T0/T1, existing task5 outputs, and figures 01–18."""
    snapshot = protected()
    files = {}
    for p in sorted((ROOT / "output").rglob("*")):
        if p.is_file() and p.relative_to(ROOT / "output").parts[0] not in ("benchmark","benchmark_selections"):
            files[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted((ROOT / "figures").glob("*")):
        if p.suffix in (".png",".svg") and p.name[:2] in ("16","17","18"):
            files[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    snapshot["task5_outputs"] = files
    return snapshot


def load_inputs() -> tuple[list[Json], list[Json], Json]:
    """Verify frozen task5 artifacts and join existing names, labels and checkpoint identities."""
    folder = ROOT / "output" / "reputation"
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("checks") or not all(manifest["checks"].values()):
        raise ValueError("任务5前置核验未通过")
    for name, expected in manifest["outputs_sha256"].items():
        if hashlib.sha256(owned(ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"任务5产物已改变：{name}")
    package = json.loads((folder / "data.json").read_text(encoding="utf-8"))
    catalog, audit = load_catalog()
    if package["source"] != manifest["source"] or package["source"]["dataset_version"] != audit["dataset_version"]:
        raise ValueError("任务5与T1来源版本不一致")
    by_id = {g["appid"]:g for g in catalog}
    rows = []
    for g in package["background"]:
        core = by_id[g["appid"]]
        labels = core["gameplay_labels"].split("|")
        if not core["three_point_available"] or any(core[k] != g[k] for k in PROGRESS):
            raise ValueError("任务6输入与T1完整三节点指标不一致")
        rows.append({**g,"gameplay_labels":"|".join(labels),
                     "similarity_labels":[t for t in labels if t not in ("other","uncertain")],
                     "node_count":core["node_count"],"known_caveat":KNOWN_CAVEATS.get(g["appid"],""),
                     "semantic_review_status":"known_issue" if g["appid"] in KNOWN_CAVEATS else "not_individually_reviewed",
                     **{f+"_display_name":core[f+"_display_name"] for f in ("first","middle","end")}})
    expected_ids = [g["appid"] for g in catalog if g["three_point_available"]]
    if len(rows) != 183 or [g["appid"] for g in rows] != expected_ids:
        raise ValueError("任务6不再是既有183款完整三节点范围")
    # Carry original wording for all targets so a selected case can be interpreted
    # without guessing from its title or treating a model stage as a verified fact.
    with source.connect(source.DEFAULT_DB) as conn:
        for row in rows:
            core=by_id[row["appid"]]
            for position in ("first","middle","end"):
                node=conn.execute("SELECT display_name,description FROM achievements WHERE appid=? AND local_id=?",
                                  (row["appid"],core[position+"_local_id"])).fetchone()
                if node is None or node["display_name"]!=row[position+"_display_name"]:
                    raise ValueError("任务6案例节点原文与T1选点不一致")
                row[position+"_description"]=node["description"]
    audit.update({"upstream_manifest_sha256":hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  "upstream_data_sha256":hashlib.sha256((folder/"data.json").read_bytes()).hexdigest(),
                  "three_point_appids_sha256":digest(expected_ids)})
    return rows,catalog,audit


def jaccard(a: Json, b: Json) -> Fraction:
    """Compute exact set similarity, excluding vague labels but preserving the original label list."""
    x,y = set(a["similarity_labels"]),set(b["similarity_labels"])
    return Fraction(len(x & y),len(x | y)) if x | y else Fraction(0)


def eligible_peer(target: Json, peer: Json, config: Json) -> bool:
    """Choose peers only by identity, tags, ending type, and optional source background values."""
    if target["appid"] == peer["appid"] or target["ending_type"] != peer["ending_type"]:
        return False
    if jaccard(target,peer) < Fraction(str(config["jaccard_min"])):
        return False
    if config["steam_gap_max"] is not None:
        a = Fraction(target["positive"],target["review_count"])
        b = Fraction(peer["positive"],peer["review_count"])
        if abs(a-b) > Fraction(str(config["steam_gap_max"])):
            return False
    if config["hours_ratio_max"] is not None:
        a,b = target["hltb_main_hours"],peer["hltb_main_hours"]
        if a is None or b is None or max(a,b)/min(a,b) > config["hours_ratio_max"]:
            return False
    return True


def summarize_target(target: Json, peers: list[Json], config_name: str) -> Json:
    """Summarize equal-weight reference games; differences are fractions, not percentages."""
    missing_length = config_name == "length_close" and target["hltb_main_hours"] is None
    status = "missing_target_length" if missing_length else "available" if len(peers)>=MIN_PEERS else "insufficient_peers"
    result = {"config":config_name, **target, "peer_status":status,"peer_n":len(peers),
              "peer_appids_sha256":digest([p["appid"] for p in peers]),
              "known_issue_peer_n":sum(bool(p["known_caveat"]) for p in peers)}
    for field in PROGRESS:
        values = [p[field] for p in peers]
        q1,median,q3 = map(float,np.quantile(values,[.25,.5,.75])) if status=="available" else (None,None,None)
        result.update({field+"_reference_q1":q1,field+"_reference_median":median,field+"_reference_q3":q3,
                       field+"_delta":target[field]-median if median is not None else None,
                       field+"_peer_percentile":(sum(v<target[field] for v in values)+.5*sum(v==target[field] for v in values))/len(values)
                           if status=="available" else None})
    return result


def compute(games: list[Json]) -> tuple[list[Json], list[Json], list[Json]]:
    """Build all five frozen background comparisons, keeping insufficient and missing targets."""
    results,membership,coverage = [],[],[]
    for name,config in CONFIGS.items():
        rows = []
        for target in games:
            peers = sorted([p for p in games if eligible_peer(target,p,config)],
                           key=lambda p:(-jaccard(target,p),p["appid"]))
            rows.append(summarize_target(target,peers,name))
            for peer in peers:
                membership.append({"config":name,"appid":target["appid"],"peer_appid":peer["appid"],
                                   "peer_name_en":peer["name_en"],"jaccard":float(jaccard(target,peer)),
                                   "peer_gameplay_labels":peer["gameplay_labels"],"peer_ending_type":peer["ending_type"],
                                   "peer_known_caveat":peer["known_caveat"],
                                   "peer_steam_positive_ratio":peer["steam_positive_ratio"],"peer_hltb_main_hours":peer["hltb_main_hours"],
                                   **{f:peer[f] for f in PROGRESS}})
        results.extend(rows)
        eligible = [r for r in rows if r["peer_status"]!="missing_target_length"]
        coverage.append({"config":name,"cohort_n":len(rows),"eligible_target_n":len(eligible),
                         "available_n":sum(r["peer_status"]=="available" for r in rows),
                         "at_least10_peers":sum(r["peer_n"]>=10 for r in rows),
                         "insufficient_n":sum(r["peer_status"]=="insufficient_peers" for r in rows),
                         "missing_length_n":sum(r["peer_status"]=="missing_target_length" for r in rows),
                         "median_peer_n":float(np.median([r["peer_n"] for r in eligible]))})
    expected = {"main":(183,181,160),"score_close":(183,165,138),"length_close":(68,46,33)}
    for row in coverage:
        if row["config"] in expected and (row["eligible_target_n"],row["available_n"],row["at_least10_peers"]) != expected[row["config"]]:
            raise ValueError(f"参照覆盖与已核验规划不同：{row}")
    return results,membership,coverage


def sensitivities(results: list[Json]) -> list[Json]:
    """Pair the same target across reference conditions; missing comparisons remain missing."""
    indexed = {(r["config"],r["appid"]):r for r in results}
    rows = []
    for main in (r for r in results if r["config"]=="main"):
        row = {"appid":main["appid"],"name_en":main["name_en"],"main_peer_n":main["peer_n"],
               "main_delta":main[PROGRESS[2]+"_delta"]}
        for name in ("jaccard04","jaccard06","score_close","length_close"):
            other = indexed[name,main["appid"]]
            a,b = main[PROGRESS[2]+"_delta"],other[PROGRESS[2]+"_delta"]
            row.update({name+"_status":other["peer_status"],name+"_peer_n":other["peer_n"],name+"_delta":b,
                        name+"_same_direction":(a>0)==(b>0) and a!=0 and b!=0 if a is not None and b is not None else None})
        row["jaccard_direction_stable"] = row["jaccard04_same_direction"] is True and row["jaccard06_same_direction"] is True
        rows.append(row)
    return rows


def choose_cases(results: list[Json], sensitivity: list[Json]) -> list[Json]:
    """Choose up to three positive and two negative stable cases, keeping known issues out of automatic promotion."""
    stable = {r["appid"]:r for r in sensitivity}
    available = [r for r in results if r["config"]=="main" and r["peer_n"]>=MIN_CASE_PEERS
                 and not r["known_caveat"] and stable[r["appid"]]["jaccard_direction_stable"]
                 and abs(r[PROGRESS[2]+"_delta"])>=.10]
    selected = []
    for positive,limit in ((True,3),(False,2)):
        group = sorted([r for r in available if (r[PROGRESS[2]+"_delta"]>0)==positive],
                       key=lambda r:(-abs(r[PROGRESS[2]+"_delta"]),-r["peer_n"],r["appid"]))
        selected.extend(group[:limit])
    return [{**r,"case":chr(65+i),"selection_reason":"at least10 peers; |delta|>=10pp; stable Jaccard .4/.5/.6; no documented issue"}
            for i,r in enumerate(selected)]
