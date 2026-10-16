"""只用 SteamSpy theme 标签的 Jaccard 推荐对照，不训练模型。"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any


def tag_set(row: dict) -> dict[str, str]:
    """标签去空白、忽略大小写去重，保留展示词形；忽略其他来源与平台标签。"""
    result = {}
    for item in row.get("tags") or []:
        if (
            isinstance(item, dict)
            and item.get("source") == "steamspy"
            and item.get("kind") == "theme"
            and isinstance(item.get("tag"), str)
        ):
            value = item["tag"].strip()
            if value:
                result.setdefault(value.casefold(), value)
    return result


def eligible(row: dict) -> bool:
    """推荐仅使用范围内、身份与成就摘要有效且映射已解决的游戏。"""
    try:
        released = date.fromisoformat(row["release_date"])
        return (
            isinstance(row.get("appid"), int)
            and not isinstance(row["appid"], bool)
            and row["appid"] > 0
            and bool((row.get("name_zh") or row.get("name_en") or "").strip())
            and released < date(2026, 1, 1)
            and row.get("mapping_unresolved") is False
            and isinstance(row.get("ach_count"), int)
            and row["ach_count"] > 0
            and all(
                isinstance(row.get(key), (int, float)) and 0 <= row[key] <= 100
                for key in ("min_percent", "max_percent", "mean_percent")
            )
            and row["min_percent"] <= row["mean_percent"] <= row["max_percent"]
            and bool(tag_set(row))
        )
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def candidate_rows(rows: list[dict]) -> list[dict]:
    """重复 appid 整组排除，避免任意选取一条污染结果。"""
    counts = Counter(row.get("appid") for row in rows)
    return [row for row in rows if counts[row.get("appid")] == 1 and eligible(row)]


def recommend(
    rows: list[dict],
    *,
    appid: int | None = None,
    tags: list[str] | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """按种子游戏或标签集合推荐，返回共同标签及可复算的交并集计数。"""
    if (appid is None) == (tags is None) or not 1 <= top_k <= 100:
        raise ValueError("指定一种查询：appid 或 tags；top-k 须在 1–100 之间")
    candidates = candidate_rows(rows)
    if appid is not None:
        seed = next((row for row in candidates if row["appid"] == appid), None)
        if seed is None:
            raise ValueError("种子游戏不存在或未通过推荐数据检查；请查看质量报告")
        query = tag_set(seed)
    else:
        query = {
            value.strip().casefold(): value.strip()
            for value in tags
            if isinstance(value, str) and value.strip()
        }
        if not query:
            raise ValueError("至少提供一个非空标签")
    results = []
    for row in candidates:
        if row["appid"] == appid:
            continue
        labels = tag_set(row)
        shared = query.keys() & labels.keys()
        if not shared:
            continue
        union = query.keys() | labels.keys()
        results.append(
            {
                "appid": row["appid"],
                "name": row.get("name_zh") or row["name_en"],
                "score": len(shared) / len(union),
                "shared_tags": sorted(labels[key] for key in shared),
                "intersection_count": len(shared),
                "union_count": len(union),
                "candidate_tag_count": len(labels),
                "query_tag_count": len(query),
                "reason": f"共同标签 {len(shared)} 个 / 合并标签 {len(union)} 个",
            }
        )
    return sorted(results, key=lambda row: (-row["score"], row["appid"]))[:top_k]
