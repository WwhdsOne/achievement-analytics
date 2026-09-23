## 项目定位

Steam 成就数据分析，**总目标：分析用户和玩家更愿意玩什么样的游戏**。先读 `README.md` 了解背景，再读 `docs/plan.md` 了解研究问题与排期。做任何事之前确认处于正确阶段，不要提前实现后期任务。

> ⚠️ `docs/plan.md` 的**「数据源」与「清洗核心步骤」两节已过期**：它仍按「逐玩家 API + 需 key 的
> `GetSchemaForGame`」写，而实际在 2026-09-15 / 09-17 已改为**纯游戏级、免 key（RAWG 除外）**方案。
> 数据侧的当前口径以本文件为准，限额速查见 `docs/sources.md`。

当前研究范围（详见 `docs/plan.md`）：

- **Q2（核心）**：玩家偏好特征回归 + SHAP 归因——"愿意玩"操作化为参与度指标（时长 / 完成深度 / 活跃度 / 全成就比例），归因到游戏特征；
- **Q1（支撑）**：IRT 难度与玩家能力建模——为偏好分析提供难度结构特征；
- 分群、弃坑生存分析、跨游戏迁移、PSN 数据源均已裁剪，不要复活。

## 目录约定

```
crawler/    每个数据源一个模块（http.py 共享限速层 · config.py 配置 · registry.py 源注册表
            · store_applist.py 全量 appid · store_search.py 商店枚举
            · steam_api.py · steamspy.py · rawg.py）；
            test_crawl.py 是单款游戏抓取演示，用 `uv run python -m crawler.test_crawl` 跑
cleaning/   抓取编排与入库，**产物是 PostgreSQL 数据仓库**，不是 data/processed
            · schema.sql 数据库唯一真源（表 / 视图 / 源清单）· db.py 连接与 apply_schema
            · writers.py 单源抓取+入库 · seed.py 灌全量游戏 · worker.py gap 驱动回填
            · rawg_keys.py RAWG 密钥池（多 key 协调取用）
            · repair_mapping.py 成就名映射收尾修复（两源顺序不一致时按 percent 重对齐）
modeling/   Q1 与 Q2 各一个子包：irt/（Q1 难度建模，**目前仅占位**）
            · regression/（Q2 偏好归因，**尚未创建**）；一个实验一个脚本，
            实验记录统一写 modeling/experiments.md
dashboard/  内部状态面板（标准库 http.server，零额外依赖）：队列进度 / 单游戏查询 /
            按任务方式补抓 · `uv run python -m dashboard.app`
viz/        图表函数，与 notebook 解耦
notebooks/  只做探索，不放正式逻辑；正式逻辑沉淀到模块
data/       全部不入 git。interim/ 与 processed/ 目前是**空占位**（未启用）
docs/       commands.md（命令手册，**日常先看这个**）· sources.md（数据源限额速查）
            · multi-machine.html（多机分工与防冲突讲解）· data-pipeline.html（流程讲解）
            · plan.md（研究问题与排期，数据源两节已过期）
learning-logs/  中文日志，每天一个文件
tests/      关键函数必须有测试（响应解析、schema 契约、队列状态机、写入层）
```

## 数据获取流程（2026-09-17 起：gap 驱动）

**当前数据范围：只取 2026 年以前发售的游戏**（`seed --before-year 2026`，已是默认）。
实测采样估计该范围约 **49,900 款**（占带成就游戏 81,850 款的 61%）；2026 年新作 14.8%、
发售日缺失/未发售 24.2% 都被排除。要改范围用 `--before-year` 或 `--all-years`。

不再靠人工维护的目标清单，改为**全量枚举 + 按缺口回填**：

1. **种子** `uv run python -m cleaning.seed` —— 用 `crawler/store_search.py`
   （免 key）枚举全部**带 Steam 成就的游戏（当前约 81,850 款，数字每日浮动）**，写入 `games`
   + `store_search_games`。成本约 819 次请求，顺利时 1s 间隔约 14 分钟；
   **遇限流会留空洞，需重跑补齐**（重跑会重新发那些页的请求）。
   随后把 (游戏 × 逐款源) 展开物化成 `fetch_tasks` 任务队列。
2. **回填** `uv run python -m cleaning.worker` —— 反复「取缺口 → 抓 → 回填」，
   可随时 Ctrl-C、重跑自动续。进度看 `ingest_progress` 视图，
   「还缺什么」看 `ingest_gaps`。

**规模是运行参数**：`seed --sample N --order random` 先物化一小批跑通验收，
再扩到全量。别一上来就全量——管道有 bug 时不该等几十小时才发现。

要点：

