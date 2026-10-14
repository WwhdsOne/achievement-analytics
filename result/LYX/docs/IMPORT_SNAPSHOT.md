# 评价数前1000款：远端只读迁移说明

2026-10-14链路调整：本文件仅描述独立的数据准备，日常DeepSeek分类不连接远端。import_snapshot.py的完成率转换已改从local_database.py读取，旧probe依赖已解除；既有冻结清单、批次与checkpoint保持不变。当前分类执行见[PROCESS.md](PROCESS.md)，历史主线审核/分析表述不属于最新任务。

下文“本轮迁移”指2026-10-14已完成的前1000款导入；其中124项FF7成就/127条旧类型及旧运行目录是当时记录，不是当前DeepSeek进度。最新表结构、类型数量和分类完成状态见[DATABASE.md](DATABASE.md)。该历史任务的schema版本2 checkpoint不改写为当前版本3。

实现日期：2026-10-14。程序为[import_snapshot.py](../process/import_snapshot.py)。所有文件和SQLite写入仅限result/LYX；共享PostgreSQL只读，不调用worker、源API、配额登记、云端建表或修复程序。

## 固定人群与数据链路

先在store_search_games按review_count降序排序，同分按appid升序，排除NULL，取1000行。没有额外按发售年份、类型、成就数、主线是否明确或RAWG覆盖筛选。固定AppID数组保存为database/data/top1000_appids.json；排名明细、SQL、读取时间、连接方式和实际文件SHA256另存top1000_selection.json。

已保存清单包含1000个唯一AppID，评价数范围7326～634194。续跑沿用这份清单，不重新排名，也不覆盖旧清单。

按每批50款，共20批提取。每批单独使用REPEATABLE READ READ ONLY事务，查询games、steam_appdetails、store_search_games、rawg_games、achievements及mapping_issues。创建连接时default_transaction_read_only=on，服务端确认transaction_read_only=on；查询参数使用AppID数组，不拼接身份值。IDE配置优先，缺完整凭据时回退根目录.env；本次最终为.env。

不同批次不是一个跨全程数据库事务；各源fetched_at也不一定相同。批次JSON保留读入时刻、来源抓取时间和原始属性；achievements没有逐行fetched_at，不把批次读取时间伪装成来源抓取时间。

## 字段映射与已有成果保护

| 本地表 | 远端来源 | 写入内容 |
|---|---|---|
| games | games | appid、name_en、name_zh |
| games_details | steam_appdetails | is_free、price_cents、release_date、valve_genres |
| games_rate | store_search_games + rawg_games | review_label、review_percent、review_count、metacritic、rating |
| games_time | rawg_games | playtime；不调用攻略网站、不填guide字段 |
| achievements | achievements | appid、position、api_name、display_name、description、percent |
| achievement_types | 本地已有结果 | 不生成新分类，保护已有type/method/confidence；当前版本3重写标签时同步原始成就display_name |

当前本地schema版本3；旧版2的已完成checkpoint/备份属于历史产物，不改写其版本。程序继续拒绝跨schema版本续跑；需要再次导入时使用新的运行目录。日常成就分类不需要重新导入或连接远端。

valve_genres使用local_database.py的CSV转义竖线分隔文本转换。BOOLEAN转0/1，DATE转YYYY-MM-DD，完成率保持两位小数；不把NULL补成0。SQLite字段结构不变，不新增game_tags、不存JSON列。

新成就status=pending、mainline_index=NULL，不自动推断类别或剧情顺序。已有分类、审核状态与主线顺序按appid/api_name保留；字段一致时可重放。已有分类输入的展示名/描述改变或身份缺失时，保留该游戏全部原成就并记录冲突，避免跨来源错配破坏已有判断。背景信息仍正常迁移。

两款FF7的云库存在描述缺失，部分内部名与展示名对应关系和原API试跑不同，因此本轮保留本地124项成就及127条类型作为例外；详细冲突在运行报告与原始批次中可核对。不得将这些例外称为与云库逐字段完全一致。

