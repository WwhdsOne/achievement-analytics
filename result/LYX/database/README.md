# 刘宇翔：分析输入与成就标注数据库规划

规划更新日期：2026-10-14。研究内容以项目 [docs/plan.md](../../../docs/plan.md) 的“主线进度漏斗与成就参与分析”为准，并结合刘宇翔在本次讨论中明确的方向：**研究游戏标签与主线完成表现的关联，用支线、收集、挑战等成就和有效时长数据解释参与方式的差异。**

本模块只允许编辑 `result/LYX`；其他目录永久只读。共享 PostgreSQL 是原始来源，只读访问；本地 SQLite 存选定游戏的固定输入与本模块标注，不向共享库回写。本文整理此前核验与讨论，本次仅更新 README，没有重新采集数据库或网站。

## 数据库需要支持的分析

| 数据层 | 回答的问题 | 本地保存原则 |
|---|---|---|
| 游戏特征 | 哪些标签、年份和难度印象与完成表现相关？ | 保留来源、原始标签与票数，另外记录标签归一化版本 |
| 成就语义与关系 | 哪项是主线、支线、收集或挑战？哪项能代表剧情阶段？ | 内容类型、人工审核、主线前置关系分别记录 |
| 参与表现 | 主线推进多深？可选目标完成到什么程度？投入时长怎样？ | 使用固定版本解锁率；时长独立保存，不混入成就类型判定 |

分析单位是游戏。没有个人玩家记录，不能识别“普通玩家”与“硬核玩家”，也不能从聚合量确认同一批玩家同时通关、收集或游玩较久。“粘性”在本模块中具体指主线推进和可选内容参与等代理表现，不直接称为时间留存或因果效应。

## 当前实现状态

- `schema.sql` 是可审阅的本地 SQLite 建表草案，已在内存数据库验证；尚未创建磁盘数据库或导入成就。
- `remote_audit.json` 是2026-10-13脱敏的远端结构与规模核验结果，已 Git 忽略，不包含地址、用户名、口令或成就正文。
- `../process/inspect_remote.py` 是只读核验脚本。自动标注、数据导入与人工审核界面尚未实现。
- 时长与难度专项统计来自此前交互中的只读查询，现有核验脚本尚未自动输出这些专项统计。
- 下文新增的游戏特征、辅助目标强度与外部攻略字段均为待设计的数据契约，**未写入现有六表 SQL**。本次不改共享 schema、依赖或程序，不 commit / push。

## 远端核验与连接路径

优先检查了 PyCharm `.idea/dataSources.xml` / `.idea/dataSources.local.xml`。其中有 PostgreSQL 连接信息与用户名，但没有项目内可用的密码；当前没有可以直接执行 PyCharm 数据源查询的连接工具，也不尝试解密 IDE 密码保险箱。保存配置的直接连接尝试未成功。

最终使用项目根目录 `.env` 中的 `POSTGRES_*` 与已有 psycopg 3 驱动连接成功。受限环境内连接未成功，取得网络执行权限后完成核验。服务端确认 `transaction_read_only=on`。每次核验分别使用 `REPEATABLE READ READ ONLY` 事务；每条查询的 statement_timeout 为 8 秒、lock_timeout 为 1 秒，连接结束即关闭，没有留下闲置事务。不同日期的核验结果不宣称属于同一读取快照。

2026-10-13核验快照（不是持续更新的实时统计）：

| 指标 | 数值 |
|---|---:|
| games 行数 | 50,956 |
| achievements 行数 | 1,971,064 |
| 有成就的游戏数 | 50,738 |
| 每款有成就游戏的平均成就数 | 38.85 |
| 每款有成就游戏的成就数中位数 | 19 |
| 最大单游戏成就数 | 10,979 |
| 未解决映射问题的游戏数 | 3 |
| 远端 dataset_versions 行数 | 1 |
| PostgreSQL 成就表数据页大小 | 224,731,136 字节，约 214.3 MiB |
| PostgreSQL 成就表含索引等的总大小 | 577,249,280 字节，约 550.5 MiB |

