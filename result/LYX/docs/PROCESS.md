# LYX流程与运行说明：DeepSeek分类

更新：2026-10-14。当前链路为：**本地SQLite → DeepSeek八类多标签判断 → 整批校验 → SQLite关系表与状态。** 不再运行规则比较、参与深度、主线指标或人工审核程序。

## 当前文件

| 文件 | 用途 | 地位 |
|---|---|---|
| process/DataAgent.py | 选择输入、提示词、HTTP、校验、缓存、结果写入 | 分类入口 |
| process/local_database.py | 本地连接、字段转换、结构检查、原子写入 | 共用基础 |
| process/import_snapshot.py | 远端只读提取前1000款并迁入本地 | 独立数据准备，已完成 |
| process/inspect_remote.py | IDE配置优先、.env回退的只读连接/核查 | 数据准备依赖 |
| process/migrate_methods.py | 备份后迁移本地method约束 | 一次性维护，已执行 |

旧probe_achievement_types.py、import_probe.py及API_PROBE.md归档到process/runtime/archive/20261014T171916-deepseek-only/process，日常不使用。旧重建脚本和probe测试本轮开始前已不在活动目录，本轮没有新增测试文件。归档保存原始路径逻辑，不能直接当活动入口运行。

import_snapshot.py的sqlite_percent已改从local_database.py获取，和旧probe解耦。历史缓存、报告、数据全部保留。归档目录另存修改前代码和完整before_changes.sqlite。

## 输入与输出

默认清单database/data/top1000_appids.json。--appids、--appids-file、--all-games三者互斥；非法/重复AppID或本地不存在的游戏拒绝。

只向模型发送游戏名称、官方类型、成就展示名/描述；当前没有简介或细粒度标签字段。不发送api_name、解锁率、评分、时长或规则结果。

SQLite保存标签和状态；report保留理由、原文依据与不确定说明；classifications.csv每标签一行，不含人工审核空栏。提示词版本lyx-deepseek-multilabel-v3；旧缓存保留，但不自动套用新契约。

## 命令

先从项目根目录同步main，再进入个人目录。沿用已有环境，不修改共享依赖：

~~~powershell
Set-Location D:\PycharmProjects\achievement-analytics\result\LYX
$env:UV_CACHE_DIR = "$PWD\process\runtime\uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan
~~~

plan离线，不调用模型、不写SQLite或运行报告。当前1000款有71,447项待分类、18项保护，20项/批4023批，4款无成就。预览字符数不是token，也不是费用报价。

两款FF7少量试跑如下。**classify会请求模型并自动写入本地数据库：**

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --appids 1462040 2909400 --sample-size 8 --max-requests 2
~~~

沿前1000款逐轮推进：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py classify --max-requests 10
~~~

10是包含重试的实际请求上限，不是10款游戏。每批最多20项；默认最多2次请求，不自动全量付费。重复运行跳过已完成DeepSeek项，继续剩余输入。--max-requests 0禁止新请求，只复用同参数/输入的合格缓存。

其他选择：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan --all-games
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan --appids-file database/data/top1000_appids.json
uv run --frozen --no-sync python -X utf8 -B process/DataAgent.py plan --appids 1462040 2909400 --reclassify
~~~

--reclassify重新判断已有机器结果，仍保护人工成果。默认uncertain也算已有模型结果，不无限重试。--sample-size按身份哈希固定取前N项用于试跑；--batch-size范围1～40默认20；--min-confidence默认0.8只分流状态。

凭据环境变量优先、根.env回退：DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL。只接受官方HTTPS入口，TLS开启，不打印密钥。check-connection是独立小请求，可选，本轮没有运行。

## 写入与恢复

每轮classify在HTTP前备份到runtime/deepseek/runs/<UTC时间>/before_classify.sqlite。读取事务结束后关闭SQLite连接，再调用模型。合格响应先保存receipt及report，再核对当前游戏上下文/成就文本，以BEGIN IMMEDIATE原子替换自动标签并更新status。

已有approved、manual标签或mainline_index非空受到保护，读取和写入前均检查。suggested表示明确且各类confidence达阈值，uncertain表示unknown或低置信度；不生成approved或主线排序。置信度不等于准确率。

response已成功但写入前中断时，可在相同输入/参数下缓存恢复；改变提示词、模型、输入、选样或批大小可能改变指纹。输入调用期间改变则拒绝整批；失败不覆盖已有成果。

budget_reached表示还有工作但本轮请求预算耗尽；success只表示本轮选中项处理完。报告sqlite_counts给出written/unchanged/protected，每项sqlite_outcome说明写入结果。运行锁防止同runtime同时执行。

429、格式错误、截断和传输超时停止；连接错误/5xx有限退避。失败不会变成unknown。实际token来自响应，本轮复用缓存不重复统计历史用量。

## 当前验证

临时真实SQLite与模拟HTTP验证通过：多标签、unknown互斥、完整ID、数值/证据约束、幂等写入、输入变更回滚、人工保护、预算续跑和零请求缓存恢复。真实供应商请求0，实际工作库未写入模拟分类。

实际库仍有127条历史rule标签，deepseek=0；全量语义分类和质量核查待真实运行。验证记录：process/runtime/validation/verification.json。详细契约见[DEEPSEEK_PLAN.md](DEEPSEEK_PLAN.md)，数据准备见[IMPORT_SNAPSHOT.md](IMPORT_SNAPSHOT.md)。
