"""按发售年份统计 SteamSpy 主题标签的占比演变（描述性分析，只读）。

研究问题
    不同类型的游戏标签，在 Steam 各年发售的游戏里占比如何变化。

统计口径（固定，改口径必须同步改本 docstring 与实验记录）
    年份        = ``steam_appdetails.release_date`` 的年份。
    主导标签源  = ``game_tags`` 中 ``source='steamspy' AND kind='theme'``
                  （SteamSpy 用户标签；RAWG 的 tags 混入平台功能词，不用于本分析）。
    某标签在年份 y 的占比
                = 该年含该标签的游戏数 ÷ 该年**有效标签游戏数**。
    「有效标签游戏」= 该年至少有一个主题标签的游戏（``with_tags``）。
    多标签游戏在每个标签上**重复计入**，因此各标签占比之和**必然大于 100%**，
    不构成互斥分割。

标签归类
    ``CATEGORIES`` 把标签按语义归为五类（玩法类型 / 题材设定 / 美术与呈现 /
    模式与功能 / 氛围与叙事），非游戏条目（Steam 上的软件与影片）单列排除。
    归类是**人工规则**，用于提供类目级视角；标签级统计不受归类影响。
    匹配前统一做规范化（小写、去标点），输出仍保留数据库原始标签名。

必须在结论中同时报告的三条局限
    1. 标签是**抓取当时**的 Steam 用户标签，不是当年标签；库中没有当年的
       玩家数 / 销量 / 评论历史记录，因此**不能用它判断某游戏在当年是否流行**，
       也不能用现今的拥有量反推历史热度。
    2. ``2026`` 年未纳入分析帧（项目口径为 ``release_date < 2026-01-01``），
       且该年尚未结束，其年度数量不可与完整年份直接比较。
    3. 各年标签覆盖率不同（近年抓取尚未完成），覆盖率低的年份占比不可与
       覆盖率高的年份直接比较——因此覆盖率随占比一并输出。

运行::

    uv run python -m modeling.tag_trends
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _project_root() -> Path:
    """向上查找含 pyproject.toml 的目录。

    本脚本会被归档到 ``result/<缩写>/`` 下（位置不固定），因此不能靠写死的
    ``parents[n]`` 定位项目根——按标志文件向上找才稳。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("未找到项目根（向上没有 pyproject.toml）")


ROOT = _project_root()
# 脚本被移出 modeling/ 后 sys.path 不再含项目根，需自己补上才能 import 项目包。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from sqlalchemy import text

from cleaning.db import get_engine

# 交付归档：按用户要求，本次任务的产出（脚本 / 图 / 报告）全部集中在脚本所在的
# result/<缩写>/，该目录自包含、可直接交付。明细缓存是 18 MB 的中间物，留在项目
# 内部的 data/processed/（不入 Git），不占交付目录。
OUT_DIR = Path(__file__).resolve().parent
ASSETS = OUT_DIR
REPORT = OUT_DIR / "tag-trends.json"
DETAIL_CACHE = ROOT / "data/processed/tag-trends-detail.pkl"

# 出图窗口：下界避开样本极少的早期年份，上界为最后一个完整且覆盖率可接受的年份。
PLOT_START, PLOT_END = 2014, 2024
# 增长排名的主口径：两端年份覆盖率都 ≥98%，可比性最强。
GROWTH_BASE, GROWTH_END = 2014, 2020
# 标签进入增长排名所需的基准年游戏数，避免小基数放大出虚高增幅。
MIN_BASE_GAMES = 30

COLORS = ["#167a72", "#3761b7", "#b65267", "#749543", "#62656b"]
LINE_COLORS = [
    "#167a72",
    "#3761b7",
    "#b65267",
    "#749543",
    "#b07d2f",
    "#4a8aa8",
    "#7a4fb0",
    "#c4633c",
    "#4f9e7a",
    "#8a5a44",
    "#5c6b8a",
    "#a0453f",
    "#3f7d7a",
    "#9a6aa8",
]
# 类目演变图中不画的类目：「玩法类型」在 2014–2024 全部年份都接近 100%
# （几乎每款游戏都至少带一个玩法标签），画出来是一条压顶的水平线，
# 既无信息量又会压缩其余类目的纵向分辨率。标签级统计不受影响。
CATEGORY_PLOT_SKIP = {"玩法类型"}


