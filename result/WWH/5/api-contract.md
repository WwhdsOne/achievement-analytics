# DeepSeek 标注接口文档

本文件说明**实际发给模型的请求长什么样、期望返回什么、拿到后怎么算指标**。
内容以代码为准（[wwh5/deepseek.py](./wwh5/deepseek.py)，提示词版本 `wwh5-ds-v2`）；
**发给模型的指令原文与字段含义见 [指令文档.md](./指令文档.md)**。
没有真实 key 时也可照本文件用 curl 手工验证协议。

## 1. 一次游戏要发几次请求

```
每款游戏
 ├─ 分类请求 × N 批（每批 ≤ 40 个成就，按 achievements 表顺序切）
 └─ 主线请求 × 1（只在分类全部成功后才发）
```

- **分类**：把该游戏的成就分批送模型，判断每个成就是主线/支线/收集/挑战等，并给出游戏维度标签。
- **主线**：分类完成后，把该游戏**所有被判为 `main` 的成就**作为候选，**一次性**送模型排剧情顺序。
  分出来单发是为了避免不同批次各自编顺序、互相矛盾。
- 分类若有一批失败，该游戏**不发**主线请求（下次重跑再补）。
- 被 `blocked_reason` 挡住的游戏（映射未解决 / 无成就 / 缺展示名）**完全不发请求**。

## 2. 传输层

| 项 | 值 |
|---|---|
| 方法 / 路径 | `POST {DEEPSEEK_BASE_URL}/chat/completions`，默认 `https://api.deepseek.com/chat/completions` |
| 认证 | 请求头 `Authorization: Bearer <DEEPSEEK_API_KEY>` |
| 超时 | 总计 120 秒，连接 10 秒 |
| 协议 | OpenAI 兼容的 chat/completions |

**请求体固定参数**（除 `messages` 外全部写死）：

```json
{
  "model": "deepseek-flash",
  "messages": [ { "role": "system", "content": "..." }, { "role": "user", "content": "..." } ],
  "response_format": { "type": "json_object" },
  "thinking": { "type": "disabled" },
  "temperature": 0,
  "max_tokens": 12000
}
```

说明：

- `model` 默认 `deepseek-flash`，可用 `.env` 的 `DEEPSEEK_MODEL` 覆盖。
- `response_format: json_object` 要求提示词里出现 "json" 字样——system 指令里已经写了，别删。
- `thinking: disabled` 是 DeepSeek 的关思考参数（省钱、更快）。
- `temperature: 0` 只降低随机性，**不保证**再次调用结果完全相同，所以结果必须落库复用而不是重算。

**手工验证用的 curl**（把 key 换成自己的）：

```bash
curl -s https://api.deepseek.com/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-flash",
    "response_format": {"type": "json_object"},
    "thinking": {"type": "disabled"},
    "temperature": 0,
    "max_tokens": 12000,
    "messages": [
      {"role": "system", "content": "Return one valid json object, no markdown."},
      {"role": "user", "content": "{\"title\":\"Hollow Knight\"}"}
    ]
  }'
```

## 3. 送给模型的输入（严格白名单）

`user` 消息是**紧凑 JSON 字符串**（`sort_keys=True`、无多余空格、中文不转义）。

**只发这些字段**：

