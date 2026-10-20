# 真实服务对照验收

保留原 Python 实现，用相同的冻结图谱/快照启动 Python 与 Rust 两个独立端口后运行：

```bash
uv run python scripts/check_rust_recommendation.py \
  --python-url http://127.0.0.1:18605 \
  --rust-url http://127.0.0.1:18606 \
  --output /tmp/rust-recommendation-validation.json
```

脚本只有 Python 标准库依赖，不读取 `.env`、不连接数据库，不启动 worker，不修改原 Python 服务或冻结文件。它向两个服务发送真实 HTTP 请求。摘要只含检查名、通过情况、错误字段位置和计数，不保存响应记录或服务地址。

验收覆盖：

- 中文名、人工别名、AppID、英文名、全角与大小写空白归一化、分页偏移、无匹配搜索。
- 从完整冻结搜索发现真实合格/不合格游戏；1–3 种子、重复种子、种子在年份范围外、空年份范围、空边界、混入不合格种子。
- 精确排名 AppID 顺序、所有业务字段及列表成员、数值分数/关系分量/IDF/路径贡献（绝对与相对容差均为 `1e-12`）。
- 原完整解释，包括每种子关系、完整 `path_catalog`、双端事实来源与事实 ID、展示图的全部节点/边/标签及裁剪贡献。图节点/边的插入顺序不影响成员比较；排名和路径目录顺序仍严格比较。
- 独立复算 IDF、关系分量、种子等权分数、原路径/联合路径贡献，以及展示/隐藏路径守恒；确认展示图边来自所显示路径的真实事实。
- 未知/重复/格式错误/越界参数、未知路由、POST/PUT/PATCH/DELETE 拒绝，随后再次探活。

两套实现可拥有不同的实现版本号与绑定嵌套结构；脚本明确排除 `view_version`、`query_service_version`、`algorithm_version`、`base_algorithm_version` 以及绑定对象本身的结构比较，同时**另外强制比较**其中的图谱版本/manifest SHA256、快照版本/SHA256 和关系权重。数据身份不能因更换实现而跳过核验。其他业务输出不会因排名一致而免检。

`data_loading` 的运行实现信息另外检查：Rust 必须明确标为 `persistent_sqlite`、`database_access=false`、`cache_reused=true`，且快照版本、图谱版本和快照游戏数与原服务一致；启动时间等实现信息允许不同。`commentary` 能力声明仍完整比较。

退出码 `0` 表示上述实际请求全部通过，`1` 表示失败。未运行脚本、服务未启动或冻结样本缺失都不能当作完成验收。它是 `scripts/` 中的独立验收工具，不新增 pytest 用例。

## 已完成的 Docker 实测（2026-10-20）

2026-10-20 18:29（北京时间）对原 Python 服务 `127.0.0.1:18605` 与 ARM64 Rust Docker 服务 `127.0.0.1:18606` 运行上述真实 HTTP 对照，退出码 `0`，**69/69 项通过，0 项失败**。

| 核验项 | 实际计数 |
| --- | ---: |
| HTTP 请求 | 138 |
| 数值比较（绝对/相对容差 `1e-12`） | 23,443 |
| 双端来源事实检查 | 2,728 |
| 排名结果检查 | 54 |
| 完整解释路径检查 | 1,364 |

事实、结果和路径检查计数包含 Python 与 Rust 两侧的独立守恒核验。完整 `ranking`、每种子/关系分量、原始来源证明、`path_catalog` 和 `display_graph` 均通过比较；结果包括年份筛选、空候选、不合格种子、严格参数拒绝及只读方法。

此次目标为本机 **ARM64 Docker** 镜像 `sha256:e3b714a5edb2fcc3d861ff2a0ead659ba8959afb0b5bc87c678ae409ee7f6dab`，限制 **1 CPU / 256 MiB**；根文件系统只读，`/data` 为只读 bind mount，`/tmp` 为可写磁盘 bind mount。服务使用从原冻结输入完整重放导入、经过语义校验的 SQLite，随库 SHA256 为 `438e99b30e61b5fb6bf12a32936bc56dd2f3b67783c2d558acbde5987cd26fb5`。这些信息已通过 Docker image/container inspect 和当前库摘要核对。

实际命令：

```bash
uv run python scripts/check_rust_recommendation.py \
  --python-url http://127.0.0.1:18605 \
  --rust-url http://127.0.0.1:18606 \
  --output /tmp/rust-recommendation-docker-validation.json
```

该摘要只保存检查结果与计数，不保存原始接口记录、凭据或服务地址；它是本次运行的本机证据文件，不入 git。

## 最终部署架构实测：linux/amd64

2026-10-20 18:35（北京时间）进一步运行最终 `linux/amd64` 镜像，与同一原 Python 服务重新完成全部 **69/69 项**对照，退出码 `0`，0 项失败。实际计数仍为 138 次 HTTP 请求、23,443 个数值比较、2,728 条双端事实检查、54 个排名结果和 1,364 条完整解释路径。

目标为 `achievement-recommendation-rust:f5439da7d68d1a82532d`，image ID `sha256:8a2b964a3fbace2b5339681b14111aa2a770a3449e023ba5a4178571a4d6eefd`，通过 Docker inspect 确认架构为 `amd64`。此次在 ARM64 宿主的 Docker 中运行 AMD64 镜像；约束仍为 1 CPU / 256 MiB、只读根文件系统、只读 `/data` 和可写磁盘 bind mount `/tmp`，使用同一 SQLite SHA256 `438e99b30e61b5fb6bf12a32936bc56dd2f3b67783c2d558acbde5987cd26fb5`。相比前一次 ARM64 实测，仅 CLI 帮助中的默认端口提示由 8605 修正为 8606，查询与存储逻辑相同。

```bash
uv run python scripts/check_rust_recommendation.py \
  --python-url http://127.0.0.1:18605 \
  --rust-url http://127.0.0.1:18608 \
  --output /tmp/rust-recommendation-amd64-validation.json
```

最终架构本机摘要为 `/tmp/rust-recommendation-amd64-validation.json`，仅含验收计数和结果，不入 git。
