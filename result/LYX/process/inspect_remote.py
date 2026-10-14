"""只读核验共享 PostgreSQL；不导入成就、不初始化 SQLite、不修改其他目录。"""

from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import psycopg
from dotenv import dotenv_values

WORKSPACE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WORKSPACE.parents[1]
OPTIONS = (
    "-c default_transaction_read_only=on -c statement_timeout=8000 "
    "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=10000"
)
TABLES = ("games", "achievements", "mapping_issues", "dataset_versions", "game_tags", "ingest_log")


def error_summary(exc: Exception) -> dict[str, Any]:
    """仅输出异常类别，不输出可能包含地址、用户名或口令的原始错误。"""
    message = str(exc).lower()
    kind = next((kind for token, kind in (
        ("timeout", "timeout"), ("no password", "password_required"),
        ("authentication", "authentication"), ("closed the connection", "server_closed"),
        ("refused", "connection_refused"),
    ) if token in message), "connection_error")
    return {"error_class": type(exc).__name__, "error_kind": kind,
            "sqlstate": getattr(exc, "sqlstate", None)}


def idea_parameters() -> dict[str, Any] | None:
    """读取 PyCharm 项目数据源；不访问或解密 IDE 的全局密码保险箱。"""
    source_file = PROJECT_ROOT / ".idea" / "dataSources.xml"
    local_file = PROJECT_ROOT / ".idea" / "dataSources.local.xml"
    if not source_file.exists():
        return None
    sources = ET.parse(source_file).findall(".//data-source")
    candidates = [source for source in sources if source.findtext("driver-ref") == "postgresql"]
    if len(candidates) != 1:
        return None  # 多个数据源不能凭顺序猜测目标。
    source = candidates[0]
    local = next((item for item in ET.parse(local_file).findall(".//data-source")
                  if item.get("uuid") == source.get("uuid")), None) if local_file.exists() else None
    url = urlparse((source.findtext("jdbc-url") or "").removeprefix("jdbc:"))
    query = parse_qs(url.query)
    user = source.findtext("user-name") or (local.findtext("user-name") if local is not None else None)
    password = source.findtext("password") or (local.findtext("password") if local is not None else None)
    if not url.hostname or not user or not password:
        return None
    params = {"host": url.hostname, "port": url.port or 5432,
              "dbname": unquote(url.path.lstrip("/")), "user": user, "password": password}
    if query.get("sslmode"):
        params["sslmode"] = query["sslmode"][0]
    return params


