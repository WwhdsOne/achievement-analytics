"""核验交付页与冻结来源的一致性；只读检查，不修改任何来源或页面。"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from typing import Any

from data_adapter import load_dashboard_data

ROOT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    """读取文件的SHA-256指纹。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class PageReader(HTMLParser):
    """只提取内嵌数据和外部运行时依赖声明。"""

    def __init__(self) -> None:
        super().__init__()
        self.in_data = False
        self.chunks: list[str] = []
        self.external_dependencies: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """识别数据脚本、外置脚本和外置样式。"""
        values = dict(attrs)
        if tag == "script":
            self.in_data = values.get("id") == "lyx-data"
            if values.get("src"):
                self.external_dependencies.append(str(values["src"]))
        if tag == "link" and values.get("rel") == "stylesheet":
            self.external_dependencies.append(str(values.get("href")))

    def handle_endtag(self, tag: str) -> None:
        """停止收集数据脚本内容。"""
        if tag == "script":
            self.in_data = False

    def handle_data(self, data: str) -> None:
        """收集HTML中实际交付的JSON。"""
        if self.in_data:
            self.chunks.append(data)


def verify(check_protected: bool = False) -> dict[str, Any]:
    """核对构建指纹、内嵌数据及可选的本轮保护基线。"""
    manifest = json.loads((ROOT / "source_manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["web_sources"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"页面源文件已变化，请先重新构建：{name}")
    if sha(ROOT / "index.html") != manifest["outputs"]["index.html"]["sha256"]:
        raise ValueError("交付页指纹与构建清单不同")
    parser = PageReader()
    parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
    if parser.external_dependencies:
        raise ValueError(f"页面存在外部运行时依赖：{parser.external_dependencies}")
    embedded = json.loads("".join(parser.chunks))
    fresh = load_dashboard_data(ROOT.parent)
    fresh["meta"]["source_files"] = fresh.pop("sources")
    fresh["meta"]["page_built_at"] = embedded["meta"]["page_built_at"]
    if embedded != fresh:
        raise ValueError("内嵌页面数据与当前已验证的冻结结果不同，请检查来源后重新构建")
    protected_count: int | None = None
    if check_protected:
        baseline_path = ROOT / "runtime" / "protected_before.json"
        if not baseline_path.exists():
            raise ValueError("本轮保护基线不在Git中；当前机器没有runtime/protected_before.json")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        changed = [name for name, expected in baseline.items() if not Path(name).is_file() or sha(Path(name)) != expected]
        if changed:
            raise ValueError(f"保护基线检测到内容变化：{changed}")
        protected_count = len(baseline)
    return {
        "status": "passed",
        "embedded_data_matches_sources": True,
        "external_runtime_dependencies": 0,
        "source_files": len(manifest["sources"]),
        "counts": embedded["meta"]["counts"],
        "source_check_status": embedded["meta"]["source_checks"]["status"],
        "historical_manifest_warnings": len(embedded["meta"]["source_checks"].get("warnings", [])),
        "protected_files_unchanged": protected_count,
        "database_writes": False,
        "provider_requests": 0,
    }


def main() -> int:
    """输出只读验收结果；失败时以非零退出码结束。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-protected", action="store_true", help="额外核验本轮施工前的本机文件指纹基线")
    args = parser.parse_args()
    print(json.dumps(verify(args.check_protected), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
