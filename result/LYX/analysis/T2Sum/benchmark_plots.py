"""任务6：同类参照散点、阶段差及所选游戏的参照分布。"""

from __future__ import annotations

from pathlib import Path
import textwrap

import numpy as np

from reputation_data import Json, PROGRESS
from reputation_plots import plotting, save, COLORS
from plot_files import add_footer

FIGURES = ("19_peer_benchmark","20_peer_stage_gaps","21_peer_cases")
FOOT_SOURCE = "样本来源：2026-10-13冻结快照的183款完整三节点游戏；每款仅与其他游戏比较，不把自身放入参照。"
FOOT_RULE = "参照：完整玩法多标签Jaccard≥0.5，忽略other/uncertain，相同结局口径；至少5款有效，游戏等权。"
FOOT_LIMIT = "解释：同类是属性相似而非随机对照，模型节点未必等价；差值不等于因果效应、日留存或游戏质量。"


def unavailable_reason(game: Json) -> str:
    """Translate missing-state codes into an explanation for the figure reader."""
    if game["peer_status"]=="outside_three_point_cohort":
        return "仅两个有效节点，不参与本专题"
    return f"同类参照仅{game['peer_n']}款，至少需要5款"


def title(game: Json, width: int = 29) -> str:
    """Wrap stored game names, omitting trademark glyphs only in figure typography."""
    return "\n".join(textwrap.wrap(game["name_en"].translate(str.maketrans("","","™®©")),width=width,break_long_words=False))


def draw_overview(rows: list[Json], selected: list[Json], output: Path) -> None:
    """Draw all eligible frozen targets with an equality diagonal and optional outlines."""
    from matplotlib.ticker import PercentFormatter
    plt,style = plotting()
    valid = [r for r in rows if r["peer_status"]=="available"]
    with plt.rc_context(style):
        fig,ax = plt.subplots(figsize=(11.8,8.5))
        x=[g[PROGRESS[2]+"_reference_median"] for g in valid]
        y=[g[PROGRESS[2]] for g in valid]
        deltas=[g[PROGRESS[2]+"_delta"]*100 for g in valid]
        extent=max(abs(v) for v in deltas)
        dots=ax.scatter(x,y,c=deltas,cmap="PuOr_r",vmin=-extent,vmax=extent,s=49,alpha=.82,
                        linewidths=.4,edgecolors="white",zorder=3)
        upper=max(1.02,max(x+y)*1.04)
        ax.plot([0,upper],[0,upper],linestyle="--",color="#6C7C88",linewidth=1.2,label="实际＝参照中位数")
        for item in selected:
            if item["peer_status"]!="available":continue
            ax.scatter(item[PROGRESS[2]+"_reference_median"],item[PROGRESS[2]],s=160,facecolors="none",edgecolors="#142D3F",linewidths=1.5,zorder=5)
            ax.annotate(item.get("case",str(item["appid"])),(item[PROGRESS[2]+"_reference_median"],item[PROGRESS[2]]),
                        xytext=(5,5),textcoords="offset points",fontsize=10,zorder=6)
        ax.set_xlim(-.02,upper); ax.set_ylim(-.02,upper)
        ax.xaxis.set_major_formatter(PercentFormatter(1,decimals=0));ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0))
        ax.set_xlabel("同类参照的全程推进中位数",labelpad=12);ax.set_ylabel("该游戏实际全程推进比：末 / 首")
        ax.grid(color="#E0E7EC",linewidth=.7);ax.set_axisbelow(True)
        ax.legend(loc="upper left",frameon=False)
        bar=fig.colorbar(dots,ax=ax,pad=.03,fraction=.045)
        bar.set_label("实际 - 参照（百分点）",labelpad=10)
        fig.suptitle(f"同类参照：{len(valid)}款有效游戏的实际与参照推进",fontsize=20,y=.965)
        add_footer(fig,[FOOT_SOURCE,FOOT_RULE,
            f"数据：每点一款目标游戏；183款中{len(valid)}款参照充足，其余保留缺失说明；对角线上方为高于自身参照。",FOOT_LIMIT])
        fig.subplots_adjust(left=.09,right=.87,top=.87,bottom=.24)
        save(fig,output/FIGURES[0]);plt.close(fig)


