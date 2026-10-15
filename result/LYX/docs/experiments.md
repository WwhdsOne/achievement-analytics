# 刘宇翔模块实验与实现记录

以下按阶段记录当时的代码、参数与数据，旧prompt/阈值/schema和sample-size/batch-size命令保留作历史证据，不作为当前入口。日常操作以[PROCESS.md](PROCESS.md)为准，当前数据以[DATABASE.md](DATABASE.md)的带时间核查快照及SQLite查询为准。

## 2026-10-15：分类链路文档对齐与后续真实运行核查

- 本轮仅核对分类代码、历史凭据、运行报告和本地SQLite，并更新分类有关Markdown；没有调用DeepSeek、重跑分类、迁移数据或改动代码。SQLite连接使用mode=ro。文档明确本项目LLM as Judge为固定八类规则下的语义分类，简介并非独立事实来源或第二位评审；工程验收与分类质量、人核主线节点/排序、后续聚合分析分开。
- 用户后续真实运行：[20261015T064109506808Z报告](../process/runtime/deepseek/runs/20261015T064109506808Z/report.json)，北京时间14:41:07～14:41:24，分类v6、简介v1、逐标签confidence>=0.6。简介与分类各1次新请求，星露谷49项/49标签全部写入，无错误；Rust105项和博德之门3的54项复用缓存，已有118项跳过、低分41项保留；再复用赛博朋克简介后，分类处达到请求预算，state=budget_reached。classified_count=208、accepted_label_count=167、successful_game_count=3均包含缓存或已有结果，本轮实际新增标签为49，不能把这些候选统计当成新增完成数。
- 本轮真实用量：prompt2320、completion3913、total6233 tokens；API前缀命中640、未命中1680，输入命中比约27.6%；本地缓存命中5次，历史用量不计入本轮。该单轮结果不证明稳定缓存收益、整体费用或分类准确率。
- 只读快照（北京时间14:54）：schema4；1000款、71465项成就。achievement_types为2271行、覆盖2146项，其中DeepSeek2205行/2083项、rule66行/63项；confidence=0.6标签74行。status分布pending69319/suggested1874/uncertain272，不能单凭status或总标签覆盖当作DeepSeek完成数。累计datacache2313行，低分107行，冲突1行、legacy_existing1行。11:06补录时的2222标签行/2097项覆盖/2264累计行保留为历史快照。
- 文档更新：DEEPSEEK_PLAN补完整链路、判别/程序校验/门槛/人核边界和真实验收；PROCESS补累计CSV22列、四层产物、逐标签结果及恢复/统计解释；DATABASE同步分类快照；两份README与总体plan同步阶段状态。默认plan、分类预算2次、>=0.6、每段evidence<500、简介90秒/分类300秒总时限、15秒进度、同类3次超时暂停均以当前代码为准。原始报告及旧门槛历史条目不改写，未把1000款分类或语义准确率标成已完成。

## 2026-10-15：包含0.6的门槛、累计CSV与历史结果补写

- 用户授权：人工抽查后接受confidence=0.6，将本地筛选从严格大于0.6改为大于等于0.6，恢复已有缓存中达到门槛的分类；新增process/datacache.csv累计保存有效分类，包括未达门槛、已有和本轮写入的标签。confidence仍是模型自报信心，不解释为准确率或校准概率。
- 处理规则：默认门槛0.6，入口、SQLite写入、CSV标记和report的confidence_comparison统一为>=；这是本地后处理，分类prompt v6、简介v1、API请求内容和指纹不变。此前实验中的>0.6保留为当时口径，不改写历史报告或CSV。
- 累计留档：每标签一行，按(appid,api_name,type,request_hash)去重，保留source_csv/first_seen_at/last_seen_at；每款完整校验后先保存全部有效候选，再提交SQLite、刷新写入结果。低分和已有结果同样可追溯，原runtime CSV/JSON及receipt继续保留，不迁走或删除原文件。普通分类命令无需改动，--datacache可指定LYX内累计CSV路径。
- 离线迁移：process/import_classification_cache.py默认只预检，--apply才实际落盘；source-root默认runtime/deepseek/runs，支持--source-root/--database/--datacache/--min-confidence。实际SQLite先备份，再核对当前原文、完整请求和证据，只补合格且缺失的标签，已有机器/人工结果及主线排序不覆盖；坏CSV、过期上下文或证据不合规项拒绝导入并报告，不调用DeepSeek、不连接远端。
- 实际结果（2026-10-15 11:06北京时间）：扫描9份历史CSV共2666标签行，去除402次重复回放后累计2264行，其中2157行达到门槛、107行低于0.6。实际补录74个confidence=0.6标签，涉及68个原未分类成就及6个已有成就的缺失标签；类型表总计2222行、覆盖2097个成就。低分涉及88个成就，与107标签行口径不同。1条《重生》Grind It Out新候选other=0.9与既有challenge=0.7不相容，保留旧标签并标记conflict；早期v3单条试跑仅按legacy_existing归档，不重新导入旧契约。实际新增请求0、验证错误0，原runtime文件不变。
- 验收：隔离SQLite完整迁移后重复导入新增0标签、累计CSV仍2264行；实际DataAgent入口以Rust缓存运行，新请求0、缓存命中2、105行累计导出成功。边界0.59拒绝/0.6接受/0.61接受；人工确认、manual、mainline_index保护、类型冲突和整款事务回滚均验证通过。真实迁移后原2148条标签全部保留，18个受保护成就不变，四张游戏表及成就原始字段不变，integrity_check与foreign_key_check通过。
- 追溯：[真实迁移报告](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/report.json)、[迁移前SQLite备份](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/before_import.sqlite)、[真实数据验收](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/verification.json)、[隔离链路与重复导入验收](../process/runtime/verification/20261015T030512124887Z-inclusive-confidence/verification.json)。以上是本地忽略产物，不提交Git。

## 2026-10-15：请求总时限、等待进度与连续超时暂停

