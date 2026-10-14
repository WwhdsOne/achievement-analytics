"""独立浏览器验收；uv run --with playwright python scripts/check_dashboard_browser.py。"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    """验知名游戏互动、旧链接、缺失数据及桌面手机布局。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    parser.add_argument("--output", default="/tmp/achievement-dashboard-screenshots")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    pages = {"overview": "成就清单有多长", "reputation": "这些名作，口碑如何",
             "states": "喜欢，也可能放下", "beyond": "热门之外的世界"}
    results = []
    errors = []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=True,
        )
        context = browser.new_context()
        response = context.request.get(args.url + "/api/analysis")
        assert response.ok
        report = response.json()
        assert set(report) == {"metadata", "stories", "generated_at"}
        games = {row["appid"]: row for row in report["stories"]["familiar_games"]}
        for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
            page = context.new_page()
            page.set_viewport_size({"width": width, "height": height})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url + "/#analysis/overview", wait_until="networkidle")
            page.locator(".analysis-heading h1").wait_for()
            for key, title in pages.items():
                page.locator(f'#analysisNav a[href="#analysis/{key}"]').click()
                page.wait_for_function("expected => document.querySelector('.analysis-heading h1')?.textContent === expected", arg=title)
                assert page.locator('#analysisNav a[aria-current="page"]').count() == 1
                assert page.locator("#analysisNav a").count() == 4
                text = page.locator("#analysisPage").text_content()
                assert not re.search(r"随机森林|SHAP|Ridge|RMSE|R²|预测|模型|OOF", text)
                assert page.locator('script[src*="plotly"]').count() == 0
                if key == "overview":
                    assert page.locator(".game-bar-row").count() == len(games)
                    assert "81" in page.locator("#comparisonResult").inner_text()
                    page.select_option("#compareFirst", "1245620")
                    page.select_option("#compareSecond", "367520")
                    assert "42" in page.locator("#comparisonResult").inner_text()
                    assert "63" in page.locator("#comparisonResult").inner_text()
                    assert "0.7 倍" in page.locator("#comparisonResult").inner_text()
                    page.select_option("#compareFirst", "2358720")
                    page.select_option("#compareSecond", "814380")
                if key == "reputation":
                    assert "星露谷物语" in page.locator("#reputationResult h2").first.inner_text()
                    page.select_option("#reputationMetric", "reviews")
                    assert "黑神话：悟空" in page.locator("#reputationResult h2").first.inner_text()
                    page.select_option("#reputationMetric", "approval")
                if key == "states":
                    for appid in (814380, 1245620, 367520, 413150):
                        page.select_option("#stateGame", str(appid))
                        content = page.locator("#stateResult").inner_text()
                        assert games[appid]["name_zh"] in content
                        assert f'{games[appid]["beaten"]:,} 人' in content
                        assert f'{games[appid]["dropped"]:,} 人' in content
                if key == "beyond":
                    assert page.locator(".waffle-cell").count() == 100
                    assert page.locator(".waffle-cell.filled").count() == 70
                assert not page.locator(".method-details").evaluate("node => node.open")
                page.locator(".method-details summary").click()
                assert "用户不同" in page.locator(".method-details").inner_text()
                page.locator(".method-details summary").click()
                overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                assert not overflow, f"{label}/{key} horizontal overflow"
                page.evaluate("window.scrollTo(0,0)")
                page.screenshot(path=str(output / f"{label}-{key}.png"), full_page=True)
                results.append({"viewport": label, "page": key, "overflow": overflow})
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_function("location.hash === '#analysis/states'")
            page.go_forward(wait_until="domcontentloaded")
            page.wait_for_function("location.hash === '#analysis/beyond'")
            for old in ("models", "structure", "types", "robustness", "extensions"):
                page.goto(args.url + "/#analysis/" + old, wait_until="domcontentloaded")
                page.wait_for_function("location.hash === '#analysis/overview'")
                assert page.locator(".analysis-heading h1").inner_text() == pages["overview"]
            page.route("**/api/game?*", lambda route: route.fulfill(status=404, content_type="application/json", body='{"error":"test"}'))
            page.locator('.game-bars [data-game="1245620"]').click()
            assert page.locator("#viewGame").is_visible()
            assert page.locator("#appidInput").input_value() == "1245620"
            for tab, view in (("tabQueue", "viewQueue"), ("tabCloud", "viewCloud")):
                page.locator("#" + tab).click()
                assert page.locator("#" + view).is_visible()
            page.close()
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        fixture = copy.deepcopy(report)
        fixture["stories"] = None
        page.route("**/api/analysis", lambda route: route.fulfill(content_type="application/json", body=json.dumps(fixture)))
        page.goto(args.url + "/#analysis/overview", wait_until="networkidle")
        page.get_by_role("heading", name="请更新展示数据").wait_for()
        fixture["stories"] = {"familiar_games": [], "reviews": {"sample_n": 0}}
        page.reload(wait_until="networkidle")
        assert "没有有效的成就数量" in page.locator("#analysisPage").inner_text()
        page.locator('a[href="#analysis/states"]').click()
        assert "没有足够" in page.locator("#analysisPage").inner_text()
        page.locator('a[href="#analysis/beyond"]').click()
        assert page.locator(".waffle-cell").count() == 0
        page.unroute("**/api/analysis")
        page.route("**/api/analysis", lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"展示数据尚未生成"}'))
        page.reload(wait_until="networkidle")
        page.locator("#retryAnalysis").wait_for()
        page.unroute("**/api/analysis")
        page.locator("#retryAnalysis").click()
        page.locator(".waffle-cell").first.wait_for()
        assert not errors, errors
        browser.close()
    print(json.dumps({"checks": results, "screenshots": str(output), "page_errors": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
