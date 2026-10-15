# Gamer Guides 难度补全与历史时间记录

更新：2026-10-15。当前 [guide_time.py](../process/guide_time.py) 和 [guide_agent.py](../process/guide_agent.py) 只更新本地 `games_time.guide_difficulty`，不连接云库、不调用模型、不改结构。schema4三类时长由 [HLTB同步入口](HLTB_TIME.md)维护；旧 `guide_time_hours_min` / `guide_time_hours_max` 已物理删列。原 `playtime`、HLTB三列、难度和其余五表由各入口按职责保护。

实际网址发现、浏览器DOM交接和1000款持久队列见 [GUIDE_AGENT.md](GUIDE_AGENT.md)。用户已确认站方许可；普通HTTP曾返回403并暂停，浏览器可读取不能替代HTTP可用性验证。当前难度覆盖使用 `guide_agent.py summary` 查询SQLite，HLTB覆盖按[HLTB_TIME.md](HLTB_TIME.md)查询。

## 当前解析与写库契约

新receipt的parser_version为 `fixed-chips-v4-difficulty-only`，scope为 `achievement_difficulty_reference`。只读取以下固定节点中的明确 `/10` 数值，范围0～10；难度缺节点或空值保留NULL，异常值、重复难度节点和访问挑战明确报错。

```css
.achv-roadmap-chip[title="Difficulty"] .achv-roadmap-chip-value
```

新捕获不解析Time，Time缺单位、缺失或非空异常不影响难度提取。旧v1/v2/v3来源仍按保存版本完整重新解析、校验SHA256和当前身份，时间字段仅供历史审计；重放只从结果选择guide_difficulty，不能把旧时间写入HLTB列或恢复已删除属性。

| 文件 | 当前职责 |
|---|---|
| `process/guide_time.py` | 离线预检、HTTP难度采集、receipt重放、备份与报告 |
| `process/guide_time_parser.py` | 难度固定节点解析；保留历史时间解析以复核旧receipt |
| `process/guide_time_storage.py` | 查询当前难度、在线备份和仅更新guide_difficulty的短事务 |
| `process/guide_agent.py` / `guide_agent_queue.py` | 真实搜索、浏览器证据、身份校验和仅按难度缺口推进的队列 |

## 当前命令

先按AGENTS.md同步main，再进入LYX。以下复用已安装的uv环境：

```powershell
Set-Location D:\PycharmProjects\achievement-analytics
git pull origin main
Set-Location result\LYX
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py plan
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py summary
```

