import json
from http.server import ThreadingHTTPServer
import threading

import httpx
import pytest

from modeling.recommendation.graph_recommender import GraphRecommender
from modeling.recommendation.knowledge_graph import build_graph
from modeling.recommendation.knowledge_graph_inspector import GraphInspector
from modeling.recommendation.snapshot import save_snapshot
from process.deepseek_commentary import DeepSeekConfig
from process.site_service import make_handler
from test_deepseek_commentary import answer


@pytest.fixture
def server(tmp_path, request):
    rows = [
        dict(
            appid=i,
            name_en=f"Game {i}",
            name_zh=None,
            release_date="2020-01-01",
            ach_count=3,
            min_percent=1,
            mean_percent=20,
            max_percent=80,
            mapping_unresolved=False,
            tags=[dict(source="steamspy", kind="theme", tag="Exploration", votes=5)],
            genres=[],
            developers=[],
            publishers=[],
        )
        for i in [1, 2, 3]
    ]
    meta = save_snapshot(rows, {}, tmp_path / "snapshots")
    graph = build_graph(
        meta["version"], snapshots=tmp_path / "snapshots", folder=tmp_path / "kg"
    )
    base = GraphRecommender(
        GraphInspector(
            tmp_path / "kg" / graph["version"], snapshots=tmp_path / "snapshots"
        )
    )
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(answer(), ensure_ascii=False)
                        },
                    }
                ]
            },
        )

    # Inject only in tests; a real no-key server remains disabled.
    config = DeepSeekConfig.from_env(
        tmp_path / "absent.env",
        environ={
            "DEEPSEEK_API_KEY": "test-key",
            "COMMENTARY_PUBLIC_ORIGINS": getattr(request, "param", ""),
        },
    )
    handler = make_handler(
        base,
        meta,
        {"source": "test"},
        commentary_config=config,
        commentary_transport=httpx.MockTransport(transport),
    )
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{http.server_port}", trust_env=False
        ) as client:
            yield client, calls
    finally:
        http.shutdown()
        http.server_close()
        worker.join()


def test_explicit_post_generates_and_get_cannot_charge(server):
    client, calls = server
    assert client.get("/api/meta").json()["commentary"]["configured"]
    assert client.get("/api/commentary").status_code == 404
    payload = {"appids": [1], "candidate_appid": 2}
    first = client.post("/api/commentary", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "ok"
    assert first.json()["commentary"]["summary"] == answer()["summary"]
    assert client.post("/api/commentary", json=payload).json()["cached"]
    assert len(calls) == 1
    assert (
        "test-key" not in first.text and "test-key" not in client.get("/api/meta").text
    )


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_other_methods_remain_rejected(server, method):
    client, calls = server
    assert getattr(client, method)("/api/commentary").status_code == 405
    assert not calls


def test_cross_origin_and_bad_bodies_rejected_before_call(server):
    client, calls = server
    body = {"appids": [1], "candidate_appid": 2}
    assert (
        client.post(
            "/api/commentary", json=body, headers={"Origin": "https://foreign.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/commentary",
            content="x" * 5000,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/commentary", content="{", headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert client.post("/api/commentary", content="{}").status_code == 415
    assert (
        client.post(
            "/api/commentary", json={"appids": [1], "candidate_appid": 999}
        ).status_code
        == 400
    )
    assert client.post("/api/commentary?extra=1", json=body).status_code == 405
    assert not calls


@pytest.mark.parametrize("server", ["https://games.example.com"], indirect=True)
@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "games.example.com", "Origin": "https://games.example.com"},
        {"Origin": "https://games.example.com"},
        {"Host": "games.example.com"},
        {"Host": "games.example.com:443", "Origin": "https://games.example.com"},
    ],
)
def test_configured_same_origin_proxy_accepts_preserved_and_rewritten_host(
    server, headers
):
    client, calls = server
    result = client.post(
        "/api/commentary", json={"appids": [1], "candidate_appid": 2}, headers=headers
    )
    assert result.status_code == 200, result.text
    assert result.json()["commentary"]["reasons"] and len(calls) == 1


@pytest.mark.parametrize("server", ["https://games.example.com:8443"], indirect=True)
def test_explicit_public_port_is_respected(server):
    client, calls = server
    body = {"appids": [1], "candidate_appid": 2}
    assert (
        client.post(
            "/api/commentary",
            json=body,
            headers={
                "Host": "games.example.com:8443",
                "Origin": "https://games.example.com:8443",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/commentary",
            json=body,
            headers={
                "Host": "games.example.com",
                "Origin": "https://games.example.com",
            },
        ).status_code
        == 403
    )
    assert len(calls) == 1


@pytest.mark.parametrize("server", ["https://games.example.com"], indirect=True)
@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "foreign.example", "Origin": "https://games.example.com"},
        {"Host": "games.example.com", "Origin": "https://foreign.example"},
        {"Host": "games.example.com", "Origin": "http://games.example.com"},
        {"Host": "games.example.com", "Origin": "null"},
        {"Host": "games.example.com", "Origin": "https://games.example.com/evil"},
        {
            "Host": "foreign.example",
            "X-Forwarded-Host": "games.example.com",
            "X-Forwarded-Proto": "https",
        },
    ],
)
def test_untrusted_origin_host_and_forwarded_headers_never_call_provider(
    server, headers
):
    client, calls = server
    assert (
        client.post(
            "/api/commentary",
            json={"appids": [1], "candidate_appid": 2},
            headers=headers,
        ).status_code
        == 403
    )
    assert not calls


def test_public_domain_is_not_enabled_by_default(server):
    client, calls = server
    assert (
        client.post(
            "/api/commentary",
            json={"appids": [1], "candidate_appid": 2},
            headers={
                "Host": "games.example.com",
                "Origin": "https://games.example.com",
            },
        ).status_code
        == 403
    )
    assert not calls
