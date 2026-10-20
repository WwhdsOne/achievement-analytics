# T1Core：主线指标、类型、过程与时长分析

实施日期：2026-10-16。负责人：刘宇翔。已完成[data_plan](../../docs/data_plan.md)中的专题1指标准备、游戏对比、专题2类型阶段、专题3完整过程和专题4固定69款时长分析。任务5口碑与任务6同类参照已在[T2Sum](../T2Sum/README.md)完成，交接与审查见[delivery](../delivery/README.md)。当前图集统一位于[figures](figures/README.md)，编号01～15。

阅读入口：[INSTRUCT.md](../../docs/INSTRUCT.md)已统一汇总T1Core与T2Sum六项任务、完整命令、逐图读法、实际例子和解释边界；[DEPLOY.md](../../docs/DEPLOY.md)交接网页布局、交互与数据方案，包含任务4固定69款高亮、任务5评分口径与任务6参照条件切换和缺失处理。部署与前端交互由组长后续实施，文中明确区分已有能力与建议新增；本README继续作为程序参数、字段与保护规则的技术参考。

## 运行

从 `result/LYX` 执行：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py prepare
```

从项目根目录执行：

```powershell
uv --cache-dir result/LYX/analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B result/LYX/analysis/T1Core/run.py prepare
```

从 T1Core 内也可执行 `uv --cache-dir runtime/uv-cache run --frozen --no-sync python -X utf8 -B run.py prepare`。路径以程序位置解析，默认输出到 `T1Core/output`；`--output` 只能指向T1Core内的位置，重复运行覆盖该目录的本轮文件。

不需要API key、网络或共享云库。首次使用需要先有[T0Pre默认highest复现结果](../T0Pre/README.md)，包括metrics.json、verification.json和现有WWH借用库。源文件缺失、基准变为start、范围不再是198款、数据库文件或重算节点与T0Pre不同，会停止而不替换样本。

## 选择最多五款游戏画对比图

从LYX目录运行，按AppID选择，图中顺序与输入顺序一致：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py compare --appids 1593500 220240 367520 489830 424840
```

也可以使用游戏名称：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py compare --game-names "God of War" "Far Cry 3" "Hollow Knight" "The Elder Scrolls V: Skyrim Special Edition" "Little Nightmares"
```

或混合输入：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py compare --games 1593500 "Far Cry 3" "Hollow Knight" 489830 "Little Nightmares"
```

三个选择参数互斥，一次1～5款，重复游戏报错。名称优先规范化精确匹配，再尝试唯一的名称片段；忽略大小写、空格、标点和商标符号。若简称匹配多款，列出候选并要求使用完整名称或AppID，不自动猜。中文名只使用WWH原始name_zh实际存在的名称，不补造翻译。

不传选择参数时使用上述五款示例。只能选这198款底表已有的游戏，不将198款之外的游戏自动加入范围。列出全部可选名称和AppID：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py compare --list-games
```

默认 `--view both` 画上下两幅分组柱状图：

- 上图：首节点p_s、中位p_m、代表结局p_f的原始覆盖率。
- 下图：前段p_m/p_s、后段p_f/p_m、全程p_f/p_s的推进比。

可用 `--view coverage` 只画上图，或 `--view progress` 只画下图。每根柱标注百分比；没有中位节点的游戏显示“缺失”，不绘制假零值。比值若超100%会扩展坐标轴，不截断。标题下标明节点数及统一/多结局代理，保留原始选点规则。

图片默认集中在 `figures/`，五款示例命名为`01_game_stages.png/.svg`；其他选择使用`01_game_stages_<选择摘要>_<view>`，避免长文件名及相互覆盖。实际绘图长表CSV及来源JSON仍位于`output/comparisons`，以完整AppID顺序和view命名。相同选择与view重复运行会覆盖同名结果；`--output`可指定T1Core内其他目录。每次绘图先验证底表文件哈希，直接读取已有指标，不重新prepare、不改CSV底表、不写数据库或T0Pre。

示例：[五款游戏对比PNG](figures/01_game_stages.png)、[SVG](figures/01_game_stages.svg)。长表及来源JSON为本地忽略产物，图片可以跟踪。自定义`--output`时图输出到该目录的`figures/`，不覆盖默认图集；来源JSON的输出哈希路径相对于JSON所在目录解析。

## 专题2：类型与阶段差异

从 `result/LYX` 执行，不传游戏选择参数：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py types
```

