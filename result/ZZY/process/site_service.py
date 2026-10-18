"""单端口连接推荐、标签基线、图谱核查与单游戏解释，共享一次加载的输入。"""

from __future__ import annotations

import copy
from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import urlsplit

from modeling.recommendation import knowledge_graph_view, query_view, scoring_view, web
from modeling.recommendation.query_service import RecommendationQueryService
from .deepseek_commentary import CommentaryService, DeepSeekConfig, CommentaryError
from .commentary_access import allows_request


def make_handler(
    base,
    metadata: dict,
    provenance: dict,
    *,
    commentary_config=None,
    commentary_transport=None,
):
    """四个入口共用图谱/数据版本，不创建额外数据库连接或辅助端口。"""
    query = query_view.QueryViewService(RecommendationQueryService(base))
    commentary = CommentaryService(
        query,
        commentary_config or DeepSeekConfig.from_env(),
        transport=commentary_transport,
    )
    explanation = scoring_view.ExplanationService(base)
    baseline = web.RecommendationService(list(base.inspector._rows.values()), metadata)
    sections = {
        "/baseline": (web.route, baseline),
        "/graph": (knowledge_graph_view.route, base.inspector),
        "/explain": (scoring_view.route, explanation),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                url = urlsplit(self.path)
                if len(self.path) > 4096 or url.scheme or url.netloc:
                    self.respond(
                        400,
                        "application/json; charset=utf-8",
                        b'{"error":"Invalid request"}',
                    )
                    return
                if url.path in sections:
                    self.send_response(308)
                    self.send_header(
                        "Location",
                        url.path + "/" + ("?" + url.query if url.query else ""),
                    )
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                route, service, target = query_view.route, query, self.path
                for prefix, (candidate_route, candidate_service) in sections.items():
                    if url.path.startswith(prefix + "/"):
                        route, service = candidate_route, candidate_service
                        target = self.path[len(prefix) :]
                        break
                status, mime, body = route(service, target)
                if status == 200 and (
                    target in ("/api/meta", "/api/summary")
                    or (
                        route is knowledge_graph_view.route
                        and target.startswith("/api/pair?")
                    )
                ):
                    packet = json.loads(body)
                    packet["data_loading"] = copy.deepcopy(provenance)
                    if route is query_view.route:
                        packet["commentary"] = commentary.metadata()
                    if route is knowledge_graph_view.route:
                        packet["ranking_note"] = (
                            "本页核查游戏与标签、类型、开发商、发行商之间的事实关系，不计算推荐分数。"
                            "联合推荐和单游戏解释使用当前评分权重；共享事实本身不证明玩法相似。"
                        )
                    if route is scoring_view.route:
                        packet["limits"] = (
                            "本页展示单游戏真实图谱排名；多游戏、年份筛选和完整搜索可返回联合推荐页。权重未经独立人工效果验证。"
                        )
                    body = json.dumps(
                        packet, ensure_ascii=False, allow_nan=False
                    ).encode("utf-8")
            except Exception:
                status, mime, body = (
                    500,
                    "application/json; charset=utf-8",
                    b'{"error":"Service error"}',
                )
            self.respond(status, mime, body)

        def respond(self, status: int, mime: str, body: bytes) -> None:
            self.send_response(status)
            for name, value in {
                "Content-Type": mime,
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; img-src 'self' https://cdn.akamai.steamstatic.com; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            }.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self) -> None:
            body_read = False

            def packet(status, body):
                nonlocal body_read
                # Consume small rejected bodies before closing to avoid a TCP
                # reset hiding the error response on Windows. Never drain unbounded input.
                if (
                    not body_read
                    and self.command == "POST"
                    and not self.headers.get("Transfer-Encoding")
                ):
                    try:
                        discard = int(self.headers.get("Content-Length", "0"))
                        if 0 < discard <= 65536:
                            self.connection.settimeout(2)
                            self.rfile.read(discard)
                    except (ValueError, OSError):
                        pass
                    body_read = True
                self.respond(
                    status,
                    "application/json; charset=utf-8",
                    json.dumps(body, ensure_ascii=False).encode("utf-8"),
                )

            if self.command != "POST" or self.path != "/api/commentary":
                packet(405, {"error": "Method not allowed"})
                return
            try:
                if not allows_request(
                    self.headers.get("Host", ""),
                    self.headers.get("Origin"),
                    self.server.server_port,
                    commentary.config.public_origins,
                ):
                    packet(
                        403,
                        {
                            "error": "点评请求来源未获允许，请核对网站来源配置。",
                            "code": "origin_not_allowed",
                        },
                    )
                    return
                if (
                    self.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    != "application/json"
                ):
                    packet(415, {"error": "需要JSON请求。"})
                    return
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("请求格式无效。")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    packet(413, {"error": "点评请求过长或为空。"})
                    return
                self.connection.settimeout(15)
                raw = self.rfile.read(length)
                body_read = True
                body = json.loads(raw)
                packet(200, commentary.generate(body))
            except CommentaryError as exc:
                packet(exc.status, {"error": str(exc), "code": exc.code})
            except (ValueError, UnicodeError):
                packet(
                    400,
                    {
                        "error": "点评参数无效，请重新选择游戏。",
                        "code": "invalid_request",
                    },
                )
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                packet(
                    503,
                    {
                        "error": "点评暂时无法生成，下方推荐依据仍可使用。",
                        "code": "unavailable",
                    },
                )

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def log_message(self, *_args: object) -> None:
            pass

    return Handler
