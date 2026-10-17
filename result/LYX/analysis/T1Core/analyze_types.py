"""按WWH玩法汇总固定198款游戏的主线阶段指标；不修改指标底表或数据库。"""

from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
import os
from pathlib import Path
import textwrap
from typing import Any
import warnings

from compare_games import COLORS, PANELS, load_catalog
from prepare_metrics import ROOT, baseline, csv_text, digest, owned_path, protected_snapshot, source, write_text
from plot_files import COHORT_SOURCE, TYPE_FIGURES, add_footer, figure_directory

VERSION = "lyx-type-stages-v2"
DEFAULT_TYPES = ROOT / "output" / "type_analysis"
SEED = 42
BOOTSTRAP = 2000
MIN_DISPLAY = 5
MIN_INTERVAL = 10
TYPE_NAMES = {"action": "动作", "adventure": "冒险", "rpg": "角色扮演", "simulation": "模拟",
              "platformer": "平台跳跃", "strategy": "策略", "puzzle": "解谜", "survival": "生存",
              "racing": "竞速", "rhythm": "节奏", "sports": "体育", "casual": "休闲", "other": "其他", "uncertain": "不确定"}
METRICS = [field for spec in PANELS.values() for field, _ in spec["series"]]
LABELS = {field: label for spec in PANELS.values() for field, label in spec["series"]}
GAP = "late_minus_early"
LABELS[GAP] = "后段减前段（百分点差）"
SUBSETS = {"main_three_point": "完整三节点主分析", "all_available": "全198款有效值补充",
           "start_three_point": "唯一首位start且三节点", "unified_three_point": "三节点且统一结局",
           "multi_three_point": "三节点且多结局代理"}
Json = dict[str, Any]


def enrich(games: list[Json]) -> list[Json]:
    """Validate type membership and add a paired within-game late-minus-early contrast."""
    result = []
    for game in games:
        labels = game["gameplay_labels"].split("|")
        if not labels or len(set(labels)) != len(labels) or labels[0] != game["primary_gameplay"]:
            raise ValueError(f"appid={game['appid']}玩法列表或主类型不一致")
        if any(label not in TYPE_NAMES for label in labels):
            raise ValueError(f"未识别的WWH玩法：{labels}")
        complete = all(game[field] is not None for field in METRICS)
        if complete != game["three_point_available"]:
            raise ValueError(f"appid={game['appid']}三节点标记与六指标有效性不一致")
        result.append({**game, "types": labels, "complete": complete,
                       GAP: game["late_progress_ratio"] - game["early_progress_ratio"] if complete else None})
    return result


def subset_games(games: list[Json]) -> dict[str, list[Json]]:
    """Keep the fixed cohort while declaring every sensitivity subset explicitly."""
    complete = [g for g in games if g["complete"]]
    return {"main_three_point": complete, "all_available": games,
            "start_three_point": [g for g in complete if int(g["start_label_count"]) == 1 and g["first_stage"] == "start"],
            "unified_three_point": [g for g in complete if g["ending_type"] == "unified"],
            "multi_three_point": [g for g in complete if g["ending_type"] == "multi"]}


def membership_rows(games: list[Json]) -> list[Json]:
    """Export unique AppID/type links separately for exclusive and overlapping schemes."""
    return [{"scheme": scheme, "appid": g["appid"], "title": g["title"], "group": label,
             "group_zh": TYPE_NAMES[label], "primary_gameplay": g["primary_gameplay"],
             "three_point_available": g["complete"], "start_label_count": int(g["start_label_count"]),
             "first_stage": g["first_stage"], "ending_type": g["ending_type"]}
            for scheme in ("primary", "multilabel") for g in games
            for label in ([g["primary_gameplay"]] if scheme == "primary" else g["types"])]


