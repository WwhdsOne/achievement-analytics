"""任务6入口与查询：同类参照、补充条件、可解释案例和只读网页数据。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from reputation_data import ROOT, Json, PROGRESS, csv_text, digest, owned, source, write
from compare_games import load_catalog, select_games
from benchmark_data import (VERSION, DEFAULT_OUTPUT, CONFIGS, MIN_PEERS, MIN_CASE_PEERS,
                            load_inputs, prior_snapshot, compute, sensitivities, choose_cases)

CONFIG_NAMES = {"main":"多标签主参照","jaccard04":"相似度≥0.4","jaccard06":"相似度≥0.6",
                "score_close":"主参照＋好评差≤10个百分点","length_close":"主参照＋主线时长比≤2"}


def scalar_rows(rows: list[Json]) -> list[Json]:
    """Flatten label lists for CSV while retaining lists in JSON."""
    return [{k:"|".join(v) if isinstance(v,list) else v for k,v in row.items()} for row in rows]


def selections(package: Json, catalog: list[Json], selectors: list[str] | None, kind: str) -> list[Json]:
    """Resolve optional 1–5 games without changing their precomputed reference groups."""
    if kind not in ("mixed","appid","name"):
        raise ValueError("kind必须为mixed、appid或name")
    chosen = select_games(catalog,selectors,kind) if selectors is not None else package["cases"]
    rows = {r["appid"]:r for r in package["results"]}
    sensitivity = {r["appid"]:r for r in package["sensitivity"]}
    result = []
    for game in chosen:
        appid=game["appid"]
        if appid in rows:
            row={**rows[appid]}
            if selectors is None:row["case"]=game["case"]
        else:
            row={"appid":appid,"name_en":game["title"],"name_zh":game.get("name_zh"),
                 "peer_status":"outside_three_point_cohort","peer_n":0,"gameplay_labels":game["gameplay_labels"],
                 "ending_type":game["ending_type"],"known_caveat":"仅两个有效节点，不在任务6完整三节点范围。",
                 **{f+"_delta":None for f in PROGRESS}}
        row["references"]=[r for r in package["membership"] if r["config"]=="main" and r["appid"]==appid]
        row["sensitivity"]=sensitivity.get(appid)
        result.append(row)
    return result


def matched_sensitivity(package: Json) -> list[Json]:
    """Compare each condition on the same valid target intersection, not different populations."""
    indexed={(r["config"],r["appid"]):r for r in package["sensitivity_results"]}
    result=[]
    for name in ("jaccard04","jaccard06","score_close","length_close"):
        pairs=[(r,indexed[name,r["appid"]]) for r in package["results"]
               if r["peer_status"]=="available" and indexed[name,r["appid"]]["peer_status"]=="available"]
        a=[r[PROGRESS[2]+"_delta"] for r,_ in pairs]
        b=[r[PROGRESS[2]+"_delta"] for _,r in pairs]
        nonzero=[(x,y) for x,y in zip(a,b) if x!=0 and y!=0]
        result.append({"config":name,"common_valid_target_n":len(pairs),"nonzero_pair_n":len(nonzero),
                       "same_direction_n":sum((x>0)==(y>0) for x,y in nonzero),
                       "main_delta_median":float(np.median(a)) if a else None,
                       "condition_delta_median":float(np.median(b)) if b else None,
                       "median_absolute_delta_change":float(np.median([abs(y-x) for x,y in zip(a,b)])) if a else None,
                       "common_appids_sha256":digest([r["appid"] for r,_ in pairs])})
    return result


def read_prepared() -> Json:
    """Read already prepared task6 data and reject stale input versions without computing references."""
    manifest_path=DEFAULT_OUTPUT/"manifest.json"
    if not manifest_path.is_file():
        raise ValueError("请先运行run.py benchmark生成同类参照底表")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if not all(manifest["checks"].values()) or manifest["version"]!=VERSION:
        raise ValueError("任务6产物版本或核验状态不匹配，请先复跑benchmark")
    data_path=DEFAULT_OUTPUT/"data.json"
    key=str(data_path.relative_to(ROOT))
    if hashlib.sha256(data_path.read_bytes()).hexdigest()!=manifest["outputs_sha256"][key]:
        raise ValueError("任务6data.json已改变")
    upstream=ROOT/"output"/"reputation"/"manifest.json"
    if hashlib.sha256(upstream.read_bytes()).hexdigest()!=manifest["source"]["upstream_manifest_sha256"]:
        raise ValueError("任务5上游版本已改变，请先复跑benchmark")
    return json.loads(data_path.read_text(encoding="utf-8"))


def query_benchmark(selectors: list[str] | None = None, kind: str = "mixed") -> Json:
    """Return frozen background and reference details for 1–5 names/AppIDs, without writes or recomputation."""
    package=read_prepared()
    catalog,audit=load_catalog()
    if any(audit[k]!=package["source"][k] for k in ("dataset_version","game_metrics_sha256","manifest_sha256")):
        raise ValueError("任务6与当前T1版本不同")
    background=[r for r in package["results"] if r["peer_status"]=="available"]
    return {"version":package["version"],"source":package["source"],"parameters":package["parameters"],
            "units":package["units"],"background":background,"background_n":len(background),
            "game_catalog":package["game_catalog"],"coverage":package["coverage"],
            "matched_sensitivity":package["matched_sensitivity"],
            "selected":selections(package,catalog,selectors,kind),
            "selection_mode":"manual" if selectors is not None else "automatic_cases",
            "selection_changes_background":False}


def list_benchmark_games() -> list[Json]:
    """List the original198 choices with explicit three-node/reference availability."""
    package=read_prepared()
    catalog,_=load_catalog()
    rows={r["appid"]:r for r in package["results"]}
    return [{"appid":g["appid"],"name_en":g["title"],"name_zh":g.get("name_zh"),
             "peer_status":rows[g["appid"]]["peer_status"] if g["appid"] in rows else "outside_three_point_cohort",
             "peer_n":rows[g["appid"]]["peer_n"] if g["appid"] in rows else 0} for g in catalog]


def report(package: Json, output: Path, figures: Path) -> str:
    """Explain observed peer differences, data coverage, selection criteria and limitations."""
    def cell(value: object) -> str:
        return str(value).replace("|","/").replace("\n"," ")
    def image(stem: str) -> str:
        return Path(os.path.relpath(figures/(stem+".png"),output)).as_posix()
    valid=[r for r in package["results"] if r["peer_status"]=="available"]
    high=sum(r[PROGRESS[2]+"_delta"]>0 for r in valid)
    low=sum(r[PROGRESS[2]+"_delta"]<0 for r in valid)
    rows=["# 专题6：相对同类的主线推进表现", "",f"版本：{VERSION}。运行时间：{source.now()}。",
          f"冻结来源：{package['source']['dataset_version']}，不是今天实时数据。", "",
          "## 范围与方法", "",
          "沿用198款底表中的183款完整三节点游戏；既有分类、数组位置中位节点和代表结局不变。旧库HLTB仅作68款长度补充，评分沿用任务5SteamSpy正负评价数。",
          "完整gameplay集合用于Jaccard=交集数量/并集数量，忽略other与uncertain但保留原标签；相似度≥0.5、结局口径相同、排除自身，其他参照游戏等权。",
          "不使用推进值挑参照，也不按相似度对结果加权。至少5款参照才报中位数、Q1/Q3、推进差与参照内百分位；不足时原值和参照数量保留、统计留空，不自动放宽条件。",
          "推进差=目标实际值−参照游戏该指标中位数，内部单位0～1，展示差乘100为百分点；参照内百分位=(低于目标款数＋0.5×同值款数)/n。",
          "前/后/全程各自取游戏级中位数，三项参照名单相同；三个中位数不能相乘，三项差值不能相加。箱体是参照游戏间四分位范围，不是置信区间。", "",
          "这是留一同类描述基准，不是交叉验证预测模型；没有回归、SHAP、用户级留存推断或因果控制。183款不代表全部Steam，多个目标的参照可能重叠，不能当成独立重复实验。", "",
          "## 实际覆盖", "", "| 条件 | 待分析范围 | 有效参照≥5 | 参照≥10 | 参照不足 | 缺目标时长 | 参照数中位数 |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for r in package["coverage"]:
        rows.append(f"| {CONFIG_NAMES[r['config']]} | {r['eligible_target_n']} | {r['available_n']} | {r['at_least10_peers']} | {r['insufficient_n']} | {r['missing_length_n']} | {r['median_peer_n']:g} |")
    rows += ["",f"主参照有效{len(valid)}款：高于参照{high}款、低于参照{low}款、相等{len(valid)-high-low}款。每款的参照不同，正负数量不要求对半。", "",
             "主口径参照不足的游戏："+"；".join(f"{g['appid']} {cell(g['name_en'])}（n={g['peer_n']}）" for g in package["results"] if g["peer_status"]!="available")+"。", "",
             "长度条件使用较宽的两倍时长带来建立一组参照，与任务5找成对案例的1.25倍条件用途不同；不声称完全匹配长度。缺失不补值、不要求所有183款都具备HLTB。", "",
             "## 条件对照：同一批目标游戏", "",
             "以下只在主参照与相应条件都有效的目标交集比较；差值变化来自参照名单变化，目标实际推进未改变。方向一致只表示相对位置符号一致，不是统计显著性。", "",
             "| 条件 | 共同有效目标 | 两差均非零 | 方向一致 | 主差中位数 | 条件差中位数 | 差变动绝对值中位数 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in package["matched_sensitivity"]:
        rows.append(f"| {CONFIG_NAMES[r['config']]} | {r['common_valid_target_n']} | {r['nonzero_pair_n']} | {r['same_direction_n']} | {r['main_delta_median']*100:+.2f}pp | {r['condition_delta_median']*100:+.2f}pp | {r['median_absolute_delta_change']*100:.2f}pp |")
    rows += ["", "## 自动案例与选择规则", "",
             "主参照至少10款、全程差绝对值≥10个百分点，Jaccard≥0.4/0.5/0.6下均至少5参照且差值方向一致；按差绝对值降序、参照数降序、AppID升序，最多取3个正向和2个负向。",
             "已在任务5记录具体语义疑点的6款不自动推荐，但仍参与完整计算和参照，已知疑点参照数单列。未列疑点不等于已人工核验；案例是探索性偏离，不是游戏质量或设计排行榜。", "",
             "| 案例 | AppID | 游戏 | 全部玩法标签 | 参照n | 实际全程 | 参照中位数 | 差值 | 参照内百分位 |", "|---|---:|---|---|---:|---:|---:|---:|---:|"]
    for r in package["cases"]:
        rows.append(f"| {r['case']} | {r['appid']} | {cell(r['name_en'])} | {cell(r['gameplay_labels'])} | {r['peer_n']} | {r[PROGRESS[2]]:.1%} | {r[PROGRESS[2]+'_reference_median']:.1%} | {r[PROGRESS[2]+'_delta']*100:+.1f}pp | {r[PROGRESS[2]+'_peer_percentile']:.1%} |")
    rows += ["", "案例数量不足时不凑数。同系列、相同标签或重叠参照会使多个案例相关，不能把每款当成独立的设计效果证据。",
             "每个目标的完整参照名单保存在peer_membership.csv，包括相似度、标签、评分、HLTB时长和已知节点提示。", "",
             "### 自动案例的原始三节点", "",
             "| AppID | 游戏 | 首节点描述 | 中节点描述 | 末节点描述 | 来源标记 |", "|---:|---|---|---|---|---|"]
    for r in package["cases"]:
        descriptions=" | ".join(cell(r[p+"_description"]) if r[p+"_description"] is not None else "缺失" for p in ("first","middle","end"))
        rows.append(f"| {r['appid']} | {cell(r['name_en'])} | {descriptions} | {cell(r['quality_flags'])} |")
    rows += ["", "例如Pony Island末节点含Learned every secret of your past（全部秘密）要求，不能直接当成普通剧情结局；STEINS;GATE中位节点描述缺失；The Walking Dead: The Final Season的末节点只标Completed Act Three，覆盖是否等于整部游戏结局仍待人工核对。",
             "自动案例只是按数据规则挑出的核查对象，并非通过了语义质量审查。保留原文比把高/低差值直接归因于设计更重要。", "",
             "## 节点可比性限制", "",
             "同结局口径只区分unified/multi代理，不证明末节点任务要求等价。来源中的“全部任务线”“100%战役”“特定模式”“一局胜利”及教程中位节点、描述缺失等疑点继续保留；没有在本轮改分类、顺序或数据库。", "",
             "| AppID | 游戏 | 已记录疑点 | 主参照n | 实际−参照 |", "|---:|---|---|---:|---:|"]
    for r in package["results"]:
        if not r["known_caveat"]:continue
        gap=r[PROGRESS[2]+"_delta"]
        rows.append(f"| {r['appid']} | {cell(r['name_en'])} | {r['known_caveat']} | {r['peer_n']} | {gap*100:+.1f}pp |" if gap is not None else
                    f"| {r['appid']} | {cell(r['name_en'])} | {r['known_caveat']} | {r['peer_n']} | 不足5参照 |")
    rows += ["", "不是所有目标或参照都做过逐项人工语义核验，因此不能把相对差值称为真实留存优势。强结论应先对目标及主要参照的节点含义作人工复核；本轮不把全面人工核验设为运行前置。", "",
             "## 本次图中所选游戏", "", "| AppID | 游戏 | 可用状态 | 参照数 |", "|---:|---|---|---:|"]
    for r in package["selected"]:
        rows.append(f"| {r['appid']} | {cell(r['name_en'])} | {r['peer_status']} | {r['peer_n']} |")
    rows += ["", "上述选择仅影响描边和20/21展示对象，前面自动案例表与总体条件统计不随选择变化。", "",
             "## 图表与读法", "",
             f"![19同类参照散点]({image('19_peer_benchmark')})", "",
             "19：全部有效目标构成固定背景；对角线上方表示实际全程高于其同类参照，不表示该游戏绝对完成率更高，也不是模型预测准确度图。选择只加描边。", "",
             f"![20阶段差]({image('20_peer_stage_gaps')})", "",
             "20：各阶段的实际值减同阶段参照中位数。可以定位相对差距在前段还是后段，但不是时间轨迹或玩家流失归因。", "",
             f"![21案例分布]({image('21_peer_cases')})", "",
             "21：蓝点为其他参照游戏，箱体Q1～Q3、须最小～最大、黑菱形为目标；右侧卡片含最相似参照和语义提示。参照不足或两节点选择保留说明，不补零点。", "",
             "## 产物、交互与后续", "",
             "[游戏主参照](peer_benchmark.csv)、[915行条件结果](peer_conditions.csv)、[完整参照名单](peer_membership.csv)、[覆盖](peer_coverage.csv)、",
             "[逐目标条件对照](benchmark_sensitivity.csv)、[共同交集汇总](matched_sensitivity.csv)、[自动案例](benchmark_cases.csv)、[节点提示](semantic_caveats.csv)。",
             "data.json含183款、全部参照条件、案例与名录；manifest保存源版本、代码/产物指纹和数据库及既有1～18图/输出保护。CSV/JSON为本地忽略产物，网页发布需单独交接。",
             "query_benchmark支持1～5款AppID/已有中英文名，从已准备数据取结果，不重新计算参照。183款以外但在原198款内的选择保留两节点提示；主参照不足保留n与缺失原因。",
             "总体19图及所有参照始终固定；20/21展示所选游戏。后端不需要重新抓取、调用模型或将Python依赖装入Go网页。未实现HTTP服务或网页部署。",
             "下一步可人工抽查突出案例及其主要参照的节点语义，再讨论是否需要普通结局子样本；不因差值大就自动改数据。当前未训练回归模型，不声称已经排除所有可观察差异。", ""]
    return "\n".join(rows)


def analyze(selectors: list[str] | None = None, kind: str = "mixed") -> Json:
    """Run an auditable peer baseline, write only task6 paths, and preserve previous outputs."""
    before=prior_snapshot()
    games,catalog,audit=load_inputs()
    results,membership,coverage=compute(games)
    sensitivity=sensitivities(results)
    cases=choose_cases(results,sensitivity)
    package={"version":VERSION,"source":audit,"cohort":games,
             "results":[r for r in results if r["config"]=="main"],"sensitivity_results":results,
             "membership":membership,"coverage":coverage,"sensitivity":sensitivity,"cases":cases,
             "parameters":{"configs":CONFIGS,"min_peers":MIN_PEERS,"min_case_peers":MIN_CASE_PEERS,
                           "excluded_similarity_labels":["other","uncertain"],"peer_weighting":"equal",
                           "case_absolute_delta_min":.10,"case_max_positive":3,"case_max_negative":2},
             "units":{"progress":"0_to_1","delta":"fraction; multiply100 for percentage points","peer_percentile":"0_to_1"}}
    package["matched_sensitivity"]=matched_sensitivity(package)
    main_rows={r["appid"]:r for r in package["results"]}
    package["game_catalog"]=[{"appid":g["appid"],"name_en":g["title"],"name_zh":g.get("name_zh"),
                              "gameplay_labels":g["gameplay_labels"],"node_count":g["node_count"],
                              "peer_status":main_rows[g["appid"]]["peer_status"] if g["appid"] in main_rows else "outside_three_point_cohort",
                              "peer_n":main_rows[g["appid"]]["peer_n"] if g["appid"] in main_rows else 0} for g in catalog]
    package["selected"]=selections(package,catalog,selectors,kind)
    package["selection_mode"]="manual" if selectors is not None else "automatic_cases"
    package["selection_changes_background"]=False
    if not package["selected"]:
        raise ValueError("暂无符合条件的自动案例，可用--games选择1～5款查看，不降低自动条件")
    output=owned(ROOT/"output"/"benchmark_selections"/digest([g["appid"] for g in package["selected"]])[:12]) if selectors else DEFAULT_OUTPUT
    figures=owned(output/"figures" if selectors else ROOT/"figures")
    output.mkdir(parents=True,exist_ok=True);figures.mkdir(parents=True,exist_ok=True)
    tables={"peer_benchmark.csv":package["results"],"peer_conditions.csv":results,"peer_membership.csv":membership,
            "peer_coverage.csv":coverage,"benchmark_sensitivity.csv":sensitivity,"matched_sensitivity.csv":package["matched_sensitivity"],
            "benchmark_cases.csv":cases,"semantic_caveats.csv":[{k:g[k] for k in ("appid","name_en","known_caveat","semantic_review_status")} for g in games]}
    for name,rows in tables.items():
        if rows:write(output/name,csv_text(scalar_rows(rows)))
    write(output/"data.json",json.dumps(package,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    from benchmark_plots import draw_overview,draw_stage_gaps,draw_cases,FIGURES
    draw_overview(package["results"],package["selected"],figures)
    draw_stage_gaps(package["selected"],figures)
    draw_cases(package["selected"],membership,figures)
    write(output/"report.md",report(package,output,figures))
    after=prior_snapshot()
    checks={"previous_databases_outputs_and_figures_unchanged":before==after,
            "fixed183_distinct_targets":len(games)==len({g["appid"] for g in games})==183,
            "no_target_is_own_peer":all(r["appid"]!=r["peer_appid"] for r in membership),
            "condition_results_complete":len(results)==len(CONFIGS)*183,
            "missing_references_not_zero_filled":all(r[PROGRESS[2]+"_delta"] is None for r in results if r["peer_status"]!="available"),
            "selection_size1_to5":1<=len(package["selected"])<=5}
    if not all(checks.values()):raise ValueError(f"任务6核验失败：{checks}")
    generated=[output/name for name,rows in tables.items() if rows]+[output/"data.json",output/"report.md"]
    generated += [figures/(stem+suffix) for stem in FIGURES for suffix in (".png",".svg")]
    implementation=[Path(__file__),ROOT/"benchmark_data.py",ROOT/"benchmark_plots.py",ROOT/"run.py",ROOT/"reputation_data.py"]
    manifest={"analyzed_at":source.now(),"version":VERSION,"source":audit,"parameters":package["parameters"],
              "coverage":coverage,"checks":checks,"output_counts":{name:len(rows) for name,rows in tables.items()},
              "implementation_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in implementation},
              "outputs_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in generated},
              "protected_before":before,"protected_after":after}
    write(output/"manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return {"state":"success","coverage":coverage,"automatic_case_appids":[g["appid"] for g in cases],
            "selected_appids":[g["appid"] for g in package["selected"]],"report":str(output/"report.md"),"figures":str(figures),"checks":checks}
