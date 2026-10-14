# 刘宇翔模块实验与实现记录

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