默认读取已有指标文件，数值表、报告和manifest仍输出到 `output/type_analysis`，六张图集中输出到`figures/02_*`至`07_*`；`--output` 可指定T1Core内独立子目录，不能覆盖底表目录或comparisons。重复运行覆盖同名专题产物；自定义`--output`时图隔离到指定目录的`figures/`；不重新prepare、不调用API、不改数据库或T0Pre。缺少底表时先运行prepare，输入指纹不一致时停止，不自动换样本。

### 分组、样本与统计

- 主类型：WWH `gameplay[0]`，每款只进入一个组；完整玩法多标签另外计算，组内AppID去重，组间重叠，不能把组数量相加或当独立样本。
- 主分析：完整三节点183款，六项指标使用同一批游戏。全198款另存有效值补充，15款的中间指标保持缺失。
- 对照：唯一首位start且三节点170款、三节点且统一结局107款、三节点且多结局76款；均为主分析子集，不替换主范围。
- 先计算逐游戏比值，再汇总类型内中位数与四分位数，不按成就数或评论数加权，不用覆盖率的汇总中位数互除。
- n>=5进入主图，n<5只保留明细；n>=10提供95%百分位Bootstrap中位数区间，整行游戏联合重采样2000次，种子42，组级子流由分组/子集名称SHA256派生。区间反映当前游戏集合的重采样波动，不是玩家级误差或全Steam代表性保证。
- `late_minus_early`为每款游戏的后段减前段，再取组内中位数，不是两个组内中位数相减。CSV差值内部为比例，`*_pp`字段为百分点；其余指标内部0～1。
- `delta_to_cohort_pp`以同一子集所有游戏的该指标中位数为参照；多标签下整体参照每款游戏只算一次。

### 产物

| 文件 | 内容 |
|---|---|
| [analyze_types.py](analyze_types.py) | 分组、统计、联合重采样、口径对照与绘图 |
| [专题报告](output/type_analysis/report.md) | 全类型数值表、观察、解释边界与案例 |
| [group_summary.csv](output/type_analysis/group_summary.csv) | 主类型/多标签 × 主183款/全198款；六指标及配对差，n、缺失、分位数、区间与整体参照差 |
| [game_membership.csv](output/type_analysis/game_membership.csv) | 主类型和完整标签的唯一游戏成员关系 |
| [sensitivity_summary.csv](output/type_analysis/sensitivity_summary.csv) | 起点/结局子集及多标签相对主类型对照，含各自有效n与中位数差 |
| [case_pairs.csv](output/type_analysis/case_pairs.csv) | 同主类型、全程相近而阶段不同的最多三组案例与全部绘图数值 |
| [manifest.json](output/type_analysis/manifest.json) | 输入版本、参数、各子集AppID、保护核验、程序和产物SHA256 |

六张图均输出PNG和SVG：

1. [主类型节点覆盖热力图](figures/02_type_coverage.png)：首、中、末覆盖的游戏级中位数。
2. [主类型阶段推进热力图](figures/03_type_progress.png)：前段、后段、全程推进比。
3. [组内分布与中位数区间](figures/04_type_distribution.png)：每点一款游戏，箱体为四分位范围；n<10中位数用空心点，不画区间。
4. [完整标签节点覆盖](figures/05_tag_coverage.png)和[阶段推进](figures/06_tag_progress.png)：标签重叠下的补充。
5. [阶段差异案例](figures/07_stage_cases.png)：同主类型、全程差<=3个百分点，按前后段绝对差之和排序，取最多三组不重复游戏；分组柱状图不连接成玩家时间轨迹。

