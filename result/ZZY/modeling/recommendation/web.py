"""本地离线推荐页：python -m modeling.recommendation.web --version <版本>。"""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .baseline import tag_set
from .game_aliases import (
    ALIASES,
    FAMILIAR_APPIDS,
    matched_aliases,
    normalize_search,
    search_fields,
)
from .graph import build_graph
from .ranking import METHODS, RankingIndex
from .snapshot import load_snapshot

ASSET_ROOT = Path(__file__).parent / "web_assets"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class RecommendationService:
    """一次加载有效候选与索引，后续请求不访问数据库或文件。"""

    def __init__(self, rows: list[dict], metadata: dict) -> None:
        self.index = RankingIndex(rows)
        self.metadata = metadata
        self._games = [
            {
                "appid": appid,
                "name": row.get("name_zh") or row["name_en"],
                "alias": next(iter(ALIASES.get(appid, ())), ""),
            }
            for appid, row in sorted(self.index.rows.items())
        ]
        self._searchable = [
            (r, search_fields(self.index.rows[r["appid"]])) for r in self._games
        ]
        display = {}
        for row in self.index.rows.values():
            for key, value in tag_set(row).items():
                display.setdefault(key, value)
        self._tags = [
            {"tag": display[key], "key": key, "games": count}
            for key, count in sorted(
                self.index.frequency.items(), key=lambda p: (-p[1], p[0])
            )
        ]

    def search(self, text: str) -> list[dict]:
        """搜索有效游戏名/便捷别名/appid；空查询给预设名作。"""
        if len(text) > 200:
            raise ValueError("搜索词过长")
        text = normalize_search(text)
        if not text:
            familiar = [r for r in self._games if r["appid"] in FAMILIAR_APPIDS]
            return familiar or self._games[:8]
        return [
            {**row, "matched_aliases": matched_aliases(row["appid"], text)}
            for row, fields in self._searchable
            if any(text in field for field in fields)
        ][:20]

    def tags(self) -> list[dict]:
        """列出可推荐候选中的真实SteamSpy主题标签。"""
        return self._tags

    def recommend(self, query: dict) -> dict:
        """验证入口，返回版本、真实推荐解释和局部标签图。"""
        appid, tags = query.get("appid"), query.get("tags")
        method = query.get("method", "jaccard")
        if (appid is None) == (tags is None) or method not in METHODS:
            raise ValueError("需要一种查询与有效方法")
        if appid is not None:
            if (
                isinstance(appid, bool)
                or not isinstance(appid, int)
                or appid not in self.index.rows
            ):
                raise ValueError("种子不在有效候选中")
            labels = self.index.labels[appid]
        else:
            if (
                not isinstance(tags, list)
                or not 1 <= len(tags) <= 20
                or any(
                    not isinstance(t, str) or not t.strip() or len(t) > 200
                    for t in tags
                )
            ):
                raise ValueError("标签无效")
            labels = {t.strip().casefold() for t in tags}
        return self._recommend(tuple(sorted(labels)), appid, method)

    @lru_cache(maxsize=128)
    def _recommend(
        self, labels: tuple[str, ...], appid: int | None, method: str
    ) -> dict:
        query = set(labels)
        results = self.index.neighbors(query, exclude=appid, method=method)
        return {
            "version": self.metadata["version"],
            "sha256": self.metadata["sha256"],
            "method": method,
            "query": {"appid": appid, "tags": list(labels)},
            "results": results,
            "graph": build_graph(self.index, query, results, appid=appid),
            "limits": "基于标签的相似与匹配，不是喜欢概率；尚未完成独立人工相关性评价。",
        }


def route(service: RecommendationService, target: str) -> tuple[int, str, bytes]:
    """固定只读路由，未知路径不映射任意本地文件。"""

    def encoded(value: dict | list, status: int = 200) -> tuple[int, str, bytes]:
        return (
            status,
            "application/json; charset=utf-8",
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
        )

    if len(target) > 4096:
        return encoded({"error": "请求过长，请减少标签。"}, 400)
    url = urlparse(target)
    params = parse_qs(url.query, keep_blank_values=True)
    try:
        if url.path in ASSETS:
            file, mime = ASSETS[url.path]
            return 200, mime, (ASSET_ROOT / file).read_bytes()
        if url.path == "/api/meta":
            return encoded(
                {
                    "version": service.metadata["version"],
                    "sha256": service.metadata["sha256"],
                    "candidates": len(service.index.rows),
                    "tags": len(service.tags()),
                    "familiar": service.search(""),
                }
            )
        if url.path == "/api/games":
            return encoded(service.search(params.get("q", [""])[0]))
        if url.path == "/api/tags":
            return encoded(service.tags())
        if url.path == "/api/recommend":
            query = {"method": params.get("method", ["jaccard"])[0]}
            if "appid" in params:
                query["appid"] = int(params["appid"][0])
            if "tags" in params:
                query["tags"] = params["tags"]
            return encoded(service.recommend(query))
    except (ValueError, TypeError, KeyError):
        return encoded(
            {"error": "查询无效：请选择列表中的游戏，或输入1–20个非空标签。"}, 400
        )
    return encoded({"error": "没有这个页面或接口。"}, 404)


def make_handler(service: RecommendationService) -> type[BaseHTTPRequestHandler]:
    """为本地只读服务创建固定资源HTTP处理器。"""

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
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'",
            )
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


def main() -> int:
    """校验指定本地快照后只监听loopback，不自动提取或连接云库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", type=int, default=8602)
    args = parser.parse_args()
    try:
        rows, metadata = load_snapshot(args.version)
        service = RecommendationService(rows, metadata)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    except (OSError, ValueError, KeyError):
        print("启动失败：请检查冻结快照是否完整、版本是否正确，以及端口是否占用。")
        return 1
    print(
        f"本地推荐页 http://127.0.0.1:{server.server_port} · {len(service.index.rows):,} 款候选",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
