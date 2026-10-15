# LYX本地SQLite数据说明

更新：2026-10-15。当前库为[achievements.sqlite](../database/achievements.sqlite)，结构见[schema.sql](../database/schema.sql)，user_version=4。分类入口仍为DeepSeek自动分类并写入本地标签关系与状态；HLTB三类时长按AppID只读复制远端hltb_games，攻略入口仅补guide_difficulty，共享PostgreSQL永远只读。同步操作与验收见[HLTB_TIME.md](HLTB_TIME.md)。

## 当前实际数据

下表为2026-10-15 14:54北京时间的本地只读核查快照，不是每次启动时固定的行数：

| 表 | 行数 | 用途 |
|---|---:|---|
| games | 1000 | 游戏身份、中英文名 |
| games_details | 1000 | 官方细节；分类使用valve_genres |
| games_rate | 1000 | 历史评价/评分；分类不使用 |
| games_time | 1000 | RAWG时长、HLTB三类时长与攻略难度；分类不使用 |
| achievements | 71465 | 原始成就、状态、既有排序 |
| achievement_types | 2271 | 展示名、多类型及方法、置信度 |

当前标签关系覆盖2146项成就：deepseek 2205行、覆盖2083项；rule 66行、覆盖63项。成就status为pending 69,319、suggested 1,874、uncertain 272、approved 0；18项非空mainline_index仍保留。已有标签不一定代表当前DeepSeek链路已完成，尤其历史rule项仍按分类器的状态、方法与保护规则计算。confidence恰为0.6的DeepSeek关系有74行，当前门槛允许这些结果入库。累计datacache.csv为2313行、低分107行；CSV按请求保留候选，不能与2271条SQLite关系或2146项成就直接相减。

保留今天不同阶段的历史验收，便于解释行数变化：

| 阶段 | 标签行数 | 标签覆盖成就数 | 累计CSV行数 | 含义 |
|---|---:|---:|---:|---|
| HLTB迁移完成时 | 2148 | 2029 | 尚未建立本次累计表 | deepseek 2082行、rule 66行；状态pending 69,436、suggested 1,759、uncertain 270 |
| 11:06置信度补录完成 | 2222 | 2097 | 2264 | 新增74标签，其中68项原未分类、6项已有成就补标签；保留1项冲突 |
| 14:54只读复核 | 2271 | 2146 | 2313 | 后续运行新增49项成就/49标签；不是再次执行HLTB迁移 |

HLTB迁移当时的验收结论仍保留：迁移前后其余五表全部数据，以及games_time的appid/playtime/guide_difficulty摘要完全一致，六表行数不变。分类后续可继续增加标签和改变状态，最新值以SQLite只读查询为准。11:06补录的[报告](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/report.json)和[核验记录](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/verification.json)记录了原始字段、既有标签和人工排序保留；14:41后续运行见[报告](../process/runtime/deepseek/runs/20261015T064109506808Z/report.json)。

保留2026-10-14 13:58 UTC历史核查：当时标签168条，status为pending 71,303、suggested 125、uncertain 37、approved 0；类型关系为deepseek 102、rule 66。DeepSeek关系覆盖99项成就、2款游戏：重生61项/61条类型，HELLDIVERS™ 2为38项/41条多标签关系。18项非空mainline_index保留，当时user_version=3。这些历史计数不代表当前分类覆盖。

清单：[top1000_appids.json](../database/data/top1000_appids.json)，排名明细：[top1000_selection.json](../database/data/top1000_selection.json)。996款有成就、4款无成就；上述2026-10-14快照默认保护18项，已有99项取得DeepSeek结果，71,348项待处理。status='pending'统计原记录状态；分类器待处理数还包含未转换的rule/jev结果，二者不能混为同一个指标。

展示名迁移时的完整备份：[achievements.sqlite](../database/backups/20261014T125409120039Z-display-names/achievements.sqlite)，同目录migration.json记录当时127条名称回填；这份备份早于后续分类，不是当前标签快照。上述历史核查时168条展示名均与来源成就一致，空缺0。每轮classify另生成before_classify.sqlite，保护当轮写入前状态。SQLite适合当前个人规模，使用短事务，保持DELETE日志模式。

## 六表字段

| 表 | 字段与SQLite类型 | 主键/来源 |
|---|---|---|
| games | appid INTEGER；name_en TEXT非空；name_zh TEXT可空 | appid；远端games |
| games_details | appid INTEGER；is_free INTEGER；price_cents INTEGER；release_date TEXT；valve_genres TEXT | appid；steam_appdetails |
| games_rate | appid INTEGER；review_label TEXT；review_percent INTEGER；review_count INTEGER；metacritic INTEGER；rating NUMERIC(3,2) | appid；store_search_games+rawg_games |
| games_time | appid INTEGER；playtime INTEGER；main_hours REAL；extra_hours REAL；completionist_hours REAL；guide_difficulty REAL | appid；playtime来自rawg_games，三类时长来自hltb_games，攻略入口仅补难度 |
| achievements | appid INTEGER；position INTEGER；api_name TEXT；display_name TEXT；description TEXT；percent NUMERIC(5,2)；status TEXT；mainline_index INTEGER | (appid,api_name)，另有(appid,position)唯一 |
| achievement_types | appid INTEGER；api_name TEXT；display_name TEXT非空；type TEXT；method TEXT；confidence REAL | (appid,api_name,type)，外键关联成就 |

