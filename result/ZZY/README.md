# 朱政宇（ZZY）：游戏知识图谱与可解释推荐

搜索游戏，选择1–3款作为种子，按年份筛选推荐，并查看每条推荐的关系贡献与事实来源。四个页面由同一条启动命令提供，导航不依赖其他端口。默认启动时从小组 PostgreSQL **只读加载一次**，自动生成本机图谱缓存；重启更新数据。正常运行不需要手动接收数据包。

## 运行

最新版交付包：`ZZY-site-v5.zip`，包含整合原搜索框的中文译名与简称搜索。

在小组仓库根目录使用已有 `.env` 中的 `POSTGRES_*` 配置：

```powershell
uv sync
uv run python result/ZZY/run.py serve
```

等待终端打印地址后打开 `http://127.0.0.1:8605/`。首次需要读取数据并构建图谱，不能刚启动就访问；后续启动仍读取数据库，再按内容版本复用并核验缓存。程序只执行查询，不写共享数据库。`.env` 只保留本机，不上传。

配置放在其他位置时使用 `--env-file`；不会读取当前工作目录下不明来源的 `.env`。环境变量优先于配置文件。数据库连接失败明确停止，不自动使用旧缓存。

```powershell
uv run python result/ZZY/run.py serve --env-file "C:/你的路径/achievement-analytics/.env" --port 8606
```

## 在哪里查看知识图谱和推荐解释

搜索支持中文名、常用译名和简称，例如“老头环”“空洞骑士”“星露谷”；首批本地别名表覆盖44款游戏、114个搜索词，两个原搜索入口共用，不增加单独的别名入口或提示。补充方式及本次验证见[中文别名搜索](docs/SEARCH-ALIASES.md)。更新代码后需重启服务。

启动后，以下地址共用当前服务端口，无需分别启动：

| 页面 | 地址 | 查看内容 |
|---|---|---|
| 联合推荐 | `/` | 搜索选种子，推荐结果下方的“游戏知识图谱”子图、关系贡献和双端来源 |
| 标签基线 | `/baseline/` | 只用主题标签的对照方法和标签关系图 |
| 图谱来源核查 | `/graph/` | 游戏/标签/类型/开发商/发行商实体、关系数量、覆盖缺失和原始事实回查 |
| 单游戏解释台 | `/explain/` | 单种子真实排名、共同路径、每条路径贡献、原始字段证据 |

知识图谱是全库游戏与四类实体形成的事实关系集合；页面按所选游戏展示局部关系子图。可解释推荐把实际分数分解到关系与路径，并能展开两端原始字段，不把图的布局当成评分依据。

## 成果与说明

- [专题报告](report.md)：方法、功能、历史实验结果与限制。
- [AI辅助评价对照](figures/ai-method-comparison.png)、[缺失标签上下界](figures/ai-unknown-bounds.png)。
- [桌面截图](figures/desktop-preview.png)、[手机截图](figures/mobile-preview.png)：原冻结数据演示截图。
- [运行说明](docs/RUN.md)、[数据库与缓存](docs/DATA.md)、[接口约定](docs/API.md)、[上传步骤](docs/GITHUB.md)。
- [数据库加载改造](docs/database-loading-plan.md)、[数据库验证](docs/DATABASE-VERIFICATION.md)、[导航与图谱展示验证](docs/SITE-VERIFICATION.md)、[历史迁移验证](docs/VERIFICATION.md)。

```text
result/ZZY/
  run.py                     默认数据库启动入口
  modeling/recommendation/   推荐计算模块与页面
  process/database_input.py  只读提取、自动版本缓存
  process/site_service.py    同端口四页面，共享图谱和数据
  process/                   历史AI指标复现与绘图
  reports/、figures/          已保存的来源摘要、实验结果与截图
  docs/、report.md            运行说明及专题报告
  runtime/database/          自动生成的本地快照/图谱/启动审计，不入Git
  data/、runtime/            旧离线输入及运行输出，不入Git
```

显式离线运行 `uv run python result/ZZY/run.py serve --source snapshot`，需要原冻结输入；此模式只用于历史复现。默认数据库启动不需要旧输入或数据ZIP。

当前仍是独立本地演示服务，尚未接入小组Go面板。177对外部AI评分属于原冻结数据的探索性评价，不是实时数据的新评价或独立真人效果。上传本版代码不代表统一网站集成已完成。
