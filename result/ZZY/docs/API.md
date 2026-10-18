# 本机演示接口与组内接入

入口为 `run.py serve`，默认127.0.0.1:8605。查询接口使用GET；新增 `POST /api/commentary` 按需生成点评。接口不写数据库，不提供任意文件下载路由。默认启动时只读数据库一次并建立一致的本地输入，查询期间不连数据库。

| 路由 | 用途 |
|---|---|
| `/` | 统一推荐页面 |
| `/api/meta` | 快照范围、候选数、展示与算法版本 |
| `/api/search?q=ELDEN&limit=20&offset=0` | 搜索完整快照，返回资格信息与分页 |
| `/api/recommend?appids=1245620&top_k=5&path_limit=8` | 单游戏推荐和路径 |
| `/api/recommend?appids=367520,413150&year_min=2020&year_max=2025&top_k=5&path_limit=all` | 多游戏、年份先筛后排及完整路径 |
| `POST /api/commentary` | 根据当前推荐结果的真实匹配依据生成结构化点评 |

appids为1–3个唯一且合格的种子；全部种子从候选中排除。年份包含首尾，无边界时省略；种子发售年不受候选年份限制。path_limit只裁剪展示，不改变推荐排名或原始报告。空结果保留为空，不补热门游戏。

meta主要字段为snapshot_games、candidate_games、view_version、query_service_version、algorithm_version和limits。推荐响应包含原排名、各个种子的贡献和关系/来源投影，评分不是喜欢概率。具体结构以实际JSON响应为准，代码位于modeling/recommendation/query_view.py。

与现有Go面板的集成尚未实施。本交付可作为独立服务演示；后续组内接入应约定读取的报告字段或新增调用方式，处理同源/反向代理及服务生命周期。当前仅本机监听，不把本地可访问当作已部署的网站。


## 默认数据库启动的来源信息

推荐页 /api/meta 新增data_loading：source=group_database、database_access=true、started_at/finished_at为本次数据库抽取时刻，database_settings包含read_only=on和isolation=repeatable read，另含本次snapshot_version/graph_version。每次启动重新读库，内容相同可复用已核验图谱；查询期间不连数据库。
显式离线模式source=frozen_snapshot、database_access=false。meta不提供连接串、地址、账号或密码。原搜索/推荐请求与响应排名字段保持原样；算法版本由实际图谱绑定决定，新数据不沿用旧版本号。页面资源改动可使view_version改变。


## 同端口辅助入口

serve一次启动同源四页面。/baseline/api/meta、/baseline/api/games、/baseline/api/recommend复用标签基线；/graph/api/summary、/graph/api/pair回查图谱事实；/explain/api/meta、/explain/api/recommend提供单游戏评分路径。所有辅助页面资源位于各自子路径，无需其他端口。
四入口共用同一份数据来源记录。子目录缺尾斜杠时308跳转，未知GET路径404；仅 `/api/commentary` 接受POST，其他POST及PUT/PATCH/DELETE为405。不提供数据库写接口。辅助页面调用的原评分/核查函数不改。

## POST /api/commentary

仅在用户主动点击时调用。`Content-Type: application/json`，请求体最多4096字节，不接受任意提示词或外部URL。

```json
{"appids":[1],"candidate_appid":2,"top_k":5,"year_min":null,"year_max":null}
```

上面ID仅演示参数结构，实际必须使用本服务 `/api/recommend` 返回的游戏ID。`appids` 为1–3个正整数，`candidate_appid` 必须位于同一组种子、年份和数量条件下的推荐结果；`top_k` 默认为5，只能为1、3、5。年份可省略或为null，填整数时范围为1–9999且下界不得大于上界。JSON布尔值不能代替整数。不接受额外参数；请求URL不能带查询串。

成功返回200，结构示例：

