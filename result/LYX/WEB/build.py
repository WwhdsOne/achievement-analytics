"""从已有分析结果构建单文件静态简报；所有写入仅发生在WEB内。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
LYX = ROOT.parent
sys.path.insert(0, str(ROOT))


def sha(path: Path) -> str:
    """读取文件内容指纹，不更改来源。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def owned(path: Path) -> Path:
    """检查最终写入位置始终位于本WEB目录。"""
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError("页面构建输出必须位于LYX/WEB内")
    return resolved


def hero_svg(data: dict[str, Any]) -> str:
    """以真实案例的完整节点生成首屏静态SVG，无示意数据。"""
    lookup = {g["appid"]: g for g in data["games"]}
    parts = ['<svg class="hero-svg" viewBox="0 0 520 310" role="img" aria-label="Splinter Cell Blacklist与Dead Cells相对各自首节点的主线推进曲线，终点相近而过程不同">']
    for value in (0, .25, .5, .75, 1):
        y = 246 - value * 192
        parts.append(f'<line x1="42" x2="480" y1="{y}" y2="{y}" stroke="#ffffff" stroke-opacity=".09"/><text x="30" y="{y+4}" text-anchor="end" fill="#b8c8de" font-size="10">{value*100:.0f}%</text>')
    for appid, color in ((235600, "#77b6ff"), (588650, "#f5b169")):
        game = lookup[appid]
        nodes = game["nodes"]
        points = [(42 + i * 438 / (len(nodes)-1), 246 - n["rate"] / game["p_s"] * 192) for i, n in enumerate(nodes)]
        path = " ".join(("M" if i == 0 else "L") + f" {x:.2f} {y:.2f}" for i, (x, y) in enumerate(points))
        parts.append(f'<path d="{path}" stroke="{color}" stroke-width="2.5" fill="none"/>')
        for i, (x, y) in enumerate(points):
            label = html.escape(str(nodes[i]["display_name"]))
            parts.append(f'<circle cx="{x}" cy="{y}" r="3.4" fill="{color}"><title>{label}</title></circle>')
    parts.append('<text x="42" y="278" fill="#b8c8de" font-size="11">各自首节点</text><text x="480" y="278" fill="#b8c8de" font-size="11" text-anchor="end">代表末节点</text><text x="480" y="31" text-anchor="end" fill="#e6eefb" font-size="12">43.75% / 43.80% · 全程推进</text></svg>')
    return "".join(parts)


def build() -> dict[str, Any]:
    """核对现有数据并内嵌资源，原库、原CSV和图片始终只读。"""
    from data_adapter import load_dashboard_data

    data = load_dashboard_data(LYX)
    timestamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    data["meta"]["page_built_at"] = timestamp
    source_files = data.pop("sources", [])
    data["meta"]["source_files"] = source_files
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    script = (ROOT / "app.js").read_text(encoding="utf-8")
    template = (ROOT / "page.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    replacements = {"/*__STYLE__*/": css, "/*__APP__*/": script, "__HERO_SVG__": hero_svg(data), "__DATA__": payload, "__DATASET_VERSION__": html.escape(data["meta"]["dataset_version"]), "__BUILD_DATE__": timestamp[:10]}
    for token, replacement in replacements.items():
        if template.count(token) != 1:
            raise ValueError(f"页面模板标记数量异常: {token}")
        template = template.replace(token, replacement)
    output = owned(ROOT / "index.html")
    output.write_text(template, encoding="utf-8", newline="\n")
    manifest = {"page_version": "lyx-web-story-v1", "built_at": timestamp, "dataset_version": data["meta"]["dataset_version"], "counts": data["meta"]["counts"], "source_checks": data["meta"].get("source_checks"), "sources": source_files, "web_sources": {name: sha(ROOT/name) for name in ("page.html", "style.css", "app.js", "data_adapter.py", "build.py")}, "outputs": {"index.html": {"sha256": sha(output), "bytes": output.stat().st_size}}, "database_writes": False, "provider_requests": 0}
    owned(ROOT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return {"file": str(output), "bytes": output.stat().st_size, "data_bytes": len(payload.encode("utf-8")), "counts": data["meta"]["counts"], "database_writes": False, "provider_requests": 0}


def main() -> int:
    """提供零依赖、可离线执行的固定页面构建命令。"""
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
