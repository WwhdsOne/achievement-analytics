"""Gamer Guides 难度的独立批量补全入口；HLTB 时长不由此入口更新。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Any, BinaryIO
import unicodedata
from uuid import uuid4

import httpx

from guide_time_parser import (
    GuideParseError, normalize_game_name, parse_guide_html, validate_guide_url,
)
from guide_time_storage import GUIDE_COLUMNS, backup_database, read_games, write_guide_values
from local_database import DEFAULT_DATABASE, WORKSPACE, database_path, workspace_path

FORMAT_VERSION = "gamerguides-guide-v1"
PARSER_VERSION = "fixed-chips-v4-difficulty-only"
LEGACY_FIELDS = ("guide_time_hours_min", "guide_time_hours_max", "guide_difficulty")
LEGACY_PARSER_VERSIONS = frozenset({"fixed-chips-v1", "fixed-chips-v2-unitless-partial", "fixed-chips-v3-unitless-hours"})
COMPATIBLE_PARSER_VERSIONS = LEGACY_PARSER_VERSIONS | {PARSER_VERSION}
DEFAULT_RUNTIME = WORKSPACE / "process" / "runtime" / "gamerguides"
FIELDS = GUIDE_COLUMNS
MAX_HTML_BYTES = 10 * 1024 * 1024


def utc_now() -> str:
    """返回带UTC时区的来源/运行时间。"""
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, value: Any) -> None:
    """在LYX内原子保存JSON；刷新缓冲后替换，禁止非有限数。"""
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_json(path: Path) -> Any:
    """读取LYX内JSON，拒绝JSON扩展中的NaN/Infinity。"""
    def reject_constant(value: str) -> None:
        raise ValueError(f"JSON含非有限数字：{value}")

    return json.loads(workspace_path(path, must_exist=True).read_text(encoding="utf-8-sig"), parse_constant=reject_constant)


def candidate_url(name: str) -> str | None:
    """仅生成一个未确认候选；成功读取后仍须核对网页游戏名称。"""
    clean = unicodedata.normalize("NFKD", name.replace("™", "").replace("®", ""))
    ascii_name = clean.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    return f"https://www.gamerguides.com/{slug}/steam-achievements/overview" if slug else None


def load_mapping(path: Path | None, games: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """加载明确URL/可选名称别名映射；无清单时生成未确认候选。"""
    if path is None:
        return {g["appid"]: {"url": candidate_url(g["name_en"]), "method": "slug_candidate"} for g in games}
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError("映射文件必须为JSON数组：[{appid,url,page_game_name(可选)}]")
    known = {g["appid"] for g in games}
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("appid")) is not int or row["appid"] <= 0:
            raise ValueError("映射appid必须为正整数")
        appid = row["appid"]
        if appid in result:
            raise ValueError(f"映射appid重复：{appid}")
        if appid not in known:
            raise ValueError(f"映射appid不在本地库：{appid}")
        alias = row.get("page_game_name")
        if alias is not None and (not isinstance(alias, str) or not alias.strip()):
            raise ValueError("page_game_name必须为非空名称")
        result[appid] = {"url": validate_guide_url(row.get("url")), "page_game_name": alias, "method": "explicit_mapping"}
    return result


def parse_record_html(html: str, url: str, parser_version: str = PARSER_VERSION) -> dict[str, Any]:
    """按来源保存版本解析；新来源只取难度，旧来源完整复核其历史三字段。"""
    if parser_version not in COMPATIBLE_PARSER_VERSIONS:
        raise ValueError("来源解析器版本不支持")
    return parse_guide_html(
        html, url, unitless_time_as_hours=parser_version == "fixed-chips-v3-unitless-hours",
        difficulty_only=parser_version == PARSER_VERSION,
    )


def make_record(game: dict[str, Any], html: str, url: str, source_kind: str,
                fetched_at: str, alias: str | None = None, *, parser_version: str = PARSER_VERSION) -> dict[str, Any]:
    """解析实际HTML，并以规范化完整名称核对AppID身份。"""
    if source_kind not in ("http_html", "browser_dom"):
        raise ValueError("来源类型必须为http_html或browser_dom")
    parsed = parse_record_html(html, url, parser_version)
    names = [game["name_en"], game.get("name_zh")]
    if alias:
        names.append(alias)
    if normalize_game_name(parsed["game_name"]) not in {normalize_game_name(n) for n in names if n}:
        raise GuideParseError(f"游戏身份不匹配：本地={game['name_en']}，网页={parsed['game_name']}")
    return {
        "format": FORMAT_VERSION, "parser_version": parser_version,
        "appid": game["appid"], "name_en": game["name_en"],
        "source_url": validate_guide_url(url), "source_kind": source_kind,
        "fetched_at": fetched_at, "mapping_alias": alias,
        "page_game_name": parsed["game_name"], **parsed,
    }


def save_receipt(runtime: Path, record: dict[str, Any], html_bytes: bytes) -> Path:
    """先持久化原始HTML/DOM片段及其指纹，再允许写库。"""
    if len(html_bytes) > MAX_HTML_BYTES:
        raise ValueError("HTML超过10MiB限制")
    digest = hashlib.sha256(html_bytes).hexdigest()
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    directory = workspace_path(runtime / "receipts" / str(record["appid"]))
    directory.mkdir(parents=True, exist_ok=True)
    html_path = directory / f"{name}.html"
    with html_path.open("xb") as file:
        file.write(html_bytes)
        file.flush()
        os.fsync(file.fileno())
    receipt_path = directory / f"{name}.json"
    save_json(receipt_path, {**record, "html_file": str(html_path), "html_sha256": digest})
    return receipt_path


def verify_receipt(path: Path, games: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """重读HTML、校验指纹和当前游戏身份，拒绝手工篡改的解析结果。"""
    saved = read_json(path)
    if not isinstance(saved, dict) or saved.get("format") != FORMAT_VERSION or saved.get("parser_version") not in COMPATIBLE_PARSER_VERSIONS:
        raise ValueError(f"来源记录版本不支持：{path}")
    appid = saved.get("appid")
    if type(appid) is not int or appid not in games or saved.get("name_en") != games[appid]["name_en"]:
        raise ValueError("来源记录与当前本地游戏身份不一致")
    html_path = workspace_path(Path(saved["html_file"]), must_exist=True)
    if html_path.stat().st_size > MAX_HTML_BYTES:
        raise ValueError("来源HTML过大")
    raw = html_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != saved.get("html_sha256"):
        raise ValueError("来源HTML指纹不一致")
    fresh = make_record(games[appid], raw.decode("utf-8-sig"), saved["source_url"],
                        saved["source_kind"], saved["fetched_at"], saved.get("mapping_alias"),
                        parser_version=saved["parser_version"])
    for key in ("values", "time_text", "difficulty_text", "page_game_name", "status", "scope"):
        if fresh[key] != saved.get(key):
            raise ValueError(f"来源解析结果不一致：{key}")
    return {**fresh, "receipt": str(path.resolve())}


def latest_receipts(path: Path, games: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """选择每款最新记录并重新校验；损坏记录明确失败，不静默回退。"""
    root = workspace_path(path)
    if root.is_file():
        paths = [root]
    elif root.name in {str(appid) for appid in games}:
        paths = sorted(root.glob("*.json"))
    else:
        paths = sorted(entry for appid in games for entry in (root / str(appid)).glob("*.json"))
    selected: dict[int, Path] = {}
    for entry in paths:
        value = read_json(entry)
        appid = value.get("appid") if isinstance(value, dict) else None
        if type(appid) is int and appid in games:
            selected[appid] = entry
    return {appid: verify_receipt(entry, games) for appid, entry in selected.items()}


def progress_key(game: dict[str, Any], entry: dict[str, Any] | None) -> str:
    """以游戏身份、URL、别名及解析器版本区分可恢复采集任务。"""
    payload = {"appid": game["appid"], "name_en": game["name_en"], "parser_version": PARSER_VERSION,
               "url": entry.get("url") if entry else None,
               "alias": entry.get("page_game_name") if entry else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def read_progress(runtime: Path) -> dict[str, Any]:
    """读取跨轮游戏状态；不存在时创建内存状态，绝不据此填写数据库空值。"""
    path = runtime / "progress.json"
    if not path.exists():
        return {"format": FORMAT_VERSION, "entries": {}}
    value = read_json(path)
    if not isinstance(value, dict) or value.get("format") != FORMAT_VERSION or not isinstance(value.get("entries"), dict):
        raise ValueError("采集进度文件格式无效")
    return value


def acquire_runtime_lock(runtime: Path) -> BinaryIO:
    """独占当前采集流水线的进度文件；操作系统在进程退出/崩溃时释放锁。"""
    runtime.mkdir(parents=True, exist_ok=True)
    file = (runtime / "runtime.lock").open("a+b")
    try:
        file.seek(0)
        if not file.read(1):
            file.write(b"0")
            file.flush()
        file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        file.close()
        raise RuntimeError("相同runtime已有补全程序运行；退出后锁自动释放") from error
    return file


def new_run(runtime: Path, command: str) -> tuple[Path, dict[str, Any]]:
    """为每轮创建独立运行报告目录，不覆盖历史来源或报告。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    directory = workspace_path(runtime / "runs" / stamp)
    directory.mkdir(parents=True, exist_ok=False)
    report = {"command": command, "started_at": utc_now(), "state": "running", "requests": 0, "games": [],
              "scope": "achievement_difficulty_reference", "write_fields": list(FIELDS)}
    save_json(directory / "report.json", report)
    return directory, report


