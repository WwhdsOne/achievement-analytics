"""crawler.test_crawl — 单款游戏的多源抓取演示

手动填写下面的 APPID，运行一次，把这个游戏从各个数据源抓到的信息打印
出来，用于肉眼验收「数据源效果」和「组合成一条记录」的形态。

流程（按 AGENTS.md 的定位）：
  1. 先查**官方权威数据**（Steam 商店 appdetails）拿到**官方中英文名**
  2. 再用官方名 / appid 去查其他数据源（SteamSpy / RAWG）

这是探索脚本，不是正式管道；正式逻辑在 crawler/ 与 cleaning/ 各模块里。

用法:
    1. 改下面的 APPID
    2. uv run python -m crawler.test_crawl

**必须用 -m 以模块方式运行**。直接 `uv run crawler/test_crawl.py` 会把脚本所在
目录（crawler/）放进 sys.path[0] 而不是项目根，导致 `import crawler.steam_api`
报 ModuleNotFoundError（2026-09-15 踩过）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from crawler.steam_api import (
    fetch_appdetails,
    fetch_community_achievements,
    fetch_global_achievement_percentages,
)
from crawler.steamspy import fetch_app_details as fetch_steamspy

# ═══════════════════════════════════════════════════════════
APPID = 374320  # ← 改这里（374320 = 黑暗之魂3）
# ═══════════════════════════════════════════════════════════

LINE = "=" * 68


def main() -> None:
    print(LINE)
    print(f"Steam AppID = {APPID}")
    print(LINE)

    en = fetch_appdetails([APPID], lang="english").get(str(APPID)) or {}
    zh = fetch_appdetails([APPID], lang="schinese").get(str(APPID)) or {}
    name_en = en.get("name") or ""
    name_zh = zh.get("name") or name_en

    _print_official(en, name_en, name_zh)

    spy = fetch_steamspy(APPID)
    _print_steamspy(spy)

    rawg = _fetch_and_print_rawg(APPID, name_en, name_zh)

    valve_ach = fetch_global_achievement_percentages(APPID)
    community = fetch_community_achievements(APPID)
    achievements = _print_achievements(valve_ach, community)

    _print_record(en, name_en, name_zh, spy, rawg, achievements)


def _print_official(d: dict[str, Any], name_en: str, name_zh: str) -> None:
    """打印官方权威数据（Steam 商店 appdetails）。"""
    print("\n【1】官方权威数据（Steam appdetails，免 key）")
    if not d:
        print("  无数据")
        return
    price = d.get("price_overview") or {}
    print(f"  名称（英文）   {name_en}")
    print(f"  名称（中文）   {name_zh}")
    print(f"  类型           {d.get('type')}")
    print(f"  发售日         {(d.get('release_date') or {}).get('date')}")
    print(
        f"  价格           {price.get('final_formatted') or ('免费' if d.get('is_free') else '未定价')}"
    )
    print(f"  开发商         {', '.join(d.get('developers') or [])}")
    print(f"  发行商         {', '.join(d.get('publishers') or [])}")
    print(f"  官方 genre     {[g['description'] for g in d.get('genres') or []]}")
    print(
        f"  官方 category  {', '.join(c['description'] for c in d.get('categories') or [])}"
    )
    print(f"  好评数         {(d.get('recommendations') or {}).get('total')}")


def _print_steamspy(s: dict[str, Any]) -> None:
    """打印 SteamSpy 数据与用户标签。"""
    print("\n【2】SteamSpy（免 key）")
    if not s:
        print("  SteamSpy 查不到这个 appid")
        return
    print(f"  owners         {s.get('owners')}")
    print(f"  ccu            {s.get('ccu')}")
    print(f"  好评 / 差评    {s.get('positive')} / {s.get('negative')}")
    print(
        f"  时长字段       average_forever={s.get('average_forever')} "
        f"median_forever={s.get('median_forever')}   ← 已失效，恒为 0"
    )
    tags = s.get("tags") or {}
    print(f"\n  用户标签（{len(tags)} 个，按票数降序；即 Steam 商店的用户自定义标签）")
    for tag, votes in sorted(tags.items(), key=lambda kv: kv[1], reverse=True):
        print(f"    {tag:<30} {votes}")


def _fetch_and_print_rawg(
    appid: int, name_en: str, name_zh: str
) -> dict[str, Any]:
    """按名搜索 + appid 校验匹配 RAWG，并打印结果。返回 {} 表示未匹配/未配置。"""
    print("\n【3】RAWG（需 key，按官方英文名搜 + appid 校验）")
    # 判据是「有 key 来源」：本 demo 不认识共享密钥池（那是 worker 的活），
    # 所以这里只认本地 .env 的 key —— 用 key_available() 与抓取管道保持同一套语义
    from crawler.rawg import key_available

    if not key_available():
        print("  跳过：既无本地 RAWG_API_KEY，也无共享密钥池（worker 跑时才会注入池子）")
        return {}

    from crawler.rawg import match_by_appid

    detail = match_by_appid(appid, [name_en, name_zh])
    if not detail:
        print(f"  RAWG 未能匹配到 appid={appid}（候选里有游戏的 appid 都对不上）")
        return {}
    print(f"  name           {detail.get('name')}")
    print(f"  released       {detail.get('released')}")
    print(f"  metacritic     {detail.get('metacritic')}   ← RAWG 独有价值")
    print(f"  rating         {detail.get('rating')}（RAWG 用户评分）")
    print(f"  genres         {[g['name'] for g in detail.get('genres') or []]}")

    from crawler.rawg import split_tags

    themes, platform = split_tags(detail.get("tags") or [])
    print(f"\n  题材类 tags（{len(themes)} 个）")
    print(f"    {themes}")
    print(f"  平台功能类 tags（{len(platform)} 个，做题材特征时要剔除）")
    print(f"    {platform}")
    return detail


def _print_achievements(
    valve: list[dict[str, Any]], community: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """按位对齐两个成就源并打印，返回对齐后的成就记录列表。

    两个源的成就顺序一致才敢按位 zip；长度不一致时只对齐到较短的一方，
    并打印告警（正式管道里这种情况要出差集报告）。
    """
    print("\n【4】成就（两个免 key 源按位对齐）")
    if not valve and not community:
        print("  这个游戏没有成就数据")
        return []

    valve_pct = [float(a["percent"]) for a in valve]
    page_pct = [r["percent"] for r in community]
    n_valve, n_page = len(valve), len(community)
    print(f"  全局接口 {n_valve} 项 / 社区页 {n_page} 项")
    print(f"  条数一致 = {n_valve == n_page}    顺序一致 = {valve_pct == page_pct}")
    if n_valve != n_page or valve_pct != page_pct:
        print("  ⚠ 两源不一致，按位对齐可能错位——正式管道这里要出差集报告")

    n = min(n_valve, n_page)
    rows = [
        {
            "position": i + 1,
            "api_name": valve[i]["name"],
            "display_name": community[i]["display_name"],
            "description": community[i]["description"],
            "percent": valve_pct[i],
        }
        for i in range(n)
    ]

    print(f"\n  {'#':>3}  {'api_name（内部名）':<28} {'展示名':<32} {'完成率':>7}")
    print("  " + "-" * 74)
    for r in rows:
        print(
            f"  {r['position']:>3}  {r['api_name']:<28} "
            f"{r['display_name'][:30]:<32} {r['percent']:>6.1f}%"
        )

    if rows:
        pcts = sorted(r["percent"] for r in rows)
        m = len(pcts)
        median = pcts[m // 2] if m % 2 else (pcts[m // 2 - 1] + pcts[m // 2]) / 2
        p10 = pcts[max(0, int(m * 0.1))]
        hard = sum(1 for p in pcts if p < 10)
        print(
            f"\n  难度结构   n={m}  中位={median:.1f}%  P10={p10:.1f}%  "
            f"极难(<10%)={hard} 项  最易={pcts[-1]:.1f}%  最难={pcts[0]:.1f}%"
        )
    return rows


def _print_record(
    details: dict[str, Any],
    name_en: str,
    name_zh: str,
    spy: dict[str, Any],
    rawg: dict[str, Any],
    achievements: list[dict[str, Any]],
) -> None:
    """打印「组合成一条记录」的形态（未来入库的样子）。"""
    print("\n【5】组合成一条记录（未来入库的样子）")
    record = {
        "appid": APPID,
        "name_en": name_en,
        "name_zh": name_zh,
        "type": details.get("type"),
        "release_date": (details.get("release_date") or {}).get("date"),
        "is_free": details.get("is_free"),
        "price_cents": (details.get("price_overview") or {}).get("final"),
        "developers": details.get("developers"),
        "publishers": details.get("publishers"),
        "valve_genres": [g["description"] for g in details.get("genres") or []],
        "steamspy": {
            "owners": spy.get("owners"),
            "ccu": spy.get("ccu"),
            "positive": spy.get("positive"),
            "negative": spy.get("negative"),
            "tags": spy.get("tags"),
        },
        "rawg": (
            {
                "metacritic": rawg.get("metacritic"),
                "rating": rawg.get("rating"),
                "released": rawg.get("released"),
                "genres": [g["name"] for g in rawg.get("genres") or []],
            }
            if rawg
            else None
        ),
        "achievement_count": len(achievements),
        # 完整列表上面表格已列，这里只放前 3 条示意字段形态
        "achievements": [
            {k: r[k] for k in ("api_name", "display_name", "percent")}
            for r in achievements[:3]
        ],
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        ),
    }
    print("  " + json.dumps(record, ensure_ascii=False, indent=2).replace("\n", "\n  "))
    if len(achievements) > 3:
        print(f"\n  ↑ achievements 实际共 {len(achievements)} 条，上面只展示前 3 条")


if __name__ == "__main__":
    main()
