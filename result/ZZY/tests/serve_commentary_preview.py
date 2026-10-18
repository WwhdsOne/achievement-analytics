"""Run an offline browser-test server with external commentary calls disabled."""

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path

from modeling.recommendation.graph_recommender import GraphRecommender
from modeling.recommendation.knowledge_graph_inspector import GraphInspector
from modeling.recommendation.snapshot import load_snapshot
from modeling.recommendation.snapshot import save_snapshot
from modeling.recommendation.knowledge_graph import build_graph
from process.deepseek_commentary import DeepSeekConfig
from process.site_service import make_handler

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--port", type=int, default=8618)
    args = parser.parse_args()
    rows, _ = load_snapshot(
        "recommendation-v1-c58f1d57439d2c28", args.data_root / "snapshots"
    )
    seed = next(r for r in rows if r["appid"] == 367520)
    sample = [seed] + [
        r
        for r in rows
        if r["appid"] != 367520
        and any(
            t.get("tag") == "Exploration"
            for t in (r.get("tags") or [])
            if isinstance(t, dict)
        )
    ][:12]
    fixture = Path(__file__).resolve().parents[1] / "runtime/commentary-preview-fixture"
    meta = save_snapshot(
        sample, {"purpose": "browser_layout_sample"}, fixture / "snapshots"
    )
    graph = build_graph(
        meta["version"], snapshots=fixture / "snapshots", folder=fixture / "kg"
    )
    inspector = GraphInspector(
        fixture / "kg" / graph["version"], snapshots=fixture / "snapshots"
    )
    handler = make_handler(
        GraphRecommender(inspector),
        meta,
        {"source": "offline_browser_test"},
        commentary_config=DeepSeekConfig(),
    )
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(
            f"Offline browser-test server http://127.0.0.1:{server.server_port}",
            flush=True,
        )
        server.serve_forever()
