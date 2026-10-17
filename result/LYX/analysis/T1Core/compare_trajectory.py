"""自选游戏的主线过程对比；每组1～5款，默认每组2款，保留末组余数。"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import textwrap
from typing import Any

import analyze_trajectory as trajectory
from compare_games import load_catalog, select_games
from plot_files import add_footer
from prepare_metrics import ROOT, DEFAULT_OUTPUT, csv_text, digest, owned_path, protected_snapshot, source, write_text

VERSION = "lyx-selected-trajectory-v1"
DEFAULT_SELECTION = DEFAULT_OUTPUT / "trajectory_comparisons"
COLORS = ("#397BA6", "#E69F00", "#009E73", "#8E6C8A", "#D55E00")
Json = dict[str, Any]


def group_games(games: list[Json], games_per_group: int | None = None,
                group_count: int | None = None) -> list[list[Json]]:
    """Chunk by explicit size/default two, or balance when only a group count is supplied."""
    count = len(games)
    if not 1 <= count <= 198:
        raise ValueError("请选择1～198款范围内的游戏，每组最多5款")
    for value, label, maximum in ((games_per_group, "每组款数", 5), (group_count, "组数", count)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum):
            raise ValueError(f"{label}必须为1～{maximum}的整数")
    if games_per_group is not None or group_count is None:
        size = games_per_group if games_per_group is not None else 2
        groups = [games[i:i + size] for i in range(0, count, size)]
        if group_count is not None and len(groups) != group_count:
            raise ValueError(f"{count}款按每组{size}款应输出{len(groups)}组，与--groups {group_count}不一致；请调整参数或只指定其中一个")
    else:
        quotient, remainder = divmod(count, group_count)
        sizes = [quotient + (i < remainder) for i in range(group_count)]
        if max(sizes) > 5:
            raise ValueError("均分后单组超过5款，请增加组数")
        groups, offset = [], 0
        for size in sizes:
            groups.append(games[offset:offset + size]); offset += size
    return groups


def query_trajectory(selectors: list[str | int], kind: str = "mixed", games_per_group: int | None = None,
                     group_count: int | None = None) -> Json:
    """Return ordered, grouped chart-ready data without plotting or writing any file."""
    if kind not in ("mixed", "appid", "name"):
        raise ValueError("选择类型必须为mixed、appid或name")
    if not 1 <= len(selectors) <= 198:
        raise ValueError("请选择1～198款游戏；每组支持1～5款")
    catalog, audit = load_catalog()
    selected, seen = [], set()
    for selector in selectors:
        game = select_games(catalog, [str(selector)], kind)[0]
        if game["appid"] in seen:
            raise ValueError(f"重复选择同一游戏：{game['title']} ({game['appid']})")
        seen.add(game["appid"]); selected.append(game)
    grouped = group_games(selected, games_per_group, group_count)
    sequences = trajectory.load_sequences(catalog)
    groups = []
    for number, members in enumerate(grouped, 1):
        games = []
        for game in members:
            profile, edges = trajectory.describe_game(game, sequences[game["appid"]])
            nodes = []
            for raw in sequences[game["appid"]]:
                nodes.append({"appid": game["appid"], "local_id": raw["local_id"], "display_name": raw["display_name"],
                              "sequence_position": raw["sequence_position"], "source_checkpoint_index": raw["source_checkpoint_index"],
                              "source_checkpoint_order": int(raw["source_checkpoint_order"]), "stage": raw["stage"], "route": raw["route"],
                              "confidence": raw["confidence"], "requires_start": raw["requires_start"] == "true" if raw["requires_start"] else None,
                              "rate": raw["rate"], "normalized_rate": raw["rate"] / game["p_s"] if game["p_s"] > 0 else None,
                              "node_fraction": (raw["sequence_position"] - 1) / (game["node_count"] - 1),
                              **{key: raw[key] == "true" for key in ("is_first", "is_middle", "is_end")}})
            for edge in edges:
                edge["to_requires_start"] = edge["to_requires_start"] == "true" if edge["to_requires_start"] else None
            games.append({"appid": game["appid"], "name_en": game["title"], "name_zh": game["name_zh"],
                          "profile": profile, "nodes": nodes, "adjacent": edges})
        groups.append({"group": number, "games": games})
    sizes = [len(g["games"]) for g in groups]
    return {"version": VERSION, "source": audit,
            "selection": {"selectors": [str(s) for s in selectors], "selector_kind": kind,
                          "selected_appids": [g["appid"] for g in selected], "game_count": len(selected),
                          "requested_groups": group_count, "requested_games_per_group": games_per_group,
                          "group_count": len(groups), "group_sizes": sizes,
                          "grouping_rule": "balanced" if group_count is not None and games_per_group is None else "sequential_chunks",
                          "effective_games_per_group": None if group_count is not None and games_per_group is None else (games_per_group or 2)},
            "units": {"rate": "0_to_1", "node_fraction": "node position, not time", "coverage_gap_pp": "percentage points"},
            "groups": groups}


def draw_curves(group: Json, output: Path, total_groups: int) -> None:
    """Overlay up to five selected curves with matching game cards and original first coverage."""
    from matplotlib.ticker import PercentFormatter

    plt, style = trajectory.plotting()
    games = group["games"]
    with plt.rc_context(style):
        fig, (ax, cards) = plt.subplots(1, 2, figsize=(14.2, max(8.4, len(games) * 1.65 + 2.5)),
                                      gridspec_kw={"width_ratios": [2, 1.1]})
        cards.axis("off"); cards.set_title("所选游戏与最大相对差距", loc="left", fontsize=11, pad=14)
        for i, game in enumerate(games):
            profile, nodes = game["profile"], game["nodes"]
            color = COLORS[i]
            x, y = [n["node_fraction"] for n in nodes], [n["normalized_rate"] for n in nodes]
            if profile["p_s"] > 0:
                ax.plot(x, y, marker="o", markersize=4, linewidth=1.6, color=color)
                edge = profile["max_relative_edge_position"]
                if edge is not None:
                    ax.plot(x[edge - 1:edge + 1], y[edge - 1:edge + 1], color=color, linewidth=4)
            name = "\n".join(textwrap.wrap(f"{'ABCDE'[i]}  {game['name_zh'] or game['name_en']}", width=34, break_long_words=False))
            overall = f"{profile['overall_progress_ratio']:.1%}" if profile['overall_progress_ratio'] is not None else "缺失"
            maximum = (f"最大相对降幅{profile['max_relative_relative_drop']:.1%}（第{edge}→{edge + 1}节点）"
                       if (edge := profile["max_relative_edge_position"]) is not None else "首节点覆盖非正，相对指标留空")
            body = f"\n{profile['node_count']}节点 · 首覆盖{profile['p_s']:.1%} · 全程{overall}\n{maximum}"
            if profile["node_count"] == 2:
                body += "\n仅首末两节点，无内部过程可比较"
            cards.text(0, .97 - i / len(games), name + body, transform=cards.transAxes, va="top", fontsize=9, color=color)
        observed = [n["normalized_rate"] for g in games for n in g["nodes"] if n["normalized_rate"] is not None]
        ax.set_xlim(-.025, 1.025); ax.set_ylim(-.025, max(1.075, max(observed, default=1) * 1.08))
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0)); ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_xlabel("节点相对位置（非时间）", labelpad=10); ax.set_ylabel("相对各自首节点覆盖")
        ax.grid(color="#DFE6EC", linewidth=.7)
        fig.suptitle(f"自选游戏主线过程：第{group['group']}/{total_groups}组 · {len(games)}款完整节点曲线", fontsize=19, y=.965)
        add_footer(fig, [f"样本来源：固定198款有效主线曲线中按AppID/中英文名称选择；本组{len(games)}款，保持输入顺序，不按解锁率重排。",
                         "数据：各自首覆盖归一100%；横轴按原有效节点位置归一，不是时间或真实剧情百分比；只画原观测节点。",
                         "标记：粗线为最早最大相对降幅区间，所有并列和完整成就名称保存在JSON/CSV；两节点游戏只描述首末。",
                         "解释：手动选择不套用自动案例的同类型、至少6节点或全程相近条件；模型节点覆盖之比不等于日留存或因果。"])
        fig.subplots_adjust(left=.065, right=.985, top=.84, bottom=.25, wspace=.25)
        trajectory.save_figure(fig, output); plt.close(fig)


def draw_adjacent(group: Json, output: Path, total_groups: int) -> None:
    """Give every selected game its own adjacent-interval panel, without aligning unrelated chapters."""
    from matplotlib.ticker import PercentFormatter

    plt, style = trajectory.plotting()
    games = group["games"]
    rows, columns = (len(games), 1) if len(games) <= 2 else (math.ceil(len(games) / 2), 2)
    with plt.rc_context(style):
        fig, axes = plt.subplots(rows, columns, figsize=(15.6 if columns == 2 else 12.6, rows * 3.45 + 2.6), squeeze=False)
        for ax, game in zip(axes.flat, games):
            profile, edges = game["profile"], game["adjacent"]
            for position, edge in enumerate(edges, 1):
                value = edge["adjacent_progress_ratio"]
                if value is None:
                    ax.text(position, .03, "缺失", ha="center", rotation=90, fontsize=8)
                else:
                    ax.bar(position, value, width=.72, color=COLORS[1] if edge["is_max_relative_drop"] else COLORS[0], zorder=3)
                    if len(edges) <= 25:
                        ax.annotate(f"{value:.0%}", (position, value), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.5)
            observed = [e["adjacent_progress_ratio"] for e in edges if e["adjacent_progress_ratio"] is not None]
            ax.set_ylim(0, max(1.15, max(observed, default=1) * 1.15))
            ticks = list(range(1, len(edges) + 1, max(1, math.ceil(len(edges) / 24))))
            ax.set_xticks(ticks, [f"{p}→{p + 1}" for p in ticks], rotation=45 if len(edges) > 12 else 0, fontsize=8)
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.grid(axis="y", color="#DFE6EC", zorder=0); ax.set_axisbelow(True); ax.set_ylabel("相邻推进比", fontsize=9)
            name = "\n".join(textwrap.wrap(game['name_zh'] or game['name_en'], width=43, break_long_words=False))
            ax.set_title(f"{name}\n{profile['node_count']}节点 · {len(edges)}段真实相邻区间", loc="left", fontsize=10, pad=13)
            maximum = profile["max_relative_relative_drop"]
            note = (f"最大相对降幅{maximum:.1%}；该段原始覆盖差{profile['max_relative_coverage_gap_pp']:.2f}个百分点；并列{profile['max_relative_tie_count']}段"
                    if maximum is not None else "非正分母对应区间留空，不跨节点拼接")
            if profile["node_count"] == 2:
                note += "；仅首末，无内部比较"
            ax.set_xlabel(note, fontsize=8.5, labelpad=10)
        for ax in list(axes.flat)[len(games):]:
            ax.axis("off")
        fig.suptitle(f"自选游戏相邻推进：第{group['group']}/{total_groups}组 · 逐游戏区间与最大相对差距", fontsize=18, y=.97)
        add_footer(fig, [f"样本来源：固定198款有效主线曲线中手动选择，本组{len(games)}款；每款一个面板，不要求同类型或至少6节点。",
                         "数据：每柱一段真实相邻节点，推进比=后/前；最大相对降幅=1-推进比，百分点差=100×(前覆盖-后覆盖)。",
                         "标记：橙色包括所有并列最大相对降幅；缺失不补0、不跨节点；节点较多时简化刻度，全部柱与明细仍保留。",
                         "解释：横轴序号对应各自章节，不把不同游戏相同序号当同一阶段；聚合覆盖之比不等于条件留存或流失率。"])
        fig.subplots_adjust(left=.075, right=.98, top=.84 if rows == 1 else .88, bottom=.27 if rows == 1 else .22,
                            hspace=.82, wspace=.23)
        trajectory.save_figure(fig, output); plt.close(fig)


def previous_outputs(run_directory: Path, figure_directory: Path) -> Json:
    """Fingerprint all earlier tables and images except the exact selection being regenerated."""
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in (DEFAULT_OUTPUT, ROOT / "figures") for p in sorted(folder.rglob("*"))
            if p.is_file() and p.suffix in (".csv", ".json", ".md", ".png", ".svg")
            and not p.is_relative_to(run_directory) and not p.is_relative_to(figure_directory)
            and p != ROOT / "figures" / "README.md"}


def compare(selectors: list[str | int], kind: str = "mixed", games_per_group: int | None = None,
            group_count: int | None = None, output: str | Path = DEFAULT_SELECTION) -> Json:
    """Export one selected-data package and two PNG/SVG figures per actual group."""
    output = owned_path(output)
    reserved = (ROOT / "figures", DEFAULT_OUTPUT / "comparisons", DEFAULT_OUTPUT / "type_analysis",
                trajectory.DEFAULT_TRAJECTORY, DEFAULT_OUTPUT / "duration_analysis", DEFAULT_OUTPUT / "duration_references")
    if output in (ROOT, DEFAULT_OUTPUT) or any(output.is_relative_to(p) for p in reserved):
        raise ValueError("自选过程图须使用独立目录，不能覆盖既有分析、底表或图集")
    protected_before = protected_snapshot()
    data = query_trajectory(selectors, kind, games_per_group, group_count)
    signature = digest([[g["appid"] for g in group["games"]] for group in data["groups"]])[:12]
    run_directory = owned_path(output / signature)
    figures = owned_path(ROOT / "figures" / "trajectory_comparisons" / signature if output == DEFAULT_SELECTION else run_directory / "figures")
    prior_before = previous_outputs(run_directory, figures)
    run_directory.mkdir(parents=True, exist_ok=True); figures.mkdir(parents=True, exist_ok=True)
    nodes, profiles, edges, names = [], [], [], []
    total = data["selection"]["group_count"]
    for group in data["groups"]:
        for game in group["games"]:
            identity = {"group": group["group"], "appid": game["appid"], "name_en": game["name_en"], "name_zh": game["name_zh"]}
            nodes.extend({**identity, **node} for node in game["nodes"])
            profiles.append({**identity, **game["profile"]})
            edges.extend({**identity, **edge} for edge in game["adjacent"])
        for stem, draw in (("08_story_curves", draw_curves), ("09_adjacent_progress", draw_adjacent)):
            name = f"{stem}_g{group['group']:02}"
            draw(group, figures / name, total)
            names.extend(Path(os.path.relpath(figures / f"{name}.{ext}", run_directory)).as_posix() for ext in ("png", "svg"))
    tables = {"selected_nodes.csv": nodes, "selected_profiles.csv": profiles, "selected_adjacent.csv": edges}
    for name, rows in tables.items():
        write_text(run_directory / name, csv_text(rows), "utf-8-sig")
    write_text(run_directory / "data.json", json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    report = ["# 自选游戏主线过程对比", "", f"日期：{source.now()[:10]}。输入{data['selection']['game_count']}款，实际{total}组，每组款数：{data['selection']['group_sizes']}。",
              "按输入顺序分组；默认每组2款，显式每组款数优先且尾组保留余数，仅指定组数时尽量均分。两参数同时传入必须一致。", "",
              "手动选择不套用自动案例的同类型、至少6节点或全程相近条件。数组顺序、代表结局及全部指标沿用既有底表，缺失不补0；归一节点位置不是时间，主线推进比不是日留存。", ""]
    for group in data["groups"]:
        report += [f"## 第{group['group']}组", "", "、".join(g["name_zh"] or g["name_en"] for g in group["games"]), ""]
        for stem in ("08_story_curves", "09_adjacent_progress"):
            path = Path(os.path.relpath(figures / f"{stem}_g{group['group']:02}.png", run_directory)).as_posix()
            report += [f"![第{group['group']}组]({path})", ""]
    report += ["[前端可读取的结构化数据](data.json)、[节点](selected_nodes.csv)、[过程摘要](selected_profiles.csv)、[相邻区间](selected_adjacent.csv)、[来源与保护](manifest.json)。", ""]
    write_text(run_directory / "report.md", "\n".join(report))
    _, after_audit = load_catalog()
    protected_after = protected_snapshot()
    checks = {"same_sources": data["source"] == after_audit and protected_before == protected_after,
              "previous_outputs_unchanged": previous_outputs(run_directory, figures) == prior_before,
              "all_selected_games_once": len(profiles) == len({g["appid"] for g in profiles}) == data["selection"]["game_count"],
              "groups_have_one_to_five": all(1 <= len(g["games"]) <= 5 for g in data["groups"])}
    names += [*tables, "data.json", "report.md"]
    manifest = {"version": VERSION, "created_at": source.now(), "source": data["source"], "selection": data["selection"], "checks": checks,
                "protected_before": protected_before, "protected_after": protected_after, "previous_outputs": prior_before,
                "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    (Path(__file__), Path(trajectory.__file__), ROOT / "run.py", ROOT / "compare_games.py")},
                "outputs_path_base": "manifest directory", "outputs_sha256": {n: hashlib.sha256((run_directory / n).read_bytes()).hexdigest() for n in names}}
    write_text(run_directory / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if not all(checks.values()):
        raise RuntimeError("自选过程对比核验失败，请查看manifest")
    return {"version": VERSION, "selection": data["selection"], "checks": checks, "report": str(run_directory / "report.md"),
            "data_json": str(run_directory / "data.json"), "figures": [str((run_directory / n).resolve()) for n in names if n.endswith(".png")]}
