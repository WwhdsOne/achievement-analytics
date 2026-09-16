-- ============================================================================
-- cleaning/schema.sql — 游戏级多源数据仓库 DDL
--
-- 执行：uv run python -c "from cleaning.db import get_engine, apply_schema; apply_schema(get_engine())"
--      或 psql -f cleaning/schema.sql
--
-- 设计原则
--   1. 每个数据源**一张表**，靠 appid 联表；`games` 只存身份（appid + 官方中英文名）
--   2. 每张源表都有 `fetched_at` —— 各源抓取时间不同，建模必须能绑定数据版本
--      （AGENTS.md：全局完成率 percent 随抓取批次漂移）
--   3. 全部幂等：CREATE ... IF NOT EXISTS / ALTER ... IF NOT EXISTS /
--      DROP VIEW + CREATE / COMMENT ON 覆盖写，可反复重跑
--   4. 写入顺序必须**父表 → 子表**：所有源表都 REFERENCES games(appid)
--   5. 注释一律用 COMMENT ON 写在库里（不是 -- 行注释），这样 psql \d+ 和
--      图形客户端都能看到；看全库说明：
--        SELECT obj_description('games'::regclass);
--        SELECT col_description('games'::regclass, ordinal_position), column_name
--          FROM information_schema.columns WHERE table_name='games';
--   6. 数据源：Steam appdetails / 全局成就完成率 / Steam 社区成就页 / SteamSpy / RAWG。
--      **IGDB 已于 2026-09-15 放弃**：它需 Twitch OAuth2，而 Twitch 两步验证在国内
--      手机号上走不通；其时长（RAWG playtime 已覆盖）、评分（RAWG metacritic 已覆盖）
--      价值已由 RAWG 承接，只剩系列归属属加分项，故整表移除。
-- ============================================================================

BEGIN;

-- ════════════════════════════════════════════════════════════════════════════
-- 一、表
-- ════════════════════════════════════════════════════════════════════════════

-- ── 1.1 身份表 ──────────────────────────────────────────────────────────────
-- 全库只有 appid 一个身份键；官方中英文名是查询其他数据源的入口

