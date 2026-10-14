"""CLI: independent read-only export, model annotation, local analysis and status."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import analysis, deepseek, params, storage


def main() -> None:
    """Dispatch task phases without exposing credentials in failures."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="WWH task 5 local SQLite + DeepSeek")
    parser.add_argument("--db", type=Path, default=storage.DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "label", "analyze", "status"):
        sub = commands.add_parser(command)
        sub.add_argument("--db", type=Path, default=argparse.SUPPRESS)
        if command == "export":
            sub.add_argument("--limit", type=int, default=1000)
            sub.add_argument("--dataset-version")
        elif command == "label":
            sub.add_argument("--dry-run", action="store_true")
            sub.add_argument("--max-requests", type=int)
            sub.add_argument("--max-games", type=int)
            sub.add_argument("--batch-size", type=int, default=params.LABEL_BATCH_SIZE)
            sub.add_argument(
                "--workers", type=int, default=params.LABEL_WORKERS,
                help="并行处理的游戏数（不是并发请求数的硬上限）；1 = 串行",
            )
        elif command == "analyze":
            sub.add_argument("--output", type=Path, default=storage.TASK_ROOT)
            sub.add_argument("--bootstrap-samples", type=int, default=params.BOOTSTRAP_SAMPLES)
    args = parser.parse_args()
    try:
        if args.command == "export":
            meta = storage.export_snapshot(args.db, args.limit, args.dataset_version)
            result = {key: meta[key] for key in ("dataset_version", "input_sha256", "frame_count", "exported_at")}
        elif args.command == "label":
            result = deepseek.run_labeling(args.db, dry_run=args.dry_run, batch_size=args.batch_size,
                max_requests=args.max_requests, max_games=args.max_games, workers=args.workers)
        elif args.command == "analyze":
            metrics = analysis.analyze(args.db, args.output, args.bootstrap_samples)
            result = {key: metrics[key] for key in ("frame", "category_labeled", "labeled", "blocked", "pending", "errors", "usable_curves", "paired")}
            result["report"] = str(args.output / "report.md")
        else:
            result = storage.status(args.db)
            result["metadata"] = {k: v for k, v in result["metadata"].items()
                if k in ("dataset_version", "input_sha256", "exported_at", "active_annotation")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "label" and result.get("errors", 0) > 0:
            sys.exit(1)
    except (RuntimeError, ValueError) as exc:
        print(f"Task 5: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Task 5: {type(exc).__name__}; operation failed (credentials suppressed)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
