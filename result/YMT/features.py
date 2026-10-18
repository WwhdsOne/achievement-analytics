"""YMT 游戏画像聚类：特征抽取（只读查共享库，产出本地快照）。

研究问题
    同样属于某一类型的游戏，它们的**成就完成结构**是否存在不同类型？

本脚本只做一件事
    把「一款游戏」压成一行特征，连同标签明细落成本地缓存，供 ``cluster.py``
    反复聚类出图而不必重查云库。**不做任何聚类、不做任何结论**。

特征口径（固定，改口径必须同步改本 docstring 与 experiments.md）
    成就规模    ``n_ach``（成就条数），建模时取 ``log1p``。
    解锁分布    ``percent`` 的均值 / 中位数 / 25 分位 / 75 分位 / 总体标准差。
    稀有成就    ``percent < 1`` 与 ``percent < 5`` 的成就占比。
    普及成就    ``percent > 50`` 与 ``percent > 80`` 的成就占比。
    游戏类型    仅用于**聚类之后**的描述，不作为聚类输入（理由见下）。
    游玩投入    ``rawg.playtime``，仅 RAWG 子集有值，只在缩帧上做描述性补充。

为什么标签不进聚类输入
    447 个标签直接多热编码会得到 447 维稀疏二值矩阵，方差远大于 10 个
    数值特征，K-Means 的结果会基本由标签决定——那等于把「按类型分组」
    伪装成「按完成结构分组」，正是 ``docs/plan.md`` 明确要避免的。
    因此聚类只用成就侧数值特征，标签在聚类完成后用于解释各簇是什么游戏。

一致性读
    查库走 ``REPEATABLE READ`` + ``SET TRANSACTION READ ONLY``：既保证一次
    一致读（共享库被队友持续写入），也从机制上排除写库的可能。

必须在结论中同时报告的局限
    1. ``percent`` 是**当前时点**的 Steam 全球解锁率，不是历史上任一时刻的值。
    2. 聚的是**游戏的群体完成特征**，不能据此认定玩家分成了哪些人群。
    3. SteamSpy 标签对近年游戏的覆盖率系统性偏低（YJH 已证 2024 年仅
       82% 有标签），因此各簇的**发售年份构成必须一并报告**。

运行::

    uv run python result/YMT/features.py            # 复用缓存
    uv run python result/YMT/features.py --refresh  # 重查云库
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _project_root() -> Path:
    """向上查找含 pyproject.toml 的目录。

    脚本放在 ``result/YMT/`` 下，位置不固定，不能靠写死的 ``parents[n]``
    定位项目根——按标志文件向上找才稳。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("未找到项目根（向上没有 pyproject.toml）")


ROOT = _project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from sqlalchemy import text

from cleaning.db import get_engine

HERE = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "data" / "processed"
FEATURES_PKL = CACHE_DIR / "ymt-features.pkl"
TAGS_PKL = CACHE_DIR / "ymt-tags.pkl"
PERCENT_PKL = CACHE_DIR / "ymt-percent-sample.pkl"
META_JSON = CACHE_DIR / "ymt-features.meta.json"

#: 成就解锁率抽样：取 ``appid % 13 == 0`` 的游戏的全部成就。
#: 用它而不是 ``random()`` 是为了可复现，且按游戏整取——同一个游戏的所有成就
#: 都进来，画出的簇内分布才不会被「每款只抽几条」削平形状。
PERCENT_MOD = 13

#: 建模用的数值特征（顺序即列顺序，cluster.py 直接照此取 X）
FEATURE_COLS = [
    "p_mean", "p_median", "p_p25", "p_p75", "p_std",
    "share_lt1", "share_lt5", "share_gt50", "share_gt80",
]

#: 主建模帧的成就数下限（见 experiments.md「口径」一节）
MIN_ACH = 10

#: 稳健性复跑用的更严下限
MIN_ACH_STRICT = 20


