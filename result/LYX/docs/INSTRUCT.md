# LYX分析使用与读图说明：T1Core与T2Sum六项任务

**2026-10-20任务5评分更新：** [评分补充输入](../analysis/T2Sum/inputs/manual_rating_supplements.csv)记录33号远征队92/4.42、God of War94/4.54及RAWG评分人数5310。共同评分样本由原140款增加至142款，图16～18及统计重算；Steam183款不变。两库只读，补充确认日期与旧快照采集日期分开记录。

**2026-10-20任务4更新：原65款加人工补充4款，共69款。** 用户手动查询确认的10个值保存在[人工补充输入](../analysis/T1Core/inputs/manual_duration_supplements.csv)，不写回两份SQLite。三款补HLTB三类耗时，God of War补RAWG 15小时；五款预选均可在任务4显示。任务5三评分142款、任务6长度条件原68款不随本次补充改变。


更新：2026-10-19。阅读对象：刘宇翔、组长及需要复现或讲解图表的组员。

本文件解释“做了什么、如何调用、图上在比较什么、能得出什么结论”。程序与字段细节见[T1Core说明](../analysis/T1Core/README.md)、[T2Sum说明](../analysis/T2Sum/README.md)及[同类参照说明](../analysis/T2Sum/BENCHMARK.md)，网页交接见[DEPLOY](DEPLOY.md)，固定图见[T1图集](../analysis/T1Core/figures/README.md)与[T2图集](../analysis/T2Sum/figures/README.md)。六项任务现已整合为[WEB交互简报](../WEB/index.html)，支持1～5款选择、图表切换和高亮；它读取冻结结果，不在点击时运行下文的Python分析命令，当前尚未公网部署。

