# LYX整款分类流程与运行说明

更新：2026-10-14。链路为：**游戏名定位 → 读取完整成就 → 缓存/生成背景摘要 → 整款一次分类 → 校验 → 本地SQLite。** 默认不按固定成就数拆批。共享PostgreSQL永远只读，日常分类不连接远端。

## 程序与提示词位置

| 文件 | 职责 |
|---|---|
| [DataAgent.py](../process/DataAgent.py) | 游戏名/AppID选择、整款预检、共用客户端、缓存、预算、分类与写库 |
| [game_intro.py](../process/game_intro.py) | 游戏背景摘要提示词、响应校验和缓存调用 |
| [local_database.py](../process/local_database.py) | 本地连接、字段转换、结构检查、整款输入核对与原子存储 |
| [import_snapshot.py](../process/import_snapshot.py)、[inspect_remote.py](../process/inspect_remote.py) | 独立的只读数据准备，已有迁移完成 |
| [migrate_methods.py](../process/migrate_methods.py) | 已完成的一次性method维护 |
| [migrate_display_names.py](../process/migrate_display_names.py) | 已完成的本地版本2→3迁移，给标签表添加并回填展示名 |

分类常量CLASSIFICATION_PROMPT在DataAgent.py的导入区之后，版本lyx-deepseek-whole-game-v5；简介常量GAME_INTRO_PROMPT在game_intro.py的导入区之后，版本lyx-game-intro-v1。修改相应提示词时同步升级其版本。简介与分类使用不同任务命名空间，分类版本更新不会连带使简介缓存失效。

旧probe/规则脚本和旧代码备份保留在runtime/archive，历史命令不再是当前入口。当前命令没有--batch-size和--sample-size，不会默认每20项调用。

## 游戏选择与离线预检

先在项目根目录同步main，再进入LYX。使用已有环境，不修改共享依赖：