热力图两套口径均固定0～100%色阶，类型按样本数排序，各格与行标签共享有效n；不是留存曲线。当前存在主类型/多标签结果变化，不能仅凭主类型排名宣称稳定类型差异。极端案例用于检查章节跨度与模型节点含义，不直接归因于设计。

图面标题明确“主类型分组”或“完整多标签分组”，保留原两套口径。样本来源单独一行小字置于图底，其下简要注明分组方式、n为游戏数、逐游戏计算/组内中位数、阈值和解释。01与07分别注明所选游戏和案例筛选规则；全部图使用统一底部注释布局，文件名与数值不变。

数值、标签、成员、缺失、区间小样本规则、图中数值及旧prepare/compare入口通过真实运行与离线核查，记录见[runtime/type_analysis_acceptance.json](runtime/type_analysis_acceptance.json)。CSV/manifest/runtime继续Git忽略，图和聚合报告可跟踪；无需新增依赖。

2026-10-16图集整理：上述统计验收保留为原始实施记录；当前图片路径、编号、人名清理、来源哈希与数值文件不变的最新核验见[runtime/figure_cleanup_acceptance.json](runtime/figure_cleanup_acceptance.json)。默认图集7组PNG/SVG集中于figures，来源哈希的相对路径按manifest/JSON所在目录解析。

## 专题3：完整主线过程与相邻区间

从 `result/LYX` 执行：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py trajectory
```

不传游戏选择参数时，默认读取已有game_metrics/checkpoints/manifest，复现原来的自动三组案例；不重新prepare或写数据库。数据与报告写入`output/trajectory_analysis`，图片为`figures/08_story_curves`和`09_adjacent_progress`的PNG/SVG。`--output`可指向T1Core内独立目录，自定义图放其figures子目录；不能覆盖底表、类型结果、comparisons或默认图集目录。传入游戏选择参数时改用下述自选模式；`--view`仍只用于compare。

### 自选游戏与分组

支持`--games`混合输入AppID/英文名/已有中文名，也支持互斥的`--appids`或`--game-names`。只能从固定198款选择，保持输入顺序、拒绝重复和歧义，不自动扩样。每组1～5款，跨组总数最多198款；手动选择不受自动案例的同类型、同结局、至少6节点或全程相近条件限制。两节点游戏仍绘制一个首末区间并注明没有内部过程。

| 参数 | 行为 |
|---|---|
| 不指定分组参数 | 每组2款，5款分为2＋2＋1 |
| `--games-per-group K` | 每组1～5款，按输入顺序切分；末组不足K款仍输出 |
| `--groups G`或`--group-count G` | 只指定组数时尽量均分，前面的组多1款；5款指定2组为3＋2，组数不能超过游戏数、每组仍最多5款 |
| 同时指定两个参数 | 按每组款数切分，实际组数必须等于G；不一致报错，不截断游戏、不补空组 |
| `--list-games` | 列出198款的appid/name_en/name_zh，不生成图片；不与选择或分组参数混用 |

从LYX运行，5款默认输出3组：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py trajectory --games 1593500 "Far Cry 3" "Hollow Knight" 489830 "Little Nightmares"
```

