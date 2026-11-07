# 第 6 项：游戏口碑预测与关联因素

用现有标签和商店属性预测当前 Steam 好评率，不额外抓取数据。结果见 [实验记录](experiments.md)，方案见 [plan.md](plan.md)。

## 运行

在仓库根目录，先按项目规范拉取最新代码。使用已有 uv 环境，无新增依赖：

```bash
git pull origin main
uv run python result/WWH/6/run.py
```

默认执行：只读提取云库固定快照 → 登记 `dataset_versions` → 训练和评价。除登记版本外，不写数据库，不运行 DDL，不花 RAWG 配额。原始提取、模型与逐款预测均在被 Git 忽略的 `data/processed/wwh6/`。

完全离线重放本次固定快照（需要本机已有该文件）：

```bash
uv run python result/WWH/6/run.py --snapshot data/processed/wwh6/reputation-20261022-44cf2a8877ca.snapshot.json
```

用保存的模型预测《都市：天际线2》，不重新训练：

```bash
uv run python result/WWH/6/run.py --snapshot data/processed/wwh6/reputation-20261022-44cf2a8877ca.snapshot.json --predict-appid 949230
```

默认使用随机划分的标签＋属性 Ridge，可加 `--model attributes_trees` 或 `--split release_cohort`。输出会说明该游戏属于训练集、留出集还是被排除样本，避免把训练内拟合当泛化结果。只能预测快照中已有属性的游戏，不会自动抓取新游戏。模型 joblib 只加载本地本实验产物。

## 输入与目标

- 目标：SteamSpy `positive / (positive + negative) × 100`，每款游戏等权；不是 RAWG 评分，不是销量或热度。
- 样本：评价≥100、2026年前发售、官方类型为 game、有正票数的 SteamSpy 用户标签；排除未解决成就映射问题。发售日优先 appdetails，缺失时用 store_search。
- 标签：票数最高的前20个，二值编码；相同票数按标签排序。不输入标签票数，不输入评价数。
- 额外属性：发售年份、免费状态、官方类型、官方功能分类、开发商、发行商。分类缺失有独立指示；低频类别不进入词表。
- 价格：当前采集未保留币种，且请求未固定地区，主实验不使用。
- 不输入其他评分、正/负评价数、评价等级、推荐人数、在线人数、成就完成率和游玩时长。

## 实验口径

两种对照为训练集平均好评率和中位数好评率。三种模型为标签 Ridge、标签＋属性 Ridge、标签＋属性 ExtraTrees。所有预测截断至0—100。

两种外部划分都固定后再训练：规范化标题分组随机留出20%；发售年代留出以2023—2025为测试集、≤2022为训练集，剔除跨组同标题。Ridge alpha 从1、10、100中用训练集内部另一次标题分组留出选择。类别出现门槛为训练集至少10款，词表不接触验证/测试样本。ExtraTrees为200棵树、叶节点至少5款、最大深度24、max_features=0.7、两个线程，未搜索参数。随机种子42。

主指标 MAE，单位为百分点，同时报告 RMSE 和 R²。评价≥1000和训练中未见开发商的子集只做诊断，不据此重新调参。

当前标签和属性都形成于发售后，不能将这项实验称为上市前预测或真正的未来回测。规范化标题不能识别所有系列、重制版与不同命名版本；开发商跨集合仍可能重合。门槛筛选使结果不代表全部 Steam 游戏，用户标签也可能包含评价性描述。

## 产物

固定快照 SHA256 在加载时校验。版本目录含 `metrics.json`、两份 `*-predictions.csv` 和每种划分的五份 `*.joblib`。逐款 CSV 均为对应划分的留出预测，便于复核误差案例；不会在仓库提交原始数据或模型二进制。
