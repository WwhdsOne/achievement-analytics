# 北京交通大学 软件工程 数据科学小组作业

> 组长：王文海
> 组员：刘宇翔、杨金辉、耶美田、朱政宇

# achievement-analytics

> Steam 成就数据分析：分析用户和玩家更愿意玩什么样的游戏

数据都在共享的 PostgreSQL 里（`crawler/` + `cleaning/` 是采集管道，采集已完成）。
当前目标：**分析游戏数据，包含五个方向**，产物放各自的 `result/<缩写>/`。

## 五个方向

| 方向 | 优先级 | 执行人 | 预期产出 | 进度 |
|---|---|---|---|---|
| 发售年份与潮流类型演变 | 主线 | 杨金辉 | 年度趋势与热力图 | 进行中 |
| 游戏画像聚类 | 扩展 | 耶美田 | 游戏类别与代表作品 | 进行中 |
| 可解释推荐 | 主线 | 朱政宇 | 相似游戏与推荐理由 | 进行中 |
| 实际完成曲线与游戏用户粘性分析 | 主线 | 王文海、刘宇翔 | 关键主线节点完成率、内容分类与跨平台对照 | 进行中 |
| 游戏口碑预测与关联因素 | 扩展 | 王文海 | 预测评估与相关因素 | 进行中 |

产物与实验记录放各自的 `result/<缩写>/`（YJH / YMT / ZZY / WWH / LYX）。

## 部署

服务都跑在腾讯云那台机器上，**在本机执行**，服务器不需要仓库：

```bash
bash dashboard/deploy.sh      # 状态面板（Go 只读，含推荐服务连接配置）
bash result/ZZY/deploy.sh     # 可解释推荐服务（Python，独立包与数据卷）

bash result/ZZY/deploy.sh --prepare-only   # 只在本机打包检查，不连服务器/数据库
bash result/ZZY/deploy.sh --refresh-data   # 仅需要更新推荐服务数据时显式刷新
```

两份脚本默认读同一份 `dashboard/.env`（不入 git），凭据不出本机。
完整用法与环境变量见 [`docs/commands.md`](docs/commands.md) §9、§10。

## 状态面板

面板已部署，需要网址请发 issue 提醒我。

Go 后端 + 前端打进同一个二进制，镜像 16MB、容器内存约 6MB。`dashboard/` 是自包含的：
`go.mod`、`.env`、`Dockerfile`、`docker-compose.yml`、`deploy.sh` 都在这个目录里。

```bash
# 本机预览：dashboard/.env 里的 POSTGRES_HOST 是给容器用的 127.0.0.1，
# 本机要临时覆盖成公网地址（环境变量优先于 .env）
cd dashboard && POSTGRES_HOST=82.157.208.173 go run . --port 8601
```

## 常用命令

```bash
uv sync                                              # Python 3.13 + uv
cp .env.example .env                                 # 数据库与 key，问组长王文海要
uv run python -m cleaning.worker --appid <id>        # 单款游戏补数据
```

## 目录

```
crawler/ · cleaning/   采集管道（采集已完成，补数据仍走这里）
dashboard/             状态面板（自包含 Go 模块）
docs/                  plan.md 选题方向 · commands.md 命令手册 · experiments.md 面板实验记录
result/<缩写>/         每人的产物与实验记录
scripts/               浏览器验收脚本
```

数据口径与协作规范见 `AGENTS.md`；各方向的具体做法见 `docs/plan.md`。

## 许可与使用

本项目采用 **PolyForm Noncommercial License 1.0.0**（全文见 [`LICENSE`](LICENSE)）。
**商业用途需事先取得书面授权。**

- **非商业用途自由使用**：学习、研究、实验、个人项目，以及教育机构、公益组织、公共研究
  机构等主体的使用，都无需申请
- **商业用途**：需事先取得授权，请通过仓库 Issue 或仓库维护者
  （<https://github.com/WwhdsOne>）联系
- 版权为五位作者共有（王文海、刘宇翔、杨金辉、耶美田、朱政宇），**商业授权需全体同意**

两点必须说明：

1. 该许可属于 **source-available（源码可得）**，**不是 OSI 意义上的开源许可**——它限制了
   使用领域（禁止商用），因此不满足开源定义。引用时请勿称本项目为「开源项目」
2. **许可只覆盖本仓库的代码与文档，不覆盖第三方数据**。Steam / SteamSpy / RAWG / PlayMyData
   各有各的条款，其中 **RAWG 免费档本身就禁止商业用途**，且要求使用其数据的页面加 RAWG 回链。
   也就是说：即使拿到本项目的商业授权，使用这些数据仍受各自条款约束