- 用户授权：实施此前规划中除第五项之外的内容；没有新增stop子命令、停止文件或进程控制。只改LYX的分类传输、编排与相关说明，不操作正在运行的任务。工作区原有攻略用时程序、说明和共享依赖改动保留。
- 问题依据：用户的454次预算运行在Overwatch简介第67次请求等待完整响应，后已正常记录interrupted；随后预算2次的新运行又停在Stardew Valley简介。原同步HTTP只有每次读取超时，保活空行可能使总等待超过300秒；这属于请求等待问题，不能靠减少max-requests解决。
- 实施：新增process/deepseek_transport.py，用惰性且复用的asyncio.Runner/AsyncClient管理可取消HTTP；业务仍逐款串行、API payload保持stream=False。新增--intro-total-timeout-seconds=90与--classification-total-timeout-seconds=300，从首次网络尝试到完整正文共享总时限，连接/重试/退避均计入；现有--timeout-seconds=300仍是读超时，连接15秒。提示词v6/简介v1、输入和请求指纹未变，没有新增依赖。
- 可见性：每15秒独立心跳，终端及本轮progress.json记录游戏、任务、尝试与请求预算、awaiting_headers/reading_response、累计/剩余秒数、接收字节数、是否已有非空白正文、最后接收时刻；无数据时也更新。完整正文保存response_text；超时、传输失败或中断的部分正文留partial_response_text及response_complete=false，不能缓存或入库。旧receipt缺少该字段仍按历史完整规则兼容，显式false即使有可解析JSON也拒绝复用。
- 超时处理：总时限或ReadTimeout记request_timeout，本款不写库、不自动重发，继续下一款。简介失败不分类，分类失败保留成功简介；已尝试HTTP计预算，缺失usage保持未知。简介/分类分别连续计数，同类完整HTTP200清零，缓存命中不清零；同类第三次超时service_paused、退出码1。超时同时计入failed_game_count/failed_appids，并单列timeout_game_count/timeout_appids；预算及零星失败沿用budget_reached/completed_with_errors语义，其他网络、429、TLS/认证/余额和存储故障仍整体停止。
- 验收：[batch-verification.json](../process/runtime/tmo/012125400336/batch-verification.json)有14种完整入口隔离场景，通过简介/分类/读超时后继续、两类各连续3次暂停、超时后预算耗尽、429/401/402、ConnectTimeout、SQLite故障、响应契约错误、连接检查超时及真实旧缓存恢复。Terraria原137项响应在SQLite副本零HTTP恢复，写入137项/137条标签，未写正式工作库。
- 边界验收：[edge-verification.json](../process/runtime/tmo/012125400336/edge-verification.json)有5组，通过退避共享总时限、准备重试时写盘跨deadline不新增HTTP计数、缓存不清超时计数/完整200清零、显式partial拒绝而旧完整receipt可复用、CLI参数正有限及不存在stop入口。503完整正文不会因退避超时被误改为不完整；未发送的重试另留not_sent记录。
- 补充：[direct-summary.json](../process/runtime/tmo/012125400336/direct-summary.json)验证持续空行仍触发总超时并关闭流；[interrupt-verification.json](../process/runtime/tmo/012125400336/interrupt-verification.json)验证KeyboardInterrupt后receipt/report为interrupted、退出130、保留部分正文和已收到响应头、关闭传输且不处理下一款。上述合计21组主程序离线验收；传输层另外核验无响应头也有心跳、回调写盘失败会取消HTTP、清理后无后台任务、多请求复用同一loop/client。
- 验证范围：使用本地HTTP替身、已有完整响应及隔离SQLite，没有新增pytest或持久测试程序，真实API请求0、远端访问0、正式库写入0。本轮前置备份为process/runtime/archive/20261015T011334591331Z-request-deadlines；工作区已有其他改动不回退，不提交或推送。新逻辑从下次启动生效，当前进程不会热更新；真实代理/上游可用性仍须之后实际运行观察。

## 2026-10-15：引用长度放宽、旧响应恢复与批量失败隔离

- 问题证据：用户默认1000款、max_requests=456的运行在Terraria（105600）停止，仅使用简介与分类各1次请求。分类HTTP200、finish_reason=stop、完整137项；It's Hard!的evidence准确复制161字符描述，超过v5的150限制，触发整款拒绝并跳出整个游戏循环。本轮只读核查原始响应与报告，没有补发API请求。
- 原文分布：当前SQLite共71,465项成就，description为空9,942项；非空61,523条按Python len计数（含空格/标点），中位数39、P90=77、P95=92、P99=129、最大471字符，百分位采用最近秩法。超过150字符345条、涉及51款；这是描述原文统计，不等同于模型引用长度。
- 用户授权实施：分类prompt升为lyx-deepseek-whole-game-v6，evidence每段严格小于500字符（499通过、500拒绝），保留1～2段非空原文、逐字来源、完整ID、闭集、互斥和置信度校验；report新增evidence_length_comparison="<"。标签入库仍按confidence > 0.6，SQLite结构及写入程序不改。
- 缓存恢复：优先v6，兼容仅长度行和版本不同的精确v5/v4完整请求；游戏上下文、原始成就、模型、接口及生成参数仍需一致，所有响应重校验。源版本、requested_prompt_version及compatible_cache保留，旧receipt及报告不改写。真实Terraria的137项旧响应在新规则下全部通过。
- 逐款隔离：新增ResponseValidationError，仅将HTTP200中的JSON、截断和简介/分类契约错误归为游戏局部失败；记录response_error、阶段、错误和receipt位置，整款不写库、仍待处理，继续下一款。429、认证/余额、网络、SQLite与文件错误仍停止，连接失败/5xx保留有限退避。遍历完有局部失败时completed_with_errors、退出码1；预算耗尽仍budget_reached并保留先前失败及退出码1。报告增加failed_game_count/failed_appids，失败不伪造成unknown。
- 隔离恢复验收：[cache-recovery.json](../process/runtime/validation/20261015T001724182578Z-evidence-500/cache-recovery.json)。用完整run入口、正式库的隔离副本和已有两份缓存执行Terraria恢复；新HTTP请求0、缓存命中2、分类137项，隔离库写入137项/137条标签，无低分拒绝，完整性ok、外键问题0。正式工作库没有执行此次恢复，后续可由用户运行--game-name "Terraria" --max-requests 0补写。
- 批处理验收：[batch-scenarios.json](../process/runtime/validation/20261015T001724182578Z-evidence-500/batch-scenarios.json)。最终12种离线场景通过，合计32次模拟HTTP、真实请求0：错误引用/无效JSON/截断/无效简介均保留首款失败并成功写入下一款；错误后预算耗尽保留失败计数；429/401/402/超时/503/SQLite错误/文件错误均停止后续游戏。语法、499/500边界、非原文拒绝、超大置信度整数、旧prompt精确重建及变化输入/模型/生成参数不复用也已核验，未新增pytest或持久测试程序。
- 验证中的坑：最初隔离runtime路径过深触发Windows长路径限制，文件写入失败会按整体存储错误停止；改用process/runtime/v500中的短目录后完成验收，没有扩大正式程序修改范围。
- 修改边界：仅修改LYX程序及现行说明/实验记录。备份为process/runtime/archive/20261015T001526682065Z-evidence-500；哈希确认正式SQLite、本地schema、旧响应/旧报告、game_intro/local_database、选样JSON、.gitignore、共享schema及uv.lock均未改变。未访问远端、未发起真实API请求、未提交或推送；旧版实验继续保留当时口径。

## 2026-10-14：整款入库验收、参数说明与文档核查

