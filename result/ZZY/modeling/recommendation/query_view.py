"""多游戏、年份与完整快照搜索统一页；仅本机只读，默认8605。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import scoring_view
from .graph_recommender import GraphRecommender
from .knowledge_graph import GRAPHS, digest_file, json_text
from .knowledge_graph_inspector import GraphInspector
from .query_service import RecommendationQueryService
from .scoring_view import build_explanation
from .snapshot import SNAPSHOTS
from . import presentation_names

ASSET_ROOT = Path(__file__).parent / "query_view_assets"
ASSETS = {
    "/": ("discovery.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/discovery.js": ("discovery.js", "text/javascript"),
    "/commentary.js": ("commentary.js", "text/javascript"),
    "/renderer.js": ("renderer.js", "text/javascript"),
    "/style.css": ("discovery.css", "text/css"),
}


class QueryViewService:
    """连接现有查询服务和纯展示投影，保留全部原排名与版本绑定。"""

    def __init__(self, query: RecommendationQueryService) -> None:
        self.query = query
        self._assets = {
            url: (mime + "; charset=utf-8", (ASSET_ROOT / name).read_bytes())
            for url, (name, mime) in ASSETS.items()
        }
        self.binding = {
            "purpose": "multi_game_year_search_readonly_presentation_v1",
            "query_service_version": query.query_service_version,
            "query_binding": copy.deepcopy(query.binding),
            "clip_policy": "display_only_full_ranking_and_paths_retained",
            "source_sha256": {
                "query_view.py": digest_file(Path(__file__)),
                "scoring_view.py": digest_file(Path(scoring_view.__file__)),
                "presentation_names.py": digest_file(Path(presentation_names.__file__)),
                "display_names_zh.json": digest_file(presentation_names.NAME_PATH),
                **{
                    name: hashlib.sha256(self._assets[url][1]).hexdigest()
                    for url, (name, _) in ASSETS.items()
                },
            },
        }
        self.view_version = (
            "query-view-v1-"
            + hashlib.sha256(json_text(self.binding).encode("utf-8")).hexdigest()
        )

    def metadata(self) -> dict:
        """公开完整快照/候选范围和固定版本，明确效果证据边界。"""
        self.query.base.inspector._check_unchanged()
        return {
            "view_version": self.view_version,
            "view_binding": copy.deepcopy(self.binding),
            "algorithm_version": self.query.base.algorithm_version,
            "query_service_version": self.query.query_service_version,
            "snapshot_games": len(self.query._searchable),
            "candidate_games": len(self.query.base.rows),
            "limits": "仅搜索固定快照；1–3种子、年份先筛后评分。相似度不是喜欢概率，权重未经独立人工效果验证。",
        }

    def explain(
        self,
        seeds: list[int],
        *,
        year_min: int | None = None,
        year_max: int | None = None,
        top_k: int = 5,
        path_limit: int | None = 8,
    ) -> dict:
        """直接投影T2.3完整报告，联合分数及事实来源不做重新定义。"""
        if path_limit is not None and (
            not isinstance(path_limit, int)
            or isinstance(path_limit, bool)
            or not 1 <= path_limit <= 200
        ):
            raise ValueError("显示路径上限须为1–200整数或None")
        ranking = self.query.recommend(
            seeds, year_min=year_min, year_max=year_max, top_k=top_k
        )
        report = build_explanation(ranking, path_limit)
        report.update(
            query_games=copy.deepcopy(ranking["seed_checks"]),
            view_version=self.view_version,
            view_binding=copy.deepcopy(self.binding),
        )
        ids = set(seeds) | {r["appid"] for r in ranking["results"]}
        report["display_names"] = {
            str(appid): presentation_names.display_title(
                self.query.base.inspector._rows[appid]
            )
            for appid in sorted(ids)
        }
        for item in report["explanations"]:
            for node in item["display_graph"]["nodes"]:
                if node["type"] == "Game":
                    node["label"] = self.query.base.inspector.entities[node["id"]][
                        "display_name"
                    ]
        self.query.base.inspector._check_unchanged()
        return report


def route(service: QueryViewService, target: str) -> tuple[int, str, bytes]:
    """只接受固定资源和搜索/推荐GET；未知、重复和异常参数明确拒绝。"""

    def encoded(value: dict, status: int = 200) -> tuple[int, str, bytes]:
        return (
            status,
            "application/json; charset=utf-8",
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        )

    try:
        if len(target) > 4096:
            raise ValueError("请求参数过长")
        url = urlsplit(target)
        if url.path in ASSETS and not url.query:
            mime, body = service._assets[url.path]
            return 200, mime, body
        if url.path == "/api/meta" and not url.query:
            return encoded(service.metadata())
        if url.path not in ("/api/search", "/api/recommend"):
            return encoded({"error": "没有这个页面或接口"}, 404)
        params = parse_qs(url.query, keep_blank_values=True, max_num_fields=6)
        allowed = (
            {"q", "limit", "offset"}
            if url.path == "/api/search"
            else {"appids", "year_min", "year_max", "top_k", "path_limit"}
        )
        if set(params) - allowed or any(len(v) != 1 for v in params.values()):
            raise ValueError("不接受未知或重复参数")

        def integer(key: str, default: str) -> int:
            value = params.get(key, [default])[0]
            if not re.fullmatch(r"[0-9]{1,10}", value):
                raise ValueError(f"{key}须为有效整数")
            return int(value)

        if url.path == "/api/search":
            results = service.query.search(
                params.get("q", [""])[0], integer("limit", "20"), integer("offset", "0")
            )
            for game in results["results"]:
                game.update(presentation_names.display_title(game))
            return encoded(results)
        raw = params.get("appids", [""])[0]
        if not re.fullmatch(r"[0-9]{1,10}(?:,[0-9]{1,10}){0,9}", raw):
            raise ValueError("appids须为逗号分隔的1–3个唯一游戏appid")
        seeds = [int(s) for s in raw.split(",")]
        years = {
            k: None if not params.get(k, [""])[0] else integer(k, "")
            for k in ("year_min", "year_max")
        }
        limit = params.get("path_limit", ["8"])[0]
        return encoded(
            service.explain(
                seeds,
                **years,
                top_k=integer("top_k", "5"),
                path_limit=None if limit == "all" else integer("path_limit", "8"),
            )
        )
    except ValueError as exc:
        return encoded({"error": str(exc)}, 400)


def make_handler(service: QueryViewService) -> type[BaseHTTPRequestHandler]:
    """生成只读处理器，取消连接不影响后续请求；不提供写入路由。"""

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
            for key, value in {
                "Content-Type": mime,
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; img-src 'self' https://cdn.akamai.steamstatic.com; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            }.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


def main() -> int:
    """完整校验本地图谱和快照后只监听127.0.0.1，不读取云库配置。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", type=int, default=8605)
    parser.add_argument("--folder", type=Path, default=GRAPHS)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    args = parser.parse_args()
    if not re.fullmatch(r"kg-v1-[a-f0-9]{64}", args.version):
        parser.error("无效图谱版本")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        base = GraphRecommender(
            GraphInspector(args.folder / args.version, snapshots=args.snapshots)
        )
        service = QueryViewService(RecommendationQueryService(base))
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    except (OSError, ValueError, KeyError):
        print("启动失败：请检查完整图谱/冻结快照、版本和端口。", flush=True)
        return 1
    print(f"游戏寻迹统一推荐页 http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
