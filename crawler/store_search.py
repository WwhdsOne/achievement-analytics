"""crawler.store_search — Steam 商店搜索（全量枚举入口，免 key）

这是本项目**唯一免 key 的全量游戏枚举入口**，用途是「种子」：先把大量游戏灌进
``games`` 表，再让 gap 驱动的 worker 逐个源回填。

为什么是它（2026-09-17 实测）：
- ``ISteamApps/GetAppList/v2`` **整个接口已被删除**（不是改名）
  —— 返回 ``Method 'GetAppList' not found in interface 'ISteamApps'``，
  v1 / v0002 同样 404
- 替代品 ``IStoreService/GetAppList/v1`` **需要 API key**（403 Access is denied）
- 商店搜索**免 key**，且 ``total_count`` 直接给出总体规模

过滤条件的实测口径（2026-09-17）：

=================================  =========  ==============================
过滤                                 total_count  说明
=================================  =========  ==============================
无过滤                                  285,346  全站条目，含 DLC / 软体 / 原声
``category1=998``                       176,932  只要游戏（排除 DLC / 软体等）
``category1=998`` + ``category2=22``     81,847  游戏 **且带 Steam 成就**
``category2=22``                        117,791  带成就，但含 DLC / 软体
=================================  =========  ==============================

**81,849 才是 Q1/Q2 的真正总体**：Q1 的 IRT 需要成就，Q2 的难度特征也来自成就。
（当日多次探测得到 81,847 / 81,849 / 81,850 / 81,859，见下方「total_count 会变动」）

排序与完整性（2026-09-17 实测，**这是本项目最重要的一条爬虫结论**）：

默认排序**在翻页期间会漂移**，实测一轮 819 页只拿到 69,498 个唯一 appid
（目标 81,850，**覆盖率 84.9%**，重复 12,392 行）——重复被去重丢掉，尾部数据整段
没拿到，**而漏项无法自知**（`holes` 只统计取页失败）。

``sort_by=Released_DESC`` 是修法。它按发售日严格递减（逐页抽查 0/100/…/600 页，
页内与页间都单调），好处是**新作只从顶部进入**：累积位移 = 翻页期间的新作数，
实测重复从 **12,392 条降到 99 条（125 倍）**，因此帧接近完整。

⚠️ **不要拿这个排序去「提前停止」**（我一开始就是这么想的，方向搞反了）：
``Released_DESC`` 是**新的在前**，2026 年新作在**前面**、我们要的 pre-2026 全在
**后面**——「翻到 pre-2026 就停」恰好停在有用数据开始的地方。想省掉前面那段
2026 新作（约 106 页 / 10,496 款），得改成「从边界偏移开始翻」而不是「到头就停」。

各排序的 ``total_count`` 不同（实测）：

====================  =========  ====================================
``sort_by``            total      说明
====================  =========  ====================================
（默认）                81,859   相关度排序，**漂移最严重**
``Released_DESC``       61,491   按发售日降序，排除了未发售的；**用它**
``Reviews_DESC``        42,017   按评价数降序，排除无评价的
``Name_ASC``            81,859   按名称
====================  =========  ====================================

（用 ``Released_DESC`` 时，2026 年新作 ≈ 10,496 款 → 减去即得 pre-2026 ≈ 50,995 款，
与随机采样估的 49,900 一致。）

规模换算：81,849 款 ÷ 100 条/页 ≈ **819 次请求**，1s 间隔约 **14 分钟**
——这是全量枚举的全部成本，比逐款源便宜三个数量级，所以「先灌全量再回填」值得做。

限制与坑（均为 2026-09-17 实测）：
- 每页 ``count`` **硬上限 100**：传 ``count=1000`` 仍只返回 100 条
- **每页条数不是承诺值**：被限流时会悄悄缩水（请求 count=100 曾只回 25 条），
  所以分页必须按**实际返回行数**推进，不能按请求的 count（否则整段跳数据）
- ``total_count`` 会随时间变动（同一天两次探测得到 81,847 与 81,849）——商店库在实时
  增删，这不是 bug。收尾比对条数时按「±小偏差」判断，别要求严格相等
- 排序可能在分页之间漂移，理论上有重复或漏项 —— 所以结果**必须按 appid 去重**，
  且 appid 是 ``games`` 主键，重复 upsert 天然无害；但**漏项无法自知**，
  收尾时应比对抓到的条数与 ``total_count``
- 每行顺带给出 ``data-ds-tagids``（Steam 官方标签 ID）、发售日、好评率与评价数、
  ``data-price-final``（美分），这些是免费的热度与题材信号

每行解析出的字段（全部来自 ``results_html``，无需逐款再请求）::

    {
      "appid": 1867240,
      "name_en": "WARDOGS",
      "release_date": "Sep 10, 2026",     # 展示格式，入库前需解析
      "tag_ids": [493, 1663, 19],
      "review_label": "Very Positive",     # tooltip 第一行，展示名
      "review_class": "positive",          # CSS slug，不是展示名
      "review_percent": 85,
      "review_count": 39068,
      "price_cents": 3999,
    }
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any, Iterator

from crawler.http import request_json

logger = logging.getLogger(__name__)

SEARCH_URL = "https://store.steampowered.com/search/results/"

# count 的硬上限，实测传 1000 仍只返回 100 条
PAGE_SIZE = 100

# 页级重试：某个偏移取失败时**不能把整轮枚举带崩**（2026-09-17 实测：819 页跑到
# 第 32 页被限流打断，整轮直接抛错退出，前 3000 条白抓）。取不到的偏移记进
# `holes`，继续往下翻，最后一起报告——这样至少能拿到完整的其余部分。
PAGE_MAX_ATTEMPTS = 3
PAGE_BACKOFF_SEC = 5.0

# Steam 商店搜索的分类过滤值
CATEGORY_GAMES = 998       # 「游戏」，排除 DLC / 软体 / 原声带
CATEGORY_ACHIEVEMENTS = 22  # 「Steam 成就」

# ── results_html 解析 ─────────────────────────────────────
# 单行结构（2026-09-17 实测）::
#   <a href="https://store.steampowered.com/app/1867240/WARDOGS/..."
#      data-ds-appid="1867240" data-ds-tagids="[493,1663,19]"
#      class="search_result_row ...">
#     <span class="title">WARDOGS</span>
#     <div class="search_released ...">Sep 10, 2026</div>
#     <span class="search_review_summary positive"
#           data-tooltip-html="Very Positive&lt;br&gt;85% of the 39,068 user reviews...">
#     <div ... data-price-final="3999">
_ROW_SPLIT = re.compile(r'(?=<a href="https://store\.steampowered\.com/app/)')
_APPID_RE = re.compile(r'data-ds-appid="(\d+)"')
_TAGIDS_RE = re.compile(r'data-ds-tagids="\[([\d,\s]*)\]"')
_TITLE_RE = re.compile(r'<span class="title">(.*?)</span>', re.S)
_RELEASED_RE = re.compile(
    r'<div class="search_released[^"]*">\s*(.*?)\s*</div>', re.S
)
_PRICE_RE = re.compile(r'data-price-final="(\d+)"')
# 注意：class 里是评价档位的 **CSS slug**（positive / very_positive ...），
# 展示名（"Very Positive"）只在 tooltip 第一行，别抓错（2026-09-17 踩到）
_REVIEW_CLASS_RE = re.compile(r'class="search_review_summary ([^"]*)"')
_TOOLTIP_RE = re.compile(r'data-tooltip-html="(.*?)"', re.S)
# 例：「85% of the 39,068 user reviews for this game are positive」
_REVIEW_STATS_RE = re.compile(r"([\d.]+)% of the ([\d,]+) user reviews")


def build_params(
    start: int,
    *,
    count: int = PAGE_SIZE,
    games_only: bool = True,
    has_achievements: bool = True,
    sort_by: str | None = None,
) -> dict[str, Any]:
    """构造商店搜索的 query 参数。

    Args:
        start: 起始偏移（0 起）。
        count: 每页条数，**硬上限 100**，超出无效。
        games_only: 只保留 ``category1=998``（游戏），排除 DLC / 软体 / 原声带。
        has_achievements: 只保留 ``category2=22``（带 Steam 成就）的游戏。
        sort_by: 排序方式。**强烈建议用 ``Released_DESC``**（见模块 docstring 的
            「排序与完整性」）：它按发售日严格递减，既能「翻到目标年份就停」得到
            可证明完整的帧，又能把排序漂移从上万条压到几十条。

    Returns:
        query 参数字典。
    """
    count = min(count, PAGE_SIZE)  # 实测硬上限，超出也不会多返回
    params: dict[str, Any] = {
        "query": "",
        "start": start,
        "count": count,
        "infinite": 1,
        "json": 1,
    }
    if games_only:
        params["category1"] = CATEGORY_GAMES
    if has_achievements:
        params["category2"] = CATEGORY_ACHIEVEMENTS
    if sort_by:
        params["sort_by"] = sort_by
    return params


def parse_search_page(html_text: str) -> list[dict[str, Any]]:
    """解析搜索结果页的 ``results_html``，每行一条游戏记录。

    缺 appid 或标题的行直接跳过（结构变了不该静默产出脏数据）。

    Args:
        html_text: 接口返回的 ``results_html`` 片段。

    Returns:
        记录列表，字段见模块 docstring。字段缺失时为 None，**不臆造默认值**
        （例如没有评价就 review_count=None，而不是 0）。
    """
    rows: list[dict[str, Any]] = []
    for block in _ROW_SPLIT.split(html_text)[1:]:
        appid_m = _APPID_RE.search(block)
        title_m = _TITLE_RE.search(block)
        if not (appid_m and title_m):
            continue

        tag_m = _TAGIDS_RE.search(block)
        tag_ids = (
            [int(x) for x in tag_m.group(1).split(",") if x.strip()]
            if tag_m
            else []
        )

        released_m = _RELEASED_RE.search(block)
        price_m = _PRICE_RE.search(block)

        review_class: str | None = None
        review_label: str | None = None
        review_percent: int | None = None
        review_count: int | None = None
        class_m = _REVIEW_CLASS_RE.search(block)
        if class_m:
            review_class = html.unescape(class_m.group(1)).strip() or None
        tooltip_m = _TOOLTIP_RE.search(block)
        if tooltip_m:
            # tooltip 形如 "Very Positive<br>85% of the 39,068 user reviews..."
            tooltip = html.unescape(tooltip_m.group(1))
            review_label = tooltip.split("<br>")[0].strip() or None
            stats_m = _REVIEW_STATS_RE.search(tooltip)
            if stats_m:
                review_percent = int(float(stats_m.group(1)))
                review_count = int(stats_m.group(2).replace(",", ""))

        rows.append(
            {
                "appid": int(appid_m.group(1)),
                "name_en": html.unescape(title_m.group(1)).strip(),
                "release_date": (
                    html.unescape(released_m.group(1)).strip()
                    if released_m
                    else None
                ),
                "tag_ids": tag_ids,
                "review_label": review_label,
                "review_class": review_class,
                "review_percent": review_percent,
                "review_count": review_count,
                "price_cents": int(price_m.group(1)) if price_m else None,
            }
        )
    return rows


def fetch_search_page(
    start: int,
    *,
    count: int = PAGE_SIZE,
    games_only: bool = True,
    has_achievements: bool = True,
    sort_by: str | None = None,
) -> dict[str, Any]:
    """抓一页商店搜索结果（已缓存不重爬）。

    ``sort_by`` 决定分页内容，换排序等于换一套结果。

    Returns:
        ``{"total_count": int, "start": int, "rows": [...]}``。
        接口返回 success=false 时 rows 为空并告警。
    """
    params = build_params(
        start,
        count=count,
        games_only=games_only,
        has_achievements=has_achievements,
        sort_by=sort_by,
    )
    payload = request_json(SEARCH_URL, params, source="store_search")
    if not payload.get("success"):
        logger.warning("商店搜索未成功：start=%s payload=%s", start, payload)
        result: dict[str, Any] = {"total_count": 0, "start": start, "rows": []}
    else:
        result = {
            "total_count": int(payload.get("total_count") or 0),
            "start": int(payload.get("start") or start),
            "rows": parse_search_page(payload.get("results_html") or ""),
        }
    return result


def fetch_search_page_resilient(
    start: int,
    *,
    count: int = PAGE_SIZE,
    games_only: bool = True,
    has_achievements: bool = True,
    sort_by: str | None = None,
) -> dict[str, Any] | None:
    """带页级退避重试地取一页；彻底失败返回 None（由调用方记录成空洞）。

    与 ``http.request_json`` 的内部重试是两层不同的保护：那里管「一次请求」，
    这里管「一整页的取数」，且退避更长，能跨过站点的限流窗口。
    """
    for attempt in range(1, PAGE_MAX_ATTEMPTS + 1):
        try:
            return fetch_search_page(
                start,
                count=count,
                games_only=games_only,
                has_achievements=has_achievements,
                sort_by=sort_by,
            )
        except RuntimeError as exc:
            logger.warning(
                "取页失败（%d/%d）start=%s：%s", attempt, PAGE_MAX_ATTEMPTS, start, exc
            )
            if attempt < PAGE_MAX_ATTEMPTS:
                time.sleep(PAGE_BACKOFF_SEC * attempt)
    logger.error("放弃该页：start=%s（记为空洞，稍后可重跑补齐）", start)
    return None


# 从展示格式里抽年份：'Sep 10, 2026' / 'Q4 2026' / '2026' / 'February 2027' 都能命中；
# 'Coming soon' / 'To be announced' 命中不了 → 返回 None。
# 提前停止只需要年份粒度，所以不必引入完整日期解析（那属于 cleaning 层，
# crawler 依赖 cleaning 是分层倒置）。
_YEAR_RE = re.compile(r"(\d{4})\s*$")


def release_year(raw: str | None) -> int | None:
    """从商店的展示格式发售日里抽出年份；抽不到返回 None。

    用于校验排序方向、统计各年份占比等。**不要用它做「提前停止」**——
    见 :func:`iter_games` 的说明。
    """
    if not raw:
        return None
    match = _YEAR_RE.search(raw.strip())
    return int(match.group(1)) if match else None


def iter_games(
    start: int = 0,
    *,
    total: int | None = None,
    count: int = PAGE_SIZE,
    games_only: bool = True,
    has_achievements: bool = True,
    sort_by: str | None = None,
    holes: list[int] | None = None,
    report: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """逐页枚举游戏，产出**去重后**的记录。

    **单页失败不会中断整轮**：取不到的偏移会追加进 ``holes`` 并继续往下翻，
    调用方据此判断帧是否完整（扇区有洞就无法宣称是全量）。

    ⚠️ **「无空洞」不等于「帧完整」**（2026-09-17 踩到）：商店搜索的排序会在
    翻页期间漂移，造成**大量重复**——实测用**默认排序**跑一轮 819 页只拿到
    69,498 个唯一 appid（目标 81,850，**覆盖率 84.9%**），重复项被这里的去重
    丢掉，尾部数据整段没拿到。这个损失**不体现在 holes 里**，必须看 ``report``
    的 ``coverage``。

    正确做法是用 ``sort_by="Released_DESC"``（见模块 docstring）：按发售日严格
    递减，新作只从顶部进入，累积位移只有翻页期间的新作数——实测重复从 12,392 条
    降到 99 条。

    Args:
        start: 起始偏移。
        total: 最多枚举多少款；None 表示一直翻到 ``total_count``。
        count: 每页条数（硬上限 100）。
        games_only: 只枚举游戏。
        has_achievements: 只枚举带 Steam 成就的游戏。
        sort_by: 排序方式，建议 ``Released_DESC``。
        holes: 传入一个列表用于收集取数失败的偏移（就地追加）。
        report: 传入一个 dict 收集统计（就地写入）：
            ``total_count`` / ``pages`` / ``rows_seen`` / ``duplicates`` /
            ``unique`` / ``coverage``。

    Yields:
        去重后的游戏记录，字段同 ``parse_search_page``。
    """
    seen: set[int] = set()
    offset = start
    emitted = 0
    total_count: int | None = None
    pages = 0
    rows_seen = 0

    try:
        while True:
            if total is not None and emitted >= total:
                return
            page = fetch_search_page_resilient(
                offset,
                count=count,
                games_only=games_only,
                has_achievements=has_achievements,
                sort_by=sort_by,
            )
            pages += 1
            if page is None:
                if holes is not None:
                    holes.append(offset)
                # 记洞后继续翻页：一整轮几百页不该因为一页失败而前功尽弃
                offset += count
                if total_count and offset >= total_count:
                    return
                continue

            if total_count is None:
                total_count = page["total_count"]
                logger.info("商店搜索命中 %d 款（过滤条件已生效）", total_count)
            rows = page["rows"]
            if not rows:
                logger.info("枚举结束：start=%s 无数据", offset)
                return

            rows_seen += len(rows)
            for row in rows:
                if row["appid"] in seen:
                    continue
                seen.add(row["appid"])
                emitted += 1
                yield row
                if total is not None and emitted >= total:
                    return

            # **按实际返回行数推进，不能按请求的 count**：实测该接口会在被限流时
            # 悄悄缩水每页条数（请求 count=100 曾只回 25 条、99 条），若仍按 count
            # 推进就会整段跳过数据（2026-09-17 踩到）。
            offset += len(rows)
            if total_count and offset >= total_count:
                logger.info("枚举结束：已翻过 total_count=%d", total_count)
                return
    finally:
        if report is not None:
            report.update(
                total_count=total_count or 0,
                pages=pages,
                rows_seen=rows_seen,
                unique=emitted,
                duplicates=rows_seen - emitted,
                coverage=(emitted / total_count) if total_count else None,
            )


def total_count(*, games_only: bool = True, has_achievements: bool = True) -> int:
    """取符合过滤条件的总体条数（只发一次请求）。"""
    return fetch_search_page(
        0, games_only=games_only, has_achievements=has_achievements
    )["total_count"]