- **数据源清单与限速/配额只在 `sources` 表**（`schema.sql`）与 `crawler/registry.py`
  两处声明，`tests/test_registry.py` 断言两者一致；加源要同时改，别只改一处
- **源分两类**：`bulk`（一次请求覆盖多款：商店搜索 100/次、SteamSpy `all` 1000/次）
  **不进队列**；`per_game`（一次一款）才进 `fetch_tasks`
- `fetch_tasks`（可变**当前状态**·该抓谁）与 `ingest_log`（不可变**审计历史**·何时抓的）
  分工明确，不要混用
- 循环有**终止条件**：`empty` 是确定性终态不重试，`error` 退避重试到
  `sources.max_attempts` 后转 `exhausted`。因此 `ingest_gaps` 单调收敛
- RAWG 等按量计费的源**不暴露剩余额度**（实测响应头无 x-ratelimit），
  配额靠 `api_usage` 自己记账，余额查 `quota_status`
- appdetails 中英文是**两次独立请求**：队列路径下 `appdetails_en` / `appdetails_zh`
  各自只拉自己要的语言；`crawler/steam_api.py` 的 `fetch_official_names()` 一次拉两个，
  **队列里别用**，否则请求数翻倍
- **枚举会遇到限流**：商店搜索实测连续约 30 次请求后开始失败。取不到的偏移记成「空洞」，
  跑完会报空洞数——**有空洞就说明帧不完整**，重跑同一条命令会重新发那些页的请求、只补空洞

### 多机并行（2026-09-17 起）

用多台机器提高吞吐的做法与前提（讲解页见 `docs/multi-machine.html`）：

- **没有分工表**：任务不预先分配给机器，所有 worker 对等，各自从共享队列**抢占**。
  谁快谁多做，机器下线后它没做完的任务立刻被别人抢走
- **抢占是原子的**：`worker` 的 claim 用一条
  `UPDATE ... WHERE (appid, source) IN (SELECT ... FOR UPDATE SKIP LOCKED) RETURNING`
  同时完成「选任务」与「写租约」，所以多台机器共用一个库不会重复抓同一条
- **`SKIP LOCKED` 是不卡的关键**：别人锁着的行直接跳过而不是排队等待——否则机器越多
  排队越长，最后比单机还慢
- **租约（`claimed_by` / `lease_until`，默认 5 分钟）**：到期即自动可被重新抢占，
  所以 **worker 崩溃不会让任务永久卡住**，也不需要额外的僵尸任务清理。
  ⚠️ `claimed_by` 只是「主机名:pid」标签，**不是互斥手段**——真正的互斥靠数据库行锁
  与租约时间戳，字符串本身写错/重复都不影响正确性
- **任务粒度是「游戏 × 数据源」而非游戏**：同一款游戏的 6 条任务可能落在两台机器上
  （批次边界处），这是允许的——每个源独立写入且幂等，最终数据与单机跑完全一致
- **前提：所有机器连同一个 Postgres**（`.env` 里改 `POSTGRES_HOST`）。队列、配额账本、
  密钥池都在那个库里。**无本地缓存**，换机器接着跑即可
- **RAWG 是唯一「加机器无效」的源**：20,000 次/月**绑定 API key**，扩容只能加 key，见下
- **SteamSpy 只有按机器的速率限制**（2026-09-22 取消自设的 1000/天上限）：N 台机器
  对它的聚合速率 = N × 1 req/s，不加协调。与 RAWG 的按 key 配额是两回事
- **无成就的游戏会被自动剔除**：`global_ach` 对无成就 appid 返回 403（已归一成
  「确定性无数据」），worker 确认后立即取消该游戏其余任务——**最贵的 RAWG 放在
  最后一个源**（见 `sources.priority`），被剔除的游戏不花配额

⚠️ **唯一会「卡住所有人」的操作是 DDL**（2026-09-22 实际踩到）：
`db init` 要拿 `DROP VIEW` / `CREATE VIEW` 的排他锁，一旦被别的会话挡住（典型是
`idle in transaction` 的滞留连接），排他锁会**排队**，而排在它后面的所有请求
（包括 worker 抢任务）也一并堵住——整个管道停摆。因此：

- **建表/改表只由一个人执行一次**，不要在别人 worker 正跑时改结构
- **不要中途强杀正在执行的 `db init`**：客户端没了但服务端会话仍在等锁，形成死结
- 怀疑卡住时查 `pg_stat_activity`：`state='idle in transaction'` 且 `xact_start` 很旧的
  会话就是元凶，`SELECT pg_terminate_backend(pid)` 清掉即可（worker 会自动重连）

### RAWG 密钥池

