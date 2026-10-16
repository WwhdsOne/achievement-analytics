"""cleaning.import_hltb — HowLongToBeat 时长分解 CSV 导入（按游戏名匹配）

数据来源是静态 Kaggle 快照 CSV（``all_games_PC.csv``，HLTB 风格：main / extra /
completionist 三类时长 + people_polled 样本量）。CSV **没有 appid**，只能按游戏名
匹配 ``games`` 表后落库到 ``hltb_games``。

匹配策略两级（``match_method`` 记录每行走的是哪级）：

1. ``exact``   —— 规范化（小写、去商标符号、弯引号归一、压空白）后精确相等
2. ``relaxed`` —— 在此基础上再去掉全部标点与冠词，**唯一命中才采用**（多命中
   说明名字有歧义，宁缺勿错）

已知边界（2026-10-15 实测）：games 表只收带 Steam 成就的游戏，CSV 里有大量
前 Steam 时代的老游戏（Dungeon Siege、F1 2002 这类）根本不在库里，名称差异
只贡献约 2% 的未匹配——覆盖不全主要由「无成就 → 不在库」决定，属预期。

用法::

    uv run python -m cleaning.import_hltb --csv data/interim/all_games_PC.csv [--dry-run]

可重复执行：upsert 幂等，重跑会刷新已有行的时长并补进新匹配上的行。
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from cleaning.db import get_engine

logger = logging.getLogger(__name__)

# 时长三列任一非空才值得导入（rating 之类的列不在本表范围）
DURATION_COLS = ("main", "extra", "completionist")

_TRADEMARK_CHARS = ("™", "®", "©")
_QUOTES = {"’": "'", "‘": "'", "“": '"', "”": '"'}
_DASHES = {"–": "-", "—": "-"}
_ARTICLES = re.compile(r"\b(the|a|an)\b")


def normalize(name: str) -> str:
    """精确匹配用的规范化：小写、去商标符号、引号破折号归一、压空白。

    Args:
        name: 原始游戏名。

    Returns:
        规范化后的名字；空串原样返回（调用方自行判空）。
    """
    s = str(name).strip().lower()
    for ch in _TRADEMARK_CHARS:
        s = s.replace(ch, "")
    for src, dst in {**_QUOTES, **_DASHES}.items():
        s = s.replace(src, dst)
    return " ".join(s.split())


def relax(name: str) -> str:
    """放宽匹配用的规范化：normalize 之上再去全部标点与冠词（the/a/an）。

    歧义风险更高（不同游戏可能被压成同一个串），所以 relaxed 级只在
    **唯一命中**时才采用。
    """
    s = normalize(name)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = _ARTICLES.sub(" ", s)
    return " ".join(s.split())


def load_csv(csv_path: Path) -> pd.DataFrame:
    """读 CSV 并聚合成「每个规范化名一行」的待匹配帧。

    CSV 里同名多行（HLTB 上不同游戏重名，或快照本身重复）无法按名区分，
    聚合规则：有时长数据的行优先，再取 people_polled 最大的一行（最主流）。

    Args:
        csv_path: CSV 文件路径。

    Returns:
        列为 name / hltb_id / main / extra / completionist / people_polled / norm，
        只含时长三列任一非空的行，每个 norm 名一行。
    """
    df = pd.read_csv(csv_path).rename(columns={"id": "hltb_id"})
    df = df[df[list(DURATION_COLS)].notna().any(axis=1)].copy()
    df["norm"] = df["name"].map(normalize)
    df = df[df["norm"] != ""]

    df["_has_main"] = df["main"].notna().astype(int)
    df["_pp"] = df["people_polled"].fillna(-1)
    agg = (
        df.sort_values(["_has_main", "_pp"], ascending=False)
        .drop_duplicates(subset="norm", keep="first")
        .drop(columns=["_has_main", "_pp"])
    )
    collapsed = len(df) - len(agg)
    if collapsed:
        logger.info("CSV 同名多行折叠：%d 行 → 取 people_polled 最大的一行", collapsed)
    logger.info("CSV 待匹配行（含时长）：%d", len(agg))
    return agg


def build_indexes(
    games: pd.DataFrame,
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """从 games 表构建 exact / relaxed 两级「规范化名 → appid 列表」索引。

    Args:
        games: 含 appid / name_en 两列的帧。

    Returns:
        (exact_index, relaxed_index) 两个 dict；同名多 appid 时列表长度 > 1。
    """
    exact: dict[str, list[int]] = {}
    relaxed: dict[str, list[int]] = {}
    for appid, name in zip(games["appid"], games["name_en"]):
        if not isinstance(name, str) or not name.strip():
            continue
        n = normalize(name)
        if n:
            exact.setdefault(n, []).append(appid)
        r = relax(name)
        if r:
            relaxed.setdefault(r, []).append(appid)
    return exact, relaxed


def match_rows(
    df: pd.DataFrame, exact: dict[str, list[int]], relaxed: dict[str, list[int]]
) -> pd.DataFrame:
    """两级匹配：exact 全收；relaxed 只在唯一命中时收。

    Args:
        df: ``load_csv`` 的输出。
        exact: 精确匹配索引。
        relaxed: 放宽匹配索引。

    Returns:
        增加 appid / match_method 两列、只保留匹配成功行的帧。
    """
    appids: list[list[int]] = []
    methods: list[str] = []
    for norm in df["norm"]:
        hits = exact.get(norm)
        if hits:
            appids.append(hits)
            methods.append("exact")
            continue
        r = relax(norm)
        hits = relaxed.get(r, [])
        if len(hits) == 1:
            appids.append(hits)
            methods.append("relaxed")
        else:
            appids.append([])
            methods.append("")
    df = df.copy()
    df["appids"] = appids
    df["match_method"] = methods
    return df[df["appids"].map(bool)]


def upsert(engine, rows: pd.DataFrame) -> int:
    """把匹配结果 upsert 进 hltb_games（重跑幂等，刷新时长与 imported_at）。

    一个 CSV 名命中多个 appid 时，每个 appid 各写一行（同名游戏共享时长）。

    Returns:
        实际写入的行数。
    """
    sql = text(
        """
        INSERT INTO hltb_games
            (appid, hltb_id, name, main_hours, extra_hours,
             completionist_hours, people_polled, match_method, imported_at)
        VALUES (:appid, :hltb_id, :name, :main, :extra, :completionist,
                :people_polled, :match_method, now())
        ON CONFLICT (appid) DO UPDATE SET
            hltb_id             = EXCLUDED.hltb_id,
            name                = EXCLUDED.name,
            main_hours          = EXCLUDED.main_hours,
            extra_hours         = EXCLUDED.extra_hours,
            completionist_hours = EXCLUDED.completionist_hours,
            people_polled       = EXCLUDED.people_polled,
            match_method        = EXCLUDED.match_method,
            imported_at         = now()
        """
    )
    params: list[dict] = []
    for _, r in rows.iterrows():
        for appid in r["appids"]:
            params.append(
                {
                    "appid": appid,
                    "hltb_id": none_if_nan(r["hltb_id"]),
                    "name": r["name"],
                    "main": none_if_nan(r["main"]),
                    "extra": none_if_nan(r["extra"]),
                    "completionist": none_if_nan(r["completionist"]),
                    "people_polled": none_if_nan(r["people_polled"]),
                    "match_method": r["match_method"],
                }
            )
    with engine.begin() as conn:
        conn.execute(sql, params)
    return len(params)


def none_if_nan(v):
    """pandas 的 NaN → None，其余原样（便于参数绑定）。"""
    if pd.isna(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def main() -> None:
    """CLI：读 CSV → 匹配 → upsert，打印各级匹配统计。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="HowLongToBeat 时长 CSV 按名导入 hltb_games"
    )
    parser.add_argument(
        "--csv", required=True, type=Path, help="HLTB 风格快照 CSV 路径"
    )
    parser.add_argument("--dry-run", action="store_true", help="只匹配统计，不写库")
    args = parser.parse_args()

    engine = get_engine()
    df = load_csv(args.csv)
    games = pd.read_sql("SELECT appid, name_en FROM games", engine)
    exact, relaxed = build_indexes(games)
    matched = match_rows(df, exact, relaxed)

    n_exact = (matched["match_method"] == "exact").sum()
    n_relaxed = (matched["match_method"] == "relaxed").sum()
    n_multi = matched["appids"].map(len).gt(1).sum()
    print(
        f"匹配成功 {len(matched)} / {len(df)}（exact={n_exact}, relaxed={n_relaxed}）"
    )
    print(f"一个名字对应多个 appid 的行数: {n_multi}（每个 appid 各写一行）")
    print(f"upsert 参数行数（= 写入行数）: {matched['appids'].map(len).sum()}")

    if args.dry_run:
        print("dry-run：未写库")
        return
    written = upsert(engine, matched)
    print(f"✓ 已写入 hltb_games {written} 行")


if __name__ == "__main__":
    main()
