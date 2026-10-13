"""tests.test_appdetails_retry — appdetails 软拒绝必须重试，不能直接判空

2026-09-27 事故：Steam 在 HTTP 200 下返回 ``{"success": false}`` 作为随机软拒绝，
旧实现直接记成**终态** ``empty``（永不重试）→ 7,402 条 appdetails 任务里抽样重抓
93% 其实有数据。UA 与请求速率两个假设都用对照实验排除了，所以只能靠「重试 +
可复核终态」来兜。

这里锁住三件事：
1. 软拒绝后**重试**，恢复即取到数据；
2. 连续软拒绝才判为无数据（返回空，交给上层记 empty）；
3. 反爬挑战**不重试**（那是源级问题，交给 worker 挂起），避免白白多打请求。
"""

from __future__ import annotations

import pytest

from crawler import steam_api


def _payload(appid: int, success: bool, name: str = "Some Game") -> dict:
    return {str(appid): {"success": success, "data": {"name": name, "appid": appid}}}


class TestEmptyRetry:
    def test_soft_reject_then_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """第一次软拒绝、第二次成功 → 必须拿到数据。"""
        calls = {"n": 0}

        def fake_request_json(url, params, **kw):
            calls["n"] += 1
            appid = params["appids"]
            return _payload(appid, success=calls["n"] > 1)

        monkeypatch.setattr(steam_api, "request_json", fake_request_json)
        monkeypatch.setattr(steam_api.time, "sleep", lambda s: None)

        out = steam_api.fetch_appdetails([367520], lang="english")
        assert out["367520"]["name"] == "Some Game"
        assert calls["n"] == 2, "软拒绝后应当重试一次"

    def test_persistent_soft_reject_returns_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """连续软拒绝 → 判为无数据（上层记 empty），且尝试次数有上限。"""
        calls = {"n": 0}

        def fake_request_json(url, params, **kw):
            calls["n"] += 1
            return _payload(params["appids"], success=False)

        monkeypatch.setattr(steam_api, "request_json", fake_request_json)
        monkeypatch.setattr(steam_api.time, "sleep", lambda s: None)

        assert steam_api.fetch_appdetails([123], lang="english") == {}
        assert calls["n"] == steam_api._EMPTY_RETRY_ATTEMPTS

    def test_source_unavailable_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """挑战/限流原样上抛（worker 会挂起源），不能在这里空转重试。"""
        from crawler import http as http_module

        calls = {"n": 0}

        def fake_request_json(url, params, **kw):
            calls["n"] += 1
            raise http_module.SourceThrottled("限流持续（429）", 429)

        monkeypatch.setattr(steam_api, "request_json", fake_request_json)
        monkeypatch.setattr(steam_api.time, "sleep", lambda s: None)

        with pytest.raises(http_module.SourceUnavailable):
            steam_api.fetch_appdetails([123], lang="english")
        assert calls["n"] == 1, "源级不可用不该在这里重试"

    def test_fetch_failure_propagates_instead_of_looking_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**回归点**：请求失败必须上抛，不能返回空字典。

        旧实现把失败吞掉、返回 {}，上层看到「没数据」就落成**终态 empty**——
        2026-09-27 的 429 限流因此被永久写成「无数据」，7,402 条 appdetails 任务
        被判空。这里锁住：失败要变成可重试的 error，而不是确定性的 empty。
        """
        calls = {"n": 0}

        def fake_request_json(url, params, **kw):
            calls["n"] += 1
            raise RuntimeError("重试耗尽（429）")

        monkeypatch.setattr(steam_api, "request_json", fake_request_json)
        monkeypatch.setattr(steam_api.time, "sleep", lambda s: None)

        with pytest.raises(RuntimeError):
            steam_api.fetch_appdetails([123], lang="english")
        assert calls["n"] == 1
