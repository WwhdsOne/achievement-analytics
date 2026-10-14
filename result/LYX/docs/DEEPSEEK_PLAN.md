# DeepSeek背景摘要与整款分类契约

更新：2026-10-14。按游戏名定位本地数据，背景摘要缓存后复用，每款默认一次完整分类。所有写入限LYX，远端永远只读。

## 1. 提示词与调用链

分类常量[CLASSIFICATION_PROMPT](../process/DataAgent.py)位于DataAgent.py导入区之后，版本lyx-deepseek-whole-game-v5；简介常量[GAME_INTRO_PROMPT](../process/game_intro.py)位于game_intro.py导入区之后，版本lyx-game-intro-v1。用户可直接读改常量，并同步升级版本。

调用链：selected_appids/resolve_game_name → load_games完整读取 → game_plan只读预检 → game_intro.get_intro → classification_messages → DeepSeekClient.call → validate_classification → classification_rows → store_classifications。

选择方式为--game-name、--appids、--appids-file、--all-games四选一；未指定时使用冻结前1000款。无子命令默认plan，不会自动调用API；classify默认预算2次，而非默认一次跑完全部。完整参数及终端例子统一见[PROCESS.md的游戏选择参数](PROCESS.md#游戏选择参数)。

摘要模块接收客户端，不反向导入DataAgent。凭据、HTTP、脱敏、缓存和请求预算仅由同一个客户端负责。请求指纹含任务、各自版本、接口、模型、消息与生成参数，不含密钥。

## 2. 背景摘要契约

输入只有title、localized_title、valve_genres，不发送成就或结果变量。摘要是模型知识的显式背景，不增加外部事实来源，不声称网页检索或官方核验。

~~~json
{"recognized":true,"summary":"40～80字符的中文游戏背景摘要","uncertainty":""}
~~~

严格校验3个字段、布尔值、文本及长度；summary在recognized=true时40～80字符，uncertainty最多80字符。不能识别时recognized=false、summary为空且说明原因，仍可继续基于原始成就分类。简介格式或网络失败则停止本轮，成功缓存保留供恢复。

简介响应存既有runtime/cache，分类报告增加source=model_generated和摘要内容。不给SQLite增加简介列、JSON列或版本表。分类规则升级不使简介缓存自动失效。

## 3. 分类输入与输出

固定system包含任务、八类定义、边界/对照、背景依据和输出契约。user先<game_context>，后<achievement_batch>；分段各自使用canonical，避免全对象排序把achievements放在固定背景之前。

game_context含名称、官方类型、model_intro、intro_recognized、intro_source、intro_uncertainty；成就只含短引用id、display_name、description（NULL转空文本）。appid/api_name在本地映射。原始成就条件优先，摘要不能证明成就具体条件；依赖摘要或模型知识时声明knowledge_used及疑点。

~~~json
{
  "achievements": [{
    "id": "a0001",
    "types": [{"type": "other", "confidence": 0.9}],
    "evidence": ["本项输入中的逐字片段"],
    "reason": "普通成长目标",
    "uncertainty": "",
    "knowledge_used": false
  }]
}
~~~

八类mainline/side/collection/challenge/multiplayer/dlc/other/unknown。允许多标签，unknown独占；普通等级目标不单凭数值归challenge，特殊难度/技巧/成绩/限制条件才适用。mainline不意味着顺序或必经性。

evidence是从本项display_name/description逐字抽取的原文，reason是模型解释为何选择类型；两者均由DeepSeek返回，职责不同。完整ID不增不漏不重复；字段严格匹配；置信度有限0～1；reason非空且≤40字符，uncertainty≤40字符；knowledge_used=true时疑点非空；evidence为1～2段对应成就原文、每段≤150字符（Python len计数，含空格标点）。原文匹配检查保留，长度/空引用/非原文分别报错并指出成就ID和名称。重复JSON键、NaN、截断或契约错误拒绝整款。格式校验不证明语义正确。

## 4. 整款与已有结果保护

一款有待处理项时，模型收到全部原始成就，包括已有机器或人工结果对应的原文，但不接收旧标签。完整响应先校验，默认只写待处理项。已有DeepSeek且状态suggested/uncertain记already_classified；--reclassify可更新机器标签，人工approved/manual和非空排序号始终保护。

整款已无待处理项则整个跳过，简介也不请求。写入前检查完整原始集合/文本和游戏背景；调用期间新增/删除成就也会拒绝。整个游戏用一个短事务更新标签和状态，HTTP在事务外。

已完成判据是非保护项status为suggested/uncertain且全部已有标签method=deepseek；rule/jev旧结果不能据此跳过。更改门槛或提示词不会自动重判既有DeepSeek项，显式--reclassify才允许替换；该开关仍优先复用缓存，不强制新请求。

method=deepseek；标签每类一行。默认门槛0.6，先逐类筛选confidence > 0.6，等于或低于门槛仅保存在runtime JSON，不写achievement_types。classification_rows保留完整types及accepted_types/rejected_types；store_classifications使用相同门槛再次筛选，防止绕过入口写入低分标签。全部未通过时保留旧标签和状态，记below_threshold；部分通过时只用通过的标签替换可更新的自动结果。明确类别为suggested；unknown也按相同门槛筛选，通过后仍为uncertain，不自动approved或填写mainline_index。标签表增加display_name，入库从原始成就填写，来源改名时触发器同步；当前六表、user_version=3，原始成就不改。

门槛仅为本地处理参数，不改提示词版本或API请求指纹。更改门槛可复用同一完整响应缓存；已完成机器结果默认保留，需要重筛时显式--reclassify。原始响应和未通过标签均留在JSON，CSV同时标记confidence_passed/label_sqlite_outcome。筛选后的accepted_label_count不等于入库数（包含保护项），written_label_count统计实际写入标签；全部未通过的待处理项纳入remaining_pending_count及unprocessed_achievement_count。

## 5. 输出预检、恢复与统计

game_plan显示完整成就数、输入字符/字节、1024+160*N输出估计、待处理/保护数及缓存。简介缺失时仅在本地测量中使用长度预留，不向API发送占位摘要。默认max-output-tokens=65536、max-input-chars=300000；超限为oversized_game，无模型请求，不自动拆分。字符不是token，估计不是保证。

首次普通游戏通常简介1次+分类1次，不含重试；max-requests限制本轮新HTTP尝试数，包括两阶段及重试，缓存/SQLite查询不计，每次启动重新计数，0禁止新请求。简介成功而预算耗尽后可续跑；响应先落盘，写库前中断可复用完整缓存。每轮备份before_classify.sqlite。HTTP读超时默认300秒；保持429/契约错误/超时停止、连接错误/5xx有限退避。失败不生成unknown，也不默认跳过失败游戏继续本轮。

local_response_cache_hits区别于API输入前缀缓存；api_cache_hit_tokens、api_cache_miss_tokens和ratio只汇总本轮真实响应。usage_by_task分开简介与分类，缺失字段为null，本地复用不重复记历史用量。旧v1/v2/v3文件保留但不套用新契约。

v5只放宽引用长度，允许从严格一致的v4完整请求中读取已有响应并按当前150字符规则重新校验。兼容请求除system中60→150及版本号外，其余游戏上下文、原始成就、模型、接口与生成参数必须相同；变化的输入或其他版本不回退。新缓存优先，旧receipt不改写；调用元数据保留源prompt_version及requested_prompt_version/compatible_cache。原先因超长引用记error的HTTP200响应，只要现在完整校验通过，也可零请求恢复。

## 6. 当前验收状态

2026-10-14 13:58 UTC核查快照：重生61项已完成，普通重跑为already_classified_or_protected、新请求0；重制版63项仍有45项待处理、18项保护，输出估计11104。全1000款预检978款ready、16款oversized、4款无成就、2款已完成；总待处理71,348（包括超规模项），正常路径预计新请求1956、重试另计。进度随运行变化，以最新plan为准。

此前用户真实试跑重生共2次请求、7511 tokens，因9段原文引用长度62～84超过旧60上限而未写库。150字符修复后，用户通过--max-requests 0成功恢复：完整候选61项、更新60、保留1、缓存命中2、未处理0。后续默认清单运行又成功分类HELLDIVERS™ 2的38项成就，生成41条关系，2次请求后budget_reached、无错误。跨游戏流程及多标签写入已实际执行，语义准确率与API前缀缓存收益仍未形成结论。命令见[PROCESS.md](PROCESS.md)，记录见[experiments.md](experiments.md)。
