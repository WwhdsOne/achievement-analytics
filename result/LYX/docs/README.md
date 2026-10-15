# LYX文档索引

说明和实验记录集中在本目录。DeepSeek成就分类工程链路已实现，当前仍按预算推进冻结1000款数据；完整覆盖和分类语义质量需分别核验。详细历史保存在实验记录和归档。返回[LYX工作空间](../README.md)。

| 文档 | 内容 |
|---|---|
| [plan.md](plan.md) | LLM as Judge目标、已实现阶段及后续验收 |
| [PROCESS.md](PROCESS.md) | 程序职责、命令和运行恢复 |
| [DEEPSEEK_PLAN.md](DEEPSEEK_PLAN.md) | 固定八类判别规则、模型上下文、证据校验与存储契约 |
| [DATABASE.md](DATABASE.md) | 六表、实际数据、状态和连接 |
| [IMPORT_SNAPSHOT.md](IMPORT_SNAPSHOT.md) | 独立的远端只读数据准备 |
| [experiments.md](experiments.md) | 历史及当前实现验证 |
| [API_PROBE.md](API_PROBE.md) | 历史API资料入口，旧命令不属于当前流程 |
| [HLTB_TIME.md](HLTB_TIME.md) | 远端hltb_games三类时长只读同步、本地schema4迁移与验收 |
| [GUIDE_TIME.md](GUIDE_TIME.md) | 当前仅补攻略难度、来源重放及历史时间试跑 |
| [GUIDE_AGENT.md](GUIDE_AGENT.md) | Codex浏览器1000款队列、页面检索、DOM交接和难度写入 |

日常程序入口：[DataAgent.py](../process/DataAgent.py)。SQL和数据库入口：[schema.sql](../database/schema.sql)。

本项目的 **LLM as Judge** 是DeepSeek按固定八类定义对原始成就作语义判断，可输出多标签；不包含第二个独立模型评审器。模型简介只提供背景，`evidence`必须逐字来自本成就的名称或描述，`reason`才是分类理由。模型自报信心通过门槛、响应通过结构校验和人工确认语义正确是三个不同层次；目前没有人工金标集及准确率结论。

游戏时长由[import_hltb_times.py](../process/import_hltb_times.py)按AppID同步远端hltb_games三列，见[HLTB_TIME.md](HLTB_TIME.md)。攻略入口仅补guide_difficulty：[guide_time.py](../process/guide_time.py)负责难度解析、HTTP和来源重放，[guide_agent.py](../process/guide_agent.py)接收Codex真实检索与浏览器DOM并维护持久队列。用户已确认站方许可，普通HTTP仍403挂起；已实际枚举Steam目录6页134张卡片，匹配55款精确名称候选，候选不等于核验或写入完成。当前难度覆盖执行 `guide_agent.py summary` 查看。浏览器操作见[GUIDE_AGENT.md](GUIDE_AGENT.md)，历史时间来源记录保留在[GUIDE_TIME.md](GUIDE_TIME.md)。

游戏选择及完整参数见[PROCESS.md](PROCESS.md#游戏选择参数)：--game-name、--appids、--appids-file、--all-games互斥；不写选择参数默认冻结1000款，不写子命令默认离线plan，classify默认新请求预算2。

当前契约：本地schema版本4（标签表含display_name，games_time使用HLTB三类时长），分类prompt v6、简介v1；evidence每项1～2段本成就非空逐字原文，每段严格小于500字符（最多499），逐标签confidence >= 0.6通过入库门槛。confidence是模型自报信心，不是准确概率。阈值属于本地后处理，不改变提示词或请求指纹。仅长度规则及版本不同、其余完整请求一致时，可重校验复用v5/v4缓存，旧响应不覆盖。

[process/datacache.csv](../process/datacache.csv)累计各轮有效分类全部标签，包括未过门槛、已有及已写结果；每标签一行，按(appid,api_name,type,request_hash)去重，保留来源CSV及首次/最近出现时间。每款先累计留档再写SQLite，提交后刷新写入结果，原runtime CSV/JSON保留。历史导入用[import_classification_cache.py](../process/import_classification_cache.py)，默认只预检，--apply才实际写入；核对原始上下文和证据后只补缺失标签，保留已有机器/人工结果和主线排序，不调用模型或远端。详情见[运行说明](PROCESS.md#累计分类csv与历史结果导入)。

HTTP读超时仍为--timeout-seconds=300，连接15秒；新增简介总时限--intro-total-timeout-seconds=90、分类总时限--classification-total-timeout-seconds=300，重试/退避共享总时限，保活空行不延长。每15秒终端心跳并更新本轮progress.json，业务仍逐款串行；详见[请求总时限与恢复](PROCESS.md#请求总时限等待进度与超时恢复)。

单款HTTP 200的JSON、截断或契约错误记response_error；总时限/读超时记request_timeout，均不写本款且继续后续游戏。简介、分类各自连续3次超时触发service_paused（退出码1）；同类完整HTTP 200响应清零，缓存不清零。其他网络、限流、TLS/认证/余额及数据库/文件错误仍停止。报告failed_game_count/failed_appids包含响应失败及超时，timeout_game_count/timeout_appids单列超时，consecutive_timeouts/paused_reason说明暂停；遍历结束有零星失败时completed_with_errors、退出码1，预算先耗尽仍budget_reached并保留失败。完整响应可缓存恢复，部分正文只留partial_response_text及response_complete=false，不复用、不入库；旧receipt保留兼容规则。没有新增停止命令，Ctrl+C仍正常中断收尾。

真实单款、有限预算批量、旧响应恢复及2026-10-15的`>=0.6`补录已有执行证据；请求超时、失败隔离、人工保护和重复导入另有离线验收。请求receipt、每轮report/CSV、跨轮datacache与SQLite分层保存，不能用CSV行数或`successful_game_count`代替全量完成率。具体数量均为[experiments.md](experiments.md)中的带时间快照，历史实验保留当时参数。后续主线节点人工核验、剧情排序及聚合分析尚未实施，不能直接用自动`mainline`标签得出通关或粘性结论。
