"""固定65款共同样本，分析主线参考耗时、平均游玩时长与主线推进。"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import textwrap
from typing import Any

from analyze_types import plotting
from compare_games import COLORS, load_catalog
from plot_files import add_footer, figure_directory
from prepare_metrics import DEFAULT_OUTPUT, ROOT, csv_text, digest, owned_path, protected_snapshot, source, write_text

VERSION = "lyx-duration-common65-v1"
DEFAULT_DURATION = DEFAULT_OUTPUT / "duration_analysis"
COHORT_SHA256 = "41aed4f5c6cfff37d0032fc3bfb3812a8d30b48e3ef0058cab7865cf90a42271"
SEED = 42
BOOTSTRAP = 2000
MIN_GROUP_INTERVAL = 10
PROGRESS = ("early_progress_ratio", "late_progress_ratio", "overall_progress_ratio")
TIME_FIELDS = ("main_hours", "playtime", "time_ratio")
LABELS = {"main_hours": "主线参考耗时（HLTB，小时）", "playtime": "平均游玩时长（RAWG，小时）",
          "time_ratio": "平均游玩时长 / 主线参考耗时",
          "early_progress_ratio": "前段推进比：中 / 首", "late_progress_ratio": "后段推进比：末 / 中",
          "overall_progress_ratio": "全程推进比：末 / 首"}
FIGURE_NAMES = ("10_time_comparison", "11_length_progress", "12_playtime_progress", "13_time_ratio")
BINS = (("≤5小时", 0.0, 5.0), (">5～15小时", 5.0, 15.0), (">15～30小时", 15.0, 30.0), (">30小时", 30.0, math.inf))
QUADRANTS = ("比值≥1，推进≥中位数", "比值≥1，推进<中位数", "比值<1，推进≥中位数", "比值<1，推进<中位数")
SOURCE_NOTE = "样本来源：198款有效主线曲线 → 183款完整三节点 → 68款正值HLTB主线时长 → 65款同时具备正值RAWG时长。"
TIME_NOTE = "时长：HLTB main_hours为主线参考耗时，RAWG playtime按研究口径作为用户平均游玩时长；单位均为小时。"
LIMIT_NOTE = "解释：游戏级跨来源比较，时长比不等于个人完成度或通关后投入；相关不作因果解释，不代表全部Steam游戏。"
Json = dict[str, Any]


def prior_artifacts() -> dict[str, str]:
    """Fingerprint earlier outputs and figures 01..09, excluding this new analysis."""
    files = [p for folder in (DEFAULT_OUTPUT / "comparisons", DEFAULT_OUTPUT / "type_analysis", DEFAULT_OUTPUT / "trajectory_analysis")
             for p in folder.rglob("*") if p.is_file()]
    files += [p for p in DEFAULT_OUTPUT.iterdir() if p.is_file()]
    files += [p for p in (ROOT / "figures").iterdir() if p.suffix in (".png", ".svg") and p.name[:2] in {f"{i:02}" for i in range(1, 10)}]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def number_status(value: Any, present: bool = True) -> str:
    """Distinguish absent rows, nulls, zero and invalid values without filling missing data."""
    if not present:
        return "not_in_local_table"
    if value is None:
        return "null"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return "invalid"
    return "positive" if value > 0 else "zero"


def load_duration_data() -> tuple[list[Json], list[Json], Json]:
    """Read two existing SQLite files without writes and freeze the agreed 65-AppID overlap."""
    catalog, audit = load_catalog()
    appids = [g["appid"] for g in catalog]
    placeholders = ",".join("?" for _ in appids)
    path = source.database_path(source.LEGACY_DB)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        times = {r["appid"]: dict(r) for r in conn.execute(
            f"SELECT t.appid,t.main_hours,t.playtime,t.extra_hours,t.completionist_hours,g.name_en FROM games_time t JOIN games g USING(appid) WHERE t.appid IN ({placeholders})", appids)}
    finally:
        conn.rollback()
        conn.close()
    with source.connect(source.DEFAULT_DB) as conn:
        payloads = {r[0]: json.loads(r[1]) for r in conn.execute(f"SELECT appid,payload FROM games WHERE appid IN ({placeholders})", appids)}
    eligible, selected = [], []
    rawg_checks = 0
    for game in catalog:
        appid = game["appid"]
        local = times.get(appid)
        rawg = payloads[appid].get("rawg")
        playtime = rawg.get("playtime") if isinstance(rawg, dict) else None
        main = local["main_hours"] if local else None
        main_status = number_status(main, local is not None)
        play_status = number_status(playtime)
        if local and local["name_en"] != game["title"]:
            raise ValueError(f"AppID={appid}名称不一致，停止而不按名称推断版本")
        # Agreement is checked where HLTB is available; source precedence is never implicit.
        if main_status == "positive" and game["three_point_available"]:
            if local["playtime"] != playtime:
                raise ValueError(f"AppID={appid}两份RAWG时长副本不一致，停止避免静默换源")
            rawg_checks += 1
        reason = ("missing_three_point" if not game["three_point_available"] else
                  "hltb_" + main_status if main_status != "positive" else
                  "rawg_" + play_status if play_status != "positive" else "included")
        order_issue = bool(local and main_status == "positive" and any(
            number_status(local[k]) == "positive" and local[k] < main for k in ("extra_hours", "completionist_hours")))
        eligible.append({"appid": appid, "title": game["title"], "three_point_available": game["three_point_available"],
                         "main_hours": main, "playtime": playtime, "hltb_status": main_status, "rawg_status": play_status,
                         "time_order_anomaly": order_issue, "exclusion_reason": reason, "included": reason == "included"})
        if reason == "included":
            selected.append({"appid": appid, "title": game["title"], "main_hours": main, "playtime": playtime,
                             "time_ratio": playtime / main, **{f: game[f] for f in ("p_s", "p_m", "p_f", *PROGRESS)},
                             "node_count": game["node_count"], "ending_type": game["ending_type"],
                             "quality_flags": game["quality_flags"], "time_order_anomaly": order_issue})
    ids = [g["appid"] for g in selected]
    if len(ids) != 65 or digest(ids) != COHORT_SHA256:
        raise ValueError("共同样本不是已确认的65款，请先核对来源，不自动换样本")
    if any(g[f] is None for g in selected for f in PROGRESS):
        raise ValueError("65款中存在缺失阶段指标")
    counts = {"fixed_games": len(catalog), "three_point": sum(g["three_point_available"] for g in catalog),
              "hltb_positive_all": sum(r["hltb_status"] == "positive" for r in eligible),
              "hltb_positive_three_point": rawg_checks, "common_games": len(selected),
              "hltb_status_all": dict(Counter(r["hltb_status"] for r in eligible)),
              "exclusion_reasons": dict(Counter(r["exclusion_reason"] for r in eligible)),
              "time_order_anomalies_in_65": sum(g["time_order_anomaly"] for g in selected)}
    return selected, eligible, {**audit, "cohort_sha256_65": COHORT_SHA256, "selected_appids": ids, "counts": counts,
                              "hltb_source": "local games_time.main_hours; copied by AppID on 2026-10-15",
                              "rawg_source": "borrowed games.payload.rawg.playtime; agrees with local games_time.playtime on all 68 HLTB-positive three-point games",
                              "legacy_database_sha256": source.fingerprint(path)["sha256"], "unit": "hours"}


def correlation_statistics(games: list[Json]) -> list[Json]:
    """Compute tie-aware Spearman and paired-game percentile-bootstrap intervals without p-value selection."""
    import numpy as np
    from scipy.stats import rankdata

    fields = [*TIME_FIELDS, *PROGRESS]
    matrix = np.array([[g[f] for f in fields] for g in games], dtype=float)
    ranks = rankdata(matrix, axis=0)
    centered = ranks - ranks.mean(axis=0)
    rng = np.random.default_rng(SEED)
    indexes = rng.integers(0, len(games), size=(BOOTSTRAP, len(games)))
    sampled_ranks = rankdata(matrix[indexes], axis=1)
    sampled_centered = sampled_ranks - sampled_ranks.mean(axis=1, keepdims=True)
    pairs = [(x, y) for x in TIME_FIELDS for y in PROGRESS] + [("main_hours", "playtime")]
    rows = []
    for x, y in pairs:
        i, j = fields.index(x), fields.index(y)
        denominator = float(np.sqrt(np.sum(centered[:, i] ** 2) * np.sum(centered[:, j] ** 2)))
        rho = float(np.sum(centered[:, i] * centered[:, j]) / denominator) if denominator > 0 else None
        a, b = sampled_centered[:, :, i], sampled_centered[:, :, j]
        denom = np.sqrt(np.sum(a * a, axis=1) * np.sum(b * b, axis=1))
        samples = np.divide(np.sum(a * b, axis=1), denom, out=np.full(BOOTSTRAP, np.nan), where=denom > 0)
        valid = samples[np.isfinite(samples)]
        lo, hi = [float(v) for v in np.quantile(valid, [0.025, 0.975])] if rho is not None and len(valid) else [None, None]
        rows.append({"x": x, "y": y, "n": len(games), "x_unique_values": len(set(g[x] for g in games)),
                     "y_unique_values": len(set(g[y] for g in games)), "spearman": rho,
                     "interval_low": lo, "interval_high": hi, "valid_bootstrap_replicates": len(valid),
                     "requested_bootstrap_replicates": BOOTSTRAP, "random_state": SEED})
    return rows


def group_statistics(games: list[Json]) -> list[Json]:
    """Summarize fixed HLTB intervals; only n>=10 receives game-level median intervals."""
    import numpy as np

    result = []
    for label, lower, upper in BINS:
        members = [g for g in games if lower < g["main_hours"] <= upper]
        matrix = np.array([[g[f] for f in PROGRESS] for g in members], dtype=float)
        bootstrap = None
        if len(members) >= MIN_GROUP_INTERVAL:
            offset = int(digest(label)[:8], 16)
            rng = np.random.default_rng(np.random.SeedSequence([SEED, offset]))
            bootstrap = np.median(matrix[rng.integers(0, len(members), size=(BOOTSTRAP, len(members)))], axis=1)
        for i, field in enumerate(PROGRESS):
            values = matrix[:, i] if len(members) else []
            q1, median, q3 = [float(v) for v in np.quantile(values, [.25, .5, .75])] if len(values) else [None] * 3
            lo, hi = [float(v) for v in np.quantile(bootstrap[:, i], [.025, .975])] if bootstrap is not None else [None, None]
            result.append({"hours_group": label, "lower_exclusive": lower, "upper_inclusive": upper if math.isfinite(upper) else None,
                           "metric": field, "n": len(members), "median": median, "q1": q1, "q3": q3,
                           "interval_low": lo, "interval_high": hi, "bootstrap_replicates": BOOTSTRAP if bootstrap is not None else 0})
    return result


def variable_summary(games: list[Json]) -> list[Json]:
    """Describe game-level time and progression distributions without player weighting."""
    import numpy as np

    rows = []
    for f in (*TIME_FIELDS, *PROGRESS):
        values = [g[f] for g in games]
        q1, median, q3 = [float(v) for v in np.quantile(values, [.25, .5, .75])]
        rows.append({"field": f, "n": len(values), "minimum": min(values), "q1": q1, "median": median, "q3": q3,
                     "maximum": max(values), "unique_values": len(set(values))})
    return rows


def choose_cases(games: list[Json]) -> tuple[list[Json], float]:
    """Select one transparent extreme per ratio/progress quadrant, without type comparisons."""
    import statistics

    median = statistics.median(g["overall_progress_ratio"] for g in games)
    result = []
    for i, label in enumerate(QUADRANTS):
        ratio_high, progress_high = i < 2, i % 2 == 0
        group = [g for g in games if (g["time_ratio"] >= 1) == ratio_high
                 and (g["overall_progress_ratio"] >= median) == progress_high]
        if not group:
            continue
        ordered = sorted(group, key=lambda g: (-abs(math.log2(g["time_ratio"])), -abs(g["overall_progress_ratio"] - median), g["appid"]))
        result.append({"case": chr(65 + len(result)), "quadrant": label, "quadrant_games": len(group),
                       "overall_median_reference": median, **ordered[0]})
    return result, median


def save_figure(fig: Any, path: Path) -> None:
    """Export a PNG/SVG pair under the owned figure directory."""
    fig.savefig(owned_path(path.with_suffix(".png")), dpi=180)
    fig.savefig(owned_path(path.with_suffix(".svg")), metadata={"Date": None})


def correlation_label(row: Json) -> str:
    """Format correlation and uncertainty with explicit unavailable handling."""
    if row["spearman"] is None:
        return f"n={row['n']} · Spearman不可计算（变量恒定）"
    return f"n={row['n']} · Spearman ρ={row['spearman']:+.3f}\n95%重采样区间 [{row['interval_low']:+.3f}, {row['interval_high']:+.3f}]"


def draw_time_comparison(games: list[Json], stats: list[Json], output: Path) -> None:
    """Compare two hour measures with an equal-time reference and progression color scale."""
    from matplotlib.ticker import PercentFormatter

    plt, style = plotting()
    row = next(r for r in stats if r["x"] == "main_hours" and r["y"] == "playtime")
    with plt.rc_context(style):
        fig, ax = plt.subplots(figsize=(11.7, 8.1))
        dots = ax.scatter([g["main_hours"] for g in games], [g["playtime"] for g in games],
                          c=[g["overall_progress_ratio"] for g in games], cmap="viridis", vmin=0, vmax=1,
                          s=62, alpha=.85, linewidths=.5, edgecolors="white", zorder=3)
        maximum = max(max(g["main_hours"], g["playtime"]) for g in games) * 1.08
        ax.plot([0, maximum], [0, maximum], color="#697C89", linestyle="--", linewidth=1.2, label="两类时长相等参考线")
        ax.set_xlim(0, maximum); ax.set_ylim(0, maximum)
        ax.set_xlabel(LABELS["main_hours"]); ax.set_ylabel(LABELS["playtime"])
        ax.grid(color="#E0E7EC", linewidth=.7); ax.set_axisbelow(True)
        ax.text(.035, .96, correlation_label(row), transform=ax.transAxes, va="top", fontsize=10,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85})
        ax.legend(loc="upper center", frameon=False, fontsize=10)
        colorbar = fig.colorbar(dots, ax=ax, fraction=.04, pad=.035)
        colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        colorbar.set_label("全程推进比（末 / 首）", labelpad=12)
        fig.suptitle("65款游戏：主线参考耗时与平均游玩时长对照", fontsize=20, y=.965)
        add_footer(fig, [SOURCE_NOTE, TIME_NOTE,
                   "数据：每点一款游戏，颜色为全程推进比；虚线为两类时长相等的位置，不是通关或留存阈值。", LIMIT_NOTE])
        fig.subplots_adjust(left=.09, right=.87, top=.87, bottom=.24)
        save_figure(fig, output / FIGURE_NAMES[0]); plt.close(fig)


def draw_progress(games: list[Json], stats: list[Json], output: Path, xfield: str) -> None:
    """Draw the same 65-game cohort against each of the three existing progression ratios."""
    from matplotlib.ticker import PercentFormatter

    plt, style = plotting()
    lookup = {(r["x"], r["y"]): r for r in stats}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 3, figsize=(15.6, 7.4), sharey=True)
        for ax, field in zip(axes, PROGRESS):
            ax.scatter([g[xfield] for g in games], [g[field] for g in games], s=39, alpha=.70,
                       color=COLORS[0], edgecolors="white", linewidths=.4, zorder=3)
            ax.set_xlim(0, max(g[xfield] for g in games) * 1.08); ax.set_ylim(-.025, 1.10)
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.set_xlabel(LABELS[xfield], fontsize=10, labelpad=12)
            ax.set_title(LABELS[field], fontsize=13, loc="left", pad=15)
            ax.text(.035, .96, correlation_label(lookup[xfield, field]), transform=ax.transAxes, va="top", fontsize=9,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85})
            ax.grid(color="#E0E7EC", linewidth=.7); ax.set_axisbelow(True)
        axes[0].set_ylabel("阶段推进比")
        subject = "主线参考耗时" if xfield == "main_hours" else "平均游玩时长"
        fig.suptitle(f"同一65款游戏：{subject}与前段、后段、全程推进", fontsize=20, y=.965)
        add_footer(fig, [SOURCE_NOTE, TIME_NOTE,
                   "统计：每点一款游戏；前/后/全程依次为中/首、末/中、末/首；Spearman并列取平均秩，游戏级Bootstrap 2000次、种子42。", LIMIT_NOTE])
        fig.subplots_adjust(left=.065, right=.985, top=.83, bottom=.25, wspace=.15)
        save_figure(fig, output / FIGURE_NAMES[1 if xfield == "main_hours" else 2]); plt.close(fig)


def draw_ratio(games: list[Json], stats: list[Json], cases: list[Json], median: float, output: Path) -> None:
    """Show a descriptive time ratio, median reference and auditable exploratory cases."""
    from matplotlib.ticker import PercentFormatter

    plt, style = plotting()
    row = next(r for r in stats if r["x"] == "time_ratio" and r["y"] == "overall_progress_ratio")
    with plt.rc_context(style):
        fig, (ax, cards) = plt.subplots(1, 2, figsize=(14.2, 8.6), gridspec_kw={"width_ratios": [2.25, 1]})
        for high, color, label in ((False, COLORS[0], "时长比<1"), (True, COLORS[1], "时长比≥1")):
            members = [g for g in games if (g["time_ratio"] >= 1) == high]
            ax.scatter([g["time_ratio"] for g in members], [g["overall_progress_ratio"] for g in members],
                       color=color, label=f"{label}（{len(members)}款）", s=48, alpha=.75, edgecolors="white", linewidths=.4, zorder=3)
        ax.axvline(1, color="#7B8790", linestyle="--", linewidth=1)
        ax.axhline(median, color="#7B8790", linestyle=":", linewidth=1)
        ax.set_xlim(0, max(1.2, max(g["time_ratio"] for g in games) * 1.10)); ax.set_ylim(-.025, 1.10)
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_xlabel("平均游玩时长 / 主线参考耗时（倍）", labelpad=12); ax.set_ylabel(LABELS["overall_progress_ratio"])
        ax.grid(color="#E0E7EC", linewidth=.7); ax.set_axisbelow(True)
        ax.text(.03, .965, correlation_label(row), transform=ax.transAxes, va="top", fontsize=9,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85})
        ax.legend(loc="upper right", fontsize=9, frameon=False)
        cards.axis("off"); cards.set_title("探索性案例（按固定规则选择）", loc="left", fontsize=11, pad=14)
        for i, case in enumerate(cases):
            ax.annotate(case["case"], (case["time_ratio"], case["overall_progress_ratio"]), xytext=(6, 5),
                        textcoords="offset points", fontsize=11, color="#273F50")
            title = "\n".join(textwrap.wrap(f"{case['case']}  {case['title']}", width=32, break_long_words=False))
            body = (f"\nRAWG {case['playtime']:g}h / HLTB {case['main_hours']:g}h\n时长比{case['time_ratio']:.2f}倍 · 全程{case['overall_progress_ratio']:.1%}"
                    f"\n{case['quadrant']}（{case['quadrant_games']}款）")
            cards.text(0, .97 - i * .245, title + body, transform=cards.transAxes, va="top", fontsize=9)
        fig.suptitle("同一65款游戏：平均游玩时长与主线参考耗时之比，及全程推进", fontsize=18, y=.965)
        add_footer(fig, [SOURCE_NOTE, TIME_NOTE,
                   "数据：R=RAWG/HLTB，虚线R=1；横点线为全程比样本中位数；每象限取|log2(R)|最大案例，同分按推进偏离和AppID排序。", LIMIT_NOTE])
        fig.subplots_adjust(left=.07, right=.985, top=.84, bottom=.25, wspace=.24)
        save_figure(fig, output / FIGURE_NAMES[3]); plt.close(fig)


def report_text(games: list[Json], eligibility: list[Json], stats: list[Json], groups: list[Json], summary: list[Json], cases: list[Json],
                audit: Json, output: Path, figures: Path) -> str:
    """Report game-level evidence with fixed sample, canceled type contrasts and source limits."""
    values = {r["field"]: r for r in summary}
    counts = audit["counts"]
    lines = ["# 专题4：内容长度、平均游玩时长与主线推进", "", "实施日期：2026-10-16。",
             f"主线快照版本：{audit['dataset_version']}。共同样本65款，AppID顺序指纹：{COHORT_SHA256}。", "",
             "## 固定样本与来源", "",
             "采用用户确认口径：RAWG playtime为用户平均游玩时长（小时），HLTB main_hours为主线参考耗时（小时）。二者独立保留，不互相填缺失；主线指标仍使用既有数组位置中位节点和代表结局。",
             "不开展类型对照、类型分组、类型着色或按类型拟合。全部主图使用同一65款，不把不同有效集合混为一条阶段过程。",
             "| 筛选步骤 | 游戏数 |", "|---|---:|",
             f"| 固定有效主线范围 | {counts['fixed_games']} |", f"| 完整三节点 | {counts['three_point']} |",
             f"| 其中正值HLTB主线时长 | {counts['hltb_positive_three_point']} |", f"| 再与正值RAWG时长取交集 | {len(games)} |", "",
             "全部198款中，HLTB主线时长正值75款、本地未匹配37款、NULL85款、零值1款；本地未匹配不代表HLTB网站没有该游戏。",
             "三节点且正值HLTB的68款中，3款RAWG缺失：God of War、Call of Duty®: Black Ops II、Resident Evil。其余65款为固定共同样本。RAWG以借用快照为源，68款的值与旧库playtime逐项一致；HLTB只读旧本地快照，不合并或修改数据库。", "",
             "## 输入分布与时长比", "", "| 变量 | n | 最小 | 中位数 | 最大 |", "|---|---:|---:|---:|---:|"]
    for f in TIME_FIELDS:
        r = values[f]
        lines.append(f"| {LABELS[f]} | {r['n']} | {r['minimum']:.2f} | {r['median']:.2f} | {r['maximum']:.2f} |")
    lines += ["", f"时长比R=playtime/main_hours；R<1有{sum(g['time_ratio'] < 1 for g in games)}款，R>=1有{sum(g['time_ratio'] >= 1 for g in games)}款。",
              "R=0.6只表示RAWG平均值为HLTB参考值的60%，不是个人完成了60%主线；R>1也不能据此认定通关后继续游玩。", "",
              "## 关联分析", "",
              "每款游戏同等权重，Spearman并列值取平均秩。以整行游戏联合重采样2000次、随机种子42，报告2.5/97.5百分位区间；常量重采样不可计算时剔除并记录有效次数。未用p值挑选结论，也未拟合复杂趋势或搜索时间门槛。",
              "| 时长变量 | 对照指标 | n | Spearman ρ | 95%游戏重采样区间 |", "|---|---|---:|---:|---|"]
    for r in stats:
        rho = f"{r['spearman']:+.3f}" if r['spearman'] is not None else "不可计算"
        interval = f"[{r['interval_low']:+.3f}, {r['interval_high']:+.3f}]" if r['interval_low'] is not None else "不可计算"
        lines.append(f"| {LABELS[r['x']]} | {LABELS[r['y']]} | {r['n']} | {rho} | {interval} |")
    lines += ["", "区间表示当前65款游戏的重采样波动，不是Steam玩家级误差或总体随机抽样保证。相关方向与大小分别说明，不凭区间重叠认定两种相关系数不同。", "",
              "## HLTB主线长度分组（仍为相同65款）", "", "| 参考耗时 | n | 前段中位数 | 后段中位数 | 全程中位数 |", "|---|---:|---:|---:|---:|"]
    for label, _, _ in BINS:
        rows = [r for r in groups if r["hours_group"] == label]
        lines.append(f"| {label} | {rows[0]['n']} | " + " | ".join(f"{r['median']:.1%}" if r['median'] is not None else "缺失" for r in rows) + " |")
    lines += ["", "组内先计算每款游戏指标再取中位数；四分位使用线性插值。n>=10才提供中位数Bootstrap区间，>30小时组7款只报告分布；分组不是根据结果寻找的最优切点。", "",
              "## 观察与可复查案例", ""]
    for field in TIME_FIELDS:
        r = next(r for r in stats if r["x"] == field and r["y"] == "overall_progress_ratio")
        if r["spearman"] is not None:
            lines.append(f"- {LABELS[field]}与全程推进比：ρ={r['spearman']:+.3f}，重采样区间[{r['interval_low']:+.3f}, {r['interval_high']:+.3f}]。这是一项游戏级关联，不作因果归因。")
    lines += ["", "案例以R=1和65款全程比中位数划分四象限；每象限按|log2(R)|降序、全程比偏离中位数距离降序、AppID升序取一款。属于刻意选择的探索性极端案例，不能代表各象限的典型游戏；无样本时不调整阈值补齐。", ""]
    for c in cases:
        lines.append(f"- {c['case']} {c['title']}：HLTB {c['main_hours']:g}h，RAWG {c['playtime']:g}h，R={c['time_ratio']:.2f}，全程{c['overall_progress_ratio']:.1%}；{c['quadrant']}。")
    lines += ["", "平均玩得更久与主线推进更深是不同观测维度。重复游玩、支线或其他活动只能作为后续待核验解释，不能凭时长比值直接确认。比值含HLTB分母，始终同时展示两种原始时长的关联，避免仅依据派生比值作结论。", "", "## 四张图", ""]
    for stem, title in zip(FIGURE_NAMES, ("两类时长对照", "主线参考耗时与推进", "平均游玩时长与推进", "时长比与全程推进")):
        path = Path(os.path.relpath(figures / (stem + ".png"), output)).as_posix()
        lines += [f"![{title}]({path})", ""]
    lines += ["## 明细与边界", "",
              "[65款底表](duration_cohort.csv)、[198款筛选记录](duration_eligibility.csv)、[变量分布](duration_summary.csv)、[相关与区间](time_correlations.csv)、[时长分组](duration_groups.csv)、[案例](duration_cases.csv)、[来源与保护核验](manifest.json)。",
              "这65款来自既有冻结游戏的有效交集，样本覆盖不完整；两类时长和成就统计的来源口径不同，不宣称是同一批玩家的时长与轨迹。RAWG是整数小时，保留并列值，不抖动数据用于统计。",
              "阶段推进是聚合节点覆盖之比，不是日留存、流失率或个人完成度；节点跨度、首节点和代表结局含义仍有差异。本轮未控制其他游戏属性，不把时长关联解释为内容长度造成了流失。",
              "两份数据库、T0Pre、旧底表与01～09图保持只读/不变，无新采集、模型调用或数据库写入。RAWG来源：[RAWG](https://rawg.io/)。", ""]
    return "\n".join(lines)


def analyze(output: str | Path = DEFAULT_DURATION) -> Json:
    """Build the fixed 65-game duration analysis while protecting all existing results."""
    output = owned_path(output)
    old = (ROOT / "figures", DEFAULT_OUTPUT / "comparisons", DEFAULT_OUTPUT / "type_analysis", DEFAULT_OUTPUT / "trajectory_analysis")
    if output in (ROOT, DEFAULT_OUTPUT) or any(output.is_relative_to(p) for p in old):
        raise ValueError("时长分析须使用独立目录，不能覆盖旧底表、分析结果或图集目录")
    protected_before, prior_before = protected_snapshot(), prior_artifacts()
    games, eligibility, audit = load_duration_data()
    stats, groups, summary = correlation_statistics(games), group_statistics(games), variable_summary(games)
    cases, median = choose_cases(games)
    checks = {"fixed_65_appids": len(games) == 65 and digest([g['appid'] for g in games]) == COHORT_SHA256,
              "eligibility_198": len(eligibility) == 198, "all_three_ratios_available": all(g[f] is not None for g in games for f in PROGRESS),
              "positive_finite_times": all(number_status(g[f]) == "positive" for g in games for f in TIME_FIELDS),
              "every_correlation_uses_65": all(r['n'] == 65 for r in stats),
              "fixed_bin_counts": [r['n'] for r in groups if r['metric'] == PROGRESS[0]] == [10, 30, 18, 7],
              "small_groups_no_interval": all(r['interval_low'] is None for r in groups if r['n'] < MIN_GROUP_INTERVAL)}
    if not all(checks.values()):
        raise ValueError(f"时长计算核验失败：{checks}")
    output.mkdir(parents=True, exist_ok=True)
    tables = {"duration_cohort.csv": games, "duration_eligibility.csv": eligibility, "duration_summary.csv": summary,
              "time_correlations.csv": stats, "duration_groups.csv": groups, "duration_cases.csv": cases}
    for name, rows in tables.items():
        write_text(output / name, csv_text(rows), "utf-8-sig")
    figures = figure_directory(output, DEFAULT_DURATION); figures.mkdir(parents=True, exist_ok=True)
    draw_time_comparison(games, stats, figures)
    draw_progress(games, stats, figures, "main_hours")
    draw_progress(games, stats, figures, "playtime")
    draw_ratio(games, stats, cases, median, figures)
    write_text(output / "report.md", report_text(games, eligibility, stats, groups, summary, cases, audit, output, figures))
    _, _, after_audit = load_duration_data()
    protected_after, prior_after = protected_snapshot(), prior_artifacts()
    checks['inputs_unchanged'] = audit == after_audit and protected_before == protected_after
    checks['previous_outputs_and_figures_unchanged'] = prior_before == prior_after
    names = [*tables, "report.md"] + [Path(os.path.relpath(figures / f"{stem}.{ext}", output)).as_posix() for stem in FIGURE_NAMES for ext in ("png", "svg")]
    manifest = {"created_at": source.now(), "version": VERSION, "source": audit, "counts": audit['counts'], "checks": checks,
                "parameters": {"random_state": SEED, "bootstrap_iterations": BOOTSTRAP, "bootstrap_unit": "paired game rows; all variables together",
                               "correlation": "Spearman; average ranks for ties; percentile intervals", "minimum_group_interval_n": MIN_GROUP_INTERVAL,
                               "hltb_bins": [{"label": label, "lower_exclusive": lo, "upper_inclusive": hi if math.isfinite(hi) else None} for label, lo, hi in BINS],
                               "case_rule": "R>=1/<1 and overall>=median/<median; abs(log2(R)) desc, progress deviation desc, appid asc",
                               "overall_median_for_cases": median, "type_comparisons": False, "data_unit": "hours"},
                "protected_before": protected_before, "protected_after": protected_after,
                "prior_artifacts_before": prior_before, "prior_artifacts_after": prior_after,
                "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                    (Path(__file__).name, "run.py", "plot_files.py", "prepare_metrics.py", "compare_games.py", "analyze_types.py")},
                "outputs_path_base": "manifest directory", "outputs_sha256": {n: hashlib.sha256((output / n).read_bytes()).hexdigest() for n in names}}
    write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if not all(checks.values()):
        raise RuntimeError("时长分析期间输入或旧结果改变，请核对manifest")
    return {"version": VERSION, "counts": audit['counts'], "checks": checks,
            "overall_correlations": [r for r in stats if r['y'] == 'overall_progress_ratio'],
            "report": str(output / 'report.md'), "figures": [str(figures / (s + '.png')) for s in FIGURE_NAMES]}
