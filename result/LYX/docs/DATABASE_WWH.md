# WWH借用冻结数据库：当前分析主源

数据库核验快照：2026-10-17；网页用途说明更新：2026-10-19。只读文件 `result/LYX/NewDB/wwh5.sqlite3`；约105.8 MB，SQLite user_version=0（此库按自身schema/metadata校验，不是LYX schema4）。源项目为组长WWH的第5方向，LYX复制适配程序在[analysis/T0Pre](../analysis/T0Pre/README.md)。本次文档同步未重新查询或修改原分类、剧情标识、数组顺序或数据库。

版本：`wwh5-2026-10-13T10:26:09.722887+00:00`；输入SHA256：`17a0c8e213e73d38ebf20939d5a26413dd49b858d3b315b4c6afa12722d0ebb0`；文件SHA256：`4c6ad6553b408efbecdd209c669f7ef9250da0f38c4f60e0e631660aaa35fae9`。2026-10-17记录的integrity_check=ok，foreign_key_check无问题。这是冻结快照，不是今日实时Steam统计。

## 原表与字段

| 表 | 行数 | 字段/连接 | 分析用途 |
|---|---:|---|---|
| metadata | 12 | key TEXT主键、value TEXT(JSON) | 数据版本、SQL、范围、输入指纹、active_annotation |
| games | 1000 | appid INTEGER主键、frame_rank INTEGER、review_count INTEGER、blocked_reason TEXT、payload TEXT(JSON) | 游戏与源数据快照、名称、评价、RAWG |
| achievements | 72616 | appid INTEGER、local_id TEXT、display_name TEXT、description TEXT、percent REAL | appid/local_id连接成就；percent为0～100 |
| achievement_labels | 69834 | appid、local_id、call_id INTEGER、payload TEXT(JSON) | 单成就分类，call_id→model_calls.id |
| game_labels | 988 | appid、call_id、payload TEXT(JSON) | 玩法/主题/表现/玩家模式等多维标签 |
| story_labels | 982 | appid、call_id、payload TEXT(JSON) | 剧情节点数组与统一结局判断 |
| model_calls | 3317 | id INTEGER主键、appid、kind、model、prompt_version、input_hash、request_messages、response_body、usage、status、attempt、error、started_at、finished_at | 标签关联与成功状态核验，原请求/响应审计；不是网页展示必需内容 |
| analysis_runs | 14 | id INTEGER、analyzed_at TEXT、metadata TEXT、metrics TEXT | 原有历史分析留痕；当前LYX另存CSV/JSON与manifest |

payload的JSON是WWH源库固有结构，LYX未改表。数字/空值/布尔从JSON解析后再验证；不能把不同库的local_id与api_name直接对等拼接。

排名按`steam_appdetails.type='game' AND release_date<'2026-01-01'`，SteamSpy正/负评价非负且非空，按positive+negative降序、appid升序，固定前1000款。metadata保存原SQL、只读REPEATABLE READ与导出时间；与[LYX旧库](DATABASE_LYX.md)的商店review_count前1000范围不同。

## 当前实际读取的payload