**RAWG 任务有评价数阈值（2026-09-18 定，默认 review_count ≥ 100）**：seed 物化任务时
低于阈值的游戏**不建** RAWG 任务（`seed.py` 的 `INSERT_TASKS`，可用
`--rawg-min-reviews` 调整，传 0 关闭）。理由：实测 RAWG 成本 ≈ 6.3 次请求/游戏
（单 key 月配额 20,000 ≈ 只够 3,100 款），而试水证实低评价游戏在 RAWG 上几乎必然
没数据。改阈值 = 改 RAWG 花费预算，帧全量入库后按「达标游戏数 × 6.3 ≈ 所需配额」复核。

RAWG 配额按 key 计，所以 key 放在**共享库**里（不是各机器本地 `.env`），
这样所有机器看到同一份余额并协调取用：

```bash
uv run python -m cleaning.rawg_keys add --key <KEY> --label <谁的>   # 注册
uv run python -m cleaning.rawg_keys list                            # 看各 key 余额
uv run python -m cleaning.rawg_keys disable --key-id 3              # 停用已超额的
```

- 取用接口 `cleaning/rawg_keys.reserve_key`：**原子地**挑一个本月还有余额的 key 并计数 +1；
  `worker` 启动时把它注入 `crawler.rawg.set_key_provider`，每次真实请求消耗一次
- `rawg_key_status` 视图**刻意不暴露 key 明文**（只给尾 4 位），避免查额度时把密钥
  读进终端或日志
- ⚠️ RAWG 条款：免费档限**非商业用途**，且要求使用数据的页面加 RAWG 回链。
  本项目是课程项目符合非商业；**回链要求在最终报告/展示页里必须落实**

## 环境规范

- Python 3.13，统一用 **uv** 原生工作流管理依赖（`pyproject.toml` + `uv.lock`）：`uv sync` 建环境并装依赖
- 依赖变更必须同步 `pyproject.toml` 与 `uv.lock` 并在日志中说明
- 执行脚本统一 `uv run <cmd>`（如 `uv run pytest`），不必手动 activate
- **数据库跑在腾讯云**（2026-09-17 起不再用本地 Docker；服务器上是 Docker 里的 PostgreSQL）：
  `.env` 里配 `POSTGRES_HOST` / `POSTGRES_PORT`（**本项目当前是 15432**，不是默认 5432）/
  `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`
- ⚠️ **自建库不支持 SSL**：`POSTGRES_SSLMODE=require` 会直接连不上（2026-09-18 实测），
  留空或注释掉；托管型云库（如阿里云 RDS）才需要
- ⚠️ **云库是共享的**：**建表/改表只走 `uv run python -m cleaning.db init`，且只由一个人执行**
  （worker/seed 启动仅校验、不碰 DDL）。多机同时 init 会争排他锁，排他锁排队会把所有请求
  （含大家抢任务）一起堵住——2026-09-22 实际踩到，详见「多机并行」一节
- DB 连接参数读 `.env`，统一走 `crawler/config.py`
- ⚠️ **删库 = 丢掉 RAWG 配额账本**：`api_usage` 与密钥池用量都在库里，删库会让当月已用
  次数归零、密钥池「看起来」满额。删库前先记下 `quota_status` 与 `rawg_key_status`
- **只用公开数据源**；唯一的例外是 **RAWG**（评分 / 时长 / 弃坑率 / 题材标签），其 key 放项目根目录 `.env`（不入 git），读取统一走 `crawler/config.py`
- IGDB 已于 2026-09-15 放弃，不要复活：它需 Twitch OAuth2，而 Twitch 两步验证在国内手机号上走不通；其时长/评分价值已被 RAWG 覆盖

## 数据规范

- **PostgreSQL 是唯一事实源**（2026-09-17 起废除本地文件缓存）：抓到的数据只进云库，
  各源表（`games` / `store_search_games` / `achievements` …）就是原始记录。
  **因此云库必须开自动备份**（按天快照）——废缓存后「删库」等于全部重抓 + 重花 RAWG 配额
- 抓取时间由 HTTP 层记录（`crawler.http.last_fetched_at`，成功拿到响应的时刻），
  落在 `ingest_log.fetched_at`。它是「数据何时获取」，不是「何时写库」
- `data/` 分层：`interim/` → `processed/`。**两层目前是空占位**（建模阶段才会启用）；
  当前管道的产物全部在 PostgreSQL
- **原始数据不进 git**，git 只跟踪代码与 schema
- schema 变更必须同步更新 `cleaning/schema.sql`（**唯一真源**）；**建表/改表只能通过
  `uv run python -m cleaning.db init`**（幂等），worker/seed 启动时不碰 DDL、只校验就绪