def summarize(games: list[Json], scheme: str, subset: str) -> list[Json]:
    """Compute game-level medians, quartiles and paired-row bootstrap median intervals."""
    import numpy as np

    fields = METRICS + [GAP]
    reference = {field: float(np.median([g[field] for g in games if g[field] is not None]))
                 if any(g[field] is not None for g in games) else None for field in fields}
    groups: dict[str, list[Json]] = {}
    for game in games:
        for label in ([game["primary_gameplay"]] if scheme == "primary" else game["types"]):
            groups.setdefault(label, []).append(game)
    result = []
    for label, members in sorted(groups.items()):
        matrix = np.array([[g[field] if g[field] is not None else np.nan for field in fields] for g in members])
        # One sampled row is one game; all metrics use identical resampled game indices.
        offset = int(digest([scheme, subset, label])[:8], 16)
        rng = np.random.default_rng(np.random.SeedSequence([SEED, offset]))
        sampled = matrix[rng.integers(0, len(members), size=(BOOTSTRAP, len(members)))]
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered", category=RuntimeWarning)
            boot = np.nanmedian(sampled, axis=1)
        for index, field in enumerate(fields):
            values = matrix[:, index]
            valid = values[np.isfinite(values)]
            n = len(valid)
            q1, med, q3 = [float(v) for v in np.quantile(valid, [0.25, 0.5, 0.75])] if n else [None] * 3
            replicates = boot[:, index]
            replicates = replicates[np.isfinite(replicates)]
            interval = n >= MIN_INTERVAL and len(replicates) >= MIN_INTERVAL
            lower, upper = [float(v) for v in np.quantile(replicates, [0.025, 0.975])] if interval else [None] * 2
            result.append({"scheme": scheme, "subset": subset, "group": label, "group_zh": TYPE_NAMES[label],
                           "n_total": len(members), "n_three_point": sum(g["complete"] for g in members),
                           "n_no_start": sum(int(g["start_label_count"]) == 0 for g in members),
                           "n_multi_ending": sum(g["ending_type"] == "multi" for g in members),
                           "metric": field, "n_valid": n, "n_missing": len(members) - n,
                           "median": med, "q1": q1, "q3": q3,
                           "minimum": float(valid.min()) if n else None, "maximum": float(valid.max()) if n else None,
                           "interval_low": lower, "interval_high": upper,
                           "bootstrap_replicates": len(replicates) if interval else 0,
                           "eligible_main_plot": n >= MIN_DISPLAY, "cohort_median": reference[field],
                           "delta_to_cohort_pp": (med - reference[field]) * 100 if n else None})
    return result


def sensitivity_rows(summaries: list[Json]) -> list[Json]:
    """Compare explicit subsets and overlapping labels against the declared main baseline."""
    main = {(r["scheme"], r["group"], r["metric"]): r for r in summaries if r["subset"] == "main_three_point"}
    result = []
    for row in summaries:
        if row["subset"] in ("main_three_point", "all_available"):
            continue
        base = main[(row["scheme"], row["group"], row["metric"])]
        result.append({**row, "reference_subset": "main_three_point", "reference_n": base["n_valid"],
                       "reference_median": base["median"],
                       "delta_to_main_pp": (row["median"] - base["median"]) * 100
                       if row["median"] is not None and base["median"] is not None else None})
    for row in summaries:
        if row["scheme"] != "multilabel" or row["subset"] != "main_three_point":
            continue
        base = main.get(("primary", row["group"], row["metric"]))
        result.append({**row, "reference_subset": "primary_main_three_point", "reference_n": base["n_valid"] if base else 0,
                       "reference_median": base["median"] if base else None,
                       "delta_to_main_pp": (row["median"] - base["median"]) * 100
                       if base and base["median"] is not None and row["median"] is not None else None})
    return result