约束与口径：

- is_free为NULL或0/1；price_cents非负，沿用来源计价单位；release_date为来源日期文本。
- review_percent/metacritic为0～100；review_count非负；rating为0～5、最多两位小数，均可空。
- playtime为非负小时或NULL；main_hours、extra_hours、completionist_hours为非负有限小时或NULL，分别复制远端hltb_games对应字段；guide_difficulty为0～10或NULL。仅按AppID查询，无来源行时三类时长均置NULL，不增加名称匹配或版本推断，来源0原样保留。2026-10-15真实导入1000款，三类时长各覆盖347款、各缺653；来源0分别17、24、26条，原guide_difficulty覆盖11款并完整保留。旧guide_time_hours_min/max已物理删列，旧DOM时间不转换成HLTB值，也不再由攻略程序落库。HLTB流程与当前覆盖查询见[HLTB_TIME.md](HLTB_TIME.md)，难度批量操作见[GUIDE_AGENT.md](GUIDE_AGENT.md)。分类不使用这些值。
- position≥1是来源排列，不是剧情顺序；api_name是身份键，展示使用display_name，description可空。
- percent为0～100、两位小数，0有效；CHECK落实范围与小数位，导入用Decimal四舍五入。分类不读取它。
- mainline_index≥1或NULL，单游戏非空值唯一，必须有mainline标签；移除mainline会清空排序。本分类任务不填写它。
- confidence为0～1或NULL；模型输入校验拒绝非有限数，历史规则/人工不虚构分数。

valve_genres将PostgreSQL TEXT[]转为CSV转义的“|”分隔文本，不存JSON。Action|RPG为普通例子；含分隔符/引号时按CSV规则转义。用local_database.encode_genres/decode_genres，不直接split('|')；NULL表示缺失，空文本表示来源空数组。它仅为官方类型，不是完整用户标签；不建立game_tags表。

achievement_types.display_name与achievements.display_name使用相同的TEXT非空/非空白约束，按(appid,api_name)复制，便于直接浏览标签表；它不参与主键，同名成就不会混淆身份。分类/导入写入时同步填写；achievements_display_name_sync触发器在来源名称改变时更新该成就所有标签行。来源仍以achievements为准，不用api_name推测名称。

## 模型摘要与整款分类

模型背景摘要只保存在既有runtime响应缓存和运行报告，source=model_generated，不作为官方说明或成就条件证据。没有摘要列、SQLite JSON字段或新增表；标签展示名扩展发生在版本3，当前user_version=4来自games_time的HLTB时长结构更新。

一款有待处理项时模型收到全部原始成就，默认写入只更新待处理项；已有DeepSeek结果记already_classified，--reclassify才更新机器结果，人工/排序保护不变。落库前比较完整成就集合、文本与游戏上下文；新增、删除或改变也会拒绝整款。

输出估计超默认预算的16款游戏单列跳过，不自动拆分；详见[运行说明](PROCESS.md)。用户已完成重生整款缓存恢复及HELLDIVERS™ 2的新分类；本次文档核查不写实际库。

## 分类关系与状态

八类mainline/side/collection/challenge/multiplayer/dlc/other/unknown，每标签一行，允许多标签，unknown必须独占，触发器同时约束插入/更新。

method允许deepseek/jev/rule/manual，不支持hybrid。新流程仅写deepseek，其他值保留兼容历史记录，不运行其他方法。

| status | 含义 |
|---|---|
| pending | 尚无当前分类结果 |
| suggested | 本次写入的明确类别均达到置信度门槛（包含等于）；兼容历史规则状态 |
| uncertain | 本次通过门槛的unknown；兼容历史低分机器/规则状态 |
| approved | 既有人工确认；分类器不生成 |

阈值默认0.6，逐标签按confidence >= 0.6筛选，等于门槛也通过；多标签独立筛选。低分标签留在runtime JSON及process/datacache.csv，不进入achievement_types。累计CSV同时保留已有、受保护与本轮写入的有效分类标签，每标签一行，按(appid,api_name,type,request_hash)去重，并用source_csv/first_seen_at/last_seen_at追溯；它不是新增业务表，不改变SQLite六表和schema版本4。全部未通过时不替换旧标签、不更新原有status；旧pending保持pending。unknown也按相同门槛筛选，通过后仍标uncertain。confidence是模型自报信心，不代表校准后的正确概率或准确率，suggested仍不能说成人工确认；历史低分数据不会自动删除。

