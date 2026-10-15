# 刘宇翔模块实验与实现记录

按日汇总已经实现和验证的工作；时间均为北京时间，运行目录保留原UTC命名。历史规则仅解释当时结果，当前命令以[PROCESS.md](PROCESS.md)为准，字段与最新覆盖见[DATABASE.md](DATABASE.md)。原始响应、快照、备份和验收文件留在本地忽略目录。

## 2026-10-15

### 23:13 成就分类进度

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

### 今日实施与验证

**数据版本与范围：** 沿用冻结1000款、71,465项成就；AppID清单SHA256为`4e8fafab192456653c81dbc698d249b01f3602f5a9a6d439610c528cc89ddfde`。本地schema3→4，远端只读。

### 分类与恢复

- 修复Terraria完整响应因161字符引用被拒的问题：分类prompt v6允许每段evidence严格小于500字符，仍要求1～2段逐字原文。仅长度规则及版本不同、其余完整请求一致的v5/v4响应可重校验复用；Terraria的137项在隔离副本零新请求恢复。旧响应和历史报告不改写。
- HTTP 200中的JSON、截断或契约错误改为单游戏response_error，拒绝本款写库后继续；网络、认证、限流或存储故障仍停止。简介/分类增加90/300秒总时限，包含重试退避；每15秒终端及progress.json更新等待状态。读超时或总时限记request_timeout并继续，同类连续3次超时暂停。部分正文留档且禁止复用，Ctrl+C正常保存interrupted。
- 逐标签门槛由`>0.6`调整为`>=0.6`，不改变prompt或请求指纹。11:06离线扫描9份历史CSV的2666行，去重后累计2264行；补录74条0.6标签，涉及68项原未分类成就及6项已有成就的缺失标签。1项不相容结果记conflict并保留旧标签，新API请求0，重复导入新增0；既有标签、原始字段与18项排序保留。
- 新增datacache累计有效候选，每标签一行，按`(appid,api_name,type,request_hash)`去重；先留档再写SQLite、提交后刷新结果。20:08从20,036行累计表初始化failure_data，提取1,146条低分标签，涉及1,096项成就、79款游戏。低分表与全量表同为22列，按各行`confidence<min_confidence`派生；不同请求的低分历史保留，不能当作当前未分类清单。初始化不改全量CSV或SQLite。
- 14:41真实运行：2次新请求、5次本地缓存命中，星露谷49项/49标签写入，后续budget_reached；本轮6233 tokens。候选统计包含缓存和已有结果，不能用classified_count或successful_game_count当新增完成量。

验证覆盖499/500引用边界、0.59/0.6/0.61门槛、多标签独立筛选、缓存精确匹配、重复导入、人工/排序保护及事务回滚；超时、保活空行、部分响应和失败隔离使用本地传输替身与SQLite副本验收，不等于真实服务持续可用。未新增pytest。

主要证据：

- [引用与缓存恢复验收](../process/runtime/validation/20261015T001724182578Z-evidence-500/cache-recovery.json)、[批量失败隔离](../process/runtime/validation/20261015T001724182578Z-evidence-500/batch-scenarios.json)
- [超时链路验收](../process/runtime/tmo/012125400336/batch-verification.json)、[超时边界](../process/runtime/tmo/012125400336/edge-verification.json)、[中断收尾](../process/runtime/tmo/012125400336/interrupt-verification.json)
- [0.6补录报告](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/report.json)、[真实核验](../process/runtime/deepseek/cache_imports/20261015T030622858723Z/verification.json)
- [低分CSV初始化](../process/runtime/verification/20261015T120748902480Z-failure-data/initialization.json)、[真实分类报告](../process/runtime/deepseek/runs/20261015T064109506808Z/report.json)

### 时长与难度来源迁移

