# 标签相似、口碑不同：项目数据中的反例

查询日期：2026-10-22。只读查询共享 PostgreSQL，没有修改库、重新抓取或消耗 RAWG 配额。

## 结论

能找到，而且存在前十标签集合完全相同、好评率相差约 30 个百分点的游戏。
这些案例支持“游戏类型标签不足以充分区分口碑”，不能单独证明“口碑无法预测”，也不能说明差评由什么因素造成。

## 统一口径

- 好评率 = `steamspy_games.positive / (positive + negative)`，不是 RAWG 评分，也不是 Steam 最近评价。
- 每款至少 1,000 条评价；仅使用正、负评价数均非负的记录。
- 标签取 `game_tags` 中 `source='steamspy' AND kind='theme' AND votes>0` 的前十名，按票数降序，同票按标签字母顺序；至少有十个有效标签。
- “10/10 重合”表示前十标签的集合相同，不代表顺序、票数、全部标签相同；“9/10”表示各自前十标签中有九个共同标签。
- Jaccard = 交集 / 并集：10/10 对应 1，9/10 对应 9/11≈0.818。
- 数据版本：2026-10-22 查询时的库内记录，未登记独立 dataset_versions 版本；下列评价记录抓取于 2026-09-22 至 2026-09-25（UTC），不是查询当天的实时口碑。标签表没有逐行抓取时间，无法保证标签与评价来自同一时刻。报告保留本次汇总结果，脚本重跑将读取届时库内数据。

## 可用于展示的案例

表内两款游戏的好评率、评价数及抓取日期均按名称出现顺序列出。差距用未四舍五入的好评率计算，单位为百分点。

| 游戏对 | 前十标签重合 | 好评率 | 评价数 | 好评率差距 | 评价抓取日（UTC） |
|---|---:|---:|---:|---:|---|
| Transport Fever 2 / Cities in Motion 2 | 10/10 | 90.35% / 57.67% | 27,627 / 2,483 | 32.67 | 09-25 / 09-22 |
| 底特律：化身为人 / The Uncertain: Light At The End | 10/10 | 95.77% / 64.92% | 169,199 / 1,123 | 30.86 | 09-25 / 09-24 |
| Blood Bowl 2: Legendary Edition (Classic) / Blood Bowl 3 | 10/10 | 78.71% / 48.76% | 8,890 / 4,861 | 29.95 | 09-22 / 09-25 |
| Cities: Skylines / Cities: Skylines II | 9/10 | 92.96% / 52.63% | 275,770 / 73,524 | 40.33 | 09-22 / 09-24 |
| Cities: Skylines / Cities XXL | 9/10 | 92.96% / 39.82% | 275,770 / 2,323 | 53.14 | 09-22 / 09-23 |

### 案例一：标签集合完全相同

[Transport Fever 2](https://store.steampowered.com/app/1066780/) 与 [Cities in Motion 2](https://store.steampowered.com/app/225420/) 的前十标签集合都是：Simulation、Strategy、Transportation、Management、City Builder、Sandbox、Economy、Building、Singleplayer、Trains。

也就是模拟、策略、交通运输、管理、城市营造、沙盒、经济、建造、单人、火车。同一套标签之下，好评率分别为 90.35% 与 57.67%，相差 32.67 个百分点。

如果模型输入仅是这十个标签是否出现，两款游戏的输入向量完全相同，模型就无法仅凭这些输入为两款游戏给出不同的预测；加入标签票数、其他标签或其他属性后，这一限制不一定成立。

### 案例二：叙事题材也存在同样现象

[底特律：化身为人](https://store.steampowered.com/app/1222140/) 与 [The Uncertain: Light At The End](https://store.steampowered.com/app/925570/) 的共同前十标签：Adventure、Choices Matter、Cinematic、Emotional、Futuristic、Multiple Endings、Robots、Sci-fi、Singleplayer、Story Rich。

两者都被描述为选择影响剧情、电影化、情感、未来、机器人、科幻、丰富剧情等，但好评率分别为 95.77% 和 64.92%。这说明类似现象不只出现在交通模拟类。

### 案例三：同系列作品的直观对照

[Cities: Skylines](https://store.steampowered.com/app/255710/) 与 [Cities: Skylines II](https://store.steampowered.com/app/949230/) 共享九个前十标签：City Builder、Simulation、Building、Management、Strategy、Sandbox、Singleplayer、Moddable、Economy。

第一代额外标签为 Resource Management，第二代为 Realistic。好评率却分别为 92.96% 与 52.63%，差 40.33 个百分点；两者评价数都超过七万。这个案例在展示时容易理解，但同系列不等于控制了发售年代、玩家预期和其他差异，不能当作因果实验。

## 避免只挑个例

本次共筛到 5,055 款满足口径的游戏。全部无序游戏对中，前十标签至少重合八个的有 2,631 对，其中好评率相差至少 25 个百分点的有 199 对，占 7.56%。

这里的 7.56% 是满足筛选条件的游戏对占比，不是游戏占比，也不是预测错误率；同一游戏可出现在多个游戏对中。这个结果同时说明“大差距案例确实存在”和“不能据此宣称相似标签游戏普遍口碑悬殊”。阈值为本次探索规则，未做阈值稳健性分析。

## 建议写进汇报的表述

> 在至少有 1,000 条评价的游戏中，我们发现，即使前十用户标签完全相同，好评率仍可相差约 30 个百分点。例如 Transport Fever 2 与 Cities in Motion 2 的好评率分别为 90.35% 和 57.67%。这表明类型标签能够描述游戏“是什么”，但不足以充分刻画其口碑差异。因此，我们将基于现有粗粒度属性的口碑预测降为探索方向，把主要精力放在成就完成表现与玩家参与度分析上。

要声称“本项目的口碑模型没有实用价值”，仍需模型相对均值 baseline 的独立验证结果。这些案例主要支持原讨论中的第二点，对市场变化和创新游戏的可预测性没有直接验证。

## 复现

仓库根目录执行：

```bash
git pull origin main
uv run python -m result.WWH.reputation-counterexamples.analyze
```

脚本只读查询，共用一个连接，事务内固定读快照，数据库查询超时 30 秒；在本机计算标签交集与差距。本次实际运行成功。
