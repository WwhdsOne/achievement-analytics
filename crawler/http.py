"""crawler.http — 共享的 HTTP 请求与缓存层

所有数据源模块共用这一层：
- 全局限速：相邻请求间隔 >= REQUEST_INTERVAL_SEC
- 失败重试 <= MAX_RETRIES，失败记日志不中断
- 缓存到 data/raw/cache/，已爬不重爬（断点续爬）

本模块不含任何业务逻辑，缓存键由调用方按业务决定。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from crawler.config import DATA_RAW, MAX_RETRIES, REQUEST_INTERVAL_SEC

logger = logging.getLogger(__name__)

CACHE_DIR: Path = DATA_RAW / "cache"

# 部分站点（如 Steam 社区页）会拒绝默认 python UA
REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; achievement-analytics/0.1)"
}

_last_request_ts = 0.0


def _throttle() -> None:
    """全局限速：保证相邻两次请求间隔 >= REQUEST_INTERVAL_SEC。"""
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    if elapsed < REQUEST_INTERVAL_SEC:
        time.sleep(REQUEST_INTERVAL_SEC - elapsed)
    _last_request_ts = time.monotonic()


def request_json(url: str, params: dict[str, Any]) -> Any:
    """GET 并解析 JSON：限速 + 失败重试 <= MAX_RETRIES。不含缓存。

    Raises:
        RuntimeError: 重试耗尽仍失败。
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _throttle()
            resp = httpx.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_exc = exc
            logger.warning(
                "请求失败（%d/%d）%s %s：%s", attempt, MAX_RETRIES, url, params, exc
            )
    raise RuntimeError(f"重试耗尽：{url} {params}") from last_exc


def request_text(url: str) -> str:
    """GET 并返回网页文本（用于 HTML 页面）。限速与重试同 request_json。

    Raises:
        RuntimeError: 重试耗尽仍失败。
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _throttle()
            resp = httpx.get(url, headers=REQUEST_HEADERS, timeout=30.0)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("请求失败（%d/%d）%s：%s", attempt, MAX_RETRIES, url, exc)
    raise RuntimeError(f"重试耗尽：{url}") from last_exc


def cache_path(key: str) -> Path:
    """缓存键 -> data/raw/cache/ 下文件路径。键须为合法文件名字符。"""
    return CACHE_DIR / f"{key}.json"


def read_cache(key: str) -> Any | None:
    """命中返回缓存内容，未命中或文件损坏返回 None。"""
    path = cache_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("缓存损坏，忽略并重爬：%s", path.name)
        return None


def write_cache(key: str, payload: Any) -> None:
    """写入缓存。键唯一即文件唯一，不覆盖其他条目。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(key).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cache_fetched_at(key: str) -> datetime | None:
    """缓存文件的写入时间 —— 即该数据的**真实抓取时间**。

    用途：``ingest_log.fetched_at`` 不能用事务的 ``now()``。数据可能来自几天前
    的缓存，用 ``now()`` 会把"抓取时间"记成"入库时间"，直接答错"何时获取"
    （2026-09-15 发现）。缓存文件在抓取成功的当下写入，其 mtime 才是准确值。

    Returns:
        带时区的抓取时间；缓存文件不存在（该源未跑或跳过）时返回 None。
    """
    path = cache_path(key)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
