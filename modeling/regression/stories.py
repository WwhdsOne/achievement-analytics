"""从固定游戏快照生成易读的数据故事，不拟合模型或查询云库。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from modeling.regression.dataset import REPORT_PATH, load_snapshot

FAMILIAR_GAMES = {
    2358720: "黑神话：悟空", 1245620: "艾尔登法环", 814380: "只狼：影逝二度",
    367520: "空洞骑士", 413150: "星露谷物语", 1086940: "博德之门3",
    292030: "巫师3：狂猎", 1174180: "荒野大镖客：救赎2",
    374320: "黑暗之魂3", 646570: "杀戮尖塔", 601150: "鬼泣5",
    883710: "生化危机2：重制版",
}


def familiar_games(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """整理预先选定的名作，各指标独立核验，缺失不补零。"""
    records = []
    indexed = frame.set_index("appid")
    for appid, name in FAMILIAR_GAMES.items():
        if appid not in indexed.index:
            continue
        row = indexed.loc[appid]
        counts = {
            key: int(row[key]) if pd.notna(row[key]) and np.isfinite(row[key])
            and row[key] >= 0 and row[key] % 1 == 0 else None
            for key in ("ach_count", "positive", "negative", "beaten", "dropped")
        }
        reviews = (counts["positive"] + counts["negative"]
                   if counts["positive"] is not None and counts["negative"] is not None else None)
        states = (counts["beaten"] + counts["dropped"]
                  if counts["beaten"] is not None and counts["dropped"] is not None else None)
        has_states = states is not None and states >= 20
        records.append({
            "appid": appid, "name_zh": name, "name_en": row.name_en,
            "ach_count": counts["ach_count"] if counts["ach_count"] else None,
            "reviews": reviews,
            "approval": counts["positive"] / reviews if reviews is not None and reviews >= 100 else None,
            "beaten": counts["beaten"] if has_states else None,
            "dropped": counts["dropped"] if has_states else None,
            "state_total": states if has_states else None,
        })
    return records


def _counts(values: pd.Series) -> pd.Series:
    """仅接受有限、非负的整数计数，缺失值保持无效。"""
    return values.notna() & np.isfinite(values) & values.ge(0) & values.mod(1).eq(0)


def build_stories(frame: pd.DataFrame) -> dict[str, Any]:
    """按各自有效样本统计成就、评价及预先指定的星露谷案例。"""
    achievements = frame[_counts(frame.ach_count) & frame.ach_count.gt(0)]
    leaders = achievements.sort_values(
        ["ach_count", "appid"], ascending=[False, True]
    ).head(5)
    reviews = frame[_counts(frame.positive) & _counts(frame.negative)]
    totals = reviews.positive + reviews.negative
    featured = None
    candidates = frame[
        frame.appid.eq(413150)
        & _counts(frame.positive) & _counts(frame.negative)
        & _counts(frame.beaten) & _counts(frame.dropped)
        & (frame.positive + frame.negative).ge(100)
        & (frame.beaten + frame.dropped).ge(20)
    ]
    if not candidates.empty:
        row = candidates.iloc[0]
        featured = {
            "appid": 413150, "name_zh": "星露谷物语", "name_en": "Stardew Valley",
            "approval": float(row.positive / (row.positive + row.negative)),
            "reviews": int(row.positive + row.negative),
            "beaten": int(row.beaten), "dropped": int(row.dropped),
            "state_total": int(row.beaten + row.dropped),
        }
    return {
        "familiar_games": familiar_games(frame),
        "achievements": {
            "sample_n": len(achievements),
            "median_count": float(achievements.ach_count.median()) if len(achievements) else None,
            "thousand_plus": int(achievements.ach_count.ge(1000).sum()),
            "leaders": [
                {"appid": int(row.appid), "name_en": row.name_en,
                 "name_zh": row.name_zh if pd.notna(row.name_zh) else None,
                 "ach_count": int(row.ach_count)}
                for row in leaders.itertuples()
            ],
        },
        "reviews": {
            "sample_n": len(totals), "under_100": int(totals.lt(100).sum()),
            "under_100_ratio": float(totals.lt(100).mean()) if len(totals) else None,
            "median_count": float(totals.median()) if len(totals) else None,
        },
        "featured": featured,
    }


def refresh_report(version: str, path: Path = REPORT_PATH) -> None:
    """核验版本与指纹后原子更新故事；保留原模型与其生成时间。"""
    frame, metadata = load_snapshot(version)
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "metadata": {key: value for key, value in metadata.items() if key != "text_examples"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if any(report.get("metadata", {}).get(key) != metadata[key]
           for key in ("version", "sha256")):
        raise ValueError("报告与快照版本不一致，请先生成对应版本的完整分析报告")
    report["stories"] = build_stories(frame)
    report["stories_generated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def main() -> None:
    """从已存在的固定快照更新故事，不重新训练或访问数据库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="已有报告对应的固定快照版本")
    args = parser.parse_args()
    refresh_report(args.version)
    print(f"故事已更新：{REPORT_PATH}")


if __name__ == "__main__":
    main()
