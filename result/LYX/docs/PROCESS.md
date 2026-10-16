# LYX整款分类流程与运行说明

更新：2026-10-16。链路为：**游戏名定位 → 读取完整成就 → 缓存/生成背景摘要 → 整款一次分类 → 校验 → 累计CSV留档 → 本地SQLite → 更新写入结果。** 默认不按固定成就数拆批。共享PostgreSQL永远只读，日常分类不连接远端。

DeepSeek在此承担LLM as Judge的语义标签判定：依据固定八类规则判断每项成就，程序负责身份、完整性、原文引用、门槛与写入保护。当前已验证的是请求、缓存、校验、恢复及持久化链路；模型自报confidence和工程验收通过都不能代替人工抽样形成的分类准确率。

## 程序与提示词位置

| 文件 | 职责 |
|---|---|
| [DataAgent.py](../process/DataAgent.py) | 游戏名/AppID选择、整款预检、共用客户端、缓存、预算、分类与写库 |
| [deepseek_transport.py](../process/deepseek_transport.py) | 可取消HTTP传输、请求总时限、接收进度和部分响应记录；业务仍逐款串行 |
| [game_intro.py](../process/game_intro.py) | 游戏背景摘要提示词、响应校验和缓存调用 |
| [local_database.py](../process/local_database.py) | 本地连接、字段转换、结构检查、整款输入核对与原子存储 |
| [datacache.py](../process/datacache.py) | 当轮17列CSV导出、累计22列CSV校验与去重，并同步派生低分failure_data.csv；带文件锁和原子替换，不连接API或数据库 |
| [import_classification_cache.py](../process/import_classification_cache.py) | 离线核验历史分类CSV与原始响应，只补符合门槛且本地缺失的标签，并汇总累计缓存 |
| [import_snapshot.py](../process/import_snapshot.py)、[inspect_remote.py](../process/inspect_remote.py) | 独立的只读数据准备，已有迁移完成 |
| [migrate_methods.py](../process/migrate_methods.py) | 已完成的一次性method维护 |
| [migrate_display_names.py](../process/migrate_display_names.py) | 已完成的本地版本2→3迁移，给标签表添加并回填展示名 |
| [old/](../process/old/README.md) | 已弃用的Gamer Guides五个源码文件，仅作历史归档 |

分类常量CLASSIFICATION_PROMPT在DataAgent.py的导入区之后，版本lyx-deepseek-whole-game-v7；简介常量GAME_INTRO_PROMPT在game_intro.py的导入区之后，版本lyx-game-intro-v2。修改相应提示词时同步升级其版本。简介与分类使用不同任务命名空间；当前分类v7可重校验复用精确保留的v6/v5/v4完整响应，简介v2可复用合格的v1。原提示词原样保留，当前缓存优先，旧文件不改写。

旧probe/规则脚本和旧代码备份保留在runtime/archive，历史命令不再是当前入口。当前命令没有--batch-size和--sample-size，不会默认每20项调用。

## 游戏选择与离线预检

先在项目根目录同步main，再进入LYX。使用已有环境，不修改共享依赖：

~~~powershell
Set-Location D:\PycharmProjects\achievement-analytics
git pull origin main
Set-Location result\LYX
$env:UV_CACHE_DIR = "$PWD\process\runtime\uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan --game-name "FINAL FANTASY VII REBIRTH"
~~~

完整名称可忽略大小写、Unicode形式和多余空白；中文匹配取决于库中是否保存该名称。名称不唯一或只有部分/相似匹配时只展示候选，不猜选、不调用模型。--game-name、--appids、--appids-file、--all-games互斥；未指定默认冻结前1000款清单。

### 游戏选择参数

下面的参数用于替换命令中的整个`--game-name "..."`部分；四种方式互斥，一次只能使用一种。运行预算等参数可以与任意选择方式搭配。

| 写法 | 作用 |
|---|---|
| `--game-name "FINAL FANTASY VII REBIRTH"` | 按库中完整中英文名称选一款；不支持同时传多个名称 |
| `--appids 2909400` | 按AppID选一款 |
| `--appids 1462040 2909400` | 按AppID选多款；要求正整数且不重复 |
| `--appids-file database/data/top1000_appids.json` | 按JSON清单选择；文件内容为非空、不重复的正整数数组，如`[1462040,2909400]`，路径须在LYX内 |
| `--all-games` | 选择本地games表全部游戏，按AppID升序 |
| 不写选择参数 | 使用冻结的前1000款AppID清单，按清单顺序；不重新查询远端排名 |