```json
{
  "title": "Hollow Knight",
  "localized_title": "空洞骑士",
  "tags": ["Metroidvania", "Difficult", "Atmospheric"],
  "achievements": [
    { "id": "763", "display_name": "False Knight", "description": "击败假骑士" },
    { "id": "764", "display_name": "Steel Heart",  "description": "" }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `title` | 英文官方名，必有 |
| `localized_title` | 中文官方名，可能为 `null` |
| `tags` | SteamSpy 玩家标签 |
| `achievements[].id` | **本地快照定位号**（`achievements.local_id`，字符串）——只是主键，**不是剧情顺序** |
| `achievements[].description` | 没有时发空字符串 `""`，不发 `null` |

**刻意不发的字段**：`percent`（完成率）、`review_count`（评价数）、RAWG 通关/弃坑数、`position`。
理由是这些是**结果变量**，发了模型就会按"解锁率低 = 主线"这类相关性倒推，而不是真的读文本判断。

**第二批起多发一个字段**：`authoritative_game_dimensions`，值是第一批返回的游戏维度。
目的是让同一款游戏的所有成就批次用同一套维度标签，避免各批各起一套。

## 4. system 指令（分类）要求什么

原文在 `classification_messages()`。硬性要求：

- 返回**一个合法 JSON 对象，不要 markdown 包裹**。
- 输入里的成就 ID **每个恰好分类一次**，不许多、不许漏、不许重复。
- 枚举：`primary_category` ∈ main/side/collection/challenge/other/uncertain；
  `scope` ∈ base/dlc/uncertain；`requires_multiplayer` 为 true/false/null。
- `gameplay` / `theme` / `presentation` / `player_mode` 都必须是**字符串列表**；
  `gameplay` **非空**且只能取固定 14 词表（action, adventure, rpg, strategy, simulation,
  puzzle, platformer, racing, sports, survival, rhythm, casual, other, uncertain），
  **第一位即主玩法**；每个列表内部不允许重复标签。
- 证据不足时用 `uncertain`，**不许给空列表**代替。
- 每条标签都要有 `evidence`（非空文本）和 `uncertainty`（文本）。
- `confidence` 是 0～1 的有限数。
- **不许编造引用、URL，也不许声称经过人工验证。**
- 需要"多结局不算一个"这类纪律：联机是独立属性，不是分类；无法区分主线和可选 Boss 时标 uncertain。
- 第一批之后若带上 `authoritative_game_dimensions`，必须**原样重复**。
- 指令末尾附一个完整 JSON 示例（few-shot）。

## 5. system 指令（主线）要求什么

原文在 `story_messages()`。硬性要求：

- 本次调用给的就是**该游戏全部主线候选**，请一次选定全局有序节点。
- **按剧情前置关系排序，绝不按 ID 顺序**。
- `stage` ∈ start/early/middle/late/end；`route` ∈ common/branch。
- `requires_start`：该节点是否**必然**要求经过所选入门节点。
- **最多一个明确的 start 和一个统一的 common 结局**；如果多个结局无法用一个成就代表，
  必须 `unified_ending=false`。**绝不允许把多个结局合并或相加。**
- 如果不存在站得住脚的线性主线（沙盒、服务型游戏等），返回**空 checkpoints** +
  `unified_ending=false`。
- 只能引用输入里给过的 ID，每个最多一次；**允许省略**（不是每个 main 成就都要当节点）。
- 每条要有 `confidence` 和 `evidence`；不许编引用。

## 6. 期望的返回体

### 6.1 外层：标准 chat/completions 信封

```json
{
  "choices": [
    {
      "finish_reason": "stop",
      "message": { "role": "assistant", "content": "{\"game_dimensions\":{...},\"achievements\":[...]}" }
    }
  ],
  "usage": { "prompt_tokens": 1840, "completion_tokens": 2103, "total_tokens": 3943 }
}
```

`response_content()` 对信封的硬性检查（任一不满足都算**可重试失败**）：

1. 响应体必须是 JSON 对象；
2. `choices` 必须是非空数组，`choices[0]` 是对象；
3. `choices[0].finish_reason` 必须**恰好是 `"stop"`**——否则判为「输出被截断」；
4. `choices[0].message` 是对象，`message.content` 是非空字符串。

`usage` 不做校验，只原样记账（非数字/布尔值会被过滤掉）。

### 6.2 内层：`content` 是一段 JSON 字符串

注意 `content` 是**字符串**，里面才是 JSON，需要再解析一次。

**分类请求的 content**：

```json
{
  "game_dimensions": {
    "gameplay": ["action", "platformer"],
    "theme": ["dark fantasy"],
    "presentation": ["2d"],
    "player_mode": ["single-player"],
    "confidence": 0.9,
    "evidence": "supplied text",
    "uncertainty": "explain"
  },
  "achievements": [
    {
      "id": "763",
      "primary_category": "main",
      "scope": "base",
      "requires_multiplayer": null,
      "confidence": 0.9,
      "evidence": "supplied text",
      "uncertainty": "explain"
    }
  ]
}
```

**主线请求的 content**：

```json
{
  "checkpoints": [
    {
      "id": "763",
      "stage": "start",
      "route": "common",
      "requires_start": false,
      "confidence": 0.9,
      "evidence": "supplied text"
    },
    {
      "id": "810",
      "stage": "end",
      "route": "common",
      "requires_start": true,
      "confidence": 0.85,
      "evidence": "supplied text"
    }
  ],
  "unified_ending": true,
  "confidence": 0.85,
  "evidence": "supplied text",
  "uncertainty": "explain"
}
```

注意 `checkpoints[]` **不需要** `uncertainty` 字段（只有 `evidence` + `confidence`），
顶层需要。

## 7. 校验规则（不合格就重试，不落库）

### 分类 `validate_classification(data, ids)`

| 检查 | 不通过时 |
|---|---|
| 顶层是对象，且含对象类型的 `game_dimensions` | 拒 |
| `gameplay`/`theme`/`presentation`/`player_mode` 都是**非空字符串列表** | 拒 |
| 四个维度列表内部**无重复标签** | 拒 |
| `gameplay` 非空且**全部落在 14 词表内** | 拒 |
| `game_dimensions` 自身有 `confidence` / `evidence` / `uncertainty` | 拒 |
| `achievements` 是数组 | 拒 |
| 每个元素的 `id` 是字符串 | 拒 |
| `primary_category` / `scope` 在枚举内 | 拒 |
| `requires_multiplayer` **字段必须存在**，值为 bool 或 null | 拒 |
| 每条有 `confidence` / `evidence` / `uncertainty` | 拒 |
| **返回的 id 集合与输入批次完全相同**（不重、不漏、不新增） | 拒 |

另外：第二批起，返回的 `game_dimensions` 必须与第一批**完全相等**，否则判「批次间维度漂移」。
以及：返回内容里若出现 API key 明文，直接判失败（防泄漏）。

### 主线 `validate_story(data, ids)`

| 检查 | 不通过时 |
|---|---|
| 顶层 `unified_ending` 必须是 **bool**（不能是 null / 字符串） | 拒 |
| 顶层有 `confidence` / `evidence` / `uncertainty` | 拒 |
| `checkpoints` 是有序数组 | 拒 |
| 每个元素 `id` 是字符串，`stage` / `route` 在枚举内 | 拒 |
| `requires_start` 必须是 **bool** | 拒 |
| 每个元素有 `confidence` / `evidence`（不需要 `uncertainty`） | 拒 |
| checkpoint 的 id **不许重复**，且必须是输入候选的**子集**（允许省略） | 拒 |

## 8. 什么样的返回才"能用"（分析侧的额外条件）

校验通过只代表**格式合格**。`analysis.py` 还会在此基础上筛，主线曲线要满足
（**下面每个门槛都能在 [wwh5/params.py](./wwh5/params.py) 里调**，改完重跑 `analyze` 即可、不花钱）：

- 主线标签整体 `confidence ≥ 0.6`（原本是 0.8，见下方说明）；
- 至少 **2 个** `route=common` 的节点，且至少有一个 `stage=end`；
- 阶段顺序单调不减（start→early→middle→late→end），非 end 部分不倒退；
- 每个节点：`primary_category=main`、`scope=base`、`requires_multiplayer=false`、
  标签与节点 `confidence` 均 `≥ 0.6`；
- **沿剧情顺序完成率不出现反向上升**，且结局完成率不高于它前面的节点
  （出现则整条曲线排除，**不重排数据**）。

**不再要求**（2026-10-13 放宽）：`unified_ending=true`、恰好一个 start 在首位、
除首个节点外 `requires_start` 均为 true。

不满足的会写进报告的「排除原因」计数里，**不会**用示例数据顶替。

## 9. 错误与重试

单个请求最多尝试 **`params.MAX_ATTEMPTS` 次（默认 3）**，退避 **2s → 4s**
（`RETRY_BACKOFF_BASE ** attempt`，等待上限 `RETRY_MAX_WAIT_SEC`）。矩阵：

| 情况 | 处理 |
|---|---|
| HTTP 400 / 401 / 402 / 403 / 404 / 422 | **致命**：判为认证/计费/配置问题，**立即停止整轮**（避免把配置错误当成"这游戏没数据"） |
| 其他非 200（429、500、503…） | 可重试；等待时间取 `max(退避, Retry-After)`，上限 60 秒 |
| `finish_reason != "stop"` | 可重试（输出被截断） |
| `content` 不是合法 JSON，或校验不通过 | 可重试 |
| 网络/传输异常 | 可重试 |
| 3 次都失败 | 记 `status='error'`，该游戏本轮跳过；**不写标签**，任务是可重试的 |
| 进程被 Ctrl-C / 异常打断 | 记 `status='interrupted'`；下次启动会把遗留的 `running` 统一改判为 `interrupted` |

**错误文本里不保存传输异常原文**（可能含 URL 或密钥），只存
`HTTP <状态码>; <异常类型>: response validation failed` 这类归纳信息。

## 10. 续跑与去重

- 每次请求前算 `input_hash = SHA256(canonical(messages))`（对 messages 整体做哈希）。
- 若库里已有同一 `(appid, model, prompt_version, input_hash)` 且 `status='success'` 的记录，
  **直接复用已存的响应，不发请求、不重复计费**。
- 启动时把 `{model, prompt_version, batch_size}` 记为 `active_annotation`；
  之后若这三项变了而库没换，直接报错要求用新的 `--db`，防止新旧标注混在一张表里。
- `--max-requests N` 限制的是**真实 HTTP 次数（含重试）**，不是任务数。

## 11. 落库字段

`model_calls`（每次尝试一行）：

| 列 | 内容 |
|---|---|
| `appid` / `kind` | 游戏；`classification` 或 `story` |
| `model` / `prompt_version` | 参与去重的键 |
| `input_hash` | messages 的 SHA256 |
| `request_messages` | 发出去的 messages 原文（可复现） |
| `response_body` | 响应原文，**key 明文已替换成 `[REDACTED]`** |
| `usage` | 归一化后的 token 用量 |
| `status` | running / success / error / interrupted |
| `attempt` / `error` / `started_at` / `finished_at` | 重试与时间审计 |

响应校验通过后，**在同一个事务里**写标签表（`game_labels` / `achievement_labels` / `story_labels`），
所以「标了但没提交」不会发生，断点后不会重复付费。

## 12. 请求量的估算口径

`label --dry-run` 不发请求，输出两个计数：

- `pending_batch_calls`：**精确**的分类请求数（按每 40 条成就一批算）。
- `pending_story_calls`：每个待标注游戏算 1 次，是**上界估计**
  （因为只有被判为 `main` 的候选才发主线请求，而 main 数要分类完才知道）。
  返回值里带 `story_count_is_estimate: true` 提醒这一点。

实际请求数 = 分类批次数 + 有主线候选的游戏数，再乘上重试次数。

## 13. 并发执行（`--workers`）

**并行单位是「游戏」，不是「请求」。** 原因：同一款游戏的批次必须**串行**——第二批起要把
第一批的 `game_dimensions` 原样重复回去（见第 7 节），游戏内并行没有意义。不同游戏之间没有
任何共享状态，所以并行不改变结果，只是把网络等待重叠起来。

```bash
uv run python result/WWH/5/run.py label --workers 4    # 默认：同时处理 4 款游戏
uv run python result/WWH/5/run.py label --workers 1    # 串行（改造前的行为）
```

| 项 | 说明 |
|---|---|
| `--workers N` | 并行处理的**游戏数**，不是并发请求数的硬上限（重试会让瞬时请求数略高） |
| 默认值 | `params.LABEL_WORKERS`（4）|
| 与 `--max-requests` 的关系 | 名额由锁保护「判断 + 占用」一步完成，**并发下也不会超发**（不会因为 N 个线程同时看到"还剩 1 个"而多花钱） |
| 预算用尽 / 致命错误 | 不再开新的游戏，**已发出的请求等它收尾**（取消只对还没开始的生效） |
| SQLite | N 路并发共用一条连接，全部数据库操作由一把锁串行化；**网络请求在锁外**，所以慢等待互不阻塞 |
| 撞到 429 | 按 `Retry-After` 等待重试（同第 9 节）；并发越高越容易撞，可调低 `--workers` |
| `--dry-run` | 只扫描本地库、不发请求，一律串行（并行没意义） |

实测（2026-10-13，3 款游戏 / 3 workers）：**10 次请求 34 秒**跑完，日志里三个 appid 的请求
交错发出。单次请求约 10~13 秒，串行约需 110 秒。跑完核对：`integrity_check` 正常、
无悬空 `call_id`、同一 `input_hash` 无重复成功记录、标签数与成就数一致。

## 14. 分析口径（报告里这些数怎么算）

### 样本怎么定的

评价数 = SteamSpy `positive + negative`，非空且非负；按评价数降序、同分按 appid 升序取前 1000。
**先固定前 1000，再检查 RAWG / 映射 / 主线可用性**——缺数据或缺主线的游戏保留，
不用第 1001 名递补。输入来自一次 PostgreSQL 只读一致性快照，此后只在本地 SQLite 上做。

### 分类完成率

先在**每款游戏内**对同类成就取解锁率中位数，再跨游戏**等权**汇总（成就多的游戏不占更大权重）。
某款游戏没有该类别就记为不适用，**不填 0**。
按解锁率排序后的分布只能叫「成就解锁率排序曲线」，**不能当剧情顺序**。

### 主线完成比例

```
走到结局的人的占比 = 结局完成率 / 该游戏完成率最高的成就
```

**基准是该游戏完成率最高的成就**（≈「玩过这款游戏的人」），不是模型指定的入门节点——
所以这个数读作「**走到结局的人 ÷ 玩过这款游戏的人**」。

纳入条件见第 8 节。**多结局**取完成率最高的那个结局作分子，含义是「**至少**走到某个结局」
的**下界**；**绝不把多个结局相加**（解锁者可能重叠，相加会超过 100%）。单一结局游戏是
精确值，报告里按 `unified` / `multi` 分开统计。

倒挂的曲线**整条排除、不重排数据**；沙盒或在线游戏无可靠结局时仍保留分类统计。

Steam 全球成就比例和个人成就记录是**不同接口**，本项目用的是群体聚合数据。

> **2026-10-13 放宽了三处**：原口径只适用于「有唯一通关成就的单机线性游戏」，1000 款里
> 只剩 **7 款**可用（配对也只有 7，相关分析实际做不了）。放宽后可用曲线 **198 款**、
> RAWG 可配对 **183 款**，Spearman 从无意义变成 **0.645**。
> 代价是指标语义降级为「模型标出的主线序列上的到达比例」，报告与图表都据此改写过措辞。

### RAWG 配对对比

```
RAWG 通关占比 = beaten / (beaten + dropped)
```

两项计数都必须已观测且非负，**分母至少 20**；另报门槛 10 和 50，
四状态敏感性分析用 `owned + playing + beaten + dropped`（四字段都要观测到）。
`owned` 不能证明实际玩过，**NULL 不补 0**。

两个平台人群和定义不同，只比较散点分布、排序和 Spearman 相关，并报告实际配对游戏数；
常数或样本不足时相关不可计算。**不能把数值差距解释成某个平台"算错"。**

### 措辞红线

- 主线完成比例**不等于留存率**；`1 − 该比例` **不命名为弃坑率**。
- 平均成就解锁率**不等于**全成就玩家占比。
- 相关系数**不解释为因果**。
- 分类、剧情顺序、游戏维度全部是**模型判断**，没有人工复核，不能把模型自报置信度当准确率。
