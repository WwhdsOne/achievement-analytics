"""Game-weighted descriptive completion metrics, with strict story eligibility.

所有可调门槛集中在 ``wwh5/params.py``（**唯一调参入口**），本模块不再写字面量常量——
改完参数重跑 ``analyze`` 即可，只读本地 SQLite、不花 API 额度。
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import params
from . import storage


def _nonnegative(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def rawg_ratio(
    rawg: dict | None, minimum: int | None = None, four_status: bool = False
) -> float | None:
    """Compute a status ratio; missing fields never become zero."""
    if minimum is None:
        minimum = params.RAWG_MIN_DENOMINATOR
    if rawg is None:
        return None
    names = ["status_beaten", "status_dropped"]
    if four_status:
        names += ["status_playing", "status_owned"]
    values = [rawg.get(key) for key in names]
    if not all(_nonnegative(v) for v in values):
        return None
    denominator = sum(values)
    return (
        values[0] / denominator if denominator > 0 and denominator >= minimum else None
    )


def spearman(x: list[float], y: list[float]) -> float | None:
    """Use game-level average tie ranks; <3 or constant pairs are unavailable."""
    if len(x) != len(y) or len(x) < 3:
        return None
    a, b = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def bootstrap_interval(
    values: list[float], samples: int | None = None
) -> list[float] | None:
    """Seed-42 game-bootstrap interval for the mean, excluding annotation uncertainty."""
    if samples is None:
        samples = params.BOOTSTRAP_SAMPLES
    if len(values) < 3 or samples < 1:
        return None
    rng = np.random.default_rng(params.RANDOM_STATE)
    means = np.mean(
        rng.choice(np.asarray(values), (samples, len(values)), replace=True), axis=1
    )
    return [float(v) for v in np.quantile(means, [0.025, 0.975])]


def category_summary(
    game_values: list[list[float]], bootstrap_samples: int | None = None
) -> dict:
    """First median within each game; then equally weight games."""
    if bootstrap_samples is None:
        bootstrap_samples = params.BOOTSTRAP_SAMPLES
    medians = [float(np.median(values)) for values in game_values if values]
    return {
        "games": len(medians),
        "mean_game_median": float(np.mean(medians)) if medians else None,
        "median_game_median": float(np.median(medians)) if medians else None,
        "bootstrap_mean_ci95": bootstrap_interval(medians, bootstrap_samples),
    }


def story_curve(game: dict, labels: list[dict], story: dict | None) -> dict:
    """模型标出的公共主线序列，按「最容易获取的成就」归一化。

    门禁与基准全部来自 ``params``，**改参数不用改这里**。当前默认（2026-10-13 放宽后）
    相对旧口径放开了三处，可用样本 7 → 198 款、RAWG 可配对 7 → 183 款：

    1. ``params.ALLOW_MULTI_ENDING``：不再要求 ``unified_ending=true``。
       很多游戏**有结局，只是不止一个**——原先把「没有统一结局」直接当成「算不了」，
       把两种完全不同的情况混成一个 false。放行后取完成率**最高**的结局作分子，
       含义是「**至少**走到某个结局」的**下界**；**绝不把多个结局相加**。
    2. ``params.REQUIRE_START_CHAIN=False``：不再要求「后续节点必然必经入门」。
       该字段要模型对每个节点单独作答，过于严苛，且叠在「已判为 main + 本体 + 非联机 +
       置信度达标」之后属于双重门禁（实测这一条单独砍掉 158 款）。
    3. ``params.CURVE_BASELINE="highest"``：基准从「模型指定的入门节点」改为
       该游戏完成率最高的成就 → 读作「走到结局的人 ÷ 玩过这款游戏的人」。

    无论参数怎么调都保留的纪律：节点必须是本体公共主线（非 DLC、非联机）、
    阶段顺序不倒退、完成率不反向上升、必须有 end 阶段节点、多结局不相加、
    倒挂的曲线**整条排除而不重排数据**。
    """
    result = {
        "completion": None,
        "points": [],
        "reason": None,
        "ending_type": None,
        "baseline": None,
    }

    def exclude(reason: str) -> dict:
        return {**result, "reason": reason}

    if storage.blocked_reason(game):
        return exclude("source mapping/display-name quality failed")
    if story is None:
        return exclude("story labeling pending")
    unified = story.get("unified_ending") is True
    if not unified and not params.ALLOW_MULTI_ENDING:
        return exclude("no single unified ending (never sum endings)")
    if story.get("confidence", 0) < params.STORY_CONF_MIN:
        return exclude("low story confidence")
    by_id = {str(a["local_id"]): a for a in game["achievements"]}
    label_by_id = {str(a["id"]): a for a in labels}
    points = [p for p in story.get("checkpoints", []) if p.get("route") == "common"]
    if len(points) < params.MIN_COMMON_CHECKPOINTS:
        return exclude(
            f"at least {params.MIN_COMMON_CHECKPOINTS} common checkpoints required"
        )
    # 基准（分母）：见 params.CURVE_BASELINE 的两种口径
    if params.CURVE_BASELINE == "start":
        starts = [p for p in points if p.get("stage") == "start"]
        if len(starts) != 1 or points[0] is not starts[0]:
            return exclude("explicit single leading start required by CURVE_BASELINE")

        def _baseline_of(point_id: str) -> float | None:
            ach = by_id.get(point_id)
            pct = ach.get("percent") if ach else None
            return pct / 100 if _nonnegative(pct) and pct <= 100 else None

        baseline = _baseline_of(starts[0].get("id"))
        if baseline is None:
            return exclude("no valid achievement percent")
    else:
        # 该游戏完成率最高的成就（≈「玩过这款游戏的人」），不依赖模型的进入点判断
        percents = [
            a["percent"]
            for a in game["achievements"]
            if _nonnegative(a.get("percent")) and a["percent"] <= 100
        ]
        if not percents:
            return exclude("no valid achievement percent")
        baseline = max(percents) / 100
    if baseline <= 0:
        return exclude("zero baseline completion")
    order = {"start": 0, "early": 1, "middle": 2, "late": 3, "end": 4}
    seen = set()
    for index, point in enumerate(points):
        aid = point.get("id")
        label, achievement = label_by_id.get(aid), by_id.get(aid)
        if aid in seen or label is None or achievement is None:
            return exclude("unknown or duplicate story checkpoint")
        seen.add(aid)
        if (
            label.get("primary_category") != "main"
            or label.get("scope") != "base"
            or label.get("requires_multiplayer") is not False
            or label.get("confidence", 0) < params.STORY_CONF_MIN
            or point.get("confidence", 0) < params.STORY_CONF_MIN
        ):
            return exclude("checkpoint not high-confidence base main story")
        # 旧口径要求每个后续节点都声明「必然要求经过入门」；由 params 控制是否启用
        if (
            params.REQUIRE_START_CHAIN
            and index > 0
            and point.get("requires_start") is not True
        ):
            return exclude("later checkpoint does not necessarily require start")
        percent = achievement.get("percent")
        if not _nonnegative(percent) or percent > 100:
            return exclude("invalid source completion percent")
        if order.get(point.get("stage"), -1) < 0:
            return exclude("invalid narrative stage order")
        result["points"].append(
            {
                "id": aid,
                "display_name": achievement["display_name"],
                "stage": point["stage"],
                "rate": percent / 100,
            }
        )
    inner_points = [p for p in result["points"] if p["stage"] != "end"]
    end_points = [p for p in result["points"] if p["stage"] == "end"]
    if not end_points:
        return exclude("no end-stage checkpoint")
    if not inner_points:
        return exclude("no pre-end checkpoint")
    inner_stages = [order[p["stage"]] for p in inner_points]
    if any(b < a for a, b in zip(inner_stages, inner_stages[1:])):
        return exclude("invalid narrative stage order")
    inner_rates = [p["rate"] for p in inner_points]
    if any(b > a for a, b in zip(inner_rates, inner_rates[1:])):
        return exclude("reverse completion jump; curve excluded without sorting")
    # 模型说单一结局且确实只给了一个 end → 精确值；否则取最高的 end 作下界
    if unified and len(end_points) == 1:
        end_rate, ending_type = end_points[0]["rate"], "unified"
    else:
        end_rate, ending_type = max(p["rate"] for p in end_points), "multi"
    if end_rate > inner_rates[-1]:
        return exclude("end more common than the node before it")
    for point in result["points"]:
        point["normalized"] = point["rate"] / baseline
    result["completion"] = end_rate / baseline
    result["ending_type"] = ending_type
    result["baseline"] = baseline
    return result


def _paired_summary(pairs: list[dict], bootstrap_samples: int) -> dict:
    x, y = [p["steam"] for p in pairs], [p["rawg"] for p in pairs]
    correlation, interval = spearman(x, y), None
    if correlation is not None and bootstrap_samples > 0:
        rng, estimates = np.random.default_rng(params.RANDOM_STATE), []
        for _ in range(bootstrap_samples):
            indexes = rng.integers(0, len(x), len(x))
            value = spearman([x[i] for i in indexes], [y[i] for i in indexes])
            if value is not None:
                estimates.append(value)
        if len(estimates) >= 3:
            interval = [float(v) for v in np.quantile(estimates, [0.025, 0.975])]
    return {
        "paired_games": len(pairs),
        "spearman": correlation,
        "bootstrap_ci95": interval,
    }


# 图内文字一律用中文（给人看）。类别与剧情阶段的键名保持英文，只在这里翻译展示。
CATEGORY_CN = {
    "main": "主线",
    "side": "支线",
    "collection": "收集",
    "challenge": "挑战",
    "other": "其他",
    "uncertain": "不确定",
}
STAGE_CN = {
    "start": "入门",
    "early": "前期",
    "middle": "中期",
    "late": "后期",
    "end": "结局",
}


def _cjk_fonts() -> list[str]:
    """按优先级挑一个系统里真有中文字形的字体。

    matplotlib 的默认字体 DejaVu Sans 没有汉字，不换字体中文会变方框。
    这里列出三大平台上常见的简体中文字体名，取系统里装了的那些；都找不到时
    回落 DejaVu Sans（中文会显示为方框，但不会报错）。
    """
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    preferred = (
        "PingFang SC",
        "Hiragino Sans GB",
        "Heiti SC",
        "Songti SC",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "WenQuanYi Zen Hei",
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
    )
    return [name for name in preferred if name in available] + ["DejaVu Sans"]


def _titles(ax: Any, title: str, note: str) -> None:
    """主标题与「坐标轴含义」都横排放在图表上方，不在左侧竖排。

    原先 ylabel 竖着贴在左边，中文读起来费劲。改成：主标题一行，说明文字一行，
    都放在坐标系上方，正文里也就不用再靠旋转文字辨认纵轴是什么。
    """
    ax.set_title(title, fontsize=13, pad=28)
    ax.text(
        0.0,
        1.015,
        note,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9,
        color="#666666",
    )


def _figures(
    output: Path,
    categories: dict,
    curves: list[dict],
    pairs: list[dict],
    rho: float | None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    folder = output / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    # 走 font.sans-serif 惯用法：直接把具体字体名塞进 font.family 会触发
    # 「Failed to find font weight normal」这类刷屏警告（实测）。
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": _cjk_fonts(),
            "axes.unicode_minus": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    percent = PercentFormatter(1.0)

    fig, ax = plt.subplots(figsize=(9, 5))
    names = [name for name, summary in categories.items() if summary["games"]]
    if names:
        ax.bar(
            [CATEGORY_CN.get(n, n) for n in names],
            [categories[n]["mean_game_median"] for n in names],
            color="#3B7A99",
        )
    else:
        ax.text(
            0.5,
            0.5,
            "尚无完整的模型分类结果",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_xticks([])  # 没有柱时横轴会露出无意义的 0.0–1.0 数字刻度
    ax.set(ylim=(0, 1))
    ax.yaxis.set_major_formatter(percent)
    _titles(
        ax,
        "各成就类别的完成率",
        "纵轴：各游戏内解锁率中位数之均值（按游戏等权，最高 100%）",
    )
    fig.tight_layout()
    fig.savefig(folder / "category-completion.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    stages = {"start": 0, "early": 1, "middle": 2, "late": 3, "end": 4}
    if curves:
        grouped = defaultdict(lambda: defaultdict(list))
        counts = Counter()
        for curve in curves:
            group = curve["primary_gameplay"]
            counts[group] += 1
            within_game = defaultdict(list)
            for point in curve["points"]:
                within_game[point["stage"]].append(point["normalized"])
            for stage, values in within_game.items():
                grouped[group][stage].append(float(np.median(values)))
        for group in sorted(grouped, key=lambda name: (-counts[name], name)):
            observed = [stage for stage in stages if grouped[group].get(stage)]
            ax.plot(
                [stages[stage] for stage in observed],
                [float(np.median(grouped[group][stage])) for stage in observed],
                marker="o",
                label=f"{group}："
                + "，".join(
                    f"{STAGE_CN[stage]} n={len(grouped[group][stage])}"
                    for stage in observed
                ),
            )
        ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1))
    else:
        ax.text(
            0.5,
            0.5,
            "尚无合格的本体公共主线曲线",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    ax.set(
        xticks=list(stages.values()),
        xticklabels=[STAGE_CN[s] for s in stages],
        ylim=(0, 1.03),
    )
    ax.yaxis.set_major_formatter(percent)
    unified = sum(1 for c in curves if c.get("ending_type") == "unified")
    # 标题短、说明长：标题居中容易被画布裁掉左端，计数放说明里
    _titles(
        ax,
        "主线推进曲线：各剧情阶段的完成率",
        f"可用 {len(curves)} 款（单一结局 {unified} / 多结局 {len(curves) - unified}）；"
        "纵轴：该阶段完成率 ÷ 该游戏完成率最高的成就；横轴：剧情阶段",
    )
    fig.tight_layout()
    fig.savefig(folder / "main-story-curves.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 6))
    if pairs:
        ax.scatter(
            [p["steam"] for p in pairs],
            [p["rawg"] for p in pairs],
            alpha=0.6,
            color="#B47E37",
        )
    else:
        ax.text(
            0.5,
            0.5,
            "尚无可配对的游戏",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.xaxis.set_major_formatter(percent)
    ax.yaxis.set_major_formatter(percent)
    rho_text = f"{rho:.3f}" if isinstance(rho, (int, float)) else "不可用"
    _titles(
        ax,
        f"Steam 与 RAWG 完成口径对比（配对 {len(pairs)} 款，相关系数 {rho_text}）",
        "横轴：Steam 结局/基准比例；纵轴：RAWG 通关/(通关+弃坑)",
    )
    fig.tight_layout()
    fig.savefig(folder / "rawg-comparison.png", dpi=180)
    plt.close(fig)


def analyze(
    path: str | Path = storage.DEFAULT_DB,
    output: str | Path = storage.TASK_ROOT,
    bootstrap_samples: int | None = None,
) -> dict:
    """Read only SQLite, persist computed metrics, and write truthful reports and PNGs.

    门槛与阈值全部取自 ``params``（唯一调参入口）；``bootstrap_samples`` 传 None 时用
    ``params.BOOTSTRAP_SAMPLES``。本函数只读 SQLite，不产生任何 API 调用。
    """
    if bootstrap_samples is None:
        bootstrap_samples = params.BOOTSTRAP_SAMPLES
    if bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be nonnegative")
    output = storage.owned_path(output)
    output.mkdir(parents=True, exist_ok=True)
    per_category, dimensions_completion = defaultdict(list), defaultdict(list)
    primary_completion = defaultdict(list)
    excluded, attributes = Counter(), Counter()
    curve_types = Counter()
    curves, per_game, pairs_four = [], [], []
    pairs_by_threshold = {str(n): [] for n in params.RAWG_THRESHOLDS}
    with storage.connect(path) as conn:
        meta = storage.metadata(conn)
        if not meta.get("dataset_version"):
            raise RuntimeError("Run export first: no frozen snapshot")
        games = storage.load_games(conn)
        labels_by_game = defaultdict(list)
        for row in conn.execute("SELECT appid,payload FROM achievement_labels"):
            labels_by_game[row[0]].append(json.loads(row[1]))
        stories = {
            r[0]: json.loads(r[1])
            for r in conn.execute("SELECT appid,payload FROM story_labels")
        }
        dimensions = {
            r[0]: json.loads(r[1])
            for r in conn.execute("SELECT appid,payload FROM game_labels")
        }
        category_labeled = 0
        for game in games:
            labels = labels_by_game[game["appid"]]
            complete = len(labels) == len(game["achievements"]) and bool(labels)
            if complete:
                category_labeled += 1
                by_category = defaultdict(list)
                ach = {a["local_id"]: a for a in game["achievements"]}
                for label in labels:
                    by_category[label["primary_category"]].append(
                        ach[label["id"]]["percent"] / 100
                    )
                    attributes[f"scope_{label['scope']}"] += 1
                    attributes[f"multiplayer_{label['requires_multiplayer']}"] += 1
                    if label["confidence"] < 0.8:
                        attributes["low_confidence"] += 1
                for category, values in by_category.items():
                    per_category[category].append(values)
            curve = story_curve(game, labels, stories.get(game["appid"]))
            per_game.append(
                {
                    "appid": game["appid"],
                    "title": game["name_en"],
                    "curve": curve,
                    "category_labeled": complete,
                    "rawg_ratio20": rawg_ratio(game.get("rawg")),
                }
            )
            if curve["completion"] is None:
                excluded[curve["reason"]] += 1
                continue
            curve_types[curve["ending_type"]] += 1  # 单一结局是精确值，多结局是下界
            curve["primary_gameplay"] = dimensions.get(game["appid"], {}).get(
                "gameplay", ["uncertain"]
            )[0]
            primary_completion[curve["primary_gameplay"]].append(curve["completion"])
            curves.append(curve)
            for field in ("gameplay", "theme", "presentation", "player_mode"):
                for label in dimensions.get(game["appid"], {}).get(field, []):
                    dimensions_completion[f"{field}:{label}"].append(
                        curve["completion"]
                    )
            for threshold in params.RAWG_THRESHOLDS:
                ratio = rawg_ratio(game.get("rawg"), threshold)
                if ratio is not None:
                    pairs_by_threshold[str(threshold)].append(
                        {
                            "appid": game["appid"],
                            "steam": curve["completion"],
                            "rawg": ratio,
                        }
                    )
            ratio = rawg_ratio(game.get("rawg"), four_status=True)
            if ratio is not None:
                pairs_four.append(
                    {
                        "appid": game["appid"],
                        "steam": curve["completion"],
                        "rawg": ratio,
                    }
                )
        categories = {
            name: category_summary(per_category[name], bootstrap_samples)
            for name in (
                "main",
                "side",
                "collection",
                "challenge",
                "other",
                "uncertain",
            )
        }
        blocked = sum(storage.blocked_reason(g) is not None for g in games)
        errors = conn.execute(
            "SELECT count(DISTINCT appid) FROM model_calls WHERE status='error' AND appid NOT IN (SELECT appid FROM story_labels)"
        ).fetchone()[0]
        usage = Counter()
        for row in conn.execute(
            "SELECT usage FROM model_calls WHERE usage IS NOT NULL"
        ):
            try:
                usage.update(storage.numeric_usage(json.loads(row[0])))
            except (ValueError, TypeError):
                # Older call logs may contain malformed optional usage. Their response audit remains intact.
                continue
        metrics = {
            "frame": len(games),
            "blocked": blocked,
            "category_labeled": category_labeled,
            "labeled": len(stories),
            "pending": len(games) - blocked - len(stories),
            "errors": errors,
            "usable_curves": len(curves),
            "paired": len(pairs_by_threshold["20"]),
            "rawg_present": sum(g.get("rawg") is not None for g in games),
            "rawg_valid20": sum(rawg_ratio(g.get("rawg")) is not None for g in games),
            "bootstrap_samples": bootstrap_samples,
            "excluded_curves": dict(excluded),
            "annotation_attributes": dict(attributes),
            "curve_types": dict(curve_types),
            "categories": categories,
            "usage": dict(usage),
            "rawg_comparisons": {
                k: _paired_summary(v, bootstrap_samples)
                for k, v in pairs_by_threshold.items()
            },
            "rawg_four_status": _paired_summary(pairs_four, bootstrap_samples),
            "primary_gameplay_completion": {
                k: {
                    "games": len(v),
                    "mean": float(np.mean(v)),
                    "median": float(np.median(v)),
                    "bootstrap_mean_ci95": bootstrap_interval(v, bootstrap_samples),
                }
                for k, v in primary_completion.items()
            },
            "dimension_completion": {
                k: {
                    "games": len(v),
                    "mean": float(np.mean(v)),
                    "bootstrap_mean_ci95": bootstrap_interval(v, bootstrap_samples),
                }
                for k, v in dimensions_completion.items()
            },
            "per_game": per_game,
        }
        analysis_meta = {
            "dataset_version": meta["dataset_version"],
            "input_sha256": meta["input_sha256"],
            "active_annotation": meta.get("active_annotation"),
            "bootstrap_samples": bootstrap_samples,
            "random_state": params.RANDOM_STATE,
            "analysis_version": "wwh5-analysis-v1",
            "analyzed_at": storage.now(),
        }
        conn.execute(
            "INSERT INTO analysis_runs(analyzed_at,metadata,metrics) VALUES (?,?,?)",
            (
                analysis_meta["analyzed_at"],
                storage.canonical(analysis_meta),
                storage.canonical(metrics),
            ),
        )
    _figures(
        output,
        categories,
        curves,
        pairs_by_threshold["20"],
        metrics["rawg_comparisons"]["20"]["spearman"],
    )
    _report(output, meta, metrics)
    return metrics


def _report(output: Path, meta: dict, metrics: dict) -> None:
    fmt = lambda value: "不可用" if value is None else f"{value:.4f}"
    bootstrap_n = metrics.get("bootstrap_samples", params.BOOTSTRAP_SAMPLES)
    lines = [
        "# WWH 任务 5：分类完成曲线与 RAWG 对比",
        "",
        f"数据版本：`{meta['dataset_version']}`；输入 SHA256：`{meta['input_sha256']}`。",
        f"模型配置：`{storage.canonical(meta.get('active_annotation'))}`。所有分析从本地 SQLite 读取。",
        "",
        "## 覆盖与当前状态",
        "",
        f"固定排名样本 {metrics['frame']} 款；分类完整 {metrics['category_labeled']}；剧情标注完成 {metrics['labeled']}；",
        f"映射/展示名阻塞 {metrics['blocked']}；尚待完整标注 {metrics['pending']}（其中有失败记录 {metrics['errors']}）。",
        f"可用主线曲线 {metrics['usable_curves']}；RAWG 已匹配 {metrics['rawg_present']}；有效状态样本 {metrics['rawg_valid20']}；有效配对 {metrics['paired']}。",
        "",
        "游戏按 SteamSpy 好评数＋差评数排序（并列按 appid），仅游戏且 2026 年以前发售。排名后才检查缺口，不用后续游戏替换缺失项。",
        "所有游戏维度、成就分类、剧情节点均由 DeepSeek 给出，属于模型判断，未经人工核实。",
        "模型输入只有名称、标签、成就展示名与描述，不含完成率、评价数或 RAWG 状态。",
        "",
        "## 分类完成率",
        "",
        "每款游戏先计算每类成就的完成率中位数，再对游戏等权汇总；不把成就多的游戏赋予更高权重。",
        "主线、支线、收集、挑战、其他、不确定分类均保留；DLC、联机、低置信度为独立属性。分类汇总含低置信度条目，剧情曲线另有严格筛选。",
        "",
        "| 类别 | 游戏数 | 游戏中位数的均值 |",
        "| --- | ---: | ---: |",
    ]
    for name, summary in metrics["categories"].items():
        lines.append(
            f"| {name} | {summary['games']} | {fmt(summary['mean_game_median'])} |"
        )
    lines += [
        "",
        "![分类完成率](figures/category-completion.png)",
        "",
        "## 主线曲线",
        "",
        f"只使用映射无未解决问题、有展示名、置信度至少 {params.STORY_CONF_MIN} 的共同路线本体主线节点（非 DLC、非联机）。",
        "**归一化基准是该游戏完成率最高的成就**（≈「玩过这款游戏的人」），不再使用模型指定的入门节点——"
        "该指标因此读作「走到结局的人 ÷ 玩过这款游戏的人」。",
        "**多结局处理**：模型判定没有唯一结局时，取完成率最高的那个结局作分子，得到「**至少**走到某个结局」的"
        "**下界**；绝不相加（多个结局的解锁者可能重叠，相加会超过 100%）。单一结局游戏是精确值，报告里分开统计。",
        "节点按模型给出的全局剧情顺序排列；出现反向完成率跳跃则排除整条曲线，**不按完成率重排数据**。",
        "",
        f"曲线类型：`{storage.canonical(metrics['curve_types'])}`（unified = 模型确认的唯一结局，精确值；multi = 多结局取最高者，下界）。",
        "排除原因：`" + storage.canonical(metrics["excluded_curves"]) + "`。",
        "",
        "该比例是聚合观测指标，**不代表弃坑率、留存率或全成就玩家比例**；剧情顺序与节点前置关系属于模型判断，仍需独立验证。",
        "",
        "每款游戏使用模型首个玩法标签作为主类型，分组不会因多标签重复计入。图中各阶段先在游戏内取中位数，再对同类游戏取中位数；图例逐阶段给出有效游戏数。缺少某阶段的游戏不插值补齐，因此阶段构成可能不同。",
        "",
        "| 主玩法 | 有效游戏数 | 结局/基准均值 | 游戏层 Bootstrap 95% 区间 |",
        "| --- | ---: | ---: | --- |",
    ]
    for group, summary in sorted(metrics["primary_gameplay_completion"].items()):
        lines.append(
            f"| {group} | {summary['games']} | {fmt(summary['mean'])} | {summary['bootstrap_mean_ci95'] or '不可用'} |"
        )
    lines += [
        "",
        "补充维度采用重叠多标签分组，同一游戏可进入多个组，不代表独立样本。",
        "",
        "| 模型维度标签 | 游戏数 | 结局/基准均值 | 95% 区间 |",
        "| --- | ---: | ---: | --- |",
    ]
    for label, summary in sorted(metrics["dimension_completion"].items()):
        lines.append(
            f"| {label.replace('|', '/')} | {summary['games']} | {fmt(summary['mean'])} | {summary['bootstrap_mean_ci95'] or '不可用'} |"
        )
    lines += [
        "",
        "![主线曲线](figures/main-story-curves.png)",
        "",
        "## RAWG 对比",
        "",
        "主指标 beaten/(beaten+dropped)：两字段均须已观测且非负，分母至少 20；缺失保持缺失，不补零。另报告阈值 10、50。",
        "四状态敏感性分析分母为 beaten+dropped+playing+owned，四字段都须观测；owned 不能证明已游玩。",
        "",
        "| 最低分母 | 配对游戏数 | Spearman | Bootstrap 95% 区间 |",
        "| --- | ---: | ---: | --- |",
    ]
    for threshold, summary in metrics["rawg_comparisons"].items():
        lines.append(
            f"| {threshold} | {summary['paired_games']} | {fmt(summary['spearman'])} | {summary['bootstrap_ci95'] or '不可用'} |"
        )
    lines += [
        "",
        f"四状态口径：`{storage.canonical(metrics['rawg_four_status'])}`。",
        "",
        f"Spearman 在配对游戏层面计算；少于 3 款或变量恒定时不可用。Bootstrap 按游戏重抽样 {bootstrap_n} 次、随机种子 {params.RANDOM_STATE}；不能覆盖模型标注误差。",
        "",
        "![RAWG 对比](figures/rawg-comparison.png)",
        "",
        "Steam 与 RAWG 用户群及状态口径不同，只比较描述趋势与排序，不能据此判断哪个平台更准确，也不能解释为因果效应。",
        "RAWG 数据来源：[RAWG](https://rawg.io/)。",
        "",
        f"模型返回用量累计（含取得响应但解析失败的请求）：`{storage.canonical(metrics['usage'])}`。",
        "HTTP 次数上限含重试；成功响应按模型、提示版本、输入 hash 续跑。服务商收费后、SQLite 提交前终止属于外部结果未知，恢复可能重复付费。",
    ]
    if not metrics["category_labeled"]:
        lines += [
            "",
            "当前尚无完整模型分类，图表显示待标注状态，不能据此给出完成差异结论。",
        ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
