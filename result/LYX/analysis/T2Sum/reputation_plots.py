"""任务5的三张图：四象限、阶段关联、同样本跨评分对照。"""

from __future__ import annotations

import os
from pathlib import Path
import textwrap
from typing import Any

from reputation_data import ROOT, Json, LABELS, PROGRESS, SCORES, owned
from plot_files import add_footer
from prepare_metrics import baseline

FIGURES = ("16_reputation_quadrants", "17_reputation_stages", "18_rating_sources")
COLORS = ("#397BA6", "#E69F00", "#009E73", "#8664A4")
SOURCE_NOTE = "样本来源：2026-10-13冻结1000款快照 → 198款有效主线曲线 → 183款完整三节点且三项推进比有效。"
LIMIT_NOTE = "解释：评论者与成就统计人群不同；模型主线节点的聚合覆盖比不是日留存，游戏级相关不证明因果。"


def plotting() -> tuple[Any, dict[str, Any]]:
    """Keep Matplotlib cache in T2Sum and reuse the established Chinese font palette."""
    os.environ["MPLCONFIGDIR"] = str(owned(ROOT / "runtime" / "matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt, {"font.family":"sans-serif", "font.sans-serif":baseline._cjk_fonts(),
                 "axes.unicode_minus":False, "font.size":11,
                 "axes.spines.top":False, "axes.spines.right":False}


def save(fig: Any, path: Path) -> None:
    """Export readable PNG and scalable SVG without embedding a variable SVG date."""
    fig.savefig(owned(path.with_suffix(".png")), dpi=180)
    fig.savefig(owned(path.with_suffix(".svg")), metadata={"Date":None})


def stat_text(row: Json) -> str:
    """Format an estimate and paired-game bootstrap interval, including unavailable cases."""
    if row["spearman"] is None:
        return f"n={row['n']} · 变量恒定，相关不可计算"
    return (f"n={row['n']} · Spearman ρ={row['spearman']:+.3f}\n"
            f"95%重采样区间 [{row['interval_low']:+.3f}, {row['interval_high']:+.3f}]")


def decorate(ax: Any, maximum: float) -> None:
    """Apply progression units without truncating exceptional ratios above one."""
    from matplotlib.ticker import PercentFormatter
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_ylim(-.025, max(1.08, maximum*1.08))
    ax.grid(color="#E0E7EC", linewidth=.7); ax.set_axisbelow(True)


def highlight(ax: Any, selected: list[Json], x: str, y: str, common: bool = False) -> None:
    """Outline eligible selected games while leaving the fixed background and statistics intact."""
    for g in selected:
        if not g["complete_three_point"] or (common and not g["three_scores_common"]) or g[x] is None:
            continue
        ax.scatter(g[x], g[y], s=145, facecolors="none", edgecolors="#172E3C", linewidths=1.7, zorder=6)
        ax.annotate(str(g["appid"]), (g[x],g[y]), xytext=(4,-12), textcoords="offset points", fontsize=8, zorder=7)


def draw_quadrants(games: list[Json], cases: list[Json], thresholds: Json, stat: Json,
                   selected: list[Json], output: Path) -> None:
    """Draw cohort-median quadrants with four explicitly exploratory extreme cases."""
    from matplotlib.ticker import PercentFormatter
    plt, style = plotting()
    with plt.rc_context(style):
        fig, (ax, cards) = plt.subplots(1,2,figsize=(14.8,8.6),gridspec_kw={"width_ratios":[1.6,1]})
        sx, sy = thresholds["steam_median"], thresholds["overall_median"]
        for i,(hx,hy) in enumerate(((True,True),(True,False),(False,True),(False,False))):
            members = [g for g in games if (g["steam_positive_ratio"]>=sx)==hx and (g["overall_progress_ratio"]>=sy)==hy]
            ax.scatter([g["steam_positive_ratio"] for g in members],[g["overall_progress_ratio"] for g in members],
                       s=43,alpha=.75,color=COLORS[i],edgecolors="white",linewidths=.4,
                       label=f"口碑{'高' if hx else '低'} / 推进{'高' if hy else '低'}：{len(members)}款")
        ax.axvline(sx,color="#697C89",linestyle="--",linewidth=1)
        ax.axhline(sy,color="#697C89",linestyle="--",linewidth=1)
        ax.set_xlim(max(0,min(g["steam_positive_ratio"] for g in games)-.04),1.015)
        decorate(ax,max(g["overall_progress_ratio"] for g in games))
        ax.xaxis.set_major_formatter(PercentFormatter(1,decimals=0))
        ax.set_xlabel("Steam好评率（SteamSpy正评 / 正负评价总数）",labelpad=12)
        ax.set_ylabel("全程推进比：代表结局 / 首节点")
        ax.text(.03,.97,stat_text(stat),transform=ax.transAxes,va="top",fontsize=10,
                bbox={"facecolor":"white","edgecolor":"none","alpha":.9})
        ax.legend(loc="upper center",bbox_to_anchor=(.5,-.16),ncol=2,fontsize=9,frameon=False)
        for c in cases:
            ax.annotate(c["case"],(c["steam_positive_ratio"],c["overall_progress_ratio"]),xytext=(6,6),
                        textcoords="offset points",fontsize=12,zorder=7)
        highlight(ax,selected,"steam_positive_ratio","overall_progress_ratio")
        cards.axis("off")
        cards.set_title("四象限探索案例（按固定规则选取）",loc="left",fontsize=12,pad=20)
        for i,c in enumerate(cases):
            title="\n".join(textwrap.wrap(c["name_en"].translate(str.maketrans("","","™®©")),width=39,break_long_words=False))
            text=(f"{c['case']}  {title}\nAppID {c['appid']} · {c['primary_gameplay']}\n"
                  f"好评率 {c['steam_positive_ratio']:.1%} · 全程推进 {c['overall_progress_ratio']:.1%}\n"
                  f"评价数 {c['review_count']:,}")
            cards.text(0,.97-i*.24,text,va="top",fontsize=10,linespacing=1.45)
        fig.suptitle("183款游戏：Steam口碑与主线全程推进的四象限",fontsize=20,y=.965)
        add_footer(fig,[SOURCE_NOTE,
            f"分界：同183款Steam中位数{sx:.2%}、全程推进中位数{sy:.2%}；等于中位数归高组，不代表绝对好坏或及格线。",
            "数据：每点一款游戏；案例按两个维度秩偏离中位位置的乘积降序选取，并列按AppID；为空间极端例而非典型代表。",
            LIMIT_NOTE])
        fig.subplots_adjust(left=.065,right=.985,top=.86,bottom=.30,wspace=.20)
        save(fig,output/FIGURES[0]); plt.close(fig)


def draw_panels(games: list[Json], stats: list[Json], selected: list[Json], output: Path, common: bool) -> None:
    """Use equal game membership for stage panels and for all three rating-source panels."""
    from matplotlib.ticker import PercentFormatter
    plt, style = plotting()
    pairs = [(s,"overall_progress_ratio") for s in SCORES] if common else [(SCORES[0],m) for m in PROGRESS]
    with plt.rc_context(style):
        fig, axes = plt.subplots(1,3,figsize=(16,7.4),sharey=True)
        for i,(ax,(x,y)) in enumerate(zip(axes,pairs)):
            ax.scatter([g[x] for g in games],[g[y] for g in games],s=38,alpha=.68,color=COLORS[i],
                       edgecolors="white",linewidths=.4,zorder=3)
            decorate(ax,max(g[p] for g in games for p in (PROGRESS if not common else (y,))))
            if x == SCORES[0]:
                ax.set_xlim(max(0,min(g[x] for g in games)-.04),1.015)
                ax.xaxis.set_major_formatter(PercentFormatter(1,decimals=0))
            else:
                ax.set_xlim(0,100 if x=="metacritic" else 5)
            ax.set_xlabel(LABELS[x]+("（0～100）" if x=="metacritic" else "（0～5）" if x=="rawg_rating" else ""),labelpad=12)
            ax.set_title(LABELS[x] if common else LABELS[y],fontsize=13,loc="left",pad=15)
            stat=next(r for r in stats if r["score"]==x and r["metric"]==y)
            ax.text(.035,.97,stat_text(stat),transform=ax.transAxes,va="top",fontsize=9,
                    bbox={"facecolor":"white","edgecolor":"none","alpha":.9})
            highlight(ax,selected,x,y,common)
        axes[0].set_ylabel("全程推进比：末 / 首" if common else "阶段推进比")
        title="同一140款游戏：三种评分来源与主线全程推进" if common else "同一183款游戏：Steam口碑与前段、后段、全程推进"
        fig.suptitle(title,fontsize=20,y=.965)
        add_footer(fig,[SOURCE_NOTE,
            "分组：183款中三种评分共同有效的140款，各面板游戏完全相同；缺失及RAWG零分不补值。" if common else "分组：三个面板始终使用同183款；前/后/全程分别为中/首、末/中、末/首。",
            "统计：游戏等权Spearman，并列取平均秩；整行联合Bootstrap 2000次、种子42；各评分保留原单位，不合成总分。",
            LIMIT_NOTE])
        fig.subplots_adjust(left=.06,right=.985,top=.84,bottom=.24,wspace=.17)
        save(fig,output/FIGURES[2 if common else 1]); plt.close(fig)