def choose_cases(games: list[Json]) -> list[Json]:
    """Choose up to three disjoint same-primary pairs with similar overall and different stages."""
    candidates = []
    for first, second in itertools.combinations([g for g in games if g["complete"]], 2):
        if first["primary_gameplay"] != second["primary_gameplay"]:
            continue
        gap = abs(first["overall_progress_ratio"] - second["overall_progress_ratio"])
        contrast = sum(abs(first[f] - second[f]) for f in ("early_progress_ratio", "late_progress_ratio"))
        if gap <= 0.03:
            candidates.append((contrast, gap, first, second))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]["appid"], c[3]["appid"]))
    result, used = [], set()
    for contrast, gap, first, second in candidates:
        if first["appid"] in used or second["appid"] in used:
            continue
        result.append({"pair": len(result) + 1, "primary_gameplay": first["primary_gameplay"],
                       "appid_a": first["appid"], "title_a": first["title"], "appid_b": second["appid"], "title_b": second["title"],
                       "overall_gap_pp": gap * 100, "stage_absolute_difference_sum_pp": contrast * 100,
                       **{f"{f}_{side}": g[f] for side, g in (("a", first), ("b", second)) for f in METRICS}})
        used.update((first["appid"], second["appid"]))
        if len(result) == 3:
            break
    return result


def plotting() -> tuple[Any, Any]:
    """Configure offline Matplotlib and local font cache, without changing global dependencies."""
    os.environ["MPLCONFIGDIR"] = str(ROOT / "runtime" / "matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt, {"font.family": "sans-serif", "font.sans-serif": baseline._cjk_fonts(), "axes.unicode_minus": False,
                 "font.size": 11, "axes.spines.top": False, "axes.spines.right": False}


def save_figure(fig: Any, output: Path) -> None:
    """Save a PNG preview and scalable SVG using the same figure geometry."""
    fig.savefig(owned_path(output.with_suffix(".png")), dpi=180)
    fig.savefig(owned_path(output.with_suffix(".svg")), metadata={"Date": None})


def draw_heatmaps(summary: list[Json], output: Path, scheme: str = "primary") -> None:
    """Plot medians and denominators with identical ordering and fixed 0..100 percent scale."""
    import numpy as np

    plt, style = plotting()
    main = [r for r in summary if r["scheme"] == scheme and r["subset"] == "main_three_point"]
    lookup = {(r["group"], r["metric"]): r for r in main}
    groups = sorted({r["group"] for r in main if r["metric"] == "p_s" and r["eligible_main_plot"]},
                    key=lambda g: (-lookup[g, "p_s"]["n_valid"], g))
    for panel, spec in PANELS.items():
        fields = [f for f, _ in spec["series"]]
        values = np.array([[lookup[g, f]["median"] for f in fields] for g in groups])
        if np.any((values < 0) | (values > 1)):
            raise ValueError("热力图出现越界比值；停止以避免固定色阶截断，请先核对异常")
        with plt.rc_context(style):
            fig, ax = plt.subplots(figsize=(10.7, 7.1))
            image = ax.imshow(values, cmap="YlGnBu", vmin=0, vmax=1, aspect="auto")
            ax.set_xticks(range(3), [label for _, label in spec["series"]], fontsize=12)
            ax.set_yticks(range(len(groups)), [f"{TYPE_NAMES[g]}  n={lookup[g, 'p_s']['n_valid']}" for g in groups])
            ax.tick_params(length=0, pad=10)
            for i, group in enumerate(groups):
                for j, field in enumerate(fields):
                    row = lookup[group, field]
                    ax.text(j, i, f"{row['median']:.1%}", ha="center", va="center", fontsize=14,
                            color="white" if row["median"] > 0.58 else "#172B3A")
            colorbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.035)
            colorbar.set_ticks(np.linspace(0, 1, 6), labels=[f"{round(v * 100)}%" for v in np.linspace(0, 1, 6)])
            grouping = "主类型分组" if scheme == "primary" else "完整多标签分组"
            subject = "首、中、末主线节点覆盖" if panel == "coverage" else "前段、后段与全程主线推进比"
            fig.suptitle(f"{grouping}：{subject}", fontsize=20, y=0.965)
            membership = ("分组：仅取gameplay首标签，每款只归一组；n为游戏数，仅显示n≥5的类型。" if scheme == "primary" else
                          "分组：使用完整gameplay标签，每款可归多组，组内去重、组间重叠；n为游戏数，仅显示n≥5的类型。")
            definition = ("数据：每格为组内各游戏首/位置中位/代表结局成就原始解锁率的中位数；各列使用同一批游戏。" if panel == "coverage" else
                          "数据：先逐游戏计算中/首、末/中、末/首，再取组内中位数；各列使用同一批游戏。")
            add_footer(fig, [COHORT_SOURCE, membership, definition,
                       "解释：位置中位非时间中点，结局为代表代理；各列汇总值不可互除，覆盖与推进比不等于日留存或因果效应。"])
            fig.subplots_adjust(left=0.20, right=0.90, top=0.88, bottom=0.24)
            stem = f"type_{panel}_heatmap" if scheme == "primary" else f"multilabel_{panel}_heatmap"
            save_figure(fig, output / TYPE_FIGURES[stem])
            plt.close(fig)


