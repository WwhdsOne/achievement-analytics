"""分析口径与特征工程的契约测试。"""

import numpy as np
import pandas as pd
import pytest


def test_popular_examples_use_chinese_names_and_keep_selection_thresholds():
    from modeling.regression.analysis import popular_examples

    frame = pd.DataFrame({
        "appid": [601150, 883710, 374320, 588650],
        "name_en": ["Devil May Cry 5", "Resident Evil 2", "Dark Souls III", "Dead Cells"],
        "name_zh": [None] * 4,
        "approval": [.96, .97, .89, .97],
        "drop_ratio": [.174, .112, .239, .518],
        "resolved_total": [1706, 2527, 2882, 100],
        "playtime": [10, 8, 30, 12],
    })
    rows = popular_examples(frame)
    assert [row["appid"] for row in rows] == [601150, 883710]
    assert [row["name_zh"] for row in rows] == ["鬼泣5", "生化危机2：重制版"]
    assert frame.loc[0, "name_zh"] is None
    frame.loc[0, "resolved_total"] = 49
    assert [row["appid"] for row in popular_examples(frame)] == [883710]


def test_status_denominator_does_not_treat_missing_as_zero():
    from modeling.regression.dataset import derive_metrics

    frame = pd.DataFrame({
        "beaten": [30, 0, np.nan, 10], "dropped": [10, 0, 5, 0],
        "owned": [200, 20, 1, np.nan], "playing": [4, 2, 1, 1],
        "positive": [90, 0, 20, 10], "negative": [10, 0, 0, 0],
        "playtime": [5, 0, np.nan, 10],
    })
    result = derive_metrics(frame)
    assert result.loc[0, "drop_ratio"] == .25
    assert result.loc[0, "resolved_total"] == 40
    assert np.isnan(result.loc[1, "drop_ratio"])
    assert np.isnan(result.loc[2, "drop_ratio"])
    assert np.isnan(result.loc[1, "log_hours"])
    assert result.loc[0, "approval"] == .9


def test_wilson_interval_handles_extremes_and_rejects_invalid_counts():
    from modeling.regression.analysis import wilson_interval

    low, high = wilson_interval(0, 20)
    assert low == pytest.approx(0)
    assert 0 < high < .2
    low, high = wilson_interval(20, 20)
    assert .8 < low < 1
    assert high == pytest.approx(1)
    assert wilson_interval(0, 0) == (None, None)
    with pytest.raises(ValueError):
        wilson_interval(21, 20)


def test_owners_interval_is_not_a_precise_sales_number():
    from modeling.regression.dataset import owners_midpoint

    assert owners_midpoint("5,000,000 .. 10,000,000") == 7500000
    assert np.isnan(owners_midpoint(None))
    assert np.isnan(owners_midpoint("unknown"))


def test_feature_matrix_excludes_outcomes_and_preserves_missing_price():
    from modeling.regression.analysis import feature_matrix

    frame = pd.DataFrame({
        "median_percent": [80, 20], "p10_percent": [10, 1],
        "hard_ratio": [.1, .4], "ultra_ratio": [0, .1],
        "spread": [30, 50], "ach_count": [20, 40], "year": [2020, 2021],
        "price_cents": [np.nan, 500], "is_free": [False, False],
        "owners": [None, "0 .. 20,000"], "reviews": [100, 200],
        "genres": [["Action"], ["RPG"]], "tags": [["Rogue-like"], []],
        "drop_ratio": [.5, .2], "playtime": [30, 10], "approval": [.9, .8],
    })
    matrix = feature_matrix(frame)
    assert np.isnan(matrix.loc[0, "现价 log1p"])
    assert matrix.loc[0, "成就稀有度"] == 20
    assert not set(matrix.columns) & {"drop_ratio", "playtime", "approval"}
    assert matrix.loc[0, "类型·Action"] == 1
    assert matrix.loc[0, "标签·Rogue-like"] == 1
    assert matrix.loc[1, "标签·Rogue-like"] == 0


def test_strict_json_removes_nonfinite_values():
    import json
    from modeling.regression.analysis import strict_json

    encoded = strict_json({"nested": [np.nan, np.inf, np.float64(2)]})
    assert json.loads(encoded) == {"nested": [None, None, 2]}
    assert "NaN" not in encoded and "Infinity" not in encoded
