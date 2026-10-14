"""只读图谱质量与来源页：独立本地入口，默认8603。"""

from __future__ import annotations

import argparse
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .knowledge_graph import GRAPHS
from .knowledge_graph_inspector import GraphInspector

ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
ASSET_ROOT = Path(__file__).parent / "kg_view_assets"


def route(inspector: GraphInspector, target: str) -> tuple[int, str, bytes]:
    """固定GET路由，无写入/任意文件访问或推荐接口。"""
    def encoded(value: dict, status: int = 200) -> tuple[int, str, bytes]:
        return status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")

    try:
        if len(target) > 500:
            raise ValueError("请求参数过长")
        url = urlsplit(target)
        if url.path in ASSETS and not url.query:
            name, mime = ASSETS[url.path]
            return 200, mime + "; charset=utf-8", (ASSET_ROOT / name).read_bytes()
        if url.path == "/api/summary" and not url.query:
            return encoded(inspector.summary())
        if url.path == "/api/pair":
            query = parse_qs(url.query, keep_blank_values=True, max_num_fields=4)
            if set(query) != {"left", "right"} or any(len(values) != 1 or not re.fullmatch(r"[0-9]{1,10}", values[0]) for values in query.values()):
                raise ValueError("请输入两个有效appid，每个参数只出现一次")
            return encoded(inspector.inspect_pair(int(query["left"][0]), int(query["right"][0])))
        return encoded({"error": "没有这个页面或接口"}, 404)
    except ValueError as exc:
        return encoded({"error": str(exc)}, 400)


def make_handler(inspector: GraphInspector) -> type[BaseHTTPRequestHandler]:
    """创建本机只读处理器，数据使用安全JSON和严格CSP输出。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                status, mime, body = route(inspector, self.path)
            except Exception:
                status, mime, body = 500, "application/json; charset=utf-8", b'{"error":"Service error"}'
            self.send_response(status)
            for name, value in {"Content-Type": mime, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                                "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items():
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
    """指定已构建版本，完整校验后仅监听loopback。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", type=int, default=8603)
    parser.add_argument("--folder", type=Path, default=GRAPHS)
    args = parser.parse_args()
    if not re.fullmatch(r"kg-v1-[a-f0-9]{64}", args.version):
        parser.error("无效图谱版本")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        inspector = GraphInspector(args.folder / args.version)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(inspector))
    except (OSError, ValueError, KeyError):
        print("启动失败：请检查图谱版本、完整冻结快照和端口。", flush=True)
        return 1
    print(f"图谱质量与来源 http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