def _tags(block: str) -> set[str]:
    """把 ``|`` 分隔的标签清单解析为规范化集合。"""
    return {_norm(part) for part in block.split("|") if part.strip()}


def _norm(tag: str) -> str:
    """规范化标签名：统一大小写并去掉标点，用于容忍库中的写法差异。"""
    return re.sub(r"[^a-z0-9]+", "", tag.lower())


CATEGORIES: dict[str, set[str]] = {
    "玩法类型": _tags("""
    Action | Adventure | Indie | Casual | Puzzle | Strategy | Simulation | RPG
    | Platformer | 2D Platformer | 3D Platformer | Precision Platformer
    | Puzzle-Platformer | Shooter | Arcade | Racing | Sports | Fighting
    | 2D Fighter | 3D Fighter | Spectacle fighter | Visual Novel | RTS | FPS
    | Metroidvania | Rogue-like | Rogue-lite | Roguelike Deckbuilder
    | Traditional Roguelike | Roguevania | Action Roguelike | Souls-like
    | Deckbuilding | Card Game | Card Battler | Trading Card Game
    | Tower Defense | Idler | Clicker | Rhythm | Sandbox | Survival
    | Open World | Open World Survival Craft | Management | Resource Management
    | Turn-Based | Turn-Based Strategy | Turn-Based Combat | Turn-Based Tactics
    | Tactical | Tactical RPG | Strategy RPG | Real Time Tactics | Real-Time
    | Real-Time with Pause | Auto Battler | Battle Royale | MOBA
    | Walking Simulator | Point & Click | Hidden Object | Match 3 | Sokoban
    | Runner | Dungeon Crawler | Immersive Sim | Colony Sim | City Builder
    | Base-Building | Crafting | Automation | Farming Sim | Life Sim
    | Dating Sim | Otome | Party Game | Board Game | Tabletop | Word Game
    | Solitaire | Education | Trivia | Beat 'em up | Hack and Slash
    | Bullet Hell | Shoot 'Em Up | Arena Shooter | Twin Stick Shooter
    | Top-Down Shooter | Third-Person Shooter | Looter Shooter | Hero Shooter
    | Boomer Shooter | Extraction Shooter | On-Rails Shooter
    | Character Action Game | Action RTS | 4X | Grand Strategy | Wargame
    | God Game | Political Sim | Outbreak Sim | Medical Sim | Job Simulator
    | Automobile Sim | Space Sim | Hobby Sim | Fishing | Hunting | Mining
    | Time Management | Inventory Management | Trading | Diplomacy | Hex Grid
    | Grid-Based Movement | Quick-Time Events | Time Attack | Boss Rush
    | Typing | Spelling | Logic | Chess | Mahjong | Pinball | Mini Golf
    | Golf | Tennis | Basketball | Baseball | Football (Soccer)
    | Football (American) | Hockey | Cricket | Volleyball | Rugby | Bowling
    | Pool | Snooker | Boxing | Wrestling | Sniper | Archery | Naval Combat
    | Combat Racing | Vehicular Combat | Destruction | Parkour | Stealth
    | Hacking | Interactive Fiction | Choose Your Own Adventure | Escape Room
    | Minigames | Party | Procedural Generation | Level Editor
    | Character Customization | Gun Customization | Moddable | Mod
    | Creature Collector | Collectathon | Score Attack | Time Manipulation
    | Bullet Time | Musou | Shop Keeper | Action-Adventure | Action RPG
    | Music-Based Procedural Generation | Medical | Farming
    """),
    "题材设定": _tags("""
    Fantasy | Dark Fantasy | Sci-fi | Horror | Survival Horror
    | Psychological Horror | Anime | Space | Zombies | Post-apocalyptic
    | Cyberpunk | Medieval | Historical | War | Detective | Mystery
    | Romance | Comedy | Drama | Supernatural | Magic | Mythology
    | Lovecraftian | Steampunk | Gothic | Aliens | Demons | Dragons | Mechs
    | Robots | Military | Crime | Noir | Dystopian | Alternate History
    | Capitalism | Science | Ninja | Pirates | Vampire | Werewolves | Dwarf
    | Elf | Vikings | Rome | Cold War | World War I | World War II | Mars
    | Dinosaurs | Superhero | Assassin | Heist | Political | Politics | Faith
    | Illuminati | Conspiracy | Time Travel | Underwater | Underground | Snow
    | Western | Trains | Sailing | Naval | Submarine | Spaceships | Tanks
    | Jet | Transhumanism | LEGO | Warhammer 40K | Dungeons & Dragons
    | Games Workshop | Martial Arts | Sexual Content | Nudity | Hentai
    | NSFW | Mature | LGBTQ+ | Cats | Dog | Fox | Birds | Horses
    """),
    "美术与呈现": _tags("""
    2D | 3D | 2.5D | Pixel Graphics | Colorful | Cartoony | Cartoon
    | Stylized | Minimalist | Hand-drawn | Isometric | Top-Down
    | First-Person | Third Person | Realistic | Surreal | Voxel | Abstract
    | Psychedelic | Cinematic | Comic Book | Text-Based | FMV | Side Scroller
    | Soundtrack | Great Soundtrack | Music | Electronic Music | Rock Music
    | Instrumental Music | 8-bit Music | Ambient | Electronic | Retro
    | Old School | 1990's | 1980s | Remake | Sequel | Reboot | Episodic
    | Based On A Novel | Full Motion Video
    """),
    "模式与功能": _tags("""
    Singleplayer | Multiplayer | Co-op | Local Co-Op | Online Co-Op | PvP
    | PvE | Massively Multiplayer | MMO | MMORPG | Controller | VR
    | Asymmetric VR | Free to Play | Early Access | Split Screen | Team-Based
    | Competitive | Co-op Campaign | 4 Player Local | Asynchronous Multiplayer
    | Touch-Friendly | Voice Control | TrackIR | 3D Vision | 6DOF
    | Intentionally Awkward Controls | e-sports | Mouse only
    | Cross-Platform Multiplayer | LAN | LAN Co-Op | Sound card
    | Crowdfunded | Kickstarter
    """),
    "氛围与叙事": _tags("""
    Atmospheric | Relaxing | Funny | Cute | Dark | Difficult | Emotional
    | Wholesome | Cozy | Psychological | Story Rich | Choices Matter
    | Multiple Endings | Linear | Nonlinear | Replay Value | Short
    | Experimental | Memes | Dark Humor | Dark Comedy | Narration
    | Dynamic Narration | Silent Protagonist | Well-Written | Lore-Rich
    | Epic | Nostalgia | Immersive | Unforgiving | Addictive | Beautiful
    | Gore | Violent | Blood | Jump Scare | Thriller | Philosophical
    | Satire | Parody | Cult Classic | Masterpiece | Experience | Modern
    | Classic | Tutorial | Conversation | Female Protagonist
    | Villain Protagonist
    """),
}

