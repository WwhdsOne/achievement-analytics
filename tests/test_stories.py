"""故事数字的缺失值、分母与固定版本契约。"""

import json

import numpy as np
import pandas as pd
import pytest

from modeling.regression import stories


def sample():
    return pd.DataFrame([
        dict(appid=413150, name_en="Stardew Valley", name_zh=None,
             ach_count=19, positive=984, negative=16, beaten=1112, dropped=1234),
        dict(appid=2, name_en="Many", name_zh="很多", ach_count=1000,
             positive=99, negative=0, beaten=None, dropped=4),
        dict(appid=3, name_en="Boundary", name_zh=None, ach_count=10,
             positive=100, negative=0, beaten=0, dropped=0),
        dict(appid=4, name_en="Missing", name_zh=None, ach_count=np.nan,
             positive=3, negative=None, beaten=None, dropped=None),
        dict(appid=5, name_en="Invalid", name_zh=None, ach_count=-1,
             positive=-3, negative=5, beaten=-2, dropped=3),
    ])


def test_story_counts_use_observed_valid_samples_and_strict_threshold():
    result = stories.build_stories(sample())
    assert result["achievements"]["sample_n"] == 3
    assert result["achievements"]["median_count"] == 19
    assert result["achievements"]["thousand_plus"] == 1
    assert result["achievements"]["leaders"][0]["appid"] == 2
    assert result["reviews"] == {
        "sample_n": 3, "under_100": 1, "under_100_ratio": 1 / 3,
        "median_count": 100.0,
    }
    featured = result["featured"]
    assert featured["name_zh"] == "星露谷物语"
    assert featured["approval"] == .984
    assert featured["beaten"] == 1112
    assert featured["dropped"] == 1234
    assert featured["state_total"] == 2346


def test_empty_samples_and_missing_status_never_become_zero_claims():
    empty = stories.build_stories(sample().iloc[:0])
    assert empty["achievements"]["leaders"] == []
    assert empty["achievements"]["median_count"] is None
    assert empty["reviews"]["under_100_ratio"] is None
    assert empty["featured"] is None
    rows = sample()
    rows.loc[0, "beaten"] = np.nan
    assert stories.build_stories(rows)["featured"] is None


def test_refresh_preserves_models_and_rejects_mixed_versions(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    metadata = {"version": "v1", "sha256": "abc"}
    monkeypatch.setattr(stories, "load_snapshot", lambda version: (sample(), metadata))
    original = {"metadata": metadata, "models": [{"score": .123}], "generated_at": "old"}
    path.write_text(json.dumps(original))
    stories.refresh_report("v1", path)
    updated = json.loads(path.read_text())
    assert updated["models"] == original["models"]
    assert updated["generated_at"] == "old"
    assert updated["stories"]["reviews"]["sample_n"] == 3
    original["metadata"] = {"version": "v2", "sha256": "different"}
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="版本"):
        stories.refresh_report("v1", path)
    assert path.read_bytes() == before