def _sql_features() -> text:
    """逐款游戏的成就侧特征。

    ``percentile_cont`` 是有序集聚合，需在组内排序，比 ``avg`` 慢，
    但 197 万行 / 5 万组在实测中一次查询约十秒量级，可接受。
    """
    return text(
        """
        SELECT a.appid,
               count(*)                                              AS n_ach,
               avg(a.percent)                                        AS p_mean,
               percentile_cont(0.5)  WITHIN GROUP (ORDER BY a.percent) AS p_median,
               percentile_cont(0.25) WITHIN GROUP (ORDER BY a.percent) AS p_p25,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY a.percent) AS p_p75,
               stddev_pop(a.percent)                                 AS p_std,
               avg(CASE WHEN a.percent <  1 THEN 1.0 ELSE 0.0 END)   AS share_lt1,
               avg(CASE WHEN a.percent <  5 THEN 1.0 ELSE 0.0 END)   AS share_lt5,
               avg(CASE WHEN a.percent > 50 THEN 1.0 ELSE 0.0 END)   AS share_gt50,
               avg(CASE WHEN a.percent > 80 THEN 1.0 ELSE 0.0 END)   AS share_gt80
          FROM achievements a
         WHERE a.appid NOT IN (
                   SELECT appid FROM mapping_issues WHERE NOT resolved)
      GROUP BY a.appid
        """
    )


def _sql_context() -> text:
    """建模帧需要但不参与聚类的上下文列：年份、免费标记、评价数、RAWG 时长与评分。

    ``reviews`` 的口径与面板一致：**SteamSpy 的好评 + 差评优先，缺失时回退商店搜索的
    评价数**。两者都缺则为 NULL——排序时排到最后，不当作 0（0 评价与「没有数据」是两回事）。
    ``rawg_playtime`` 只有约 1.2 万款有值，**不用于主模型**，只在 RAWG 子集上做描述性对比。
    """
    return text(
        """
        SELECT d.appid,
               extract(year FROM d.release_date)::int AS year,
               coalesce(d.is_free, false)             AS is_free,
               d.release_date,
               g.name_en,
               g.name_zh,
               CASE WHEN s.positive IS NOT NULL AND s.negative IS NOT NULL
                    THEN s.positive + s.negative
                    ELSE ss.review_count END           AS reviews,
               r.playtime                             AS rawg_playtime,
               r.rating                               AS rawg_rating,
               r.ratings_count                        AS rawg_ratings_count
          FROM steam_appdetails d
          JOIN games g ON g.appid = d.appid
          LEFT JOIN steamspy_games s       ON s.appid = d.appid
          LEFT JOIN store_search_games ss  ON ss.appid = d.appid
          LEFT JOIN rawg_games r           ON r.appid = d.appid
        """
    )


def _sql_tags() -> text:
    """SteamSpy 主题标签明细（与 YJH 的分析口径一致）。

    ``kind='platform'``（Windows / macOS / Linux）不参与，``source='rawg'``
    的标签混有平台功能词，同样不参与。
    """
    return text(
        """
        SELECT appid, tag, votes
          FROM game_tags
         WHERE source = 'steamspy' AND kind = 'theme'
        """
    )


def _sql_percent_sample() -> text:
    """解锁率抽样明细，用于画各簇的真实分布形状。

    分位数只能说明「分散程度」，说明不了「是不是两极分化」——一个双峰分布
    和一个同样四分位距的均匀分布，分位数可以几乎一样。这张图就是为了让
    「两极分化」这类说法有直接的形状证据。
    """
    return text(
        """
        SELECT appid, percent::float8 AS percent
          FROM achievements
         WHERE mod(appid, :mod) = 0
           AND appid NOT IN (
                   SELECT appid FROM mapping_issues WHERE NOT resolved)
        """
    ).bindparams(mod=PERCENT_MOD)