- **成就名称映射是硬性要求**：全局完成率接口给的是 API 内部名（如 `ACH41`）+ percent，
  展示名从 Steam 社区成就页取；两源**顺序一致**，按位对齐即完成映射（2026-09-15 实测）。
  映射结果落在 `achievements.api_name` → `achievements.display_name`；
  建模与报告**只允许用 `display_name`**，禁止内部名出现在正式分析与报告中。
  ⚠️ 顺序一致用**逐位容差**判定（≤0.5 个百分点视为一致，两源有 ≤0.1 的舍入/缓存差，
  精确比较会误报）；判定不通过的记进 `mapping_issues` 台账。
  **全量跑完后必须收尾**：`uv run python -m cleaning.repair_mapping --from-issues`
  （按 percent 重对齐，两源免费不花 RAWG 配额），建模时过滤 `resolved=false` 的 appid
- 全局完成率 percent 随抓取批次漂移，建模必须绑定固定数据版本：在 `dataset_versions`
  登记版本号；追溯真实抓取时间看各源表的 `fetched_at` 与 `ingest_log.fetched_at`

## 爬虫规范（硬性）

- **限速按源配置，不是一刀切 1s**。权威清单在 `sources` 表（`schema.sql`）与
  `crawler/registry.py`：多数源 ≥1s，**SteamSpy `request=all` 是 60s**（官方文档）。
  计时**按 host 分桶**，不同站点互不排队。限额速查见 `docs/sources.md`
- **没有缓存层**（已废除）：防重复靠 `fetch_tasks` 的任务状态——已完成的任务不会被
  重跑；多机共享队列，不需要本地缓存
- 失败重试 ≤ 3 次，且**重试之间必须有指数退避**（2s / 4s，封顶 30s）。没有退避时几次尝试会
  挤在同一个限流窗口里全部撞墙——实测把一次 819 页的枚举在第 32 页整轮打断（2026-09-17）
- 失败记录到日志，**不中断整体任务**；批量枚举再包一层页级重试，取不到的偏移记「空洞」并继续翻页
- 按量计费的源（RAWG）**不暴露剩余额度**（实测响应头无 x-ratelimit 字段），
  每次真实请求都要在 `api_usage` 记账，否则无从判断还能抓多少
- 不爬任何需要登录态才能访问的页面
- appdetails 实测**不支持批量**（多 appid 返回 400，2026-09-15 验证），单 appid 请求

## 代码规范

- 模块化优先：函数单一职责，方便后期替换（如难度建模从手工指标换成 IRT）
- 公共函数必须有类型注解与 docstring
- 统一用 `rg` 替代 grep 检索代码
- 可视化配色遵循中国股市惯例之外的通用色板；涨跌类图表才用红涨绿跌
- 随机过程必须设 `random_state=42`，保证实验可复现

## 建模规范

- **baseline 先行**：任何高级模型（IRT 2PL / 梯度提升树）上线前，必须先有简单对照组（原始全局完成率 / Rasch 1PL / 线性回归）
- 每次实验记录：日期、数据版本、参数、指标，写入 `modeling/experiments.md`
- 指标约定：回归用 R² / RMSE + 交叉验证，归因用 SHAP（须说明是模型归因而非因果）；IRT 报告收敛诊断
- Q2 的 SHAP 结论必须区分"模型归因"与"因果效应"，报告措辞不得越界

## Git 工作流（全组统一）

远程仓库：`origin` → https://github.com/WwhdsOne/achievement-analytics.git

1. 分支：`main` 保护，功能开发走 `feat/xxx` 分支，合并前自测
2. commit message：`<scope>: <做了什么>`，中文描述，如 `crawler: 增加成就时间戳字段`
3. 每日流程：**code/debug → commit → 写中文日志 `learning-logs/YYYY-MM-DD.md` → push**
4. 日志格式：今天做了什么 / 遇到什么坑 / 明天计划，坑与解法必须写清，供队友检索
5. **不要擅自提交**：改动做完先停下汇报，等明确说"提交"再 commit。`commit` / `amend` / `push` 都必须等明确指示，不要顺手做

## 禁止事项

- 禁止把爬取到的原始数据提交进仓库（`data/` 全部不进 git）
- 禁止把 `.env` 提交进仓库（内含 RAWG key；`.gitignore` 已挡，但新增密钥文件时务必确认）
- 禁止在 notebook 里写正式管道逻辑（探索可以，沉淀必须进模块）
- 禁止跳过 baseline 直接上深度模型
- **云库必须开自动备份**（按天快照）：数据只存在库里，没有本地缓存兜底
- 禁止用未映射的 API 内部名称（如 `NEW_ACHIEVEMENT_1_1`）出现在正式分析与报告中
- 不确定的设计决策先确认，不要自行拍板改 schema
