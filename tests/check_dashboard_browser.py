"""独立浏览器验收；uv run --with playwright python tests/check_dashboard_browser.py。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    """核验导航、图表、筛选、报告缺失和移动端布局，并保存截图。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    parser.add_argument("--output", default="/tmp/achievement-dashboard-screenshots")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    pages = {
        "overview": "游戏里的意外发现", "structure": "成就结构", "types": "类型对照",
        "reputation": "口碑与参与度", "models": "模型归因",
        "robustness": "方法与数据质量", "extensions": "内容与标签",
    }
    results = []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=True,
        )
        for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url + "/#analysis/overview", wait_until="domcontentloaded")
            page.locator(".analysis-heading h1").wait_for()
            for key, title in pages.items():
                if key != "overview":
                    page.locator(".research-nav-details").evaluate("node => node.open = true")
                page.locator(f'#analysisNav a[href="#analysis/{key}"]').click()
                page.wait_for_function("expected => document.querySelector('.analysis-heading h1')?.textContent === expected", arg=title)
                page.wait_for_timeout(400)
                if key in ("structure", "types", "reputation", "models"):
                    page.locator(".analysis-plot .main-svg").first.wait_for()
                assert page.locator(".analysis-description").inner_text().strip()
                if key == "overview":
                    assert page.locator(".data-story").count() == 3
                    assert page.locator(".waffle-cell").count() == 100
                    assert page.locator(".waffle-cell.filled").count() == 70
                    assert "10,979" in page.locator(".story-achievements").inner_text()
                    assert "1,234 人" in page.locator(".story-stardew").inner_text()
                    assert not page.locator(".research-nav-details").evaluate("node => node.open")
                    assert not page.locator(".method-details").last.evaluate("node => node.open")
                    page.locator(".story-details summary").click()
                    assert page.locator(".story-details tbody tr").count() == 5
                    page.locator(".story-details summary").click()
                else:
                    assert page.locator(".findings li").count() >= 2
                assert page.locator('#analysisNav a[aria-current="page"]').count() == 1
                if key == "robustness":
                    assert page.get_by_role("heading", name="成就描述分类抽查", exact=True).count() == 1
                    assert "没有计算分类准确率" in page.locator("#analysisPage").inner_text()
                if key == "extensions":
                    assert page.get_by_role("heading", name="成就描述分类抽查", exact=True).count() == 0
                    assert page.get_by_role("heading", name="这些结果能说明什么", exact=True).count() == 1
                overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                assert not overflow, f"{label}/{key} horizontal overflow"
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(output / f"{label}-{key}.png"), full_page=True)
                if key == "structure":
                    page.select_option("#structureGenre", "RPG")
                    page.check("#showIntervals")
                    page.wait_for_timeout(150)
                if key == "models":
                    for target in ("log_hours", "approval", "drop_ratio"):
                        page.select_option("#modelTarget", target)
                        page.locator("#shapDependence .main-svg").first.wait_for()
                    page.locator("#shapFeature").select_option(index=1)
                results.append({"viewport": label, "page": key, "overflow": overflow})
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_function("location.hash === '#analysis/robustness'")
            page.go_forward(wait_until="domcontentloaded")
            page.wait_for_function("location.hash === '#analysis/extensions'")
            page.locator("#tabGame").click()
            assert page.locator("#viewGame").is_visible()
            page.locator("#tabQueue").click()
            assert page.locator("#viewQueue").is_visible()
            page.locator("#tabCloud").click()
            assert page.locator("#viewCloud").is_visible()
            assert not errors, errors
            page.close()
        # 旧报告和缺失故事样本有可读说明；首页不依赖 Plotly。
        page = browser.new_page()
        report = page.request.get(args.url + "/api/analysis").json()
        page.route("**/assets/plotly.min.js", lambda route: route.abort())
        page.goto(args.url + "/#analysis/overview", wait_until="domcontentloaded")
        page.locator(".data-story").first.wait_for()
        assert page.locator(".waffle-cell").count() == 100
        # 用只读失败响应代替单游戏云库查询，只验跳转和 appid。
        page.route("**/api/game?*", lambda route: route.fulfill(status=404, content_type="application/json", body='{"error":"test"}'))
        page.locator('.story-stardew [data-game="413150"]').click()
        assert page.locator("#viewGame").is_visible()
        assert page.locator("#appidInput").input_value() == "413150"
        report.pop("stories")
        page.route("**/api/analysis", lambda route: route.fulfill(content_type="application/json", body=json.dumps(report)))
        page.goto(args.url + "/#analysis/overview", wait_until="domcontentloaded")
        page.reload(wait_until="domcontentloaded")
        page.get_by_role("heading", name="这份报告还没有数据故事").wait_for()
        report["stories"] = {"achievements": {"sample_n": 0, "leaders": []},
                             "reviews": {"sample_n": 0, "under_100": 0, "under_100_ratio": None}, "featured": None}
        page.reload(wait_until="domcontentloaded")
        page.locator(".data-story").first.wait_for()
        assert "暂不展示这个案例" in page.locator(".story-stardew").inner_text()
        assert page.locator(".waffle-cell").count() == 0
        page.close()
        # 缺报告不白屏，重试可恢复。API层自身另有单测。
        page = browser.new_page()
        page.route("**/api/analysis", lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"分析报告尚未生成"}'))
        page.goto(args.url + "/#analysis/overview", wait_until="domcontentloaded")
        page.locator("#retryAnalysis").wait_for()
        assert "尚未生成" in page.locator(".analysis-status").inner_text()
        page.unroute("**/api/analysis")
        page.locator("#retryAnalysis").click()
        page.locator(".analysis-heading h1").wait_for()
        browser.close()
    print(json.dumps({"checks": results, "screenshots": str(output), "page_errors": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
