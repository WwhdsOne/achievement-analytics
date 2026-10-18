"""从固定198款指标底表选择最多五款，绘制多阶段分组柱状对比图。"""

from __future__ import annotations

import csv
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import textwrap
import unicodedata
from typing import Any

from prepare_metrics import DEFAULT_OUTPUT, EXPECTED_GAMES, ROOT, canonical, csv_text, digest, owned_path, protected_snapshot, source, write_text
from plot_files import add_footer, comparison_name, figure_directory

DEFAULT_COMPARISONS = DEFAULT_OUTPUT / "comparisons"
DEMO_APPIDS = [1593500, 220240, 367520, 489830, 424840]
PANELS = {
    "coverage": {
        "title": "节点覆盖率：首节点 → 位置中位节点 → 代表结局",
        "series": [("p_s", "首节点"), ("p_m", "位置中位节点"), ("p_f", "代表结局")],
    },
    "progress": {
        "title": "阶段推进比：前段、后段与全程分别比较",
        "series": [("early_progress_ratio", "前段：中 / 首"),
                   ("late_progress_ratio", "后段：末 / 中"),
                   ("overall_progress_ratio", "全程：末 / 首")],
    },
}
COLORS = ("#397BA6", "#E69F00", "#009E73")


def normalize_name(value: str) -> str:
    """Normalize case, spacing, punctuation and trademark symbols for name lookup."""
    value = unicodedata.normalize("NFKC", value.translate(str.maketrans("", "", "™®©"))).casefold()
    return "".join(ch for ch in value if ch.isalnum())


