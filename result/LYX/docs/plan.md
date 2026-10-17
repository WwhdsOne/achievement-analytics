# LYX当前交付规划

更新：2026-10-17。研究内容以[data_plan.md](data_plan.md)为准，模块重心已经从分类工程转向游戏级主线推进分析。任务1公共指标准备及五个专题（任务2～6）当前确定范围均已实现；回归模型、因果推断和玩家级留存不在本轮交付。

## 当前交付

| 阶段 | 内容 | 入口 |
|---|---|---|
| 基线 | 只读WWH库，保留既有分类/阶段/数组顺序/玩法；复现原三图 | [T0Pre](../analysis/T0Pre/README.md) |
| 任务1～4 | 198款指标和任选游戏对比、183款类型、198款过程、65款时长 | [INSTRUCT](INSTRUCT.md) |
| 任务5～6 | 183/140款口碑、183目标/181有效同类参照 | [T2Sum](../analysis/T2Sum/README.md) |
| 交接 | 来源摘录、49张结果CSV、01～21图、文件哈希与上传选择 | [delivery](../analysis/delivery/README.md) |

## 下一步

1. 按[审查报告](../analysis/delivery/AUDIT.md)同步样本、公式、语义限制与计算来源，确认组长需要静态图、结果交互或完整复算哪种交付。
2. 网页以冻结结果只读展示，允许名称/AppID选择和高亮，不因选择改变总体背景。布局建议见[DEPLOY](DEPLOY.md)，服务器接入由组长实施。
3. 继续人工审视关键案例的节点原文与结局代理。发现问题先标记并确认，不静默改WWH或LYX库，不将模型节点当成已证明必经剧情。

保留的DeepSeek获取agent说明统一见[PROCESS](PROCESS.md)，旧库和原始准备见[DATABASE_LYX](DATABASE_LYX.md)，分析主源见[DATABASE_WWH](DATABASE_WWH.md)。旧分类补齐和LYX人工排序不再是当前分析的前置条件。旧工程规划已合并，不在此重复过期prompt版本或恢复命令。
