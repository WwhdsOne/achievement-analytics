# 研究成果入口与可解释推荐接入

目标：新增「研究成果」顶层标签，左侧五方向导航，先展示朱政宇的真实推荐成果。

架构：dashboard 继续使用 Go 与内嵌前端。通过同源 GET `/api/research/recommendation/{meta,search,recommend}` 调用独立 ZZY 服务，复用算法及来源绑定，不在面板镜像引入 Python。默认上游为同机 `http://127.0.0.1:8605`，可用启动参数覆盖；不代理点评 POST。

- [x] `dashboard/index.html`、`explore.js`：接入 `#research/<方向>`，保留旧入口行为。
- [x] `dashboard/research.css`、`research.js`：纸灰黑白主题、五项导航、负责人和范围；其他四项标记待接入；推荐支持搜索、最多三款种子、年份、数量与推荐理由/来源明细。
- [x] `dashboard/research.go`、`main.go`：限定三个 GET 端点，设置超时、响应大小限制和上游不可用提示；注册内嵌静态资源。
- [x] 文档：记录两服务启动方法、生产接入条件、只读及数据版本口径。
- [x] 验收：Go 构建与静态检查；真实服务查询核对；浏览器桌面/移动端导航、推荐、年份、空结果、不可用/重试、路由恢复和既有探索回归。遵照项目要求不新增测试用例、不提交。

运行补充：交付 source-map 因工作区源码变化失效，新增 `result/ZZY/dashboard_service.py` 为集成入口，保留真实读库、当前源码图谱绑定与完整校验。原8605已被占用，本次预览将独立推荐服务放在8607，Go使用 `--recommendation-url http://127.0.0.1:8607`；两者均仅监听本机。
