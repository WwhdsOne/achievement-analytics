"""crawler.http — 共享的 HTTP 请求层

所有数据源模块共用这一层：
- **按站点**限速：相邻请求间隔 >= 该源的 interval（见 crawler.registry）
- 失败重试 <= MAX_RETRIES，重试之间有指数退避
- 真实请求计数与抓取时间钩子：只在**实际发出网络请求**时回调/记录

**本层没有缓存**（2026-09-17 决定）：任务的状态由共享库的 ``fetch_tasks`` 表管
（抢占是原子的，完成的任务不会被重跑），数据库是唯一事实源，本地文件缓存只会
造成「多机各一份、跨机重复、删库前还得先搬」的负担。

暴露两组由调用方注入/读取的钩子：
- :func:`set_call_recorder` —— 每次真实请求回调一次（供 ``api_usage`` 记账）
- :func:`last_fetched_at` —— 每个源最近一次成功响应的时间（供 ``ingest_log.fetched_at``）

本模块不含任何业务逻辑，也不依赖数据库。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from crawler.config import (
    MAX_RETRIES,
    REQUEST_INTERVAL_SEC,
    RETRY_BACKOFF_SEC,
)
from crawler.registry import interval_for

logger = logging.getLogger(__name__)

# 部分站点（如 Steam 社区页）会拒绝默认 python UA
REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; achievement-analytics/0.1)"
}

# 限速秒表：**按 host 分别计时**。旧版用一个全局变量，导致 Steam / SteamSpy / RAWG
# 三个不同站点互相排队，把总耗时凭空拉长（2026-09-17 发现）。
_last_ts: dict[str, float] = {}

# 每个源最近一次**成功响应**的时刻（UTC）。替代旧版「缓存文件 mtime」：
# 没有缓存文件之后，真实抓取时间只能由请求本身记录。
_last_fetched_at: dict[str, datetime] = {}

# 真实请求计数回调，由调用方（worker）注入以写 api_usage
_call_recorder: Callable[[str], None] | None = None


def set_call_recorder(recorder: Callable[[str], None] | None) -> None:
    """注入「发出一次真实请求」的回调（参数为源标识）。

    用于配额记账。传 None 取消注入。HTTP 层本身不碰数据库，记账由调用方决定。
    """
    global _call_recorder
    _call_recorder = recorder


def last_fetched_at(source: str | None) -> datetime | None:
    """某源最近一次成功拿到响应的时刻（UTC）；该源从未成功过则返回 None。

    用途：``ingest_log.fetched_at`` 要的是「数据何时获取」，不是「何时写库」。
    旧版取缓存文件的 mtime；没有缓存之后由请求本身记录，语义不变。
    """
    if source is None:
        return None
    return _last_fetched_at.get(source)


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


class HttpStatusError(RuntimeError):
    """请求重试耗尽，且最后一次拿到了 HTTP 状态码。

    存在的理由：有些**状态码本身携带业务语义**，必须让调用方看见。典型例子是
    ``GetGlobalAchievementPercentagesForApp`` 对**没有成就数据**的 appid 返回
    **403**（实测 12/12 双向正确，2026-09-17）——如果只抛笼统的 RuntimeError，
    调用方就没法把「这游戏本来就没成就」（确定性）和「网络/限流故障」（可重试）
    区分开，前者会白白重试 3 次并最终记成 ``exhausted``。

    Attributes:
        status: 最后一次响应的 HTTP 状态码；连不上时为 None。
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class SourceChallenge(HttpStatusError):
    """被站点的反爬挑战挡住（典型：Cloudflare 的 ``cf-mitigated: challenge``）。

    为什么要单列一类（2026-09-24 加）：这类失败**不是任务的错，也不是网络故障**，
    而是「这个源暂时不欢迎自动请求」。它有两个和普通失败不同的性质：

    1. **快速重试毫无意义**：挑战窗口通常持续几分钟，2s/4s 的退避只会白烧请求；
    2. **不该消耗任务的重试预算**：``worker`` 每个任务周期 attempts+1，攒够
       ``sources.max_attempts`` 就转终态 ``exhausted``——2026-09-24 实测
       SteamSpy 的间歇 403 就这样烧掉了 23 条任务（数据其实过几分钟就能抓到）。

    所以调用方（``cleaning.worker``）应当把它当作「**源级临时不可用**」：
    任务放回 ``pending``、本轮的源挂起、稍后自然重试。

    继承 :class:`HttpStatusError`，这样没专门处理的调用方（如旧脚本）仍能
    按「带状态码的 HTTP 失败」对待，不会漏接。
    """


# Cloudflare 挑战页的响应体特征（大小写不敏感）。光看状态码不够——403 也可能
# 是业务语义（如全局成就率接口对「无成就」返回 403），所以必须同时看响应头/体。
_CHALLENGE_BODY_MARKERS = (
    "just a moment",
    "cf-chl",
    "challenge-platform",
    "cf_chl_opt",
    "__cf_chl",
    "attention required",
    "enable javascript and cookies",
)


