# 手动训练指南

> 更新：2026-10-02。面向第一次运行本项目模型的同学。
> 当前阶段：数据获取已完成，正在做游戏级回归分析与模型归因。
> 本文描述已实现的代码；当前模型为均值参照、Ridge 和随机森林，IRT 子包仍是占位。

## 1. 哪些文件负责训练？

| 文件 | 负责什么 | 你什么时候需要看它 |
|---|---|---|
| `modeling/regression/analysis.py` | 训练入口、特征工程、样本筛选、五折评估、跨年代测试、SHAP、报告生成 | 运行训练或修改模型参数 |
| `modeling/regression/dataset.py` | 从PostgreSQL提取聚合数据、计算目标、保存固定快照、加载快照并校验指纹 | 修改数据口径、目标公式或文本关键词 |
| `modeling/experiments.md` | 人工记录数据版本、参数、指标和结论 | 每完成一次实验 |
| `dashboard/app.py` | 启动面板，通过 `/api/analysis` 读取已有报告 | 查看结果，不负责训练 |
| `dashboard/analysis.js` | 把报告渲染成表格、图表和结论 | 修改展示方式或同步页面方法说明 |
| `tests/test_analysis.py` | 检查比例计算、缺失值、特征和JSON输出等契约 | 修改分析代码后检查 |

不直接运行 `dataset.py`、`crawler/` 或 `cleaning.worker` 来训练。训练命令不会请求Steam/RAWG接口，不消耗抓取配额。

`analysis.py` 中几个关键函数：

| 函数 | 小白版说明 |
|---|---|
| `main()` | 接收命令行参数，选数据，执行分析，写报告 |
| `build_report()` | 安排三种目标的实验，以及类型对照和稳健性分析 |
| `valid_sample()` | 根据目标、评价数、状态人数等规则挑选可用游戏 |
| `feature_matrix()` | 把游戏资料变成模型能读取的数字表 |
| `ridge_pipeline()` | 创建“填补缺失 → 标准化 → Ridge”的模型流程 |
| `score_cv()` | 真正调用 `.fit()` 训练，每一折用没参与训练的游戏测试 |
| `model_experiment()` | 用相同五折比较七种模型/特征配置，再计算SHAP和跨年代分数 |

## 2. 最快的重跑方法：使用首轮固定数据

所有命令在项目根目录执行：

```bash
cd /Users/Learning/course/achievement-analytics
uv sync
uv run python -m modeling.regression.analysis --version engagement-20261001-079598c5d7ae
```

第三条命令会重新训练和评估全部三个目标，不只是弃坑占比。它还会重算类型对照、门槛敏感性、SHAP和报告。

使用 `--version` 时不查询云库，也不登记新版本，但本机必须存在这两个文件：

```text
data/processed/snapshots/engagement-20261001-079598c5d7ae.json.gz
data/processed/snapshots/engagement-20261001-079598c5d7ae.json.metadata.json
```

前者是固定的游戏级建模输入，后者包含版本、指纹、抓取时间信息和描述核验样本。两者都不入Git；只克隆仓库不会得到它们。

正常情况下会看到类似输出：

```text
固定数据版本: engagement-20261001-079598c5d7ae (50922款)
建模 drop_ratio: 3390 款
建模 log_hours: 11007 款
建模 approval: 14654 款
报告已生成: .../data/processed/analysis-report.json
```

这些样本数对应首轮版本和默认筛选条件。改变数据或筛选后，不保证仍是这些数字。CPU训练即可，无需GPU；随机森林使用 `n_jobs=-1`，会使用多个CPU核心。耗时取决于机器。

## 3. 新机器首次训练，或使用云库最新数据

没有固定快照时，先配置已有的 `.env` 中 `POSTGRES_*` 连接参数。本项目端口是15432，自建库不要求SSL。训练不需要Steam或RAWG API key。

```bash
uv sync
uv run python -m cleaning.db status
uv run python -m modeling.regression.analysis
```

不传 `--version` 的过程是：

```text
云库一致性读取 → 游戏级聚合与目标计算 → 固定快照与SHA256指纹
→ 登记dataset_versions → 三种目标训练与评估 → 派生报告
```

数据提取使用只读 repeatable-read 事务，之后在已有 `dataset_versions` 表插入版本登记，不建表、不改表、不重抓。数据库需已初始化，无需为训练运行 `cleaning.db init`。

注意两个区别：

- **数据版本不是实验编号**：同一份快照可以尝试不同模型参数；仅修改模型参数不会得到新的数据指纹。
- **当前版本名前缀固定为 `engagement-20261001-`**：后面的指纹取决于输入内容，真实提取时间看元数据的 `built_at`，不要把前缀当成每次训练日期。

