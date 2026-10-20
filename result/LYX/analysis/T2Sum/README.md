# T2Sum：口碑与主线推进、同类参照

2026-10-17专题5与专题6当前阶段均已实现。专题6交付同类参照基线、条件对照和案例，未训练回归模型；专题5原先的成对匹配案例与专题6群体参照仍分别保存。

统一使用/读图指南见[docs/INSTRUCT](../../docs/INSTRUCT.md)，六页签布局与网页数据契约见[docs/DEPLOY](../../docs/DEPLOY.md)。本README和BENCHMARK继续提供模块技术细节，不再维护另一套使用/部署指南。

任务6的运行、19～21图、字段与网页查询见[BENCHMARK.md](BENCHMARK.md)，结果见[同类参照报告](output/benchmark/report.md)。下文继续说明专题5。

入口：[run.py](run.py)。结果：[完整报告](output/reputation/report.md)、[16～18图集](figures/README.md)。返回[分析目录](../README.md)。

## 做了什么、为什么做

口碑与推进是不同的观测维度：评论者认可一款游戏，不意味着成就统计人群都推进到结局。本任务把评分与三个阶段推进并置，分析相关、分布与反例，不以某一个指标代替游戏质量或玩家忠诚度。

| 子方向 | 固定范围 | 输出 | 读图重点 |
|---|---:|---|---|
| Steam口碑与全程推进 | 完整三节点183款 | 16_reputation_quadrants | 看中位线两侧分布和探索案例，“低组”仅指低于本样本中位数 |
| Steam口碑与前/后/全程推进 | 同183款 | 17_reputation_stages | 看三个阶段的相关系数和区间；它们不是三个独立实验 |
| Steam、媒体、RAWG玩家评分对照 | 同142款评分齐全游戏 | 18_rating_sources | 各评分保留原单位，比较秩相关及成对系数差，不能直接比较散点斜率 |

198款底表中15款只有两个节点，全部排除本专题。中期继续取有效节点数组位置中位项，偶数取前一个；多结局继续沿用代表结局，不重新排序或标注。前三个推进比均有效、首/中分母正，三个节点身份不同才进入183款。原数据库、T0Pre、T1Core及01～15图均不变。

## 来源与字段

| 来源 | 读取内容 | 用途 |
|---|---|---|
| T1Core/output/game_metrics.csv及manifest.json | p_s/p_m/p_f、前/后/全程比、类型、结局与质量标记 | 指标与固定范围；先核验CSV和借用库指纹 |
| NewDB/wwh5.sqlite3的games.payload | name_en/name_zh、positive、negative、review_count、steamspy_fetched_at | Steam好评率=positive/(positive+negative)；183款全部有效，逐款核对总数 |
| 同一payload.rawg叠加inputs/manual_rating_supplements.csv | metacritic、rating、ratings_count、fetched_at和逐字段补充来源 | 叠加评分更新后媒体142款；正值玩家评分174款；三评分共同142款 |
| 同一借用库game_labels.payload | 完整gameplay及theme/presentation/player_mode | 四象限及后段区域的多标签构成；与T1玩法列表核对，原样保留自由文本标签 |
| database/achievements.sqlite的games_time | appid、main_hours | 仅为同类型/同结局/相近长度补充案例提供HLTB参考时长，68款有正值 |

源数据版本为`wwh5-2026-10-13T10:26:09.722887+00:00`。Steam来自SteamSpy正负评价数，不混入旧库store_search来源的review_percent；原始媒体评分来自RAWG保存的Metacritic字段；本轮两款的媒体/RAWG评分及战神人数来自用户手动核验。不是统一时点的实时评分，逐款源采集时间保存在CSV。

183款中媒体41款NULL；RAWG有4款NULL、5款零分。原始零分及人数保留审计，正值评分才用于分析，不将零分直接解释成差评。共同142款的RAWG评价人数都≥50，再加这一要求样本仍为142。HLTB交集68款、同时评分齐全62款，仅用于案例补充，不限制前三方向主样本。

## 命令

在`result/LYX`目录运行：

```powershell
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation
```

默认生成全部统计、CSV、JSON、报告及三组PNG/SVG；不调用DeepSeek、不连接云库、不修改SQLite。无需重跑前四项；若前置CSV或源库指纹变化，会停止并提示先核验来源。使用现有依赖，不执行uv sync、不改锁文件。

只读查看可选的198款名称和任务5状态，不出图：

```powershell
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --list-games
```

可以输入1～5款用于在总体图上高亮；这是选择观察对象，**不是把总体改成只分析这几款**：

```powershell
# 混合AppID、英文名、已有中文名。此例覆盖正常、缺评分和缺三节点三种状态。
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --games 367520 "God of War" "艾尔登法环" 379720 "Raft"

# 仅AppID；或仅名称，三种选择参数互斥。
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --appids 1245620 367520
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py reputation --game-names "Hollow Knight" "艾尔登法环"
```

