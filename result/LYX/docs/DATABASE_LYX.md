# LYX本地数据库：原始准备与DeepSeek分类

数据库核验快照：2026-10-17；网页用途说明更新：2026-10-19。文件 `result/LYX/database/achievements.sqlite`，SQLite `user_version=4`。原核验的完整性与外键通过，本次文档同步未重新查询或修改数据库。分析现已采用[WWH冻结库](DATABASE_WWH.md)，本库主要为分析补充HLTB三类参考耗时，仍保留既有DeepSeek分类成果。

## 当前只读核查

| 表 | 行数 | 主键 |
|---|---:|---|
| games | 1000 | appid |
| games_details | 1000 | appid，外键games |
| games_rate | 1000 | appid，外键games |
| games_time | 1000 | appid，外键games |
| achievements | 71465 | appid/api_name；另有appid/position唯一约束 |
| achievement_types | 51872 | appid/api_name/type，外键achievements |

DeepSeek标签51854条，覆盖48390项成就、803款游戏；另外18条rule标签属于受保护的历史记录。标签条数不等于成就数，更不等于语义人工核验完成数。历史2026-10-15的分类进度留在[实验记录](experiments.md)，不冒充当前值。

文件SHA256：`9690c8ca6bf9e727760992a99f57fca595d3561e15f5ff5e7f4abd846bfe2585`。这份文件是分析绑定的快照，若以后继续分类导致文件哈希改变，需显式核验和刷新分析来源；本轮没有运行classify。

## 六表字段及来源

字段精确类型、CHECK、外键、名称同步及unknown互斥触发器以[database/schema.sql](../database/schema.sql)为准。数值型SQLite列仍需按有效范围解释，NULL不补0。

| 表 | 字段与类型 | 原来源/用途 |
|---|---|---|
| games | appid INTEGER；name_en TEXT NOT NULL；name_zh TEXT | 远端games；AppID主连接键，中文名允许缺失 |
| games_details | appid INTEGER；is_free INTEGER；price_cents INTEGER；release_date TEXT；valve_genres TEXT | steam_appdetails；布尔0/1、日期YYYY-MM-DD、价格分。价格保留历史数据，当前分析不用 |
| games_rate | appid INTEGER；review_label TEXT；review_percent INTEGER；review_count INTEGER；metacritic INTEGER；rating NUMERIC(3,2) | store_search_games前3项评价信息 + rawg_games媒体/用户评分。当前评分专题改读WWH源，不混用此表 |
| games_time | appid INTEGER；playtime INTEGER；main_hours REAL；extra_hours REAL；completionist_hours REAL；guide_difficulty REAL | RAWG小时、HLTB三类小时、game_difficulty.hard_ratio |
| achievements | appid INTEGER；position INTEGER；api_name TEXT；display_name TEXT；description TEXT；percent NUMERIC(5,2)；status TEXT；mainline_index INTEGER | 远端原文/完成率 + 本地分类处理状态/旧排序；percent为0～100，position从1开始 |
| achievement_types | appid INTEGER；api_name TEXT；display_name TEXT；type TEXT；method TEXT；confidence REAL | 本地多标签结果；每个成就可多行，不在achievements重复保存标签 |

`valve_genres`为PostgreSQL TEXT[]转来的CSV转义竖线分隔文本。NULL是缺失、空文本是空数组；含竖线/换行/引号的单项需按CSV规则读取，不能简单split。当前[local_database.py](../process/local_database.py)保留decode_genres供DeepSeek读取。这是Steam官方分类，不是WWH的gameplay语义玩法标签。

`api_name`仅作身份连接，正式图表使用display_name。achievement_types.display_name由原成就同步；更新/插入触发器负责一致性。method允许deepseek/jev/rule/manual以兼容已有数据，当前agent只写deepseek。status允许pending/suggested/uncertain/approved；自动门槛通过仍只是suggested，unknown通过为uncertain。`mainline_index`为旧人工排序，当前分析不读它，也不由DeepSeek填写；当前分析顺序来自WWH的checkpoints数组。

八类为mainline/side/collection/challenge/multiplayer/dlc/other/unknown，unknown独占。confidence是模型自报数值，当前逐标签`>=0.6`可自动入库，人工/批准/已有排序受保护。输入、校验、备份、CSV和终止逻辑统一见[PROCESS](PROCESS.md)。

## 时长与难度：不要混淆单位