plan完全离线，不写运行产物；缺口仅指guide_difficulty。推荐浏览器采集按GUIDE_AGENT执行capture-batch，再分批apply。合法保存的receipt也可离线重放：

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py apply --appids 1245620
```

`--receipts` 可选择本地来源根目录、AppID目录或单个记录；缺失或损坏来源报错。真实新HTML/DOM仍可通过import-html导入，必须指定对应AppID、实际Steam总览URL和来源类型，浏览器DOM不可冒充HTTP响应。普通HTTP确认可用后，fetch仍支持limit/max-requests预算、串行限速和来源暂停；不绕过挑战或恢复已弃用时间采集。

实际写入前完整在线备份，再在短事务内重新检查AppID/name_en和当前难度。默认只补NULL，冲突不写；显式 `--overwrite` 只允许非空新难度替换旧难度，NULL不清空已有值。原playtime、三类HLTB时长、成就文本、标签和mainline_index保留。运行产物继续在 `process/runtime/gamerguides/`，Git忽略，无新增依赖或pytest。

## 历史时间策略与验收（schema3）

以下完整保留此前三字段方案、参数和试跑记录，描述的是当时schema3。旧时间解析规则和旧覆盖数不代表当前结构或当前写入行为；其中命令如使用当前程序执行，只会补guide_difficulty。Time的无单位规则及此前三款缺时间的任务已由HLTB方案取代，不再需要填写旧时间属性。

历史实现记录（schema3，已由当前难度入口及HLTB时长同步取代）：独立入口为 `process/guide_time.py`，只更新本地 `games_time` 的三个攻略参考字段，不连接云库，不调用模型。六表结构与版本3保持不变，原始 `playtime` 保留。成就分类入口仍为 DataAgent，不读取这些值。

从1000款AppID实际发现网址、浏览器DOM采集与分批续跑，使用新增 [`guide_agent.py`](../process/guide_agent.py)，完整操作与交接提示见 [GUIDE_AGENT.md](GUIDE_AGENT.md)。用户已确认取得覆盖本项目的站方许可。Steam目录已真实枚举6页134张卡片，得到55款精确名称候选；候选不是完成数，当前字段覆盖请执行 `guide_agent.py summary` 查看。

### 实际验证与口径

2026-10-15用户调整了Time规则：新采集遇无单位单数字时同时填上下限（80→80/80），双数字分别填上下限（40-50→40/50），作为项目小时字段保存；空值或缺节点保留NULL，非空异常值报错。明确小时/分钟单位仍按原规则解析。当前解析器为`fixed-chips-v3-unitless-hours`；旧v1/v2来源按原版本复核，本次不自动重写此前三款旧记录，用户将人工补充。批量操作见[GUIDE_AGENT.md](GUIDE_AGENT.md)。

主库清单1000款游戏。2026-10-15首次单款试跑读取 Elden Ring 的真实浏览器DOM片段，按下列固定节点解析，并在完整备份后写入 AppID 1245620：时间下限21、上限32小时，难度6/10；原RAWG playtime=62小时保留。首次试跑结束时三列各覆盖1款，其余999款仍NULL；这是历史验收快照，当前覆盖以新增agent入口的summary为准。重复重放返回unchanged。

```css
.achv-roadmap-chip[title="Time"] .achv-roadmap-chip-value
.achv-roadmap-chip[title="Difficulty"] .achv-roadmap-chip-value
```

这只是成就总览页提供的参考值，来源标记 `achievement_overview_reference`，不解释为主线通关均值或已确认的全成就耗时。示例Roadmap页面当时显示“No roadmap yet”，时间的进一步依据未确认。来源URL为 https://www.gamerguides.com/elden-ring/steam-achievements/overview 。

单次普通HTTP试跑返回403，程序只请求一次即source_paused。浏览器读取成功不等于独立HTTP批量链路已打通；没有绕过挑战、导入浏览器Cookie或关闭TLS验证。站方[当前条款第3/5节](https://www.gamerguides.com/terms)要求系统抓取、构建数据集取得事先书面许可；用户已确认取得本项目许可。当前使用agent浏览器流程，本文HTTP批量命令仍需确认HTTP访问可用后才能运行。

### 文件与运行产物

| 文件 | 职责 |
|---|---|
| `process/guide_time.py` | CLI、候选URL、身份匹配、HTTP限速/预算、来源记录、续跑和报告 |
| `process/guide_time_parser.py` | 标准库HTMLParser固定标签解析与数字校验 |
| `process/guide_time_storage.py` | 本地只读查询、在线备份、三字段短事务写入 |
| `process/guide_agent.py` / `process/guide_agent_queue.py` | Codex实际检索和DOM交接、持久AppID队列、身份核验与批次写入，详见GUIDE_AGENT.md |
| `process/runtime/gamerguides/receipts/<appid>/` | 不覆盖的HTML/DOM片段、SHA256及JSON来源记录 |
| `process/runtime/gamerguides/progress.json` | 各游戏候选的跨轮采集状态；身份、URL、别名、解析器版本共同决定任务键 |
| `process/runtime/gamerguides/runs/<时间>/` | report.json，发生写入时有before_apply.sqlite |

仅使用现有httpx和Python标准库，没有修改根pyproject.toml/uv.lock，没有新增pytest。原始片段、来源记录、运行报告和备份均Git忽略。所有路径必须在LYX内。相同runtime使用操作系统文件锁；另一进程会明确失败，退出或崩溃后锁自动释放。

### 命令

在项目根按AGENTS.md先同步main，再进入LYX。这里用 `--no-cache` 避免当前Windows环境的uv缓存权限问题：

```powershell
Set-Location D:\PycharmProjects\achievement-analytics\result\LYX
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py plan
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py plan --appids 1245620 2622380
```

plan完全离线，不写运行产物；显示真实缺失数及候选URL。没有映射文件时，每款按英文名只生成一个slug候选；候选不等于匹配成功，网页h1必须与本地中英文完整名称规范化后相同。保留版本词、冒号和连字符，不自动合并本体/重制版/DLC。站方URL与名称不一致时可提供明确核对的映射文件，JSON数组例如：

```json
[{"appid":1245620,"url":"https://www.gamerguides.com/elden-ring/steam-achievements/overview"}]
```

文件可放 `process/runtime/gamerguides/mapping.json`。可选 `page_game_name` 指定人工核对过的网页名称别名；误填可能造成身份误配，不能把模糊候选直接当成确认别名。URL只接受Gamer Guides的HTTPS Steam成就总览，不接受PS/Xbox页、其他域、账号、端口和query/fragment。

获站方许可并且HTTP访问可用后，小批次采集、自动写库：

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py fetch --limit 20 --max-requests 20 --apply
```

