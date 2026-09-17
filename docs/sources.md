# 数据源限额与成本

> 本文是**限额速查表**。程序侧的真源是 `cleaning/schema.sql` 的 `sources` 表与
> `crawler/registry.py`（`tests/test_registry.py` 断言两者一致），本文只做人和文档的对照。
> 核对日期：**2026-09-17**。

## 来源等级说明（重要）

本文中每个数字都标注来源，三类不可混排：

| 标记 | 含义 |
|---|---|
| **实测** | 本项目实际发请求验证过 |
| **官方文档** | 站点公开文档的原文口径，已附链接 |
| **自设** | 官方没有公布，本项目为礼貌抓取自行设定的保守值 |

**没有官方公布限速的接口不要臆造数字。** 此前代码注释曾写「SteamSpy 官方限速每天
1000 次」，2026-09-17 核对官方页面后确认**查无此说**，已改为标注「自设」。

## 限额总表

| 源 | 类型 | 限速 | 日限 | 月限 | key | 限速来源 |
|---|---|---|---|---|---|---|
| `store_search` | bulk | 1s | — | — | 免 | **自设** |
| `steamspy_all` | bulk | **60s** | — | — | 免 | **官方文档** |
| `appdetails_en` | per_game | 1s | — | — | 免 | **自设** |
| `appdetails_zh` | per_game | 1s | — | — | 免 | **自设** |
| `global_ach` | per_game | 1s | — | — | 免 | **自设** |
| `community_ach` | per_game | 1s | — | — | 免 | **自设** |
| `steamspy` | per_game | 1s | — | — | 免 | 限速官方 / 日限自设 |
| `rawg` | per_game | 1s | — | **20,000**（官方文档） | **需** | 配额官方 / 限速自设 |

`—` = 无限制或不适用。**bulk 源不进队列**（一次请求覆盖多款），**per_game 源进
`fetch_tasks`** 走 gap 驱动回填。

## 逐源说明

### Steam 商店搜索 `store_search`（bulk，免 key）

- **一次 100 款**（`count` 硬上限 100，传 1000 仍只回 100 —— 实测）
- 免 key，且是全项目**唯一**的全量枚举入口
- 过滤口径（实测 `total_count`）：全站 285,346 ／ 只要游戏（`category1=998`）
  176,932 ／ **游戏且带成就（`+category2=22`）81,850**
- **限速 1s 是自设**：Steam 未公布此接口的限速
- 坑：① 每页条数**不是承诺值**，限流时会缩到 25/99 条，故分页必须按实际返回行数推进；
  ② `total_count` 会随时间变动（同日测到 81,847 / 81,849 / 81,850 / 81,851）；
  ③ 实测连续约 30 次请求后开始失败，需退避（已加页级重试）

### SteamSpy 全量 `steamspy_all`（bulk，免 key）

- **一次 1000 款**，含 `owners` / `ccu` / 好评差评
- **限速 60s（官方文档）**：`Allowed poll rate - 1 request per second for most
  requests, 1 request per 60 seconds for the *all* requests.`
  （<https://steamspy.com/api.php>，2026-09-17 核对）
- 覆盖约 8.5 万款（实测 page 85 仍返回 1000 条，page 88 报
  `Connection failed: Too many connections`；**这是服务端连接数限制，非公布的分页上限，会浮动**）
- 坑：返回**不含 `tags`**（官方文档「Return format for an app」列的 tags 是
  `appdetails` 的字段，`all` 没有 —— 实测）；`average_forever` / `median_forever` 已失效恒为 0

### Steam 官方三源 `appdetails_en` / `appdetails_zh` / `global_ach` / `community_ach`（per_game，免 key）

- 各 1 款/请求，**限速 1s 全部是自设**（Steam 未公布任何限速；AGENTS.md 要求 ≥1s）
- 坑：① `appdetails` **不支持批量**（多 appid 返回 400，2026-09-15 验证）；
  ② 中英文是**两次独立请求**，队列路径下各自只拉自己要的语言，否则请求数翻倍；
  ③ 全局完成率与社区成就页返回的成就**顺序一致**，按位对齐完成名称映射

### SteamSpy 逐款 `steamspy`（per_game，免 key）

- 唯一独有价值是 **`tags`**（用户自定义标签 + 票数），bulk 的 `all` 拿不到
- 限速 1s（官方文档）；**日限 1000 是本项目自设的保守上限，官方页面未记载此限制**
- **成本警告**：81,850 款按 1000/天要 **82 天**，不要盲目全量入队

### RAWG `rawg`（per_game，**需 key**）

- 免费档 **20,000 请求/月**（**官方文档** <https://rawg.io/apidocs>，2026-09-17 核对）；
  免费档限非商业用途，且要求使用页面加 RAWG 回链
- **响应头不暴露剩余额度**（实测无任何 `x-ratelimit` 字段）→ 必须靠 `api_usage` 自行记账，
  余额查 `quota_status` 视图
- **成本（实测，样本 n=5，可信度有限）**：26 次请求匹配 5 款 ≈ **5.2 次/款**。
  按此推算月覆盖量约 **3,800 款/月** —— 注意这比我早期估的 2~3 次/款保守得多，
  且样本含新品硬例，建议先跑 50~100 款再据实定价
- 坑：RAWG **不支持按 Steam appid 查**，只能「按官方名搜 → 逐个候选查
  `/games/{id}/stores` → appid 一致才算匹配」。已改为 `search_exact` 优先以压低候选数

## 成本换算（1s 间隔，串行）

| 层 | 覆盖 | 请求数 | 耗时 |
|---|---|---|---|
| 商店枚举（bulk） | 81,850 款 | ≈ 819 | **≈ 14 分钟** |
| SteamSpy 热度（bulk） | ≈ 8.5 万款 | ≈ 86 | ≈ 86 分钟（60s/页） |
| 单个 per_game 源 | 81,850 款 | 81,850 | ≈ **22.7 小时** |
| 成就两源合计 | 81,850 款 | 163,700 | ≈ **45.5 小时** |
| RAWG | 受配额锁死 | 20,000/月 | ≈ 3,800 款/月 |

结论：**bulk 层可以全量，per_game 层（尤其 RAWG 与 SteamSpy）必须抽样。**
分层总体的定义与抽样口径见 `docs/plan.md`；运行参数见 `AGENTS.md`。

## HTTP 层的重试与退避

| 层级 | 次数 | 退避 |
|---|---|---|
| 单次请求（`crawler/http.py`） | ≤ 3 | 2s、4s（`RETRY_BACKOFF_SEC`，封顶 30s） |
| 商店搜索页（`crawler/store_search.py`） | ≤ 3 | 5s、10s；彻底失败记「空洞」并继续翻页 |

- **缓存命中不计配额**：`http.py` 只在真正发出网络请求时回调记账，缓存命中不经过该层
- 商店枚举出现空洞 → 帧不完整，重跑同一条命令会命中缓存、只补空洞
- 若空洞持续出现，应提高 `sources.interval_ms`（同时改 `crawler/registry.py`，测试会校验一致）