def draw_distribution(games: list[Json], summary: list[Json], output: Path) -> None:
    """Draw within-type game variation and bootstrap median intervals as separate panels."""
    import numpy as np
    from matplotlib.ticker import PercentFormatter

    plt, style = plotting()
    rows = sorted([r for r in summary if r["scheme"] == "primary" and r["subset"] == "main_three_point"
                   and r["metric"] == "overall_progress_ratio" and r["eligible_main_plot"]],
                  key=lambda r: (-r["n_valid"], r["group"]))
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 2, figsize=(13.6, 7.2), sharey=True, gridspec_kw={"width_ratios": [2.1, 1]})
        rng = np.random.default_rng(SEED)
        for i, row in enumerate(rows):
            values = [g["overall_progress_ratio"] for g in games if g["complete"] and g["primary_gameplay"] == row["group"]]
            axes[0].boxplot([values], positions=[i], vert=False, widths=0.5, showfliers=False, patch_artist=True,
                            boxprops={"facecolor": "#DCEAF4", "edgecolor": COLORS[0]},
                            medianprops={"color": "#182D3C", "linewidth": 2}, whiskerprops={"color": COLORS[0]},
                            capprops={"color": COLORS[0]})
            axes[0].scatter(values, i + rng.uniform(-0.16, 0.16, len(values)), s=23, alpha=0.55, color=COLORS[0], zorder=3)
            med = row["median"]
            if row["interval_low"] is not None:
                axes[1].plot([row["interval_low"], row["interval_high"]], [i, i], color=COLORS[0], linewidth=3)
                axes[1].scatter([med], [i], color=COLORS[0], s=45, zorder=3)
            else:
                axes[1].scatter([med], [i], facecolors="white", edgecolors=COLORS[0], s=45, zorder=3)
            axes[1].annotate(f"{med:.1%}", (med, i), xytext=(0, -18), textcoords="offset points", ha="center", fontsize=9)
        axes[0].set_yticks(range(len(rows)), [f"{r['group_zh']}  n={r['n_valid']}" for r in rows])
        axes[0].set_ylim(len(rows) - 0.4, -0.6)
        for ax in axes:
            ax.set_xlim(-0.025, 1.025)
            ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.grid(axis="x", color="#E0E5EA", linewidth=0.7)
            ax.set_axisbelow(True)
            ax.set_xlabel("全程推进比：代表结局 / 首节点", labelpad=12)
        axes[0].set_title("游戏分布：每个点是一款游戏", loc="left", fontsize=13, pad=15)
        axes[1].set_title("中位数与95%重采样区间", loc="left", fontsize=12, pad=15)
        fig.suptitle("主类型分组：全程推进比的游戏分布与中位数区间", fontsize=20, y=0.965)
        add_footer(fig, [COHORT_SOURCE,
                   "分组：仅取gameplay首标签，每款只归一组；n为游戏数，仅显示n≥5的类型。",
                   "数据：每点一款游戏；全程比=末/首；箱体为四分位范围，须线为1.5倍IQR内最远值。",
                   "区间：游戏级Bootstrap 2000次、种子42，n<10仅画空心中位点；反映样本波动，不是玩家级误差或日留存。"])
        fig.subplots_adjust(left=0.14, right=0.98, top=0.84, bottom=0.25, wspace=0.14)
        save_figure(fig, output / TYPE_FIGURES["type_progress_distribution"])
        plt.close(fig)