def load_catalog(input_dir: str | Path = DEFAULT_OUTPUT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate prepared CSV fingerprints and read WWH name aliases without recalculation."""
    input_dir = Path(input_dir).resolve(strict=True)
    manifest_path = input_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not all(manifest.get("checks", {}).values()) or not manifest.get("checks"):
        raise ValueError("指标准备核验未通过，请先运行prepare")
    for name, expected in manifest["outputs_sha256"].items():
        if hashlib.sha256((input_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"指标文件已改变：{name}，请先重跑prepare")
    with (input_dir / "game_metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    appids = [int(r["appid"]) for r in rows]
    if len(appids) != EXPECTED_GAMES or len(set(appids)) != EXPECTED_GAMES:
        raise ValueError("指标底表不再是固定198款")
    if digest(appids) != manifest["source"]["cohort_sha256"]:
        raise ValueError("指标底表AppID清单与来源清单不一致")
    if source.fingerprint(source.DEFAULT_DB)["sha256"] != manifest["source"]["source_database_sha256"]:
        raise ValueError("WWH借用库已改变，请先核对prepare来源")
    placeholders = ",".join("?" for _ in appids)
    with source.connect(source.DEFAULT_DB) as conn:
        names = {r[0]: json.loads(r[1]) for r in conn.execute(
            f"SELECT appid,payload FROM games WHERE appid IN ({placeholders})", appids)}
    result = []
    for row in rows:
        appid = int(row["appid"])
        game = names[appid]
        values = {}
        for spec in PANELS.values():
            for field, _ in spec["series"]:
                text = row[field]
                value = float(text) if text != "" else None
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError(f"appid={appid}指标不是有效非负数：{field}")
                values[field] = value
        result.append({**row, **values, "appid": appid, "title": game["name_en"],
                       "name_zh": game.get("name_zh"), "node_count": int(row["node_count"]),
                       "three_point_available": row["three_point_available"] == "true"})
    audit = {"input_directory": str(input_dir), "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
             "cohort_sha256": manifest["source"]["cohort_sha256"],
             "dataset_version": manifest["source"]["database_metadata"]["dataset_version"],
             "game_metrics_sha256": manifest["outputs_sha256"]["game_metrics.csv"]}
    return result, audit


def select_games(catalog: list[dict[str, Any]], selectors: list[str] | None, kind: str = "mixed") -> list[dict[str, Any]]:
    """Resolve one to five unique games in input order, never extending the cohort."""
    selectors = selectors if selectors is not None else [str(i) for i in DEMO_APPIDS]
    if not 1 <= len(selectors) <= 5:
        raise ValueError("一次请选择1～5款游戏")
    by_id = {g["appid"]: g for g in catalog}
    aliases: dict[str, set[int]] = {}
    for game in catalog:
        for name in (game["title"], game.get("name_zh")):
            if name and normalize_name(name):
                aliases.setdefault(normalize_name(name), set()).add(game["appid"])
    result = []
    for selector in selectors:
        selector = str(selector).strip()
        if kind == "appid" or (kind == "mixed" and selector.isdecimal()):
            if not selector.isdecimal() or int(selector) not in by_id:
                raise ValueError(f"AppID {selector} 不在固定198款范围；可用compare --list-games查看清单")
            matches = {int(selector)}
        else:
            query = normalize_name(selector)
            if not query:
                raise ValueError("游戏名不能为空或仅包含符号")
            matches = aliases.get(query, set())
            if not matches:
                matches = set().union(*(ids for name, ids in aliases.items() if query in name))
            if not matches:
                suggestions = difflib.get_close_matches(query, list(aliases), n=3, cutoff=0.4)
                titles = sorted({by_id[i]["title"] for name in suggestions for i in aliases[name]})
                raise ValueError(f"未在198款范围匹配游戏：{selector}。候选：{'；'.join(titles) or '请用--list-games查看'}")
            if len(matches) > 1:
                choices = "；".join(f"{i} {by_id[i]['title']}" for i in sorted(matches))
                raise ValueError(f"游戏名有多个匹配，请使用AppID或完整名称：{selector} → {choices}")
        game = by_id[next(iter(matches))]
        if any(g["appid"] == game["appid"] for g in result):
            raise ValueError(f"重复选择同一游戏：{game['title']} ({game['appid']})")
        result.append(game)
    return result


def comparison_rows(games: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
    """Export the exact long-form values plotted, keeping missing bars empty."""
    panels = list(PANELS) if view == "both" else [view]
    return [{"appid": game["appid"], "title": game["title"], "panel": panel,
             "metric": field, "label": label, "value": game[field],
             "node_count": game["node_count"], "ending_type": game["ending_type"],
             "three_point_available": game["three_point_available"]}
            for panel in panels for game in games for field, label in PANELS[panel]["series"]]


def draw_comparison(games: list[dict[str, Any]], view: str, output: Path) -> None:
    """Draw percentage-labeled grouped bars with an explicit missing-data label."""
    os.environ["MPLCONFIGDIR"] = str(ROOT / "runtime" / "matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator, PercentFormatter
    from prepare_metrics import baseline

    panels = list(PANELS) if view == "both" else [view]
    with plt.rc_context({"font.family": "sans-serif", "font.sans-serif": baseline._cjk_fonts(),
                         "axes.unicode_minus": False, "axes.spines.top": False,
                         "axes.spines.right": False, "font.size": 11}):
        fig, axes = plt.subplots(len(panels), 1, figsize=(max(10, len(games) * 2.55 + 1.5), len(panels) * 4.9 + 1.25),
                                 squeeze=False, sharex=True)
        x = list(range(len(games)))
        width = 0.24
        for ax, panel in zip(axes[:, 0], panels):
            spec = PANELS[panel]
            observed = [g[field] for g in games for field, _ in spec["series"] if g[field] is not None]
            ymax = max(1.12, max(observed, default=1.0) * 1.16)
            for index, (field, label) in enumerate(spec["series"]):
                first = True
                for position, game in zip(x, games):
                    center = position + (index - 1) * width
                    value = game[field]
                    if value is None:
                        ax.text(center, ymax * 0.025, "缺失", ha="center", va="bottom", fontsize=9, color="#777777", rotation=90)
                        continue
                    ax.bar(center, value, width=width * 0.92, color=COLORS[index],
                           label=label if first else None, zorder=3)
                    first = False
                    ax.annotate(f"{value:.1%}", (center, value), xytext=(0, 4), textcoords="offset points",
                                ha="center", va="bottom", fontsize=9, color="#263238")
                if first:
                    ax.bar([], [], color=COLORS[index], label=label)
            ax.set_title(spec["title"], loc="left", fontsize=13, pad=17)
            ax.set_ylim(0, ymax)
            ax.yaxis.set_major_locator(MultipleLocator(0.2))
            ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
            ax.grid(axis="y", color="#DCE3E8", linewidth=0.7, zorder=0)
            ax.set_axisbelow(True)
            ax.legend(loc="upper right", ncol=3, frameon=False, fontsize=10)
        labels = []
        for game in games:
            title = game.get("name_zh") or game["title"]
            ending = "统一结局" if game["ending_type"] == "unified" else "多结局代理"
            labels.append("\n".join(textwrap.wrap(title, width=22, break_long_words=False))
                          + f"\n{game['node_count']}个节点 · {ending}")
        axes[-1, 0].set_xticks(x, labels, fontsize=10)
        axes[-1, 0].set_xlim(-0.6, len(games) - 0.4)
        subject = "节点覆盖与阶段推进对比" if view == "both" else "首中末节点覆盖对比" if view == "coverage" else "前后段与全程推进对比"
        fig.suptitle(f"所选{len(games)}款游戏：{subject}", fontsize=19, y=0.985)
        add_footer(fig, [f"样本来源：2026-10-13冻结1000款快照 → 198款有效主线曲线；本图按输入AppID或名称选择{len(games)}款。",
                   "选点：有效主线序列的首项、数组位置中位项和代表结局；偶数取靠前中点，多结局取最高解锁率者。",
                   "数据：覆盖为对应成就的原始解锁率；前/后/全程推进比依次为中/首、末/中、末/首，逐游戏展示。",
                   "解释：缺失不补0，位置中位不是时间中点；结局为代表代理，推进比不等于日留存。"])
        fig.subplots_adjust(left=0.065, right=0.985, top=0.90 if len(panels) > 1 else 0.82,
                            bottom=0.32 if len(panels) == 1 else 0.24, hspace=0.37)
        try:
            fig.savefig(owned_path(output.with_suffix(".png")), dpi=180)
            fig.savefig(owned_path(output.with_suffix(".svg")), metadata={"Date": None})
        finally:
            plt.close(fig)


def compare(selectors: list[str] | None = None, kind: str = "mixed", view: str = "both",
            output: str | Path = DEFAULT_COMPARISONS) -> dict[str, Any]:
    """Create selected-game chart artifacts without modifying prepared data or databases."""
    if view not in (*PANELS, "both"):
        raise ValueError("view只能是coverage、progress或both")
    output = owned_path(output)
    protected_before = protected_snapshot()
    catalog, audit = load_catalog()
    games = select_games(catalog, selectors, kind)
    rows = comparison_rows(games, view)
    stem = "compare_" + "_".join(str(g["appid"]) for g in games) + "_" + view
    base = owned_path(output / stem)
    output.mkdir(parents=True, exist_ok=True)
    figures = figure_directory(output, DEFAULT_COMPARISONS)
    figures.mkdir(parents=True, exist_ok=True)
    plot_base = figures / comparison_name([g["appid"] for g in games], view)
    draw_comparison(games, view, plot_base)
    write_text(base.with_suffix(".csv"), csv_text(rows), "utf-8-sig")
    _, after_audit = load_catalog()
    protected_after = protected_snapshot()
    unchanged = protected_before == protected_after and audit == after_audit
    artifacts = [plot_base.with_suffix(ext) for ext in (".png", ".svg")] + [base.with_suffix(".csv")]
    manifest = {"created_at": source.now(), "plot_version": "lyx-stage-bars-v2", "source": audit, "view": view, "selector_kind": kind,
                "selectors": selectors, "selected_games": [{k: g[k] for k in
                    ("appid", "title", "node_count", "ending_type")} for g in games],
                "missing_value_policy": "no bar; label missing; CSV empty", "data_sha256": digest(rows),
                "inputs_unchanged": unchanged, "protected_before": protected_before, "protected_after": protected_after,
                "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (Path(__file__), ROOT / "run.py", ROOT / "plot_files.py")},
                "outputs_path_base": "metadata directory",
                "outputs_sha256": {Path(os.path.relpath(p, output)).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in artifacts}}
    write_text(base.with_suffix(".json"), json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if not unchanged:
        raise RuntimeError("绘图期间输入指纹改变，请核对比较JSON；未写数据库或T0Pre")
    return {"selected": manifest["selected_games"], "view": view, "png": str(plot_base.with_suffix(".png")),
            "svg": str(plot_base.with_suffix(".svg")), "data_csv": str(base.with_suffix(".csv")),
            "metadata": str(base.with_suffix(".json")), "inputs_unchanged": unchanged}
