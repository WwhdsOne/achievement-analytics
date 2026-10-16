# 研究成果接入

入口：`/#research/recommendation`。顶部「研究成果」内含五方向导航：

页面顶部保留「游戏探索」「数据全景」「队列总览」直达链接。推荐与搜索结果使用 Steam 游戏封面，封面可点击进入原 dashboard 的单款详情；推荐卡片另有 Steam 商店链接。封面不可用时保留游戏名占位。

「成果图示」展示 ZZY 原交付的图谱、路径来源截图和两张 AI 辅助评价图，可新标签页打开原图。图示基于2026-10-14历史冻结成果，独立标注日期、评价分母与局限，不随交互推荐刷新。图片复制自 `result/ZZY/figures/` 到 `dashboard/figures/zzy/` 并嵌入 Go 二进制，部署不依赖个人目录或运行中的推荐服务。仅游戏封面需要联网访问 Steam CDN。

| 方向 | 负责人 | 当前页面 |
|---|---|---|
| 发售年份与潮流类型演变 | 杨金辉 | 年度趋势与热力图，待接入 |
| 游戏画像聚类 | 耶美田 | 游戏类别与代表作品，待接入 |
| 可解释推荐 | 朱政宇 | 搜索、组合推荐、年份筛选、贡献与事实来源 |
| 实际完成曲线与游戏用户粘性分析 | 王文海、刘宇翔 | 主线节点、内容分类、跨平台对照，待接入 |
| 游戏口碑预测与关联因素 | 王文海 | 预测评估与相关因素，待接入 |

## 本机运行

在仓库根目录启动推荐服务，等待终端提示服务已启动：

```bash
uv run python result/ZZY/dashboard_service.py
```

缓存保存在已忽略的 `result/ZZY/runtime/dashboard/`。首次为空时使用仓库根 `.env` 在只读一致性事务中加载共享 PostgreSQL，生成快照与图谱并释放数据库连接；后续启动直接核验和加载持久化版本，不重复读库或生成。需要更新数据时显式加 `--refresh-data`，可用 `--env-file` 指定已有数据库配置。查询期间不访问数据库。

另一个终端启动面板：

```bash
cd dashboard
POSTGRES_HOST=82.157.208.173 go run . --port 8601
```

打开 `http://127.0.0.1:8601/#research/recommendation`。在 `dashboard/.env` 设置 `RECOMMENDATION_HOST=127.0.0.1` 和 `RECOMMENDATION_PORT=8605` 指定上游。环境变量优先于文件，显式 `--recommendation-url http://内网地址:端口` 优先于两者；缺失时默认同机8605。推荐服务默认只绑定循环地址，跨机器时配置其 `--host` 或部署配置中的 `RECOMMENDATION_BIND_HOST` 为可达私网IPv4。

## 运行边界

Go 只代理三个 GET 接口：`/api/research/recommendation/meta`、`search`、`recommend`。响应保留原算法排名、解释、数据与算法版本。点评 POST 不在本次接入范围；原补抓 POST 仍返回 404。服务未启动或失联时，成果页显示提示并支持重试，其他面板功能照常工作。

集成入口 `dashboard_service.py` 使用当前源码生成的图谱绑定与完整校验；原 `run.py` 还会检查交付包 `reports/source-map.json` 的文件字节摘要。交付文件格式变化会使原入口拒绝运行，不能把旧交付摘要视为当前集成版本的校验结果。本次没有改写交付包摘要或推荐算法。

生产环境仍使用纯 Go / scratch 面板镜像。`bash result/ZZY/deploy.sh` 单独部署推荐容器，`bash dashboard/deploy.sh` 单独部署面板。两者读取 `dashboard/.env`，面板只接收 POSTGRES_* 与推荐连接 HOST/PORT；推荐容器另从本机 `result/WWH/5/.env` 接收DeepSeek配置，SSH凭据留在本机。服务器 `/opt/achievement-recommendation/runtime` 绑定到容器 `/runtime`，普通部署与重启直接复用；仅 `bash result/ZZY/deploy.sh --refresh-data` 显式更新数据。详细配置与仅打包模式见 [推荐部署说明](../result/ZZY/deploy/README.md)。

## 验收

2026-10-16 已部署到 `http://82.157.208.173:8600/#research/recommendation`。服务器受控重启确认缓存指针不变且不重新读库，推荐与面板健康检查通过；公网桌面/手机的导航、图示、封面与真实推荐验收通过。推荐上游仅监听服务器127.0.0.1:8605。

```bash
uv run --with playwright python scripts/check_research_browser.py --url http://127.0.0.1:8601
```

使用真实推荐数据，检查五方向、桌面/手机、单款原排名、组合和年份筛选、路径来源、空结果、错误重试与路由恢复。截图默认写 `/tmp/achievement-research/`，不入仓库。
