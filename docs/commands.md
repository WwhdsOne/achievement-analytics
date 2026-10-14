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

## 6. 冒烟与验收

```bash
uv run python -m crawler.test_crawl          # 单款游戏六源抓取演示（不走队列、不写库）
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
| 改了代码想提交 | **项目不维护测试用例**（`tests/` 已于 2026-10-13 删除）：把受影响的命令真跑一遍确认没问题；commit message 用 `<scope>: <中文>` |

## 8. 状态面板

数据获取阶段汇报见 [HTML汇报](data-acquisition-report.html)，可直接打开，无需服务器；仅展示获取流程与描述性成果，数字注明统计日期。

```bash
# 本机起面板（Go 只读后端，前端已 embed 进二进制）；端口已占用时换另一个。
# 在 dashboard/ 里跑：它读同目录的 .env，报告路径自动找到 ../data/processed/。
# ⚠️ .env 里的 POSTGRES_HOST 是给容器用的 127.0.0.1，本机预览要临时覆盖成公网地址
cd dashboard && POSTGRES_HOST=82.157.208.173 go run . --port 8601
# 在 dashboard/ 里跑：它读同目录的 .env，报告路径自动找到 ../data/processed/。
# ⚠️ .env 里的 POSTGRES_HOST 是给容器用的 127.0.0.1，本机预览要临时覆盖成公网地址
cd dashboard && POSTGRES_HOST=82.157.208.173 go run . --port 8601

# 带上与线上一致的限速（本地默认不限速）。循环地址豁免，所以本机访问不受影响
cd dashboard && POSTGRES_HOST=82.157.208.173 go run . --port 8601 --rate-limit 60

# 浏览器验收，临时测试依赖不改变pyproject.toml/uv.lock；需安装Google Chrome
uv run --with playwright python scripts/check_dashboard_browser.py --url http://127.0.0.1:8601
```

展示入口：`http://127.0.0.1:8601/#explore`。游戏数据故事与 AppID 查询已合并为「游戏探索」，直接只读查询云库，不依赖分析报告。搜索与发现分成「搜索游戏」「发现游戏」两个标签页，搜索支持游戏名、AppID、Steam 商店链接；发现入口展示热门、成就数量较多、免费游戏，当前展示集合可按评价数/好评率/成就数重新排序。详情含常见/稀有成就、三平台评分、玩家标签票数、同开发商作品与同名成就趣味对照，「更多游戏信息」默认展开（完整成就清单与数据详情折叠）。旧 `#analysis/*` 和 `#game` 地址自动转到新入口。队列总览保留。

「类型词云」已改为「数据全景」（`#overview`），移除官方类型词云，保留玩家标签词云。新增游戏/成就/标签规模、评价数分档与前1%游戏的评价份额、成就数量中位数与千成就游戏数量、低于1%解锁率的成就占比，以及免费/付费标记分布。每块明确统计分母与缺失量，全部仅为当前库的描述性统计；`/api/overview` 一个只读SQL获取一致统计并缓存五分钟，不依赖报告文件。旧 `#cloud` 自动跳转到 `#overview`。

开发口径：`随便逛逛` 在服务端按评价数量前500款均匀抽取一款，页面不展示筛选范围。评价数优先使用 SteamSpy 的好评+差评，任一字段缺失时回退商店搜索记录，同分按 appid 排序；好评率使用同源的计数，零评价时不显示比例；发现列表缓存五分钟。价格字段未保存货币，现有数据混有不同地区金额，因此只展示免费/付费并提供商店链接；在线数标明采集时口径，SteamSpy 已失效的时长字段不展示，成就名称映射有疑义时不展示具名故事。页面保留 RAWG 回链，不包含研究计划中的专题。

⚠️ **原 Q2 建模代码（`modeling/`）已于 2026-10-14 删除**——项目改为按 `docs/plan.md` 的方向
分工，各人产物放 `result/<缩写>/`，实验记录也迁到各自目录（面板相关的在
[experiments.md](experiments.md)）。当时生成的 `data/processed/analysis-report.json`
（不入Git）仍在，但**再也不能重新生成**。

## 9. 面板部署（腾讯云，Go 单文件）

`dashboard/` 是**自包含**的：`go.mod` / `.env` / `Dockerfile` / `docker-compose.yml` /
`deploy.sh` 全在这个目录里，仓库根目录不放任何面板相关文件。后端是 **Go、只读**，前端 embed
在同一个二进制里；镜像 `FROM scratch`，最终 16MB，容器内存约 6MB。跑在腾讯云那台机器上
（`network_mode: host`，容器内 `127.0.0.1:15432` 即宿主上的 PostgreSQL），公网入口
`http://82.157.208.173:8600`。

