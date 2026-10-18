"""沿既有主线节点顺序分析相邻区间，展示全程相近游戏的完整推进过程。"""

from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import textwrap
from typing import Any

from analyze_types import TYPE_NAMES, plotting
from compare_games import COLORS, load_catalog
from plot_files import add_footer, figure_directory
from prepare_metrics import DEFAULT_OUTPUT, ROOT, csv_text, digest, owned_path, protected_snapshot, source, write_text

VERSION = "lyx-adjacent-trajectory-v1"
DEFAULT_TRAJECTORY = DEFAULT_OUTPUT / "trajectory_analysis"
FIGURE_NAMES = ("08_story_curves", "09_adjacent_progress")
CASE_MIN_NODES = 6
CASE_NODE_GAP = 2
CASE_OVERALL_GAP = 0.03
MAX_CASE_PAIRS = 3
Json = dict[str, Any]


def prior_artifacts() -> dict[str, str]:
    """Fingerprint existing metric/type/selection outputs and the first seven figures."""
    files = [p for folder in (DEFAULT_OUTPUT / "comparisons", DEFAULT_OUTPUT / "type_analysis")
             for p in folder.rglob("*") if p.is_file()]
    files += [p for p in DEFAULT_OUTPUT.iterdir() if p.is_file()]
    files += [p for p in (ROOT / "figures").glob("*") if p.suffix in (".png", ".svg") and p.name[:2] in {f"{i:02}" for i in range(1, 8)}]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def load_sequences(games: list[Json]) -> dict[int, list[Json]]:
    """Read frozen checkpoint CSV, preserving original indices and excluding unused endings."""
    by_id = {g["appid"]: g for g in games}
    sequences: dict[int, list[Json]] = defaultdict(list)
    seen = set()
    with (DEFAULT_OUTPUT / "checkpoints.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            appid = int(row["appid"])
            if appid not in by_id:
                raise ValueError(f"节点AppID不在固定范围：{appid}")
            identity = (appid, row["local_id"])
            if identity in seen:
                raise ValueError(f"重复节点：{identity}")
            seen.add(identity)
            included = row["is_in_sequence"] == "true"
            if included != bool(row["sequence_position"]):
                raise ValueError("节点序列标记与位置不一致")
            if not included:
                continue
            rate = float(row["rate"])
            if not math.isfinite(rate) or not 0 <= rate <= 1:
                raise ValueError("节点原始解锁率不合法")
            sequences[appid].append({**row, "appid": appid, "rate": rate,
                                     "sequence_position": int(row["sequence_position"]),
                                     "source_checkpoint_index": int(row["source_checkpoint_index"]),
                                     "confidence": float(row["confidence"])})
    if set(sequences) != set(by_id):
        raise ValueError("节点明细与198款指标范围不一致")
    for appid, nodes in sequences.items():
        # File order must already be narrative order: do not repair by sorting.
        if [n["sequence_position"] for n in nodes] != list(range(1, len(nodes) + 1)):
            raise ValueError(f"appid={appid}节点顺序不连续，禁止重排修复")
        original = [n["source_checkpoint_index"] for n in nodes]
        if original != sorted(set(original)):
            raise ValueError("节点原数组下标不严格递增")
        game = by_id[appid]
        if len(nodes) != game["node_count"] or len(nodes) < 2:
            raise ValueError("有效节点数量与底表不一致")
        if (nodes[0]["local_id"] != game["first_local_id"] or nodes[-1]["local_id"] != game["end_local_id"]
                or not math.isclose(nodes[0]["rate"], game["p_s"], abs_tol=1e-12)
                or not math.isclose(nodes[-1]["rate"], game["p_f"], abs_tol=1e-12)):
            raise ValueError("首末节点与既有指标不一致")
    return dict(sequences)


def matching_maxima(rows: list[Json], field: str) -> list[Json]:
    """Keep every maximum within numerical tolerance; file order breaks display ties."""
    valid = [r for r in rows if r[field] is not None]
    if not valid:
        return []
    maximum = max(r[field] for r in valid)
    return [r for r in valid if math.isclose(r[field], maximum, rel_tol=1e-12, abs_tol=1e-12)]


def describe_game(game: Json, nodes: list[Json]) -> tuple[Json, list[Json]]:
    """Compute adjacent ratios, signed percentage-point gaps and an auditable game profile."""
    n = len(nodes)
    ps, pf = nodes[0]["rate"], nodes[-1]["rate"]
    edges = []
    for index, (first, second) in enumerate(zip(nodes, nodes[1:]), 1):
        a, b = first["rate"], second["rate"]
        ratio = b / a if a > 0 else None
        flags = []
        if a <= 0:
            flags.append("nonpositive_denominator")
        if b > a:
            flags.append("reverse_jump")
        if game["ending_type"] == "multi":
            flags.append("multi_ending_proxy")
        edges.append({"appid": game["appid"], "title": game["title"], "primary_gameplay": game["primary_gameplay"],
                      "ending_type": game["ending_type"], "node_count": n, "edge_position": index,
                      "from_local_id": first["local_id"], "to_local_id": second["local_id"],
                      "from_display_name": first["display_name"], "to_display_name": second["display_name"],
                      "from_sequence_position": index, "to_sequence_position": index + 1,
                      "from_source_checkpoint_index": first["source_checkpoint_index"],
                      "to_source_checkpoint_index": second["source_checkpoint_index"],
                      "from_stage": first["stage"], "to_stage": second["stage"],
                      "from_confidence": first["confidence"], "to_confidence": second["confidence"],
                      "to_requires_start": second["requires_start"], "route": second["route"],
                      "from_rate": a, "to_rate": b, "adjacent_progress_ratio": ratio,
                      "relative_drop": 1 - ratio if ratio is not None else None,
                      "coverage_gap_pp": (a - b) * 100,
                      "gap_relative_to_first": (a - b) / ps if ps > 0 else None,
                      "from_node_fraction": (index - 1) / (n - 1), "to_node_fraction": index / (n - 1),
                      "interval_midpoint_fraction": (index - 0.5) / (n - 1), "quality_flags": "|".join(flags)})
    relative = matching_maxima(edges, "relative_drop")
    absolute = matching_maxima(edges, "coverage_gap_pp")
    monotonic = all(e["coverage_gap_pp"] >= 0 for e in edges)
    product = math.prod(e["adjacent_progress_ratio"] for e in edges) if all(e["adjacent_progress_ratio"] is not None for e in edges) else None
    overall = pf / ps if ps > 0 else None
    consistent = math.isclose(product, overall, rel_tol=1e-10, abs_tol=1e-12) if product is not None and overall is not None else None
    if overall is not None and game["overall_progress_ratio"] is not None and not math.isclose(overall, game["overall_progress_ratio"], abs_tol=1e-12):
        raise ValueError("全程推进比与既有指标不一致")
    if consistent is False:
        raise ValueError("相邻比值乘积与全程比不一致")
    flags = []
    if n == 2:
        flags.append("two_nodes_no_internal_comparison")
    if not monotonic:
        flags.append("nonmonotonic_profile")
    if ps == pf:
        flags.append("no_total_coverage_gap")
    if int(game["start_label_count"]) != 1 or game["first_stage"] != "start":
        flags.append("no_unique_leading_start")
    if game["ending_type"] == "multi":
        flags.append("multi_ending_proxy")
    concentration = absolute[0]["coverage_gap_pp"] / ((ps - pf) * 100) if absolute and ps > pf and monotonic else None
    profile = {"appid": game["appid"], "title": game["title"], "primary_gameplay": game["primary_gameplay"],
               "gameplay_labels": game["gameplay_labels"], "ending_type": game["ending_type"],
               "node_count": n, "edge_count": n - 1, "p_s": ps, "p_f": pf,
               "overall_progress_ratio": overall, "adjacent_ratio_product": product, "product_consistent": consistent,
               "valid_ratio_count": sum(e["adjacent_progress_ratio"] is not None for e in edges),
               "reverse_jump_count": sum(e["coverage_gap_pp"] < 0 for e in edges),
               "max_gap_share": concentration, "case_eligible": n >= CASE_MIN_NODES and monotonic and product is not None and concentration is not None,
               "quality_flags": "|".join(flags)}
    for prefix, selected in (("max_relative", relative), ("max_coverage_gap", absolute)):
        chosen = selected[0] if selected else None
        profile[prefix + "_tie_count"] = len(selected)
        for field in ("edge_position", "from_display_name", "to_display_name", "from_stage", "to_stage",
                      "relative_drop", "coverage_gap_pp", "interval_midpoint_fraction"):
            profile[prefix + "_" + field] = chosen[field] if chosen else None
    for edge in edges:
        edge["is_max_relative_drop"] = edge in relative
        edge["is_max_coverage_gap"] = edge in absolute
    return profile, edges


def choose_pairs(profiles: list[Json]) -> tuple[list[Json], list[Json]]:
    """Rank eligible same-primary, same-ending pairs and select at most three disjoint pairs."""
    eligible = [g for g in profiles if g["case_eligible"]]
    candidates = []
    for first, second in itertools.combinations(sorted(eligible, key=lambda g: g["appid"]), 2):
        gap = abs(first["overall_progress_ratio"] - second["overall_progress_ratio"])
        node_gap = abs(first["node_count"] - second["node_count"])
        if (first["primary_gameplay"] != second["primary_gameplay"] or first["ending_type"] != second["ending_type"]
                or node_gap > CASE_NODE_GAP or gap > CASE_OVERALL_GAP):
            continue
        candidates.append({"appid_a": first["appid"], "title_a": first["title"], "appid_b": second["appid"], "title_b": second["title"],
                           "primary_gameplay": first["primary_gameplay"], "ending_type": first["ending_type"],
                           "node_count_a": first["node_count"], "node_count_b": second["node_count"], "node_count_gap": node_gap,
                           "overall_ratio_a": first["overall_progress_ratio"], "overall_ratio_b": second["overall_progress_ratio"],
                           "overall_gap_pp": gap * 100,
                           "max_relative_position_gap": abs(first["max_relative_interval_midpoint_fraction"] - second["max_relative_interval_midpoint_fraction"]),
                           "concentration_gap": abs(first["max_gap_share"] - second["max_gap_share"])})
    candidates.sort(key=lambda r: (-r["max_relative_position_gap"], -r["concentration_gap"], r["overall_gap_pp"],
                                   r["node_count_gap"], r["appid_a"], r["appid_b"]))
    selected, used = [], set()
    for index, row in enumerate(candidates, 1):
        row["candidate_rank"] = index
        chosen = len(selected) < MAX_CASE_PAIRS and not used.intersection((row["appid_a"], row["appid_b"]))
        row["selected_pair"] = len(selected) + 1 if chosen else None
        if chosen:
            selected.append(row)
            used.update((row["appid_a"], row["appid_b"]))
    return candidates, selected


def short_name(name: str, length: int = 30) -> str:
    """Shorten only figure annotations; keep full achievement names in the audit tables."""
    return name if len(name) <= length else name[:length - 1] + "…"


def save_figure(fig: Any, output: Path) -> None:
    """Save a checked PNG/SVG pair without writing other figures or input files."""
    fig.savefig(owned_path(output.with_suffix(".png")), dpi=180)
    fig.savefig(owned_path(output.with_suffix(".svg")), metadata={"Date": None})


def draw_curves(pairs: list[Json], sequences: dict[int, list[Json]], profiles: dict[int, Json], output: Path) -> None:
    """Overlay original normalized node observations, highlighting the earliest maximum relative gap."""
    from matplotlib.ticker import PercentFormatter

    plt, style = plotting()
    count = max(1, len(pairs))
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, count, figsize=(max(11, count * 5.2), 8.6), squeeze=False)
        for ax, pair in zip(axes[0], pairs):
            for index, side in enumerate(("a", "b")):
                appid = pair[f"appid_{side}"]
                g, nodes = profiles[appid], sequences[appid]
                x = [i / (len(nodes) - 1) for i in range(len(nodes))]
                y = [n["rate"] / g["p_s"] for n in nodes]
                label = "\n".join(textwrap.wrap(f"{'AB'[index]} {g['title']}", width=37, break_long_words=False))
                label += f"\n首覆盖{g['p_s']:.1%} · 全程{g['overall_progress_ratio']:.1%}"
                ax.plot(x, y, marker="o", markersize=4, linewidth=1.6, color=COLORS[index],
                        label=label)
                edge = g["max_relative_edge_position"]
                ax.plot(x[edge - 1:edge + 1], y[edge - 1:edge + 1], color=COLORS[index], linewidth=4)
                caption = (f"{'AB'[index]}最大相对降幅{g['max_relative_relative_drop']:.1%}："
                           f"{short_name(g['max_relative_from_display_name'])} → {short_name(g['max_relative_to_display_name'])}")
                ax.text(0, -0.39 - index * 0.17, "\n".join(textwrap.wrap(caption, width=47)),
                        transform=ax.transAxes, ha="left", va="top", fontsize=8.5, color=COLORS[index])
            ending = "统一结局" if pair["ending_type"] == "unified" else "多结局代理"
            ax.set_title(f"{TYPE_NAMES[pair['primary_gameplay']]} · {ending}\n全程差{pair['overall_gap_pp']:.2f}个百分点", fontsize=12, loc="left", pad=14)
            ax.set_xlim(-0.025, 1.025)
            ax.set_ylim(-0.025, 1.075)
            ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.set_xlabel("节点相对位置（非时间）", labelpad=10)
            ax.set_ylabel("相对首节点覆盖", labelpad=8)
            ax.grid(color="#DFE6EC", linewidth=0.7)
            ax.legend(loc="upper left", bbox_to_anchor=(0, -0.14), frameon=False, fontsize=8)
        if not pairs:
            axes[0, 0].text(0.5, 0.5, "没有满足既定条件的游戏对，不放宽筛选规则", ha="center")
        fig.suptitle("同主类型游戏：全程相近时的完整主线覆盖曲线", fontsize=20, y=0.97)
        add_footer(fig, [f"样本来源：2026-10-13冻结1000款快照 → 198款有效主线曲线；从其中133款至少6节点游戏选取{len(pairs)}组案例。",
                   "选择：同主类型、同结局口径，节点数差≤2、全程比差≤3个百分点；优先最大相对差距位置不同的组合，游戏不重复。",
                   "数据：原始节点覆盖除以本游戏首节点覆盖；横轴=(节点序号-1)/(节点数-1)，连线辅助阅读，不插值生成观测节点。",
                   "解释：粗线标最大相对降幅区间，并列展示最早一段；名称过长在图中截短，完整名称见明细；非日留存或设计因果。"])
        fig.subplots_adjust(left=0.055, right=0.985, top=0.84, bottom=0.44, wspace=0.30)
        save_figure(fig, output / FIGURE_NAMES[0])
        plt.close(fig)


