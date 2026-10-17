# 刘宇翔模块实验与实现记录

按日汇总已经实现和验证的工作；时间均为北京时间。历史规则仅解释当时结果，当前命令以[PROCESS.md](PROCESS.md)为准，字段与最新覆盖见[DATABASE_LYX.md](DATABASE_LYX.md)。分析验收与两份数据库保留；旧process运行历史已按本轮要求清理。

## 2026-10-17 分析交接审查与处理链路清理

- 审查五个分析专题（任务2～6）及任务1公共底表；两库完整性/外键通过，219项manifest输出指纹一致。只读重算198款指标、类型分组/区间、1543相邻段、65款时长明细、183/140款评分及915组参照结果，未改原数值/图片或数据库。
- 新增analysis/delivery交接核验程序、来源表/结果表/任务总结三张索引表；生成123文件、约40.8 MB本地忽略包，含49张结果CSV、42图和9份源表摘录。说明仅展示与完整复算所需数据的区别，不执行上传或网页部署。
- docs统一：数据获取和DeepSeek契约合入PROCESS；DATABASE拆为DATABASE_LYX和DATABASE_WWH，前1000款迁移说明融入前者；删除重复文档并修复导航。data_plan的研究口径不改。
- 经无活跃进程检查，安全删除process/runtime旧历史、process/old、旧字节码/临时文件、一次性导入和迁移入口。当前只保留5个DeepSeek模块；移除旧prompt缓存兼容及旧schema迁移功能，当前两段prompt内容和版本不变，预算/超时/事务/门槛/保护逻辑不变。
- 保留datacache和failure_data两个活跃累计CSV及全部database/backups；旧运行路径现不可回放。新运行仍建立新的receipt/报告/备份。仅离线plan、help、导入/契约核查，未调用DeepSeek或连接远端；无提交推送。
- 实际结果、文件清单、语义限制与上传选择见[交接审查](../analysis/delivery/AUDIT.md)和[交接说明](../analysis/delivery/README.md)。

## 2026-10-17 分析实施记录

### T2Sum专题6：多标签同类参照基线

- 冻结版本`wwh5-2026-10-13T10:26:09.722887+00:00`，复用183款完整三节点及原模型顺序，主参照为完整gameplay Jaccard≥0.5、同结局类型、排除自身，忽略other/uncertain。相似度精确分数判定、游戏等权，不按推进结果挑参照或按相似度加权。
- 至少5参照有效，主分析181款、其中160款至少10参照；Clustertruck为4、Session: Skate Sim为0，不补零、不自动放宽。相似度0.4/0.6分别182/157款有效，口碑差≤10个百分点165款，主线时长比≤2在68款中46款有效。保存5条件×183＝915行，长度缺失115款与参照不足22款分别标记。
- 前/后/全程分别保存参照中位数、Q1/Q3、实际减参照差、参照内百分位；内部比例0～1、差值展示乘100为百分点，箱体为游戏间分散非置信区间。主参照91款高于、90款低于；条件对照只用共同有效目标交集。口碑165款中161款、长度46款中42款方向一致，方向一致不是因果或显著性证明。
- 自动选最多3正2负核查案例：参照≥10、全程差绝对值≥10pp、相似度0.4/0.5/0.6有效且方向一致，按差/参照数/AppID排序。已有6款具体语义疑点不自动推荐但仍参与计算，参照内疑点数单列；未列疑点不等于人工确认。自动案例附首中末原文，保留Pony Island全部秘密、STEINS;GATE缺中位描述、Final Season末节点只标Act Three等限制，未修订数据库。
- 新增benchmark_data.py、benchmark.py、benchmark_plots.py，run.py增加benchmark分支，任务5入口与产物保留。新增19实际/参照散点、20阶段差、21分布/案例卡，支持1～5款AppID/已有中英文名；手动选择独立保存，query_benchmark只读预计算结果、不重新构建参照，提供198款名称目录和缺失状态供组长接入。未新增HTTP服务或部署网页，没有训练回归模型。
- 输出CSV、JSON、报告和manifest；默认与混合五款手选实际运行，独立核对915组参照成员与三阶段统计、目标排除、精确边界、缺失、1～5款查询和前置保护，见[任务6验收](../analysis/T2Sum/runtime/benchmark_acceptance.json)。两份SQLite、T0/T1、任务5全部输出和01～18图、uv.lock前后指纹一致；git pull已完成同步，没有提交或推送。
- [任务6说明与网页接入](../analysis/T2Sum/BENCHMARK.md)、[结果报告](../analysis/T2Sum/output/benchmark/report.md)、[图集](../analysis/T2Sum/figures/README.md)。data_plan当前六项确认范围均已有产物，专题6止于透明同类基线，回归预测需另行决定。

### 任务5图表探索解读补充

