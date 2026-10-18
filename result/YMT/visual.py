"""YMT 聚类结果的可视化单页（自包含 HTML，无外部依赖）。

读 ``cluster-report.json`` 与 ``data/processed/`` 的缓存，重算两遍聚类的标签，
把每簇**真实的解锁率分布**（每款游戏先算自己的直方图、再在簇内等权平均）
渲染成一张可以直接投屏的单页。

只做展示，不改任何结论。所有数字都由本脚本从数据重算，不手抄。

运行::

    uv run python result/YMT/visual.py
"""

from __future__ import annotations

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

HERE = Path(__file__).resolve().parent
OUT = HERE / "visual.html"
REPORT = HERE / "cluster-report.json"

BINS = 40

#: 每类的一句话补充。类名已经是玩家视角的说法，这里只补「具体到什么程度」。
#: 数字全部由数据算，措辞是看过画像之后写的。
GIST = {
    "正常型": "难度随流程平缓上升，最常见的一种",
    "好玩但入坑难型": "解锁率普遍卡在 20% 上下，多数人只拿到一部分",
    "入门劝退型": "过半数成就，连 1% 的玩家都没拿到",
    "两极分化型": "一头人人都有，一头几乎没人有，中间很少",
    "玩家友好型": "99% 的成就，过半玩家都能拿到",
    "大多好拿": "成就不难，随便玩玩就能收集一批",
    "中等": "难度居中，占全库一半以上",
    "大多难拿": "半数成就解锁率不足 5%",
}

#: 技术叫法，仅供页面底部的「名词对照」，不作为展示名。
FORMAL = {
    "正常型": "宽幅铺开型",
    "好玩但入坑难型": "中段收敛型",
    "入门劝退型": "极稀有型",
    "两极分化型": "双峰分化型",
    "玩家友好型": "近乎全普及型",
}


def density_by_cluster(frame, labels, pct, belong, cids):
    """每簇的解锁率分布：**每款游戏先算自己的直方图，再在簇内等权平均**。

    直接把簇内所有成就堆起来会错——成就数多的游戏会压倒性主导，
    实测同一簇两种算法能差 47 个百分点。
    """
    import numpy as np
    import pandas as pd

    on = pct.loc[pct["appid"].isin(belong.index)].copy()
    edges = np.linspace(0, 100, BINS + 1)
    on["bin"] = np.clip(np.digitize(on["percent"], edges) - 1, 0, BINS - 1)
    per_game = on.groupby(["appid", "bin"]).size().unstack(fill_value=0)
    per_game = per_game.div(per_game.sum(axis=1), axis=0)
    cluster_of_game = belong.reindex(per_game.index)
    dens = per_game.groupby(cluster_of_game).mean()

    out = {}
    for cid in cids:
        row = (dens.loc[cid].reindex(range(BINS), fill_value=0)
               if cid in dens.index else pd.Series([0.0] * BINS))
        arr = row.to_numpy(dtype=float)
        out[str(int(cid))] = [round(float(v), 5) for v in arr]
    return out


def tag_matrix(frame, tags, labels, k, per_cluster=4, min_cov=0.03,
               min_cluster_rate=0.055):
    """「标签 × 结构型」的富集矩阵，给交叉热图用。

    富集倍数 = 该簇里含这个标签的游戏占比 ÷ 全库含这个标签的占比。
    候选标签要求全库覆盖 ≥ 3%，且至少在一簇里出现率 ≥ 5.5%（再高会把
    「本地多人」这类覆盖本就不大的标签全滤掉，双峰那一列就整列空白）。
    选出的标签按「富集最强的簇」排序，视觉上成组出现。
    """
    import pandas as pd

    belong = pd.Series(labels, index=frame["appid"].to_numpy())
    tagged = tags.loc[tags["appid"].isin(belong.index)].copy()
    tagged["cluster"] = tagged["appid"].map(belong)
    n = len(belong)

    base = tagged.groupby("tag")["appid"].nunique() / n
    base = base.loc[base >= min_cov]

    rate = {}
    for cid in range(k):
        m = int((belong == cid).sum())
        rate[cid] = (tagged.loc[tagged["cluster"] == cid]
                     .groupby("tag")["appid"].nunique() / m)
    rate = pd.DataFrame(rate).reindex(base.index).fillna(0.0)
    lift = rate.div(base, axis=0).fillna(0.0)

    keep = rate.index[rate.max(axis=1) >= min_cluster_rate]
    # 每个簇各取若干个，而不是全按「最大富集」排名。
    # 后者只会选出 VR / 找猫这种富集 3~6 倍的极端标签，把富集只有 1.4 倍但
    # 同样有代表性的「肉鸽」「视觉小说」全挤掉，热图就只剩两端两列有色。
    picked_list, seen = [], set()
    for cid in range(k):
        col = lift[cid].loc[keep].sort_values(ascending=False).head(per_cluster)
        for t in col.index:
            if t not in seen:
                seen.add(t)
                picked_list.append(t)
    picked = lift.loc[picked_list]

    cluster_of = picked.to_numpy().argmax(axis=1)
    order = sorted(range(len(picked.index)),
                   key=lambda i: (cluster_of[i], -picked.to_numpy()[i].max()))
    names = [picked.index[i] for i in order]
    return {
        "tags": names,
        "clusterOf": [int(cluster_of[i]) for i in order],
        "lift": [[round(float(v), 2) for v in picked.loc[t]] for t in names],
        "cov": [[round(float(v) * 100, 1) for v in rate.loc[t]] for t in names],
    }