def is_cloudflare_challenge(
    status: int | None, headers: Any, body: str
) -> bool:
    """判断响应是否为 Cloudflare 之类的反爬挑战页。

    Args:
        status: HTTP 状态码。
        headers: 响应头（大小写不敏感地按键取值）。
        body: 响应体（只看开头若干 KB 即可）。

    Returns:
        是否为挑战页。判据：状态码是 403/503 **且**
        （有 ``cf-mitigated`` 响应头 **或** 响应体含挑战页特征串）。
    """
    if status not in (403, 503):
        return False
    try:
        mitigated = (headers or {}).get("cf-mitigated", "")
    except AttributeError:  # 非常规 headers 容器
        mitigated = ""
    if str(mitigated).lower() == "challenge":
        return True
    low = (body or "")[:4096].lower()
    return any(marker in low for marker in _CHALLENGE_BODY_MARKERS)


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
    """GET 并解析 JSON：限速 + 失败重试 <= MAX_RETRIES。

    Args:
        url: 请求地址。
        params: query 参数。
        source: 源标识（crawler.registry 的键），用于取该源的限速间隔并记账。
        interval_sec: 显式覆盖限速间隔（秒）；给了就不查注册表。

    Returns:
        解析后的 JSON。

    Raises:
        HttpStatusError: 重试耗尽仍失败（带最后一次的 HTTP 状态码）。
    """
    interval = _resolve_interval(source, interval_sec)
    last_exc: Exception | None = None
    last_status: int | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _throttle(url, interval)
            # follow_redirects 必须开：Steam 社区页对改过名的老游戏会把
            # /stats/{appid}/achievements 302 到 /stats/{别名}/achievements
            # （实测 appid=300 → DOD:S），默认不跟随会被 raise_for_status 当错误
            # 白白重试 3 次（2026-09-22 踩到）。
            resp = httpx.get(
                url, params=params, headers=REQUEST_HEADERS, timeout=30.0,
                follow_redirects=True,
            )
            last_status = resp.status_code
            # 反爬挑战：立即抛出，不做快速重试（挑战窗口是分钟级，2s/4s 退避纯属浪费），
            # 让 worker 把它当作「源临时不可用」处理（2026-09-24）
            if is_cloudflare_challenge(last_status, resp.headers, resp.text):
                logger.warning(
                    "被反爬挑战拦截（status=%s，cf-mitigated=%s）：%s",
                    last_status, resp.headers.get("cf-mitigated"), url,
                )
                raise SourceChallenge(
                    f"被反爬挑战拦截：{url}（status={last_status}）", last_status
                )
            resp.raise_for_status()
            key = source or _host_of(url)
            _last_fetched_at[key] = datetime.now(timezone.utc)
            if _call_recorder is not None:
                _call_recorder(source or _host_of(url))
            return resp.json()
        except SourceChallenge:
            raise  # 挑战不算「重试耗尽」，原样上抛给 worker 做源级处理
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_exc = exc
            logger.warning(
                "请求失败（%d/%d）%s %s：%s", attempt, MAX_RETRIES, url, params, exc
            )
            if attempt < MAX_RETRIES:
                _backoff(attempt)
    raise HttpStatusError(
        f"重试耗尽：{url} {params}（最后状态码 {last_status}）", last_status
    ) from last_exc


def request_text(
    url: str,
    *,
    source: str | None = None,
    interval_sec: float | None = None,
) -> str:
    """GET 并返回网页文本（用于 HTML 页面）。限速与重试同 request_json。

    Raises:
        HttpStatusError: 重试耗尽仍失败。
    """
    interval = _resolve_interval(source, interval_sec)
    last_exc: Exception | None = None
    last_status: int | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _throttle(url, interval)
            resp = httpx.get(
                url, headers=REQUEST_HEADERS, timeout=30.0, follow_redirects=True
            )
            last_status = resp.status_code
            if is_cloudflare_challenge(last_status, resp.headers, resp.text):
                logger.warning(
                    "被反爬挑战拦截（status=%s）：%s", last_status, url
                )
                raise SourceChallenge(
                    f"被反爬挑战拦截：{url}（status={last_status}）", last_status
                )
            resp.raise_for_status()
            key = source or _host_of(url)
            _last_fetched_at[key] = datetime.now(timezone.utc)
            if _call_recorder is not None:
                _call_recorder(source or _host_of(url))
            return resp.text
        except SourceChallenge:
            raise  # 见 request_json 的同样说明
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("请求失败（%d/%d）%s：%s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                _backoff(attempt)
    raise HttpStatusError(f"重试耗尽：{url}（最后状态码 {last_status}）", last_status) from last_exc
