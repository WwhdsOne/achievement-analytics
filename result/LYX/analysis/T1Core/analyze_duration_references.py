"""沿用13号图，为同69款游戏补充主线＋支线与全收集耗时比对照。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import textwrap
from typing import Any

import analyze_duration as base
from plot_files import add_footer, figure_directory
from prepare_metrics import ROOT, DEFAULT_OUTPUT, csv_text, digest, owned_path, protected_snapshot, write_text

VERSION = "lyx-duration-references-common69-manual-v2"
DEFAULT_REFERENCES = DEFAULT_OUTPUT / "duration_references"
REFERENCES = (
    ("extra_hours", "主线＋支线", "14_extra_time_ratio"),
    ("completionist_hours", "全收集", "15_completionist_time_ratio"),
)
Json = dict[str, Any]


def previous_files(excluded: Path = DEFAULT_REFERENCES) -> dict[str, str]:
    """Protect all existing result tables and figures 01..13, without hashing editable docs."""
    paths = [p for p in DEFAULT_OUTPUT.rglob("*") if p.is_file()
             and not p.is_relative_to(DEFAULT_REFERENCES) and not p.is_relative_to(excluded)]
    paths += [p for p in (ROOT / "figures").iterdir()
              if p.suffix in (".png", ".svg") and p.name[:2] in {f"{i:02}" for i in range(1, 14)}]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def load_reference_data() -> tuple[list[Json], Json]:
    """Verify the original 69-game analysis and read two extra HLTB fields without writes."""
    manifest_path = base.DEFAULT_DURATION / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not all(manifest["checks"].values()):
        raise ValueError("原时长分析未通过核验，不生成补充图")
    for name, expected in manifest["outputs_sha256"].items():
        path = owned_path(base.DEFAULT_DURATION / name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"原时长产物已改变：{name}")
    games, _, audit = base.load_duration_data()
    if audit != manifest["source"]:
        raise ValueError("来源与13号图的69款快照不同，请先核对，不静默替换")
    path = base.source.database_path(base.source.LEGACY_DB)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        appids = [g["appid"] for g in games]
        placeholders = ",".join("?" for _ in appids)
        times = {r["appid"]: dict(r) for r in conn.execute(
            f"SELECT appid,extra_hours,completionist_hours FROM games_time WHERE appid IN ({placeholders})", appids)}
    finally:
        conn.rollback()
        conn.close()
    supplements, _ = base.load_supplements(games)
    rows = []
    for game in games:
        row = dict(game)
        for field, _, _ in REFERENCES:
            value = base.resolve_value(game["appid"], field, times.get(game["appid"], {}).get(field), supplements)
            if base.number_status(value) != "positive":
                raise ValueError(f"AppID={game['appid']} {field}不是正值，停止避免缩小69款范围")
            row[field] = value
            row[field + "_source"] = base.value_source(game["appid"], field, supplements)
            row[field + "_ratio"] = game["playtime"] / value
        row["reference_order_anomaly"] = not (row["main_hours"] <= row["extra_hours"] <= row["completionist_hours"])
        rows.append(row)
    if len(rows) != base.COHORT_SIZE or digest([g["appid"] for g in rows]) != base.COHORT_SHA256:
        raise ValueError("补充图范围不再是原69款")
    return rows, {"base_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  "base_source": audit, "reference_source": "local games_time.extra_hours/completionist_hours plus explicit manual HLTB supplements",
                  "unit": "hours", "reference_order_anomalies": sum(g["reference_order_anomaly"] for g in rows)}


def reference_statistics(games: list[Json], field: str) -> tuple[Json, list[Json], float]:
    """Reuse figure 13's bootstrap and case rules with only the ratio denominator replaced."""
    adapted = [{**g, "time_ratio": g[field + "_ratio"]} for g in games]
    row = next(r for r in base.correlation_statistics(adapted)
               if r["x"] == "time_ratio" and r["y"] == "overall_progress_ratio")
    cases, median = base.choose_cases(adapted)
    return {**row, "x": "playtime/" + field, "reference_field": field,
            "ratio_below_one": sum(g["time_ratio"] < 1 for g in adapted),
            "ratio_at_least_one": sum(g["time_ratio"] >= 1 for g in adapted)}, cases, median


