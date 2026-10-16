# 北京交通大学 软件工程 数据科学小组作业

> 组长：王文海
> 组员：刘宇翔、杨金辉、耶美田、朱政宇

# achievement-analytics

> Steam 成就数据分析：分析用户和玩家更愿意玩什么样的游戏

数据都在共享的 PostgreSQL 里（`crawler/` + `cleaning/` 是采集管道，采集已完成）。
每人从 `docs/plan.md` 的方向里认领一个，产物放自己的 `result/<缩写>/`。

## 分工

| 谁 | 方向（见 `docs/plan.md`） | 产物 |
|---|---|---|
| LYX | 主线进度漏斗与成就参与分析 | `result/LYX/`（规划中） |
| YJH | 按发售年份的游戏类型演变 | `result/YJH/`（已交付） |
| WWH | 分类完成曲线与 RAWG 对比<br>游戏口碑预测与关联因素分析 | `result/WWH/5/`（已交付） |
| YMT | 游戏画像聚类与自动分型 | — |
| ZZY | 游戏知识图谱与可解释推荐 | — |

## 状态面板

dashboard已部署，需要网址请发issue提醒我。

Go 后端 + 前端打进同一个二进制，镜像 16MB、容器内存约 6MB。`dashboard/` 是自包含的：
`go.mod`、`.env`、`Dockerfile`、`docker-compose.yml`、`deploy.sh` 都在这个目录里。

```bash
bash dashboard/deploy.sh                                            # 部署到服务器

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
