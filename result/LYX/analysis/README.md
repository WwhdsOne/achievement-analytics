# LYX分析目录

更新：2026-10-17。当前已完成任务1公共指标和任务2～6五个分析专题，覆盖固定图01～21；真实运行核验已通过。分析以游戏为单位，正式使用“节点覆盖、阶段推进、游戏级关联与同类参照”，不将聚合数据直接解释为玩家留存或因果。

## 从这里开始

| 需要做什么 | 阅读入口 |
|---|---|
| 查命令、参数、各任务含义和逐图读法 | [统一使用指南：docs/INSTRUCT.md](../docs/INSTRUCT.md) |
| 给组长看页面布局、游戏选择、高亮、评分/参照切换及数据契约 | [统一网页交接：docs/DEPLOY.md](../docs/DEPLOY.md) |
| 看研究任务、样本和解释边界 | [data_plan.md](../docs/data_plan.md) |
| 查应交哪些CSV/JSON/图或SQLite，核验数据包 | [delivery/README.md](delivery/README.md) |
| 查来源表、结果表、计算核验与语义限制 | [delivery/AUDIT.md](delivery/AUDIT.md) |

**INSTRUCT.md和DEPLOY.md已统一迁至LYX/docs，并补齐T2Sum内容，T1Core内不再保留副本。** 本README作为分析目录导航；完整读图和部署说明以两份统一指南为准。

## 目录与当前职责

```text
analysis/
  T0Pre/      复制适配的三图基线、固定样本与来源核验
  T1Core/     任务1～4代码、output数值表、figures图01～15
  T2Sum/      任务5～6代码、output数值表、figures图16～21
  delivery/   来源/结果索引、审查与打包程序、本地package数据附件
```

| 目录 | 技术说明 | 当前状态 |
|---|---|---|
| T0Pre | [README](T0Pre/README.md) | highest基线复现完成，保留来源归属及start对照说明 |
| T1Core | [README](T1Core/README.md) | 公共指标、游戏对比、类型、过程和时长均完成 |
| T2Sum | [README](T2Sum/README.md)、[BENCHMARK](T2Sum/BENCHMARK.md) | 口碑与同类参照均完成；未训练回归模型 |
| delivery | [README](delivery/README.md) | 本地数据附件与核验入口已就绪，未执行远程上传或网页部署 |

各阶段的runtime仅保存本地运行、图形缓存和验收记录；output中的CSV/数据JSON/manifest以及数据库按忽略规则单独交接。删除process旧运行历史不影响当前分析输入与结果。

## 六项任务和图表范围

| 任务 | 样本与主要计算 | 图号 | 当前结果 |
|---|---|---|---|
| 1. 主线指标准备与游戏对比 | 固定198款，183款完整三节点，15款中间留空；首/中/末覆盖及前/后/全程比 | 01 | [底表报告](T1Core/output/report.md) |
| 2. 类型与阶段 | 主183款、补充198款；主类型与完整多标签分别汇总 | 02～07 | [类型报告](T1Core/output/type_analysis/report.md) |
| 3. 完整主线过程 | 198款、1741个序列节点、1543段相邻区间；自动案例及自选分组 | 08～09 | [过程报告](T1Core/output/trajectory_analysis/report.md) |
| 4. 时长与推进 | 同65款；RAWG平均游玩时长、HLTB三类参考耗时及比值 | 10～15 | [主分析](T1Core/output/duration_analysis/report.md)、[补充参照](T1Core/output/duration_references/report.md) |
| 5. 口碑与推进 | Steam183款、三评分共同140款；四象限、阶段相关和多标签探索 | 16～18 | [口碑报告](T2Sum/output/reputation/report.md) |
| 6. 同类参照 | 183款目标，主条件181款参照充足；五条件915行及21294条有向参照 | 19～21 | [同类参照报告](T2Sum/output/benchmark/report.md) |

固定图索引：[T1图集01～15](T1Core/figures/README.md)、[T2图集16～21](T2Sum/figures/README.md)。T0Pre的三张基线图在其自身figures中，不占上述编号；过程自选例图另见[分组图集](T1Core/figures/trajectory_comparisons/README.md)。

## 运行入口与刷新顺序

先按项目约定在仓库根目录同步main，再进入LYX；下列Python路径均从LYX解析：

```powershell
cd D:\PycharmProjects\achievement-analytics
git pull origin main
cd result\LYX
```