- 重生恢复由用户执行：[report.json](../process/runtime/deepseek/runs/20261014T133727794594Z/report.json)。command=classify、游戏名精确选择、max_requests=0、prompt v5/简介v1、evidence上限150、门槛0.6；state=success，完整候选61项、写入60项/60条标签、already_classified保留1项，新请求0、缓存命中2、未处理0。读取运行前备份对照，原始成就字段/排序、四张背景表和其他游戏未变，写入标签及状态与报告一致；展示名空缺/不一致0、完整性ok、外键问题0。
- 已完成判据核验：重生61项method均deepseek，60项suggested、1项旧uncertain保留；再次普通预检pending_count=0、already_classified_or_protected，简介与分类都不请求。保护项排除后，只有method全deepseek且status为suggested/uncertain才算完成；rule/jev旧结果仍会处理，status='pending'不是分类器剩余量的完整口径。
- 默认清单后续运行由用户执行：[report.json](../process/runtime/deepseek/runs/20261014T135413196167Z/report.json)。默认前1000款、max_requests=2，HELLDIVERS™ 2（553850）38项成就完成，生成41条多标签关系；新请求2、errors为空，随后budget_reached正常暂停。当前累计2款、99项成就、102条DeepSeek类型关系；类别关系数与成就数不同。
- 2026-10-14 13:58 UTC核查快照：游戏1000、成就71,465、类型关系168（deepseek102/rule66）；status为pending71,303/suggested125/uncertain37，approved0，主线排序18。默认1000款预检978 ready、16 oversized、4无成就、2已完成，待处理71,348，正常新请求估计1956、重试另计。进度已较上一轮核验增加，以带时刻快照记录；后续用户执行会继续改变数据。
- 文档核查：读取docs全部8份说明及当前7个活动Python模块/3份本地SQL的相关路径。补充PROCESS的--game-name/--appids/--appids-file/--all-games互斥表、子命令、全部运行参数默认值、请求计数/重试/缓存/每轮重置、自动跳过及全量选择例子。同步README、plan、DATABASE、DEEPSEEK_PLAN的阶段状态与最新数据；IMPORT_SNAPSHOT标明历史导入/版本2 checkpoint及当前版本3续跑边界。历史API索引内容与链接有效，无需改动；既有历史实验不改写。
- 今日实现主线：完成前1000款本地数据准备，收缩为DeepSeek八类多标签；常量分类prompt+独立简介prompt/缓存，按游戏名整款输入；严格confidence > 0.6逐标签入库、完整JSON保留低分；标签表增加display_name并同步写入/导入/迁移；修复60字符引用限制为150并零请求复用失败响应；用户完成两款真实链路及多标签写入验证。尚未完成全量标签或语义准确率评估，不生成主线排序与分析结论。
- 已知核验边界：import_snapshot.verify_run仍只比较原五个类型字段，没有单独核查新增展示名与来源一致；实际六列INSERT与同步触发器已适配，本轮更新说明而未改程序。提交前留意LYX .gitignore的/database/规则还会忽略SQL；本轮没有改变Git忽略规则，也不提交原始数据/缓存/SQLite/凭据。
- 本轮范围：只修改result/LYX/docs，未运行classify、未调用API、未连接远端、未修改程序/SQL/实际库、未提交/推送。文档修改前备份为process/runtime/archive/20261014T135807506671Z-docs-audit，含核查快照及文件哈希；参数、链接与修改边界检查见[verification.json](../process/runtime/validation/docs-audit-20261014/verification.json)。

## 2026-10-14：真实试跑引用超长诊断与150字符修复

- 用户实际运行：classify --game-name "FINAL FANTASY VII REBIRTH" --max-requests 2；原提示词v4、简介v1、0.6严格门槛，完整61项、待处理60、已有DeepSeek1。运行目录process/runtime/deepseek/runs/20261014T131828498819Z，简介及整款各1次真实请求，合计prompt2795/completion4716/total7511 tokens，API缓存命中0；这两次请求由用户发起。
- 原因：分类HTTP200、finish_reason=stop，61项完整且无重复，其他字段契约通过；9段evidence为准确原文引用，长度62～84，超过原60字符上限。旧错误将超长和非原文混为“evidence必须逐字引用”，整款停止、写入0。只读对比运行前备份，实际六表业务数据一致，标签仍rule126/deepseek1。
- 用户授权修复：evidence每段上限改为150，解释链路，不代用户运行分类。DataAgent提示词及EVIDENCE_MAX_CHARS/校验同步，版本v4→v5；保留每项1～2段、逐字来源检查，reason/uncertainty仍最多40字符。错误区分段数、空引用、超长、非原文，并显示成就ID/名称。本轮没有修改SQLite结构或写入程序。
- 缓存恢复：仅此次长度放宽兼容相同v4完整请求；用户输入、模型、接口、生成参数或版本变化不能套用。旧响应重新完整校验，新缓存优先，原receipt不改；元数据注明源prompt_version、requested_prompt_version及compatible_cache。由此旧错误响应可在当前规则下复用，避免要求用户再次付费生成同一结果。
- 验证：[verification.json](../process/runtime/validation/20261014T133248668332Z-evidence-150/verification.json)共6组，覆盖提示词/校验150与旧prompt精确一致、150通过/151拒绝/错误区分、真实已保存61项原样校验与零请求缓存读取、上下文/模型/参数/任务/其他版本变化不复用、坏缓存拒绝/新缓存优先、实际库及原响应/共享文件不变。仅调用缓存读取与本地validator，未执行run/classify、未新增pytest文件。
- 结果：已保存响应最大引用84字符，61项在新规则下全部通过，候选标签61个通过0.6、低分0；这些是候选校验结果，尚未写入。简介和分类缓存均命中，预计新请求0。原始数据、原receipt、原运行report、共享依赖/SQL、game_intro/local_database/import_snapshot哈希不变，真实供应商请求0、远端连接0、数据库写入0。
- 备份：process/runtime/archive/20261014T133042839206Z-evidence-150保存原DataAgent、说明、旧prompt及基线；数据库只读摘要前后均d730f985be46931963604e6d61a575ba60f27edbde5f7f7947d865348cffa124。
- 用户恢复命令（LYX目录）：uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --game-name "FINAL FANTASY VII REBIRTH" --max-requests 0；只复用缓存，允许按现有保护规则写本地SQLite。本轮未代用户执行、未提交/推送。

## 2026-10-14：标签表新增并回填display_name

- 用户授权：修改本地achievement_types结构，加入展示名并补齐已有记录；远端永远只读。本轮同步main后仅修改LYX。
- 结构：schema版本2→3；标签表为appid/api_name/display_name/type/method/confidence，主键仍(appid,api_name,type)。display_name为TEXT NOT NULL，非空白，与achievements.display_name约束一致，按(appid,api_name)回填；不新增其他业务表或JSON字段。
- 实现：[migrate_display_names.py](../process/migrate_display_names.py)与[迁移SQL](../database/migrate_display_names.sql)先备份、事务重建并回填，恢复索引/触发器，检查原字段及名称关联、完整性和外键；失败回滚，重复运行不改库。当前版本中名称不一致也可从来源修复。local_database同步结构检查/分类INSERT，import_snapshot保留标签时同步名称，旧method迁移兼容版本2/3并填写新列。
- 名称同步：新增achievements_display_name_sync，来源成就改名时只按完整复合键更新对应所有标签。分类提示词、API请求指纹及0.6严格门槛不变；仍保护人工/排序，仍逐标签筛选并在runtime保留低分结果。
- 实际迁移：127条名称全部回填；原六表字段（排除新增列）SHA256前后均为175e9a19e557a3fadf7849a6b9f38f197cc1214f65469d50b40f34d72433c4ac。保留1000款、71,465项成就、127条类型（rule126/deepseek1），18个主线排序号及所有状态不变。名称空缺/来源缺失/不一致均0，integrity_check=ok、外键问题0，原6个触发器及索引保留并新增名称同步触发器。
- 备份：[achievements.sqlite](../database/backups/20261014T125409120039Z-display-names/achievements.sqlite)，同目录migration.json。代码/说明修改前备份为process/runtime/archive/20261014T124752539110Z-display-name，附基线及before_changes.sqlite。
- 验证：[verification.json](../process/runtime/validation/20261014T125303979722Z-display-names/verification.json)共7组检查：语法、旧版迁移/原字段保留/幂等、当前名称修复、失败回滚、旧method兼容、分类写名/0.6筛选/复合键同步/非空约束、来源快照导入保留标签并填名。使用临时数据库，不新增pytest文件；导入检查补全模拟背景的四个标志字段后通过。
- 最终核对：[final-check.json](../process/runtime/validation/20261014T125303979722Z-display-names/final-check.json)。实际库迁移再次运行already_migrated=true、回填0；两款FF7离线plan读库成功、门槛0.6、待处理105、实际请求0。共享文件、原DataAgent/game_intro代码哈希不变；未访问远端、未调用模型、未提交/推送。PyCharm刷新/Synchronize后可直接浏览新列。

## 2026-10-14：confidence 0.6逐标签写入门槛