上述命令末尾加`--games-per-group 5`可将五款画在同一组；加`--games-per-group 3`或仅加`--groups 2`均为3＋2；同时加`--games-per-group 2 --groups 3`为2＋2＋1。单款与中文名示例：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py trajectory --game-names "机械迷城"
```

每个实际分组输出两张PNG/SVG：08完整曲线叠加，右侧按颜色列游戏名、原始首覆盖、全程比与最大相对差距；09每款一个独立相邻区间面板，末组单款照常输出。默认图片放`figures/trajectory_comparisons/<分组摘要>/`，数据放`output/trajectory_comparisons/<分组摘要>/`，不覆盖固定01～15。摘要由有序AppID及实际分组生成，同一分组重跑覆盖其自身产物；自定义`--output`时图片隔离到其`<分组摘要>/figures`。

实现为[compare_trajectory.py](compare_trajectory.py)。`query_trajectory(selectors, kind="mixed", games_per_group=None, group_count=None)`只读返回结构化数据，不画图、不写文件，可供后续网页薄封装调用；selectors可为AppID整数/字符串或名称。返回selection分组信息、每组游戏的appid/name_en/name_zh、过程摘要、完整节点和相邻区间，缺失为null、比例内部0～1；当前仍校验指标快照并读取借用库名称，尚未新增HTTP服务。

绘图入口另存`data.json`供网页读取，以及selected_nodes.csv、selected_profiles.csv、selected_adjacent.csv、报告与来源manifest；完整成就名称、原数组位置、最大值并列标记均保留。1～5款真实示例与分组效果见[自选图集](figures/trajectory_comparisons/README.md)，核验记录见[runtime/trajectory_selection_acceptance.json](runtime/trajectory_selection_acceptance.json)。

### 计算与范围

固定198款全部保留，共1741个有效序列节点、1543段真实相邻区间；15款两节点游戏没有内部过程可比较，仍保存一个区间。至少3、4、6节点分别183、172、133款；至少6节点仅为案例筛选条件。

- 只使用`sequence_position`非空的节点，原文件顺序、序号连续性、原数组下标及首末身份必须一致；不用未选中的备选结局，不按解锁率或id排序。输入缺失/不合法则停止，不跨越节点拼接。
- 相邻推进比=`to_rate/from_rate`，相对降幅=`1-ratio`，原始覆盖差=`100*(from_rate-to_rate)`个百分点；原始覆盖与节点身份全部保留。
- 分母<=0时留空，零分子保留0；反向跳跃不截断或重排，保存异常标记。相邻比值全部有效时，乘积必须与既有全程比一致。
- 原始节点覆盖除以该游戏首覆盖形成归一曲线；横轴`(序号-1)/(节点数-1)`只是节点相对位置，不是时间或真实剧情百分比，不插值补出观测节点。
- 最大相对降幅和最大百分点差分别计算，并列全部在明细标记，摘要和曲线展示最早一段。`max_gap_share`=最大百分点差/首末总百分点差，仅非反向且首末有正差时计算，否则留空；它受节点数量影响，不直接跨游戏排名。

### 案例、图表与解释

至少6节点、同主类型、同结局口径、节点数差<=2、全程比差<=3个百分点，共63对候选。排序依次为：最大相对差距区间中点位置差降序、覆盖差集中度差降序、全程差升序、节点数差升序、AppID升序；贪心选最多3组不重复游戏，不自动放宽条件。全部候选、排名、选中组号留档。

- [08完整主线曲线](figures/08_story_curves.png)：每组两款，起点归一100%，只画原观测节点；粗线标最早最大相对降幅区间，图例同时给原始首覆盖与全程比，图下标具体成就名称（长名截短，正文完整）。
- [09相邻区间推进](figures/09_adjacent_progress.png)：每款一个面板，每柱一段真实相邻区间；橙色标最大相对降幅及并列，轴下给该区间原始百分点差。相对降幅较大不一定意味着原始百分点差较大。

当前三组均为动作主类型、统一结局：Splinter Cell Blacklist/Dead Cells，POSTAL 2/Dragon's Dogma 2，Nuclear Throne/CrossCode。它们是特定选样结果，不代表所有类型；不同游戏首覆盖不同，归一化曲线不代表同一批玩家或相同门槛。模型节点、跨度和结局代理仍有边界，不能由最大差距认定Boss、剧情或操作难度导致流失。

| 文件 | 内容 |
|---|---|
| [analyze_trajectory.py](analyze_trajectory.py) | 节点验证、相邻计算、摘要、63对候选、案例与两图 |
| [adjacent_nodes.csv](output/trajectory_analysis/adjacent_nodes.csv) | 1543行：两端名称/身份/位置/阶段/置信度、解锁率、比值、差值、并列和异常 |
| [game_profiles.csv](output/trajectory_analysis/game_profiles.csv) | 198行：节点数、全程与乘积核对、两类最大差距及并列、集中度和展示条件 |
| [case_candidates.csv](output/trajectory_analysis/case_candidates.csv) | 全部合格候选、可重现排序和3组选中标记 |
| [report.md](output/trajectory_analysis/report.md) | 完整节点名称、实际案例数值、计算与解释边界 |
| [manifest.json](output/trajectory_analysis/manifest.json) | 来源、参数、计数、旧图保护、程序与产物哈希 |

运行前后保护两份数据库、T0Pre/T2/T3、原底表、比较/类型结果和01～07图片；新图不覆盖旧图。独立CSV核查与边界验证见[runtime/trajectory_acceptance.json](runtime/trajectory_acceptance.json)。不增加依赖或API请求。

## 专题4：主线参考耗时、平均游玩时长与推进

从 `result/LYX` 执行：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py duration
```

