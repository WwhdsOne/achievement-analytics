# 刘宇翔（LYX）工作空间

当前任务是用DeepSeek对成就做八类多标签分类，直接保存至本地SQLite。所有个人编辑限于本目录，共享远端数据库永远只读。详细说明集中在[docs](docs/README.md)，子目录README保留入口索引。

| 文档 | 内容 |
|---|---|
| [总体规划](docs/plan.md) | 分类目标、阶段任务与验收 |
| [运行说明](docs/PROCESS.md) | 命令、写库与预算续跑 |
| [DeepSeek契约](docs/DEEPSEEK_PLAN.md) | 输入、响应、校验与恢复 |
| [数据库说明](docs/DATABASE.md) | 六表字段、状态与连接 |
| [数据准备](docs/IMPORT_SNAPSHOT.md) | 前1000款只读获取与迁移 |
| [实验记录](docs/experiments.md) | 历史与本轮验证 |
| [历史API资料](docs/API_PROBE.md) | 归档说明入口 |

程序入口见[process/README.md](process/README.md)，SQL与本地库入口见[database/README.md](database/README.md)。数据、缓存和备份保持原位且Git忽略；不自动提交或推送。