| 路径 | 含义 | 用到的分析 |
|---|---|---|
| games.payload.name_en/name_zh | 已有中英文名；中文缺失不造译名 | 全部，名称查询目录 |
| games.payload.achievements | local_id、原文和percent的源快照 | T0及任务1逐项核对独立achievements表 |
| games.payload.positive/negative/review_count | SteamSpy评价计数；好评率=positive/(positive+negative) | 任务5，任务6好评相近条件 |
| games.payload.rawg.playtime | 小时；负责人授权按用户平均游玩时长使用 | 任务4，与LYX副本核对 |
| games.payload.rawg.metacritic/rating/ratings_count | 媒体0～100、用户0～5、RAWG评分数 | 任务5，同140款做评分对照；0分不是有效低分 |
| games.payload.tags | 原始多源标签 | 游戏标签来源追溯；不替换gameplay闭集 |
| games.payload.steamspy_fetched_at/rawg.fetched_at/source_success_times | 源抓取时间 | 防止将冻结数据说成实时；不以分析日期替代来源时间 |
| achievement_labels.payload.primary_category | main/side/collection/challenge/other/uncertain | T0分类与候选判定；同时核对调用success |
| achievement_labels.payload.scope/requires_multiplayer | base/dlc/uncertain及多人要求（true/false/null） | 与主分类分离，不是LYX的dlc/multiplayer并列类型 |
| game_labels.payload.gameplay | 玩法数组，第一项为主类型，其余同属有效多标签 | 任务2分组、任务6Jaccard匹配 |
| game_labels.payload.theme/presentation/player_mode | 自由文本维度 | 任务5探索共性，保留原英文标签与不确定性 |
| story_labels.payload.checkpoints | 剧情节点数组，元素id/stage/route/confidence/requires_start | 任务1和3主线节点身份与顺序 |
| story_labels.payload.unified_ending/confidence | 结局结构及故事级置信度 | T0筛选、后续结局代理及分组边界 |

类型闭集和字段值以源程序/数据库为准；LYX的mainline与WWH的main概念相关但不是可直接覆盖的同一列。WWH将主类别、DLC范围、多人要求拆开，LYX八类允许多标签，两者不能通过改名无损互换。当前分析全面使用WWH结果，不做两库分类融合。

## 从1000款到198/183/65/140/181款

T0Pre保留原模型分类、证据门槛与质量剔除规则，在highest基线中有198款可用主线曲线；198款AppID顺序SHA256为`26b6a452b72e9466bced793868e7af8bd01c15980cf9bb4e27ab0799316f477b`。982款有story_labels并不意味着982款都有合格主线曲线。

1. 候选节点保留checkpoints原数组位置，不按解锁率或local_id排序。原数组索引从0开始，展示序号另外从1开始，不与LYX mainline_index混用。
2. 先保留有效common路线节点；非end按原顺序，end候选中选解锁率最高项，同率选原数组最先项，形成有效序列。结局采用最高单路线覆盖作代理，不把不同结局覆盖相加。
3. 首节点为序列第一项；至少3节点时，中位位置取零基`(n-1)//2`（偶数取靠前项）；末节点为已选代表结局。
4. 首、中、末覆盖为p_s/p_m/p_f，均转0～1。前段=p_m/p_s，后段=p_f/p_m，全程=p_f/p_s；分母<=0或所需节点缺失留空，分子0有效。15款只有两节点，全程可算，中位/前后段不补值。
5. 183款完整三节点用于类型主分析和Steam口碑；HLTB正值68且RAWG正值65用于时长；三评分有效交集140；同类主口径至少5参照时可比较181款（另外2款保持不足状态）。

当前候选节点1824行，选中序列1741行、相邻区间1543行。多结局/非唯一首位start、缺描述、已知模式限制等标记都保留；采用模型顺序不等于人工证明必经剧情或真实玩家留存。

## 连接与交接

PyCharm新增SQLite数据源选择本文件，保持只读使用。[storage.py](../analysis/T0Pre/wwh_replay/storage.py)的connect使用mode=ro、query_only和一致读事务，检查八张必需表；各层manifest再核对数据库SHA及固定样本。复制后只要文件字节不变，路径不同不影响指纹；应保留LYX内预期相对路径或显式适配。

当前[WEB简报](../WEB/index.html)由T1/T2正式结果的26张CSV与7份manifest构建，玩法、剧情节点和评分均沿用冻结来源，浏览时不读取本库或原请求响应。只演示可交付单文件HTML；修改后重建页面也只读已有结果。需自行适配时可用[交接包](../analysis/delivery/README.md)中的49张结果CSV、JSON和图。198款源表摘录包含11143条成就/11143条成就分类、198条玩法/剧情记录和587条调用索引，但不能取代原完整SQLite供T0全范围重跑。原库含model_calls大段历史文本，完整复算时私下传整库，不提交Git，也不作为公开静态文件发布。页面已保留RAWG来源回链；构建、交接及来源警告见[WEB说明](../WEB/README.md)。