def draw_adjacent(pairs: list[Json], edges: list[Json], profiles: dict[int, Json], output: Path) -> None:
    """Show each selected game's real adjacent intervals and its maximum gap in percentage points."""
    from matplotlib.ticker import PercentFormatter

    plt, style = plotting()
    grouped: dict[int, list[Json]] = defaultdict(list)
    for edge in edges:
        grouped[edge["appid"]].append(edge)
    count = max(1, len(pairs))
    with plt.rc_context(style):
        fig, axes = plt.subplots(count, 2, figsize=(15.6, count * 3.4 + 2.5), squeeze=False)
        for row, pair in enumerate(pairs):
            for column, side in enumerate(("a", "b")):
                ax = axes[row, column]
                g = profiles[pair[f"appid_{side}"]]
                items = grouped[g["appid"]]
                x = list(range(1, len(items) + 1))
                for position, edge in zip(x, items):
                    value = edge["adjacent_progress_ratio"]
                    color = COLORS[1] if edge["is_max_relative_drop"] else COLORS[0]
                    if value is not None:
                        ax.bar(position, value, width=0.72, color=color, zorder=3)
                        ax.annotate(f"{value:.0%}", (position, value), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.5)
                    else:
                        ax.text(position, 0.02, "缺失", rotation=90, ha="center", fontsize=8)
                ax.set_title(f"第{row + 1}组 {'AB'[column]} · {g['title']}\n{g['node_count']}节点 · 全程{g['overall_progress_ratio']:.1%}", loc="left", fontsize=10, pad=10)
                ax.set_ylim(0, 1.15)
                ax.set_xticks(x, [f"{e['from_sequence_position']}→{e['to_sequence_position']}" for e in items], rotation=45 if len(items) > 12 else 0, fontsize=8)
                ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
                ax.grid(axis="y", color="#DFE6EC", zorder=0)
                ax.set_axisbelow(True)
                ax.set_ylabel("相邻推进比", fontsize=9)
                note = (f"最大相对降幅{g['max_relative_relative_drop']:.1%}；该区间覆盖差"
                        f"{g['max_relative_coverage_gap_pp']:.2f}个百分点；并列{g['max_relative_tie_count']}段")
                ax.set_xlabel(note, fontsize=9, labelpad=10)
        if not pairs:
            axes[0, 0].text(0.1, 0.5, "没有满足条件的案例")
        fig.suptitle("逐游戏相邻节点：推进比与最大相对差距区间", fontsize=20, y=0.975)
        add_footer(fig, [f"样本来源：固定198款的1741个有效主线节点、1543段相邻区间；本图展示与08相同的{len(pairs)}组、{len(pairs) * 2}款案例。",
                   "顺序：保留原有效主线数组顺序；横轴i→i+1对应真实相邻节点，不跨越缺失节点，不按解锁率重排。",
                   "数据：柱高=后节点解锁率/前节点解锁率；橙色标最大相对降幅（含并列），轴下注明该区间的原始覆盖差。",
                   "解释：相对降幅大不一定对应较大的百分点差；节点跨度和结局代理可能不同，不能解释为玩家流失或设计因果。"])
        fig.subplots_adjust(left=0.06, right=0.985, top=0.89, bottom=0.23, wspace=0.17, hspace=0.95)
        save_figure(fig, output / FIGURE_NAMES[1])
        plt.close(fig)