默认数值表和报告写入`output/duration_analysis`，图10～13集中figures；自定义`--output`限T1Core独立目录，图片放该目录的figures，不覆盖默认图集。不能指向旧底表、comparisons、type_analysis、trajectory_analysis或默认图集目录；duration不接受游戏选择或分组参数，游戏选择仅用于compare/trajectory，view仅用于compare。

### 数据与固定69款

所有主图均为同一69款，按原排名顺序冻结AppID，清单SHA256为`48d3f0600fbbb2cbaff4e1ffe3df9d330af35ab6ec70e384906a9161ff82e4a9`。

- 主线、三节点与阶段推进继续读取既有指标表，固定主范围198款，其中三节点183款。
- HLTB `main_hours`只读旧本地库`database/achievements.sqlite`，再叠加人工确认输入。原快照198款中正值75、NULL85、本地未匹配37、零值1；补充后三款NULL转为分析层有效值，正值78、NULL82；完整三节点且HLTB正值由68变71。本地未匹配不等于HLTB网站无数据。
- RAWG `playtime`读取借用库games.payload.rawg，并与旧库playtime逐项核对这68款；两份副本当前完全一致。原快照有3款RAWG缺失，人工补充God of War后仅2款仍缺失；再增加3款HLTB，最终共同样本69款，不补零或用一类时长填补另一类。
- 按负责人授权的研究口径，RAWG作为用户平均游玩时长，HLTB作为主线参考耗时，均为小时。R=`playtime/main_hours`，53款R<1、16款R>=1；R不是个人主线完成度或通关后游玩量。
- 名称按同AppID交叉核对，出现差异或RAWG副本不一致时停止，不自动按名称改配；两份数据库只读事务，不合并或回写。不做类型分组、着色、拟合或对照。

### 统计与图

Spearman使用平均秩处理整数RAWG时长的并列；对69行游戏联合重采样2000次、种子42，以2.5/97.5百分位给相关区间，记录有效重复数。计算两种时长及R与三个推进比的9项关联，另列两种时长的关联，共10项；不按p值挑选结论，不做复杂曲线或自动门槛搜索。

HLTB四个预先规定区间≤5、>5～15、>15～30、>30小时分别10、30、20、9款；保存阶段比中位数/四分位范围，n>=10才给游戏级Bootstrap中位数区间。仍以每款游戏为单位、不按评论数或成就条数加权，不开展类型对照。

| 图 | 用途 |
|---|---|
| [10_time_comparison](figures/10_time_comparison.png) | HLTB主线参考耗时×RAWG平均游玩时长，虚线为相等参考，颜色为全程推进比 |
| [11_length_progress](figures/11_length_progress.png) | 主线参考耗时与前/后/全程推进，三个面板同69款 |
| [12_playtime_progress](figures/12_playtime_progress.png) | 平均游玩时长与前/后/全程推进，布局同11 |
| [13_time_ratio](figures/13_time_ratio.png) | R与全程推进，R=1及全程样本中位数作描述参考，旁列固定规则选出的案例 |