- 负责人确认图号为16号四象限、17号后段推进面板；用原183款、完整gameplay多标签做构成与标签对照，不改样本或数据库。右上区域固定好评≥90%、后段≥80%，28款中解谜19（67.9%），背景38/183（20.8%）；叙事/悬疑/恐怖自由标签作为描述补充，保留模型来源及未合并同义词的限制。
- 四象限：高口碑高推进解谜48.0%；高口碑低推进模拟47.6%、策略33.3%；低口碑高推进动作88.1%；低低策略36.7%、角色扮演59.2%、生存26.5%。每款可归多标签，保存背景/区域外占比、提升倍数及共现组合，不以数量最多代替有区分度的共性。
- 新增9组区域边界、同为高口碑102款对照、解谜/非解谜描述相关；右上区域整体阶段中位数更高，但HLTB只覆盖其中12款，不能据此把全部28款概括为短游戏。Persona 4 Golden后段83.78%、全程4.01%，中末节点描述缺失，保留模型语义疑点，不将高后段等同于高全程。
- 定义口碑与全程推进的等权百分位秩共同表现分，只用于解释案例，不作三平台混合分或游戏质量排名；保留原183款排序、前五/后五、边界并列与25/75、50/50、75/25权重对照。先合并精确平均秩再除以n，避免浮点误差拆散并列。
- 前五包含The Room系列3款、Balatro、Firework；后五末位存在3款并列。原文核验发现Outward全部3条任务线、Sniper Elite 3的100%战役、Dragon's Dogma 2特定模式限制、Balatro一局胜利、Arma中位教程节点等可比性问题；均只读留证，不改变节点或数据库，不把靠后直接解读成游戏差。
- 新增reputation_exploration.py并接入原reputation入口，10张CSV、data.json.exploration、报告及manifest同步生成。完整分析见[T2Sum报告](../analysis/T2Sum/output/reputation/report.md)；来源、口径、复跑与交接见[T2Sum说明](../analysis/T2Sum/README.md)。独立重算标签成员/秩分/并列、核对主统计和数据库/前四项指纹，证据见[探索验收](../analysis/T2Sum/runtime/exploration_acceptance.json)。未提交或推送。

### T2Sum专题5：口碑与主线推进

- 数据版本`wwh5-2026-10-13T10:26:09.722887+00:00`；严格从T1固定198款中选183款完整且不同的首/中/末节点、三项推进比均有效的游戏，排除15款两节点。Steam好评率取借用库SteamSpy正负评价数，183款均有效；媒体140款、RAWG正值173款，三评分交集140款。媒体43款NULL；RAWG5款NULL、5款零，原值/状态保留，不以旧库review_percent混合补值。
- 图16、17固定同183款；图18三个面板固定同140款，均保存PNG/SVG及来源、分组、指标和解释小字。Steam183前/后/全程Spearman为+0.255/+0.108/+0.164；共同140款Steam/媒体/RAWG与全程为+0.125/+0.224/+0.282。全部12项相关、9项成对系数差和区间均留档，不挑显著结果。
- 游戏等权、并列平均秩，整行联合Bootstrap 2000次、种子42；共同140的评分使用同轮抽样。保存单一start 170款、统一结局107款、多结局代理76款对照；共同140款RAWG评分人数均≥50，不再减少样本。四象限中位线91.0575%/32.6203%，四组50/42/42/49款，按百分位秩偏离乘积选4个极端例。
- 只读旧库games_time.main_hours用于补充案例：68款正值HLTB中同主类型、同结局且时长比≤1.25形成99对候选，选3对不重复的口碑/推进反向案例。不是因果配对，不视为任务6模型完成。
- 新增T2Sum独立代码与命令、198款排除台账、183/140底表、CSV、JSON、manifest及完整报告。可选1～5款AppID/已有中英文名，只高亮，背景/中位线/统计不随选择变动；两节点或缺共同评分的选择保留原因，自选输出独立。提供无文件写入Python查询，给组长的网页增补说明在T2Sum/README，未改dashboard或部署网页。
- 真实运行生成三图；独立核对样本、SciPy相关、配对重采样、选择与缺失处理及产物保护，验收证据见[T2Sum运行记录](../analysis/T2Sum/runtime/acceptance.json)。两份SQLite、T0Pre、T1Core（含CSV/原01～15图）与既有uv.lock前后指纹一致。实施前git pull因本地uv.lock已有改动而中止合并，保留原改动，未提交或推送。
- 解释边界：冻结评分与成就覆盖不来自同一个体样本；模型主线与多结局代理继续保留标记；相关与重采样区间不等于真实留存或因果结论。报告及图见[专题5](../analysis/T2Sum/output/reputation/report.md)，复跑及接口见[说明](../analysis/T2Sum/README.md)。

## 2026-10-16

### T1Core使用指南与网页展示交接

- 新增INSTRUCT.md，汇总已完成专题1～4的来源、指标、完整命令、固定与自选输出、逐图读法和可解释结论；用实际类型口径变化、全程相近但过程不同、三类时长比说明研究意义，保留模型节点、聚合比值及观察性关联边界。
- 新增DEPLOY.md面向组长，区分当前CLI/只读Python查询/CSV产物与待开发网页。规划四页签、统一1～5款选择、任务2总体背景和任务3分组；重点明确任务4始终保留65款背景、统计与参考线，选择仅高亮和更新卡片，切参照同步更换横坐标/字段/对应统计，缺失游戏保留选择并提示原因。给出Hollow Knight三个真实坐标与God of War缺RAWG的处理例子。
- 交接内容含当前数据位置、名称索引缺口、离线发布包与只读GET契约建议、比例/小时/百分点转换及页面验收场景；建议接口和发布包均标明尚未实现，不增加HTTP服务、不修改dashboard、不代组长部署。LYX、analysis、T1Core与docs导航同步加入入口。
- 本轮仅新增/更新说明文档，核对代码和本地数据，不重跑分类或分析、不改SQLite/程序/CSV/图表/既有data_plan与DATABASE。按文档命令与当前解析器核对参数，并检查本地链接、示例数值和受保护文件指纹；未提交或推送。