def report_text(profiles: list[Json], edges: list[Json], candidates: list[Json], pairs: list[Json], audit: Json,
                output: Path, figures: Path) -> str:
    """Report complete coverage, exact case nodes, selection rules and interpretation limits."""
    by_id = {g["appid"]: g for g in profiles}
    lines = ["# 专题3：全程相近游戏的完整主线推进过程", "", f"实施日期：2026-10-16。数据版本：{audit['dataset_version']}。", "",
             "## 范围与计算", "",
             f"固定198款，{sum(g['node_count'] for g in profiles)}个有效序列节点、{len(edges)}段真实相邻区间；不改原指标、节点、数组顺序或代表结局。",
             "183款至少3节点、172款至少4节点、133款至少6节点；15款仅有首末节点仍保留，不能用一个区间判断内部差距位置。",
             "相邻推进比=p后/p前；相对降幅=1-相邻推进比；原始覆盖差=100×(p前-p后)个百分点；相对首节点覆盖=p节点/p首。",
             "横轴相对位置=(序号-1)/(节点数-1)，不是游玩时间或真实剧情百分比。分母非正时留空，不补零或跨过缺失段；反向上升保留原值与标记，不截断或重排。",
             "最大值并列均在明细标记，摘要与曲线标注原数组中最早一段；相邻比值全有效时检查乘积等于既有全程比。",
             "max_gap_share=最大百分点差/(首末总百分点差)，仅在非反向且首末有正差时计算；首末相同留空。该比例受节点数量影响，不跨节点密度直接排名。", "",
             "## 案例选择", "",
             f"至少6节点、同主类型、同结局口径、节点数差≤2、全程比差≤3个百分点，共{len(candidates)}对候选；按最大相对降幅区间中点位置差降序、覆盖差集中度差降序、全程差升序、节点数差升序、AppID升序排序，贪心取最多3组不重复游戏。",
             "该规则仅用于探索性展示，不是相同玩家、相同章节长度或因果控制；全部候选和是否选中均保存。节点不足不改变198款计算范围。", "",
             "| 组 | 主类型 / 结局口径 | 游戏A（节点） | 游戏B（节点） | A全程 | B全程 | 全程差 |",
             "|---|---|---|---|---:|---:|---:|"]
    for i, pair in enumerate(pairs, 1):
        lines.append(f"| {i} | {TYPE_NAMES[pair['primary_gameplay']]} / {pair['ending_type']} | {pair['title_a']}（{pair['node_count_a']}） | "
                     f"{pair['title_b']}（{pair['node_count_b']}） | {pair['overall_ratio_a']:.2%} | {pair['overall_ratio_b']:.2%} | {pair['overall_gap_pp']:.2f}个百分点 |")
    for i, pair in enumerate(pairs, 1):
        lines += ["", f"### 第{i}组：具体差距节点", ""]
        for side in ("a", "b"):
            g = by_id[pair[f"appid_{side}"]]
            lines.append(f"- {g['title']}：相对降幅最大区间为“{g['max_relative_from_display_name']}” → “{g['max_relative_to_display_name']}”，"
                         f"第{g['max_relative_edge_position']}→{g['max_relative_edge_position'] + 1}节点，"
                         f"阶段{g['max_relative_from_stage']}→{g['max_relative_to_stage']}；相对降幅{g['max_relative_relative_drop']:.2%}，"
                         f"原始覆盖差{g['max_relative_coverage_gap_pp']:.2f}个百分点，并列{g['max_relative_tie_count']}段。")
        first, second = by_id[pair["appid_a"]], by_id[pair["appid_b"]]
        lines += [f"原始首节点覆盖分别为{first['p_s']:.2%}与{second['p_s']:.2%}；图08将各自首节点归一为100%，"
                  "因此曲线是在不同原始覆盖基准上的形态对照，不是相同玩家人群或相同入门门槛。"]
    lines += ["", "## 图与审计表", ""]
    for stem, label in zip(FIGURE_NAMES, ("完整主线曲线", "相邻区间推进")):
        link = Path(os.path.relpath(figures / (stem + ".png"), output)).as_posix()
        lines += [f"![{label}]({link})", ""]
    lines += ["[相邻区间明细](adjacent_nodes.csv)、[全部游戏过程摘要](game_profiles.csv)、[全部案例候选及选中标记](case_candidates.csv)、[版本与保护核验](manifest.json)。", "",
              "## 可解释结论与限制", "",
              "图中可观察的是标注节点之间的聚合覆盖差距；全程相近并不意味着覆盖差距发生在同一个位置。这里按既定规则挑选差异较大的案例，不能据此估计此类模式在所有游戏中的普遍程度。",
              "当前三组均为动作主类型、统一结局口径，是筛选和排序后的案例构成，不代表已检验所有类型；原始首节点覆盖差异同时展示，不因归一化而隐藏。",
              "正文保留成就完整展示名；只在图中截短过长名称，不展示内部ID。后续可以结合成就描述核查节点语义和章节跨度；当前没有额外人工事实或设计原因证据，不把差距归因为Boss、剧情或操作难度。",
              "模型公共主线和先后顺序继续复用，未证实玩家解锁集合的包含关系；相邻推进比不是条件玩家比例、流失率或日留存。不同节点密度、首节点与多结局代理均影响可比性。",
              "数据库、T0Pre、既有底表和01～07图保持不变，无新采集、模型调用或数据库写入。", ""]
    return "\n".join(lines)


