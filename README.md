# achievement-analytics

> Steam 成就数据分析：分析用户和玩家更愿意玩什么样的游戏

## 一句话简介

以 **Steam 公开接口**（商店 `appdetails`、全局成就完成率、社区成就页、SteamSpy）+ **RAWG**（评分 / 时长 / 弃坑率 / 题材）为数据源，覆盖 **2026 年以前发售、带 Steam 成就的全部游戏（约 5 万款）**，把"玩家愿意玩"操作化为可测量的参与度信号（游玩时长、成就完成深度、活跃度、全成就比例），再归因到游戏特征——**难度结构（IRT 建模）+ 类型 / 价格 / 标签 / 热度**——回答"用户和玩家更愿意玩什么样的游戏"。

> 数据是**游戏级聚合**（不含个体玩家档案）：`percent` 是全局完成率，`owners` 是区间估算。
> 这是刻意的口径选择，也决定了结论的措辞边界（见「已知方法学坑」）。

## 核心研究问题

**总目标：用户和玩家更愿意玩什么样的游戏？**（"愿意玩"用参与度指标操作化：游玩时长、完成深度、活跃度、全成就比例）

| # | 问题 | 方法与角色 |
|---|------|-----------|
| Q1（支撑） | 成就难度结构如何刻画？ | IRT（1PL baseline → 2PL），**全局完成率作为难度参数的代理指标交叉验证**；难度结构是解释偏好的核心特征 |
| Q2（核心） | 什么特征的游戏更受欢迎？为什么玩家更愿意玩？ | 特征回归 + SHAP 归因，特征含标签 / 价格 / 热度 / 难度结构，直接回答总目标 |

分群、弃坑生存分析、跨游戏迁移、PSN 数据源均已裁剪，不要复活（见 `docs/plan.md`）。

## 数据获取：多台机器各自跑，为什么不会卡

数据侧只有三步，产物全部落在一台共享的 PostgreSQL 里（**没有本地缓存，数据库是唯一事实源**）：

```
① seed   枚举全量游戏 → 写入 games / store_search_games（约 819 次请求、14 分钟，已由组长跑完）
         并把「每款游戏 × 每个逐款源」展开成任务队列 fetch_tasks（约 27 万条）
② worker 反复「抢一批任务 → 抓 → 写库」，直到抢不到（各人自己的机器上跑）
③ 收尾   repair_mapping --from-issues 修完成就名映射；然后进入建模
```

### 开始干活（每台机器都一样）

```bash
git clone https://github.com/WwhdsOne/achievement-analytics.git
cd achievement-analytics
uv sync                 # Python 3.13 + uv
cp .env.example .env    # 填共享库地址（问组长要）与 STEAM_API_KEY
uv run python -m cleaning.worker            # 开抢，随时 Ctrl-C，重跑自动续
uv run python -m cleaning.worker --progress # 只看进度，不干活
uv run python -m dashboard.app              # 可选：本机开状态面板（队列进度 / 查游戏 / 补抓）
```

RAWG 的任务**不需要各自配 key**：所有人的 key 注册进共享库的密钥池，worker 自动协调取用：

```bash
uv run python -m cleaning.rawg_keys add --key <你的 RAWKey> --label <姓名>
uv run python -m cleaning.rawg_keys list     # 看各 key 本月余额（只显示尾 4 位）
```

### 角色：谁在干什么

| 角色 | 干什么 | 谁来做 |
|---|---|---|
| 云数据库 | 只存放任务队列 / 抓取历史 / 配额账本 / RAWG 密钥池，**本身不抓数据** | 组长维护（腾讯云） |
| worker 机器 | 从共享队列抢任务并抓取，**彼此完全对等** | 全组，每人一条命令 |
| 状态面板 | 看进度、查单个游戏、按任务方式补抓（只读 + 补抓） | 谁想看谁开 |
| seed | 枚举全量游戏 + 物化任务队列，**只跑一次** | 组长（已完成） |

### 为什么不会冲突——五道保险