案例按R>=1/<1、全程>=69款中位数/<中位数划四象限，每区按`abs(log2(R))`降序、推进偏离中位数距离降序、AppID升序取一款，无样本不调阈值补齐。这是探索性极端案例，不是各区的典型代表，也不是入库/质量门槛。

| 文件 | 内容 |
|---|---|
| [analyze_duration.py](analyze_duration.py) | 双库只读、69款冻结、统计、案例和四张图 |
| [duration_cohort.csv](output/duration_analysis/duration_cohort.csv) | 固定69款的两类时长、R、六项节点/推进指标和来源质量标记 |
| [duration_eligibility.csv](output/duration_analysis/duration_eligibility.csv) | 198款逐步筛选、三节点标记、两源时长状态和明确排除原因 |
| [duration_summary.csv](output/duration_analysis/duration_summary.csv) | 三个时长变量与三个推进比的游戏级分布 |
| [time_correlations.csv](output/duration_analysis/time_correlations.csv) | 10项Spearman及游戏级区间、并列数量信息、有效重采样数 |
| [duration_groups.csv](output/duration_analysis/duration_groups.csv) | 四个HLTB区间×三个推进比，n、分位数与适用的区间 |
| [duration_cases.csv](output/duration_analysis/duration_cases.csv) | 四象限选样及阈值、成员数、原始数值 |
| [report.md](output/duration_analysis/report.md) | 全部实际统计、图、来源与解释边界 |
| [manifest.json](output/duration_analysis/manifest.json) | 样本、两源指纹、参数、保护核验和产物哈希 |

两类时长与成就覆盖的来源口径不同，不宣称来自同一批玩家。69款是有效交集，不代表全部Steam；R含HLTB分母，因此保留两种原始时长独立分析作对照。相关和样本重采样区间不证明因果，也不覆盖模型标注误差；不把全程推进比当日留存。所有原底表、01～09图、其他分析结果、数据库和共享依赖文件保持不变。独立数值、区间、边界和图面核验见[runtime/duration_acceptance.json](runtime/duration_acceptance.json)。

### 补充14～15：主线＋支线与全收集参考耗时

