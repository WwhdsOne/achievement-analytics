# Codex 浏览器批量补全攻略难度

更新：2026-10-15。入口为 [`process/guide_agent.py`](../process/guide_agent.py)，由 Codex 搜索、读取浏览器真实 DOM，本地程序校验身份、保存证据、分批写入现有 SQLite。用户已确认取得覆盖本项目的 Gamer Guides 批量采集许可；执行仍遵守许可范围。

清单为 [`database/data/top1000_appids.json`](../database/data/top1000_appids.json)：已核对为1000个唯一正整数，全部存在于本地 `games` 与 `games_time`。清单 SHA256 为 `4e8fafab192456653c81dbc698d249b01f3602f5a9a6d439610c528cc89ddfde`。初始化冻结其顺序、指纹及数据库绝对路径，后续不会依赖聊天记忆寻找进度。

这条入口补的是网页来源发现和浏览器交接；普通 HTTP 曾返回403，HTTP批量访问仍未打通。浏览器读取成功不表示 `guide_time.py fetch` 已可批量运行。当前两个攻略入口共享难度固定标签解析、来源凭据、在线备份和仅更新guide_difficulty的短事务写入，不修改 schema，不连接共享云库，也不调用分类模型。schema4的三类时长由独立[HLTB同步入口](HLTB_TIME.md)维护，旧guide_time_hours_min/max已物理删列；历史Time来源仍保留供审计。

## 当前已核实的发现结果

已通过浏览器实际枚举站内 Steam 成就目录的6页、134张卡片，与清单完整名称匹配出55款候选。原始目录交接保存在 `process/runtime/gamerguides/agent/catalogues/`。

目录卡片只证明发现了一个实际网址，不能证明页面身份、Steam平台或难度值已确认。其余游戏继续站内或外部搜索；目录没有收录也不能记成该网站确定性无数据。当前成功写入数、难度覆盖数和未解决状态均以 `summary` 的实际输出为准，本文不维护会随采集变化的计数。

## 执行顺序与命令

按项目规则先在仓库根同步 main，然后进入 LYX。当前 Windows 使用 `--no-cache` 避免 uv 默认缓存权限问题，`--frozen --no-sync` 复用已经安装的项目环境；未安装时先按项目规范执行 `uv sync`。

```powershell
Set-Location D:\PycharmProjects\achievement-analytics
git pull origin main
Set-Location result\LYX
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py init
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py summary
```

