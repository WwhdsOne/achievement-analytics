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
--   6. 数据源：Steam 商店搜索（全量枚举，bulk）/ Steam appdetails / 全局成就完成率 /
--      Steam 社区成就页 / SteamSpy / RAWG。**源的清单与限速配额都在 sources 表里**，
--      加源只改那张表。
--      **IGDB 已于 2026-09-15 放弃**：它需 Twitch OAuth2，而 Twitch 两步验证在国内
--      手机号上走不通；其时长（RAWG playtime 已覆盖）、评分（RAWG metacritic 已覆盖）
--      价值已由 RAWG 承接，只剩系列归属属加分项，故整表移除。
--   7. 抓取是 **gap 驱动**的：games 先灌入全量游戏（种子），seed 时物化
--      (游戏 × 逐款源) 的任务队列 fetch_tasks，worker 反复「取缺口 → 抓 → 回填」。
--      因此本 schema 有两套并存的记录：fetch_tasks 管**当前状态**（该抓谁），
--      ingest_log 管**审计历史与真实抓取时间**（何时抓的）。
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

-- ── 1.5b 成就名映射质量台账 ─────────────────────────────────────────────────
-- 「全局接口 vs 社区页」按位对齐是成就名映射的根基（见 AGENTS.md 硬性要求）。
-- 两源 percent 序列对不上时按位配对会张冠李戴——把这类游戏记进台账：
-- 建模侧过滤 resolved=false 的 appid，repair_mapping 修复成功后置 resolved=true。
CREATE TABLE IF NOT EXISTS mapping_issues (
    appid       INTEGER     PRIMARY KEY REFERENCES games (appid) ON DELETE CASCADE,
    reason      TEXT        NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved    BOOLEAN     NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_mapping_issues_open
    ON mapping_issues (appid) WHERE NOT resolved;

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
    error      TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 迁移：cache_key 列随文件缓存一起废弃（库是唯一事实源）。
-- ⚠️ **必须放在下面「三、视图」的 DROP VIEW 之后**：ingest_latest / ingest_coverage
-- 旧定义还依赖这个列，先删列会报 dependency error。
-- ALTER TABLE ingest_log DROP COLUMN IF EXISTS cache_key;

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

-- ── 1.10 商店搜索枚举结果（种子层，bulk 源）─────────────────────────────────
-- 「最公开的信息」：一次请求拿 100 款，不需要逐款 appdetails。这是全量游戏
-- 的落地处，也是 seed 的产物。
--
-- 为什么要单独一张表而不是塞进 steam_appdetails：两者是**不同批次、不同来源**
-- 的数据，同一批 appid 上会给出不同的名字/价格/发售日（商店搜索给的是搜索索引里的
-- 值，appdetails 给的是商店页权威值）。混在一张表里就无法区分来源与新鲜度，
-- 也违背「每个数据源一张表」的设计原则。游戏身份统一由 games 表承担。

CREATE TABLE IF NOT EXISTS store_search_games (
    appid          INTEGER     PRIMARY KEY REFERENCES games (appid) ON DELETE CASCADE,
    release_date   DATE,
    review_label   TEXT,
    review_percent INTEGER     CHECK (review_percent BETWEEN 0 AND 100),
    review_count   INTEGER,
    price_cents    INTEGER,
    tag_ids        INTEGER[],
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 1.11 源注册表 ───────────────────────────────────────────────────────────
-- 单一真源：**新增数据源只改这里**，gap 视图与队列不再需要各自维护源清单
-- （旧版把源清单硬编码在 ingest_coverage 的 VALUES 里，加源容易漏改）。
--
-- kind 区分两种抓取范式，这决定了源能不能进队列：
--   bulk     = 一次请求覆盖多款游戏（商店搜索 100 款/次、SteamSpy all 1000 款/次）
--              → **不进 fetch_tasks 队列**，作为独立的「全量刷新」任务
--   per_game = 一次请求只覆盖一款游戏 → 进队列，走 gap 驱动逐个回填

CREATE TABLE IF NOT EXISTS sources (
    source        TEXT    PRIMARY KEY,
    kind          TEXT    NOT NULL CHECK (kind IN ('bulk', 'per_game')),
    interval_ms   INTEGER NOT NULL CHECK (interval_ms > 0),
    daily_quota   INTEGER,
    monthly_quota INTEGER,
    max_attempts  INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    -- 抓取优先级（小的先跑）。顺序不是随便排的，它决定「剔除无成就游戏」能省多少：
    --   appdetails_en 先跑 → 建立身份 + 拿到 type
    --   global_ach   早跑 → 一旦确认无成就能立刻取消其余任务（见 worker 的 prune）
    --   rawg         最后跑 → 最贵（每次匹配花 2~5 次月度配额），确保被剔除的游戏不花它
    -- 之前靠 source 的字母序碰巧满足，太脆弱，所以显式声明。
    priority      INTEGER NOT NULL DEFAULT 100,
    note          TEXT
);

-- 迁移：给已存在的库补列
ALTER TABLE sources ADD COLUMN IF NOT EXISTS daily_quota INTEGER;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS priority    INTEGER NOT NULL DEFAULT 100;

-- 幂等 upsert：改限速 / 配额 / 重试上限后重跑 schema.sql 即生效
INSERT INTO sources (source, kind, interval_ms, daily_quota, monthly_quota, max_attempts, priority, note) VALUES
    ('store_search',  'bulk',     1000, NULL,  NULL,  3, 100,
     'Steam 商店搜索：全量枚举入口，一次 100 款（count 上限 100，传 1000 无效）。免 key。'
     '⚠️ 默认排序在翻页期间漂移，实测一轮 819 页只覆盖 84.9%，且漏项无法自知 —— '
     '要可证明完整的全集用 store_applist'),
    ('store_applist', 'bulk',     1000, NULL,  NULL,  3, 100,
     'IStoreService/GetAppList：**按 appid 顺序**返回商店全部条目，用 last_appid 游标续页 '
     '—— 无排序漂移、完整性可证明。max_results 最大 50000，约 4 次请求覆盖 17.7 万款游戏。'
     '**需 Steam Web API key**（STEAM_API_KEY）。缺口：不含发售日与成就信息'),
    ('steamspy_all',  'bulk',    60000, NULL,  NULL,  3, 100,
     'SteamSpy request=all：一次 1000 款，含 owners/ccu/好评差评。免 key。'
     '官方限速写明 request=all 是 1 req/60s（不是 1 req/s），故 interval_ms=60000。'
     '报错字段不含 tags，且 average_forever/median_forever 已失效恒为 0'),
    ('appdetails_en', 'per_game', 1000, NULL,  NULL,  3, 10,
     'Steam 商店 appdetails（l=english）：官方英文名与元数据。实测不支持批量，只能单 appid。免 key。'
     '**优先级最高**：它建立 games 行并提供 type'),
    ('global_ach',    'per_game', 1000, NULL,  NULL,  3, 20,
     'GetGlobalAchievementPercentagesForApp：内部名 + percent，难度核心数据。免 key。'
     '**对无成就的 appid 返回 403**，已归一成「确定性无数据」→ 越早跑越好，'
     '确认无成就即可取消该游戏其余任务'),
    ('community_ach', 'per_game', 1000, NULL,  NULL,  3, 30,
     'Steam 社区成就页：展示名 + percent + 描述。免 key。与 global_ach 顺序一致，按位对齐完成名称映射。'
     '与 global_ach 是**一对**：缺任一个都生成不了 achievements 表'),
    ('appdetails_zh', 'per_game', 1000, NULL,  NULL,  3, 40,
     'Steam 商店 appdetails（l=schinese）：官方中文名，无中文名时回落英文名。免 key'),
    ('steamspy',      'per_game', 1000, NULL,  NULL,  3, 50,
     'SteamSpy appdetails：用户标签 + 票数（bulk 的 steamspy_all 拿不到 tags，这是它唯一独有价值）。'
     '免 key。官方只公布 1 req/s（2026-09-17 核对），**没有公布日配额** —— '
     '2026-09-22 取消本项目自设的 1000/天上限，现在**只有速率限制**（1 req/s，按机器分桶）。'
     '与 RAWG 不同：不存在按 key 的跨机器配额账本。'),
    ('rawg',          'per_game', 1000, NULL, 20000, 3, 90,
     'RAWG：评分 / 时长 / 弃坑率 / 题材标签。**需 key**。免费档 20,000 请求/月（官方文档），'
     '响应头不暴露剩余额度，故配额靠 api_usage 自行记账。'
     '**优先级最低**：每次匹配要花 2~5 次月度配额，放最后确保被剔除的游戏不花它')
ON CONFLICT (source) DO UPDATE SET
    kind          = EXCLUDED.kind,
    interval_ms   = EXCLUDED.interval_ms,
    daily_quota   = EXCLUDED.daily_quota,
    monthly_quota = EXCLUDED.monthly_quota,
    max_attempts  = EXCLUDED.max_attempts,
    priority      = EXCLUDED.priority,
    note          = EXCLUDED.note;

-- ── 1.12 抓取任务队列（gap 驱动的状态表）────────────────────────────────────
-- 与 ingest_log 的分工：
--   ingest_log  = **追加式审计历史**（每次尝试都留痕，回答「何时抓的、当时成功没有」）
--   fetch_tasks = **可变的当前状态**（一行一「游戏, 源」，回答「现在还缺什么、下一步该抓谁」）
-- 拆开的理由：审计历史必须不可变，而队列状态需要被反复改写；混在一张表里两者都做不好。
--
-- **终止条件**（旧设计缺失、会导致无限重爬）：attempts 到 sources.max_attempts 就转
-- exhausted，不再出现在可执行队列里。status 语义：
--   pending   = 待抓（初始态，或来自 bulk 种子的新任务）
--   ok        = 已成功拿到数据
--   empty     = 接口通但该游戏确实没有这项数据（**确定性终态**，不再重试）
--   skipped   = 按配置跳过（如未配 RAWG key）—— 配好 key 后应重置回 pending
--   error     = 失败，等 next_retry_at 退避重试；attempts 到上限转 exhausted
--   exhausted = 重试耗尽，放弃（终态）

CREATE TABLE IF NOT EXISTS fetch_tasks (
    appid         INTEGER     NOT NULL REFERENCES games (appid) ON DELETE CASCADE,
    source        TEXT        NOT NULL REFERENCES sources (source),
    status        TEXT        NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'ok', 'empty', 'skipped', 'error', 'exhausted')),
    attempts      INTEGER     NOT NULL DEFAULT 0,
    last_error    TEXT,
    next_retry_at TIMESTAMPTZ,
    -- 租约：多机并行的前提。claim 时写入「谁」和「租到什么时候」，
    -- 租约到期即自动可被任何 worker 重新抢（worker 崩了不会让任务永久卡住）。
    claimed_by    TEXT,
    lease_until   TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (appid, source)
);

