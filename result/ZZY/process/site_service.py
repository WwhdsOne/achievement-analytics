"""单端口连接推荐、标签基线、图谱核查与单游戏解释，共享一次加载的输入。"""
from __future__ import annotations

import copy
from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import urlsplit

from modeling.recommendation import knowledge_graph_view, query_view, scoring_view, web
from modeling.recommendation.query_service import RecommendationQueryService


def make_handler(base, metadata: dict, provenance: dict):
    """四个入口共用图谱/数据版本，不创建额外数据库连接或辅助端口。"""
    query = query_view.QueryViewService(RecommendationQueryService(base))
    explanation = scoring_view.ExplanationService(base)
    baseline = web.RecommendationService(list(base.inspector._rows.values()), metadata)
    sections = {
        '/baseline': (web.route, baseline),
        '/graph': (knowledge_graph_view.route, base.inspector),
        '/explain': (scoring_view.route, explanation),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                url = urlsplit(self.path)
                if len(self.path) > 4096 or url.scheme or url.netloc:
                    self.respond(400, 'application/json; charset=utf-8', b'{"error":"Invalid request"}')
                    return
                if url.path in sections:
                    self.send_response(308)
                    self.send_header('Location', url.path + '/' + ('?' + url.query if url.query else ''))
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                route, service, target = query_view.route, query, self.path
                for prefix, (candidate_route, candidate_service) in sections.items():
                    if url.path.startswith(prefix + '/'):
                        route, service = candidate_route, candidate_service
                        target = self.path[len(prefix):]
                        break
                status, mime, body = route(service, target)
                if status == 200 and (target in ('/api/meta', '/api/summary')
                                      or (route is knowledge_graph_view.route and target.startswith('/api/pair?'))):
                    packet = json.loads(body)
                    packet['data_loading'] = copy.deepcopy(provenance)
                    if route is knowledge_graph_view.route:
                        packet['ranking_note'] = ('本页核查游戏与标签、类型、开发商、发行商之间的事实关系，不计算推荐分数。'
                                                  '联合推荐和单游戏解释使用当前评分权重；共享事实本身不证明玩法相似。')
                    if route is scoring_view.route:
                        packet['limits'] = '本页展示单游戏真实图谱排名；多游戏、年份筛选和完整搜索可返回联合推荐页。权重未经独立人工效果验证。'
                    body = json.dumps(packet, ensure_ascii=False, allow_nan=False).encode('utf-8')
            except Exception:
                status, mime, body = 500, 'application/json; charset=utf-8', b'{"error":"Service error"}'
            self.respond(status, mime, body)

        def respond(self, status: int, mime: str, body: bytes) -> None:
            self.send_response(status)
            for name, value in {
                'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
                'X-Content-Type-Options': 'nosniff',
                'Content-Security-Policy': "default-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            }.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self) -> None:
            self.respond(405, 'application/json; charset=utf-8', b'{"error":"Read only"}')

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def log_message(self, *_args: object) -> None:
            pass

    return Handler
