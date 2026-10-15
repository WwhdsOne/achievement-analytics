"""Codex 浏览器难度采集交接：AppID队列、发现记录、DOM核验与批次写库。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from guide_agent_queue import initialize_queue, load_queue, next_jobs, queue_summary, update_job
from guide_time import (
    DEFAULT_RUNTIME, FIELDS, acquire_runtime_lock, apply_records, make_record, parse_record_html,
    new_run, read_json, save_json, save_receipt, utc_now, verify_receipt,
)
from guide_time_parser import normalize_game_name, validate_guide_url
from guide_time_storage import read_games
from local_database import DEFAULT_DATABASE, WORKSPACE, workspace_path

DEFAULT_MANIFEST = WORKSPACE / "database" / "data" / "top1000_appids.json"
AGENT_RUNTIME = DEFAULT_RUNTIME / "agent"
PROTECTED_CAPTURE_STATUSES = frozenset({"imported", "partial", "applied", "already_complete", "input_changed"})
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


def identity_name(value: str) -> str:
    """仅折叠字体、大小写和标点，保留数字、系列及版本词。"""
    normalized = normalize_game_name(value)
    return " ".join(re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE).split())


def discovery_url(value: str, *, allow_query: bool = False) -> str:
    """允许站内实际发现入口，拒绝其他域、账号、端口和登录路径。"""
    if not isinstance(value, str) or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("候选URL无效")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc.casefold() not in {"www.gamerguides.com", "gamerguides.com"}:
        raise ValueError("候选必须来自Gamer Guides HTTPS域名")
    if (parsed.query and not allow_query) or parsed.fragment or re.search(r"/(?:login|register|premium|delete-account)(?:/|$)", parsed.path):
        raise ValueError("候选不能包含查询、片段、账号或付费操作入口")
    if not parsed.path.startswith("/") or "\\" in parsed.path or re.search(r"%2f|%5c|\.\.", parsed.path, re.I):
        raise ValueError("候选路径无效")
    return "https://www.gamerguides.com" + parsed.path + ("?" + parsed.query if parsed.query else "")


class _PlatformParser(HTMLParser):
    """从实际平台节点读取唯一is-active文本，不把平台链接当当前平台。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.active_depth: int | None = None
        self.parts: list[str] = []
        self.active: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            return
        self.depth += 1
        classes = set((dict(attrs).get("class") or "").split())
        if "achv-service" in classes and "is-active" in classes:
            if self.active_depth is not None:
                raise ValueError("平台节点嵌套有歧义")
            self.active_depth = self.depth
            self.parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self.active_depth == self.depth:
            self.active.append(" ".join("".join(self.parts).split()))
            self.active_depth = None
        self.depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID_TAGS:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.active_depth is not None:
            self.parts.append(data)


def capture_html(capture: dict[str, Any]) -> str:
    """用同一规则封装实际DOM片段，供首次导入与写库前指纹复核共用。"""
    if not isinstance(capture, dict):
        raise ValueError("浏览器交接必须为JSON对象")
    for key in ("url", "captured_at", "page_title", "h1_html", "platform_html"):
        if not isinstance(capture.get(key), str) or not capture[key].strip():
            raise ValueError(f"浏览器交接缺少非空{key}")
    pieces = []
    for key in ("time_html", "difficulty_html"):
        if capture.get(key) is not None and not isinstance(capture[key], str):
            raise ValueError(f"{key}必须是实际DOM字符串或NULL")
        pieces.append(capture.get(key) or "")
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><title>" + escape(capture["page_title"]) +
            "</title></head><body>" + capture["h1_html"] + capture["platform_html"] + "".join(pieces) + "</body></html>")