def connect_readonly() -> tuple[psycopg.Connection[Any] | None, list[dict[str, Any]]]:
    """优先完整的 IDE 保存配置，再回退 .env；连接创建时强制只读。"""
    attempts: list[dict[str, Any]] = []
    common = {"connect_timeout": 7, "application_name": "lyx_schema_readonly", "options": OPTIONS}
    try:
        idea = idea_parameters()
    except (ET.ParseError, OSError, ValueError) as exc:
        idea = None
        attempts.append({"route": "pycharm_saved_config", "connected": False, **error_summary(exc)})
    if idea:
        try:
            connection = psycopg.connect(**idea, **common)
            attempts.append({"route": "pycharm_saved_config", "connected": True})
            return connection, attempts
        except psycopg.Error as exc:
            attempts.append({"route": "pycharm_saved_config", "connected": False, **error_summary(exc)})
    elif not attempts:
        attempts.append({"route": "pycharm_saved_config", "connected": False,
                         "reason": "complete_credentials_not_available_in_project_xml"})
    values = dotenv_values(PROJECT_ROOT / ".env")
    if not all(values.get(key) for key in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")):
        attempts.append({"route": "dotenv", "connected": False, "reason": "required_configuration_missing"})
        return None, attempts
    params = {"host": values["POSTGRES_HOST"], "port": int(values.get("POSTGRES_PORT") or 5432),
              "dbname": values["POSTGRES_DB"], "user": values["POSTGRES_USER"],
              "password": values["POSTGRES_PASSWORD"]}
    if values.get("POSTGRES_SSLMODE"):
        params["sslmode"] = values["POSTGRES_SSLMODE"]
    for number in range(2):
        try:
            connection = psycopg.connect(**params, **common)
            attempts.append({"route": "dotenv", "attempt": number + 1, "connected": True})
            return connection, attempts
        except psycopg.Error as exc:
            attempts.append({"route": "dotenv", "attempt": number + 1, "connected": False, **error_summary(exc)})
            if number == 0:
                time.sleep(2)
    return None, attempts


def bounded_query(conn: psycopg.Connection[Any], sql: str,
                  params: Any = None) -> dict[str, Any]:
    """在独立保存点执行 SELECT；超时不会污染后续只读查询。"""
    try:
        with conn.transaction():
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                keys = [column.name for column in cursor.description or ()]
                return {"rows": [dict(zip(keys, row)) for row in cursor.fetchall()]}
    except psycopg.Error as exc:
        return {"unavailable": True, **error_summary(exc)}


def inspect_remote() -> dict[str, Any]:
    """返回脱敏的结构与规模报告；不查询成就正文或任何密钥表。"""
    conn, attempts = connect_readonly()
    report: dict[str, Any] = {"inspected_at": datetime.now(timezone.utc).isoformat(),
                              "connection_attempts": attempts, "queries": {}}
    if conn is None:
        report["connected"] = False
        return report
    report["connected"] = True
    report["connection_route"] = attempts[-1]["route"]
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SELECT current_setting('transaction_read_only')")
                report["transaction_read_only"] = cursor.fetchone()[0]
                if report["transaction_read_only"] != "on":
                    raise RuntimeError("readonly connection was not enforced")
            queries = {
                "columns": ("SELECT table_name,column_name,data_type,udt_name,is_nullable,"
                            "numeric_precision,numeric_scale FROM information_schema.columns "
                            "WHERE table_schema='public' AND table_name=ANY(%s) ORDER BY table_name,ordinal_position", (list(TABLES),)),
                "constraints": ("SELECT c.relname AS table_name,con.contype,pg_get_constraintdef(con.oid) AS definition "
                                "FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid "
                                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
                                "AND c.relname IN ('games','achievements','mapping_issues','dataset_versions') "
                                "ORDER BY c.relname,con.conname", None),
                "counts": ("SELECT (SELECT count(*) FROM games) AS games,"
                           "(SELECT count(*) FROM achievements) AS achievements,"
                           "(SELECT count(*) FROM mapping_issues WHERE NOT resolved) AS unresolved_mapping_games,"
                           "(SELECT count(*) FROM dataset_versions) AS dataset_versions", None),
                "achievement_sizes": ("SELECT pg_relation_size('public.achievements') AS table_bytes,"
                                      "pg_total_relation_size('public.achievements') AS table_and_indexes_bytes", None),
                "text_sample": ("SELECT count(*) AS sample_n,round(avg(octet_length(api_name)+octet_length(display_name)"
                                "+octet_length(coalesce(description,''))),1) AS mean_text_bytes FROM "
                                "(SELECT api_name,display_name,description FROM achievements TABLESAMPLE SYSTEM (0.2) LIMIT 2000) s", None),
                "game_achievement_distribution": ("SELECT count(*) AS games_with_achievements,round(avg(n),2) AS mean_achievements,"
                                                  "percentile_cont(0.5) WITHIN GROUP (ORDER BY n) AS median_achievements,"
                                                  "max(n) AS max_achievements FROM (SELECT appid,count(*) n FROM achievements GROUP BY appid) s", None),
            }
            for name, (sql, params) in queries.items():
                report["queries"][name] = bounded_query(conn, sql, params)
                if conn.closed or conn.broken:
                    break
    except (psycopg.Error, RuntimeError) as exc:
        report["inspection_error"] = error_summary(exc)
    report["inspection_complete"] = len(report["queries"]) == 6 and all(
        not query.get("unavailable") for query in report["queries"].values())
    return report


def main() -> None:
    """CLI：可将脱敏报告写入 LYX 工作空间，其余路径拒绝写入。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="可选报告路径，只允许在 result/LYX 内")
    args = parser.parse_args()
    output = args.output.resolve() if args.output else None
    if output is not None and not output.is_relative_to(WORKSPACE.resolve()):
        parser.error("输出必须位于 result/LYX 工作空间")
    report = inspect_remote()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
