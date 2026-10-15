# HLTB 时长只读同步到本地 SQLite

更新：2026-10-15。入口为 [import_hltb_times.py](../process/import_hltb_times.py)。沿用冻结的 [1000 个 AppID](../database/data/top1000_appids.json)，按 `appid` 从远端 `public.hltb_games` 读取 `main_hours`、`extra_hours`、`completionist_hours`，完整备份后迁移并写入本地 `games_time`。共享 PostgreSQL 全程只读，不调用爬虫、worker 或模型。

## 字段与来源

本地 schema 版本4，`games_time` 按以下顺序保存：

| 字段 | SQLite 类型 | 来源与口径 |
|---|---|---|
| `appid` | INTEGER 主键 | 与本地 `games`、冻结清单逐项核对；唯一关联索引 |
| `playtime` | INTEGER，可空 | 已有 RAWG 值，迁移和 HLTB 同步均原样保留 |
| `main_hours` | REAL，可空 | 远端 `hltb_games.main_hours`，主线耗时，单位小时 |
| `extra_hours` | REAL，可空 | 远端 `hltb_games.extra_hours`，主线加额外内容耗时，单位小时 |
| `completionist_hours` | REAL，可空 | 远端 `hltb_games.completionist_hours`，完整游玩耗时，单位小时 |
| `guide_difficulty` | REAL，可空 | 已有攻略难度保留，后续 Gamer Guides 入口只补这一列 |

`guide_time_hours_min` 和 `guide_time_hours_max` 已弃用；v3→v4 迁移物理删除两列，不转换为 HLTB 值。旧值仍可在迁移前完整备份与历史来源记录中追溯。六张业务表数量不变，没有新增历史表或 JSON 列。

只按 AppID 查询，不增加名称匹配、版本推断或其他覆盖筛选。来源无行时三列均置 `NULL`；来源单字段为 `NULL` 时该字段置 `NULL`。非空数值转为非负有限 SQLite REAL，来源 `0` 原样保留，不能当成已核实的零小时，也不自动改为缺失。重复同步使用所选快照覆盖三列，因此新快照缺行或缺字段也会更新为 `NULL`。

## 命令与运行产物

按项目规则先同步 main，再进入 LYX。当前环境使用已安装的 uv 环境：

```powershell
Set-Location D:\PycharmProjects\achievement-analytics
git pull origin main
Set-Location result\LYX
uv run --no-cache --frozen --no-sync python -X utf8 -B process/import_hltb_times.py fetch
```

`fetch` 只读本地库校验清单，并在一个远端 `REPEATABLE READ READ ONLY` 事务内取得字段元数据与时长记录。确认 `transaction_read_only=on` 后保存冻结快照和 `fetch_report.json`，不修改本地 SQLite。输出中的 `snapshot` 是后续 apply 使用的实际文件路径。下面示例使用本次已保存来源副本；新一轮请替换为该轮fetch输出的路径。

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/import_hltb_times.py apply --snapshot "process/runtime/hltb_import/2026-10-15T025331.038271_0000-360a6a2d/source_snapshot.json"
```

`apply` 完全使用本地快照，不再次连接远端。它校验格式、来源、字段、数值、时间和冻结清单，保存本次来源副本与指纹，完整在线备份为 `before_import.sqlite`，再在一个 `BEGIN IMMEDIATE` 事务中完成 v3→v4 迁移及1000行同步。已有 v4 库仅同步 HLTB 三列。验收失败回滚事务并写失败报告；本次运行不应与其他本地写库进程并行。

也可一次完成读取、备份和导入：

```powershell
uv run --no-cache --frozen --no-sync python -X utf8 -B process/import_hltb_times.py import
```

默认数据库为 `database/achievements.sqlite`，默认清单为 `database/data/top1000_appids.json`，默认产物目录为 `process/runtime/hltb_import/<时间>/`。可用 `--database`、`--appids` 指定 LYX 内文件；本地 `games`、`games_time` 必须精确覆盖清单中的1000款。`--run-dir` 指定新的运行目录，已有目录拒绝覆盖。`--snapshot` 仅供 apply 使用。

来源 JSON、快照副本、报告、数据库和完整备份均 Git 忽略。代码、SQL 与说明仍在 LYX；schema.sql沿用既有Git忽略，未改变跟踪策略。不修改共享库结构，不提交或推送。

## 已读取快照与验收口径

2026-10-15 已实际只读查询远端并完成主库导入。冻结1000款中匹配347行、缺行653；三列各有347个非空值及653个 `NULL`。零值分别为 `main_hours` 17、`extra_hours` 24、`completionist_hours` 26，均按源保留。原 `guide_difficulty` 的11款覆盖保持不变；其他五表数据及原 `appid/playtime/guide_difficulty` 摘要全部一致，`integrity_check=ok`、外键问题0。运行报告与完整备份保存在 [本次运行目录](../process/runtime/hltb_import/2026-10-15T025331.038271_0000-360a6a2d/) 的 `report.json`、`before_import.sqlite`。这些是本次验收快照，当前覆盖仍以 SQLite 与对应运行报告为准。

apply 验收逐 AppID 比较三列与冻结快照，同时比较其余五表全部数据、索引/触发器定义、六表行数，以及 `games_time` 原 `appid`、`playtime`、`guide_difficulty` 的稳定摘要。仅全部一致、`integrity_check=ok` 且外键问题为0时，报告 `status=complete`。`changed_rows` 表示该次实际改变的行数，重复使用同一来源在无其他写入时应为0。

迁移完成后可在 PyCharm 刷新连接或运行只读 SQL 查看当前覆盖：

```sql
PRAGMA user_version;
PRAGMA table_info(games_time);
SELECT COUNT(*) AS games,
       COUNT(main_hours) AS main_covered,
       COUNT(extra_hours) AS extra_covered,
       COUNT(completionist_hours) AS completionist_covered,
       COUNT(guide_difficulty) AS difficulty_covered
FROM games_time;
SELECT appid,playtime,main_hours,extra_hours,completionist_hours,guide_difficulty
FROM games_time ORDER BY appid;
```

HLTB 时长不作为 DeepSeek 成就分类输入；分类目标、提示词与标签规则保持当前契约。Gamer Guides 继续只补难度，操作见 [GUIDE_AGENT.md](GUIDE_AGENT.md)，历史攻略时间记录见 [GUIDE_TIME.md](GUIDE_TIME.md)。
