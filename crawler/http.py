"""crawler.http — 共享的 HTTP 请求与缓存层

所有数据源模块共用这一层：
- **按站点**限速：相邻请求间隔 >= 该源的 interval（见 crawler.registry）
- 失败重试 <= MAX_RETRIES，失败记日志不中断
- 缓存到 data/raw/cache/，已爬不重爬（断点续爬）
- 真实请求计数钩子：只在**实际发出网络请求**时回调，供配额记账
  （缓存命中根本不经过本模块，因此天然不计入配额）

本模块不含任何业务逻辑，也不依赖数据库；缓存键由调用方按业务决定。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from crawler.config import (
    DATA_RAW,
    MAX_RETRIES,
    REQUEST_INTERVAL_SEC,
    RETRY_BACKOFF_SEC,
)
from crawler.registry import interval_for

logger = logging.getLogger(__name__)

CACHE_DIR: Path = DATA_RAW / "cache"

# 部分站点（如 Steam 社区页）会拒绝默认 python UA
REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; achievement-analytics/0.1)"
}

# 限速秒表：**按 host 分别计时**。旧版用一个全局变量，导致 Steam / SteamSpy / RAWG
# 三个不同站点互相排队，把总耗时凭空拉长（2026-09-17 发现）。
_last_ts: dict[str, float] = {}

# 真实请求计数回调，由调用方（worker）注入以写 api_usage
_call_recorder: Callable[[str], None] | None = None


def set_call_recorder(recorder: Callable[[str], None] | None) -> None:
    """注入「发出一次真实请求」的回调（参数为源标识）。

    用于配额记账。传 None 取消注入。HTTP 层本身不碰数据库，记账由调用方决定。
    """
    global _call_recorder
    _call_recorder = recorder


def _host_of(url: str) -> str:
    """取 URL 的 host 作为限速分桶键。"""
    return urlparse(url).netloc or url


def _throttle(url: str, interval_sec: float) -> None:
    """按站点限速：保证**同一 host** 相邻两次请求间隔 >= interval_sec。"""
    key = _host_of(url)
    elapsed = time.monotonic() - _last_ts.get(key, 0.0)
    if elapsed < interval_sec:
        time.sleep(interval_sec - elapsed)
    _last_ts[key] = time.monotonic()


def _resolve_interval(source: str | None, interval_sec: float | None) -> float:
    """显式 interval 优先；否则查注册表；再否则用全局默认。"""
    if interval_sec is not None:
        return interval_sec
    if source is not None:
        return interval_for(source, default=REQUEST_INTERVAL_SEC)
    return REQUEST_INTERVAL_SEC


def _backoff(attempt: int) -> None:
    """重试前的指数退避：2s、4s、8s…（封顶 30s）。

    只在**重试之间**调用。没有它时几次尝试会挤在同一个限流窗口里全部失败，
    小则浪费配额、大则让一次长任务整体中断（2026-09-17 实测）。
    """
    sleep_for = min(RETRY_BACKOFF_SEC * (2 ** (attempt - 1)), 30.0)
    logger.info("退避 %.1fs 后重试", sleep_for)
    time.sleep(sleep_for)


def request_json(
    url: str,
    params: dict[str, Any],
    *,
    source: str | None = None,
    interval_sec: float | None = None,
) -> Any:
    """GET 并解析 JSON：限速 + 失败重试 <= MAX_RETRIES。不含缓存。

    Args:
        url: 请求地址。
        params: query 参数。
        source: 源标识（crawler.registry 的键），用于取该源的限速间隔并记账。
        interval_sec: 显式覆盖限速间隔（秒）；给了就不查注册表。

    Returns:
        解析后的 JSON。

    Raises:
        RuntimeError: 重试耗尽仍失败。
    """
    interval = _resolve_interval(source, interval_sec)
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _throttle(url, interval)
            resp = httpx.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            if _call_recorder is not None:
                _call_recorder(source or _host_of(url))
            return resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_exc = exc
            logger.warning(
                "请求失败（%d/%d）%s %s：%s", attempt, MAX_RETRIES, url, params, exc
            )
            if attempt < MAX_RETRIES:
                _backoff(attempt)
    raise RuntimeError(f"重试耗尽：{url} {params}") from last_exc


def request_text(
    url: str,
    *,
    source: str | None = None,
    interval_sec: float | None = None,
) -> str:
    """GET 并返回网页文本（用于 HTML 页面）。限速与重试同 request_json。

    Raises:
        RuntimeError: 重试耗尽仍失败。
    """
    interval = _resolve_interval(source, interval_sec)
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _throttle(url, interval)
            resp = httpx.get(url, headers=REQUEST_HEADERS, timeout=30.0)
            resp.raise_for_status()
            if _call_recorder is not None:
                _call_recorder(source or _host_of(url))
            return resp.text
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("请求失败（%d/%d）%s：%s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                _backoff(attempt)
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
