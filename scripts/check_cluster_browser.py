"""验收 YMT 冻结汇总、逐图说明及桌面/手机真实渲染，不写数据库。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


def check_width(page: Page) -> None:
    """表格可以内部滚动，但整页不能横向溢出。"""
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def verify_sources(data: dict) -> None:
    """核对冻结汇总与原交付指纹、文件摘要及关键统计一致。"""
    root = Path(__file__).resolve().parents[1]
    for filename, digest in data["meta"]["sources"].items():
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == digest
    report = json.loads((root / "result/YMT/cluster-report.json").read_text())
    assert data["meta"]["fingerprint"] == report["指纹"]
    assert sum(row["games"] for row in data["clusters"]) == data["meta"]["games"]
    assert sum(row["sample_games"] for row in data["clusters"]) == 3105
    for row in data["clusters"]:
        original = report["第二遍"]["画像"][str(row["id"])]
        assert row["games"] == original["游戏数"]
        assert row["mean"] == original["均值解锁率"]
        assert abs(row["rare1"] - original["稀有<1%"] * 100) < 1e-9
        assert abs(row["common50"] - original["普及>50%"] * 100) < 1e-9
        assert abs(row["share"] - row["games"] / data["meta"]["games"]) < 0.0001
        assert len(row["density"]) == 40
        assert abs(sum(row["density"]) - 1) < 0.001
        assert row["examples"] == report["第二遍"]["代表游戏"][str(row["id"])][:2]


def check_report(page: Page, url: str, width: int, height: int, output: Path) -> None:
    """检查真实汇总的完整展示、逐图说明、图内导航和路由恢复。"""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url + "/#research/clusters", wait_until="networkidle")
    expect(page.locator("#clusterReport .cluster-shape")).to_have_count(5)
    expect(page.locator("#researchNav a")).to_have_count(5)
    expect(page.locator("#tabResearch")).to_have_class("tab active")
    expect(page.locator(".research-intro")).to_contain_text("图解报告")
    expect(page.locator("#clusterReport")).to_contain_text("40,357")
    expect(page.locator("#clusterReport")).to_contain_text("3,105")
    expect(page.locator("#clusterReport .cluster-game")).to_have_count(10)
    figures = page.locator("#clusterReport [data-cluster-chart]")
    expect(figures).to_have_count(10)
    for figure in figures.all():
        expect(figure.locator("figcaption p")).to_have_count(1)
        expect(figure.locator("figcaption")).to_contain_text("详情说明")
        expect(figure.locator("figcaption")).not_to_contain_text("怎么看")
        expect(figure.locator("figcaption")).not_to_contain_text("看图说话")
    expect(page.locator(".cluster-feature-table tbody tr")).to_have_count(5)
    expect(page.locator(".cluster-tag-table tbody tr")).to_have_count(10)
    expect(page.locator(".cluster-tag-table")).to_contain_text("2.79×")
    expect(page.locator(".cluster-shapes")).not_to_contain_text("好玩但入坑难型")
    expect(page.locator(".cluster-shapes")).not_to_contain_text("入门劝退型")
    expect(page.locator(".cluster-pca")).to_have_count(2)
    for guide in page.locator(".cluster-pca-guide").all():
        expect(guide.locator("dt")).to_have_count(5)
        for label in ("这张图画的是什么", "主成分 1、2 分别由什么组成", "横轴", "纵轴", "方差百分比", "平均值"):
            expect(guide).to_contain_text(label)
    expect(page.locator(".cluster-pca-guide")).to_have_count(2)
    expect(page.locator(".cluster-pca-inputs").first).to_contain_text("10 项指标")
    expect(page.locator(".cluster-pca-inputs").last).to_contain_text("8 项指标")
    expect(page.locator(".cluster-pca-inputs").last).to_contain_text("实际值比估计值高多少或低多少")
    for inputs in page.locator(".cluster-pca-inputs").all():
        expect(inputs.locator("li")).to_have_count(3)
        for text in ("成就总数", "标准差", "低于 1%", "超过 80%", "权重"):
            expect(inputs).to_contain_text(text)
    expect(page.locator("#clusterReport .cluster-method")).to_have_count(0)
    expect(page.locator("#clusterReport")).not_to_contain_text("换一批游戏重做，结果还像不像？")
    expect(page.locator("#clusterReport")).not_to_contain_text("这些结果是怎么来的？哪些话还不能说？")
    for text in ("1.00×", "2.00×", "0.50×", "10%", "20%", "5%"):
        expect(page.locator(".cluster-tag-key")).to_contain_text(text)
    expect(page.locator(".cluster-pca-names")).to_contain_text("原图类名对照")
    for image in page.locator(".cluster-pca img").all():
        image.scroll_into_view_if_needed()
        page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=image.element_handle())
    page.locator(".cluster-pca").first.screenshot(path=str(output / f"{width}-pca-tier.png"))
    page.locator(".cluster-pca").last.screenshot(path=str(output / f"{width}-pca-shape.png"))
    with page.expect_popup() as popup:
        page.locator(".cluster-pca-image").first.click()
    popup.value.wait_for_load_state()
    assert popup.value.url.endswith("/assets/research/ymt/tier-pca.png")
    popup.value.close()
    page.evaluate("scrollTo(0, 0)")
    page.wait_for_function("scrollY === 0")
    check_width(page)
    page.screenshot(path=str(output / f"{width}-top.png"))
    page.locator('[data-cluster-scroll="cluster-shape-2"]').click()
    expect(page).to_have_url(url + "/#research/clusters")
    expect(page.locator("#cluster-shape-2")).to_be_focused()
    page.locator("#cluster-shape-2").screenshot(path=str(output / f"{width}-shape.png"))
    for table in page.locator(".cluster-table-scroll").all():
        table.evaluate("node => { node.scrollLeft = node.scrollWidth; }")
        if width <= 390:
            assert table.evaluate("node => node.scrollLeft > 0")
    page.locator('[aria-labelledby="clusterTagsTitle"]').screenshot(
        path=str(output / f"{width}-tags.png")
    )
    page.evaluate("scrollTo(0, 0)")
    page.wait_for_function("scrollY === 0")
    page.screenshot(path=str(output / f"{width}-full.png"), full_page=True)
    check_width(page)
    page.locator(".cluster-game").first.click()
    expect(page).to_have_url(url + "/#explore/game/105600")
    expect(page.locator("#viewAnalysis")).to_be_visible()
    page.go_back(wait_until="networkidle")
    expect(page.locator("#clusterReport .cluster-shape")).to_have_count(5)
    page.locator('#researchNav a[href="#research/trends"]').click()
    expect(page.locator("#trendReport .trend-image")).to_have_count(4)
    page.locator('#researchNav a[href="#research/clusters"]').click()
    expect(page.locator("#clusterReport .cluster-shape")).to_have_count(5)
    page.reload(wait_until="networkidle")
    expect(page.locator("#clusterReport .cluster-shape")).to_have_count(5)
    check_width(page)


def main() -> None:
    """执行来源核对、四种视口、错误重试与脱离数据库的浏览器验收。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    parser.add_argument("--output", type=Path, default=Path("/tmp/achievement-clusters"))
    args = parser.parse_args()
    args.url = args.url.rstrip("/")
    args.output.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(reduced_motion="reduce")
        response = context.request.get(args.url + "/assets/research/ymt/cluster-data.json")
        assert response.ok and "application/json" in response.headers["content-type"]
        verify_sources(response.json())
        for filename in ("shape-pca.png", "tier-pca.png"):
            image = context.request.get(args.url + "/assets/research/ymt/" + filename)
            assert image.ok and image.headers["content-type"] == "image/png"
            original = Path(__file__).resolve().parents[1] / "result/YMT/figures" / filename
            assert image.body() == original.read_bytes()
        for asset in ("clusters.js", "clusters.css"):
            assert context.request.get(args.url + "/assets/" + asset).ok
        assert context.request.post(args.url + "/api/game/crawl").status == 404
        for width, height in ((1440, 1000), (768, 1024), (390, 844), (320, 740)):
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            check_report(page, args.url, width, height, args.output)
            page.close()
            print(f"PASS {width}px：逐图说明、内部滚动、游戏跳转、导航、刷新")
        failure = context.new_page()
        failure.on("pageerror", lambda error: errors.append(str(error)))
        path = "**/assets/research/ymt/cluster-data.json"
        failure.route(path, lambda route: route.fulfill(status=503, body="unavailable"))
        failure.goto(args.url + "/#research/clusters", wait_until="networkidle")
        expect(failure.locator(".cluster-error")).to_be_visible()
        failure.unroute(path)
        failure.get_by_role("button", name="重新加载", exact=True).click()
        expect(failure.locator(".cluster-shape")).to_have_count(5)
        failure.close()
        # 这里只模拟接口不可达，汇总仍从 Go 二进制真实读取。
        offline = context.new_page()
        offline.on("pageerror", lambda error: errors.append(str(error)))
        offline.route("**/api/**", lambda route: route.abort())
        offline.goto(args.url + "/#research/clusters", wait_until="networkidle")
        expect(offline.locator(".cluster-shape")).to_have_count(5)
        expect(offline.locator(".cluster-tag-table")).to_be_visible()
        offline.close()
        browser.close()
    assert not errors, errors
    print("PASS 来源摘要、指纹、汇总数值、加载失败重试、接口不可达时展示；无页面脚本错误")
    print(f"截图：{args.output}")


if __name__ == "__main__":
    main()