### T1Core专题3补充：自选游戏与可配置分组

- 实现：新增compare_trajectory.py，run.py trajectory接入--games/--appids/--game-names及--list-games。复用既有名称解析、完整节点验证、describe_game相邻计算；只读返回数据的query_trajectory与绘图导出compare分离，后续可由网页薄封装调用，目前未启动HTTP服务或修改公共面板。原trajectory不传游戏选择时仍按原规则生成自动三组案例。
- 分组：每组1～5款、默认2款；显式--games-per-group按输入顺序切分，末组余数保留；只指定--groups/--group-count时尽量均分，前面组多1款。两参数同时声明必须与实际组数一致，矛盾报错，不丢弃选择或补空组。跨组可从固定198款选择，总数最多198；重复、歧义、范围外名称/AppID均拒绝。手动选择不套用自动案例的同类型、至少6节点、结局相同或全程相近条件，15款两节点游戏仍可显示一个首末区间。
- 图与数据：每组输出08完整归一曲线和09逐游戏相邻区间，两类PNG/SVG按有序AppID及实际分组摘要隔离；图片位于figures/trajectory_comparisons，数据位于output/trajectory_comparisons，不覆盖固定01～15。卡片保留原始首覆盖与全程比，粗线标最早最大相对降幅，区间图橙色保留全部并列；缺失和反向值不截断，节点多时仅简化刻度，不减少数据。另存含appid/name_en/name_zh、节点与区间的data.json，以及三张CSV、报告和来源manifest。CSV/数据JSON继续Git忽略，部署时单独交付。
- 真实示例：分别跑通单组1、2、3、4、5款，游戏按God of War、Far Cry 3、Hollow Knight、Skyrim Special Edition、Little Nightmares顺序取前N款；五款默认2＋2＋1及仅指定两组3＋2均有完整产物。另通过机械迷城中英文/AppID解析，实际出图验证机械迷城与仅两节点DOOM的选择。1～5款和两种分组示例均收录自选图集。
- 验证：核对8份数据包的有序选择、分组、节点身份/原下标/解锁率/归一坐标、全部区间比值/差值及JSON/CSV行数，校验程序与产物哈希。覆盖1～5款的各每组款数、按组数均分、余数、6款跨组、两参数一致/冲突、0/负数/越界/空选择/重复/歧义及保留目录等边界；CLI选择、分组别名、清单和错误组合通过。14张活图独立逐点核对曲线与柱高，检查页脚和卡片边界/重叠，两节点提示正确；已查看五款叠加及区间样例，无pytest文件。
- 回归与保护：默认prepare在runtime隔离重跑，原四个底表/报告字节一致；原自动trajectory在隔离目录重跑，三张CSV字节一致、仍198款/1741节点/1543区间/63对候选/3组选中。旧compare也从CLI隔离试跑，compare与trajectory清单均198款。两份数据库、T0Pre、T2Sum、原全部分析结果、固定01～15及共享uv.lock前后指纹一致，无模型、采集或数据库写入，无新增依赖，未提交或推送。
- 证据：[参数与查询函数说明](../analysis/T1Core/README.md)、[1～5款与余数组图集](../analysis/T1Core/figures/trajectory_comparisons/README.md)、[独立核验](../analysis/T1Core/runtime/trajectory_selection_acceptance.json)。仅扩展专题3的选择与展示，不改变原统计样本及指标，不将聚合推进比解释为真实日留存或因果。

### T1Core专题4补充：主线＋支线与全收集时长比

- 需求与实现：按负责人确认，沿用13号图的“时长比×全程推进＋案例”形式，新增14_extra_time_ratio、15_completionist_time_ratio的PNG/SVG。独立入口analyze_duration_references.py，复用既有时长加载、Spearman整行Bootstrap和四象限选例函数；仅替换比值的HLTB分母，不重新生成10～13，原duration命令与产物保持原样。结果独立存output/duration_references。
- 范围与字段：固定同65款及原顺序，逐项校验原duration manifest与来源快照；只读旧本地库games_time.extra_hours、completionist_hours，均65款正值，主线≤主线＋支线≤全收集的顺序异常0。Main + Extras是主线＋额外内容，此处简称主线＋支线；Completionist是完整游玩/全收集参考，不等于Steam全成就耗时。RAWG继续按负责人授权作为平均游玩时长，单位均为小时；不更换游戏、不填缺失、不做类型对照。
- 两图：14横轴playtime/extra_hours，15横轴playtime/completionist_hours，纵轴均为原p_f/p_s；R=1、全程比中位数参考线及坐标风格沿用13。R>=1分别5款、2款；R<1分别60款、63款。底部明确来源、字段、统计与解释；小比值案例保留三位小数，避免显示成0.00。
- 统计观察：14的Spearman ρ=+0.647，95%游戏重采样区间[+0.436,+0.801]；15为+0.617，[+0.398,+0.777]。每款等权，2000次整行游戏重采样、种子42、平均秩处理并列；均有2000个有效重复。相关属于当前65款的描述，不以系数相近认定三种口径等价，不因更换分母而推断内容导致粘性变化。
- 案例：14四象限数量4/1/29/31，按既有规则选The Room Two、Pony Island、Hollow Knight、Spiral Knights；15为2/0/31/32，仅选The Room Two、FTL: Faster Than Light、Spiral Knights，空象限在图中注明0款，不改变阈值补例。纵轴仍为主线推进，不能当作支线/全收集完成率；R>=1也不能确认玩家完成相应内容。
- 验证与保护：真实运行成功。独立只读SQLite核对65款两列原值、比值与原推进指标；使用scipy.stats.spearmanr复算两项系数、4000次重采样相关和全部7个案例规则。活图逐点核对坐标、页脚/案例卡片范围与空象限提示；语法、输出边界、程序/产物哈希通过。两份数据库、原底表与全部旧分析产物、01～13图、T0Pre/T2/T3及共享uv.lock指纹一致。无新依赖、模型/采集请求、数据库写入或Git提交推送。
- 证据：[运行说明](../analysis/T1Core/README.md)、[补充报告](../analysis/T1Core/output/duration_references/report.md)、[14主线＋支线](../analysis/T1Core/figures/14_extra_time_ratio.png)、[15全收集](../analysis/T1Core/figures/15_completionist_time_ratio.png)、[来源与旧产物保护](../analysis/T1Core/output/duration_references/manifest.json)、[独立核验](../analysis/T1Core/runtime/duration_references_acceptance.json)。T1图集现为01～15，不代表已开展data_plan后续六个专题。

