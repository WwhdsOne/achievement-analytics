# PROCESS：数据准备沿革与当前DeepSeek分类链路

更新：2026-10-17。个人模块当前重心为[数据分析](data_plan.md)；本文件统一保存数据获取沿革和仍可运行的DeepSeek成就分类说明。旧DEEPSEEK_PLAN、API_PROBE及分类工程plan中的有效内容已合并；数据库定义分别见[LYX](DATABASE_LYX.md)、[WWH](DATABASE_WWH.md)，基础迁移摘要已并入LYX库文档。

## 数据获取和当前分析的关系

2026-10-14曾从两款FF7的API试跑开始，后按商店评价数冻结1000款，通过远端只读事务迁入LYX六表。连接曾优先读取IDE配置，最终用根.env；这些连接和迁移程序现已删除，日常DeepSeek只读本地输入、按授权写本地分类结果，不连接远端数据库。

Gamer Guides曾用于参考耗时/难度：普通HTTP遇到403后暂停，后来采用人工核验页面与DOM；没有把受阻当作确定性无数据。当前耗时已改为远端hltb_games的三类参考值，难度字段已改为game_difficulty.hard_ratio。旧网页探测、队列、DOM解析、导入与迁移入口和历史运行数据均已退役清理，不再提供抓取或断点恢复命令。来源、缺口、FF7版本例外及两份1000款范围区别见数据库文档。

当前五个分析专题使用WWH冻结分类、剧情数组和游戏类型，LYX仅补充HLTB；**不依赖本目录的DeepSeek分类是否补齐**。这里的LLM as Judge是DeepSeek根据八类语义规则直接判别，不是另设第二模型评审器；简介也由同一模型生成，不能算独立证据。工程校验和自报confidence不等于语义准确率，目前没有全量人工金标准确率结论。

## 保留的五个程序

| 文件 | 职责 |
|---|---|
| [DataAgent.py](../process/DataAgent.py) | 游戏选择、整款预检、客户端、缓存、预算、分类校验、协调CSV与SQLite |
| [game_intro.py](../process/game_intro.py) | 独立游戏背景摘要prompt、校验与缓存调用 |
| [deepseek_transport.py](../process/deepseek_transport.py) | 可取消HTTP、总时限、接收状态与部分响应；业务仍逐款串行 |
| [local_database.py](../process/local_database.py) | 只连接现有本地库、校验schema4、读取genres、筛选和原子写入 |
| [datacache.py](../process/datacache.py) | 每轮CSV与全量累计CSV、去重锁、原子替换、低分failure_data派生 |

分类常量CLASSIFICATION_PROMPT在导入区后，版本lyx-deepseek-whole-game-v7；简介GAME_INTRO_PROMPT版本lyx-game-intro-v2，也在导入区后。本轮只移除历史prompt拼接与旧版本缓存兼容分支，**当前两段提示词字节内容、版本和请求协议保持一致**。当前版本缓存仍正常重校验复用；没有保留旧v4/v5/v6、简介v1的回放入口。

## 完整链路

1. selected_appids/resolve_game_name定位本地游戏；load_games读取游戏名、官方类型和全部成就原文，并划分待处理、已分类与受保护项。
2. game_plan只读检查整款输入大小、估计输出预算及缓存；已完成或无成就游戏跳过。超规模游戏标记并跳过，不自动拆分。
3. get_intro先找当前版本合格本地缓存；缺失才发一条短请求。仅发送游戏名、中英文别名和官方类型，输出recognized/summary/uncertainty。
4. classification_messages组装固定system规则、game_context和achievement_batch。发送整款成就名称/描述及临时短ID，即使部分已有结果也保留完整上下文；不发送percent、时长、价格、好评率、排名或已有分类答案。
5. DeepSeekClient按预算、缓存和超时执行请求，先保存receipt，再校验完整JSON与逐字引用。简介与分类为两个任务命名空间，共享本轮请求预算。
6. classification_rows展开为本地身份；先将完整合规候选保存在本轮report及累计CSV，然后store_classifications进行输入一致性检查和逐游戏事务写入。
7. 按每个标签confidence>=0.6筛选，达标才写achievement_types；低分只留CSV/JSON。写入后再次刷新每标签结果、全量累计表与failure_data，最终保存本轮report、classifications.csv和progress。

单个游戏任何成就的结构/引用校验失败时，该次整款输出都不写库，也不以unknown冒充失败；原始完整/部分响应留新receipt，记录失败后继续下一款。门槛筛选则是结构校验之后的逐标签步骤，多标签中只保留达标项，不能把二者混为“整款没过0.6”。

## 提示词和输出契约

