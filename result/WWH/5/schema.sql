-- ══════════════════════════════════════════════════════════════════════════
-- WWH 第 5 项 · 本地 SQLite schema（只属于 result/WWH/5，不动公共采集库）
--
-- 本文件是**唯一真源**：wwh5/storage.py 的 connect() 每次开连接都会执行一遍全文
-- （所有语句都幂等，可反复跑），所以改表结构只改这里。
--
-- 设计原则——**输入与模型产出全部留痕**：
--   输入快照   games / achievements      导入后不再变，保证可复算
--   调用审计   model_calls               每次 HTTP 尝试一行（含失败）
--   派生标注   *_labels                  指回 call_id，可追溯到具体那次请求
-- 三者分开存，是为了任何一条标注都能回答「哪次调用、用什么提示词、输入是什么」。
-- ══════════════════════════════════════════════════════════════════════════

-- 每条连接都要显式打开外键约束（SQLite 默认是关的，不写这句外键形同虚设）
PRAGMA foreign_keys = ON;

-- ── 1. 运行元数据 ─────────────────────────────────────────────────────────
-- 键值对表。存 dataset_version、input_sha256、active_annotation（当前绑定的
-- 模型 + 提示词版本 + 批次大小）、导出排序口径与 SQL 等，用于复现与版本校验。
-- active_annotation 的作用：模型/提示词变了却没换库时直接报错，
-- 防止新旧标注混在同一张表里无法区分。
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- ── 2. 输入快照：游戏帧 ───────────────────────────────────────────────────
-- 从云库一次性只读导入的固定样本（评价数最高的前 1000 款），导入后不再更新。
--   frame_rank      排名（1 起），UNIQUE 保证一个名次只对应一款游戏
--   review_count    SteamSpy 好评数＋差评数，就是排序依据本身
--   blocked_reason  质量阻塞原因（映射未解决 / 无成就 / 缺展示名）；
--                   **非空即不送模型**，但游戏仍留在样本里，不用下一名递补
--   payload         该游戏导入时的全部原始字段（JSON），保留完整信息
CREATE TABLE IF NOT EXISTS games (
    appid INTEGER PRIMARY KEY, frame_rank INTEGER UNIQUE NOT NULL,
    review_count INTEGER NOT NULL, blocked_reason TEXT, payload TEXT NOT NULL
);

-- ── 3. 输入快照：成就 ─────────────────────────────────────────────────────
--   local_id      本地快照内的成就定位号（字符串）。**只是主键，不是剧情顺序**，
--                 发给模型时也只作为引用 ID，防止模型按 ID 大小推断先后
--   display_name  展示名（成就名映射的产物；内部名不出现在分析与报告中）
--   percent       Steam 全局完成率 0~100，CHECK 卡住越界值
--                 ⚠️ 这个字段**不发给模型**——它是结果变量，发了模型就会按
--                 「解锁率低 = 主线」倒推，而不是真的读文本判断
CREATE TABLE IF NOT EXISTS achievements (
    appid INTEGER NOT NULL REFERENCES games(appid), local_id TEXT NOT NULL,
    display_name TEXT NOT NULL, description TEXT, percent REAL NOT NULL
        CHECK(percent >= 0 AND percent <= 100),
    PRIMARY KEY(appid, local_id)
);

-- ── 4. 模型调用审计（每次 HTTP 尝试一行）──────────────────────────────────
-- 为什么逐次记录而不是只记成功：计费与排错都要看失败的那几次。
--   kind              classification（成就分类 + 游戏维度）或 story（主线排序）
--   model / prompt_version / input_hash
--                     三者 + status='success' 构成**续跑去重键**：
--                     命中即直接复用已存响应，不发请求、不重复计费
--   request_messages  请求原文，能复现当时到底发了什么
--   response_body     响应原文，**API key 明文会先替换成 [REDACTED]** 再存
--   usage             归一化后的 token 用量（JSON），非数字/布尔字段会被过滤
--   status            running 进行中 / success 成功 / error 可重试失败 /
--                     interrupted 被中断（下次启动会把遗留的 running 统一改判成它）
--   attempt           第几次尝试（上限见 wwh5/params.py 的 MAX_ATTEMPTS）；都失败记 error，
--                     该游戏下次可重跑
--   error             归纳后的失败原因（**不含传输异常原文**，避免把 URL 或密钥写进库）
CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY, appid INTEGER NOT NULL REFERENCES games(appid),
    kind TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL, request_messages TEXT NOT NULL,
    response_body TEXT, usage TEXT, status TEXT NOT NULL
        CHECK(status IN ('running','success','error','interrupted')),
    attempt INTEGER NOT NULL, error TEXT, started_at TEXT NOT NULL,
    finished_at TEXT
);

-- 续跑查询专用索引：每次调用前都要按
-- (model, prompt_version, input_hash, status='success') 查一遍是否已完成
CREATE INDEX IF NOT EXISTS call_resume ON model_calls(model,prompt_version,input_hash,status);

-- ── 5. 派生标注（模型产出，与调用记录分表）────────────────────────────────
-- 三张表都带 call_id 指回 model_calls：任何一条标注都能追溯到具体那次请求，
-- 反过来也能查出某次调用产出了哪些标注。
-- ⚠️ 标注写入与调用状态更新在**同一事务**提交（见 deepseek.py 的 _execute），
--    避免「标了但状态没落库」导致断点后重复调用已付费的请求。

-- 游戏维度（玩法 / 题材 / 表现形式 / 单人多人），每款游戏一行，来自第一批调用；
-- 后续批次必须原样重复这套维度，程序会校验，不一致就整批判失败
CREATE TABLE IF NOT EXISTS game_labels (
    appid INTEGER PRIMARY KEY REFERENCES games(appid), call_id INTEGER NOT NULL REFERENCES model_calls(id),
    payload TEXT NOT NULL
);

-- 逐个成就的分类结果（主类 / 本体-DLC / 联机要求 / 置信度 / 依据）
-- 主键与 achievements 对齐，外键保证不会写进不存在的成就
CREATE TABLE IF NOT EXISTS achievement_labels (
    appid INTEGER NOT NULL, local_id TEXT NOT NULL, call_id INTEGER NOT NULL REFERENCES model_calls(id),
    payload TEXT NOT NULL, PRIMARY KEY(appid,local_id),
    FOREIGN KEY(appid,local_id) REFERENCES achievements(appid,local_id)
);

-- 主线剧情排序结果（有序节点列表 + unified_ending），每款游戏一行；
-- 只有该游戏分类全部成功才会产生，候选是「已判为 main 的成就」
CREATE TABLE IF NOT EXISTS story_labels (
    appid INTEGER PRIMARY KEY REFERENCES games(appid), call_id INTEGER NOT NULL REFERENCES model_calls(id),
    payload TEXT NOT NULL
);

-- ── 6. 分析运行记录 ───────────────────────────────────────────────────────
-- 每次 analyze 追加一行（不覆盖）：metadata 记数据版本与分析参数，
-- metrics 记全部指标。用于回答「报告里这个数字是哪次、用哪个数据版本算出来的」。
CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY, analyzed_at TEXT NOT NULL, metadata TEXT NOT NULL, metrics TEXT NOT NULL
);