def verify_identity(job: dict[str, Any], capture: dict[str, Any], parsed: dict[str, Any], database: Path) -> dict[str, Any]:
    """确认当前Steam平台与产品身份，明确异名证据不足时拒绝自动映射。"""
    platform = _PlatformParser()
    platform.feed(capture["platform_html"])
    platform.close()
    if platform.active != ["Steam"]:
        raise ValueError(f"当前平台不是唯一Steam：{platform.active}")
    if "steam achievements" not in capture["page_title"].casefold():
        raise ValueError("页面标题缺少Steam Achievements身份")
    page_name = parsed["game_name"]
    local_names = [n for n in (job["name_en"], job.get("name_zh")) if n]
    observed_ids: set[int] = set()
    for link in capture.get("steam_links", []):
        target = link.get("url") if isinstance(link, dict) else link
        if not isinstance(target, str):
            raise ValueError("Steam链接必须为实际URL")
        url = urlsplit(target)
        if url.scheme == "https" and url.hostname == "store.steampowered.com":
            matched = re.match(r"/app/(\d+)(?:/|$)", url.path)
        elif url.scheme == "https" and url.hostname == "steamcommunity.com":
            matched = re.match(r"/(?:stats|app)/(\d+)(?:/|$)", url.path)
        else:
            matched = None
        if matched:
            observed_ids.add(int(matched.group(1)))
    if observed_ids and observed_ids != {job["appid"]}:
        raise ValueError(f"网页Steam AppID与本地不一致或有歧义：{sorted(observed_ids)}")
    if observed_ids == {job["appid"]}:
        method = "steam_appid_match"
        evidence: dict[str, Any] = {"observed_steam_appids": sorted(observed_ids)}
    elif identity_name(page_name) in {identity_name(n) for n in local_names}:
        method = "normalized_full_name_and_steam"
        evidence = {"local_name": job["name_en"], "page_name": page_name}
    else:
        raise ValueError("页面名称与本地完整名称不同，须取得对应Steam AppID链接后才能自动映射")
    return {"method": method, "platform": "Steam", "page_game_name": page_name, "evidence": evidence}


def record_discovery(runtime: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """记录实际检索候选或有限搜索未确认结果；不把猜测URL的404当全游戏终态。"""
    queue = load_queue(runtime)
    prepared = []
    for row in rows:
        appid = row.get("appid")
        if type(appid) is not int or str(appid) not in queue["jobs"]:
            raise ValueError("发现记录AppID必须在冻结队列中")
        candidates = row.get("candidates", [])
        if not isinstance(candidates, list) or len(candidates) > 3:
            raise ValueError("每款每轮最多3条候选")
        clean = []
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("title"), str):
                raise ValueError("候选必须包含实际标题和URL")
            clean.append({**candidate, "url": discovery_url(candidate["url"])})
        queries = [row.get("query"), row.get("followup_query")]
        searches = [{"query": q, "observed_at": row.get("observed_at") or utc_now(), "evidence": row.get("evidence")} for q in queries if q]
        if not searches or any(not isinstance(s["query"], str) for s in searches):
            raise ValueError("必须记录实际搜索词或目录发现来源")
        prepared.append((row, clean, searches))
    outcomes = []
    for row, candidates, searches in prepared:
        job = load_queue(runtime)["jobs"][str(row["appid"])]
        protected = job["status"] in PROTECTED_CAPTURE_STATUSES
        existing = {c["url"]: c for c in job.get("candidates", [])}
        existing.update({c["url"]: c for c in candidates})
        status = job["status"] if protected else "candidates_found" if existing else "no_verified_page"
        update_job(runtime, row["appid"], status, {
            "searches": job.get("searches", []) + searches,
            "candidates": list(existing.values()), "attempts": job.get("attempts", 0) + len(searches),
            "notes": row.get("evidence") or "检索结果只是候选，须浏览器身份核验",
        })
        outcomes.append({"appid": row["appid"], "status": status, "candidate_count": len(existing)})
    return {"outcomes": outcomes}