默认同域请求间隔3秒，串行；这是项目自设值，仍需遵循站方授权要求。--max-requests计入实际重试和跳转，不计本地来源复用。--limit限制本轮新处理的游戏数量；重跑跳过已尝试的404、无映射、部分缺失和缺字段页面，继续后面的游戏，不会被前20款堵住。单款网络/格式错误跨轮最多尝试3轮，之后exhausted，--retry-errors可显式恢复。挑战/401/403/429立即暂停整个来源，其他游戏不被标成无数据。5xx/连接错误最多3次，2/4秒退避。

全库分请求预算续跑，可重复相同命令；有映射文件时再加--mapping：

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py fetch --limit 1000 --max-requests 20 --apply
```

不加--apply只采集、保存来源记录；后续可离线批量重放：

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py apply
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py apply --appids 1245620
```

--receipts可指定来源根目录、单个AppID目录或单个记录JSON。目录不存在、没有来源或明确选择的AppID缺少来源时退出1，不报告成功。只重放相应AppID的来源，其他游戏损坏记录不会影响定向运行。重放重新解析HTML、校验SHA256和当前游戏名称；损坏/丢失来源明确报错，--refresh可以重新采集。

已经合法取得的本地HTML或浏览器DOM片段也可导入；必须明确URL和AppID，浏览器DOM要标记来源类型，不冒充原始HTTP响应。以下是本轮已成功执行的真实样本命令：

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_time.py import-html --appid 1245620 --url https://www.gamerguides.com/elden-ring/steam-achievements/overview --html-file process/runtime/gamerguides/validation/elden-ring-browser-dom.html --source-kind browser_dom --fetched-at 2026-10-15T00:59:30.433Z --apply
```

--fetched-at应填写实际读取时间，ISO8601且有时区；省略时记录导入时刻。默认source-kind=http_html。--refresh重新读取选定游戏，包括三列已有值的游戏；默认仍保护旧值，冲突整条不写。只有显式--overwrite才允许用非空新值替换旧值，NULL永不清空已有值。

### 校验、恢复与结果判读

- 时间支持21-32h、Unicode横线、30h、90min、30+ hours等；开放区间只填已确定下限。只有30-50、1-2等数字但无明确时间单位时，两个小时字段均保留NULL，原文与警告留在receipt。N/A、Unknown或缺节点保留NULL，有效0保留。
- 难度要求明确/10尺度；拒绝NaN/Infinity、负数、反向范围、难度超过10、重复目标节点和挑战页面。
- HTTP与SQLite事务分开；保存来源后完整在线备份，再单游戏BEGIN IMMEDIATE。事务内重新检查AppID/name_en及当前旧值，默认只补NULL。保留playtime、标签、原始成就与mainline_index。
- source_paused退出2；数据/文件/数据库错误或写入冲突退出1；预算耗尽可退出0但state=budget_reached；batch_completed表示本批结束，仍有未尝试游戏。
- completed_selection只表示选择范围的本次处理结束，不等于数据完整。报告的remaining_missing_fields、complete_game_count才说明字段覆盖，remaining_unattempted_count说明尚未尝试的候选数量。
- 部分缺失是明确的来源缺口，不自动反复抓取。要检查网站后续补齐或更改URL，使用--refresh或更新映射；不能用0或猜测值填满1000款。

本轮真实HTTP暂停报告：`process/runtime/gamerguides/runs/20261015T010442031830Z-e9767680/report.json`。真实DOM写入及备份：`process/runtime/gamerguides/runs/20261015T010545635436Z-7d2139a3/`。重放报告：`process/runtime/gamerguides/runs/20261015T010637744153Z-7a71c147/report.json`。

批次恢复验收使用独立SQLite备份与MockTransport，报告在 `process/runtime/gamerguides/validation/cli-20261015T010746864182Z/acceptance-report.json`：404→部分缺失→完整来源三轮顺序推进，共3次模拟请求；第四轮0请求。200挑战仅1次模拟请求即暂停；缺来源退出1；运行锁重入拒绝、释放后可恢复。模拟数据只在验收库，不写主库，不能作为站点覆盖率或HTTP成功证据。主库与写前备份比较：其他五表及games_time的appid/playtime完全一致，integrity_check=ok、外键问题0。