云库原始记录仍是唯一事实源；processed快照用于复现实验，是固定建模输入，不是抓取缓存。

## 4. 当前训练什么？

| 目标代码 | 实际含义 | 当前有效样本条件 |
|---|---|---|
| `drop_ratio` | `dropped / (beaten + dropped)`，通关或弃坑标记者中的弃坑占比 | 至少5个成就、100条SteamSpy评价、20个通关/弃坑标记，目标非缺失 |
| `log_hours` | `log1p(playtime)`，RAWG时长的对数变换 | 至少5个成就、100条SteamSpy评价，时长为正 |
| `approval` | `positive / (positive + negative)`，Steam好评占比 | 至少5个成就、100条SteamSpy评价，目标非缺失 |

`log1p(h)` 就是自然对数 `ln(1+h)`；时长目标的RMSE不是小时单位。状态计数缺失不补零，零分母不计算比例。

每个目标分别比較均值baseline、元数据Ridge、整体稀有度Ridge、尾部结构Ridge、文本规则Ridge、标签交互Ridge、随机森林。它们使用同一目标样本和同一随机五折，比较多提供某组特征是否有帮助。

数据划分和预处理规则：

- 随机五折：`KFold(n_splits=5, shuffle=True, random_state=42)`；每折重新训练。OOF指标汇总每款游戏未参与对应模型训练时的预测。
- 缺失填补和标准化只在训练折拟合。Ridge默认alpha=10；随机森林默认160棵树、最大深度9、最小叶节点15。
- 跨发售年代测试：≤2022年训练、2023–2025年测试，比较均值baseline、尾部结构Ridge和随机森林。并未对每一种扩展模型都执行跨年代测试。
- SHAP只解释最后一折随机森林在最多300款留出游戏上的预测；不是最高分Ridge的解释，也不是五折贡献的平均。
- 好评目标不使用“评价数”作为解释特征。不要将目标或可直接重建目标的字段加入输入。

## 5. 训练完成后怎么查看？

输出文件固定为：

```text
data/processed/analysis-report.json
```

它包含数据版本、参数、各模型R²/RMSE、各折表现、跨年代指标、SHAP贡献和其他页面数据。完整运行成功后原子替换该文件；运行失败时旧的已完成报告通常仍保留，因此要查看版本及生成时间，不能把旧报告当成新实验。

启动dashboard：

```bash
uv run python -m dashboard.app --port 8601
```

打开：

- 分析总览：`http://127.0.0.1:8601/#analysis/overview`
- 模型归因：`http://127.0.0.1:8601/#analysis/models`

若面板已经在运行，训练后刷新整个浏览器页面即可读取新报告，通常不必重启服务。只切换主题导航不会强制重新读取报告。端口被占用时换一个端口，并同步修改访问地址。

**当前没有保存 `.pkl` / `.joblib` 模型，也没有对新游戏提供预测接口。**这是一套“重复训练 → 评估 → 解释 → 报告”的实验流程。`score_cv()` 返回的模型只对应最后一折，不是使用所有游戏训练的最终部署模型。报告JSON不能代替模型权重。

## 6. 想改参数，去哪里改？

目前CLI只支持 `--version` 和 `--help`；没有 `--alpha`、`--target`、`--trees` 等参数。完整dashboard流程的参数需要在代码里修改。

| 想改变什么 | 修改位置 | 同步事项 |
|---|---|---|
| Ridge正则强度 | `analysis.py` 的 `ridge_pipeline()`：`Ridge(alpha=10)` | 同步 `build_report()` 的参数记录与dashboard方法说明 |
| 树数量、深度、叶节点最小样本 | `model_experiment()` 的 `RandomForestRegressor(...)` | 同步 `build_report()` 的森林参数记录与dashboard说明 |
| 特征列或标签组合 | `feature_matrix()`、`GENRES`、`TAGS`、`STRUCTURE` | 核实实际标签词形；记录各模型究竟使用哪些特征 |
| 主线样本门槛 | `valid_sample()` 的默认参数和成就数量条件 | 同步敏感性设置、参数记录、自动结论和页面口径文字 |
| 五折划分 | `score_cv()` 中的 `KFold(...)` | 同步参数记录与页面说明；保留random_state=42 |
| 跨年代划分 | `model_experiment()` 的 `train_mask` / `test_mask` | 同步参数记录与页面文字 |
| 目标公式 | `dataset.py` 的 `derive_metrics()` | 固定快照已包含算好的目标，需要重新派生输入 |
| 文本关键词 | `dataset.py` 的 `TEXT_RULES` 与提取SQL | 固定快照已包含旧规则匹配占比，需要重新提取输入 |

