# 本机演示接口与组内接入

入口为 `run.py serve`，默认127.0.0.1:8605。全部接口只读GET，后端从本地冻结输入计算，不提供写库或任意文件下载路由。

| 路由 | 用途 |
|---|---|
| `/` | 统一推荐页面 |
| `/api/meta` | 快照范围、候选数、展示与算法版本 |
| `/api/search?q=ELDEN&limit=20&offset=0` | 搜索完整快照，返回资格信息与分页 |
| `/api/recommend?appids=1245620&top_k=5&path_limit=8` | 单游戏推荐和路径 |
| `/api/recommend?appids=367520,413150&year_min=2020&year_max=2025&top_k=5&path_limit=all` | 多游戏、年份先筛后排及完整路径 |

appids为1–3个唯一且合格的种子；全部种子从候选中排除。年份包含首尾，无边界时省略；种子发售年不受候选年份限制。path_limit只裁剪展示，不改变推荐排名或原始报告。空结果保留为空，不补热门游戏。

meta主要字段为snapshot_games、candidate_games、view_version、query_service_version、algorithm_version和limits。推荐响应包含原排名、各个种子的贡献和关系/来源投影，评分不是喜欢概率。具体结构以实际JSON响应为准，代码位于modeling/recommendation/query_view.py。

与现有Go面板的集成尚未实施。本交付可作为独立服务演示；后续组内接入应约定读取的报告字段或新增调用方式，处理同源/反向代理及服务生命周期。当前仅本机监听，不把本地可访问当作已部署的网站。


## 默认数据库启动的来源信息

推荐页 /api/meta 新增data_loading：source=group_database、database_access=true、started_at/finished_at为本次数据库抽取时刻，database_settings包含read_only=on和isolation=repeatable read，另含本次snapshot_version/graph_version。每次启动重新读库，内容相同可复用已核验图谱；查询期间不连数据库。
显式离线模式source=frozen_snapshot、database_access=false。meta不提供连接串、地址、账号或密码。原搜索/推荐请求与响应排名字段保持原样；算法版本由实际图谱绑定决定，新数据不沿用旧版本号。页面资源改动可使view_version改变。


## 同端口辅助入口

serve一次启动同源四页面。/baseline/api/meta、/baseline/api/games、/baseline/api/recommend复用标签基线；/graph/api/summary、/graph/api/pair回查图谱事实；/explain/api/meta、/explain/api/recommend提供单游戏评分路径。所有辅助页面资源位于各自子路径，无需其他端口。
四入口共用同一份数据来源记录。子目录缺尾斜杠时308跳转，未知路径404，POST/PUT/PATCH/DELETE为405；不提供数据库写接口。辅助页面调用的原评分/核查函数不改，挂载层更新当前来源与过时说明。