def import_capture(runtime: Path, appid: int, capture: dict[str, Any]) -> dict[str, Any]:
    """接收浏览器原始DOM片段，核验映射并保存receipt；此步骤不写SQLite。"""
    queue = load_queue(runtime)
    if str(appid) not in queue["jobs"]:
        raise ValueError("AppID不在冻结队列")
    job = queue["jobs"][str(appid)]
    if job["status"] in {"input_changed", "already_complete", "applied"}:
        raise ValueError("当前任务输入已改变或已完成；请明确retry后重新采集")
    html = capture_html(capture)
    url = validate_guide_url(capture["url"])
    time_value = datetime.fromisoformat(capture["captured_at"].replace("Z", "+00:00"))
    if time_value.tzinfo is None:
        raise ValueError("captured_at必须含时区")
    candidates = {c["url"] for c in job.get("candidates", [])}
    chain = capture.get("navigation", [])
    if url not in candidates:
        if not isinstance(chain, list) or not chain:
            raise ValueError("目标URL未在实际发现候选中，也没有站内链接导航证据")
        previous = discovery_url(chain[0]["from_url"])
        if previous not in candidates:
            raise ValueError("导航链起点不在已发现候选中")
        for hop in chain:
            if discovery_url(hop["from_url"]) != previous or not hop.get("link_text"):
                raise ValueError("站内实际链接导航链不连续")
            previous = discovery_url(hop["to_url"])
        if previous != url:
            raise ValueError("导航证据没有到达当前Steam总览")
    parsed = parse_record_html(html, url)
    proof = verify_identity(job, capture, parsed, Path(queue["database"]))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    evidence_file = workspace_path(runtime / "captures" / str(appid) / f"{stamp}.json")
    save_json(evidence_file, {"source_kind": "browser_dom", "appid": appid, "capture": capture, "identity": proof})
    mapping = {"url": url, "page_game_name": parsed["game_name"], **proof,
               "proof_file": str(evidence_file), "proof_sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
               "captured_at": capture["captured_at"]}
    update_job(runtime, appid, "mapping_verified", {"verified_mapping": mapping})
    record = make_record(job, html, url, "browser_dom", capture["captured_at"], parsed["game_name"])
    receipt = save_receipt(runtime, record, html.encode("utf-8"))
    update_job(runtime, appid, "imported", {"receipt": str(receipt), "import_result": {
        "status": parsed["status"], "values": parsed["values"], "warnings": parsed["warnings"],
    }})
    return {"appid": appid, "status": "imported", "scope": parsed["scope"], "identity": proof,
            "values": parsed["values"], "receipt": str(receipt)}


def record_capture_error(runtime: Path, appid: int, error: ValueError) -> str:
    """记录捕获失败但保护已有核验来源和完成状态，挑战单独留作blocked。"""
    job = load_queue(runtime)["jobs"].get(str(appid))
    if job is None:
        raise ValueError("AppID不在冻结队列") from error
    status = job["status"] if job["status"] in PROTECTED_CAPTURE_STATUSES else (
        "blocked" if "challenge" in str(error).casefold() else "ambiguous")
    update_job(runtime, appid, status, {"reason": str(error), "last_error": str(error)})
    return status


def handoff_checksum(value: Any) -> str:
    """核对浏览器DOM导出到文件时未被改写的UTF8 JSON内容，算法为FNV1a32。"""
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    checksum = 2166136261
    for byte in encoded:
        checksum = ((checksum ^ byte) * 16777619) & 0xFFFFFFFF
    return f"{checksum:08x}"