def draw_reference(games: list[Json], field: str, label: str, stem: str, stats: Json,
                   cases: list[Json], median: float, output: Path) -> None:
    """Render the same ratio/progression layout with correctly named reference hours and cases."""
    from matplotlib.ticker import PercentFormatter

    plt, style = base.plotting()
    ratio_field = field + "_ratio"
    with plt.rc_context(style):
        fig, (ax, cards) = plt.subplots(1, 2, figsize=(14.2, 8.6), gridspec_kw={"width_ratios": [2.25, 1]})
        for high, color, name in ((False, base.COLORS[0], "时长比<1"), (True, base.COLORS[1], "时长比≥1")):
            members = [g for g in games if (g[ratio_field] >= 1) == high]
            ax.scatter([g[ratio_field] for g in members], [g["overall_progress_ratio"] for g in members],
                       color=color, label=f"{name}（{len(members)}款）", s=48, alpha=.75,
                       edgecolors="white", linewidths=.4, zorder=3)
        ax.axvline(1, color="#7B8790", linestyle="--", linewidth=1)
        ax.axhline(median, color="#7B8790", linestyle=":", linewidth=1)
        ax.set_xlim(0, max(1.2, max(g[ratio_field] for g in games) * 1.10)); ax.set_ylim(-.025, 1.10)
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_xlabel(f"平均游玩时长 / {label}参考耗时（倍）", labelpad=12)
        ax.set_ylabel(base.LABELS["overall_progress_ratio"])
        ax.grid(color="#E0E7EC", linewidth=.7); ax.set_axisbelow(True)
        ax.text(.03, .965, base.correlation_label(stats), transform=ax.transAxes, va="top", fontsize=9,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85})
        ax.legend(loc="upper right", fontsize=9, frameon=False)
        cards.axis("off"); cards.set_title("探索性案例（按13号图规则选择）", loc="left", fontsize=11, pad=14)
        for i, case in enumerate(cases):
            ax.annotate(case["case"], (case["time_ratio"], case["overall_progress_ratio"]), xytext=(6, 5),
                        textcoords="offset points", fontsize=11, color="#273F50")
            title = "\n".join(textwrap.wrap(f"{case['case']}  {case['title']}", width=32, break_long_words=False))
            body = (f"\nRAWG {case['playtime']:g}h / HLTB {case[field]:g}h\n时长比{case['time_ratio']:.3f}倍 · 全程{case['overall_progress_ratio']:.1%}"
                    f"\n{case['quadrant']}（{case['quadrant_games']}款）")
            cards.text(0, .97 - i * .245, title + body, transform=cards.transAxes, va="top", fontsize=9)
        empty = [q for q in base.QUADRANTS if q not in {c["quadrant"] for c in cases}]
        if empty:
            cards.text(0, .97 - len(cases) * .245, "空象限（0款，不选案例）：\n" + "\n".join(empty),
                       transform=cards.transAxes, va="top", fontsize=9, color="#58636B")
        fig.suptitle(f"同一69款游戏：平均游玩时长与{label}参考耗时之比，及全程推进", fontsize=18, y=.965)
        note = (f"时长：RAWG playtime为平均游玩时长；HLTB {field}为{label}参考耗时；单位小时，未作玩家匹配。")
        definition = ("主线＋支线对应Main + Extras，含额外内容；" if field == "extra_hours" else
                      "全收集对应Completionist完整游玩参考，不等于Steam全成就；")
        add_footer(fig, ["样本来源：沿用13号图的固定69款游戏，两类新增HLTB参考耗时均69款正值，未重新选样。",
                         note,
                         "统计：R=RAWG/本图HLTB；全程=末/首；Spearman与游戏级Bootstrap 2000次、种子42；案例沿用四象限规则。",
                         definition + "R=1及全程样本中位数仅作参考；时长比非个人完成度，关联不作因果解释。"])
        fig.subplots_adjust(left=.07, right=.985, top=.84, bottom=.25, wspace=.24)
        base.save_figure(fig, output / stem); plt.close(fig)


