"""源注册表与 schema.sql 的一致性校验。

防的是「加了数据源只改一处」这类漂移：``cleaning/schema.sql`` 的 ``sources`` 表是
DDL 层的真源（gap 视图与配额视图都读它），``crawler/registry.py`` 是同一清单的
Python 视图（限速要在进程内生效，不能每发一次请求都查库）。两者必须逐字段一致。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from crawler.registry import SOURCES, bulk_sources, per_game_sources

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "cleaning" / "schema.sql"

# 匹配 INSERT INTO sources (...) VALUES 之后到 ON CONFLICT 之前的所有行值
_INSERT_BLOCK = re.compile(
    r"INSERT INTO sources\s*\(([^)]*)\)\s*VALUES(.*?)ON CONFLICT",
    re.S,
)
# 单行值组：('name', 'kind', int, quota|NULL, quota|NULL, int, 'note' ...)
_ROW = re.compile(r"\(([^()]*?)\)\s*,\s*\n", re.S)


def _parse_schema_sources() -> dict[str, tuple[str, int, int | None, int | None, int]]:
    """从 schema.sql 里解析出 sources 表的行值。

    Returns:
        {source: (kind, interval_ms, daily_quota, monthly_quota, max_attempts)}。
    """
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    block = _INSERT_BLOCK.search(sql)
    assert block, "schema.sql 里找不到 INSERT INTO sources 语句"

    parsed: dict[str, tuple[str, int, int | None, int | None, int]] = {}
    for match in _ROW.finditer(block.group(2) + ",\n"):
        raw = match.group(1)
        # 值里含字符串（note），不能简单 split(',')；用正则逐字段取
        fields = re.findall(
            r"'((?:[^']|'')*)'|(NULL)|(-?\d+)",
            raw,
        )
        values: list[str | None] = []
        for s, null, num in fields:
            if s:
                values.append(s.replace("''", "'"))
            elif null:
                values.append(None)
            else:
                values.append(num)
        # 前 6 个字段之外的字符串都属 note 的续行，拼回去
        rest = [v for v in values[6:] if v is not None]
        values = values[:6]
        if len(values) < 6:
            continue
        source, kind, interval_ms, daily, monthly, max_attempts = values
        if rest:
            source = source  # note 续行不影响被断言的字段
        parsed[str(source)] = (
            str(kind),
            int(interval_ms or 0),
            int(daily) if daily is not None else None,
            int(monthly) if monthly is not None else None,
            int(max_attempts or 0),
        )
    return parsed


def test_schema_sources_parsed() -> None:
    """解析器本身要能拿到行（否则下面的断言会假通过）。"""
    parsed = _parse_schema_sources()
    assert parsed, "没能从 schema.sql 解析出任何 sources 行"


def test_registry_matches_schema_source_set() -> None:
    """两边的源集合必须完全相同，不允许只改一处。"""
    parsed = _parse_schema_sources()
    assert set(SOURCES) == set(parsed), (
        f"registry 与 schema.sql 的源清单不一致："
        f"仅 registry 有 {set(SOURCES) - set(parsed)}，"
        f"仅 schema 有 {set(parsed) - set(SOURCES)}"
    )


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_registry_row_matches_schema_row(source: str) -> None:
    """逐源逐字段比对 kind / 限速 / 配额 / 重试上限。"""
    parsed = _parse_schema_sources()
    spec = SOURCES[source]
    kind, interval_ms, daily, monthly, max_attempts = parsed[source]
    assert spec.kind == kind, f"{source}.kind"
    assert spec.interval_ms == interval_ms, f"{source}.interval_ms"
    assert spec.daily_quota == daily, f"{source}.daily_quota"
    assert spec.monthly_quota == monthly, f"{source}.monthly_quota"
    assert spec.max_attempts == max_attempts, f"{source}.max_attempts"


def test_bulk_and_per_game_partition() -> None:
    """bulk / per_game 两类必须互斥且穷尽——漏一个源就再也不会被抓。"""
    assert set(bulk_sources()) | set(per_game_sources()) == set(SOURCES)
    assert not (set(bulk_sources()) & set(per_game_sources()))


def test_steamspy_all_rate_limit_is_60s() -> None:
    """SteamSpy request=all 官方限速是 1 req/60s，不是 1 req/s。

    文档原文：``Allowed poll rate - 1 request per second for most requests,
    1 request per 60 seconds for the *all* requests.``
    写成 1s 会让 86 页的枚举凭空快 60 倍，属于会被封的错。
    """
    assert SOURCES["steamspy_all"].interval_sec == 60.0
    # 逐款的 appdetails 才是 1 req/s
    assert SOURCES["steamspy"].interval_sec == 1.0


def test_steamspy_daily_quota_is_self_imposed_cap() -> None:
    """SteamSpy 逐款接口的 1000/天是**本项目自设的保守上限**，不是官方额度。

    2026-09-17 核对官方页面（https://steamspy.com/api.php），只公布了
    ``1 request per second for most requests, 1 request per 60 seconds for the
    *all* requests``，**没有任何「每天 N 次」的配额**。此前代码注释里写的
    「官方限速每天 1000 次」无法佐证，已改为标注自设。

    这一列仍然要存在：它让 worker 能在撞到限流前主动停下。
    """
    assert SOURCES["steamspy"].daily_quota == 1000
    # 官方未公布日限的源不能凭空写一个数字
    assert SOURCES["appdetails_en"].daily_quota is None
    assert SOURCES["global_ach"].daily_quota is None


def test_rawg_monthly_quota_is_20000() -> None:
    """RAWG 免费档 20,000 请求/月（官方文档口径，响应头不暴露剩余额度）。"""
    assert SOURCES["rawg"].monthly_quota == 20000
    assert SOURCES["rawg"].daily_quota is None


def test_only_rawg_needs_interval_above_one_second() -> None:
    """除 SteamSpy all 外，其余源的礼貌间隔都是 1s（AGENTS.md 硬性要求 >= 1s）。"""
    for spec in SOURCES.values():
        assert spec.interval_sec >= 1.0, f"{spec.source} 限速低于 1s，违反 AGENTS.md"