快速定位：[网页使用](#31-已有网页的打开预览与核验) · [命令总览](#32-python分析与出图接口) · [任务5口碑](#8-任务5口碑与主线推进) · [任务6同类参照](#9-任务6玩法多标签下的同类参照) · [刷新与讲解顺序](#10-快速使用顺序与核验)。任务1～4的详细说明保留在第4～7节。

## 1. 六项任务如何连起来

研究目标是从公开聚合成就数据观察游戏的主线推进表现，结合玩法类型、过程形态和游玩投入解释差异。当前没有个人游玩轨迹或逐日活跃数据，因此使用“覆盖率、推进比、游戏级关联”作为正式名称。

| 任务 | 回答的问题 | 已完成的内容 | 样本与图 |
|---|---|---|---|
| 1. 建立指标 | 如何统一比较不同游戏的主线推进？ | 首/中/末节点选择、原始覆盖、前/后/全程推进比、任选游戏柱状对比 | 198款；图01 |
| 2. 类型差异 | 不同玩法的差异出现在入门、前段还是后段？ | 主类型与完整多标签分组，中位数、分布、样本量与重采样区间 | 主183款、补充198款；图02～07 |
| 3. 完整过程 | 全程表现相近，过程是否也相近？ | 全节点曲线、真实相邻区间、最大相对降幅与百分点差、自动案例和自选分组 | 198款、1741个序列节点、1543段区间；图08～09及自选图 |
| 4. 时长关联 | 内容参考长度、平均游玩投入与主线推进有什么关系？ | 两类时长对照、阶段关联、三类参考耗时比值与案例 | 固定同69款；图10～15 |
| 5. 口碑关联 | 高评价的游戏是否也有较高主线推进，差异在哪个阶段？ | Steam四象限、阶段关联、三评分共同样本、多标签共性和探索案例 | Steam183款、共同评分142款；图16～18 |
| 6. 同类参照 | 与玩法及结局口径相近的游戏相比，目标处于什么位置？ | 留一同类参照、三阶段差值、五条件对照、解释卡片 | 183目标、主参照181有效；图19～21 |

固定来源链为：借用的1000款冻结快照→198款有效主线曲线；198款中183款三节点完整；叠加本次人工补充后，这183款中71款有正值HLTB主线耗时，其中69款也有正值RAWG时长。183款是类型主分析的范围，69款是时长专题范围，不能把它们的统计分母混用。任务5先固定完整三节点183款，跨评分对照再取同142款；任务6沿用183款目标，至少5款参照才计算比较，主口径181款有效。这些是不同资格条件，不是数据丢失或全量1000款的完成比例。

## 2. 数据来自哪里，当前保存在哪里

### 2.1 两份数据库的分工

主线、分类、剧情顺序和游戏类型采用[借用快照](../NewDB/wwh5.sqlite3)：

| 表 | 作用 |
|---|---|
| games | 冻结游戏身份与排名；payload中保存name_en/name_zh、原始成就快照和RAWG信息 |
| achievements | 核对成就展示名、描述和percent原值 |
| achievement_labels | 使用已有语义分类参与主线节点资格判断 |
| story_labels | payload.checkpoints提供主线节点、stage、route、原数组顺序及相关标记 |
| game_labels | payload.gameplay提供玩法闭集；首项作为主类型，完整列表作为多标签 |
| model_calls、metadata | 核对成功分类调用及数据版本，不在本模块调用模型 |

任务1从上述表构建底表；任务2、3复用底表，并通过games补充名称。任务4还读取games.payload.rawg.playtime。

任务4额外只读[旧本地库](../database/achievements.sqlite)的games_time：main_hours、extra_hours、completionist_hours，并核对本地playtime副本；games用于按AppID核对名称。数据库始终只读，不合并、不建分析表、不回写分类。

任务5继续读取WWH games.payload中的positive/negative与rawg评分，game_labels补充完整玩法及自由文本维度；LYX games_time.main_hours只用于相近长度案例。任务6复用任务5已保存的评分/时长底表，再读取WWH原始成就描述解释节点。两库的字段分工见[DATABASE_WWH](DATABASE_WWH.md)与[DATABASE_LYX](DATABASE_LYX.md)。

### 2.2 分析结果已落盘

| 位置 | 核心内容 |
|---|---|
| [game_metrics.csv](../analysis/T1Core/output/game_metrics.csv)、[cohort.csv](../analysis/T1Core/output/cohort.csv) | 198款游戏指标与范围 |
| [checkpoints.csv](../analysis/T1Core/output/checkpoints.csv) | 1824项有效公共节点，含未选中的备选结局；其中1741项进入最终序列 |
| [type_analysis](../analysis/T1Core/output/type_analysis) | 类型汇总、游戏成员关系、口径对照、案例 |
| [trajectory_analysis](../analysis/T1Core/output/trajectory_analysis) | 198款过程摘要、1543段相邻区间、63对候选及自动案例报告 |
| [trajectory_comparisons](../analysis/T1Core/output/trajectory_comparisons) | 各次手动选择的分组数据JSON、节点/摘要/区间CSV、报告 |
| [duration_analysis](../analysis/T1Core/output/duration_analysis) | 69款主线时长底表、198款筛选记录、时长分组、10项关联及案例 |
| [reference_cohort.csv](../analysis/T1Core/output/duration_references/reference_cohort.csv) | 同69款的RAWG时长、三类HLTB耗时、三个时长比及主线指标 |
| [duration_references](../analysis/T1Core/output/duration_references) | 图14～15的两项关联、案例与报告 |

数值保留精度，比例内部通常为0～1；CSV为空表示缺失，不能读成0。`*_pp`表示百分点；内部的后段减前段差值仍为比例，需要展示时乘100。CSV为UTF-8 BOM，布尔序列化为true/false；JSON的缺失为null。

manifest记录来源版本、参数、清单和产物哈希；PNG用于直接看图，SVG可缩放。当前T1Core/output、T2Sum/output已按交付要求纳入Git；SQLite、runtime和其他被忽略附件仍须单独准备。原Python分析/查询程序仍会读SQLite核对快照或名称；已有CSV不代表所有原命令均能脱离数据库运行。WEB则只消费现有26张CSV与7份manifest，构建后把展示数据内嵌到HTML，查看与交互均不读取SQLite。

## 3. 运行前提与命令总览

### 3.1 已有网页的打开、预览与核验

直接打开[WEB/index.html](../WEB/index.html)可查看六项任务的核心交互。默认选中Hollow Knight、奥德赛、33号远征队、God of War及艾尔登法环；搜索限于198款有效主线游戏，支持AppID、英文名及已有中文名，最多选5款。时长、口碑、类型等总体背景不随选择缩小；缺失值保留原因，不补零。

推荐使用本机HTTP预览，使页面末尾21张原图、34份来源及完整文档链接都能按原目录访问。以下命令从**仓库根目录**执行：

```powershell
uv run --frozen --no-sync python -X utf8 -B -m http.server 8765 --bind 127.0.0.1 --directory result/LYX
```

打开`http://127.0.0.1:8765/WEB/index.html`，结束时在启动服务的终端按Ctrl+C。服务根应为LYX；仅托管WEB或单独复制index.html仍支持核心交互，但无法访问上级docs、analysis中的附件。HTML的脚本、样式、数据均已内嵌；内置浏览器已核验HTTP访问，未直接实测file://离线模式。

只有修改WEB源码或更新冻结结果时才需重新构建。下列命令也从**仓库根目录**执行，第一条写入WEB成品，第二条只读检查成品与来源一致性：

```powershell
uv run --frozen --no-sync python -X utf8 -B result/LYX/WEB/build.py
uv run --frozen --no-sync python -X utf8 -B result/LYX/WEB/verify.py
```

二者均不连接数据库、不请求DeepSeek、不重跑分析统计；构建只写WEB/index.html与source_manifest.json。详细操作、文件分工与交互范围见[WEB使用说明](../WEB/README.md)。当前浏览器28项检查的记录与边界见[WEB验收](../WEB/ACCEPTANCE.md)：消费CSV自身哈希与关键数值关系已通过检查，但当前仍保留4条历史父manifest指纹漂移警告，不能表述为全部历史审计链同步通过。

### 3.2 Python分析与出图接口

本节之后的分析终端命令均从LYX目录运行：

```powershell
cd D:\PycharmProjects\achievement-analytics
git pull origin main
cd result\LYX
```

使用项目已有uv环境，不需DeepSeek密钥或共享云库。需要已存在的两份本地SQLite、[T0Pre最高覆盖基准产物](../analysis/T0Pre/README.md)及当前代码依赖。查看已有图不需要重跑分析；源数据或输入指纹不一致时应先核对来源，不强行绕过校验。

表中省略路径的run.py均指analysis/T1Core/run.py；任务5/6明确使用analysis/T2Sum/run.py，不能在LYX根目录直接写python run.py。

| 目的 | 入口 | 是否选择游戏 |
|---|---|---|
| 准备指标 | run.py prepare；省略子命令也等同prepare | 固定198款，不出图 |
| 任务1对比 | run.py compare | 1～5款；不传时使用既有五款示例 |
| 任务2总体分析 | run.py types | 固定主分析及补充子集 |
| 任务3自动案例 | run.py trajectory | 不传选择参数时，按原规则选三对案例 |
| 任务3自选 | run.py trajectory加选择参数 | 每组1～5款，可多组 |
| 任务4主分析 | run.py duration | 固定69款，生成10～13 |
| 任务4补充 | analyze_duration_references.py | 固定同69款，生成14～15 |
| 任务5总体/高亮 | analysis/T2Sum/run.py reputation | 无选择为固定总体；1～5款选择仅高亮，生成16～18 |
| 任务6总体/自选 | analysis/T2Sum/run.py benchmark | 无选择为固定背景＋自动案例；1～5款选择只更新关注对象，生成19～21 |

T1Core入口的写入限于T1Core。`--output`是输出位置，不是新的输入底表目录；默认命令之间仍读取既有默认指标文件。自定义输出使用独立子目录，避免覆盖其他专题。各入口具体目录保护见T1Core README。T2Sum两个入口将输出写入自身目录；当前不提供--output，手选结果按摘要独立存储。

## 4. 任务1：主线覆盖与阶段推进

### 4.1 选点与指标

有效公共主线节点保持原checkpoints数组顺序。多个结局沿用既有规则：取解锁率最高的一个，比例并列取原数组先出现者；保留备选结局明细，不相加、不当作连续章节。

在“非结局节点＋一个代表结局”的序列中，选择首项、位置中位项、末项。偶数节点取靠前中点，Python下标为`(n-1)//2`；只有两项则中点留空。位置中位不等于stage=middle，也不表示一半游玩时间。

| 符号/字段 | 定义 | 主要说明 |
|---|---|---|
| p_s / p_m / p_f | 首、中、末成就的原始解锁率 | 观察这些节点在全局统计中的覆盖 |
| early_progress_ratio | p_m / p_s | 从首节点到位置中位节点的相对覆盖 |
| late_progress_ratio | p_f / p_m | 从位置中位节点到代表结局的相对覆盖 |
| overall_progress_ratio | p_f / p_s | 从首节点到代表结局的相对覆盖 |

例如首/中/末覆盖80%/48%/24%，前段/后段/全程推进比为60%/50%/30%。前后段比值相乘等于全程比；不能拿不同类型的汇总中位数互除代替逐游戏计算。

分母非正或缺失时留空，合法零分子保留。当前198款中183款三节点完整，15款中点与前后段为空；无明确start或多start保留标记，不自动删除。WWH原p_f/最高成就覆盖另存，不能与本任务p_f/p_s混为一个指标。

### 4.2 出图命令

先在需要准备/刷新底表时运行：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py prepare
```

任选游戏，AppID和名称可混合：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py compare --games 1593500 "Far Cry 3" "Hollow Knight" 489830 "Little Nightmares"
```

可替换为互斥的`--appids`或`--game-names`；`--view both`为默认上下两图，coverage只画覆盖，progress只画推进比。用`compare --list-games`查看198款清单。名称先规范化精确匹配，再尝试唯一片段；歧义/重复报错。中文名只认数据库已有别名，并非任意中文译名都可查。

默认五款图为[01](../analysis/T1Core/figures/01_game_stages.png)，其他选择使用摘要命名，实际值和来源另存在output/comparisons。相同选择/视图重跑覆盖自身结果。

### 4.3 怎么看图，研究意义是什么

先看上图原始首覆盖，再看下图推进比：某游戏首覆盖较高但全程比低，说明已有标注节点之间覆盖差距较大；另一款首覆盖低但全程比较高，则是在不同起点基准上保持了较高的首末比例。两种现象都应保留，不能只按一个数给游戏排“粘性总榜”。

前段较低、后段较高提示差距更多集中于前半段标注节点；反过来提示后半段差距较大。它们帮助选择下一步要查看完整过程的游戏。缺失柱表示缺少中位节点，不表示所有人都停止游玩。

这些比值比较的是聚合覆盖。只有节点解锁集合的前置包含关系被证明时，才可能进一步讨论条件玩家比例；本快照没有逐日玩家轨迹，因此不能直接读成日留存或已弃坑人数。

## 5. 任务2：类型与阶段差异

### 5.1 调用与两套分组

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py types
```

本入口不接收游戏选择参数，生成固定图02～07。主类型采用gameplay[0]，每款只属于一个组；完整多标签采用全部gameplay，组内AppID去重、组间允许重叠。两套图属于不同成员口径，不能把多标签组的游戏数相加当独立总样本。

主分析固定183款三节点完整游戏，六个指标使用同一批成员；另存全198款有效值，以及起点/结局子集对照。先算每款比值，再对类型取中位数。每款游戏同权，不按成就或评论数加权。

有效n>=5进入主图；n>=10才提供2000次游戏级Bootstrap中位数95%百分位区间，种子42。n是游戏数，区间不是玩家级误差，也不保证代表全部Steam。

### 5.2 逐图读法

| 图 | 看什么 | 能观察的模式 |
|---|---|---|
| [02](../analysis/T1Core/figures/02_type_coverage.png) | 主类型×首/中/末原始覆盖；同时看n | 哪类起点覆盖较高，结局覆盖是否仍较高 |
| [03](../analysis/T1Core/figures/03_type_progress.png) | 主类型×前/后/全程推进比 | 相对差距更偏前段还是后段，类型内部汇总有何不同 |
| [04](../analysis/T1Core/figures/04_type_distribution.png) | 每点一款、四分位范围、中位数与适用区间 | 类型内是否分散，少量极端游戏是否影响直觉 |
| [05](../analysis/T1Core/figures/05_tag_coverage.png)、[06](../analysis/T1Core/figures/06_tag_progress.png) | 全部玩法标签下的同类覆盖与推进 | 主类型结论是否依赖“谁被归入这一组” |
| [07](../analysis/T1Core/figures/07_stage_cases.png) | 同主类型、全程相近的成对阶段柱 | 全程相近时，前后段是否存在明显反差 |

热力图色阶相同，先确认行的样本数，再横向比较阶段、纵向比较类型；颜色深浅不是显著性判断。04中的分布反映“游戏之间不同”，不是每款游戏内部玩家的时长或留存分布。

实际例子：当前主类型“冒险”21款，全程中位数58.8%；按完整冒险标签则146款、中位数35.9%。成员口径变化会改变汇总，这两张图不是互相矛盾。它提示后续讲解必须带上分组定义，而不能只说“冒险游戏完成率最高/最低”。

价值是建立总体比较背景、发现值得具体查看的类别与案例。小组、标签重叠和区间波动限制了排名解释；区间是否重叠本身也不是两组差异检验。

## 6. 任务3：完整主线过程与相邻区间

### 6.1 自动案例与手动选择

保留原自动入口：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py trajectory
```

它处理198款全量明细，再从至少6节点、同主类型/结局口径、节点数差<=2、全程差<=3个百分点的63对候选中，按既有差异规则挑最多三对不复用游戏，生成固定08～09。自动规则用于寻找有对照价值的案例，不代表一般游戏都必须满足这些条件。

手动选择五款，默认按2＋2＋1分组：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py trajectory --games 1593500 "Far Cry 3" "Hollow Knight" 489830 "Little Nightmares"
```

| 改变方式 | 五款的结果 |
|---|---|
| 加`--games-per-group 5` | 5款同组 |
| 加`--games-per-group 3` | 3＋2 |
| 只加`--groups 2`或`--group-count 2` | 尽量均分3＋2 |
| 加`--games-per-group 2 --groups 3` | 2＋2＋1，两参数一致 |
| 加`--games-per-group 2 --groups 2` | 报错，实际应为3组，不丢弃第5款 |

每组1～5款，跨组总选择不超过既有198款；按输入顺序分组。支持与任务1相同的三种互斥选择参数；用`trajectory --list-games`列出appid/name_en/name_zh。单款中文示例：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py trajectory --game-names "机械迷城"
```

手动选择不套自动案例的六节点、同类型等条件。两节点游戏仍出图，但只描述首末一个区间；不能据此判断内部哪一章出现变化。分组参数必须搭配手动选择；`--view`只用于任务1，任务3每组都输出两种图。

### 6.2 图08：完整节点曲线

横轴`(序号-1)/(节点数-1)`归一到0～100%，纵轴为每个节点覆盖/本游戏首覆盖，起点均为100%。各游戏节点数可以不同，点的位置不代表相同剧情或相同游玩时间；连线仅连接实际节点，不补造中间观测。

先看曲线在哪个节点区间下降，再看全程终点，最后核对图例/卡片中的原始首覆盖。粗线标最早最大相对降幅区间，并列在CSV中完整保留。完整成就展示名可从节点/区间明细查看。

当前自动案例中，Splinter Cell Blacklist与Dead Cells均11节点，全程约43.75%/43.80%，最大相对差距却分别位于1→2与10→11。它直观说明“相近的最终比例可以来自不同过程”，不说明已经找到了具体设计原因。

### 6.3 图09：相邻区间

| 指标 | 公式 | 读法 |
|---|---|---|
| 相邻推进比 | 后节点覆盖 / 前节点覆盖 | 柱越低，两个标注节点间的相对差距越大 |
| 相对降幅 | 1-相邻推进比 | 相对于前节点覆盖的差距 |
| 原始覆盖差 | 100×(前覆盖-后覆盖) | 以百分点表达绝对差距 |

例如80%→60%与20%→15%的推进比都是75%，相对降幅都是25%，但原始覆盖差分别20和5个百分点。因而要把柱高与注释的百分点差一起看。

每款一个独立面板，横轴是该游戏自己的节点序号，橙色包括所有并列最大相对降幅区间；不同游戏的第3段不自动代表同一阶段。缺失分母留空、不跨节点；反向跳跃保留标记和原值，不截断。相邻比值全部可算时，其乘积等于首末全程比。

意义是从“结果高低”走向“差异发生的位置”。章节跨度、节点密度、分支与模型语义仍需结合文本解释；不能由一段较低的柱直接认定Boss或剧情导致玩家流失。

### 6.4 输出与网页复用

1～5款及余数组示例见[自选图集](../analysis/T1Core/figures/trajectory_comparisons/README.md)。每个实际组保存两组PNG/SVG，图片位于figures/trajectory_comparisons/分组摘要，数据位于output/trajectory_comparisons/同摘要；不覆盖固定01～15。同一有序AppID及实际分组重跑覆盖自身产物。

[compare_trajectory.py](../analysis/T1Core/compare_trajectory.py)中的`query_trajectory(selectors, kind="mixed", games_per_group=None, group_count=None)`只返回结构化数据，不画图、不写文件。已有导出包还保存data.json和selected_nodes/selected_profiles/selected_adjacent三个CSV，包含中英文名称、节点原位置、区间与来源。当前尚无HTTP接口，函数的SQLite/快照依赖见DEPLOY。

## 7. 任务4：内容参考长度、游玩时长与推进

### 7.1 三种HLTB口径与固定69款

| 字段 | 本项目显示名称 | 含义 |
|---|---|---|
| RAWG playtime | 用户平均游玩时长 | 按负责人确认纳入分析的研究口径，小时 |
| HLTB main_hours | 主线参考耗时 | 主线内容的参考投入，小时 |
| HLTB extra_hours | 主线＋支线参考耗时 | Main + Extras，含额外内容，不仅限剧情支线 |
| HLTB completionist_hours | 全收集参考耗时 | Completionist完整游玩参考，不等于Steam全成就耗时 |

两类来源并未做玩家匹配，不能声称它们统计了同一批玩家。三图13～15的69款均有三类正值HLTB耗时，原游戏与推进值完全相同。69款是有效数据交集，不推广为全部1000款或全部Steam。

### 7.2 出图命令

生成10～13：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/run.py duration
```

补充14～15，保持原10～13产物不变：

```powershell
uv --cache-dir analysis/T1Core/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T1Core/analyze_duration_references.py
```

这两个Python入口均为固定样本分析，没有新增按1～5款筛选时长的CLI参数。WEB已独立实现保留69款背景、选择高亮和三种参考耗时切换，直接读取已存结果，不调用这两条命令重跑统计。

### 7.3 图10～12怎么看

| 图 | 横纵轴/编码 | 推荐读法 |
|---|---|---|
| [10](../analysis/T1Core/figures/10_time_comparison.png) | x=主线参考耗时，y=平均游玩时长，颜色=全程推进比；斜线y=x | 看实际平均投入与参考长度的相对位置，再观察颜色；斜线上方仅表示两个统计量前者较大，不确认通关 |
| [11](../analysis/T1Core/figures/11_length_progress.png) | x=主线参考耗时，三个面板y=前/后/全程推进比 | 内容参考长度与哪个阶段的推进更有关联？较长游戏是否仍有高推进的例外？ |
| [12](../analysis/T1Core/figures/12_playtime_progress.png) | x=平均游玩时长，三个面板y同11 | 平均投入较多的游戏是否对应更深主线推进？与参考长度的关系是否相同？ |

每点是一款游戏，不是一个玩家。Spearman衡量游戏之间的秩关联，接近+1/-1表示较一致的同向/反向排序，接近0表示较弱的单调关联，不表示解释了多少比例的玩家行为。图左上角给69款的系数与2000次整行游戏重采样区间，种子42；RAWG整数小时的并列值保留，不人为抖动后再计算。

### 7.4 图13～15：三种时长比

三个横轴依次是R_main=playtime/main_hours、R_extra=playtime/extra_hours、R_completionist=playtime/completionist_hours；纵轴始终是同一个全程推进比p_f/p_s。R=0.6表示两个游戏级时长统计量之比为0.6，不表示某个玩家完成了60%内容。

| 图 | 分母 | R<1 / R>=1 | 与全程推进的Spearman及95%重采样区间 |
|---|---|---|---|
| [13](../analysis/T1Core/figures/13_time_ratio.png) | 主线 | 53 / 16 | +0.652［+0.462，+0.794］ |
| [14](../analysis/T1Core/figures/14_extra_time_ratio.png) | 主线＋支线 | 64 / 5 | +0.652［+0.457，+0.805］ |
| [15](../analysis/T1Core/figures/15_completionist_time_ratio.png) | 全收集 | 67 / 2 | +0.630［+0.442，+0.779］ |

竖线R=1是时长相等参考，横点线是69款全程比中位数。右上表示相对参考投入较高、主线推进也高；右下表示时长比高但主线推进低；左上表示时长比低但主线推进较高；左下表示两项都较低。这些位置用来寻找待解释案例，不能直接命名为“忠诚玩家”“通关后投入”或“设计失败”。

每象限按|log2(R)|最大选一例，同分再按推进偏离中位数和AppID排序，是刻意挑出的探索性极端案例。图15右下象限当前0款，明确留空；不为了凑案例修改阈值。

三种分母回答不同参照尺度下的相对投入问题。切换分母只改变同一游戏横坐标，纵坐标不变；图14/15纵轴仍是主线推进，不是支线或全收集完成率。相关系数相近不证明三种指标等价，也不能据此宣布哪种指标更准确。

### 7.5 当前观察如何讲解

当前69款中，主线参考耗时与全程推进比相关约-0.364，RAWG平均游玩时长与全程推进比约+0.289，后者95%重采样区间约[+0.041,+0.511]。它说明“内容参考长度”和“平均投入”并非相同观测维度，需要分开展示。

时长比与主线推进存在正向秩关联，但它包含HLTB分母，也会受到游戏样本构成影响；没有控制其他属性或识别玩家个体行为。可写“当前样本中观察到关联”，不能写“缩短游戏就能提高留存”。完整数值见[时长报告](../analysis/T1Core/output/duration_analysis/report.md)与[参考耗时补充报告](../analysis/T1Core/output/duration_references/report.md)。

## 8. 任务5：口碑与主线推进

### 8.1 做了什么，为什么需要单独分析

口碑描述评论者的认可，推进描述已标注成就节点的聚合覆盖。高评价不自动意味着主线推进高，两者并置可以寻找“广受认可但首末差距大”或“评价一般但节点推进较高”的例外；不能把这些现象直接解释成忠诚度或因果。

全部子方向都先要求完整且不同的首/中/末三节点和有效阶段比：198款中183款合格，15款两节点不参与。Steam好评率来自WWH games.payload的positive/(positive+negative)，不是LYX旧库的review_percent；媒体分和RAWG玩家评分来自同一payload.rawg。Steam183款有效、媒体142款、RAWG正值174款；跨评分比较固定三者共同142款，不让每个面板自行换样本。

评分基于冻结快照，叠加2026-10-20用户确认的两款评分更新；不是统一时点评分。RAWG的4个NULL和5个零分分开保存，零分不当作真实低评价；共同142款RAWG评分人数均≥50。HLTB主线正值68款仅用于相近长度案例，不把主分析收缩到68或69款。

### 8.2 运行与1～5款选择

以下从result/LYX运行，默认计算完整统计和探索、生成16～18图：

```powershell
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation
```

选择观察对象，背景和统计仍为183/142款：

```powershell
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --games 367520 "God of War" "艾尔登法环" 379720 "Raft"
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --appids 1245620 367520
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --game-names "Hollow Knight" "艾尔登法环"
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --list-games
```

--games、--appids、--game-names互斥，选择1～5款，名称解析和重复/歧义保护沿用T1；--list-games只读列出198款及任务资格，不出图。CLI没有--output。默认数值表在T2Sum/output/reputation，图在T2Sum/figures；自选另存output/selections/有序选择摘要及其figures，相同选择重跑覆盖自身结果。选择会重跑固定全量统计及绘图，适合离线准备；网页不能每次点击就执行这条命令。

### 8.3 图16～18分别怎么看

| 图 | 比较内容 | 推荐读法 |
|---|---|---|
| [16 四象限](../analysis/T2Sum/figures/16_reputation_quadrants.png) | x=Steam好评率，y=全程推进；两条样本中位线划分183款 | 先看原始坐标，再看所属区域；“高/低”仅相对样本中位数，不是好坏定级 |
| [17 三阶段](../analysis/T2Sum/figures/17_reputation_stages.png) | 同183款的好评率与前段、后段、全程推进 | 对照三个阶段的秩关联和区间，看关联是否集中于某段；不是玩家随时间变化的轨迹 |
| [18 三评分](../analysis/T2Sum/figures/18_rating_sources.png) | 固定共同142款，Steam/Metacritic/RAWG分别与阶段推进对照 | 各自用原单位，看同样本的Spearman与成对系数差；不能直接比较横轴斜率或把三个分数相加 |

图16中位分界为好评91.0575%、全程32.6203%，等于中位线归高组，四组50/42/42/49款。案例按两轴百分位偏离选取，是刻意挑出的探索例子，不一定具有典型性。

Steam183款前/后/全程Spearman为+0.255/+0.108/+0.164；共同142款全程对应Steam+0.140、媒体+0.239、RAWG+0.295。同是Steam出现两个全程系数，是因为183与142的样本不同，不能混写成一项指标变化。数值表示游戏级单调关联，不是解释了多少玩家行为，也不能仅凭系数大小宣布某来源更准确。

统计为游戏等权，整行Bootstrap 2000次、种子42，重采样后重新计算平均秩。共同142款的评分系数差使用同轮抽样，完整9行差值区间保留；区间不代表玩家级误差。相近长度案例要求同主类型/结局且HLTB比≤1.25，99对候选中选3对，不是随机实验。

### 8.4 多标签共性和探索排名能说明什么

图16的每个象限按完整gameplay多标签统计，分母是象限内游戏数；一款可贡献多个标签，不能相加当游戏总量。与全183款背景或区域外成员对照占比，区分“这个组很多”与“相对总体更集中”。theme/presentation/player_mode自由文本原样保存，不假定近义词已经归并。

图17后段右上区域另定义为好评≥90%、后段推进≥80%，共28款，其中解谜19款（67.9%），背景38/183（20.8%）。这是描述性富集，不证明解谜导致后段推进高；它与图16的样本中位四象限不是同一分界。Singleplayer在此区域100%，总体也有99.5%，因此虽常见却缺少区分度。另存9组边界对照供检查阈值依赖。

探索排序把好评与全程推进的平均秩百分位50/50合成位置分，另存25/75和75/25对照。前五中The Room系列占三款，提示系列聚集；末端并列与节点语义限制同样留档。这个位置分不是六项任务共同的“粘性总分”，也不等于游戏质量最好/最差。具体榜单和原始节点文字见[口碑报告](../analysis/T2Sum/output/reputation/report.md)。

### 8.5 输出表和选择状态

| 文件，均位于T2Sum/output/reputation | 用来做什么 |
|---|---|
| reputation_eligibility.csv / reputation_cohort.csv / rating_common.csv | 198资格台账、183主明细、共同142款；保留原值、评分状态与抓取时间 |
| score_coverage.csv / score_summary.csv | 覆盖和分布，防止把缺失评分补零 |
| reputation_correlations.csv / correlation_differences.csv | 12项主关联及9项共同样本评分差 |
| sensitivity_correlations.csv | 单一start170、统一结局107、多结局76的对照 |
| reputation_quadrants.csv / quadrant_cases.csv | 分界、象限归属与预置案例 |
| matched_candidates.csv / matched_cases.csv | 99对匹配候选和3对案例 |
| exploration_*.csv | 10张多标签、文本标签、共现、边界、排序、权重和节点原文等明细 |
| data.json / manifest.json / report.md | 完整背景与统计、来源和指纹、解释报告 |

自选状态分三类：available_all_panels可在全部图定位；available_steam_only只在16/17定位，18坚持共同142款；incomplete_three_point保留原因而不画假点。上述五款示例中Hollow Knight和艾尔登法环属于第一类，God of War补齐后属于第一类，Raft缺媒体评分属第二类，DOOM只有两节点属第三类。某个评分有值也不能临时加入18的某一面板，破坏共同样本。

## 9. 任务6：玩法多标签下的同类参照

### 9.1 研究问题与匹配规则

绝对推进较低的游戏，在相近玩法和结局结构的游戏中可能并不低。任务6给每个目标建立“其他相近游戏”的参照，再比较前/后/全程实际值；它补充总体相关的解释，不是预测模型或质量排行榜。

目标固定183款完整三节点。主参照使用完整gameplay标签的Jaccard≥0.5，去掉other/uncertain后计算交并集，结局unified/multi标记相同，排除自身；每款参照等权。选择参照不看推进值，不以结果挑同伴；仍不意味着排除了所有混杂，标签和节点跨度也并不完全等价。

| 条件 | 有资格目标 | 至少5参照可比较 | 至少10参照 |
|---|---:|---:|---:|
| 主口径Jaccard≥0.5 | 183 | 181 | 160 |
| Jaccard≥0.4 | 183 | 182 | 175 |
| Jaccard≥0.6 | 183 | 157 | 120 |
| 主口径＋Steam好评差≤10个百分点 | 183 | 165 | 138 |
| 主口径＋HLTB主线时长比≤2 | 68 | 46 | 33 |

五种条件各保留183行，共915行；时长条件115款缺目标时长另记，68款中22款参照不足。五条件是分开的对照，不是全部叠加。时长比≤2用于组成群体，和任务5成对案例的≤1.25用途不同。

### 9.2 命令、前置关系和选择

默认先有任务5默认结果，再生成任务6：

```powershell
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --games "Hollow Knight" "艾尔登法环" 379720 397950 861650
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --appids 1245620 367520
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --game-names "Emily is Away" "Sanfu"
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --list-games
```

三种选择互斥、1～5款，--list-games需已有默认benchmark，列出198款的三节点/参照状态，不出图。默认输出output/benchmark及figures/19～21；自选输出output/benchmark_selections/摘要及其figures。CLI没有--output。自选依然计算完整183目标及五条件，图19背景仍181，不只计算选择对象。

任务6绑定默认任务5的manifest/data指纹；**重新生成默认reputation后，应再生成默认benchmark**，即使数值没变，新的来源manifest也可能使旧任务6查询拒绝。手动reputation选择输出不能替代默认上游。刷新T1底表时也需按依赖顺序更新下游，不能绕过来源校验。

### 9.3 指标怎么理解

| 指标 | 公式/定义 | 展示单位 |
|---|---|---|
| reference_q1/median/q3 | 参照群体各阶段推进值的四分位数/中位数 | 比例展示百分比 |
| delta | 目标实际推进−参照中位数 | 内部比例，乘100显示百分点；不是相对提升百分数 |
| peer_percentile | (低于目标的参照数＋0.5×并列数)/参照数 | 0～1或百分位位置，不是准确概率 |
| peer_n | 当前条件下其他游戏的数量 | 款，不是玩家数 |

至少5个参照才计算比较值，否则留空。三阶段用同一名单，各自求中位数；三个参照中位数不必满足前×后=全程，阶段差也不能相加。箱体表示参照游戏之间的四分位分散，不是置信区间。

一个真实例子：Hollow Knight实际全程34.22%，34款主参照中位42.95%，差为−8.72个百分点，参照内百分位约23.53%。这描述模型节点口径下的相对位置，不证明游戏粘性差。艾尔登法环实际54.00%，46款参照中位38.79%，差＋15.21个百分点；不同目标的参照名单不同，不能把这两个差简单当作同一条排名尺度。

### 9.4 图19～21逐图读法

| 图 | 看什么 | 可以观察什么 |
|---|---|---|
| [19 同类背景](../analysis/T2Sum/figures/19_peer_benchmark.png) | x=自身参照全程中位数，y=实际全程；虚线y=x，颜色为差值 | 线上方高于自身参照；同时保留绝对推进和参照难易背景，不能称作预测准确度 |
| [20 三阶段差](../analysis/T2Sum/figures/20_peer_stage_gaps.png) | 所选/预置案例前、后、全程各减自身参照中位数 | 相对差距集中在哪个阶段；0是持平参照，不是没有推进 |
| [21 参照分布](../analysis/T2Sum/figures/21_peer_cases.png) | 其他游戏的点/箱体与目标菱形，旁列相近参照和原节点提示 | 目标是否偏离主要参照分布，还是同类本来就很分散；展开完整名单核查可比性 |

主参照181款中91款为正差、90款为负差。对照条件比较共同有效的同一批目标：好评相近条件169款中161款方向一致，时长相近条件46款中42款一致。不能用换过人群的总体中位数冒充同一批游戏的变化，也不能把一致性当因果稳健性或显著性。

### 9.5 不足、案例与产物

DOOM在198款目录内但只有两节点，状态outside_three_point_cohort；Clustertruck主参照4款、Session为0款，状态insufficient_peers，仍可展示自身原值/标签与参照数，但比较中位数、差值和百分位留空，不在图19补零点。时长补充条件还可能missing_target_length。

自动案例要求主参照≥10、全程差绝对值≥10个百分点、Jaccard0.4/0.5/0.6都有效且方向一致，最多3正2负；六项已记录具体语义疑点的目标不自动推荐，但仍保留计算，也可能作为其他目标的参照。未列疑点不代表已人工审核。自动案例中的Pony Island末节点涉及全部秘密，STEINS;GATE中位描述缺失，Final Season末节点仅写Act Three，这些限制必须随案例说明。

| 文件，均位于T2Sum/output/benchmark | 用来做什么 |
|---|---|
| peer_benchmark.csv | 183款主条件统计、原值、差值与语义标记 |
| peer_conditions.csv / peer_membership.csv | 915条件结果、21294条有向参照关系；包含相似度与完整成员 |
| peer_coverage.csv | 五条件的资格、有效和参照数覆盖 |
| benchmark_sensitivity.csv / matched_sensitivity.csv | 逐目标条件变化、共同有效目标的汇总 |
| benchmark_cases.csv / semantic_caveats.csv | 自动核查案例、全183款已知疑点或尚未逐项核验状态 |
| data.json / manifest.json / report.md | 完整离线结果、来源/规则/指纹、解释与原节点文本 |

query_benchmark只读查询已有默认结果，不会重新构建参照；与CLI重算路径不同。原完整data.json约15 MB。已完成的静态网页通过WEB/data_adapter.py只读整理各条件摘要和成员，内嵌后在浏览器按AppID/config筛选，不调用query_benchmark，也不向后端逐次请求。原Python查询与未来HTTP接口的能力边界见[DEPLOY](DEPLOY.md)。

## 10. 快速使用顺序与核验

只查看结果：先打开[交互简报](../WEB/index.html)，或看[T1图集](../analysis/T1Core/figures/README.md)、[T2图集](../analysis/T2Sum/figures/README.md)及对应report，不需要重跑。网页交互视图提炼核心问题，原21张图通过末尾图集入口保留，不随选择生成新PNG。需要全量刷新时，在来源版本匹配前提下，顺序为T0基线（必要时）→T1 prepare→types/trajectory/duration及参考补图→T2 reputation→benchmark→WEB build→WEB verify。T1 --output只隔离输出，不自动改变下游默认输入路径；不要把试跑输出当作已经替换正式底表。

1. 讲解先说明1000→198→183，时长69、三评分142、主参照181各自的资格条件。
2. 用任务1解释覆盖与阶段比、首节点和位置中位；任务2先交代主类型/多标签，再比较组内汇总。
3. 用任务3说明同全程可以有不同过程；用任务4区分参考长度、平均投入和相对耗时比。
4. 用任务5展示口碑与推进的不同维度，用任务6说明相对同类位置；随时回到节点原文和资格台账。
5. 网页保持固定总体背景＋选择详情，具体布局、能力边界和验收见[DEPLOY](DEPLOY.md)。

2026-10-17已真实运行10条命令覆盖公共准备与五专题，49张CSV与当时交付逐字一致，30张PNG和对应SVG完整，三个只读查询均核验1～5款；两份SQLite和既有结果未变。2026-10-19新增WEB静态交付，核验1～5款联动、分组、固定总体、缺失及桌面/手机容器布局；没有重算原统计。完整WEB记录见[验收说明](../WEB/ACCEPTANCE.md)。原数据附件仍可复用[交接说明](../analysis/delivery/README.md)中的打包入口，运行实录留在本地忽略的delivery/runtime。

所有任务没有合成统一的玩家“粘性总分”，当前未训练回归模型，也没有个人留存/因果识别。输入来源、单位、缺失与语义限制都是结论的一部分。重点案例人工审核已由WWH完成，依据2026-10-17刘宇翔确认；这不等于198款全部逐项人工审核。代码、说明与当前纳入Git的output结果可随仓库交接；SQLite及其他忽略附件按需单独提供，单独演示WEB核心交互不需要数据库。
