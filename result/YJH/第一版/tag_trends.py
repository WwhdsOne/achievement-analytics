"""按发售年份统计 Steam 用户标签的占比演变（描述性分析，只读）。

研究问题
    不同类型 / 机制 / 题材 / 画风 / 玩家模式的标签，在 Steam 各年发售的游戏里
    占比如何变化。**主结果只回答「游戏类型（genre / subgenre）结构如何变化」**；
    机制、题材、画风、玩家模式、制作与发行属性各出一张**补充增长榜**，不并入主榜。
    这样主榜的每一行都可比「类型」，不会被 Colorful、Singleplayer 这类非类型标签
    稀释成混合维度的排名。

统计口径（固定，改口径必须同步改本 docstring 与实验记录）
    年份        = ``steam_appdetails.release_date`` 的年份。
    样本        = ``steam_appdetails.type = 'game'`` 且 ``release_date < 2026-01-01``。
                  **应用类型是唯一的样本判据**——不因为某款游戏带了软件 / 影片类
                  标签就把整款游戏删掉（见「非游戏标签」）。当前全库均为
                  ``type='game'``，因此该判据不改变任一现有数值，只是把它落实成
                  可核验的规则。
    标签源      = ``game_tags`` 中 ``source='steamspy' AND kind='theme'``。
                  ⚠️ ``kind`` 是本项目的**入库标记**（当前 schema 只允许
                  ``theme`` / ``platform``），**不等于**分析层面的类型/机制/题材
                  分类——入库时每个 SteamSpy 标签都统一写成 ``kind='theme'``。
                  语义分类只在本脚本的 ``DIMENSIONS`` 里做。
    官方对照    = ``steam_appdetails.valve_genres``（Steam 官方粗粒度类型），
                  只作对照，**不默认它优于细分标签**，并单独报告覆盖率。
    某标签在年份 y 的占比
                = 该年含该标签的游戏数 ÷ 该年**有效标签游戏数**。
    「有效标签游戏」= 该年至少有一个 SteamSpy 标签的游戏（``with_tags``）。
    所有维度**共用这一个固定样本**与同一个分母，各维度另报自身标签覆盖率，避免
    换分母后误比。
    多标签游戏在每个标签上**重复计入**，因此各标签占比之和**必然大于 100%**，
    不构成互斥分割。

维度映射（版本化的人工规则）
    ``DIMENSIONS`` 带版本号 ``TAXONOMY_VERSION``；**同一标签只归一个维度**，
    冲突会在导入时直接报错而不是静默覆盖。归类规则：

    * 「类型与子类型」只收回答「这是什么游戏」的玩法门类（含其子类型）；
    * 程序生成、编辑器、自定义、模组、建造、自动化、战斗/物理等**机制与功能**
      另立一维，不再混进类型；
    * Indie、抢先体验、免费、众筹、引擎工具等**制作与发行属性**另立一维——它们
      描述的是谁做的、怎么发行，而不是玩法是什么；
    * 交叉语义标签按「对分析问题最有解释力的那一面」归类，逐例见
      ``_CROSSWALK_NOTES``。

    库中未被任何维度命中的标签统一落到「其他」，并输出 ``unmapped-tags.csv``
    清单（含游戏数），便于下一版映射补漏。

必须在结论中同时报告的四条局限
    1. 标签是**抓取当时**的 Steam 用户标签，不是当年标签；库中没有当年的
       玩家数 / 销量 / 评论历史记录。标签票数描述的是**游戏属性**，**不等于
       「玩家更愿意玩」**。本分析支持的结论只是「抓取时标签所描述的、不同发售
       年份游戏的结构差异」；占比上升**不能**直接证明历史热度或玩家偏好上升。
    2. ``2026`` 年未纳入分析帧（项目口径为 ``release_date < 2026-01-01``），
       且该年尚未结束，其年度数量不可与完整年份直接比较。
    3. 各年标签覆盖率不同（近年抓取尚未完成），覆盖率低的年份占比不可与
       覆盖率高的年份直接比较——因此覆盖率随占比一并输出。
    4. 「仅付费游戏口径方向一致」只说明该趋势对**「剔除免费游戏」这一项样本
       限制**稳健，**不能证明已排除所有缺失偏差**（缺失本身就与「近年」和
       「免费属性」同时相关，两者无法用同一次切分同时剥离）。

运行::

    uv run python result/YJH/tag_trends.py        # 默认复用本地明细缓存
    uv run python result/YJH/tag_trends.py --refresh   # 重新只读查库
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
# result/<缩写>/，该目录自包含、可直接交付。明细缓存是 18 MB 级的中间物，留在项目
# 内部的 data/processed/（不入 Git），不占交付目录。
OUT_DIR = Path(__file__).resolve().parent
ASSETS = OUT_DIR
REPORT = OUT_DIR / "tag-trends.json"
UNMAPPED_CSV = OUT_DIR / "unmapped-tags.csv"
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
# 维度演变图中不画的维度：主维度在 2014–2024 全部年份都接近 100%
# （几乎每款游戏都至少带一个类型标签），画出来是一条压顶的水平线，既无信息量
# 又会压缩其余维度的纵向分辨率。「具体类型占比」由主结果图 genre-share-lines.png
# 承担，不再靠这条类目线。标签级统计不受影响。
DIMENSION_PLOT_SKIP = {"类型与子类型"}


def _tags(block: str) -> set[str]:
    """把 ``|`` 分隔的标签清单解析为规范化集合。"""
    return {_norm(part) for part in block.split("|") if part.strip()}


def _norm(tag: str) -> str:
    """规范化标签名：统一大小写并去掉标点，用于容忍库中的写法差异。"""
    return re.sub(r"[^a-z0-9]+", "", tag.lower())


# ---------------------------------------------------------------------------
# 维度映射（带版本）
# ---------------------------------------------------------------------------

TAXONOMY_VERSION = "2026-10-16.1"

MAIN_DIMENSION = "类型与子类型"
OTHER_DIMENSION = "其他"
NON_GAME_DIMENSION = "非游戏标签"

DIMENSIONS: dict[str, set[str]] = {
    # 只收「这是什么游戏」的玩法门类与子类型。制作属性、机制、编辑器与模组支持
    # 已在 v2026-10-16.1 移出（审查意见 2）。
    "类型与子类型": _tags("""
    Action | Adventure | Casual | Puzzle | Strategy | Simulation | RPG
    | Platformer | 2D Platformer | 3D Platformer | Precision Platformer
    | Puzzle-Platformer | Shooter | Arcade | Racing | Sports | Fighting
    | 2D Fighter | 3D Fighter | Spectacle fighter | Visual Novel | RTS | FPS
    | Metroidvania | Rogue-like | Rogue-lite | Roguelike Deckbuilder
    | Traditional Roguelike | Roguevania | Action Roguelike | Souls-like
    | Deckbuilding | Card Game | Card Battler | Trading Card Game
    | Tower Defense | Idler | Clicker | Rhythm | Sandbox | Survival
    | Open World | Open World Survival Craft | Management | Time Management
    | Turn-Based | Turn-Based Strategy | Turn-Based Combat | Turn-Based Tactics
    | Tactical | Tactical RPG | Strategy RPG | Real Time Tactics | Real-Time
    | Real-Time with Pause | Auto Battler | Battle Royale | MOBA
    | Walking Simulator | Point & Click | Hidden Object | Match 3 | Sokoban
    | Runner | Dungeon Crawler | Immersive Sim | Colony Sim | City Builder
    | Farming Sim | Life Sim
    | Dating Sim | Otome | Party Game | Board Game | Tabletop | Word Game
    | Solitaire | Education | Trivia | Beat 'em up | Hack and Slash
    | Bullet Hell | Shoot 'Em Up | Arena Shooter | Twin Stick Shooter
    | Top-Down Shooter | Third-Person Shooter | Looter Shooter | Hero Shooter
    | Boomer Shooter | Extraction Shooter | On-Rails Shooter
    | Character Action Game | Action RTS | 4X | Grand Strategy | Wargame
    | God Game | Political Sim | Outbreak Sim | Medical Sim | Job Simulator
    | Automobile Sim | Space Sim | Hobby Sim | Fishing | Hunting | Mining
    | Trading | Diplomacy
    | Typing | Spelling | Logic | Chess | Mahjong | Pinball | Mini Golf
    | Golf | Tennis | Basketball | Baseball | Football (Soccer)
    | Football (American) | Hockey | Cricket | Volleyball | Rugby | Bowling
    | Pool | Snooker | Boxing | Wrestling | Sniper | Archery | Naval Combat
    | Combat Racing | Vehicular Combat | Destruction | Parkour | Stealth
    | Hacking | Interactive Fiction | Choose Your Own Adventure | Escape Room
    | Minigames | Party | Creature Collector | Collectathon | Musou
    | Shop Keeper | Action-Adventure | Action RPG | Medical | Farming
    | JRPG | CRPG | Party-Based RPG | Mystery Dungeon | Social Deduction
    | Lemmings | Driving | Flight | Agriculture | Transportation
    | Offroad | Motorbike | Bikes | Cycling | Skating | Motocross
    | Skateboarding | Skiing | BMX | Snowboarding | ATV
    """),
    # v2026-10-16.1 新立：原「玩法类型」里的机制 / 编辑 / 模组 / 自定义/ 生成类标签
    # 全部迁到这里，另补 Exploration 等原先漏掉的机制标签。
    "机制与特色": _tags("""
    Procedural Generation | Level Editor | Character Customization
    | Gun Customization | Moddable | Mod | Crafting | Automation
    | Resource Management | Inventory Management | Base-Building
    | Hex Grid | Grid-Based Movement | Quick-Time Events | Time Manipulation
    | Bullet Time | Music-Based Procedural Generation
    | Exploration | Combat | Physics | Building | Investigation | Economy
    | Perma Death | Loot | Artificial Intelligence | Swordplay
    | Class-Based | Dice | Time Attack | Score Attack | Boss Rush
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
    | Futuristic | Nature | America | Cooking | Gambling
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
    # 原「模式与功能」：免费 / 抢先体验 / 众筹已按审查意见移入「制作与发行属性」。
    "玩家模式与支持": _tags("""
    Singleplayer | Multiplayer | Co-op | Local Co-Op | Online Co-Op | PvP
    | PvE | Massively Multiplayer | MMO | MMORPG | Controller | VR
    | Asymmetric VR | Split Screen | Team-Based
    | Competitive | Co-op Campaign | 4 Player Local | Asynchronous Multiplayer
    | Local Multiplayer | Touch-Friendly | Voice Control | TrackIR | 3D Vision
    | 6DOF | Intentionally Awkward Controls | e-sports | Mouse only
    | Cross-Platform Multiplayer | LAN | LAN Co-Op | Sound card | Foreign
    """),
    # v2026-10-16.1 新立：商业 / 发行形态，与玩法无关，不做主榜。
    "制作与发行属性": _tags("""
    Indie | Free to Play | Early Access | Crowdfunded | Kickstarter
    | RPGMaker | GameMaker
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
    | Villain Protagonist | Family Friendly | Fast-Paced | Narrative
    """),
}

