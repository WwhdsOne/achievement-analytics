"""worker 的队列状态机与退避测试。

重点覆盖**循环为什么能终止**：
- ``empty`` / ``skipped`` / ``ok`` 是终态，不再重试
- ``error`` 退避重试，尝试次数达 ``sources.max_attempts`` 后转 ``exhausted``

不需要真数据库：用假 connection 记录写出的参数。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cleaning.worker import (
    BACKOFF_BASE_SEC,
    BACKOFF_CAP_SEC,
    UsageRecorder,
    complete,
    next_retry_at,
)


class _FakeResult:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


class FakeConn:
    """只认识 ``_max_attempts`` 的查询，其余 execute 记录下来当断言依据。"""

    def __init__(self, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts
        self.updates: list[dict[str, Any]] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        if "SELECT max_attempts" in str(stmt):
            return _FakeResult((self.max_attempts,))
        if params is not None:
            self.updates.append(params)
        return _FakeResult(None)


# ── 退避计算 ──────────────────────────────────────────────


def test_backoff_grows_exponentially() -> None:
    """第 1 次失败等 60s，第 2 次 120s，第 3 次 240s。"""
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    assert next_retry_at(1, now) == now + timedelta(seconds=BACKOFF_BASE_SEC)
    assert next_retry_at(2, now) == now + timedelta(seconds=BACKOFF_BASE_SEC * 2)
    assert next_retry_at(3, now) == now + timedelta(seconds=BACKOFF_BASE_SEC * 4)


def test_backoff_is_capped() -> None:
    """退避封顶，否则第 10 次失败要等好几天。"""
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    assert next_retry_at(20, now) == now + timedelta(seconds=BACKOFF_CAP_SEC)


def test_backoff_handles_zero_attempts() -> None:
    """attempts=0 不该算出负指数（防御性：调用方传错也不炸）。"""
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    assert next_retry_at(0, now) == now + timedelta(seconds=BACKOFF_BASE_SEC)


# ── 状态机：终态判定 ──────────────────────────────────────


def test_ok_is_terminal_without_retry() -> None:
    """成功是终态，不留 next_retry_at。"""
    conn = FakeConn()
    complete(conn, 1, "global_ach", "ok", None, attempts_after=1)
    u = conn.updates[-1]
    assert u["status"] == "ok"
    assert u["next_retry_at"] is None


def test_empty_is_terminal_this_is_what_makes_loop_terminate() -> None:
    """``empty`` 是**确定性终态**：该游戏确实没这项数据，绝不重试。

    这是整个循环能收敛的关键。旧设计把 empty 也算「缺口」，一个本来就没成就的
    游戏会被永远重爬。
    """
    conn = FakeConn()
    complete(conn, 1, "global_ach", "empty", None, attempts_after=1)
    u = conn.updates[-1]
    assert u["status"] == "empty"
    assert u["next_retry_at"] is None


def test_skipped_is_terminal() -> None:
    """未配 key 而跳过：终态，配好 key 后需人工重置回 pending。"""
    conn = FakeConn()
    complete(conn, 1, "rawg", "skipped", "RAWG_API_KEY 未配置", attempts_after=1)
    u = conn.updates[-1]
    assert u["status"] == "skipped"
    assert u["next_retry_at"] is None


def test_error_schedules_retry_below_limit() -> None:
    """未到上限的失败：保持 error 并排下次重试。"""
    conn = FakeConn(max_attempts=3)
    complete(conn, 1, "rawg", "error", "boom", attempts_after=1)
    u = conn.updates[-1]
    assert u["status"] == "error"
    assert u["next_retry_at"] is not None
    assert u["error"] == "boom"


def test_error_becomes_exhausted_at_limit() -> None:
    """尝试次数达上限：转 exhausted 并停止重试（终止条件的另一半）。"""
    conn = FakeConn(max_attempts=3)
    complete(conn, 1, "rawg", "error", "boom", attempts_after=3)
    u = conn.updates[-1]
    assert u["status"] == "exhausted"
    assert u["next_retry_at"] is None


def test_max_attempts_is_read_per_source() -> None:
    """上限按源取，不是硬编码常量。"""
    conn = FakeConn(max_attempts=1)
    complete(conn, 1, "rawg", "error", "boom", attempts_after=1)
    assert conn.updates[-1]["status"] == "exhausted"


# ── 配额记账 ──────────────────────────────────────────────


def test_usage_recorder_accumulates_and_drains() -> None:
    """真实请求数按源累计，drain 取走并清零（刷库后不该重复计）。"""
    rec = UsageRecorder()
    rec("rawg")
    rec("rawg")
    rec("global_ach")
    assert rec.drain() == {"rawg": 2, "global_ach": 1}
    assert rec.drain() == {}


def test_usage_recorder_is_callable_by_http_layer() -> None:
    """HTTP 层按 ``recorder(source)`` 回调，签名必须兼容。"""
    rec = UsageRecorder()
    assert callable(rec)
    rec(source="steamspy")
    assert rec.drain() == {"steamspy": 1}
