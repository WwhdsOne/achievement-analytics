"""Q1 baseline、Q2 回归和报告生成；所有页面使用同一固定输入。"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from plotly.utils import PlotlyJSONEncoder
from sklearn.base import clone
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from modeling.regression.dataset import (
    REPORT_PATH,
    TEXT_RULES,
    extract_snapshot,
    load_snapshot,
    owners_midpoint,
)
from modeling.regression.stories import build_stories

SEED = 42
POPULAR_EXAMPLES = {
    413150: "星露谷物语",
    601150: "鬼泣5",
    883710: "生化危机2：重制版",
    374320: "黑暗之魂3",
    646570: "杀戮尖塔",
    367520: "空洞骑士",
    814380: "只狼：影逝二度",
    1086940: "博德之门3",
    1245620: "艾尔登法环",
    2358720: "黑神话：悟空",
    1174180: "荒野大镖客：救赎2",
    292030: "巫师3：狂猎",
}


def popular_examples(reputation: pd.DataFrame) -> list[dict[str, Any]]:
    """从符合口径的样本中选取热门案例，中文常用名只用于报告展示。"""
    selected = reputation[
        reputation["appid"].isin(POPULAR_EXAMPLES)
        & (reputation["approval"] >= 0.9)
        & (reputation["resolved_total"] >= 50)
    ].sort_values(["drop_ratio", "appid"], ascending=[False, True])
    selected = selected[
        ["appid", "name_en", "name_zh", "approval", "drop_ratio", "resolved_total", "playtime"]
    ].copy()
    selected["name_zh"] = selected["appid"].map(POPULAR_EXAMPLES)
    return selected.to_dict("records")


GENRES = (
    "Action",
    "Adventure",
    "RPG",
    "Strategy",
    "Simulation",
    "Casual",
    "Indie",
    "Sports",
    "Racing",
)
TAGS = (
    "Souls-like",
    "Difficult",
    "Rogue-like",
    "Deckbuilding",
    "Cozy",
    "Metroidvania",
    "Story Rich",
    "Puzzle",
    "Multiplayer",
    "Open World",
    "Visual Novel",
    "Action",
    "Strategy",
)
STRUCTURE = (
    "成就稀有度",
    "成就数量 log1p",
    "低于5%占比",
    "低于1%占比",
    "P10完成率",
    "完成率分位差",
)
TARGETS = {
    "drop_ratio": "通关/弃坑标记者中的弃坑占比",
    "log_hours": "RAWG 时长 log1p(小时)",
    "approval": "Steam 好评占比",
}


def wilson_interval(success: int, total: int) -> tuple[float | None, float | None]:
    """给出计数比例的 Wilson 95% 描述性区间，不覆盖平台选择偏差。"""
    if total < 0 or success < 0 or success > total:
        raise ValueError("计数必须满足 0 <= success <= total")
    if total == 0:
        return None, None
    z = 1.959963984540054
    p = success / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = (
        z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    )
    return max(0.0, center - radius), min(1.0, center + radius)


def feature_matrix(frame: pd.DataFrame, *, extensions: bool = False) -> pd.DataFrame:
    """构建无目标组成量的固定特征集；缺失值留给训练折内填补。"""
    price = frame["price_cents"].where(~frame["is_free"].fillna(False), 0)
    matrix = pd.DataFrame(
        {
            "成就稀有度": 100 - frame["median_percent"],
            "成就数量 log1p": np.log1p(frame["ach_count"]),
            "低于5%占比": frame["hard_ratio"],
            "低于1%占比": frame["ultra_ratio"],
            "P10完成率": frame["p10_percent"],
            "完成率分位差": frame["spread"],
            "发售年份": frame["year"],
            "现价 log1p": np.log1p(price / 100),
            "免费游戏": frame["is_free"].fillna(False).astype(float),
            "拥有量中点 log1p": np.log1p(frame["owners"].map(owners_midpoint)),
            "评价数 log1p": np.log1p(frame["reviews"]),
        },
        index=frame.index,
    )
    for genre in GENRES:
        matrix[f"类型·{genre}"] = frame["genres"].map(
            lambda values: int(genre in values)
        )
    for tag in TAGS:
        matrix[f"标签·{tag}"] = frame["tags"].map(lambda values: int(tag in values))
    if extensions:
        for i, category in enumerate(TEXT_RULES):
            if f"text_{i}" in frame:
                matrix[f"文本规则·{category}"] = frame[f"text_{i}"]
        for left, right in (
            ("Rogue-like", "Deckbuilding"),
            ("Rogue-like", "Action"),
            ("Story Rich", "Puzzle"),
        ):
            matrix[f"交互·{left} × {right}"] = (
                matrix[f"标签·{left}"] * matrix[f"标签·{right}"]
            )
    return matrix.astype(float)


def valid_sample(
    frame: pd.DataFrame, target: str, minimum: int = 20, reviews: int = 100
) -> pd.DataFrame:
    """按独立目标口径选样本，至少五个成就且目标非缺失。"""
    mask = (
        (frame["ach_count"] >= 5)
        & (frame["reviews"] >= reviews)
        & frame[target].notna()
    )
    if target == "drop_ratio":
        mask &= frame["resolved_total"] >= minimum
    return frame.loc[mask].copy()


def correlation(x: pd.Series, y: pd.Series) -> float | None:
    """返回成对有效观测的 Spearman 系数；常量或小样本返回缺失。"""
    values = pd.concat([x, y], axis=1).dropna()
    if (
        len(values) < 3
        or values.iloc[:, 0].nunique() < 2
        or values.iloc[:, 1].nunique() < 2
    ):
        return None
    return float(values.iloc[:, 0].corr(values.iloc[:, 1], method="spearman"))


def ridge_pipeline() -> Any:
    """缺失填补、标准化和正则化均由训练折拟合。"""
    return make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        Ridge(alpha=10),
    )


def score_cv(
    matrix: pd.DataFrame, target: pd.Series, estimator: Any
) -> tuple[dict[str, Any], Any, np.ndarray]:
    """同一随机五折输出 out-of-fold 指标及最后一折留出归因对象。"""
    folds = KFold(n_splits=5, shuffle=True, random_state=SEED)
    predicted = np.empty(len(target))
    scores = []
    for train, test in folds.split(matrix):
        model = clone(estimator).fit(matrix.iloc[train], target.iloc[train])
        prediction = model.predict(matrix.iloc[test])
        predicted[test] = prediction
        scores.append(
            {
                "r2": float(r2_score(target.iloc[test], prediction)),
                "rmse": float(
                    math.sqrt(mean_squared_error(target.iloc[test], prediction))
                ),
            }
        )
    result = {
        "n": len(target),
        "r2": float(r2_score(target, predicted)),
        "rmse": float(math.sqrt(mean_squared_error(target, predicted))),
        "folds": scores,
        "r2_std": float(np.std([s["r2"] for s in scores])),
    }
    return result, model, test


def model_experiment(sample: pd.DataFrame, target: str) -> dict[str, Any]:
    """比较元数据、整体稀有度、尾部、文本与交互；再比较随机森林。"""
    import shap

    matrix = feature_matrix(sample, extensions=True)
    if target == "approval":
        matrix = matrix.drop(columns="评价数 log1p")
    y = sample[target]
    controls = [
        c
        for c in matrix
        if c not in STRUCTURE and not c.startswith(("文本规则", "交互"))
    ]
    overall = controls + list(STRUCTURE[:2])
    full = controls + list(STRUCTURE)
    variants = {
        "均值 baseline": (controls, DummyRegressor(strategy="mean")),
        "元数据 Ridge": (controls, ridge_pipeline()),
        "整体稀有度 Ridge": (overall, ridge_pipeline()),
        "尾部结构 Ridge": (full, ridge_pipeline()),
        "文本规则 Ridge": (
            full + [c for c in matrix if c.startswith("文本规则")],
            ridge_pipeline(),
        ),
        "标签交互 Ridge": (
            full + [c for c in matrix if c.startswith("交互")],
            ridge_pipeline(),
        ),
        "随机森林": (
            full,
            make_pipeline(
                SimpleImputer(strategy="median", keep_empty_features=True),
                RandomForestRegressor(
                    n_estimators=160,
                    max_depth=9,
                    min_samples_leaf=15,
                    n_jobs=-1,
                    random_state=SEED,
                ),
            ),
        ),
    }
    metrics = []
    forest = None
    for name, (columns, estimator) in variants.items():
        scores, fitted, holdout = score_cv(matrix[columns], y, estimator)
        metrics.append({"name": name, **scores})
        if name == "随机森林":
            forest = fitted
    # 归因只在最后一折未参与拟合的游戏上计算；同一规则挑最多300款。
    rng = np.random.default_rng(SEED)
    explain_rows = rng.choice(holdout, min(300, len(holdout)), replace=False)
    values = forest[0].transform(matrix[full].iloc[explain_rows])
    shap_values = shap.TreeExplainer(forest[1]).shap_values(
        values, check_additivity=False
    )
    importance = np.abs(shap_values).mean(axis=0)
    top = np.argsort(importance)[::-1][:12]
    attribution = [
        {"feature": full[i], "mean_abs_shap": float(importance[i])} for i in top
    ]
    temporal = []
    train_mask = sample["year"] <= 2022
    test_mask = sample["year"] >= 2023
    if train_mask.sum() >= 100 and test_mask.sum() >= 100:
        for name in ("均值 baseline", "尾部结构 Ridge", "随机森林"):
            columns, estimator = variants[name]
            fitted = clone(estimator).fit(
                matrix.loc[train_mask, columns], y.loc[train_mask]
            )
            prediction = fitted.predict(matrix.loc[test_mask, columns])
            temporal.append(
                {
                    "name": name,
                    "train_n": int(train_mask.sum()),
                    "test_n": int(test_mask.sum()),
                    "r2": float(r2_score(y.loc[test_mask], prediction)),
                    "rmse": float(
                        math.sqrt(mean_squared_error(y.loc[test_mask], prediction))
                    ),
                }
            )
    return {
        "target": target,
        "label": TARGETS[target],
        "metrics": metrics,
        "shap": attribution,
        "features": full,
        "shap_n": len(explain_rows),
        "temporal": temporal,
        "interaction_counts": {
            c: int(matrix[c].sum()) for c in matrix if c.startswith("交互")
        },
        "shap_points": {
            full[i]: {"x": values[:, i].tolist(), "y": shap_values[:, i].tolist()}
            for i in top[:4]
        },
    }


def type_comparison(sample: pd.DataFrame) -> list[dict[str, Any]]:
    """对照整体、类型内和控制后的稀有度关联；不是玩家分群。"""
    rows = []
    for genre in (
        "全部",
        "Action",
        "Adventure",
        "RPG",
        "Strategy",
        "Simulation",
        "Casual",
    ):
        group = (
            sample
            if genre == "全部"
            else sample[sample["genres"].map(lambda v: genre in v)]
        )
        if len(group) < 100:
            continue
        matrix = feature_matrix(group)
        unadjusted = ridge_pipeline().fit(matrix[["成就稀有度"]], group["drop_ratio"])
        adjusted = ridge_pipeline().fit(matrix, group["drop_ratio"])
        slope = lambda model: float(model[-1].coef_[0] / model[-2].scale_[0] * 10 * 100)
        rows.append(
            {
                "type": genre,
                "n": len(group),
                "rho": correlation(100 - group["median_percent"], group["drop_ratio"]),
                "raw_slope": slope(unadjusted),
                "adjusted_slope": slope(adjusted),
                "drop_median": float(group["drop_ratio"].median()),
            }
        )
    return rows


def scatter_records(sample: pd.DataFrame, limit: int = 1300) -> list[dict[str, Any]]:
    """固定种子抽取可视化点；统计分析始终使用完整有效样本。"""
    columns = [
        "appid",
        "name_en",
        "name_zh",
        "genres",
        "tags",
        "median_percent",
        "hard_ratio",
        "ultra_ratio",
        "spread",
        "drop_ratio",
        "resolved_total",
        "dropped",
        "approval",
        "playtime",
    ]
    points = sample.sample(min(len(sample), limit), random_state=SEED)
    result = []
    for row in points[columns].to_dict("records"):
        low, high = wilson_interval(int(row["dropped"]), int(row["resolved_total"]))
        row.update({"ci_low": low, "ci_high": high})
        result.append(row)
    return result


def summary_group(group: pd.DataFrame, label: str) -> dict[str, Any]:
    """汇总游戏等权的中位数，避免把大游戏状态计数混为游戏偏好。"""
    return {
        "label": label,
        "n": len(group),
        "median_rarity": float((100 - group["median_percent"]).median()),
        "median_drop": float(group["drop_ratio"].median()),
        "median_hours": float(group["playtime"].where(group["playtime"] > 0).median()),
        "median_approval": float(group["approval"].median()),
    }


def build_report(frame: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    """在固定输入上执行批准的研究方向并生成供 dashboard 展示的结论。"""
    drop = valid_sample(frame, "drop_ratio")
    if len(drop) < 100:
        raise ValueError("弃坑占比有效样本不足100款，不能执行主线模型")
    models = []
    for target in TARGETS:
        sample = valid_sample(frame, target)
        print(f"建模 {target}: {len(sample)} 款", flush=True)
        if len(sample) < 100:
            continue
        models.append(model_experiment(sample, target))
    type_rows = type_comparison(drop)
    sensitivity = []
    for reviews, minimum in ((100, 10), (100, 20), (100, 50), (500, 20), (1000, 20)):
        sample = valid_sample(frame, "drop_ratio", minimum=minimum, reviews=reviews)
        scores = {"r2": None, "rmse": None}
        if len(sample) >= 100:
            scores, _, _ = score_cv(
                feature_matrix(sample), sample["drop_ratio"], ridge_pipeline()
            )
        sensitivity.append(
            {
                "reviews_min": reviews,
                "states_min": minimum,
                "n": len(sample),
                "rho": correlation(
                    100 - sample["median_percent"], sample["drop_ratio"]
                ),
                **scores,
            }
        )
    coverage = []
    for label, sample in (
        ("全量帧", frame),
        ("RAWG覆盖", frame[frame["rawg_id"].notna()]),
        ("RAWG未覆盖", frame[frame["rawg_id"].isna()]),
        ("主线状态样本", drop),
    ):
        coverage.append(
            {
                "label": label,
                "n": len(sample),
                "year": float(sample["year"].median()),
                "reviews": float(sample["reviews"].median()),
                "rarity": float((100 - sample["median_percent"]).median()),
                "free_ratio": float(sample["is_free"].mean()),
            }
        )
    structures = []
    for label, subset in (
        ("中位完成率 ≥50%", drop[drop["median_percent"] >= 50]),
        ("中位完成率 <50%", drop[drop["median_percent"] < 50]),
        (
            "较常见主体 + 稀有尾部",
            drop[(drop["median_percent"] >= 50) & (drop["ultra_ratio"] > 0)],
        ),
        (
            "主体与尾部都较常见",
            drop[(drop["median_percent"] >= 50) & (drop["ultra_ratio"] == 0)],
        ),
    ):
        structures.append(summary_group(subset, label))
    tag_comparison = []
    for tag in ("Souls-like", "Cozy", "Metroidvania", "Difficult"):
        tagged = drop[drop["tags"].map(lambda values: tag in values)]
        comparison = drop[
            drop["genres"].map(lambda values: "Action" in values)
            & ~drop["tags"].map(lambda values: tag in values)
        ]
        tag_comparison.append(
            {
                "tag": tag,
                "tagged": summary_group(tagged, tag),
                "comparison": summary_group(comparison, f"Action且无{tag}标签"),
            }
        )
    difficulty = frame[frame["ach_count"] >= 5]
    histogram, edges = np.histogram(
        difficulty["median_percent"].dropna(), bins=np.arange(0, 101, 5)
    )
    reputation = valid_sample(frame, "drop_ratio").dropna(subset=["approval"])
    correlation_rows = []
    for left, right in (
        ("approval", "drop_ratio"),
        ("approval", "log_hours"),
        ("drop_ratio", "log_hours"),
    ):
        pair = reputation[[left, right]].dropna()
        correlation_rows.append(
            {
                "left": TARGETS[left],
                "right": TARGETS[right],
                "n": len(pair),
                "rho": correlation(pair[left], pair[right]),
            }
        )
    discordant_rows = popular_examples(reputation)
    text_summary = [
        {
            "category": category,
            "games_with_match": int((difficulty[f"text_{i}"] > 0).sum()),
            "median_share": float(difficulty[f"text_{i}"].median()),
            "rule": rule,
        }
        for i, (category, rule) in enumerate(TEXT_RULES.items())
    ]
    text_examples = []
    for example in metadata["text_examples"]:
        text_examples.append(
            {
                **example,
                "matches": [
                    name
                    for name, rule in TEXT_RULES.items()
                    if re.search(rule, example["description"], re.I)
                ],
            }
        )
    # 判断是否真出现符号反转；不为预设故事强行命名辛普森悖论。
    overall = type_rows[0]
    reversed_types = [
        r["type"] for r in type_rows[1:] if r["raw_slope"] * overall["raw_slope"] < 0
    ]
    drop_model = next(m for m in models if m["target"] == "drop_ratio")
    overall_model = next(
        m for m in drop_model["metrics"] if m["name"] == "整体稀有度 Ridge"
    )
    tail_model = next(m for m in drop_model["metrics"] if m["name"] == "尾部结构 Ridge")
    best_model = max(drop_model["metrics"], key=lambda m: m["r2"])
    delta = tail_model["r2"] - overall_model["r2"]
    sensitivity_rhos = [s["rho"] for s in sensitivity if s["rho"] is not None]
    covered = coverage[1]
    uncovered = coverage[2]
    extension_text = next(
        m for m in drop_model["metrics"] if m["name"] == "文本规则 Ridge"
    )
    extension_tags = next(
        m for m in drop_model["metrics"] if m["name"] == "标签交互 Ridge"
    )
    temporal_findings = [
        f"{m['label']}的随机森林随机五折R²={m['metrics'][-1]['r2']:.3f}，跨发售年代留出R²={m['temporal'][-1]['r2']:.3f}。"
        for m in models
        if m["temporal"]
    ]
    conclusions = {
        "overview": [
            f"固定快照包含 {len(frame):,} 款游戏；主线状态分析保留 {len(drop):,} 款（至少5个成就、100条Steam评价、20个通关/弃坑标记）。",
            f"成就稀有度与弃坑标记占比的 Spearman 相关为 {overall['rho']:.3f}；这是跨游戏关联，不表示提高难度会导致弃坑。",
            f"弃坑占比模型中，随机五折表现最高的是 {best_model['name']}，R²={best_model['r2']:.3f}。请结合时间留出结果判断推广能力。",
        ],
        "structure": [
            f"加入尾部结构后，Ridge 的交叉验证 R² 相比整体稀有度模型变化 {delta:+.3f}。"
            + (
                "尾部特征带来预测增益，但不能据此推断设计效果。"
                if delta > 0
                else "当前未观察到尾部特征的预测增益。"
            ),
            "低完成率混合挑战、可选内容、流程位置与投入；排序曲线不提供解锁时间。",
        ],
        "types": [
            f"整体稀有度每增加10点，未控制回归对应弃坑占比变化 {overall['raw_slope']:+.2f} 个百分点；加入控制特征后为 {overall['adjusted_slope']:+.2f} 个百分点。",
            f"类型内未控制斜率与整体反向的类型：{'、'.join(reversed_types) if reversed_types else '本次选取的类型中未出现'}。这只是描述性对照，不能单凭符号变化认定辛普森悖论。",
        ],
        "reputation": [
            f"在 {correlation_rows[0]['n']:,} 款联合样本中，好评率与弃坑标记占比的 Spearman 相关为 {correlation_rows[0]['rho']:.3f}。",
            "好评、时长与通关/弃坑状态分别描述口碑和参与方式，不合并成一个偏好总分。示例表是条件筛选结果，不是质量排行榜。",
        ],
        "models": [
            f"弃坑占比随机五折最佳模型 R²={best_model['r2']:.3f}，RMSE={best_model['rmse']:.3f}（比例单位）。负R²表示预测弱于该测试集均值参照。",
            *temporal_findings,
            "SHAP只解释随机森林在留出游戏上的预测；即使线性模型更好，也不把树模型归因当作因果解释或最终证据。",
        ],
        "robustness": [
            f"RAWG 覆盖 {frame['rawg_id'].notna().sum():,}/{len(frame):,} 款，主线有效状态样本仅 {len(drop):,} 款。覆盖率不等于每个指标的有效率。",
            f"覆盖与未覆盖游戏的Steam评价数中位数分别为 {covered['reviews']:,.0f} 与 {uncovered['reviews']:,.0f}；主线状态样本的发售年份中位数为 {coverage[3]['year']:.0f}，样本明显偏向较老且评价较多的作品。",
            f"五组门槛下，稀有度与弃坑占比的Spearman相关介于 {min(sensitivity_rhos):.3f}–{max(sensitivity_rhos):.3f}；本次比较中方向保持为正，但仅覆盖这些门槛下的有效游戏。",
            "覆盖比较与门槛敏感性量化适用范围，不能恢复未覆盖游戏的行为。时长为RAWG聚合字段，不解释为每位玩家的留存时间。",
        ],
        "extensions": [
            f"弃坑占比目标中，文本规则和固定标签交互相对结构Ridge的R²增量分别为 {extension_text['r2']-tail_model['r2']:+.4f}、{extension_tags['r2']-tail_model['r2']:+.4f}；探索增益不等于稳定或显著改善。",
            "文本类别来自可多标签的关键词规则，尚未独立人工验证；匹配率不等于真实内容占比，不能称为已验证的分类模型。",
            "标签交互与文本规则的增益使用相同五折比较；少数固定组合只作探索，不推广到所有标签组合。",
        ],
    }
    return {
        "metadata": {k: v for k, v in metadata.items() if k != "text_examples"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stories": build_stories(frame),
        "parameters": {
            "random_state": SEED,
            "folds": 5,
            "reviews_min": 100,
            "states_min": 20,
            "achievements_min": 5,
            "ridge_alpha": 10,
            "forest": {"trees": 160, "max_depth": 9, "min_leaf": 15},
            "temporal": "训练发售年份≤2022；测试2023–2025",
            "aggregation": "每款游戏等权",
        },
        "conclusions": conclusions,
        "sample_counts": {t: len(valid_sample(frame, t)) for t in TARGETS},
        "models": models,
        "types": type_rows,
        "structures": structures,
        "histogram": {
            "counts": histogram.tolist(),
            "edges": edges.tolist(),
            "n": len(difficulty),
        },
        "points": scatter_records(drop),
        "correlations": correlation_rows,
        "discordant": discordant_rows,
        "coverage": coverage,
        "sensitivity": sensitivity,
        "tag_comparison": tag_comparison,
        "text_summary": text_summary,
        "text_examples": text_examples,
        "description_coverage": float(difficulty["description_coverage"].mean()),
        "rawg_task_counts": frame["rawg_task_status"]
        .fillna("未安排任务")
        .value_counts()
        .to_dict(),
        "denominator_rho": correlation(drop["drop_ratio"], drop["all_status_drop"]),
        "tag_counts": dict(
            Counter(tag for tags in frame["tags"] for tag in tags).most_common(30)
        ),
    }


def strict_json(payload: Any) -> str:
    """将图表/numpy对象和非有限值规范化，输出浏览器可解析的严格JSON。"""
    intermediate = json.loads(
        json.dumps(payload, cls=PlotlyJSONEncoder, ensure_ascii=False)
    )

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    return json.dumps(
        clean(intermediate), ensure_ascii=False, allow_nan=False, indent=2
    )


def main() -> None:
    """提取或重放快照，执行实验并原子替换派生报告。"""
    parser = argparse.ArgumentParser(description="执行游戏级分析并更新 dashboard 报告")
    parser.add_argument("--version", help="重放已固定的快照，不重新查询源表")
    args = parser.parse_args()
    frame, metadata = (
        load_snapshot(args.version) if args.version else extract_snapshot()
    )
    print(f"固定数据版本: {metadata['version']} ({len(frame)}款)", flush=True)
    report = build_report(frame, metadata)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT_PATH.with_suffix(".tmp")
    temporary.write_text(strict_json(report), encoding="utf-8")
    temporary.replace(REPORT_PATH)
    print(f"报告已生成: {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