| 字段 | 含义 | 当前覆盖1000款 |
|---|---|---|
| playtime | RAWG playtime，按负责人授权作为用户平均游玩时长（小时） | 正值938，0值37，NULL25；零值不当作有效正时长 |
| main_hours | HLTB主线参考耗时，小时 | 非NULL347；0值17，正值330 |
| extra_hours | HLTB主线＋支线参考耗时，小时 | 非NULL347；0值24，正值323 |
| completionist_hours | HLTB全收集参考耗时，小时 | 非NULL347；0值26，正值321 |
| guide_difficulty | 远端视图game_difficulty.hard_ratio，0～1 | 非NULL996，NULL4；Decimal ROUND_HALF_UP保留两位小数 |

HLTB来自远端 `hltb_games`，2026-10-15按AppID导入；三列各653款NULL。NULL代表此次本地无匹配/无值，不证明HLTB网站没有该游戏；零值保留源语义，正式时长样本要求正值。schema4已移除旧guide_time_hours_min/max，不再采Gamer Guides参考区间。导入脚本已完成并移除，当前DeepSeek链路不能重新抓取这些数据。

guide_difficulty虽保留旧字段名，**现在不是Gamer Guides的1～10难度评分**。hard_ratio按源视图成就解锁率低于10%的比例构建，与成就覆盖同源，不是独立专家难度；当前五个专题不用它，不能不说明同源关系就拿来解释推进率。4个缺失AppID：511960、1404210、1962663、3028330。

HLTB的参考人群与RAWG统计口径不同，比值不是个人主线完成度。固定198款WWH分析样本只有161款匹配本库；三节点且HLTB主线正值68款，其中RAWG正值65款，三类时长比较固定这65款。详情见[交接审查](../analysis/delivery/AUDIT.md)。

## 基础迁移摘要（原IMPORT_SNAPSHOT内容）

2026-10-14从远端store_search_games按`review_count DESC, appid ASC`取1000行，排除NULL，没有额外加发售年份、类型、成就数或RAWG覆盖门槛。固定清单和排名SQL/读取时间记录保留于[AppID清单](../database/data/top1000_appids.json)、[选择来源](../database/data/top1000_selection.json)，评价数范围7326～634194。不要把这个范围与WWH的“2026年前发售、SteamSpy正负评价合计排名”范围混为一谈。

当时优先尝试PyCharm配置，最终使用根目录.env连接。远端采用只读事务，50款/批、20批分别REPEATABLE READ；不是跨全程一致事务，各源抓取时刻也不同。没有触碰共享库结构、worker或写入接口。原始迁入games、steam_appdetails、store_search_games、rawg_games、achievements字段；BOOLEAN转0/1、日期转文本、完成率两位小数，缺失不补零。

既有类型、status和排序按appid/api_name保护；FF7两款存在原文/映射差异，保留原本地124项成就及127条类型作为当时迁移例外（不是当前类别总量），不宣称全部字段与远端逐项一致。FF7重制版RAWG曾误匹配原版，相关playtime/评分未纳入；其它AppID有值也不等于版本已人工逐一核验。未解决名称映射不得进入正式分析；缺描述、无RAWG、无成就分别解释。

迁移和结构升级已经完成：display_name回填、method扩展、HLTB字段替代、hard_ratio同步均为历史操作。2026-10-17删除一次性导入/迁移脚本和process/runtime旧批次、checkpoint、请求响应及写前备份，本文保留可核实的来源和边界，不再提供失效的resume命令或承诺旧批次可恢复。`database/backups`原有备份未清理；它们可能是旧schema，不能直接当作当前快照。

## PyCharm与只读核验

Database → New Data Source → SQLite → File选择本文件的绝对路径，下载驱动后Test Connection，刷新Schema即可。分析连接采用URI `file:///.../achievements.sqlite?mode=ro` 并开启 `PRAGMA query_only=ON`；IDE中编辑网格不会更新到Python自动刷新视图，运行后需重新刷新。此轮数据库保持只读。

```sql
PRAGMA user_version;
PRAGMA integrity_check;
PRAGMA foreign_key_check;
SELECT method,COUNT(*) AS labels,COUNT(DISTINCT appid) AS games
FROM achievement_types GROUP BY method;
SELECT COUNT(*) AS mismatched_names
FROM achievement_types t JOIN achievements a USING(appid,api_name)
WHERE t.display_name IS NOT a.display_name;
```

现成[WEB交互简报](../WEB/index.html)已内嵌由正式结果表整理的游戏/时长展示数据，打开页面不读本SQLite。只演示可交付单文件HTML；重建页面读取T1/T2已有CSV与manifest，不重新查询本库。若另外适配数据，可参考[delivery/package](../analysis/delivery/README.md)中的游戏/时长摘录和计算结果；按现有分析代码完整复算仍需整份原SQLite及指纹。不得将SQLite、累计CSV或原始导出提交Git；网页打开、构建与交接见[WEB说明](../WEB/README.md)。