| 类别 | 语义边界 |
|---|---|
| mainline | 主线推进或结局；不能仅凭该标签证明必经性或排序 |
| side | 可选支线任务或剧情 |
| collection | 收集、探索或集合完成 |
| challenge | 明确特殊难度、技术、成绩或限制条件；普通等级/数值成长通常不算 |
| multiplayer | 该成就条件必须多人、在线或合作；游戏支持多人不代表全成就都需要 |
| dlc | 条件依赖扩展内容 |
| other | 含义明确但不属于上述类别，包括普通操作、成长、全成就汇总 |
| unknown | 证据不足；必须独占，不能与明确类别并存 |

允许mainline+challenge、collection+dlc等多标签。每项必须恰好返回id/types/evidence/reason/uncertainty/knowledge_used；types非空、类别闭集且不重复，confidence为0～1有限数；输入短ID集合完整且每项一次，不允许多漏或跨游戏错配。

**evidence是支持判断的原文引用，不是模型自由解释。** 每项1～2段非空连续片段，只能来自该成就display_name或description，逐字保持大小写；仅兼容NBSP与普通空格。每段严格小于500字符（最多499，含空格标点），不能引用简介、别的成就或补写括号说明。description为空时可引用已有名称；原文不足以判断则标unknown。

reason才是简短中文判定理由，非空且最多40字符；uncertainty最多40字符，可为空，但knowledge_used=true时必须说明具体待核验事项。引用正确仅证明文本可追溯，不保证类别语义正确。

简介recognized=true时summary为40～80字符，写作目标55～65以留余量，uncertainty<=80；不能可靠识别具体作品/版本则recognized=false、summary为空且解释原因。简介明确标记model_generated，不作为官方背景或具体成就条件证据。

## 命令和参数

先按项目约定在仓库根目录git pull origin main，然后进入result/LYX。以下命令均从LYX执行，使用现有依赖，不修改共享锁文件：

```powershell
uv --cache-dir analysis/delivery/runtime/uv-cache run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan --game-name "FINAL FANTASY VII REBIRTH"
```

| 子命令 | 行为 |
|---|---|
| plan，或不写子命令 | 离线读取输入/当前版本缓存并打印预检；无API调用、无库/CSV写入、无新运行目录 |
| classify | 实际分类、按门槛写本地SQLite，创建运行报告与写前备份；可能发生付费请求 |
| check-connection | 极小JSON响应检查，最多1次新请求，可命中本地缓存；不分类成就、不写库 |

四种游戏选择方式互斥，不指定则按database/data/top1000_appids.json冻结顺序；仅有游戏原始记录不等于已分类。

| 参数示例 | 含义 |
|---|---|
| --game-name "FINAL FANTASY VII REBIRTH" | 唯一的已有完整中文或英文名称；不一次传多名字；规范化后歧义则给候选，不猜选 |
| --appids 1462040 2909400 | 一个或多个正整数AppID，不重复 |
| --appids-file database/data/top1000_appids.json | LYX内JSON正整数数组，非空且唯一 |
| --all-games | 本地games全部游戏，AppID升序；与冻结清单处理顺序可能不同 |

| 运行参数 | 默认 | 说明 |
|---|---|---|
| --max-requests | 2 | 本轮真实API尝试总次数，简介/分类/重试都算，缓存不算；0禁止新请求，不等于无限 |
| --reclassify | 关闭 | 允许更新机器结果；仍保护人工/批准/非空mainline_index；仍优先缓存，不是强制重新请求 |
| --min-confidence | 0.6 | 逐标签>=，等于0.6可入库；自报分数不是准确率 |
| --max-output-tokens，别名--max-tokens | 65536 | 上限32～384000；分类实际请求上限按1024+160×完整成就数估计，超限跳过 |
| --max-input-chars | 300000 | 正数，字符预算不是token或费用 |
| --timeout-seconds | 300 | HTTP读超时；连接超时仍15秒 |
| --intro-total-timeout-seconds | 90 | 简介完整请求总时限，包含重试与退避 |
| --classification-total-timeout-seconds | 300 | 整款分类完整请求总时限，包含重试与退避，保活空行不续期 |
| --database | database/achievements.sqlite | 已存在的LYX内schema4库，拼错不创建空库，不自动DDL |
| --runtime | process/runtime/deepseek | 新请求缓存、报告、备份和锁；实际运行时创建，可指定LYX内其他目录 |
| --datacache | process/datacache.csv | 累计22列CSV，同目录派生failure_data.csv |

路径默认按程序位置确定；显式相对路径按终端当前目录。简介单独max_tokens=512，连接检查32。默认不按成就数分批，没有--batch-size或--sample-size。

显式授权要继续分类时可用：

```powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --game-name "FINAL FANTASY VII REBIRTH" --max-requests 2
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --max-requests 100
```

这两条会进入可能调用API/写库的路径，**本次清理没有执行**。单游戏通常需要简介+整款分类两次，不含重试；100次请求不是100款游戏。--max-requests 0只可复用清理后新积累的合格receipt，累计CSV本身不当作请求缓存。

