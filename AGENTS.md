## 项目定位

Steam 成就数据分析，**总目标：分析用户和玩家更愿意玩什么样的游戏**。先读 `README.md` 了解背景，再读 `docs/plan.md` 了解排期与当前阶段。做任何事之前确认处于正确阶段，不要提前实现后期任务。

当前研究范围（详见 `docs/plan.md`）：

- **Q2（核心）**：玩家偏好特征回归 + SHAP 归因——"愿意玩"操作化为参与度指标（时长 / 完成深度 / 活跃度 / 全成就比例），归因到游戏特征；
- **Q1（支撑）**：IRT 难度与玩家能力建模——为偏好分析提供难度结构特征；
- 分群、弃坑生存分析、跨游戏迁移、PSN 数据源均已裁剪，不要复活。

## 目录约定

```
crawler/    每个数据源一个模块（http.py 共享限速/缓存层 · registry.py 源注册表 · steam_api.py · steamspy.py · rawg.py · store_search.py 全量枚举）；test_crawl.py 是单款游戏抓取演示，用 `uv run python -m crawler.test_crawl` 跑
cleaning/   清洗、成就名称映射与反作弊，输入 data/raw，输出 data/processed；schema.sql 是数据库唯一真源
            · writers.py 单源抓取+入库（两条路径共用）· seed.py 灌全量游戏 · worker.py gap 驱动回填
modeling/   irt/（Q1 难度建模）+ regression/（Q2 偏好归因）两个子包，一个实验一个脚本
viz/        图表函数，与 notebook 解耦
notebooks/  只做探索，不放正式逻辑；正式逻辑沉淀到模块
data/       不入 git（见下）
docs/       plan.md 等正式文档
learning-logs/  中文日志，每天一个文件
tests/      关键函数必须有测试（schema 校验、名称映射、反作弊规则）
```

## 数据获取流程（2026-09-17 起：gap 驱动）

不再靠人工维护的目标清单，改为**全量枚举 + 按缺口回填**：

1. **种子** `uv run python -m cleaning.seed` —— 用 `crawler/store_search.py`
   （免 key）枚举全部**带 Steam 成就的游戏（当前约 81,850 款）**，写入 `games`
   + `store_search_games`。成本约 819 次请求、14 分钟，一次灌满。
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
- 不要盲跑 `fetch_official`（一次两请求）：队列路径下 `appdetails_en` / `appdetails_zh`
  各自只拉自己要的那个语言，否则请求数翻倍

## 环境规范

- Python 3.13，统一用 **uv** 原生工作流管理依赖（`pyproject.toml` + `uv.lock`）：`uv sync` 建环境并装依赖
- 依赖变更必须同步 `pyproject.toml` 与 `uv.lock` 并在日志中说明
- 执行脚本统一 `uv run <cmd>`（如 `uv run pytest`），不必手动 activate
- **只用公开数据源**；唯一的例外是 **RAWG**（题材标签 / 评分 / 时长 / 弃坑率），其 key 放项目根目录 `.env`（不入 git），读取统一走 `crawler/config.py`
- IGDB 已于 2026-09-15 放弃，不要复活：它需 Twitch OAuth2，而 Twitch 两步验证在国内手机号上走不通；其时长/评分价值已被 RAWG 覆盖

## 数据规范

- `data/` 分层：`raw/`（原始，只读不改）→ `interim/`（中间）→ `processed/`（建模输入）
- **原始数据永不入库**（体积大且含个人信息），git 只跟踪处理后的样本与 schema
- schema 变更必须同步更新 `cleaning/schema.sql`（**唯一真源**）并通知全组；`apply_schema()` 幂等，改完重跑即可，无需手工迁移
- **成就名称映射是硬性要求**：`GetGlobalAchievementPercentagesForApp` 返回的是 API 内部名称（如 `ACH41`），展示名要从 Steam 社区成就页取；两个数据源的成就**顺序一致**，按位对齐即完成映射（2026-09-15 实测）。建模只消费映射后的标准成就数据文件，禁止直接用内部名称进报告
- 全局完成率 percent 随抓取批次漂移，建模必须绑定固定数据版本，记录抓取时间

## 爬虫规范（硬性）

- 限速：请求间隔 ≥ 1s，遵守各站 robots / ToS，只采公开数据
- 必须带缓存层（已爬过的 URL/AppID 不重复请求），断点续爬
- 爬虫失败重试 ≤ 3 次，失败记录到日志，不中断整体任务
- 不爬任何需要登录态才能访问的页面
- appdetails 实测**不支持批量**（多 appid 返回 400，2026-09-15 验证），单 appid 请求；省配额靠缓存层不重复请求

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

- 禁止把爬取到的原始数据提交进仓库（`data/` 全部不入库）
- 禁止把 `.env` 提交进仓库（内含 RAWG key；`.gitignore` 已挡，但新增密钥文件时务必确认）
- 禁止在 notebook 里写正式管道逻辑（探索可以，沉淀必须进模块）
- 禁止跳过 baseline 直接上深度模型
- 禁止删除或覆盖 `data/raw/` 下任何文件
- 禁止用未映射的 API 内部名称（如 `NEW_ACHIEVEMENT_1_1`）出现在正式分析与报告中
- 不确定的设计决策，先在群里问，不要自行拍板改 schema
