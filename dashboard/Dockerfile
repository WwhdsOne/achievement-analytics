# 面板的运行时镜像。
#
# ⚠️ 构建上下文**不是这个目录**，而是服务器上的部署目录
# （/opt/achievement-dashboard）：由 dashboard/deploy.sh 上传，里面只有交叉编译好的
# 静态二进制、本文件、docker-compose.yml、.dockerignore、派生的 .env 和 data/。
# 所以下面 COPY 的是 `achievement-dashboard`（那个二进制），不是 dashboard/ 这份源码。
#
# 直接用 scratch：没有 shell、没有包管理器、没有任何第三方基础镜像，
# 运行时零依赖下载，也没有基础镜像的可利用面。要加东西先想清楚——
# 需要 shell 时就说明这个思路破了。
FROM scratch

# 由 deploy.sh 里 `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build` 产出
COPY achievement-dashboard /dashboard
# scratch 没有系统信任库；仅补 CA 公钥证书以校验 OSS HTTPS。
COPY ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

# 冻结数据通过 compose 只读挂载 /app/content，报告路径由 compose 显式指定。
WORKDIR /app

ENTRYPOINT ["/dashboard"]