def draw_stage_gaps(selected: list[Json], output: Path) -> None:
    """Compare three stage differences for one to five games without recomputing any peers."""
    plt,style=plotting()
    with plt.rc_context(style):
        fig,ax=plt.subplots(figsize=(max(10.5,3*len(selected)),8.3))
        xs=np.arange(len(selected))
        values=[]
        for index,field in enumerate(PROGRESS):
            for i,g in enumerate(selected):
                v=g.get(field+"_delta")
                if v is None:continue
                value=v*100;values.append(value)
                ax.bar(xs[i]+(index-1)*.25,value,width=.22,color=COLORS[index],zorder=3,
                       label=("前段差","后段差","全程差")[index] if i==next((j for j,h in enumerate(selected) if h.get(field+"_delta") is not None),-1) else None)
                ax.annotate(f"{value:+.1f}",(xs[i]+(index-1)*.25,value),xytext=(0,5 if value>=0 else -12),
                            textcoords="offset points",ha="center",fontsize=9)
        for i,g in enumerate(selected):
            if g["peer_status"]!="available":
                ax.text(xs[i],0,unavailable_reason(g),ha="center",va="bottom",rotation=90,fontsize=9,color="#687D89")
        ax.axhline(0,color="#647987",linewidth=1)
        ax.set_ylim(min(-10,min(values,default=0)-12),max(10,max(values,default=0)+12))
        ax.set_xticks(xs,[title(g,25)+f"\nAppID {g['appid']} · 参照n={g['peer_n']}" for g in selected],fontsize=9)
        ax.set_ylabel("实际 - 同类参照中位数（百分点）")
        ax.grid(axis="y",color="#E0E7EC",linewidth=.7);ax.set_axisbelow(True)
        if values:ax.legend(ncol=3,loc="lower left",bbox_to_anchor=(0,1.02),frameon=False)
        fig.suptitle(f"{len(selected)}款游戏：相对同类的前段、后段与全程差异",fontsize=19,y=.965)
        add_footer(fig,[FOOT_SOURCE,FOOT_RULE,
            "数据：三根柱分别使用同一参照名单在对应阶段的中位数；各阶段中位数不可相乘，全程差也不等于前后段差之和。",FOOT_LIMIT])
        fig.subplots_adjust(left=.07,right=.985,top=.86,bottom=.33)
        save(fig,output/FIGURES[1]);plt.close(fig)


def draw_cases(selected: list[Json], membership: list[Json], output: Path) -> None:
    """Show exact peer distributions and a target marker, with audit information in side cards."""
    from matplotlib.ticker import PercentFormatter
    plt,style=plotting()
    with plt.rc_context(style):
        count=len(selected)
        fig,axes=plt.subplots(count,2,figsize=(15,max(6,count*3.0+2.0)),squeeze=False,
                              gridspec_kw={"width_ratios":[1.3,1]})
        for i,(g,(ax,card)) in enumerate(zip(selected,axes)):
            peers=[r for r in membership if r["config"]=="main" and r["appid"]==g["appid"]]
            if g["peer_status"]=="available":
                vals=[p[PROGRESS[2]] for p in peers]
                ax.boxplot([vals],positions=[1],vert=False,widths=.33,whis=(0,100),patch_artist=True,
                           boxprops={"facecolor":"#DFEAF2","edgecolor":COLORS[0]},
                           medianprops={"color":"#19394D","linewidth":2},whiskerprops={"color":COLORS[0]},capprops={"color":COLORS[0]})
                ax.scatter(vals,[1]*len(vals),s=26,color=COLORS[0],alpha=.45,zorder=3)
                ax.scatter(g[PROGRESS[2]],1,s=95,color="#172F41",marker="D",label="所选游戏",zorder=5)
                ax.legend(loc="upper left",frameon=False,fontsize=9)
                info=f"实际 {g[PROGRESS[2]]:.1%} · 参照中位数 {g[PROGRESS[2]+'_reference_median']:.1%} · 差 {g[PROGRESS[2]+'_delta']*100:+.1f}个百分点\n"
                info+=f"参照n={g['peer_n']} · 其中已知节点疑点 {g['known_issue_peer_n']}款\n"
                closest="；".join(p["peer_name_en"].translate(str.maketrans("","","™®©")) for p in peers[:3])
                info+="相似度最高的参照（最多列3款）：\n"+"\n".join(textwrap.wrap(closest,width=60,break_long_words=False))
            else:
                ax.text(.5,.5,unavailable_reason(g),transform=ax.transAxes,ha="center",fontsize=11)
                info=f"参照n={g['peer_n']}；缺失不补零、不自动扩大范围。"
            ax.set_title(f"{g.get('case',i+1)}  "+title(g,48).replace("\n"," "),loc="left",fontsize=11,pad=9)
            ax.set_ylim(.5,1.55);ax.set_yticks([]);ax.set_xlim(-.02,1.04)
            ax.xaxis.set_major_formatter(PercentFormatter(1,decimals=0));ax.grid(axis="x",color="#E0E7EC")
            ax.set_xlabel("全程推进比：参照游戏分布与所选游戏",fontsize=9)
            card.axis("off")
            labels=g.get("gameplay_labels","").replace("|"," / ")
            warning=g.get("known_caveat") or "未单独人工核验，不代表节点语义已获确认。"
            flags=g.get("quality_flags") or "无额外来源标记"
            raw_end=g.get("end_description") or "末节点描述缺失"
            warning+="\n来源标记："+flags+"\n末节点原文："+raw_end
            card.text(0,.99,f"AppID {g['appid']} · {g.get('ending_type','—')}\n"+
                      "\n".join(textwrap.wrap(labels,width=65))+"\n"+info+"\n提示："+
                      "\n".join(textwrap.wrap(warning,width=38)),va="top",fontsize=9,linespacing=1.4)
        fig.suptitle("所选游戏与同类参照：实际位置、分布及节点提示",fontsize=20,y=.98)
        add_footer(fig,[FOOT_SOURCE,FOOT_RULE,
            "数据：箱体为游戏间Q1～Q3、中线为中位数、须为最小～最大，蓝点为参照、黑菱形为所选游戏；不是置信区间。",FOOT_LIMIT])
        fig.subplots_adjust(left=.055,right=.985,top=.91,bottom=.19 if count>1 else .27,hspace=.85,wspace=.17)
        save(fig,output/FIGURES[2]);plt.close(fig)