```bash
# 一条命令搞定（也可 cd dashboard && bash deploy.sh）
bash dashboard/deploy.sh
```

脚本做四件事：交叉编译 linux/amd64 → **从 `dashboard/.env` 抽出容器连库需要的 `POSTGRES_*`**
（值原样照搬，不做任何改写）→ 打成 tar 上传到服务器 `/opt/achievement-dashboard/` →
`docker compose up -d --build` → 远端探活 → 本机探公网 → 确认补抓接口是 404。
**服务器上不需要仓库、不需要 Git、不需要 Python。**

配置全在 **`dashboard/.env`**（不入 git，也**不读仓库根的 `.env`**）。两段各自独立填写、
原样使用：

| 键 | 用途 |
|---|---|
| `DEPLOY_HOST` / `DEPLOY_USER` | 服务器地址与登录账号，只给 `deploy.sh` 用 |
| `DEPLOY_PASSWORD` | SSH 密码，脚本用 `expect` 免交互应答（macOS 没有 sshpass） |
| `DEPLOY_PATH` / `DEPLOY_PORT` | 部署目录（默认 `/opt/achievement-dashboard`）与端口（默认 8600） |
| `POSTGRES_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` | 数据库地址与凭据，原样传给容器。面板与库同机、容器走 host 网络，所以 `HOST` 填 `127.0.0.1` |

**本机预览面板**时把数据库地址临时覆盖成公网地址（环境变量优先于 `.env`）：

```bash
cd dashboard && POSTGRES_HOST=82.157.208.173 go run . --port 8601
```

面板启动时会打印实际连的库（`数据库：host:port/db`），一眼能确认填对没有。

**首次在一台新机器上部署前的准备**：服务器装好 Docker 与 compose 插件；在**腾讯云控制台
放行入站 TCP 8600**。就这两步——部署目录、容器 `.env`、报告文件都由脚本自动铺好。
每次部署都会重新上传那份容器 `.env`，它只有 `POSTGRES_*` 五个键，
**SSH 账号密码不会离开本机**。

服务器上的排障命令（都在 `/opt/achievement-dashboard` 下）：

```bash
docker compose ps                       # 容器在不在、健康状态
docker compose logs --tail 50 dashboard # 面板日志（只有 stderr，不落文件）
docker compose restart dashboard        # 只重启
docker compose down                     # 停掉（公网随即不可访问）

curl -s localhost:8600/api/progress | head -c 200   # 数据接口
curl -s -o /dev/null -w '%{http_code}\n' localhost:8600/   # 静态页
ls -lh /opt/achievement-dashboard                   # 看二进制/报告是什么时候传上来的
```

排障要点：

- **公网打不开但服务器本机 curl 127.0.0.1:8600 正常** → 十有八九是安全组没放行。
  踩过的坑：没放行时 `curl` 会报「Connected 然后 Empty reply」，很像服务端故障，
  其实包根本没到主机（`tcpdump -i eth0 port 8600` 一个包都抓不到），是前置网关代答了握手
- 面板 500 且日志是 `FATAL: sorry, too many clients already` → 共享云库连接数被占满，
  先去查是不是有机器在并发跑 `worker`。面板自身连接池上限是 4，且全程共用一个池
- 限速与端口写在 compose 的 `command` 里，改完要**重新部署**（`bash dashboard/deploy.sh`）才生效。
  验收脚本（`scripts/check_dashboard_browser.py`）会连发几十个 `/api/*`，**从自己机器打公网
  地址时会被限速**（60 次/分钟）；要跑就先临时把 `--rate-limit 60` 去掉再部署
- **同一 IP 累计被拒 2 次即封禁 8 小时**：封禁期间 `/api/*` 一律 429（`Retry-After` 为剩余
  秒数），错误信息里写明原因与剩余时长。被封大多是一轮爆发超额——第 61 个请求被拒后，
  只要再来 1 个被拒请求就封。谁被封看容器日志（`docker compose logs dashboard | grep 已封禁`）
- 面板是课程内部工具，`net/http` 直接对公网服务，没做请求体大小/超时那类加固。
  已知限度：限速是进程级的，重启容器即清零、多出口 IP 也能绕过——挡手滑和爬虫，不挡 DDoS