def apply_records(database: Path, records: list[dict[str, Any]], directory: Path,
                  report: dict[str, Any], overwrite: bool) -> None:
    """完整核验来源后仅写难度；时长字段即使保存在旧 receipt 也不参与写库。"""
    writable = [r for r in records if any(r["values"][f] is not None for f in FIELDS)]
    if writable:
        backup_path = directory / "before_apply.sqlite"
        backup_database(database, backup_path)
        report["backup"] = str(backup_path)
        save_json(directory / "report.json", report)
    report["writes"] = []
    for record in records:
        outcome = write_guide_values(database, record, overwrite=overwrite)
        report["writes"].append({"appid": record["appid"], "receipt": record.get("receipt"), **outcome})
        save_json(directory / "report.json", report)


class SourcePaused(RuntimeError):
    """当前来源被挑战/限流或拒绝访问；停止本轮而不消耗其他游戏。"""


class RequestBudgetReached(RuntimeError):
    """本轮真实HTTP请求预算耗尽，保留已有来源记录。"""


def fetch_html(client: httpx.Client, url: str, args: argparse.Namespace,
               report: dict[str, Any], timing: list[float]) -> tuple[str, str] | None:
    """有限退避获取HTML；挑战/429立即挂起，404才标记候选不存在。"""
    current = validate_guide_url(url)
    redirects = 0
    for attempt in range(3):
        while True:
            if report["requests"] >= args.max_requests:
                raise RequestBudgetReached("真实请求预算已耗尽")
            delay = args.interval - (time.monotonic() - timing[0])
            if delay > 0:
                time.sleep(delay)
            report["requests"] += 1
            timing[0] = time.monotonic()
            try:
                response = client.get(current)
            except httpx.RequestError:
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
                break
            if response.headers.get("cf-mitigated", "").lower() == "challenge" or response.status_code in (401, 403, 429):
                report["http_status"] = response.status_code
                report["retry_after"] = response.headers.get("retry-after")
                raise SourcePaused(f"来源暂不可访问：HTTP {response.status_code}；保留待处理记录")
            if response.status_code == 404:
                return None
            if response.is_redirect:
                redirects += 1
                if redirects > 3 or not response.headers.get("location"):
                    raise ValueError("跳转次数过多或缺少目标")
                current = validate_guide_url(str(response.url.join(response.headers["location"])))
                continue
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                break
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "").lower():
                raise ValueError("响应不是HTML")
            if len(response.content) > MAX_HTML_BYTES:
                raise ValueError("响应超过10MiB")
            html = response.text
            if re.search(r"<title[^>]*>\s*(?:Just a moment|Attention Required)", html, re.I) or any(
                marker in html.casefold() for marker in ("cf-chl", "cf-mitigated", "challenge-platform", "cf-browser-verification")
            ):
                raise SourcePaused("来源返回挑战页面，尚未取得游戏HTML")
            return html, current
    raise RuntimeError("HTTP获取失败")


