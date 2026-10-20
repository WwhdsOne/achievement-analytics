"""按「Steam 官方类型 × 发售年份」统计游戏数量，并附该类型最具代表性游戏的头图链接。

输出（3 列 + 每年 1 列，年份列名为纯年份，全表不含英文）：
    代表游戏名 | 游戏类型 | 图片链接 | 2014 | 2015 | ... | 2025

口径（只读库，不写库）：
  · 类型   = steam_appdetails.valve_genres，仅统计 type='game'；
             表内输出中文类型名（见 GENRE_ZH），内部排序仍用英文原名
  · 年份   = steam_appdetails.release_date 的年份，区间见 YEAR_START / YEAR_END
  · 数值   = **累计口径**：第 N 列 = 该类型在 YEAR_START..N 各年数量之和
             （所以列单调递增，最后一列即 2014 起的总量）
  · 游戏名 = 只保留中文名；无译名时退回英文原名（见 ZH_OVERRIDE）
  · 图片   = Steam 推荐数最高的那款游戏（同分用 SteamSpy 拥有量中值）的商店头图
             （库里没有图片字段，链接按 appid 拼官方 CDN，无需调 API）

运行：uv run python "result/YJH/第三版/genre_year_table.py"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# 脚本躺在 result/<缩写>/ 下，不在包内，需把项目根加进 sys.path 才能 import cleaning
ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()
)
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- 产物路径
OUT_DIR = Path(__file__).resolve().parent
OUT_CSV = OUT_DIR / "游戏类型年度分布.csv"

# ---------------------------------------------------------------- 口径参数
YEAR_START = 2014
YEAR_END = 2025  # 库只收「2026 年以前发售」，2025 是完整最后一年（2026 仅 28 款）

# valve_genres 里混着商业模式 / 内容分级 / 软件用途，不是「游戏类型」，剔除
NON_GENRE: frozenset[str] = frozenset({
    "Free To Play", "Early Access",                     # 商业模式 / 发售状态
    "Violent", "Gore", "Sexual Content", "Nudity",      # 内容分级标记
    "Utilities", "Game Development", "Education",       # 非游戏本体
    "Design & Illustration", "Software Training",
    "Video Production", "Accounting",
    "Animation & Modeling", "Web Publishing",
    "Audio Production", "Movie", "Photo Editing",
})

# 类型中文名：取 Steam 商店中文界面「类型」栏的官方译法，表里不留英文
GENRE_ZH: dict[str, str] = {
    "Action": "动作",
    "Adventure": "冒险",
    "Casual": "休闲",
    "Indie": "独立",
    "Massively Multiplayer": "大型多人在线",
    "Racing": "竞速",
    "RPG": "角色扮演",
    "Simulation": "模拟",
    "Sports": "体育",
    "Strategy": "策略",
}

IMAGE_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"

# ---------------------------------------------------------------- 数据查询
DETAIL_SQL = """
select a.appid,
       gm.name_en                                as name_en,
       gm.name_zh                                as name_zh,
       g                                         as genre,
       extract(year from a.release_date)::int     as year,
       a.recommendations                          as recommendations,
       s.owners                                   as owners
from steam_appdetails a
cross join unnest(a.valve_genres) as g
join games gm on gm.appid = a.appid
left join steamspy_games s on s.appid = a.appid
where a.type = 'game'
  and a.release_date is not null
  and extract(year from a.release_date) between :y0 and :y1
