import json
from dataclasses import asdict

import httpx
import pytest

from process.deepseek_commentary import (
    CommentaryService,
    DeepSeekConfig,
    CommentaryError,
    build_evidence,
)


class Query:
    view_version = "view-1"
    query = type("Underlying", (), {"query_service_version": "query-1"})()

    def explain(self, appids, **kwargs):
        return {
            "view_version": self.view_version,
            "query_games": [{"appid": 1, "name": "Seed"}],
            "display_names": {
                "1": {"display_name": "已选游戏"},
                "2": {"display_name": "候选游戏"},
            },
            "ranking": {
                "snapshot_version": "snapshot-1",
                "algorithm_version": "score-1",
                "filters": {"year_min": None, "year_max": None},
                "results": [{"appid": 2, "name": "Candidate", "score": 0.5}],
            },
            "explanations": [
                {
                    "appid": 2,
                    "path_catalog": [
                        {
                            "key": "p1",
                            "seed_appid": 1,
                            "field": "tags",
                            "name": "Exploration",
                            "contribution": 0.5,
                            "used_for_score": True,
                        },
                        {
                            "key": "p2",
                            "seed_appid": 1,
                            "field": "publishers",
                            "name": "Zero",
                            "contribution": 0,
                            "used_for_score": False,
                        },
                    ],
                }
            ],
        }


def request():
    return {"appids": [1], "candidate_appid": 2, "top_k": 5}


def answer(
    text="结合你选择的游戏，这款作品与它共享探索标签，可以作为继续寻找探索体验的一个候选。",
):
    return {
        "summary": text,
        "reasons": [
            {
                "title": "探索标签相近",
                "text": "与《已选游戏》共有探索标签。",
                "evidence_ids": ["e1"],
            }
        ],
        "caution": "标签关联仅供挑选参考，具体体验还需查看实机内容。",
    }


def response(content, status=200):
    return httpx.Response(
        status,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(content, ensure_ascii=False)},
                }
            ]
        },
    )


def test_no_key_does_not_call_transport_or_reveal_configuration(tmp_path):
    config = DeepSeekConfig.from_env(tmp_path / "missing.env", environ={})
    assert not config.api_key
    service = CommentaryService(
        Query(),
        config,
        transport=httpx.MockTransport(lambda r: pytest.fail("unexpected network")),
    )
    assert service.metadata()["configured"] is False
    with pytest.raises(CommentaryError, match="未配置"):
        service.generate(request())


def test_key_precedence_repr_and_public_metadata(tmp_path):
    p = tmp_path / "deepseek.env"
    p.write_text("DEEPSEEK_API_KEY=file-test-key\n", encoding="utf-8")
    config = DeepSeekConfig.from_env(p, environ={"DEEPSEEK_API_KEY": "env-test-key"})
    assert config.api_key == "env-test-key"
    assert "env-test-key" not in repr(config)
    assert "env-test-key" not in json.dumps(
        CommentaryService(Query(), config).metadata()
    )


def test_public_origins_normalize_and_environment_can_clear_file_setting(tmp_path):
    p = tmp_path / "deepseek.env"
    p.write_text("COMMENTARY_PUBLIC_ORIGINS=https://old.example\n", encoding="utf-8")
    config = DeepSeekConfig.from_env(
        p,
        environ={
            "COMMENTARY_PUBLIC_ORIGINS": "https://Games.Example:443/, http://localhost:8080"
        },
    )
    assert config.public_origins == ("https://games.example", "http://localhost:8080")
    assert (
        DeepSeekConfig.from_env(
            p, environ={"COMMENTARY_PUBLIC_ORIGINS": ""}
        ).public_origins
        == ()
    )


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.example",
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com?query=1",
        "ftp://example.com",
        "https://example.com:99999",
        "https://bad example.com",
    ],
)
def test_invalid_public_origin_configuration_fails_closed(tmp_path, value):
    with pytest.raises(ValueError, match="COMMENTARY_PUBLIC_ORIGINS"):
        DeepSeekConfig.from_env(
            tmp_path / "absent.env", environ={"COMMENTARY_PUBLIC_ORIGINS": value}
        )


def test_payload_uses_positive_real_evidence_not_raw_connection_or_zero_facts():
    payload = build_evidence(Query().explain([1]), 2)
    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["id"] == "e1"
    assert payload["evidence"][0]["name"] == "Exploration"
    assert "Zero" not in json.dumps(payload)


def test_actual_query_report_keeps_snapshot_identity_in_binding():
    report = Query().explain([1])
    report["ranking"]["binding"] = {
        "snapshot_version": report["ranking"].pop("snapshot_version")
    }
    assert build_evidence(report, 2)["snapshot_version"] == "snapshot-1"


