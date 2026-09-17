"""crawler.store_search 的解析与分页测试。

固定样本取自 2026-09-17 的真实响应结构（含一个缺评价字段的未发售游戏），
不依赖网络。
"""

from __future__ import annotations

import pytest

from crawler.store_search import (
    PAGE_SIZE,
    build_params,
    parse_search_page,
)

# 两行：一行数据齐全，一行是未发售游戏（没有评价摘要、price 为 0）
SAMPLE_HTML = """
<a href="https://store.steampowered.com/app/1867240/WARDOGS/?snr=1_7_7_230_150_1"
 data-ds-appid="1867240" data-ds-itemkey="App_1867240" data-ds-tagids="[493,1663,19]"
 class="search_result_row ds_collapse_flag "
   data-search-page="1">
            <div class="search_capsule"><img src="https://x/capsule.jpg" ></div>
            <div class="responsive_search_name_combined">
                <div class="search_name ellipsis">
                    <span class="title">WARDOGS</span>
                </div>
                <div class="search_released responsive_secondrow">
                    Sep 10, 2026                </div>
                <div class="search_reviewscore responsive_secondrow">
                                            <span class="search_review_summary positive" data-tooltip-html="Very Positive&lt;br&gt;85% of the 39,068 user reviews for this game are positive.&lt;br&gt;&lt;br&gt;The review score"></span>
                                    </div>
                <div class="search_price_discount_combined responsive_secondrow" data-price-final="3999">
                        <div class="discount_block search_discount_block no_discount" data-price-final="3999"><div class="discount_prices"><div class="discount_final_price">$39.99</div></div></div>
                </div>
            </div>
        </a>
<a href="https://store.steampowered.com/app/9990001/Coming_Soon/?snr=1_7_7_230_150_2"
 data-ds-appid="9990001" data-ds-tagids="[]"
 class="search_result_row ds_collapse_flag "
   data-search-page="1">
            <div class="responsive_search_name_combined">
                <div class="search_name ellipsis">
                    <span class="title">Untitled &amp;amp; Unreleased</span>
                </div>
                <div class="search_released responsive_secondrow">
                    Coming soon                </div>
                <div class="search_price_discount_combined responsive_secondrow" data-price-final="0">
                        <div class="discount_block search_discount_block no_discount" data-price-final="0"></div>
                </div>
            </div>
        </a>
"""


def test_parse_fills_all_fields() -> None:
    """字段齐全的行应被完整解析出来。"""
    rows = parse_search_page(SAMPLE_HTML)
    assert len(rows) == 2
    r = rows[0]
    assert r["appid"] == 1867240
    assert r["name_en"] == "WARDOGS"
    assert r["release_date"] == "Sep 10, 2026"
    assert r["tag_ids"] == [493, 1663, 19]
    assert r["review_percent"] == 85
    assert r["review_count"] == 39068  # 千分位逗号已剥掉
    assert r["price_cents"] == 3999


def test_review_label_is_display_name_not_css_class() -> None:
    """评价档位要取 tooltip 里的展示名，不能取 CSS class 的 slug。

    2026-09-17 踩到：class 里是 ``positive``，展示名 ``Very Positive`` 只在 tooltip
    第一行，抓错就会把「好评如潮」和「褒贬不一」压成同一个值。
    """
    r = parse_search_page(SAMPLE_HTML)[0]
    assert r["review_label"] == "Very Positive"
    assert r["review_class"] == "positive"


def test_missing_review_is_none_not_zero() -> None:
    """未发售游戏没有评价，应为 None —— 用 0 顶替会让「没数据」看起来像「没人好评」。"""
    r = parse_search_page(SAMPLE_HTML)[1]
    assert r["review_label"] is None
    assert r["review_percent"] is None
    assert r["review_count"] is None
    assert r["tag_ids"] == []


def test_parse_skips_rows_without_appid() -> None:
    """结构变了（缺 appid / 缺标题）时跳过，不产出脏数据。"""
    assert parse_search_page("<div>没有结果行</div>") == []
    assert parse_search_page('<span class="title">孤儿标题</span>') == []


def test_parse_unescapes_entities() -> None:
    """HTML 实体要反转义（``&amp;`` -> ``&``）。"""
    r = parse_search_page(SAMPLE_HTML)[1]
    assert "&" in r["name_en"]


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(5, 5), (25, 25), (100, 100), (200, PAGE_SIZE), (1000, PAGE_SIZE)],
)
def test_build_params_clamps_count(requested: int, expected: int) -> None:
    """count 硬上限 100：实测传 1000 仍只返回 100 条。"""
    params = build_params(0, count=requested)
    assert params["count"] == expected


def test_build_params_category_filters() -> None:
    """默认只要「带成就的游戏」：category1=998 + category2=22。"""
    params = build_params(0)
    assert params["category1"] == 998
    assert params["category2"] == 22

    loose = build_params(0, games_only=False, has_achievements=False)
    assert "category1" not in loose
    assert "category2" not in loose