~~~powershell
Set-Location D:\PycharmProjects\achievement-analytics\result\LYX
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
| `plan`，或不写子命令 | 离线读取本地输入/缓存并打印预检；不调用API、不写库或运行报告 |
| `classify` | 对选中游戏执行缓存/简介/整款分类，并按门槛自动写本地SQLite；有运行报告及备份 |
| `check-connection` | 极小JSON响应检查，可复用缓存，最多1次新请求；不分类成就、不写SQLite |

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--max-requests N` | `2` | 本轮新API请求次数上限，非负整数；包含简介、分类及重试，缓存不计；`0`禁止新请求 |
| `--reclassify` | 不启用 | 允许更新已有机器结果，仍保护人工/排序；仍优先缓存，不表示强制重新请求API |
| `--min-confidence X` | `0.6` | 有限数0～1；逐标签仅写`confidence > X`，等于门槛也不写 |
| `--max-output-tokens N`，别名`--max-tokens` | `65536` | 分类输出估计的允许上限，范围32～384000；实际分类请求使用`1024 + 160 × 完整成就数`的估计值作为max_tokens，超限跳过，不自动拆批 |
| `--max-input-chars N` | `300000` | 输入字符预算，须为正整数；字符数不是token数 |
| `--timeout-seconds N` | `300` | HTTP读超时，须为正有限秒数；连接超时仍15秒 |
| `--database PATH` | `database/achievements.sqlite` | 已存在的LYX内SQLite文件，不自动创建或改表；日常要求schema版本3 |
| `--runtime PATH` | `process/runtime/deepseek` | LYX内的缓存、运行报告与进程锁目录；更换目录不会沿用原目录缓存 |

路径默认值按程序所在的LYX工作空间定位；手动传入的相对路径按当前终端目录解析，因此以下命令统一从LYX运行。简介输出上限单独固定512 tokens，连接检查为32，不随分类输出预算增加。

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan --appids 1462040 2909400
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan
~~~

plan完全离线，不调用模型、不写数据库或运行报告。显示每款完整成就数、待写项、保护项、输入字符/字节、输出预算和本地缓存。简介缺失时用最大长度预留估计输入，不将占位文本发给模型；字符数不是token，输出预算也不是实际用量或费用报价。

2026-10-14 13:58 UTC核查快照：《重生》61项已全部取得DeepSeek结果，待处理0；再次普通运行直接跳过。默认1000款预检为978款ready、16款oversized、4款无成就、2款已完成；71,348项待处理包含超规模游戏，正常路径预计新请求1956，重试另计。统计会随运行变化，以新的plan输出为准。

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

三行分别是预检、冻结清单分类、本地全库分类，按需要选择，不要求连续执行后两行。budget_reached表示预算暂停，重跑同一命令会用新一轮预算继续；已写项、简介和响应缓存保留。error表示接口/契约/文件/数据库问题，应先查看errors；当前会停止本轮，不自动跳过失败游戏继续全部任务。超规模游戏仍单列跳过，选择全量不等于已经处理超规模项。

--max-requests 0只允许复用本地缓存。缓存路径为process/runtime/deepseek/cache/<请求指纹>/receipt-*.json；原始响应和简介也通过此机制保存。分类结果与本轮简介在runs/<UTC时间>/report.json中关联，CSV每标签一行，sqlite_outcome表明written/unchanged/protected/already_classified/below_threshold；confidence_passed及label_sqlite_outcome区分每条标签是否通过门槛和实际存储结果。

v5把evidence上限从60改为150字符。仅这次长度放宽允许精确匹配的v4完整请求缓存回放：输入、摘要、模型、接口和生成参数必须相同，响应重新通过当前校验；其他版本或变化的输入不能套用。旧receipt保留原样，返回prompt_version=v4、requested_prompt_version=v5及compatible_cache=true，说明实际来源。新版本缓存优先使用。

用户已用以下缓存命令完成《重生》恢复：更新60项、保留已有1项，新请求0、缓存命中2，未处理0。再次普通运行会跳过；下列命令作为“有待处理项时只用缓存恢复”的示例，缓存缺失时仅暂停：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --game-name "FINAL FANTASY VII REBIRTH" --max-requests 0
~~~

## 简介、结构化输入与结果

简介只根据游戏中英文名及valve_genres生成40～80字符中文摘要；recognized=false时摘要为空且说明原因。它是模型背景摘要，不是Steam官方介绍；source=model_generated。简介不生成章节、成就条件、等级上限等细节，不修改SQLite六表，不抓网站。

分类输入顺序固定为：CLASSIFICATION_PROMPT → <game_context>名称、官方类型、模型摘要及来源/疑点 → <achievement_batch>全部成就名称和描述。原始成就条件优先，使用模型摘要或模型知识判断须声明knowledge_used及疑点。

输出仍是八类多标签、各类confidence、原文evidence、reason、uncertainty和knowledge_used。evidence是DeepSeek逐字引用的本项名称或描述，reason才是模型的分类解释；引用不允许来自背景摘要或其他成就。普通升级/成长不因数值目标自动归challenge。reason/uncertainty最多40字符，evidence为1～2段、每段最多150字符（含空格与标点），对应DataAgent.EVIDENCE_MAX_CHARS。超长、空引用、非原文引用分别报告成就ID/名称及原因。完整ID覆盖、闭集、互斥、长度与有限数检查通过后才落库；格式合格不证明语义准确率。

SQLite标签表保存appid/api_name/display_name/type/method/confidence，成就表保存状态。display_name来自对应原始成就，分类入库自动填写，来源改名时触发器同步；当前user_version=3。--min-confidence默认0.6，是逐标签写入门槛：只有confidence > 0.6才写入，等于0.6也不通过。例如mainline=0.9、challenge=0.55只存mainline；低分标签不拖累高分标签。通过的明确类别为suggested；独占的unknown也按相同门槛筛选，通过后仍为uncertain。不生成approved或排序号。

所有原始模型标签保留在runtime JSON的types中，同时单列accepted_types和rejected_types。全部未通过时sqlite_outcome=below_threshold，不删除旧标签、不改原有status，仍计入待处理；原先pending继续pending。已有DeepSeek/人工结果的保护规则仍生效，不主动清理历史低分结果。需要重筛已有机器结果时显式加--reclassify；阈值不进入API提示词或请求指纹，同一完整输入可用--max-requests 0复用缓存筛选，无额外请求。格式错误仍拒绝整款，原始错误响应留在receipt JSON。

## 预算、恢复与缓存统计

- 每轮classify先完整备份为运行目录before_classify.sqlite。HTTP发生在SQLite事务外。
- 响应先持久化再校验/写库；收到响应后中断可缓存恢复。简介和分类复用同一客户端，不各自超发预算。
- 写入前检查名称/类型和整款成就集合/文本；新增、删除或变化都会回滚整款，避免把旧响应配给变化的输入。人工成果和已有机器结果在写入时再次保护。
- 输出预算估计为1024+160×完整成就数，默认上限65536；输入字符阈值默认300000。超过任一配置限制为oversized_game，单列跳过，不自动拆分。可在plan评估后显式调整预算，估计不是输出保证。
- HTTP读超时默认300秒，可用--timeout-seconds调整；连接超时15秒。429、截断、契约错误及传输超时停止；连接失败/5xx有限退避，重试计入预算，失败不转unknown。
- state=budget_reached意味着尚有工作；success_with_skips表示大型游戏未处理；success_with_rejections表示有待处理成就全部标签未过门槛。remaining_pending_count和unprocessed_achievement_count包含这些未写项，不能只看退出码或classified_count（完整模型覆盖数）。accepted/rejected_label_count统计本轮模型标签筛选，包含保护项；written_label_count才是实际写入的标签数，sqlite_counts.written为写入成就数。

report.type_counts/unknown_count统计本轮完整模型候选，并非SQLite累计类型分布；旧项被保护或already_classified时，候选类型可能与被保留的数据库类型不同。核查实际分布应查询achievement_types。

local_response_cache_hits（兼容旧cache_hits）是本地响应复用次数。api_cache_hit_tokens/api_cache_miss_tokens/api_cache_hit_ratio来自本轮真实API响应，usage_by_task分开汇总简介与分类；缺失用量保持null，历史缓存用量不重复统计。

环境变量优先、根.env回退：DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL。官方HTTPS入口、TLS校验和密钥脱敏保留。用户已完成《重生》61项零请求恢复，以及HELLDIVERS™ 2的38项分类（41条多标签关系）；后者默认选1000款、预算2次后正常暂停。本次文档更新不调用API或写库，记录见[experiments.md](experiments.md)。