def test_actual_api_shape_success_and_cache():
    calls = []

    def transport(req):
        calls.append(req)
        assert str(req.url) == "https://api.deepseek.com/chat/completions"
        assert req.headers["Authorization"] == "Bearer test-key"
        body = json.loads(req.content)
        assert (
            body["model"] == "deepseek-flash" and body["thinking"]["type"] == "disabled"
        )
        assert body["response_format"]["type"] == "json_object"
        assert "test-key" not in req.content.decode()
        return response(answer())

    service = CommentaryService(
        Query(),
        DeepSeekConfig(api_key="test-key"),
        transport=httpx.MockTransport(transport),
    )
    first = service.generate(request())
    second = service.generate(request())
    assert first["status"] == "ok" and not first["cached"] and second["cached"]
    assert first["evidence"][0]["name"] == "Exploration" and len(calls) == 1
    assert first["commentary"]["summary"] == answer()["summary"]
    assert first["commentary"]["reasons"][0]["title"] == "探索标签相近"
    first["commentary"]["reasons"].clear()
    assert service.generate(request())["commentary"]["reasons"]
    first["evidence"].clear()
    assert service.generate(request())["evidence"]


@pytest.mark.parametrize(
    "body",
    [
        {"appids": [1], "candidate_appid": 999},
        {"appids": [], "candidate_appid": 2},
        {"appids": [True], "candidate_appid": 2},
        {"appids": [1], "candidate_appid": True},
        {"appids": [1], "candidate_appid": 2, "prompt": "override"},
        {"appids": [1], "candidate_appid": 2, "top_k": 99},
        {"appids": [1], "candidate_appid": 2, "year_min": 2025, "year_max": 2020},
    ],
)
def test_invalid_request_never_calls_api(body):
    service = CommentaryService(
        Query(),
        DeepSeekConfig(api_key="test-key"),
        transport=httpx.MockTransport(lambda r: pytest.fail("unexpected network")),
    )
    with pytest.raises(ValueError):
        service.generate(body)


@pytest.mark.parametrize(
    "invalid",
    [
        {**answer(), "summary": ""},
        {**answer(), "summary": "字" * 101},
        {**answer(), "summary": "分行\n结论"},
        {**answer(), "caution": "字" * 81},
        {**answer(), "reasons": []},
        {**answer(), "reasons": answer()["reasons"] * 3},
        {
            **answer(),
            "reasons": [{"title": "理由", "text": "正文", "evidence_ids": ["fake"]}],
        },
        {
            **answer(),
            "reasons": [{"title": "理由", "text": "正文", "evidence_ids": []}],
        },
        {
            **answer(),
            "reasons": [{"title": "字" * 17, "text": "正文", "evidence_ids": ["e1"]}],
        },
        {
            **answer(),
            "reasons": [{"title": "理由", "text": "字" * 141, "evidence_ids": ["e1"]}],
        },
        {**answer(), "reasons": [None]},
        {**answer(), "extra": "unknown"},
        {"commentary": "伪造的点评" * 12, "evidence_ids": ["not-a-real-id"]},
        {"commentary": "", "evidence_ids": ["e1"]},
        {"commentary": "字" * 401, "evidence_ids": ["e1"]},
        {"commentary": "字" * 50, "evidence_ids": []},
        {"commentary": "字" * 50, "evidence_ids": ["e1"], "extra": "unknown"},
    ],
)
def test_invalid_output_is_rejected_and_not_cached(invalid):
    calls = []

    def transport(req):
        calls.append(req)
        return response(invalid)

    service = CommentaryService(
        Query(),
        DeepSeekConfig(api_key="test-key"),
        transport=httpx.MockTransport(transport),
    )
    for _ in range(2):
        with pytest.raises(CommentaryError):
            service.generate(request())
    assert len(calls) == 2


def test_structured_reasons_keep_distinct_seed_evidence():
    class MultiQuery(Query):
        def explain(self, appids, **kwargs):
            report = super().explain(appids, **kwargs)
            report["query_games"].append({"appid": 3, "name": "另一款已选游戏"})
            report["explanations"][0]["path_catalog"].append(
                {
                    "seed_appid": 3,
                    "field": "developers",
                    "name": "Studio",
                    "contribution": 0.1,
                    "used_for_score": True,
                }
            )
            return report

    packet = answer()
    packet["reasons"].append(
        {
            "title": "开发背景有关联",
            "text": "与《另一款已选游戏》共有开发商 Studio。",
            "evidence_ids": ["e2", "e2"],
        }
    )
    service = CommentaryService(
        MultiQuery(),
        DeepSeekConfig(api_key="test-key"),
        transport=httpx.MockTransport(lambda req: response(packet)),
    )
    result = service.generate({"appids": [1, 3], "candidate_appid": 2})
    assert [e["seed_appid"] for e in result["evidence"]] == [1, 3]
    assert result["commentary"]["reasons"][1]["evidence_ids"] == ["e2"]


def test_timeout_and_provider_error_do_not_echo_secrets():
    def transport(req):
        raise httpx.ReadTimeout("test-key provider detail", request=req)

    service = CommentaryService(
        Query(),
        DeepSeekConfig(api_key="test-key"),
        transport=httpx.MockTransport(transport),
    )
    with pytest.raises(CommentaryError) as caught:
        service.generate(request())
    assert "test-key" not in str(caught.value)
    service = CommentaryService(
        Query(),
        DeepSeekConfig(api_key="test-key"),
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="test-key")),
    )
    with pytest.raises(CommentaryError) as caught:
        service.generate(request())
    assert "test-key" not in str(caught.value)