```json
{
  "status":"ok",
  "provider":"DeepSeek",
  "model":"以服务配置为准",
  "candidate_appid":2,
  "commentary":{
    "summary":"一句推荐结论",
    "reasons":[{"title":"理由短标题","text":"与某款已选游戏的关系说明","evidence_ids":["e1"]}],
    "caution":"一句挑选提醒"
  },
  "evidence":[{"id":"e1","seed_appid":1,"seed_name":"已选游戏","relation":"tags","name":"Exploration","contribution":0.1}],
  "cached":false,
  "note":"AI生成的推荐解读；已核对引用范围，内容仍可能有误。"
}
```

`summary` 最多100字；`reasons` 为1–2条，每条title最多16字、text最多140字；`caution` 最多80字。各文本为单行，理由的 `evidence_ids` 均来自返回的 `evidence`。结构校验与引用检查不保证模型语义完全正确。原推荐排名、分数和数据库保持不变。

相同请求按模型、提示词及展示版本缓存1小时，最多64条；同一请求生成中或同时已有2个生成请求时返回429。缓存命中时 `cached=true`，无需再次调用模型；“再看这次点评”可能返回缓存，非强制重新生成。

失败响应含 `error`，业务错误还包含 `code`：

| HTTP | 场景/主要code |
|---|---|
| 400 | 非法参数、候选不属于当前结果：invalid_request |
| 403 | Host或Origin未获允许：origin_not_allowed |
| 405 | POST路径错误或不支持的方法 |
| 413 | 请求体为空或超过4096字节 |
| 415 | Content-Type不是application/json |
| 422 | 无可用正向依据：insufficient_evidence |
| 429 | 正在生成或并发限制：busy |
| 502 | 模型输出校验失败invalid_output，或provider_unavailable |
| 503 | 未配置密钥not_configured，或服务unavailable |
| 504 | 模型超时：timeout |

`GET /api/commentary` 返回404且不触发模型调用。`/api/meta` 的 `commentary` 给出 configured、provider、model、trigger、prompt_version；不含密钥。关闭或失败时原推荐和图谱仍可使用。

## 交给组长的网站接入配置

本交付已补齐可配置来源和本机模拟测试，实际网站部署及Go网站联调由组长完成。Python服务保持监听127.0.0.1，由同机网站代理转发。不同机器/容器需要组长提供可达的私有转发方式。

在Python服务环境变量或个人目录 `result/ZZY/.env.deepseek` 中配置（环境变量优先）：

```dotenv
DEEPSEEK_API_KEY=由部署者在服务器填写自己的密钥
COMMENTARY_PUBLIC_ORIGINS=https://games.example.com
```

域名是占位示例，必须换成网站实际来源；来源包含http/https、域名与可选端口，多个来源用逗号分隔。不填来源时仅允许本机访问；不接受通配符、URL路径或带账号密码的来源。非法配置会使启动失败并给出配置项名称。修改后重启服务。密钥仅存在后端，压缩包和前端不携带真实密钥。

浏览器继续同域 `fetch('/api/commentary', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})`。来源白名单兼容代理保留公共Host，或改写为本机Host但保留公共Origin。不使用客户端提交的X-Forwarded-Host等头放宽验证；不配置跨域CORS。来源白名单不是用户登录验证，网站原有身份/额度控制由组长在公开代理入口应用。

若组长使用Nginx，可参考下面的同域代理配置；Go网站使用等价转发即可：

```nginx
location = /api/commentary {
    proxy_pass http://127.0.0.1:8605/api/commentary;
    proxy_set_header Host $http_host;
    proxy_set_header Origin $http_origin;
    proxy_read_timeout 60s;
}
```

网站外部来源（包括非默认端口）应与 COMMENTARY_PUBLIC_ORIGINS 一致。无Origin的同源服务端转发也支持；Host仍须为本机或已配置来源。组长联调时先检查 `/api/meta` 的 configured，再从相同服务的推荐结果选择候选；403先核对Host、Origin与来源配置，502/504核对模型连接，勿把来源限制误当成模型故障。
