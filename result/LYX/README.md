# 刘宇翔（LYX）工作空间

当前已跑通DeepSeek成就分类工程链路：定位游戏 → 复用或生成背景摘要 → 一次性判断整款成就的八类多标签 → 校验、累计留档并按门槛写入本地SQLite。这里的 **LLM as Judge** 指模型按固定类别规则作语义判别，不是另设模型复核另一模型的答案。所有个人编辑限于本目录，共享远端数据库永远只读。详细说明集中在[docs](docs/README.md)，子目录README保留入口索引。

| 文档 | 内容 |
|---|---|
| [总体规划](docs/plan.md) | 已实现链路、验证边界与后续任务 |
| [运行说明](docs/PROCESS.md) | 命令、写库与预算续跑 |
| [DeepSeek契约](docs/DEEPSEEK_PLAN.md) | LLM as Judge定义、输入、响应、校验与恢复 |
| [数据库说明](docs/DATABASE.md) | 六表字段、状态与连接 |
| [数据准备](docs/IMPORT_SNAPSHOT.md) | 前1000款只读获取与迁移 |
| [实验记录](docs/experiments.md) | 历史与本轮验证 |
| [HLTB时长同步](docs/HLTB_TIME.md) | 按AppID只读复制三类时长、本地schema4迁移和完整验收 |
| [攻略难度补全](docs/GUIDE_TIME.md) | 仅更新guide_difficulty、来源重放及旧时间策略记录 |
| [浏览器批量补全](docs/GUIDE_AGENT.md) | 1000款AppID队列、真实网址发现、DOM核验和难度写入 |

程序入口见[DataAgent.py](process/DataAgent.py)，SQL与本地库入口见[schema.sql](database/schema.sql)。数据、缓存和备份保持原位且Git忽略；不自动提交或推送。

分类当前按`confidence >= 0.6`逐标签筛选；这是模型自报信心的本地门槛，不是准确概率，不改变v6提示词或API缓存指纹。每次分类把有效的全部标签累计到[process/datacache.csv](process/datacache.csv)，包括低分、已有和本轮写入结果，历史runtime文件保留。历史CSV通过[import_classification_cache.py](process/import_classification_cache.py)离线预检和补写，默认不落盘，`--apply`才写本地SQLite和累计CSV；已有机器/人工结果及主线排序保护。命令和去重规则见[运行说明](docs/PROCESS.md#累计分类csv与历史结果导入)。

2026-10-15已完成真实单款、有限预算批量、旧响应恢复及0.6边界标签补录，另验证了请求总时限、失败隔离和重复导入。工程链路已实现，冻结1000款的分类仍未全部完成；当前没有人工金标集或语义准确率结论，机器`mainline`还需后续人工核验和剧情排序。每轮报告、跨轮CSV和SQLite的职责及带时间数据快照见[总体规划](docs/plan.md)与[实验记录](docs/experiments.md)。

时长入口为[import_hltb_times.py](process/import_hltb_times.py)：按冻结1000款AppID只读复制远端hltb_games的main_hours、extra_hours、completionist_hours，完整备份后迁移到schema4；旧guide_time_hours_min/max物理删列，playtime与guide_difficulty保留。操作、快照与验收见[HLTB_TIME.md](docs/HLTB_TIME.md)。

攻略补全现有两个入口：[guide_time.py](process/guide_time.py)负责难度固定标签解析、HTTP与来源重放；[guide_agent.py](process/guide_agent.py)接收Codex真实搜索和浏览器DOM，维护1000款AppID的可恢复队列，再核验、备份和仅写guide_difficulty。用户已确认站方许可，普通HTTP仍遇403；浏览器已枚举Steam目录6页134张卡片、找到55款精确名称候选，候选仍须逐页核验。当前难度覆盖执行 `guide_agent.py summary` 查看，操作及下次Codex交接提示见[GUIDE_AGENT.md](docs/GUIDE_AGENT.md)。