### T1Core专题4：65款共同样本的时长与主线推进

- 实现：新增analyze_duration.py及run.py duration入口，复用已核验的198款主线底表和三阶段推进指标；借用快照读取RAWG playtime，只读旧本地库补充HLTB main_hours，以AppID连接。输出独立duration_analysis目录，10～13图集中figures，不重新prepare、不分类、不采集、不修改数据库。按负责人确认，RAWG playtime作为用户平均游玩时长；取消本专题的类型对照、类型分组、类型着色与按类型拟合。
- 固定范围：198款有效主线曲线→183款完整三节点→68款有正值HLTB主线时长→65款同时具备正值RAWG时长，四图均用同一65款。AppID顺序SHA256为41aed4f5c6cfff37d0032fc3bfb3812a8d30b48e3ef0058cab7865cf90a42271。68款的RAWG值与旧本地playtime逐项一致；其中God of War、Call of Duty®: Black Ops II、Resident Evil缺RAWG而排除。全部198款的HLTB情况为正值75、本地未匹配37、NULL85、零值1；保留逐款筛选记录，不把本地未匹配解释为网站无数据，不填补缺失。
- 数据：HLTB主线参考耗时最小/中位/最大0.66/12.13/50.41小时，RAWG平均游玩时长1/6/27小时，整数小时保留并列。R=RAWG/HLTB，中位0.605，R<1为50款、R>=1为15款；时长顺序异常0。R是跨来源游戏级比值，不是个人主线完成度，R>1也不能据此确认通关后投入。
- 统计：每款游戏同等权重，Spearman并列取平均秩；整行游戏联合Bootstrap 2000次、种子42，重新计算每轮秩并报告2.5/97.5百分位区间，常量样本不可计算时记录有效次数。全部10组相关使用65款，各有2000个有效重采样；不以p值筛选结果，不拟合复杂曲线。
- 观察：HLTB主线参考耗时与全程推进比ρ=-0.451，95%重采样区间[-0.670,-0.201]；RAWG平均游玩时长与全程推进比ρ=+0.257，区间[+0.001,+0.506]，下界接近零；R与全程推进比ρ=+0.641，区间[+0.441,+0.796]。两类时长本身ρ=+0.358，区间[+0.098,+0.569]。这些是当前游戏样本的关联，不能说明内容长度造成流失，也不能凭区间重叠判断两种相关是否不同。
- 分组补充：HLTB固定(0,5]、(5,15]、(15,30]、>30小时，分别10/30/18/7款；全程推进比中位数54.9%/42.1%/26.1%/28.4%。保存三阶段中位数、线性四分位数和n>=10组的中位数区间，7款组不生成区间，不根据结果搜索分界。
- 图表：10两类时长散点对照，颜色为全程推进比；11主线参考耗时对三个阶段推进比；12平均游玩时长对三个阶段推进比；13时长比与全程推进及四象限案例。图名明确变量，底部四行注明同65款来源链、字段与小时单位、统计和解释边界，无组员姓名。R=1及全程比中位数仅作参考线，不是通关门槛。
- 案例：按R=1与全程比样本中位数分四象限，每象限取|log2(R)|最大者，同分按全程比偏离和AppID排序；选出TEKKEN 7、Pony Island、Deus Ex: Human Revolution - Director's Cut、Spiral Knights，所属象限分别12/3/21/29款。属于透明规则挑出的探索性极端案例，不代表典型游戏，不以案例反推玩家行为。
- 验证：真实duration运行成功；独立只读查询两份SQLite核对65款来源和原三阶段指标，使用scipy.stats.spearmanr复算全部10组系数及20,000次重采样相关，独立核对全部分组四分位数、区间、四象限规则，均通过。检查缺失、零值、负数、非有限值、布尔值、常量相关及输出越界；活图逐点核对四图坐标、页脚和案例卡片范围，未新增pytest文件。默认prepare在runtime隔离目录回归、compare仍列198款，duration拒绝compare专用选择参数。
- 保护与证据：两份数据库、T0Pre/T2/T3、原全部output底表与报告、01～09图片及共享uv.lock前后指纹一致；只新增专题4产物并同步LYX说明。无新依赖、API调用或数据库写入，未提交或推送。见[专题4运行说明](../analysis/T1Core/README.md#专题4主线参考耗时平均游玩时长与推进)、[完整报告](../analysis/T1Core/output/duration_analysis/report.md)、[图集](../analysis/T1Core/figures/README.md)、[来源与保护记录](../analysis/T1Core/output/duration_analysis/manifest.json)、[独立核验](../analysis/T1Core/runtime/duration_acceptance.json)。当前data_plan任务1～4完成，T2Depth/T3Sum其余六项按需开展。

### T1Core专题3：完整主线过程与相邻区间

- 实现：新增analyze_trajectory.py及run.py trajectory入口，直接验证并读取既有game_metrics/checkpoints/manifest，沿原文件和数组顺序形成相邻区间；不按解锁率或id排序、不使用备选结局、不重新prepare或写数据库。输出独立trajectory_analysis子目录，08/09图集中figures，自定义输出的图隔离到其figures目录。
- 范围：198款全部保留、1741个有效序列节点、1543段相邻区间；15款两节点游戏保留一个区间，不推断内部形态。至少3/4/6节点分别183/172/133款。当前零分母区间0、反向区间0。
- 指标：相邻推进比=后/前，相对降幅=1-比值，原始覆盖差=100×(前-后)个百分点；节点曲线除以各自首覆盖归一化。每款分别保存最大相对降幅、最大百分点差、所有并列标记和最早代表位置；集中度仅在非反向且首末有正差时计算，首末相同留空。全部可算相邻比值乘积与原全程比一致。
- 案例：至少6节点、同主类型和结局口径、节点数差<=2、全程差<=3个百分点，共63对；按最大相对差距中点位置差、集中度差降序，再按全程差/节点差/AppID升序，贪心取3组不复用游戏。完整候选、排序与选中组号保存，不自动放宽条件。三个展示组均为动作/统一结局，不宣称覆盖其他类型。
- 真实样例：235600 Splinter Cell Blacklist与588650 Dead Cells（各11节点），全程43.75%/43.80%，差0.05个百分点，最大相对差距在1→2/10→11；223470 POSTAL 2与2054970 Dragon's Dogma 2（7/6节点），全程17.14%/18.84%；242680 Nuclear Throne与368340 CrossCode（9/10节点），全程23.74%/20.87%。完整成就展示名、阶段、相对和百分点差均在报告中。
- 图表：08完整主线覆盖曲线，起点各自归一100%，横轴为节点位置而非时间，粗线标最早最大相对降幅；图例同时给原始首覆盖，保留不同基准差异。09每款一个面板，每柱一段真实相邻区间，橙色含并列最大相对降幅，轴下给对应百分点差。沿用中性标题、四行来源与口径说明；修正公式字体不支持的Unicode减号，PNG/SVG无缺字警告。
- 验证：真实命令运行通过，独立逐行核对1543段身份/顺序/比值/降幅/百分点差，核对198款乘积、最大值、并列和集中度；复算全部63对条件与排序、3组不重复。离线检查零分子/零分母、平坦曲线、反向值保留、最大值并列与缺失节点不得桥接，均通过；未新增pytest文件。活图核查08全部节点坐标和09柱高，页脚、图例及节点注释不重叠。
- 回归与保护：默认prepare在runtime隔离目录运行，原四个底表/报告字节一致；compare列表仍为198款，trajectory拒绝compare专用选择参数。两份数据库、T0Pre/T2/T3、原全部output结果、01～07图片和共享uv.lock前后指纹相同（图集README按授权更新）。无新依赖、API或数据库写入，未提交或推送。
- 证据：[任务3说明](../analysis/T1Core/README.md#专题3完整主线过程与相邻区间)、[报告](../analysis/T1Core/output/trajectory_analysis/report.md)、[08完整曲线](../analysis/T1Core/figures/08_story_curves.png)、[09相邻区间](../analysis/T1Core/figures/09_adjacent_progress.png)、[来源与旧图保护](../analysis/T1Core/output/trajectory_analysis/manifest.json)、[独立核验](../analysis/T1Core/runtime/trajectory_acceptance.json)。结果描述聚合节点覆盖，不能认定玩家流失或具体设计因果；下一项为专题4参考时长分析。

### T1图名与图下注释微调

- 保留既有口径：02～04继续按gameplay首标签作互斥主类型分组，05～06继续使用完整玩法多标签；固定198款、主分析183款、各组成员、n阈值、排序、指标和Bootstrap参数不变。此次仅修改绘图函数、共享页脚和图集说明，不修改统计函数或数据库。
- 图名直接区分主类型/完整多标签，并注明节点覆盖、阶段推进或游戏分布与区间；01、07分别注明所选游戏对比与同主类型案例对照。七组PNG/SVG原编号与文件名保持不变。
- 注释集中图底四行：一行完整样本来源链、分组或选样规则、数值定义、解释或区间规则。明确n是游戏数、多标签组间重叠、逐游戏比值后汇总，以及中位节点和代表结局含义；不再在图上方放样本说明。
- compare与types真实重跑，目视检查热力图、分布与案例等版式；来源和数字文件前后哈希相同。最新核验见[图面说明核验](../analysis/T1Core/runtime/figure_labels_acceptance.json)。两份数据库与T0Pre未改，无依赖或API变动，未提交或推送。

### 规划重排与T1图集整理

- 按负责人要求移除data_plan原第3项及其他专题中的相关属性和比较安排；既有数据库字段和值完全保留。本次不修改数据库结构或数据。已实施的推进指标计算列为新第1项，类型比较改为第2项，过程比较改为第3项，原第4～10项顺序不变；当前已完成2项，其余8项待开展。下方旧记录中的“专题1类型分析”是当时编号，对应现任务2。
- 新增plot_files.py集中管理命名与目录；T1默认样例和类型图共7组、14个PNG/SVG统一迁入figures：01_game_stages、02_type_coverage、03_type_progress、04_type_distribution、05_tag_coverage、06_tag_progress、07_stage_cases。自定义选择附短摘要与view，避免长文件名；自定义输出的图隔离到其figures目录。
- 图面去除组员姓名缩写，改为固定分析样本、主类型分组等中性表述；数据来源归属和历史审计仍保留在说明及来源JSON，不修改统计口径。默认compare与types已真实重跑，所有图和报告引用、图集索引及哈希路径随之更新；CSV/JSON仍在原目录。
- 核验：图集SVG可见文本无人名标注、PNG实际查看；七组PNG/SVG完整，旧默认输出目录不再残留图片。两份数据库、T0Pre及既有指标/专题/对比CSV与旧指标manifest前后SHA256一致；共享uv.lock保持原样。数值不变，仅输出图面、组织、链接与实施编号变化。验证记录见[图集整理核验](../analysis/T1Core/runtime/figure_cleanup_acceptance.json)，索引见[T1图集](../analysis/T1Core/figures/README.md)。未提交或推送。

### T1Core专题1：玩法类型与阶段推进

- 实现：新增analyze_types.py及run.py types入口。复用现有game_metrics/checkpoints/manifest，不重新prepare或调用模型；输出限定T1Core独立子目录，拒绝覆盖底表目录和comparisons。主类型取WWH gameplay[0]，完整玩法另作重叠多标签补充，组内AppID去重。
- 范围：固定198款；183款三节点用于同批游戏的六指标阶段比较，15款在全范围补充中保留首末和全程、中间留空。起点对照170款、统一结局三节点107款、多结局三节点76款。主分析主类型数量为动作90、RPG22、冒险21、模拟16、平台跳跃13、策略9、解谜7、生存2、竞速/节奏/体育各1。
- 统计：游戏级中位数与线性插值四分位数；n>=5进入主图，n>=10提供2000次、种子42的整行游戏联合Bootstrap中位数95%百分位区间；每个分组由固定SHA256派生子流。配对的后段减前段先逐游戏计算，再汇总，不把两列中位数相减。区间仅表示当前游戏集合的重采样波动，不是玩家级误差。
- 产物：336行group_summary、881行唯一成员关系（主类型198、完整标签683）、560行起点/结局/标签口径对照、3组不重复游戏案例。生成主类型覆盖与推进热力图、组内分布/中位数区间、完整标签覆盖与推进图、案例柱状图，共6张PNG和6张SVG；明细和manifest继续Git忽略。
- 观察：主类型183款中，冒险类前/后段中位数69.3%/86.5%，模拟类48.9%/32.7%。解谜全程中位数73.3%但只有7款；改用完整标签后解谜为38款、46.7%，冒险由21款58.8%变为146款35.9%。成员构成变化明显，不能将主类型排名直接认定为稳定类型差异或因果结论。
- 案例：同主类型、全程差<=3个百分点，按前后段绝对差之和排序，选三组不复用游戏；规则与所有数值落盘。极端阶段反差保留为核查章节跨度和模型节点语义的线索，不直接解释为设计问题。分组柱状图不把指标连接成时间轨迹。
- 验证：真实types运行成功，逐行独立核对全部汇总和对照CSV的样本数、中位数、四分位数、缺失与差值；独立复算动作组整行Bootstrap区间；热力图SVG文本与CSV一致。成员去重、小样本规则、案例源值、输出与程序哈希、输出边界和语法通过。旧默认prepare在runtime隔离目录回归，四个底表/报告与现有生产产物字节一致；compare清单入口仍返回198款。已查看三张主图、多标签推进图和修正后的案例图。
- 保护：数据库、T0Pre、T2/T3及既有指标底表前后指纹一致，无新依赖、采集、API请求或数据库写入。价格、时长、口碑与全节点过程专题未开展，不提交或推送。
- 证据：[专题说明](../analysis/T1Core/README.md#专题2类型与阶段差异)、[专题报告](../analysis/T1Core/output/type_analysis/report.md)、[来源和保护核验](../analysis/T1Core/output/type_analysis/manifest.json)、[独立数据核验](../analysis/T1Core/runtime/type_analysis_acceptance.json)。

### T1Core最多五款游戏的多阶段柱状对比

- 实现：新增compare_games.py，run.py保留prepare默认行为并增加compare。支持--appids、--game-names、--games混合选择，最多五款，按输入顺序绘图；--list-games只列198款清单。名称优先精确匹配，再允许唯一片段，歧义/重复/范围外/超过五款均拒绝，不扩充研究范围。
- 图表：默认both上下两图，上图p_s/p_m/p_f原始覆盖，下图前段/后段/全程推进比；coverage/progress可分别单图。柱顶百分比，缺少中位节点显示缺失，不补0；单图标题与说明预留独立空间。输出PNG、SVG、实际绘图长表CSV与来源JSON，均位于T1Core；不重新prepare或修改底表。
- 示例：1593500 God of War、220240 Far Cry 3、367520 Hollow Knight、489830 Skyrim Special Edition、424840 Little Nightmares。AppID、名称与混合三种入口真实绘图，选择顺序和30个绘图数值与指标表完全一致。
- 验证：DOOM两节点缺失示例、单图coverage/progress、名称规范化与唯一片段、歧义/重复/六款/范围外/空选择均通过；已查看五款、两节点和单图PNG。原prepare通过自定义输出目录回归，198款覆盖不变，原生产底表没有被覆盖。
- 保护：绘图前后核对CSV/manifest来源及数据库/T0Pre保护文件指纹，所有输入保持不变，无模型/网络请求、无数据库写入。图表读取WWH既有名称，不补造中文翻译。用户看到的比值仍是主线聚合指标，不解释成实际日留存。
- 文件：[运行与参数](../analysis/T1Core/README.md#选择最多五款游戏画对比图)、[五款示例图](../analysis/T1Core/figures/01_game_stages.png)、[选择与绘图核验](../analysis/T1Core/runtime/comparison_acceptance.json)。CSV与来源JSON保持Git忽略；未提交或推送。

### T1Core固定198款的数组位置中位指标准备

- 范围与来源：复用T0Pre默认highest基线的198个AppID，原排名顺序不变；清单SHA256为26b6a452b72e9466bced793868e7af8bd01c15980cf9bb4e27ab0799316f477b。源数据库版本wwh5-2026-10-13T10:26:09.722887+00:00，模型deepseek-flash、提示词wwh5-ds-v3。只查询这198款的WWH记录，逐款重算曲线并与T0Pre完全一致；不重新分析或分类1000款。
- 选点：WWH有效公共节点保持原数组顺序，多end沿用最高解锁率、并列取先出现者；有效序列取首、位置中位、代表结局，偶数取靠前中点。不按stage=middle或完成率选中间，不新增至少6节点或人工标注前置，保留全部198款。
- 实现：T1Core/run.py与prepare_metrics.py，输出cohort.csv、checkpoints.csv、game_metrics.csv、report.md及manifest.json。输入和T0Pre只读，输出限定T1Core，CSV/manifest/runtime保持Git忽略，不写任何数据库。
- 结果：183款完整三节点，15款仅首末节点、中间指标留空；统一结局120款、多结局78款；无start9款、多个start7款；代表结局最高解锁率并列6款。节点明细1,824行，代表结局处理后序列1,741项；比值越界异常0。唯一首位start且三节点齐全的170款仅作为对照标记，不替代主范围。
- 指标：内部0～1；p_s/p_m/p_f记录首中末覆盖，前段p_m/p_s、后段p_f/p_m、全程p_f/p_s。保留WWH原基准与结局比例供核对。缺失/非正分母不补零，有效零分子保留；多结局和模型前置关系保留标记。
- 验证：从LYX及T1Core目录真实运行通过。核验全部CSV节点的原数组id、名称和原始解锁率；偶数靠前中位、奇数中位、双节点缺失、并列结局、零分母/零分子、输出越界和语法检查均通过，无新增pytest或测试文件。两份数据库、T0Pre核心文件与T2/T3文件前后指纹一致，借用库SHA256与T0Pre已核验源快照一致，未调用API。
- 证据：[说明](../analysis/T1Core/README.md)、[报告](../analysis/T1Core/output/report.md)、[来源与保护核验](../analysis/T1Core/output/manifest.json)、[CSV及边界核验](../analysis/T1Core/runtime/acceptance.json)。这只完成指标准备，不代表类型、时长、价格或口碑专题已开展；不提交或推送。

### WWH基线复现迁入analysis/T0Pre

- 目录：将WWH复现入口、wwh_replay包、说明、来源指纹、历史对照、三张图、报告、metrics/verification及runtime/current_start整体迁到T0Pre。analysis根目录只保留阶段导航与T0Pre、T1Core、T2Depth、T3Sum；后三目录文件前后完全一致，本次不开展后续专题。
- 引用：修正storage中LYX根目录定位与T0Pre输出边界，数据库仍指向原NewDB/wwh5.sqlite3和database/achievements.sqlite。同步运行命令、README、data_plan阶段目录和文档导航；WWH原项目已经将源码/说明移到src/docs，参考链接相应修正，初次来源哈希保留。
- 重跑：从LYX目录运行highest，198条曲线、183款配对，Spearman=0.6449350317486812；从T0Pre目录运行start，182条曲线、168款配对，Spearman=0.6446329517422187。两种模式的全部metrics均与迁移前一致，默认三张PNG与report.md文件哈希也一致。
- 数据保护：两份数据库的SHA256与大小在整个迁移前后一致，运行内指纹核验通过；统计核心analysis.py与params.py字节保持不变，连接仍为mode=ro/query_only，不追加数据库分析记录，不调用API。
- 核验：Python语法、所有本次涉及的Markdown文件引用、原数组下标保留、输出位于T0Pre和拒绝写入T1Core等边界均通过。完整记录见[T0Pre迁移核验](../analysis/T0Pre/runtime/migration_verification.json)，日常入口见[T0Pre说明](../analysis/T0Pre/README.md)。未提交或推送。

### 全面采用WWH快照，独立复现三张分析图

- 来源决策：全面采用`NewDB/wwh5.sqlite3`的1000款样本、既有成就分类、剧情阶段、checkpoints数组顺序和game_labels游戏类型。旧LYX六表与分类链路保留，不进行合并或重新标注。
- 实施范围：复制WWH第5项`wwh5/analysis.py`与分析参数到`analysis/T0Pre/wwh_replay`；新增只读storage、独立run.py和说明。移除原程序执行schema、追加analysis_runs的写库路径，改用文件保存指标和验证记录；未复制API、采集或建表CLI。
- 数据版本：`wwh5-2026-10-13T10:26:09.722887+00:00`，源输入SHA256为`17a0c8e213e73d38ebf20939d5a26413dd49b858d3b315b4c6afa12722d0ebb0`。模型为deepseek-flash、提示词wwh5-ds-v3；全部为已有结果，无新请求。
- 默认复现：WWH当前参数为start，已有figures及最后历史分析却采用highest。本模块默认highest，置信度0.6、至少2个公共节点、允许多结局、不强制requires_start、RAWG分母20并报告10/50敏感性、游戏层Bootstrap2000次、种子42，完整参数留档。
- 真实结果：完整分类982款、剧情标注982款；可用曲线198款（unified120、multi78）、RAWG配对183款，Spearman为0.6449350317486812。分类汇总、曲线排除、各玩法/维度汇总、RAWG敏感性及用量与借用库最后一次历史分析逐项一致。
- start对照：独立输出到analysis/T0Pre/current_start，182条曲线（unified112、multi70）、168款配对，Spearman为0.6446329517422187。默认复现文件未被覆盖；两份数据库指纹仍一致。
- 数据保护：使用mode=ro、query_only和只读事务；借用WWH库及旧LYX库的SHA256、文件大小和mtime_ns运行前后一致。输出仅在LYX/analysis；旧库不参与指标计算，WWH源目录和共享配置保持不变。
- 节点追溯：指标文件为选中节点额外保存原checkpoints数组0基下标和1基顺序，保留route、requires_start及置信度，不按id、完成率重排，不写mainline_index。保持WWH原筛选和统计规则；此前至少6节点与人工核验前置不加到本次复现中。
- 图表：已生成并查看分类完成率、主线阶段曲线、RAWG对照三图，中文与图例显示正常。报告准确标注实际分母，不将最高成就解锁率等同于实际启动玩家。
- 文件：[运行说明](../analysis/T0Pre/README.md)、[复现报告](../analysis/T0Pre/report.md)、[来源指纹](../analysis/T0Pre/source_provenance.json)、[运行核验](../analysis/T0Pre/verification.json)。这只完成三图基线复现，不代表data_plan十个专题均已实施，不自动提交或推送。

## 2026-10-14～15 数据与分类工程历史摘要

历史事实以发生时间解释；当前操作入口统一为[PROCESS](PROCESS.md)，字段来源、一次性导入及FF7版本例外在[DATABASE_LYX](DATABASE_LYX.md)。旧请求/批次/DOM/运行备份已于2026-10-17按用户要求删除，不再给出失效的历史证据路径或resume命令；原数据库及database/backups保留。

2026-10-14完成六表重建、两款FF7原124项成就和127条类型保护、商店评价数前1000款固定清单只读迁移，原始成就总71465。method统一为deepseek/jev/rule/manual，标签新增display_name与同步触发器。开发按游戏名发送整款成就的DeepSeek流程、独立模型背景摘要、精确短ID与原文引用校验、写前备份/原子事务、人工及排序保护。当日阈值曾为严格>0.6，引用长度由60调至150；这些不是当前规则。

2026-10-15改为逐标签>=0.6、evidence每段<500；原文引用/结构失败按游戏隔离，低分不写库。引入可取消传输、简介90秒/分类300秒整调用总时限、15秒进度、连续同类3次超时暂停；完整响应缓存重校验，预算包含简介/分类/重试。datacache保存全量候选，failure_data另存各行门槛下的标签；两表仍由当前程序维护。置信度是模型自报，以上工程验收不等于语义准确率。

同日HLTB三类参考耗时按AppID导入，各覆盖347款；guide_difficulty替换为hard_ratio，覆盖996/1000款并四舍五入两位。旧Gamer Guides取时长/十分制评分方案已弃用，历史52款评分不再是当前值；2026-10-17一并清理源码与运行记录，不保留网站批量采集入口。

### 2026-10-15 23:13 成就分类进度记录

以下为当时冻结1000款的历史进度，非本次实时核查值。

| 状态 | 游戏数量 |
|---|---:|
| 已有DeepSeek分类结果入库 | 731 |
| 其中整款全部完成 | 598 |
| 其中仍有部分成就待处理 | 133 |
| 总计仍需处理，包含上述133款 | 398 |

另外4款没有成就。

| 状态 | 成就数量 |
|---|---:|
| 总成就数量 | 71465 |
| DeepSeek已完成分类 | 43284 |
| 受保护、无需自动处理 | 18 |
| 仍需处理 | 28163 |

2026-10-16后分析全面采用WWH冻结结果，本库分类完成不再是分析前置。v7分类与v2简介补充格式要求，原文只兼容NBSP/普通空格而不放松大小写/内容；历史离线恢复不代表新提示词已完成线上质量评测。旧版缓存兼容入口在本次清理后移除。
