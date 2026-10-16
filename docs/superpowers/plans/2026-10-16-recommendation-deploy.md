# 推荐服务独立部署

目标：`bash result/ZZY/deploy.sh` 单独打包、上传和启动推荐服务；Go 面板通过 `dashboard/.env` 的 `RECOMMENDATION_HOST` / `RECOMMENDATION_PORT` 连接。

架构：独立 Docker Compose 项目及持久化 runtime，默认 host 网络+127.0.0.1:8605。共享现有 dashboard 部署凭据与数据库配置，上传配置严格限定数据库与推荐运行参数。只读加载和图谱准备仍由推荐服务启动完成，不执行 DDL、worker 或模型训练。Go 镜像保持纯 Go。

- [x] Go：CLI URL 显式覆盖优先，其次环境变量/面板 `.env`，再用默认127.0.0.1:8605；校验 host/port，IPv6正确拼接。
- [x] dashboard：示例配置与当前忽略的 `.env` 增加连接参数，原部署脚本白名单携带这两个参数。
- [x] ZZY：独立 deploy.sh、打包上传程序、Dockerfile、compose、健康检查和最小 pyproject/uv.lock；`--prepare-only` 不连接远程。
- [x] 验证：真实生成部署包，检查成员与凭据边界，最小依赖环境和本机Docker镜像启动真实服务；Go构建与配置优先级、shell/compose静态检查通过。
- [x] 用户追加：服务器宿主目录 runtime 绑定 `/runtime`，首次生成，普通部署/重启复用，只有 `--refresh-data` 显式更新；DeepSeek配置从 WWH/5/.env 读取，仅注入推荐容器。
- [x] 验证缓存复用：在容器内将数据库地址改为不可用的127.0.0.1，重新创建容器，元数据返回 persistent_cache、database_access=false、cache_reused=true，真实推荐成功，DeepSeek configured=true；未调用付费模型。
- [x] 用户放行SSH22后，推荐服务与Go面板已实际部署到腾讯云。服务器首次生成后执行受控重启，缓存指针SHA256未变化，API确认cache_reused=true、database_access=false、DeepSeek configured=true，并返回真实推荐。
- [x] 公网浏览器验收：五导航、四张内嵌图、真实推荐、探索封面、桌面/手机无溢出及无脚本错误；仅6个页面API请求，避免触发限流。公开响应不含密钥。未提交。
