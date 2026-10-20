"""验收 YJH 年份趋势冻结成果、原图与分母说明，不写数据库。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


def check_width(page: Page) -> None:
    """检查整页没有横向溢出。"""
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def verify_sources(data: dict) -> None:
    """核对交付摘要、数据版本、计数分母和中文标签来源。"""
    root = Path(__file__).resolve().parents[1]
    for filename, digest in data["meta"]["sources"].items():
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == digest
    source = root / "result/YJH/第二版"
    report = json.loads((source / "tag-trends.json").read_text())
    assert data["meta"]["input_sha256"] == report["meta"]["sha256"]
    assert data["meta"]["games"] == report["meta"]["games"] == 50925
    assert sum(row["games"] for row in data["coverage"].values()) == 50925
    assert data["coverage"] == report["coverage"]
    assert data["meta"]["plot_window"] == [2014, 2024]
    assert data["meta"]["growth_window"] == [2014, 2020]
    assert data["theme_growth"] == report["growth_by_dimension"]["题材设定"]["records"][:10]
    assert data["player_growth"] == report["growth_by_dimension"]["玩家模式与支持"]["records"]
    assert data["casual_comparison"] == next(
        row for row in report["main_genre"]["growth_wide_window"] if row["tag"] == "Casual"
    )
    translations = {
        row["英文原名"]: row["图中中文名"]
        for row in csv.DictReader(
            (source / "标签中英对照.csv").read_text(encoding="utf-8-sig").splitlines()
        )
    }
    translations.update(data["meta"]["label_overrides"])
    for tag, label in data["labels"].items():
        assert translations[tag] == label
    for row in data["theme_growth"] + data["player_growth"]:
        assert row["base_games"] >= data["meta"]["minimum_base_games"]
        assert abs(row["base_games"] / data["coverage"]["2014"]["with_tags"] * 100 - row["base_pct"]) < 0.006
        assert abs(row["end_games"] / data["coverage"]["2020"]["with_tags"] * 100 - row["end_pct"]) < 0.006
        assert abs(row["end_pct"] - row["base_pct"] - row["delta_pp"]) < 0.021
    for year in ("2014", "2024"):
        assert data["official_share"][year] == report["official_genre"]["share_pct"][year]


def check_report(page: Page, url: str, width: int, height: int, output: Path) -> None:
    """验收真实汇总、图片、逐图说明、导航与直链刷新。"""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url + "/#research/trends", wait_until="networkidle")
    expect(page.locator("#trendReport .trend-image")).to_have_count(4)
    expect(page.locator("#researchNav a")).to_have_count(5)
    expect(page.locator("#tabResearch")).to_have_class("tab active")
    expect(page.locator("#researchNav a[aria-current=page]")).to_have_attribute("href", "#research/trends")
    expect(page.locator(".research-intro")).to_contain_text("杨金辉")
    expect(page.locator(".research-intro")).to_contain_text("图解报告 · 2026-10-16")
    expect(page.locator(".trend-kpis")).to_contain_text("50,925")
    expect(page.locator(".trend-kpis")).to_contain_text("2014–2024")
    expect(page.locator(".trend-kpis")).to_contain_text("2014–2020")
    expect(page.locator(".trend-coverage-chart")).to_have_count(0)
    expect(page.locator("#trendReport")).not_to_contain_text("不同年份的游戏，标签齐不齐？")
    expect(page.locator('[data-trend-chart="genre"] .trend-figure-note')).to_contain_text("为什么没画 2025 年")
    expect(page.locator('[data-trend-chart="genre"] .trend-figure-note')).to_contain_text("34.4%")
    expect(page.locator('[data-trend-chart="genre"] .trend-figure-note')).to_contain_text("旧快照")
    figures = page.locator("#trendReport [data-trend-chart]")
    expect(figures).to_have_count(4)
    for figure in figures.all():
        expect(figure.locator("figcaption")).to_contain_text("详情说明")
        expect(figure.locator("figcaption")).not_to_contain_text("怎么看")
        expect(figure.locator("figcaption")).not_to_contain_text("看图说话")
    expect(page.locator("#trendReport .trend-guide")).to_have_count(0)
    expect(page.locator("#trendReport dt")).to_have_count(0)
    expect(page.locator('[data-trend-chart="genre"]')).to_contain_text("35.16%")
    expect(page.locator('[data-trend-chart="genre"]')).to_contain_text("44.71%")
    expect(page.locator(".trend-definition")).to_contain_text("统计范围不同")
    expect(page.locator('[data-trend-chart="theme"]')).to_contain_text("2.76 个百分点")
    expect(page.locator('[data-trend-chart="theme"]')).to_contain_text("57 款增到 233 款")
    expect(page.locator('[data-trend-chart="players"]')).to_contain_text("21.45%")
    expect(page.locator('[data-trend-chart="players"]')).to_contain_text("13.83%")
    expect(page.locator(".trend-label-key").first.locator("span")).to_have_count(10)
    expect(page.locator(".trend-label-key").last.locator("span")).to_have_count(7)
    expect(page.locator(".trend-label-key").first).to_contain_text("心理恐怖")
    expect(page.locator(".trend-label-key").last).to_contain_text("手柄支持")
    for image in page.locator(".trend-image img").all():
        image.scroll_into_view_if_needed()
        page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=image.element_handle())
    page.locator('[data-trend-chart="genre"]').screenshot(path=str(output / f"{width}-genre.png"))
    page.locator('[data-trend-chart="theme"]').screenshot(path=str(output / f"{width}-theme.png"))
    with page.expect_popup() as popup:
        page.locator(".trend-image").first.click()
    popup.value.wait_for_load_state()
    assert popup.value.url.endswith("/assets/research/yjh/genre-share.png")
    popup.value.close()
    page.evaluate("scrollTo(0, 0)")
    page.wait_for_function("scrollY === 0")
    check_width(page)
    page.screenshot(path=str(output / f"{width}-top.png"))
    page.screenshot(path=str(output / f"{width}-full.png"), full_page=True)
    page.locator('#researchNav a[href="#research/clusters"]').click()
    expect(page.locator("#clusterReport .cluster-shape")).to_have_count(5)
    page.locator('#researchNav a[href="#research/trends"]').click()
    expect(page.locator("#trendReport .trend-image")).to_have_count(4)
    page.locator('#researchNav a[href="#research/retention"]').click()
    expect(page.locator("#retFrame")).to_have_attribute("src", "/assets/research/lyx/WEB/index.html")
    page.go_back(wait_until="networkidle")
    expect(page.locator("#trendReport .trend-image")).to_have_count(4)
    page.reload(wait_until="networkidle")
    expect(page.locator("#trendReport .trend-image")).to_have_count(4)
    check_width(page)


def main() -> None:
    """核对真实交付，并验收四种视口、加载失败、独立展示和异步路由。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    parser.add_argument("--output", type=Path, default=Path("/tmp/achievement-trends"))
    args = parser.parse_args()
    args.url = args.url.rstrip("/")
    args.output.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(reduced_motion="reduce")
        response = context.request.get(args.url + "/assets/research/yjh/trend-data.json")
        assert response.ok and "application/json" in response.headers["content-type"]
        data = response.json()
        verify_sources(data)
        root = Path(__file__).resolve().parents[1]
        for figure in data["figures"]:
            image = context.request.get(args.url + "/assets/research/yjh/" + figure["file"])
            assert image.ok and image.headers["content-type"] == "image/png"
            assert image.body() == (root / figure["source"]).read_bytes()
        assert context.request.post(args.url + "/api/game/crawl").status == 404
        for width, height in ((1440, 1000), (768, 1024), (390, 844), (320, 740)):
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            check_report(page, args.url, width, height, args.output)
            page.close()
            print(f"PASS {width}px：四张原图、逐图说明、2025 年范围说明、标签翻译、导航与刷新")
        failure = context.new_page()
        failure.on("pageerror", lambda error: errors.append(str(error)))
        path = "**/assets/research/yjh/trend-data.json"
        failure.route(path, lambda route: route.fulfill(status=503, body="unavailable"))
        failure.goto(args.url + "/#research/trends", wait_until="networkidle")
        expect(failure.locator(".trend-error")).to_be_visible()
        failure.unroute(path)
        failure.get_by_role("button", name="重新加载", exact=True).click()
        expect(failure.locator(".trend-image")).to_have_count(4)
        failure.close()
        offline = context.new_page()
        offline.on("pageerror", lambda error: errors.append(str(error)))
        offline.route("**/api/**", lambda route: route.abort())
        offline.goto(args.url + "/#research/trends", wait_until="networkidle")
        expect(offline.locator(".trend-image")).to_have_count(4)
        offline.close()
        delayed = context.new_page()
        delayed.on("pageerror", lambda error: errors.append(str(error)))
        pending = []
        delayed.route(path, lambda route: pending.append(route))
        delayed.goto(args.url + "/#research/trends", wait_until="domcontentloaded")
        expect(delayed.locator("#trendReport [role=status]")).to_be_visible()
        delayed.locator('#researchNav a[href="#research/clusters"]').click()
        expect(delayed.locator("#clusterReport .cluster-shape")).to_have_count(5)
        assert len(pending) == 1
        pending[0].continue_()
        delayed.wait_for_load_state("networkidle")
        expect(delayed.locator("#trendReport")).to_have_count(0)
        delayed.locator('#researchNav a[href="#research/trends"]').click()
        expect(delayed.locator(".trend-image")).to_have_count(4)
        delayed.close()
        browser.close()
    assert not errors, errors
    print("PASS 来源摘要、原图字节、分母与端点、错误重试、API 不可达、请求中切换路由；无页面脚本异常")
    print(f"截图：{args.output}")


if __name__ == "__main__":
    main()