def draw_cases(cases: list[Json], games: list[Json], output: Path) -> None:
    """Plot reproducibly selected similar-overall pairs without recomputing their nodes."""
    from matplotlib.ticker import PercentFormatter

    if not cases:
        return
    plt, style = plotting()
    by_id = {g["appid"]: g for g in games}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, len(cases), figsize=(5.1 * len(cases), 6), squeeze=False)
        for ax, case in zip(axes[0], cases):
            for j, side in enumerate(("a", "b")):
                g = by_id[case[f"appid_{side}"]]
                values = [g[f] for f in METRICS[3:]]
                centers = [x + (j - 0.5) * 0.34 for x in range(3)]
                ax.bar(centers, values, width=0.30, color=COLORS[j],
                       label="\n".join(textwrap.wrap(g["title"], width=42, break_long_words=False)), zorder=3)
                for x, v in enumerate(values):
                    ax.annotate(f"{v:.1%}", (centers[x], v), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)
            ax.set_title(f"{TYPE_NAMES[case['primary_gameplay']]} · 全程差{case['overall_gap_pp']:.1f}个百分点", loc="left", fontsize=11, pad=15)
            ax.set_xticks(range(3), ["前段", "后段", "全程"])
            ax.set_xlim(-0.5, 2.5)
            ax.set_ylim(0, 1.12)
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.grid(axis="y", color="#E0E5EA")
            ax.set_axisbelow(True)
            ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), fontsize=8, frameon=False)
        fig.suptitle("同主类型游戏对照：全程相近时的前后段推进差异", fontsize=20, y=0.97)
        add_footer(fig, [f"样本来源：2026-10-13冻结1000款快照的198款有效曲线；从183款三节点游戏中选取{len(cases)}组、{len(cases) * 2}款案例。",
                   "选择：同主类型且全程差≤3个百分点，按前后段绝对差总和降序，游戏不重复。",
                   "数据：柱高为逐游戏的中/首、末/中、末/首；各对游戏的全程差标于子图标题。",
                   "解释：横轴是三个比值指标，不是时间轨迹；节点跨度和代表结局含义可能不同，案例不证明因果。"])
        fig.subplots_adjust(left=0.055, right=0.985, top=0.84, bottom=0.33, wspace=0.28)
        save_figure(fig, output / TYPE_FIGURES["stage_contrast_cases"])
        plt.close(fig)