CREATE TABLE IF NOT EXISTS games (
    appid         INTEGER     PRIMARY KEY,
    name_en       TEXT        NOT NULL,
    name_zh       TEXT,
    source_title  TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1.2 Steam 商店 appdetails（免 key，官方权威数据）────────────────────────

CREATE TABLE IF NOT EXISTS steam_appdetails (
    appid            INTEGER     PRIMARY KEY REFERENCES games (appid) ON DELETE CASCADE,
    type             TEXT,
    is_free          BOOLEAN,
    price_cents      INTEGER,
    release_date     DATE,
    developers       TEXT[],
    publishers       TEXT[],
    valve_genres     TEXT[],
    valve_categories TEXT[],
    recommendations  INTEGER,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1.3 SteamSpy（免 key）：用户自定义标签 + owners/ccu ─────────────────────

CREATE TABLE IF NOT EXISTS steamspy_games (
    appid           INTEGER     PRIMARY KEY REFERENCES games (appid) ON DELETE CASCADE,
    owners          TEXT,
    ccu             INTEGER,
    positive        INTEGER,
    negative        INTEGER,
    average_forever INTEGER,
    median_forever  INTEGER,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1.4 RAWG（需 key）：评分 / 时长 / 弃坑与通关 —— Q2 因变量的主要来源 ─────

CREATE TABLE IF NOT EXISTS rawg_games (
    appid          INTEGER     PRIMARY KEY REFERENCES games (appid) ON DELETE CASCADE,
    rawg_id        INTEGER,
    name           TEXT,
    released       DATE,
    metacritic     INTEGER,
    rating         NUMERIC(3, 2),
    ratings_count  INTEGER,
    genres         TEXT[],
    playtime       INTEGER,
    added_count    INTEGER,
    status_yet     INTEGER,
    status_owned   INTEGER,
    status_beaten  INTEGER,
    status_toplay  INTEGER,
    status_dropped INTEGER,
    status_playing INTEGER,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1.5 成就（一行一成就）───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS achievements (
    appid        INTEGER      NOT NULL REFERENCES games (appid) ON DELETE CASCADE,
    position     INTEGER      NOT NULL CHECK (position >= 1),
    api_name     TEXT         NOT NULL,
    display_name TEXT         NOT NULL,
    description  TEXT,
    percent      NUMERIC(5, 2) NOT NULL CHECK (percent >= 0 AND percent <= 100),
    PRIMARY KEY (appid, api_name),
    UNIQUE (appid, position)
);

-- ── 1.6 标签（一行一「游戏, 来源, 标签」）────────────────────────────────────

CREATE TABLE IF NOT EXISTS game_tags (
    appid  INTEGER NOT NULL REFERENCES games (appid) ON DELETE CASCADE,
    source TEXT    NOT NULL,
    tag    TEXT    NOT NULL,
    votes  INTEGER,
    kind   TEXT    NOT NULL DEFAULT 'theme'
           CHECK (kind IN ('theme', 'platform')),
    PRIMARY KEY (appid, source, tag)
);

-- ── 1.7 抓取审计（断点续爬 / 增量判断的依据）────────────────────────────────

CREATE TABLE IF NOT EXISTS ingest_log (
    id         BIGSERIAL   PRIMARY KEY,
    appid      INTEGER,
    source     TEXT        NOT NULL,
    status     TEXT        NOT NULL
               CHECK (status IN ('ok', 'empty', 'skipped', 'error')),
    cache_key  TEXT,
    error      TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1.8 数据版本（建模复现用）───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dataset_versions (
    version  TEXT        PRIMARY KEY,
    built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    note     TEXT
);

-- ── 1.9 迁移：给已存在的库补新列 ────────────────────────────────────────────
-- CREATE TABLE IF NOT EXISTS 对**已存在**的表不会加列，所以列清单变更要在这里
-- 补一条 ALTER ... ADD COLUMN IF NOT EXISTS，schema.sql 才能对新库旧库都收敛。

ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS ratings_count  INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS playtime       INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS added_count    INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS status_yet     INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS status_owned   INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS status_beaten  INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS status_toplay  INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS status_dropped INTEGER;
ALTER TABLE rawg_games ADD COLUMN IF NOT EXISTS status_playing INTEGER;

-- ════════════════════════════════════════════════════════════════════════════
-- 二、索引
-- ════════════════════════════════════════════════════════════════════════════
-- 主键与外键已自动建索引；这里只补「实际会按它查」的列。
-- 复合主键的前缀列（如 achievements 的 appid）已被主键索引覆盖，不重复建。

-- 按标签反查游戏（做特征工程时高频：把某标签的游戏捞出来）
CREATE INDEX IF NOT EXISTS idx_game_tags_tag
    ON game_tags (tag);

-- 按标签来源与类型筛（区分 SteamSpy / RAWG，剔除平台功能标签）
CREATE INDEX IF NOT EXISTS idx_game_tags_source_kind
    ON game_tags (source, kind);

-- 按难度筛成就（Q2 的「极难成就」类特征）
CREATE INDEX IF NOT EXISTS idx_achievements_percent
    ON achievements (percent);

-- 按官方名查游戏（跨源名称对齐、人工核对时用）
CREATE INDEX IF NOT EXISTS idx_games_name_en
    ON games (name_en);

CREATE INDEX IF NOT EXISTS idx_games_name_zh
    ON games (name_zh);

-- 按发售年份切片（Q2 的控制变量；按年分组交叉验证也要走这里）
CREATE INDEX IF NOT EXISTS idx_appdetails_release_date
    ON steam_appdetails (release_date);

-- 抓取审计：查某款游戏的抓取历史 / 查某源最近一批
CREATE INDEX IF NOT EXISTS idx_ingest_appid
    ON ingest_log (appid);

CREATE INDEX IF NOT EXISTS idx_ingest_source
    ON ingest_log (source, fetched_at DESC);

-- ════════════════════════════════════════════════════════════════════════════
-- 三、视图
-- ════════════════════════════════════════════════════════════════════════════
-- 注意：``CREATE OR REPLACE VIEW`` **不能删除列**（Postgres 限制，会报
-- ``cannot drop columns from view``），所以改视图列清单时必须先 DROP 再 CREATE。
-- 视图是纯派生对象、不存数据，DROP 是安全的。2026-09-15 移除 IGDB 列时踩到。
-- 下面按依赖倒序 DROP（games_full 依赖 game_difficulty 与 game_engagement；
-- ingest_gaps 依赖 ingest_coverage）。

DROP VIEW IF EXISTS games_full      CASCADE;
DROP VIEW IF EXISTS ingest_gaps     CASCADE;
DROP VIEW IF EXISTS game_engagement CASCADE;
DROP VIEW IF EXISTS game_difficulty CASCADE;
DROP VIEW IF EXISTS ingest_coverage CASCADE;
DROP VIEW IF EXISTS ingest_latest   CASCADE;

-- ── 3.1 游戏级难度结构 ──────────────────────────────────────────────────────
-- 必须**先于 games_full** 创建（games_full 会 JOIN 它）。
-- 这是 Q2 的核心难度特征来源：一个游戏的成就完成率分布刻画它的难度结构。

CREATE OR REPLACE VIEW game_difficulty AS
SELECT
    appid,
    count(*)                                             AS ach_count,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY percent)  AS median_percent,
    percentile_cont(0.1) WITHIN GROUP (ORDER BY percent)  AS p10_percent,
    min(percent)                                         AS hardest_percent,
    max(percent)                                         AS easiest_percent,
    avg(CASE WHEN percent < 10 THEN 1.0 ELSE 0.0 END)     AS hard_ratio
FROM achievements
GROUP BY appid;

-- ── 3.2 游戏级参与度（Q2 的因变量来源）──────────────────────────────────────
-- 必须**先于 games_full** 创建（games_full 会 JOIN 它）。
-- 这些指数量化了「玩家整体愿不愿意玩下去」，是本项目唯一可得的参与度测量。
--
-- 分母的取法：**已实际玩过的用户** = owned + beaten + dropped + playing，
-- 不含 yet（想玩）与 toplay（待玩）——那两类还没开始玩，拿进来会稀释比例。
-- 口径若调整，必须同步改这里的注释与报告中的说明。

CREATE OR REPLACE VIEW game_engagement AS
WITH base AS (
    SELECT
        appid,
        playtime,
        added_count,
        ratings_count,
        coalesce(status_owned, 0)   AS owned,
        coalesce(status_beaten, 0)  AS beaten,
        coalesce(status_dropped, 0) AS dropped,
        coalesce(status_playing, 0) AS playing
    FROM rawg_games
)
SELECT
    appid,
    playtime                            AS playtime_hours,
    owned + beaten + dropped + playing  AS played_total,
    dropped,
    beaten,
    added_count,
    ratings_count,
    CASE WHEN owned + beaten + dropped + playing > 0
         THEN dropped::numeric / (owned + beaten + dropped + playing)
    END                                 AS dropped_ratio,
    CASE WHEN owned + beaten + dropped + playing > 0
         THEN beaten::numeric / (owned + beaten + dropped + playing)
    END                                 AS beaten_ratio
FROM base;

-- ── 3.3 宽表（建模 / EDA 直接用）────────────────────────────────────────────

CREATE OR REPLACE VIEW games_full AS
SELECT
    g.appid,
    g.name_en,
    g.name_zh,
    g.source_title,
    a.type,
    a.is_free,
    a.price_cents,
    a.release_date,
    a.developers,
    a.publishers,
    a.valve_genres,
    a.valve_categories,
    a.recommendations,
    s.owners,
    s.ccu,
    s.positive,
    s.negative,
    r.metacritic        AS rawg_metacritic,
    r.rating            AS rawg_rating,
    ge.playtime_hours,
    ge.dropped_ratio,
    ge.beaten_ratio,
    d.ach_count,
    d.median_percent,
    d.p10_percent,
    d.hard_ratio
FROM games g
LEFT JOIN steam_appdetails a  USING (appid)
LEFT JOIN steamspy_games   s  USING (appid)
LEFT JOIN rawg_games       r  USING (appid)
LEFT JOIN game_engagement  ge USING (appid)
LEFT JOIN game_difficulty  d  USING (appid);

-- ════════════════════════════════════════════════════════════════════════════
-- 四、表注释
-- ════════════════════════════════════════════════════════════════════════════

COMMENT ON TABLE games IS
    '游戏身份表：全库唯一的 appid 与官方中英文名。其余表都以 appid 为外键挂在它下面，'
    '写入顺序必须先在表建立本行。';
COMMENT ON TABLE steam_appdetails IS
    'Steam 商店 appdetails（免 key）：Valve 官方元数据。'
    '官方 genre 极粗（如黑魂3 只有 Action），题材分析要用 game_tags 的用户标签。';
COMMENT ON TABLE steamspy_games IS
    'SteamSpy（免 key）：owners/ccu/好评差评数。注意 average_forever / median_forever 已失效恒为 0。';
COMMENT ON TABLE rawg_games IS
    'RAWG（需 key）：评分（metacritic / rating）+ **时长（playtime）** + '
    '**玩家进度分布（status_*）**。后两者是本项目唯一的时长与弃坑率来源；'
    '题材标签与 SteamSpy 高度重叠且更脏，只作补充。';
COMMENT ON TABLE achievements IS
    '成就（一行一成就）。position 是「全局完成率接口」与「社区成就页」的按位对齐序号——'
    '两源成就顺序一致（2026-09-15 实测），按位 zip 即得到 api_name→display_name 映射。';
COMMENT ON TABLE game_tags IS
    '游戏标签（一行一「游戏, 来源, 标签」）。kind 区分题材标签与平台功能标签：'
    'RAWG 会把 Steam Achievements / Full controller support 混进 tags，做题材特征时必须剔除。';
COMMENT ON TABLE ingest_log IS
    '抓取审计（一行一「游戏, 源, 批次」）：支撑断点续爬、增量抓取与数据版本追溯。';
COMMENT ON TABLE dataset_versions IS
    '数据版本：每次建模前在此登记版本号，实验记录里写版本号而非「库里的数据」，'
    '否则库每天在变，SHAP 结果无法复现。';

-- ════════════════════════════════════════════════════════════════════════════
-- 五、字段注释
-- ════════════════════════════════════════════════════════════════════════════

-- games
COMMENT ON COLUMN games.appid IS 'Steam AppID，全库唯一身份键';
COMMENT ON COLUMN games.name_en IS '官方英文名（appdetails l=english）';
COMMENT ON COLUMN games.name_zh IS '官方中文名（appdetails l=schinese）；Valve 无中文名时回落为 name_en';
COMMENT ON COLUMN games.source_title IS '原始来源标题（如 B 站白金视频标题），便于回溯数据从哪条清单来；可能含「忠于自我」等非官方名后缀';
COMMENT ON COLUMN games.first_seen_at IS '该 appid 首次入库时间';
COMMENT ON COLUMN games.updated_at IS '该行最近一次更新时间';

-- steam_appdetails
COMMENT ON COLUMN steam_appdetails.appid IS '外键 → games.appid';
COMMENT ON COLUMN steam_appdetails.type IS 'appdetails 的 type：game / dlc / demo';
COMMENT ON COLUMN steam_appdetails.is_free IS '是否免费游戏';
COMMENT ON COLUMN steam_appdetails.price_cents IS '当前售价（美分）。取自 price_overview.final，免费或未定价为 NULL';
COMMENT ON COLUMN steam_appdetails.release_date IS '发售日。appdetails 原值是「Apr 11, 2016」这类展示格式，入库前已解析为 ISO 日期';
COMMENT ON COLUMN steam_appdetails.developers IS '开发商（可能多个）';
COMMENT ON COLUMN steam_appdetails.publishers IS '发行商（可能多个）';
COMMENT ON COLUMN steam_appdetails.valve_genres IS 'Valve 官方 genre（固定词表，极粗，如黑魂3 只有 [Action]）';
COMMENT ON COLUMN steam_appdetails.valve_categories IS 'Valve 官方 category（功能特性：Single-player / Co-op / Steam Achievements 等），不是题材';
COMMENT ON COLUMN steam_appdetails.recommendations IS 'Steam 好评总数（recommendations.total）';
COMMENT ON COLUMN steam_appdetails.fetched_at IS '本行数据的抓取时间（appdetails 价格会变，做时间敏感分析要看它）';

-- steamspy_games
COMMENT ON COLUMN steamspy_games.appid IS '外键 → games.appid';
COMMENT ON COLUMN steamspy_games.owners IS '销量估算**区间字符串**（如 "5,000,000 .. 10,000,000"），只能作数量级参考，不能当精确销量';
COMMENT ON COLUMN steamspy_games.ccu IS '峰值同时在线人数';
COMMENT ON COLUMN steamspy_games.positive IS '好评数';
COMMENT ON COLUMN steamspy_games.negative IS '差评数';
COMMENT ON COLUMN steamspy_games.average_forever IS '平均游玩时长（分钟）。**SteamSpy 该字段已失效，恒为 0**，不要当游玩时长用';
COMMENT ON COLUMN steamspy_games.median_forever IS '中位游玩时长（分钟）。**同上，已失效恒为 0**';
COMMENT ON COLUMN steamspy_games.fetched_at IS '本行数据的抓取时间（SteamSpy 有缓存延迟，可能滞后数天到数周）';

-- rawg_games
COMMENT ON COLUMN rawg_games.appid IS '外键 → games.appid';
COMMENT ON COLUMN rawg_games.rawg_id IS 'RAWG 自己的游戏 id。RAWG 不支持按 Steam appid 查，本字段是「按名搜 + 查 /stores 校验 appid」匹配出来的';
COMMENT ON COLUMN rawg_games.name IS 'RAWG 侧的游戏名（可能与官方名有出入，保留以便核对）';
COMMENT ON COLUMN rawg_games.released IS 'RAWG 侧的发售日';
COMMENT ON COLUMN rawg_games.metacritic IS 'Metacritic 媒体评分（0-100）';
COMMENT ON COLUMN rawg_games.rating IS 'RAWG 用户评分（0-5）';
COMMENT ON COLUMN rawg_games.ratings_count IS 'RAWG 评分的**样本量**。判断 rating 可不可信要看它——冷门游戏可能只有几条评分';
COMMENT ON COLUMN rawg_games.genres IS 'RAWG 的粗粒度 genre（如 [Action, RPG]），与 Valve genres 类似，信息量低';
COMMENT ON COLUMN rawg_games.playtime IS '**平均游玩时长（小时）**。本项目唯一的时长来源（SteamSpy 该字段已失效、逐玩家接口拿不到）';
COMMENT ON COLUMN rawg_games.added_count IS 'RAWG 上添加该游戏（收藏/加库）的用户总数。可作为下面各比例的参考分母';
COMMENT ON COLUMN rawg_games.status_yet IS 'RAWG 用户标记「想玩」的人数。**未开始玩，不计入弃坑率分母**';
COMMENT ON COLUMN rawg_games.status_owned IS 'RAWG 用户标记「拥有/在玩」的人数';
COMMENT ON COLUMN rawg_games.status_beaten IS 'RAWG 用户标记「已通关」的人数';
COMMENT ON COLUMN rawg_games.status_toplay IS 'RAWG 用户标记「待玩」的人数。**未开始玩，不计入弃坑率分母**';
COMMENT ON COLUMN rawg_games.status_dropped IS 'RAWG 用户标记「已弃坑」的人数。**「玩家不愿意玩」最直接的信号**';
COMMENT ON COLUMN rawg_games.status_playing IS 'RAWG 用户标记「正在玩」的人数';
COMMENT ON COLUMN rawg_games.fetched_at IS '本行数据的抓取时间';

-- achievements
COMMENT ON COLUMN achievements.appid IS '外键 → games.appid';
COMMENT ON COLUMN achievements.position IS '两源按位对齐的序号（从 1 开始）。与成就页面/接口的返回顺序一致';
COMMENT ON COLUMN achievements.api_name IS 'API 内部名（如 ACH41）。来自全局完成率接口；**报告中禁止直接展示**，必须用 display_name';
COMMENT ON COLUMN achievements.display_name IS '成就展示名（如 Enkindle）。来自 Steam 社区成就页，是建模与报告唯一允许使用的成就名';
COMMENT ON COLUMN achievements.description IS '成就描述。来自社区成就页；隐藏成就可以为空';
COMMENT ON COLUMN achievements.percent IS '全局完成率（0-100）。**本项目难度的核心数据**；随抓取批次漂移，建模必须绑定固定数据版本';

-- game_tags
COMMENT ON COLUMN game_tags.appid IS '外键 → games.appid';
COMMENT ON COLUMN game_tags.source IS '标签来源：steamspy（用户投票，带票数）/ rawg（无票数）';
COMMENT ON COLUMN game_tags.tag IS '标签名，保留来源原始写法（不同源大小写、连字符风格不一致，跨源比较前需归一化）';
COMMENT ON COLUMN game_tags.votes IS '标签票数。**只有 SteamSpy 有值**，可作特征权重；RAWG 为 NULL。注意只有 top 20 标签有票数';
COMMENT ON COLUMN game_tags.kind IS 'theme = 题材标签（可用于建模）；platform = 平台功能标签（如 Steam Achievements，做题材特征时必须剔除）';

-- ingest_log
COMMENT ON COLUMN ingest_log.id IS '自增主键';
COMMENT ON COLUMN ingest_log.appid IS '抓取对象；整批任务级的日志可为 NULL';
COMMENT ON COLUMN ingest_log.source IS
    '数据源标识，**细粒度到真实请求**：appdetails_en / appdetails_zh / global_ach / '
    'community_ach / steamspy / rawg。appdetails 中英文是两次独立请求、'
    '两个成就源也相互独立，任一失败不该让另一个看起来也失败，所以分开记';
COMMENT ON COLUMN ingest_log.status IS 'ok=成功；empty=接口通但无数据；skipped=跳过（如未配 key）；error=失败';
COMMENT ON COLUMN ingest_log.cache_key IS
    '对应的 data/raw/cache/ 缓存键，记录**真实文件名**（如 appdetails_english_374320），'
    '用于从库反查原始响应';
COMMENT ON COLUMN ingest_log.error IS '失败原因（status=error 时有值）';
COMMENT ON COLUMN ingest_log.fetched_at IS
    '该数据**真实的抓取时间**，取自缓存文件 mtime。**不要退化成入库时的 now()**——'
    '数据可能来自几天前的缓存，用 now() 会把"何时获取"答错';

-- dataset_versions
COMMENT ON COLUMN dataset_versions.version IS '版本号（建议用日期，如 2026-09-15）';
COMMENT ON COLUMN dataset_versions.built_at IS '该版本冻结的时间';
COMMENT ON COLUMN dataset_versions.note IS '备注：这批数据包含哪些源、抓取批次、已知问题等';

-- ════════════════════════════════════════════════════════════════════════════
-- 六、索引注释
-- ════════════════════════════════════════════════════════════════════════════

COMMENT ON INDEX idx_game_tags_tag IS
    '按标签反查游戏（特征工程高频：把某标签的游戏捞出来）';
COMMENT ON INDEX idx_game_tags_source_kind IS
    '按标签来源与类型筛（区分 SteamSpy / RAWG，剔除 platform 类标签）';
COMMENT ON INDEX idx_achievements_percent IS
    '按难度筛成就（Q2 的「极难成就占比」类特征）';
COMMENT ON INDEX idx_games_name_en IS
    '按官方英文名查游戏（跨源名称对齐、人工核对用）';
COMMENT ON INDEX idx_games_name_zh IS
    '按官方中文名查游戏';
COMMENT ON INDEX idx_appdetails_release_date IS
    '按发售日期切片（发售年份是 Q2 的控制变量，也是分组交叉验证的维度）';
COMMENT ON INDEX idx_ingest_appid IS
    '查某款游戏在各源的抓取历史';
COMMENT ON INDEX idx_ingest_source IS
    '查某数据源最近一批抓取（按 fetched_at 倒序；断点续爬与增量判断用）';

-- ════════════════════════════════════════════════════════════════════════════
-- 七、视图注释
-- ════════════════════════════════════════════════════════════════════════════

COMMENT ON VIEW game_difficulty IS
    '游戏级难度结构（从 achievements 聚合）。Q2 的核心难度特征来源：'
    '一个游戏的成就完成率分布刻画它有多难。用 Postgres percentile_cont 计算。';
COMMENT ON COLUMN game_difficulty.appid IS '外键 → games.appid';
COMMENT ON COLUMN game_difficulty.ach_count IS '成就总数';
COMMENT ON COLUMN game_difficulty.median_percent IS '全局完成率中位数，本游戏「典型成就」有多难';
COMMENT ON COLUMN game_difficulty.p10_percent IS '全局完成率 P10 分位，反映「最难那批成就」的难度';
COMMENT ON COLUMN game_difficulty.hardest_percent IS '最难的成就完成率（越小越难）';
COMMENT ON COLUMN game_difficulty.easiest_percent IS '最易的成就完成率';
COMMENT ON COLUMN game_difficulty.hard_ratio IS '极难成就占比（完成率 < 10% 的成就比例），0-1';

COMMENT ON VIEW game_engagement IS
    '游戏级参与度（Q2 的因变量来源）。量化「玩家整体愿不愿意玩下去」——'
    '分母是**已实际玩过**的用户（owned+beaten+dropped+playing），'
    '不含 yet / toplay（还没开始玩）。口径基于 RAWG 用户自标记，存在样本自选择偏差。';
COMMENT ON COLUMN game_engagement.appid IS '外键 → games.appid';
COMMENT ON COLUMN game_engagement.playtime_hours IS '平均游玩时长（小时），来自 RAWG';
COMMENT ON COLUMN game_engagement.played_total IS '已实际玩过的用户数 = owned + beaten + dropped + playing（各比例的分母）';
COMMENT ON COLUMN game_engagement.dropped IS '标记「已弃坑」的人数';
COMMENT ON COLUMN game_engagement.beaten IS '标记「已通关」的人数';
COMMENT ON COLUMN game_engagement.added_count IS 'RAWG 上添加该游戏的总人数（含未开始玩的），用于看整体热度';
COMMENT ON COLUMN game_engagement.ratings_count IS 'RAWG 评分样本量，判断评分与各比例可信度的参考';
COMMENT ON COLUMN game_engagement.dropped_ratio IS '**弃坑率** = dropped / played_total，0-1。越高说明这游戏越留不住人';
COMMENT ON COLUMN game_engagement.beaten_ratio IS '**通关率** = beaten / played_total，0-1。越高说明玩家越愿意玩到底';

COMMENT ON VIEW games_full IS
    '宽表视图：把 games 与各源表、难度与参与度视图 LEFT JOIN 起来，建模与 EDA 直接用。'
    '各源的 fetched_at 不在此视图中，需要追溯版本时回各自的源表查。';
COMMENT ON COLUMN games_full.appid IS 'Steam AppID';
COMMENT ON COLUMN games_full.name_en IS '官方英文名';
COMMENT ON COLUMN games_full.name_zh IS '官方中文名';
COMMENT ON COLUMN games_full.source_title IS '原始来源标题';
COMMENT ON COLUMN games_full.type IS 'game / dlc / demo';
COMMENT ON COLUMN games_full.is_free IS '是否免费';
COMMENT ON COLUMN games_full.price_cents IS '售价（美分）';
COMMENT ON COLUMN games_full.release_date IS '发售日';
COMMENT ON COLUMN games_full.developers IS '开发商';
COMMENT ON COLUMN games_full.publishers IS '发行商';
COMMENT ON COLUMN games_full.valve_genres IS 'Valve 官方 genre（极粗）';
COMMENT ON COLUMN games_full.valve_categories IS 'Valve 官方 category（功能特性）';
COMMENT ON COLUMN games_full.recommendations IS 'Steam 好评数';
COMMENT ON COLUMN games_full.owners IS 'SteamSpy 销量估算区间字符串';
COMMENT ON COLUMN games_full.ccu IS '峰值同时在线';
COMMENT ON COLUMN games_full.positive IS '好评数（SteamSpy）';
COMMENT ON COLUMN games_full.negative IS '差评数（SteamSpy）';
COMMENT ON COLUMN games_full.rawg_metacritic IS 'Metacritic 媒体评分（来自 RAWG）';
COMMENT ON COLUMN games_full.rawg_rating IS 'RAWG 用户评分（0-5）';
COMMENT ON COLUMN games_full.playtime_hours IS '平均游玩时长（小时）';
COMMENT ON COLUMN games_full.dropped_ratio IS '弃坑率（来自 game_engagement）';
COMMENT ON COLUMN games_full.beaten_ratio IS '通关率（来自 game_engagement）';
COMMENT ON COLUMN games_full.ach_count IS '成就总数';
COMMENT ON COLUMN games_full.median_percent IS '全局完成率中位数';
COMMENT ON COLUMN games_full.p10_percent IS '全局完成率 P10 分位';
COMMENT ON COLUMN games_full.hard_ratio IS '极难成就占比（完成率 < 10%）';

-- ════════════════════════════════════════════════════════════════════════════
-- 八、抓取覆盖：哪些游戏的哪些数据源已获取 / 成功失败 / 何时获取
-- ════════════════════════════════════════════════════════════════════════════
-- ingest_log 是**追加式日志**，同一 (游戏,源) 会有多行历史，所以要先取最新一条，
-- 再和「期望的源清单」交叉展开——否则「从没跑过」和「跑了失败」分不清。

-- 该索引服务于下面 ingest_latest 的 DISTINCT ON 查询
CREATE INDEX IF NOT EXISTS idx_ingest_appid_source_time
    ON ingest_log (appid, source, fetched_at DESC, id DESC);

CREATE OR REPLACE VIEW ingest_latest AS
SELECT DISTINCT ON (appid, source)
       appid, source, status, cache_key, error, fetched_at
FROM ingest_log
WHERE appid IS NOT NULL
ORDER BY appid, source, fetched_at DESC, id DESC;

CREATE OR REPLACE VIEW ingest_coverage AS
WITH expected (source, ord) AS (
    VALUES ('appdetails_en', 1), ('appdetails_zh', 2), ('global_ach', 3),
           ('community_ach', 4), ('steamspy', 5), ('rawg', 6)
)
SELECT
    g.appid,
    g.name_en,
    e.source,
    l.status,                                  -- NULL = 这个源从没跑过
    l.fetched_at,
    l.error,
    (l.status = 'ok') AS ok
FROM games g
CROSS JOIN expected e
LEFT JOIN ingest_latest l
       ON l.appid = g.appid AND l.source = e.source
ORDER BY g.appid, e.ord;

-- 只看有问题的行（没跑过 / empty / error / skipped），一眼看出还缺什么
CREATE OR REPLACE VIEW ingest_gaps AS
SELECT * FROM ingest_coverage
WHERE status IS DISTINCT FROM 'ok';

COMMENT ON INDEX idx_ingest_appid_source_time IS
    '服务 ingest_latest 的 DISTINCT ON (appid, source) 查询：每游戏每源取最新一条';

COMMENT ON VIEW ingest_latest IS
    '每 (游戏, 源) 的**最新一次**抓取状态。ingest_log 是追加式日志，查当前状态要走这个视图。';
COMMENT ON COLUMN ingest_latest.appid IS 'Steam AppID';
COMMENT ON COLUMN ingest_latest.source IS '数据源标识';
COMMENT ON COLUMN ingest_latest.status IS '最新一次的状态：ok / empty / skipped / error';
COMMENT ON COLUMN ingest_latest.cache_key IS '对应的 data/raw/cache/ 缓存键';
COMMENT ON COLUMN ingest_latest.error IS '失败原因（status=error 时有值）';
COMMENT ON COLUMN ingest_latest.fetched_at IS '该数据**真实的抓取时间**（取缓存文件 mtime，不是入库时间）';

COMMENT ON VIEW ingest_coverage IS
    '覆盖矩阵：每个游戏 × 每个期望数据源一行，直接回答「哪些游戏的哪些源已获取/成功失败/何时获取」。';
COMMENT ON COLUMN ingest_coverage.appid IS 'Steam AppID';
COMMENT ON COLUMN ingest_coverage.name_en IS '官方英文名，方便人眼扫';
COMMENT ON COLUMN ingest_coverage.source IS '期望的数据源（view 里硬编码的清单，新增源要同步这里）';
COMMENT ON COLUMN ingest_coverage.status IS '最新状态；**NULL 表示这个源从没跑过**（区别于跑了但失败）';
COMMENT ON COLUMN ingest_coverage.fetched_at IS '该源最近一次抓取时间；没跑过为 NULL';
COMMENT ON COLUMN ingest_coverage.error IS '最近一次失败原因';
COMMENT ON COLUMN ingest_coverage.ok IS '是否已成功获取（status = ok）';

COMMENT ON VIEW ingest_gaps IS
    '覆盖率缺口：只列 status 不是 ok 的 (游戏, 源) —— 没跑过 / empty / error / skipped。'
    '抓取任务收尾时扫一眼这张表就知道还缺什么。';
COMMENT ON COLUMN ingest_gaps.appid IS 'Steam AppID';
COMMENT ON COLUMN ingest_gaps.name_en IS '官方英文名';
COMMENT ON COLUMN ingest_gaps.source IS '还缺或出问题的数据源';
COMMENT ON COLUMN ingest_gaps.status IS 'NULL=没跑过；empty=接口通但无数据；error=失败；skipped=跳过（如未配 key）';
COMMENT ON COLUMN ingest_gaps.fetched_at IS '该源最近一次抓取时间；没跑过为 NULL';
COMMENT ON COLUMN ingest_gaps.error IS '失败原因';
COMMENT ON COLUMN ingest_gaps.ok IS '恒为 false（视图已过滤掉成功的行）';

COMMIT;