- 用户授权：默认门槛改为0.6，多标签分别筛选，仅confidence > 0.6写入SQLite；其余标签继续保留runtime JSON。等于0.6明确不通过。
- 实现：local_database.DEFAULT_MIN_CONFIDENCE为单一默认值；partition_classification_types先校验完整结果再分流，DataAgent和SQLite入口共用。报告types保留全部标签，accepted_types/rejected_types列出筛选；写入入口再次校验筛选一致性，防止低分写入。全部未通过记below_threshold，不删除旧类型、不改status；部分通过只替换可更新自动结果中的通过标签。人工、排序和默认已有DeepSeek保护保留。
- 状态：通过的明确标签为suggested；unknown也按相同门槛，通过后仍uncertain。全未通过的待处理成就记remaining_pending_count，运行可返回success_with_rejections。classified_count表示完整模型覆盖，accepted/rejected_label_count表示候选标签筛选（含保护项），written_label_count表示真正写入标签数，sqlite_counts.written表示更新成就数。
- 记录与缓存：运行report.json记录min_confidence和confidence_comparison；CSV每标签保留confidence_passed/label_sqlite_outcome。API提示词/版本不变，阈值不影响请求指纹，同一响应可零请求重筛；已有机器结果需显式--reclassify。错误格式仍拒绝整款，原始响应留在receipt JSON。旧实验中的0.8仅为当时口径，不改写历史记录。
- 验证：7组离线检查通过，使用临时SQLite和模拟HTTP；包含默认参数/语法、0.9/0.61通过与0.6/0.59拒绝、全部结果JSON/CSV、原有规则/人工/排序/已完成保护、全未通过空库与旧结果保留、零请求缓存续跑、更改门槛缓存重筛、非法类型/分数拒绝、输入改变原子回滚及SQLite完整性。共4次模拟HTTP、真实供应商请求0，没有新增pytest或持久测试程序。
- 真实本地离线预检：FF7重制/重生完整63/61项，待处理45/60项，保护18/0项，已完成DeepSeek0/1；输出估计11104/10784。默认min_confidence=0.6、confidence_comparison=>，requests=0、database_writes=false；输入SHA256=dfe395df510d7680b216c302a0ec939e6e5972cb9d8808016d07674b67134a51。
- 产物：[verification.json](../process/runtime/validation/20261014T123711121985Z-confidence-gate/verification.json)及同目录模拟运行report/CSV。备份：[before_changes.sqlite](../process/runtime/archive/20261014T123214458821Z-confidence-gate/before_changes.sqlite)，附原代码/说明及baseline.json。本轮只改LYX程序与说明，不迁移schema、不写实际工作库、不连接远端、不提交/推送。
- 最终核对：[final-check.json](../process/runtime/validation/20261014T123711121985Z-confidence-gate/final-check.json)。真实SQLite六表业务数据及schema与本轮基线一致，integrity_check=ok、外键问题0；现有类型仍deepseek1/rule126。共享uv.lock、cleaning/schema.sql、docs/plan.md、LYX .gitignore和本地schema.sql哈希不变，简介程序未改，活动说明链接有效。

## 2026-10-14：常量提示词、背景摘要缓存与游戏名整款分类

- 用户审批范围：分类和简介prompt放在导入区之后；新增game_intro.py；按游戏名查询并整款一次分类；超大游戏先预检跳过；SQLite六表不变。本轮只实施和离线验证，未请求真实模型。
- 提示词：DataAgent.CLASSIFICATION_PROMPT为结构化常量，版本lyx-deepseek-whole-game-v4；game_intro.GAME_INTRO_PROMPT为结构化常量，独立版本lyx-game-intro-v1。普通成长/等级门槛与挑战边界补充；两段输入固定为game_context在前、全部achievement_batch在后。
- 摘要：只传名称/官方类型，recognized=true时40～80字符中文summary，false时空摘要与原因；标记model_generated，外部缓存/报告保存，不新增SQL表/字段，不冒充官方资料或成就证据。复用DataAgent客户端，共用请求预算、密钥、HTTP和缓存；任务/版本命名空间独立。
- 入口：--game-name唯一完整名称匹配，大小写/Unicode/空白规范化；中文、重名、部分/近似候选行为已检查，非唯一不发请求。保留AppID/冻结清单/全库选项；移除正常入口batch-size/sample-size。
- 全款保护：模型看到全部原始成就，默认只更新待处理项；已有DeepSeek标为already_classified，--reclassify才重判机器结果；approved/manual/非空排序始终保护。整款集合/文本变化（包括新增/删除）在写库前拒绝；响应先保存，再短事务落库。
- 预算：输出估计1024+160*N，默认上限65536；输入字符阈值300000；超限oversized_game，不自动拆分或发简介请求。读超时默认300秒、连接15秒；请求预算包括简介/分类/重试。新增任务用量、本地复用、API命中/未命中token/比例统计，缺失字段null，缓存历史不重计。
- 真实本地离线plan：1000款、71,465项成就；71,446待处理、18保护、已完成DeepSeek1。980款ready、16款oversized、4款无成就；冷缓存新请求估计1960是全范围估计，不会自动发出。整个输入SHA256=26a444789681404de6cc240a91bbec2416fcd8bc4c4043ef7a87799bdb0e5ae2。
- FF7预检：重制63项、输出估计11104；重生61项、输出估计10784，默认保留已有一项，待写60项。新版分类仍要求完整响应覆盖全部输入ID。
- 验证：临时真实SQLite+模拟HTTP共7组检查通过，覆盖名称选择、prompt排列与不泄露结果变量、摘要/分类契约、共用预算、缓存恢复、显式重判、原始集合变化回滚、保护、未识别摘要继续分类、token统计、超限无请求及离线plan不写文件。额外验证摘要格式失败不重试、截断分类不写库/不重试，两条失败路径通过。未新增pytest文件。
- 产物：process/runtime/validation/whole-game/verification.json与failure-paths.json。模拟结果仅写临时库，真实供应商请求0，真实摘要/全款语义效果和API缓存收益尚未验证。
- 备份：process/runtime/archive/20261014T185837-whole-game/before_changes.sqlite，附修改前代码/文档/基线。开工库SHA256=cf42623fa461869d765d20397c43406ada9f85579eef0fe5e737038579d9b1a4；最终核对时物理SHA256=b0eff3817d2c3360345c567daa8e51e9d729fd4ca2d6759558e0a0026001aac4。逐表比较发现仅games_details中appid34330的valve_genres从空文本改为Action|Strategy|Singleplayer|Multiplayer；本轮模拟写入仅针对临时库，保留工作期间该背景更新，不回退。实际成就/标签逐项一致、结构一致，类型仍rule126/deepseek1，18项排序完整保留。
- 文档：更新plan/PROCESS/DEEPSEEK_PLAN/DATABASE及入口索引；工作区已移除的process/database README链接改为实际程序/SQL或docs入口，没有恢复旧目录README。
- 边界：只改LYX，schema/原始数据/共享依赖/其他成员目录不改，未访问远端，未提交/推送。下一步按已确认预算对FF7做真实整款验收，先看摘要与完整分类质量，再逐游戏推进。

## 2026-10-14：单成就真实分类与SQLite写入