def analyze(output: str | Path = DEFAULT_TRAJECTORY) -> Json:
    """Run adjacent-node analysis and two case figures, checking previous results stay intact."""
    output = owned_path(output)
    forbidden = (ROOT / "figures", DEFAULT_OUTPUT / "comparisons", DEFAULT_OUTPUT / "type_analysis")
    if output in (ROOT, DEFAULT_OUTPUT) or any(output.is_relative_to(p) for p in forbidden):
        raise ValueError("过程分析须使用独立目录，不能覆盖原底表、类型分析或图集目录")
    protected_before, prior_before = protected_snapshot(), prior_artifacts()
    games, audit = load_catalog()
    sequences = load_sequences(games)
    profiles, edges = [], []
    for game in games:
        profile, items = describe_game(game, sequences[game["appid"]])
        profiles.append(profile)
        edges.extend(items)
    candidates, pairs = choose_pairs(profiles)
    checks = {"fixed_198": len(profiles) == 198, "selected_nodes_1741": sum(len(v) for v in sequences.values()) == 1741,
              "adjacent_edges_1543": len(edges) == 1543, "two_node_games_15_preserved": sum(g["node_count"] == 2 for g in profiles) == 15,
              "all_available_products_match": all(g["product_consistent"] is not False for g in profiles),
              "no_repeated_case_games": len({p[f"appid_{s}"] for p in pairs for s in ("a", "b")}) == 2 * len(pairs)}
    if not all(checks.values()):
        raise ValueError(f"过程计算核验失败：{checks}")
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("adjacent_nodes.csv", edges), ("game_profiles.csv", profiles), ("case_candidates.csv", candidates)):
        content = csv_text(rows) if rows else "candidate_rank,appid_a,appid_b,selected_pair\n"
        write_text(output / name, content, "utf-8-sig")
    figures = figure_directory(output, DEFAULT_TRAJECTORY)
    figures.mkdir(parents=True, exist_ok=True)
    by_id = {g["appid"]: g for g in profiles}
    draw_curves(pairs, sequences, by_id, figures)
    draw_adjacent(pairs, edges, by_id, figures)
    write_text(output / "report.md", report_text(profiles, edges, candidates, pairs, audit, output, figures))
    _, audit_after = load_catalog()
    protected_after, prior_after = protected_snapshot(), prior_artifacts()
    checks["inputs_unchanged"] = audit == audit_after and protected_before == protected_after
    checks["previous_outputs_and_figures_unchanged"] = prior_before == prior_after
    names = ["adjacent_nodes.csv", "game_profiles.csv", "case_candidates.csv", "report.md"]
    names += [Path(os.path.relpath(figures / f"{stem}.{ext}", output)).as_posix() for stem in FIGURE_NAMES for ext in ("png", "svg")]
    parameters = {"case_min_nodes": CASE_MIN_NODES, "max_node_count_gap": CASE_NODE_GAP,
                  "max_overall_ratio_gap": CASE_OVERALL_GAP, "max_case_pairs": MAX_CASE_PAIRS,
                  "ranking": "position gap desc; concentration gap desc; overall gap asc; node gap asc; appids asc",
                  "max_tie_tolerance": 1e-12, "node_fraction": "(position-1)/(node_count-1)",
                  "missing_denominator": "blank; never skip over an interval"}
    manifest = {"created_at": source.now(), "version": VERSION, "source": audit, "parameters": parameters, "checks": checks,
                "counts": {"games": len(profiles), "nodes": sum(len(v) for v in sequences.values()), "edges": len(edges),
                           "case_eligible_games": sum(g["case_eligible"] for g in profiles), "candidate_pairs": len(candidates),
                           "selected_pairs": len(pairs), "zero_denominator_edges": sum(e["adjacent_progress_ratio"] is None for e in edges),
                           "reverse_edges": sum(e["coverage_gap_pp"] < 0 for e in edges)},
                "selected_pairs": pairs, "protected_before": protected_before, "protected_after": protected_after,
                "prior_artifacts_before": prior_before, "prior_artifacts_after": prior_after,
                "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                    (Path(__file__).name, "run.py", "plot_files.py", "compare_games.py", "prepare_metrics.py", "analyze_types.py")},
                "outputs_path_base": "manifest directory", "outputs_sha256": {n: hashlib.sha256((output / n).read_bytes()).hexdigest() for n in names}}
    write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if not all(checks.values()):
        raise RuntimeError("过程分析期间输入或既有图表改变，请核对manifest")
    return {"version": VERSION, "counts": manifest["counts"], "checks": checks,
            "selected_pairs": [{k: p[k] for k in ("title_a", "title_b", "overall_gap_pp", "node_count_a", "node_count_b")} for p in pairs],
            "report": str(output / "report.md"), "figures": [str(figures / (stem + ".png")) for stem in FIGURE_NAMES]}