从LYX运行独立补充入口，仅生成14～15，不重跑或覆盖10～13：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/analyze_duration_references.py
```

沿用13号图的同69款、原全程推进比与案例规则；只读旧库`games_time.extra_hours`和`completionist_hours`并叠加人工确认的HLTB补空值，有效输入两列均69款正值，顺序异常0。前者对应HLTB Main + Extras（主线＋额外内容，此处简称主线＋支线），后者对应Completionist完整游玩参考（此处简称全收集），不等于Steam全成就耗时。

| 图 | 横轴 | 纵轴 | R<1 / R>=1 |
|---|---|---|---|
| [14_extra_time_ratio](figures/14_extra_time_ratio.png) | playtime / extra_hours | 原全程推进比p_f/p_s | 60 / 5款 |
| [15_completionist_time_ratio](figures/15_completionist_time_ratio.png) | playtime / completionist_hours | 原全程推进比p_f/p_s | 63 / 2款 |

Spearman、整行游戏Bootstrap 2000次、种子42与13号图完全一致，两个相关系数分别+0.652和+0.630。案例仍按四象限取极端值；全收集图的“R>=1且推进低于中位数”象限为0款，明确留空，不改变阈值。纵轴没有改成支线或全收集完成率，时长比也不代表个人内容完成比例。

实现为[analyze_duration_references.py](analyze_duration_references.py)，默认新增[output/duration_references报告](output/duration_references/report.md)、reference_cohort.csv（69款原值与两个新比值）、reference_correlations.csv（两项关联及区间）、reference_cases.csv（按reference_field区分案例，time_ratio为该参考口径的比值）与manifest.json。支持`--output`指定T1Core内独立目录，图随之放其figures；拒绝覆盖旧分析和默认图集目录。

原duration入口及其完整产物保持不变；01～13图、两份数据库、底表、T0Pre和共享依赖文件均保持不变。来源、数值、区间、图面和旧产物保护核验见[runtime/duration_references_acceptance.json](runtime/duration_references_acceptance.json)。

## 数据来源与范围

- 主线、分类与类型来源：`result/LYX/NewDB/wwh5.sqlite3`，只读；时长专题额外只读旧本地库的HLTB字段，叠加人工补充后形成69款子样本，不替换198款主范围。
- 唯一入选范围：T0Pre默认highest口径下，`curve.completion` 非空的198个AppID，保持原冻结排名顺序。
- 当前清单SHA256：`26b6a452b72e9466bced793868e7af8bd01c15980cf9bb4e27ab0799316f477b`。它是AppID数组的canonical JSON SHA256，不是CSV文件的SHA256。
- 复用T0Pre的storage只读连接、story_curve筛选和参数；只调用计算函数，不调用T0Pre的analyze入口或文件写入函数。
- 仅查询这198款的游戏、成就、分类、剧情和游戏维度，逐款重算曲线并与T0Pre完全比较；不重跑1000款分析、不重新分类，不套用旧LYX八类关系表。
- 游戏主类型来自`game_labels.payload.gameplay[0]`；`gameplay_labels`保存其闭集玩法列表，竖线分隔。本次未把自由文本题材等维度强行整理为新分类。

## 数组位置中位节点：主口径

1. 读取WWH已经通过筛选的公共本体主线节点，保留每项原`source_checkpoint_index`，不按id或解锁率排序。
2. 非结局节点全部按原数组顺序保留；结局沿用WWH计算：取解锁率最高的end节点，并列时取原数组中最先出现者。不相加、不把多个结局当作连续章节。
3. 得到“非结局节点＋一个代表结局”的有效序列，继续核对其原数组下标严格递增。
4. 首节点为序列第1项，末节点为代表结局。n>=3时，中位1基位置为ceil(n/2)，即Python下标`(n-1)//2`；偶数取靠前者。
5. 只有2项时，中点及前/后段推进比均留空，仍保留该游戏及首到末比例。

因此“数组位置中位”是**WWH筛选和代表结局处理后的有效序列中位**。原始数组中未进入公共主线的分支不参与取中位；备选结局仍在节点明细中留档。它不是stage=middle、解锁率中位数，也不代表游玩时间中点。原数组0基下标与分析序列1基位置分别保存。

无start或多个start不导致游戏被删除；按首个可用节点计算，并保留start_label_count、first_stage及quality_flags。不新增至少6节点、唯一结局或人工核验前置。

## 公式与单位

| 字段 | 定义 |
|---|---|
| p_s | 首节点解锁率，0～1 |
| p_m | 位置中位节点解锁率，0～1；缺失留空 |
| p_f | 代表结局解锁率，0～1 |
| early_progress_ratio | p_m / p_s |
| late_progress_ratio | p_f / p_m |
| overall_progress_ratio | p_f / p_s |
| wwh_baseline_rate | WWH原有最高成就解锁率，0～1 |
| wwh_completion_ratio | p_f / wwh_baseline_rate，必须与T0Pre完全对应 |

WWH选样基准为highest；T1新增三节点比值的分母为首节点。两者区分保存。分母<=0或缺失时留空，分子为0保留有效零；比值越界保留原值并记录异常，不截断。

## 文件与字段