- 用户授权：只试跑一个成就，查看完整链路效果。同步main后选2909400（FINAL FANTASY VII REBIRTH），sample-size=1、batch-size=1、max-requests=1、max-tokens=8192、阈值0.8；提示词lyx-deepseek-multilabel-v3，model=deepseek-flash。
- 样本：Grind It Out；描述为“Attain level 70 with a character.”。原标签unknown、method=rule、confidence=NULL、status=uncertain、mainline_index=NULL。
- 实际执行：根.env凭据、官方HTTPS接口，1次真实请求、HTTP200、缓存命中0；选中1项、分类1项、写入1项，state=success。约13.10秒，prompt553/completion100/total653 token。未另发连接测试或第二次分类请求。
- 结果：challenge、confidence=0.7、method=deepseek；低于0.8阈值，status仍为uncertain。原unknown标签由新模型标签替换；原始字段未变，mainline_index仍为NULL。自报0.7不是70%的准确率。
- 语义观察：模型将达到等级目标解释为挑战，并在理由中推断“重复游玩或刷取经验”，但输入只明确要求达到70级，knowledge_used=false。普通成长与特殊挑战边界仍需进一步明确；不能凭这一项认定分类准确率已验证。
- 数据验证：与本轮before_classify.sqlite按字段核对，游戏级四表、全部原始成就、排序号与其他成就标签未变；仅此项类型来源/置信度改变。完整性ok、外键问题0，实际类型总数仍127（rule126、deepseek1）。
- 数据版本与产物：runtime/deepseek/runs/20261014T094723361217Z；input_sha256=21ba513670e43d662a95ebe95243198b11ffdb9cfab0577377b78be641a4b31d。该目录含report.json、classifications.csv、before_classify.sqlite和verification.json；响应receipt路径登记在report.calls。
- 边界：未修改分类代码或schema，未访问远端，未提交/推送。之前离线阶段“deepseek=0”的文档统计是试跑前状态，当前已写入1条真实模型标签。
- 复用命令：在LYX目录执行uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --appids 2909400 --sample-size 1 --batch-size 1 --max-requests 1；重复执行默认会选择下一项尚未获得DeepSeek结果的成就。

## 2026-10-14：收缩为DeepSeek直接分类链路

- 最新范围：只做八类多标签分类与SQLite存储，退出规则比较、参与深度、人工审核程序和主线分析；mainline仍是类别。
- 程序：DataAgent.py去掉旧规则依赖、scope/ordinary_mainline/target_depth和审核空栏；提示词升为lyx-deepseek-multilabel-v3。默认前1000款清单，支持显式AppID/清单/全库、稳定小样本、预算限制和--reclassify。
- 本地写入：local_database.store_classifications整批短事务，先核对游戏上下文/成就文本再替换自动标签、更新suggested/uncertain；unknown互斥，人工approved/manual及非空主线排序号保护，重复同结果无变更。
- 恢复：每轮classify自动备份，先持久化响应与关联记录再落库；成功缓存可复用，预算包含重试。默认跳过已有DeepSeek结果，包括uncertain。
- 清理：probe_achievement_types.py、import_probe.py和旧API说明归档到process/runtime/archive/20261014T171916-deepseek-only/process。import_snapshot.py改从local_database获取sqlite_percent，保留独立的数据准备工具与已完成method维护入口；本轮开始时旧rebuild_sqlite.py和probe测试已不在活动目录。
- 布局：沿用工作期间已整理的docs集中布局，更新总体规划、流程、数据库与DeepSeek契约，保留目录README入口及历史实验。没有恢复旧文档路径。
- 本轮数据版本：现有SQLite及前1000款冻结清单；离线输入SHA256=b57acc36e0dbd1e633ceffe03cc465f725ccaa96b0004d96d3890a251cc9da6d。实际1000款、71,465项成就、127条rule标签，DeepSeek标签0，approved=0；18项已有非空mainline_index受到保护。
- 离线plan参数：20项/批、sample-size=0、默认请求上限2、阈值0.8；71,447项待分类、18项保护、4款无成就、4023批、新契约缓存0。字符数不是token，未估算费用。
- 验证：临时真实SQLite与模拟HTTP共6组检查通过，覆盖多标签/unknown、ID/置信度/证据、幂等写入、输入变化整批回滚、人工保护、缓存恢复、预算续跑与完成项跳过。模拟响应没有写实际工作库，真实供应商请求0；未新增pytest用例。
- 备份：process/runtime/archive/20261014T171916-deepseek-only/before_changes.sqlite，附代码、文档及基线记录。实际库SHA256修改前后为f5089edae13ccc40504de7f1c1236183252668dee004477d5eb97cbab0a5fe92；业务数据未变、integrity_check=ok、foreign_key_check为空。
- 边界：没有连接远端、没有模型费用、没有修改共享依赖/其他成员目录、没有提交或推送。method约束此前已迁移，本轮未再改schema。
- 下一步：少量真实classify直接入库，查看语义和实际token后按预算推进1000款。当前交付是可执行链路，不是全量标签完成或准确率验证。

## 2026-10-14：说明文档集中到docs

- 总体规划、实验记录、数据库说明、流程说明、DeepSeek方案和批量导入说明共6份迁入docs；原database/process的README保留为入口索引，新增LYX与docs的README。
- 迁移过程中旧API说明和旧抓取脚本已被另一项操作归档；docs/API_PROBE.md提供历史资料入口，归档文件保持原位，不恢复旧程序。
- 更新文档、程序、SQL、输入与备份的相对链接，修复原数据库口径锚点；工作区已不存在的旧重建备份改为注明历史路径，当前method备份保持可访问。
- 后续个人说明和实验记录统一写入docs；本次不修改程序逻辑、SQL或数据库，不提交或推送。

## 2026-10-14：method枚举调整

- 用户确认：仅支持deepseek/jev/rule/manual，移除hybrid。
- 范围：只修改LYX的SQL、连接校验、旧结构迁移入口的方法校验及相关说明；新迁移程序process/migrate_methods.py与database/migrate_methods.sql。未访问远端、未调用模型、未改共享依赖、未提交/推送、未新增测试用例。
- 当前库迁移：先完整备份，再BEGIN IMMEDIATE事务重建achievement_types并恢复索引/六个触发器；异常回滚。没有改其他业务表结构，字段布局/user_version保持2；ensure_schema额外校验method CHECK，既有导入checkpoint继续兼容。
- 数据：游戏1000款、成就71,465项、类型127条且全部rule。六表业务记录SHA256迁移前后均为c90b3dc6df6d6de2c326e8bf8644e0e3e77c23a00aa1f393c6474b2f853cf631，原始字段、标注、审核状态与主线顺序完整保留。
- 备份：database/backups/20261014T090228682686Z-methods/achievements.sqlite，迁移记录为同目录migration.json。
- 验证：四个允许值在实际SQLite中写入检查通过，hybrid触发CHECK拒绝，检查用临时修改全部回滚；integrity_check=ok，foreign_key_check问题0，触发器名称完整保留。迁移再次运行返回already_migrated=true；DataAgent plan离线读取通过，真实API请求0。
- 结论：method定义和现有数据库已生效，原127条标注没有改成模型结果；审核文件导入仍为后续工作。

## 2026-10-14：DeepSeek连接、多标签初标和缓存重放