改模型参数/数字特征变换时，可以复用同一固定快照；改目标公式、SQL聚合或文本规则后，只使用 `--version` 不会自动重算已经冻结的列。

首次学习建议只调整一个参数，例如alpha从10改为30，保留同一数据版本与划分，比较R²/RMSE。不要同时换数据、筛选门槛和模型参数，否则无法判断变化来自哪里。

## 7. 只想练习训练一个Ridge，暂时不更新dashboard

下面是独立小实验：用同一快照和全部基础特征预测弃坑占比，alpha=30，执行五折评估，写到独立的实验文件。**这段不会覆盖dashboard报告，也不会计算随机森林SHAP。**

```bash
uv run python - <<'PY'
from pathlib import Path
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from modeling.regression.dataset import load_snapshot
from modeling.regression.analysis import valid_sample, feature_matrix, score_cv, strict_json

frame, metadata = load_snapshot("engagement-20261001-079598c5d7ae")
sample = valid_sample(frame, "drop_ratio")
matrix = feature_matrix(sample)
estimator = make_pipeline(
    SimpleImputer(strategy="median", keep_empty_features=True),
    StandardScaler(),
    Ridge(alpha=30),
)
scores, last_fold_model, last_fold_test = score_cv(matrix, sample["drop_ratio"], estimator)
result = {
    "version": metadata["version"],
    "target": "drop_ratio",
    "features": list(matrix.columns),
    "parameters": {"alpha": 30, "folds": 5, "random_state": 42},
    "metrics": scores,
}
output = Path("data/processed/experiments/drop-ridge-alpha30.json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(strict_json(result), encoding="utf-8")
print("R²:", scores["r2"], "RMSE:", scores["rmse"])
print("实验结果:", output)
PY
```

这个实验与首轮“尾部结构Ridge”使用相同基础特征、目标门槛和五折方式，可作alpha对照。不要把它的输出文件改成 `analysis-report.json`：简化实验的JSON结构不满足dashboard整份报告的契约。

## 8. 每次实验如何记录和验证？

在 `modeling/experiments.md` 追加一条记录，包含日期、数据版本、目标/样本数、特征、参数、R²/RMSE，以及与原配置的差异。脚本不会自动替你追加该Markdown日志，也不会自动保留历史dashboard报告。

若需要保留上一轮报告，可在重跑前执行：

```bash
uv run python -c 'from pathlib import Path; import shutil; folder=Path("data/processed/experiments"); folder.mkdir(parents=True, exist_ok=True); shutil.copy2("data/processed/analysis-report.json", folder / "report-before-alpha30.json")'
```

改代码后的检查：

```bash
uv run python -m pytest tests/test_analysis.py tests/test_dashboard_analysis.py -q
uv run python -m pytest -q
```

关键结果不只看最高R²，还要看误差、各折变化、跨年代结果和有效样本。用测试分数反复挑参数会产生选择偏差；需要正式调参时，应另设验证流程。SHAP仍然是模型归因，不是因果效应。

## 9. 常见问题

| 情况 | 处理方法 |
|---|---|
| `--version` 报文件不存在 | 当前机器没有对应快照或元数据文件；核对 `data/processed/snapshots/`。新机器可不传版本，从云库生成自己的快照；要复现旧版，须取得匹配的两个旧文件 |
| 提示数据快照指纹不一致 | 快照内容与元数据SHA256不符，核对是否使用了匹配的一组文件，不删除校验来继续训练 |
| 数据库连接失败 | 首次提取需要有效 `.env`，核对15432端口及SSL配置；本机已有完整快照时可用 `--version` 离线重跑 |
| `ModuleNotFoundError` | 在项目根目录执行 `uv sync`，并使用 `uv run python ...`；测试用 `python -m pytest`，避免落到全局pytest |
| dashboard仍显示旧结果 | 确认训练已成功结束，检查报告生成时间，再完整刷新页面 |
| 修改alpha后说明仍写10 | 训练代码、报告参数字典和页面方法说明目前有重复声明，需要同步修改；单独练习优先用第7节的小实验 |
| Ctrl-C中断训练 | 没有模型级断点续训，下次会从头重新训练；固定数据可复用，不必重新提取 |
| 想同时跑多个实验 | 完整入口共用同一报告和临时文件，按顺序运行；独立练习使用不同实验输出名 |

训练入口帮助可随时查看：

```bash
uv run python -m modeling.regression.analysis --help
```