# 展示顺序（JSON 与图例都用它，保证每次运行的列序稳定）。
DIMENSION_ORDER = [
    MAIN_DIMENSION,
    "机制与特色",
    "题材设定",
    "美术与呈现",
    "玩家模式与支持",
    "制作与发行属性",
    "氛围与叙事",
    OTHER_DIMENSION,
    NON_GAME_DIMENSION,
]
# 补充图的文件名后缀（ASCII，避免中文文件名在各平台的编码差异）。
DIMENSION_FILEKEY = {
    "机制与特色": "feature",
    "题材设定": "theme",
    "美术与呈现": "visual",
    "玩家模式与支持": "players",
    "制作与发行属性": "production",
    "氛围与叙事": "mood",
}

# 非游戏标签：Steam 上的创作 / 办公软件与影片类标签。
# ⚠️ 只用于**标注标签**，不用于删除游戏——样本判据是 ``steam_appdetails.type``。
NON_GAME_TAGS: set[str] = _tags("""
    Design & Illustration | Programming | Audio Production | Photo Editing
    | Video Production | Web Publishing | Software Training | Utilities
    | Game Development | Hardware | Benchmark | Software | Movie
    | Documentary | Feature Film | Gaming | Coding | Steam Machine
    | Animation & Modeling | 360 Video
""")

