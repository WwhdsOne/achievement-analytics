# 自选游戏主线过程：1～5款与分组示例

2026-10-16真实运行。选择顺序为God of War、Far Cry 3、Hollow Knight、Skyrim Special Edition、Little Nightmares，各行取此前N款，并显式指定每组N款，展示单组1～5款的效果。原固定01～15不变。

| 同组游戏数 | 完整节点曲线PNG | 逐游戏相邻区间PNG | 本次报告及JSON/CSV入口 |
|---|---|---|---|
| 1 | [1款曲线](8f814af788b9/08_story_curves_g01.png) | [1款区间](8f814af788b9/09_adjacent_progress_g01.png) | [报告](../../output/trajectory_comparisons/8f814af788b9/report.md) |
| 2 | [2款曲线](fb5cc5bec010/08_story_curves_g01.png) | [2款区间](fb5cc5bec010/09_adjacent_progress_g01.png) | [报告](../../output/trajectory_comparisons/fb5cc5bec010/report.md) |
| 3 | [3款曲线](de97ebc08d1e/08_story_curves_g01.png) | [3款区间](de97ebc08d1e/09_adjacent_progress_g01.png) | [报告](../../output/trajectory_comparisons/de97ebc08d1e/report.md) |
| 4 | [4款曲线](3785063f0415/08_story_curves_g01.png) | [4款区间](3785063f0415/09_adjacent_progress_g01.png) | [报告](../../output/trajectory_comparisons/3785063f0415/report.md) |
| 5 | [5款曲线](7ef31f223e6e/08_story_curves_g01.png) | [5款区间](7ef31f223e6e/09_adjacent_progress_g01.png) | [报告](../../output/trajectory_comparisons/7ef31f223e6e/report.md) |

每张PNG旁均有同名SVG。曲线只画实际节点，横轴归一的是节点位置而非时间；右侧卡片与线条颜色一致，同时保留原始首覆盖、全程比和最大相对差距位置。区间图每款一个面板，橙色标所有并列最大相对降幅。

同五款不指定分组参数时，每组默认2款，按输入顺序输出2＋2＋1：

- 第1组：[2款曲线](4cf771561ac6/08_story_curves_g01.png)、[相邻区间](4cf771561ac6/09_adjacent_progress_g01.png)。
- 第2组：[2款曲线](4cf771561ac6/08_story_curves_g02.png)、[相邻区间](4cf771561ac6/09_adjacent_progress_g02.png)。
- 第3组：[剩余1款曲线](4cf771561ac6/08_story_curves_g03.png)、[相邻区间](4cf771561ac6/09_adjacent_progress_g03.png)。
- [分组报告与数据](../../output/trajectory_comparisons/4cf771561ac6/report.md)。

同五款仅指定`--groups 2`时尽量均分为3＋2：第1组[曲线](661cc54349ed/08_story_curves_g01.png)/[区间](661cc54349ed/09_adjacent_progress_g01.png)，第2组[曲线](661cc54349ed/08_story_curves_g02.png)/[区间](661cc54349ed/09_adjacent_progress_g02.png)，[报告](../../output/trajectory_comparisons/661cc54349ed/report.md)。

显式`--games-per-group K`按K切分，末组不足照常保留；组数与每组款数同时指定时必须一致，容量矛盾报错，不丢弃选择。参数只用于自选模式，原`trajectory`不加选择参数仍复现自动三组案例。完整命令与网页数据查询函数见[运行说明](../../README.md)。手动选择支持既有198款，不受自动案例的同类型、至少6节点或全程相近条件限制。

数据JSON和CSV、manifest均为本地忽略产物；部署时须单独打包交付，不会随Git自动上传。图表与说明可跟踪。统计解释仍为模型主线节点的聚合覆盖，不是个人留存或因果结论。
