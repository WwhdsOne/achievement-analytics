# LYX文档导航

更新：2026-10-19。任务1公共指标、任务2～6五个分析专题及01～21图已完成当前确定范围，现已增加[WEB交互简报](../WEB/index.html)，支持1～5款游戏联动。网页使用冻结结果在本地展示；数据交接包已准备，尚未公网部署，也未新增分析HTTP接口。

| 文档 | 用途 |
|---|---|
| [网页成品](../WEB/index.html) · [WEB使用说明](../WEB/README.md) | 六项分析交互入口、打开/预览/构建/核验、单文件与完整目录的交付方式 |
| [WEB验收记录](../WEB/ACCEPTANCE.md) | 28项浏览器检查、桌面/手机布局、来源指纹与验证边界 |
| [ANALYSIS.md](ANALYSIS.md) | 课程项目报告初稿：研究问题、指标、逐专题发现及可追溯证据 |
| [INSTRUCT.md](INSTRUCT.md) | 六任务的网页使用、Python出图命令、逐图读法、样本、产物与解释边界 |
| [DEPLOY.md](DEPLOY.md) | 已实现静态网页的布局、联动、数据契约，以及组长后续托管/整合与接口边界 |
| [data_plan.md](data_plan.md) | 六项任务、指标、样本与解释边界的权威分析规划 |
| [分析交接与上传选择](../analysis/delivery/README.md) | 哪些CSV/JSON/图片交网页，什么时候需要两份原SQLite；打包/核验命令 |
| [本轮审查报告](../analysis/delivery/AUDIT.md) | 五专题来源、计算核查、结果索引、样本与限制 |
| [DATABASE_WWH.md](DATABASE_WWH.md) | 当前主分析源，八表、JSON路径、剧情数组顺序、198/183/142/181样本 |
| [DATABASE_LYX.md](DATABASE_LYX.md) | 原本地六表、当前覆盖、HLTB/hard_ratio、前1000迁移摘要和连接 |
| [PROCESS.md](PROCESS.md) | 合并后的数据获取沿革、当前DeepSeek五模块、prompt/响应/门槛/超时/存储与清理说明 |
| [plan.md](plan.md) | 当前交付重心与文档入口，不重复分类工程细节 |
| [experiments.md](experiments.md) | 分析实施与审查记录；分类历史保留必要摘要与带时间进度 |
| [T0Pre](../analysis/T0Pre/README.md) | 原有三图只读复现与highest基线 |
| [T1技术说明](../analysis/T1Core/README.md) | 数据表、程序参数、分组与保护规则 |
| [T2任务5](../analysis/T2Sum/README.md) | 口碑与推进、183/142款、16～18图与高亮查询 |
| [T2任务6](../analysis/T2Sum/BENCHMARK.md) | 同类参照、183目标/181有效、19～21图与1～5款查询 |

原DeepSeek契约、API试跑说明已并入PROCESS；原基础迁移说明并入DATABASE_LYX。旧单一数据库文档由两份来源说明取代。process历史runtime和旧网页逻辑已清理，当前两个累计CSV保留；两份SQLite、本地备份、全部分析数值和图片未改。数据包与数据库不进Git；不自动提交或推送。

当前`WEB/index.html`内嵌26张CSV和7份manifest整理后的展示数据，不在浏览时连接两库或调用模型。完整报告、原图及来源文件入口需保留LYX目录结构；T1/T2正式output已纳入Git，SQLite、runtime和delivery/package仍按原规则单独保留或交接。来源元数据存在6条历史父清单指纹漂移，已消费结果表自身校验通过，详细限制见WEB核验记录；不因网页已完成就将完整历史审计标为全部通过。

2026-10-20：任务4采用用户确认的10个时长值，由65扩为69款，10～15图、网页及报告均已同步。Word课程报告见[个人任务汇报](刘宇翔_主线推进与玩家投入分析报告.docx)。来源输入位于analysis/T1Core/inputs/manual_duration_supplements.csv；两份原SQLite不变。
