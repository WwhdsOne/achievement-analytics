# 推荐服务独立部署

在本机仓库根目录运行，不需要先把仓库 clone 到服务器：

```bash
bash result/ZZY/deploy.sh --prepare-only  # 仅本机打包检查，不连服务器/数据库
bash result/ZZY/deploy.sh                 # 单独部署推荐服务
bash result/ZZY/deploy.sh --refresh-data  # 只有需要更新数据时才显式刷新
bash dashboard/deploy.sh                  # 单独部署 Go 面板
```

两份脚本默认读取同一份 `dashboard/.env`，不会改写这份文件。示例见 `dashboard/.env.example`，已有配置只需补充推荐地址和端口，不能直接用示例覆盖凭据。

```dotenv
RECOMMENDATION_HOST=127.0.0.1
RECOMMENDATION_PORT=8605
```

默认推荐服务与面板部署到同一台服务器，推荐容器只监听127.0.0.1，面板通过 host 网络访问，无需对公网开放8605。Go优先使用显式 `--recommendation-url`，否则读取环境变量/面板 `.env` 的 HOST/PORT；缺失时默认127.0.0.1:8605。修改地址后重新部署或重启面板使配置生效，修改服务端口时还需重部署推荐服务。

部署脚本沿用 `.env` 的 `DEPLOY_HOST/USER/PASSWORD` 及 `POSTGRES_*`。推荐服务独立目录默认 `/opt/achievement-recommendation`，可通过 `RECOMMENDATION_DEPLOY_PATH` 修改，禁止与面板目录相同。SSH、RAWG、Steam密钥不上传。DeepSeek的API key、模型和地址默认从本机 `result/WWH/5/.env` 读取，仅注入推荐容器的运行环境，不输出明文或打进镜像；可用 `RECOMMENDATION_DEEPSEEK_ENV_FILE` 指定其他现有配置，显式环境变量优先。源码和依赖按白名单打包，不传个人报告或虚拟环境。

## 启动和更新

服务器需要已安装 Docker 和 Docker Compose ≥2.30（支持raw环境文件），能拉取基础镜像及Python依赖；本机需要uv、SSH/SCP和expect。独立依赖项目位于本目录 `pyproject.toml` / `uv.lock`，仅包含推荐路径需要的httpx、numpy、psycopg、python-dotenv、SQLAlchemy；不会安装整套建模/绘图库，也不会改变仓库根依赖。

脚本只更新推荐容器，不重启面板。服务器目录的 `./runtime` 绑定到容器 `/runtime`，即默认的 `/opt/achievement-recommendation/runtime`。首次为空时只读抽取共享库、生成快照与图谱；之后部署、重建容器和重启都保留并复用该目录，仅完整核验和建立内存索引，不重新读库或生成数据。缓存损坏时明确失败，不静默换数据版本。查询期间不连库。

只有 `--refresh-data` 才运行一次独立的数据刷新任务，成功后重新创建服务容器；普通部署也重建容器，但继续使用原持久化版本。默认最多等待900秒就绪，可用 `--health-timeout 1800` 延长。CPU限制为1核。部署不执行db init、worker或训练。

在服务器的推荐部署目录下管理：

```bash
docker compose ps
docker compose logs --tail 50 recommendation
docker compose restart recommendation
docker compose down
```

健康检查直接调用本容器的 `/api/meta`，只在输入和图谱准备完成后成功。部署输出中的“成功”以此为准。若等待失败，先看日志，不需重新采集数据。部署包及配置位于忽略的 `result/ZZY/build/deploy/`，其中包含数据库凭据和配置的DeepSeek密钥，请勿分享或提交。

## 推荐服务使用另一台机器

仍在 `dashboard/.env` 配置客户端目标与独立服务端监听/部署目标：

```dotenv
RECOMMENDATION_HOST=推荐机器的私网IPv4
RECOMMENDATION_PORT=8605
RECOMMENDATION_BIND_HOST=推荐机器的私网IPv4
RECOMMENDATION_DEPLOY_HOST=推荐机器的SSH地址
# 账号不同时另填 RECOMMENDATION_DEPLOY_USER / RECOMMENDATION_DEPLOY_PASSWORD
```

此时 `POSTGRES_HOST` 必须是推荐机器可访问的数据库地址。当前两份脚本共用 `dashboard/.env` 的数据库设置；若两机所需配置不同，使用 `--env-file` 指向一份独立的推荐部署配置。访问目标、监听地址、SSH地址各自按配置使用，脚本不自动改写。跨机链路需已经可达，推荐服务没有用户登录认证，使用私网转发。

参考：[uv Docker集成](https://docs.astral.sh/uv/guides/integration/docker/)、[Compose环境文件格式](https://docs.docker.com/reference/compose-file/services/#format)。生成的 `.env` 只含监听地址与端口，含数据库密码的 `runtime.env` 用raw格式，避免 `$`、引号和反斜杠被二次解析；二者均不进入镜像。
