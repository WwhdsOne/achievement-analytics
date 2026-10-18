# 分析审查与数据交接

2026-10-17，刘宇翔。审查对象是五个分析专题（任务2～6），另将任务1主线指标准备作为公共依赖一起核查。代码和文档随Git交接；原始数据库、CSV、JSON与运行缓存不进Git。本目录不自动上传、部署或调用模型。

## 可以交给组长什么

已生成本地目录 `package/`，约40.8 MB、123个文件，可作为独立数据附件交接。它不是网页后端，也没有执行远程上传。

| 入口 | 用途 |
|---|---|
| `package/analysis_summary.csv` | 六项任务的输入、明细、汇总、样本数、图号、解释边界总表 |
| `package/source_tables.csv` | 9份源表摘录的字段、行数、范围、路径、SHA256 |
| `package/result_tables.csv` | 109份已有产物的路径、用途、行数、体量、SHA256，其中49张结果CSV、42个PNG/SVG、7份来源manifest、11份上下文文件 |
| `package/delivery_manifest.json` | 整包内容哈希、源数据库版本与指纹、本轮审查计数 |
| `package/game_catalog.csv` | 198款可选游戏，含appid/name_en/name_zh；中文缺失保持空值 |
| `package/T1Core/`、`package/T2Sum/` | 保持原相对路径的默认结果、报告和01～21图，不包含重复的自选示例 |
| `package/sources/` | 仅198款相关源记录；LYX表为其中161款AppID交集，未匹配37款不补行 |

**网页直接展示和前端筛选：优先上传整个package作为数据附件。** 只有静态图展示时，上传两个figures目录及对应报告即可。完整交互时保留明细、汇总、缺失/资格台账和JSON，不能只交图或中位数。数据可放服务器私有目录，由只读接口返回需要的字段；不建议把源表摘录和全量同类关系直接暴露为公开下载。

**按当前Python代码从头复算：再私下传递两份未改动的原库**：`NewDB/wwh5.sqlite3`（约105.8 MB）与`database/achievements.sqlite`（约21.7 MB），保留LYX相对路径、analysis代码、T0Pre参数及固定基线产物。当前适配器验证WWH完整八表和数据库文件指纹；不能把摘录CSV或删减后的SQLite直接替换原库。纯展示不需要这两库，更不需要process、API key、.env、旧运行备份或完整model_calls请求/响应。

## 五个专题的交接重点

| 专题 | 明细/来源表 | 总结表 | 交互与解释 |
|---|---|---|---|
| 类型与阶段，02～07 | game_metrics、cohort、game_membership | group_summary、sensitivity_summary、case_pairs | 总体图固定183完整三节点；198为另列补充；主类型与多标签不能混算或把多标签人数相加 |
| 完整过程，08～09 | checkpoints、adjacent_nodes | game_profiles、case_candidates | 可以按名称/AppID选游戏；按组切分；节点相对位置不是实际时间 |
| 时长，10～15 | duration_eligibility、duration_cohort、reference_cohort | time_correlations、reference_correlations、duration_groups等 | 背景固定65款，建议高亮所选；不合格选择展示缺失原因，不能补零或改变整体统计 |
| 口碑，16～18 | reputation_eligibility、reputation_cohort、rating_common | reputation_correlations、reputation_quadrants、score_summary及探索表 | 16/17用183款，18固定共同140款；1～5款选择只高亮；综合秩是探索指标，不是质量排名 |
| 同类参照，19～21 | peer_conditions、peer_membership、semantic_caveats | peer_benchmark、peer_coverage、matched_sensitivity等 | 183目标中181满足主口径；不足5个参照显示不足，不计算假零差；全背景保持固定 |

所有专题共用 `T1Core/output/{cohort,game_metrics,checkpoints}.csv` 及manifest；01为1～5款首中末覆盖与阶段比对比。CSV比率内部0～1，`*_pp`为百分点；空字符串表示缺失。读取JSON优先保留null/布尔值，CSV显式转换数字与布尔。源payload列是WWH原库已有JSON，不是新增SQLite设计。

网页布局与查询接口详见[统一部署交接](../../docs/DEPLOY.md)、[任务5](../T2Sum/README.md)、[任务6](../T2Sum/BENCHMARK.md)。已有query函数有的仍会读本地SQLite并验证快照；若使用“仅package”的部署方式，组长需实现CSV/JSON只读适配，不能直接假定全部query函数已经脱离数据库。`benchmark/data.json`含完整关系约15 MB，首次页面只需摘要与背景点，按选中游戏索取其参照，避免整包一次发往浏览器。

## 核查与重新打包

从LYX目录执行，先依项目约定同步main：

```powershell
uv --cache-dir analysis/delivery/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/delivery/audit_delivery.py verify
```

`snapshot`保存清理前保护文件与体量，已有快照时拒绝覆盖；`build`从既有结果核验并打包，已有package时拒绝覆盖以防混合版本；`verify`检查包内哈希和本轮239个保护文件。组长只拿到结果包和此脚本时，可保持delivery/package布局运行`audit_delivery.py verify-package`，仅用Python标准库检查缺失、多余文件及内容哈希，不需要SQLite、旧缓存、密钥或科学计算依赖。未来刷新数据时，人工移动旧package和本轮before快照，再依次snapshot/build。输出只在delivery内，数据库始终mode=ro；不重新分类、不重画图、不修改既有分析结果。此工具是交接核验程序，不是新增pytest测试。

本轮核验报告见[AUDIT.md](AUDIT.md)，详细机器记录留本地 `runtime/audit.json`。package内原manifest保留历史绝对路径和代码哈希，仅作来源记录；跨机器校验包内容使用delivery_manifest的相对路径，不能拿历史绝对路径直接当服务器地址。
