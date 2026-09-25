"""tests.test_http_challenge — 反爬挑战（Cloudflare 403）的识别与处置

背景（2026-09-24）：SteamSpy 间歇返回 Cloudflare 挑战 403，worker 的「3 次快速重试
→ 记 error → 攒满 attempts → exhausted」把 23 条任务烧成终态。修法是把「被挑战」
单列成 :class:`SourceChallenge`：不快速重试、不消耗任务预算，由 worker 做源级挂起。

这里锁住三件事：
1. 识别判据（403 + cf-mitigated 头或挑战页特征串），且**不误伤**业务语义的 403；
2. HTTP 层遇到挑战**立即抛出**，不做 3 次快速重试（省请求、省时间）；
3. 全局成就率接口的 403 语义（「无成就」）**不被挑战 403 污染**——否则会把游戏
   误判成「没有成就」并连带剔除它的其余任务。
"""

from __future__ import annotations

import httpx
import pytest

from crawler import http as http_module
from crawler.http import (
    HttpStatusError,
    SourceChallenge,
    is_cloudflare_challenge,
)


class TestChallengeDetection:
    """识别判据的真值表。"""

    def test_cf_mitigated_header(self) -> None:
        assert is_cloudflare_challenge(403, {"cf-mitigated": "challenge"}, "") is True

    def test_challenge_body_markers(self) -> None:
        body = "<html><head><title>Just a moment...</title></head></html>"
        assert is_cloudflare_challenge(403, {}, body) is True
        assert is_cloudflare_challenge(403, {}, "<div id='cf-chl-wrap'>") is True
        assert is_cloudflare_challenge(503, {}, "challenge-platform") is True

    def test_plain_403_is_not_a_challenge(self) -> None:
        """业务语义的 403（无挑战特征）不能被误判。"""
        assert is_cloudflare_challenge(403, {}, '{"error": "no achievements"}') is False

    def test_other_statuses_are_not_challenges(self) -> None:
        assert is_cloudflare_challenge(200, {"cf-mitigated": "challenge"}, "") is False
        assert is_cloudflare_challenge(404, {}, "just a moment") is False
        assert is_cloudflare_challenge(None, {}, "") is False

    def test_empty_or_odd_inputs(self) -> None:
        assert is_cloudflare_challenge(403, None, "") is False
        assert is_cloudflare_challenge(403, {}, "") is False


class _FakeResp:
    """最小响应桩。"""

    def __init__(self, status: int, headers: dict, text: str = "") -> None:
        self.status_code = status
        self.headers = headers
        self.text = text
        self.content = text.encode()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self):  # noqa: ANN201
        return {"ok": True}


class TestHttpLayerBehaviour:
    """HTTP 层的处置：挑战立刻抛，普通失败仍走重试。"""

    def test_challenge_raises_immediately_without_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def fake_get(url, **kw):
            calls["n"] += 1
            return _FakeResp(403, {"cf-mitigated": "challenge"}, "Just a moment")

        monkeypatch.setattr(http_module.httpx, "get", fake_get)
        with pytest.raises(SourceChallenge):
            http_module.request_json("https://x.test/a", {}, interval_sec=0)
        assert calls["n"] == 1, "挑战不该触发快速重试（挑战窗口是分钟级）"

    def test_plain_failure_still_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def fake_get(url, **kw):
            calls["n"] += 1
            return _FakeResp(403, {}, '{"error":"no achievements"}')

        monkeypatch.setattr(http_module.httpx, "get", fake_get)
        monkeypatch.setattr(http_module, "_backoff", lambda attempt: None)
        with pytest.raises(HttpStatusError) as excinfo:
            http_module.request_json("https://x.test/a", {}, interval_sec=0)
        assert not isinstance(excinfo.value, SourceChallenge)
        assert calls["n"] == http_module.MAX_RETRIES


class TestGlobalAch403Semantics:
    """全局成就率接口：业务 403 = 无成就；挑战 403 = 源不可用（不能用空列表糊过去）。"""

    def test_challenge_403_is_not_treated_as_no_achievements(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from crawler import steam_api

        def fake_request_json(url, params, **kw):
            raise SourceChallenge("被反爬挑战拦截", 403)

        monkeypatch.setattr(steam_api, "request_json", fake_request_json)
        # 若被当成「无成就」返回 []，worker 会把该游戏其余任务全部剔除
        with pytest.raises(SourceChallenge):
            steam_api.fetch_global_achievement_percentages(367520)

    def test_business_403_still_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from crawler import steam_api

        def fake_request_json(url, params, **kw):
            raise HttpStatusError("无成就数据", 403)

        monkeypatch.setattr(steam_api, "request_json", fake_request_json)
        assert steam_api.fetch_global_achievement_percentages(367520) == []


class TestRunSourcePropagates:
    """run_source 必须把挑战原样上抛，不能吞成 error（那会消耗重试预算）。"""

    def test_source_challenge_propagates_without_ingest_log(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cleaning import writers

        def boom(conn, appid, source):
            raise SourceChallenge("被反爬挑战拦截", 403)

        class _Savepoint:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _Conn:
            def begin_nested(self):
                return _Savepoint()

        logged: list[tuple] = []
        monkeypatch.setattr(writers, "_run_source_inner", boom)
        monkeypatch.setattr(writers, "log_ingest", lambda *a, **kw: logged.append(a))

        with pytest.raises(SourceChallenge):
            writers.run_source(_Conn(), 1108240, "steamspy")
        assert logged == [], "挑战不该写 ingest_log（不产生 error 记录）"
