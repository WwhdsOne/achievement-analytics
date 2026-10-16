"""中文别名搜索的行为测试，可同时运行于开发与私有交付模块。"""

import json
from urllib.parse import urlencode

import pytest

from modeling.recommendation.graph_recommender import GraphRecommender
from modeling.recommendation.knowledge_graph import build_graph
from modeling.recommendation.knowledge_graph_inspector import GraphInspector
from modeling.recommendation.query_service import RecommendationQueryService
from modeling.recommendation.query_view import QueryViewService, route
from modeling.recommendation.snapshot import save_snapshot
from modeling.recommendation.web import RecommendationService


def game(appid, name, tags=("RPG",)):
    return dict(
        appid=appid,
        name_en=name,
        name_zh=None,
        release_date="2020-01-01",
        ach_count=3,
        min_percent=1,
        mean_percent=20,
        max_percent=80,
        mapping_unresolved=False,
        tags=[dict(source="steamspy", kind="theme", tag=t, votes=5) for t in tags],
        genres=[],
        developers=[],
        publishers=[],
    )


@pytest.fixture
def services(tmp_path):
    rows = [
        game(1245620, "ELDEN RING"),
        game(367520, "Hollow Knight"),
        game(413150, "Stardew Valley"),
        game(374320, "DARK SOULS III"),
        game(236430, "DARK SOULS II", ()),
        game(999, "老头环测试记录"),
    ]
    metadata = save_snapshot(rows, {}, tmp_path / "snapshots")
    graph = build_graph(
        metadata["version"], snapshots=tmp_path / "snapshots", folder=tmp_path / "kg"
    )
    base = GraphRecommender(
        GraphInspector(
            tmp_path / "kg" / graph["version"], snapshots=tmp_path / "snapshots"
        )
    )
    return RecommendationQueryService(base), RecommendationService(rows, metadata)


@pytest.mark.parametrize(
    "text,appid",
    [
        ("艾尔登法环", 1245620),
        ("老头环", 1245620),
        ("空洞骑士", 367520),
        ("星露谷物语", 413150),
        ("星露谷", 413150),
        ("黑魂3", 374320),
    ],
)
def test_aliases_resolve_existing_game_in_both_searches(services, text, appid):
    query, baseline = services
    assert appid in [r["appid"] for r in query.search(text)["results"]]
    assert appid in [r["appid"] for r in baseline.search(text)]


def test_alias_matches_merge_with_names_and_keep_unique_paging(services):
    query, _ = services
    result = query.search("老头环", limit=1)
    assert result["total_matches"] == 2
    assert result["results"][0]["appid"] == 999
    next_page = query.search("老头环", limit=1, offset=1)
    assert [r["appid"] for r in next_page["results"]] == [1245620]
    assert next_page["results"][0]["matched_aliases"] == ["老头环"]
    assert query.search("老头环", offset=2)["results"] == []
    # Multiple aliases containing the same substring still produce one game.
    assert query.search("星露谷")["total_matches"] == 1


def test_alias_does_not_create_absent_game_or_bypass_eligibility(services):
    query, baseline = services
    assert query.search("杀戮尖塔")["results"] == []
    assert baseline.search("杀戮尖塔") == []
    result = query.search("黑魂2")["results"][0]
    assert result["appid"] == 236430 and not result["recommendation_eligible"]
    assert "missing_tags" in {r["code"] for r in result["ineligible_reasons"]}
    assert query.recommend([result["appid"]])["status"] == "seed_ineligible"
    assert baseline.search("黑魂2") == []


@pytest.mark.parametrize(
    "text", ["  ｅｌｄｅｎ　ＲＩＮＧ  ", "ELDEN    ring", "　老头环　", "1245620"]
)
def test_name_alias_and_appid_normalization(services, text):
    query, baseline = services
    assert 1245620 in [r["appid"] for r in query.search(text)["results"]]
    assert 1245620 in [r["appid"] for r in baseline.search(text)]


def test_fields_cannot_accidentally_match_across_name_and_alias(services):
    query, baseline = services
    assert query.search("ring 艾尔登")["results"] == []
    assert baseline.search("ring 艾尔登") == []


def test_search_does_not_change_recommendation_scores_or_source_names(services):
    query, baseline = services
    graph_before = query.base.recommend(1245620)
    query_before = query.recommend([1245620])
    baseline_before = baseline.recommend({"appid": 1245620})
    found = query.search("老头环")["results"][-1]
    assert found["name"] == "ELDEN RING" and found["name_zh"] is None
    assert query.recommend([found["appid"]]) == query_before
    assert query.base.recommend(1245620) == graph_before
    assert (
        baseline.recommend({"appid": baseline.search("老头环")[-1]["appid"]})
        == baseline_before
    )
    found["matched_aliases"].clear()
    assert query.search("老头环")["results"][-1]["matched_aliases"] == ["老头环"]


def test_http_search_to_recommend_accepts_alias_selected_appid(services):
    query, _ = services
    view = QueryViewService(query)
    status, _, payload = route(view, "/api/search?" + urlencode({"q": "空洞骑士"}))
    data = json.loads(payload)
    assert status == 200 and data["results"][0]["appid"] == 367520
    status, _, payload = route(view, "/api/recommend?appids=367520")
    assert status == 200 and json.loads(payload)["ranking"]["query_appids"] == [367520]
