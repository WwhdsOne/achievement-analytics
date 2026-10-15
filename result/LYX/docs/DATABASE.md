# LYX本地SQLite数据说明

更新：2026-10-15。当前库为[achievements.sqlite](../database/achievements.sqlite)，结构见[schema.sql](../database/schema.sql)，user_version=4。DeepSeek分类结果写入本地标签关系与状态；三类时长来自远端hltb_games，guide_difficulty来自game_difficulty.hard_ratio，保留两位小数。共享PostgreSQL永远只读。来源归类见下文，今天的迁移记录见文末。

## 当前实际数据

### 成就分类进度：2026-10-15 23:13

以下为北京时间23:13核对本地SQLite得到的进度快照，统计范围为冻结的1000款游戏。

| 状态 | 游戏数量 |
|---|---:|
| 已有 DeepSeek 分类结果入库 | **731 款** |
| 其中整款全部完成 | **598 款** |
| 其中仍有部分成就待处理 | **133 款** |
| 总计仍需处理，包含上述 133 款 | **398 款** |

另外 **4 款没有成就**。

成就总量及进度：

| 状态 | 成就数量 |
|---|---:|
| **总成就数量** | **71,465 个** |
| DeepSeek 已完成分类 | **43,284 个** |
| 受保护、无需自动处理 | **18 个** |
| 仍需处理 | **28,163 个** |

整款完成数、部分完成数和成就完成数分别统计；以上是本次核查的固定快照，后续运行的实际进度以本地SQLite为准。

### 数据表行数历史快照：2026-10-15 22:33

下表为2026-10-15 22:33北京时间的本地只读核查快照；分类仍在推进，数量不是实时进度：

| 表 | 行数 | 用途 |
|---|---:|---|
| games | 1000 | 游戏身份、中英文名 |
| games_details | 1000 | 官方细节；分类使用valve_genres |
| games_rate | 1000 | 历史评价/评分；分类不使用 |
| games_time | 1000 | RAWG时长、HLTB三类时长与hard_ratio指标；分类不使用 |
| achievements | 71465 | 原始成就、状态、既有排序 |
| achievement_types | 39943 | 展示名、多类型及方法、置信度 |

标签关系覆盖37,364项成就、涉及617款游戏，其中deepseek 39,925行、覆盖37,346项；rule 18行、覆盖18项。status为pending 34,101、suggested 32,247、uncertain 5,117、approved 0；18项非空mainline_index集中在1款游戏，仍保留。覆盖某款游戏不表示该款已全部分类，标签行数也不等于成就数。历史迁移及阶段验收统一见[实验记录](experiments.md)。

清单：[top1000_appids.json](../database/data/top1000_appids.json)，排名明细：[top1000_selection.json](../database/data/top1000_selection.json)。996款有成就、4款无成就。status='pending'统计原记录状态；分类器待处理数还需考虑旧rule/jev结果和人工/排序保护，不能与该状态计数混用。累计CSV按请求保留候选，也不能直接与SQLite关系数相减。

展示名迁移时的完整备份：[achievements.sqlite](../database/backups/20261014T125409120039Z-display-names/achievements.sqlite)，同目录migration.json记录当时127条名称回填；这份备份早于后续分类，不是当前标签快照。2026-10-14后续核查时168条标签的展示名均与来源一致。每轮classify另生成before_classify.sqlite，保护当轮写入前状态。SQLite适合当前个人规模，使用短事务，保持DELETE日志模式。

## 六表字段

| 表 | 字段与SQLite类型 | 主键/来源 |
|---|---|---|
| games | appid INTEGER；name_en TEXT非空；name_zh TEXT可空 | appid；远端games |
| games_details | appid INTEGER；is_free INTEGER；price_cents INTEGER；release_date TEXT；valve_genres TEXT | appid；steam_appdetails |
| games_rate | appid INTEGER；review_label TEXT；review_percent INTEGER；review_count INTEGER；metacritic INTEGER；rating NUMERIC(3,2) | appid；store_search_games+rawg_games |
| games_time | appid INTEGER；playtime INTEGER；main_hours REAL；extra_hours REAL；completionist_hours REAL；guide_difficulty REAL | appid；playtime来自rawg_games，三类时长来自hltb_games，当前难度为game_difficulty.hard_ratio |
| achievements | appid INTEGER；position INTEGER；api_name TEXT；display_name TEXT；description TEXT；percent NUMERIC(5,2)；status TEXT；mainline_index INTEGER | (appid,api_name)，另有(appid,position)唯一 |
| achievement_types | appid INTEGER；api_name TEXT；display_name TEXT非空；type TEXT；method TEXT；confidence REAL | (appid,api_name,type)，外键关联成就 |

