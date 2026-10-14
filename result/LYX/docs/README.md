# LYX文档索引

说明和实验记录集中在本目录。当前目标为DeepSeek成就分类，详细历史保存在实验记录和归档。返回[LYX工作空间](../README.md)。

| 文档 | 内容 |
|---|---|
| [plan.md](plan.md) | 当前分类目标、分阶段实现与验收 |
| [PROCESS.md](PROCESS.md) | 程序职责、命令和运行恢复 |
| [DEEPSEEK_PLAN.md](DEEPSEEK_PLAN.md) | 摘要缓存、整款分类和直接写库 |
| [DATABASE.md](DATABASE.md) | 六表、实际数据、状态和连接 |
| [IMPORT_SNAPSHOT.md](IMPORT_SNAPSHOT.md) | 独立的远端只读数据准备 |
| [experiments.md](experiments.md) | 历史及当前实现验证 |
| [API_PROBE.md](API_PROBE.md) | 历史API资料入口，旧命令不属于当前流程 |

日常程序入口：[DataAgent.py](../process/DataAgent.py)。SQL和数据库入口：[schema.sql](../database/schema.sql)。

游戏选择及完整参数见[PROCESS.md](PROCESS.md#游戏选择参数)：--game-name、--appids、--appids-file、--all-games互斥；不写选择参数默认冻结1000款，不写子命令默认离线plan，classify默认新请求预算2。

当前契约：本地schema版本3（标签表含display_name），分类prompt v5、简介v1；evidence每段150字符，逐标签confidence严格大于0.6才入库。重生和HELLDIVERS™ 2的分类链路已实际执行，数据统计为带时间快照，以当前数据库/plan为准；历史实验保留当时参数，不能将旧命令复制为当前运行方式。
