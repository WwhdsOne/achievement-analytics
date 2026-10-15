"""Gamer Guides 浏览器代理的持久 AppID 队列；SQLite 始终只读。

调用方在 initialize_queue/update_job 期间持有 guide_time.acquire_runtime_lock。
queue.json 是当前状态真源，events.jsonl 只用于审计；本模块不重复加运行锁。
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

from guide_time import FIELDS, LEGACY_FIELDS, read_json, save_json, utc_now
from guide_time_storage import read_games
from local_database import database_path, workspace_path

FORMAT = "gamerguides-agent-queue-v1"
SCHEMA_VERSION = 1
STATUSES = frozenset({
    "discovery_pending", "candidates_found", "mapping_verified", "dom_saved",
    "imported", "applied", "partial", "metadata_missing", "ambiguous",
    "no_verified_page", "blocked", "error", "input_changed", "already_complete",
})
DEFAULT_NEXT_STATUSES = (
    "discovery_pending", "candidates_found", "mapping_verified", "dom_saved",
    "imported", "error",
)
DETAIL_FIELDS = frozenset({
    "searches", "candidates", "rejected_candidates", "verified_mapping", "receipt",
    "attempts", "reason", "last_error", "notes", "import_result", "apply_result",
})


def _appids(value: Any, *, allow_empty: bool = False) -> list[int]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError("AppID 清单必须是非空 JSON 整数数组")
    if any(type(appid) is not int or not 0 < appid <= 2**63 - 1 for appid in value):
        raise ValueError("AppID 必须是 SQLite 可表示的正整数，不能是布尔值")
    if len(set(value)) != len(value):
        raise ValueError("AppID 清单不能重复")
    return value


def _status(value: Any) -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise ValueError(f"不支持的队列状态：{value!r}")
    return value


def _validate_queue(queue: Any) -> dict[str, Any]:
    if not isinstance(queue, dict) or queue.get("format") != FORMAT or type(queue.get("schema_version")) is not int or queue.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("队列格式或 schema 版本不支持；请使用独立 runtime，不能覆盖旧状态")
    manifest = queue.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("队列缺少 manifest")
    appids = _appids(manifest.get("appids"))
    if manifest.get("count") != len(appids):
        raise ValueError("队列 manifest 数量与 AppID 顺序不一致")
    digest = manifest.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("队列 manifest SHA256 无效")
    if not isinstance(manifest.get("path"), str) or not Path(manifest["path"]).is_absolute():
        raise ValueError("队列 manifest 路径必须为绝对路径")
    if not isinstance(queue.get("database"), str) or not Path(queue["database"]).is_absolute():
        raise ValueError("队列 database 必须为绝对路径")
    workspace_path(Path(manifest["path"]))
    workspace_path(Path(queue["database"]))
    if type(queue.get("revision")) is not int or queue["revision"] < 1:
        raise ValueError("队列 revision 无效")
    jobs = queue.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != {str(appid) for appid in appids}:
        raise ValueError("队列 jobs 与冻结 AppID 清单不一致")
    for rank, appid in enumerate(appids, 1):
        job = jobs[str(appid)]
        if not isinstance(job, dict) or type(job.get("appid")) is not int or job["appid"] != appid or type(job.get("rank")) is not int or job.get("rank") != rank:
            raise ValueError("队列任务 AppID 或 rank 被修改")
        _status(job.get("status"))
        # v1 队列的历史缺口仍可读取；initialize_queue 按当前难度口径对账。
        if not isinstance(job.get("missing_fields"), list) or any(field not in LEGACY_FIELDS for field in job["missing_fields"]):
            raise ValueError("队列 missing_fields 无效")
        for field in ("searches", "candidates", "rejected_candidates"):
            if not isinstance(job.get(field), list):
                raise ValueError(f"队列 {field} 必须是数组")
        if type(job.get("attempts")) is not int or job["attempts"] < 0:
            raise ValueError("队列 attempts 必须是非负整数")
        snapshot = job.get("input_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("name_en") != job.get("name_en") or snapshot.get("name_zh") != job.get("name_zh"):
            raise ValueError("任务名称与冻结输入快照不一致")
    pending = queue.get("pending_event")
    if pending is not None and (not isinstance(pending, dict) or not isinstance(pending.get("event_id"), str)):
        raise ValueError("队列待补审计事件无效")
    return queue


def _trim_incomplete_event_tail(file: BinaryIO) -> int:
    """只截断没有换行结尾的半行，保留此前全部完整 JSONL，返回追加起点。"""
    size = file.seek(0, os.SEEK_END)
    if not size:
        return 0
    file.seek(size - 1)
    if file.read(1) == b"\n":
        return size
    cursor, complete_size = size, 0
    while cursor:
        start = max(0, cursor - 65536)
        file.seek(start)
        chunk = file.read(cursor - start)
        last_newline = chunk.rfind(b"\n")
        if last_newline >= 0:
            complete_size = start + last_newline + 1
            break
        cursor = start
    file.truncate(complete_size)
    file.flush()
    os.fsync(file.fileno())
    return complete_size


def _append_event(runtime: Path, event: dict[str, Any]) -> None:
    payload = (json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    path = workspace_path(runtime / "events.jsonl")
    # 无缓冲写入便于短写失败后回退追加段，避免关闭缓冲区时再次写入残片。
    with path.open("a+b", buffering=0) as file:
        original_size = _trim_incomplete_event_tail(file)
        try:
            if file.write(payload) != len(payload):
                raise OSError("events.jsonl 写入不完整")
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            # 回退只能移除本次追加字节；若磁盘故障使回退也失败，pending_event 仍保留，
            # 下一次恢复会先清掉未完成尾行后重放该 event_id。
            try:
                file.truncate(original_size)
                file.flush()
                os.fsync(file.fileno())
            except OSError:
                pass
            raise


def _recover_event(runtime: Path, queue: dict[str, Any]) -> None:
    """补齐已提交状态的待写审计；重复 event_id 表示崩溃后的同一事件重放。"""
    pending = queue.get("pending_event")
    if pending is None:
        return
    try:
        _append_event(runtime, pending)
        queue["pending_event"] = None
        save_json(runtime / "queue.json", queue)
    except (OSError, ValueError) as error:
        raise RuntimeError("queue.json 状态已持久化，但待补审计事件写入失败；保留 pending_event 后可重试") from error


def _commit(runtime: Path, queue: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    stamp = utc_now()
    queue["revision"] = queue.get("revision", 0) + 1
    queue["updated_at"] = stamp
    queue["pending_event"] = {
        "event_id": uuid4().hex, "at": stamp, "revision": queue["revision"], **event,
    }
    # 先原子提交当前状态和审计 outbox；写审计失败不能把实际已生效的状态说成未生效。
    save_json(runtime / "queue.json", queue)
    _recover_event(runtime, queue)
    return queue


def _new_job(game: dict[str, Any], rank: int, stamp: str) -> dict[str, Any]:
    missing = [field for field in FIELDS if game[field] is None]
    names = {"name_en": game["name_en"], "name_zh": game["name_zh"]}
    return {
        "appid": game["appid"], "rank": rank, **names,
        "input_snapshot": names.copy(), "missing_fields": missing,
        "status": "discovery_pending" if missing else "already_complete",
        "searches": [], "candidates": [], "rejected_candidates": [],
        "verified_mapping": None, "receipt": None, "attempts": 0,
        "updated_at": stamp,
    }


def initialize_queue(database: Path, appids_file: Path, runtime: Path) -> dict[str, Any]:
    """验证清单并创建或续用队列；调用方须持有 runtime 锁，数据库仅以 ro 读取。"""
    db = database_path(database)
    manifest_path = workspace_path(appids_file, must_exist=True)
    root = workspace_path(runtime)
    raw = manifest_path.read_bytes()
    appids = _appids(read_json(manifest_path))
    digest = hashlib.sha256(raw).hexdigest()
    # 同一文件在校验期间若改变，不允许把解析内容和另一次读取的 SHA 混合保存。
    if manifest_path.read_bytes() != raw:
        raise ValueError("AppID 清单在校验期间改变，请重新初始化")
    games = {game["appid"]: game for game in read_games(db, appids)}
    absent = [appid for appid in appids if appid not in games]
    if absent:
        raise ValueError(f"清单中的 AppID 缺少 games 或 games_time 行：{absent}")
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "queue.json").exists():
        stamp = utc_now()
        queue = {
            "format": FORMAT, "schema_version": SCHEMA_VERSION,
            "database": str(db), "manifest": {
                "path": str(manifest_path), "sha256": digest, "appids": appids,
                "count": len(appids),
            },
            "created_at": stamp, "updated_at": stamp, "revision": 0,
            "jobs": {str(appid): _new_job(games[appid], rank, stamp)
                     for rank, appid in enumerate(appids, 1)},
            "pending_event": None,
        }
        return _commit(root, queue, {"kind": "queue_initialized", "count": len(appids), "manifest_sha256": digest})
    queue = load_queue(root)
    if Path(queue["database"]).resolve() != db or queue["manifest"]["sha256"] != digest or queue["manifest"]["appids"] != appids:
        raise ValueError("已有队列的数据库、清单 SHA 或顺序不一致；请保留原 runtime 并使用新目录")
    _recover_event(root, queue)
    changed: list[int] = []
    stamp = utc_now()
    for appid in appids:
        job, game = queue["jobs"][str(appid)], games[appid]
        before = deepcopy(job)
        current_names = {"name_en": game["name_en"], "name_zh": game["name_zh"]}
        job["missing_fields"] = [field for field in FIELDS if game[field] is None]
        if current_names != job["input_snapshot"]:
            if job.get("verified_mapping") or job.get("receipt"):
                job.setdefault("superseded_evidence", []).append({
                    "at": stamp, "input_snapshot": job["input_snapshot"].copy(),
                    "verified_mapping": job["verified_mapping"], "receipt": job["receipt"],
                })
            job["verified_mapping"], job["receipt"] = None, None
            job["current_input"] = current_names
            job["status"] = "input_changed"
            job["reason"] = "本地游戏名称与冻结输入不同；旧映射已失效，请核对后使用新 runtime"
        elif job["status"] == "input_changed":
            # 输入即使又恢复原名，也保留人工核对要求，不能自动重用曾失效的证据。
            job["current_input"] = current_names
        elif not job["missing_fields"]:
            if job["status"] != "applied" or not job.get("receipt"):
                job["status"] = "already_complete"
        elif job["status"] == "applied":
            # 备份恢复或外部修改可能把已应用字段重新变为空；数据库缺口应可恢复处理。
            job["status"] = "imported" if job.get("receipt") and job.get("verified_mapping") else "discovery_pending"
        elif job["status"] == "already_complete":
            job["status"] = "discovery_pending"
        if job != before:
            job["updated_at"] = stamp
            changed.append(appid)
    if changed:
        return _commit(root, queue, {"kind": "queue_reconciled", "appids": changed})
    return queue


def load_queue(runtime: Path) -> dict[str, Any]:
    """只读加载并验证当前队列；审计暂未写齐时 queue.json 仍是状态真源。"""
    root = workspace_path(runtime)
    return _validate_queue(read_json(root / "queue.json"))


def update_job(runtime: Path, appid: int, status: str, details: dict[str, Any]) -> dict[str, Any]:
    """原子更新指定任务并持久审计；只允许工作证据字段，调用方须持有 runtime 锁。"""
    _appids([appid])
    new_status = _status(status)
    if not isinstance(details, dict) or set(details) - DETAIL_FIELDS:
        raise ValueError(f"details 只能包含：{', '.join(sorted(DETAIL_FIELDS))}")
    # 提前验证可序列化性，避免状态已提交后才发现审计证据含 Path 或非有限数字。
    json.dumps(details, ensure_ascii=False, allow_nan=False)
    for field in ("searches", "candidates", "rejected_candidates"):
        if field in details and not isinstance(details[field], list):
            raise ValueError(f"{field} 必须为数组")
    if "attempts" in details and (type(details["attempts"]) is not int or details["attempts"] < 0):
        raise ValueError("attempts 必须为非负整数")
    if "verified_mapping" in details and details["verified_mapping"] is not None and not isinstance(details["verified_mapping"], dict):
        raise ValueError("verified_mapping 必须为对象或 NULL")
    if "receipt" in details and details["receipt"] is not None and not isinstance(details["receipt"], str):
        raise ValueError("receipt 必须为路径字符串或 NULL")
    root = workspace_path(runtime)
    queue = load_queue(root)
    if str(appid) not in queue["jobs"]:
        raise ValueError(f"AppID 不在冻结队列中：{appid}")
    job = queue["jobs"][str(appid)]
    if job["status"] == "input_changed" and new_status != "input_changed":
        raise ValueError("冻结名称输入已变化，不能直接恢复旧映射；请核对输入并使用新 runtime")
    _recover_event(root, queue)
    old_status = job["status"]
    job.update(deepcopy(details))
    job["status"], job["updated_at"] = new_status, utc_now()
    _commit(root, queue, {"kind": "job_updated", "appid": appid, "from_status": old_status,
                         "to_status": new_status, "details": details})
    return deepcopy(job)


def next_jobs(runtime: Path, limit: int = 10, statuses: list[str] | None = None,
              appids: list[int] | None = None) -> list[dict[str, Any]]:
    """按冻结清单顺序返回可续跑任务；显式 AppID 未指定状态时可取任意选中任务。"""
    if type(limit) is not int or limit < 1:
        raise ValueError("limit 必须为正整数，不能是布尔值")
    if statuses is not None:
        if not isinstance(statuses, list):
            raise ValueError("statuses 必须是合法状态数组")
        for item in statuses:
            _status(item)
    allowed = set(statuses) if statuses is not None else (None if appids is not None else set(DEFAULT_NEXT_STATUSES))
    selected = set(_appids(appids, allow_empty=True)) if appids is not None else None
    queue = load_queue(runtime)
    if selected is not None and selected - set(queue["manifest"]["appids"]):
        raise ValueError("选择的 AppID 不在冻结队列内")
    result = []
    for appid in queue["manifest"]["appids"]:
        job = queue["jobs"][str(appid)]
        if (selected is None or appid in selected) and (allowed is None or job["status"] in allowed):
            result.append(deepcopy(job))
            if len(result) == limit:
                break
    return result


def queue_summary(runtime: Path) -> dict[str, Any]:
    """只读汇总任务状态与当前 SQLite 实际覆盖；未确认网页不等于网站确定性无数据。"""
    queue = load_queue(runtime)
    appids = queue["manifest"]["appids"]
    games = {game["appid"]: game for game in read_games(database_path(Path(queue["database"])), appids)}
    missing = {field: sum(appid not in games or games[appid][field] is None for appid in appids) for field in FIELDS}
    complete = sum(appid in games and all(games[appid][field] is not None for field in FIELDS) for appid in appids)
    return {
        "format": FORMAT, "database": queue["database"], "total": len(appids),
        "manifest_sha256": queue["manifest"]["sha256"], "revision": queue["revision"],
        "updated_at": queue["updated_at"],
        "status_counts": dict(Counter(job["status"] for job in queue["jobs"].values())),
        "coverage": {field: len(appids) - missing[field] for field in FIELDS},
        "missing_fields": missing, "complete_count": complete, "pending_count": len(appids) - complete,
        "missing_database_rows": [appid for appid in appids if appid not in games],
        "audit_pending": queue.get("pending_event") is not None,
        "scope": "achievement_difficulty_reference",
        "note": "当前队列只补攻略难度，HLTB 时长由独立同步入口维护；历史 Time 证据保留。no_verified_page 仅表示本轮未确认页面；覆盖直接读取 SQLite",
    }