约束与口径：

- is_free为NULL或0/1；price_cents非负，沿用来源计价单位；release_date为来源日期文本。
- review_percent/metacritic为0～100；review_count非负；rating为0～5、最多两位小数，均可空。
- playtime为RAWG非负小时或NULL；三类HLTB时长为非负有限小时或NULL，guide_difficulty为hard_ratio的0～1值或NULL。具体来源、缺失与导入数量见下节。
- position≥1是来源排列，不是剧情顺序；api_name是身份键，展示使用display_name，description可空。
- percent为0～100、两位小数，0有效；CHECK落实范围与小数位，导入用Decimal四舍五入。分类不读取它。
- mainline_index≥1或NULL，单游戏非空值唯一，必须有mainline标签；移除mainline会清空排序。本分类任务不填写它。
- confidence为0～1或NULL；模型输入校验拒绝非有限数，历史规则/人工不虚构分数。

valve_genres将PostgreSQL TEXT[]转为CSV转义的“|”分隔文本，不存JSON。Action|RPG为普通例子；含分隔符/引号时按CSV规则转义。用local_database.encode_genres/decode_genres，不直接split('|')；NULL表示缺失，空文本表示来源空数组。它仅为官方类型，不是完整用户标签；不建立game_tags表。

achievement_types.display_name与achievements.display_name使用相同的TEXT非空/非空白约束，按(appid,api_name)复制，便于直接浏览标签表；它不参与主键，同名成就不会混淆身份。分类/导入写入时同步填写；achievements_display_name_sync触发器在来源名称改变时更新该成就所有标签行。来源仍以achievements为准，不用api_name推测名称。

## 时长与难度口径

### HLTB三类时长

- **来源与字段：** 按冻结1000个AppID只读复制远端public.hltb_games：main_hours为主线耗时，extra_hours为主线加额外内容耗时，completionist_hours为完整游玩耗时，单位均为小时。只按AppID关联，不做名称匹配或版本推断；不与RAWG playtime混用。
- **导入数量：** 2026-10-15匹配347款、缺行653款，三列各347个非空、653个NULL；零值分别17、24、26个，按源保留，不视为已核实的零小时。
- **缺失与结构：** 导入时来源缺行或字段NULL写NULL，不填0。schema3→4已物理删除guide_time_hours_min/max，旧攻略时间不转换为HLTB值，历史值保留在迁移前备份。
- **维护状态：** 一次性HLTB导入脚本已移除；既有三类时长、playtime、guide_difficulty及其余五表保留。来源快照、报告与完整备份见文末迁移记录，远端更新不会自动同步到本地。

### hard_ratio难度指标

- **来源与定义：** 按本地games_time全部1000个AppID只读复制远端public.game_difficulty.hard_ratio。视图按成就appid聚合，计算完成率percent<10%的成就占比，表达式为`avg(CASE WHEN percent < 10 THEN 1.0 ELSE 0.0 END)`；范围不限于347款HLTB子集。
- **数值口径：** 写入guide_difficulty，值域0～1或NULL，Decimal ROUND_HALF_UP保留两位（如0.125→0.13），不乘10或100。SQLite类型仍REAL，schema仍4；旧CHECK允许0～10，导入器额外验证0～1。显示0.5与0.50数值相同。
- **导入数量：** 2026-10-15匹配996款、缺行4款；996个有效值中68个为0，替换此前52个攻略评分。缺行AppID为511960、1404210、1962663、3028330，均保留NULL；来源NULL同样写NULL，不将缺失填0。
- **解释与维护：** 这是低完成率成就占比，与成就完成率同源，会受主线、DLC、联机等成就构成影响，不能独立证明操作难度，也不是旧攻略十分制。一次性hard_ratio导入脚本已移除；既有guide_difficulty、时长、其他表和结构保留，远端更新不会自动同步到本地。

