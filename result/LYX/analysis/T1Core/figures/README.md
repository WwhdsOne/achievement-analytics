# T1 图表

按“单款指标 → 类型汇总 → 类型内部差异 → 多标签对照 → 阶段案例 → 完整过程 → 时长关联”排序。每张图提供PNG与可缩放SVG；正式图面使用中性描述，不显示组员姓名或缩写。来源归属仍保留在运行说明和审计记录中。

图名明确区分“主类型分组”（02～04）和“完整多标签分组”（05～06）。每图底部四行小字依次给出一行样本来源、分组或选样规则、数据定义和解释/区间口径；正文上方不再放样本说明。分组、阈值、排序、数据、文件名与编号均保持原样。

| 序号 | 图与PNG预览 | SVG | 含义 |
|---|---|---|---|
| 01 | [game_stages](01_game_stages.png) | [SVG](01_game_stages.svg) | 五款示例的首中末覆盖、前后及全程推进比 |
| 02 | [type_coverage](02_type_coverage.png) | [SVG](02_type_coverage.svg) | 主类型分组：首、中、末主线节点覆盖 |
| 03 | [type_progress](03_type_progress.png) | [SVG](03_type_progress.svg) | 主类型分组：前段、后段与全程主线推进比 |
| 04 | [type_distribution](04_type_distribution.png) | [SVG](04_type_distribution.svg) | 主类型分组：全程推进比的游戏分布与中位数区间 |
| 05 | [tag_coverage](05_tag_coverage.png) | [SVG](05_tag_coverage.svg) | 完整多标签分组：首、中、末主线节点覆盖 |
| 06 | [tag_progress](06_tag_progress.png) | [SVG](06_tag_progress.svg) | 完整多标签分组：前段、后段与全程主线推进比 |
| 07 | [stage_cases](07_stage_cases.png) | [SVG](07_stage_cases.svg) | 全程相近而前后段不同的三组游戏案例 |
| 08 | [story_curves](08_story_curves.png) | [SVG](08_story_curves.svg) | 同主类型、全程相近案例的完整节点覆盖曲线 |
| 09 | [adjacent_progress](09_adjacent_progress.png) | [SVG](09_adjacent_progress.svg) | 对应六款游戏的逐相邻区间推进比与最大相对差距 |
| 10 | [time_comparison](10_time_comparison.png) | [SVG](10_time_comparison.svg) | 同69款的HLTB主线参考耗时与RAWG平均游玩时长对照 |
| 11 | [length_progress](11_length_progress.png) | [SVG](11_length_progress.svg) | 主线参考耗时与三个阶段推进比 |
| 12 | [playtime_progress](12_playtime_progress.png) | [SVG](12_playtime_progress.svg) | 平均游玩时长与三个阶段推进比 |
| 13 | [time_ratio](13_time_ratio.png) | [SVG](13_time_ratio.svg) | 两类时长之比与全程推进及探索性案例 |
| 14 | [extra_time_ratio](14_extra_time_ratio.png) | [SVG](14_extra_time_ratio.svg) | 平均游玩时长/主线＋支线参考耗时，与原全程推进比 |
| 15 | [completionist_time_ratio](15_completionist_time_ratio.png) | [SVG](15_completionist_time_ratio.svg) | 平均游玩时长/全收集参考耗时，与原全程推进比 |

`01`属于data_plan任务1的指标展示；`02`～`07`属于任务2的类型阶段分析。类型主分析用183款完整三节点，全部198款另存有效值补充。图上的推进比是聚合覆盖之比，不是日留存；类型差异不等于因果。

`08`～`09`属于任务3：全198款1741节点形成1543相邻区间；从133款至少6节点游戏的63对合格候选中选取3组不重复案例，不改变前两个任务。08横轴只是节点位置、纵轴按各自首覆盖归一，图例同时标原始首覆盖；09每柱对应一段真实相邻节点。全程相近不等于过程相同，章节跨度和模型节点含义需要保留边界。

`10`～`13`属于任务4，统一采用69款完整三节点且两类时长为正的共同样本。按负责人研究口径，RAWG为平均游玩时长、HLTB为主线参考耗时，单位小时；R=RAWG/HLTB，不互相填缺失，不做类型对照。10的斜线是时长相等参考，13的竖线R=1、横点线为样本全程比中位数，都不是通过门槛。散点相关及区间是游戏级统计，不作因果解释。

从LYX目录运行原有`compare`示例生成01，运行`types`生成02～07；见[运行说明](../README.md)。默认图统一在本目录，CSV、来源JSON、统计报告仍位于原`output/`。同名选择重复覆盖原图，其他游戏选择以`01_game_stages_<选择摘要>_<view>`命名，选择顺序和完整AppID保存在来源JSON中。

自定义`--output`的隔离运行把图放在指定目录的`figures/`子目录，避免覆盖本图集。索引按PNG/SVG成对维护，不移动数据库、指标底表或T0Pre图表。

从LYX运行`analysis/T1Core/run.py trajectory`生成08～09；完整uv命令、候选规则和报告见[任务3说明](../README.md#专题3完整主线过程与相邻区间)。01～07图面及数值保持不变。

从LYX运行`analysis/T1Core/run.py duration`生成10～13；完整uv命令和固定69款说明见[任务4说明](../README.md#专题4主线参考耗时平均游玩时长与推进)。01～09图面及数值保持不变。

`14`～`15`沿用13号图的固定69款、纵轴和统计/案例规则，仅把HLTB分母分别改为extra_hours、completionist_hours，两列均69款正值。R>=1分别5款、2款；15有一个空象限，明确标记而不补案例。全收集是Completionist完整游玩参考，不等于Steam全成就；纵轴仍是主线推进。重跑补充图使用`analysis/T1Core/analyze_duration_references.py`，详见[补充说明](../README.md)与[补充报告](../output/duration_references/report.md)。01～13保持不变。

专题3另支持自选分组，不改变本页固定01～15：[1～5款自选图集](trajectory_comparisons/README.md)。每组1～5款、默认2款，末组余数单独成组；仅指定组数时尽量均分。每个分组各有08曲线和09相邻区间的PNG/SVG，放在选择摘要子目录；数据JSON/CSV、来源与报告位于对应output/trajectory_comparisons目录。
