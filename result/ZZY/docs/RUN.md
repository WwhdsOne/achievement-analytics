# 运行说明

Python 3.13，使用小组仓库已有 `uv`、`pyproject.toml` 和 `uv.lock`。未增加共享依赖。

## 默认：读取小组数据库

在仓库根执行：

```powershell
uv sync
uv run python result/ZZY/run.py serve
```

默认读取仓库根 `.env`，使用已有 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`；可选 `POSTGRES_SSLMODE`。环境变量优先。没有配置时列出缺少的变量名，不猜测地址、端口或密码。`.env` 和密码不提交、不发送到页面。沿用小组现有配置，不改共享库结构。

只运行这一条serve即可访问联合推荐、标签基线、图谱来源核查、单游戏解释四页面；导航使用同源子路径/、/baseline/、/graph/、/explain/，无需启动8602/8603/8604。

读取一次数据库后自动建立/核验本地版本图谱，再打印 `http://127.0.0.1:8605/`。首次构建需要等待，期间终端有进度；浏览器查询期间不再访问数据库。数据每次重启更新，运行期间保持一致。Ctrl+C停止自己启动的服务。

配置位于别处时：

```powershell
uv run python result/ZZY/run.py serve --env-file "C:/你的路径/achievement-analytics/.env" --port 8606
```

配置文件路径和显式缓存路径相对当前终端解释，默认配置/缓存路径相对项目文件解释。默认缓存 `result/ZZY/runtime/database/` 自动生成，不入Git。`--cache-root` 可指定缓存位置；不要用他人的数据目录。

连接超时10秒、每条SQL最多120秒；读取使用一个只读一致性事务，关闭后再本机构图。失败停止启动，不静默回退旧缓存；终端不显示数据库原始异常或连接串。

## 基线与校验

```powershell
uv run python result/ZZY/run.py baseline
uv run python result/ZZY/run.py check
```

serve已经内置/baseline/标签基线；baseline命令只为需要独立基线端口的人保留，默认同样只读数据库，启动标签基线页8602，不构建图谱。check默认读取数据库并核验生成图谱，会单独执行一次提取；正常启动不必先跑check。它们支持相同的 `--env-file` 和 `--cache-root`。

## 显式离线复现

已持有原冻结数据时：

```powershell
uv run python result/ZZY/run.py check --source snapshot
uv run python result/ZZY/run.py serve --source snapshot
uv run python result/ZZY/run.py baseline --source snapshot
```

默认旧输入位于个人 `data/processed/recommendation/`；存放在其他位置时加 `--data-root`，该目录须同时包含原 `snapshots/` 与 `kg/`。离线模式不读取 `.env`，不连接数据库；不能混用数据库配置参数。默认数据库模式不接受 `--data-root`，避免把旧输入误当实时来源。

## 历史AI评价

```powershell
uv run python result/ZZY/run.py evaluate --output-dir result/ZZY/runtime/replay-new
```

仅在持有原协议、既有排名、空模板、AI原始表的 `runtime/evaluation-input/` 时使用。此命令不连接数据库，不重跑实时推荐，不创建真人锁。已有输出目录拒绝覆盖。可用 `--input-dir` 指定历史输入；缺历史输入不影响默认推荐服务。无需为了启动页面传输旧AI表或旧图谱包。

## 排错

- 缺配置：使用组内已有 `.env` 或设置同名 `POSTGRES_*`；不上传凭据。
- 数据库提取失败：检查网络、配置、查询权限和表结构；程序不建表、不修库。
- 端口占用：指定 `--port`，不停止其他人的服务。
- 校验失败：检查文件版本和Git换行，保留原记录，不修改manifest绕过校验。
- 与组员统一Go网站的接入仍为后续工作；本次只改变个人服务的数据来源。


## 可选：DeepSeek 个性化点评（v9）

后端读取个人目录 `result/ZZY/.env.deepseek` 或同名环境变量，环境变量优先。该私有文件不进入交付包；无Key时正常推荐与图谱仍可使用。配置后重启serve。

```dotenv
DEEPSEEK_API_KEY=在本机填写你的Key
DEEPSEEK_MODEL=deepseek-flash
```

用户点击生成才请求官方 `https://api.deepseek.com/chat/completions`，只发送所选游戏和匹配关系。网络操作超时20秒，最多2个并发生成，成功结果按模型/数据/查询绑定缓存1小时；取消是停止等待，已发给供应商的请求仍可能计费。JSON结构和引用范围检查不能证明生成内容完全正确。

协议依据：[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)。默认模型以本轮官方文档为据，可在私有配置中替换为账号支持的模型名。

本轮用户尚未配置Key；通过的是模拟传输、实际本机HTTP与浏览器夹具，真实DeepSeek外部调用待本机配置后验证。README保持v8原字节。