def import_capture_batch(runtime: Path, document: dict[str, Any]) -> dict[str, Any]:
    """导入至多10款实际DOM交接；逐款保留失败，遇挑战即停止该来源。"""
    rows = document.get("captures")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
        raise ValueError("每批captures必须含1至10款")
    ids = [row.get("appid") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or any(type(i) is not int for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("批次AppID必须为不重复整数")
    if any(not isinstance(row.get("capture"), dict) for row in rows):
        raise ValueError("每条批次记录必须含capture对象")
    if document.get("captures_checksum") != handoff_checksum(rows):
        raise ValueError("浏览器批次导出校验不一致")
    queue = load_queue(runtime)
    if any(str(i) not in queue["jobs"] for i in ids):
        raise ValueError("批次AppID必须在冻结队列中")
    outcomes = []
    for row in rows:
        try:
            outcomes.append(import_capture(runtime, row["appid"], row["capture"]))
        except ValueError as error:
            status = record_capture_error(runtime, row["appid"], error)
            outcomes.append({"appid": row["appid"], "status": status, "error": str(error)})
            if "challenge" in str(error).casefold():
                break
    return {"outcomes": outcomes, "summary": queue_summary(runtime)}


def apply_queue(runtime: Path, selected: list[int] | None, overwrite: bool) -> dict[str, Any]:
    """校验本批来源及身份文件后统一备份，只写攻略难度并更新队列。"""
    queue = load_queue(runtime)
    queue = initialize_queue(Path(queue["database"]), Path(queue["manifest"]["path"]), runtime)
    games = {g["appid"]: g for g in read_games(Path(queue["database"]))}
    jobs = next_jobs(runtime, limit=len(queue["jobs"]), statuses=["imported", "partial"], appids=selected)
    jobs = [j for j in jobs if j["status"] in {"imported", "partial"}]
    if not jobs:
        raise ValueError("没有待写入的已核验DOM来源")
    records = []
    for job in jobs:
        mapping = job.get("verified_mapping") or {}
        proof_path = workspace_path(Path(mapping["proof_file"]), must_exist=True)
        if hashlib.sha256(proof_path.read_bytes()).hexdigest() != mapping.get("proof_sha256"):
            raise ValueError("身份依据指纹不一致")
        proof = read_json(proof_path)
        receipt_path = workspace_path(Path(job["receipt"]), must_exist=True)
        saved_receipt = read_json(receipt_path)
        record = verify_receipt(receipt_path, games)
        if proof.get("appid") != job["appid"] or record["appid"] != job["appid"]:
            raise ValueError("队列、DOM依据与receipt的AppID不一致")
        capture = proof["capture"]
        html = capture_html(capture)
        if hashlib.sha256(html.encode("utf-8")).hexdigest() != saved_receipt.get("html_sha256"):
            raise ValueError("DOM身份依据与receipt不是同一次捕获内容")
        if proof.get("source_kind") != "browser_dom" or record["source_kind"] != "browser_dom":
            raise ValueError("agent队列只接受实际浏览器DOM来源")
        if (validate_guide_url(capture["url"]) != record["source_url"] or
                capture["captured_at"] != record["fetched_at"] or capture["captured_at"] != mapping.get("captured_at")):
            raise ValueError("DOM、映射与receipt的URL或捕获时间不一致")
        parsed = parse_record_html(html, capture["url"], record["parser_version"])
        if parsed["game_name"] != record["page_game_name"] or parsed["values"] != record["values"]:
            raise ValueError("DOM与receipt的游戏名称或字段值不一致")
        recomputed = verify_identity(job, capture, parsed, Path(queue["database"]))
        if (recomputed != proof["identity"] or record["source_url"] != mapping["url"] or
                any(mapping.get(k) != v for k, v in recomputed.items())):
            raise ValueError("身份依据、映射与来源记录不一致")
        records.append(record)
    directory, report = new_run(runtime, "agent-apply")
    report["games"] = [{"appid": r["appid"], "state": r["status"]} for r in records]
    try:
        apply_records(Path(queue["database"]), records, directory, report, overwrite)
        for outcome in report["writes"]:
            if outcome["state"] == "conflict":
                status = "error"
            elif all(outcome["after"].get(f) is not None for f in FIELDS):
                status = "applied"
            elif any(outcome["after"].get(f) is not None for f in FIELDS):
                status = "partial"
            else:
                status = "metadata_missing"
            update_job(runtime, outcome["appid"], status, {"apply_result": outcome})
        report["state"] = "completed_with_conflicts" if any(o["state"] == "conflict" for o in report["writes"]) else "completed_batch"
    except BaseException as error:
        report["state"] = "error"
        report["error"] = str(error)
        save_json(directory / "report.json", report)
        raise
    report["finished_at"] = utc_now()
    save_json(directory / "report.json", report)
    return {"report": str(directory / "report.json"), "writes": report["writes"], "summary": queue_summary(runtime)}


def catalogue_candidates(runtime: Path, document: dict[str, Any]) -> dict[str, Any]:
    """将浏览器实际目录卡片按完整名称匹配为候选，目录匹配仍须打开页面核验。"""
    source = discovery_url(document["source_url"], allow_query=True)
    if urlsplit(source).path != "/achievements":
        raise ValueError("目录来源必须是实际/achievements页面")
    items = document.get("items")
    if not isinstance(items, list):
        raise ValueError("目录items必须是实际卡片数组")
    if "items_checksum" in document:
        if handoff_checksum([[i["name"], i["url"]] for i in items]) != document["items_checksum"]:
            raise ValueError("目录浏览器导出校验不一致，禁止使用发生改变的交接数据")
    queue = load_queue(runtime)
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("目录卡片缺少名称")
        clean = {"url": discovery_url(item["url"]), "title": item["name"], "evidence": f"实际目录卡片：{source}", "platform_text": item.get("platform_text")}
        index.setdefault(identity_name(item["name"]), []).append(clean)
    rows = []
    for job in queue["jobs"].values():
        if job["status"] in {"applied", "already_complete", "input_changed"}:
            continue
        matches = index.get(identity_name(job["name_en"]), [])
        if not matches and job.get("name_zh"):
            matches = index.get(identity_name(job["name_zh"]), [])
        if matches:
            rows.append({"appid": job["appid"], "query": "browser_catalogue:" + source,
                         "observed_at": document.get("captured_at") or utc_now(), "candidates": matches[:3]})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    save_json(runtime / "catalogues" / f"{stamp}.json", document)
    result = record_discovery(runtime, rows)
    return {"observed_card_count": len(items), "matched_game_count": len(rows), **result}


def main(argv: list[str] | None = None) -> int:
    """执行本地交接命令；浏览器和搜索动作由当前Codex agent执行。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=AGENT_RUNTIME)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    init.add_argument("--appids-file", type=Path, default=DEFAULT_MANIFEST)
    for name in ("next", "summary", "apply", "retry"):
        command = sub.add_parser(name)
        if name != "summary":
            command.add_argument("--appids", type=int, nargs="+")
        if name == "next":
            command.add_argument("--limit", type=int, default=10)
            command.add_argument("--phase", choices=("discovery", "capture", "apply", "all"), default="discovery")
        if name == "apply":
            command.add_argument("--overwrite", action="store_true")
    for name in ("discovery", "capture", "capture-batch", "catalogue"):
        command = sub.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        if name == "capture":
            command.add_argument("--appid", type=int, required=True)
    mark = sub.add_parser("mark")
    mark.add_argument("--appid", type=int, required=True)
    mark.add_argument("--status", choices=["ambiguous", "no_verified_page", "blocked", "error", "metadata_missing"], required=True)
    mark.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        runtime = workspace_path(args.runtime)
        with acquire_runtime_lock(runtime):
            if args.command == "init":
                initialize_queue(args.database, args.appids_file, runtime)
                result = queue_summary(runtime)
            elif args.command == "summary":
                result = queue_summary(runtime)
            elif args.command == "next":
                phases = {"discovery": ["discovery_pending", "error"], "capture": ["candidates_found", "mapping_verified", "dom_saved"], "apply": ["imported"], "all": None}
                jobs = next_jobs(runtime, args.limit, phases[args.phase], args.appids)
                result = {"phase": args.phase, "jobs": jobs}
                for job in jobs:
                    job["suggested_queries"] = [f'site:gamerguides.com "{job["name_en"]}" "Steam Achievements"', f'site:gamerguides.com "{job["name_en"]}"']
            elif args.command == "discovery":
                rows = read_json(args.input)
                if not isinstance(rows, list):
                    raise ValueError("发现记录必须为JSON数组")
                result = record_discovery(runtime, rows)
            elif args.command == "capture":
                capture = read_json(args.input)
                try:
                    result = import_capture(runtime, args.appid, capture)
                except ValueError as error:
                    record_capture_error(runtime, args.appid, error)
                    raise
            elif args.command == "capture-batch":
                result = import_capture_batch(runtime, read_json(args.input))
            elif args.command == "mark":
                job = load_queue(runtime)["jobs"].get(str(args.appid))
                if job is None:
                    raise ValueError("AppID不在冻结队列")
                status = job["status"] if job["status"] in PROTECTED_CAPTURE_STATUSES else args.status
                result = update_job(runtime, args.appid, status, {"reason": args.reason})
            elif args.command == "catalogue":
                result = catalogue_candidates(runtime, read_json(args.input))
            elif args.command == "apply":
                result = apply_queue(runtime, args.appids, args.overwrite)
            else:
                if not args.appids:
                    raise ValueError("retry必须明确指定AppID，不自动重抓全库")
                for appid in args.appids:
                    update_job(runtime, appid, "discovery_pending", {"reason": "显式重新检索，旧来源保留"})
                result = queue_summary(runtime)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        failed = (args.command == "apply" and any(o["state"] == "conflict" for o in result["writes"])) or (
            args.command == "capture-batch" and any("error" in o for o in result["outcomes"]))
        return 1 if failed else 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError) as error:
        print(json.dumps({"state": "error", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
