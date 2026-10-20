# 磁盘版推荐的工作方式

原 Python 代码、入口和部署均保留。Rust 新版负责 Go 面板使用的三个只读接口：
`/api/meta`、`/api/search`、`/api/recommend`。原 Python 独立研究页面与外部 AI 点评仍由原版提供；Go 面板原本没有代理点评接口。

## 数据在哪里

服务器默认目录为 `/opt/achievement-recommendation-rust/data/`，每个 SQLite 文件与摘要
放在 `versions/<SHA256>/` 下，`current` 指向启用版本。普通发布只更换镜像，复用这里的
数据。首次可以直接读取服务器已有 `/opt/achievement-recommendation/runtime/`
冻结快照和图谱生成 SQLite，不重新查云库，不把图谱从本机再传一遍。

| SQLite 表 | 内容 | 什么时候读取 |
|---|---|---|
| games | 原游戏记录、候选资格、发售年份、搜索字段、别名 | 搜索、筛选与显示当前涉及的游戏 |
| entities | 标签、类型、开发商、发行商与游戏实体的原始 JSON | 当前解释涉及的实体 |
| relations | 游戏关系、原始证据、来源时间、事实 ID | 候选计算与最终结果的证据 |
| metadata | 固定数据版本、摘要、计数与实现绑定 | 元信息与版本检查 |

正向和反向索引也在 SQLite 磁盘文件内。运行时不复制整张图谱、全部游戏记录或完整倒排表
到 Rust 集合中。搜索逐行扫描已归一化字段；评分逐个读取匹配候选，只保留 Top K。
本次查询的少量种子、当前候选、IDF 查询缓存和最终解释仍会使用内存。

SQLite 页缓存设为 8 MiB，关闭 mmap，临时排序使用磁盘目录 `/tmp`，容器把它挂载到
服务器 `scratch/`；不使用 tmpfs。请求逐个处理，避免并发时重复建立工作区。操作系统
仍可能缓存磁盘页；这部分可回收文件缓存与程序 RSS 应分别观察。

## 首次导入与启动

```bash
cargo build --release --locked --manifest-path result/ZZY/rust-recommendation/Cargo.toml

result/ZZY/rust-recommendation/target/release/achievement-recommendation-rust import \
  --cache-root result/ZZY/runtime/dashboard \
  --db result/ZZY/rust-recommendation/runtime/recommendation.sqlite

result/ZZY/rust-recommendation/target/release/achievement-recommendation-rust serve \
  --db result/ZZY/rust-recommendation/runtime/recommendation.sqlite \
  --host 127.0.0.1 --port 8606
```

导入流式读取 gzip 快照与 JSONL，核对原始文件 SHA256、版本绑定、关系数量与资格；
然后逐游戏回放原始字段，核对实体、事实关系和证据。完整成功才发布 SQLite 与摘要。
同输入再次导入只核验和复用，已有不同输入不会被覆盖，需要另选输出路径。
输入源文件与 SQLite 都必须加入服务器磁盘备份。

服务启动核对 SQLite 摘要与完整性，只读打开数据库，查询期间不连接 PostgreSQL。
数据文件缺失或损坏会失败；程序不会静默刷新或切换成另一批游戏。

## 推荐含义保持

- 标签 / 类型 / 开发商 / 发行商权重：0.75 / 0.15 / 0.10 / 0。
- 使用关系内 IDF-Jaccard；年份先筛选，再确定 IDF 参考库，排除全部唯一种子。
- 联合查询对 1–3 个唯一种子等权；无匹配的种子保留零分份额。
- 缺少关系不重新分配权重；同分按 AppID 升序，不生成任意兜底推荐。
- 保留完整贡献与来源事实；显示路径数量只影响展示，不改变排名。
- 版本使用独立 `rust-*` 标识，绑定同一快照与图谱，不冒充原 Python 源码版本。

实际部署方式、显式数据更新与切回 Python 见 [README](README.md)。真实对照脚本与
判断范围见 [VALIDATION](VALIDATION.md)。