最后两项是核验时远端 PostgreSQL 的物理占用，不能直接换算为 SQLite 大小。另做了 2,000 行物理页抽样，三个文本字段合计平均 55.6 字节；这是存储参考，抽样可能偏向同页游戏，不作为整体文本分布或研究结论。

## 补充数据的核验结果与取用口径

### 时长：RAWG 正值可辅助，SteamSpy 当前不可用

| 原表属性 | 原类型 | 此前核验结果 | 分析口径 |
|---|---|---|---|
| steamspy_games.average_forever | INTEGER，分钟 | 50,741条全部为0 | 不作为时长数据；不能解释为所有人没有游玩 |
| steamspy_games.median_forever | INTEGER，分钟 | 50,741条全部为0 | 同上 |
| rawg_games.playtime | INTEGER，小时 | 15,770条：11,648条正值、4,122条零值、无NULL | 正值为候选有效值；零值含义未确认，首版排除并报告缺失覆盖 |
| game_engagement / games_full 的 playtime_hours | INTEGER，小时 | 来源均为rawg_games.playtime | 同一份数据的视图别名，不是两份独立证据 |

上述时长核验于2026-10-13完成。RAWG 正值约覆盖全部50,956款游戏的22.9%，抓取时间为2026-09-18至10-01；上游任务偏向评价数至少100的游戏，时长补充样本因此偏向主流游戏。正式样本还要过滤映射问题、核验版本，并报告所选游戏的实际覆盖率。

