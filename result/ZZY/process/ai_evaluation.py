"""Reproduce external AI-label metrics without the historical human-lock flow."""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re

from modeling.recommendation.effect_metrics import calculate

HOME = Path(__file__).resolve().parents[1]
PATTERN = re.compile("未加载|资料不足|信息不足|无法判断|无法访问|未能|打不开|未获取")


def digest(path: Path) -> str:
    """Hash a small evaluation input file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Parse CSV and reject ragged records before identity checks."""
    cells = list(
        csv.reader(
            io.StringIO(path.read_text(encoding="utf-8-sig"), newline=""), strict=True
        )
    )
    if not cells or any(len(row) != len(cells[0]) for row in cells[1:]):
        raise ValueError("CSV为空或列数不一致")
    return cells[0], [dict(zip(cells[0], row)) for row in cells[1:]]


def evaluate(inputs: Path, output: Path) -> dict:
    """Keep AI identity, exact source labels and a separate conservative scenario."""
    if not output.is_relative_to((HOME / "runtime").resolve()):
        raise ValueError("输出必须位于个人result/ZZY/runtime内")
    if output.exists():
        raise FileExistsError("输出目录已存在，请使用新目录")
    protocol = json.loads((inputs / "protocol.json").read_bytes())
    rankings = json.loads((inputs / "rankings.json").read_bytes())
    export = json.loads((inputs / "export-manifest.json").read_bytes())
    if (
        digest(inputs / "protocol.json") != export["protocol_sha256"]
        or digest(inputs / "rankings.json") != export["files"]["private/rankings.json"]
        or rankings["protocol_sha256"] != export["protocol_sha256"]
    ):
        raise ValueError("原协议/排名摘要不一致")
    columns, rows = read_csv(inputs / "labels-original.txt")
    expected_columns, template = read_csv(inputs / "human-review-template.csv")
    expected = {r["pair_id"]: r for r in template}
    if (
        columns != expected_columns
        or len(rows) != len(expected)
        or len({r["pair_id"] for r in rows}) != len(rows)
        or {r["pair_id"] for r in rows} != set(expected)
    ):
        raise ValueError("标签表列、游戏对覆盖或唯一性不符")
    labels, flagged, punctuation = {}, [], []
    for row in rows:
        for column in columns[:8]:
            original = expected[row["pair_id"]][column]
            if row[column] != original:
                table = str.maketrans({"“": '"', "”": '"'})
                if column not in ("seed_name", "candidate_name") or row[
                    column
                ].translate(table) != original.translate(table):
                    raise ValueError("游戏对身份变化：" + row["pair_id"])
                punctuation.append(row["pair_id"])
        value = row["relevance"]
        if value not in ("0", "1", "2", "unknown") or not row["reviewer_id"].startswith(
            "AI-"
        ):
            raise ValueError("标签非法或AI来源未保留：" + row["pair_id"])
        if any(not row[k].strip() for k in columns[8:]):
            raise ValueError("标签字段空白：" + row["pair_id"])
        key = row["query_id"], int(row["candidate_appid"])
        labels[key] = value if value == "unknown" else int(value)
        if value != "unknown" and PATTERN.search(row["rationale"] + row["fact_notes"]):
            flagged.append((row["pair_id"], key))
    sensitivity = dict(labels)
    for _, key in flagged:
        sensitivity[key] = "unknown"
    metrics = {}
    for name, selected in (("original", labels), ("sensitivity", sensitivity)):
        result = calculate(protocol, rankings, selected)
        result.update(
            schema_version="ai-exploratory-metrics-v1",
            label_origin="external_ai",
            formal_human_evaluation=False,
            interpretation="AI生成的探索性标签；非真人评价。保留原评分，敏感性分析另存。上下界不是置信区间。",
        )
        metrics[name] = result
    matches = {
        name: result == json.loads((HOME / "reports" / f"ai-{name}.json").read_bytes())
        for name, result in metrics.items()
    }
    audit = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label_origin": "external_ai",
        "formal_human_evaluation": False,
        "human_lock_used": False,
        "rows": len(rows),
        "label_counts": dict(Counter(row["relevance"] for row in rows)),
        "missing_evidence_pair_ids": [pair for pair, _ in flagged],
        "identity_punctuation_changes": punctuation,
        "matches_saved_reference": matches,
        "source_page_and_timestamp_verification": "not_performed",
        "input_sha256": {p.name: digest(p) for p in inputs.iterdir() if p.is_file()},
        "source_sha256": digest(Path(__file__)),
        "limitations": [
            "原正式盲评包说明/换行摘要差异仍保留；本命令不调用或替代正式真人流程。",
            "敏感性分析为分析后诊断，不生成新的人工标签。",
        ],
    }
    output.mkdir(parents=True)
    (output / "labels-original.txt").write_bytes(
        (inputs / "labels-original.txt").read_bytes()
    )
    for name, result in metrics.items():
        (output / f"ai-{name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (output / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "output": str(output),
        "rows": len(rows),
        "matches_saved_reference": matches,
        "complete_queries": {
            name: result["complete_queries"] for name, result in metrics.items()
        },
        "label_origin": "external_ai",
        "formal_human_evaluation": False,
    }
