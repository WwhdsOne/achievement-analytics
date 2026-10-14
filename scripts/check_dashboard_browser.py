"""游戏探索浏览器验收；uv run --with playwright python scripts/check_dashboard_browser.py。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


def open_search_tab(page: Page) -> None:
    """探索页默认停在「发现游戏」，搜索表单在另一个标签页里。"""
    page.locator('[data-explore-tab="search"]').click()
    expect(page.locator("#exploreInput")).to_be_visible()


def open_discover_tab(page: Page) -> None:
    """切回「发现游戏」标签页，供发现列表与随便逛逛使用。"""
    page.locator('[data-explore-tab="discover"]').click()
    expect(page.locator("#discoveryGames")).to_be_visible()


def lookup_game(page: Page, value: str, appid: int) -> None:
    """从统一搜索框打开游戏，并等待真实详情完成。"""
    open_search_tab(page)
    page.locator("#exploreInput").fill(value)
    page.locator("#exploreSearchBtn").click()
    expect(page.locator(".game-story-header")).to_be_visible(timeout=30000)
    expect(page.locator(".game-story-header .explore-eyebrow")).to_contain_text(str(appid))


def check_overflow(page: Page) -> None:
    """检查视口内没有整页横向溢出。"""
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"), "horizontal overflow"


def main() -> None:
    """验收真实搜索、随机、发现、详情、旧链接与错误状态。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    parser.add_argument("--output", default="/tmp/achievement-dashboard-screenshots")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    results: list[dict[str, object]] = []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context()
        response = context.request.get(args.url + "/api/explore?mode=popular")
        assert response.ok, response.text()
        popular = response.json()["games"]
        assert popular and all(g["reviews"] > 0 for g in popular)
        for _ in range(5):
            random = context.request.get(args.url + "/api/explore?mode=random")
            assert random.ok and len(random.json()["games"]) == 1
        assert context.request.post(args.url + "/api/game/crawl").status == 404
        for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
            page = context.new_page()
            page.set_viewport_size({"width": width, "height": height})
            # 验证总览与探索在词云 CDN 不可达时仍正常工作。
            page.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url + "/#explore", wait_until="networkidle")
            expect(page.locator("#discoveryGames .explore-game").first).to_be_visible(timeout=30000)
            assert page.locator("#tabGame").count() == 0
            assert "前500" not in page.locator("#viewAnalysis").inner_text()
            check_overflow(page)
            page.screenshot(path=str(output / f"{label}-explore.png"), full_page=True)

            before = page.locator("#discoveryGames [data-game]").evaluate_all("nodes => nodes.map(n => n.dataset.game).sort()")
            page.locator("#discoveryMetric").select_option("ach_count")
            after = page.locator("#discoveryGames [data-game]").evaluate_all("nodes => nodes.map(n => n.dataset.game).sort()")
            assert before == after
            for mode in ("free", "achievements", "popular"):
                page.locator(f'[data-discovery="{mode}"]').click()
                expect(page.locator("#discoveryGames .explore-game").first).to_be_visible(timeout=30000)

            open_search_tab(page)
            page.locator("#exploreInput").fill("Hollow Knight")
            page.locator("#exploreSearchBtn").click()
            expect(page.locator('#searchResults [data-game="367520"]')).to_be_visible(timeout=30000)
            page.locator('#searchResults [data-game="367520"]').click()
            expect(page.locator(".game-story-header")).to_be_visible(timeout=30000)
            expect(page.locator(".game-story-header .explore-eyebrow")).to_contain_text("367520")
            expect(page.locator(".tag-votes")).to_be_visible()
            assert not page.locator("#achCard").evaluate("node => node.open")
            page.locator("#achCard summary").click()
            expect(page.locator("#achBody tr").first).to_be_visible()
            assert page.locator("#achBody .api").count() == 0
            assert page.locator("#achBody tr").count() <= 50
            page.locator("#achNext").click()
            expect(page.locator("#achievementPageNote")).to_contain_text("第 2 / 2 页")
            first_name = page.locator("#achBody .disp").first.inner_text()
            page.locator("#achievementSearch").fill(first_name)
            expect(page.locator("#achievementPageNote")).to_contain_text("第 1 / 1 页")
            assert all(first_name.lower() in name.lower() for name in page.locator("#achBody .disp").all_inner_texts())
            page.locator("#achievementSearch").fill("")
            assert not page.locator("#resultCard").evaluate("node => node.open")
            page.locator("#resultCard summary").click()
            expect(page.locator("#gmeta")).to_contain_text("最近抓取")
            check_overflow(page)
            page.screenshot(path=str(output / f"{label}-game.png"), full_page=True)

            if label == "desktop":
                lookup_game(page, "664290", 664290)
                page.locator("#achCard summary").click()
                assert page.locator("#achBody tr").count() == 50
                expect(page.locator("#achievementPageNote")).to_contain_text("220 页")

            lookup_game(page, "367520", 367520)
            open_discover_tab(page)
            with page.expect_response("**/api/explore?mode=random"):
                page.locator("#randomGame").click()
            page.wait_for_function("!document.getElementById('randomGame').disabled")
            expect(page.locator(".game-story-header")).to_be_visible(timeout=30000)
            assert page.url.split("#")[-1].startswith("explore/game/")
            for tab, view in (("tabQueue", "viewQueue"), ("tabCloud", "viewCloud"), ("tabAnalysis", "viewAnalysis")):
                page.locator("#" + tab).click()
                expect(page.locator("#" + view)).to_be_visible()
                if tab == "tabCloud":
                    expect(page.locator("#tabCloud")).to_have_text("数据全景")
                    expect(page.locator(".overview-section")).to_have_count(5, timeout=30000)
                    assert page.locator("#cloudCanvas").count() == 0
                    assert page.locator("#tagCanvas").count() == 1
                    assert "玩家都在做哪类游戏" not in page.locator("#viewCloud").inner_text()
                    check_overflow(page)
                    page.evaluate("window.scrollTo(0,0)")
                    page.screenshot(path=str(output / f"{label}-overview.png"), full_page=True)
            page.goto(args.url + "/#cloud", wait_until="domcontentloaded")
            page.wait_for_function("location.hash === '#overview'")
            expect(page.locator(".overview-section")).to_have_count(5, timeout=30000)
            page.goto(args.url + "/#analysis/states", wait_until="networkidle")
            page.wait_for_function("location.hash === '#explore'")
            assert page.locator("#gameStory").is_hidden()
            page.goto(args.url + "/#game", wait_until="networkidle")
            page.wait_for_function("location.hash === '#explore'")
            results.append({"viewport": label, "search": True, "overview": True, "overflow": False})
            page.close()

        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url + "/#explore", wait_until="networkidle")
        page.route("**/api/game?appid=999999999", lambda route: route.fulfill(status=404, content_type="application/json", body='{"error":"not found"}'))
        page.route("**/api/explore?appid=999999999", lambda route: route.fulfill(status=404, content_type="application/json", body='{"error":"not found"}'))
        open_search_tab(page)
        page.locator("#exploreInput").fill("999999999")
        page.locator("#exploreSearchBtn").click()
        expect(page.locator("#gameStory")).to_contain_text("尚未收录", timeout=30000)
        assert page.locator("#achCard").is_hidden() and page.locator("#infoCard").is_hidden()
        lookup_game(page, "367520", 367520)
        page.route("**/api/explore?mode=free", lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"unavailable"}'))
        open_discover_tab(page)
        page.locator('[data-discovery="free"]').click()
        expect(page.locator('[data-retry="discovery"]')).to_be_visible()
        page.unroute("**/api/explore?mode=free")
        page.locator('[data-retry="discovery"]').click()
        expect(page.locator("#discoveryGames .explore-game").first).to_be_visible(timeout=30000)
        # 映射待核对时，不把内部名或可能错配的展示名用于正式展示。
        base = context.request.get(args.url + "/api/game?appid=367520").json()
        extra = context.request.get(args.url + "/api/explore?appid=367520").json()
        extra["mapping_unresolved"] = True
        extra["shared"] = []
        page.route("**/api/game?appid=367520", lambda route: route.fulfill(content_type="application/json", body=json.dumps(base)))
        page.route("**/api/explore?appid=367520", lambda route: route.fulfill(content_type="application/json", body=json.dumps(extra)))
        page.reload(wait_until="networkidle")
        expect(page.locator("#gameStory")).to_contain_text("成就名称映射待核对")
        assert page.locator(".achievement-tile").count() == 0
        page.locator("#achCard summary").click()
        expect(page.locator("#achBody .disp").first).to_have_text("名称待核对")
        page.unroute("**/api/explore?appid=367520")
        page.route("**/api/explore?appid=367520", lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"unavailable"}'))
        page.reload(wait_until="networkidle")
        expect(page.locator(".game-story-header")).to_be_visible()
        expect(page.locator("#gameStory")).to_contain_text("部分附加信息读取失败")
        assert page.locator(".achievement-tile").count() == 0
        # 总览失败可以重试；词云失败不影响统计内容。
        page.route("**/api/overview", lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"unavailable"}'))
        page.goto(args.url + "/#overview", wait_until="domcontentloaded")
        expect(page.locator("#overviewRetry")).to_be_visible()
        page.unroute("**/api/overview")
        page.locator("#overviewRetry").click()
        expect(page.locator(".overview-section")).to_have_count(5, timeout=30000)
        page.close()
        assert not errors, errors
        browser.close()
    print(json.dumps({"checks": results, "screenshots": str(output), "page_errors": errors, "write_api": 404}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
