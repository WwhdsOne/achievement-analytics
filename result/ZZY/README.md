# 朱政宇（ZZY）：游戏知识图谱与可解释推荐

搜索游戏，选择1–3款作为种子，按年份筛选推荐，并查看每条推荐的关系贡献与事实来源。四个页面由同一条启动命令提供，导航不依赖其他端口。默认启动时从小组 PostgreSQL **只读加载一次**，自动生成本机图谱缓存；重启更新数据。正常运行不需要手动接收数据包。

## 在哪里查看知识图谱和推荐解释


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