"""

_OWNERS_RE = re.compile(r"([\d,]+)\s*\.\.\s*([\d,]+)")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 库里的 name_zh 覆盖率很高（99.6%），但大量值其实就是英文原名（Steam 中文商店
# 对这些游戏没本地化标题，如实测 Rust / Among Us / ARK / Stardew Valley / RDR2
# 五款的商店页标题都是英文，name_zh 因此等于 name_en）。
# 下面按「网查 + 官方简体中文译名」人工补齐这批缺译名的游戏；appid 优先于库值。
ZH_OVERRIDE: dict[int, str] = {
    252490: "腐蚀",                # 百度百科词条名《腐蚀》(Rust)
    945360: "我们之中",            # 百度百科中文名（别名：太空狼人杀）
    1174180: "荒野大镖客：救赎 2",  # 官方简体中文译名
    413150: "星露谷物语",          # 官方简体中文译名
    284160: "车祸模拟器",          # 无官方译名，中文社区通用叫法
    346110: "方舟：生存进化",       # 官方简体中文译名
}


def display_name(appid: int, en: str, zh: str | None) -> str:
    """只输出中文名；确实找不到译名时退回英文原名（保证单元格不为空）。

    中文名优先级：人工覆盖表 > 库内 name_zh（须含汉字且 ≠ 英文名）。
    """
    zh_clean = zh.strip() if isinstance(zh, str) and zh.strip() else None
    if zh_clean is not None and (zh_clean == en.strip() or not _CJK_RE.search(zh_clean)):
        zh_clean = None
    zh_final = ZH_OVERRIDE.get(int(appid)) or zh_clean
    return zh_final or en


def owners_midpoint(raw: str | None) -> float | None:
    """'200,000 .. 500,000' -> 350000.0；解析不了返回 None。"""
    if not raw:
        return None
    m = _OWNERS_RE.search(raw)
    if not m:
        return None
    lo, hi = (int(x.replace(",", "")) for x in m.groups())
    return (lo + hi) / 2


def fetch_detail() -> pd.DataFrame:
    from cleaning.db import get_engine

    with get_engine().connect() as conn:
        df = pd.read_sql(
            text(DETAIL_SQL), conn, params={"y0": YEAR_START, "y1": YEAR_END}
        )
    print(f"明细行数：{len(df):,}（游戏×类型×年份展开）")
    return df


# ---------------------------------------------------------------- 构建表
def build(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df["genre"].isin(NON_GENRE)].copy()
    years = list(range(YEAR_START, YEAR_END + 1))

    # 每类型每年「有多少款游戏」——同一款游戏在同一类型下只算一次
    counts = (
        df.groupby(["genre", "year"])["appid"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(columns=years, fill_value=0)
        .astype(int)
    )

    # 累计口径：每一年的数字 = 该年及此前所有年份之和（列单调递增，末列即总量）
    cum = counts.cumsum(axis=1)

    # 代表性游戏：先按 Steam 官方推荐数（商店评价数）降序，再用拥有量中值破平。
    # 注意：不能单用 SteamSpy owners —— 它按评论估算，对部分 appid 严重失真
    # （实测 'Street Warriors Online' 被记成 10,000,000..20,000,000），会选出垃圾图。
    df["owners_mid"] = df["owners"].map(owners_midpoint)

    out = pd.DataFrame({"游戏类型": cum.index})
    # 年份列：列名就是纯年份，值取累计数
    for y in years:
        out[str(y)] = cum[y].to_numpy()

    # 行序：仍按末年的「单年」数量降序（不随累计口径改变，保持与前版一致），
    # 同值再看累计总量。这样只改数值口径，不扰动行序与代表图分配。
    out["_last"] = counts[YEAR_END].to_numpy()
    out["_total"] = cum[YEAR_END].to_numpy()
    out = out.sort_values(["_last", "_total"], ascending=False).drop(
        columns=["_last"]
    ).reset_index(drop=True)

    # 逐行挑代表图，已用过的 appid 跳过 —— 避免 Indie/Casual 撞同一张图
    ranked = df.sort_values(
        ["recommendations", "owners_mid"], ascending=False, na_position="last"
    )
    cand = {g: sub["appid"].drop_duplicates().tolist() for g, sub in ranked.groupby("genre")}
    meta = df.drop_duplicates("appid").set_index("appid")[["name_en", "name_zh"]]
    used: set[int] = set()
    picked: list[int] = []
    for g in out["游戏类型"]:
        choice = next((a for a in cand.get(g, []) if int(a) not in used), None)
        if choice is None:  # 该类型所有候选都被占了，退回第一顺位
            choice = cand[g][0]
        used.add(int(choice))
        picked.append(int(choice))
    out.insert(1, "图片链接", [IMAGE_URL.format(appid=a) for a in picked])
    out.insert(
        0,
        "代表游戏名",
        [
            display_name(a, m["name_en"], m["name_zh"])
            for a, m in ((a, meta.loc[a]) for a in picked)
        ],
    )

    missing = [g for g, n in zip(out["游戏类型"], out["代表游戏名"]) if not _CJK_RE.search(n)]
    if missing:
        print(f"⚠️ 以下类型仍未找到中文译名（保持英文原名）：{missing}")
    unmapped = [g for g in out["游戏类型"] if g not in GENRE_ZH]
    if unmapped:
        print(f"⚠️ 以下类型缺中文映射：{unmapped}")

    out.attrs["rep_appid"] = dict(zip(out["游戏类型"], picked))
    # 类型名换成中文放最后一步 —— 前面排序与挑代表图的逻辑都依赖英文原名
    out["游戏类型"] = out["游戏类型"].map(lambda g: GENRE_ZH.get(g, g))
    return out.drop(columns=["_total"])


# ---------------------------------------------------------------- 导出
def export(out: pd.DataFrame) -> None:
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    years = [c for c in out.columns if c.isdigit()]
    print(f"\n类型数：{len(out)}  年份列：{len(years)}（{years[0]}–{years[-1]}，累计口径）")
    print(f"\n{'类型':<22}{'2014':>7}{'2025':>8}   代表性游戏")
    for _, r in out.iterrows():
        print(f"{r['游戏类型']:<22}{r[years[0]]:>7}{r[years[-1]]:>8}   {r['代表游戏名']}")

    print(f"\n已写出：{OUT_CSV}")
    print(f"列名：{list(out.columns)}")


def main() -> None:
    export(build(fetch_detail()))


if __name__ == "__main__":
    main()
