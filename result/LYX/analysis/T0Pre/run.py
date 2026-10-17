"""在LYX/T0Pre复现WWH三张图；只读现有SQLite，结果写入analysis/T0Pre。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
# Set caches before importing NumPy/Matplotlib; all cache writes stay inside LYX.
os.environ["MPLCONFIGDIR"] = str(ROOT / "runtime" / "matplotlib")
sys.dont_write_bytecode = True

from wwh_replay import analysis, params, storage


def main() -> int:
    """Run the copied analysis with explicit baseline and database integrity evidence."""
    parser = argparse.ArgumentParser(description="LYX：只读复现WWH分类、主线阶段与RAWG三张图")
    parser.add_argument("command", nargs="?", choices=("analyze",), default="analyze")
    parser.add_argument("--db", type=Path, default=storage.DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--baseline", choices=("highest", "start"), default=params.CURVE_BASELINE,
                        help="highest复现WWH历史figures；start对应WWH当前参数文件")
    parser.add_argument("--bootstrap-samples", type=int, default=params.BOOTSTRAP_SAMPLES)
    args = parser.parse_args()
    if args.bootstrap_samples < 0:
        parser.error("--bootstrap-samples必须大于等于0")
    params.CURVE_BASELINE = args.baseline
    params.BOOTSTRAP_SAMPLES = args.bootstrap_samples
    output = storage.owned_path(args.output)
    database = storage.database_path(args.db)
    protected = list(dict.fromkeys([database, storage.LEGACY_DB.resolve()]))
    protected = [p for p in protected if p.is_file()]
    before = [storage.fingerprint(p) for p in protected]
    print(f"只读分析 baseline={args.baseline} database={database}", flush=True)
    metrics = analysis.analyze(database, output, args.bootstrap_samples)
    after = [storage.fingerprint(p) for p in protected]
    unchanged = before == after
    historical = None
    with storage.connect(database) as conn:
        row = conn.execute("SELECT id,analyzed_at,metrics FROM analysis_runs ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            historical = {"id": row["id"], "analyzed_at": row["analyzed_at"], "metrics": json.loads(row["metrics"])}
    # Ignore only added point provenance fields and new run metadata when comparing.
    comparison = {}
    if historical and args.baseline == "highest" and args.bootstrap_samples == 2000:
        for key in ("frame", "category_labeled", "labeled", "blocked", "pending", "errors", "usable_curves", "paired", "rawg_present", "rawg_valid20", "excluded_curves", "curve_types", "categories", "rawg_comparisons", "rawg_four_status", "primary_gameplay_completion", "dimension_completion", "usage"):
            comparison[key] = metrics.get(key) == historical["metrics"].get(key)
    manifest = {
        "completed_at": storage.now(), "database": str(database), "output": str(output),
        "database_access": "mode=ro; PRAGMA query_only=ON; read transaction",
        "parameters": {**params.snapshot(), "BOOTSTRAP_SAMPLES": args.bootstrap_samples},
        "database_fingerprints_before": before, "database_fingerprints_after": after,
        "databases_unchanged": unchanged,
        "historical_analysis_id": historical["id"] if historical else None,
        "historical_comparison": comparison,
    }
    storage.write_json(output / "verification.json", manifest)
    result = {k: metrics[k] for k in ("frame", "category_labeled", "labeled", "usable_curves", "paired", "curve_types")}
    result.update(baseline=args.baseline, spearman=metrics["rawg_comparisons"]["20"]["spearman"],
                  databases_unchanged=unchanged, historical_metrics_match=all(comparison.values()) if comparison else None,
                  report=str(output / "report.md"), verification=str(output / "verification.json"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not unchanged:
        raise RuntimeError("运行期间输入数据库指纹变化，请检查外部写入；本程序连接只读")
    if comparison and not all(comparison.values()):
        raise RuntimeError("复现结果与借用库最新历史分析不一致，请查看verification.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
