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
- **配额绑定 API key**，不是按机器、也不是按 IP → **加机器对 RAWG 完全无效**，
  扩容只能加 key。多个 key 放在**共享库的密钥池**里协调取用（见下）
- **响应头不暴露剩余额度**（实测无任何 `x-ratelimit` 字段）→ 靠 `api_usage` 与
  `rawg_key_usage` 自行记账；余额查 `quota_status` 与 `rawg_key_status` 视图
- **成本（实测，n=100）**：**4.95 次请求/款**（495 次 / 100 款）
- **评价数阈值（2026-09-18）**：seed 物化任务时，`review_count < 100` 的游戏**不建**
  RAWG 任务（`--rawg-min-reviews` 可调，传 0 关闭）。试水证实低评价游戏在 RAWG 上
  几乎必然没数据（n=100：72 款未匹配、28 款匹配上也近乎空表），阈值把月配额留给
  有知名度的游戏
- 坑：RAWG **不支持按 Steam appid 查**，只能「按官方名搜 → 逐个候选查
  `/games/{id}/stores` → appid 一致才算匹配」。已改为 `search_exact` 优先以压低候选数
- **未做的优化**：`match_by_appid` 匹配成功后仍调了一次 `fetch_game_detail`，但搜索
  结果的候选里**已经带齐** `metacritic` / `rating` / `ratings_count` / `playtime` /
  `added_by_status` / `tags` / `genres`（核对搜索结果确认），这次详情请求是冗余的。
  去掉它 + 收紧 `max_candidates`（现 6）后，4.95 有望降到 ~2.5 次/款，
  单 key 覆盖量从 ~4,040 款/月 翻倍到 ~8,000 款/月

#### 密钥池（多 key）

```bash
uv run python -m cleaning.rawg_keys add --key <KEY> --label <谁的>   # 注册
uv run python -m cleaning.rawg_keys list                            # 看各 key 余额（不显示明文）
uv run python -m cleaning.rawg_keys disable --key-id 3              # 停用已超额的
```

- 取用：`reserve_key()` **原子地**挑一个本月还有余额的 key 并计数 +1；`worker` 把它
  注入 `crawler.rawg.set_key_provider`，每次真实请求消耗一次
- `rawg_key_status` 视图只给 `key_hint`（尾 4 位），**不暴露明文**
- ⚠️ 为单一项目批量注册 key 去绕过「每 key 20,000/月」的额度，可能违背 RAWG 的条款
  精神。负责人已知悉并决定采用；**回链与「非商业」两条要求必须落实**

## 成本换算

**当前数据范围：只取 2026 年以前发售的游戏，实测估计约 49,900 款**
（`seed --before-year 2026`，已是默认；采样 24 页估算，占带成就游戏 81,850 的 61%）。

| 层 | 覆盖 | 请求数 | 单机 1 req/s | 多机器 |
|---|---|---|---|---|
| 商店枚举（bulk） | 49,900 款 | ≈ 819 | **≈ 14 分钟** | — |
| SteamSpy 热度（bulk） | ≈ 8.5 万款 | ≈ 86 | ≈ 86 分钟（60s/页） | ✅ |
| `appdetails_en` | 49,900 款 | 49,900 | ≈ 13.9 小时 | ✅ |
| `appdetails_zh` | 49,900 款 | 49,900 | ≈ 13.9 小时 | ✅ |
| `global_ach` | 49,900 款 | 49,900 | ≈ 13.9 小时 | ✅ |
| `community_ach` | 49,900 款 | 49,900 | ≈ 13.9 小时 | ✅ |
| **Steam 侧小计** | | **≈ 199,600** | **≈ 55.4 小时** | ✅ **线性缩短** |
| `steamspy` | 49,900 款 | 49,900 | — | ✅（但受自设 1000/天限制） |
| `rawg` | 49,900 款 | **≈ 247,000** | — | ❌ **只能加 key**：单 key 需 **12.4 个月** |

两条结论：

1. **Steam 侧加机器有效**：55.4 小时 ÷ N 台。
2. **RAWG 加机器无效**，只有两条路：加 key，或先把每款请求数从 4.95 压到 ~2.5。

抽样口径与总体定义见 `docs/plan.md`；运行参数见 `AGENTS.md`。

## HTTP 层的重试与退避

| 层级 | 次数 | 退避 |
|---|---|---|
| 单次请求（`crawler/http.py`） | ≤ 3 | 2s、4s（`RETRY_BACKOFF_SEC`，封顶 30s） |
| 商店搜索页（`crawler/store_search.py`） | ≤ 3 | 5s、10s；彻底失败记「空洞」并继续翻页 |

- **没有缓存层**（2026-09-17 废除）：防重复靠 `fetch_tasks` 的任务状态，DB 是唯一事实源
- 商店枚举出现空洞 → 帧不完整，重跑同一条命令会重新发那些页的请求、只补空洞
- 若空洞持续出现，应提高 `sources.interval_ms`（同时改 `crawler/registry.py`，测试会校验一致）
