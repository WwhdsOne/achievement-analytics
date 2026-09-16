# achievement-analytics

> Steam 成就数据分析：分析用户和玩家更愿意玩什么样的游戏

## 一句话简介

以 **Steam Web API**（玩家成就解锁、全局成就百分比、游玩时长）+ **appdetails**（游戏详情与成就架构）+ **SteamSpy**（游戏元数据）为数据源，把"玩家愿意玩"操作化为可测量的参与度信号（游玩时长、成就完成深度、活跃度、全成就比例），再归因到游戏特征——**难度结构（IRT 建模）+ 类型 / 价格 / 标签 / 热度**——回答"用户和玩家更愿意玩什么样的游戏"。

## 核心研究问题

**总目标：用户和玩家更愿意玩什么样的游戏？**（"愿意玩"用参与度指标操作化：游玩时长、完成深度、活跃度、全成就比例）

| # | 问题 | 方法与角色 |
|---|------|-----------|
| Q1（支撑） | 成就难度与玩家能力如何联合建模？ | IRT 2PL 模型（难度 b、区分度 a、能力 θ），**全局完成率作为难度 b 的代理指标交叉验证**；难度结构是解释偏好的核心特征 |
| Q2（核心） | 什么类型的游戏受欢迎 / 被弃坑？为什么玩家更愿意玩？ | 特征回归 + SHAP 归因，特征含 SteamSpy 标签 / 价格 / 热度 / 难度结构，直接回答总目标 |

## 数据源（Steam 全家桶）

| 数据来源 | 关键字段 | 说明 |
|---------|---------|------|
| Steam Web API `GetPlayerAchievements` / `GetOwnedGames` | 玩家成就解锁状态、`unlocktime`、游玩时长（分钟） | 仅公开档案；unlocktime 精度为**天** |
| Steam Web API `GetGlobalAchievementPercentagesForApp` | `name`（API 内部名称）+ `percent`（全局完成率） | **难度核心数据**：percent 直接作 IRT 难度 b 的代理指标 |
| 商店接口 `appdetails`（单 appid，批量已失效） | 游戏名、类型、价格、成就概览（仅 10 个 highlighted 展示名） | 游戏元数据（Q2 特征）；完整名称映射走 `GetSchemaForGame` |
| SteamSpy | owners 估算、标签、价格、CCU | 特征补充；owners 为估算值，只作数量级参考 |

### 成就名称映射（清洗阶段核心步骤）

两个接口的 `name` 字段都是 **API 内部名称**（如 `ACH41`），游戏内显示的真名在 `displayName`（如 `The Dark Soul`）。完整映射的唯一来源是 `GetSchemaForGame`（需 API key）；`appdetails` 只有 10 个 highlighted 展示名，不敷使用。以内部名称为键 JOIN schema 与全局完成率，为每款游戏生成**标准成就数据文件**（`api_name` / `display_name` / `percent`），后续建模与可视化直接消费。详见 `docs/plan.md`。

## 方法论亮点

1. **"愿意玩"可测量**：把偏好问题操作化为参与度指标（时长、完成深度、活跃度、全成就比例），观察性数据变成可建模对象。
2. **SHAP 归因**：特征回归 + SHAP 定量拆解游戏元数据（标签、价格、热度、难度结构）对参与度的贡献，回答"玩家更愿意玩什么"而不是只看相关系数。
3. **全局完成率 = 难度先验**：`GetGlobalAchievementPercentagesForApp` 的 percent 给出 IRT 难度参数 b 的外部代理，与模型估计值交叉验证。
4. **IRT 2PL 模型**：一个概率模型同时输出成就难度与玩家潜在能力，为偏好分析提供难度结构特征。对标并尝试超越 Cunha et al. 2024（arXiv:2404.15295）。
5. **名称映射 pipeline**：清洗阶段自动完成内部名称 → 显示名称的 JOIN，一次清洗、全程复用。
6. **反作弊预处理**：通过时间戳异常（乱序 / 同日全解锁 / 早于购买时间）识别 SAM 用户，保证统计干净。

## 团队分工（5 人）

| 角色 | 职责 |
|------|------|
| 爬虫 | Steam Web API / appdetails / SteamSpy 采集，批量查询、缓存、断点续爬 |
| 清洗 | 数据质量、schema 统一、**名称映射**、**时间戳反作弊**、参与度指标口径 |
| 难度建模（Q1） | IRT 2PL、全局完成率交叉验证、难度结构特征输出 |
| 特征回归（Q2） | 参与度指标构造、特征工程、回归 + SHAP 归因 |
| 可视化 | 仪表盘、一致性散点图、SHAP 图、最终报告图表 |

## 已知方法学坑（报告必须讨论）

- **选择偏差**：公开档案偏核心玩家，参与度系统性高估；隐藏档案的玩家完全不可见
- unlocktime 为**天级精度**：作息画像、分钟级解锁节奏分析不可行
- 全局完成率的分母是"曾启动过游戏的账号"口径，与"购买者"口径有差异
- SteamSpy owners 是估算区间，不能当精确销量
- appdetails 与 Web API 的成就列表可能不一致（DLC / 隐藏成就），需在映射时做差集报告
- Q2 是观察性数据：SHAP 解释的是模型归因，不能直接当因果结论

## 快速开始

```bash
git clone https://github.com/WwhdsOne/achievement-analytics.git
cd achievement-analytics
uv sync
```

## 目录结构

```
achievement-analytics/
├── README.md          # 本文件
├── docs/plan.md       # 分析计划、里程碑、验收清单
├── AGENTS.md          # AI 助手 / 协作规范
├── crawler/           # steam_api.py / steamspy.py 爬虫模块
├── cleaning/          # 清洗、名称映射与反作弊
├── modeling/          # irt/（Q1 难度建模）+ regression/（Q2 偏好归因）
├── viz/               # 可视化
├── notebooks/         # EDA 探索
├── learning-logs/     # 中文工作日志（YYYY-MM-DD.md）
├── data/              # 数据目录（不入库，见 AGENTS.md）
└── tests/             # 单元测试
```

状态：**文档已定稿——目标为分析玩家更愿意玩的游戏（Q2 核心偏好归因 + Q1 支撑难度建模，Steam API 数据源）**（见 docs/plan.md）。
