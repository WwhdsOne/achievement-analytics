# DeepSeek成就分类实现说明

更新：2026-10-14。按最新决定直接用DeepSeek做八类多标签分类并存储结果；规则比较、主线排序、参与深度和人工审核程序退出当前计划。本轮没有执行新一轮真实模型分类。

## 1. 调用链

DataAgent.main → selected_appids → load_games → classification_messages → DeepSeekClient.call → validate_classification → classification_rows → local_database.store_classifications。

默认前1000款冻结清单，可显式选AppID或全库。读取一个SQLite只读快照，HTTP期间已关闭数据库连接。运行锁保护同runtime，最终SQLite写入使用短事务。

## 2. 输入与判断

输入为游戏中英文名、Steam官方类型valve_genres、成就display_name/description。当前没有简介/细粒度标签字段，不额外访问网站。appid/api_name留本地，模型看稳定短引用id；完成率、源顺序、评价、时长与旧标签不进提示词。

八类为mainline/side/collection/challenge/multiplayer/dlc/other/unknown。明确类型可多标签，unknown必须独占。mainline只说明内容，不证明必经性或先后；DLC、多人和挑战可附加到内容类别。

描述缺失保持缺失，证据不足返回unknown。依赖模型知识必须声明knowledge_used及具体uncertainty，不能编造网站核验。

## 3. 响应契约

~~~json
{
  "achievements": [
    {
      "id": "a0001",
      "types": [{"type": "side", "confidence": 0.9}],
      "evidence": ["对应输入的逐字片段"],
      "reason": "中文分类依据",
      "uncertainty": "",
      "knowledge_used": false
    }
  ]
}
~~~

整批检查字段完全匹配、每个ID恰好一次、类型闭集/无重复、置信度有限0～1且不接受布尔值、unknown互斥、reason非空、证据逐字来自对应成就。JSON重复键、NaN、截断及错误信封拒绝整批。

不返回scope、ordinary_mainline、target_depth，不生成规则对照或人工修订空栏。提示词版本lyx-deepseek-multilabel-v3，旧v1/v2缓存保留但不自动套用。

## 4. SQLite契约

写入前核对当前游戏名称/valve_genres及成就展示名/描述，变化则回滚整批。以(appid,api_name)定位，整体替换自动标签；相同标签/置信度/状态重放不变更。

achievement_types每标签一行，method=deepseek。achievements只更新status：每类confidence≥阈值且明确时suggested，否则uncertain；unknown始终uncertain。默认0.8只是状态分流，不是准确率。

读取与写入都保护approved、manual标签或非空mainline_index，不自动批准或排序。本轮实际库18项既有排序号保留。游戏级表和原始成就字段不变。

method已为deepseek/jev/rule/manual，列布局和user_version=2不变，本轮没有再次迁移。理由、依据与指纹存外部report/CSV，不新增SQLite JSON列或版本表。

## 5. 缓存、预算、恢复

请求指纹包含接口、提示词版本、模型、输入与生成参数，不含密钥。receipt先持久化响应再校验；合格200缓存复用前重验，支持收到响应后写库前的中断恢复，不重复统计历史token为本轮用量。

默认最多2次实际请求，包含重试。耗尽时budget_reached，保留已写批次；重复运行默认跳过已完成DeepSeek项，包括uncertain。--reclassify才重做机器结果。输入、批大小或选样变化可能导致旧缓存不命中。

429停止；连接失败/5xx最多3次，2/4秒退避；传输超时可能服务端已处理，因此不自动重发；格式/身份契约错误停止。失败不写unknown。每轮classify在HTTP前完整备份，本地文件均在LYX，缓存/报告/备份Git忽略。

## 6. 当前状态与下一步

离线默认plan通过：1000款、71,447项待分类、18项保护、20项/批4023批，4款无成就，v3缓存0。实际库127条类型仍全为rule，DeepSeek标签0。

临时SQLite与模拟HTTP验证多标签、原子写入、幂等、保护、输入变更回滚、缓存恢复、预算续跑和完成项跳过；真实模型请求0。没有新增pytest用例。

下一步先运行少量真实classify，观察语义及用量，再按预算扩展冻结清单。质量抽查可以实施，但不作为强制人工审核流水线。命令见[PROCESS.md](PROCESS.md)，阶段见[plan.md](plan.md)。