# 交叉语义标签的归类理由（审查意见 2 要求「说明采用的归类规则」）。
_CROSSWALK_NOTES: dict[str, str] = {
    "Indie": "官方 valve_genres 也把它列为类型，但它描述的是制作/发行身份而非玩法，"
    "会与「独立」绑定的整体规模共振，故归「制作与发行属性」，并在对照图中说明。",
    "Early Access / Free to Play": "商业发行形态，归「制作与发行属性」；"
    "与游戏玩法结构无关。",
    "Exploration": "原映射缺失、落到「其他」；它是玩法活动而非玩法门类，归「机制与特色」。",
    "Dice / Time Attack / Score Attack / Boss Rush": "挑战与判定机制，归「机制与特色」，"
    "不归类型。",
    "Time Management / Management": "Steam 官方把它们当作玩法门类（休闲管理类游戏），"
    "故留在「类型与子类型」；而同族的 Resource / Inventory Management 是机制，归「机制与特色」。",
    "Farming / Agriculture": "作为玩法门类（农作模拟）归「类型与子类型」。",
    "Gambling / Cooking / Nature / Futuristic": "题材设定，归「题材设定」。",
    "RPGMaker / GameMaker": "引擎与制作工具标记，归「制作与发行属性」。",
    "Foreign / Local Multiplayer": "本地化与联机支持功能，归「玩家模式与支持」。",
}


def _dimension_index() -> dict[str, str]:
    """展开 规范化标签 → 维度 的索引；同一标签出现在两个维度时直接报错。

    静默覆盖会让归类变得不可审计，因此这里选择 fail-fast。
    """
    index: dict[str, str] = {}
    for dim, tags in DIMENSIONS.items():
        for tag in tags:
            if tag in index:
                raise ValueError(f"标签 {tag!r} 同时归入「{index[tag]}」与「{dim}」")
            index[tag] = dim
    for tag in NON_GAME_TAGS:
        if tag in index:
            raise ValueError(f"标签 {tag!r} 既是游戏标签又是非游戏标签")
        index[tag] = NON_GAME_DIMENSION
    return index


def _app_type_counts(tags: pd.DataFrame) -> dict[str, int]:
    """按 appid 去重统计应用类型——样本核验用（不是行数，别把标签行算进去）。"""
    return {
        str(k): int(v)
        for k, v in tags.drop_duplicates("appid")
        .app_type.astype(str)
        .value_counts()
        .items()
    }


