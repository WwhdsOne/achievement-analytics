# 专题6：同类参照与突出案例

2026-10-17实现。任务6当前交付范围是可解释的同类参照基线、条件对照和案例，不包含回归预测模型。返回[T2Sum](README.md)，查看[报告](output/benchmark/report.md)和[19～21图](figures/README.md)。

## 研究含义

任务5观察口碑与推进怎样共同分布；本任务回答“这款游戏相比玩法相近的其他游戏，推进高出或低于多少”。绝对推进高不等于相对同类突出，每款游戏的参照也不相同。比较的是冻结快照中的游戏级聚合比值，不是个人真实留存或设计因果效果。

输入完全复用任务5冻结数据、T1完整三节点与已有多标签。原183款保留；181款主参照有效，Clustertruck（397950）只有4款参照，Session: Skate Sim（861650）为0，二者保留原值与状态，不补零、不自动扩大范围。原198款中的15款两节点仍可在选择界面识别，但不进入本任务计算。

## 数据与参照规则

| 输入 | 使用内容 |
|---|---|
| T2Sum/output/reputation/data.json及manifest | 183款指标、Steam好评率、HLTB、来源与保护；先验证全部上游产物指纹 |
| T1Core/output/game_metrics.csv及manifest | 完整gameplay、结局口径、原数组选点、来源质量标记 |
| 借用SQLite的achievements | 原始首/中/末成就展示名与描述，只读用于案例解释 |
| 旧SQLite | 本任务不另查数值；使用任务5已保存的games_time.main_hours快照，旧库仍纳入保护核验 |

完整玩法标签计算Jaccard=共同标签数/不同标签并集数，忽略other、uncertain但保留原列表；目标与参照Jaccard≥0.5、结局unified/multi相同，始终排除自身。集合相似度使用精确分数判定边界，参照排序按相似度降序、AppID升序，仅用于名单展示，统计中每款等权。

参照选择不使用首中末解锁率或派生推进值，也不使用hard_ratio。这里排除的是用结果挑参照的直接偏向，不宣称已经排除所有混杂。相同结局标记不代表任务要求相同。

| 条件 | 待分析范围 | 至少5参照 | 至少10参照 |
|---|---:|---:|---:|
| 多标签主参照，Jaccard≥0.5 | 183 | 181 | 160 |
| Jaccard≥0.4 | 183 | 182 | 175 |
| Jaccard≥0.6 | 183 | 157 | 120 |
| 主参照＋好评差≤10个百分点 | 183 | 165 | 138 |
| 主参照＋HLTB主线时长比≤2 | 68 | 46 | 33 |

每个条件保存183行；时长条件115款缺目标时长另标记，68款中22款参照不足。时长比≤2用于获得参照群体，和任务5找成对案例的1.25倍用途不同，不宣称时长精确匹配。口碑与时长条件分别对照，没有将所有条件叠加后仍称覆盖183款。

## 指标与单位

对前段、后段、全程分别计算：

- reference_q1/median/q3：参照游戏该阶段的四分位数及中位数。
- delta：目标实际值−参照中位数。内部0～1，显示乘100为百分点；例如0.25是＋25个百分点。
- peer_percentile：`(参照低于目标款数 + 0.5 × 与目标相同款数) / 参照数`，0～1。
- peer_n：参照游戏数，不能当成玩家数；至少5款才计算上述统计。

三阶段使用同一参照名单，但分别求中位数；三中位数不能相乘，三阶段差不能相加。箱体四分位范围描述游戏间分散程度，不是置信区间；本专题不以显著性或玩家数虚构误差条。

主参照中91款高于、90款低于各自参照。条件对照只比较两套条件都有效的同一批目标：加入相近口碑后165款中161款方向一致；加入相近时长后46款中42款方向一致。方向一致不代表因果稳健或统计显著，参照名单和中位数依然可能变化。

## 命令：从result/LYX目录运行

```powershell
# 默认全183款计算，图19显示181款有效目标，图20/21展示自动挑选的最多5个案例。
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark

# AppID、已有英文名、已有中文名可混用；选择1～5款，参照始终固定。
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --games "Hollow Knight" "艾尔登法环" 379720 397950 861650

# 仅AppID或仅名称，三种选择参数互斥。
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --appids 1245620 367520
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --game-names "Emily is Away" "Sanfu"

# 已运行默认benchmark后，只读列出198款名称、任务6状态与参照数，不出图。
uv --cache-dir analysis/T2Sum/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T2Sum/run.py benchmark --list-games
```

默认写入output/benchmark，19～21图写入T2Sum/figures。手动选择独立存入output/benchmark_selections/<有序AppID摘要>/及其figures，不覆盖默认图或任务5结果；相同选择复跑会更新自己的结果。

