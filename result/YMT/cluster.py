"""YMT 游戏画像聚类：两遍 K-Means + 事后解释（只读，输入来自 features.py 的缓存）。

研究问题
    同样属于某一类型的游戏，它们的**成就完成结构**是否存在不同类型？

为什么要聚类两遍
    第一遍用全部 10 维特征，结果发现三簇几乎完全沿「解锁率高低」排开，
    也就是说**第一主成分就是难度水平**——k=3 切出来的是难度档位，不是结构
    类型。这本身是一个结果（见 experiments.md「第一遍」），但它回答不了
    「同类游戏是否有不同结构」。
    因此第二遍先把难度水平回归掉（对 p_mean 取残差），只留**形状**特征：
    离散度、四分位距、偏斜、稀有/普及成就占比、成就规模。这样问的是
    「平均解锁率相同的两款游戏，成就是均匀分布还是一头沉」。

第一遍（难度档）特征
    ``n_ach_log`` + 5 个分布统计量 + 4 个占比（见 ``features.FEATURE_COLS``）。

第二遍（结构型）特征
    ``p_std``、``iqr = p75 - p25``、``skew = (mean - median) / (std + 1)``、
    4 个占比，以上全部对 ``p_mean`` 取残差；再加不取残差的 ``n_ach_log``。

两遍共同的流程
    占比类特征在 ``logit`` 方案下先做 Jeffreys 平滑再取 logit；标准化后
    K-Means 扫 k = 3…12，用轮廓系数（1 万点固定种子采样）与最小簇占比
    ≥ 2% 共同选 k。标签**不进聚类输入**，只用于聚类后解释各簇是什么游戏。
    稳健性用「成就数 ≥ 20」与「仅付费游戏」两套口径复跑，看调整兰德指数。

必须在结论中同时报告的局限
    1. 聚的是**游戏的群体完成特征**，不能据此认定玩家分成了哪些人群。
    2. ``percent`` 是当前时点的全球解锁率，不是历史值。
    3. 类名是**看过各簇真实均值之后归纳的**，不是事先设定的假设。
    4. SteamSpy 标签对近年游戏覆盖率偏低，各簇年份构成必须一并报告。

运行::

    uv run python result/YMT/cluster.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("未找到项目根（向上没有 pyproject.toml）")


ROOT = _project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from result.YMT import features as F

HERE = Path(__file__).resolve().parent
FIG_DIR = HERE / "figures"
REPORT_JSON = HERE / "cluster-report.json"

SEED = 42
K_MIN, K_MAX = 3, 12
MIN_CLUSTER_SHARE = 0.01
"""最小簇门槛：占全帧 1%（主帧约 400 款）。

用百分比而不是固定条数，是为了让门槛随帧规模伸缩；但门槛不能定太严——
最初写的是 2%，结果把第二遍的 k=5 挡掉了（它的最小簇 1.9%），而 k=5 的
轮廓系数本来就高于 k=4。**纯按轮廓系数选，k=5 才是更优解**；2% 这个门槛
是我自己加的，放宽到 1% 后由数据自己选。
"""
SIL_SAMPLE = 10_000
SCATTER_MAX = 12_000

BG = "#f7f8fa"
INK = "#262d35"
MUTED = "#5c6470"
PALETTE = [
    "#3b6ea5", "#c96a4a", "#5f9e6e", "#a174b5", "#d0a03c",
    "#4aa3a3", "#b5566f", "#7b8b4a", "#8a6fb0", "#c47f3a",
    "#5a7d9a", "#9a7b5a",
]

SHARE_COLS = ["share_lt1", "share_lt5", "share_gt50", "share_gt80"]
DIST_COLS = ["p_mean", "p_median", "p_p25", "p_p75", "p_std"]
PROFILE_COLS = ["成就数中位", "均值解锁率", "中位解锁率", "标准差",
                "稀有<1%", "稀有<5%", "普及>50%", "普及>80%"]

#: 类名在看过各簇真实均值之后归纳（见 experiments.md「结果」与 report.md）。
#: key 是 KMeans 的簇编号——``random_state`` 固定，同一份输入上可复现。
#: 这些名字**不是事先设定的假设**：换数据、换 k 都可能不成立。
NAMES_TIER: dict[int, str] = {
    0: "大多好拿",
    1: "中等",
    2: "大多难拿",
}
NAMES_SHAPE: dict[int, str] = {
    0: "正常型",
    1: "好玩但入坑难型",
    2: "入门劝退型",
    3: "两极分化型",
    4: "玩家友好型",
}
"""类名：用「这一簇的游戏对玩家是什么体验」来命名。

命名迭代过三次：
    1. 形态学叫法（宽幅铺开型 / 中段收敛型 / …）——准确但不像人话；
    2. 描述分布形状的人话（越玩越难 / 难度都差不多 / …）——好懂，但仍在说分布；
    3. **现在这套**（正常型 / 入门劝退型 / 玩家友好型 / …）——直接说玩家体验。

