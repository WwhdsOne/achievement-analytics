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
    priority: int = 100
    """抓取优先级，小的先跑。**顺序决定「剔除无成就游戏」能省多少**：
    ``global_ach`` 越早跑，越早能确认某游戏没有成就并取消它其余任务；
    ``rawg`` 放最后，因为它每次匹配要花 2~5 次月度配额。"""

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
            source="store_applist",
            kind="bulk",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            note=(
                "IStoreService/GetAppList：**按 appid 顺序**返回商店全部条目，用 last_appid "
                "游标续页 —— **无排序漂移、完整性可证明**（商店搜索会漂移，实测一轮 819 页"
                "只覆盖 84.9% 且漏项无法自知）。max_results 最大 50000，"
                "约 4 次请求覆盖 17.7 万款游戏。**需 Steam Web API key**。"
                "缺口：不含发售日与成就信息，需与 store_search / appdetails 配合"
            ),
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
            priority=10,
            note="Steam 商店 appdetails（l=english）：官方英文名与元数据。实测不支持批量，只能单 appid。免 key。优先级最高：建立 games 行并提供 type",
        ),
        SourceSpec(
            source="appdetails_zh",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            priority=40,
            note="Steam 商店 appdetails（l=schinese）：官方中文名，无中文名时回落英文名。免 key",
        ),
        SourceSpec(
            source="global_ach",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            priority=20,
            note="GetGlobalAchievementPercentagesForApp：内部名 + percent，难度核心数据。免 key。对无成就的 appid 返回 403，已归一成「确定性无数据」→ 越早跑越好，确认无成就即可取消该游戏其余任务",
        ),
        SourceSpec(
            source="community_ach",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            priority=30,
            note="Steam 社区成就页：展示名 + percent + 描述。免 key。与 global_ach 顺序一致，按位对齐完成名称映射。两者是**一对**：缺任一个都生成不了 achievements",
        ),
        SourceSpec(
            source="steamspy",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=None,
            max_attempts=3,
            priority=50,
            note=(
                "SteamSpy appdetails：用户标签 + 票数（bulk 的 steamspy_all 拿不到 tags，这是它唯一独有价值）。"
                "免 key。官方页面只公布 1 req/s（2026-09-17 核对），**没有公布任何日配额** —— "
                "2026-09-22 起取消本项目自设的 1000/天上限（48,798 个待抓任务按 1000/天要 49 天，"
                "而官方限速 1 req/s 的理论上限是 86,400/天，1000 定得过于保守）。"
                "现在**只有速率限制**：1 req/s，按机器分桶（与 RAWG 的按 key 配额不同，"
                "不存在跨机器的共享账本）。"
            ),
        ),
        SourceSpec(
            source="rawg",
            kind="per_game",
            interval_sec=1.0,
            daily_quota=None,
            monthly_quota=20000,
            max_attempts=3,
            priority=90,
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
