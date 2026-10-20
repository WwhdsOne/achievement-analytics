"""对运行中的 Python/Rust 冻结推荐服务做真实 HTTP 验收，不读取或修改数据库。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


# 只放宽实现身份/绑定结构；图谱/快照版本、数据摘要和权重另外强制核对。
IMPLEMENTATION_KEYS = frozenset(
    {"view_version", "query_service_version", "algorithm_version", "base_algorithm_version"}
)
BINDING_KEYS = frozenset({"binding", "query_binding", "view_binding", "scoring_binding"})
DATA_BINDING_KEYS = frozenset(
    {"graph_version", "graph_manifest_sha256", "snapshot_version", "snapshot_sha256", "weights"}
)
PREDICATES = {
    "tags": "has_tag",
    "genres": "has_genre",
    "developers": "developed_by",
    "publishers": "published_by",
}


class CheckFailure(Exception):
    """只携带检查位置，不把原始数据写进控制台或摘要。"""


def require(condition: bool, location: str) -> None:
    """检查必要条件，失败时仅报告位置。"""
    if not condition:
        raise CheckFailure(location)


def close(left: float, right: float, location: str) -> None:
    """有限数值按严格的绝对/相对误差检查。"""
    require(
        math.isfinite(left)
        and math.isfinite(right)
        and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12),
        location,
    )


def semantic(value: Any) -> Any:
    """移除实现版本和绑定结构；数据版本/摘要/权重另外强制核对。"""
    if isinstance(value, dict):
        result = {
            key: {} if key == "data_loading" else semantic(item)
            for key, item in value.items()
            if key not in IMPLEMENTATION_KEYS and key not in BINDING_KEYS
        }
        # 图节点/边的排列只影响 SVG 插入顺序；成员和全部属性仍严格比较。
        if "nodes" in result and "edges" in result:
            result["nodes"] = sorted(result["nodes"], key=lambda node: node["id"])
            result["edges"] = sorted(
                result["edges"],
                key=lambda edge: (edge["path_key"], edge["source"], edge["fact_id"]),
            )
        return result
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value


def data_bindings(value: Any) -> dict[str, set[str]]:
    """收集嵌套绑定的数据身份，不依赖两种实现的元数据嵌套结构。"""
    found: dict[str, set[str]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in DATA_BINDING_KEYS:
                    found.setdefault(key, set()).add(json.dumps(child, sort_keys=True, ensure_ascii=False))
                if key in BINDING_KEYS:
                    visit(child)

    visit(value)
    return found


def compare(left: Any, right: Any, location: str = "$", counts: Counter | None = None) -> None:
    """比较所有字段、列表顺序及数值，错误不包含原始字段值。"""
    if isinstance(left, dict):
        require(isinstance(right, dict), location + ":object_type")
        require(left.keys() == right.keys(), location + ":field_membership")
        for key, value in left.items():
            compare(value, right[key], location + "." + key, counts)
    elif isinstance(left, list):
        require(isinstance(right, list) and len(left) == len(right), location + ":list_length")
        for index, value in enumerate(left):
            compare(value, right[index], f"{location}[{index}]", counts)
    elif isinstance(left, (float, int)) and not isinstance(left, bool):
        require(isinstance(right, (float, int)) and not isinstance(right, bool), location + ":number_type")
        if isinstance(left, int) and isinstance(right, int):
            require(left == right, location + ":integer")
        else:
            close(left, right, location + ":number")
        if counts is not None:
            counts["numeric_values_compared"] += 1
    else:
        require(type(left) is type(right) and left == right, location + ":value")


def validate_explanations(report: dict, counts: Counter) -> None:
    """独立复算原分/联合分/完整与裁剪路径，并检查双端事实方向。"""
    ranking = report["ranking"]
    require(report["presentation_only"] is True, "presentation_only")
    results, explanations = ranking["results"], report["explanations"]
    require([r["appid"] for r in results] == [e["appid"] for e in explanations], "explanation_appids")
    require(not set(ranking["query_appids"]) & {r["appid"] for r in results}, "seed_exclusion")
    for index, (result, explanation) in enumerate(zip(results, explanations)):
        location = f"result[{index}]"
        seeds = result.get("seed_contributions") or [
            {"appid": ranking["query_appids"][0], "weight": 1.0, "relations": result["relations"]}
        ]
        all_paths: dict[str, dict] = {}
        joint_scores = []
        for seed in seeds:
            raw_scores = []
            close(seed["weight"], 1 / len(ranking["query_appids"]), location + ":seed_weight")
            for field, component in seed["relations"].items():
                require(field in PREDICATES, location + ":relation_field")
                paths = component["paths"]
                close(math.fsum(p["contribution"] for p in paths), component["weighted_score"], location + ":raw_path_sum")
                denominator = component["denominator"]
                close(component["weighted_score"], component["weight"] * component["numerator"] / denominator if denominator else 0.0, location + ":component_formula")
                raw_scores.append(component["weighted_score"])
                for path in paths:
                    entity = path["entity"]["id"]
                    key = f"{seed['appid']}:{field}:{entity}"
                    require(key not in all_paths, location + ":unique_path")
                    all_paths[key] = path
                    expected = component["weight"] * path["idf"] / denominator if denominator else 0.0
                    close(path["contribution"], expected, location + ":path_formula")
                    close(path["idf"], math.log((ranking["idf_reference_games"] + 1) / (path["document_frequency"] + 1)) + 1, location + ":idf_formula")
                    if "joint_contribution" in path:
                        close(path["joint_contribution"], path["contribution"] * seed["weight"], location + ":joint_path")
                    for side, appid in (("left_edge", seed["appid"]), ("right_edge", result["appid"])):
                        edge = path[side]
                        require(edge.get("source_verified") is True and edge.get("relation_kind") == "source_fact", location + ":verified_source_fact")
                        require("score" not in edge and edge["subject"] == f"game:{appid}" and edge["object"] == entity, location + ":fact_direction")
                        require(edge["predicate"] == path["predicate"] == PREDICATES[field], location + ":fact_predicate")
                    counts["source_facts_checked"] += 2
            score = math.fsum(raw_scores)
            if "score" in seed:
                close(seed["score"], score, location + ":seed_score")
                close(seed["contribution"], score * seed["weight"], location + ":seed_contribution")
            joint_scores.append(score * seed["weight"])
        close(math.fsum(joint_scores), result["score"], location + ":ranked_score")
        catalog = explanation["path_catalog"]
        require(len(catalog) == len(all_paths) == explanation["total_paths"], location + ":catalog_count")
        require({p["key"] for p in catalog} == all_paths.keys(), location + ":catalog_membership")
        require(catalog == sorted(catalog, key=lambda path: (-path["contribution"], path["key"])), location + ":catalog_order")
        for path in catalog:
            raw = all_paths[path["key"]]
            close(path["contribution"], raw.get("joint_contribution", raw["contribution"]), location + ":catalog_contribution")
            require(path["left_fact_id"] == raw["left_edge"]["id"] and path["right_fact_id"] == raw["right_edge"]["id"], location + ":catalog_fact_ids")
        close(math.fsum(p["contribution"] for p in catalog), result["score"], location + ":catalog_score")
        limit = report["path_limit"]
        shown = catalog if limit is None else catalog[:limit]
        require(explanation["shown_paths"] == len(shown), location + ":shown_count")
        close(explanation["shown_contribution"], math.fsum(p["contribution"] for p in shown), location + ":shown_sum")
        close(explanation["hidden_contribution"], math.fsum(p["contribution"] for p in catalog[len(shown):]), location + ":hidden_sum")
        expected_edges = Counter(
            (p["key"], f"game:{appid}", p["entity_id"], fact)
            for p in shown
            for appid, fact in ((p["seed_appid"], p["left_fact_id"]), (result["appid"], p["right_fact_id"]))
        )
        actual_edges = Counter((e["path_key"], e["source"], e["target"], e["fact_id"]) for e in explanation["display_graph"]["edges"])
        require(expected_edges == actual_edges, location + ":display_graph_facts")
        counts["ranked_results_checked"] += 1
        counts["explanation_paths_checked"] += len(catalog)


class Suite:
    """顺序请求两套真实服务，保存不含原始记录的验收计数。"""

    def __init__(self, python_url: str, rust_url: str, timeout: float) -> None:
        self.urls = (python_url.rstrip("/"), rust_url.rstrip("/"))
        self.timeout = timeout
        self.counts: Counter = Counter()
        self.cases: list[dict] = []

    def request(self, endpoint: int, path: str, method: str = "GET") -> tuple[int, Any]:
        """执行有超时的 HTTP 请求；网络错误不包含可能敏感的地址。"""
        request = Request(self.urls[endpoint] + path, method=method)
        try:
            response = urlopen(request, timeout=self.timeout)
        except HTTPError as error:
            response = error
        except (URLError, TimeoutError, OSError) as error:
            raise CheckFailure(f"endpoint[{endpoint}]:{type(error).__name__}") from None
        with response:
            status = response.status
            body = response.read(64 * 1024 * 1024 + 1)
        self.counts["http_requests"] += 1
        require(len(body) <= 64 * 1024 * 1024, "response_too_large")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            payload = None
        return status, payload

    def pair(self, path: str, *, recommendation: bool = False, expected_status: str | None = None) -> dict:
        """比较成功响应，推荐接口额外独立检查完整解释的守恒与来源。"""
        left_status, left = self.request(0, path)
        right_status, right = self.request(1, path)
        require(left_status == right_status == 200, "successful_http_status")
        require(isinstance(left, dict) and isinstance(right, dict), "json_object")
        if "data_loading" in left:
            provenance = right.get("data_loading")
            require(isinstance(provenance, dict), "rust_loading_provenance")
            require(provenance.get("source") == "persistent_sqlite", "rust_persistent_sqlite_source")
            require(provenance.get("database_access") is False and provenance.get("cache_reused") is True, "rust_no_cloud_database_and_reused_cache")
            for key in ("snapshot_version", "graph_version", "snapshot_games"):
                require(provenance.get(key) == left["data_loading"].get(key), "loading_provenance:" + key)
        left_bindings, right_bindings = data_bindings(left), data_bindings(right)
        require(set(left_bindings) == DATA_BINDING_KEYS, "python_complete_data_binding")
        require(left_bindings == right_bindings, "frozen_data_and_weights_binding")
        compare(semantic(left), semantic(right), counts=self.counts)
        if recommendation:
            validate_explanations(left, self.counts)
            validate_explanations(right, self.counts)
            if expected_status is not None:
                require(left["ranking"]["status"] == expected_status, "expected_ranking_status")
        return left

    def run(self, name: str, action: Callable[[], Any]) -> Any:
        """记录单项结果，允许后续独立检查继续执行。"""
        try:
            result = action()
        except (CheckFailure, KeyError, TypeError, ValueError) as error:
            self.cases.append({"name": name, "passed": False, "failure": str(error) if isinstance(error, CheckFailure) else type(error).__name__})
            print(f"FAIL {name}: {self.cases[-1]['failure']}", flush=True)
            return None
        self.cases.append({"name": name, "passed": True})
        print(f"PASS {name}", flush=True)
        return result

    def rejection(self, path: str, expected: int = 400) -> None:
        """严格检查拒绝状态与错误对象，错误文案允许实现差异。"""
        for endpoint in range(2):
            status, payload = self.request(endpoint, path)
            require(status == expected, f"endpoint[{endpoint}]:rejection_status")
            require(isinstance(payload, dict) and set(payload) == {"error"} and isinstance(payload["error"], str) and bool(payload["error"]), f"endpoint[{endpoint}]:error_schema")

    def readonly(self, method: str, path: str) -> None:
        """原 Python 的 501 与 Rust 的 405/404 均是明确的只读拒绝。"""
        for endpoint in range(2):
            status, _ = self.request(endpoint, path, method)
            require(status in {404, 405, 501}, f"endpoint[{endpoint}]:readonly_status")


def endpoint(path: str, **params: Any) -> str:
    """编码接口参数，保留显式空字符串。"""
    return path + "?" + urlencode(params)


def execute(suite: Suite) -> None:
    """运行固定边界案例，并从真实完整搜索中发现合格与不合格种子。"""
    meta = suite.run("metadata", lambda: suite.pair("/api/meta"))
    if meta is None:
        # 元数据字段不一致仍要继续评分/解释核验；不能让一个元数据问题掩盖排名问题。
        status, meta = suite.request(0, "/api/meta")
        require(status == 200 and isinstance(meta, dict), "python_metadata_for_discovery")
    require(meta["snapshot_games"] > meta["candidate_games"] > 0, "frozen_snapshot_scope")
    discovered: dict[int, dict] = {}
    for label, query in (
        ("chinese", "空洞骑士"), ("alias", "老头环"),
        ("appid", "367520"), ("fullwidth", "ＨＯＬＬＯＷ　ＫＮＩＧＨＴ"),
        ("case_and_spaces", "  hOLLoW   Knight  "),
        ("english", "Stardew Valley"), ("third_seed", "Slay the Spire"),
    ):
        found = suite.run("search_" + label, lambda query=query: suite.pair(endpoint("/api/search", q=query, limit=20)))
        if found is not None:
            require(found["total_matches"] > 0, "known_search_has_matches")
            discovered.update((row["appid"], row) for row in found["results"])
    suite.run("search_offset", lambda: suite.pair(endpoint("/api/search", q="", limit=7, offset=7)))
    suite.run("search_no_matches", lambda: suite.pair(endpoint("/api/search", q="__no_game_9b31e6f7__", limit=5)))
    # 搜索结果必须包含真实不合格样本；没有找到时失败，不偷偷跳过此分支。
    for offset in range(0, meta["snapshot_games"], 100):
        eligible = sorted(a for a, row in discovered.items() if row["recommendation_eligible"])
        ineligible = sorted(a for a, row in discovered.items() if not row["recommendation_eligible"])
        if len(eligible) >= 4 and ineligible:
            break
        page = suite.run(f"discover_page_{offset // 100}", lambda offset=offset: suite.pair(endpoint("/api/search", q="", limit=100, offset=offset)))
        if page is None:
            return
        discovered.update((row["appid"], row) for row in page["results"])
    eligible = sorted(a for a, row in discovered.items() if row["recommendation_eligible"])
    ineligible = sorted(a for a, row in discovered.items() if not row["recommendation_eligible"])
    require(len(eligible) >= 4 and bool(ineligible), "real_seed_discovery")
    preferred = [a for a in (367520, 413150, 646570) if a in eligible]
    seeds = (preferred + [a for a in eligible if a not in preferred])[:3]
    csv = lambda values: ",".join(map(str, values))
    for count in (1, 2, 3):
        suite.run(f"recommend_{count}_seeds_all_paths", lambda count=count: suite.pair(endpoint("/api/recommend", appids=csv(seeds[:count]), top_k=5, path_limit="all"), recommendation=True))
    require(any(discovered[a]["release_year"] < 2020 for a in seeds[:2]), "seed_outside_requested_years")
    for label, selected, extra, expected_status in (
        ("duplicate_seeds", [seeds[1], seeds[0], seeds[0]], {}, "ok"),
        ("duplicate_single", [seeds[0], seeds[0]], {}, "ok"),
        ("year_filtered_outside_seed", seeds[:2], {"year_min": 2020, "year_max": 2025}, "ok"),
        ("empty_year", seeds[:2], {"year_min": 1, "year_max": 1}, "no_candidates"),
        ("empty_boundaries", seeds[:1], {"year_min": "", "year_max": ""}, "ok"),
        ("ineligible_seed", [ineligible[0]], {}, "seed_ineligible"),
        ("mixed_ineligible", [seeds[0], ineligible[0]], {}, "seed_ineligible"),
    ):
        suite.run("recommend_" + label, lambda selected=selected, extra=extra, expected_status=expected_status: suite.pair(endpoint("/api/recommend", appids=csv(selected), top_k=3, path_limit=1, **extra), recommendation=True, expected_status=expected_status))
    bad = [
        "/api/search?q=a&q=b", "/api/search?unknown=1", "/api/search?limit=0",
        "/api/search?limit=101", "/api/search?limit=-1", "/api/search?offset=1.5",
        "/api/search?limit=", "/api/search?offset=99999999999",
        endpoint("/api/search", q="a" * 201),
        "/api/search?q=1&limit=1&offset=0&a=1&b=1&c=1&d=1",
        "/api/recommend", "/api/recommend?appids=", "/api/recommend?appids=1,,2",
        "/api/recommend?appids=-1", "/api/recommend?appids=1.0",
        "/api/recommend?appids=9999999999",
        endpoint("/api/recommend", appids=csv(eligible[:4])),
        f"/api/recommend?appids={seeds[0]}&appids={seeds[0]}",
        f"/api/recommend?appids={seeds[0]}&unknown=1",
    ]
    for key, values in {"top_k": ("0", "101", "1.5", "-1", "+1", " 1", "１", ""), "path_limit": ("0", "201", "ALL", "1.5", ""), "year_min": ("0", "10000", "-1", "1.5"), "year_max": ("0", "10000", "1e3")}.items():
        bad.extend(endpoint("/api/recommend", appids=seeds[0], **{key: value}) for value in values)
    bad.append(endpoint("/api/recommend", appids=seeds[0], year_min=2025, year_max=2020))
    bad.append("/api/search?q=" + "a" * 4096)
    for index, path in enumerate(bad):
        suite.run(f"reject_{index:02}", lambda path=path: suite.rejection(path))
    for index, path in enumerate(("/api/unknown", "/api/meta?unknown=1", "/../.env")):
        suite.run(f"unknown_route_{index}", lambda path=path: suite.rejection(path, 404))
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        suite.run("readonly_" + method.lower(), lambda method=method: suite.readonly(method, "/api/recommend"))
    suite.run("still_healthy_after_rejections", lambda: suite.pair("/api/meta"))
    require(suite.counts["explanation_paths_checked"] > 0, "nonvacuous_explanation_checks")


def main() -> int:
    """输出紧凑检查计数，可选保存不含原始记录和凭据的 JSON 摘要。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-url", required=True, help="原 Python query_view 服务根地址")
    parser.add_argument("--rust-url", required=True, help="Rust 服务根地址")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, help="仅保存检查名/计数/错误位置，不保存接口记录")
    args = parser.parse_args()
    for value in (args.python_url, args.rust_url):
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password or url.query or url.fragment:
            parser.error("服务地址须为不含凭据、查询参数或片段的 HTTP(S) 地址")
    if args.timeout <= 0:
        parser.error("timeout 必须为正数")
    suite = Suite(args.python_url, args.rust_url, args.timeout)
    try:
        execute(suite)
    except (CheckFailure, KeyError, TypeError, ValueError) as error:
        suite.cases.append({"name": "suite_execution", "passed": False, "failure": str(error) if isinstance(error, CheckFailure) else type(error).__name__})
        print(f"FAIL suite_execution: {suite.cases[-1]['failure']}", flush=True)
    passed = sum(case["passed"] for case in suite.cases)
    failed = len(suite.cases) - passed
    summary = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "passed": failed == 0,
        "case_counts": {"passed": passed, "failed": failed},
        "checks": dict(suite.counts),
        "numeric_tolerance": {"absolute": 1e-12, "relative": 1e-12},
        "excluded_implementation_metadata": sorted(IMPLEMENTATION_KEYS | BINDING_KEYS | {"data_loading"}),
        "separately_compared_data_bindings": sorted(DATA_BINDING_KEYS),
        "required_rust_loading": {"source": "persistent_sqlite", "database_access": False, "cache_reused": True, "same_as_python": ["snapshot_version", "graph_version", "snapshot_games"]},
        "cases": suite.cases,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": failed == 0, "cases_passed": passed, "cases_failed": failed, **suite.counts}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
