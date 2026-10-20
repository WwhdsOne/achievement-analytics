# LYX当前交付规划

**2026-10-20任务5评分更新：** [评分补充输入](../analysis/T2Sum/inputs/manual_rating_supplements.csv)记录33号远征队92/4.42、God of War94/4.54及RAWG评分人数5310。共同评分样本由原140款增加至142款，图16～18及统计重算；Steam183款不变。两库只读，补充确认日期与旧快照采集日期分开记录。

**2026-10-20任务4更新：原65款加人工补充4款，共69款。** 用户手动查询确认的10个值保存在[人工补充输入](../analysis/T1Core/inputs/manual_duration_supplements.csv)，不写回两份SQLite。三款补HLTB三类耗时，God of War补RAWG 15小时；五款预选均可在任务4显示。任务5三评分142款、任务6长度条件原68款不随本次补充改变。


更新：2026-10-19。研究内容以[data_plan.md](data_plan.md)为准，模块重心已经从分类工程转向游戏级主线推进分析。任务1公共指标准备及五个专题（任务2～6）当前确定范围均已实现，六项任务已整合为本地静态交互网页；回归模型、因果推断和玩家级留存不在本轮交付。

## 当前交付

| 阶段 | 内容 | 入口 |
|---|---|---|
| 基线 | 只读WWH库，保留既有分类/阶段/数组顺序/玩法；复现原三图 | [T0Pre](../analysis/T0Pre/README.md) |
| 任务1～4 | 198款指标和任选游戏对比、183款类型、198款过程、69款时长 | [INSTRUCT](INSTRUCT.md) |
| 任务5～6 | 183/142款口碑、183目标/181有效同类参照 | [T2Sum](../analysis/T2Sum/README.md) |
| 交接 | 来源摘录、49张结果CSV、01～21图、文件哈希与上传选择 | [delivery](../analysis/delivery/README.md) |
| 网页 | 六项分析、1～5款游戏联动、固定背景/缺失提示、原图与来源入口；尚未公网部署 | [WEB成品](../WEB/index.html) · [使用与构建](../WEB/README.md) · [核验](../WEB/ACCEPTANCE.md) |

## 下一步

1. 结合[分析报告](ANALYSIS.md)和[交互网页](../WEB/index.html)审核最终叙事；消费结果表已核验，但仍需追溯并同步历史父级manifest来源记录，不静默改写或把警告当作全部通过。
2. 向组长交接现成`WEB/index.html`及所需文档/原图/结果文件，按[DEPLOY](DEPLOY.md)决定独立静态托管或接入既有网站。网页本地交互已实现，服务器发布尚未执行；当前无需新增后端计算接口。
3. 保留WWH已完成重点案例人工审核的确认及节点语义说明；新增争议先标记并确认，不扩大为全198/183款逐项审核，也不静默改两份数据库或研究口径。

保留的DeepSeek获取agent说明统一见[PROCESS](PROCESS.md)，旧库和原始准备见[DATABASE_LYX](DATABASE_LYX.md)，分析主源见[DATABASE_WWH](DATABASE_WWH.md)。旧分类补齐和LYX人工排序不再是当前分析的前置条件。旧工程规划已合并，不在此重复过期prompt版本或恢复命令。