| 文件 | 内容 |
|---|---|
| [run.py](run.py) | 命令入口，默认prepare |
| [prepare_metrics.py](prepare_metrics.py) | 固定范围、只读加载、节点选择、公式、CSV及报告 |
| [plot_files.py](plot_files.py) | 图表编号、短命名和默认/隔离目录路由 |
| [compare_games.py](compare_games.py) | AppID/名称选择、最多五款的分组柱状图、PNG/SVG与绘图数据留档 |
| [analyze_types.py](analyze_types.py) | 专题2：主类型与完整标签分组、阶段分布、样本与结局对照 |
| [analyze_trajectory.py](analyze_trajectory.py) | 专题3：完整主线过程、相邻区间、候选与案例曲线 |
| [compare_trajectory.py](compare_trajectory.py) | 专题3自选：名称/AppID解析、1～5款分组、只读查询、曲线/区间图及JSON/CSV |
| [analyze_duration.py](analyze_duration.py) | 专题4：69款共同样本的两类时长、相对比值和推进关联 |
| [output/cohort.csv](output/cohort.csv) | 一款游戏一行：AppID、展示名、原排名、WWH玩法、版本、范围指纹 |
| [output/checkpoints.csv](output/checkpoints.csv) | 一项WWH有效公共节点一行，包含未选中的备选结局、原数组位置、阶段、条件、解锁率、选点角色 |
| [output/game_metrics.csv](output/game_metrics.csv) | 一款游戏一行，保留全部198款、三节点及指标、缺失与来源标记 |
| [output/report.md](output/report.md) | 口径、覆盖、游戏级指标描述与样例 |
| [output/manifest.json](output/manifest.json) | 来源版本、全部参数、清单/输出指纹、保护对象前后哈希、核验结果 |

节点字段：`local_id`用于关联WWH成就，`source_checkpoint_index`是原数组0基下标，`source_checkpoint_order`是下标+1，`sequence_position`是当前有效序列1基位置。未选结局的sequence_position为空；`is_first/is_middle/is_end`指明角色。

游戏字段：`common_checkpoint_count`是WWH所有有效公共节点数；`node_count`是只保留一个代表结局后的序列长度。`middle_sequence_position`是中位节点1基位置。`first/middle/end_local_id`及对应展示名、原数组下标、阶段可追溯具体选点。

`three_point_available`表示是否有三个不同节点；`metric_status`为complete_three_point或two_point_only。`quality_flags`以竖线分隔，包含two_points_only、no_explicit_start、multiple_start_labels、multi_ending_proxy、end_max_tie，以及可能的零分母或比值越界标记。

`ending_type`、`end_candidate_count`、`end_max_tie_count`保留WWH结局代理信息。`model_all_later_requires_start`仅表示所有后续选中节点的模型标记，不是人工证明。

CSV使用UTF-8 BOM，缺失值为空、布尔值为true/false；数值保留浮点精度，不提前四舍五入。Excel公式前缀文本加单引号，仅影响CSV展示安全，不改源数据。CSV与详细manifest作为运行产物忽略，说明、程序和聚合报告可以跟踪。

## 实际结果与边界

当前198款中：183款具备完整三节点，15款只有首末节点；统一结局120款、多结局78款；无start9款、多个start7款。唯一首位start且三节点齐全的对照子集170款，不替换主范围。

prepare每轮均核对：198款及顺序不变、重算曲线与T0Pre一致、节点身份唯一、中点不与首末重复、缺失不补零、前后段乘积等于全程比、代表结局与WWH原指标一致，以及数据库/T0Pre核心文件/T2Depth/T3Sum前后指纹不变。compare/types读取并校验prepare产物，不改原底表。无新增数据库表、写库或模型调用。

这些指标描述模型标注主线节点的聚合覆盖差异，不直接代表用户留存或弃坑；没有节点包含关系证据时不解释为条件玩家比例。不同游戏节点密度、首节点和代表结局的含义仍可能不同。

报告中各项游戏级中位数分别使用该字段的有效游戏集合，不能将这些汇总中位数互除来代替逐游戏比值，也不能将它们连成同一批玩家的留存轨迹。离线边界与CSV核验记录见 [runtime/acceptance.json](runtime/acceptance.json)。

## 2026年10月20日任务4补充

原65款加4款人工补充形成69款。10个值保存在[人工时长输入](inputs/manual_duration_supplements.csv)，两份数据库不变。10～15图、结果表、来源清单和网页同步更新；默认预选Hollow Knight、奥德赛、33号远征队、God of War、艾尔登法环。全程推进相关：主线比+0.652、主线加额外内容比+0.652、全收集比+0.630。任务5和任务6原样本、原统计不变。