名称复用T1的大小写/符号归一、完整名及唯一简称匹配；重复、超过5款、名称歧义或不在198款内均报错，不扩大总体范围。不补造缺失中文名。选中后用描边和AppID标记，原四象限颜色保留。

默认结果位于`output/reputation/`，默认图在`figures/`。自选另存`output/selections/<有序AppID摘要>/`及其`figures/`，相同有序选择可复跑更新，不覆盖总体图；来源、背景样本、阈值和统计均不随选择改变。

## 保存了哪些数据

| 输出 | 行数/含义 |
|---|---|
| reputation_eligibility.csv | 198款的三节点状态、排除原因、各评分原值及状态、名称与来源时间 |
| reputation_cohort.csv | 完整三节点183款底表 |
| rating_common.csv | 三评分共同有效142款，同顺序用于所有评分面板 |
| score_coverage.csv / score_summary.csv | 覆盖数与游戏级分布 |
| reputation_correlations.csv | Steam183的3项关联；共同142的3评分×3阶段，共12行 |
| correlation_differences.csv | 共同142款上3组评分差×3阶段，共9行 |
| sensitivity_correlations.csv | 单一start 170款、统一结局107款、多结局代理76款，各3项关联 |
| reputation_quadrants.csv / quadrant_cases.csv | 183款四象限归属、分界及四个探索案例 |
| matched_candidates.csv / matched_cases.csv | 相近长度且同主类型/结局的99对候选、3对不重复反向案例 |
| data.json | 两个固定背景、可选游戏状态、全部主统计及单位；给网页复用 |
| manifest.json | 版本、参数、来源、AppID指纹、输出指纹、数据库/前四项产物前后保护核验 |
| report.md | 完整统计表、样本来源、案例规则、图表及解释 |

正式output下CSV/JSON及manifest已由.gitignore例外规则允许跟踪；本轮inputs评分补充CSV也需提交，runtime继续忽略。网页成品已内嵌结果，打开页面不依赖SQLite。

## 统计与案例规则

- 游戏等权Spearman，评分不按评论数加权；评论数不是成就玩家数。
- 整行联合Bootstrap 2000次，种子42，每次重新计算平均秩；共同142款的三评分共用同一批抽样下标，系数差区间由同轮差值计算。
- 不合成三平台评分总分、不自动挑显著结果；全量数值及区间均保留。区间表示游戏集合重采样波动，不是用户级误差，不保证对全部Steam有代表性。新增Steam与全程推进的双指标位置排序单独定义，不当成游戏质量评分。
- 四象限采用183款Steam和全程推进各自中位数（91.0575%、32.6203%），等于分界归高组；四组为50、42、42、49款。案例按两轴百分位秩偏离0.5的乘积选极端，并列按AppID；不是典型游戏排名。
- 匹配案例只用同183款中68款有HLTB的游戏，要求同主类型、同结局口径，主线参考时长之比≤1.25；从评分差/推进差方向相反的候选中按乘积选最多3对不重复游戏。完整99对留档，不虚构因果对照。

当前Steam183前/后/全程ρ分别为+0.255、+0.108、+0.164；同142款全程ρ分别为Steam +0.140、媒体+0.239、RAWG +0.295。这个量级说明口碑不能代替主线推进。评分人群不同、结局代理及节点跨度仍影响解释，数值不是玩家忠诚度或真实留存率。

## 图16～18的探索解读补充

同日按负责人确认，新增[reputation_exploration.py](reputation_exploration.py)，随原`reputation`命令自动运行，结果追加到[完整报告](output/reputation/report.md)的“图16～18的进一步探索解读”。无需单独命令，不改变183/142款或原三图口径，不涉及实际15号时长图。

- 四象限按完整gameplay多标签统计，分母为象限游戏数，每个标签每款计一次。保存相对183款背景的占比、百分点差、提升倍数及区域外占比；标签占比之和可超过100%，并保存共现组合，不能把重叠标签当成独立证据。
- 后段右上区域明确为Steam≥90%、末/中≥80%，共28款；解谜19款（67.9%），背景38/183（20.8%），提升3.27倍。同为高口碑的102款作为额外背景，另有9组85/90/95%×70/80/90%边界对照。自由题材/表现/人数标签原样读取，未合并近义词；Singleplayer在区域内100%、背景99.5%，不是有区分度的共性。
- 排序只用图16两轴：先在183款内求好评与全程推进平均秩百分位，50/50等权，共同表现分为两百分位均值×100。先合并整数/半整数秩再除以样本数，避免浮点误差拆散理论并列；同分展示按AppID，保留全部183款与边界并列名单。25/75、50/50、75/25权重另存，前五/后五只作为当前规则下案例。
- 前五有3款The Room系列，提示系列聚集；后五边界还存在Pathfinder/Arma/Dragon's Dogma 2同分，不能按展示名额认定谁更差。保存所有榜单/边界并列游戏及反直觉案例的首中末成就原文、描述和原始百分数；不修订模型节点或数据库。
- 发现Outward“全部3条任务线”、Sniper Elite 3“100%战役”、Dragon's Dogma 2特定模式限制、Balatro“一局胜利”、Arma中位教程节点及Persona 4 Golden中末描述缺失等可比性疑点。报告保留这些限制，不把靠后榜写成游戏质量差或真实通关低；是否另做普通通关子样本留待人工判断。