重制版RAWG仍匹配为Final Fantasy VII，未纳入该条playtime/metacritic/rating；源值保留批次文件供核验。其他RAWG属性按AppID复制，但“有正值”不代表版本已经人工核验。0时长仅保留源值，分析时另行处理。

存在映射问题的游戏不从排名清单静默删除，问题单独记录，正式分析应排除未解决项。没有成就记录、没有RAWG、缺发售日与网络请求失败分别处理；失败不会被记成空数据。

## 事务、备份与中断续跑

首次迁移前完整备份当前SQLite到运行目录before_import.sqlite。每款游戏在本地BEGIN IMMEDIATE事务内写入，失败回滚该游戏；已有其它游戏不会受影响。原始成就需更新时，在同游戏事务内重建并恢复已有类型/状态/排序，以处理position重排产生的唯一键冲突。

运行目录包含：

- before_import.sqlite：迁移前完整备份。
- batch_0001.json等：成功提取的固定批次输入，SHA256登记于checkpoint。
- checkpoint.json：固定AppID、分批参数、完成身份、失败与冲突，可续跑。
- report.json：全部批次完成后的逐字段核验、行数、空值覆盖和质量问题。
- .run.lock：系统文件锁，保护同一运行目录；进程退出自动释放。

JSON是用户要求的本地输入/运行文件格式，不是SQLite内的字段存储格式。所有数据与运行文件均受本模块Git忽略规则保护，不提交原始数据。

若SQLite已经提交而checkpoint尚未保存，续跑可从固定批次重放，不重复添加类型或覆盖人工结果。已登记快照指纹不符时停止，不静默复用被改动的输入。临时远端失败退避2秒/4秒重试；失败进度保留，不重新排名。执行期间只保持一个迁移进程。

## 命令

在LYX目录使用已有uv环境，避免修改根目录依赖：

~~~powershell
Set-Location D:\PycharmProjects\achievement-analytics\result\LYX
$env:UV_CACHE_DIR = "$PWD\process\runtime\uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run --frozen --no-sync python -X utf8 -B process/import_snapshot.py --select-only
~~~

新迁移会新建运行目录和完整备份：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/import_snapshot.py --batch-size 50
~~~

若新版本3导入中途暂停，可用该次输出的run_dir续跑。下列目录名须替换为你这次新导入的实际目录，不能使用历史版本2目录：

~~~powershell
uv run --frozen --no-sync python -X utf8 -B process/import_snapshot.py --resume --run-dir "process/runtime/remote_import/你的本轮目录名"
~~~

续跑使用checkpoint中的分批参数和固定快照，不重新获取已经完成的批次。全部完成后再次续跑只执行本地最终核验，不发远端请求、不重复写库。complete_with_conflicts表示已有输入被保护，需要单独核验冲突，不能当作所有成就与云库完全一致。

这些续跑行为要求checkpoint、数据库、清单及schema版本与该次运行一致，且保留输入和分类符合导入时的核验口径。历史任务后已进行结构升级和新分类，不应把旧目录用于复核当前状态；当前流程不需要重新导入。

## 最终验收

检查1000个AppID、四张游戏级表、每款原始成就与固定批次的字段、SQLite完整性/外键、已有类型和审核状态保留；质量报告另外列无成就、缺RAWG、版本疑点、缺发售日、未解决映射以及既有分类输入冲突。全过程不执行成就分类、人工批准、剧情排序、分析指标或外部采集。

当前核验边界：verify_run对标签保留仍比较原五字段appid/api_name/type/method/confidence，没有单独比较新增display_name与来源成就；实际INSERT已写六列，名称同步触发器已生效。后续代码可补充这一独立一致性检查，本次只更新说明、不修改程序。当前名称核查可用[DATABASE.md中的只读SQL](DATABASE.md#pycharm连接与核查)。

这1000款是评价数偏高的初步获取样本，尚未完成主线/类型人工审核，不代表1000款正式分析样本已经准备完成。