| 机制 | 解决什么 | 说明 |
|---|---|---|
| **原子抢占** | 两台机器同时抢同一批任务 | 一条 SQL 同时「选任务」和「写租约」（`FOR UPDATE SKIP LOCKED`），行锁是数据库级硬保证 |
| **不排队（SKIP LOCKED）** | 机器互相等锁 → 越加机器越慢 | 别人锁着的行**直接跳过**去拿别的活，而不是排队等待 |
| **租约 5 分钟** | 机器崩溃 / 合盖休眠 / 强杀后任务被永久占住 | 租约到期自动回到可抢状态，**不需要人工清理**；`claimed_by` 只是「谁的租约」标签，不是互斥手段 |
| **幂等写入** | 同一份数据被抓两次（租约到期重抢等） | 全部是 `INSERT ... ON CONFLICT DO UPDATE`，后写覆盖先写，结果一致，代价仅是多几次请求 |
| **终态不重跑** | 已完成任务被反复抓 | `ok / empty / skipped` 是终态，永不再进入可抢集合，队列单调收敛 |

### 为什么不会卡——唯一的例外要知道

**worker 永远不会互相卡住**：抢不到任务时它会打印「抢不到任务了」正常退出，而不会像排队那样干等。

**唯一会卡住所有人的是 DDL（改表结构）**：`db init` 需要排他锁，一旦被滞留连接挡住，
排他锁会排队，后面所有请求（包括大家抢任务）也一起堵住。

> 2026-09-22 实际踩过一次：两个 `idle in transaction` 的滞留会话持锁，加上一个被强杀的
> `db init` 会话在排队等锁，导致整个管道停摆。处理方式是终止滞留会话。

因此约定：**建表/改表只由一个人执行一次；不要在别人 worker 正跑时改结构；不要中途强杀
`db init`**。真遇到全场不动，先查 `pg_stat_activity` 里有没有 `state='idle in transaction'`
的旧会话，清掉即可（worker 会自动重连）。完整讲解见 **`docs/multi-machine.html`**。

### 任务粒度：一条任务 = 一个游戏的一个数据源

一款游戏有 5~6 条任务（中英文详情 / 全局成就率 / 社区成就页 / SteamSpy / 可能还有 RAWG）。
抢占排序是「先按 appid、同游戏内再按源优先级」，所以同一游戏的几条任务通常落在同一批、
由同一台机器处理完。批次边界处可能被两台机器分抓——**这是允许的且无害**，各源独立写入、
彼此幂等，最终数据与单机跑完全一致。

### 两个全局约束（与机器数无关）

- **RAWG**：20,000 次/月**绑定 API key**，不是按机器 → 加机器对 RAWG 没有加速作用，
  扩容只能加 key；所有 key 放共享库的密钥池协调取用。成本实测 ≈ 6.3 次请求/游戏，
  故只给**评价数 ≥ 100** 的游戏建 RAWG 任务（`--rawg-min-reviews` 可调）
- **SteamSpy**：只有按机器的速率限制（1 req/s，官方文档），**没有配额**，
  也不做跨机器协调——N 台机器的聚合速率就是 N req/s（刻意选择，否则 4.9 万任务要跑 49 天）

## 数据源（六个逐款源 + 三个批量源）

| 源 | 类型 | 给什么 | 限速 | 配额 | key |
|---|---|---|---|---|---|
| `appdetails_en` | 逐款 | 英文名、类型、价格、发售日、开发商、官方 genres/categories | 1s | — | 免 |
| `global_ach` | 逐款 | **每个成就的全局解锁率**（难度核心数据） | 1s | — | 免 |
| `community_ach` | 逐款 | 成就**展示名** + 描述（与上一源按位对齐完成映射） | 1s | — | 免 |
| `appdetails_zh` | 逐款 | 官方中文名等本地化信息 | 1s | — | 免 |
| `steamspy` | 逐款 | 拥有量区间、同时在线、好评/差评数、平均/中位时长、**玩家标签** | 1s | — | 免 |
| `rawg` | 逐款 | metacritic、社区评分、平均时长、**玩家状态分布（通关/弃坑/想玩…）**、题材 | 1s | 20,000/月/key | **需** |
| `store_search` / `store_applist` / `steamspy_all` | 批量 | 全量游戏枚举（100 款或 1000 款/次，不进任务队列） | 1s / 1s / **60s** | — | 部分需 |