-- 迁移：给已存在的库补租约列
ALTER TABLE fetch_tasks ADD COLUMN IF NOT EXISTS claimed_by  TEXT;
ALTER TABLE fetch_tasks ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;

-- ── 1.13 配额账本 ───────────────────────────────────────────────────────────
-- RAWG 等按量计费的源**不暴露剩余额度**（2026-09-17 实测响应头无任何 x-ratelimit
-- 字段），不自己记账就无从判断还能抓多少。按 (源, 日期) 聚合而非逐请求一行：
-- 全量抓取会有几十万次请求，逐行存是没必要的膨胀。

CREATE TABLE IF NOT EXISTS api_usage (
    source   TEXT    NOT NULL,
    day      DATE    NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
    PRIMARY KEY (source, day)
);

ALTER TABLE api_usage ADD COLUMN IF NOT EXISTS requests INTEGER NOT NULL DEFAULT 0;

-- ── 1.14 RAWG 密钥池 ────────────────────────────────────────────────────────
-- RAWG 的 20,000 次/月是**绑定 API key** 的配额（不是按机器、不是按 IP），所以
-- 「多机并行」对 RAWG 一分钱都不多——要扩容只能增加 key。
-- 这里把 key 放在**共享库**里而不是各机器本地文件，理由是：只有共享库能让所有机器
-- 看到统一的剩余额度并协调取用，否则 N 台机器会各自把同一份额度用满。
--
-- 明文 key 落在库里（库不在 git 里，也不进 data/）。**rawg_key_status 视图刻意
-- 不暴露 api_key**，这样队友查额度时不会顺手把密钥读到终端或日志里。

