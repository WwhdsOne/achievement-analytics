"""验收 LYX 的「实际完成曲线与游戏用户粘性」板块，不写数据库。

板块是 LYX 原始交付页的 iframe 嵌入，所以核三件事：面板里的副本与源文件逐字节一致、
iframe 里那页真的跑起来了、页内那些相对链接（21 张原图 + 35 份来源明细 + 3 份文档）都点得开。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "result" / "LYX"
BUNDLE = ROOT / "dashboard" / "lyx"
ENTRY = "/assets/research/lyx/WEB/index.html"

# 抽样覆盖三类相对链接：文档、T1 原图、T2 原图、来源明细表
SAMPLES = [
    # .md 走 text/plain（浏览器里当纯文本读，点击即看，不会被下载），与 LYX 原交付一致
    ("docs/ANALYSIS.md", "text/plain"),
    ("analysis/T1Core/figures/01_game_stages.png", "image/png"),
    ("analysis/T2Sum/figures/21_peer_cases.png", "image/png"),
    ("analysis/T1Core/output/game_metrics.csv", "text/csv"),
    ("analysis/T2Sum/output/benchmark/peer_coverage.csv", "text/csv"),
]


def check_width(page: Page) -> None:
    """外层页面不能横向溢出；原页自己的横向滚动在 iframe 内部。"""
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def collect_expected() -> list[str]:
    """与 scripts/sync_lyx_bundle.py 同源的清单：入口 + 文档 + 21 张图 + 35 份来源文件。"""
    text = (SOURCE / "WEB" / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script id="lyx-data" type="application/json">(.*?)</script>', text, re.S).group(1))
    files = ["WEB/index.html", "docs/ANALYSIS.md", "docs/INSTRUCT.md", "docs/experiments.md"]
    for directory in ("analysis/T1Core/figures", "analysis/T2Sum/figures"):
        files += [f"{directory}/{p.name}" for p in sorted((SOURCE / directory).glob("*.png"))]
    files += [row["path"] for row in data["meta"].get("source_files") or []]
    return files


def verify_bundle() -> None:
    """面板里的副本必须与源逐字节一致——否则用户看到的是过期内容。"""
    files = collect_expected()
    stale = [name for name in files if (BUNDLE / name).read_bytes() != (SOURCE / name).read_bytes()]
    assert not stale, f"面板副本已过期，重跑 scripts/sync_lyx_bundle.py：{stale[:5]}"
    assert len(files) == 60, len(files)
    total = sum((SOURCE / name).stat().st_size for name in files)
    assert total > 15 * 1024 * 1024


def check_report(page: Page, url: str, width: int, height: int, output: Path) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url + "/#research/retention", wait_until="networkidle")
    expect(page.locator("#retentionReport")).to_be_visible()
    expect(page.locator(".research-empty")).to_have_count(0)
    expect(page.locator("#tabResearch")).to_have_class("tab active")
    expect(page.locator("#researchNav a[aria-current=page]")).to_have_attribute("href", "#research/retention")
    expect(page.locator(".research-intro")).to_contain_text("刘宇翔")
    expect(page.locator(".research-intro")).to_contain_text("原始交付页 · 2026-10-20")
    expect(page.locator("#retFrame")).to_have_attribute("src", ENTRY)

    # iframe 里那页真的渲染了：标题、六段导航、游戏选择器
    frame = page.frame_locator("#retFrame")
    expect(frame.locator("body")).to_be_visible(timeout=30000)
    expect(frame.locator("body")).to_contain_text("玩到哪里")
    for label in ("指标与过程", "玩法", "投入", "口碑", "同类", "依据"):
        expect(frame.locator("body")).to_contain_text(label)

    # 全屏切换
    toggle = page.locator("#retFullscreen")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    toggle.click()
    expect(page.locator("#retentionReport")).to_have_class(re.compile("is-fullscreen"))
    expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(toggle).to_contain_text("退出全屏")
    page.keyboard.press("Escape")
    expect(page.locator("#retentionReport")).not_to_have_class(re.compile("is-fullscreen"))
    expect(toggle).to_contain_text("全屏查看")

    # 新标签页出口
    expect(page.locator("#retentionReport .ret-open")).to_have_attribute("href", ENTRY)

    # 路由往返
    page.locator('#researchNav a[href="#research/clusters"]').click()
    expect(page.locator("#clusterReport .cluster-shape")).to_have_count(5)
    page.locator('#researchNav a[href="#research/retention"]').click()
    expect(page.locator("#retFrame")).to_have_attribute("src", ENTRY)

    page.evaluate("scrollTo(0, 0)")
    check_width(page)
    page.screenshot(path=str(output / f"{width}-top.png"))
    page.screenshot(path=str(output / f"{width}-full.png"), full_page=True)


def main() -> None:
    """核对副本字节、相对链接可达、iframe 渲染与全屏行为。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8601")
    parser.add_argument("--output", type=Path, default=Path("/tmp/achievement-retention"))
    args = parser.parse_args()
    args.url = args.url.rstrip("/")
    args.output.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    verify_bundle()

    with sync_playwright() as tool:
        browser = tool.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(reduced_motion="reduce")

        entry = context.request.get(args.url + ENTRY)
        assert entry.ok and "text/html" in entry.headers["content-type"]
        assert entry.body() == (BUNDLE / "WEB/index.html").read_bytes()
        assert hashlib.sha256(entry.body()).hexdigest() == hashlib.sha256((SOURCE / "WEB/index.html").read_bytes()).hexdigest()

        # 从持久化版本提供时也要逐个核对全部附件，不能只相信本机副本或服务器清单。
        for rel in collect_expected():
            response = context.request.get(f"{args.url}/assets/research/lyx/{rel}")
            assert response.ok, rel
            assert response.body() == (SOURCE / rel).read_bytes(), rel
        print("PASS HTTP 提供的全部 60 个 LYX 文件与原始交付逐字节一致")

        for rel, ctype in SAMPLES:
            resp = context.request.get(f"{args.url}/assets/research/lyx/{rel}")
            assert resp.ok, rel
            assert ctype in resp.headers["content-type"], (rel, resp.headers["content-type"])
            assert resp.body() == (SOURCE / rel).read_bytes(), rel

        # 目录不提供文件索引；补抓接口仍是 404
        assert context.request.get(args.url + "/assets/research/lyx/analysis/").status == 404
        assert context.request.post(args.url + "/api/game/crawl").status == 404

        for width, height in ((1440, 1000), (768, 1024), (390, 844), (320, 740)):
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            check_report(page, args.url, width, height, args.output)
            page.close()
            print(f"PASS {width}px：iframe 渲染、六段导航、全屏、相对链接、路由往返、无横向溢出")

        browser.close()

    assert not errors, errors
    print("PASS 副本逐字节一致、目录不列文件、补抓接口 404；无页面脚本异常")
    print(f"截图：{args.output}")


if __name__ == "__main__":
    main()
