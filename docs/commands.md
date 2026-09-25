# 命令手册

> 数据获取侧的日常操作速查。口径细节见 `AGENTS.md`，限额见 `docs/sources.md`，
> 流程讲解见 `docs/data-pipeline.html`。所有命令在项目根目录执行。

## 0. 环境准备（每人一次）

```bash
git clone https://github.com/WwhdsOne/achievement-analytics.git
cd achievement-analytics
uv sync                                  # Python 3.13，自动建环境
cp .env.example .env                     # 然后填好数据库与 key
```

`.env` 必填项：

| 变量 | 说明 |
|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | 共享云库（所有人填同一组值，这是多机并行的前提） |
| `STEAM_API_KEY` | 仅全量 appid 枚举用，可共用 |
| `RAWG_API_KEY` | 可不填——key 应注册进密钥池（见 §4）；没有 key 的机器上 RAWG 任务会退避重试，不阻塞其他源 |

⚠ 自建库**不要**设 `POSTGRES_SSLMODE`（服务器不支持 SSL）。

## 1. 数据库初始化（全组只跑一次，已由组长完成）

```bash
uv run python -m cleaning.db init      # 应用 schema.sql，唯一改表结构的入口，幂等
uv run python -m cleaning.db status    # 检查库是否就绪
```

- `worker` / `seed` / `rawg_keys` 启动时**只校验**、不建表——队友不可能意外改共享库结构
- 要改 schema：先在自己本地验证，再走 `db init`，并同步 `cleaning/schema.sql`

## 2. 种子 seed（组长已完成，队友一般不用碰）

```bash
# 全量枚举 + 物化任务队列（约 819 次请求、14 分钟）
uv run python -m cleaning.seed --materialize

# 帧已入库后，只补物化任务（秒级、幂等，日常用这个）
uv run python -m cleaning.seed --no-enumerate --materialize

# 冒烟：只枚举前 N 款看数据形态（非随机，别当分析样本）
uv run python -m cleaning.seed --limit 300 --materialize

# 从完整帧随机抽 N 款先跑（无偏）
uv run python -m cleaning.seed --no-enumerate --materialize --sample 1000
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--before-year N` | 2026 | 只枚举该年份以前发售的游戏；`--all-years` 关闭 |
| `--sort` | `Released_DESC` | 枚举排序；**只有它能保证低漂移与提前停止的完整性**，别改 |
| `--materialize` | 关 | 物化 `fetch_tasks` 任务队列 |
| `--sample N` / `--order` | — | 只给 N 款建任务；`random`（帧完整时无偏）/ `review_count`（热门优先）/ `appid` |
| `--rawg-min-reviews N` | 100 | RAWG 任务的评价数阈值，0 = 不设限（改阈值 = 改 RAWG 预算） |

要点：
- 枚举**每次都会真实重发**那 819 页请求（无缓存层），帧完整后一律加 `--no-enumerate`
- 物化只**增**不**删**：已存在的任务不会被重置或撤回；调 RAWG 阈值口径需先删对应行再物化
- 结束时报告「空洞」数——**空洞 > 0 说明帧不完整**，重跑同命令只补洞

## 3. 回填 worker（日常，随便开）

```bash
uv run python -m cleaning.worker              # 跑到抢不到任务为止，可随时 Ctrl-C
uv run python -m cleaning.worker --progress   # 只看各源进度，不干活
uv run python -m cleaning.worker --dry-run    # 看接下来会抓什么，不发请求
uv run python -m cleaning.worker --limit 10000   # 只处理 10000 个任务（试跑）
uv run python -m cleaning.worker --source rawg              # 只跑某个源
uv run python -m cleaning.worker --exclude steamspy         # 挂起某源跑其余（源临时不可用）
uv run python -m cleaning.worker --appid 367520             # 单游戏全流程（调试）
uv run python -m cleaning.worker --prune      # 批量剔除「无成就」游戏的剩余任务后退出
```

- 抢占是原子的（`FOR UPDATE SKIP LOCKED` + 5 分钟租约），**多台机器同时跑不会重复抓同一条**
- 中断 / 崩溃都安全：重跑自动续，租约到期自动释放，无需清理
- 「还缺什么」看 `ingest_gaps` 视图，「进度」看 `ingest_progress`

## 4. RAWG 密钥池

```bash
uv run python -m cleaning.rawg_keys add --key <KEY> --label 张三   # 注册（可重复注册更新）
uv run python -m cleaning.rawg_keys list                           # 各 key 余额（只显示尾 4 位）
uv run python -m cleaning.rawg_keys disable --key-id 3             # 停用超额 key
uv run python -m cleaning.rawg_keys enable  --key-id 3             # 重新启用
```

- key 存**共享库**，所有机器看到同一份余额；worker 每次请求原子取一个有余量的 key
- 余额速查 SQL：`SELECT * FROM rawg_key_status;`（本月用量 / 剩余 / 今日用量）
- 配额按 key 计（20,000 次/月/key），**加机器无效，扩容只能加 key**
- 条款义务：非商业（课程项目符合）+ 使用页加 RAWG 回链（最终报告必须落实）

## 5. 配额与进度速查（只读 SQL）

```sql
SELECT * FROM ingest_progress;   -- 各源任务分布（ok/empty/skipped/err/待抓/可执行）
SELECT * FROM ingest_gaps;       -- 还缺什么（error / exhausted 的任务清单）
SELECT * FROM quota_status;      -- 各源今日/本月配额余量
SELECT * FROM rawg_key_status;   -- 逐 key 余额（不含明文）
```

## 6. 测试与冒烟

```bash
uv run pytest                                # 全量单测（schema 契约、抢占 SQL、状态机…）
uv run python -m crawler.test_crawl          # 单款游戏六源抓取演示（不走队列）
```

## 7. 场景速查

| 场景 | 命令 |
|---|---|
| 新队友第一天 | `uv sync` → 配 `.env` → `worker --progress` 看一眼 → 直接 `worker` 开抢 |
| 全量开跑（只做一次） | 组长跑 `seed --materialize` 物化全部任务，之后大家只跑 `worker` |
| 中途断了 | 直接重跑同一条 `worker`，自动续 |
| **某源临时不可用**（如 Cloudflare challenge / 整站 403） | 现在会**自动处理**：worker 识别挑战后把任务放回队列、本轮挂起该源，日志会打印「遭到反爬挑战，本轮挂起」。想手动挂起用 `worker --exclude steamspy`；探测恢复：`curl -s -o /dev/null -w "%{http_code}" "https://steamspy.com/api.php?request=appdetails&appid=440"` 返回 200 即恢复 |
| **全量跑完后的收尾（必做）** | `uv run python -m cleaning.repair_mapping --from-issues` —— 把台账里「成就两源顺序不一致」的游戏按 percent 重对齐修复（两源免费，不花 RAWG 配额）。跑完 `mapping_issues` 里 `resolved=false` 应为 0；建模时用 `WHERE appid NOT IN (SELECT appid FROM mapping_issues WHERE NOT resolved)` 过滤兜底 |
| 怀疑某游戏数据有问题 | `worker --appid <id> --limit 6` 单款重抓（先 `DELETE` 该款任务行可强制重跑） |
| RAWG 快没额度了 | `rawg_keys list` 看谁还有余量；都耗尽就等下月或加 key |
| 改了代码想提交 | 全量 `uv run pytest` 过了再说；commit message 用 `<scope>: <中文>` |
