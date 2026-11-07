#!/usr/bin/env python3
"""Sync YJH's interactive trend page and its two CSV downloads into dashboard."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "result/YJH/第三版"
DESTINATION = ROOT / "dashboard/yjh"
FILES = {
    "游戏类型年度分布.html": "trend-race.html",
    "游戏标签年度分布.csv": "all-tags.csv",
    "游戏类型年度分布.csv": "curated-genres.csv",
}


def sync(check: bool) -> None:
    """Copy exact source bytes, or fail if a staged file differs from its source."""
    html = (SOURCE / "游戏类型年度分布.html").read_text(encoding="utf-8")
    for name in FILES:
        if name.endswith(".csv") and f'./{name}' not in html:
            raise ValueError(f"趋势页缺少下载链接：{name}")
    if not check:
        DESTINATION.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in FILES.items():
        source = SOURCE / source_name
        target = DESTINATION / target_name
        if check:
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                raise ValueError(f"YJH 面板副本与原交付不一致：{target}")
        else:
            shutil.copyfile(source, target)
    print(f"YJH 趋势页及 {len(FILES) - 1} 份 CSV 已{'核对' if check else '同步'}")


def main() -> None:
    """Run the exact-byte sync from any working directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只核对副本，不写文件")
    args = parser.parse_args()
    sync(args.check)


if __name__ == "__main__":
    main()