def load_detail(
    refresh: bool = False,
) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    """提取 (appid, year, app_type, is_free, tag) 明细与官方 genre 对照表。

    默认复用本地缓存。查库路径用 ``REPEATABLE READ`` + ``SET TRANSACTION
    READ ONLY`` 保证一次一致性读，且从机制上排除写库的可能。结果落本地 pickle
    （一个含 ``tags`` / ``official`` 两张表的字典），使同一份输入可反复出图而
    不必重查云库（对齐项目「固定输入可复现」的做法）。

    本机没有 ``data/processed/snapshots/`` 下的既有快照，因此**未写入
    ``dataset_versions``**——库对本 agent 只读；改以输入指纹记录版本。
    """
    if DETAIL_CACHE.exists() and not refresh:
        try:
            blob = pd.read_pickle(DETAIL_CACHE)
        except Exception:
            blob = None
        # 旧版缓存是单张 DataFrame（无 app_type / 无官方 genre 表），格式不符即重取。
        if (
            isinstance(blob, dict)
            and {"tags", "official"} <= set(blob)
            and {"year", "is_free", "tag", "app_type"} <= set(blob["tags"].columns)
            and {"year", "is_free", "genre"} <= set(blob["official"].columns)
        ):
            meta = json.loads(DETAIL_CACHE.with_suffix(".meta.json").read_text("utf-8"))
            # 应用类型分布每次现算：它是样本核验量，不能沿用可能过期的旧元数据。
            meta["app_type_counts"] = _app_type_counts(blob["tags"])
            meta["cache"] = "hit"
            return blob, meta

    engine = get_engine()
    tags_query = text("""
        SELECT a.appid,
               extract(year FROM a.release_date)::int AS year,
               coalesce(a.is_free, false) AS is_free,
               coalesce(a.type, '(null)') AS app_type,   -- 样本判据：只有 game 进分析
               t.tag
        FROM steam_appdetails a
        LEFT JOIN game_tags t
               ON t.appid = a.appid
              AND t.source = 'steamspy' AND t.kind = 'theme'
        WHERE a.release_date < make_date(2026, 1, 1)
        """)
    # 官方粗粒度类型：同一款游戏可有多个 genre，摊平成一行一 genre，用于对照。
    official_query = text("""
        SELECT a.appid,
               extract(year FROM a.release_date)::int AS year,
               coalesce(a.is_free, false) AS is_free,
               g AS genre
        FROM steam_appdetails a
        CROSS JOIN LATERAL unnest(a.valve_genres) AS g
        WHERE a.release_date < make_date(2026, 1, 1)
        """)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            tags = pd.read_sql(tags_query, conn)
            official = pd.read_sql(official_query, conn)
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

    tags["app_type"] = tags["app_type"].astype("category")
    blob = {"tags": tags, "official": official}

    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(tags, index=False).values.tobytes())
    digest.update(pd.util.hash_pandas_object(official, index=False).values.tobytes())
    type_counts = _app_type_counts(tags)
    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(tags),
        "games": int(tags.appid.nunique()),
        "official_rows": len(official),
        "app_type_counts": type_counts,
        "app_type_counts_note": "按 appid 去重后的条目数（样本核验用）",
        "sha256": digest.hexdigest(),
        "steamspy_fetch_window": dict(fetched) if fetched else None,
        "registered_version": None,
        "note": "本机无快照文件，故直接只读查库；未写入 dataset_versions（库对本 agent 只读）",
    }
    DETAIL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(blob, DETAIL_CACHE)
    DETAIL_CACHE.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta["cache"] = "miss"
    return blob, meta


def build_tables(frames: dict[str, pd.DataFrame]) -> dict[str, object]:
    """构造年度统计表：覆盖率、标签占比矩阵、维度占比矩阵、付费子样本、官方对照。

    样本在此处一次性确定（``app_type == 'game'``），此后所有维度共用同一分母。
    """
    raw = frames["tags"]
    is_game = raw.app_type.astype(str).eq("game")
    # 应用类型核验：非 game 的 appid 在这里被排除，并记录到 sample 以便报告。
    dropped_appids = sorted(set(raw.loc[~is_game, "appid"].tolist()))
    frame = raw.loc[is_game].drop(columns=["app_type"]).copy()
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

    # 维度归属：标签级 → 维度级。未命中的标签记入「其他」，非游戏标签单列。
    dim_of_tag = _dimension_index()
    normalized = tagged.tag.map(_norm)
    tagged["dimension"] = normalized.map(dim_of_tag).fillna(OTHER_DIMENSION)
    dedup = tagged.drop_duplicates(["appid", "dimension"])
    dim_counts = (
        dedup.groupby(["year", "dimension"]).appid.nunique().unstack(fill_value=0)
    )
    dim_counts = dim_counts.reindex(columns=DIMENSION_ORDER).fillna(0).astype(int)
    dim_share = dim_counts.div(per_year.with_tags, axis=0)

    # 每个维度实际覆盖到的标签（用库里的原始写法），供分维度增长榜过滤。
    dim_tag_columns: dict[str, list[str]] = {}
    for dim in DIMENSION_ORDER:
        dim_tag_columns[dim] = [
            col
            for col in counts.columns
            if dim_of_tag.get(_norm(col), OTHER_DIMENSION) == dim
        ]

    # 未分类标签清单：只统计进入样本、且未被任何维度命中的标签。
    total_by_tag = counts.sum().sort_values(ascending=False)
    unmapped = pd.DataFrame(
        {
            "tag": [t for t in total_by_tag.index if dim_of_tag.get(_norm(t)) is None],
            "games": [
                int(total_by_tag[t]) for t in total_by_tag.index
                if dim_of_tag.get(_norm(t)) is None
            ],
        }
    )

    # 稳健性口径：只保留付费游戏。缺失标签的绝大多数是免费游戏，
    # 若趋势在两套口径下方向一致，说明它对「剔除免费游戏」这一项样本限制稳健
    # （注意：这不等于已排除所有缺失偏差）。
    paid = tagged[~tagged.is_free]
    paid_per_year = paid.groupby("year").appid.nunique()
    paid_counts = paid.groupby(["year", "tag"]).appid.nunique().unstack(fill_value=0)
    paid_counts = paid_counts.reindex(columns=sorted(paid_counts.columns))
    paid_share = paid_counts.div(paid_per_year, axis=0)

    # 官方粗粒度类型对照：与主分析共用同一个固定分母（with_tags），
    # 另单独报告 valve_genres 自身覆盖率，避免「换分母后误比」。
    official = frames["official"]
    official = official.loc[official.appid.isin(set(frame.appid))]
    official_counts = (
        official.groupby(["year", "genre"]).appid.nunique().unstack(fill_value=0)
    )
    official_counts = official_counts.reindex(
        columns=sorted(official_counts.columns)
    ).fillna(0)
    official_share = official_counts.div(per_year.with_tags, axis=0)
    official_coverage = (
        official.groupby("year").appid.nunique().reindex(per_year.index).fillna(0)
        / per_year.games.replace(0, np.nan)
    )

    return {
        "per_year": per_year,
        "counts": counts,
        "share": share,
        "paid_counts": paid_counts,
        "paid_share": paid_share,
        "paid_per_year": paid_per_year,
        "dim_counts": dim_counts,
        "dim_share": dim_share,
        "dim_tag_columns": dim_tag_columns,
        "unmapped": unmapped,
        "official_counts": official_counts,
        "official_share": official_share,
        "official_coverage": official_coverage,
        "sample": {
            "rule": "steam_appdetails.type = 'game' 且 release_date < 2026-01-01；"
            "不因标签内容删除任何游戏",
            "games": int(frame.appid.nunique()),
            "app_type_counts": _app_type_counts(raw),
            "app_type_counts_note": "按 appid 去重后的条目数（应用类型核验用）",
            "dropped_non_game": len(dropped_appids),
            "dropped_appids": dropped_appids[:50],
        },
    }


