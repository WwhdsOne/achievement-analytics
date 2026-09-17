"""crawler.registry — 数据源注册表（运行时配置）

与 ``cleaning/schema.sql`` 里 ``sources`` 表的关系：
- **schema.sql 是唯一真源**（它是 DDL 与人读文档），这里只做「同一个清单的 Python 视图」，
  因为限速要在**进程内**生效（http.py 的节流），不能每发一次请求都去查库。
- 两边必须一致，``tests/test_registry.py`` 会解析 schema.sql 断言这一点——防的是
  「加了源只改一处」这类漂移。

``kind`` 决定抓取范式，也决定源能不能进队列：

===========  ==========================================  ================
kind         含义                                        是否进 fetch_tasks
===========  ==========================================  ================
bulk         一次请求覆盖多款（商店搜索 100/次，          否，走独立的
             SteamSpy all 1000/次）                      「全量刷新」任务
per_game     一次请求只覆盖一款                           是，走 gap 驱动队列
===========  ==========================================  ================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["bulk", "per_game"]


@dataclass(frozen=True)
class SourceSpec:
    """单个数据源的抓取配置。字段与 schema.sql 的 sources 表一一对应。"""

    source: str
    kind: Kind
    interval_sec: float
    daily_quota: int | None
    monthly_quota: int | None
    max_attempts: int
    note: str

    @property
    def interval_ms(self) -> int:
        """毫秒表示的限速间隔（schema.sql 里存的是毫秒）。"""
        return round(self.interval_sec * 1000)


SOURCES: dict[str, SourceSpec] = {
    spec.source: spec
    for spec in (
        SourceSpec(
            source="store_search",
            kind="bulk",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            note="Steam 商店搜索：全量枚举入口，一次 100 款（count 上限 100，传 1000 无效）。免 key",
        ),
        SourceSpec(
            source="steamspy_all",
            kind="bulk",
            interval_sec=60.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            note=(
                "SteamSpy request=all：一次 1000 款，含 owners/ccu/好评差评。免 key。"
                "官方限速写明 request=all 是 1 req/60s（不是 1 req/s），故 interval_sec=60。"
                "报错字段不含 tags，且 average_forever/median_forever 已失效恒为 0"
            ),
        ),
        SourceSpec(
            source="appdetails_en",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            note="Steam 商店 appdetails（l=english）：官方英文名与元数据。实测不支持批量，只能单 appid。免 key",
        ),
        SourceSpec(
            source="appdetails_zh",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            note="Steam 商店 appdetails（l=schinese）：官方中文名，无中文名时回落英文名。免 key",
        ),
        SourceSpec(
            source="global_ach",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            note="GetGlobalAchievementPercentagesForApp：内部名 + percent，难度核心数据。免 key",
        ),
        SourceSpec(
            source="community_ach",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            note="Steam 社区成就页：展示名 + percent + 描述。免 key。与 global_ach 顺序一致，按位对齐完成名称映射",
        ),
        SourceSpec(
            source="steamspy",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=1000,
            monthly_quota=None,
            max_attempts=3,
            note=(
                "SteamSpy appdetails：用户标签 + 票数（bulk 的 steamspy_all 拿不到 tags，这是它唯一独有价值）。"
                "免 key。官方页面只公布 1 req/s（2026-09-17 核对），"
                "**没有公布任何「每天 N 次」的配额** —— 这里 daily_quota=1000 是"
                "**本项目自设的保守上限**（避免在限流窗口里反复撞墙），不是官方额度。"
                "81,850 款按 1000/天要 82 天，故只应作为「取标签」的可选补充，不要盲目全量入队"
            ),
        ),
        SourceSpec(
            source="rawg",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=20000,
            max_attempts=3,
            note=(
                "RAWG：评分 / 时长 / 弃坑率 / 题材标签。**需 key**。免费档 20,000 请求/月（官方文档），"
                "响应头不暴露剩余额度，故配额靠 api_usage 自行记账"
            ),
        ),
    )
}


def get(source: str) -> SourceSpec:
    """取某个源的配置。

    Raises:
        KeyError: 源未注册。
    """
    return SOURCES[source]


def per_game_sources() -> list[str]:
    """全部逐款源的标识（这些才进 fetch_tasks 队列）。"""
    return [s.source for s in SOURCES.values() if s.kind == "per_game"]


def bulk_sources() -> list[str]:
    """全部批量源的标识（一次请求覆盖多款，不进队列）。"""
    return [s.source for s in SOURCES.values() if s.kind == "bulk"]


def interval_for(source: str, default: float = 1.0) -> float:
    """取某源的限速间隔（秒）；未注册的源用 default，便于临时源不炸。"""
    spec = SOURCES.get(source)
    return spec.interval_sec if spec else default