def finish(directory: Path, report: dict[str, Any]) -> int:
    """持久化最终摘要；来源暂停用退出码2，数据/写入错误用退出码1。"""
    report["finished_at"] = utc_now()
    report["counts"] = dict(Counter(g["state"] for g in report["games"]))
    if "writes" in report:
        report["write_counts"] = dict(Counter(g["state"] for g in report["writes"]))
    save_json(directory / "report.json", report)
    print(json.dumps({**report, "report": str(directory / "report.json")}, ensure_ascii=False, indent=2, allow_nan=False))
    if report["state"] == "source_paused":
        return 2
    if report["state"] == "error" or report["counts"].get("error") or report.get("write_counts", {}).get("conflict"):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """定义独立预检、HTTP采集、本地HTML导入及来源记录重放命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "fetch", "import-html", "apply"):
        command = sub.add_parser(name)
        command.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
        command.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
        if name != "import-html":
            command.add_argument("--appids", type=int, nargs="+")
        if name in ("plan", "fetch"):
            command.add_argument("--mapping", type=Path)
            command.add_argument("--limit", type=int, default=20)
        if name == "fetch":
            command.add_argument("--max-requests", type=int, default=20)
            command.add_argument("--interval", type=float, default=3)
            command.add_argument("--timeout", type=float, default=30)
            command.add_argument("--refresh", action="store_true")
            command.add_argument("--retry-errors", action="store_true", help="重新处理已达到3轮失败上限的游戏")
            command.add_argument("--apply", action="store_true")
        if name == "import-html":
            command.add_argument("--appid", type=int, required=True)
            command.add_argument("--url", required=True)
            command.add_argument("--html-file", type=Path, required=True)
            command.add_argument("--source-kind", choices=("http_html", "browser_dom"), default="http_html")
            command.add_argument("--fetched-at", help="实际读取时间，ISO8601含时区；缺省为导入时刻")
            command.add_argument("--page-game-name", help="明确核对过的页面别名；默认要求本地完整名称一致")
            command.add_argument("--apply", action="store_true")
        if name == "apply":
            command.add_argument("--receipts", type=Path)
        if name in ("import-html", "apply", "fetch"):
            command.add_argument("--overwrite", action="store_true", help="显式替换非空冲突值；NULL不清除已有值")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行本地六表补全；所有写入、网络与状态均由显式子命令控制。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    directory: Path | None = None
    report: dict[str, Any] | None = None
    runtime_lock: BinaryIO | None = None
    try:
        database = database_path(args.database)
        runtime = workspace_path(args.runtime)
        all_games = read_games(database)
        by_id = {g["appid"]: g for g in all_games}
        selected_ids = [args.appid] if args.command == "import-html" else args.appids
        if selected_ids is not None and (any(i <= 0 or i not in by_id for i in selected_ids) or len(set(selected_ids)) != len(selected_ids)):
            raise ValueError("AppID必须是本地存在且不重复的正整数")
        games = [by_id[i] for i in selected_ids] if selected_ids else all_games
        if args.command in ("plan", "fetch"):
            if args.limit < 1:
                raise ValueError("limit必须大于0")
            mapping = load_mapping(args.mapping, all_games)
            include_complete = args.command == "fetch" and (args.refresh or args.overwrite)
            pending = [g for g in games if include_complete or any(g[f] is None for f in FIELDS)]
            if args.command == "plan":
                print(json.dumps({"scope": "achievement_difficulty_reference", "selected_count": len(games), "pending_count": len(pending),
                    "missing_fields": {f: sum(g[f] is None for g in games) for f in FIELDS},
                    "games": [{"appid": g["appid"], "name_en": g["name_en"], **mapping.get(g["appid"], {"url": None, "method": "unmapped"})} for g in pending[:args.limit]],
                    "note": "URL只是候选，网页名称校验成功后才算匹配；plan不发请求、不落盘"}, ensure_ascii=False, indent=2))
                return 0
            if args.max_requests < 0 or not math.isfinite(args.interval) or not 1 <= args.interval <= 60 or not math.isfinite(args.timeout) or not 1 <= args.timeout <= 60:
                raise ValueError("预算须非负；interval/timeout须为1～60秒有限数")
        runtime_lock = acquire_runtime_lock(runtime)
        directory, report = new_run(runtime, args.command)
        report["database"] = str(database)
        report["selected_count"] = len(games)
        records: list[dict[str, Any]] = []
        if args.command == "import-html":
            html_path = workspace_path(args.html_file, must_exist=True)
            if html_path.stat().st_size > MAX_HTML_BYTES:
                raise ValueError("HTML超过10MiB")
            raw = html_path.read_bytes()
            fetched_at = args.fetched_at or utc_now()
            moment = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                raise ValueError("fetched-at必须含时区")
            record = make_record(games[0], raw.decode("utf-8-sig"), args.url,
                                 args.source_kind, fetched_at, args.page_game_name)
            receipt = save_receipt(runtime, record, raw)
            record["receipt"] = str(receipt)
            records.append(record)
            report["games"].append({"appid": record["appid"], "state": record["status"], "values": record["values"], "receipt": str(receipt)})
        elif args.command == "apply":
            receipt_root = workspace_path(args.receipts or runtime / "receipts")
            if not receipt_root.exists():
                raise ValueError("来源记录文件/目录不存在；请先fetch或import-html")
            cached = latest_receipts(receipt_root, {g["appid"]: g for g in games})
            if not cached:
                raise ValueError("选中的游戏没有可重放来源记录")
            if selected_ids and set(selected_ids) - set(cached):
                raise ValueError(f"选中AppID缺少来源记录：{sorted(set(selected_ids) - set(cached))}")
            records = list(cached.values())
            report["games"] = [{"appid": r["appid"], "state": r["status"], "receipt": r["receipt"]} for r in records]
        else:
            report["selected_count"] = len(games)
            report["pending_count_before"] = len(pending)
            cached = {} if args.refresh else latest_receipts(runtime / "receipts", {g["appid"]: g for g in games})
            progress = read_progress(runtime)
            queued: list[dict[str, Any]] = []
            terminal = {"parsed", "partial", "missing", "unmatched", "unmapped"}
            for game in pending:
                entry = mapping.get(game["appid"])
                key = progress_key(game, entry)
                previous = progress["entries"].get(key, {})
                old = cached.get(game["appid"])
                if old and entry and entry.get("url") and old["source_url"] == validate_guide_url(entry["url"]) and old.get("mapping_alias") == entry.get("page_game_name"):
                    records.append(old)
                    report["games"].append({"appid": game["appid"], "state": "reused", "receipt": old["receipt"], "values": old["values"]})
                    continue
                if not args.refresh and previous.get("state") in {"parsed", "partial", "missing"}:
                    try:
                        stored = workspace_path(Path(previous["receipt"]), must_exist=True)
                        recovered = verify_receipt(stored, {game["appid"]: game})
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        report["games"].append({"appid": game["appid"], "state": "error", "error": f"历史来源记录缺失或损坏，可用--refresh重新采集：{error}"})
                        continue
                    records.append(recovered)
                    report["games"].append({"appid": game["appid"], "state": "reused", "receipt": recovered["receipt"], "values": recovered["values"]})
                    continue
                if not args.refresh and previous.get("state") in terminal:
                    report["games"].append({"appid": game["appid"], "state": "previously_attempted", "source_state": previous["state"]})
                    continue
                if not args.refresh and not args.retry_errors and previous.get("state") == "error" and previous.get("attempts", 0) >= 3:
                    report["games"].append({"appid": game["appid"], "state": "exhausted"})
                    continue
                queued.append(game)
            report["queued_count"] = len(queued)
            timing = [0.0]
            with httpx.Client(timeout=args.timeout, follow_redirects=False,
                              headers={"User-Agent": "achievement-analytics-course/0.1", "Accept": "text/html"}) as client:
                for game in queued[:args.limit]:
                    entry = mapping.get(game["appid"])
                    key = progress_key(game, entry)
                    previous = progress["entries"].get(key, {})
                    if not entry or not entry["url"]:
                        report["games"].append({"appid": game["appid"], "state": "unmapped"})
                        progress["entries"][key] = {"appid": game["appid"], "state": "unmapped", "updated_at": utc_now()}
                        save_json(runtime / "progress.json", progress)
                        continue
                    try:
                        result = fetch_html(client, entry["url"], args, report, timing)
                        if result is None:
                            report["games"].append({"appid": game["appid"], "state": "unmatched", "url": entry["url"]})
                            progress["entries"][key] = {"appid": game["appid"], "state": "unmatched", "updated_at": utc_now()}
                            save_json(runtime / "progress.json", progress)
                            continue
                        html, url = result
                        record = make_record(game, html, url, "http_html", utc_now(), entry.get("page_game_name"))
                        receipt = save_receipt(runtime, record, html.encode("utf-8"))
                        record["receipt"] = str(receipt)
                        state = record["status"]
                        records.append(record)
                        report["games"].append({"appid": game["appid"], "state": state, "receipt": record["receipt"], "values": record["values"]})
                        progress["entries"][key] = {"appid": game["appid"], "state": state, "receipt": record["receipt"], "updated_at": utc_now()}
                    except SourcePaused as error:
                        report["state"] = "source_paused"
                        report["games"].append({"appid": game["appid"], "state": "blocked", "error": str(error)})
                        break
                    except RequestBudgetReached:
                        report["state"] = "budget_reached"
                        break
                    except (ValueError, httpx.HTTPError, RuntimeError) as error:
                        report["games"].append({"appid": game["appid"], "state": "error", "error": str(error)})
                        progress["entries"][key] = {"appid": game["appid"], "state": "error", "attempts": previous.get("attempts", 0) + 1, "updated_at": utc_now()}
                    save_json(runtime / "progress.json", progress)
                    save_json(directory / "report.json", report)
            attempted_states = terminal | {"error"}
            queued_ids = {g["appid"] for g in queued}
            attempted = sum(g["appid"] in queued_ids and g["state"] in attempted_states for g in report["games"])
            report["remaining_unattempted_count"] = len(queued) - attempted
        if args.command == "apply" or args.apply:
            apply_records(database, records, directory, report, args.overwrite)
        current = read_games(database, [g["appid"] for g in games])
        report["remaining_missing_fields"] = {f: sum(g[f] is None for g in current) for f in FIELDS}
        report["complete_game_count"] = sum(all(g[f] is not None for f in FIELDS) for g in current)
        if report["state"] == "running":
            report["state"] = "completed_with_errors" if any(g["state"] == "error" for g in report["games"]) else (
                "batch_completed" if report.get("remaining_unattempted_count", 0) else "completed_selection"
            )
        return finish(directory, report)
    except (OSError, ValueError, RuntimeError, httpx.HTTPError, sqlite3.Error, KeyError, TypeError) as error:
        if directory is not None and report is not None:
            report["state"] = "error"
            report["error"] = str(error)
            return finish(directory, report)
        print(json.dumps({"state": "error", "error": str(error)}, ensure_ascii=False))
        return 1
    finally:
        if runtime_lock is not None:
            runtime_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