def fastest_growing(
    share: pd.DataFrame,
    counts: pd.DataFrame,
    base: int,
    end: int,
    top: int = 12,
    tags: list[str] | None = None,
) -> pd.DataFrame:
    """在两端年份间比较占比变化（百分点），并给出相对增幅。

    ``tags`` 非空时只在给定的标签集合内排名——主榜据此**只比较类型与子类型**，
    其余维度各自单独排名（审查意见 1）。
    只保留基准年游戏数达到 ``MIN_BASE_GAMES`` 的标签——小基数标签的占比
    分母极小，一年涨三款就能造出巨大增幅，不具解释力。
    """
    if tags is not None:
        keep = [t for t in counts.columns if t in set(tags)]
        counts = counts[keep]
        share = share[keep]
    if counts.empty:
        return pd.DataFrame(
            columns=["base_share", "end_share", "base_games", "end_games", "delta_pp", "ratio"]
        )
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


def growth_records(growth: pd.DataFrame) -> list[dict[str, object]]:
    """把增长榜 DataFrame 转成报告里的记录列表（统一一处，避免口径漂移）。"""
    return [
        {
            "tag": tag,
            "base_pct": round(row.base_share * 100, 2),
            "end_pct": round(row.end_share * 100, 2),
            "delta_pp": round(row.delta_pp, 2),
            "base_games": int(row.base_games),
            "end_games": int(row.end_games),
        }
        for tag, row in growth.iterrows()
    ]


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
    share: pd.DataFrame,
    counts: pd.DataFrame,
    path: Path,
    line_count: int = 12,
    tags: list[str] | None = None,
) -> list[str]:
    """多标签占比随年份的折线图（取样本窗口内游戏数最多的若干标签）。

    ``tags`` 非空时只在该集合内取标签——主结果图据此**只画类型与子类型**。
    终点数值并入图例而非贴在曲线尾部——多条线在 40–50% 区间汇聚时，
    曲线末端的直接标注会互相叠压，图例带值既不丢信息也不遮挡。
    """
    pool = counts if tags is None else counts[[t for t in counts.columns if t in set(tags)]]
    if pool.empty:
        return []
    window = pool.loc[PLOT_START:PLOT_END].sum().sort_values(ascending=False)
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