当前本地1000款与冻结清单范围相同，处理顺序可以不同；以后新增本地游戏时，`--all-games`与冻结前1000款不一定相同。已有游戏记录只表示原始数据已准备，不等于已经完成DeepSeek分类。

### 子命令与运行参数

| 子命令 | 行为 |
|---|---|
| `plan`，或不写子命令 | 离线读取本地输入/缓存并打印预检；不调用API、不写库、运行报告或两份累计CSV |
| `classify` | 对选中游戏执行缓存/简介/整款分类，并按门槛自动写本地SQLite；有运行报告及备份 |
| `check-connection` | 极小JSON响应检查，可复用缓存，最多1次新请求；不分类成就、不写SQLite |

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--max-requests N` | `2` | 本轮新API请求次数上限，非负整数；包含简介、分类及重试，缓存不计；`0`禁止新请求 |
| `--reclassify` | 不启用 | 允许更新已有机器结果，仍保护人工/排序；仍优先缓存，不表示强制重新请求API |
| `--min-confidence X` | `0.6` | 有限数0～1；逐标签按`confidence >= X`筛选，等于门槛也通过 |
| `--max-output-tokens N`，别名`--max-tokens` | `65536` | 分类输出估计的允许上限，范围32～384000；实际分类请求使用`1024 + 160 × 完整成就数`的估计值作为max_tokens，超限跳过，不自动拆批 |
| `--max-input-chars N` | `300000` | 输入字符预算，须为正整数；字符数不是token数 |
| `--timeout-seconds N` | `300` | HTTP读超时，须为正有限秒数；连接超时仍15秒 |
| `--intro-total-timeout-seconds N` | `90` | 一次简介调用的总时限，须为正有限秒数；覆盖网络尝试、接收完整正文及有限重试/退避 |
| `--classification-total-timeout-seconds N` | `300` | 一次整款分类调用的总时限，须为正有限秒数；保活空行不延长时限 |
| `--database PATH` | `database/achievements.sqlite` | 已存在的LYX内SQLite文件，不自动创建或改表；日常要求schema版本4 |
| `--runtime PATH` | `process/runtime/deepseek` | LYX内的缓存、运行报告与进程锁目录；更换目录不会沿用原目录缓存 |
| `--datacache PATH` | `process/datacache.csv` | LYX内的累计有效分类CSV；包括低分、已有、受保护和本轮写入结果，并在同目录自动刷新failure_data.csv，不取代每轮报告或原始响应 |

路径默认值按程序所在的LYX工作空间定位；手动传入的相对路径按当前终端目录解析，因此以下命令统一从LYX运行。简介输出上限单独固定512 tokens，连接检查为32，不随分类输出预算增加。

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan --appids 1462040 2909400
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan
~~~

plan完全离线，不调用模型、不写数据库或运行报告。显示每款完整成就数、待写项、保护项、输入字符/字节、输出预算和本地缓存。简介缺失时用最大长度预留估计输入，不将占位文本发给模型；字符数不是token，输出预算也不是实际用量或费用报价。

历史默认预检有16款超规模游戏；ready、已完成与待处理数量会随运行变化，以本轮plan为准。带时间的验收快照统一见[实验记录](experiments.md)。

## 实际整款分类

下列命令会执行分类链路；存在待处理项且没有合格缓存时才调用模型。首次普通游戏通常需要简介1次、整款分类1次，不含重试；通过的标签自动写入本地SQLite：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --game-name "FINAL FANTASY VII REBIRTH" --max-requests 2
~~~

--max-requests是本次进程的请求上限，每次启动从0重新计数；它不是游戏数、成就数、token数、金额或每日总额度。失败尝试/重试也计数，本地缓存、SQLite查询、跳过完成游戏不计数。简介缓存命中后通常只需分类请求；两阶段均命中则新请求0。预算只有1次且简介缺失时，简介保存后以budget_reached暂停；续跑复用简介，继续分类。没有额外的连接测试或缓存预热请求。

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --appids 1462040 2909400 --max-requests 4
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --game-name "FINAL FANTASY VII REBIRTH" --reclassify --max-requests 2
~~~

默认保留已有DeepSeek结果，包括uncertain；--reclassify才重判机器结果，仍保护approved、manual标签或非空mainline_index。模型看到全部原始成就，不看到旧标签；完整响应中无需更新的条目也经过校验，但不会覆盖其既有结果。整个游戏已无待处理项时，不再生成简介或分类。

具体完成判据：排除approved/manual/非空mainline_index保护项后，成就status为suggested或uncertain，且已有全部标签method都是deepseek，即记已完成。只有rule/jev结果的成就仍待处理，不能仅按games表存在或status='pending'判断。整款pending_count=0则state=already_classified_or_protected；部分未完成时仍发送全款原文，默认仅更新待处理项。输入相同可复用已有响应；低分全部未通过的成就不会被虚记完成。

### 默认全量选择与预算续跑

不写游戏选择参数即可选择冻结前1000款；`classify`默认预算仍只有2次请求，不能据此认为会一次完成1000款。以下例子显式设本轮20次预算，冷缓存、无重试时通常约可处理10款，完成项自动跳过：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --max-requests 20
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --all-games --max-requests 20
~~~

三行分别是预检、冻结清单分类、本地全库分类，按需要选择，不要求连续执行后两行。budget_reached表示预算暂停，重跑同一命令会用新一轮预算继续；已写项、简介和响应缓存保留。单款HTTP 200响应中的无效JSON、截断或契约错误记为该游戏response_error；总时限或读超时记request_timeout。这两类失败均不写本款，继续后续游戏；同类请求连续3次超时则暂停整轮，详见下节。其他网络、认证、余额、限流、文件或数据库问题仍停止本轮并记error。超规模游戏仍单列跳过，选择全量不等于已经处理超规模项。

--max-requests 0只允许复用本地缓存。缓存路径为process/runtime/deepseek/cache/<请求指纹>/receipt-*.json；原始响应和简介也通过此机制保存。每次真实响应新增带时间戳的receipt文件，旧响应不被后续生成覆盖；每轮报告使用独立的runs/<UTC时间>/目录。分类结果与本轮简介在report.json中关联，CSV每标签一行，sqlite_outcome表明written/unchanged/protected/already_classified/below_threshold；confidence_passed及label_sqlite_outcome区分每条标签是否通过门槛和实际存储结果。

### 累计分类CSV与历史结果导入

[process/datacache.csv](../process/datacache.csv)是跨运行累计分类表，每个标签一行，覆盖通过和未通过门槛、已有结果、受保护及本轮写入项。每款完整响应通过当前校验后，先保存所有候选标签到该表，再提交SQLite；提交后刷新标签对应的写入结果。按`(appid,api_name,type,request_hash)`去重，同一请求的重复回放不会不断增加重复行；`source_csv`、`first_seen_at`、`last_seen_at`用于追溯。不同请求产生的同一标签保留各自记录，累计CSV行数不能直接当成唯一标签数或已写库数。原始runtime CSV、JSON和历史报告继续保留，不删除或覆盖。

同目录的[failure_data.csv](../process/failure_data.csv)是累计表中**未通过置信度门槛的逐标签子集**，列名、22列顺序和去重键与datacache一致。筛选条件为本行`confidence < min_confidence`，当前默认门槛0.6；恰为0.6的标签通过，不进入低分表。多标签成就只抽取其中低分标签，其他合格标签仍按原逻辑入库。这个文件便于集中人工复核，保留游戏名、成就名、原文、理由、分数、门槛及请求来源。

普通`classify`及历史导入`--apply`每次更新累计表时，在同一文件锁内由完整datacache重建低分表；不改变模型调用、预算、SQLite写入和已有结果保护。`--datacache`改到其他路径时，低分表仍命名failure_data.csv，位于所选累计表的同一目录，不增加单独参数；建议每个目录仅放一个累计源，避免多个源共用同名派生文件。独立`rebuild_failure_data(datacache_path)`可从现有累计表初始化或恢复低分表，只读源CSV，不调用API、不读写SQLite、不改datacache；源不存在则报错，不用空表覆盖已有派生文件，没有低分时输出仅含表头的CSV。`plan`和历史导入预检均不生成或刷新它；新逻辑自下次启动任务生效。

低分表按每行最近累计更新记录的门槛筛选，改命令行门槛不会重写未被再次处理的历史行；同一请求重新评判后会更新对应去重键，达到新门槛的行会从低分表移除。不同request_hash的历史判断仍分别保留，所以某成就后来已有合格分类，也可能保留旧请求的低分记录。不能用低分表行数当作当前SQLite未分类成就数。结构、证据或网络失败没有有效候选，不进入该表；已达门槛但因`conflict`、已有结果或人工保护未写库的行也不属于低分，仍查看datacache及report/receipt。

### 四层产物与累计表字段

| 产物 | 保存内容与用途 | 是否决定普通分类跳过 |
|---|---|---|
| `runtime/deepseek/cache/<请求指纹>/receipt-*.json` | 请求payload、原始响应、HTTP/usage/阶段；完整有效响应可复用，错误或部分响应保留供排查 | 否；只决定能否免新请求复用 |
| `runtime/deepseek/runs/<UTC时间>/report.json`及`classifications.csv` | 本轮游戏/调用/错误统计，以及有效分类候选的逐标签明细；CSV是17列 | 否；不是全局进度表 |
| `process/datacache.csv` | 跨轮累计有效分类候选、门槛结果、存储结果与追溯信息；包括低分、已有和写入项，共22列 | 否；仍低分的成就可以继续pending |
| `process/failure_data.csv`（累计层派生表） | datacache中confidence低于本行min_confidence的22列逐标签快照，供人工复核 | 否；不新增任务状态或写入规则 |
| `database/achievements.sqlite` | 通过门槛且允许写入的标签关系，以及成就状态、人工确认和排序 | 是；以状态、已有标签方法及保护规则计算待处理项 |

累计CSV的前17列与每轮CSV相同，最后5列用于累计追溯：

| 字段 | 含义 |
|---|---|
| `appid` | 游戏身份键 |
| `name_en` | 本地游戏英文名 |
| `api_name` | 成就身份键；结合appid定位 |
| `display_name` | 原始成就展示名 |
| `description` | 原始成就描述；缺失时空列 |
| `type` | 本行候选标签，八类之一 |
| `method` | 分类来源；当前新流程为deepseek |
| `confidence` | 模型对本标签自报的有限数0～1 |
| `status` | 本候选筛选后的suggested/uncertain，不保证等于因保护而保留的SQLite状态 |
| `sqlite_outcome` | 整项成就的处理结果；同一成就的多行可以相同 |
| `confidence_passed` | 本标签是否达到本次门槛，True/False；不表示一定写库 |
| `label_sqlite_outcome` | 本标签的实际处理结果，可区分同一成就中已有、补写及低分标签 |
| `knowledge_used` | 是否使用模型背景或模型知识判断 |
| `evidence` | 逐字原文引用，1～2段以` \| `拼接；原始数组见JSON |
| `reason` | 模型分类解释 |
| `uncertainty` | 判定疑点或不确定说明 |
| `request_hash` | 原始分类请求指纹；阈值变化不改变该指纹 |
| `min_confidence` | 最近一次累计更新所使用的门槛 |
| `confidence_comparison` | 当前比较符，固定`>=` |
| `source_csv` | 最近一次累计更新的来源CSV路径，不是全部来源列表 |
| `first_seen_at` | 该去重键首次进入累计表的带时区时间戳 |
| `last_seen_at` | 最近一次累计更新的带时区时间戳 |

`written`表示写入，`already_classified`表示保留已有机器结果，`protected`表示人工/排序保护，`unchanged`表示目标与当前结果一致，`below_threshold`表示该标签未达门槛。离线补录还可能出现`conflict`和`legacy_existing`；`pending`仅表示候选已保存、尚未确认SQLite提交。上述结果不能只看`confidence_passed`替代：例如一个多标签成就可同时有already_classified、written和below_threshold三种标签结果。

两份累计表使用相同的UTF-8 BOM、标准CSV转义，表格公式前缀会加单引号以便安全浏览；核验原始文本仍以SQLite和receipt/JSON为准。更新采用同一文件锁、校验旧表头/行及临时文件原子替换；这保证的是CSV单文件更新，**datacache、failure_data与SQLite不是跨文件事务**。若先留档后数据库失败，可能保留pending；若数据库已提交而CSV结果刷新失败，累计结果可能滞后，应查询SQLite并依据原始响应、报告恢复，不能仅凭CSV状态推断回滚。低分派生表若因文件错误未刷新，可从完整datacache单独重建；不要用它反向覆盖全量表或数据库。

缓存表收录的是格式、身份与证据校验有效的分类；低置信度有效结果可以留档，坏CSV、非原文evidence、无法验证的响应和过期游戏上下文不能冒充有效结果导入。旧CSV当时的`confidence_passed=false`是历史标记，导入时使用当前`>=0.6`重新筛选，并核对当前SQLite原始成就和所关联的完整响应。

历史导入入口默认只输出离线预检，显式`--apply`才写本地SQLite和累计CSV，不调用DeepSeek、不连接远端。以下命令从LYX目录执行：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/import_classification_cache.py
uv run --frozen --no-sync python -X utf8 -B process/import_classification_cache.py --apply
~~~

默认扫描`process/runtime/deepseek/runs`，可用`--source-root PATH`指定历史运行根目录；`--database PATH`、`--datacache PATH`分别指定本地库与累计表，`--min-confidence X`默认0.6且按`>=`比较。路径限制在LYX内。实际写库前备份，按成就身份核验后只补缺失的合格标签；已有机器标签不覆盖，人工确认、manual和非空mainline_index仍保护，不以导入为由重新排序。旧上下文、坏CSV或证据不合规的条目拒绝导入，并记录原因；此工具也不会修复这些原始响应。普通分类命令不必更改，之后每轮会同步累计缓存。

历史补录只有在已有标签的类型、分数及名称均与当前候选一致时，才补充同一成就缺失的其他合格标签；不相容结果记为`conflict`，保留SQLite原结果。早期v3抽样记录仅在原文及标签与当前库中已有结果一致时按`legacy_existing`归档，不按旧契约重新入库。累计CSV的`pending`表示候选已落盘但尚未确认提交；`label_sqlite_outcome`用于区分同一成就中已有、补录及低分的各个标签。累计CSV不代替SQLite的进度判断：低分仍待处理，重复回放只刷新累计记录，不增加相同请求的重复行。

普通`classify`的already_classified保护与离线补录的`merge_existing=True`用途不同：普通运行不补齐已完成成就的机器标签；需要整体重筛机器结果时用`--reclassify`。离线工具在不覆盖已有结果的前提下补缺，要求全部已有标签都是当前合格目标中的同类型、同方法、同分数、同展示名记录；只要有不相容项，整项记conflict而不补写。manual/approved/非空mainline_index在两条链路中都优先保护。

2026-10-15已完成一次历史缓存零API补录，具体数量和核验见[实验记录](experiments.md#2026-10-15)。后续分类数量以当前SQLite为准。

v6要求每段evidence严格小于500字符，即最多499字符；报告同时记录evidence_max_chars=500与evidence_length_comparison="<"，不能将500理解为允许的最大长度。v5原为最多150字符，v4原为最多60字符。当前仅对版本号和这条长度规则不同的v5/v4完整请求提供兼容回放：游戏输入、摘要、模型、接口及生成参数必须完全相同，响应重新通过v6的全部校验；其他版本或变化的输入不能套用。新v6缓存优先，旧receipt保留原样，调用元数据保留源prompt_version（v5或v4），并记录requested_prompt_version=v6及compatible_cache=true。此前因长度超限失败的响应可尝试--max-requests 0恢复；仍有其他错误时不会入库，失败游戏仍待处理。

用户已用以下缓存命令完成《重生》恢复：更新60项、保留已有1项，新请求0、缓存命中2，未处理0。再次普通运行会跳过；下列命令作为“有待处理项时只用缓存恢复”的示例，缓存缺失时仅暂停：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --game-name "FINAL FANTASY VII REBIRTH" --max-requests 0
~~~

### 请求总时限、等待进度与超时恢复

`--max-requests`只限制实际新请求次数；`--timeout-seconds`仍是每次网络读取等待的上限，不是整次调用的总时限。简介默认总时限90秒，分类默认300秒，连接上限仍15秒。总时限从该次逻辑调用首次网络尝试开始，到完整正文接收结束；有限重试和退避共用剩余时间，收到空行或少量保活数据不重新计时。HTTP传输使用可取消的异步客户端，超时会取消本地等待并关闭响应；业务仍逐款串行，API请求保持`stream=False`，模型输入、提示词版本及缓存指纹不因超时配置改变。

下面是在冻结清单上使用默认时限的显式写法；确需更长分类等待时可先评估后只增大分类总时限：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --max-requests 20 --intro-total-timeout-seconds 90 --classification-total-timeout-seconds 300
~~~

等待期间每15秒输出一次进度，并原子更新本轮`runs/<UTC时间>/progress.json`；没有收到数据时也更新。记录游戏/AppID、任务、attempt、request_count/max_requests、phase、elapsed/remaining、received_bytes、has_non_whitespace_body及last_data_at。阶段区分等待响应头、接收正文和退避等待；`has_non_whitespace_body=false`仅说明尚未观察到非空白正文，不能据此判断服务端有没有开始处理。该小文件用于查看当前请求，完整`report.json`仍保存游戏结果与整轮统计。

总时限到达或发生HTTP读超时，记本款`request_timeout`并继续下一款，不自动重发同一个超时请求。简介失败时不再请求本款分类；分类失败时保留已成功的简介缓存。已发生的HTTP尝试仍计入预算；本地取消不保证服务端也取消，未取得usage时用量为未知，不能当作零消耗。只有完整正文记`response_text`；未收完正文单独记`partial_response_text`及`response_complete=false`，不得作为可复用分类缓存或写库依据。旧receipt没有`response_complete`字段时按历史完整响应规则兼容，显式false始终不能复用。

简介和分类分别累计连续超时次数。同类实际收到完整HTTP 200响应即清零（即使后续内容校验失败），缓存命中不清零；同类连续3次超时暂停整轮，报告`state=service_paused`、`paused_reason`及`consecutive_timeouts`，退出码1。零星超时后遍历结束记`completed_with_errors`、退出码1；`timeout_game_count`和`timeout_appids`列出超时款，并同时计入`failed_game_count/failed_appids`。预算先耗尽仍为`budget_reached`，之前的失败记录保留。

429、TLS/认证/余额错误、其他非读超时网络故障以及SQLite/文件错误仍停止整轮；连接错误或5xx仅沿用有限退避，共享本次总时限和请求预算，不无限重试。Ctrl+C沿用正常中断收尾，保存`interrupted`；没有独立停止命令或停止标记。

## 简介、结构化输入与结果

简介只根据游戏中英文名及valve_genres生成40～80字符中文摘要；v2将写作目标定为55～65字符，追加合规格式示例与输出前长度检查，硬性范围不变；recognized=false时摘要为空且说明原因。它是模型背景摘要，不是Steam官方介绍；source=model_generated。简介不生成章节、成就条件、等级上限等细节，不修改SQLite六表，不抓网站。

分类输入顺序固定为：CLASSIFICATION_PROMPT → <game_context>名称、官方类型、模型摘要及来源/疑点 → <achievement_batch>全部成就名称和描述。原始成就条件优先，使用模型摘要或模型知识判断须声明knowledge_used及疑点。

输出仍是八类多标签、各类confidence、原文evidence、reason、uncertainty和knowledge_used。evidence是DeepSeek逐字引用的本项名称或描述，reason才是模型的分类解释；引用不允许来自背景摘要或其他成就，也不能证明分类语义一定正确。原文匹配优先逐字比较，仅兼容U+00A0与普通空格；大小写改写、额外说明和空引用仍拒绝，报告标明evidence_match_policy=exact_or_nbsp_space。v7提示词明确要求保留大小写、描述为空时引用展示名、knowledge_used=true时填写待核验事项；不增加自动纠错请求。普通升级/成长不因数值目标自动归challenge。reason/uncertainty最多40字符，evidence为1～2段非空原文、每段严格小于500字符，即最多499字符（Python len计数，含空格与标点），对应DataAgent.EVIDENCE_MAX_CHARS的排他上界。500字符本身不通过。超长、空引用、非原文引用分别报告成就ID/名称及原因。完整ID覆盖、闭集、互斥、长度与有限数检查全部通过后才进入逐标签门槛筛选及落库。

SQLite标签表保存appid/api_name/display_name/type/method/confidence，成就表保存状态。display_name来自对应原始成就，分类入库自动填写，来源改名时触发器同步；当前user_version=4。--min-confidence默认0.6，是逐标签写入门槛：confidence >= 0.6通过，等于0.6也通过。例如mainline=0.6、challenge=0.55只存mainline；低分标签不拖累高分标签。confidence是模型自报的判断信心，不是经过校准的正确概率，0.6不能直接解释为60%准确率。通过的明确类别为suggested；独占的unknown也按相同门槛筛选，通过后仍为uncertain。不生成approved或排序号。

所有原始模型标签保留在runtime JSON的types中，同时单列accepted_types和rejected_types；有效分类的全部标签也累计到process/datacache.csv，包含未过门槛和已有结果。全部未通过时sqlite_outcome=below_threshold，不删除旧标签、不改原有status，仍计入待处理；原先pending继续pending。已有DeepSeek/人工结果的保护规则仍生效，不主动清理历史低分结果。普通分类需要重筛已有机器结果时显式加--reclassify；历史导入工具只补新标签，不覆盖已有机器/人工结果。阈值是本地后处理参数，不进入API提示词或请求指纹；比较符为>=，分类prompt为v7，同一完整输入可用--max-requests 0复用缓存筛选，无额外请求。report记录confidence_comparison=">="，CSV的confidence_passed和各类入库计数使用同一比较规则。格式错误仍拒绝整款，原始错误响应留在receipt JSON；该游戏记录response_error及失败阶段，继续处理后续游戏，不把错误转换为unknown。

## 预算、恢复与缓存统计

- 每轮classify先完整备份为运行目录before_classify.sqlite。HTTP发生在SQLite事务外。
- 完整响应先持久化再校验/写库；收到完整响应后中断可缓存恢复。部分响应单独留档且不进入缓存。简介和分类复用同一客户端，不各自超发预算。
- 写入前检查名称/类型和整款成就集合/文本；新增、删除或变化都会回滚整款，避免把旧响应配给变化的输入。人工成果和已有机器结果在写入时再次保护。
- 输出预算估计为1024+160×完整成就数，默认上限65536；输入字符阈值默认300000。超过任一配置限制为oversized_game，单列跳过，不自动拆分。可在plan评估后显式调整预算，估计不是输出保证。
- HTTP读超时默认300秒，简介/分类总时限分别90/300秒；连接超时15秒。读超时或总时限到达按单游戏记request_timeout，不自动重发；同类连续3次超时service_paused。HTTP 200响应的JSON/截断/契约错误仍按单游戏记response_error。两类失败都不转unknown，已提交其他游戏不回滚。
- 报告failed_game_count和failed_appids列出本轮响应失败、超时及终止本轮的传输失败游戏，errors保留局部及整体错误；timeout_game_count/timeout_appids、consecutive_timeouts和paused_reason单列超时与暂停信息。游戏项的error、failure_stage、failure_task、failure_receipt和failed_request_hash及calls可定位原始/部分响应。传输异常另记录error_type类名，receipt直接保存AppID/游戏名；仍按原策略停止整轮，不计作超时，不记录可能携带凭据的原始异常正文。遍历结束仍有失败时state=completed_with_errors、退出码1；失败款原有数据保留且仍待处理，后续可重跑恢复。预算提前耗尽时仍为budget_reached，同时保留此前失败计数，不能将它理解为无错误。
- state=budget_reached意味着尚有工作；service_paused表示连续超时触发暂停；success_with_skips表示大型游戏未处理；success_with_rejections表示有待处理成就全部标签未过门槛。remaining_pending_count和unprocessed_achievement_count包含这些未写项，不能只看退出码或classified_count（完整模型覆盖数）。accepted/rejected_label_count统计本轮模型标签筛选，包含保护项；written_label_count才是实际写入的标签数，sqlite_counts.written为写入成就数。纯正常结束退出码0；completed_with_errors、service_paused及整体error应按失败处理。

report.type_counts/unknown_count统计本轮完整模型候选，并非SQLite累计类型分布；旧项被保护或already_classified时，候选类型可能与被保留的数据库类型不同。核查实际分布应查询achievement_types。

local_response_cache_hits（兼容旧cache_hits）是本地响应复用次数。api_cache_hit_tokens/api_cache_miss_tokens/api_cache_hit_ratio来自本轮真实API响应，usage_by_task分开汇总简介与分类；缺失用量保持null，历史缓存用量不重复统计。

历史运行曾在大量缓存复用后仅对下一款发出新请求，也曾在预算暂停前成功提交部分游戏；这些都符合上述预算与缓存规则。实际请求、候选及写入量分别核对，案例和报告见[实验记录](experiments.md)。

环境变量优先、根.env回退：DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL。官方HTTPS入口、TLS校验和密钥脱敏保留。真实验收记录见[experiments.md](experiments.md)，当前覆盖见[DATABASE.md](DATABASE.md)。