所有分析使用已有uv环境，不需DeepSeek密钥、不连接共享云库，也不写SQLite。查看已生成图和报告无需重跑。需要计算时，按以下形式使用项目环境：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py compare --games 367520 "艾尔登法环"
```

| 目的 | 上述python之后的脚本/参数 | 运行条件 |
|---|---|---|
| 基线复现 | analysis/T0Pre/run.py analyze --baseline highest | 需要复现/刷新时运行，默认产物仍在T0Pre |
| 公共指标 | analysis/T1Core/run.py prepare | 固定198款，不出图 |
| 游戏阶段对比 | analysis/T1Core/run.py compare --games 367520 "艾尔登法环" | 1～5款，支持互斥的--appids/--game-names |
| 类型总体 | analysis/T1Core/run.py types | 固定样本，不接受游戏选择 |
| 自动过程案例 | analysis/T1Core/run.py trajectory | 固定全量过程明细及自动案例 |
| 自选过程分组 | analysis/T1Core/run.py trajectory --games 367520 220240 1245620 --games-per-group 2 | 默认每组2款，余数保留；只指定--groups时尽量均分 |
| 时长主分析 | analysis/T1Core/run.py duration | 固定65款，生成10～13 |
| 时长补图 | analysis/T1Core/analyze_duration_references.py | 同65款，生成14～15 |
| 口碑总体/高亮 | analysis/T2Sum/run.py reputation | 可加--games/--appids/--game-names选1～5款 |
| 同类参照总体/自选 | analysis/T2Sum/run.py benchmark | 需默认reputation结果，可选1～5款 |

T2Sum建议使用自身缓存路径 `--cache-dir analysis/T2Sum/runtime/uv-cache`；T0Pre、delivery同理。完整可复制命令和参数见[INSTRUCT](../docs/INSTRUCT.md#3-运行前提与命令总览)。

刷新依赖顺序为：T0Pre（必要时）→T1 prepare→类型/过程/时长与补图→T2 reputation→benchmark。重新生成默认reputation后应重新生成默认benchmark，避免上游manifest指纹不同。T1 --output仅隔离输出，不自动改下游默认输入；T2没有--output，自选输出按摘要独立保存。不能通过跳过校验混合旧表和新来源。

## 游戏选择与网页能力

| 分析 | 已实现的选择方式 | 总体背景如何处理 |
|---|---|---|
| 任务1 | CLI输入1～5款AppID/已有中英文名 | 展示所选指标 |
| 任务2 | CLI固定总体，无单独选择参数 | 网页可定位成员，类型统计不随选择改变 |
| 任务3 | CLI及query_trajectory支持自选分组 | 保留原节点顺序，每组1～5款；不套自动案例条件 |
| 任务4 | CLI固定65款，无高亮参数 | 网页高亮和三种参考切换是待实现交互 |
| 任务5 | CLI静态高亮、query_reputation只读查询 | 固定183/140款，保留缺评分/缺三节点状态 |
| 任务6 | CLI自选、query_benchmark只读查询 | 主背景181款不随选择变；参照不足不补零 |

名称按已有appid/name_en/name_zh匹配，歧义和重复报错，不补造中文译名。query_benchmark当前没有config参数；网页若切五种条件，需要组长按已保存的条件结果/成员表适配，不能把主条件数据只换标题。现有Python查询部分仍依赖本地SQLite，尚无这些分析专用的HTTP接口或已部署交互页面。详细布局与能力边界见[DEPLOY](../docs/DEPLOY.md)。

## 数据输入、产物与交接

主分析只读 `NewDB/wwh5.sqlite3` 的既有分类、剧情阶段、checkpoints数组顺序、玩法与评分；`database/achievements.sqlite`补充HLTB时长及副本核对。不合并分类、不改两库，不再以旧LYX成就分类补齐或mainline_index人工排序作为运行前置。[WWH库说明](../docs/DATABASE_WWH.md)、[LYX库说明](../docs/DATABASE_LYX.md)。

公共底表为T1Core/output中的cohort.csv、game_metrics.csv、checkpoints.csv；各专题明细、汇总、缺失台账和manifest继续保存在对应output子目录。比例通常0～1，*_pp为百分点，空值不补0；网页与报告使用display_name，内部身份只用于连接。

现成交接目录 `delivery/package/` 约40.8 MB、123个文件，含49张结果CSV、42个PNG/SVG、9份源表摘录及198款game_catalog.csv。source_tables.csv、result_tables.csv、analysis_summary.csv分别提供来源、结果与任务总表，delivery_manifest.json登记相对路径和内容哈希。

只做网页展示优先单独传结果包；按当前Python代码完整复算还需两份原SQLite。局部CSV摘录不能直接替代原库，Git拉代码也不会获得被忽略的数据。上传选择、体量和包核验命令见[delivery说明](delivery/README.md)；本目录不执行上传、发布或面板部署。

## 最近运行核验

2026-10-17已实际执行10条命令，覆盖基线、公共准备、五专题、时长补图和自选分组，全部成功；重新生成的49张CSV与现有交付逐字一致，30张PNG及配套SVG完整，三个只读查询均覆盖1～5款输入。239个保护文件指纹未变，包含两库和既有数值/图；日志未见警告或Traceback。

[本机运行核验报告](delivery/runtime/run_check_20261017T043521Z/REPORT.md)及其acceptance.json保存命令、耗时、产物和保护结果；这些运行记录属于本地忽略文件，Git克隆后不会自动携带。本次README更新仅同步导航与状态，没有重新执行统计、修改程序或写数据库。