def plot_growth_bars(
    growth: pd.DataFrame,
    path: Path,
    title: str,
    subtitle: str,
    top: int = 10,
) -> list[str]:
    """按占比变化（百分点）排序的横向条形图，用于分维度增长榜。

    每个维度各出一张：主维度是主榜，其余维度是补充榜，**不混进同一张图**，
    避免把「机制变多」读成「类型变强」。各柱标注两端占比与两端游戏数。
    """
    frame = growth.head(top)
    if frame.empty:
        return []
    frame = frame.iloc[::-1]  # 增幅最大的画在最上面
    fig, ax = plt.subplots(
        figsize=(10.6, 0.5 * len(frame) + 2.6), facecolor="#f7f8fa"
    )
    style_axis(ax)
    colors = ["#b65267" if d >= 0 else "#3761b7" for d in frame.delta_pp]
    ax.barh(frame.index, frame.delta_pp, color=colors, height=0.62)
    neg = float(frame.delta_pp.min())
    pos = float(frame.delta_pp.max())
    span = max(abs(neg), abs(pos), 1.0)
    # 柱端标注文字较长（两端占比 + 两端游戏数），必须按标注实际占位留白，
    # 否则负增长的标签会被裁到坐标区之外（标签少的小维度尤其明显）。
    room = span * 0.95
    ax.set_xlim(
        (neg - room) if neg < 0 else -span * 0.06,
        (pos + room) if pos > 0 else span * 0.06,
    )
    for idx, (tag, row) in enumerate(frame.iterrows()):
        offset = span * 0.02
        ax.text(
            row.delta_pp + (offset if row.delta_pp >= 0 else -offset),
            idx,
            f"{row.base_share * 100:.0f}%→{row.end_share * 100:.0f}%"
            f"（{int(row.base_games)}→{int(row.end_games)} 款）",
            va="center",
            ha="left" if row.delta_pp >= 0 else "right",
            fontsize=9.5,
            color="#3b424b",
        )
    ax.axvline(0, color="#c3cad3", linewidth=1)
    ax.set_xlabel("计入该标签的游戏占比变化（百分点）", fontsize=11.5, color="#5c6470")
    ax.grid(axis="x", color="#e1e5ea", linewidth=0.7)
    ax.set_title(title, fontsize=13, color="#262d35", pad=18)
    ax.text(
        0.0,
        1.02,
        subtitle,
        transform=ax.transAxes,
        fontsize=10,
        color="#5c6470",
        ha="left",
    )
    fig.tight_layout(pad=1.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return list(frame.index)


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
        label="其中带 SteamSpy 标签者（计入占比分母）",
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
        if year in coverage.index:
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


def plot_dimensions(dim_share: pd.DataFrame, path: Path) -> None:
    """维度级占比演变：跨维度的宏观走势（固定样本、共用分母）。

    ``DIMENSION_PLOT_SKIP`` 中的维度不绘制（当前为主维度，见该常量注释）；
    主维度的内部结构由图 genre-share-lines.png 承担。
    """
    years = [y for y in range(PLOT_START, PLOT_END + 1) if y in dim_share.index]
    present = [
        c
        for c in DIMENSION_ORDER
        if c in dim_share.columns
        and c not in DIMENSION_PLOT_SKIP
        and dim_share[c].loc[years].max() > 0
    ]

    fig, ax = plt.subplots(figsize=(11.5, 5.4), facecolor="#f7f8fa")
    style_axis(ax)
    for cat, color in zip(present, LINE_COLORS):
        values = dim_share.loc[years, cat] * 100
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


def plot_official_genre(
    official_share: pd.DataFrame, official_coverage: pd.Series, path: Path, top: int = 8
) -> list[str]:
    """官方粗粒度类型对照图：Steam ``valve_genres`` 的年度占比走势。

    用途只是「先用官方类型做简单对照」——分母沿用主分析的固定样本，图例里
    同时给出官方字段自身的覆盖率，避免把「细分标签更细」误读成「官方更差」。
    """
    years = [y for y in range(PLOT_START, PLOT_END + 1) if y in official_share.index]
    window = official_share.loc[years].mean().sort_values(ascending=False)
    picked = list(window.head(top).index)
    picked.sort(key=lambda g: -official_share.loc[PLOT_END, g])

    fig, ax = plt.subplots(figsize=(11.5, 5.8), facecolor="#f7f8fa")
    style_axis(ax)
    for genre, color in zip(picked, LINE_COLORS):
        values = official_share.loc[years, genre] * 100
        ax.plot(
            years,
            values,
            marker="o",
            markersize=4,
            linewidth=2,
            color=color,
            label=f"{genre}（{PLOT_END} 年 {values.iloc[-1]:.0f}%）",
        )
    ax.set_xticks(years)
    ax.set_ylabel("该年含此官方类型的游戏占比（%）", fontsize=12, color="#5c6470")
    ax.set_xlabel("发售年份", fontsize=12, color="#5c6470")
    ax.grid(axis="y", color="#e1e5ea", linewidth=0.7)
    ax.set_xlim(PLOT_START - 0.4, PLOT_END + 0.4)
    cover = official_coverage.reindex(range(PLOT_START, PLOT_END + 1))
    ax.set_title(
        "官方 valve_genres 对照（粗粒度）"
        f"｜覆盖率 {cover.min() * 100:.1f}%–{cover.max() * 100:.1f}%，与细分标签共用同一分母",
        fontsize=12.5,
        color="#262d35",
        pad=12,
    )
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


def plot_robustness(
    share: pd.DataFrame,
    paid_share: pd.DataFrame,
    counts: pd.DataFrame,
    path: Path,
    top: int = 6,
) -> list[str]:
    """稳健性对照：全样本口径 vs 仅付费游戏口径。

    标签缺失高度偏向免费游戏，因此把「是否剔除免费游戏」作为敏感性检验。
    取样本窗口内占比变化最大的标签逐个对照——两条线方向一致，只说明该走势
    对**这一项**样本限制稳健，**不等于**已排除所有缺失偏差。
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
    """跑完整条链路：只读取数 → 年度统计 → 分维度出图 → 写本地报告。"""
    parser = argparse.ArgumentParser(description="按发售年份的标签占比演变")
    parser.add_argument(
        "--refresh", action="store_true", help="忽略本地明细缓存，重新只读查库"
    )
    args = parser.parse_args()
    plt.rcParams.update({"font.family": pick_font(), "axes.unicode_minus": False})
    ASSETS.mkdir(parents=True, exist_ok=True)

    frames, meta = load_detail(refresh=args.refresh)
    tables = build_tables(frames)
    per_year = tables["per_year"]
    counts, share = tables["counts"], tables["share"]
    dim_share = tables["dim_share"]
    dim_tag_columns = tables["dim_tag_columns"]

    # 标签级结果（混合维度，只作标签趋势用，不作为类型结论）
    line_tags = plot_lines(share, counts, ASSETS / "tag-share-lines.png")
    heat_tags = plot_heatmap(share, counts, ASSETS / "tag-year-heatmap.png")
    plot_coverage(per_year, ASSETS / "tag-coverage.png")
    plot_dimensions(dim_share, ASSETS / "category-share-lines.png")
    robust_tags = plot_robustness(
        share, tables["paid_share"], counts, ASSETS / "robustness-paid-only.png"
    )

    # 标签级排名：混合维度，只作**标签趋势**参考，绝不当类型结论用
    # （原报告的主榜就是这份数据，保留以免丢失信息，但降级为参考）。
    growth_all_short = fastest_growing(share, counts, GROWTH_BASE, GROWTH_END, top=15)
    growth_all_wide = fastest_growing(share, counts, PLOT_START, PLOT_END, top=15)

    # 主结果：**只比较类型与子类型**（审查意见 1、3）
    genre_tags = dim_tag_columns[MAIN_DIMENSION]
    genre_line_tags = plot_lines(
        share, counts, ASSETS / "genre-share-lines.png", line_count=12, tags=genre_tags
    )
    growth_short = fastest_growing(
        share, counts, GROWTH_BASE, GROWTH_END, top=15, tags=genre_tags
    )
    growth_wide = fastest_growing(
        share, counts, PLOT_START, PLOT_END, top=15, tags=genre_tags
    )
    plot_growth_bars(
        growth_short,
        ASSETS / "genre-growth-bars.png",
        f"主结果：类型与子类型占比变化（{GROWTH_BASE}→{GROWTH_END}）",
        f"只含「类型与子类型」维度；基准年游戏数 ≥{MIN_BASE_GAMES} 款；"
        "两端年份覆盖率均 ≥98%",
        top=12,
    )

    # 补充结果：其余维度**各出一张**增长榜，不与主榜混合
    dim_growth: dict[str, list[dict[str, object]]] = {}
    dim_figures: dict[str, str] = {}
    for dim in DIMENSION_ORDER:
        if dim in (MAIN_DIMENSION, OTHER_DIMENSION, NON_GAME_DIMENSION):
            continue
        growth = fastest_growing(
            share,
            counts,
            GROWTH_BASE,
            GROWTH_END,
            top=15,
            tags=dim_tag_columns.get(dim, []),
        )
        dim_growth[dim] = growth_records(growth)
        key = DIMENSION_FILEKEY[dim]
        name = f"dimension-growth-{key}.png"
        picked = plot_growth_bars(
            growth,
            ASSETS / name,
            f"补充：{dim}标签占比变化（{GROWTH_BASE}→{GROWTH_END}）",
            f"与主结果共用固定样本与基准年门槛（≥{MIN_BASE_GAMES} 款）；"
            "仅作该维度的补充榜，不与类型榜合并解读",
            top=10,
        )
        if picked:
            dim_figures[dim] = name

    # 官方粗粒度类型对照
    official_picked = plot_official_genre(
        tables["official_share"],
        tables["official_coverage"],
        ASSETS / "official-genre-compare.png",
    )

    # 未分类标签清单：写 CSV，便于下一版映射补漏
    unmapped: pd.DataFrame = tables["unmapped"]
    unmapped.to_csv(UNMAPPED_CSV, index=False, encoding="utf-8-sig")

    taxonomy = {
        "version": TAXONOMY_VERSION,
        "main_dimension": MAIN_DIMENSION,
        "dimension_order": DIMENSION_ORDER,
        "rules": [
            "同一标签只归一个维度，冲突在导入时直接报错。",
            "类型与子类型只收回答「这是什么游戏」的玩法门类与子类型。",
            "程序生成、编辑器、自定义、模组、建造、自动化等机制归「机制与特色」。",
            "Indie、抢先体验、免费、众筹、引擎工具等归「制作与发行属性」，描述发行形态而非玩法。",
            "交叉语义标签按「对分析问题最有解释力的那一面」归类。",
        ],
        "crosswalk_notes": _CROSSWALK_NOTES,
        "dimensions": {
            dim: sorted(DIMENSIONS[dim]) for dim in DIMENSION_ORDER if dim in DIMENSIONS
        },
        "non_game_tags": sorted(NON_GAME_TAGS),
        "non_game_note": "只标注标签、不删除游戏；样本判据是 steam_appdetails.type。",
        "unmapped_count": int(len(unmapped)),
        "unmapped_tags": [
            {"tag": str(r.tag), "games": int(r.games)} for r in unmapped.itertuples()
        ],
    }

    summary = {
        "meta": {
            **meta,
            "taxonomy_version": TAXONOMY_VERSION,
            "plot_window": [PLOT_START, PLOT_END],
            "growth_window": [GROWTH_BASE, GROWTH_END],
            "min_base_games": MIN_BASE_GAMES,
            "sample_rule": tables["sample"]["rule"],
        },
        "scope": {
            "statement": "本分析支持结论：抓取时标签所描述的、不同发售年份游戏的结构差异。",
            "not_supported": [
                "不能据此判断某款游戏在发售当年是否流行，也不能用现今拥有量反推历史热度。",
                "标签票数描述游戏属性，不等于「玩家更愿意玩」，不能当作玩家偏好强度。",
                "占比上升不能直接证明历史热度或玩家偏好上升，只能说明该属性在近年发售的游戏中更常见。",
            ],
            "main_result_dimension": MAIN_DIMENSION,
            "supplementary_dimensions": [
                d for d in DIMENSION_ORDER
                if d not in (MAIN_DIMENSION, OTHER_DIMENSION, NON_GAME_DIMENSION)
            ],
        },
        "sample": tables["sample"],
        "taxonomy": taxonomy,
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
        "tag_level": {
            "note": "全部标签的排名（混合类型 / 机制 / 题材 / 画风 / 玩家模式 / 发行属性），"
            "只作标签趋势参考，**不可整体解释为类型增长排名**；类型结论请看 main_genre。",
            "figure": "tag-share-lines.png",
            "growth_main": growth_records(growth_all_short),
            "growth_wide_window": growth_records(growth_all_wide),
        },
        "main_genre": {
            "dimension": MAIN_DIMENSION,
            "line_tags": genre_line_tags,
            "figure": "genre-share-lines.png",
            "growth_figure": "genre-growth-bars.png",
            "growth_main": growth_records(growth_short),
            "growth_wide_window": growth_records(growth_wide),
        },
        "growth_by_dimension": {
            dim: {
                "records": records,
                "figure": dim_figures.get(dim),
            }
            for dim, records in dim_growth.items()
        },
        "official_genre": {
            "source": "steam_appdetails.valve_genres",
            "figure": "official-genre-compare.png",
            "picked": official_picked,
            "coverage_pct": {
                str(year): round(float(v) * 100, 1)
                for year, v in tables["official_coverage"].items()
                if year >= PLOT_START
            },
            "share_pct": {
                str(year): {
                    g: round(float(tables["official_share"].loc[year, g]) * 100, 1)
                    for g in official_picked
                }
                for year in range(PLOT_START, PLOT_END + 1)
                if year in tables["official_share"].index
            },
            "note": "官方类型粗粒度且与本项目细分标签口径不同，仅作对照；"
            "不默认官方类型优于细分标签，两者共用同一固定分母。",
        },
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
            "「有标签游戏」中的占比落差，落差越大说明缺失越非随机。"
            "「仅付费游戏口径方向一致」只说明趋势对剔除免费游戏这一项样本限制稳健，"
            "不能证明已排除所有缺失偏差。",
        },
        "dimension_coverage": {
            str(year): {
                dim: round(float(dim_share.loc[year, dim]) * 100, 1)
                for dim in DIMENSION_ORDER
                if dim in dim_share.columns
            }
            for year in range(PLOT_START, PLOT_END + 1)
            if year in dim_share.index
        },
        "dimension_note": "维度覆盖率 = 该年该维度至少命中一个标签的游戏 ÷ 该年有效标签游戏数，"
        "所有维度共用同一固定样本与分母；主维度接近 100% 属正常（几乎每款游戏都有类型标签），"
        "因此它的内部结构由图 genre-share-lines.png 与 genre-growth-bars.png 呈现。",
        "caveats": [
            "标签是抓取当时的 Steam 用户标签，不是当年标签；库中无当年的玩家数、销量或"
            "评论历史记录，不能用它判断某游戏在当年是否流行，也不能用现今拥有量反推历史热度。",
            "标签票数描述的是游戏属性，不等于「玩家更愿意玩」；本分析支持的结论只是"
            "抓取时标签所描述的不同发售年份游戏结构差异，占比上升不能直接证明历史热度上升。",
            "2026 年未纳入分析帧（口径 release_date < 2026-01-01）且尚未结束，"
            "其年度数量不可与完整年份直接比较。",
            "各年标签覆盖率不同，2021 年起逐年下降、2025 年不足 35%，"
            "覆盖率低的年份占比不可与覆盖率高的年份直接比较。",
            "多标签游戏在每个标签上重复计入，各标签占比之和大于 100%，不构成互斥分割。",
            "「仅付费游戏口径方向一致」只说明趋势对剔除免费游戏这一项样本限制稳健，"
            "不能证明已排除所有缺失偏差。",
            "kind='theme' 是入库标记而非语义分类；类型 / 机制 / 题材等区分只由本脚本"
            "带版本的 DIMENSIONS 映射给出。",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    print(
        json.dumps(
            {
                "游戏数": meta["games"],
                "明细行数": meta["rows"],
                "样本外条目": tables["sample"]["dropped_non_game"],
                "指纹": meta["sha256"][:12],
                "维度映射版本": TAXONOMY_VERSION,
                "主结果维度": MAIN_DIMENSION,
                "主结果折线标签": genre_line_tags,
                "未分类标签数": int(len(unmapped)),
                "覆盖率_2014_2020_2024_2025": [
                    round(per_year.coverage.get(y, float("nan")) * 100, 1)
                    for y in (2014, 2020, 2024, 2025)
                ],
                "类型增长最快_2014_2020": [
                    f"{tag} {row.base_share * 100:.1f}%→{row.end_share * 100:.1f}%"
                    f"({row.delta_pp:+.1f}pp)"
                    for tag, row in growth_short.head(8).iterrows()
                ],
                "标签级榜首_混合维度_仅供参考": [
                    f"{tag} {row.delta_pp:+.1f}pp"
                    for tag, row in growth_all_short.head(5).iterrows()
                ],
                "各维度增长榜首": {
                    dim: (records[0]["tag"] if records else None)
                    for dim, records in dim_growth.items()
                },
                "报告": str(REPORT.relative_to(ROOT)),
                "未分类清单": str(UNMAPPED_CSV.relative_to(ROOT)),
                "图": sorted(p.name for p in ASSETS.glob("*.png")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
