"""真实推荐服务的浏览器验收，不创建 pytest 用例或更改数据库。"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


def check_width(page: Page) -> None:
    """确认手机与桌面均无整页横向溢出。"""
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def main() -> None:
    """验收真实搜索、原排名、五方向路由、空结果和服务不可用状态。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/achievement-research")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context()
        metadata = context.request.get(args.url + "/api/research/recommendation/meta")
        assert metadata.ok, metadata.text()
        assert metadata.json()["candidate_games"] > 0
        assert (
            context.request.get(
                args.url + "/api/research/recommendation/commentary"
            ).status
            == 404
        )
        assert (
            context.request.post(
                args.url + "/api/research/recommendation/recommend"
            ).status
            == 404
        )
        assert context.request.post(args.url + "/api/game/crawl").status == 404
        for filename in (
            "current-knowledge-graph.png",
            "current-path-explanation.png",
            "ai-method-comparison.png",
            "ai-unknown-bounds.png",
        ):
            image = context.request.get(args.url + "/assets/research/zzy/" + filename)
            assert image.ok and image.headers["content-type"] == "image/png"
            assert image.body().startswith(b"\x89PNG\r\n\x1a\n")
        for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
            page = context.new_page()
            page.set_viewport_size({"width": width, "height": height})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url + "/#research/recommendation", wait_until="networkidle")
            expect(page.locator("#recService")).to_contain_text("已连接", timeout=30000)
            expect(page.locator("#researchNav a")).to_have_count(5)
            expect(page.locator("#tabResearch")).to_have_class("tab active")
            expect(page.locator("#recFigures .rec-figure")).to_have_count(4)
            expect(page.locator("#recFigures")).to_contain_text("2026-10-14")
            for target, view in (
                ("explore", "viewAnalysis"),
                ("overview", "viewCloud"),
                ("queue", "viewQueue"),
            ):
                page.locator(f'.research-dashboard-links a[href="#{target}"]').click()
                expect(page.locator("#" + view)).to_be_visible()
                page.locator("#tabResearch").click()
                expect(page.locator("#recSearch")).to_be_visible()
            for topic in ("trends", "clusters", "retention", "reputation"):
                page.locator(f'#researchNav a[href="#research/{topic}"]').click()
                expect(page.locator(".research-empty")).to_be_visible()
                expect(
                    page.locator("#researchNav a[aria-current=page]")
                ).to_have_attribute("href", "#research/" + topic)
                check_width(page)
            page.locator('#researchNav a[href="#research/recommendation"]').click()
            page.locator('[data-example="空洞骑士"]').click()
            expect(page.locator('[data-add="367520"]')).to_be_enabled(timeout=30000)
            page.locator('[data-add="367520"]').click()
            expect(page.locator('#recSelected [data-remove="367520"]')).to_be_visible()
            page.locator("#recSubmit").click()
            expect(page.locator(".rec-candidate")).to_have_count(5, timeout=60000)
            original = context.request.get(
                args.url
                + "/api/research/recommendation/recommend?appids=367520&top_k=5&path_limit=8"
            ).json()
            actual = page.locator("[data-recommendation]").evaluate_all(
                "nodes => nodes.map(n => Number(n.dataset.recommendation))"
            )
            assert actual == [game["appid"] for game in original["ranking"]["results"]]
            assert 367520 not in actual
            expect(page.locator(".rec-candidate .rec-cover img")).to_have_count(5)
            first_card = page.locator(".rec-candidate").first
            expect(first_card.locator(".rec-game-links a").first).to_have_attribute(
                "href", f"#explore/game/{actual[0]}"
            )
            expect(first_card.locator(".rec-game-links a").last).to_have_attribute(
                "href", f"https://store.steampowered.com/app/{actual[0]}/"
            )
            first_card.locator(".rec-cover").click()
            expect(page).to_have_url(args.url + f"/#explore/game/{actual[0]}")
            expect(page.locator("#viewAnalysis")).to_be_visible()
            page.locator("#tabResearch").click()
            expect(page.locator(".rec-candidate")).to_have_count(5)
            page.locator("#recFigures .rec-figure").last.scroll_into_view_if_needed()
            page.wait_for_function(
                "Array.from(document.querySelectorAll('#recFigures img')).every(img => img.complete && img.naturalWidth > 0)"
            )
            with page.expect_popup() as popup:
                page.locator("#recFigures .rec-figure a").first.click()
            popup.value.wait_for_load_state()
            assert popup.value.url.endswith(
                "/assets/research/zzy/current-knowledge-graph.png"
            )
            popup.value.close()
            page.evaluate("scrollTo(0, 0)")
            page.screenshot(
                path=str(args.output / f"{label}-recommendations.png"), full_page=True
            )
            page.locator(".rec-candidate summary").first.click()
            expect(page.locator(".rec-evidence").first).to_be_visible()
            expect(page.locator(".rec-table").first).to_be_visible()
            check_width(page)
            page.locator(".rec-source summary").first.click()
            expect(page.locator(".rec-source small").first).to_be_visible()

            page.route(
                "https://cdn.akamai.steamstatic.com/**", lambda route: route.abort()
            )
            first_cover = page.locator(".rec-candidate .rec-cover").first
            first_cover.locator("img").evaluate(
                "img => { img.hidden = false; img.src += '?unavailable=1'; }"
            )
            expect(first_cover).to_have_class("rec-cover cover-missing")
            expect(first_cover.locator("span")).to_be_visible()
            check_width(page)
            page.unroute("https://cdn.akamai.steamstatic.com/**")

            page.locator('[data-example="星露谷物语"]').click()
            expect(page.locator('[data-add="413150"]')).to_be_enabled(timeout=30000)
            page.locator('[data-add="413150"]').click()
            page.locator("#recYearMin").fill("2020")
            page.locator("#recYearMax").fill("2025")
            page.locator("#recCount").select_option("3")
            page.locator("#recSubmit").click()
            expect(page.locator(".rec-candidate")).to_have_count(3, timeout=60000)
            expect(page.locator("#recResults")).to_contain_text("2020–2025")
            expect(page.locator("#recResults")).to_contain_text("星露谷物语")
            assert not set(
                page.locator("[data-recommendation]").evaluate_all(
                    "nodes => nodes.map(n => Number(n.dataset.recommendation))"
                )
            ) & {367520, 413150}
            page.locator("#recYearMin").fill("2025")
            page.locator("#recYearMax").fill("2020")
            page.locator("#recSubmit").click()
            expect(page.locator("#recMessage")).to_contain_text("起始年份不能晚于")
            page.locator("#recYearMin").fill("1")
            page.locator("#recYearMax").fill("1")
            page.locator("#recSubmit").click()
            expect(page.locator("#recResults")).to_contain_text(
                "暂时没有合适的推荐", timeout=60000
            )
            page.reload(wait_until="networkidle")
            expect(page.locator("#recSearch")).to_be_visible()
            expect(page.locator("#recSubmit")).to_be_disabled()

            page.route(
                "**/api/research/recommendation/meta",
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"error":"推荐服务暂未就绪，请稍后重试。"}',
                ),
            )
            page.locator("[data-retry-meta]").click()
            expect(page.locator("#recService")).to_contain_text("暂未就绪")
            page.unroute("**/api/research/recommendation/meta")
            page.locator("[data-retry-meta]").click()
            expect(page.locator("#recService")).to_contain_text("已连接")
            page.locator("#tabAnalysis").click()
            expect(page.locator("#viewAnalysis")).to_be_visible()
            expect(page.locator("#viewResearch")).not_to_be_visible()
            page.locator("#tabResearch").click()
            expect(page.locator("#recSearch")).to_be_visible()
            page.goto(args.url + "/#research/unknown", wait_until="networkidle")
            expect(page).to_have_url(args.url + "/#research/recommendation")
            check_width(page)
            page.close()
            print(
                f"{label}: navigation, real ranking, multi-game filters, evidence, empty results, retry and routing passed"
            )
        browser.close()
    assert not errors, errors
    print("No browser JavaScript errors; screenshots:", args.output)


if __name__ == "__main__":
    main()
