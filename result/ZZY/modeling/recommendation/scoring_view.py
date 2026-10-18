"""真实排名的路径/分数解释台，默认本机8604；不改写评分或原页面。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .graph_recommender import GraphRecommender
from .knowledge_graph import FIELDS, GRAPHS, digest_file, json_text
from .knowledge_graph_inspector import FIELD_LABELS, GraphInspector
from .snapshot import SNAPSHOTS

ASSET_ROOT = Path(__file__).parent / "scoring_view_assets"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}
STATUS = {
    "matched": "有共同关系",
    "no_shared": "双方有数据，但没有共同实体",
    "both_missing": "双方均缺数据，证据不足",
    "seed_missing": "种子缺数据，证据不足",
    "candidate_missing": "候选缺数据，证据不足",
}


def build_explanation(ranking: dict, path_limit: int | None = 8) -> dict:
    """纯展示投影：保留完整原报告，只裁剪SVG引用，联合报告使用联合贡献。"""
    if path_limit is not None and (
        not isinstance(path_limit, int)
        or isinstance(path_limit, bool)
        or not 1 <= path_limit <= 200
    ):
        raise ValueError("显示路径上限须为1–200整数或None（全部）")
    explanations = []
    for result in ranking["results"]:
        seed_results = result.get("seed_contributions") or [
            dict(
                appid=ranking["query_appid"], weight=1.0, relations=result["relations"]
            )
        ]
        catalog, relations = [], []
        for seed in seed_results:
            for field, component in seed["relations"].items():
                score = component["weighted_score"] * seed["weight"]
                if not math.isclose(
                    math.fsum(p["contribution"] for p in component["paths"]),
                    component["weighted_score"],
                    rel_tol=0,
                    abs_tol=1e-12,
                ):
                    raise ValueError("路径贡献不能重建关系分数，拒绝展示")
                relations.append(
                    {
                        "seed_appid": seed["appid"],
                        "field": field,
                        "label": FIELD_LABELS[field],
                        "weight": component["weight"],
                        "seed_weight": seed["weight"],
                        "score": score,
                        "status": component["status"],
                        "status_note": STATUS[component["status"]]
                        + ("；权重0，不计分" if component["weight"] == 0 else ""),
                        "numerator": component["numerator"],
                        "denominator": component["denominator"],
                        "query_only_entities": copy.deepcopy(
                            component["query_only_entities"]
                        ),
                        "candidate_only_entities": copy.deepcopy(
                            component["candidate_only_entities"]
                        ),
                        "path_count": len(component["paths"]),
                    }
                )
                for index, path in enumerate(component["paths"]):
                    for side, appid in (
                        ("left_edge", seed["appid"]),
                        ("right_edge", result["appid"]),
                    ):
                        edge = path[side]
                        if (
                            not edge.get("source_verified")
                            or edge.get("relation_kind") != "source_fact"
                            or "score" in edge
                            or edge["subject"] != f"game:{appid}"
                            or edge["object"] != path["entity"]["id"]
                            or edge["predicate"] != FIELDS[field][2]
                            or path["predicate"] != edge["predicate"]
                        ):
                            raise ValueError("路径事实来源/方向未通过验证")
                    contribution = path.get("joint_contribution", path["contribution"])
                    if not math.isclose(
                        contribution,
                        path["contribution"] * seed["weight"],
                        rel_tol=0,
                        abs_tol=1e-12,
                    ):
                        raise ValueError("联合路径贡献与种子权重不一致")
                    catalog.append(
                        {
                            "key": f"{seed['appid']}:{field}:{path['entity']['id']}",
                            "seed_appid": seed["appid"],
                            "field": field,
                            "path_index": index,
                            "entity_id": path["entity"]["id"],
                            "name": path["entity"]["display_name"],
                            "predicate": path["predicate"],
                            "contribution": contribution,
                            "raw_contribution": path["contribution"],
                            "used_for_score": contribution > 0,
                            "left_fact_id": path["left_edge"]["id"],
                            "right_fact_id": path["right_edge"]["id"],
                        }
                    )
        catalog.sort(key=lambda p: (-p["contribution"], p["key"]))
        if not math.isclose(
            math.fsum(p["contribution"] for p in catalog),
            result["score"],
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("全部路径不能重建总分，拒绝展示")
        displayed = catalog if path_limit is None else catalog[:path_limit]
        nodes = {
            f"game:{result['appid']}": {
                "id": f"game:{result['appid']}",
                "type": "Game",
                "label": result["name"],
            }
        }
        edges = []
        for path in displayed:
            game_id = f"game:{path['seed_appid']}"
            nodes[game_id] = {
                "id": game_id,
                "type": "Game",
                "label": f"种子 {path['seed_appid']}",
            }
            nodes[path["entity_id"]] = {
                "id": path["entity_id"],
                "type": FIELDS[path["field"]][0],
                "label": path["name"],
            }
            for subject, fact_id in (
                (game_id, path["left_fact_id"]),
                (f"game:{result['appid']}", path["right_fact_id"]),
            ):
                edges.append(
                    {
                        "source": subject,
                        "target": path["entity_id"],
                        "predicate": path["predicate"],
                        "fact_id": fact_id,
                        "path_key": path["key"],
                        "relation_kind": "source_fact",
                    }
                )
        explanations.append(
            {
                "appid": result["appid"],
                "relations": relations,
                "path_catalog": catalog,
                "total_paths": len(catalog),
                "shown_paths": len(displayed),
                "shown_contribution": math.fsum(p["contribution"] for p in displayed),
                "hidden_contribution": math.fsum(
                    p["contribution"] for p in catalog[len(displayed) :]
                ),
                "display_graph": {"nodes": list(nodes.values()), "edges": edges},
            }
        )
    return {
        "ranking": copy.deepcopy(ranking),
        "explanations": explanations,
        "path_limit": path_limit,
        "presentation_only": True,
    }


class ExplanationService:
    """仅从已验证评分器生成当前排名解释，页面文件和算法均有版本绑定。"""

    def __init__(self, base: GraphRecommender) -> None:
        self.base = base
        self._assets = {
            url: (mime + "; charset=utf-8", (ASSET_ROOT / name).read_bytes())
            for url, (name, mime) in ASSETS.items()
        }
        self.binding = {
            "purpose": "actual_ranked_paths_readonly_presentation_v1",
            "algorithm_version": base.algorithm_version,
            "scoring_binding": copy.deepcopy(base.binding),
            "clip_policy": "display_only_full_ranking_and_paths_retained",
            "source_sha256": {
                "scoring_view.py": digest_file(Path(__file__)),
                **{
                    name: hashlib.sha256(self._assets[url][1]).hexdigest()
                    for url, (name, _) in ASSETS.items()
                },
            },
        }
        self.view_version = (
            "scoring-view-v1-"
            + hashlib.sha256(json_text(self.binding).encode("utf-8")).hexdigest()
        )

    def metadata(self) -> dict:
        """显示当前固定数据/评分版本，明确独立单种子解释台边界。"""
        self.base.inspector._check_unchanged()
        return {
            "view_version": self.view_version,
            "view_binding": copy.deepcopy(self.binding),
            "algorithm_version": self.base.algorithm_version,
            "candidate_games": len(self.base.rows),
            "limits": "本页展示单种子真实图谱排名；多游戏/年份/完整搜索页面接入留T3.2。权重未经独立人工效果验证。",
        }

    def explain(self, appid: int, top_k: int = 5, path_limit: int | None = 8) -> dict:
        """评分一次后仅作展示投影，完整贡献与双端来源不裁剪。"""
        report = build_explanation(self.base.recommend(appid, top_k), path_limit)
        report.update(
            view_version=self.view_version,
            view_binding=copy.deepcopy(self.binding),
            query_game={
                "appid": appid,
                "name": self.base.inspector.entities[f"game:{appid}"]["display_name"],
            },
        )
        for item in report["explanations"]:
            for node in item["display_graph"]["nodes"]:
                if node["type"] == "Game":
                    node["label"] = self.base.inspector.entities[node["id"]][
                        "display_name"
                    ]
        self.base.inspector._check_unchanged()
        return report


def route(service: ExplanationService, target: str) -> tuple[int, str, bytes]:
    """固定只读资源/GET接口，拒绝额外/重复/过长参数和任意文件访问。"""

    def encoded(value: dict, status: int = 200) -> tuple[int, str, bytes]:
        return (
            status,
            "application/json; charset=utf-8",
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        )

    try:
        if len(target) > 500:
            raise ValueError("请求参数过长")
        url = urlsplit(target)
        if url.path in ASSETS and not url.query:
            mime, payload = service._assets[url.path]
            return 200, mime, payload
        if url.path == "/api/meta" and not url.query:
            return encoded(service.metadata())
        if url.path == "/api/recommend":
            query = parse_qs(url.query, keep_blank_values=True, max_num_fields=3)
            if (
                "appid" not in query
                or set(query) - {"appid", "top_k", "path_limit"}
                or any(len(v) != 1 for v in query.values())
            ):
                raise ValueError("需要唯一appid和可选top_k/path_limit参数")
            if any(
                not re.fullmatch(r"[0-9]{1,10}", v[0])
                for k, v in query.items()
                if not (k == "path_limit" and v[0] == "all")
            ):
                raise ValueError("appid/数量须为有效整数，path_limit也可为all")
            limit = query.get("path_limit", ["8"])[0]
            return encoded(
                service.explain(
                    int(query["appid"][0]),
                    int(query.get("top_k", ["5"])[0]),
                    None if limit == "all" else int(limit),
                )
            )
        return encoded({"error": "没有这个页面或接口"}, 404)
    except ValueError as exc:
        return encoded({"error": str(exc)}, 400)


def make_handler(service: ExplanationService) -> type[BaseHTTPRequestHandler]:
    """创建无写入接口的本机HTTP处理器，严格CSP和no-store响应。"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                status, mime, body = route(service, self.path)
            except Exception:
                status, mime, body = (
                    500,
                    "application/json; charset=utf-8",
                    b'{"error":"Service error"}',
                )
            self.send_response(status)
            for name, value in {
                "Content-Type": mime,
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            }.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


def main() -> int:
    """完整验证指定图谱和快照后，只监听127.0.0.1，不自动连接云库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", type=int, default=8604)
    parser.add_argument("--folder", type=Path, default=GRAPHS)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    args = parser.parse_args()
    if not re.fullmatch(r"kg-v1-[a-f0-9]{64}", args.version):
        parser.error("无效图谱版本")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        service = ExplanationService(
            GraphRecommender(
                GraphInspector(args.folder / args.version, snapshots=args.snapshots)
            )
        )
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    except (OSError, ValueError, KeyError):
        print("启动失败：请检查完整图谱/冻结快照、版本和端口。", flush=True)
        return 1
    print(f"图谱推荐解释台 http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