名称匹配复用T1的规范化、完整名和唯一简称；歧义、重复、超过5款或不在原198款范围均报错。上面的五款示例覆盖：Hollow Knight和艾尔登法环可定位；DOOM只有两个节点；Clustertruck和Session参照不足。所有选择都保留说明，图19背景仍为181款。

CLI会重新生成完整固定范围的参照与输出；网页查询函数读取预先准备的数据，不在选择时重新计算。无需重跑任务1～5、重分类、连接远端或调用模型。

## 读图与自动案例

| 图 | 怎么看 | 可以判断什么 |
|---|---|---|
| 19_peer_benchmark | x是参照中位数，y是实际全程比；上方高于参照，颜色是差值，选择加描边 | 绝对位置与相对同类位置是否一致；不表示模型预测准确度 |
| 20_peer_stage_gaps | 前、后、全程各减自身对应参照中位数 | 相对差距主要表现在哪一段，不能归因于具体设计 |
| 21_peer_cases | 蓝点/箱体是其他游戏，黑菱形是目标，右侧列最近参照及节点提示 | 目标高于大多数参照，还是参照内部本来就很分散 |

自动案例要求主参照≥10、全程差绝对值≥10个百分点、Jaccard0.4/0.5/0.6均有效且方向一致；最多3个正向、2个负向，按差绝对值/参照数/AppID排序。已记录6个具体节点疑点的目标不自动推荐，但仍参与计算和其他目标的参照，其数量单列。未列疑点不代表通过人工审核。

当前自动核查案例：The Walking Dead: The Final Season、Emily is Away、Sanfu、Pony Island、STEINS;GATE。它们的三节点原文在报告中逐项列出。Pony Island末节点是全部秘密要求，STEINS;GATE中位描述缺失，Final Season末节点仅标Act Three；这些都提示“自动突出案例”不能直接称为更好/更差的普通通关设计。所有原标签和数据库保持不变。

## 输出与复现

| 文件 | 含义 |
|---|---|
| peer_benchmark.csv | 全183款主参照、原值、三阶段参照统计/差值、语义提示 |
| peer_conditions.csv | 5种条件×183款＝915行，缺失与不足均保留 |
| peer_membership.csv | 逐目标/条件的完整有向参照名单、相似度和背景/推进值 |
| peer_coverage.csv | 5种条件的范围、有效数、参照数量 |
| benchmark_sensitivity.csv | 同一目标的条件变化、方向与缺失状态 |
| matched_sensitivity.csv | 共同有效目标交集的汇总，避免换样本比较 |
| benchmark_cases.csv | 固定规则挑选的5个自动核查案例 |
| semantic_caveats.csv | 全183款已知具体疑点或尚未逐项人工核验状态 |
| data.json | 183款、915条件结果、全参照关系、198款名称目录、自动及当前选择 |
| manifest.json / report.md | 来源、规则、代码/数据指纹、先前产物保护及完整读图解释 |

CSV/JSON在本地忽略，Git不携带这些数据；代码、报告、图和说明正常跟踪。输入变动应先核对版本，不能把旧CSV、当前数据库及不同条件的统计任意混用。执行前后核验两份SQLite、T0/T1、任务5全部输出和1～18号图保持不变；没有改schema或uv.lock，不自动提交/推送。

## 网页接入与只读查询

从LYX目录可调用：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("analysis/T2Sum").resolve()))
from benchmark import query_benchmark
payload = query_benchmark(["Hollow Knight", "艾尔登法环", "379720", "397950", "861650"])
```

先运行一次默认benchmark。查询读取已生成数据，验证版本及数据指纹、通过既有名称目录匹配，不写文件、不重新构建参照。返回固定background（181款）、game_catalog（198款）、coverage、条件对照和selected；不会把915行条件和全部有向关系原样重复返回。selected包含该游戏主统计、references及其sensitivity。

页面可以在任务5之后增加“同类参照”页签：上方规则/版本/有效181款，中间固定图19，下方显示1～5款的阶段差和图21式分布卡。悬浮与卡片至少给出原值、中位数、差值单位、参照n、标签、结局口径及原始末节点；可展开完整参照名单，不只展示最相似3款。

页面选择不改变任何参照或总体背景。peer_status有三种主要状态：available、insufficient_peers、outside_three_point_cohort；补充时长条件还可能missing_target_length。不可定位时保留选择芯片和原因，不画假零点。相近口碑/时长的条件是预先计算好的独立对照，页面切换时必须同步切换状态、n及差值，不能保留主口径的181背景却标成时长46款结果。

完整审计data.json约15MB，建议Go服务启动时读取一次后按视图取子集，不在每次选择时传全表，更不为此安装Python。当前没有新增HTTP服务或实施网页部署。六任务统一网页规划见[docs/DEPLOY](../../docs/DEPLOY.md)；本说明保留任务6技术细节，使用/读图见[统一INSTRUCT](../../docs/INSTRUCT.md)。
