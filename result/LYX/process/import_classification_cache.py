"""离线核验历史分类CSV，补录合格标签并建立累计datacache；默认只读预检。"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, nullcontext
from copy import deepcopy
import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import shutil
import sqlite3
from typing import Any

import DataAgent as agent
from datacache import (
    DEFAULT_DATACACHE,
    classification_csv_rows,
    update_datacache,
    write_classification_csv,
)
from local_database import (
    DEFAULT_DATABASE,
    DEFAULT_MIN_CONFIDENCE,
    connect_local,
    ensure_schema,
    partition_classification_types,
    store_classifications,
    workspace_path,
)

Json = dict[str, Any]
DEFAULT_SOURCE_ROOT = agent.RUNTIME / "runs"
_CSV_IDENTITY_FIELDS = (
    "appid",
    "name_en",
    "api_name",
    "display_name",
    "description",
    "type",
    "method",
    "confidence",
    "knowledge_used",
    "evidence",
    "reason",
    "uncertainty",
    "request_hash",
)


def _csv_value(value: Any) -> str:
    value = "" if value is None else str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def _csv_identity(row: Json) -> tuple[str, ...]:
    return tuple(_csv_value(row.get(field)) for field in _CSV_IDENTITY_FIELDS)


def _receipt(report: Json, request_hash: str, source_root: Path) -> Json:
    calls = [
        call for call in report["calls"] if call.get("request_hash") == request_hash
    ]
    if not calls:
        raise ValueError("CSV分类结果没有对应请求凭据")
    original = Path(calls[-1]["receipt"])
    fallback = source_root.parent / "cache" / request_hash / original.name
    path = workspace_path(original if original.is_file() else fallback, must_exist=True)
    receipt = agent.strict_json(path.read_text(encoding="utf-8"))
    if (
        receipt.get("http_status") != 200
        or receipt.get("response_complete", True) is not True
        or receipt.get("request_hash") != request_hash
    ):
        raise ValueError("凭据不是完整成功响应")
    return receipt


def _validate_batch(
    report: Json, game: Json, request_hash: str, source_root: Path, threshold: float
) -> list[Json]:
    receipt = _receipt(report, request_hash, source_root)
    version = receipt.get("prompt_version")
    prompts = {
        agent.PROMPT_VERSION: agent.CLASSIFICATION_PROMPT,
        **dict(agent.COMPATIBLE_CLASSIFICATION_PROMPTS),
    }
    if version not in prompts:
        raise ValueError("旧版抽样响应只归档，不按当前整款契约补录")
    payload = receipt["payload"]
    expected_hash = agent.digest(
        {
            "endpoint": report["base_url"] + "/chat/completions",
            "task": agent.CLASSIFICATION_TASK,
            "prompt_version": version,
            "payload": payload,
        }
    )
    if expected_hash != request_hash or payload["model"] != report["model"]:
        raise ValueError("请求凭据指纹或模型不一致")
    content = payload["messages"][1]["content"]
    prefix = "<game_context>\n"
    if not content.startswith(prefix):
        raise ValueError("请求缺少结构化游戏上下文")
    context, _ = agent.json.JSONDecoder().raw_decode(content, len(prefix))
    intro = {
        "recognized": context["intro_recognized"],
        "summary": context["model_intro"],
        "uncertainty": context["intro_uncertainty"],
    }
    expected_messages = agent.classification_messages(game, game["achievements"], intro)
    expected_messages[0]["content"] = prompts[version]
    if payload["messages"] != expected_messages:
        raise ValueError("缓存游戏上下文、成就集合或原文与当前SQLite不一致")
    result = agent.validate_classification(
        agent.response_result(agent.strict_json(receipt["response_text"])),
        game["achievements"],
    )
    return agent.classification_rows(
        game,
        game["achievements"],
        {"result": result, "request_hash": request_hash},
        threshold,
    )


def collect_candidates(
    source_root: Path, database: Path, threshold: float
) -> tuple[list[Json], list[Json], Json]:
    """以CSV为入口，交叉核对报告、完整响应及当前原文；不相信旧筛选标志。"""
    files = sorted(
        workspace_path(source_root).glob("*/classifications.csv"), reverse=True
    )
    candidates: list[Json] = []
    legacy: list[Json] = []
    seen: set[tuple[int, str]] = set()
    games: dict[int, Json] = {}
    errors: list[Json] = []
    source_rows = duplicate_rows = 0
    with closing(connect_local(database)) as con:
        ensure_schema(con)
        for source in files:
            try:
                with source.open(encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle, strict=True)
                    if not set(_CSV_IDENTITY_FIELDS).issubset(reader.fieldnames or []):
                        raise ValueError("CSV缺少分类身份或依据字段")
                    csv_rows = list(reader)
                source_rows += len(csv_rows)
                if not csv_rows:
                    continue
                report = agent.strict_json(
                    (source.parent / "report.json").read_text(encoding="utf-8")
                )
                groups: dict[tuple[int, str], list[Json]] = {}
                for row in csv_rows:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("CSV存在不完整字段或多余列")
                    key = (int(row["appid"]), row["request_hash"])
                    groups.setdefault(key, []).append(row)
                for (appid, request_hash), rows in groups.items():
                    try:
                        raw = [
                            deepcopy(item)
                            for item in report["classifications"]
                            if item["appid"] == appid
                            and item["request_hash"] == request_hash
                        ]
                        if not raw:
                            raise ValueError("CSV没有对应的完整JSON分类记录")
                        for item in raw:
                            item["accepted_types"], item["rejected_types"] = (
                                partition_classification_types(item["types"], threshold)
                            )
                        # 只比较稳定原文、标签及依据；旧门槛、状态、写库结果不作为新筛选依据。
                        expected = Counter(
                            _csv_identity(row) for row in classification_csv_rows(raw)
                        )
                        actual = Counter(
                            tuple(row[field] for field in _CSV_IDENTITY_FIELDS)
                            for row in rows
                        )
                        if expected != actual or any(
                            count != 1 for count in expected.values()
                        ):
                            raise ValueError("CSV与JSON分类原文、标签或依据不一致/重复")
                        key = (appid, request_hash)
                        if key in seen:
                            duplicate_rows += len(rows)
                            continue
                        if appid not in games:
                            games[appid] = agent.load_games(database, [appid])[0][0]
                        game = games[appid]
                        receipt = _receipt(report, request_hash, source_root)
                        if (
                            receipt.get("prompt_version")
                            == "lyx-deepseek-multilabel-v3"
                        ):
                            # 已落库的早期单条试跑仅作为历史记录归档，不重新信任旧输出契约。
                            current = {a["api_name"]: a for a in game["achievements"]}
                            for item in raw:
                                original = current.get(item["api_name"])
                                tags = con.execute(
                                    "SELECT type,confidence,method FROM achievement_types WHERE appid=? AND api_name=?",
                                    (appid, item["api_name"]),
                                ).fetchall()
                                if (
                                    original is None
                                    or item["name_en"] != game["name_en"]
                                    or (item["display_name"], item["description"])
                                    != (
                                        original["display_name"],
                                        original["description"],
                                    )
                                    or any(
                                        (tag["type"], tag["confidence"], "deepseek")
                                        not in tags
                                        for tag in item["types"]
                                    )
                                ):
                                    raise ValueError(
                                        "旧版试跑记录不是当前数据库中的已有结果"
                                    )
                                item.update(
                                    sqlite_outcome="legacy_existing",
                                    status="uncertain"
                                    if item["types"][0]["type"] == "unknown"
                                    else "suggested",
                                )
                            legacy.append(
                                {
                                    "source_csv": str(source.resolve()),
                                    "game": game,
                                    "records": raw,
                                }
                            )
                        else:
                            records = _validate_batch(
                                report, game, request_hash, source_root, threshold
                            )
                            stable_new = Counter(
                                _csv_identity(row)
                                for row in classification_csv_rows(
                                    [
                                        {**item, "sqlite_outcome": "pending"}
                                        for item in records
                                    ]
                                )
                            )
                            if stable_new != expected:
                                raise ValueError("报告中的分类结果与完整响应不一致")
                            candidates.append(
                                {
                                    "source_csv": str(source.resolve()),
                                    "game": game,
                                    "records": records,
                                }
                            )
                        seen.add(key)
                    except (
                        agent.AgentError,
                        ValueError,
                        KeyError,
                        TypeError,
                        OSError,
                    ) as exc:
                        errors.append(
                            {
                                "source_csv": str(source),
                                "appid": appid,
                                "request_hash": request_hash,
                                "error": str(exc),
                            }
                        )
            except (
                agent.AgentError,
                ValueError,
                KeyError,
                TypeError,
                OSError,
                csv.Error,
            ) as exc:
                errors.append({"source_csv": str(source), "error": str(exc)})
    return (
        candidates,
        legacy,
        {
            "source_csv_count": len(files),
            "source_row_count": source_rows,
            "duplicate_row_count": duplicate_rows,
            "validation_errors": errors,
        },
    )


def import_cache(
    source_root: Path,
    database: Path,
    datacache: Path,
    threshold: float,
    *,
    apply: bool = False,
) -> Json:
    """默认预检；显式apply后先备份，再逐款补录且保留冲突及所有历史文件。"""
    source_root, database, datacache = (
        workspace_path(path) for path in (source_root, database, datacache)
    )
    report: Json = {
        "started_at": agent.now(),
        "state": "plan",
        "database": str(database),
        "datacache_path": str(datacache),
        "min_confidence": threshold,
        "confidence_comparison": ">=",
        "requests": 0,
        "database_writes": False,
    }
    with agent.run_lock(source_root.parent) if apply else nullcontext():
        batches, legacy, stats = collect_candidates(source_root, database, threshold)
        report.update(
            stats,
            batch_count=len(batches),
            legacy_archive_count=sum(len(b["records"]) for b in legacy),
        )
        all_records = [item for batch in batches + legacy for item in batch["records"]]
        report.update(
            classification_count=len(all_records),
            label_count=sum(len(r["types"]) for r in all_records),
            accepted_label_count=sum(len(r["accepted_types"]) for r in all_records),
            rejected_label_count=sum(len(r["rejected_types"]) for r in all_records),
        )
        if not apply:
            return report
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = workspace_path(source_root.parent / "cache_imports" / stamp)
        run_dir.mkdir(parents=True)
        report.update(
            state="running",
            report_path=str(run_dir / "report.json"),
            backup_path=str(run_dir / "before_import.sqlite"),
            sqlite_counts={},
            written_label_count=0,
            classifications=[],
        )
        agent.backup_database(database, run_dir / "before_import.sqlite")
        if datacache.exists():
            shutil.copy2(datacache, run_dir / "before_datacache.csv")
        try:
            for batch in batches + legacy:
                records = batch["records"]
                for item in records:
                    item.setdefault("sqlite_outcome", "pending")
                report["classifications"].extend(records)
                report["datacache"] = update_datacache(
                    datacache,
                    records,
                    source_csv=batch["source_csv"],
                    min_confidence=threshold,
                    seen_at=agent.now(),
                )
                if batch in batches:
                    counts = store_classifications(
                        database,
                        batch["game"],
                        records,
                        merge_existing=True,
                        expected_input=batch["game"]["achievements"],
                        min_confidence=threshold,
                    )
                    for key, value in counts.items():
                        report["sqlite_counts"][key] = (
                            report["sqlite_counts"].get(key, 0) + value
                        )
                    report["written_label_count"] += sum(
                        len(item["written_types"]) for item in records
                    )
                    report["database_writes"] |= counts["written"] > 0
                report["datacache"] = update_datacache(
                    datacache,
                    records,
                    source_csv=batch["source_csv"],
                    min_confidence=threshold,
                    seen_at=agent.now(),
                )
                agent.write_json(run_dir / "report.json", report)
            report["state"] = (
                "completed_with_errors" if report["validation_errors"] else "success"
            )
        except KeyboardInterrupt:
            report["state"] = "interrupted"
            raise
        except (ValueError, OSError, sqlite3.Error) as exc:
            report.update(state="error", error=str(exc))
            raise
        finally:
            report["finished_at"] = agent.now()
            write_classification_csv(
                run_dir / "classifications.csv", report["classifications"]
            )
            agent.write_json(run_dir / "report.json", report)
    return report


def main() -> int:
    """命令行默认只读预检；--apply才允许本地备份、累计CSV及SQLite写入。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--datacache", type=Path, default=DEFAULT_DATACACHE)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.min_confidence) or not 0 <= args.min_confidence <= 1:
        parser.error("min-confidence必须在0～1")
    try:
        report = import_cache(
            args.source_root,
            args.database,
            args.datacache,
            args.min_confidence,
            apply=args.apply,
        )
        print(
            agent.json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key != "classifications"
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return (
            0
            if report["state"] in ("plan", "success")
            and not report["validation_errors"]
            else 1
        )
    except (agent.AgentError, ValueError, OSError, sqlite3.Error) as exc:
        print(f"离线缓存导入失败：{exc}", file=agent.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