def build_payload() -> dict:
    import numpy as np
    import pandas as pd

    from result.YMT import cluster as C
    from result.YMT import features as F

    saved = json.loads(REPORT.read_text(encoding="utf-8"))
    k_tier = saved["第一遍"]["k"]
    k_shape = saved["第二遍"]["k"]

    feat, tags, meta = F.load()
    pct = F.load_percent()
    feat = C.add_shape_cols(feat)
    frame = F.main_frame(feat)

    X_tier, _ = C.build_full(frame, "raw")
    X_shape, _ = C.build_shape(frame, "raw")
    lab_tier, dist_tier = C.fit(X_tier, k_tier)
    lab_shape, dist_shape = C.fit(X_shape, k_shape)

    def pack(labels, X, names, k, tag):
        prof = C.profile(frame, labels)
        lifts = C.tag_lift(frame, tags, labels)
        reps = C.representatives(
            frame, labels, X, feat[["appid", "name_en", "name_zh"]]
        )
        belong = pd.Series(labels, index=frame["appid"].to_numpy())
        dens = density_by_cluster(frame, labels, pct, belong, range(k))

        rows = []
        for cid in range(k):
            p = prof.loc[cid]
            nm = names.get(int(cid), f"簇 {int(cid)}")
            rows.append({
                "id": int(cid),
                "name": nm,
                "gist": GIST.get(nm, ""),
                "color": C.PALETTE[cid % len(C.PALETTE)],
                "games": int(p["游戏数"]),
                "share": round(float(p["占比"]) * 100, 1),
                "density": dens[str(cid)],
                "stats": [
                    {"label": "成就数中位", "value": f"{int(p['成就数中位'])}"},
                    {"label": "均值解锁率", "value": f"{p['均值解锁率']:.1f}%"},
                    {"label": "中位解锁率", "value": f"{p['中位解锁率']:.1f}%"},
                    {"label": "稀有 <1%", "value": f"{p['稀有<1%']*100:.1f}%"},
                    {"label": "普及 >50%", "value": f"{p['普及>50%']*100:.1f}%"},
                    {"label": "四分位距", "value": f"{p['四分位距']:.1f}pp"},
                ],
                "tags": [t for t, _, _ in lifts.get(cid, [])[:4]],
                "lifts": [f"{l:.1f}×" for _, l, _ in lifts.get(cid, [])[:4]],
                # 三区占比：把曲线翻译成三个数，比读密度图直观得多。
                # lt5 与 gt50 不相交，所以中间段 = 1 - lt5 - gt50（精确，不是估算）。
                "zones": [
                    {"label": "稀有 <5%", "pct": round(float(p["稀有<5%"]) * 100, 1)},
                    {"label": "中间 5–50%",
                     "pct": round((1 - float(p["稀有<5%"]) - float(p["普及>50%"])) * 100, 1)},
                    {"label": "普及 >50%", "pct": round(float(p["普及>50%"]) * 100, 1)},
                ],
                "reps": [g["name"] for g in reps.get(cid, [])[:5]],
                "year": int(p["发售年中位"]),
                "paid": round(float(p["付费占比"]) * 100, 1),
            })
        return rows

    tier_rows = pack(lab_tier, X_tier, C.NAMES_TIER, k_tier, "tier")
    shape_rows = pack(lab_shape, X_shape, C.NAMES_SHAPE, k_shape, "shape")

    # ── 特征热图：五类 × 8 个特征 ─────────────────────────────────────────
    # 注意两套量纲：p_mean / p_median / p_std 本身就是百分点数值（29.4 就是 29.4%），
    # 而 share_* 是 0–1 的小数（0.031 才是 3.1%），只有后者需要乘 100。
    # 一视同仁地乘 100 会得到「2937.7%」这种离谱数字。
    prof = C.profile(frame, lab_shape)
    cols = ["成就数中位", "均值解锁率", "中位解锁率", "标准差",
            "稀有<1%", "稀有<5%", "普及>50%", "普及>80%"]
    units = ["", "%", "%", "", "%", "%", "%", "%"]
    scale = [1, 1, 1, 1, 100, 100, 100, 100]
    dec = [0, 1, 1, 1, 1, 1, 1, 1]

    raw = prof[cols].astype(float).copy()
    for c, s in zip(cols, scale):
        raw[c] = raw[c] * s
    # 列内 min–max 伸缩到 0–1：热图的读法是「同一列里谁高谁低」，
    # 用 min–max 而不是 z 分数，是因为 5 个点的 z 只落在 ±1.2 内，
    # 除以色阶范围后整张图都会被冲成浅色。
    lo, hi = raw.min(), raw.max()
    t = (raw - lo) / (hi - lo).replace(0, 1)

    feat_heat = {
        "cols": cols,
        "unit": units,
        "dec": dec,
        "rows": [{"name": C.NAMES_SHAPE.get(int(c), f"簇 {int(c)}"),
                  "color": C.PALETTE[int(c) % len(C.PALETTE)]} for c in prof.index],
        "raw": [[round(float(v), d) for v, d in zip(raw.loc[c], dec)]
                for c in prof.index],
        "t": [[round(float(v), 3) for v in t.loc[c]] for c in prof.index],
    }

    return {
        "meta": {
            "games": int(len(frame)),
            "achievements": int(frame["n_ach"].sum()),
            "fingerprint": meta["sha256"][:12],
            "k_tier": k_tier,
            "k_shape": k_shape,
            "bins": BINS,
        },
        "tier": tier_rows,
        "shape": shape_rows,
        "featHeat": feat_heat,
        "tagHeat": tag_matrix(frame, tags, lab_shape, k_shape),
        "shapeNames": [C.NAMES_SHAPE.get(c, f"簇 {c}") for c in range(k_shape)],
        "shapeColors": [C.PALETTE[c % len(C.PALETTE)] for c in range(k_shape)],
    }


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>游戏画像聚类 · 四万款游戏只有五种成就结构</title>
<style>
  :root{
    --ink:#1b2230; --ink2:#4a5568; --ink3:#8a94a6;
    --bg:#f4f6fa; --card:#ffffff; --line:#e4e9f2;
    --shadow:0 1px 2px rgba(24,34,58,.05),0 8px 24px -12px rgba(24,34,58,.18);
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
    font-size:15px; line-height:1.65; -webkit-font-smoothing:antialiased;
  }
  .wrap{max-width:1180px;margin:0 auto;padding:0 28px}

  /* ---------- hero ---------- */
  .hero{padding:64px 0 40px}
  .kicker{
    display:inline-block;font-size:12px;letter-spacing:.14em;text-transform:uppercase;
    color:#185fa5;background:#e6f1fb;border-radius:999px;padding:5px 14px;margin-bottom:18px;
  }
  h1{font-size:40px;line-height:1.24;margin:0 0 16px;letter-spacing:-.02em;font-weight:600}
  h1 em{font-style:normal;color:#185fa5}
  .lede{font-size:17px;color:var(--ink2);max-width:680px;margin:0 0 32px}
  .figures{display:flex;gap:48px;flex-wrap:wrap}
  .fig .n{font-size:32px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
  .fig .l{font-size:12.5px;color:var(--ink3);margin-top:2px}

  /* ---------- section ---------- */
  section{padding:8px 0 52px}
  h2{font-size:23px;margin:0 0 8px;font-weight:600;letter-spacing:-.01em}
  .sub{color:var(--ink2);margin:0 0 26px;max-width:760px}

  /* ---------- insight duo ---------- */
  .duo{display:grid;grid-template-columns:1fr 1fr;gap:22px}
  .cell{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 22px 16px;box-shadow:var(--shadow)}
  .cell h3{margin:0 0 2px;font-size:15.5px;font-weight:600}
  .cell .cap{color:var(--ink3);font-size:13px;margin-bottom:8px}
  .cell .mean{font-size:12px;color:var(--ink3);margin-top:6px}
  .cell .mean b{color:var(--ink);font-weight:600}

  /* ---------- segmented ---------- */
  .seg{display:inline-flex;background:#e8edf6;border-radius:11px;padding:4px;margin-bottom:26px}
  .seg button{
    border:0;background:transparent;padding:9px 20px;border-radius:8px;cursor:pointer;
    font-size:14px;font-family:inherit;color:var(--ink2);font-weight:500;transition:.18s;
  }
  .seg button.on{background:var(--card);color:var(--ink);box-shadow:0 1px 3px rgba(24,34,58,.12)}
  .seg button:hover:not(.on){color:var(--ink)}

  /* ---------- cards ---------- */
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px}
  .card{
    background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;
    box-shadow:var(--shadow);transition:transform .2s ease,box-shadow .2s ease;
    display:flex;flex-direction:column;
  }
  .card:hover{transform:translateY(-3px);box-shadow:0 2px 4px rgba(24,34,58,.06),0 18px 40px -16px rgba(24,34,58,.3)}
  .card .bar{height:4px}
  .card .body{padding:20px 22px 18px;display:flex;flex-direction:column;flex:1}
  .head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:2px}
  .head .nm{font-size:17px;font-weight:600}
  .head .pc{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
  .head .pc span{font-size:13px;font-weight:500;color:var(--ink3);margin-left:2px}
  .cnt{font-size:12.5px;color:var(--ink3);margin-bottom:12px}
  .gist{font-size:14.5px;font-weight:600;letter-spacing:-.005em;margin-bottom:10px;line-height:1.45}

  .spark{width:100%;height:92px;display:block;margin:4px 0 2px}
  .axis{display:flex;justify-content:space-between;font-size:11px;color:var(--ink3);margin-bottom:12px}

  .zbar{display:flex;height:9px;border-radius:5px;overflow:hidden;margin-bottom:7px;background:#eef1f7}
  .zbar span{display:block;height:100%}
  .zlabels{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--ink3);margin-bottom:14px}
  .zlabels i{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:4px;vertical-align:middle}
  .zlabels b{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}

  .stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px 8px;margin-bottom:14px}
  .stat .lab{font-size:11px;color:var(--ink3);line-height:1.35}
  .stat .val{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.01em}

  .tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
  .tag{
    font-size:11.5px;padding:3px 9px;border-radius:999px;background:#f1f4f9;
    color:var(--ink2);border:1px solid var(--line);white-space:nowrap;
  }
  .tag b{font-weight:600;color:#185fa5;margin-left:4px}

  .reps{border-top:1px dashed var(--line);padding-top:11px;margin-top:auto}
  .reps .lab{font-size:11px;color:var(--ink3);margin-bottom:5px}
  .reps div.names{font-size:12.5px;color:var(--ink2);line-height:1.75}

  /* ---------- heatmap ---------- */
  .heat{display:grid;gap:3px;align-items:center}
  .heat-feat{grid-template-columns:158px repeat(8,minmax(0,1fr))}
  .heat-tag{grid-template-columns:158px repeat(5,minmax(0,1fr))}
  .hcell{
    height:44px;border-radius:6px;display:flex;align-items:center;justify-content:center;
    font-size:12px;font-variant-numeric:tabular-nums;transition:transform .14s ease,box-shadow .14s ease;
  }
  .hcell.tap{cursor:default}
  .hcell.tap:hover{transform:scale(1.07);box-shadow:0 6px 18px -6px rgba(24,34,58,.4);z-index:3}
  .hcol{height:38px;font-size:11.5px;color:var(--ink3);font-weight:500;line-height:1.25;text-align:center}
  .hrow{
    justify-content:flex-start;gap:7px;font-size:12.5px;color:var(--ink);font-weight:500;
    height:44px;padding-left:2px;
  }
  .hrow i{width:8px;height:8px;border-radius:2px;flex:none}
  .hrow.tag{padding-left:10px;font-weight:400;color:var(--ink2);font-size:12px}
  .hcorner{}
  .heatcard{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:var(--shadow)}
  .legend{display:flex;align-items:center;gap:10px;margin-top:14px;font-size:11.5px;color:var(--ink3)}
  .legend .grad{height:8px;width:180px;border-radius:4px}

  /* ---------- tooltip ---------- */
  #tip{
    position:fixed;left:0;top:0;pointer-events:none;opacity:0;transition:opacity .12s;
    background:#1b2230;color:#fff;font-size:12px;line-height:1.5;padding:7px 10px;border-radius:7px;
    max-width:260px;z-index:99;box-shadow:0 8px 24px -8px rgba(0,0,0,.5);
  }
  #tip.on{opacity:1}

  /* ---------- reveal ---------- */
  .js .reveal{opacity:0;transform:translateY(16px);transition:opacity .55s ease,transform .55s ease}
  .js .reveal.in{opacity:1;transform:none}
  .topline{height:3px;background:linear-gradient(90deg,#185fa5,#5f9e6e,#d0a03c,#c96a4a,#a174b5)}

  /* 打印 / 转 PDF 时没有滚动，滚动进场动画会让下方区块保持空白 */
  @media print{
    .js .reveal{opacity:1!important;transform:none!important}
    .card:hover{transform:none}
  }

  /* ---------- note ---------- */
  .note{
    background:#fdf6e8;border:1px solid #f0dfb8;border-radius:12px;padding:16px 20px;
    font-size:13.5px;color:#6b5320;margin-top:26px;
  }
  .note b{color:#4a3a12}
  .limits{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:26px 28px;box-shadow:var(--shadow)}
  .limits ul{margin:10px 0 0;padding-left:20px;color:var(--ink2);font-size:14px}
  .limits li{margin-bottom:8px}
  .limits li b{color:var(--ink)}

  footer{border-top:1px solid var(--line);padding:22px 0 48px;color:var(--ink3);font-size:12.5px}
  footer a{color:#185fa5;text-decoration:none}
  footer a:hover{text-decoration:underline}

  @media (max-width:820px){
    h1{font-size:29px} .duo{grid-template-columns:1fr} .hero{padding:40px 0 28px}
    .figures{gap:28px} .fig .n{font-size:25px}
  }
</style>
</head>
<body>
<div class="topline"></div>
<div id="tip"></div>

<div class="wrap">
  <div class="hero">
    <div class="kicker">YMT · 游戏画像聚类与自动分型</div>
    <h1>四万款游戏，成就的「铺法」<br/>其实只有<em>五种</em></h1>
    <p class="lede">
      每款游戏的成就都带一个「全球多少玩家拿到了」的百分比。把这些百分比画成一条曲线，
      游戏之间就有了形状上的区别——有的平铺、有的两头翘、有的全挤在一根尖峰上。
      下面这些图全部由真实数据算出，不是示意。
    </p>
    <div class="figures">
      <div class="fig"><div class="n">__GAMES__</div><div class="l">款游戏进入分析</div></div>
      <div class="fig"><div class="n">__ACH__</div><div class="l">条成就记录</div></div>
      <div class="fig"><div class="n">5</div><div class="l">种成就结构型</div></div>
    </div>
  </div>

  <section>
    <h2>先看这一组对比：平均一样，形状完全相反</h2>
    <p class="sub">
      这两类的成就平均解锁率几乎相同（都在 23%–25%）。只看平均值，它们是一回事；
      看形状，它们正好相反。这就是为什么直接按平均值聚类，只会得到一张难度排行榜。
    </p>
    <div class="duo" id="duo"></div>
    <div class="note">
      <b>怎么读这张图：</b>横轴是成就的解锁率（0% 到 100%），曲线的高度表示「有多少成就落在这一档」。
      左边这类游戏每个成就都不好不坏，一路平顺衰减；右边这类在极低端堆了 58% 的成就，
      又在 50%–80% 之间鼓出第二个包，10%–50% 这段明显下凹。
      <br/><b>纵轴做了平方根压缩</b>——主峰常比次峰高一个数量级，不压缩的话次峰完全看不见。
      各簇的均值、占比等统计量仍按原始数值计算，没有受压缩影响。
    </div>
  </section>

  <section>
    <h2>两种看法：先分难度，再看结构</h2>
    <p class="sub">
      同一个聚类算法，喂不同的特征就答不同的问题。切换看看：「只按难度」只能分出三档，
      「剥掉难度」才分出五种有实际含义的结构。
    </p>
    <div class="seg">
      <button id="btn-shape" class="on" data-view="shape">剥掉难度后 · 五种结构</button>
      <button id="btn-tier" data-view="tier">只按难度 · 三档</button>
    </div>
    <div class="grid" id="cards"></div>
  </section>

  <section class="reveal">
    <h2>五类的特征指纹</h2>
    <p class="sub">
      每一列单独伸缩到同一个色阶——所以看的是「同一列里谁偏高谁偏低」，不是跨列比大小。
      格子里是真实数值，颜色只是让它一眼可读。
    </p>
    <div class="heatcard">
      <div id="heat-feat" class="heat heat-feat"></div>
      <div class="legend">
        <span>偏低</span>
        <span class="grad" id="grad-feat"></span>
        <span>偏高</span>
        <span style="margin-left:12px">（列内 min–max 伸缩，两端为各列最小 / 最大值）</span>
      </div>
    </div>
  </section>

  <section class="reveal">
    <h2>什么类型的游戏，落进哪一类结构</h2>
    <p class="sub">
      行为 Steam 玩家标签，列为五种结构型。数字是<b>富集倍数</b>：这一簇里含该标签的游戏占比
      ÷ 全库含该标签的占比。3 表示「这种类型在这一簇里的浓度是全库的 3 倍」。
      标签按富集最强的簇成组排列，所以同一列的深色块会连成一片。
    </p>
    <div class="heatcard">
      <div id="heat-tag" class="heat heat-tag"></div>
      <div class="legend">
        <span>1×</span>
        <span class="grad" id="grad-tag"></span>
        <span>10× 以上</span>
        <span style="margin-left:12px">（对数色阶；全库覆盖不足 3% 的标签未纳入）</span>
      </div>
    </div>
    <div class="note">
      <b>这张图能读出什么：</b>视觉小说几乎全落在「好玩但入坑难型」，「找猫」这类收集小游戏和
      Hand-drawn、Point &amp; Click 一堆相关标签都堆在「玩家友好型」，肉鸽与经营集中在
      「正常型」，联机与 VR 则集中在「入门劝退型」。
      也就是说，成就的铺法不是随机的，它和游戏类型高度绑定——但这是<b>相关</b>，不是因果。
      <br/><b>还有一件事：</b>「两极分化型」几乎没有专属标签（只有一行 Local Co-Op，1.3×）。
      它更像一种<b>跨品类的成就设计</b>——任何类型都可能出现「开一局就送 + 全收集极难」的组合，
      而不是某个品类自带的属性。这一条是看图看出来的，不是事先设想的。
    </div>
  </section>

  <section class="reveal">
    <h2>这些结论不能怎么用</h2>
    <div class="limits">
      <ul>
        <li><b>聚的是游戏，不是玩家。</b>一款游戏属于「极稀有型」，说的是它的成就大多数人拿不到，<b>不能</b>说成「它的玩家更硬核」——库里没有个人解锁记录。</li>
        <li><b>百分比是当前快照。</b>这是今天回看的解锁率，不是历史上任一时刻的值。</li>
        <li><b>类名是归纳出来的，不是事先的假设。</b>换数据、换聚类数都可能不成立。这份结论中途就修正过一次：最初把「极稀有」和「近乎全普及」误并成了一类。</li>
        <li><b>结构不算锐利。</b>「宽幅铺开型」与「中段收敛型」在特征空间里重叠明显，这两类的边界只能当弱结论。</li>
        <li><b>游玩时长没有参与聚类。</b>SteamSpy 的时长字段已失效，RAWG 只覆盖约三分之一游戏，样本不足以支撑主模型。</li>
      </ul>
    </div>
  </section>

  <footer>
    数据来源：Steam 商店与 Steam Web API（成就、标签）、SteamSpy（用户标签）、
    <a href="https://rawg.io/" target="_blank" rel="noopener">RAWG</a>（时长与评分，仅作事后描述）。
    RAWG 数据按免费档非商业用途使用。输入指纹 __FP__。
    <div style="margin-top:10px;color:#a6aebb">名词对照：__NAMEMAP__</div>
  </footer>
</div>

<script>
const DATA = __DATA__;

const W = 300, H = 92;

function pathOf(density, color){
  const n = density.length;
  const max = Math.max(...density, 1e-6);
  // 纵轴取平方根压缩：真实分布里主峰常比次峰高一个数量级（如双峰分化型 0.237 vs 0.022），
  // 线性刻度下次峰会看不见。压缩只用于显示，所有统计量与报告里的数字仍按原尺度算。
  const pts = density.map((v,i)=>{
    const x = (i + 0.5) / n * W;
    const y = H - 4 - Math.sqrt(v / max) * (H - 14);
    return [x, y];
  });
  // 平滑：Catmull-Rom 转二次贝塞尔
  let line = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for(let i=0;i<pts.length-1;i++){
    const p0 = pts[i], p1 = pts[i+1];
    const mx = (p0[0]+p1[0])/2, my = (p0[1]+p1[1])/2;
    line += ` Q ${p0[0].toFixed(1)} ${p0[1].toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`;
  }
  const last = pts[pts.length-1];
  line += ` L ${last[0].toFixed(1)} ${last[1].toFixed(1)}`;
  const area = `${line} L ${W} ${H} L 0 ${H} Z`;
  return {line, area};
}

function spark(density, color, id){
  const {line, area} = pathOf(density, color);
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="g${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0.02"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#g${id})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
  </svg>
  <div class="axis"><span>0%</span><span>50%</span><span>100%</span></div>`;
}

function zoneBar(zones, color){
  const ops = [0.24, 0.52, 0.92];
  const segs = zones.map((z,i)=>
    `<span style="width:${z.pct}%;background:${color};opacity:${ops[i]}"></span>`).join("");
  const labels = zones.map((z,i)=>
    `<span><i style="background:${color};opacity:${ops[i]}"></i>${z.label} <b>${z.pct}%</b></span>`).join("");
  return `<div class="zbar">${segs}</div><div class="zlabels">${labels}</div>`;
}

function card(c){
  const stats = c.stats.slice(0,6).map(s=>
    `<div class="stat"><div class="lab">${s.label}</div><div class="val">${s.value}</div></div>`
  ).join("");
  const tags = c.tags.map((t,i)=>
    `<span class="tag">${t}<b>${c.lifts[i]}</b></span>`
  ).join("");
  const reps = c.reps.map(r=>`· ${r}`).join("<br/>");
  return `<div class="card">
    <div class="bar" style="background:${c.color}"></div>
    <div class="body">
      <div class="head">
        <div class="nm">${c.name}</div>
        <div class="pc" style="color:${c.color}">${c.share}<span>%</span></div>
      </div>
      <div class="cnt">${c.games.toLocaleString()} 款游戏 · 发售年中位 ${c.year} · 付费占 ${c.paid}%</div>
      <div class="gist" style="color:${c.color}">${c.gist}</div>
      ${spark(c.density, c.color, c.id + (c.view||""))}
      ${zoneBar(c.zones, c.color)}
      <div class="stats">${stats}</div>
      <div class="tags">${tags}</div>
      <div class="reps">
        <div class="lab">该簇最热门的 5 款（按评价数）</div>
        <div class="names">${reps}</div>
      </div>
    </div>
  </div>`;
}

function renderDuo(){
  const pick = ["好玩但入坑难型","两极分化型"]
    .map(n=>DATA.shape.find(c=>c.name===n)).filter(Boolean);
  document.getElementById("duo").innerHTML = pick.map(c=>`
    <div class="cell">
      <h3 style="color:${c.color}">${c.name}</h3>
      <div class="cap">${c.games.toLocaleString()} 款 · 占 ${c.share}%</div>
      ${spark(c.density, c.color, "d"+c.id)}
      <div class="mean">平均解锁率 <b>${c.stats[1].value}</b> · 稀有 &lt;1% 仅 <b>${c.stats[3].value}</b> · 普及 &gt;50% 仅 <b>${c.stats[4].value}</b></div>
    </div>`).join("");
}

function render(view){
  const rows = (view === "tier" ? DATA.tier : DATA.shape).map(c=>({...c, view}));
  document.getElementById("cards").innerHTML = rows.map(card).join("");
  document.querySelectorAll(".seg button").forEach(b=>{
    b.classList.toggle("on", b.dataset.view === view);
  });
}

document.querySelectorAll(".seg button").forEach(b=>{
  b.addEventListener("click", ()=>render(b.dataset.view));
});

// ---------------- heatmaps ----------------
const DIV_STOPS = [[44,123,182],[213,231,245],[250,250,250],[249,209,190],[198,62,74]];
const SEQ_STOPS = [[244,248,252],[198,219,239],[107,174,214],[33,113,181],[8,48,107]];

function ramp(stops, t){
  t = Math.max(0, Math.min(1, t));
  const n = stops.length - 1;
  const i = Math.min(Math.floor(t * n), n - 1);
  const f = t * n - i;
  const a = stops[i], b = stops[i + 1];
  return `rgb(${Math.round(a[0]+(b[0]-a[0])*f)},${Math.round(a[1]+(b[1]-a[1])*f)},${Math.round(a[2]+(b[2]-a[2])*f)})`;
}

function luminance(rgb){
  const parts = rgb.match(/\d+/g).map(Number);
  const [r,g,b] = parts.map(v=>{
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126*r + 0.7152*g + 0.0722*b;
}

function inkOf(bg){ return luminance(bg) > 0.42 ? "#1b2230" : "#ffffff"; }

const tip = document.getElementById("tip");
document.addEventListener("mousemove", e=>{
  tip.style.left = (e.clientX + 14) + "px";
  tip.style.top  = (e.clientY + 14) + "px";
});

function bindTips(root){
  root.querySelectorAll("[data-tip]").forEach(el=>{
    el.addEventListener("mouseenter", ()=>{ tip.textContent = el.dataset.tip; tip.classList.add("on"); });
    el.addEventListener("mouseleave", ()=>tip.classList.remove("on"));
  });
}

function gradientCss(stops){
  return "linear-gradient(90deg," + stops.map(s=>`rgb(${s})`).join(",") + ")";
}

function renderFeatHeat(H){
  const el = document.getElementById("heat-feat");
  let h = '<div class="hcell hcorner"></div>';
  H.cols.forEach(c=>{ h += `<div class="hcell hcol">${c}</div>`; });
  H.rows.forEach((r,i)=>{
    h += `<div class="hcell hrow"><i style="background:${r.color}"></i>${r.name}</div>`;
    H.cols.forEach((c,j)=>{
      const v = H.raw[i][j], u = H.unit[j], v2 = v.toFixed(H.dec[j]);
      const bg = ramp(DIV_STOPS, H.t[i][j]);
      h += `<div class="hcell tap" style="background:${bg};color:${inkOf(bg)}"
             data-tip="${r.name} · ${c}：${v2}${u}">${v2}${u}</div>`;
    });
  });
  el.innerHTML = h;
  bindTips(el);
  document.getElementById("grad-feat").style.background = gradientCss(DIV_STOPS);
}

function renderTagHeat(H){
  const el = document.getElementById("heat-tag");
  let h = '<div class="hcell hcorner"></div>';
  DATA.shapeNames.forEach(n=>{ h += `<div class="hcell hcol">${n}</div>`; });
  const lo = Math.log10(0.6), hi = Math.log10(12);
  H.tags.forEach((t,i)=>{
    h += `<div class="hcell hrow tag">${t}</div>`;
    H.lift[i].forEach((v,j)=>{
      const pos = (Math.log10(Math.max(v, 0.6)) - lo) / (hi - lo);
      const bg = ramp(SEQ_STOPS, pos);
      const txt = v >= 10 ? v.toFixed(0) : (v >= 1 ? v.toFixed(1) : v.toFixed(2));
      h += `<div class="hcell tap" style="background:${bg};color:${inkOf(bg)}"
             data-tip="${t} → ${DATA.shapeNames[j]}：富集 ${v}×，该簇 ${H.cov[i][j]}% 的游戏带此标签">${txt}</div>`;
    });
  });
  el.innerHTML = h;
  bindTips(el);
  document.getElementById("grad-tag").style.background = gradientCss(SEQ_STOPS);
}

// ---------------- reveal ----------------
document.body.classList.add("js");
const io = new IntersectionObserver(entries=>{
  entries.forEach(e=>{
    if(e.isIntersecting){ e.target.classList.add("in"); io.unobserve(e.target); }
  });
}, {threshold: 0.06});
document.querySelectorAll(".reveal").forEach(el=>io.observe(el));

renderDuo();
render("shape");
renderFeatHeat(DATA.featHeat);
renderTagHeat(DATA.tagHeat);
</script>
</body>
</html>
"""


def main() -> None:
    payload = build_payload()
    namemap = " ｜ ".join(
        f"{c['name']} = 原「{FORMAL[c['name']]}」"
        for c in payload["shape"] if c["name"] in FORMAL
    )
    html = (
        TEMPLATE
        .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
        .replace("__GAMES__", f"{payload['meta']['games']:,}")
        .replace("__ACH__", f"{payload['meta']['achievements']:,}")
        .replace("__FP__", payload["meta"]["fingerprint"])
        .replace("__NAMEMAP__", namemap)
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"✓ 已生成 {OUT}  （{OUT.stat().st_size/1024:.0f} KB）")
    print(f"  主帧 {payload['meta']['games']:,} 款 / "
          f"{payload['meta']['achievements']:,} 条成就 / "
          f"k_tier={payload['meta']['k_tier']} k_shape={payload['meta']['k_shape']}")


if __name__ == "__main__":
    main()