默认数据库为 `database/achievements.sqlite`，默认清单为上述1000款文件，默认运行目录为 `process/runtime/gamerguides/agent/`。指定独立运行目录时，`--runtime` 放在子命令前，后续每条命令使用同一目录：

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py --runtime process/runtime/gamerguides/another-batch init --database database/achievements.sqlite --appids-file database/data/top1000_appids.json
```

已有相同清单和数据库的 `init` 会保留进度并对账；清单内容、顺序或数据库路径改变则拒绝覆盖，应保留旧目录并使用新 runtime。若本地名称变化，任务标为 `input_changed`，保留旧输入快照并废弃旧映射，核对新输入后另建 runtime。

1. **读取下一批任务。** 每轮最多10款，先处理已有候选，也可读取需要发现页面的游戏：

   ```powershell
   uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py next --phase capture --limit 10
   uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py next --phase discovery --limit 10
   ```

   输出包含 AppID、本地中英文名称、原有候选、检索记录和建议搜索词。`--phase apply` 读取已导入等待写库的任务；`--phase all` 按队列默认可续跑状态取任务。`--appids` 可明确选择本轮 AppID。

2. **从实际搜索或目录取得链接。** 优先复用已记录候选；没有候选时，使用站内目录、站内搜索或 `site:gamerguides.com "完整游戏名" "Steam Achievements"`，必要时再用同一完整名称做一次补充搜索。每款每轮最多两轮搜索、三个候选，不能直接拼 slug 当作已发现网址。

   将真实检索结果写为 JSON 数组，再导入：

   ```powershell
   uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py discovery --input process/runtime/gamerguides/agent/handoffs/discovery-batch.json
   ```

   数组每项含 `appid`、实际搜索词或目录来源 `query`、可选 `followup_query`、实际读取时间 `observed_at`、说明 `evidence`、候选数组 `candidates`。候选各含实际 `title`、`url`，可附平台或发现依据。没有可确认候选时也保存该款的搜索记录，`candidates: []` 会记为 `no_verified_page`，不能假装已完成或填数值。

   目录卡片也可按 `source_url`、`captured_at`、`items: [{name,url,platform_text}]` 保存，使用 `catalogue --input <文件>` 批量匹配。该入口只产生完整名称候选，不自动完成身份确认。

3. **打开实际候选，采集 DOM。** 候选如果是游戏攻略首页，沿真实可见链接进入 Steam 成就总览，记录连续导航链；不凭模式猜出总览 URL。页面必须是 `/{slug}/steam-achievements/overview`，标题包含 Steam Achievements，当前唯一激活平台为 Steam。

   每批保存1至10款真实捕获，推荐以 `capture-batch` 一次交接。每款普通身份或解析错误会留在队列并继续下一款；遇挑战即暂停该来源，本批后面的任务保持原状态。本命令保存证据、解析和核验，尚不写 SQLite：

   ```powershell
   uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py capture-batch --input process/runtime/gamerguides/agent/handoffs/capture-batch.json
   ```

   单款也可导入同一次浏览器读取的捕获对象：

   ```powershell
   uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py capture --appid 1245620 --input process/runtime/gamerguides/agent/handoffs/capture-1245620.json
   ```

   上例 AppID 仅展示参数结构；已完成任务默认拒绝再次采集。实际执行替换为 `next` 返回的当前 AppID 和该款真实捕获文件，不重用别款样本或手工编写 DOM。

   没有可核验捕获时，使用 `mark --appid <实际AppID> --status ambiguous --reason "实际观察到的身份歧义依据"` 记录原因。状态可选 `blocked`、`ambiguous`、`no_verified_page`、`error`、`metadata_missing`；验证码或访问挑战记 blocked，并停止来源，不继续消耗整批任务。mark 保留已有 imported、partial、applied、already_complete 和 input_changed 状态，只追加原因，不能破坏已确认来源。

4. **分批写入并查看覆盖。** 写入前程序重读证据、核验 SHA256 和身份，完整在线备份，再单进程逐款只更新guide_difficulty。默认只补 NULL，已有冲突整款不写；不加 `--overwrite`。本轮用 `--appids` 指定实际已导入的最多10款：

   ```powershell
   uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py apply --appids 1245620
   uv run --no-cache --frozen --no-sync python -X utf8 -B process/guide_agent.py summary
   ```

   同样替换为本批实际 AppID。省略 `--appids` 会处理全部已导入或部分写入的来源，适用于恢复上轮中断后的待写批次。原 `playtime`、HLTB三类时长、成就文本、分类标签和主线顺序不受该入口更新。

## Discovery 与 DOM 交接格式

以下仅为字段结构说明。占位文本须替换成浏览器或搜索真实读取内容，不能直接作为采集证据导入。

```json
[
  {
    "appid": 1245620,
    "query": "实际使用的完整搜索词或 browser_catalogue:实际目录URL",
    "observed_at": "实际读取时间，ISO8601且有时区",
    "evidence": "搜索结果标题、来源页面和必要的版本说明",
    "candidates": [
      {
        "title": "实际搜索结果或目录卡片名称",
        "url": "实际观察到的Gamer Guides HTTPS链接"
      }
    ]
  }
]
```

捕获 JSON 的必填字符串为 `url`、`captured_at`、`page_title`、`h1_html`、`platform_html`。`difficulty_html` 为难度完整 chip 的 `outerHTML`，页面确实没有节点时使用 JSON `null`。`time_html` 可省略或为null；若保留真实Time片段，仅用于历史证据，不参与当前难度解析或写库。必须保留难度chip的class、title和内部value，不能只交接显示的数字：

```json
{
  "url": "实际浏览器当前Steam成就总览URL",
  "captured_at": "实际读取时间，ISO8601且有时区",
  "page_title": "实际 document.title",
  "h1_html": "实际游戏标题 h1.outerHTML",
  "platform_html": "实际当前平台 .achv-service.is-active 的outerHTML",
  "time_html": null,
  "difficulty_html": "实际完整 .achv-roadmap-chip[title=Difficulty] 的outerHTML，缺节点为null",
  "steam_links": [],
  "navigation": []
}
```

`steam_links` 保存实际观察到的当前游戏 Steam 商店或社区链接，可用 URL 字符串，也可用 `{url,text}`。当网页名称与本地名称不同，必须有唯一对应本地 AppID 的 Steam 链接才能自动接受；仅近似名称、相同成就数量或 agent 的直觉不能作为异名依据。页面出现多个或不符的 AppID 时拒绝映射，不能删掉冲突证据以通过校验。

名称相同时，只折叠字体、大小写及标点，保留续作数字、重制版、DLC 和版本词。既没有对应 AppID 链接、名称也不匹配时记为 `ambiguous`，其余游戏继续推进。

若当前 URL 不是已经导入的候选，`navigation` 必须记录实际链接链，每步形如 `{from_url,to_url,link_text}`：第一步起点属于候选，前后链接连续，最后一步到达当前总览页。无需导航的直接候选保留空数组。不能用脚本猜路径后伪造导航链。

批次文件为 `{captures: [{appid,capture}], captures_checksum: "八位小写十六进制"}`，captures 长度1～10且 AppID 不重复。`capture` 为上述原始捕获对象；checksum 是浏览器导出时，对 `JSON.stringify(captures)` 的 UTF8 字节做 FNV1a32。应在同一次导出中计算，保留对象键顺序和字符串原文；文件可以缩进，但不能排序键、重写 DOM 或读到校验不符后在本地重新算校验以掩盖改变。

浏览器中已经得到真实 `captures` 数组后，可按下列纯计算步骤生成交接对象：

```javascript
const bytes = new TextEncoder().encode(JSON.stringify(captures));
let checksum = 2166136261;
for (const byte of bytes) checksum = Math.imul(checksum ^ byte, 16777619) >>> 0;
const handoff = {
  captures,
  captures_checksum: checksum.toString(16).padStart(8, "0")
};
```

这项校验用于检查交接内容是否被改写；持久来源和写库前的核验仍使用 SHA256、原始DOM重新解析及游戏身份校验。批次命令出现逐款错误时退出1，先检查 outcomes，成功项已经保存且可 apply，不必重复浏览整批。

## 字段口径与恢复

| 本地字段 | 解析口径 |
|---|---|
| `guide_difficulty` | 明确 `/10` 尺度中的数值，范围0～10 |

当前解析器为 `fixed-chips-v4-difficulty-only`，scope为 `achievement_difficulty_reference`。新捕获只解析固定Difficulty节点；Time值是否为空、缺单位或格式异常均不影响当前难度提取，也不更新任何时长字段。难度为空或缺节点时保留NULL，无法解析或超过0～10范围时报错。

历史时间策略仍可追溯：v1/v2曾要求明确单位，v3按用户当时指定的无单位数字规则把单数填两端、双数分开填。旧 `fixed-chips-v1` / `fixed-chips-v2-unitless-partial` / `fixed-chips-v3-unitless-hours` receipt仍按保存版本完整复核；重放仅选择其中难度写入，旧时间值不写已删除列，也不写HLTB三列。此前三款缺单位时间任务属于旧策略，不再要求补旧时间属性。

| 状态 | 含义与下一步 |
|---|---|
| `discovery_pending` / `error` | 等待检索或在后续轮次重试；先查看既有原因 |
| `candidates_found` | 有实际链接，尚待浏览器身份和内容核验 |
| `mapping_verified` / `dom_saved` | 可恢复捕获阶段；已保存的证据不得伪造或覆盖 |
| `imported` | 已持久化核验过的 DOM 来源，等待 apply |
| `applied` / `already_complete` | 攻略难度已有值；覆盖仍以当前数据库为准 |
| `partial` / `metadata_missing` | 兼容旧部分状态，或网页已核验但难度缺失；保留明确缺口，不自动反复浏览 |
| `ambiguous` / `no_verified_page` | 本轮未确认身份或页面，保存搜索和拒绝依据；不等于网站确定性无数据 |
| `blocked` | 来源访问受阻，暂停该来源，不能绕过验证码或把受阻记成没有数据 |
| `input_changed` | 本地名称与冻结输入不同，旧映射失效，需核对后另建 runtime |

明确重新检索某款时使用 `retry --appids <AppID...>`，旧证据保留；`input_changed` 不允许用 retry 恢复旧身份。`summary` 直接只读查询 SQLite，包含 `status_counts`、各列 `coverage` / `missing_fields`、`complete_count` 和 `pending_count`，不能用候选数量冒充写入成功数。

当前状态真源为 `queue.json`，审计为追加写入的 `events.jsonl`。状态采用原子替换，审计失败保留 `pending_event` 供续跑补齐；崩溃造成的未完成尾行会安全截断后重放，同一 `event_id` 可能重复出现，不能拿审计行数当唯一任务数。相同 runtime 有操作系统锁，进程退出后锁释放。`init` 按当前唯一目标guide_difficulty对账，不把HLTB缺失计入攻略任务；已 applied 的难度再次缺失时，有receipt和verified_mapping则恢复imported，否则恢复discovery_pending。

| 产物目录 | 内容 |
|---|---|
| `agent/handoffs/` | agent 保存的真实发现与 DOM 交接 JSON |
| `agent/catalogues/` | 实际站内目录卡片快照 |
| `agent/captures/<appid>/` | 原始捕获、身份依据及指纹 |
| `agent/receipts/<appid>/` | 固定标签解析结果、HTML片段与指纹 |
| `agent/runs/<时间>/` | 写入报告及 `before_apply.sqlite` 备份 |

以上原始数据、来源、运行状态和备份均 Git 忽略；个人代码和说明留在 LYX，禁止提交原始数据或自行 commit/push。

## 下次 Codex 可直接使用的交接提示

```text
继续 result/LYX 的 Gamer Guides 批量难度补全。用户已确认取得覆盖本项目的许可。
先遵守 AGENTS.md 同步 main，读取 docs/GUIDE_AGENT.md 和 guide_agent.py，
使用默认清单 database/data/top1000_appids.json 和原 runtime/gamerguides/agent，
init 对账后 summary，有 imported 证据时先 apply，再 next 读取下一轮最多10款。
优先处理真实候选；没有候选时实际站内目录或 web 搜索，最多两轮搜索、三个候选。
禁止猜 URL，候选页须沿真实链接进入 Steam 总览，保存同一次真实 DOM 的交接 JSON。
异名只接受对应唯一 AppID 的 Steam 链接，版本歧义或缺证据记 ambiguous。
当前schema4，只补guide_difficulty；HLTB三类时长由import_hltb_times.py维护。
新捕获只从固定Difficulty标签提取难度，Time原文可保留但不解析或写库。
每款都有持久处理结果：未确认页面保存搜索并记 no_verified_page，受阻记 blocked 并暂停来源。
真实捕获1至10款为一批，从浏览器计算captures_checksum后按capture-batch导入，再分批apply。
未捕获任务可用mark显式保存blocked/ambiguous/no_verified_page/error及实际原因，已确认来源受保护。
默认不覆盖已有难度，不写任何时长字段，不改 schema，不启动 worker。
中断后复用 queue、capture、receipt，结束用 summary 报告真实覆盖及未解决原因。
不提交或推送，不把候选数、审计行数或离线验收误说成网站成功覆盖。
```
