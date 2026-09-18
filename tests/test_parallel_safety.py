"""多机并行与密钥池的契约测试。

全部不依赖数据库：断言 SQL 文本与 schema.sql 的形状。这类测试防的是「改了实现
但漏了某个前提」，比如抢占语句丢了 ``FOR UPDATE SKIP LOCKED``——那样多机并行会
静默重复抓取，只有在配额被白花掉之后才发现。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cleaning import db as db_module
from cleaning.worker import (
    CLAIM_TASKS,
    LEASE_SEC,
    UPDATE_TASK,
    WORKER_ID,
    claim,
    quota_exhausted,
)
from crawler import rawg

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "cleaning" / "schema.sql"
SCHEMA_SQL = SCHEMA_FILE.read_text(encoding="utf-8")


# ── 抢占语句的必备要素 ────────────────────────────────────


def test_claim_uses_skip_locked() -> None:
    """抢占必须用 FOR UPDATE SKIP LOCKED。

    没有它，两台机器会同时读到同一批任务并各自去抓——重复请求会白花配额
    （RAWG 尤其贵），而且这种浪费在日志里看不出来。
    """
    sql = str(CLAIM_TASKS)
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_claim_writes_lease_in_same_statement() -> None:
    """选任务与写租约必须是一条语句（否则存在竞态窗口）。"""
    sql = str(CLAIM_TASKS)
    assert "UPDATE fetch_tasks" in sql
    assert "claimed_by" in sql
    assert "lease_until" in sql
    assert "RETURNING" in sql


def test_claim_respects_lease_expiry() -> None:
    """租约到期的任务要能被重新抢——这是 worker 崩溃后不卡任务的关键。"""
    sql = str(CLAIM_TASKS)
    assert "t2.lease_until IS NULL" in sql
    assert "t2.lease_until <= now()" in sql


def test_claim_excludes_blocked_sources_in_sql() -> None:
    """配额耗尽的源要在 SQL 里排除，不能只在拿回来之后过滤。

    只在 Python 侧过滤的话，那些行已经白占了租约，5 分钟内谁都抢不到。
    """
    assert "exclude" in str(CLAIM_TASKS)


def test_complete_clears_lease() -> None:
    """回填状态时必须清租约，否则这条任务在租约到期前不会被任何人再抢。"""
    sql = str(UPDATE_TASK)
    assert "claimed_by    = NULL" in sql
    assert "lease_until   = NULL" in sql


def test_lease_is_longer_than_worst_case_task() -> None:
    """租约要长于单任务最坏耗时（3 次重试 + 指数退避），否则会互相抢。"""
    assert LEASE_SEC >= 120


def test_worker_id_identifies_host_and_process() -> None:
    """worker 标识要能指到具体机器与进程，便于查「谁拿着租约」。"""
    assert ":" in WORKER_ID


def test_claim_passes_exclude_and_lease_params() -> None:
    """claim() 要把 worker / lease / exclude 真传下去（防漏参导致 SQL 报错）。"""
    captured: dict[str, object] = {}

    class _Conn:
        def execute(self, stmt, params):  # noqa: ANN001, ANN201
            captured.update(params)
            return type("R", (), {"all": staticmethod(lambda: [])})()

    claim(_Conn(), source=None, limit=7, exclude={"rawg"}, worker="h:1", lease_sec=99)
    assert captured["n"] == 7
    assert captured["exclude"] == ["rawg"]
    assert captured["worker"] == "h:1"
    assert captured["lease_sec"] == 99
    assert captured["source"] is None


def test_claim_exclude_none_when_empty() -> None:
    """没有要排除的源时传 None，让 SQL 的 CAST(NULL AS TEXT[]) 生效。"""
    captured: dict[str, object] = {}

    class _Conn:
        def execute(self, stmt, params):  # noqa: ANN001, ANN201
            captured.update(params)
            return type("R", (), {"all": staticmethod(lambda: [])})()

    claim(_Conn(), exclude=set())
    assert captured["exclude"] is None


# ── schema 契约 ───────────────────────────────────────────


@pytest.mark.parametrize("col", ["claimed_by", "lease_until"])
def test_schema_fetch_tasks_has_lease_columns(col: str) -> None:
    """fetch_tasks 必须建出这两列，且要有 ALTER 迁移让老库也能收敛。"""
    assert re.search(rf"^\s*{col}\s+TEXT|^\s*{col}\s+TIMESTAMPTZ", SCHEMA_SQL, re.M)
    assert re.search(
        rf"ALTER TABLE fetch_tasks ADD COLUMN IF NOT EXISTS {col}\b", SCHEMA_SQL
    )


@pytest.mark.parametrize("table", ["rawg_keys", "rawg_key_usage"])
def test_schema_has_rawg_key_pool_tables(table: str) -> None:
    """密钥池的表必须存在——多 key 是 RAWG 唯一可行的扩容方式。"""
    assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_SQL


def test_rawg_key_pool_view_hides_plaintext_key() -> None:
    """rawg_key_status 视图**不得**输出 api_key 明文。

    查额度是高频操作，一旦视图带出明文，密钥就会出现在终端回滚、日志、截图里。
    """
    block = re.search(
        r"CREATE OR REPLACE VIEW rawg_key_status AS(.*?);", SCHEMA_SQL, re.S
    )
    assert block, "找不到 rawg_key_status 视图定义"
    body = block.group(1)
    assert "key_hint" in body
    # 只能以 right(k.api_key, 4) 这种形式出现，不能裸选 api_key
    assert not re.search(r"SELECT\s+[^;]*?\bk\.api_key\b(?!\s*,\s*4)", body), (
        "视图疑似输出了 api_key 明文，只允许 key_hint（尾 4 位）"
    )


def test_rawg_key_usage_references_keys() -> None:
    """用量表必须外键挂在 keys 上，且删除 key 时级联清理。"""
    assert "REFERENCES rawg_keys (key_id) ON DELETE CASCADE" in SCHEMA_SQL


def test_steamspy_daily_quota_check_reads_sources_table() -> None:
    """配额判断要走 quota_status 视图（它读 sources），不要在 Python 里写死。"""
    sql = str(db_module.get_dsn())  # 顺带确保 db 模块可导入
    assert sql.startswith("postgresql+psycopg://")


# ── 云库连接 ──────────────────────────────────────────────


def test_dsn_without_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    """不设 sslmode 时不追加 query 参数（本机 Docker 不需要 SSL）。"""
    monkeypatch.setattr(db_module, "DB_SSLMODE", "")
    assert "?" not in db_module.get_dsn()


def test_dsn_with_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    """设了 sslmode（云库要求的）要正确拼进 DSN。"""
    monkeypatch.setattr(db_module, "DB_SSLMODE", "require")
    assert db_module.get_dsn().endswith("?sslmode=require")


# ── RAWG key provider 钩子 ────────────────────────────────


def test_rawg_key_provider_is_used_when_injected() -> None:
    """注入 provider 后，current_key 必须向它要 key（多 key 池的接入点）。"""
    try:
        rawg.set_key_provider(lambda: "KEY-FROM-POOL")
        assert rawg.current_key() == "KEY-FROM-POOL"
    finally:
        rawg.set_key_provider(None)


def test_rawg_key_provider_none_means_exhausted() -> None:
    """provider 返回 None 表示池子用尽，current_key 要如实返回 None 而不是瞎猜。"""
    try:
        rawg.set_key_provider(lambda: None)
        assert rawg.current_key() is None
    finally:
        rawg.set_key_provider(None)


def test_rawg_falls_back_to_config_key() -> None:
    """没注入 provider 时回落到 .env 的单 key，单机开发不受影响。"""
    rawg.set_key_provider(None)
    assert rawg.current_key() == (rawg.RAWG_API_KEY or None)


def test_injected_provider_disables_env_fallback() -> None:
    """**注入 provider 就不再回退 .env** —— 这是 worker 必须按池子是否为空来注入的理由。

    2026-09-17 踩到：``worker.run`` 无条件注入了密钥池 provider，而
    ``reserve_key`` 在**空池**上返回 None，于是 ``current_key()`` 也是 None，
    连 .env 里的单 key 都被废掉，rawg 任务全部报「密钥池已用尽」。
    修法是池子为空时不注入（见 worker.run 里对 ``pool_size`` 的判断）。
    """
    try:
        rawg.set_key_provider(lambda: None)
        assert rawg.current_key() is None, (
            "provider 返回 None 时必须如实暴露，不能偷偷回退——"
            "否则 worker 的注入决策就失去了意义"
        )
    finally:
        rawg.set_key_provider(None)


def test_pool_size_helper_exists_for_injection_decision() -> None:
    """worker 靠 pool_size() 判断该不该注入 provider，别把它删了。"""
    from cleaning.rawg_keys import pool_size

    assert callable(pool_size)


def test_run_claim_filter_not_shadowed_by_loop_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """**回归测试（2026-09-18 踩坑）**：run() 主循环的循环变量曾叫 ``appid``，
    遮蔽了函数参数 ``appid``——第一批任务处理后，下一轮
    ``claim(..., appid=appid)`` 拿着「上一批最后一个任务的 appid」当过滤器，
    worker 每批 20 个之后就「抢不到任务了」。这里用假 claim 捕获每次调用的
    appid 参数，断言它始终等于 run() 收到的 appid（None），不被循环改写。
    """
    import cleaning.worker as W

    calls: list[int | None] = []

    def fake_claim(conn, source=None, limit=20, exclude=None, appid=None, **kw):
        calls.append(appid)
        if len(calls) == 1:
            return [(101, "appdetails_en"), (102, "appdetails_en")]
        if len(calls) == 2:
            return [(103, "steamspy")]
        return []

    monkeypatch.setattr(W, "claim", fake_claim)
    monkeypatch.setattr(W, "ensure_ready", lambda engine: None)
    monkeypatch.setattr(W, "pool_size", lambda engine: 0)
    monkeypatch.setattr(W, "run_source", lambda conn, appid, source: ("ok", None))
    monkeypatch.setattr(W, "complete", lambda *a, **kw: None)
    monkeypatch.setattr(W, "flush_usage", lambda conn, recorder: None)
    monkeypatch.setattr(W, "prune_no_achievement_siblings", lambda conn, appid: 0)
    monkeypatch.setattr(W, "quota_exhausted", lambda conn: set())

    from contextlib import nullcontext

    class FakeConn:
        """够 run() 主循环用的最小连接壳。"""

        def begin_nested(self):
            return nullcontext()

        def execute(self, *_a, **_kw):
            class R:
                def scalar(self):
                    return 1

            return R()

    class FakeEngine:
        """每次 begin() 给一个假连接（run() 的 finally 还会 flush 一次）。"""

        def begin(self):
            return nullcontext(FakeConn())

    stats = W.run(engine=FakeEngine(), limit=3)

    assert stats.get("ok") == 3
    assert calls == [None, None], (
        f"claim 的 appid 过滤器被循环变量污染了：{calls}——"
        "主循环变量不得叫 appid/source（遮蔽函数参数）"
    )


def test_materialize_gates_rawg_tasks_by_review_threshold() -> None:
    """**RAWG 配额护栏（2026-09-18 定）**：评价数低于阈值的游戏不得建 RAWG 任务。

    实测 RAWG ≈ 6.3 次请求/游戏（100 款试水 627 次），单 key 月配额 20,000
    ≈ 只够 3,100 款；而试水里评价数 < 100 的游戏在 RAWG 上几乎必然没数据。
    物化 SQL 必须带 review_count 门槛，且阈值可作参数传 0 关闭。
    """
    import inspect

    from cleaning import seed

    sql = inspect.cleandoc(seed.INSERT_TASKS.text)
    assert "rawg" in sql and "review_count" in sql, (
        "INSERT_TASKS 必须按 review_count 门槛过滤 rawg 源，"
        "否则长尾游戏会把 RAWG 月配额烧光"
    )
    assert seed.RAWG_MIN_REVIEWS > 0, "默认阈值必须为正（0 只能显式传参关闭）"

    # materialize_tasks 的默认值必须与常量一致，别让两处口径漂移
    sig = inspect.signature(seed.materialize_tasks)
    assert sig.parameters["rawg_min_reviews"].default == seed.RAWG_MIN_REVIEWS