def load(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """读取特征明细；默认复用本地缓存。

    Returns:
        ``(features, tags, meta)``。``features`` 一行一款游戏，
        ``tags`` 是 ``(appid, tag, votes)`` 长表，用于聚类后的描述。
        ``percent`` 抽样另存 ``PERCENT_PKL``，由 :func:`load_percent` 读取。
    """
    if (FEATURES_PKL.exists() and TAGS_PKL.exists()
            and PERCENT_PKL.exists() and not refresh):
        feat = pd.read_pickle(FEATURES_PKL)
        tags = pd.read_pickle(TAGS_PKL)
        if {"n_ach", "year", *FEATURE_COLS} <= set(feat.columns):
            meta = json.loads(META_JSON.read_text("utf-8"))
            meta["cache"] = "hit"
            return feat, tags, meta

    engine = get_engine()
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            ach = pd.read_sql(_sql_features(), conn)
            ctx = pd.read_sql(_sql_context(), conn)
            tags = pd.read_sql(_sql_tags(), conn)
            pct = pd.read_sql(_sql_percent_sample(), conn)
            window = conn.execute(
                text(
                    "SELECT min(fetched_at)::text AS first, max(fetched_at)::text AS last"
                    " FROM ingest_log WHERE source = 'global_ach' AND status = 'ok'"
                )
            ).mappings().first()
            total_ach = conn.execute(text("SELECT count(*) FROM achievements")).scalar()
    engine.dispose()

    feat = ach.merge(ctx, on="appid", how="inner")
    feat["n_ach_log"] = np.log1p(feat["n_ach"])

    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(feat, index=False).values.tobytes())
    digest.update(pd.util.hash_pandas_object(tags, index=False).values.tobytes())
    digest.update(pd.util.hash_pandas_object(pct, index=False).values.tobytes())

    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "games": int(len(feat)),
        "achievement_rows": int(total_ach),
        "tag_rows": int(len(tags)),
        "percent_sample_rows": int(len(pct)),
        "sha256": digest.hexdigest(),
        "global_ach_fetch_window": dict(window) if window else None,
        "registered_version": None,
        "note": (
            "直接只读查共享云库；来源持续被写入，指纹每次重查可能变化。"
            "未写入 dataset_versions（库对本 agent 只读）。"
        ),
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    feat.to_pickle(FEATURES_PKL)
    tags.to_pickle(TAGS_PKL)
    pct.to_pickle(PERCENT_PKL)
    META_JSON.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta["cache"] = "miss"
    return feat, tags, meta


def load_percent() -> pd.DataFrame:
    """解锁率抽样明细（``appid`` + ``percent``），用于画各簇分布形状。"""
    return pd.read_pickle(PERCENT_PKL)


def load_percent_for(appids: list[int]) -> pd.DataFrame:
    """按 appid 精确取成就解锁率（代表游戏用）。

    抽样缓存只覆盖 ``appid % 13 == 0`` 的游戏，选中作代表的 25 款大概率不在其中，
    所以这里单独查一次库。只读、量小（几十款游戏），不落缓存。
    同理：这里只拉指定 appid，**不会**把整张 achievements 表读进来。
    """
    if not appids:
        return pd.DataFrame(columns=["appid", "percent"])
    engine = get_engine()
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            frame = pd.read_sql(
                text(
                    "SELECT appid, percent::float8 AS percent FROM achievements"
                    " WHERE appid = ANY(:ids)"
                ).bindparams(ids=[int(a) for a in appids]),
                conn,
            )
    engine.dispose()
    return frame


def main_frame(feat: pd.DataFrame, min_ach: int = MIN_ACH,
               paid_only: bool = False) -> pd.DataFrame:
    """按口径切出建模帧。抽成函数是为了让 cluster.py 的稳健性复跑复用同一套规则。"""
    out = feat.loc[feat["n_ach"] >= min_ach]
    if paid_only:
        out = out.loc[~out["is_free"]]
    return out.reset_index(drop=True)


def describe(feat: pd.DataFrame, tags: pd.DataFrame, meta: dict) -> None:
    """打印建模帧规模与各特征分布，供开工前定口径。"""
    print(f"指纹           {meta['sha256'][:12]}   (cache={meta['cache']})")
    print(f"含成就游戏数     {len(feat):,}")
    print(f"标签行数         {len(tags):,}")
    print()
    print(f"{'门槛':>10} {'游戏数':>10} {'其中有标签':>12} {'有 RAWG 时长':>14}")
    tagged = set(tags["appid"])
    for floor in (1, 5, 10, 20, 30, 50):
        sub = feat.loc[feat["n_ach"] >= floor]
        print(
            f"{floor:>10} {len(sub):>10,} "
            f"{sub['appid'].isin(tagged).sum():>12,} "
            f"{sub['rawg_playtime'].notna().sum():>14,}"
        )
    print()
    frame = main_frame(feat)
    print(f"主建模帧（achievements ≥ {MIN_ACH}）：{len(frame):,} 款")
    print()
    shown = ["n_ach", *FEATURE_COLS]
    desc = frame[shown].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).T
    desc["zero_share"] = (frame[shown] == 0).mean()
    print(desc.round(3).to_string())
    print()
    print("零值占比最高的特征（决定要不要做 logit 变换）：")
    zeros = (frame[FEATURE_COLS] == 0).mean().sort_values(ascending=False)
    print(zeros.round(3).head(6).to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YMT 特征抽取（只读）")
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，重查云库")
    args = parser.parse_args()

    f, t, m = load(refresh=args.refresh)
    describe(f, t, m)
