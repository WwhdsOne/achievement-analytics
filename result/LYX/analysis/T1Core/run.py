"""T1Core主线指标、类型、过程与69款共同样本时长分析。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from prepare_metrics import DEFAULT_OUTPUT, prepare


def main() -> int:
    """Run metric, game, type, trajectory or duration analysis without source writes."""
    parser = argparse.ArgumentParser(description="T1Core：固定198款主线指标与阶段比较")
    parser.add_argument("command", nargs="?", choices=("prepare", "compare", "types", "trajectory", "duration"), default="prepare")
    parser.add_argument("--output", type=Path, help="输出限T1Core；默认图片集中figures，各分析的CSV与报告在对应output子目录，自定义输出的图片放其figures子目录")
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument("--games", nargs="+", help="compare/trajectory：AppID或中英文游戏名，可混合；compare最多5款，trajectory每组最多5款")
    selectors.add_argument("--appids", nargs="+", type=int, help="compare/trajectory：游戏AppID")
    selectors.add_argument("--game-names", nargs="+", help="compare/trajectory：中英文完整名称或唯一匹配的简称")
    parser.add_argument("--view", choices=("both", "coverage", "progress"), default="both",
                        help="compare：两图、原始节点覆盖、或阶段推进比")
    parser.add_argument("--list-games", action="store_true", help="compare/trajectory：列出198款可选游戏，不生成图片")
    parser.add_argument("--groups", "--group-count", dest="group_count", type=int,
                        help="trajectory自选：组数；单独指定时尽量均分，与每组款数同时指定须一致")
    parser.add_argument("--games-per-group", type=int,
                        help="trajectory自选：每组1～5款，默认2款；按顺序分组，末组不足仍输出")
    args = parser.parse_args()
    selected = args.games or ([str(i) for i in args.appids] if args.appids else args.game_names)
    kind = "appid" if args.appids else "name" if args.game_names else "mixed"
    grouping = args.group_count is not None or args.games_per_group is not None
    if grouping and args.command != "trajectory":
        parser.error("分组参数仅用于trajectory自选游戏")
    if args.command == "trajectory":
        if args.view != "both":
            parser.error("--view仅用于compare，trajectory每组输出完整曲线与相邻区间两种图")
        if args.list_games:
            if selected or grouping:
                parser.error("--list-games不与游戏选择或分组参数同时使用")
            from compare_games import load_catalog
            catalog, _ = load_catalog()
            result = {"count": len(catalog), "games": [{"appid": g["appid"], "name_en": g["title"], "name_zh": g["name_zh"]} for g in catalog]}
        elif selected is not None:
            from compare_trajectory import DEFAULT_SELECTION, compare
            try:
                result = compare(selected, kind, args.games_per_group, args.group_count, args.output or DEFAULT_SELECTION)
            except ValueError as exc:
                parser.error(str(exc))
        else:
            if grouping:
                parser.error("自定义分组需同时用--games、--appids或--game-names选择游戏")
            from analyze_trajectory import DEFAULT_TRAJECTORY, analyze
            try:
                result = analyze(args.output or DEFAULT_TRAJECTORY)
            except ValueError as exc:
                parser.error(str(exc))
    elif args.command in ("prepare", "types", "duration"):
        if args.games or args.appids or args.game_names or args.list_games or args.view != "both":
            parser.error("游戏选择仅用于compare/trajectory，--view仅用于compare")
        if args.command == "prepare":
            result = prepare(args.output or DEFAULT_OUTPUT)
        elif args.command == "types":
            from analyze_types import DEFAULT_TYPES, analyze
            try:
                result = analyze(args.output or DEFAULT_TYPES)
            except ValueError as exc:
                parser.error(str(exc))
        else:
            from analyze_duration import DEFAULT_DURATION, analyze
            try:
                result = analyze(args.output or DEFAULT_DURATION)
            except ValueError as exc:
                parser.error(str(exc))
    else:
        from compare_games import DEFAULT_COMPARISONS, compare, load_catalog
        if args.list_games:
            if args.games or args.appids or args.game_names:
                parser.error("--list-games不与游戏选择参数同时使用")
            catalog, _ = load_catalog()
            result = {"count": len(catalog), "games": [{k: g[k] for k in ("appid", "title", "name_zh")} for g in catalog]}
        else:
            try:
                result = compare(selected, kind, args.view, args.output or DEFAULT_COMPARISONS)
            except ValueError as exc:
                parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