def make_report(games: list[Json], summaries: list[Json], sensitivity: list[Json], cases: list[Json], audit: Json,
                figures: Path, output: Path) -> str:
    """Write bounded observations with full raw summary tables linked for reproduction."""
    main = [r for r in summaries if r["scheme"] == "primary" and r["subset"] == "main_three_point"]
    by_key = {(r["group"], r["metric"]): r for r in main}
    groups = sorted({r["group"] for r in main}, key=lambda g: (-by_key[g, "p_s"]["n_total"], g))
    lines = ["# 专题2：玩法类型与主线阶段推进", "", f"实施日期：2026-10-16。数据版本：{audit['dataset_version']}。",
             "固定WWH有效198款，主分析三节点齐全183款；其余15款保留在全范围补充，不补中位节点或零值。", "",
             "## 口径与可比性", "",
             "主类型取WWH gameplay[0]，互斥分组；完整gameplay为有重叠的补充。沿用数组位置中位、代表结局和每款游戏的已有比值，不重算选点、不写数据库。",
             "每格先计算游戏级指标再取组内中位数。有效n>=5进入主图，n>=10报告95%游戏级百分位Bootstrap区间，2000次、种子42；四分位数使用线性插值。",
             "六指标联合重采样整行游戏；不按评论数、玩家数或成就条数加权，不用汇总覆盖率互除。区间描述当前游戏集合重采样波动，不是总体随机抽样保证或玩家级误差。",
             "不同列中位数不能相乘、互除或解释为同一批玩家轨迹；后段减前段先在每款游戏内部相减，再汇总。", "",
             "## 原始分组汇总（完整三节点，游戏级中位数）", "",
             "| 类型 | n | 首覆盖 | 中覆盖 | 结局覆盖 | 前段 | 后段 | 全程 | 后段−前段中位差 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for g in groups:
        vals = [f"{by_key[g, f]['median']:.1%}" for f in METRICS]
        suffix = "（小样本，仅描述）" if by_key[g, "p_s"]["n_total"] < MIN_DISPLAY else ""
        lines.append(f"| {TYPE_NAMES[g]}{suffix} | {by_key[g, 'p_s']['n_total']} | " + " | ".join(vals)
                     + f" | {by_key[g, GAP]['median'] * 100:+.1f}个百分点 |")
    eligible = [g for g in groups if by_key[g, "p_s"]["eligible_main_plot"]]
    lines += ["", "全部指标、四分位数、缺失、区间与相对同子集整体中位数差见[group_summary.csv](group_summary.csv)。类型组总数与有效数分别保存；小组没有被合并或删除。", "",
              "## 图与可核验观察", "", "![节点覆盖](type_coverage_heatmap.png)", "", "![阶段推进](type_progress_heatmap.png)", "",
              "![组内分布](type_progress_distribution.png)", ""]
    for number, field in enumerate(("p_s", "overall_progress_ratio"), 1):
        high = max(eligible, key=lambda g: by_key[g, field]["median"])
        low = min(eligible, key=lambda g: by_key[g, field]["median"])
        h, l = by_key[high, field], by_key[low, field]
        lines += [f"{number}. 观察：在n>=5的主类型中，{LABELS[field]}中位数最高为{TYPE_NAMES[high]}{h['median']:.1%}（n={h['n_valid']}），"
                  f"最低为{TYPE_NAMES[low]}{l['median']:.1%}（n={l['n_valid']}），相差{(h['median']-l['median'])*100:.1f}个百分点。",
                  "   解释：这是当前筛选游戏的类型关联；组内游戏结构、节点和结局定义都可能参与差异。意义与下一步：结合分布和下述口径对照评估，不据此宣称某类型造成留存变化。", ""]
    lines += ["## 缺失、类型重叠与口径对照", "",
              "[game_membership.csv](game_membership.csv)列出主类型和完整标签成员，后者同一游戏可进入多个组，各组不独立、数量不能相加。",
              "全198款首末有效值与主分析183款分别保存；不把两套集合拼成同一条阶段曲线。",
              "[sensitivity_summary.csv](sensitivity_summary.csv)列出唯一首位start三节点170款、统一结局/多结局三节点子集，以及多标签相对主类型的差异；负值、缺失和小组均保留，不将变化直接解释为统计显著。", "",
              "| 口径对照（主类型、全程） | 最大绝对变化的组 | 对照有效n | 相对主分析差 |", "|---|---|---:|---:|"]
    for subset in ("start_three_point", "unified_three_point", "multi_three_point"):
        rows = [r for r in sensitivity if r["scheme"] == "primary" and r["subset"] == subset
                and r["metric"] == "overall_progress_ratio" and r["n_valid"] >= MIN_DISPLAY
                and r["reference_n"] >= MIN_DISPLAY and r["delta_to_main_pp"] is not None]
        if rows:
            row = max(rows, key=lambda r: abs(r["delta_to_main_pp"]))
            lines.append(f"| {SUBSETS[subset]} | {row['group_zh']} | {row['n_valid']} | {row['delta_to_main_pp']:+.1f}个百分点 |")
    lines += ["", "以上为探索性最大变化摘要，完整表同时保留其他组；对照重叠且不是独立实验。不能只凭区间重叠判断类型差异显著。", "",
              "| 完整三节点玩法 | 主类型n | 主类型全程中位数 | 完整标签n | 完整标签全程中位数 | 差（多标签−主类型） |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in sensitivity:
        if (row["reference_subset"] == "primary_main_three_point" and row["metric"] == "overall_progress_ratio"
                and row["n_valid"] >= MIN_DISPLAY and row["reference_n"] >= MIN_DISPLAY):
            lines.append(f"| {row['group_zh']} | {row['reference_n']} | {row['reference_median']:.1%} | {row['n_valid']} | "
                         f"{row['median']:.1%} | {row['delta_to_main_pp']:+.1f}个百分点 |")
    lines += ["", "多标签改变了各类型的成员构成，因此主类型排名不能直接当作稳定的类型差异。完整标签补充图见[multilabel_progress_heatmap.png](multilabel_progress_heatmap.png)。", "",
              "## 代表案例与后续问题", "", "案例选择规则在看结果前固定为：同一主类型、全程差不超过3个百分点，按前后段差异总和排序，选最多三组不复用游戏。它是展示规则，不是证据强度检验。", ""]
    for case in cases:
        lines.append(f"- {case['title_a']} 与 {case['title_b']}：全程差{case['overall_gap_pp']:.2f}个百分点；"
                     f"前段分别{case['early_progress_ratio_a']:.1%}/{case['early_progress_ratio_b']:.1%}，"
                     f"后段分别{case['late_progress_ratio_a']:.1%}/{case['late_progress_ratio_b']:.1%}。")
    if cases:
        lines += ["", "![阶段案例](stage_contrast_cases.png)"]
    lines += ["", "节点与展示名继续查上级[checkpoints.csv](../checkpoints.csv)，案例数值见[case_pairs.csv](case_pairs.csv)。",
              "极端前后段反差是核查节点语义和章节跨度的线索，不能仅凭这些模型节点归因于游戏设计。下一步可结合具体章节跨度检查案例，再按data_plan专题3开展全节点过程对照；时长与口碑尚未分析，不能当作已排除的解释。", "",
              "## 边界与来源", "",
              "198款来自WWH冻结1000款经有效主线曲线筛选的子集，不能推广至全Steam或所有1000款；当前主类型分布明显不均衡。",
              "首节点不是必然的游戏启动门槛，中位位置不是时间中点，多结局是代表代理，模型标注不等于人工事实。无已证实前置包含关系时，不把推进比称为条件玩家比例、日留存、弃坑率或因果影响。",
              "输入版本、参数、输出哈希和数据库/T0Pre保护核验见[manifest.json](manifest.json)。无新增采集、模型调用或数据库写入。", ""]
    text = "\n".join(lines)
    for old, new in TYPE_FIGURES.items():
        target = Path(os.path.relpath(figures / (new + ".png"), output)).as_posix()
        text = text.replace(f"({old}.png)", f"({target})")
    return text


def analyze(output: str | Path = DEFAULT_TYPES) -> Json:
    """Run the complete type analysis and verify source hashes before and after outputs."""
    output = owned_path(output)
    # A custom directory must never overwrite prepared inputs or existing comparison artifacts.
    if output in (ROOT, ROOT / "output") or output.is_relative_to(ROOT / "output" / "comparisons"):
        raise ValueError("类型分析请使用独立输出子目录，不能覆盖底表或comparisons")
    protected_before = protected_snapshot()
    catalog, audit = load_catalog()
    games = enrich(catalog)
    subsets = subset_games(games)
    members = membership_rows(games)
    all_summary = [row for scheme in ("primary", "multilabel") for subset, selected in subsets.items()
                   for row in summarize(selected, scheme, subset)]
    summary = [r for r in all_summary if r["subset"] in ("main_three_point", "all_available")]
    sensitivity = sensitivity_rows(all_summary)
    cases = choose_cases(games)
    keys = [(r["scheme"], r["appid"], r["group"]) for r in members]
    checks = {"fixed_198": len(games) == 198, "complete_183": len(subsets["main_three_point"]) == 183,
              "start_subset_170": len(subsets["start_three_point"]) == 170,
              "unique_memberships": len(keys) == len(set(keys)),
              "primary_198": sum(r["scheme"] == "primary" for r in members) == 198,
              "missing_15_preserved": sum(not g["complete"] for g in games) == 15,
              "no_false_zero_imputation": all(g["p_m"] is None and g["early_progress_ratio"] is None and
                  g["late_progress_ratio"] is None for g in games if not g["complete"]),
              "group_counts_add_up": sum(r["n_total"] for r in summary if r["scheme"] == "primary" and
                  r["subset"] == "main_three_point" and r["metric"] == "p_s") == 183,
              "main_same_games_six_metrics": all(r["n_valid"] == r["n_total"] for r in summary if r["subset"] == "main_three_point"),
              "counts_consistent": all(r["n_valid"] + r["n_missing"] == r["n_total"] for r in all_summary),
              "small_sample_no_interval": all(r["interval_low"] is None and r["interval_high"] is None
                  for r in all_summary if r["n_valid"] < MIN_INTERVAL)}
    if not all(checks.values()):
        raise ValueError(f"类型分析核验失败：{checks}")
    output.mkdir(parents=True, exist_ok=True)
    for filename, rows in (("group_summary.csv", summary), ("game_membership.csv", members),
                           ("sensitivity_summary.csv", sensitivity), ("case_pairs.csv", cases)):
        write_text(output / filename, csv_text(rows), "utf-8-sig")
    figures = figure_directory(output, DEFAULT_TYPES)
    figures.mkdir(parents=True, exist_ok=True)
    draw_heatmaps(summary, figures)
    draw_heatmaps(summary, figures, "multilabel")
    draw_distribution(games, summary, figures)
    draw_cases(cases, games, figures)
    write_text(output / "report.md", make_report(games, summary, sensitivity, cases, audit, figures, output))
    _, audit_after = load_catalog()
    protected_after = protected_snapshot()
    checks["inputs_unchanged"] = audit == audit_after and protected_before == protected_after
    names = ["group_summary.csv", "game_membership.csv", "sensitivity_summary.csv", "case_pairs.csv", "report.md"]
    names += [Path(os.path.relpath(figures / f"{stem}.{ext}", output)).as_posix() for stem in TYPE_FIGURES.values()
              for ext in ("png", "svg") if (figures / f"{stem}.{ext}").is_file()]
    manifest = {"created_at": source.now(), "version": VERSION, "source": audit,
                "parameters": {"random_state": SEED, "bootstrap_iterations": BOOTSTRAP, "minimum_plot_n": MIN_DISPLAY,
                               "minimum_interval_n": MIN_INTERVAL, "interval": "2.5/97.5 percentile game-row bootstrap median",
                               "quantile_method": "linear", "case_max_overall_gap": 0.03,
                               "case_order": "descending early/late absolute difference sum; ascending overall gap; appids"},
                "subsets": {k: {"n": len(v), "appids": [g["appid"] for g in v]} for k, v in subsets.items()},
                "main_primary_counts": dict(Counter(g["primary_gameplay"] for g in subsets["main_three_point"])),
                "membership_rows": len(members), "checks": checks,
                "protected_before": protected_before, "protected_after": protected_after,
                "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (Path(__file__), ROOT / "run.py", ROOT / "compare_games.py", ROOT / "prepare_metrics.py", ROOT / "plot_files.py")},
                "outputs_path_base": "manifest directory",
                "outputs_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names}}
    write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if not all(checks.values()):
        raise RuntimeError("类型分析期间输入指纹改变，请核对manifest")
    return {"version": VERSION, "games": len(games), "main_games": len(subsets["main_three_point"]),
            "subsets": {k: len(v) for k, v in subsets.items()}, "checks": checks,
            "output": str(output), "report": str(output / "report.md"),
            "figures": [str(output / name) for name in names if name.endswith(".png")]}