- 范围：只修改LYX；实现集中在process/DataAgent.py，设计记录为docs/DEEPSEEK_PLAN.md。提前同步main，未提交/推送、未改共享依赖、未新增测试用例。
- 实际读取：本地SQLite六表，mode=ro、query_only=ON、读取事务结束后关闭连接；没有远端访问或SQLite写入。运行期间已有本地数据扩为1000款/71,465项，DataAgent显式仅选1462040与2909400，共124项输入，并对每款8项试跑。
- 凭据/接口：环境变量优先、根.env回退；本次key_source=project .env，官方https://api.deepseek.com/chat/completions，model=deepseek-flash。未保存或显示key，TLS校验开启。
- 参数：20项/批、每款规则类型组合代表8项；classification最多2次真实请求、max_tokens=8192、非思考模式、temperature=0、JSON模式；0.8仅作候选状态分流。规则版本ff7-description-baseline-v1，成功提示词版本lyx-deepseek-multilabel-v2。
- 连接：20261014T081149636459Z请求成功，HTTP200，ok=true；prompt39、completion5、total44 token。
- 首次分类：v1模型把一个16位哈希ID最后一位改写；严格身份校验拒绝整批，0项候选、0项落库，未自动重试；耗用1840 token。响应保留在runtime供诊断，不按展示名猜配身份。
- 修复：改为按身份哈希排列的短引用编号，仍精确匹配；同步升提示词v2。另修复输入快照字典被后续采样属性影响的问题，完整与小样本的原始输入指纹现一致。
- 成功分类：20261014T081653469016Z；2次HTTP200，16/16项覆盖，18条类型候选（other4/mainline6/collection1/side2/challenge3/dlc2）。逐字证据、范围、多标签、枚举、置信度、非截断响应检查通过。规则unknown2项，模型unknown0项，2项类型集合不同；这些是待审核差异，不是准确率。
- 成功分类用量：prompt1873、completion1498、total3371 token。本轮连接+首次被拒+成功分类合计4次真实请求、5255 token，费用未估算。
- 成功输入SHA256：c2a6c97c039b6f3bf4c65cc97fade5733e7755c5e1cc8849072cbc1e9b4f01e7，包含所选两款全部原始成就文本和游戏上下文；请求指纹另包含提示词/模型/生成配置。
- 缓存重放：20261014T081920888167Z，同一小样本参数、max_requests=0，2个成功批次复用，16项候选，真实HTTP请求0，本次新token用量0；不会将缓存响应的历史用量重新计费记录。
- 最终验证：补充缓存重放20261014T082223371182Z仍为0请求，16项候选与首次成功逐项一致；CSV18行类型、人工审核栏为空。两次核对期间SQLite文件SHA256均为8e2c20e80a6e1c68fbf845f69db695cc1482283ad2e3040b0789acc597470441，完整性ok、外键问题0，原127条类型仍全部method=rule、approved=0、mainline_index非空0。
- 输出：process/runtime/deepseek/runs/20261014T081653469016Z/report.json与review.csv；缓存重放目录为20261014T081920888167Z。报告与每个类型行保留规则对照、理由、模型知识声明、原文依据和人工审核空栏，全部仍需人工审核。
- 数据库衔接：method约束没有deepseek，本轮没有改schema、没有将模型候选写成jev/hybrid；mainline_index及approved均未由程序填写。建议受控增加本地deepseek枚举后再实现审核导入。
- 结论：认证、分类契约和复用流程可用；未验证语义准确率、跨游戏泛化或前置关系。尚未全标124项，也没有对1000款执行模型批量请求。
- 下一步：人工审核这16项和规则差异；按两款完整清单复核提示词，完整初标预计8个20项批次，再建立审核与主线证据。确认本地method方案后实施迁移与审核导入，之后扩样。

## 2026-10-14：简化六表 SQLite 重建与已有试跑迁移

- 任务：按用户确认结构替换旧表；所有写入只在 result/LYX，共享 PostgreSQL 永远只读。
- 输入：旧库版本 lyx-probe-20261014-5cd7c874f114；原始报告 process/runtime/api_probe/20261014T030700254869Z/report.json。
- 输入报告 SHA256：ea783695aa3775d3324c845244f1986333c5014ca430af9d9483f19647efa1fc，重建前后未变。
- 当前结构：SQLite user_version=2，games / games_details / games_rate / games_time / achievements / achievement_types。单一当前快照，不保存JSON列或逐行数据/标注版本；不建立game_tags。
- 参数：旧库完整备份；本地BEGIN IMMEDIATE事务内改表及迁移；foreign_keys=ON，busy_timeout=5000ms，保持DELETE日志模式。
- 云库访问：PyCharm项目XML缺少完整凭据，最终通过根目录.env和psycopg连接成功；REPEATABLE READ READ ONLY，服务端transaction_read_only=on。仅读取两款的games / steam_appdetails / store_search_games / rawg_games；实际来源时间见迁移记录。
- 结果：游戏2款，三张背景表各2行，成就124项（63+61），类型127条；48项suggested、76项uncertain；approved=0，非空mainline_index=0。
- 校验：124项原始成就、127条类型及每项审核状态与旧备份逐项一致；integrity_check=ok，foreign_key_check为空；同报告真实重放already_imported=true、计数不变；已有API契约10项检查通过。
- 临时库验收：多标签、unknown互斥、外键、百分数/置信度/时间上下限约束、非主线排序拒绝、删除主线类型清空排序、导入事务、人工结果保护及变更原始输入拒绝。未新增测试用例；原多版本schema和入库检查归档到备份目录，已有API检查保留。
- 来源质量：重制版RAWG匹配为Final Fantasy VII，rawg_id=259801，存在版本疑点；本次不纳入playtime/metacritic/rating，对应本地值为NULL。重生playtime=71小时、rating=4.33；metacritic源缺失。攻略预计时间和难度尚未采集，全部NULL。
- 备份：database/backups/20261014T073823934541Z/achievements.sqlite；附old_schema.sql、migration.md及旧验证脚本。
- 结论：新结构与已有试跑链路可用，迁移没有丢失原始成就或规则分类。这不是分类准确率或用户粘性结论；规则候选仍待人工核验，未自动填写主线顺序。
- 下一步：人工核验两款的本体普通主线节点并填写mainline_index，另存必经性/前置关系和证据；审核典型支线、收集、挑战目标，再实现指标计算。细粒度标签与多路线研究暂缓，首版官方类型使用valve_genres解码。

本次没有调用Jev、批量采集攻略、修改共享依赖或执行Git提交/推送。

## 2026-10-14：评价数前1000款只读获取与迁移

- 数据版本：remote_import/20261014T081042433830Z；AppID数组SHA256=4e8fafab192456653c81dbc698d249b01f3602f5a9a6d439610c528cc89ddfde，20批来源快照的SHA256登记于checkpoint。
- 选择口径：store_search_games.review_count DESC、appid ASC，排除NULL，LIMIT 1000；不额外按年份、类型或主线过滤。评价数范围7326～634194。
- 实施：先保存database/data/top1000_appids.json，再完整备份SQLite，按50款/批只读提取，单游戏BEGIN IMMEDIATE原子写入；共20批、1000款、失败0。
- 连接：PyCharm项目XML缺完整凭据，根目录.env+psycopg成功；选择与全部批次均REPEATABLE READ READ ONLY，服务端transaction_read_only=on。无远端DDL、写入、worker或配额消耗。
- 字段：四张游戏级表各1000行，achievements=71465；新成就71341项pending，原48项suggested、76项uncertain与127条类型保留；mainline_index和攻略三个字段均全部NULL。
- 例外：两个FF7云库隐藏成就描述缺失，部分内部名/展示名与既有API输入不一致；保留原124项成就，四张背景表正常迁移。批次保留源值、报告记录冲突。重制版RAWG映射待核验，未纳入其评分和时长。
- 覆盖：4款没有成就记录、24款没有RAWG、1款发行日缺失、1款映射未解决；本地9942项描述缺失。RAWG时长938个正值、37个零值、25个NULL，正值仍需版本核验。
- 验收：1000个唯一AppID；998款成就和全部游戏背景字段与冻结来源逐字段核对；两个FF7原成就与迁移前备份逐字段一致；旧类型、审核状态完整保留；integrity_check=ok、foreign_key_check为空。
- 恢复验证：先真实运行50款核验，再使用原目录续跑至1000；完成后禁止read_remote的续跑验证通过，SQLite物理字节SHA256未变，没有远端请求或重复写库。
- 规模：SQLite=13,209,600字节，约12.6MiB。source_description_missing=10007，保留原FF7描述后local_description_missing=9942。
- 产物：process/import_snapshot.py、docs/IMPORT_SNAPSHOT.md、排名JSON、批次快照、before_import.sqlite、checkpoint.json、report.json、report.md。运行目录全部Git忽略，原API报告结构与文件未改。
- 结论：初步数据获取完成，含两个已明确保护的成就输入例外；这不是主线标注完成或分类准确率结论，不把1000款直接当正式分析样本。
- 下一步：先处理描述缺失和成就身份质量，建立两款FF7人工审核依据，再扩展分类与主线指标。没有调用Jev、自动批准、剧情排序或攻略采集。

