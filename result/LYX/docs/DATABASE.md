# LYX本地SQLite数据说明

更新：2026-10-14。当前库为[achievements.sqlite](../database/achievements.sqlite)，结构见[schema.sql](../database/schema.sql)。当前任务是DeepSeek自动分类并写入本地标签关系与状态，共享PostgreSQL永远只读。

## 当前实际数据

| 表 | 行数 | 用途 |
|---|---:|---|
| games | 1000 | 游戏身份、中英文名 |
| games_details | 1000 | 官方细节；分类使用valve_genres |
| games_rate | 1000 | 历史评价/评分；分类不使用 |
| games_time | 1000 | 历史时长与空攻略字段；分类不使用 |
| achievements | 71465 | 原始成就、状态、既有排序 |
| achievement_types | 127 | 多类型及方法、置信度 |

本轮修改前后实际库一致：71,341项pending、48项suggested、76项uncertain、approved=0；127条类型全为rule，deepseek=0。18项已有非空mainline_index保留；字段布局和user_version=2不变，约12.6MiB。

清单：[top1000_appids.json](../database/data/top1000_appids.json)，排名明细：[top1000_selection.json](../database/data/top1000_selection.json)。996款有成就，4款无成就；默认保护18项，71,447项待分类。

本轮完整备份：[before_changes.sqlite](../process/runtime/archive/20261014T171916-deepseek-only/before_changes.sqlite)。完整性ok、外键无问题；模拟分类仅写临时库，没有写此工作库。SQLite适合当前个人规模，使用短事务，保持DELETE日志模式。

## 六表字段

| 表 | 字段与SQLite类型 | 主键/来源 |
|---|---|---|
| games | appid INTEGER；name_en TEXT非空；name_zh TEXT可空 | appid；远端games |
| games_details | appid INTEGER；is_free INTEGER；price_cents INTEGER；release_date TEXT；valve_genres TEXT | appid；steam_appdetails |
| games_rate | appid INTEGER；review_label TEXT；review_percent INTEGER；review_count INTEGER；metacritic INTEGER；rating NUMERIC(3,2) | appid；store_search_games+rawg_games |
| games_time | appid INTEGER；playtime INTEGER；guide_time_hours_min REAL；guide_time_hours_max REAL；guide_difficulty REAL | appid；playtime来自rawg_games，其余未接入 |
| achievements | appid INTEGER；position INTEGER；api_name TEXT；display_name TEXT；description TEXT；percent NUMERIC(5,2)；status TEXT；mainline_index INTEGER | (appid,api_name)，另有(appid,position)唯一 |
| achievement_types | appid INTEGER；api_name TEXT；type TEXT；method TEXT；confidence REAL | (appid,api_name,type)，外键关联成就 |

约束与口径：

- is_free为NULL或0/1；price_cents非负，沿用来源计价单位；release_date为来源日期文本。
- review_percent/metacritic为0～100；review_count非负；rating为0～5、最多两位小数，均可空。
- playtime为非负小时或NULL；攻略时间非负、两端有值时min≤max；难度0～10。当前三个攻略字段全部NULL，当前任务不再获取。
- position≥1是来源排列，不是剧情顺序；api_name是身份键，展示使用display_name，description可空。
- percent为0～100、两位小数，0有效；CHECK落实范围与小数位，导入用Decimal四舍五入。分类不读取它。
- mainline_index≥1或NULL，单游戏非空值唯一，必须有mainline标签；移除mainline会清空排序。本分类任务不填写它。
- confidence为0～1或NULL；模型输入校验拒绝非有限数，历史规则/人工不虚构分数。

valve_genres将PostgreSQL TEXT[]转为CSV转义的“|”分隔文本，不存JSON。Action|RPG为普通例子；含分隔符/引号时按CSV规则转义。用local_database.encode_genres/decode_genres，不直接split('|')；NULL表示缺失，空文本表示来源空数组。它仅为官方类型，不是完整用户标签；不建立game_tags表。

## 分类关系与状态

八类mainline/side/collection/challenge/multiplayer/dlc/other/unknown，每标签一行，允许多标签，unknown必须独占，触发器同时约束插入/更新。

method允许deepseek/jev/rule/manual，不支持hybrid。新流程仅写deepseek，其他值保留兼容历史记录，不运行其他方法。

| status | 含义 |
|---|---|
| pending | 尚无当前分类结果 |
| suggested | 明确且各类置信度达到阈值的机器分类；兼容历史规则状态 |
| uncertain | unknown或至少一类低于阈值 |
| approved | 既有人工确认；分类器不生成 |

阈值默认0.8只是分流，confidence不代表准确率。当前允许机器结果直接交付，不建立强制人工审核程序，suggested仍不能说成人工确认。

DataAgent按(appid,api_name)写入；整批校验后BEGIN IMMEDIATE替换自动标签并更新状态。文本/上下文改变回滚；approved、manual标签、非空排序号在选择和落库时都保护。重复相同结果无变更；不改变原始字段及游戏级表。

理由、原文、不确定说明、模型/提示词指纹保存在runtime报告，不新增SQLite JSON列或历史表。默认跳过已完成DeepSeek项，包括uncertain；--reclassify重做机器结果且仍保护人工成果。

method约束已由[migrate_methods.py](../process/migrate_methods.py)和[migrate_methods.sql](../database/migrate_methods.sql)迁移，本轮不重复改表。ensure_schema检查实际列、user_version及method CHECK。schema.sql可初始化新空库，不是日常启动步骤。

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
SELECT a.appid,a.display_name,t.type,t.confidence,a.status
FROM achievements a JOIN achievement_types t USING(appid,api_name)
WHERE t.method='deepseek'
ORDER BY a.appid,a.position,t.type;
~~~

每轮classify自动生成before_classify.sqlite。命令与恢复见[PROCESS.md](PROCESS.md)，不要日常运行旧重建或probe导入。
