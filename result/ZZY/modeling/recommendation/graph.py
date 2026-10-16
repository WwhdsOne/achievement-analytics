"""把真实共同标签组织成局部关系图，不增加推测关系。"""

from __future__ import annotations

from .ranking import RankingIndex


def build_graph(
    index: RankingIndex,
    query: set[str],
    results: list[dict],
    *,
    appid: int | None = None,
    max_tags: int = 8,
) -> dict:
    """最多展示指定数量的稀有共同标签；展示截断不改变任何推荐。"""
    shared = set().union(*(set(row["shared_tags"]) for row in results))
    selected = sorted(shared, key=lambda t: (index.frequency[t], t))[:max_tags]
    query_id = f"seed:{appid}" if appid is not None else "query:tags"
    seed = index.rows.get(appid, {})
    nodes = [
        {
            "id": query_id,
            "kind": "seed" if appid is not None else "query",
            "label": seed.get("name_zh") or seed.get("name_en") or "你的标签偏好",
        }
    ]
    edges = []
    for tag in selected:
        nodes.append({"id": f"tag:{tag}", "kind": "tag", "label": tag, "tag": tag})
        edges.append(
            {
                "source": query_id,
                "target": f"tag:{tag}",
                "relation": "has_tag" if appid is not None else "requests",
            }
        )
    for row in results:
        target = f"game:{row['appid']}"
        nodes.append(
            {"id": target, "kind": "game", "label": row["name"], "appid": row["appid"]}
        )
        for tag in selected:
            if tag in row["shared_tags"]:
                edges.append(
                    {"source": target, "target": f"tag:{tag}", "relation": "has_tag"}
                )
    return {
        "nodes": nodes,
        "edges": edges,
        "query_node": query_id,
        "total_shared_tags": len(shared),
        "shown_tags": len(selected),
        "note": "只展示部分共同标签；线表示标签归属/请求，完整理由见推荐卡片。",
    }