历史CSV通过[import_classification_cache.py](../process/import_classification_cache.py)离线复核和补写，默认预检，--apply才实际保存。实际写库先备份，核对当前原始成就和关联完整响应后，仅补缺失且达到当前门槛的标签；已有机器/人工结果及主线排序保护，旧上下文、坏CSV与证据不合规项拒绝导入并报告。每款有效分类先累计留档，再提交SQLite、刷新写入结果；历史runtime文件保留。操作命令见[累计分类CSV与历史结果导入](PROCESS.md#累计分类csv与历史结果导入)。

写库前的身份、原文、完整ID覆盖、八类闭集、unknown互斥、有限数、逐字evidence及长度校验先于置信度筛选；低分不能掩盖格式或证据错误。evidence为1～2段本成就名称/描述逐字片段，每段严格小于500字符，reason才是分类解释。这些检查只证明输出契约合规，不能替代人工判断标签语义是否正确。

普通classify默认跳过已完成机器结果；离线补录则使用merge_existing补齐缺失标签，要求全部已有标签的类型、method、confidence、展示名都包含于当前合格目标中，保留相容已有行，只插入缺失行；否则整项记conflict，不覆盖或部分补写。v3早期单条试跑只有与当前库原文和已有标签一致时按legacy_existing归档，不按旧输出契约新增关系。两条链路均保护approved、manual和非空mainline_index；日常显式--reclassify才允许整体重筛机器结果。

原始receipt保存请求及完整/部分响应；每轮report/CSV保存当轮候选与处理统计；累计datacache保存跨轮有效候选；SQLite保存实际采用的关系。累计CSV不能直接驱动跳过，也不是SQLite事实副本；status和sqlite_outcome可反映候选处理，而confidence_passed、label_sqlite_outcome逐标签解释筛选和存储，22列字典见[四层产物与累计表字段](PROCESS.md#四层产物与累计表字段)。SQLite以单游戏事务提交，CSV以临时文件原子替换，二者不是跨文件事务。累计pending表示尚未确认提交，异常时应以SQLite查询核实是否已提交，并保留原始响应/报告追溯，不能把pending当成业务成就状态已回滚。

DataAgent按(appid,api_name)写入；整批校验后BEGIN IMMEDIATE替换自动标签并更新状态。文本/上下文改变回滚；approved、manual标签、非空排序号在选择和落库时都保护。重复相同结果无变更；不改变原始字段及游戏级表。

理由、原文、不确定说明、模型/提示词指纹保存在runtime报告；types保留全部标签，accepted_types/rejected_types分别记录通过及未通过门槛的标签，不新增SQLite JSON列或历史表。默认跳过已完成DeepSeek项，包括uncertain；--reclassify重筛机器结果且仍保护人工成果。阈值不影响请求指纹，相同输入的完整缓存可直接重筛。

没有待处理项的整款游戏会跳过简介及分类请求；仍会读取本地数据库确定进度。重生现在61项全部deepseek，其中60项suggested、1项uncertain是此前已完成结果按默认规则保留。本轮机器候选统计与实际被保留的类型可以不同，不用report.type_counts替代数据库类型分布。

method约束此前已迁移。展示名扩展由[migrate_display_names.py](../process/migrate_display_names.py)执行[迁移SQL](../database/migrate_display_names.sql)：先备份、事务重建标签表并回填，再恢复全部索引/触发器，检查原字段、名称对应、完整性和外键；失败回滚，重复运行无变化，版本3/4中名称不一致也可从来源修复。ensure_schema日常要求版本4；schema.sql可初始化新空库，不是日常启动步骤。旧标签迁移仅将版本2升到3，版本3/4修复保留原时间结构与版本，不隐式执行HLTB迁移。migrate_methods仍兼容旧method结构并填写名称。

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/migrate_display_names.py
~~~

本库已经迁移，无需再次执行。旧版2数据库备份可使用此命令升级；备份文件保留原样。

## 来源与缺口

前1000款按review_count DESC、appid ASC冻结，评价数7326～634194。远端曾优先读取PyCharm XML，缺完整凭据后由根.env+psycopg连接成功，连接和每批事务强制只读。各批REPEATABLE READ READ ONLY，源/批次时间不宣称同步。本轮没有连接远端。

本地9942项描述缺失，1款名称映射未解决，1款缺发行日，24款无RAWG。两款FF7部分云端描述/API名映射与旧API报告冲突，保留本地124项；重制版RAWG版本匹配存疑，评分/时长未纳入。缺口保留，信息不足允许unknown，不捏造确定事实。

来源与快照在database/data和process/runtime/remote_import/20261014T081042433830Z保存，迁移备份为该目录before_import.sqlite。见[IMPORT_SNAPSHOT.md](IMPORT_SNAPSHOT.md)。日常分类不连远端、不采集攻略。

数据库、原始数据、缓存和备份Git忽略。用户既有.gitignore还忽略整个/database/目录，包括SQL；本轮未改变。历史实验路径是当时记录，不保证旧文件仍存在，本轮备份链接已核对。

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
