"""写入层的契约测试：日期解析、games 表的 NOT NULL 陷阱、状态枚举一致性。

不需要真数据库——用假 connection 记录参数。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from cleaning.writers import (
    parse_release_date,
    update_game_fields,
    upsert_game,
)

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "cleaning" / "schema.sql"


class _FakeResult:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount


class FakeConn:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.executed: list[dict[str, Any]] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        if params is not None:
            self.executed.append(params)
        return _FakeResult(self.rowcount)


# ── 日期解析 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Apr 11, 2016", "2016-04-11"),   # appdetails 的展示格式
        ("Sep 10, 2026", "2026-09-10"),   # 商店搜索的展示格式（同格式）
        ("2016-04-11", "2016-04-11"),     # 已是 ISO
        ("2026", "2026-01-01"),           # 只有年份
    ],
)
def test_parse_release_date_formats(raw: str, expected: str) -> None:
    assert parse_release_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "Coming soon", "Q1 2024", "待定"])
def test_parse_release_date_unparseable_is_none(raw: str | None) -> None:
    """解析不了要返回 None 并告警，**不能臆造成某个日期**。"""
    assert parse_release_date(raw) is None


# ── games 表的 NOT NULL 陷阱 ──────────────────────────────


def test_upsert_game_rejects_empty_name_en() -> None:
    """name_en 为空必须**主动报错**，而不是让 Postgres 抛约束异常。

    踩过两次的坑：``games.name_en`` 是 NOT NULL，而 PostgreSQL 在 ON CONFLICT
    判定**之前**就校验 NOT NULL —— 所以「传 None 让
    ``COALESCE(EXCLUDED.name_en, games.name_en)`` 保住原值」这个想法不成立，
    插入路径会直接失败（连已存在的行也救不了）。只补其它字段要用
    :func:`update_game_fields`。
    """
    conn = FakeConn()
    with pytest.raises(ValueError, match="name_en"):
        upsert_game(conn, 1, name_en="")
    assert conn.executed == [], "不该发出任何 SQL"


def test_upsert_game_writes_when_name_present() -> None:
    conn = FakeConn()
    upsert_game(conn, 42, name_en="DARK SOULS III", name_zh="黑暗之魂3")
    p = conn.executed[-1]
    assert p["appid"] == 42
    assert p["name_en"] == "DARK SOULS III"
    assert p["name_zh"] == "黑暗之魂3"


def test_update_game_fields_does_not_touch_name_en() -> None:
    """UPDATE-only 路径只能改 name_zh / source_title，**绝不能碰 name_en**。

    否则「补一个来源标题」就能悄悄改掉游戏身份。
    """
    conn = FakeConn()
    update_game_fields(conn, 7, source_title="B站白金视频标题")
    p = conn.executed[-1]
    assert "name_en" not in p
    assert p["source_title"] == "B站白金视频标题"


def test_update_game_fields_reports_missing_row() -> None:
    """行不存在时返回 0 —— 调用方据此判断前置缺失（如 appdetails_en 没跑成功）。"""
    conn = FakeConn(rowcount=0)
    assert update_game_fields(conn, 7, name_zh="某中文名") == 0
    conn2 = FakeConn(rowcount=1)
    assert update_game_fields(conn2, 7, name_zh="某中文名") == 1


# ── schema 契约：状态枚举 ─────────────────────────────────


def _fetch_tasks_status_check() -> set[str]:
    """从 schema.sql 解析 fetch_tasks.status 的 CHECK 允许值。"""
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    block = re.search(
        r"CREATE TABLE IF NOT EXISTS fetch_tasks\s*\((.*?)\n\);", sql, re.S
    )
    assert block, "找不到 fetch_tasks 建表语句"
    check = re.search(r"status\s+TEXT\s+NOT NULL DEFAULT '(\w+)'\s+CHECK \(status IN \(([^)]*)\)\)", block.group(1), re.S)
    assert check, "找不到 fetch_tasks.status 的 CHECK 约束"
    allowed = set(re.findall(r"'(\w+)'", check.group(2)))
    allowed.add(check.group(1))  # DEFAULT 也是合法值
    return allowed


def test_worker_statuses_are_allowed_by_schema() -> None:
    """worker 会写入的状态必须都在 fetch_tasks 的 CHECK 白名单里。

    漏一个就会在跑到一半时爆 CHECK 约束——而且是在长时间抓取之后才暴露。
    """
    allowed = _fetch_tasks_status_check()
    written_by_worker = {"ok", "empty", "skipped", "error", "exhausted"}
    assert written_by_worker <= allowed, (
        f"worker 会写但 schema 不允许：{written_by_worker - allowed}"
    )


def test_schema_has_pending_default() -> None:
    """初始状态必须是 pending，否则新物化的任务会被 worker 忽略。"""
    assert "pending" in _fetch_tasks_status_check()