新增10张本地CSV：exploration_multilabel、exploration_text_labels、exploration_tag_pairs、exploration_group_summary、exploration_region_boundaries、exploration_joint_rankings、exploration_rank_weights、exploration_case_checkpoints、exploration_memberships、exploration_descriptive_correlations。数据在相应输出目录，`data.json.exploration`包含完整结果与版本；manifest同步记录所有表和参数。CSV/JSON仍按.gitignore忽略，部署须单独交接。探索结论是看图后的描述，不是预注册检验或因果结论。

## 给网页的接口与交互

`reputation_data.query_reputation(selectors=None, kind="mixed")`为无文件写入的Python查询函数，支持kind为mixed/appid/name，不调用模型；它验证现有T1 CSV和数据库，只读构造固定背景与1～5款选择。可以从LYX目录调用：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("analysis/T2Sum").resolve()))
from reputation_data import query_reputation
data = query_reputation(["367520", "God of War", "艾尔登法环", "379720", "Raft"])
```

查询函数只返回背景、选择与来源；完成分析生成的`data.json`还包含全部统计、中位线和案例。正式Go网页建议直接读取已发布JSON，不为请求引入Python运行环境，也不在每次选游戏时重做2000次重采样。

页面可在原四页签之外增加“口碑与推进”：上方样本说明183/142及版本，中间三个方向切换，下方1～5款详情卡与总体统计。选中只加描边/名称悬浮，不删除背景点，不重算中位数、坐标范围或相关系数。不同评分使用自身单位，不能把媒体85分显示成RAWG的85分。

`selected`每条保留完整指标、原评分、采集时间、评价数与`selection_status`、`unavailable_scores`：

- available_all_panels：可在全部面板定位。
- available_steam_only：可在16/17定位，18为固定共同样本，保留“缺少共同评分，未纳入142款”提示；即使某单个评分有值，也不临时塞入某一个18面板。
- incomplete_three_point：在198款内但不进本专题183款，保留“只有两个节点”等原因，不补0、不在本专题画点。

例如上述5款选择：Hollow Knight与艾尔登法环可在三类图中定位；God of War现已补齐并可在142款中定位，Raft仍缺媒体评分，只在183款图中定位；DOOM只有两节点，保留说明。已有API服务、网页部署及前端原因卡片仍由组长实现，本轮只提供本地接口与交接结构。

RAWG数据展示页面保留[RAWG](https://rawg.io/)回链。完整六任务网页设想见[统一交接文档](../../docs/DEPLOY.md)，本节为任务5技术补充，页面整体方案以统一文档为准。

## 2026-10-17 数据附件与来源审查

来源表、结果表、任务总结和完整上传选择已集中到[交接目录](../delivery/README.md)，当前五个专题与公共指标的只读核验见[审查报告](../delivery/AUDIT.md)。可直接交接本地package用于展示；现有部分Python查询仍读SQLite，纯结果包部署需由组长实现只读适配。原库和分析数值/图未改，process历史清理不影响这些结果。

## 2026-10-20 评分补充与重算

[评分输入](inputs/manual_rating_supplements.csv)保存用户确认的5个字段：33号远征队媒体92、RAWG 4.42；战神媒体94、RAWG 4.54、人数5310。33号远征队旧RAWG 4.44、两款媒体原NULL及战神原人数NULL均保留在*_raw字段；*_source和rating_provided_on记录新增值的来源及确认日期，旧rawg_fetched_at不代表补充值采集时间。两份数据库保持只读。

原140款全部保留，新增两款形成142款；RAWG正值174款，4款NULL、5款零。共同142款人数均≥50。16/17的183款Steam数值和统计不变，本次增加两款可识别名称标注；18的三个面板统一142款并重算。默认三张原图均描边标注两款；CLI显式选择继续沿用1～5款高亮并另存。HLTB仍使用任务5原68款规则，与评分共同62款；不混入任务4的时长补充。

任务6不使用媒体/RAWG评分，本次不重画19～21。读取旧参照结果时，若上游清单变化，程序核验当前任务5产物哈希，并逐游戏比对Steam评价、主线指标、长度、结局/类型、核心指标CSV及范围指纹；只有全部实际计算输入相同时才允许读取，其他变化仍要求重跑。历史benchmark输出不改写。
