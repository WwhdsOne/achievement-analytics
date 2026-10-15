# LYX 文档导航

更新：2026-10-15。返回 [LYX 工作空间](../README.md)。

已完成冻结前1000款、71,465项成就的本地数据准备，DeepSeek整款八类多标签分类、缓存恢复、逐标签筛选和CSV留档链路已运行。三类HLTB时长覆盖347款，hard_ratio覆盖996款；旧攻略采集已弃用。

分类仍在推进：22:33只读快照中，DeepSeek标签覆盖37,346项成就；覆盖与语义质量分别核验，不能据此认定整款或全量完成。后续先核对剩余分类、低分与失败项，再决定人工主线节点核验、剧情排序及分析范围。[data_plan.md](data_plan.md)保存后续分析基础，尚未执行其中专题。

| 文档 | 用途 |
|---|---|
| [PROCESS.md](PROCESS.md) | 日常命令、参数、预算、缓存与恢复规则 |
| [DATABASE.md](DATABASE.md) | 六表结构、来源归类、HLTB时长与hard_ratio口径、数据快照及迁移记录 |
| [DEEPSEEK_PLAN.md](DEEPSEEK_PLAN.md) | 八类定义、模型输入输出、证据与存储契约 |
| [plan.md](plan.md) | 分类工程进度、验收边界和待办 |
| [data_plan.md](data_plan.md) | 后续用户粘性分析规划与实施前提 |
| [IMPORT_SNAPSHOT.md](IMPORT_SNAPSHOT.md) | 冻结选样、基础数据只读导入及冲突保护 |
| [experiments.md](experiments.md) | 按日实现摘要、验收证据及弃用方案 |
| [API_PROBE.md](API_PROBE.md) | 历史API试跑资料入口 |

程序入口：[DataAgent.py](../process/DataAgent.py)。本地结构：[schema.sql](../database/schema.sql)。日常操作先同步main；远端只读，不自动提交或推送。
