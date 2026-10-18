"""任务5口碑分析与任务6同类参照：只读冻结输入，独立生成分析数据与图表。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from reputation_data import (ROOT, VERSION, Json, LABELS, PROGRESS, SCORES, csv_text,
                             digest, finite, owned, protected, query_reputation, source, write)
from reputation_stats import (BOOTSTRAP, SEED, correlations, correlation_differences,
                              matched_cases, quadrants)


def distribution(games: list[Json], cohort: str, fields: tuple[str, ...]) -> list[Json]:
    """Describe score and progression distributions at the game level, without review weighting."""
    import numpy as np
    result = []
    for field in fields:
        values = [g[field] for g in games]
        q1, median, q3 = map(float,np.quantile(values,[.25,.5,.75]))
        result.append({"cohort":cohort,"field":field,"n":len(games),"min":min(values),
                       "q1":q1,"median":median,"q3":q3,"max":max(values)})
    return result


def report_text(package: Json, stats: list[Json], differences: list[Json], groups: list[Json],
                cases: list[Json], pairs: list[Json], chosen: list[Json], output: Path, figures: Path) -> str:
    """Document measured associations, missingness, transparent case selection and interpretation limits."""
    import os
    def link(path: Path) -> str:
        return Path(os.path.relpath(path,output)).as_posix()
    lines=["# 专题5：口碑与主线推进", "", f"运行时间：{source.now()}。版本：{VERSION}。",
           f"数据版本：`{package['source']['dataset_version']}`；冻结快照，不是运行当天实时评分。", "",
           "## 样本与来源", "", "| 项目 | 游戏数 |", "|---|---:|",
           "| 固定主线底表 | 198 |", "| 完整且不同的首、中、末节点及全部推进比有效 | 183 |",
           "| 排除的两节点游戏 | 15 |", "| Steam好评率有效 | 183 |",
           "| Metacritic有效（43款NULL） | 140 |", "| RAWG正值评分（5款NULL、5款零） | 173 |",
           "| 三种评分共同有效 | 140 |", "| 正值HLTB主线参考耗时补充 | 68 |",
           "| 三种评分与HLTB共同有效 | 61 |", "",
           "任务5三个方向全部从183款完整三节点出发；图16、17同183款，图18三个面板固定同140款。",
           "数组位置中位节点、代表结局与类型沿用T1，不重排、不重新标注。分母须正，缺失不补零，分子有效零保留。", "",
           "主评分只读借用库`games.payload`：SteamSpy `positive/(positive+negative)`，逐款核对`review_count=positive+negative`；",
           "媒体评分取`rawg.metacritic`（0～100，正值）；玩家评分取`rawg.rating`（0～5，正值）。RAWG零分保留原值和状态供审计，不解释成低口碑。",
           "未使用旧库`games_rate.review_percent`混合补值。旧库仅以AppID补充`games_time.main_hours`供案例匹配，不改变评分样本。",
           "逐项来源时间、原始零分、评分人数、类型、质量标记与198款排除台账均保存；RAWG媒体评分的源是RAWG中的Metacritic字段，不是另行请求Metacritic。", "",
           "## 方法与统计结果", "",
           "每款游戏等权。Spearman并列取平均秩；整行游戏级Bootstrap 2000次、种子42、百分位95%区间，每次重采样后重新排名。",
           "同140款三种评分共享相同抽样下标，系数差用同轮差值形成区间；不以区间是否跨零筛选或隐藏结果，不把三平台评分合成总分。",
           "区间刻画该固定游戏集合的重采样波动，不是评论者/成就玩家的抽样误差，不能代表全部Steam。", "",
           "| 样本 | 评分 | 推进指标 | n | Spearman ρ | 95%重采样区间 |",
           "|---|---|---|---:|---:|---|"]
    for r in stats:
        lines.append(f"| {r['cohort']} | {LABELS[r['score']]} | {LABELS[r['metric']]} | {r['n']} | {r['spearman']:+.3f} | [{r['interval_low']:+.3f}, {r['interval_high']:+.3f}] |")
    primary=next(r for r in stats if r["cohort"]=="steam183" and r["metric"]==PROGRESS[2])
    stage=sorted([r for r in stats if r["cohort"]=="steam183"],key=lambda r:-abs(r["spearman"]))[0]
    lines += ["", f"**观测：** 同183款Steam好评率与全程推进ρ={primary['spearman']:+.3f}；三个阶段中绝对相关最大的为{LABELS[stage['metric']]}（ρ={stage['spearman']:+.3f}）。",
              "**解释：** 评分与推进可同时反映不同体验维度；相关强弱不证明哪个阶段导致评价，也不能用它推断个人评论与通关行为的对应关系。",
              "**使用：** 对照图中的分布和案例阅读；原始有效覆盖183/140/173只用于缺失说明，跨评分结论以共同140款为准。", "",
              "### 同样本评分相关系数差", "", "| 评分A − 评分B | 推进指标 | ρ差 | 95%成对区间 |", "|---|---|---:|---|"]
    for r in differences:
        lines.append(f"| {LABELS[r['score_a']]} − {LABELS[r['score_b']]} | {LABELS[r['metric']]} | {r['rho_a_minus_b']:+.3f} | [{r['interval_low']:+.3f}, {r['interval_high']:+.3f}] |")
    lines += ["", "区间跨零时，这一快照不足以稳定区分两种评分的关联强度；未跨零也不意味着该评分更真实或有因果解释力。", "",
              "### 起点、结局及评价人数对照", "",
              "这些子样本仍要求完整三节点，不替换183款主分析；各子集游戏名单及指纹保存在sensitivity_correlations.csv。", "",
              "| 子集 | n | 前段ρ | 后段ρ | 全程ρ |", "|---|---:|---:|---:|---:|"]
    for subset,label in (("single_start","单一start标签"),("unified_ending","统一结局"),("multi_ending","多结局代理")):
        values=[r for r in package["sensitivity"] if r["cohort"]==subset]
        lines.append(f"| {label} | {values[0]['n']} | " + " | ".join(f"{r['spearman']:+.3f}" for r in values)+" |")
    lines += ["", "分组后关联强度变化说明结局口径与游戏构成值得关注；这些子集也有其他属性差异，不能据此归因。完整区间见CSV。",
              "共同140款RAWG评价人数均≥50，加入这一人数要求后仍为同140款、统计不变；不把所有183款都当成评分人数达标。", "",
              "## 四象限与案例", "", "两轴分界均用同183款样本中位数；等于中位数归高组。“高/低”是样本内相对位置，不是绝对评价等级。", "",
              "| 象限 | 游戏数 |", "|---|---:|"]
    for r in groups:
        lines.append(f"| {r['quadrant']} | {r['n']} |")
    lines += ["",f"Steam分界{groups[0]['steam_median']:.4%}，全程推进分界{groups[0]['overall_median']:.4%}。",
              "每象限按两个维度百分位秩偏离0.5的绝对值乘积最大选一款，并列按AppID；百分位秩=(平均秩−0.5)/183。案例为空间极端示例，不是随机或典型样本，不声称控制类型/长度。", "",
              "| 案例 | AppID | 游戏 | 好评率 | 全程推进 |", "|---|---:|---|---:|---:|"]
    for c in cases:
        lines.append(f"| {c['case']} | {c['appid']} | {c['name_en'].replace('|','/')} | {c['steam_positive_ratio']:.2%} | {c['overall_progress_ratio']:.2%} |")
    lines += ["", "### 同类同长度补充案例", "",
              f"68款有HLTB的完整三节点游戏中，同主类型、同结局口径且主线参考耗时最大/最小≤1.25形成 **{len(pairs)}对候选**，不是{len(pairs)}款游戏。",
              "只从评分差和推进差反向的组合中，按两个差值乘积绝对值降序选择最多3对不重复游戏；并列按推进差、AppID。",
              "这是探索性匹配案例，未控制所有混杂因素，不是因果配对研究。无足够组合时不补凑。", "",
              "| 游戏A | 游戏B | 主类型 | 主线参考耗时A/B | 好评差（百分点） | 推进差（百分点） |", "|---|---|---|---|---:|---:|"]
    for p in chosen:
        lines.append(f"| {p['name_a'].replace('|','/')} | {p['name_b'].replace('|','/')} | {p['primary_gameplay']} | {p['main_hours_a']:.2f}/{p['main_hours_b']:.2f}小时 | {p['steam_gap_pp']:.2f} | {p['overall_gap_pp']:.2f} |")
    lines += ["", "## 图表怎么读", "",
              f"![16口碑与推进四象限]({link(figures/'16_reputation_quadrants.png')})", "",
              "16：每点一款，两个虚线是固定183款中位数。看相对位置及分布，再读A～D极端案例；低组不等于游戏质量差。", "",
              f"![17口碑与三阶段推进]({link(figures/'17_reputation_stages.png')})", "",
              "17：横轴始终Steam好评率，纵轴依次前、后、全程比。三图同183款，比较ρ和区间；这三个指标数学相关，不能当成三次独立重复实验。", "",
              f"![18三种评分来源]({link(figures/'18_rating_sources.png')})", "",
              "18：同140款、相同全程比，各评分使用原单位。点云斜率不可跨单位直接比较，应比较秩相关及成对差值区间；140款结果不能冒充183款全样本。", "",
              "## 数据交接与边界", "",
              "CSV：reputation_eligibility.csv（198），reputation_cohort.csv（183），rating_common.csv（140），score_coverage.csv，score_summary.csv，",
              "reputation_correlations.csv，correlation_differences.csv，reputation_quadrants.csv，quadrant_cases.csv，matched_candidates.csv，matched_cases.csv。",
              "data.json含固定背景183款、共同背景140款、可选1～5款的明细及全局统计；选择只高亮，不改变背景、中位线、区间或相关系数。",
              "不在183款或缺共同评分的选择仍保留状态与缺失原因，供网页展示原因卡片，不在相应图中补零。当前提供本地CLI与无写入Python查询，不表示已部署网页。", "",
              "模型节点及数组顺序继续复用，代表结局不自动证明普通必经性；评论者与成就分母人群不同，不能称为日留存、弃坑率或因果效应。",
              "本轮不调用模型或远端API、不重分类、不写SQLite、不运行任务6建模。RAWG数据的网页展示须保留[RAWG来源回链](https://rawg.io/)。", ""]
    from reputation_exploration import exploration_report
    return "\n".join(lines)+"\n"+exploration_report(package["exploration"])


def analyze(selectors: list[str] | None = None, kind: str = "mixed") -> Json:
    """Execute the fixed-cohort loop and verify every earlier artifact and database remains unchanged."""
    before=protected()
    package=query_reputation(selectors,kind)
    games, common=package["background"],package["common_background"]
    selection_key=digest([[g["appid"] for g in package["selected"]]])[:12] if selectors else None
    output=owned(ROOT/"output"/(f"selections/{selection_key}" if selectors else "reputation"))
    figures=owned(output/"figures" if selectors else ROOT/"figures")
    output.mkdir(parents=True,exist_ok=True); figures.mkdir(parents=True,exist_ok=True)
    steam_stats,_=correlations(games,(SCORES[0],),"steam183")
    common_stats,draws=correlations(common,SCORES,"common140")
    stats=steam_stats+common_stats
    differences=correlation_differences(common_stats,draws)
    sensitivity=[]
    for label,members in (("single_start",[g for g in games if g["start_label_count"]==1]),
                          ("unified_ending",[g for g in games if g["ending_type"]=="unified"]),
                          ("multi_ending",[g for g in games if g["ending_type"]=="multi"])):
        subset_stats,_=correlations(members,(SCORES[0],),label)
        sensitivity.extend(subset_stats)
    # Same comparison in a more reviewed RAWG subset; retain the zero/missing audit separately.
    min50=[g for g in common if finite(g["rawg_ratings_count"]) and g["rawg_ratings_count"]>=50]
    if len(min50)!=len(common):
        subset_stats,_=correlations(min50,SCORES,"common_rawg_min50")
        sensitivity.extend(subset_stats)
    groups,cases,thresholds=quadrants(games)
    candidates,chosen=matched_cases(games)
    from reputation_exploration import build_exploration
    exploration,exploration_tables=build_exploration(games)
    counts=package["source"]["counts"]
    coverage=[{"source":s,"n":counts[k],"base":183,"coverage":counts[k]/183}
              for s,k in ((SCORES[0],"steam"),(SCORES[1],"metacritic"),(SCORES[2],"rawg"),("common","common"))]
    summary=distribution(games,"steam183",(SCORES[0],*PROGRESS))+distribution(common,"common140",(*SCORES,*PROGRESS))
    # Reuse the fully audited original rows for the exclusion ledger, not a separate ad-hoc query.
    from reputation_data import load_data
    _,eligibility,second_audit=load_data()
    if second_audit != package["source"]:
        raise ValueError("分析期间输入来源改变")
    artifacts={"reputation_eligibility.csv":eligibility,"reputation_cohort.csv":games,"rating_common.csv":common,
               "score_coverage.csv":coverage,"score_summary.csv":summary,"reputation_correlations.csv":stats,
               "correlation_differences.csv":differences,"sensitivity_correlations.csv":sensitivity,
               "reputation_quadrants.csv":groups,"quadrant_cases.csv":cases,
               "matched_candidates.csv":candidates,"matched_cases.csv":chosen,**exploration_tables}
    for name,rows in artifacts.items():
        if rows:
            write(output/name,csv_text(rows))
    package.update({"correlations":stats,"correlation_differences":differences,"sensitivity":sensitivity,
                    "quadrants":groups,"thresholds":thresholds,"quadrant_cases":cases,"matched_cases":chosen,
                    "exploration":exploration})
    write(output/"data.json",json.dumps(package,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    from reputation_plots import draw_quadrants,draw_panels
    draw_quadrants(games,cases,thresholds,steam_stats[-1],package["selected"],figures)
    draw_panels(games,steam_stats,package["selected"],figures,False)
    draw_panels(common,common_stats,package["selected"],figures,True)
    write(output/"report.md",report_text(package,stats,differences,groups,cases,candidates,chosen,output,figures))
    after=protected()
    checks={"protected_unchanged":before==after,"common_same_games_for_every_score":len(common)==140 and all(g["three_scores_common"] for g in common),
            "all_stages_same183":len(games)==183 and all(g["complete_three_point"] for g in games),
            "quadrants_partition183":sum(r["n"] for r in groups)==183,
            "common_rawg_min50_same140":len(min50)==140,
            "progress_product_identity":all(abs(g[PROGRESS[0]]*g[PROGRESS[1]]-g[PROGRESS[2]])<1e-12 for g in games)}
    if not all(checks.values()):
        raise ValueError(f"任务5核验失败：{checks}")
    generated=[output/name for name,rows in artifacts.items() if rows]+[output/"data.json",output/"report.md"]
    generated += [p for p in sorted(figures.glob("*")) if p.suffix in (".png",".svg") and p.name[:2] in ("16","17","18")]
    manifest={"analyzed_at":source.now(),"version":VERSION,"source":package["source"],"checks":checks,
              "parameters":{"bootstrap":BOOTSTRAP,"random_state":SEED,"steam_formula":"positive/(positive+negative)",
                            "three_point_required":True,"common_score_comparison":True,"rawg_min50_common":len(min50),
                            "matched_length_ratio_max":1.25,"selected_appids":[g["appid"] for g in package["selected"]],
                            "exploration_version":exploration["version"],"exploration_late_region":[.90,.80],
                            "joint_rank_weights":[.50,.50]},
              "output_counts":{name:len(rows) for name,rows in artifacts.items()},
              "protected_before":before,"protected_after":after,
              "implementation_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob("*.py"))},
              "outputs_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in generated}}
    write(output/"manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return {"state":"success","counts":counts,"report":str(output/"report.md"),"figures":str(figures),
            "matched_candidates":len(candidates),"matched_cases":len(chosen),"checks":checks}


def main() -> int:
    """Expose reproducible analysis and optional 1–5 AppID/English/Chinese-name highlights."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("reputation","benchmark"))
    selectors=parser.add_mutually_exclusive_group()
    selectors.add_argument("--games",nargs="+",help="1～5款AppID或已有中英文名称，背景与统计保持固定")
    selectors.add_argument("--appids",nargs="+",help="1～5个AppID")
    selectors.add_argument("--game-names",nargs="+",help="1～5个已有英文名或中文名")
    parser.add_argument("--list-games",action="store_true",help="只读列出198款名称及对应任务可用状态，不出图；benchmark需先准备底表")
    args=parser.parse_args()
    try:
        if args.list_games:
            if args.command=="benchmark":
                from benchmark import list_benchmark_games
                print(json.dumps(list_benchmark_games(),ensure_ascii=False,indent=2))
            else:
                from reputation_data import load_data
                _,rows,_=load_data()
                print(json.dumps([{k:g[k] for k in ("appid","name_en","name_zh","complete_three_point","three_scores_common")} for g in rows],ensure_ascii=False,indent=2))
        else:
            selected=args.games or args.appids or args.game_names
            kind="appid" if args.appids else "name" if args.game_names else "mixed"
            if args.command=="benchmark":
                from benchmark import analyze as benchmark_analyze
                print(json.dumps(benchmark_analyze(selected,kind),ensure_ascii=False,indent=2))
            else:
                print(json.dumps(analyze(selected,kind),ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError) as exc:
        print(f"{args.command}失败：{exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
