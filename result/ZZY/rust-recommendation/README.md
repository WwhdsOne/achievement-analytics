# 独立 Rust 推荐服务

原 Python 服务与部署脚本保留。Rust 默认监听 `127.0.0.1:8606`，部署目录为
`/opt/achievement-recommendation-rust`；原 Python `8605` 与它的缓存不受影响。
运行时只读 SQLite，既不连接 PostgreSQL，也不接收 AI、数据库或 SSH 凭据。

```bash
# 仅校验源码白名单并打包；不读凭据、不连接服务器
bash result/ZZY/rust-recommendation/deploy.sh --prepare-only

# 本机额外构建 linux/amd64 镜像，供检查；仍不连接服务器
bash result/ZZY/rust-recommendation/deploy.sh --prepare-only --build-image

# 真正部署：镜像在本机编译和导出，数据在本机导入成 SQLite 后一并上传
bash result/ZZY/rust-recommendation/deploy.sh --generate-data

# 数据已在本机生成时，显式指定该文件部署（远端同版本已验证则跳过数据上传）
bash result/ZZY/rust-recommendation/deploy.sh --data-file /路径/recommendation.sqlite
```

本机需要 uv；构建镜像需要 Docker（支持 `--platform linux/amd64`）；部署需要
Expect。服务器只需 Docker Compose、shell、tar、gzip、sha256sum 等常规工具，
不编译源码，不安装 Python/Rust。构建使用 `rust:1.95-alpine` 与锁定 Cargo 依赖，
运行镜像 `FROM scratch`。首次本机构建会下载工具链与依赖。

构建上下文等价于 `result/ZZY`，只白名单复制 `rust-recommendation/{Cargo.toml,
Cargo.lock,src}` 与 `modeling/recommendation/{game_aliases.json,display_names_zh.json}`。
Dockerfile 和忽略规则也会复制到独立上下文。`build/deploy/source.tar.gz` 可供审阅；
`upload.tar.gz` 只含 Compose、镜像标识、非敏感 `release.env` 及可选已构建镜像。
`release.env` 固定本次镜像、端口、地址参数，不含任何凭据。代码包不含 `.env`、
Python 缓存、SQLite 或原始数据；数据单独打包上传。

部署只读本机 `dashboard/.env` 的 `DEPLOY_HOST/USER/PASSWORD` 作为 SSH 登录配置，
不会上传这份文件。可用同名 `RUST_RECOMMENDATION_DEPLOY_*` 环境变量覆盖登录配置，
`RUST_RECOMMENDATION_DEPLOY_PATH` 指定独立目录。`--local-cache` 指定本机用于
导入的 Python 缓存目录（默认 `result/ZZY/runtime/database`）。
不会写入原 Python 部署目录或缓存。

数据一律在本机生成：部署时传 `--generate-data`（用刚构建的镜像从本机
`result/ZZY/runtime/database` 缓存导入出 `build/deploy/recommendation.sqlite` 再上传），
或显式 `--data-file` 指定已生成的 SQLite；服务器不做任何导入或生成。按数据库真实
SHA256 命名版本，校验后才原子切换 `data/current`；同版本已存在且校验通过则零数据上传。
旧数据版本、旧镜像保留，不自动清理；服务器备份应覆盖 `data/`。

容器只读根目录；`data/` 只读挂载，不设 CPU/内存限制。
SQLite page cache 为 8MiB，临时排序使用 `scratch/` 磁盘挂载到 `/tmp`，不使用 tmpfs。
启动会校验完整文件 SHA256 与 SQLite quick_check，启动验收可能需要几分钟。

验证成功后，手工将现有 `dashboard/.env` 的 `RECOMMENDATION_PORT` 改为 `8606`，
再单独部署面板；本脚本不会改写它。也可先用面板启动参数
`--recommendation-url http://127.0.0.1:8606` 本机比较。

默认并存便于验收。面板切换成功后，如需释放原 Python 的常驻内存，可在原 Python
部署目录运行 `docker compose stop recommendation`；代码、镜像与缓存保留，恢复时
运行 `docker compose start recommendation` 并将面板切回 8605。本脚本不会自动停止原服务。

服务器手工查看状态、日志和重启都显式读取本次非敏感参数，避免默认镜像名不同：

```bash
cd /opt/achievement-recommendation-rust
docker compose --env-file release.env ps
docker compose --env-file release.env logs --tail 40 recommendation-rust
docker compose --env-file release.env up -d
```

回滚前保留当前 `release.env` 与 `data/current` 指向；旧数据位于 `versions/<SHA256>/`，
旧镜像可用 `docker image ls achievement-recommendation-rust` 查看。在服务器上：

```bash
docker compose --env-file release.env stop recommendation-rust
# 将 OLD_SHA 与 OLD_IMAGE 替换为已核对的旧数据 SHA256 与旧镜像完整标签
RUST_RECOMMENDATION_IMAGE=OLD_IMAGE docker compose --env-file release.env run --rm --no-deps recommendation-rust verify --db /data/versions/OLD_SHA/recommendation.sqlite
ln -s versions/OLD_SHA data/current.rollback
mv -fT data/current.rollback data/current
# 核对 release.env 内镜像标签并改成 OLD_IMAGE，其他参数保留
docker compose --env-file release.env up -d
```

面板切回 `8605` 即恢复原 Python 服务。本脚本从不修改共享 `dashboard/.env`。