## 2026-10-15：攻略参考时间/难度独立补全及单款真实试跑

- 数据版本：现有前1000款本地六表、user_version=3；本次只处理games_time三项guide字段，不改schema或分类链。已有用户未提交修改保留，不修改共享依赖、云库或提交/推送。
- 口径：Gamer Guides Steam成就总览参考值，scope=achievement_overview_reference；不是已确认主线平均时长/全成就耗时。示例Roadmap没有正文依据，缺口保留。
- 实现：process/guide_time.py、guide_time_parser.py、guide_time_storage.py；标准库固定title/class解析，完整名称身份核对，URL候选/显式别名，来源HTML指纹及重解析，在线备份、短事务NULL补全和冲突保护。来源、进度、报告及备份全在Git忽略的runtime/gamerguides。
- 参数：默认同域间隔3秒、并发1、HTTP预算20、单轮20款；预算计重试/跳转。跨轮按身份/URL/别名/解析器版本记录状态，缺页或部分缺失不阻塞后续批次。操作系统锁保护同runtime进度并随进程退出释放。
- 真实网页读取：浏览器DOM于2026-10-15T00:59:30.433Z读取ELDEN RING（1245620）h1和Time/Difficulty两项片段，原文21-32h、6/10；明确标记browser_dom，不冒充原始HTTP源码。
- 真实写入：runs/20261015T010545635436Z-7d2139a3；先完整before_apply.sqlite备份，再写21.0/32.0/6.0，playtime=62保留。主库三列各非空1款、各缺999款；其他五表及games_time的appid/playtime与写前备份逐表摘要完全一致，integrity_check=ok、foreign_key_check=0。
- 重放：runs/20261015T010637744153Z-7a71c147，真实HTTP请求0，write_counts.unchanged=1，没有重复修改。
- HTTP真实试跑：runs/20261015T010442031830Z-e9767680，一次403后source_paused，不写库、不标empty、不尝试后续游戏。网站批量访问尚未打通；现行站方条款要求系统采集和构建数据集事先取得书面许可，未绕过挑战或关闭TLS。
- 验收：临时SQLite在线备份与内联运行，不新增pytest。数值边界、NULL保留、冲突、过期名称、跨字段范围和重复写入均通过。MockTransport模拟404→partial→parsed，limit=1的三轮共3次请求推进，第四轮0请求；HTTP200挑战只1次即退出2，缺来源退出1，运行锁重入拒绝且释放后恢复。模拟值只写验收库，不作真实站点数据或覆盖率。
- 验收报告：process/runtime/gamerguides/validation/cli-20261015T010746864182Z/acceptance-report.json；命令和当前限制见docs/GUIDE_TIME.md。
- 结论：固定标签解析、来源记录、主库单款写入和离线批量重放可用；1000款网站采集尚未完成，HTTP访问受阻时必须暂停并保留缺失，不能将程序逻辑验收等同于网站批量成功。


## 2026-10-15：Codex驱动的Gamer Guides发现、浏览器采集与10款真实批次

- 用户确认已取得覆盖本项目的站方批量采集许可，按许可范围继续。执行前已`git pull origin main`；个人代码及记录限于LYX，没有提交或推送。
- 数据版本：`database/data/top1000_appids.json`含1000个唯一正整数，集合与本地games/games_time一致；文件SHA256=`4e8fafab192456653c81dbc698d249b01f3602f5a9a6d439610c528cc89ddfde`。六表及user_version=3保持，分类数据不参与攻略身份猜测。
- 实现：`process/guide_agent.py`交接CLI、`guide_agent_queue.py`持久队列；Codex负责真实站内目录/搜索和浏览器DOM，本地程序核验平台与完整名称或网页Steam AppID，解析固定chip并写三列。候选不能等同于身份确认，禁止拼slug当已发现链接；异名没有对应唯一Steam AppID时记ambiguous，不用成就重合自动合并版本。
- 发现参数：每款每轮至多两次搜索、三个候选；浏览器Steam目录实际遍历6页134卡片，FNV1a32导出校验`5376a370`，完整名称匹配55款候选。清单首10款实际搜索得到3款Steam候选，另外7款记no_verified_page并留搜索/误命中证据；不能据此宣称网站一定没有这7款。
- 真实浏览器采集：从55个候选中取前10款，2026-10-15T02:02:09.768Z至02:09:58.812Z读取实际H1、当前Steam平台、Time/Difficulty节点。攻略汇总页沿实际Steam列表链接导航；Fallout: New Vegas目录指向PS页，沿平台Steam链接切换后读取。两次浏览器导航超时后检查当前DOM，确认已抵达目标，没有将超时当缺页。
- 输入：`process/runtime/gamerguides/agent/inputs/first10-dom.json`，10条捕获FNV1a32=`49d9103e`与浏览器导出一致。`capture-batch`保存不覆盖的capture/identity/receipt和HTML片段、SHA256，来源明确browser_dom，不冒充HTTP原始源码。
- 口径：scope=`achievement_overview_reference`。7款带单位时间可解析；Cyberpunk 2077的`40-50`、Red Dead Redemption 2的`240-300`、Fallout: New Vegas的`80`没有单位，时间两列NULL并保留原文/警告，难度分别2、6、5。不能擅自解释为小时或主线/全成就的已核实耗时。
- 解析器升级为`fixed-chips-v2-unitless-partial`，旧v1来源允许经当前解析结果一致性核验后重放。10种无单位输入、6种既有带单位合法、12种应拒绝和3种缺值的离线执行通过；反转范围、异常文本及单位冲突仍拒绝。
- 真实写入参数：单进程、每批10款、默认NULL补全、overwrite=false。`agent/runs/20261015T021208494967Z-a278ffbc/report.json`记录10款written，先完整`before_apply.sqlite`备份，再逐款短事务。7款补齐三列，3款只写难度；增加24个非空字段。
- 真实结果（02:12 UTC快照）：时间上下限各覆盖8款、难度11款，完整三列8款；缺失分别992、992、989。队列状态applied7、already_complete1、partial3、candidates_found45、no_verified_page7、discovery_pending937，总数1000。候选/验收成功数不能冒充1000款完成。
- 重复同一apply命令：`agent/runs/20261015T021229216632Z-e54c6a45/report.json`，已完成7款跳过，3款partial返回unchanged，无新网页读取；六表与重复执行前备份一致。
- 主库验收：`agent/runs/20261015T021208494967Z-a278ffbc/validation.json`；只有预期10个AppID的guide列发生变化，其他五表及games_time的appid/playtime摘要与写前备份完全一致，schema一致，integrity_check=ok，foreign_key_check=0；旧Elden v1来源重解析通过，五个入口模块AST检查通过。
- 恢复/拒绝验收：`validation/agent-review-20261015T021048034041Z/acceptance-report.json`的21项临时库检查通过，涵盖跨AppID/捕获内容/时间混用拒绝、保护完成/导入/输入变化状态、img/br平台解析、Royal异名拒绝及对应Steam AppID接受、坏批次预检无状态变化、SQL提交后队列中断重放、字段回退和审计半行恢复。`validation/queue-recovery-5c998461/report.json`另验证70000字节尾行截断与9字节短写回退。临时数据未写主库，未新增pytest。
- 边界：这是可恢复的Codex浏览器批量流程和真实10款验收，仍需继续处理45个候选与其余发现任务；普通HTTP曾403暂停，未宣称HTTP批量已打通。访问挑战/验证码记blocked并暂停来源，未绕过挑战、登录、付费或关闭TLS。未改共享依赖、公共目录、云库或本地schema。
- 继续执行与交接提示见[GUIDE_AGENT.md](GUIDE_AGENT.md)。runtime中的原始数据、状态和备份均Git忽略。