CREATE TABLE IF NOT EXISTS rawg_keys (
    key_id        BIGSERIAL   PRIMARY KEY,
    api_key       TEXT        NOT NULL UNIQUE,
    label         TEXT,
    enabled       BOOLEAN     NOT NULL DEFAULT true,
    monthly_quota INTEGER     NOT NULL DEFAULT 20000 CHECK (monthly_quota > 0),
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rawg_key_usage (
    key_id   BIGINT  NOT NULL REFERENCES rawg_keys (key_id) ON DELETE CASCADE,
    day      DATE    NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
    PRIMARY KEY (key_id, day)
);

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

-- 取任务用：worker 的 claim 查询按「可执行状态 + 退避到期」筛，这是最热的路径
CREATE INDEX IF NOT EXISTS idx_fetch_tasks_claim
    ON fetch_tasks (status, next_retry_at);

-- 按源看队列（「这个源还剩多少没抓」）
CREATE INDEX IF NOT EXISTS idx_fetch_tasks_source_status
    ON fetch_tasks (source, status);

-- 配额账本按月汇总（「本月 RAWG 用了多少次」）
CREATE INDEX IF NOT EXISTS idx_api_usage_day
    ON api_usage (day);

-- 多机抢占用：claim 查询要按「租约是否到期」过滤
CREATE INDEX IF NOT EXISTS idx_fetch_tasks_lease
    ON fetch_tasks (lease_until);

-- 密钥池按月汇总
CREATE INDEX IF NOT EXISTS idx_rawg_key_usage_day
    ON rawg_key_usage (day);

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
DROP VIEW IF EXISTS ingest_progress CASCADE;
DROP VIEW IF EXISTS quota_status    CASCADE;
DROP VIEW IF EXISTS rawg_key_status CASCADE;
DROP VIEW IF EXISTS quota_this_month CASCADE;
DROP VIEW IF EXISTS game_engagement CASCADE;
DROP VIEW IF EXISTS game_difficulty CASCADE;
DROP VIEW IF EXISTS ingest_coverage CASCADE;
DROP VIEW IF EXISTS ingest_latest   CASCADE;

-- 迁移：cache_key 列随文件缓存一起废弃（库是唯一事实源）。
-- **必须在上面视图 DROP 之后**：ingest_latest / ingest_coverage 的旧定义依赖这个列。
ALTER TABLE ingest_log DROP COLUMN IF EXISTS cache_key;

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
    ss.review_label     AS store_review_label,
    ss.review_percent   AS store_review_percent,
    ss.review_count     AS store_review_count,
    ge.playtime_hours,
    ge.dropped_ratio,
    ge.beaten_ratio,
    d.ach_count,
    d.median_percent,
    d.p10_percent,
    d.hard_ratio
FROM games g
LEFT JOIN steam_appdetails   a  USING (appid)
LEFT JOIN steamspy_games     s  USING (appid)
LEFT JOIN rawg_games         r  USING (appid)
LEFT JOIN store_search_games ss USING (appid)
LEFT JOIN game_engagement    ge USING (appid)
LEFT JOIN game_difficulty    d  USING (appid);

-- ════════════════════════════════════════════════════════════════════════════
-- 四、表注释
-- ════════════════════════════════════════════════════════════════════════════

COMMENT ON TABLE games IS
    '游戏身份表：全库唯一的 appid 与官方中英文名。其余表都以 appid 为外键挂在它下面，'
    '写入顺序必须先在表建立本行。';
COMMENT ON TABLE steam_appdetails IS
    'Steam 商店 appdetails（免 key）：Valve 官方元数据。'
    '官方 genre 极粗（如黑魂3 只有 Action），题材分析要用 game_tags 的用户标签。';
COMMENT ON TABLE store_search_games IS
    '商店搜索枚举结果（种子层）：一次请求覆盖 100 款的**最公开信息**。'
    '与 steam_appdetails 是不同来源、不同批次的数据，故分表存放——'
    '两者在同批 appid 上会给出不同的名字/价格/发售日。'
    '免 key，是全量游戏（81,849 款带成就）的唯一免 key 枚举入口。';
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

-- store_search_games
COMMENT ON COLUMN store_search_games.appid IS '外键 → games.appid';
COMMENT ON COLUMN store_search_games.release_date IS
    '发售日。搜索结果给的是「Sep 10, 2026」展示格式，入库前已解析为 ISO 日期';
COMMENT ON COLUMN store_search_games.review_label IS
    '好评档位展示名（Very Positive / Mostly Positive / …）。**注意不是 CSS class**，'
    '后者是 positive 这类 slug（2026-09-17 踩到）';
COMMENT ON COLUMN store_search_games.review_percent IS
    '好评率（%）。免费的「口碑」信号，比 SteamSpy 的 owners 区间字符串更硬';
COMMENT ON COLUMN store_search_games.review_count IS
    '评价总数。**热度代理，也是判断 review_percent 可信度的样本量**——'
    '「39 条评价 100% 好评」和「39,068 条评价 85% 好评」不是一回事。未发售游戏为 NULL';
COMMENT ON COLUMN store_search_games.price_cents IS
    '当前售价（美分），取自搜索结果的 data-price-final。免费为 0，未定价为 NULL';
COMMENT ON COLUMN store_search_games.tag_ids IS
    'Steam 官方标签 ID 数组（data-ds-tagids）。**存的是 ID 不是名字**——'
    'ID→名字的映射表尚未采集，故这里先原样保留，勿直接当题材特征用';
COMMENT ON COLUMN store_search_games.fetched_at IS
    '本行数据的抓取时间。搜索结果的价格/好评率会变，时间敏感分析要看它';

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
COMMENT ON COLUMN ingest_log.error IS '失败原因（status=error 时有值）';
COMMENT ON COLUMN ingest_log.fetched_at IS
    '该数据**真实的抓取时间**，由 HTTP 层在成功拿到响应时记录。'
    '**不要退化成入库时的 now()**——那会把"何时获取"答成"何时写库"';

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
COMMENT ON COLUMN games_full.store_review_label IS 'Steam 好评档位展示名（来自商店搜索枚举）';
COMMENT ON COLUMN games_full.store_review_percent IS 'Steam 好评率（%），来自商店搜索枚举';
COMMENT ON COLUMN games_full.store_review_count IS 'Steam 评价总数（口碑可信度的样本量）';
COMMENT ON COLUMN games_full.playtime_hours IS '平均游玩时长（小时）';
COMMENT ON COLUMN games_full.dropped_ratio IS '弃坑率（来自 game_engagement）';
COMMENT ON COLUMN games_full.beaten_ratio IS '通关率（来自 game_engagement）';
COMMENT ON COLUMN games_full.ach_count IS '成就总数';
COMMENT ON COLUMN games_full.median_percent IS '全局完成率中位数';
COMMENT ON COLUMN games_full.p10_percent IS '全局完成率 P10 分位';
COMMENT ON COLUMN games_full.hard_ratio IS '极难成就占比（完成率 < 10%）';

-- ════════════════════════════════════════════════════════════════════════════
-- 八、抓取覆盖与进度：回答「还缺什么 / 下一步该抓谁 / 跑了多少」
-- ════════════════════════════════════════════════════════════════════════════
-- 两个数据来源分工明确：
--   fetch_tasks = **当前状态**（该抓谁）—— gap 驱动队列的驱动源，可变
--   ingest_log  = **历史与真实抓取时间**（何时抓的）—— 追加式，不可变
-- 本节的视图把两者拼起来：状态取自 fetch_tasks，抓取时间取自 ingest_log。
--
-- 旧版靠 CROSS JOIN 硬编码的源清单来「展开期望的源」；现在队列在 seed 时就已
-- 物化了 (游戏 × 逐款源) 的全集，无需再展开，加源也不用改这里。

-- 该索引服务于下面 ingest_latest 的 DISTINCT ON 查询
CREATE INDEX IF NOT EXISTS idx_ingest_appid_source_time
    ON ingest_log (appid, source, fetched_at DESC, id DESC);

CREATE OR REPLACE VIEW ingest_latest AS
SELECT DISTINCT ON (appid, source)
       appid, source, status, error, fetched_at
FROM ingest_log
WHERE appid IS NOT NULL
ORDER BY appid, source, fetched_at DESC, id DESC;

-- 覆盖矩阵：一行一「游戏 × 逐款源」的当前状态
CREATE OR REPLACE VIEW ingest_coverage AS
SELECT
    t.appid,
    g.name_en,
    t.source,
    s.kind,
    t.status,
    t.attempts,
    s.max_attempts,
    t.last_error                                 AS error,
    t.next_retry_at,
    l.fetched_at,                                -- 真实的抓取时间（来自审计日志）
    (t.status = 'ok')                            AS ok,
    (t.status IN ('pending', 'error')
     AND t.attempts < s.max_attempts)            AS actionable   -- 是否还能被 worker 捡起来
FROM fetch_tasks t
JOIN games   g ON g.appid = t.appid
JOIN sources s ON s.source = t.source
LEFT JOIN ingest_latest l
       ON l.appid = t.appid AND l.source = t.source;

-- 可执行缺口：**只列 worker 真的会去抓的行**。
-- 与 ingest_coverage 的关键区别：empty / skipped / exhausted / 重试耗尽的 error
-- 都不在此视图里。这是「循环有终止条件」的体现——若把它们也算缺口，
-- 一个本来就没有成就的游戏会被永远重爬（旧设计的缺陷）。
CREATE OR REPLACE VIEW ingest_gaps AS
SELECT * FROM ingest_coverage
WHERE actionable;

-- 进度汇总：一行一个源，直接回答「这个源还剩多少没抓」
CREATE OR REPLACE VIEW ingest_progress AS
SELECT
    s.source,
    s.kind,
    s.daily_quota,
    s.monthly_quota,
    count(t.appid)                                          AS total,
    count(*) FILTER (WHERE t.status = 'ok')                 AS ok,
    count(*) FILTER (WHERE t.status = 'empty')              AS empty,
    count(*) FILTER (WHERE t.status = 'skipped')            AS skipped,
    count(*) FILTER (WHERE t.status = 'error')              AS error,
    count(*) FILTER (WHERE t.status = 'exhausted')          AS exhausted,
    count(*) FILTER (WHERE t.status = 'pending')            AS pending,
    count(*) FILTER (WHERE t.status IN ('pending', 'error')
                       AND t.attempts < s.max_attempts)     AS actionable,
    max(t.updated_at)                                       AS last_activity_at
FROM sources s
LEFT JOIN fetch_tasks t ON t.source = s.source
GROUP BY s.source, s.kind, s.daily_quota, s.monthly_quota;

-- 配额余额：日限与月限都要看（SteamSpy 是日限 1000，RAWG 是月限 20000）
CREATE OR REPLACE VIEW quota_status AS
SELECT
    s.source,
    s.daily_quota,
    s.monthly_quota,
    coalesce(sum(u.requests) FILTER (WHERE u.day = current_date), 0)        AS used_today,
    CASE WHEN s.daily_quota IS NULL THEN NULL
         ELSE s.daily_quota
              - coalesce(sum(u.requests) FILTER (WHERE u.day = current_date), 0)
    END                                                                     AS remaining_today,
    coalesce(sum(u.requests) FILTER (
        WHERE date_trunc('month', u.day) = date_trunc('month', current_date)), 0)
                                                                            AS used_this_month,
    CASE WHEN s.monthly_quota IS NULL THEN NULL
         ELSE s.monthly_quota
              - coalesce(sum(u.requests) FILTER (
                  WHERE date_trunc('month', u.day) = date_trunc('month', current_date)), 0)
    END                                                                     AS remaining_this_month
FROM sources s
LEFT JOIN api_usage u ON u.source = s.source
GROUP BY s.source, s.daily_quota, s.monthly_quota;

-- 密钥池状态：逐 key 看本月用量与余额。**刻意不暴露 api_key 明文**，
-- 只给 key_id / label / 尾 4 位，避免队友查额度时把密钥读进终端或日志。
CREATE OR REPLACE VIEW rawg_key_status AS
WITH usage AS (
    SELECT key_id,
           sum(requests) FILTER (
               WHERE date_trunc('month', day) = date_trunc('month', current_date)
           ) AS used_this_month,
           sum(requests) FILTER (WHERE day = current_date) AS used_today
    FROM rawg_key_usage
    GROUP BY key_id
)
SELECT
    k.key_id,
    k.label,
    k.enabled,
    '…' || right(k.api_key, 4)                          AS key_hint,
    k.monthly_quota,
    coalesce(u.used_this_month, 0)                      AS used_this_month,
    k.monthly_quota - coalesce(u.used_this_month, 0)    AS remaining_this_month,
    coalesce(u.used_today, 0)                           AS used_today,
    k.created_at
FROM rawg_keys k
LEFT JOIN usage u ON u.key_id = k.key_id;

COMMENT ON INDEX idx_ingest_appid_source_time IS
    '服务 ingest_latest 的 DISTINCT ON (appid, source) 查询：每游戏每源取最新一条';

COMMENT ON VIEW ingest_latest IS
    '每 (游戏, 源) 的**最新一次**抓取状态与**真实抓取时间**。来源是追加式审计日志 '
    'ingest_log；查「该抓谁」要走 ingest_coverage（来源是 fetch_tasks）。';
COMMENT ON COLUMN ingest_latest.appid IS 'Steam AppID';
COMMENT ON COLUMN ingest_latest.source IS '数据源标识';
COMMENT ON COLUMN ingest_latest.status IS '最新一次的状态：ok / empty / skipped / error / exhausted';
COMMENT ON COLUMN ingest_latest.error IS '失败原因（status=error 时有值）';
COMMENT ON COLUMN ingest_latest.fetched_at IS '该数据**真实的抓取时间**（HTTP 层在成功拿到响应时记录）';

COMMENT ON VIEW ingest_coverage IS
    '覆盖矩阵：一行一「游戏 × 逐款源」的当前队列状态。状态取自 fetch_tasks（可变），'
    '抓取时间取自 ingest_log（审计）。批量源（kind=bulk）不在此视图中，'
    '它们不是逐款抓取的，用量看 api_usage / quota_this_month。';
COMMENT ON COLUMN ingest_coverage.appid IS 'Steam AppID';
COMMENT ON COLUMN ingest_coverage.name_en IS '英文名，方便人眼扫';
COMMENT ON COLUMN ingest_coverage.source IS '数据源标识（清单来自 sources 表，加源只需改那张表）';
COMMENT ON COLUMN ingest_coverage.kind IS 'bulk=一次请求覆盖多款；per_game=一次请求一款';
COMMENT ON COLUMN ingest_coverage.status IS
    '队列当前状态：pending / ok / empty / skipped / error / exhausted。'
    'empty 是**确定性终态**（该游戏确实没这项数据），不会重试';
COMMENT ON COLUMN ingest_coverage.attempts IS '已尝试次数';
COMMENT ON COLUMN ingest_coverage.max_attempts IS '该源的重试上限（来自 sources）';
COMMENT ON COLUMN ingest_coverage.error IS '最近一次失败原因';
COMMENT ON COLUMN ingest_coverage.next_retry_at IS '下次可重试时间（退避）；为 NULL 表示立即可抓';
COMMENT ON COLUMN ingest_coverage.fetched_at IS '该源最近一次**真实抓取时间**；从没抓成功为 NULL';
COMMENT ON COLUMN ingest_coverage.ok IS '是否已成功获取';
COMMENT ON COLUMN ingest_coverage.actionable IS
    'worker 是否还会抓它：status 为 pending/error **且** attempts 未达上限。'
    '这是「循环能否终止」的判据';

COMMENT ON VIEW ingest_gaps IS
    '可执行缺口：**只列 worker 真的会去抓的 (游戏, 源)**。'
    'empty / skipped / exhausted / 重试耗尽的 error 都不在内 —— 因此这个集合单调收敛，'
    '抓完就空，不会因为「某游戏本来就没成就」而无限重爬。';
COMMENT ON COLUMN ingest_gaps.appid IS 'Steam AppID';
COMMENT ON COLUMN ingest_gaps.name_en IS '英文名';
COMMENT ON COLUMN ingest_gaps.source IS '还缺或待重试的数据源';
COMMENT ON COLUMN ingest_gaps.status IS 'pending=待抓；error=失败待退避重试';
COMMENT ON COLUMN ingest_gaps.attempts IS '已尝试次数';
COMMENT ON COLUMN ingest_gaps.next_retry_at IS '下次可重试时间';
COMMENT ON COLUMN ingest_gaps.actionable IS '恒为 true（视图已过滤）';

COMMENT ON VIEW ingest_progress IS
    '抓取进度汇总：一行一个源，含各状态计数与 actionable 剩余量。'
    '「这个源还剩多少没抓」看 actionable 列。';
COMMENT ON COLUMN ingest_progress.source IS '数据源标识';
COMMENT ON COLUMN ingest_progress.kind IS 'bulk / per_game；bulk 源不进队列，total 为 0';
COMMENT ON COLUMN ingest_progress.daily_quota IS '每日配额上限；NULL 表示不限量';
COMMENT ON COLUMN ingest_progress.monthly_quota IS '月度配额上限；NULL 表示不限量';
COMMENT ON COLUMN ingest_progress.total IS '该源的队列任务总数（seed 时物化）';
COMMENT ON COLUMN ingest_progress.ok IS '已成功';
COMMENT ON COLUMN ingest_progress.empty IS '接口通但无数据（确定性终态，不重试）';
COMMENT ON COLUMN ingest_progress.skipped IS '按配置跳过（如未配 RAWG key）';
COMMENT ON COLUMN ingest_progress.error IS '失败待重试';
COMMENT ON COLUMN ingest_progress.exhausted IS '重试耗尽已放弃（终态）';
COMMENT ON COLUMN ingest_progress.pending IS '尚未开始';
COMMENT ON COLUMN ingest_progress.actionable IS 'worker 还会抓的总数 —— 归零即该源抓完';
COMMENT ON COLUMN ingest_progress.last_activity_at IS '该源队列最近一次变动时间';

COMMENT ON VIEW quota_status IS
    '配额余额：日限与月限都要看。RAWG 响应头不暴露剩余额度，所以这是判断'
    '「还能抓多少」的唯一依据；SteamSpy 是日限 1000，超了次日才恢复。'
    '注意 RAWG 的额度还受**密钥池**约束，逐 key 余额看 rawg_key_status。';
COMMENT ON COLUMN quota_status.source IS '数据源标识';
COMMENT ON COLUMN quota_status.daily_quota IS '每日配额上限；NULL 表示不限量';
COMMENT ON COLUMN quota_status.monthly_quota IS '月度配额上限；NULL 表示不限量';
COMMENT ON COLUMN quota_status.used_today IS '今日已发出的真实网络请求数（缓存命中不计）';
COMMENT ON COLUMN quota_status.remaining_today IS '今日剩余额度；不限量时为 NULL';
COMMENT ON COLUMN quota_status.used_this_month IS '本月已发出的真实网络请求数';
COMMENT ON COLUMN quota_status.remaining_this_month IS '本月剩余额度；不限量时为 NULL';

COMMENT ON TABLE sources IS
    '数据源注册表（单一真源）：新增数据源只改这张表，gap 视图与队列都从它读。'
    'kind 决定范式：bulk 一次请求覆盖多款（商店搜索 100/次、SteamSpy all 1000/次），'
    '不进队列；per_game 一次一款，进 fetch_tasks 走 gap 驱动回填。';
COMMENT ON COLUMN sources.source IS '数据源标识，与 ingest_log.source / fetch_tasks.source 对应';
COMMENT ON COLUMN sources.kind IS 'bulk=批量覆盖多款（不进队列）；per_game=逐款（进队列）';
COMMENT ON COLUMN sources.interval_ms IS '相邻两次请求的最小间隔（毫秒），按站点礼貌间隔设定';
COMMENT ON COLUMN sources.daily_quota IS '每日请求配额上限；NULL 表示无限制（SteamSpy 是 1000/天）';
COMMENT ON COLUMN sources.monthly_quota IS '月度请求配额上限；NULL 表示无限制（RAWG 免费档 20000/月）';
COMMENT ON COLUMN sources.max_attempts IS '重试上限，达到后转 exhausted 终止，防止无限重爬';
COMMENT ON COLUMN sources.priority IS
    '抓取优先级，小的先跑。**顺序是有含义的**：global_ach 早跑就能尽早发现'
    '「该游戏无成就」并取消它其余任务（见 worker 的 prune）；rawg 放最后，'
    '避免被剔除的游戏花掉月度配额';
COMMENT ON COLUMN sources.note IS '限速来源、是否需 key、已知坑等人读备注';

COMMENT ON TABLE fetch_tasks IS
    '抓取任务队列（gap 驱动的状态表）：一行一「游戏, 源」。'
    '与 ingest_log 分工——本表是可变的**当前状态**（该抓谁），'
    'ingest_log 是不可变的**审计历史**（何时抓的）。'
    '终止条件靠 attempts 对 sources.max_attempts：error 达上限转 exhausted。';
COMMENT ON COLUMN fetch_tasks.appid IS '外键 → games.appid';
COMMENT ON COLUMN fetch_tasks.source IS '外键 → sources.source';
COMMENT ON COLUMN fetch_tasks.status IS
    'pending 待抓 / ok 成功 / empty 确定性无数据（终态）/ skipped 按配置跳过 / '
    'error 失败待退避重试 / exhausted 重试耗尽（终态）';
COMMENT ON COLUMN fetch_tasks.attempts IS '已尝试次数，达 sources.max_attempts 即转 exhausted';
COMMENT ON COLUMN fetch_tasks.last_error IS '最近一次失败原因';
COMMENT ON COLUMN fetch_tasks.next_retry_at IS '下次可重试时间（指数退避）；NULL 表示立即可抓';
COMMENT ON COLUMN fetch_tasks.updated_at IS '该行最近一次变动时间';

COMMENT ON TABLE api_usage IS
    '配额账本：按 (源, 日期) 聚合真实网络请求数。'
    'RAWG 等按量计费的源不暴露剩余额度（实测响应头无 x-ratelimit 字段），'
    '不自己记账就无从判断还能抓多少。缓存命中不计入。';
COMMENT ON COLUMN api_usage.source IS '数据源标识';
COMMENT ON COLUMN api_usage.day IS 'UTC 日期（按日聚合，避免逐请求一行）';
COMMENT ON COLUMN api_usage.requests IS '当日真实网络请求数，缓存命中不计';

COMMENT ON COLUMN fetch_tasks.claimed_by IS
    '当前持有租约的 worker 标识（主机名+pid）。为 NULL 表示无人持有。'
    '多机并行靠它判断「谁在抓」，不要手工改。';
COMMENT ON COLUMN fetch_tasks.lease_until IS
    '租约到期时间。**到期即自动可被任何 worker 重新抢占**——这是 worker 崩溃后'
    '任务不会永久卡在 pending 的保证，也是不需要「僵尸任务清理」的原因。';

COMMENT ON TABLE rawg_keys IS
    'RAWG API 密钥池。RAWG 的 20,000 次/月**绑定 key**（不是按机器/IP），'
    '所以扩容只能加 key；放在共享库里才能让所有机器看到统一余额并协调取用。'
    '**明文 key 在库里，查额度请用 rawg_key_status 视图（它不暴露明文）。**';
COMMENT ON COLUMN rawg_keys.key_id IS '代理主键';
COMMENT ON COLUMN rawg_keys.api_key IS '明文 API key（库不在 git，也不进 data/）';
COMMENT ON COLUMN rawg_keys.label IS '归属标识，便于联系到人和追责，如「张三的 key」';
COMMENT ON COLUMN rawg_keys.enabled IS 'false = 停用（如该 key 已超额或被限），不会参与取用';
COMMENT ON COLUMN rawg_keys.monthly_quota IS '该 key 的月配额，默认 20000（RAWG 免费档官方口径）';
COMMENT ON COLUMN rawg_keys.note IS '备注：注册邮箱、已知问题等';
COMMENT ON COLUMN rawg_keys.created_at IS '入库时间';

COMMENT ON TABLE rawg_key_usage IS
    '逐 key 逐日的真实请求计数。与 api_usage 的区别：api_usage 按**源**汇总'
    '（RAWG 总量），本表按**key**拆分——因为配额是绑 key 的，不拆就不知道该用哪个 key。';
COMMENT ON COLUMN rawg_key_usage.key_id IS '外键 → rawg_keys.key_id';
COMMENT ON COLUMN rawg_key_usage.day IS 'UTC 日期';
COMMENT ON COLUMN rawg_key_usage.requests IS '该 key 当日真实请求数';

COMMENT ON VIEW rawg_key_status IS
    '密钥池状态：逐 key 看本月/今日用量与月余额。**不暴露 api_key 明文**，'
    '只给 key_hint（尾 4 位），避免查额度时把密钥读进终端或日志。'
    '取用逻辑见 cleaning/rawg_keys.py 的 reserve_key()。';
COMMENT ON COLUMN rawg_key_status.key_id IS '代理主键';
COMMENT ON COLUMN rawg_key_status.label IS '归属标识';
COMMENT ON COLUMN rawg_key_status.enabled IS '是否参与取用';
COMMENT ON COLUMN rawg_key_status.key_hint IS '密钥尾 4 位，仅供人眼核对是哪个 key';
COMMENT ON COLUMN rawg_key_status.monthly_quota IS '该 key 的月配额';
COMMENT ON COLUMN rawg_key_status.used_this_month IS '本月已用次数';
COMMENT ON COLUMN rawg_key_status.remaining_this_month IS '本月剩余次数；为 0 表示该 key 已用满';
COMMENT ON COLUMN rawg_key_status.used_today IS '今日已用次数';

COMMIT;