RAWG 官方总体介绍称其提供 Steam 平均游玩时长，字段文档明确单位为小时，但未充分披露抽样、计算窗口与分母。称“RAWG提供的游戏级平均游玩时长”，不称“普通玩家精确平均时长”；它不是主线通关所需时间。来源：[RAWG介绍](https://rawg.io/apidocs)、[接口文档](https://api.rawg.io/docs/)。

重点样本：FF7重生（appid 2909400）库内playtime=71；FF7重制版INTERGRADE（1462040）playtime=0，关联RAWG名为“Final Fantasy VII”，有版本匹配疑点。后者暂停使用RAWG补充证据，**不因此否定其Steam成就输入**。原始零值保留，分析排除理由另记；其他正值也不能仅凭大于0就认定质量合格。

### 难度：标签、条件文本和稀有程度分开保存

| 信息 | 已有属性 | 能支持什么 | 不能直接推出什么 |
|---|---|---|---|
| 难度印象/机制标签 | game_tags.tag TEXT、source TEXT、votes INTEGER、kind TEXT | 比较Difficult等标签与完成表现的关联 | 无标签不代表容易；票数也受热度影响 |
| 指定难度的成就条件 | achievements.description TEXT，可空 | 判断挑战、困难模式、速通或限制条件 | 该成就低完成率不等于普通主线困难 |
| 成就解锁率分布 | game_difficulty视图 | 描述成就稀有程度与完成结构 | 不视为独立测得的游戏难度评分 |

2026-10-14只读核验：Difficult在SteamSpy覆盖4,636款、RAWG覆盖1,227款，跨来源去重4,813款；另有Souls-like、Unforgiving和Adjustable Difficulty。Souls-like是玩法标签，Adjustable Difficulty表示可调难度，不自动归为“困难”。RAWG标签votes为空，不能填成0票。

game_difficulty的median_percent/p10_percent是解锁率分位数，hardest_percent/easiest_percent实际是最小/最大解锁率，hard_ratio是解锁率低于10%的成就占比。当前《艾尔登法环》hard_ratio=0，仅表示没有成就低于该阈值。这里沿用源字段名，但报告应使用“稀有成就占比”等准确名称。

FF7重制版Hardened Veteran要求困难难度主线全章节，库内解锁率3.10%；重生Of Hardy Stock要求困难难度全章节，2.90%。这些文本可支持challenge标注，不能替代普通主线结局节点。用同一组成就完成率构造“难度”再解释其完成率，容易循环解释；首版优先使用来源标签及明确条件文本。

### Gamer Guides：候选攻略估计来源，未进入批量导入计划

2026-10-14少量访问确认：[示例概览页](https://www.gamerguides.com/resident-evil-requiem/steam-achievements/overview)的初始HTML含Time=25–38h、Difficulty=6/10，普通请求可解析，不需要JavaScript。该页面仅验证格式，不自动纳入正式游戏样本。

页面位置提示其可能描述成就路线；评分作者、方法、是否覆盖全成就/主线/DLC仍未核实。因此暂记为“攻略路线预计耗时/难度”，适用范围未确认时保留unknown。预计区间不是玩家实际时长，也不是统计置信区间；6/10不能当作普通主线难度或等距客观量表。

当日核查的[使用条款](https://www.gamerguides.com/terms)标注更新于2026-07-05，第3/5节限制系统抓取和用于构建数据集，要求事先书面许可。HTML可读、非商业课程用途、改为手工系统摘录均不自动解决该使用要求。没有许可时不批量导入；取得许可或可用于研究的数据导出后，再评估接入，主流水线不依赖它。

## 后续数据契约：需要设计，但尚未实施

| 计划补充 | 最小属性与类型原则 | 必须保留的区别 |
|---|---|---|
| 所选游戏标签快照 | dataset_version + appid；source/tag/kind沿用TEXT，votes沿用INTEGER可空 | 原始标签与归一化标签分开；一对多关系单独存，避免成就联表膨胀 |
| RAWG补充快照与取样背景 | appid、rawg_id、name、playtime、fetched_at；按需选取已有发售日和评价数 | 保持源字段名与原类型；时间转UTC TEXT；版本疑点、零值排除属于质量标记，不改写原值 |
| 辅助目标的语义强度 | 接触/阶段目标/完整完成/未知、原始目标条件、接触机会或前置关系、核验依据 | 这些是候选语义属性，不能直接复用主线stage或凭完成率确定 |
| 获准的外部攻略估计 | 来源URL、平台/版本、范围、guide_difficulty_score/scale、guide_time_hours_min/max、核验日期、方法与许可依据 | 明确是估计；范围未核实不参与同口径比较；不覆盖RAWG playtime |

这几项会超出现有六表草案，下一轮先明确字段、关联键和版本规则，再在本地SQL中实现。TEXT[]不能原样当SQLite数组使用：标签优先拆关系表，其他多值字段按需定义序列化契约。辅助目标语义可先记在reason/review_note中供人工讨论；正式计算前置条件比例前必须结构化并核验。

## 原始字段：保持名字、声明类型和身份键

远端实际结构与 `cleaning/schema.sql` 的成就表一致：

| 字段 | PostgreSQL 类型 | 本地 SQLite 声明 | 语义 |
|---|---|---|---|
| appid | INTEGER | INTEGER | 游戏身份键 |
| position | INTEGER | INTEGER | 来源排列位置，>=1；不能解释为剧情顺序 |
| api_name | TEXT | TEXT | 内部关联键；正式展示不用它 |
| display_name | TEXT | TEXT | 正式展示名 |
| description | TEXT，可空 | TEXT，可空 | 成就条件；缺失保持 NULL |
| percent | NUMERIC(5,2) | NUMERIC(5,2) + CHECK | 全局解锁率，0～100，百分数单位 |

远端主键是 `(appid, api_name)`，另有 `UNIQUE(appid, position)` 和到 `games(appid)` 的外键。本地复制多个快照时，在这两个键前加 `dataset_version`，原始身份关系在每个快照内保持一致。

SQLite 与 PostgreSQL 的类型并非完全等价：

- INTEGER 是 SQLite 整数存储；源数据已受 PostgreSQL INTEGER 约束，本地另检查身份与位置为整数。
- SQLite 的 `NUMERIC(5,2)` 仅设置数值亲和性，不自动限制精度和小数位。本草案用 CHECK 检查数值、范围与两位小数；导入程序还需验证 Decimal 并统一序列化。percent 显示时格式化为两位小数，不要求数据库保存尾零。
- PostgreSQL TIMESTAMPTZ 映射为 UTC ISO 8601 TEXT，尽量保留 built_at / first_seen_at / updated_at 等已有名字。
- 新增布尔判断使用 INTEGER 0/1；允许 NULL 表示尚未确认，不能拿 NULL 直接当 false。
- 未启用 STRICT 表，因为 STRICT 不接受 NUMERIC(5,2) 这类声明；用外键、CHECK 和程序验证实现需要的约束。

## 为什么分成六张表

| 表 | 分工 |
|---|---|
| dataset_versions | 固定输入的版本、构建时间、整体 SHA256 与说明 |
| games | 所选游戏的身份与名称副本，以及成就源的参考抓取时间 |
| achievements | 保留上述六个原始成就字段的固定输入 |
| achievement_annotations | 一项成就的一版标注结果、审核、方法与依据 |
| achievement_annotation_types | 标注的多标签类型，一条类型一行 |
| mainline_nodes | 主线节点的阶段、剧情顺序、路线、必经性与前置关系 |

前三张是输入与版本支持；后三张是本模块新增数据。一张“大表”会重复名称、描述和完成率，也会把内容分类、自动初标和人工确认的主线关系混在一起。

## 核心标注表 achievement_annotations

| 字段 | SQLite 声明 | 必填/可空 | 用途 |
|---|---|---|---|
| dataset_version | TEXT | 必填 | 对应固定的成就输入版本 |
| appid | INTEGER | 必填 | 沿用原游戏身份 |
| api_name | TEXT | 必填 | 沿用原成就身份 |
| annotation_version | TEXT | 必填 | 标注规则、模型与人工修订版本，如 labels-v1 |
| method | TEXT | 必填 | manual / rule / llm / hybrid |
| status | TEXT | 必填 | pending / suggested / approved / rejected / uncertain |
| confidence | NUMERIC(4,3) | 可空 | 0～1 的方法输出；不等于经校准的正确概率 |
| reason | TEXT | 可空 | 分类解释，保留初标理由 |
| evidence_url | TEXT | 可空 | 主要核验来源；更多来源可先写进说明 |
| annotated_by | TEXT | 可空 | 标注人或处理程序 |
| model_name | TEXT | 可空 | 使用模型时记录实际模型 |
| prompt_version | TEXT | 可空 | 使用模型时记录提示词版本 |
| rule_version | TEXT | 可空 | 使用规则时记录规则版本 |
| input_sha256 | TEXT | 必填 | 送入标注方法的完整输入指纹 |
| created_at / updated_at | TEXT | 必填 | UTC ISO 8601 时间 |
| reviewed_by / reviewed_at | TEXT | 通常可空，approved 必填 | 人工审核记录 |
| review_note | TEXT | 可空 | 人工修订或争议说明 |

复合主键为 `(dataset_version, appid, api_name, annotation_version)`；可以在同一原始输入上保留不同标注版本。尚未审核的结果保持 suggested / uncertain；高 confidence 不自动变成 approved。

同一标注版本发布后按不可变成果使用；重新分类或大幅修改口径生成新 annotation_version。发布前的人工修订保留 reason 与 review_note。若后续确实需要每次尝试的审计历史，再增补独立的运行/事件表，本草案不预建复杂任务队列。

## 分类采用多标签

`achievement_annotation_types.achievement_type` 使用 TEXT 枚举：

| 值 | 中文 | 判断依据 |
|---|---|---|
| mainline | 主线 | 与主线推进或结局相关，需要核验 |
| side | 支线 | 可选支线任务或剧情 |
| collection | 收集 | 收集、探索或集合完成 |
| challenge | 挑战 | 特定难度、技术或限制条件 |
| multiplayer | 联机 | 需要多人、在线或合作条件 |
| dlc | DLC | 依赖扩展内容 |
| other | 其他 | 有明确含义但不属于上述类型 |
| unknown | 未知 | 证据不足或无法判定；不能与已明确类型共存 |

例如一项 DLC 收集挑战可以同时具有 dlc、collection、challenge。mainline 标签只说明内容相关，不能单独证明它是必经节点。关键词只产生候选，不按 percent 大小决定类型。

分类的目的不是给所有成就贴完标签就结束，而是解释主线之外的参与方式。同属side的“完成一个任务”与“完成全部支线”，同属collection的“找到一件物品”与“集齐全部物品”，目标强度不同。多标签类别可能重叠，类别占比不要求加总为100%；某类没有可测成就表示不可观测，不能填成零参与。

## 主线节点所需字段

mainline_nodes 关联同一版标注，增加：

| 字段 | 类型 | 用途 |
|---|---|---|
| route_id | TEXT | 区分主线/结局路线，默认 main |
| stage | TEXT | entry / early / middle / late / ending / custom |
| story_order | INTEGER | 人工确认的剧情顺序，>=1；一条路线内不重复 |
| is_required | INTEGER 0/1/NULL | 是否为该路线必经节点 |
| is_completion | INTEGER 0/1/NULL | 是否能代表该路线完成 |
| prerequisite_api_name | TEXT，可空 | 同一数据版本、游戏、标注版本和路线中的前置节点 |
| prerequisite_verified | INTEGER 0/1/NULL | 后续节点是否必然要求先解锁前置节点 |
| relation_evidence_url | TEXT，可空 | 前置关系的核验依据；确认关系时必填 |
| relation_note | TEXT，可空 | 分支、额外解锁条件、跳关等限制 |

节点类型人工审核和前置关系人工核验是两件事。未来流水线还必须检查前置节点的 story_order 更小、无环、两个节点均经审核、前置解锁率>0、解锁率关系无异常；这些跨行语义尚不由数据库完全保证。

`approved_mainline_nodes` 视图只输出已审核且有 mainline 标签的节点，并关联展示名、描述和解锁率。该视图并不表示任意相邻节点都能直接相除；只有已核验的嵌套关系允许计算条件比例。多结局分别展示，不直接相加。图表标题不称留存率或弃坑率。

## 数据时间和版本

- 远端 achievements 没有逐行 fetched_at，不添加一个虚构的原始抓取时间。
- games 中 global_fetched_at / community_fetched_at 从对应源最新成功的 ingest_log 获取，是审计参考；原日志没有逐条成就内容，因此无法凭日志重建旧成就快照。
- 本地导入当前选定游戏时新建 LYX 版本，建议 `lyx-日期-内容指纹前缀`；不能直接沿用远端游戏级汇总版本来代表新读取的成就明细。
- 固定版本的原始输入不覆写；要更新 percent 或名称，用新版本。
- input_sha256 必须覆盖实际送入标注方法的成就字段和任何上下文；若引入外部攻略或游戏标签，保存其来源/版本以便复现。
- 导入前只读过滤 mapping_issues 中 resolved=false 的 appid。2026-10-13核验有3款，实际导入时重新检查，不能把历史名单当作永久现状。
- REPEATABLE READ保证一次提取的一致性，不保证各源在同一时间抓取。记录来源抓取时间和差异；不一致的群体/时间口径不能强行计算条件比例。
- 派生分析需同时记录dataset_version、annotation_version、标签映射版本、样本清单与过滤原因、指标定义/参数。当前尚无派生指标表，首版可输出版本化报告到process/runtime。

## 下一轮数据库工作的最小验收范围

1. 先用两款FF7整理样本清单、源字段契约和问题台账，完成全成就初标与重点人工复核；随后扩大到20～30款试点。项目100～1000款是后续目标，按人工质量与覆盖扩展，不一次复制全库。
2. 在导入实现前补齐选样所需的年份、标签、RAWG正值与质量标记契约；所有新增结构仅在LYX本地设计，不修改共享库。
3. 创建一个本地快照，验收选中appid及成就行数、身份唯一性、空值与单位、来源时间、SHA256和外键；确认重跑不覆盖既有快照。
4. 主线节点审核与辅助类别审核均有记录；自动建议不直接进入正式指标。缺失、争议、不可观测与程序失败有不同状态或排除原因。
5. 发布可追溯的主线漏斗和辅助参与输入；具体公式、分析假设及程序顺序见[process规划](../process/README.md)。完成上述小样本验收再扩容。

## SQLite 容量评估

按实测每款平均 38.85 条成就估算。下列大小是规划预算，不是实测 SQLite 文件大小；假设一份数据快照、一版标注、短理由、平均少量类型标签及本草案索引，每项成就合计约 1～4 KiB：

| 规模 | 预计成就行数 | 预计本地容量 |
|---|---:|---:|
| 100 款 | 约 3,885 | 约 4～16 MiB |
| 1,000 款 | 约 38,850 | 约 38～152 MiB |
| 全量 50,738 款 | 1,971,064 | 约 1.9～7.5 GiB |

实际游戏分布偏斜，最多的一款有 10,979 个成就。正式选样后以该批 appid 的实际成就数求和；不要把平均数当作保证。长篇模型输出、多数据版本、多标注版本、提示词正文会增加容量，运行日志建议单独保存到 process/runtime。

结论：100～1000 款和本机个人标注适合 SQLite；百万级行数也不是容量障碍，但没有必要现在复制全库。数据库文件放本地磁盘，不让多台机器通过共享盘同时操作。自动标注可以并行计算，落库使用单写入者和短事务，避免模型请求期间持有写锁。

实际初始化本地数据库时设置 `foreign_keys=ON`、`busy_timeout=5000`，并先保持默认 `journal_mode=DELETE`；外键和超时需要每个连接正确设置。备份使用 sqlite3 的 backup API。SQLite 文件、附属日志、备份与原始副本都不提交 Git。

2026-10-13测得现有 Python 绑定 SQLite 3.50.4。官方记录该版本属于 WAL-reset 缺陷的受影响范围；缺陷涉及多连接并发写入/检查点，修复版包括 3.50.7 与 3.51.3 及更新版本。首版单写入者采用默认日志模式即可；将来有并发读写需求，再核验运行时版本，在 LYX 独立环境中使用已修复运行时并评估 WAL，不修改共享 Python 环境。启用 WAL 后，不能在活跃状态只复制主数据库文件。

官方依据：

- [SQLite 适用场景与单写入者限制](https://www.sqlite.org/whentouse.html)
- [SQLite 类型、NUMERIC 亲和性与时间表示](https://www.sqlite.org/datatype3.html)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [SQLite 在线备份](https://www.sqlite.org/backup.html)

## 验证命令

在项目环境已经可用的前提下，推荐从本模块目录运行（UV_CACHE_DIR 和 Python 不生成字节码的设置使缓存留在本模块）：

```powershell
Set-Location D:\PycharmProjects\achievement-analytics\result\LYX
$env:UV_CACHE_DIR = "$PWD\process\runtime\uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run --frozen --no-sync python -B process/tests/test_schema.py
uv run --frozen --no-sync python -B process/inspect_remote.py --output database/remote_audit.json
```

`--no-sync` 不创建或更新共享环境，缺依赖时停止，不在其他目录安装。只读核验不会注册远端 dataset_versions。此前直接使用已有 `.venv/Scripts/python.exe -B` 运行，避免修改 uv.lock 或产生其他目录的字节码，7项内存约束测试通过。本次仅更新文档，未重跑数据库查询、初始化或测试；新计划不等于已有功能。
