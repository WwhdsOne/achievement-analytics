"""为数据获取阶段汇报生成描述性位图；不训练、不读取预测结果。"""

from __future__ import annotations

import gzip
import json
import math
import zlib
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/processed/snapshots/engagement-20261001-079598c5d7ae.json.gz"
COLORS = ["#167a72", "#3761b7", "#b65267", "#749543", "#62656b"]
# 词云配色沿用汇报主色，颜色由词本身决定，保证每次生成的位图一致。
CLOUD_COLORS = ["#167a72", "#3761b7", "#b65267", "#749543", "#b07d2f", "#4a8aa8"]


def style_axis(ax: plt.Axes) -> None:
    """使用汇报的中性底色、细网格与易读中文字体。"""
    ax.set_facecolor("#f7f8fa")
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0, labelsize=12, colors="#5c6470")
    ax.set_axisbelow(True)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """判断两个 (x0, y0, x1, y1) 矩形是否相交。"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def word_cloud(freqs: dict[str, int], path: Path, *, max_words: int = 80) -> dict[str, object]:
    """把「词 → 计数」画成静态词云位图。

    字号按计数平方根缩放（面积正比于数量），沿中心向外的螺旋逐个落词，
    用真实文字外框做重叠检测，避免词与词相互压盖。颜色由词名哈希决定，
    因此同一份快照每次生成的图完全一致。返回落词数与词表供核对。
    """
    ax = plt.figure(figsize=(7.4, 4.6), facecolor="#f7f8fa").add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    figure = ax.figure
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    to_data = ax.transData.inverted()

    items = sorted(freqs.items(), key=lambda kv: (-kv[1], kv[0]))[:max_words]
    if not items:
        raise ValueError("词云没有可绘制的词")
    hi, lo = items[0][1], items[-1][1]
    span = max(hi - lo, 1)
    placed: list[tuple[float, float, float, float]] = []
    used: list[tuple[str, int]] = []
    margin = 0.022                                            # 留白：字形外框之外再留一点，避免边缘被裁
    for word, count in items:
        size = 7 + math.sqrt((count - lo) / span) * 42       # 7–49pt，面积 ∝ 数量
        color = CLOUD_COLORS[zlib.crc32(word.encode()) % len(CLOUD_COLORS)]
        text = ax.text(0.5, 0.5, word, fontsize=size, fontweight="bold",
                       color=color, ha="center", va="center")
        box = text.get_window_extent(renderer)
        (x0, y0), (x1, y1) = to_data.transform((box.x0, box.y0)), to_data.transform((box.x1, box.y1))
        half_w, half_h, pad = abs(x1 - x0) / 2, abs(y1 - y0) / 2, 0.002
        spot = None
        for step in range(1, 6000):                          # 中心向外螺旋找空位（横向放宽 1.9 倍）
            angle = step * 0.25
            x, y = 0.5 + 0.007 * angle * math.cos(angle) * 1.9, 0.5 + 0.007 * angle * math.sin(angle)
            if (x - half_w < margin or x + half_w > 1 - margin
                    or y - half_h < margin or y + half_h > 1 - margin):
                continue
            rect = (x - half_w - pad, y - half_h - pad, x + half_w + pad, y + half_h + pad)
            if all(not _overlap(rect, other) for other in placed):
                spot = (x, y, rect)
                break
        if spot is None:
            text.remove()                                    # 放不下就丢弃长尾词，不压盖已有词
            continue
        text.set_position(spot[:2])
        placed.append(spot[2])
        used.append((word, count))
    figure.savefig(path, dpi=200)
    plt.close(figure)
    return {"words": len(used), "top": used[:6]}


def main() -> None:
    """从本机固定快照和阶段报告聚合数生成静态位图，不访问云库。"""
    available = next((f.name for f in font_manager.fontManager.ttflist if "PingFang" in f.name), "DejaVu Sans")
    plt.rcParams.update({"font.family": available, "axes.unicode_minus": False})
    output = ROOT / "docs/assets/acquisition"
    output.mkdir(parents=True, exist_ok=True)
    rows = json.loads(gzip.decompress(SNAPSHOT.read_bytes()))["data"]
    counts = np.array([row["ach_count"] for row in rows if row["ach_count"] and row["ach_count"] > 0])
    rates = np.array([row["median_percent"] for row in rows if row["median_percent"] is not None])

    fig, ax = plt.subplots(figsize=(10, 3.3), facecolor="#f7f8fa")
    style_axis(ax)
    labels, values = ["商店详情", "成就记录", "SteamSpy", "RAWG"], [50954, 50738, 50741, 15770]
    ax.barh(labels[::-1], values[::-1], height=.45, color=COLORS[::-1][:4])
    ax.set_xlim(0, 60000)
    ax.set_xticks([0, 10000, 20000, 30000, 40000, 50000], ["0", "1万", "2万", "3万", "4万", "5万"])
    ax.grid(axis="x", color="#e1e5ea", linewidth=.7)
    for i, value in enumerate(values[::-1]):
        rate = f"{value/50956:.3%}" if value == 50954 else f"{value/50956:.1%}"
        ax.text(value+550, i, f"{value:,}  /  {rate}", va="center", fontsize=12, color="#262d35")
    fig.tight_layout(pad=1.3)
    fig.savefig(output / "source-coverage.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.8, 3.8), facecolor="#f7f8fa")
    style_axis(ax)
    bins = [int(np.sum((counts >= low) & (counts < high))) for low, high in [(1,10),(10,30),(30,60),(60,100),(100,np.inf)]]
    ax.bar(["1-9", "10-29", "30-59", "60-99", "100+"], bins, color=COLORS, width=.6)
    ax.grid(axis="y", color="#e1e5ea", linewidth=.7)
    ax.set_ylim(0, max(bins)*1.18)
    ax.set_ylabel("游戏数量", fontsize=12, color="#5c6470")
    ax.set_xlabel("每款游戏的成就条数", fontsize=12, color="#5c6470")
    for i, value in enumerate(bins):
        ax.text(i, value+max(bins)*.025, f"{value:,}", ha="center", fontsize=12)
    fig.tight_layout(pad=1.2)
    fig.savefig(output / "achievement-counts.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.8, 3.8), facecolor="#f7f8fa")
    style_axis(ax)
    hist, edges = np.histogram(rates, bins=np.arange(0,101,10))
    ax.bar(edges[:-1]+5, hist, width=7.5, color="#3761b7")
    ax.grid(axis="y", color="#e1e5ea", linewidth=.7)
    ax.set_xticks([0,20,40,60,80,100], ["0%","20%","40%","60%","80%","100%"])
    ax.set_xlim(-2,102)
    ax.set_ylabel("游戏数量", fontsize=12, color="#5c6470")
    ax.set_xlabel("游戏内成就完成率的中位数", fontsize=12, color="#5c6470")
    fig.tight_layout(pad=1.2)
    fig.savefig(output / "completion-distribution.png", dpi=200)
    plt.close(fig)

    genres = Counter(g for row in rows for g in (row.get("genres") or []))
    tags = Counter(t for row in rows for t in (row.get("tags") or []))
    genre_cloud = word_cloud(genres, output / "genre-cloud.png", max_words=24)
    tag_cloud = word_cloud(tags, output / "tag-cloud.png", max_words=70)

    print(json.dumps({"snapshot_games":len(rows),"games_with_achievements":len(counts),
                      "median_achievement_count":float(np.median(counts)),
                      "count_bands":bins,"games_with_completion_rate":len(rates),
                      "median_game_completion_rate":float(np.median(rates)),
                      "below_20_percent":int(np.sum(rates<20)),
                      "games_with_genres":sum(1 for r in rows if r.get("genres")),
                      "games_with_tags":sum(1 for r in rows if r.get("tags")),
                      "genre_cloud":genre_cloud,"tag_cloud":tag_cloud,
                      "assets":str(output)},ensure_ascii=False))


if __name__ == "__main__":
    main()