## 2026-10-15：按用户指定口径解析无单位Time数字

- 执行前`git pull origin main`确认最新。用户指定无单位Time单数字同时填时间上下限、两个数字分别填上下限，只有空值才跳过；已有三款旧任务由用户人工补充，本次不采集、不apply、不修改数据库或队列。
- 新解析器为`fixed-chips-v3-unitless-hours`：80→80/80、40-50→40/50、240-300→240/300；无单位30+按单数字处理为30/30。明确小时/分钟单位保持原语义和换算，带单位30+ hours仍只有下限。空白或缺节点保留NULL；非空无法解析、负数、非有限数、反转范围仍报错。原文及按项目规则解释单位的说明保留。
- 来源兼容：make_record保存v3；verify_receipt及agent写入前的二次解析按来源保存的v1/v2/v3规则核验。旧v2三款仍返回原有NULL时间结果，不因规则升级自动补值或破坏重放；旧来源文件保持原样。
- 数据版本仍为1000款冻结清单，SHA256=`4e8fafab192456653c81dbc698d249b01f3602f5a9a6d439610c528cc89ddfde`，schema版本3。离线内联验收18种合法与9种应拒绝输入通过；已有三个真实DOM按新规则分别得到40/50、240/300、80/80，11份已有v1/v2来源均复核通过。三个修改模块AST检查通过，另经独立只读审阅确认旧apply来源版本一致。
- 验收前后SQLite、queue.json及全部已有capture/receipt JSON的SHA256一致；没有新网页/模型请求、没有pytest文件、没有提交或推送。同步更新GUIDE_AGENT、GUIDE_TIME及DATABASE的当前规则说明，历史批次记录保留旧口径。

## 2026-10-15：用远端HLTB三项时长替换本地攻略时间上下限

- 用户明确授权修改本地结构和导入：删除guide_time_hours_min/guide_time_hours_max，新增main_hours/extra_hours/completionist_hours，保留guide_difficulty、playtime与其余五表。执行前`git pull origin main`已确认最新，仅修改LYX，不提交或推送。
- 数据版本：仍为1000款冻结清单，AppID文件SHA256=`4e8fafab192456653c81dbc698d249b01f3602f5a9a6d439610c528cc89ddfde`；本地schema3→4，仍为六张业务表。games_time列序为appid、playtime、main_hours、extra_hours、completionist_hours、guide_difficulty；appid仍INTEGER主键。
- 远端读取：按本地games_time/games与冻结清单完全相同的1000 AppID，参数化`WHERE appid=ANY(%s)`查询public.hltb_games，不额外按名称匹配。一个REPEATABLE READ READ ONLY事务读取字段元数据和全部所需记录，transaction_read_only=on；没有远端DDL、worker、API采集或模型调用。
- 来源快照于2026-10-15T02:50:59.911114+00:00读取（北京时间10:50:59），文件`process/runtime/hltb_import/2026-10-15T025101.336302_0000-66419959/source_snapshot.json`；SHA256=`debf472e471596951bae4a05723f1cf83fee7bc1f851934892ff828bde74dde5`。该时间为读取云库时间，不宣称HLTB网站采集时间。
- 口径：main_hours/extra_hours/completionist_hours逐字段复制远端小时值；来源缺行或字段NULL时置NULL，失败不转为空行。有效0原样保留，不把0解释为已核实零小时。此快照匹配347款、缺行653款，三列各347非空、653 NULL，匹配行内源NULL均0；三列零值分别17/24/26。
- 实现：`process/import_hltb_times.py`提供fetch、apply --snapshot、import。fetch仅保存只读快照；apply先完整在线备份，再BEGIN IMMEDIATE单事务重建games_time并导入1000行。结构取database/schema.sql真源，删除两旧列，无新增业务表；事务内核对备份指纹、行数、五表摘要、appid/playtime/difficulty和源三列值，失败全部回滚；已有v4重复同步仅改不同的三项HLTB值。
- 主库真实导入：`process/runtime/hltb_import/2026-10-15T025331.038271_0000-360a6a2d/report.json`，2026-10-15T02:53:34.491311+00:00完成（北京时间10:53:34）。迁移前完整备份在同目录before_import.sqlite，保留旧结构及旧guide时间；结果schema4、1000条games_time、三项时长各覆盖347、难度11保留，已删除列在PRAGMA table_info中不存在。
- 数据保护：主迁移前后games/details/rate均1000、achievements71465、achievement_types2148，五表逐表摘要完全一致；games_time的appid/playtime/guide_difficulty摘要一致。标签2148来自用户此前其他分类运行，本次没有生成或修改分类结果。完整性ok，外键问题0，其余表/索引/触发器定义保留。
- 主库独立复核：同主运行目录validation.json逐行核对全部1000条与冻结远端快照、物理字段删除、appid主键、五表与保留字段、integrity/FK，全部通过；9个相关模块AST检查通过。DataAgent单款plan请求0/写库false、guide_time单款plan及生产guide_agent init均读取v4成功，生产队列只统计难度11完整、989缺失。
- 副本验收：`process/runtime/hltb_import/validation/actual-snapshot-90739efc/acceptance-report.json`使用真实来源在本地副本迁移，重复apply changed_rows=0、六表状态不变；故障注入在DDL和1000行写入后、commit前抛异常，回滚后旧v3文件SHA256完全不变，主库未受测试影响。
- 入口兼容：Gamer Guides新来源版本fixed-chips-v4-difficulty-only，只解析和UPDATE guide_difficulty，不再访问删除列或覆盖HLTB值。历史v1/v2/v3来源按保存版本复核并保留原审计值，旧队列的时长缺口在init时收敛为仅难度；旧Time策略现只用于历史来源复核。11份真实旧receipt、24项临时库/队列检查和8项解析边界验收通过，报告`process/runtime/gamerguides/validation/difficulty-only-5439bc2c/acceptance-report.json`。
- 旧标签迁移兼容：migrate_display_names/migrate_methods仅把v2标签结构升级为v3，已有v3保持v3、v4修复保持v4，不偷改时间结构；摘要检查实际所有字段。7组副本实际SQL场景通过，报告`process/runtime/hltb_import/validation/migration-compat-5dd9e34c3606/report.json`。既有DataAgent和累计分类CSV相关用户并行修改保留，不改变分类口径。
- 结论：本地结构和HLTB三列真实导入完成；347款匹配、653款缺口明确保留。来源快照、完整备份、报告与SQLite均Git忽略；操作与后续重同步见[HLTB_TIME.md](HLTB_TIME.md)，Gamer Guides后续仅补难度。
