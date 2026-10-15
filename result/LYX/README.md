# 刘宇翔（LYX）工作空间

当前已跑通DeepSeek成就分类工程链路：定位游戏 → 复用或生成背景摘要 → 一次性判断整款成就的八类多标签 → 校验、累计留档并按门槛写入本地SQLite。这里的 **LLM as Judge** 指模型按固定类别规则作语义判别，不是另设模型复核另一模型的答案。所有个人编辑限于本目录，共享远端数据库永远只读。详细说明与导航集中在[docs](docs/README.md)。

## 今日进度记录：2026-10-15 23:13

以下为北京时间23:13核对本地SQLite得到的进度快照，统计范围为冻结的1000款游戏。

| 状态 | 游戏数量 |
|---|---:|
| 已有 DeepSeek 分类结果入库 | **731 款** |
| 其中整款全部完成 | **598 款** |
| 其中仍有部分成就待处理 | **133 款** |
| 总计仍需处理，包含上述 133 款 | **398 款** |

另外 **4 款没有成就**。

成就总量及进度：

| 状态 | 成就数量 |
|---|---:|
| **总成就数量** | **71,465 个** |
| DeepSeek 已完成分类 | **43,284 个** |
| 受保护、无需自动处理 | **18 个** |
| 仍需处理 | **28,163 个** |

整款完成数、部分完成数和成就完成数分别统计；以上是本次核查的固定快照，后续运行的实际进度以本地SQLite为准。

## 文档导航

| 文档 | 内容 |
|---|---|
| [总体规划](docs/plan.md) | 已实现链路、验证边界与后续任务 |
| [运行说明](docs/PROCESS.md) | 命令、写库与预算续跑 |
| [DeepSeek契约](docs/DEEPSEEK_PLAN.md) | LLM as Judge定义、输入、响应、校验与恢复 |
| [数据库说明](docs/DATABASE.md) | 六表字段、数据来源、HLTB与hard_ratio口径、迁移数量及连接 |
| [数据准备](docs/IMPORT_SNAPSHOT.md) | 前1000款只读获取与迁移 |
| [实验记录](docs/experiments.md) | 历史与本轮验证 |
| [后续分析规划](docs/data_plan.md) | 分类完成后待选择的分析专题、指标口径与实施前提 |
| [旧攻略采集记录](docs/experiments.md#旧攻略获取方式已弃用) | 已弃用的网页发现、DOM获取及历史评分说明 |

程序入口见[DataAgent.py](process/DataAgent.py)，SQL与本地库入口见[schema.sql](database/schema.sql)。数据、缓存和备份保持原位且Git忽略；不自动提交或推送。

分类当前按`confidence >= 0.6`逐标签筛选；这是模型自报信心的本地门槛，不是准确概率，不改变v6提示词或API缓存指纹。每次分类把有效的全部标签累计到[process/datacache.csv](process/datacache.csv)，包括低分、已有和本轮写入结果，历史runtime文件保留。历史CSV通过[import_classification_cache.py](process/import_classification_cache.py)离线预检和补写，默认不落盘，`--apply`才写本地SQLite和累计CSV；已有机器/人工结果及主线排序保护。命令和去重规则见[运行说明](docs/PROCESS.md#累计分类csv与历史结果导入)。

[process/failure_data.csv](process/failure_data.csv)另行展示累计缓存中低于各行置信度门槛的标签，保留原22列；普通分类和历史导入更新全量表时同步刷新，不增加API请求，不改变SQLite写入逻辑。默认0.6通过，混合标签只提取其中低分的标签。该表保留不同请求的历史低分，不是所有未入库成就或网络失败清单。

2026-10-15已完成真实单款、有限预算批量、旧响应恢复及0.6边界标签补录，另验证了请求总时限、失败隔离和重复导入。工程链路已实现，冻结1000款的分类仍未全部完成；当前没有人工金标集或语义准确率结论，机器`mainline`还需后续人工核验和剧情排序。每轮报告、跨轮CSV和SQLite的职责及带时间数据快照见[总体规划](docs/plan.md)与[实验记录](docs/experiments.md)。

HLTB三类时长已按冻结1000款AppID从远端hltb_games导入，并完成schema4迁移；旧guide_time_hours_min/max物理删列，playtime与guide_difficulty保留。一次性导入脚本已移除，现有数据、快照与备份保留。字段口径与导入数量见[DATABASE.md](docs/DATABASE.md#hltb三类时长)。

2026-10-15 21:49，当前guide_difficulty已换为[game_difficulty.hard_ratio](docs/DATABASE.md#hard_ratio难度指标)的0～1成就难度代理：以games_time全部1000个AppID查询，996款有值、4款NULL，Decimal四舍五入保留两位。导入时完整备份并核对仅目标列变化；一次性导入脚本已移除。

旧Gamer Guides时间与评分采集已弃用，五个源码文件归档至[process/old](process/old/README.md)，获取方式合并到[实验记录](docs/experiments.md#旧攻略获取方式已弃用)；runtime中的队列和证据保留原位。此前347款HLTB子集的攻略采集限制不适用于已完成的全1000款hard_ratio导入。
