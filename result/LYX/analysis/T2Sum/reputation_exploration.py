"""对口碑图作可复现的探索解读：多标签构成、后段右上区域和双指标案例排序。"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
import json
import statistics

from scipy.stats import rankdata, spearmanr

from reputation_data import Json, PROGRESS, SCORES, digest, source
from compare_games import load_catalog
from analyze_types import TYPE_NAMES

REGION_STEAM_MIN = .90
REGION_LATE_MIN = .80
EXPLORATION_VERSION = "lyx-reputation-reading-v1"


def label_rows(members: list[Json], background: list[Json], scope: str, dimension: str) -> list[Json]:
    """Count overlapping labels once per game; show background and complement rather than raw counts only."""
    inside = Counter(t for g in members for t in g[dimension])
    total = Counter(t for g in background for t in g[dimension])
    n, base = len(members), len(background)
    result = []
    for tag in sorted(total):
        share = inside[tag]/n if n else None
        reference = total[tag]/base
        outside_share = (total[tag]-inside[tag])/(base-n) if base > n else None
        result.append({"scope":scope,"dimension":dimension,"tag":tag,"group_n":n,"tag_n":inside[tag],
                       "share":share,"background_n":base,"background_tag_n":total[tag],"background_share":reference,
                       "difference_pp":100*(share-reference) if n else None,
                       "lift_vs_background":share/reference if n else None,
                       "outside_n":base-n,"outside_tag_n":total[tag]-inside[tag],"outside_share":outside_share,
                       "descriptive_support":n>=10 and inside[tag]>=5 and total[tag]>=10})
    return result


def numeric_summary(members: list[Json], scope: str) -> Json:
    """Describe stage levels and observed reference hours, retaining their separate denominators."""
    result = {"scope":scope,"n":len(members),
              "multi_ending_n":sum(g["ending_type"]=="multi" for g in members),
              "single_start_n":sum(g["start_label_count"]==1 for g in members),
              "missing_start_n":sum(g["start_label_count"]==0 for g in members)}
    for field in ("p_s","p_m","p_f",*PROGRESS,"steam_positive_ratio"):
        result[field+"_median"] = statistics.median(g[field] for g in members) if members else None
    hours = [g["hltb_main_hours"] for g in members if g["hltb_main_hours"] is not None]
    result.update({"hltb_n":len(hours),"hltb_main_hours_median":statistics.median(hours) if hours else None})
    return result


def joint_rankings(games: list[Json]) -> tuple[list[Json], list[Json]]:
    """Rank equal-weight score/progression percentile positions, avoiding triple counting correlated stage ratios."""
    n=len(games)
    steam_ranks=rankdata([g[SCORES[0]] for g in games])
    overall_ranks=rankdata([g[PROGRESS[2]] for g in games])
    sr=(steam_ranks-.5)/n
    pr=(overall_ranks-.5)/n
    # Combine exact integer/half-integer ranks before division so theoretical ties
    # cannot be broken by independent floating-point percentile calculations.
    values=100*(.5*steam_ranks+.5*overall_ranks-.5)/n
    ranks=rankdata(-values)
    rows=[{**g,"steam_percentile":float(sr[i]),"overall_percentile":float(pr[i]),
           "joint_score":float(values[i]),"joint_rank":float(ranks[i])} for i,g in enumerate(games)]
    rows.sort(key=lambda r:(-r["joint_score"],r["appid"]))
    top={g["appid"] for g in rows[:5]}
    bottom={g["appid"] for g in sorted(rows,key=lambda r:(r["joint_score"],r["appid"]))[:5]}
    sensitivity=[]
    for weight in (.25,.5,.75):
        weighted=sorted([{**g,"weighted_score":float(100*(weight*steam_ranks[i]+(1-weight)*overall_ranks[i]-.5)/n)} for i,g in enumerate(games)],
                        key=lambda r:(-r["weighted_score"],r["appid"]))
        worst=sorted(weighted,key=lambda r:(r["weighted_score"],r["appid"]))[:5]
        sensitivity.append({"steam_weight":weight,"overall_weight":1-weight,
                            "top5_appids":"|".join(str(g["appid"]) for g in weighted[:5]),
                            "bottom5_appids":"|".join(str(g["appid"]) for g in worst),
                            "top5_overlap_equal_weight":len(top & {g["appid"] for g in weighted[:5]}),
                            "bottom5_overlap_equal_weight":len(bottom & {g["appid"] for g in worst})})
    return rows,sensitivity


def build_exploration(games: list[Json]) -> tuple[Json, dict[str,list[Json]]]:
    """Reuse frozen model labels and checkpoint text without relabeling or changing any cohort."""
    catalog,_=load_catalog()
    by_id={g["appid"]:g for g in catalog}
    ids=[g["appid"] for g in games]
    placeholders=",".join("?" for _ in ids)
    with source.connect(source.DEFAULT_DB) as conn:
        annotations={r[0]:json.loads(r[1]) for r in conn.execute(
            f"SELECT appid,payload FROM game_labels WHERE appid IN ({placeholders})",ids)}
    enriched=[]
    for g in games:
        types=by_id[g["appid"]]["gameplay_labels"].split("|")
        if annotations[g["appid"]]["gameplay"] != types or len(set(types)) != len(types):
            raise ValueError("多标签来源与T1底表不一致")
        row={**g,"gameplay_labels":"|".join(types),"types":types}
        for dimension in ("theme","presentation","player_mode"):
            # Free-text tags are kept as stored; no unapproved synonym merging.
            row[dimension]=sorted(set(annotations[g["appid"]].get(dimension,[])))
        enriched.append(row)
    sx=statistics.median(g[SCORES[0]] for g in games)
    sy=statistics.median(g[PROGRESS[2]] for g in games)
    groups={}
    for name,hx,hy in (("high_high",True,True),("high_low",True,False),("low_high",False,True),("low_low",False,False)):
        groups[name]=[g for g in enriched if (g[SCORES[0]]>=sx)==hx and (g[PROGRESS[2]]>=sy)==hy]
    region=[g for g in enriched if g[SCORES[0]]>=REGION_STEAM_MIN and g[PROGRESS[1]]>=REGION_LATE_MIN]
    high_review_other=[g for g in enriched if g[SCORES[0]]>=REGION_STEAM_MIN and g[PROGRESS[1]]<REGION_LATE_MIN]
    profiles=[]
    for scope,members in groups.items():
        profiles.extend(label_rows(members,enriched,scope,"types"))
    profiles.extend(label_rows(region,enriched,"late_upper_right","types"))
    profiles.extend(label_rows(region,[g for g in enriched if g[SCORES[0]]>=REGION_STEAM_MIN],"late_upper_right_within_high_review","types"))
    text_labels=[]
    for dimension in ("theme","presentation","player_mode"):
        text_labels.extend(label_rows(region,enriched,"late_upper_right",dimension))
    pairs=[]
    for scope,members in {**groups,"late_upper_right":region}.items():
        total=Counter(pair for g in enriched for pair in combinations(sorted(g["types"]),2))
        subset=Counter(pair for g in members for pair in combinations(sorted(g["types"]),2))
        for pair,count in sorted(total.items()):
            pairs.append({"scope":scope,"tag_a":pair[0],"tag_b":pair[1],"group_n":len(members),
                          "pair_n":subset[pair],"share":subset[pair]/len(members),"background_pair_n":count,
                          "background_share":count/len(enriched),
                          "lift_vs_background":(subset[pair]/len(members))/(count/len(enriched))})
    summaries=[numeric_summary(enriched,"all183")]+[numeric_summary(v,k) for k,v in groups.items()]
    summaries += [numeric_summary(region,"late_upper_right"),numeric_summary(high_review_other,"high_review_other")]
    boundaries=[]
    for steam in (.85,.90,.95):
        for late in (.70,.80,.90):
            members=[g for g in enriched if g[SCORES[0]]>=steam and g[PROGRESS[1]]>=late]
            puzzle=sum("puzzle" in g["types"] for g in members)
            boundaries.append({"steam_min":steam,"late_min":late,"n":len(members),"puzzle_n":puzzle,
                               "puzzle_share":puzzle/len(members) if members else None,
                               "puzzle_lift":(puzzle/len(members))/(sum("puzzle" in g["types"] for g in enriched)/len(enriched)) if members else None})
    rankings,weights=joint_rankings(enriched)
    top=rankings[:5]
    bottom=sorted(rankings,key=lambda r:(r["joint_score"],r["appid"]))[:5]
    top_ties=[g for g in rankings if g["joint_score"]==top[-1]["joint_score"]]
    bottom_ties=[g for g in rankings if g["joint_score"]==bottom[-1]["joint_score"]]
    special=[g for g in region if g[PROGRESS[0]]<.3]
    selected_ids={g["appid"] for g in [*top,*bottom,*special,*top_ties,*bottom_ties]}
    node_rows=[]
    with source.connect(source.DEFAULT_DB) as conn:
        for appid in sorted(selected_ids):
            for position in ("first","middle","end"):
                core=by_id[appid]
                node=conn.execute("SELECT display_name,description,percent FROM achievements WHERE appid=? AND local_id=?",
                                  (appid,core[position+"_local_id"])).fetchone()
                if node is None or node["display_name"]!=core[position+"_display_name"]:
                    raise ValueError("案例节点与源成就不一致")
                node_rows.append({"appid":appid,"name_en":core["title"],"position":position,
                                  "source_checkpoint_index":core[position+"_source_checkpoint_index"],
                                  "display_name":node["display_name"],"description":node["description"],"percent":node["percent"]})
    correlations=[]
    for scope,members in (("all183",enriched),("puzzle",[g for g in enriched if "puzzle" in g["types"]]),
                          ("non_puzzle",[g for g in enriched if "puzzle" not in g["types"]])):
        correlations.append({"scope":scope,"n":len(members),"steam_late_spearman":float(spearmanr(
            [g[SCORES[0]] for g in members],[g[PROGRESS[1]] for g in members]).statistic)})
    memberships=[{"scope":scope,"appid":g["appid"],"name_en":g["name_en"],"gameplay_labels":g["gameplay_labels"]}
                 for scope,members in {**groups,"late_upper_right":region}.items() for g in members]
    # CSV columns remain scalar, while JSON keeps full overlapping label lists.
    scalar_rankings=[{k:v for k,v in g.items() if k not in ("types","theme","presentation","player_mode")} for g in rankings]
    data={"version":EXPLORATION_VERSION,"region_steam_min":REGION_STEAM_MIN,"region_late_min":REGION_LATE_MIN,
          "cohort_appids_sha256":digest(ids),"quadrant_thresholds":{"steam":sx,"overall":sy},
          "quadrant_types":profiles,"region_text_labels":text_labels,"tag_pairs":pairs,
          "summaries":summaries,"boundary_sensitivity":boundaries,"rankings":scalar_rankings,
          "top5":top,"bottom5":bottom,"top_boundary_ties":top_ties,"bottom_boundary_ties":bottom_ties,
          "weight_sensitivity":weights,"case_checkpoints":node_rows,
          "high_late_low_early":special,"descriptive_correlations":correlations,"memberships":memberships}
    tables={"exploration_multilabel.csv":profiles,"exploration_text_labels.csv":text_labels,
            "exploration_tag_pairs.csv":pairs,"exploration_group_summary.csv":summaries,
            "exploration_region_boundaries.csv":boundaries,"exploration_joint_rankings.csv":scalar_rankings,
            "exploration_rank_weights.csv":weights,"exploration_case_checkpoints.csv":node_rows,
            "exploration_memberships.csv":memberships,"exploration_descriptive_correlations.csv":correlations}
    return data,tables


def exploration_report(data: Json) -> str:
    """Render measured commonalities and bounded interpretations, including raw node wording for exceptions."""
    def type_name(tag: str) -> str:
        return TYPE_NAMES.get(tag,tag)
    def cell(value: object) -> str:
        return str(value).replace("|","/").replace("\n"," ") if value is not None else "缺失"
    names={"high_high":"口碑高 / 全程高","high_low":"口碑高 / 全程低",
           "low_high":"口碑低 / 全程高","low_low":"口碑低 / 全程低"}
    rows=["## 图16～18的进一步探索解读", "",
          "本节按负责人确认的图号分析：16为四象限，17第二面板为后段推进，18为评分来源。原15号是时长图，本轮不改变原时长专题。",
          "这里的类型使用完整gameplay多标签，每款可属于多个类型，同一游戏在同一标签内只计一次；分母为各区域的游戏数，占比之和可超过100%。",
          "比较区域内占比与全部183款背景占比，提升倍数=区域占比/背景占比。背景包含该区域；CSV另给区域外占比，不把大类数量多误认为特征。",
          "本节为看图后提出的探索性问题，不作显著性筛选或因果检验；多标签重叠、类型共现及节点语义均可能影响观察。", "",
          "### 1. 四象限里的类型有什么共性？", "",
          "正文每组列区域占比高于背景且区域至少5款、背景至少10款的前三个最大百分点差标签；全部标签（含不足5款）及零计数保存在CSV。",
          "| 象限 | n | 多标签 | 区域内 | 全183背景 | 差值（百分点） | 提升倍数 |", "|---|---:|---|---|---|---:|---:|"]
    for scope,name in names.items():
        candidates=sorted([r for r in data["quadrant_types"] if r["scope"]==scope and r["descriptive_support"] and r["difference_pp"]>0],
                          key=lambda r:(-r["difference_pp"],-r["tag_n"],r["tag"]))[:3]
        for r in candidates:
            rows.append(f"| {name} | {r['group_n']} | {type_name(r['tag'])} | {r['tag_n']}/{r['group_n']}（{r['share']:.1%}） | {r['background_tag_n']}/183（{r['background_share']:.1%}） | {r['difference_pp']:+.1f} | {r['lift_vs_background']:.2f} |")
        if not candidates:
            rows.append(f"| {name} | — | 无满足正文支持数要求的正向差异 | — | — | — | — |")
    rows += ["", "**读法与可研究的方向：**", "",
             "- 高口碑高推进：解谜占48.0%，较总体高27.2个百分点，比冒险单标签的提升更明显；可优先研究“解谜＋冒险”的组合，而不是笼统地说冒险都容易完成。",
             "- 高口碑低推进：模拟47.6%、策略33.3%均高于背景。可提出“评价认可与完成主线不是同一目标”的假设，但标签本身不足以认定游戏没有主线或玩家只玩沙盒。",
             "- 低口碑高推进：动作占88.1%，提示较低的相对口碑并不妨碍部分游戏取得较高推进。是否更线性、更短或面向不同玩家，仍需另外核查，不能从动作标签直接推出。",
             "- 低口碑低推进：策略、角色扮演、生存更常见，可研究长流程、重复尝试、不同结局代理是否影响结果；当前并没有证明这些设计导致低推进。",
             "- 一个反直觉点：平台跳跃在高口碑高推进、高口碑低推进中各有11款，不能仅看它在某个象限的提升倍数，就认定平台跳跃普遍更易完成。",
             "这些标签不能相互排斥解释。例如同一解谜游戏可以同时带冒险、休闲、其他标签，不能把各行当成不同游戏群的独立证据；other也不代表一种具体玩法。", "",
             "共现的具体组合见下表（各象限按出现款数降序，至少5款，取前2项）；这是标签组合构成，不是相加后的独立样本。", "",
             "| 象限 | 标签组合 | 区域内 | 背景占比 | 提升倍数 |", "|---|---|---|---|---:|"]
    for scope,name in names.items():
        pairs=sorted([r for r in data["tag_pairs"] if r["scope"]==scope and r["pair_n"]>=5],key=lambda r:(-r["pair_n"],r["tag_a"],r["tag_b"]))[:2]
        for r in pairs:
            rows.append(f"| {name} | {type_name(r['tag_a'])}＋{type_name(r['tag_b'])} | {r['pair_n']}/{r['group_n']}（{r['share']:.1%}） | {r['background_share']:.1%} | {r['lift_vs_background']:.2f} |")
    rows += ["", "### 2. 后段面板右上角为什么集中？", "",
             "将视觉区域明确为 **Steam好评率≥90%、后段推进比≥80%**。这是看图后设定的探索边界，不是自动发现的聚类，也不是质量合格线。",
             "| 多标签 | 右上区域 | 全183背景 | 提升倍数 | 同为好评≥90%背景中的占比 |", "|---|---|---|---:|---|"]
    main=[r for r in data["quadrant_types"] if r["scope"]=="late_upper_right"]
    high={r["tag"]:r for r in data["quadrant_types"] if r["scope"]=="late_upper_right_within_high_review"}
    for r in sorted([r for r in main if r["descriptive_support"]],key=lambda r:(-r["difference_pp"],r["tag"])):
        h=high[r["tag"]]
        rows.append(f"| {type_name(r['tag'])} | {r['tag_n']}/{r['group_n']}（{r['share']:.1%}） | {r['background_tag_n']}/183（{r['background_share']:.1%}） | {r['lift_vs_background']:.2f} | {h['background_tag_n']}/{h['background_n']}（{h['background_share']:.1%}） |")
    rows += ["", "借用库的题材/表现/人数标签可补充解释，但它们是模型根据标签整理的自由文本，不是人工统一词典；原样按字符串计数、不合并近义词，不能因未标某词就断言没有该特征。", "",
             "| 维度 | 标签 | 区域内 | 全183背景 | 提升倍数 |", "|---|---|---|---|---:|"]
    for dimension in ("theme","presentation","player_mode"):
        candidates=sorted([r for r in data["region_text_labels"] if r["dimension"]==dimension and r["descriptive_support"]],
                          key=lambda r:(-r["tag_n"],-r["difference_pp"],r["tag"]))[:3]
        for r in candidates:
            rows.append(f"| {dimension} | {cell(r['tag'])} | {r['tag_n']}/{r['group_n']}（{r['share']:.1%}） | {r['background_tag_n']}/183（{r['background_share']:.1%}） | {r['lift_vs_background']:.2f} |")
    rows += ["", "**可以支持的解释：** 该区域呈现解谜、叙事/悬疑等标签的聚集，值得把“具有明确阶段目标的叙事/解谜游戏”作为后续研究假设；不能据此断言这些设计导致高推进。单人标签即使非常普遍，也须对照总体是否同样普遍。", "",
             "**需要分开的两个问题：** 后段高只表示末/中高，不自动代表从开头就高。以下比较各组游戏级中位数，不能把这些中位数相乘重算全程。", "",
             "| 范围 | n | 首覆盖 | 中覆盖 | 末覆盖 | 前段 | 后段 | 全程 | 多结局代理 | HLTB有效n/主线时长中位数 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for scope,label in (("late_upper_right","右上区域"),("high_review_other","同为高口碑、后段<80%"),("all183","全部三节点")):
        s=next(r for r in data["summaries"] if r["scope"]==scope)
        metrics=" | ".join(f"{s[k+'_median']:.1%}" for k in ("p_s","p_m","p_f",*PROGRESS))
        hours=f"{s['hltb_n']}/{s['hltb_main_hours_median']:.2f}小时" if s["hltb_n"] else "0/缺失"
        rows.append(f"| {label} | {s['n']} | {metrics} | {s['multi_ending_n']}/{s['n']} | {hours} |")
    rows += ["", "HLTB只覆盖部分游戏，因此区域内12款的时长中位数不能当成全部28款长度；本节不据此断言该区域整体更短。", "",
             "**边界敏感性：** 保存好评85%/90%/95%×后段70%/80%/90%全部9个区域，避免只挑最醒目的边界。", "",
             "| 好评下限 | 后段下限 | n | 解谜n | 解谜占比 | 对183款背景提升倍数 |", "|---:|---:|---:|---:|---:|---:|"]
    for r in data["boundary_sensitivity"]:
        rows.append(f"| {r['steam_min']:.0%} | {r['late_min']:.0%} | {r['n']} | {r['puzzle_n']} | {r['puzzle_share']:.1%} | {r['puzzle_lift']:.2f} |")
    rows += ["", "看图后再分组的相关仅作描述，不是控制混杂的回归或因果证据：", "",
             "| 组别 | n | 好评率与后段Spearman |", "|---|---:|---:|"]
    for r in data["descriptive_correlations"]:
        rows.append(f"| {r['scope']} | {r['n']} | {r['steam_late_spearman']:+.3f} |")
    rows += ["", "总体后段相关较弱，解谜与非解谜组内的描述关联也不同，提示不能用一个总体系数概括所有类型；分组仍有重叠类型、系列与节点差异，不是已经控制其他因素的结论。", "",
             "### 3. 双指标共同表现前五与后五", "",
             "“综合”仅指图16两轴，不是游戏质量或分类准确率。为避免量纲与分布差异，分别计算183款中的Steam好评率百分位秩u及全程推进百分位秩v；均采用(平均秩−0.5)/183。",
             "**共同表现分=100×(u+v)/2**，各50%权重；保留分数并列，展示顺序同分按AppID。前/后/全程不一起求和，因为全程=前段×后段，三项并入会重复计量。", ""]
    for title,key in (("领先五款","top5"),("靠后五款","bottom5")):
        rows += [f"#### {title}", "", "| AppID | 游戏 | 完整玩法多标签 | Steam好评率 | 前段 | 后段 | 全程 | 共同表现分 |", "|---:|---|---|---:|---:|---:|---:|---:|"]
        for g in data[key]:
            types="、".join(type_name(t) for t in g["types"])
            metrics=" | ".join(f"{g[k]:.2%}" for k in (SCORES[0],*PROGRESS))
            rows.append(f"| {g['appid']} | {cell(g['name_en'])} | {types} | {metrics} | {g['joint_score']:.2f} |")
        if len(data["top_boundary_ties" if key=="top5" else "bottom_boundary_ties"])>1:
            ties=data["top_boundary_ties" if key=="top5" else "bottom_boundary_ties"]
            rows += ["",f"展示边界存在{len(ties)}款并列："+"、".join(f"{cell(g['name_en'])}（{g['appid']}）" for g in ties)+"；按AppID决定五行展示名额，不据此判断同分游戏优劣。"]
    rows += ["", "#### 原始成就语义核对", "",
             "以下从本地只读源成就直接取末节点展示名和描述，保留现有选点，不作数据库修正。节点要求不同是解释排名的实质限制，尤其不能将靠后榜当成最差游戏榜。", "",
             "| AppID | 游戏 | 末节点 | 末节点描述原文 | 节点/结局标记 | 评价数 | 媒体/RAWG |", "|---:|---|---|---|---|---:|---|"]
    ends={r["appid"]:r for r in data["case_checkpoints"] if r["position"]=="end"}
    audit_games={g["appid"]:g for g in [*data["top5"],*data["bottom5"],*data["top_boundary_ties"],*data["bottom_boundary_ties"]]}
    for g in audit_games.values():
        node=ends[g["appid"]]
        flags=g["ending_type"]+("; "+g["quality_flags"] if g["quality_flags"] else "")
        rows.append(f"| {g['appid']} | {cell(g['name_en'])} | {cell(node['display_name'])} | {cell(node['description'])} | {cell(flags)} | {g['review_count']:,} | {cell(g['metacritic'])}/{cell(g['rawg_rating'])} |")
    rows += ["", "**关键解释限制：** Outward的末节点要求Finish all 3 quest lines，和完成任一条剧情线不是同一要求；Sniper Elite 3写Complete 100% of the campaign，与普通结局是否等价需人工核验；Dragon's Dogma 2末节点还注明Not available in Casual Mode。",
             "Balatro的末节点Win a Run是赢得一局的进程代理，不是传统剧情通关；Arma Reforger的选中首末与Operation Omega campaign有关，中间却是教程任务，不能未经核验就认为三节点必然前后包含。",
             "这些差异可能影响排名，但本轮不反向更改已接受的模型节点，也不另做修正后的新榜；原始描述和三节点均留档供后续人工判断。", "",
             "领先组中的The Room系列占3/5，这提示系列聚集会影响“解谜表现好”的直觉，五款不能当成五个独立设计范式；模型分类、系列与类型效应尚未分离。", "",
             "#### 权重敏感性", "", "| 好评权重 | 推进权重 | 与50/50前五重合 | 与50/50后五重合 |", "|---:|---:|---:|---:|"]
    for r in data["weight_sensitivity"]:
        rows.append(f"| {r['steam_weight']:.0%} | {r['overall_weight']:.0%} | {r['top5_overlap_equal_weight']}/5 | {r['bottom5_overlap_equal_weight']}/5 |")
    rows += ["", "权重是解释性选择，不从数据中优化；名单变化说明不存在无需定义的“综合最好/最差”。完整183款排序、百分位秩、3组权重名单与所有原值均保存。", "",
             "### 4. 反直觉案例与下一步", ""]
    for g in data["high_late_low_early"]:
        rows += [f"- {cell(g['name_en'])}（{g['appid']}）：好评{g[SCORES[0]]:.2%}、后段{g[PROGRESS[1]]:.2%}，但前段仅{g[PROGRESS[0]]:.2%}、全程{g[PROGRESS[2]]:.2%}。高后段不能消除此前差距。"]
        nodes=[r for r in data["case_checkpoints"] if r["appid"]==g["appid"]]
        rows += ["  本地节点为"+" → ".join(f"{cell(r['display_name'])}（{r['percent']:.1f}%）" for r in nodes)+"；中/末描述缺失时，不能仅按名称确认普通剧情必经性。"]
    rows += ["", "18号同142款的RAWG全程ρ高于Steam，但已有报告保留成对差值与区间，不能因为散点看起来更陡就下结论；评分单位、人群和游戏构成均不同。",
             "下一步最有价值的是人工核对上述严格末节点/缺描述节点，讨论是否应另标为“多任务线/完整战役/一局胜利/特定模式”的推进代理；是否改变数据或主口径须另行确认。",
             "然后可在保留现有模型口径的同时，补充“普通单次主线结局”子样本；目前只记录发现，不自动清洗、不改变183/142范围，不把类型富集写成因果。", "",
             "复核明细：[标签构成](exploration_multilabel.csv)、[标签组合](exploration_tag_pairs.csv)、[区域成员](exploration_memberships.csv)、",
             "[自由文本标签](exploration_text_labels.csv)、[区域统计](exploration_group_summary.csv)、[9组边界](exploration_region_boundaries.csv)、",
             "[183款共同表现排序](exploration_joint_rankings.csv)、[权重对照](exploration_rank_weights.csv)、[原始三节点](exploration_case_checkpoints.csv)、",
             "[分组描述相关](exploration_descriptive_correlations.csv)。本节依据冻结本地数据叠加已确认的任务5评分更新，不作游戏质量断言。", ""]
    return "\n".join(rows)
