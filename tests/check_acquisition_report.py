"""独立浏览器验收：直接打开本地汇报，无需启动服务器。"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    """检查所有导航、桌面手机布局与图片，截图保存在临时目录。"""
    root = Path(__file__).resolve().parents[1]
    output = Path("/tmp/achievement-acquisition-report-shots")
    output.mkdir(exist_ok=True)
    checks = []
    with sync_playwright() as tool:
        browser = tool.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=True,
        )
        for name, width, height in (("desktop", 1440, 960), ("laptop", 1280, 720), ("mobile", 390, 844)):
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto((root / "docs/data-acquisition-report.html").as_uri(), wait_until="networkidle")
            for i in range(7):
                page.select_option("#pageSelect", str(i))
                page.wait_for_function("i => Number(document.body.dataset.page) === i", arg=i)
                assert page.locator(".slide:visible").count() == 1
                assert page.locator(".slide:visible h1").inner_text().strip()
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                assert page.locator('.slide:visible img').evaluate_all(
                    "images => images.every(image => image.complete && image.naturalWidth > 0)"
                )
                if name != "mobile":
                    assert not page.evaluate("document.documentElement.scrollHeight > innerHeight + 1"), f"{name}/{i} vertical overflow"
                page.screenshot(path=str(output / f"{name}-{i+1:02}.png"), full_page=True, animations="disabled")
                checks.append({"viewport": name, "page": i+1})
            page.select_option("#pageSelect", "0")
            page.get_by_role("button", name="下一页", exact=True).click()
            assert page.locator("#pageNumber").inner_text() == "02 / 07"
            page.keyboard.press("ArrowLeft")
            assert page.locator("#pageNumber").inner_text() == "01 / 07"
            page.keyboard.press("End")
            assert page.get_by_role("button", name="下一页", exact=True).is_disabled()
            assert not errors, errors
            page.close()
        browser.close()
    print(json.dumps({"checks": len(checks), "screenshots": str(output), "page_errors": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
