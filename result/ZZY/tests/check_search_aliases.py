"""使用显式本地冻结数据，核验交付版别名 HTTP 与桌面/手机操作；不连接数据库。"""
from __future__ import annotations

import argparse
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlencode
from urllib.request import urlopen

HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOME))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HOME / "runtime/search-alias-check")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from run import verify_sources
    from modeling.recommendation.game_aliases import ALIASES, ALIAS_PATH
    from modeling.recommendation.graph_recommender import GraphRecommender
    from modeling.recommendation.knowledge_graph_inspector import GraphInspector
    from modeling.recommendation.snapshot import load_snapshot
    from process.site_service import make_handler
    from playwright.sync_api import sync_playwright

    verified = verify_sources()
    snapshot_version = "recommendation-v1-c58f1d57439d2c28"
    graph_version = "kg-v1-f088d9b7c48edf0be3aa475f95ee744a62e70b5a4807861fe85541bdbbe84bc9"
    inspector = GraphInspector(args.data_root / "kg" / graph_version, snapshots=args.data_root / "snapshots")
    base = GraphRecommender(inspector)
    print("Loaded full frozen graph", flush=True)
    _, meta = load_snapshot(snapshot_version, args.data_root / "snapshots")
    catalog = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    # 维护参考英文名必须与本机输入一致，防止误绑到续作/重制版。
    for appid, aliases in ALIASES.items():
        assert appid in inspector._rows, ("missing_appid", appid)
        assert inspector._rows[appid]["name_en"] == catalog["games"][str(appid)]["name_en"], appid
        assert aliases and len(set(aliases)) == len(aliases), appid

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(base, meta, {"source": "explicit_local_frozen_snapshot"}))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    checks, errors = [], []

    def packet(path):
        with urlopen(origin + path, timeout=60) as response:
            assert response.status == 200
            return json.load(response)

    try:
        for appid, aliases in ALIASES.items():
            for alias in aliases:
                result = packet("/api/search?" + urlencode({"q": alias, "limit": 100}))
                matches = [r for r in result["results"] if r["appid"] == appid]
                assert len(matches) == 1 and alias in matches[0]["matched_aliases"], (appid, alias)
                assert matches[0]["name"] == (inspector._rows[appid]["name_zh"] or inspector._rows[appid]["name_en"])
                if appid in base.rows:
                    baseline = packet("/baseline/api/games?" + urlencode({"q": alias}))
                    assert appid in [r["appid"] for r in baseline], ("baseline", appid, alias)
                checks.append("http/" + str(appid) + "/" + alias)
        print("All 114 alias HTTP checks passed", flush=True)
        for appid in (1245620, 367520, 413150):
            actual = packet(f"/api/recommend?appids={appid}")["ranking"]
            expected = base.recommend(appid)
            assert [(r["appid"], r["score"]) for r in actual["results"]] == [(r["appid"], r["score"]) for r in expected["results"]]
            checks.append(f"unchanged_scores/{appid}")
        with sync_playwright() as tool:
            browser = tool.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe", headless=True)
            try:
                for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("response", lambda response: errors.append(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None)
                    page.goto(origin)
                    page.wait_for_function("() => !document.getElementById('searchButton').disabled")
                    for alias, appid in (("老头环", 1245620), ("空洞骑士", 367520), ("星露谷", 413150)):
                        page.locator("#searchText").fill(alias)
                        page.locator("#searchText").press("Enter")
                        row = page.locator("#searchResults .search-row").filter(has_text=f"{appid} ·")
                        row.wait_for()
                        assert "匹配别名" not in row.inner_text()
                        row.get_by_role("button", name="添加为种子").click()
                        checks.append(f"{label}/select/{alias}")
                    assert page.locator("#seedCount").inner_text() == "3 / 3"
                    with page.expect_response(lambda r: "/api/recommend?" in r.url) as response:
                        page.locator("#recommendButton").click()
                    assert response.value.status == 200
                    assert set(response.value.json()["ranking"]["query_appids"]) == {1245620, 367520, 413150}
                    page.locator("#result").wait_for(state="visible")
                    page.screenshot(path=str(args.output / f"{label}.png"), full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), label
                    checks.append(label + "/multi_recommend_and_layout")
                    page.goto(origin + "/baseline/")
                    page.locator("#examples button").first.wait_for()
                    page.locator("#gameSearch").fill("老头环")
                    shown_name = inspector._rows[1245620].get("name_zh") or inspector._rows[1245620]["name_en"]
                    option = page.locator("#gameOptions button").filter(has_text=shown_name)
                    option.wait_for()
                    assert "匹配别名" not in option.inner_text()
                    with page.expect_response(lambda r: "/api/recommend?" in r.url) as response:
                        option.click()
                    assert response.value.status == 200 and response.value.json()["query"]["appid"] == 1245620
                    checks.append(label + "/baseline_alias_to_recommend")
                    page.close()
                    print(label + " original-search UI checks passed", flush=True)
            finally:
                browser.close()
        assert not errors, errors
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    report = {"status": "passed", "evidence": "explicit_local_frozen_snapshot_not_live_database",
              "snapshot_version": snapshot_version, "snapshot_games": len(inspector._rows),
              "alias_games": len(ALIASES), "alias_terms": sum(map(len, ALIASES.values())),
              "alias_sha256": hashlib.sha256(ALIAS_PATH.read_bytes()).hexdigest(),
              "verified_source_files": verified, "checks": checks, "browser_errors": errors}
    (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
