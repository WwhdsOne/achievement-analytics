"""数据获取汇报的范围、数字口径与静态资源契约。"""

from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]


class ReportParser(HTMLParser):
    """提取汇报页标识和本地图片资源，不执行页面脚本。"""

    def __init__(self) -> None:
        super().__init__()
        self.pages: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "section" and "slide" in (attributes.get("class") or "").split():
            self.pages.append(attributes["id"])
        if tag == "img":
            self.images.append(attributes["src"])


def test_report_has_seven_pages_and_no_prediction_results() -> None:
    path = ROOT / "docs/data-acquisition-report.html"
    content = path.read_text()
    parser = ReportParser()
    parser.feed(content)
    assert len(parser.pages) == len(set(parser.pages)) == 7
    for forbidden in ("Ridge", "SHAP", "R²", "0.559", "Spearman", "achievement_agent"):
        assert forbidden not in content
    for expected in ("50,956", "1,971,064", "888,837", "2026-10-01", "50,922", "RAWG"):
        assert expected in content
    assert len(parser.images) >= 3
    assert all((path.parent / image).is_file() for image in parser.images)
    assert "https://rawg.io/" in content


def test_labeling_feature_and_local_results_are_removed() -> None:
    for file in ("modeling/achievement_agent.py", "modeling/achievement_batch.py",
                 "modeling/achievement_db.py", "modeling/achievement_taxonomy.py",
                 "data/processed/achievement-agent.sqlite3"):
        assert not (ROOT / file).exists()
    assert "achievement_agent" not in (ROOT / "docs/commands.md").read_text()
