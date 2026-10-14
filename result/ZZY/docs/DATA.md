# 数据库、自动缓存与历史输入

## 正常运行

默认入口启动时读取小组 PostgreSQL，数据查询口径仍为2026年以前发售游戏，使用现有 games、steam_appdetails、steamspy_games、achievements、game_tags、mapping_issues、ingest_log。沿用SteamSpy主题标签与官方类型口径；功能标志不作主题。

数据库连接以 `default_transaction_read_only=on` 建立，事务为 `REPEATABLE READ / READ ONLY`，实际读取 `transaction_read_only` 验证为on。只执行原SELECT查询，不写云库、不登记版本、不创建表、不调用worker/seed/init。数据取完即释放连接。

本机自动产生：

```text
result/ZZY/runtime/database/
  snapshots/recommendation-v1-<内容摘要>/
    manifest.json
    games.json.gz
  kg/kg-v1-<输入与构建规则摘要>/
    manifest.json
    entities.jsonl
    relations.jsonl
    quality.json
  latest-startup.json
```

每次启动仍重新读取数据库；内容和构图规则相同则完整核验并复用缓存。缓存有版本，拒绝覆盖坏版本，也不在读库失败时使用旧版本继续运行。只读抽取结束后构图不占数据库连接。运行期间查询本地已验证数据，重启刷新。

`latest-startup.json` 和 `/api/meta` 的 `data_loading` 记录**本次**提取时间、只读设置和数据版本；内容复用时不会把第一次生成快照的时间冒充本次读取时间。页面不发布数据库主机、用户名或密码。

代码上传GitHub即可；运行者使用组内数据库配置，**不必额外接收数据包**。本地缓存仍占磁盘空间，首次构建有成本。

## 历史冻结输入

旧 `ZZY-data-v2.zip` 是原实验的可选离线复现输入，不是默认数据库启动的必需品。原快照含50,925款游戏、41,279款合格候选；原图谱114,301实体、895,023事实边。这些是原版本数字，新数据库启动的规模以当前meta为准。

原输入位于 `data/processed/recommendation/snapshots/` 与 `kg/`；只有显式 `--source snapshot` 使用。历史评价5份输入位于 `runtime/evaluation-input/`，177行标签来自AI-DeepSeek-run01，包含20个unknown及已记录问题。旧AI指标只绑定原协议与排名，不因数据库更新而自动获得新的效果证据。

个人 `.gitignore` 排除 data、runtime、凭据和缓存。GitHub只保存程序、来源摘要、派生报告和图表。