# 非游戏条目：Steam 上的创作/办公软件与影片，不属于游戏标签分析范围。
EXCLUDED: set[str] = _tags("""
    Design & Illustration | Programming | Audio Production | Photo Editing
    | Video Production | Web Publishing | Software Training | Utilities
    | Game Development | Hardware | Benchmark | Software | Movie
    | Documentary | Feature Film | Gaming | Coding | Steam Machine
    | Animation & Modeling | 360 Video
""")


def load_detail(refresh: bool = False) -> tuple[pd.DataFrame, dict[str, object]]:
    """提取游戏级 (appid, year, tag) 明细；默认复用本地缓存。

    查库路径用 ``REPEATABLE READ`` + ``SET TRANSACTION READ ONLY`` 保证一次
    一致性读，且从机制上排除写库的可能。结果落本地 pickle，使同一份输入可
    反复出图而不必重查云库（对齐项目「固定输入可复现」的做法）。

    本机没有 ``data/processed/snapshots/`` 下的既有快照，因此**未写入
    ``dataset_versions``**——库对本 agent 只读；改以输入指纹记录版本。
    """
    if DETAIL_CACHE.exists() and not refresh:
        frame = pd.read_pickle(DETAIL_CACHE)
        # 列清单变更后旧缓存不可用，静默忽略并重取，避免拿到缺列的数据。
        if {"year", "is_free", "tag"} <= set(frame.columns):
            meta = json.loads(DETAIL_CACHE.with_suffix(".meta.json").read_text("utf-8"))
            meta["cache"] = "hit"
            return frame, meta

    engine = get_engine()
    query = text(
        """
        SELECT a.appid,
               extract(year FROM a.release_date)::int AS year,
               coalesce(a.is_free, false) AS is_free,
               t.tag
        FROM steam_appdetails a
        LEFT JOIN game_tags t
               ON t.appid = a.appid
              AND t.source = 'steamspy' AND t.kind = 'theme'
        WHERE a.release_date < make_date(2026, 1, 1)
        """
    )
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            frame = pd.read_sql(query, conn)
            fetched = (
                conn.execute(
                    text(
                        "SELECT min(fetched_at)::text AS first, max(fetched_at)::text AS last"
                        " FROM ingest_log WHERE source = 'steamspy' AND status = 'ok'"
                    )
                )
                .mappings()
                .first()
            )
    engine.dispose()
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(frame, index=False).values.tobytes()
    ).hexdigest()
    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(frame),
        "games": int(frame.appid.nunique()),
        "sha256": digest,
        "steamspy_fetch_window": dict(fetched) if fetched else None,
        "registered_version": None,
        "note": "本机无快照文件，故直接只读查库；未写入 dataset_versions（库对本 agent 只读）",
    }
    DETAIL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    frame.to_pickle(DETAIL_CACHE)
    DETAIL_CACHE.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta["cache"] = "miss"
    return frame, meta


