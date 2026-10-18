# 面板数据下载

面板导航的「数据下载」页（`/#download`）提供完整 PostgreSQL 归档
`achievement-analytics-data.tar.gz`，文件由 OSS 提供，面板后端流式转发，不落本地文件。

页面同时提供 GitHub 仓库与许可证链接：代码和文档采用仓库现有的 PolyForm Noncommercial
License 1.0.0，允许许可范围内的非商业使用，商业用途需全体作者书面授权。该许可属于
source-available，不应称为「完全开源」。第三方数据不在此许可覆盖范围内，使用与再分发
仍须遵守各来源条款；页面保留 RAWG 回链及其免费档非商业用途说明。

每个来源 IP 按北京时间自然日最多开始下载 5 次，每日零点重置；中途取消计数，
OSS 请求失败退还次数。并发请求也共用 5 次额度，超额返回 429 与 `Retry-After`。
循环地址同样计数，不信任客户端传来的 `X-Forwarded-For`。
计数仅在单个进程内存中，服务重启后清零；同一公网 IP 的用户共用额度。

## 凭据与预览

仅在 `dashboard/.env` 设置下列两个变量（该文件不入 Git）：

```dotenv
OSS_ACCESS_KEY_ID=你的AccessKeyID
OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
```

后端按 [OSS Authorization 签名规范](https://www.alibabacloud.com/help/en/oss/developer-reference/include-signatures-in-the-authorization-header)
读取私有对象，不向浏览器返回 OSS 签名地址或凭据。运行和部署均不读取 CSV。
未配置完整凭据时，下载返回 503。

本机预览（在项目根目录先同步 main）：

```bash
cd dashboard
go run . --port 8601
# 浏览器访问 http://127.0.0.1:8601/#download
```

## 部署

执行 `bash dashboard/deploy.sh`。部署脚本将 `.env` 中的 OSS 下载凭据传入服务器运行时
`.env`，不改写本机 `.env`，不传 SSH 凭据。派生文件权限为 600，`.dockerignore`
排除 `.env`，密钥不进入镜像。`build/` 中的打包文件含运行时凭据，不要共享。

scratch 镜像额外复制 CA 公钥证书包，用于校验 OSS HTTPS；默认从本机
`/etc/ssl/cert.pem` 读取。Linux 若使用其他位置，可运行：

```bash
CA_CERT_FILE=/etc/ssl/certs/ca-certificates.crt bash dashboard/deploy.sh
```

部署仍只读数据库，不执行 DDL、不启动 worker。五次限制依赖面板转发，OSS 对象应保持私有；
仅支持单实例内存计数。新增反向代理时需重新设计可信代理的 IP 解析。