以上来源读取时刻是云库快照时间，不是网站采集时刻。两类字段均不进入DeepSeek分类输入；旧攻略获取方式见[实验记录](experiments.md#旧攻略获取方式已弃用)。

## 模型摘要与整款分类

模型背景摘要只保存在既有runtime响应缓存和运行报告，source=model_generated，不作为官方说明或成就条件证据。没有摘要列、SQLite JSON字段或新增表；标签展示名扩展发生在版本3，当前user_version=4来自games_time的HLTB时长结构更新。

一款有待处理项时模型收到全部原始成就，默认写入只更新待处理项；已有DeepSeek结果记already_classified，--reclassify才更新机器结果，人工/排序保护不变。落库前比较完整成就集合、文本与游戏上下文；新增、删除或改变也会拒绝整款。

输出估计超默认预算的游戏单列跳过，不自动拆分；详见[运行说明](PROCESS.md)。历史默认预检有16款超规模游戏，当前数量以plan为准。

## 分类关系与状态

八类mainline/side/collection/challenge/multiplayer/dlc/other/unknown，每标签一行，允许多标签，unknown必须独占，触发器同时约束插入/更新。

method允许deepseek/jev/rule/manual，不支持hybrid。新流程仅写deepseek，其他值保留兼容历史记录，不运行其他方法。

| status | 含义 |
|---|---|
| pending | 尚无当前分类结果 |
| suggested | 本次写入的明确类别均达到置信度门槛（包含等于）；兼容历史规则状态 |
| uncertain | 本次通过门槛的unknown；兼容历史低分机器/规则状态 |
| approved | 既有人工确认；分类器不生成 |

阈值默认0.6，逐标签按confidence >= 0.6筛选，等于门槛也通过；多标签独立筛选。低分标签留在runtime JSON及process/datacache.csv，不进入achievement_types；另同步派生到同目录[failure_data.csv](../process/failure_data.csv)，方便人工复核。累计CSV同时保留已有、受保护与本轮写入的有效分类标签，每标签一行，按(appid,api_name,type,request_hash)去重，并用source_csv/first_seen_at/last_seen_at追溯；它不是新增业务表，不改变SQLite六表和schema版本4。全部未通过时不替换旧标签、不更新原有status；旧pending保持pending。unknown也按相同门槛筛选，通过后仍标uncertain。confidence是模型自报信心，不代表校准后的正确概率或准确率，suggested仍不能说成人工确认；历史低分数据不会自动删除。

failure_data与datacache同为22列，只选`confidence < 本行min_confidence`的标签，不选恰好达到门槛者。它保留各request_hash的低分历史；同成就后来已有合格标签，旧请求的低分判断仍可能在表内，因此不能将行数当作当前未入库成就数。结构/证据失败、网络失败及已达门槛的conflict不会因未写库而进入此表。独立重建只读取全量CSV并生成派生表，不查询或修改SQLite；日常分类及历史导入实际保存时自动刷新，离线plan不生成。

历史CSV通过[import_classification_cache.py](../process/import_classification_cache.py)离线复核和补写，默认预检，--apply才实际保存。实际写库先备份，核对当前原始成就和关联完整响应后，仅补缺失且达到当前门槛的标签；已有机器/人工结果及主线排序保护，旧上下文、坏CSV与证据不合规项拒绝导入并报告。每款有效分类先累计留档，再提交SQLite、刷新写入结果；历史runtime文件保留。操作命令见[累计分类CSV与历史结果导入](PROCESS.md#累计分类csv与历史结果导入)。

写库前的身份、原文、完整ID覆盖、八类闭集、unknown互斥、有限数、逐字evidence及长度校验先于置信度筛选；低分不能掩盖格式或证据错误。evidence为1～2段本成就名称/描述逐字片段，每段严格小于500字符，reason才是分类解释。这些检查只证明输出契约合规，不能替代人工判断标签语义是否正确。

普通classify默认跳过已完成机器结果；离线补录则使用merge_existing补齐缺失标签，要求全部已有标签的类型、method、confidence、展示名都包含于当前合格目标中，保留相容已有行，只插入缺失行；否则整项记conflict，不覆盖或部分补写。v3早期单条试跑只有与当前库原文和已有标签一致时按legacy_existing归档，不按旧输出契约新增关系。两条链路均保护approved、manual和非空mainline_index；日常显式--reclassify才允许整体重筛机器结果。

原始receipt保存请求及完整/部分响应；每轮report/CSV保存当轮候选与处理统计；累计datacache保存跨轮有效候选，failure_data为其中低分标签的派生快照；SQLite保存实际采用的关系。累计CSV不能直接驱动跳过，也不是SQLite事实副本；status和sqlite_outcome可反映候选处理，而confidence_passed、label_sqlite_outcome逐标签解释筛选和存储，22列字典见[四层产物与累计表字段](PROCESS.md#四层产物与累计表字段)。SQLite以单游戏事务提交，两份CSV在同一文件锁内各自以临时文件原子替换，三个文件不是跨文件事务；failure_data刷新失败可从datacache独立重建。累计pending表示尚未确认提交，异常时应以SQLite查询核实是否已提交，并保留原始响应/报告追溯，不能把pending当成业务成就状态已回滚。

DataAgent按(appid,api_name)写入；整批校验后BEGIN IMMEDIATE替换自动标签并更新状态。文本/上下文改变回滚；approved、manual标签、非空排序号在选择和落库时都保护。重复相同结果无变更；不改变原始字段及游戏级表。

理由、原文、不确定说明、模型/提示词指纹保存在runtime报告；types保留全部标签，accepted_types/rejected_types分别记录通过及未通过门槛的标签，不新增SQLite JSON列或历史表。默认跳过已完成DeepSeek项，包括uncertain；--reclassify重筛机器结果且仍保护人工成果。阈值不影响请求指纹，相同输入的完整缓存可直接重筛。

没有待处理项的整款游戏会跳过简介及分类请求；仍会读取本地数据库确定进度。历史恢复验收中，《重生》61项全部deepseek，其中60项suggested、1项旧uncertain按默认规则保留。本轮机器候选统计与实际被保留的类型可以不同，不用report.type_counts替代数据库类型分布。

method约束此前已迁移。展示名扩展由[migrate_display_names.py](../process/migrate_display_names.py)执行[迁移SQL](../database/migrate_display_names.sql)：先备份、事务重建标签表并回填，再恢复全部索引/触发器，检查原字段、名称对应、完整性和外键；失败回滚，重复运行无变化，版本3/4中名称不一致也可从来源修复。ensure_schema日常要求版本4；schema.sql可初始化新空库，不是日常启动步骤。旧标签迁移仅将版本2升到3，版本3/4修复保留原时间结构与版本，不隐式执行HLTB迁移。migrate_methods仍兼容旧method结构并填写名称。

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/migrate_display_names.py
~~~

本库已经迁移，无需再次执行。旧版2数据库备份可使用此命令升级；备份文件保留原样。

## 数据来源与缺口

| 类别 | 当前来源 → 本地落点 | 口径 |
|---|---|---|
| 冻结选样 | 远端store_search_games → top1000清单 | review_count非NULL，按review_count DESC、appid ASC取1000款；不额外按年份、类型、成就数筛选 |
| 游戏身份与官方属性 | 远端games、steam_appdetails → games、games_details | 中英文名、价格、发售日和官方类型；按AppID关联 |
| 评价、评分及原有时长 | 远端store_search_games、rawg_games → games_rate、games_time.playtime | 评价来自商店搜索；metacritic/rating/playtime来自RAWG表；已知版本疑点保留缺失 |
| 成就原文与完成率 | 远端achievements → 本地achievements | 展示名、描述、percent；两款FF7保留旧API试跑的124项原文，避免云端映射冲突覆盖 |
| 三类参考耗时 | 远端hltb_games → games_time.main_hours/extra_hours/completionist_hours | 仅按AppID复制小时值；347款有值，653款缺行；0与NULL分别保留 |
| 低完成率成就占比 | 远端game_difficulty.hard_ratio → games_time.guide_difficulty | percent<10%的成就占比，四舍五入两位；996款有值、4款NULL，替代旧攻略评分 |
| 分类与排序 | DeepSeek有效结果及本地既有标注 → achievement_types、achievements状态/排序 | 新流程只写deepseek；历史rule和既有排序受保护；模型不生成人工批准或剧情顺序 |

基础迁移见[IMPORT_SNAPSHOT.md](IMPORT_SNAPSHOT.md)，时长与难度详见[字段口径](#时长与难度口径)。模型简介只存外部缓存，旧Gamer Guides时间/评分只保留历史证据，不再作为当前列的数据来源。

前1000款按review_count DESC、appid ASC冻结，评价数7326～634194。远端曾优先读取PyCharm XML，缺完整凭据后由根.env+psycopg连接成功，连接和每批事务强制只读。各批REPEATABLE READ READ ONLY，源/批次时间不宣称同步。本轮没有连接远端。

本地9942项描述缺失，1款名称映射未解决，1款缺发行日，24款无RAWG。两款FF7部分云端描述/API名映射与旧API报告冲突，保留本地124项；重制版RAWG版本匹配存疑，评分/时长未纳入。缺口保留，信息不足允许unknown，不捏造确定事实。

来源与快照在database/data和process/runtime/remote_import/20261014T081042433830Z保存，迁移备份为该目录before_import.sqlite。见[IMPORT_SNAPSHOT.md](IMPORT_SNAPSHOT.md)。日常分类不连远端、不采集攻略。

数据库、原始数据、缓存和备份Git忽略；冻结选样的两个top1000 JSON已跟踪保留。database目录的SQL沿用既有忽略规则。历史实验路径是当时记录，不保证旧文件仍存在。

## PyCharm连接与核查

文件路径保持：D:\PycharmProjects\achievement-analytics\result\LYX\database\achievements.sqlite。

Database工具窗口Refresh/Synchronize；必要时重新连接，无需重建或改路径。手工SQL先启用foreign_keys。

~~~sql
PRAGMA foreign_keys=ON;
PRAGMA integrity_check;
PRAGMA foreign_key_check;
SELECT status,COUNT(*) FROM achievements GROUP BY status;
SELECT method,COUNT(*) FROM achievement_types GROUP BY method;
SELECT COUNT(*) AS display_name_issues
FROM achievement_types t LEFT JOIN achievements a USING(appid,api_name)
WHERE a.api_name IS NULL OR t.display_name IS NULL
   OR length(trim(t.display_name))=0 OR t.display_name IS NOT a.display_name;
SELECT appid,api_name,display_name,type,method,confidence
FROM achievement_types
ORDER BY appid,api_name,type;
SELECT a.appid,a.display_name,t.type,t.confidence,a.status
FROM achievements a JOIN achievement_types t USING(appid,api_name)
WHERE t.method='deepseek'
ORDER BY a.appid,a.position,t.type;
~~~

每轮classify自动生成before_classify.sqlite。命令与恢复见[PROCESS.md](PROCESS.md)，不要日常运行旧重建或probe导入。

## 2026-10-15 迁移记录

| 时间（北京时间） | 动作与结果 |
|---|---|
| 10:53 | HLTB时长迁移：schema3→4，物理删除guide_time_hours_min/max，新增三类HLTB时长；1000款中347款匹配、653款保留NULL。原playtime、当时11个攻略评分及其余五表保持一致。 |
| 11:06 | 分类门槛改为confidence>=0.6后，离线复核历史缓存，补录74条边界标签；已有标签、原始字段及18项排序保留，冲突不覆盖；schema仍为4。 |
| 20:08 | 从累计datacache初始化failure_data.csv：当时20,036条候选中提取1,146条低分标签；不修改SQLite或全量CSV，不新增API请求。 |
| 21:49 | 难度来源切换：全1000款按AppID同步game_difficulty.hard_ratio，保留两位；996款有效、4款NULL，替换此前52个攻略评分。只更新guide_difficulty，schema、时长及其余五表保持一致。 |

两次数据库来源迁移均先完整备份、再在本地事务内写入，完整性与外键核验通过；远端全程只读。HLTB[报告与备份](../process/runtime/hltb_import/2026-10-15T025331.038271_0000-360a6a2d/)、分类补录[报告与备份](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/)、hard_ratio[报告与备份](../process/runtime/hard_ratio_import/2026-10-15T134935.565882+0000-07f58359/)保存在本地忽略目录。旧攻略试采、跨平台及人工确认过程归入[当日实验记录](experiments.md#2026-10-15)。
