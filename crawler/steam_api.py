"""crawler.steam_api — Steam 公开数据采集模块

全部数据源免 key。2026-09-15 决定：个人 Steam API key 只能覆盖 key 持有者
本人的逐玩家数据，对本项目的**游戏级**分析没有价值，因此不申请、不使用
任何 key。

使用的公开数据源：
- appdetails（商店接口）：游戏元数据 + 成就概览。**单 appid 请求**，实测多
  appid 批量返回 400；成就字段只有 total + 10 个 highlighted 展示名
- GetGlobalAchievementPercentagesForApp：全局成就完成率，返回内部名
  （如 ACH39）+ percent，是本项目的难度核心数据
- Steam 社区成就页：**全部**成就的展示名 + 完成率。与上一项的成就顺序一致
  （2026-09-15 实测：条数 / percent 多重集 / 顺序完全相同），两者按位对齐
  即可得到 name -> displayName 映射，不需要 GetSchemaForGame

限速 / 重试 / 缓存统一走 crawler.http。硬性规范见 AGENTS.md。
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

from crawler.http import HttpStatusError, SourceChallenge, request_json, request_text

logger = logging.getLogger(__name__)

STORE_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
WEB_API_BASE = "https://api.steampowered.com"
COMMUNITY_STATS_URL = "https://steamcommunity.com/stats/{appid}/achievements"

# appdetails 的 lang 参数 -> 注册表里的源标识（限速与配额按源分别记）
_LANG_TO_SOURCE: dict[str, str] = {
    "english": "appdetails_en",
    "schinese": "appdetails_zh",
}


# ── 公开接口 ──────────────────────────────────────────────


def fetch_appdetails(
    appids: list[int], lang: str = "english"
) -> dict[str, dict[str, Any]]:
    """逐个拉取商店 appdetails（游戏元数据 + 成就概览，免 key）。

    实测 appdetails 不支持多 appid 批量（返回 400），只能单 appid 请求。

    Args:
        appids: 要拉取的 Steam AppID 列表。
        lang: 语言（english / schinese / …）。**官方名随语言变化**，取中英文
            官方名就分别用 "english" 与 "schinese" 各拉一次（2026-09-15 实测：
            ELDEN RING -> 艾尔登法环，Valve 无中文名时回落英文名）。

    Returns:
        {appid_str: data}，仅含 success 条目；失败 appid 记日志并跳过。
    """
    result: dict[str, dict[str, Any]] = {}
    for appid in appids:
        try:
            payload = request_json(
                STORE_APPDETAILS_URL,
                {"appids": appid, "l": lang},
                source=_LANG_TO_SOURCE.get(lang, "appdetails_en"),
            )
        except RuntimeError as exc:
            logger.error("appdetails 失败，跳过 appid=%s：%s", appid, exc)
            continue
        entry = payload.get(str(appid)) or {}
        if not entry.get("success"):
            logger.warning("appdetails 无数据：appid=%s", appid)
            continue
        result[str(appid)] = entry["data"]
    return result


def fetch_official_names(appid: int) -> dict[str, str]:
    """取该游戏的**官方中英文名**（Steam 商店 appdetails，免 key）。

    这是"以官方权威数据定游戏身份"的第一步：先拿到 Valve 官方名，
    再用它去查询其他数据源。

    Returns:
        {"name_en": ..., "name_zh": ...}；取不到时为缺省的空字符串。
        Valve 没有中文名时 name_zh 会回落成英文名。
    """
    en = fetch_appdetails([appid], lang="english").get(str(appid)) or {}
    zh = fetch_appdetails([appid], lang="schinese").get(str(appid)) or {}
    return {
        "name_en": en.get("name") or "",
        "name_zh": zh.get("name") or en.get("name") or "",
    }


def fetch_global_achievement_percentages(appid: int) -> list[dict[str, Any]]:
    """拉取某游戏的全局成就完成率（免 key）。

    **HTTP 403 表示该 appid 没有成就数据**（实测 12/12，2026-09-17）：
    Steam 对无成就的 appid 不是返回空列表而是直接 403。这里把它归一成空列表，
    这样调用方能记成「确定性无数据（empty）」而不是「可重试的失败（error）」——
    后者会白白重试 3 次并最终记成 exhausted，浪费请求也混淆归因。

    ⚠️ 403 的结果**故意不写缓存**：虽然当前口径下「无成就」不会再变，但若某个
    未发售游戏日后上线并加了成就，缓存会把「无成就」永久钉死。这类 appid 数量少，
    重跑时多发几次请求比钉死错误结论划算。

    Returns:
        [{"name": API 内部名, "percent": 全局完成率字符串}, ...]，无成就数据时为空列表。
        注意 name 是内部名（如 ACH39 / NEW_ACHIEVEMENT_1_1），须按位对齐
        社区成就页拿到 displayName 后才能进正式分析与报告（AGENTS.md 硬性）。
    """
    try:
        payload = request_json(
            f"{WEB_API_BASE}/ISteamUserStats/"
            f"GetGlobalAchievementPercentagesForApp/v2/",
            {"gameid": appid, "format": "json"},
            source="global_ach",
        )
    except SourceChallenge:
        # 反爬挑战也是 403，但**绝不能**当成「无成就」——那样会把这款游戏误判成
        # 没有成就数据并连带剔除它的其余任务（worker 的 prune 逻辑）。
        # 原样上抛，由 worker 按「源临时不可用」处理（2026-09-24 加）。
        raise
    except HttpStatusError as exc:
        if exc.status == 403:
            logger.info("appid=%s 无成就数据（HTTP 403），按空处理", appid)
            return []
        raise
    achievements = (payload.get("achievementpercentages") or {}).get(
        "achievements"
    ) or []
    if not achievements:
        logger.warning("全局完成率为空：appid=%s", appid)
    return achievements


def fetch_community_achievements(appid: int) -> list[dict[str, Any]]:
    """拉取 Steam 社区成就页的全部成就（展示名 + 完成率，免 key）。

    这是 name -> displayName 映射的公开替代方案：页面把「展示名 + 完成率」
    成对给出，不需要 GetSchemaForGame（需 key）。

    返回顺序与 fetch_global_achievement_percentages 一致（2026-09-15 对
    黑魂3 实测：条数、percent 多重集、顺序三者完全相同），调用方可按位
    对齐给内部名补上展示名。

    Returns:
        [{"display_name": 展示名, "percent": 完成率(float),
          "description": 成就描述}, ...]；页面无成就时返回空列表。
    """
    text = request_text(
        COMMUNITY_STATS_URL.format(appid=appid), source="community_ach"
    )
    rows = _parse_achievement_rows(text)
    if not rows:
        logger.warning("社区成就页解析不到成就行：appid=%s", appid)
    return rows


# ── 社区成就页解析 ────────────────────────────────────────

# 页面结构（2026-09-15 实测）::
#   <div class="achieveRow">
#     <div class="achievePercent">93.9%</div>
#     <div class="achieveTxt">
#       <h3>Enkindle</h3>
#       <h5>Light a bonfire flame for the first time.</h5>
#     </div>
#   </div>
_ROW_SPLIT = '<div class="achieveRow'
_PERCENT_RE = re.compile(r'class="achievePercent">([\d.]+)%')
_TITLE_RE = re.compile(r"<h3>(.*?)</h3>", re.S)
_DESC_RE = re.compile(r"<h5>(.*?)</h5>", re.S)


def _parse_achievement_rows(text: str) -> list[dict[str, Any]]:
    """从社区成就页 HTML 解析出展示名 / 完成率 / 描述。

    缺 percent 或 h3 的行直接跳过；描述缺失不跳过（隐藏成就可以没有描述）。

    Returns:
        [{"display_name": str, "percent": float, "description": str}, ...]。
    """
    rows: list[dict[str, Any]] = []
    for block in text.split(_ROW_SPLIT)[1:]:
        percent = _PERCENT_RE.search(block)
        title = _TITLE_RE.search(block)
        if not (percent and title):
            continue
        desc = _DESC_RE.search(block)
        rows.append(
            {
                "display_name": html.unescape(title.group(1)).strip(),
                "percent": float(percent.group(1)),
                "description": html.unescape(desc.group(1)).strip() if desc else "",
            }
        )
    return rows


# ── 冒烟测试：5 款 FromSoftware 游戏 ────────────────────

SMOKE_GAMES: dict[int, str] = {
    570940: "黑暗之魂：重制版",
    335300: "黑暗之魂2：原罪学者",
    374320: "黑暗之魂3",
    814380: "只狼：影逝二度",
    1245620: "艾尔登法环",
}


def easier_name(ach: dict[str, Any]) -> str:
    """打印用：截短成就内部名。"""
    return ach["name"][:28]


def smoke_test() -> None:
    """冒烟测试：跑通全部公开接口 + 验证按位对齐的名称映射。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=" * 62)
    print("1) appdetails（免 key，单 appid）")
    details = fetch_appdetails(list(SMOKE_GAMES))
    for appid, cn in SMOKE_GAMES.items():
        d = details.get(str(appid)) or {}
        ach = d.get("achievements") or {}
        print(
            f"  [{appid}] {d.get('name', '?')}（{cn}）"
            f" 成就总数={ach.get('total', '?')}"
            f" highlighted={len(ach.get('highlighted') or [])}"
        )

    print("=" * 62)
    print("2) 全局成就完成率（免 key，难度核心数据）")
    globals_by_appid: dict[int, list[dict[str, Any]]] = {}
    for appid, cn in SMOKE_GAMES.items():
        achs = fetch_global_achievement_percentages(appid)
        globals_by_appid[appid] = achs
        if achs:
            easiest = max(achs, key=lambda a: float(a["percent"]))
            hardest = min(achs, key=lambda a: float(a["percent"]))
            print(
                f"  [{appid}] {cn}：{len(achs)} 项成就，"
                f"最易 {easier_name(easiest)}={easiest['percent']}%，"
                f"最难 {easier_name(hardest)}={hardest['percent']}%"
            )

    print("=" * 62)
    print("3) 名称映射：社区成就页 vs 全局完成率（均免 key，按位对齐）")
    for appid, cn in SMOKE_GAMES.items():
        rows = fetch_community_achievements(appid)
        api = globals_by_appid[appid]
        page_pct = [r["percent"] for r in rows]
        api_pct = [float(a["percent"]) for a in api]
        print(
            f"  [{appid}] {cn}：社区页 {len(rows)} 项 / 全局接口 {len(api)} 项，"
            f"条数一致={len(rows) == len(api)}，顺序一致={page_pct == api_pct}"
        )
        if rows and api:
            print(
                f"      样例映射 {api[0]['name']} -> {rows[0]['display_name']}"
                f"（{rows[0]['percent']}%）"
            )


if __name__ == "__main__":
    smoke_test()