def build_tables(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """构造年度统计表：覆盖率、标签占比矩阵、类目占比矩阵。"""
    tagged = frame.dropna(subset=["tag"]).copy()

    per_year = frame.groupby("year").agg(
        games=("appid", "nunique"),
    )
    per_year["with_tags"] = tagged.groupby("year").appid.nunique()
    per_year["with_tags"] = per_year["with_tags"].fillna(0).astype(int)
    per_year["coverage"] = per_year.with_tags / per_year.games
    # 免费游戏占比：既看全部游戏，也看「有标签」子集——两者的落差就是
    # 缺失是否同时改变样本构成的直接证据。
    per_year["free_share_all"] = (
        frame[frame.is_free]
        .groupby("year")
        .appid.nunique()
        .reindex(per_year.index)
        .fillna(0)
        / per_year.games
    )
    per_year["free_share_tagged"] = tagged[tagged.is_free].groupby(
        "year"
    ).appid.nunique().reindex(per_year.index).fillna(0) / per_year.with_tags.replace(
        0, np.nan
    )
    # 每款游戏的平均标签数。这是解读占比变化的关键背景量：标签密度整体上行时，
    # 多数标签的占比都会被动上升，并非各自都在「变强」。
    per_year["avg_tags"] = tagged.groupby("year").size().reindex(per_year.index).fillna(
        0
    ) / per_year.with_tags.replace(0, np.nan)

    counts = tagged.groupby(["year", "tag"]).appid.nunique().unstack(fill_value=0)
    counts = counts.reindex(columns=sorted(counts.columns))
    share = counts.div(per_year.with_tags, axis=0)

    categories = {tag: cat for cat, tags in CATEGORIES.items() for tag in tags}
    # 归类表按规范化名匹配（容忍库中大小写与标点差异），输出仍用原始标签名。
    normalized = tagged.tag.map(_norm)
    tagged["category"] = normalized.map(categories).fillna("其他")
    tagged.loc[normalized.isin(EXCLUDED), "category"] = "非游戏条目"
    dedup = tagged.drop_duplicates(["appid", "category"])
    cat_counts = (
        dedup.groupby(["year", "category"]).appid.nunique().unstack(fill_value=0)
    )
    cat_share = cat_counts.div(per_year.with_tags, axis=0)
    cat_counts = cat_counts.reindex(columns=sorted(cat_counts.columns))
    cat_share = cat_share.reindex(columns=sorted(cat_share.columns))

    # 稳健性口径：只保留付费游戏。缺失标签的绝大多数是免费游戏，
    # 若趋势在两套口径下方向一致，说明它不是「免费游戏被剔除」造成的假象。
    paid = tagged[~tagged.is_free]
    paid_per_year = paid.groupby("year").appid.nunique()
    paid_counts = paid.groupby(["year", "tag"]).appid.nunique().unstack(fill_value=0)
    paid_counts = paid_counts.reindex(columns=sorted(paid_counts.columns))
    paid_share = paid_counts.div(paid_per_year, axis=0)

    return {
        "per_year": per_year,
        "counts": counts,
        "share": share,
        "paid_counts": paid_counts,
        "paid_share": paid_share,
        "paid_per_year": paid_per_year,
        "cat_counts": cat_counts,
        "cat_share": cat_share,
    }


def fastest_growing(
    share: pd.DataFrame, counts: pd.DataFrame, base: int, end: int, top: int = 12
) -> pd.DataFrame:
    """在两端年份间比较占比变化（百分点），并给出相对增幅。

    只保留基准年游戏数达到 ``MIN_BASE_GAMES`` 的标签——小基数标签的占比
    分母极小，一年涨三款就能造出巨大增幅，不具解释力。
    """
    eligible = counts.loc[base][counts.loc[base] >= MIN_BASE_GAMES].index
    frame = pd.DataFrame(
        {
            "base_share": share.loc[base, eligible],
            "end_share": share.loc[end, eligible],
            "base_games": counts.loc[base, eligible],
            "end_games": counts.loc[end, eligible],
        }
    )
    frame["delta_pp"] = (frame.end_share - frame.base_share) * 100
    frame["ratio"] = frame.end_share / frame.base_share.replace(0, np.nan)
    return frame.sort_values("delta_pp", ascending=False).head(top)


def pick_font() -> str:
    """选一个能显示中文的字体，避免中文标题渲染成方块。"""
    names = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in (
        "Microsoft YaHei",
        "SimHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ):
        if candidate in names:
            return candidate
    return "DejaVu Sans"


def style_axis(ax: plt.Axes) -> None:
    """沿用项目既有汇报风格：中性底色、细网格、无边框刻度。"""
    ax.set_facecolor("#f7f8fa")
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0, labelsize=11, colors="#5c6470")
    ax.set_axisbelow(True)


def plot_lines(
    share: pd.DataFrame, counts: pd.DataFrame, path: Path, line_count: int = 12
) -> list[str]:
    """多标签占比随年份的折线图（取样本窗口内游戏数最多的若干标签）。

    终点数值并入图例而非贴在曲线尾部——多条线在 40–50% 区间汇聚时，
    曲线末端的直接标注会互相叠压，图例带值既不丢信息也不遮挡。
    """
    window = counts.loc[PLOT_START:PLOT_END].sum().sort_values(ascending=False)
    picked = list(window.head(line_count).index)
    years = [y for y in range(PLOT_START, PLOT_END + 1) if y in share.index]
    # 排序让折线终点顺序与图例一致，减少交叉带来的误读。
    picked.sort(key=lambda t: -share.loc[PLOT_END, t])

    fig, ax = plt.subplots(figsize=(11.5, 6.4), facecolor="#f7f8fa")
    style_axis(ax)
    for tag, color in zip(picked, LINE_COLORS):
        values = share.loc[years, tag] * 100
        ax.plot(
            years,
            values,
            marker="o",
            markersize=4,
            linewidth=2,
            color=color,
            label=f"{tag}（{PLOT_END} 年 {values.iloc[-1]:.0f}%）",
        )
    ax.set_xticks(years)
    ax.set_ylabel("该年含此标签的游戏占比（%）", fontsize=12, color="#5c6470")
    ax.set_xlabel("发售年份", fontsize=12, color="#5c6470")
    ax.grid(axis="y", color="#e1e5ea", linewidth=0.7)
    ax.set_xlim(PLOT_START - 0.4, PLOT_END + 0.4)
    ax.legend(
        ncol=4,
        fontsize=10,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.11),
    )
    fig.tight_layout(pad=1.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return picked


def plot_heatmap(
    share: pd.DataFrame, counts: pd.DataFrame, path: Path, top: int = 26
) -> list[str]:
    """标签 × 年份的占比热力图，每行归一化到自身最大值以突出走势。"""
    window = counts.loc[PLOT_START:PLOT_END].sum().sort_values(ascending=False)
    picked = list(window.head(top).index)
    years = [y for y in range(PLOT_START, PLOT_END + 1) if y in share.index]
    block = share.loc[years, picked].T * 100
    # 行内归一化：绝对占比差异极大（Indie 50% vs Souls-like 2%），
    # 不归一化时热力图只剩前几个标签有颜色。
    scaled = block.div(block.max(axis=1), axis=0)
    scaled = scaled.loc[picked]  # 保持按总体游戏数排序

    fig, ax = plt.subplots(figsize=(11.5, 8.6), facecolor="#f7f8fa")
    image = ax.imshow(scaled.values, aspect="auto", cmap="YlGnBu", vmin=0, vmax=1)
    ax.set_xticks(range(len(years)), years, fontsize=11, color="#5c6470")
    ax.set_yticks(range(len(picked)), picked, fontsize=10, color="#3b424b")
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    for i, tag in enumerate(picked):
        for j, year in enumerate(years):
            value = block.loc[tag, year]
            ax.text(
                j,
                i,
                f"{value:.0f}",
                ha="center",
                va="center",
                fontsize=8,
                color="#ffffff" if scaled.loc[tag, year] > 0.62 else "#3b424b",
            )
    bar = fig.colorbar(image, ax=ax, fraction=0.022, pad=0.015)
    bar.set_label(
        "行内相对水平\n（自身最高年 = 1）", fontsize=9, color="#5c6470", labelpad=10
    )
    bar.ax.tick_params(length=0, labelsize=9)
    bar.outline.set_visible(False)
    ax.set_xlabel("发售年份", fontsize=12, color="#5c6470")
    fig.tight_layout(pad=1.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return picked


def plot_coverage(per_year: pd.DataFrame, path: Path) -> None:
    """年度游戏数与标签覆盖率：把「真实变化」和「数据缺失」分开看。"""
    years = [y for y in per_year.index if y >= 2008]
    games = per_year.loc[years, "games"]
    coverage = per_year.loc[years, "coverage"] * 100

    fig, ax = plt.subplots(figsize=(11.5, 4.6), facecolor="#f7f8fa")
    style_axis(ax)
    ax.bar(years, games, color="#c9d5e2", width=0.68, label="该年有发售日的游戏数")
    ax.bar(
        years,
        per_year.loc[years, "with_tags"],
        color=COLORS[0],
        width=0.68,
        label="其中带主题标签者（计入占比分母）",
    )
    ax.set_xticks(years, [str(y) for y in years], rotation=45, fontsize=10)
    ax.grid(axis="y", color="#e1e5ea", linewidth=0.7)
    ax.set_ylabel("游戏数量", fontsize=12, color="#5c6470")
    ax.set_ylim(0, games.max() * 1.32)
    ax.legend(fontsize=10, frameon=False, loc="upper left", ncol=1)

    twin = ax.twinx()
    twin.plot(
        years,
        coverage,
        color=COLORS[2],
        marker="o",
        markersize=4,
        linewidth=1.8,
        label="标签覆盖率",
    )
    twin.set_ylim(0, 108)
    twin.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    twin.tick_params(length=0, labelsize=11, colors="#5c6470")
    for side in twin.spines.values():
        side.set_visible(False)
    for year in (2021, 2025):
        twin.annotate(
            f"{coverage.loc[year]:.1f}%",
            (year, coverage.loc[year]),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            color=COLORS[2],
        )
    fig.tight_layout(pad=1.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_categories(cat_share: pd.DataFrame, path: Path) -> None:
    """类目级占比演变：归类后的宏观走势。

    ``CATEGORY_PLOT_SKIP`` 中的类目不绘制（当前为「玩法类型」，见该常量注释）。
    """
    years = [y for y in range(PLOT_START, PLOT_END + 1) if y in cat_share.index]
    order = ["玩法类型", "题材设定", "美术与呈现", "模式与功能", "氛围与叙事", "其他"]
    present = [
        c for c in order if c in cat_share.columns and c not in CATEGORY_PLOT_SKIP
    ]

    fig, ax = plt.subplots(figsize=(11.5, 5.4), facecolor="#f7f8fa")
    style_axis(ax)
    for cat, color in zip(present, LINE_COLORS):
        values = cat_share.loc[years, cat] * 100
        # 终点数值并入图例：多条线在 80–90% 区间收拢时，曲线尾端标注会互相叠压。
        ax.plot(
            years,
            values,
            marker="o",
            markersize=4,
            linewidth=2.2,
            color=color,
            label=f"{cat}（{PLOT_END} 年 {values.iloc[-1]:.0f}%）",
        )
    ax.set_xticks(years)
    ax.set_ylabel("该年至少含一个此类标签的游戏占比（%）", fontsize=12, color="#5c6470")
    ax.set_xlabel("发售年份", fontsize=12, color="#5c6470")
    ax.grid(axis="y", color="#e1e5ea", linewidth=0.7)
    ax.set_xlim(PLOT_START - 0.4, PLOT_END + 0.4)
    ax.legend(
        fontsize=10,
        frameon=False,
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.11),
    )
    fig.tight_layout(pad=1.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_robustness(
    share: pd.DataFrame,
    paid_share: pd.DataFrame,
    counts: pd.DataFrame,
    path: Path,
    top: int = 6,
) -> list[str]:
    """稳健性对照：全样本口径 vs 仅付费游戏口径。

    标签缺失高度偏向免费游戏，因此把「是否剔除免费游戏」作为敏感性检验。
    取样本窗口内占比变化最大的标签逐个对照——若两条线方向一致，说明该走势
    不是「免费游戏被系统性剔除」造成的假象。
    """
    window = counts.loc[PLOT_START:PLOT_END].sum()
    eligible = window[window >= MIN_BASE_GAMES * 4].index
    swing = (share.loc[PLOT_END, eligible] - share.loc[PLOT_START, eligible]).abs()
    picked = list(swing.sort_values(ascending=False).head(top).index)
    years = [y for y in range(PLOT_START, PLOT_END + 1) if y in share.index]

    fig, axes = plt.subplots(2, 3, figsize=(11.5, 6.4), facecolor="#f7f8fa")
    for ax, tag in zip(axes.ravel(), picked):
        style_axis(ax)
        full = share.loc[years, tag] * 100
        paid = paid_share.reindex(index=years)[tag] * 100
        ax.plot(
            years,
            full,
            color=COLORS[0],
            linewidth=2,
            marker="o",
            markersize=3,
            label="全部游戏",
        )
        ax.plot(
            years,
            paid,
            color=COLORS[2],
            linewidth=2,
            marker="s",
            markersize=3,
            linestyle="--",
            label="仅付费游戏",
        )
        ax.set_title(tag, fontsize=12, color="#262d35", pad=6)
        ax.grid(axis="y", color="#e1e5ea", linewidth=0.7)
        ax.set_xticks(
            [PLOT_START, 2019, PLOT_END], [str(PLOT_START), "2019", str(PLOT_END)]
        )
        ax.tick_params(labelsize=10)
        ax.set_ylim(0, float(max(full.max(), paid.max())) * 1.3)
    axes[0][0].legend(fontsize=9, frameon=False, loc="upper left")
    fig.tight_layout(pad=1.4)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return picked


def main() -> None:
    """跑完整条链路：只读取数 → 年度统计 → 出图 → 写本地报告。"""
    parser = argparse.ArgumentParser(description="按发售年份的标签占比演变")
    parser.add_argument(
        "--refresh", action="store_true", help="忽略本地明细缓存，重新只读查库"
    )
    args = parser.parse_args()
    plt.rcParams.update({"font.family": pick_font(), "axes.unicode_minus": False})
    ASSETS.mkdir(parents=True, exist_ok=True)

    frame, meta = load_detail(refresh=args.refresh)
    tables = build_tables(frame)
    per_year, counts, share = tables["per_year"], tables["counts"], tables["share"]

    line_tags = plot_lines(share, counts, ASSETS / "tag-share-lines.png")
    heat_tags = plot_heatmap(share, counts, ASSETS / "tag-year-heatmap.png")
    plot_coverage(per_year, ASSETS / "tag-coverage.png")
    plot_categories(tables["cat_share"], ASSETS / "category-share-lines.png")
    robust_tags = plot_robustness(
        share, tables["paid_share"], counts, ASSETS / "robustness-paid-only.png"
    )

    growth = fastest_growing(share, counts, GROWTH_BASE, GROWTH_END, top=15)
    growth_wide = fastest_growing(share, counts, PLOT_START, PLOT_END, top=15)

    summary = {
        "meta": {
            **meta,
            "plot_window": [PLOT_START, PLOT_END],
            "growth_window": [GROWTH_BASE, GROWTH_END],
            "min_base_games": MIN_BASE_GAMES,
        },
        "coverage": {
            str(year): {
                "games": int(row.games),
                "with_tags": int(row.with_tags),
                "coverage_pct": round(row.coverage * 100, 1),
                "avg_tags_per_game": round(row.avg_tags, 2),
            }
            for year, row in per_year.iterrows()
        },
        "line_tags": line_tags,
        "heat_tags": heat_tags,
        "growth_main": [
            {
                "tag": tag,
                "base_pct": round(row.base_share * 100, 2),
                "end_pct": round(row.end_share * 100, 2),
                "delta_pp": round(row.delta_pp, 2),
                "base_games": int(row.base_games),
                "end_games": int(row.end_games),
            }
            for tag, row in growth.iterrows()
        ],
        "growth_wide_window": [
            {
                "tag": tag,
                "base_pct": round(row.base_share * 100, 2),
                "end_pct": round(row.end_share * 100, 2),
                "delta_pp": round(row.delta_pp, 2),
                "base_games": int(row.base_games),
                "end_games": int(row.end_games),
            }
            for tag, row in growth_wide.iterrows()
        ],
        "robustness": {
            "tags": robust_tags,
            "free_share_by_year_pct": {
                str(year): {
                    "all_games": round(row.free_share_all * 100, 1),
                    "tagged_games": round(row.free_share_tagged * 100, 1),
                }
                for year, row in per_year.iterrows()
            },
            "note": "缺失标签的游戏以免费游戏为主；上表是免费游戏在「全部游戏」与"
            "「有标签游戏」中的占比落差，落差越大说明缺失越非随机。",
        },
        "category_coverage": {
            str(year): {
                cat: round(tables["cat_share"].loc[year, cat] * 100, 1)
                for cat in tables["cat_share"].columns
            }
            for year in range(PLOT_START, PLOT_END + 1)
            if year in tables["cat_share"].index
        },
        "caveats": [
            "标签是抓取当时的 Steam 用户标签，不是当年标签；库中无当年的玩家数、销量或"
            "评论历史记录，不能用它判断某游戏在当年是否流行，也不能用现今拥有量反推历史热度。",
            "2026 年未纳入分析帧（口径 release_date < 2026-01-01）且尚未结束，"
            "其年度数量不可与完整年份直接比较。",
            "各年标签覆盖率不同，2021 年起逐年下降、2025 年不足 35%，"
            "覆盖率低的年份占比不可与覆盖率高的年份直接比较。",
            "多标签游戏在每个标签上重复计入，各标签占比之和大于 100%，不构成互斥分割。",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    print(
        json.dumps(
            {
                "游戏数": meta["games"],
                "明细行数": meta["rows"],
                "指纹": meta["sha256"][:12],
                "折线标签": line_tags,
                "覆盖率_2014_2020_2024_2025": [
                    round(per_year.coverage.get(y, float("nan")) * 100, 1)
                    for y in (2014, 2020, 2024, 2025)
                ],
                "增长最快_2014_2020": [
                    f"{tag} {row.base_share * 100:.1f}%→{row.end_share * 100:.1f}%"
                    f"({row.delta_pp:+.1f}pp)"
                    for tag, row in growth.head(8).iterrows()
                ],
                "报告": str(REPORT.relative_to(ROOT)),
                "图": sorted(p.name for p in ASSETS.glob("*.png")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
