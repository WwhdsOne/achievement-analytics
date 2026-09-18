"""crawler.rawg — RAWG 数据采集模块（需 key）

密钥读 `.env` 的 ``RAWG_API_KEY``（不入 git）。文档：https://api.rawg.io/docs/

拿到：``metacritic``（媒体分）、``rating``（RAWG 用户分）、``released``、
``genres``、``tags``、``stores``。

匹配策略（2026-09-15 实测，务必了解）：
- RAWG **不支持按 Steam appid 直接查**，只能按名称搜索
- ``/games/{id}`` 详情里的 ``stores[].url`` 是**空字符串**，拿不到 appid
- 但 ``/games/{id}/stores`` 能拿到 ``url``（如
  ``http://store.steampowered.com/app/374320/``），可解析出 appid
- 因此流程是：**按官方名搜 → 逐个候选查 /stores → appid 一致才算匹配**，
  不做名称模糊匹配（实测搜 "God of War III" 唯一命中是完全无关的游戏）
- 成本上先走 ``search_exact=true`` 精确搜索（官方文档提及、**未实测**），
  命中时只需 1 次 search + 1 次 stores；失败才走宽松搜索兜底。RAWG 按月配额
  计费（免费档 20,000 次/月），匹配一款的请求数是能否放量的硬约束

**搜索词必须先清洗商标符号**：官方名 ``DARK SOULS™ III`` 直接拿去搜，真正的
游戏根本不在结果里（返回的是 ``Dark Fall 3: Lost Souls`` 之类）；去掉 ``™``
后的 ``Dark Souls III`` 第一条就命中。见 ``normalize_for_search``。

tags 质量提醒：RAWG 的 tags 混有 ``Steam Achievements`` /
``Full controller support`` 等**平台功能标签**，还有多语言重复
（``cooperative`` vs ``Co-op``、俄语条目），入库前必须清洗。题材标签与
SteamSpy 高度重叠，RAWG 的独有价值主要是 metacritic 与 rating。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from crawler.config import RAWG_API_KEY
from crawler.http import request_json

logger = logging.getLogger(__name__)

RAWG_BASE = "https://api.rawg.io/api"

# ── 密钥提供者（多 key 池的接入点）────────────────────────
# RAWG 的月配额**绑定 key**，所以多机并行时要从共享的密钥池取用，而不是各机器读
# 自己的 .env。本模块不认识数据库，只暴露一个钩子：调用方（cleaning.worker）把
# set_key_provider 指向 cleaning/rawg_keys.reserve_key 的包装即可。
# 不注入时回落到 config 里的单个 RAWG_API_KEY，单机开发不受影响。
_key_provider: Callable[[], str | None] | None = None


def set_key_provider(provider: Callable[[], str | None] | None) -> None:
    """注入「取一个可用 API key」的回调（返回 None 表示池子已用尽）。"""
    global _key_provider
    _key_provider = provider


def current_key() -> str | None:
    """当前可用的 API key。注入了 provider 就向它要，否则回落到 .env 的单个 key。"""
    if _key_provider is not None:
        return _key_provider()
    return RAWG_API_KEY or None

# /games/{id}/stores 返回的 url 形如 http(s)://store.steampowered.com/app/374320/
_STEAM_STORE_ID = 1
_STEAM_APPID_RE = re.compile(r"store\.steampowered\.com/app/(\d+)")

# 官方名里的商标符号会把 RAWG 搜索打崩，搜索前必须剥掉
_TRADEMARK_RE = re.compile(r"[™®©]")


def _api(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """调 RAWG 接口（自动带上当前可用的 key）。

    key 来自 :func:`current_key`：注入了密钥池 provider 就向池子取（每次请求都会
    消耗一次配额并记账），否则回落到 ``.env`` 里的单个 key。

    Raises:
        EnvironmentError: 密钥池已用尽，或未配置任何 key。
        RuntimeError: 请求重试耗尽。
    """
    key = current_key()
    if not key:
        raise EnvironmentError(
            "RAWG key 不可用：密钥池已用尽（查 rawg_key_status）"
            "或未配置 RAWG_API_KEY（见 .env.example）"
        )
    return request_json(
        f"{RAWG_BASE}/{path.lstrip('/')}",
        {**params, "key": key},
        source="rawg",
    )


def normalize_for_search(name: str) -> str:
    """清洗名称供搜索用：剥掉 ™/®/© 并压缩空白。

    实测（2026-09-15）：``DARK SOULS™ III`` 直接搜，真游戏不在结果里；
    去掉 ``™`` 后第一条即命中。
    """
    return re.sub(r"\s+", " ", _TRADEMARK_RE.sub("", name)).strip()


def search_variants(name: str) -> list[str]:
    """生成搜索候选词：清洗后的原名 + 去掉副标题的短名。

    短名用于对付 ``Sekiro™: Shadows Die Twice - GOTY Edition`` 这类
    带副标题/版本后缀的官方名。
    """
    base = normalize_for_search(name)
    if not base:
        return []
    variants = [base]
    short = base.split(":")[0].strip()
    if short and short != base:
        variants.append(short)
    return variants


def search_games(
    name: str, page_size: int = 5, *, exact: bool = False
) -> list[dict[str, Any]]:
    """按名称搜索 RAWG 游戏（搜索词会先清洗商标符号）。

    RAWG 的搜索很宽松（搜 "Elden Ring" 返回 5864 条），只能当**候选入口**，
    必须再用 appid 校验（见 match_by_appid）。

    Args:
        name: 搜索词，建议用**官方英文名**（中文名往往搜不到）。
        page_size: 返回候选数上限。
        exact: 用 ``search_exact=true`` 只匹配精确词。官方文档「Latest updates」
            提及此参数（**未实测**）；精确匹配能大幅减少假阳性候选，从而省下
            ``/stores`` 校验请求——RAWG 按月配额计费，候选少一个就少一次请求。

    Returns:
        候选列表（含 id / name / slug / released / metacritic / rating 等）。
    """
    clean = normalize_for_search(name)
    params: dict[str, Any] = {"search": clean, "page_size": page_size}
    if exact:
        params["search_exact"] = "true"
    payload = _api("games", params)
    results = payload.get("results") or []
    if not results:
        logger.warning("RAWG 搜不到：%s（exact=%s）", clean, exact)
    return results


def fetch_game_detail(rawg_id: int) -> dict[str, Any]:
    """取 RAWG 游戏详情（含 metacritic / rating / tags）。"""
    return _api(f"games/{rawg_id}", {})


def fetch_stores(rawg_id: int) -> list[dict[str, Any]]:
    """取该游戏在各商店的上架记录（**这里才有可解析的 url**）。"""
    payload = _api(f"games/{rawg_id}/stores", {})
    return payload.get("results") or []


def steam_appid_of(rawg_id: int) -> int | None:
    """从 /games/{id}/stores 解析出该 RAWG 游戏的 Steam appid。

    Returns:
        Steam appid；该游戏没有 Steam 版时返回 None。
    """
    for entry in fetch_stores(rawg_id):
        if entry.get("store_id") != _STEAM_STORE_ID:
            continue
        match = _STEAM_APPID_RE.search(entry.get("url") or "")
        if match:
            return int(match.group(1))
    return None


def match_by_appid(
    appid: int,
    names: list[str],
    page_size: int = 5,
    max_candidates: int = 6,
) -> dict[str, Any] | None:
    """用「名称搜索 + appid 校验」找到 appid 对应的 RAWG 游戏详情。

    依次用 ``names``（建议 [官方英文名, 官方中文名]）的各个搜索变体搜，
    对候选调 ``steam_appid_of`` 比对；**只有 appid 一模一样才算匹配**，
    避免名称搜索的假阳性。

    **成本分两轮**（RAWG 按月配额计费，候选少一个就少一次请求）：
    1. 先走 ``search_exact=true`` 精确搜索 —— 命中时总成本只有
       1 次 search + 1 次 stores
    2. 精确搜不到再走宽松搜索兜底，逐候选校验直到 ``max_candidates``

    Args:
        appid: 目标 Steam appid。
        names: 候选搜索词，按优先级排列。
        page_size: 每个搜索词取多少候选。
        max_candidates: 最多校验多少个候选，防止请求数失控（默认 6，比旧版的 12
            更保守——配额是这条链路的硬约束）。

    Returns:
        匹配到的 RAWG 详情 dict；全部候选都没对上时返回 None。
    """
    seen: set[int] = set()
    checked = 0
    for exact in (True, False):
        for name in names:
            for variant in search_variants(name):
                if checked >= max_candidates:
                    logger.warning(
                        "RAWG 候选数超上限(%d)，可能漏匹配：appid=%s",
                        max_candidates,
                        appid,
                    )
                    return None
                for cand in search_games(variant, page_size=page_size, exact=exact):
                    rawg_id = cand.get("id")
                    if not rawg_id or rawg_id in seen:
                        continue
                    if checked >= max_candidates:
                        logger.warning(
                            "RAWG 候选数超上限(%d)，可能漏匹配：appid=%s",
                            max_candidates,
                            appid,
                        )
                        return None
                    seen.add(rawg_id)
                    checked += 1
                    if steam_appid_of(rawg_id) == appid:
                        logger.info(
                            "RAWG 匹配成功：appid=%s -> rawg_id=%s"
                            "（exact=%s，校验了 %d 个候选）",
                            appid,
                            rawg_id,
                            exact,
                            checked,
                        )
                        return fetch_game_detail(rawg_id)
    logger.warning("RAWG 未能匹配：appid=%s names=%s", appid, names)
    return None


# 平台功能类标签，不属于游戏题材，入库前应剔除
# 注意 RAWG 会混用展示名（"Steam Achievements"）和 slug（"steam-trading-cards"），
# 比对前必须统一小写并把连字符换成空格（2026-09-15 实测踩到）
_PLATFORM_TAG_EXACT = {
    "full controller support",
    "steam cloud",
    "steam trading cards",
    "steam achievements",
}


def split_tags(tags: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """把 RAWG tags 拆成 (题材标签, 平台功能标签)。

    RAWG 把 ``Steam Achievements`` / ``Full controller support`` /
    ``steam-trading-cards`` 这类平台功能也塞进 tags，做题材特征时要分开。

    Returns:
        (theme_tags, platform_tags)，均为标签名列表（保留原始写法）。
    """
    themes: list[str] = []
    platform: list[str] = []
    for t in tags:
        name = (t.get("name") or "").strip()
        if not name:
            continue
        norm = name.lower().replace("-", " ")
        if norm.startswith("steam") or norm in _PLATFORM_TAG_EXACT:
            platform.append(name)
        else:
            themes.append(name)
    return themes, platform