def analyze(output: str | Path = DEFAULT_REFERENCES) -> Json:
    """Generate figures 14/15 and separate provenance without overwriting the first analysis."""
    output = owned_path(output)
    old_directories = (ROOT / "figures", DEFAULT_OUTPUT / "comparisons", DEFAULT_OUTPUT / "type_analysis",
                       DEFAULT_OUTPUT / "trajectory_analysis", base.DEFAULT_DURATION)
    if output in (ROOT, DEFAULT_OUTPUT) or any(output.is_relative_to(p) for p in old_directories):
        raise ValueError("补充图须使用独立目录，不能覆盖旧分析、底表或图集")
    protected_before, previous_before = protected_snapshot(), previous_files(output)
    games, audit = load_reference_data()
    statistics, case_rows = [], []
    output.mkdir(parents=True, exist_ok=True)
    figures = figure_directory(output, DEFAULT_REFERENCES); figures.mkdir(parents=True, exist_ok=True)
    report = ["# 专题4补充：主线＋支线与全收集参考耗时", "", "更新：2026-10-20。原65款加4款人工补充。",
              "沿用13号图的固定69款与全程推进比，两个参考耗时均69款正值；不更换样本、不开展类型对照。",
              "RAWG playtime按已授权口径作为平均游玩时长；extra_hours是HLTB Main + Extras（主线＋额外内容），completionist_hours是Completionist完整游玩参考，不等于Steam全成就耗时。单位均为小时。", "",
              "| HLTB参考口径 | n | R<1 | R>=1 | Spearman ρ | 95%游戏重采样区间 |", "|---|---:|---:|---:|---:|---|"]
    for field, label, stem in REFERENCES:
        stats, cases, median = reference_statistics(games, field)
        statistics.append(stats)
        case_rows.extend({**c, "reference_field": field, "reference_hours": c[field]} for c in cases)
        draw_reference(games, field, label, stem, stats, cases, median, figures)
        interval = f"[{stats['interval_low']:+.3f}, {stats['interval_high']:+.3f}]"
        report.append(f"| {label} | {len(games)} | {stats['ratio_below_one']} | {stats['ratio_at_least_one']} | {stats['spearman']:+.3f} | {interval} |")
    report += ["", "## 图与规则", "",
               "两图横轴分别为playtime/extra_hours、playtime/completionist_hours，纵轴均为原全程推进比p_f/p_s；三图13～15的游戏顺序、推进值、参考横线相同。每款等权，平均秩处理并列；整行游戏Bootstrap 2000次、种子42，95%百分位区间，不按p值筛选。",
               "案例沿用13号图：R=1与全程比中位数划四象限，各取|log2(R)|最大者，再按推进偏离和AppID排序；空象限不补齐，不改变阈值。案例是探索性极端值，不能代表典型游戏。", ""]
    for _, label, stem in REFERENCES:
        relative = Path(os.path.relpath(figures / (stem + ".png"), output)).as_posix()
        report += [f"![{label}时长比与推进]({relative})", ""]
    report += ["## 来源与边界", "",
               "数据分别来自借用快照的RAWG playtime与旧本地库games_time的两个HLTB字段，并叠加用户确认的人工查询值；原库只读按AppID关联；沿用时长分析的快照及补充文件指纹并校验01～13图及原分析产物未变。",
               f"主线≤主线＋支线≤全收集的顺序异常：{audit['reference_order_anomalies']}款；异常只标记，不截断或改值。",
               "R是跨来源游戏级对照，不代表个人完成比例、支线参与率或全收集率；纵轴仍为主线推进，不是支线/全收集完成率。R>=1不能确认完成了相应内容。不同分母改变相关强度，不能直接说明哪类内容造成粘性变化。",
               "[69款底表](reference_cohort.csv)、[相关与区间](reference_correlations.csv)、[案例与选样](reference_cases.csv)、[来源与保护核验](manifest.json)。原01～13图、两份数据库、其他分析结果和依赖文件不变；无采集或模型调用。RAWG来源：[RAWG](https://rawg.io/)。", ""]
    lookup = {g["appid"]: g for g in games}
    preferred = [lookup[appid] for appid in (367520, 812140, 1903340, 1593500, 1245620)]
    report += ["## 预选五款", "",
               "[preferred_games.csv](preferred_games.csv)按用户选择顺序保留五款全部时长、三个比值、推进与逐字段来源；这五款是69款总体内的展示选择，不另算五款总体相关。", ""]
    tables = {"reference_cohort.csv": games, "reference_correlations.csv": statistics, "reference_cases.csv": case_rows,
              "preferred_games.csv": preferred}
    for name, rows in tables.items():
        write_text(output / name, csv_text(rows), "utf-8-sig")
    write_text(output / "report.md", "\n".join(report))
    _, after_audit = load_reference_data()
    checks = {"same_69_cohort": digest([g["appid"] for g in games]) == base.COHORT_SHA256,
              "both_references_positive": all(base.number_status(g[field]) == "positive" for g in games for field, _, _ in REFERENCES),
              "sources_unchanged": audit == after_audit and protected_snapshot() == protected_before,
              "all_previous_outputs_and_figures_01_13_unchanged": previous_files(output) == previous_before}
    names = [*tables, "report.md"] + [Path(os.path.relpath(figures / (stem + ext), output)).as_posix()
             for _, _, stem in REFERENCES for ext in (".png", ".svg")]
    manifest = {"version": VERSION, "created_at": base.source.now(), "source": audit, "checks": checks,
                "parameters": {"bootstrap_iterations": base.BOOTSTRAP, "random_state": base.SEED,
                               "case_rule": "same as figure13; empty quadrants remain empty", "type_comparisons": False},
                "protected_before": protected_before, "protected_after": protected_snapshot(),
                "previous_files": previous_before,
                "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    (Path(__file__), Path(base.__file__), ROOT / "plot_files.py")},
                "outputs_path_base": "manifest directory",
                "outputs_sha256": {n: hashlib.sha256((output / n).read_bytes()).hexdigest() for n in names}}
    write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if not all(checks.values()):
        raise RuntimeError("补充分析核验失败，请检查manifest")
    return {"version": VERSION, "games": len(games), "checks": checks, "statistics": statistics,
            "report": str(output / "report.md"), "figures": [str(figures / (stem + ".png")) for _, _, stem in REFERENCES]}


def main() -> int:
    """Run this supplementary command separately, preserving duration's 10..13 artifacts."""
    parser = argparse.ArgumentParser(description="固定69款：补充主线＋支线/全收集时长比与全程推进图14～15")
    parser.add_argument("--output", type=Path, default=DEFAULT_REFERENCES, help="限T1Core独立目录；默认图集中figures")
    args = parser.parse_args()
    try:
        result = analyze(args.output)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