限额与字段来源速查：`docs/sources.md`；命令手册：`docs/commands.md`。

## 成就名称映射（清洗阶段核心步骤）

全局完成率接口给的是 **API 内部名**（如 `ACH41`）+ percent；显示名在社区成就页。
两源**顺序一致**，按位对齐即完成 `api_name → display_name` 映射（2026-09-15 实测）。
判定用**逐位容差**（≤0.5 个百分点视为一致——两源有 ≤0.1 的舍入/缓存差，精确比较会误报）；
判定不通过的游戏记进 `mapping_issues` 台账。

**全量跑完后必须收尾**：`uv run python -m cleaning.repair_mapping --from-issues`
（按 percent 量化重对齐，两个源免费、不花 RAWG 配额），建模时过滤 `resolved=false` 的 appid。
建模与报告**只允许用 `display_name`**，禁止内部名出现在正式分析中。

## 方法论亮点

1. **"愿意玩"可测量**：把偏好问题操作化为参与度指标（时长、完成深度、活跃度、全成就比例）。
2. **SHAP 归因**：定量拆解标签 / 价格 / 热度 / 难度结构对参与度的贡献，回答"玩家更愿意玩什么"。
3. **全局完成率 = 难度先验**：`percent` 给出 IRT 难度参数的外部代理，与模型估计值交叉验证。
4. **IRT 2PL 模型**：一个概率模型同时输出成就难度与难度结构特征；对标并尝试超越 Cunha et al. 2024 (arXiv:2404.15295)。
5. **可复现的抓取管道**：队列 + 租约 + 幂等写入，多机并行、随时中断续跑、配额全程记账。

## 已知方法学坑（报告必须讨论）

- **只有游戏级聚合，没有个体玩家**：所有"玩家行为"都是人群聚合量（全局完成率、owners 区间），
  不能推断个体偏好；"偏好"是从人群参与度反推的
- **全局完成率会漂移**：模型必须绑定 `dataset_versions` 登记的数据版本
- **RAWG 覆盖不完整**：只给评价数 ≥ 100 的游戏抓取，冷门段缺失（阈值裁剪的代价）
- **SteamSpy owners 是估算区间**，只能作数量级参考；`average_forever` 已失效恒为 0
- **成就名映射有极小概率失效**：两源顺序不一致时按位对齐会张冠李戴，用 `mapping_issues` 台账标记
- **Q2 是观察性数据**：SHAP 解释的是模型归因，不能直接当因果结论

## 快速开始

```bash
git clone https://github.com/WwhdsOne/achievement-analytics.git
cd achievement-analytics
uv sync
cp .env.example .env          # 填 POSTGRES_*（共享云库）与 STEAM_API_KEY
uv run python -m cleaning.db status     # 确认能连上共享库
uv run python -m cleaning.worker        # 开抢
```

## 目录结构

```
achievement-analytics/
├── README.md          # 本文件
├── AGENTS.md          # AI 助手 / 协作规范（数据口径的权威说明）
├── crawler/           # 各数据源模块 + 共享限速层（http.py / registry.py）+ 全量枚举
├── cleaning/          # 抓取编排与入库：schema.sql（唯一真源）/ db.py / writers.py
│                      # seed.py 种子 · worker.py 回填 · rawg_keys.py 密钥池
│                      # repair_mapping.py 映射收尾修复
├── dashboard/         # 状态面板（队列进度 / 查游戏 / 按任务补抓）
├── modeling/          # irt/（Q1 难度建模）+ regression/（Q2 偏好归因）
├── viz/               # 可视化
├── notebooks/         # EDA 探索（不放正式逻辑）
├── docs/              # commands.md 命令手册 · sources.md 限额速查
│                      # multi-machine.html 多机机制 · data-pipeline.html 流程讲解
│                      # plan.md 研究问题与排期
├── learning-logs/     # 中文工作日志（YYYY-MM-DD.md）
├── data/              # 本地数据目录（全部不入 git；当前未启用）
└── tests/             # 单元测试（schema 契约 / 抢占 SQL / 状态机 / 写入层）
```

状态：**数据采集进行中**（队列约 27 万条任务，多机并行回填；完成后进入 Q1 IRT baseline）。
