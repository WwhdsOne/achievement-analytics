# WWH 第5项三图复现

建立日期：2026-10-16；同日迁入 `analysis/T0Pre`。负责人：刘宇翔（LYX）。分析与绘图逻辑复制自王文海（WWH）的 `result/WWH/5/wwh5/analysis.py`，并在本目录独立适配运行。返回[分析阶段导航](../README.md)。源文件指纹记录在 [source_provenance.json](source_provenance.json)。其中保留初次复制时的路径与哈希；WWH现已将程序移到src、说明移到docs，文末参考链接指向现存位置。

本阶段全面采用 WWH 已有的游戏样本、成就分类、剧情阶段、节点数组顺序和游戏类型，不与旧 LYX 分类合并，不要求重新分类或新增人工排序后才能运行。模型标注仍按模型标注说明，不据此宣称人工核验或因果关系。

## 运行

从 `result/LYX` 目录执行：

```powershell
uv --cache-dir analysis/T0Pre/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T0Pre/run.py analyze
```

从项目根目录执行：

```powershell
uv --cache-dir result/LYX/analysis/T0Pre/runtime/uv-cache run --frozen --no-sync python -X utf8 -B result/LYX/analysis/T0Pre/run.py analyze
```

默认使用 `NewDB/wwh5.sqlite3`，路径以程序所在位置解析，不依赖终端当前目录。不需要 API key、`.env`、网络或共享 PostgreSQL。

### 两种基准

WWH 当前 `params.py` 中 `CURVE_BASELINE="start"`，但仓库已有三张图、报告和借用库最后一次历史分析对应 `highest`。本目录默认 **highest**，以复现那些已有结果，并把实际参数同时写进报告、图中文字和运行文件。

| 参数 | 分母 | 用途 |
|---|---|---|
| `--baseline highest`，默认 | 游戏全部成就中的最高解锁率 | 复现 WWH 已有 figures/report |
| `--baseline start` | 模型指定的显式首个入门节点解锁率 | 对照 WWH 当前参数文件 |

建议对照运行到另一目录，以保留默认复现结果：

```powershell
uv --cache-dir analysis/T0Pre/runtime/uv-cache run --frozen --no-sync python -X utf8 -B analysis/T0Pre/run.py analyze --baseline start --output analysis/T0Pre/current_start
```

`--bootstrap-samples` 默认 2000，随机种子 42；0 表示不计算 Bootstrap 区间。`--db` 可指定 LYX 内另一份已有 WWH 格式快照；`--output` 必须位于本 T0Pre 目录。重复运行覆盖指定输出目录的本轮文件，历史 WWH 数据库始终不变。

## 三张图从哪里来

全部由 [wwh_replay/analysis.py](wwh_replay/analysis.py) 的 `analyze()` 汇总，再由 `_figures()` 绘制。

| 输出 | 数据与处理 |
|---|---|
| `figures/category-completion.png` | `achievement_labels` 的六类单选主类别，关联 WWH 原始成就解锁率；只使用完整分类游戏。游戏内同类解锁率取中位数，再按游戏等权取均值。沿用 WWH 规则，包含其低置信度分类，不套用旧 LYX 的入库门槛。 |
| `figures/main-story-curves.png` | `story_labels.payload.checkpoints` 的模型数组顺序和阶段。沿用 WWH 本体、公共路线、非联机、置信度不低于0.6等筛选；反向曲线整条排除，不按解锁率重排。游戏内同阶段先取中位数，再在同类游戏间取中位数；阶段缺失不补齐，各阶段有效游戏数可能不同。 |
| `figures/rawg-comparison.png` | 同一批有效主线曲线的结局/基准比例，与 `games.payload.rawg` 的 `status_beaten/(status_beaten+status_dropped)` 配对；最低分母20，另报10/50与四状态口径；Spearman与游戏层Bootstrap。 |

游戏主类型直接取 `game_labels.payload.gameplay[0]`。补充维度使用同一记录中的 `gameplay/theme/presentation/player_mode` 多标签，不使用旧 LYX 官方类型表或重新生成类型。

## 顺序与分类的来源

- 原始成就：`achievements`，身份为 `(appid, local_id)`。
- 成就分类：`achievement_labels.payload` 的 `primary_category/scope/requires_multiplayer/confidence`。
- 剧情节点：`story_labels.payload.checkpoints`；数组下标为模型候选顺序，`id` 不是顺序号，`stage` 不是序号。
- 输出指标中的 `source_checkpoint_index` 保留原数组0基下标；`source_checkpoint_order` 为下标+1。筛除分支后可能有空号，不能据此重排或改变原数组含义。
- `route`、`requires_start` 和节点置信度随选中节点输出；默认沿用 WWH 的 `REQUIRE_START_CHAIN=False`。
- 多结局取最高结局解锁率，不相加；保留 `unified/multi` 区分。未增加旧 LYX 的至少6节点筛选。

模型给出的节点顺序、阶段、分类和类型是本阶段采用的分析输入，不自动写成旧库的 `approved` 或 `mainline_index`。最高解锁率成就不等于实际启动人数，聚合解锁率比值不等于用户级留存率。

## 文件与权限

```text
analysis/T0Pre/
  run.py                    独立入口、参数选择、数据库前后指纹核验
  wwh_replay/analysis.py     复制适配后的统计、三图及报告程序
  wwh_replay/params.py       从WWH复制的分析参数；默认highest
  wwh_replay/storage.py      只读连接与文件输出，无建表或写库接口
  source_provenance.json    原始代码/说明/报告的SHA256
  reference/WWH_REPORT.md   原报告快照，作为历史对照
  report.md                 本次生成的中文报告
  figures/                  本次生成的三张图
  metrics.json              完整游戏级和分组指标，运行产物不入Git
  verification.json         数据库指纹、参数和历史结果对照，不入Git
  runtime/                  Matplotlib/uv缓存，不入Git
```

原 WWH `storage.connect()` 会执行 schema，`analyze()` 会向 `analysis_runs` 写入。本适配全部移除，连接使用 `mode=ro`、`PRAGMA query_only=ON` 和只读快照事务；运行记录改存 `metrics.json`，不追加数据库历史。旧 `database/achievements.sqlite` 只计算前后文件指纹，不参与指标计算。

所有代码和输出限制在 `result/LYX`，本入口的输出进一步限制在 `analysis/T0Pre`。不会修改 WWH 目录、两份数据库、共享依赖或原分类流水线。没有复制采集、DeepSeek请求、建表或分类CLI。

## 原项目参考

- [WWH分析程序](../../../WWH/5/src/wwh5/analysis.py)
- [WWH参数](../../../WWH/5/src/wwh5/params.py)
- [WWH表结构](../../../WWH/5/schema.sql)
- [WWH模型契约](../../../WWH/5/docs/api-contract.md)
- [WWH提示词说明](../../../WWH/5/docs/指令文档.md)
- [WWH实验记录](../../../WWH/5/docs/experiments.md)

本模块是三图基线复现；后续 [data_plan.md](../../docs/data_plan.md) 的三节点指标、时长、价格、口碑等专题在此基础上另行推进。

## T0Pre迁移核验

2026-10-16迁移后已从LYX目录重跑highest，从T0Pre目录重跑start。两种模式的全部统计指标均与迁移前一致；默认三张PNG与报告文件字节一致，数据库SHA256不变。T1Core、T2Depth、T3Sum保持原样。

迁移清单和完整检查结果位于 [runtime/migration_verification.json](runtime/migration_verification.json)。
