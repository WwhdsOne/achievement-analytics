# LYX 总体规划：DeepSeek成就多标签分类

更新：2026-10-14。负责人：刘宇翔。按最新决定，当前目标收缩为：**用DeepSeek对本地成就进行八类多标签判断，将结果直接存入SQLite。** 主线漏斗、参与深度、用户粘性分析、规则对照和人工审核程序退出当前实施任务；mainline仍是分类标签，不附带剧情排序任务。

所有编辑只在result/LYX，其他项目目录只读，共享PostgreSQL永远只读。详细说明和实验记录集中在本docs目录，各子目录README保留入口索引。不自动提交或推送。

## 目标与完成标准

输入为冻结的前1000款AppID及本地原始成就。每个待分类成就获得一个或多个标签，每类记录method=deepseek及模型自报confidence；理由、原文片段和不确定说明保存在运行报告，不新增SQLite JSON字段。

完成标准：待分类输入均有合格模型结果，或明确记录失败/待续跑；身份覆盖、类型闭集、多标签和unknown互斥检查通过；原始字段和既有人工成果不被覆盖。网络失败不能生成unknown，也不算分类完成。覆盖率与语义准确率分别解释。

| type | 含义 | 判断重点 |
|---|---|---|
| mainline | 主线 | 主线推进或结局；不证明必经性或顺序 |
| side | 支线 | 可选支线任务或剧情 |
| collection | 收集 | 收集、探索或集合完成 |
| challenge | 挑战 | 特殊难度、技术、成绩或限制条件 |
| multiplayer | 联机 | 条件要求多人、在线或合作 |
| dlc | DLC | 条件依赖扩展内容 |
| other | 其他 | 含义明确但不属于以上类型 |
| unknown | 未知 | 证据不足，必须独占 |

允许mainline+challenge、collection+dlc等组合。游戏支持多人不意味着每项成就都是multiplayer；“all”一词不足以判collection。使用模型背景知识须声明具体不确定点，不能冒充外部核验。

## 阶段一：固定输入（已完成）

从store_search_games按review_count DESC、appid ASC取1000款，冻结到database/data/top1000_appids.json，排名与来源信息另存top1000_selection.json。数据通过远端只读链路迁至本地六表：1000款、71,465项成就，996款有成就，4款无成就记录。

保留数据缺口：9942项描述缺失、1款名称映射未解决；两款FF7源输入与既有API报告冲突，保留原124项本地输入。缺失信息不伪造。评价/时长表保留历史数据，当前分类不用，也不再采集攻略耗时、难度或其他网站。

验收：清单唯一、来源可追溯、身份键检查及SQLite完整性/外键通过。数据准备工具独立，日常分类无需连接远端。

## 阶段二：模型输入与契约（已实现）

入口为process/DataAgent.py，输入包含游戏中英文名、官方类型valve_genres、成就展示名和描述。当前库没有游戏简介/细粒度标签字段，本轮不新增或补抓这些信息；valve_genres只代表官方类型。

按身份哈希稳定排列并赋短引用id；appid/api_name留在本地关联。完成率、评分、时长、原始position、旧标签和排序号不进入模型。--sample-size固定选前N项用于试跑，不称随机准确率样本。

响应仅为id、types[{type,confidence}]、evidence、reason、uncertainty、knowledge_used。严格检查不增不漏不重复、闭集、有限数、unknown独占及逐字文本依据；截断或非法响应拒绝整批。不再生成scope、ordinary_mainline、target_depth、规则比较或人工修订空栏。

## 阶段三：直接写库与恢复（已实现）

process/local_database.py负责本地连接与原子写入。HTTP在事务外进行；响应和关联记录先保存，再核对当前上下文/文本，短事务替换自动标签并更新状态。

- achievement_types每标签一行，method=deepseek。
- 明确类型且每类置信度≥默认阈值0.8时为suggested；unknown或任一低于阈值为uncertain。阈值不是准确率。
- approved、manual标签或非空mainline_index受到保护。当前实际库18项既有排序号保留；程序不生成approved或剧情排序。
- 默认跳过已有DeepSeek结果，包括uncertain；--reclassify才重做机器分类，仍保护人工成果。
- 每轮classify先完整备份，成功响应可缓存重放；运行锁、有限重试、实际请求预算和逐批提交支持恢复。失败不转unknown。

验收已在临时真实SQLite与模拟HTTP中通过：多标签、幂等、人工保护、输入变更回滚、缓存恢复、预算续跑。没有新增pytest用例，真实模型请求0，实际库分类记录没有改变。

## 阶段四：真实分批分类（待执行）

1. 先用plan核对选择范围、待分类项和批次数。
2. 选两款FF7或少量游戏试跑classify，观察分类内容和实际token；该命令自动写本地库，备份自动生成。
3. 按已确认预算设置--max-requests，沿冻结1000款清单逐轮推进；预算包括重试，重复运行默认处理剩余项。
4. 每轮记录模型、提示词版本、输入指纹、参数、请求/token、写入数、unknown和失败。budget_reached是部分执行，不是全量完成。

本轮离线plan：71,447项待分类、18项保护，20项/批共4023批，v3缓存0。默认最多2次请求仅支持有限试跑；全量费用需依据实际token及执行时价格，当前未估价。

## 阶段五：核查与交付（真实分类后）

统计已分类、unknown、待处理、受保护和失败，按游戏/类型汇总覆盖。抽查语义帮助判断质量，但不建立强制人工审核流水线，不将未经验证的质量写成准确率。

交付代码、schema、说明和实现记录；数据库、排名、缓存、报告与备份保留在Git忽略目录。后续若恢复分析目标，另行规划指标与证据。

入口：[流程与命令](PROCESS.md)、[模型契约](DEEPSEEK_PLAN.md)、[数据库说明](DATABASE.md)、[数据准备](IMPORT_SNAPSHOT.md)、[实验记录](experiments.md)。
