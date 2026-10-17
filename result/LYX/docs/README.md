# LYX文档导航

更新：2026-10-17。当前重点为只读冻结数据上的五个分析专题（任务2～6），任务1为公共指标准备；01～21图及相关结果已完成当前确定范围。网页部署由组长后续实施，数据交接包已准备，未上传或部署。

| 文档 | 用途 |
|---|---|
| [data_plan.md](data_plan.md) | 六项任务、指标、样本与解释边界的权威分析规划 |
| [分析交接与上传选择](../analysis/delivery/README.md) | 哪些CSV/JSON/图片交网页，什么时候需要两份原SQLite；打包/核验命令 |
| [本轮审查报告](../analysis/delivery/AUDIT.md) | 五专题来源、计算核查、结果索引、样本与限制 |
| [DATABASE_WWH.md](DATABASE_WWH.md) | 当前主分析源，八表、JSON路径、剧情数组顺序、198/183/140/181样本 |
| [DATABASE_LYX.md](DATABASE_LYX.md) | 原本地六表、当前覆盖、HLTB/hard_ratio、前1000迁移摘要和连接 |
| [PROCESS.md](PROCESS.md) | 合并后的数据获取沿革、当前DeepSeek五模块、prompt/响应/门槛/超时/存储与清理说明 |
| [plan.md](plan.md) | 当前交付重心与文档入口，不重复分类工程细节 |
| [experiments.md](experiments.md) | 分析实施与审查记录；分类历史保留必要摘要与带时间进度 |
| [T0Pre](../analysis/T0Pre/README.md) | 原有三图只读复现与highest基线 |
| [T1 INSTRUCT](../analysis/T1Core/INSTRUCT.md) | 任务1～4的命令、图表含义和读图实例 |
| [T1 DEPLOY](../analysis/T1Core/DEPLOY.md) | 网页交互与任务4固定背景高亮，区分已有能力/待实施页面 |
| [T1技术说明](../analysis/T1Core/README.md) | 数据表、程序参数、分组与保护规则 |
| [T2任务5](../analysis/T2Sum/README.md) | 口碑与推进、183/140款、16～18图与高亮查询 |
| [T2任务6](../analysis/T2Sum/BENCHMARK.md) | 同类参照、183目标/181有效、19～21图与1～5款查询 |

原DeepSeek契约、API试跑说明已并入PROCESS；原基础迁移说明并入DATABASE_LYX。旧单一数据库文档由两份来源说明取代。process历史runtime和旧网页逻辑已清理，当前两个累计CSV保留；两份SQLite、本地备份、全部分析数值和图片未改。数据包与数据库不进Git；不自动提交或推送。