| 完成时间 | 实现与结果 | 验收 |
|---|---|---|
| 10:53 | 按1000个AppID只读复制hltb_games三类小时值；schema3→4，删除攻略时间上下限，新增main_hours/extra_hours/completionist_hours。各覆盖347款、缺653款，零值分别17/24/26，按源保留。 | 完整备份后单事务迁移；原playtime、当时11个攻略评分及其余五表摘要一致。全部1000款与快照逐项核对；重复apply改变0行，故障注入回滚通过。 |
| 21:49 | 全1000款同步game_difficulty.hard_ratio到guide_difficulty，Decimal ROUND_HALF_UP保留两位、不缩放；996款有效、其中68个0，4款缺行保留NULL。替换旧52个攻略评分。 | 只更新目标列，schema仍4；其余五表、RAWG及HLTB时长一致，完整性ok、外键问题0；舍入边界、重复导入与整批回滚通过。 |

HLTB来源读取时间为10:50:59，hard_ratio为21:48:12；这是云库读取时刻，不代表网站抓取时刻。当前guide_difficulty是完成率低于10%的成就占比（0～1），与成就完成率同源，不能继续解释为十分制攻略难度。

口径与证据：[时长与难度说明](DATABASE.md#时长与难度口径)、[HLTB报告及备份](../process/runtime/hltb_import/2026-10-15T025331.038271_0000-360a6a2d/)、[hard_ratio报告及备份](../process/runtime/hard_ratio_import/2026-10-15T134935.565882+0000-07f58359/)。

### 旧攻略获取方式（已弃用）

曾尝试从Gamer Guides成就总览提取Time/Difficulty固定节点。普通HTTP单次403后暂停；用户确认站方许可后，由Codex实际浏览站内目录及搜索结果，沿真实链接读取DOM，保存URL、平台、捕获时间、HTML指纹和身份依据，再由本地guide_agent/guide_time校验、备份并分批写入。固定节点为`.achv-roadmap-chip[title="Time"] .achv-roadmap-chip-value`及对应的`title="Difficulty"`节点；Time曾按小时/分钟及用户指定的无单位数字规则解析。候选页不等于身份已核验，访问受阻不记为确定性无数据。

持久队列保留1000项任务、搜索和receipt，支持中断恢复；后期仅在347款HLTB非空范围补难度，每批至多10款。Steam目录6页134卡片匹配55款候选；后续全平台目录12页268卡片，在用户接受PS/Xbox参考后自动新增28款，再经逐项人工确认新增13款（包含明确接受的版本及合辑参考限制）。新增50款目标实际完成41款；全库历史评分最终52款、HLTB范围45款，其余302款有限检索未确认页面，不能据此断言站点没有数据。

上述时间已由HLTB替代，52个旧评分已由hard_ratio替代。五个攻略源码文件归档至[process/old](../process/old/README.md)，队列、原始DOM和人工确认记录保留在原runtime路径，不再作为日常采集或当前难度口径；GUIDE_AGENT与GUIDE_TIME独立说明已合并至此并删除。历史证据：[首10款写入报告](../process/runtime/gamerguides/agent/runs/20261015T021208494967Z-a278ffbc/report.json)、[28款批次汇总](../process/runtime/gamerguides/agent/batches/run50-20261015/report.md)、[13款人工确认](../process/runtime/gamerguides/manual-review-20261015/review_status.md)。

本次源码清理单独删除已完成导入的import_hltb_times.py与import_hard_ratio.py；import_snapshot.py、import_classification_cache.py及inspect_remote.py保留原样。未重新获取数据或改动SQLite，runtime历史记录保持原位。

### 当日状态与文档整理

22:33本地只读快照：1000款、71,465项成就，标签39,943行覆盖37,364项；其中DeepSeek39,925行、覆盖37,346项。pending34,101、suggested32,247、uncertain5,117、approved0，18项排序保留。分类仍在推进，不能用标签涉及617款推断617款已全部完成。

整理文档导航、来源说明及每日记录，保留运行命令和关键契约；data_plan.md原文不变，其中分析专题尚未执行。本次整理只读核查本地实现、快照与运行证据，未调用模型、采集网页或改数据库。

## 2026-10-14

**数据版本与范围：** 从两款FF7的124项API输入起步，最终冻结评论数前1000款、71,465项成就；schema2→3。

### 本地数据准备

- 重建为games、games_details、games_rate、games_time、achievements、achievement_types六表，迁移原124项成就及127条规则标签；原始文本、状态与已有成果保留，完整性和外键核验通过。
- 远端store_search_games仅排除review_count=NULL，按review_count DESC、appid ASC取1000款，不额外筛年份、类型或主线。每批50款、20批只读提取，先保存清单和来源快照，再备份并逐游戏事务导入；中断续跑及完成后零远端重放已验收。
- 保留两款FF7本地124项原文，避免云端描述/API映射冲突；重制版RAWG版本存疑，未纳入其评分/时长。固定快照有4款无成就、24款无RAWG、1款缺发售日、1款映射未解决，本地9,942项描述缺失。RAWG时长938个正值、37个0、25个NULL；缺失和版本疑点不补猜测值。
- method收敛为deepseek/jev/rule/manual；随后标签表新增display_name，按复合身份回填127行并增加同步触发器，schema2→3。迁移先备份、事务重建、恢复约束与索引；旧标签、原始字段和18项排序保留，重复运行无变化。

### DeepSeek链路与真实验收

- 初期完成连接检查、两款各8项的多标签候选与零请求缓存重放；首次模型改写长ID导致整批拒绝，改用精确短引用ID。早期候选及规则比较未作为当前分类质量结论，旧probe/规则入口归档。
- 收敛为DeepSeek八类多标签直接分类，加入常量分类prompt、独立game_intro摘要及缓存；按游戏名/AppID发送整款原文，预算涵盖简介、分类与重试。背景摘要标记model_generated，不作为官方事实或成就证据。完整集合/文本校验、人工和排序保护、写前备份及短事务落库已实现。
- 首次真实单成就Grind It Out得到challenge=0.7，当时0.8仅用于状态分流，结果写为uncertain；其“达到70级”是否构成挑战暴露了普通成长边界问题，随后补入类别规则。该历史结果不代表当前门槛或准确率。
- 当日后来采用逐标签`>0.6`门槛（次日改为`>=0.6`）。引用上限由60放宽到150，修复《重生》完整响应中的准确长引用被拒；仅精确兼容旧请求且重校验，未重新请求模型。
- 用户零新请求恢复《重生》61项：写60、保留已有1；再以2次新请求完成HELLDIVERS™ 2的38项/41标签，随后budget_reached。当天21:58快照为DeepSeek102行覆盖99项，总标签168行；pending71,303、suggested125、uncertain37，approved0，排序18。工程链路跑通，未完成全量分类或语义质量评估。

关键参数与验证：整款输出估计`1024+160*N`，默认上限65536、输入字符阈值300000，超限跳过不拆分；当日默认预检16款超规模。隔离验收覆盖身份、证据、unknown互斥、多标签、低分筛选、人工/排序保护、缓存、幂等、输入变化回滚及预算暂停。说明集中到docs，旧命令与历史schema不作为日常入口。

主要证据：

- [基础导入目录](../process/runtime/remote_import/20261014T081042433830Z/)、[导入说明](IMPORT_SNAPSHOT.md)
- [method迁移备份](../database/backups/20261014T090228682686Z-methods/)、[展示名迁移备份](../database/backups/20261014T125409120039Z-display-names/)
- [单成就真实运行](../process/runtime/deepseek/runs/20261014T094723361217Z/report.json)、[整款零请求恢复](../process/runtime/deepseek/runs/20261014T133727794594Z/report.json)、[默认清单真实运行](../process/runtime/deepseek/runs/20261014T135413196167Z/report.json)

后续：推进剩余分类，另行组织语义抽查和主线必经性/剧情顺序核验；聚合分析以[data_plan.md](data_plan.md)为后续基础，不把自动标签、缓存命中或工程验收当成粘性或因果结论。