## 已有结果保护与SQLite持久化

人工/approved/非空mainline_index受保护；默认跳过已有DeepSeek结果的成就，整款仍有缺项时可读取全部原文重新生成上下文。同一成就已有DeepSeek结果时默认跳过；--reclassify才允许替换其机器标签，结果完全一致不重复写入。旧的历史导入补标签模式已经移除。写入前检查appid/api_name、原文与本次输入一致，冲突不覆盖。

每款以BEGIN IMMEDIATE事务处理，异常回滚该款，前面已提交的游戏不回滚。原始名称、描述、percent和剧情排序不被分类覆盖；achievement_types含display_name。自动标签为suggested，unknown为uncertain，不自动approved。通过标签数、写入成就数、already_classified/unchanged/protected/below_threshold分别统计；database_writes=false表示本轮没实际新增/更新，不表示历史库无数据。

## 本地记录、缓存和本轮清理后行为

| 层次 | 保存位置 | 内容 |
|---|---|---|
| 请求审计 | process/runtime/deepseek/cache/请求哈希/receipt-*.json | 请求payload、完整或部分响应、时限/错误/usage等；只有完整200且通过当前校验才可复用 |
| 每轮执行 | process/runtime/deepseek/runs/时间戳/ | report.json、progress.json、classifications.csv、before_classify.sqlite |
| 全量累计 | process/datacache.csv | 所有通过结构校验的标签，含达标、低分、已有、受保护及写入结果 |
| 低分派生 | process/failure_data.csv | 逐行confidence<该行min_confidence的标签，不等于全体待处理成就 |
| 当前结果 | SQLite achievement_types | 合格且实际已提交标签；不保存reason/evidence长文本 |

每轮CSV17列：appid/name_en/api_name/display_name/description/type/method/confidence/status/sqlite_outcome/confidence_passed/label_sqlite_outcome/knowledge_used/evidence/reason/uncertainty/request_hash。累计CSV另加min_confidence/confidence_comparison/source_csv/first_seen_at/last_seen_at，共22列；键为appid/api_name/type/request_hash，更新时保留首次出现时间。CSV有表格公式转义，不能把转义前缀当作游戏原文；程序处理后原文仍由SQLite核对。

累计表和低分表由同一把文件锁保护并原子替换；整款多标签某条低分，即使另一个标签写入成功，该低分条也保留在failure_data。同一成就不同请求版本可有多条候选，不能用CSV行数代替待处理数。缓存命中仅表示节省请求，结构和evidence仍重新校验，低分重复回放不会自动升分。

2026-10-17删除旧process/runtime全部历史、old目录、旧字节码/临时文件及一次性import_snapshot/inspect_remote/import_classification_cache/migrate_display_names/migrate_methods入口；local_database只保留当前schema4校验和分类所需功能。**datacache/failure_data仍是当前链路的活跃产物，因此保留并核对内容指纹**：全量54869行，低分2996行。它们不再具有全部原始receipt的回放依据；旧source_csv地址作为历史出处文本保留。未通过结构校验的旧响应随runtime清理删除，未移入分析结果包。

清理不影响已提交SQLite结果；默认跳过已分类仍有效。旧运行目录、原始响应和写前备份不可再恢复；新的classify/check-connection会重新创建runtime和后续缓存。没有调用API验证新prompt行为，也没有根据累计CSV自动改库。原有database/backups不在本次删除范围。

## 请求预算、等待与故障

本地响应缓存与DeepSeek服务端前缀缓存分开计：前者不请求、不新增token；后者仍是真实调用，usage中prompt_cache_hit/miss_tokens统计，不能保证命中或把null使用量当0费用。环境变量优先于根.env：DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、DEEPSEEK_MODEL；默认官方HTTPS地址和deepseek-flash。不输出密钥，不读PyCharm凭据连接云库。

每15秒报告当前游戏、阶段、总耗时/剩余、收到字节及是否非空白。简介90秒、分类300秒覆盖整个调用；空白保活不能无限拖住。可重试错误沿原有限尝试与退避处理，超时不立刻重发；同类任务连续3次超时暂停整轮，按原状态报告。预算耗尽budget_reached是正常预算停止；响应校验失败跳过游戏，completed_with_errors不是全成功。

Ctrl+C由可取消传输与顶层处理，记录interrupted并释放锁；若强杀进程，最后未提交事务由SQLite回滚，先前提交保留，但最后report/CSV可能落后于库。恢复前先离线plan并核查数据库，而不是删除锁/清缓存或重复付费。全量任务不要把任务进度、token使用、成功游戏数和入库标签数混用。

分析数据的上传选择、汇总/来源表和保护核验见[delivery](../analysis/delivery/README.md)，日常读图见[统一INSTRUCT](INSTRUCT.md)与[T2说明](../analysis/T2Sum/README.md)。
