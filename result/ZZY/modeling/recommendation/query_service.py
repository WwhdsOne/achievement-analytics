"""完整冻结快照搜索与年份先筛选后评分；独立离线入口。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from .baseline import tag_set
from . import game_aliases
from .game_aliases import matched_aliases, normalize_search, search_fields
from .graph_recommender import GraphRecommender
from .knowledge_graph import FIELDS, GRAPHS, digest_file, json_text
from .knowledge_graph_inspector import GraphInspector
from . import multi_game_recommender
from .multi_game_recommender import MultiGameRecommender
from .snapshot import SNAPSHOTS


def release_year(row: dict) -> int | None:
    """使用原候选规则的ISO日期解析，缺失或无效日期不猜年份。"""
    try:
        return date.fromisoformat(row["release_date"]).year
    except (TypeError, ValueError, KeyError):
        return None


def validate_years(year_min: int | None, year_max: int | None) -> dict:
    """含首尾的年份范围；None清空边界，不接受布尔、字符串或小数。"""
    for value in (year_min, year_max):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 9999):
            raise ValueError("年份须为1–9999整数或None")
    if year_min is not None and year_max is not None and year_min > year_max:
        raise ValueError("起始年份不能晚于结束年份")
    return {"year_min": year_min, "year_max": year_max, "inclusive": True}


class RecommendationQueryService:
    """复用已验证图谱；全快照可查，评分仍严格服从原推荐资格。"""

    def __init__(self, base: GraphRecommender) -> None:
        self.base = base
        base.inspector._check_unchanged()
        self.binding = copy.deepcopy(base.binding)
        self.binding.update(algorithm="snapshot-search-year-filter-v1", base_algorithm_version=base.algorithm_version,
                            search_scope="full_frozen_snapshot_name_zh_name_en_local_alias_appid_substring_appid_order",
                            filter_policy="inclusive_release_year_before_candidate_ranking_seed_year_unrestricted",
                            idf_reference="year_filtered_eligible_candidates_excluding_all_unique_seeds",
                            ineligible_policy="explain_and_block_entire_query_no_partial_seed_fallback")
        self.binding["source_sha256"].update({Path(__file__).name: digest_file(Path(__file__)),
            "game_aliases.py": digest_file(Path(game_aliases.__file__)),
            "game_aliases.json": digest_file(game_aliases.ALIAS_PATH),
            "multi_game_recommender.py": digest_file(Path(multi_game_recommender.__file__))})
        self.query_service_version = "query-service-v1-" + hashlib.sha256(json_text(self.binding).encode("utf-8")).hexdigest()
        self._searchable = [(appid, search_fields(row))
                            for appid, row in sorted(base.inspector._rows.items())]

    def _describe(self, appid: int) -> dict:
        row = self.base.inspector._rows[appid]
        reasons = []

        def issue(code: str, message: str) -> None:
            reasons.append({"code": code, "message": message})

        year = release_year(row)
        if year is None:
            issue("invalid_release_date", "发售日期缺失或无效，不能判断原推荐范围。")
        elif year >= 2026:
            issue("outside_release_scope", "发售日期不在原候选要求的2026年以前。")
        name = row.get("name_zh") or row.get("name_en") or ""
        if not isinstance(name, str) or not name.strip():
            issue("missing_name", "缺少有效游戏名称。")
        if row.get("mapping_unresolved") is not False:
            issue("unresolved_mapping", "成就身份映射未明确解决。")
        if not isinstance(row.get("ach_count"), int) or row["ach_count"] <= 0:
            issue("invalid_achievements", "缺少正数成就数量。")
        percentages = [row.get(k) for k in ("min_percent", "mean_percent", "max_percent")]
        if (not all(isinstance(v, (int, float)) and 0 <= v <= 100 for v in percentages)
                or not percentages[0] <= percentages[1] <= percentages[2]):
            issue("invalid_achievement_summary", "成就百分比摘要缺失、越界或顺序异常。")
        try:
            if not tag_set(row):
                issue("missing_tags", "缺少有效SteamSpy主题标签。")
        except TypeError:
            issue("invalid_tags", "主题标签字段不是可读取的集合，未通过原推荐数据检查。")
        eligible = appid in self.base.rows
        if not eligible and not reasons:
            issue("candidate_rule_failed", "未通过原候选唯一身份或数据检查。")
        return copy.deepcopy({"appid": appid, "name": name if isinstance(name, str) and name.strip() else f"appid:{appid}",
                "name_en": row.get("name_en"), "name_zh": row.get("name_zh"), "release_date": row.get("release_date"),
                "release_year": year, "recommendation_eligible": eligible, "ineligible_reasons": reasons})

    def search(self, text: str = "", limit: int = 20, offset: int = 0) -> dict:
        """扫描完整快照，按appid分页；资格不足仍可查并返回原因。"""
        self.base.inspector._check_unchanged()
        if (not isinstance(text, str) or len(text) > 200 or not isinstance(limit, int) or isinstance(limit, bool)
                or not 1 <= limit <= 100 or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0):
            raise ValueError("搜索词须为至多200字符文本，limit为1–100整数，offset为非负整数")
        normalized = normalize_search(text)
        matches = [appid for appid, fields in self._searchable if any(normalized in field for field in fields)]
        results = [{**self._describe(appid), "matched_aliases": matched_aliases(appid, normalized)}
                   for appid in matches[offset:offset + limit]]
        self.base.inspector._check_unchanged()
        return {"query_service_version": self.query_service_version, "query_binding": copy.deepcopy(self.binding),
                "search_scope": "full_frozen_snapshot", "snapshot_games": len(self._searchable), "candidate_games": len(self.base.rows),
                "query": normalized, "total_matches": len(matches), "limit": limit, "offset": offset, "results": results,
                "limits": "仅搜索此冻结快照；可查不等于可推荐，不是实时云库全量搜索。"}

    def _restricted_base(self, allowed: set[int], seeds: list[int], filters: dict) -> GraphRecommender:
        # 独立请求索引：保留范围外种子仅作查询，N/df会由父评分器排除全部种子。
        view = copy.copy(self.base)
        selected = sorted(allowed | set(seeds))
        view.rows = {a: self.base.rows[a] for a in selected}
        view.relations = {a: self.base.relations[a] for a in selected}
        view.postings = {field: defaultdict(set) for field in FIELDS}
        for appid in selected:
            for field in FIELDS:
                for entity in view.relations[appid][field]:
                    view.postings[field][entity].add(appid)
        view.frequency = {field: {e: len(games) for e, games in view.postings[field].items()} for field in FIELDS}
        view.binding = copy.deepcopy(self.binding)
        view.binding.update(algorithm="year-filtered-multi-relation-idf-jaccard-v1", year_filter=dict(filters),
                            query_service_version=self.query_service_version)
        view.algorithm_version = "filtered-graph-score-v1-" + hashlib.sha256(json_text(view.binding).encode("utf-8")).hexdigest()
        return view

    def recommend(self, seeds: list[int] | tuple[int, ...], *, year_min: int | None = None,
                  year_max: int | None = None, top_k: int = 5) -> dict:
        """1–3游戏先按候选年份筛选，再建立共同IDF/排名；不合格种子明确阻止查询。"""
        self.base.inspector._check_unchanged()
        filters = validate_years(year_min, year_max)
        if (not isinstance(seeds, (list, tuple)) or any(not isinstance(s, int) or isinstance(s, bool)
                                                      or s not in self.base.inspector._rows for s in seeds)):
            raise ValueError("种子须为当前冻结快照中的整数appid列表")
        seeds = sorted(set(seeds))
        if not 1 <= len(seeds) <= 3:
            raise ValueError("去重后须有1–3款种子游戏")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 100:
            raise ValueError("top-k须为1–100整数")
        allowed = {a for a, row in self.base.rows.items()
                   if (year_min is None or release_year(row) >= year_min)
                   and (year_max is None or release_year(row) <= year_max)}
        checks = [self._describe(s) for s in seeds]
        common = {"query_service_version": self.query_service_version, "query_binding": copy.deepcopy(self.binding),
                  "filters": filters, "query_appids": seeds, "seed_checks": checks, "snapshot_games": len(self._searchable),
                  "candidate_games": len(self.base.rows), "filtered_candidate_games": len(allowed), "top_k": top_k,
                  "filter_order": "year_filter_then_idf_then_rank_then_top_k"}
        if any(not c["recommendation_eligible"] for c in checks):
            self.base.inspector._check_unchanged()
            return {**common, "algorithm_version": None, "binding": None, "status": "seed_ineligible", "results": [],
                    "idf_reference_games": None, "empty_reason": "所选种子未全部通过推荐资格；请查看seed_checks原因，不对其余种子偷偷继续。"}
        view = self._restricted_base(allowed, seeds, filters)
        report = view.recommend(seeds[0], top_k) if len(seeds) == 1 else MultiGameRecommender(view).recommend(seeds, top_k)
        report["scoring_index_games"] = report["candidate_games"]
        report.update(common)
        for result in report["results"]:
            row = self.base.rows[result["appid"]]
            result.update(release_date=row["release_date"], release_year=release_year(row))
        if not allowed - set(seeds):
            report.update(status="no_candidates", empty_reason="年份范围内没有排除全部种子后的有效候选；不生成fallback。")
        else:
            report["status"] = "ok" if report["results"] else "no_shared_relation"
        self.base.inspector._check_unchanged()
        return report


def main() -> None:
    """独立search/recommend CLI；仅本地读取与新建相同版本的查询证据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--folder", type=Path, default=GRAPHS)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search")
    search.add_argument("--text", default="")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    recommend = sub.add_parser("recommend")
    recommend.add_argument("--appids", type=int, nargs="+", required=True)
    recommend.add_argument("--year-min", type=int)
    recommend.add_argument("--year-max", type=int)
    recommend.add_argument("--top-k", type=int, default=5)
    for command in (search, recommend):
        command.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"kg-v1-[a-f0-9]{64}", args.version):
        parser.error("无效图谱版本")
    engine = RecommendationQueryService(GraphRecommender(GraphInspector(args.folder / args.version, snapshots=args.snapshots)))
    report = (engine.search(args.text, args.limit, args.offset) if args.command == "search" else
              engine.recommend(args.appids, year_min=args.year_min, year_max=args.year_max, top_k=args.top_k))
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            if args.output.read_text(encoding="utf-8") != payload:
                raise ValueError("已有不同内容，拒绝覆盖，请使用新输出路径")
        else:
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        print(json_text({"output": str(args.output), "query_service_version": engine.query_service_version,
                         "results": [{"appid": r["appid"], **({"score": r["score"]} if "score" in r else {})} for r in report["results"]]}))
    else:
        print(payload)


if __name__ == "__main__":
    main()