技术叫法保留在 ``FORMAL_SHAPE``；报告与页面各有一张「名词对照」，包含前两代叫法。

⚠️ 一点必须随结果一起报告：「好玩但入坑难型」并不是**难度最高**的一簇——
它的 `稀有<1%` 只有 0.4%，是五类里最低的，也没有极端稀有的成就。
说它「入坑难」，依据是成就解锁率普遍卡在 20% 上下、多数买家只拿到一小部分，
而不是「有一批几乎拿不到的成就」；真正靠硬指标支撑的是
「入门劝退型」（55.9% 的成就解锁率不足 1%）。
"""

FORMAL_SHAPE: dict[int, str] = {
    0: "宽幅铺开型",
    1: "中段收敛型",
    2: "极稀有型",
    3: "双峰分化型",
    4: "近乎全普及型",
}
"""聚类结果的技术叫法，仅供对照，不作为展示名。"""


def pick_font() -> str:
    """选一个能显示中文的字体，避免中文标题渲染成方块。"""
    names = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in (
        "Microsoft YaHei", "SimHei", "PingFang SC",
        "Noto Sans CJK SC", "Arial Unicode MS", "DejaVu Sans",
    ):
        if candidate in names:
            return candidate
    return "DejaVu Sans"


def style_axis(ax: plt.Axes) -> None:
    """沿用项目既有汇报风格：中性底色、无边框、细刻度。"""
    ax.set_facecolor(BG)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0, labelsize=11, colors=MUTED)
    ax.set_axisbelow(True)


def jeffreys_logit(share: pd.Series, n: pd.Series) -> np.ndarray:
    """把「k 次命中 / n 次机会」的占比映射到实数轴，零与一不再是奇点。

    用 Jeffreys 先验各加 0.5 次虚拟观测再取 logit：占比恒为 0 的游戏得到
    有限负值而非 -inf，且「10 个成就里 0 个稀有」与「200 个成就里 0 个稀有」
    会被区分开——这正是直接标准化丢掉的信息。
    """
    k = np.rint(share.to_numpy() * n.to_numpy())
    n_arr = n.to_numpy()
    return np.log((k + 0.5) / (n_arr - k + 0.5))


def add_shape_cols(frame: pd.DataFrame) -> pd.DataFrame:
    """补上形状特征：四分位距与偏斜（都不随难度水平整体平移）。"""
    out = frame.copy()
    out["iqr"] = out["p_p75"] - out["p_p25"]
    out["skew"] = (out["p_mean"] - out["p_median"]) / (out["p_std"] + 1.0)
    return out


def _share_block(frame: pd.DataFrame, scheme: str) -> dict[str, np.ndarray]:
    return {
        c: (frame[c].to_numpy() if scheme == "raw"
            else jeffreys_logit(frame[c], frame["n_ach"]))
        for c in SHARE_COLS
    }


def build_full(frame: pd.DataFrame, scheme: str) -> tuple[np.ndarray, list[str]]:
    """第一遍的特征矩阵：难度水平 + 形状，全都在里面。"""
    cols: dict[str, np.ndarray] = {"n_ach_log": np.log1p(frame["n_ach"].to_numpy())}
    for c in DIST_COLS:
        cols[c] = frame[c].to_numpy()
    cols.update(_share_block(frame, scheme))
    return StandardScaler().fit_transform(np.column_stack(list(cols.values()))), list(cols)


def build_shape(frame: pd.DataFrame, scheme: str) -> tuple[np.ndarray, list[str]]:
    """第二遍的特征矩阵：把难度水平回归掉，只留形状。

    对 ``p_mean`` 做一元线性回归取残差。这样「平均解锁率 30%」的游戏无论
    落在均值高还是低的一端，都只按「分布形状是否一头沉」来分。
    """
    shaped = add_shape_cols(frame)
    level = StandardScaler().fit_transform(
        frame["p_mean"].to_numpy().reshape(-1, 1)
    ).ravel()

    cols: dict[str, np.ndarray] = {}
    for c in ["p_std", "iqr", "skew", *SHARE_COLS]:
        y = (shaped[c].to_numpy() if c not in SHARE_COLS
             else _share_block(shaped, scheme)[c])
        beta = np.polyfit(level, y, 1)
        cols[f"{c}_残差"] = y - np.polyval(beta, level)
    # 成就规模与难度水平无必然关系，不取残差，保留原尺度
    cols["n_ach_log"] = np.log1p(frame["n_ach"].to_numpy())
    return StandardScaler().fit_transform(np.column_stack(list(cols.values()))), list(cols)


def scan_k(X: np.ndarray, k_min: int = K_MIN, k_max: int = K_MAX) -> pd.DataFrame:
    """扫 k，记录惯性、轮廓系数与最小簇占比。"""
    rows = []
    for k in range(k_min, k_max + 1):
        model = KMeans(n_clusters=k, n_init=10, random_state=SEED)
        labels = model.fit_predict(X)
        sizes = np.bincount(labels, minlength=k)
        rows.append({
            "k": k,
            "inertia": model.inertia_,
            "silhouette": silhouette_score(
                X, labels, sample_size=SIL_SAMPLE, random_state=SEED
            ),
            "min_cluster_share": sizes.min() / len(labels),
        })
    return pd.DataFrame(rows)


def choose_k(scan: pd.DataFrame) -> int:
    """在「每簇不低于全帧 1%」的约束下取轮廓系数最高的 k。

    加最小簇占比约束是为了避免出现几十款游戏一簇、解释时说不出话的情况。
    """
    ok = scan.loc[scan["min_cluster_share"] >= MIN_CLUSTER_SHARE]
    if ok.empty:
        ok = scan
    return int(ok.loc[ok["silhouette"].idxmax(), "k"])


def fit(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """K-Means，返回 (标签, 到各簇中心的距离矩阵)。"""
    model = KMeans(n_clusters=k, n_init=10, random_state=SEED)
    labels = model.fit_predict(X)
    return labels, model.transform(X)


def profile(frame: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
    """各簇的原始均值画像（不标准化，直接可读）。"""
    tmp = frame.assign(cluster=labels)
    out = tmp.groupby("cluster").agg(**{
        "游戏数": ("appid", "size"),
        "成就数中位": ("n_ach", "median"),
        "均值解锁率": ("p_mean", "mean"),
        "中位解锁率": ("p_median", "mean"),
        "标准差": ("p_std", "mean"),
        "稀有<1%": ("share_lt1", "mean"),
        "稀有<5%": ("share_lt5", "mean"),
        "普及>50%": ("share_gt50", "mean"),
        "普及>80%": ("share_gt80", "mean"),
        # 簇内离散度：p90 远高于均值说明这一簇内部还有两极，是「混合簇」的信号
        "普及p90": ("share_gt80", lambda s: s.quantile(0.9)),
        "稀有p90": ("share_lt1", lambda s: s.quantile(0.9)),
        "付费占比": ("is_free", lambda s: 1 - s.mean()),
        "发售年中位": ("year", "median"),
        "四分位距": ("iqr", "mean") if "iqr" in tmp else ("p_std", "mean"),
    })
    out.insert(1, "占比", out["游戏数"] / len(tmp))
    return out


def tag_lift(frame: pd.DataFrame, tags: pd.DataFrame, labels: np.ndarray,
             top: int = 6, min_support: int = 20) -> dict[int, list]:
    """各簇「标签富集度」= 簇内出现率 ÷ 全帧出现率。

    只在样本量 ≥ ``min_support`` 的簇上算，避免小簇被单个标签带偏。
    """
    belong = pd.Series(labels, index=frame["appid"].to_numpy())
    tagged = tags.loc[tags["appid"].isin(belong.index)]
    base = tagged.groupby("tag")["appid"].nunique() / belong.size
    merged = tagged.assign(cluster=tagged["appid"].map(belong))
    out: dict[int, list] = {}
    for cid in sorted(belong.unique()):
        n = int((belong == cid).sum())
        if n < min_support:
            continue
        rate = merged.loc[merged["cluster"] == cid].groupby("tag")["appid"].nunique() / n
        lift = (rate / base.reindex(rate.index)).replace([np.inf], np.nan).dropna()
        keep = rate[rate >= 0.05].index
        picked = lift[keep].sort_values(ascending=False).head(top)
        out[int(cid)] = [(t, round(float(lift[t]), 2), round(float(rate[t]), 3))
                         for t in picked.index]
    return out


def representatives(frame: pd.DataFrame, labels: np.ndarray, X: np.ndarray,
                    names: pd.DataFrame, top: int = 5,
                    mode: str = "popular") -> dict[int, list[dict]]:
    """每簇挑 ``top`` 款代表游戏。

    ``mode="popular"``（默认）：按**评价数**取该簇最热门的几款。评价数口径与面板一致——
    SteamSpy 好评+差评优先，缺失回退商店搜索评价数；两者都缺的排到最后，
    **不当作 0**（0 评价与「没有数据」是两回事）。热门游戏读者认得，展示效果更好。

    ``mode="typical"``：簇内先跑 ``top`` 类小 KMeans 找子形态，每个子形态取最靠近其中心的
    一款。看的是「这一簇的形态」而不是「这一簇最有名的」。
    ⚠️ 两种模式都不要退回「离簇心最近」：对双峰簇，簇心落在两峰之间的稀疏谷底，
    离它最近的是没有形状信号的中间游戏，会把「要么很容易」那一半整个漏掉。
    """
    picks: dict[int, list[dict]] = {}
    lab = names.set_index("appid").to_dict("index")
    appids = frame["appid"].to_numpy()   # 行位置 → appid，两者不是一回事
    reviews = (frame["reviews"].to_numpy() if "reviews" in frame.columns
               else np.full(len(frame), np.nan))

    def one(pos: int) -> dict:
        appid = int(appids[pos])
        r = frame.iloc[pos]
        meta = lab.get(int(appid), {})
        # ⚠️ 中文名缺失时是 NaN，而 NaN 是「真值」——直接 or 会得到字符串 "nan"。
        zh, en = meta.get("name_zh"), meta.get("name_en")
        nm = zh if pd.notna(zh) else (en if pd.notna(en) else str(appid))
        rv = reviews[pos]
        return {
            "appid": int(appid),
            "name": str(nm),
            "n_ach": int(r.n_ach),
            "p_mean": round(float(r.p_mean), 2),
            "p_median": round(float(r.p_median), 2),
            "reviews": int(rv) if pd.notna(rv) else None,
        }

    for cid in sorted(np.unique(labels)):
        idx = np.where(labels == cid)[0]

        if mode == "popular":
            # 无评价数的排最后（-1 参与排序），同评价数按 appid 保证可复现
            order = sorted(
                idx,
                key=lambda i: (-(reviews[i] if pd.notna(reviews[i]) else -1),
                               int(appids[i])),
            )
            picks[int(cid)] = [one(int(i)) for i in order[:top]]
            continue

        Xc = X[idx]
        m = min(top, len(idx))
        sub = KMeans(n_clusters=m, n_init=10, random_state=SEED).fit(Xc)
        dist = sub.transform(Xc)
        sizes = np.bincount(sub.labels_, minlength=m)
        chosen: list[int] = []
        # 大子形态优先，让列表开头是这一簇的主流样子
        for j in np.argsort(-sizes):
            cand = int(idx[dist[:, j].argmin()])
            if cand not in chosen:
                chosen.append(cand)
        for i in idx:                       # 极端情况下补位
            if len(chosen) >= m:
                break
            if int(i) not in chosen:
                chosen.append(int(i))
        picks[int(cid)] = [one(a) for a in chosen[:m]]
    return picks


def plot_representatives(reps: dict[int, list[dict]], sizes: dict[int, int],
                         pct: pd.DataFrame, path: Path) -> None:
    """每簇 5 款最热门的游戏，每格画**这款游戏自己**的解锁率分布。

    热门 = 该簇内评价数最高的 5 款（口径见 :func:`representatives`）。
    这样挑是为了好认：写报告或讲 PPT 时，「原神」「星露谷」这类名字比一串陌生小游戏有说服力。

    代价也要说清：热门游戏不一定是这一簇形态上最典型的，双峰簇按热门挑可能只落在其中一头。
    想看形态代表性用 ``mode="typical"``。格子里的曲线是这一款游戏的全部成就，
    与 ``shape-density.png``（簇内等权平均）互为对照。
    """
    order = sorted(reps.keys())
    edges = np.linspace(0, 100, 21)
    centers = (edges[:-1] + edges[1:]) / 2

    fig = plt.figure(figsize=(14.2, 13.2), facecolor=BG)
    gs = fig.add_gridspec(
        len(order), 5, left=0.125, right=0.985, top=0.875, bottom=0.045,
        wspace=0.22, hspace=0.85,
    )

    for i, cid in enumerate(order):
        color = PALETTE[int(cid) % len(PALETTE)]
        axes = []
        for j, g in enumerate(reps[cid][:5]):
            ax = fig.add_subplot(gs[i, j])
            style_axis(ax)
            vals = pct.loc[pct["appid"] == g["appid"], "percent"]
            if len(vals):
                hist, _ = np.histogram(vals, bins=edges, density=True)
                ax.fill_between(centers, hist, color=color, alpha=0.30,
                                step="mid", linewidth=0)
                ax.plot(centers, hist, color=color, linewidth=1.6,
                        drawstyle="steps-mid")
            ax.set_xlim(0, 100)
            ax.set_ylim(bottom=0)
            ax.set_yticks([])
            if i == len(order) - 1:
                ax.set_xticks([0, 50, 100])
                ax.tick_params(labelsize=8.5, colors=MUTED)
            else:
                ax.set_xticks([])

            nm = g["name"]
            ax.set_title(nm if len(nm) <= 26 else nm[:25] + "…",
                         fontsize=9.5, color=INK, pad=4, loc="left")
            rv = g.get("reviews")
            rv_txt = f" · 评价 {rv:,}" if rv else " · 评价数缺失"
            ax.set_xlabel(f"{g['n_ach']} 个成就 · 平均 {g['p_mean']:.1f}%{rv_txt}",
                          fontsize=7.5, color=MUTED, labelpad=2)
            axes.append(ax)

        pos = axes[0].get_position()
        fig.text(0.012, (pos.y0 + pos.y1) / 2,
                 f"{NAMES_SHAPE.get(int(cid), f'簇 {int(cid)}')}\n"
                 f"{sizes.get(int(cid), 0):,} 款",
                 ha="left", va="center", fontsize=13.5, color=color,
                 fontweight="500", linespacing=1.6)

    fig.suptitle("每簇 5 款最热门的游戏：各自真实的成就解锁率分布",
                 fontsize=16, color=INK, x=0.012, ha="left", y=0.975)
    fig.text(0.012, 0.943,
             "热门 = 该簇内评价数最高的 5 款（SteamSpy 好评+差评，缺失时回退商店搜索评价数）。"
             "横轴为成就解锁率 0–100%，纵轴为成就密度。\n"
             "注意：热门不等于形态最典型——「两极分化型」这一簇按热门挑，可能只落在其中一头。",
             fontsize=9.5, color=MUTED, va="top", linespacing=1.9)
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def plot_scan(scan: pd.DataFrame, chosen: int, title: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 5.4), facecolor=BG)
    style_axis(ax)
    ax.plot(scan["k"], scan["inertia"], color="#3b6ea5", marker="o",
            markersize=5, linewidth=2)
    ax.set_xlabel("聚类数 k", fontsize=12, color=MUTED)
    ax.set_ylabel("簇内平方和（越低越紧）", fontsize=12, color="#3b6ea5")
    ax.set_xticks(scan["k"])

    ax2 = ax.twinx()
    ax2.plot(scan["k"], scan["silhouette"], color="#c96a4a", marker="s",
             markersize=5, linewidth=2)
    ax2.set_ylabel("轮廓系数（越高越分得开）", fontsize=12, color="#c96a4a")
    ax2.tick_params(length=0, labelsize=11, colors="#c96a4a")
    for side in ax2.spines.values():
        side.set_visible(False)

    ax.axvline(chosen, color="#7b8b4a", linestyle="--", linewidth=1.4)
    ax.annotate(f"选定 k = {chosen}", xy=(chosen, ax.get_ylim()[1] * 0.95),
                xytext=(6, 0), textcoords="offset points",
                fontsize=11, color="#5b6b2f")
    ax.set_title(title, fontsize=14, color=INK, pad=12, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def plot_scatter(X: np.ndarray, labels: np.ndarray, k: int, names: dict[int, str],
                 title: str, path: Path) -> list[float]:
    """PCA 二维投影，按簇着色。投影只用于看分得开不开，不参与聚类。"""
    pca = PCA(n_components=2, random_state=SEED)
    coords = pca.fit_transform(X)
    rng = np.random.default_rng(SEED)
    idx = (rng.choice(len(coords), SCATTER_MAX, replace=False)
           if len(coords) > SCATTER_MAX else np.arange(len(coords)))

    fig, ax = plt.subplots(figsize=(9.8, 7.0), facecolor=BG)
    style_axis(ax)
    for cid in sorted(names):
        m = labels[idx] == cid
        ax.scatter(coords[idx][m, 0], coords[idx][m, 1], s=7, alpha=0.42,
                   color=PALETTE[cid % len(PALETTE)], linewidths=0,
                   label=f"{names[cid]}（{np.sum(labels == cid):,} 款）")
    ax.set_xlabel(f"主成分 1（{pca.explained_variance_ratio_[0]*100:.0f}% 方差）",
                  fontsize=12, color=MUTED)
    ax.set_ylabel(f"主成分 2（{pca.explained_variance_ratio_[1]*100:.0f}% 方差）",
                  fontsize=12, color=MUTED)
    ax.set_title(title, fontsize=14, color=INK, pad=12, loc="left")
    ax.legend(fontsize=10, frameon=False, loc="best", markerscale=2.4, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)
    return [round(float(v), 4) for v in pca.explained_variance_ratio_]


def plot_profiles(prof: pd.DataFrame, names: dict[int, str], title: str,
                  path: Path) -> None:
    """各簇画像热力图：格内是簇内真实均值，颜色是相对全帧均值的高低。"""
    raw = prof[PROFILE_COLS].astype(float)
    z = ((raw - raw.mean()) / raw.std(ddof=0)).fillna(0)

    fig, ax = plt.subplots(figsize=(11.2, 1.5 * len(z) + 2.4), facecolor=BG)
    ax.set_facecolor(BG)
    im = ax.imshow(z.to_numpy(), cmap="RdBu_r", vmin=-2.2, vmax=2.2, aspect="auto")
    ax.set_xticks(range(len(PROFILE_COLS)))
    ax.set_xticklabels(PROFILE_COLS, fontsize=10.5, color=INK)
    ax.set_yticks(range(len(z)))
    ax.set_yticklabels(
        [f"{names.get(int(c), f'簇 {int(c)}')}\n{prof.loc[c, '游戏数']:,} 款"
         for c in z.index],
        fontsize=10, color=INK,
    )
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)

    for i, cid in enumerate(z.index):
        for j, col in enumerate(PROFILE_COLS):
            value = raw.loc[cid, col]
            text = (f"{value*100:.0f}%" if col.startswith(("稀有", "普及"))
                    else f"{value:.1f}")
            ax.text(j, i, text, ha="center", va="center", fontsize=9.5,
                    color="white" if abs(z.loc[cid, col]) > 1.3 else INK)
    bar = fig.colorbar(im, ax=ax, fraction=0.022, pad=0.02)
    bar.set_label("相对全帧均值的标准化偏离", fontsize=10, color=MUTED)
    bar.ax.tick_params(labelsize=9, colors=MUTED)
    ax.set_title(title, fontsize=14, color=INK, pad=12, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def plot_unlock(frame: pd.DataFrame, labels: np.ndarray, names: dict[int, str],
                title: str, path: Path) -> None:
    """各簇解锁率的四分位区间：看的是「难度分布形状」，不是平均值高低。"""
    tmp = frame.assign(cluster=labels)
    order = sorted(tmp["cluster"].unique())
    fig, ax = plt.subplots(figsize=(11.0, 5.6), facecolor=BG)
    style_axis(ax)
    for i, cid in enumerate(order):
        sub = tmp.loc[tmp["cluster"] == cid]
        color = PALETTE[cid % len(PALETTE)]
        q1, q2, q3 = (sub["p_p25"].median(), sub["p_median"].median(),
                      sub["p_p75"].median())
        ax.vlines(i, q1, q3, color=color, linewidth=9, alpha=0.35)
        ax.plot([i], [q2], marker="o", markersize=9, color=color)
        ax.annotate(f"{q2:.1f}%", (i, q2), textcoords="offset points",
                    xytext=(11, 0), fontsize=10, color=color, va="center")
        ax.plot([i], [sub["p_mean"].median()], marker="_", markersize=16,
                color=INK, alpha=0.55)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([names.get(int(c), f"簇 {int(c)}") for c in order],
                       fontsize=10.5, color=INK)
    ax.set_ylabel("成就解锁率（%）", fontsize=12, color=MUTED)
    ax.set_title(title, fontsize=13.5, color=INK, pad=12, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def plot_shape_density(frame: pd.DataFrame, labels: np.ndarray, pct: pd.DataFrame,
                       names: dict[int, str], title: str, path: Path) -> None:
    """各簇**真实的解锁率分布形状**：先算每款游戏自己的直方图，再在簇内平均。

    ⚠️ 不能把簇内所有成就直接堆起来画。成就数多的游戏会压倒性地主导合并后
    的分布——实测有一簇按游戏平均是「28% 的成就解锁率过半」，按成就加权却是
    「75% 的成就解锁率过半」，两者讲的是完全不同的故事。这里按游戏等权平均，
    与 ``profile()`` 的「每款游戏算一个样本」口径保持一致。
    """
    belong = pd.Series(labels, index=frame["appid"].to_numpy())
    on_frame = pct.loc[pct["appid"].isin(belong.index)].copy()
    if on_frame.empty:
        return
    bins = np.linspace(0, 100, 41)
    on_frame["bin"] = np.clip(np.digitize(on_frame["percent"], bins) - 1,
                              0, len(bins) - 2)
    per_game = on_frame.groupby(["appid", "bin"]).size().unstack(fill_value=0)
    per_game = per_game.div(per_game.sum(axis=1), axis=0)
    cluster_of_game = belong.reindex(per_game.index)
    density = per_game.groupby(cluster_of_game).mean()

    centers = (bins[:-1] + bins[1:]) / 2
    order = sorted(density.index)
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 6.8), facecolor=BG,
                             sharex=True, sharey=True)
    for ax, cid in zip(axes.ravel(), order):
        style_axis(ax)
        row = density.loc[cid].reindex(range(len(centers)), fill_value=0)
        color = PALETTE[int(cid) % len(PALETTE)]
        ax.bar(centers, row.to_numpy(), width=2.5, color=color, alpha=0.8,
               edgecolor="white", linewidth=0.3)
        n_games = int((cluster_of_game == cid).sum())
        ax.annotate(f"{int(belong.eq(cid).sum()):,} 款游戏\n抽样 {n_games:,} 款",
                    xy=(0.96, 0.92), xycoords="axes fraction", ha="right",
                    va="top", fontsize=10, color=MUTED, linespacing=1.5)
        ax.set_title(names.get(int(cid), f"簇 {int(cid)}"), fontsize=12.5,
                     color=INK, pad=8, loc="left")
    for ax in axes.ravel()[len(order):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("成就解锁率（%）", fontsize=11, color=MUTED)
    for ax in axes[:, 0]:
        ax.set_ylabel("簇内平均占比", fontsize=11, color=MUTED)
    fig.suptitle(title + "（每款游戏等权平均）", fontsize=14, color=INK,
                 x=0.012, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def robustness(rows: list[dict], path: Path) -> None:
    """稳健性：ARI 条形对比（两遍分析 × 两套更严口径）。"""
    fig, ax = plt.subplots(figsize=(11.0, 4.2), facecolor=BG)
    style_axis(ax)
    labels = [r["口径"] for r in rows]
    vals = [r["ari"] for r in rows]
    colors = [PALETTE[0] if r["遍"] == "难度档" else PALETTE[1] for r in rows]
    bars = ax.barh(labels, vals, color=colors, height=0.5)
    for b, v in zip(bars, vals):
        ax.text(min(v + 0.015, 0.84), b.get_y() + b.get_height() / 2, f"{v:.2f}",
                va="center", fontsize=11, color=INK)
    ax.set_xlim(0, 1)
    ax.set_xlabel("与主帧分型的调整兰德指数 ARI（1 = 完全一致，0 = 相当于随机）",
                  fontsize=11, color=MUTED)
    ax.set_title("换口径后分型是否稳定（蓝 = 难度档，橙 = 结构型）",
                 fontsize=13, color=INK, pad=10, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def run_pass(frame: pd.DataFrame, tags: pd.DataFrame, feat_names: pd.DataFrame,
             X: np.ndarray, tag: str, names: dict[int, str],
             fig_prefix: str, pct: pd.DataFrame | None = None,
             force_k: int | None = None) -> dict:
    """跑一遍完整的「扫 k → 选 k → 聚类 → 画像 → 图」，返回该遍的结果。"""
    scan = scan_k(X)
    k = force_k or choose_k(scan)
    best = scan.loc[scan["k"] == k].iloc[0]
    print(f"\n=== {tag} ===  k={k}  轮廓 {best['silhouette']:.4f}  "
          f"最小簇占比 {best['min_cluster_share']:.3f}")
    print(scan.round(4).to_string(index=False))

    labels, dist = fit(X, k)
    prof = profile(frame, labels)
    # 类名在看过画像之后才归纳；归纳前统一退回「簇 n」，保证图先能出。
    eff = {cid: names.get(cid, f"簇 {cid}") for cid in range(k)}
    print("\n各簇画像：")
    print(prof.round(3).to_string())

    lifts = tag_lift(frame, tags, labels)
    reps = representatives(frame, labels, X, feat_names)
    print("\n标签富集（簇内出现率 ÷ 全帧出现率）：")
    for cid, items in lifts.items():
        print(f"  {eff[cid]}: " + "、".join(f"{t}({l:.1f}×)" for t, l, _ in items[:5]))
    print("\n最热门的 5 款（按评价数）：")
    for cid, items in reps.items():
        print(f"  {eff[cid]}: " + "、".join(g["name"] for g in items[:5]))

    plot_scan(scan, k, f"聚类数选择 · {tag}", FIG_DIR / f"{fig_prefix}-k.png")
    var_ratio = plot_scatter(
        X, labels, k, eff,
        f"{tag}：各簇在特征空间的分布（PCA 投影，抽样 1.2 万款）",
        FIG_DIR / f"{fig_prefix}-pca.png")
    plot_profiles(prof, eff, f"{tag}：各簇的成就完成特征画像",
                  FIG_DIR / f"{fig_prefix}-profiles.png")
    plot_unlock(frame, labels, eff,
                f"{tag}：各簇解锁率区间（竖条 = p25–p75，圆点 = 中位，短横 = 均值）",
                FIG_DIR / f"{fig_prefix}-unlock.png")
    if pct is not None:
        plot_shape_density(frame, labels, pct, eff,
                           f"{tag}：各簇真实的解锁率分布形状",
                           FIG_DIR / f"{fig_prefix}-density.png")

    return {
        "标签": tag, "k": k, "轮廓系数": float(best["silhouette"]),
        "扫描": scan.round(4).to_dict("records"),
        "画像": json.loads(prof.round(4).to_json(orient="index", force_ascii=False)),
        "标签富集": {str(c): v for c, v in lifts.items()},
        "代表游戏": {str(c): v for c, v in reps.items()},
        "PCA解释方差": var_ratio,
        "labels": labels,
    }


def ari_vs(main_belong: pd.Series, sub: pd.DataFrame, sub_labels: np.ndarray) -> float:
    """子集重聚的标签与主帧标签在**公共 appid** 上的兰德指数。"""
    sub_appids = sub["appid"].to_numpy()
    common = np.isin(sub_appids, main_belong.index.to_numpy())
    ref = main_belong.reindex(sub_appids).to_numpy()
    return float(adjusted_rand_score(ref[common], sub_labels[common]))


def main() -> None:
    parser = argparse.ArgumentParser(description="YMT 游戏画像聚类（两遍）")
    parser.add_argument("--refresh", action="store_true", help="重查云库再聚类")
    parser.add_argument("--scheme", default="raw", choices=("raw", "logit"),
                        help="占比类特征的变换方式（默认 raw）")
    parser.add_argument("--k-tier", type=int, default=None, help="强制指定第一遍的 k")
    parser.add_argument("--k-shape", type=int, default=None, help="强制指定第二遍的 k")
    args = parser.parse_args()

    plt.rcParams.update({"font.family": pick_font(), "axes.unicode_minus": False})
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    feat, tags, meta = F.load(refresh=args.refresh)
    pct = F.load_percent()
    feat = add_shape_cols(feat)
    frame = F.main_frame(feat)
    names = feat[["appid", "name_en", "name_zh"]]
    print(f"指纹 {meta['sha256'][:12]}（cache={meta['cache']}）")
    print(f"主建模帧 {len(frame):,} 款（成就数 ≥ {F.MIN_ACH}）")

    # ── 第一遍：难度档 ────────────────────────────────────────────────────
    X_full, full_cols = build_full(frame, args.scheme)
    print(f"第一遍特征 {len(full_cols)} 维：{', '.join(full_cols)}")
    res_tier = run_pass(frame, tags, names, X_full, "第一遍 · 难度档",
                        NAMES_TIER, "tier", pct, args.k_tier)

    # ── 第二遍：结构型（难度水平已回归掉）─────────────────────────────────
    X_shape, shape_cols = build_shape(frame, args.scheme)
    print(f"\n第二遍特征 {len(shape_cols)} 维：{', '.join(shape_cols)}")
    res_shape = run_pass(frame, tags, names, X_shape, "第二遍 · 结构型",
                         NAMES_SHAPE, "shape", pct, args.k_shape)

    # ── 每簇 5 款代表游戏（画它们各自的真实分布）───────────────────────────
    # 抽样缓存只覆盖 appid % 13 == 0 的游戏，代表游戏大多不在其中，需精确查库。
    rep_ids = sorted({
        g["appid"] for v in res_shape["代表游戏"].values() for g in v
    })
    pct_rep = F.load_percent_for(rep_ids)
    sizes = {int(c): int(n) for c, n in
             zip(*np.unique(res_shape["labels"], return_counts=True))}
    plot_representatives(res_shape["代表游戏"], sizes, pct_rep,
                         FIG_DIR / "representatives.png")
    print(f"\n代表游戏 {len(rep_ids)} 款，已取到 {pct_rep['appid'].nunique()} 款的成就明细")

    # ── 稳健性：两遍 × 两套更严口径 ───────────────────────────────────────
    robust: list[dict] = []
    for tag, X_builder, k, res in (
        ("难度档", lambda f: build_full(f, args.scheme)[0], res_tier["k"], res_tier),
        ("结构型", lambda f: build_shape(f, args.scheme)[0], res_shape["k"], res_shape),
    ):
        belong = pd.Series(res["labels"], index=frame["appid"].to_numpy())
        for label, sub in (
            (f"成就≥{F.MIN_ACH_STRICT}", F.main_frame(feat, min_ach=F.MIN_ACH_STRICT)),
            ("仅付费游戏", F.main_frame(feat, paid_only=True)),
        ):
            if len(sub) < 500:
                continue
            sub_labels, _ = fit(X_builder(sub), k)
            robust.append({"遍": tag, "口径": f"{tag} · {label}",
                           "游戏数": len(sub), "ari": ari_vs(belong, sub, sub_labels)})
            print(f"\n[{tag} · {label}] {len(sub):,} 款，ARI = {robust[-1]['ari']:.3f}")
    robustness(robust, FIG_DIR / "robustness.png")

    # ── RAWG 时长：只在子集上有值，不参与聚类 ──────────────────────────────
    playtime = {}
    for tag, res in (("难度档", res_tier), ("结构型", res_shape)):
        frame_p = frame.assign(cluster=res["labels"]).dropna(subset=["rawg_playtime"])
        playtime[tag] = json.loads(
            frame_p.groupby("cluster")["rawg_playtime"]
            .agg(["median", "mean", "size"]).round(1)
            .to_json(orient="index", force_ascii=False)
        )
    print("\n各簇 RAWG 时长（小时，仅 RAWG 子集）：")
    print(json.dumps(playtime, ensure_ascii=False, indent=2))

    report = {
        "指纹": meta["sha256"],
        "抽取时间": meta["extracted_at"],
        "主帧": {"门槛": F.MIN_ACH, "游戏数": int(len(frame))},
        "变换": args.scheme,
        "第一遍": {k: v for k, v in res_tier.items() if k != "labels"},
        "第二遍": {k: v for k, v in res_shape.items() if k != "labels"},
        "类别名": {
            "难度档": {str(c): n for c, n in NAMES_TIER.items()},
            "结构型": {str(c): n for c, n in NAMES_SHAPE.items()},
        },
        "稳健性": robust,
        "RAWG时长": playtime,
    }
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✓ 图与报告已写入 {FIG_DIR} 与 {REPORT_JSON.name}")


if __name__ == "__main__":
    main()
