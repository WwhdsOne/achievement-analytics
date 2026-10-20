#!/usr/bin/env python3
"""把 LYX 的成品交互页连同它引用的附件，同步成面板可发布的静态目录。

面板的小型前端用 `//go:embed` 打包；研究内容独立持久化部署，因此先把
`result/LYX` 里「页面真正会点到的那些文件」复制到 `dashboard/lyx/`，并保持它们之间的
相对路径不变——页内写的是 `../analysis/...`、`../docs/...`，只要目录结构一致就能打开。

只搬会被点到的文件，不搬整个 result/LYX（那里有 40MB 的 selections 快照和 trajectory 图，
页面根本不引用）。

用法::

    python3 scripts/sync_lyx_bundle.py            # 复制并校验
    python3 scripts/sync_lyx_bundle.py --check    # 只校验面板里的副本是否与源一致

改 `result/LYX/WEB/index.html` 或它引用的附件之后必须重跑，否则面板里还是旧副本。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "result" / "LYX"
TARGET = ROOT / "dashboard" / "lyx"

# 页面里写死的三个文档链接（见 index.html 的 methods 区块）
DOCS = [
    "docs/ANALYSIS.md",
    "docs/INSTRUCT.md",
    "docs/experiments.md",
]

# 21 张正式图：T1Core 01–15、T2Sum 16–21，页面按 ../analysis/<子目录>/figures/<名>.png 链接
FIGURE_DIRS = ["analysis/T1Core/figures", "analysis/T2Sum/figures"]


def load_embedded_json(path: Path) -> dict:
    """取出成品页内嵌的 lyx-data，用来拿来源文件清单。"""
    text = path.read_text(encoding="utf-8")
    match = re.search(r'<script id="lyx-data" type="application/json">(.*?)</script>', text, re.S)
    if match is None:
        raise SystemExit(f"{path} 里找不到内嵌数据块 lyx-data")
    return json.loads(match.group(1))


def collect() -> list[str]:
    """列出要同步的相对路径，全部相对于 result/LYX 与 dashboard/lyx。"""
    files = ["WEB/index.html", *DOCS]
    for directory in FIGURE_DIRS:
        for png in sorted((SOURCE / directory).glob("*.png")):
            files.append(f"{directory}/{png.name}")
    data = load_embedded_json(SOURCE / "WEB" / "index.html")
    for row in data["meta"].get("source_files") or []:
        files.append(row["path"])
    missing = [name for name in files if not (SOURCE / name).is_file()]
    if missing:
        raise SystemExit("源文件缺失：\n  " + "\n  ".join(missing))
    return files


def verify_links() -> None:
    """把页面会点到的目标逐个落到面板目录上，确认复制完不会断。

    页面的三类链接来源不同：文档是写死的 `../docs/...`，原图是 JS 里 `figures` 数组拼出来的
    `../analysis/<子目录>/figures/<名>.png`，来源明细是 `'../' + meta.source_files[].path`。
    """
    html = (SOURCE / "WEB" / "index.html").read_text(encoding="utf-8")

    literal = sorted(set(re.findall(r"\.\./([A-Za-z0-9_\-./]+)", html)))
    data = load_embedded_json(SOURCE / "WEB" / "index.html")
    figures = []
    for name in sorted(set(re.findall(r"\['(\d{2}_[a-z0-9_]+)'", html))):
        directory = "analysis/T1Core/figures" if int(name[:2]) <= 15 else "analysis/T2Sum/figures"
        figures.append(f"{directory}/{name}.png")
    sources = [row["path"] for row in data["meta"].get("source_files") or []]

    targets = literal + figures + sources
    broken = [name for name in targets if not (TARGET / name).exists() and not (TARGET / name).is_dir()]
    if broken:
        raise SystemExit("以下链接目标在面板目录里不存在：\n  " + "\n  ".join(broken))
    print(f"链接自检：{len(literal)} 个显式链接 + {len(figures)} 张原图 + {len(sources)} 份来源文件，全部可达")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验副本是否与源一致，不写文件")
    args = parser.parse_args()

    files = collect()
    total = sum((SOURCE / name).stat().st_size for name in files)

    if args.check:
        stale = []
        for name in files:
            target = TARGET / name
            if not target.is_file() or target.read_bytes() != (SOURCE / name).read_bytes():
                stale.append(name)
        if stale:
            raise SystemExit("面板副本已过期，请重跑同步：\n  " + "\n  ".join(stale))
        verify_links()
        print(f"副本与源一致：{len(files)} 个文件，共 {total / 1024 / 1024:.1f}MB")
        return 0

    for name in files:
        target = TARGET / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, target)

    verify_links()
    print(f"已同步 {len(files)} 个文件到 {TARGET.relative_to(ROOT)}，共 {total / 1024 / 1024:.1f}MB")
    print(f"  入口：/assets/research/lyx/WEB/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
