# 成就分类来源小样本试跑

核查日期：2026-10-13。共享对话已阅读：
https://chatgpt.com/s/t_6acdd7f50ecc819183ea83aa2359c13d

样本为 Steam 上的 FINAL FANTASY VII REMAKE INTERGRADE（appid 1462040）和 FINAL FANTASY VII REBIRTH（appid 2909400）。此程序只在 LYX 工作空间写试跑报告，不连接任何数据库，不使用账号登录、付费服务或 API key。

## 核查结论

| 备选来源 | 当前可验证的通路 | 与“成就类型”的关系 |
|---|---|---|
| Steam Hunters | 本机公开成就 API 成功，另核验站方 API Help | 成就 API 的九个字段没有主线、支线、收集等语义标签；分组 API 只支持游戏/DLC/更新与可选联机组 |
| TrueSteamAchievements | 有官方成就 flags 定义页面；样本列表请求遇 Cloudflare 403 | 站点有 Main Storyline、Collectable 等标签，但未取得样本标签，也未核实公开分类 API |
| Gamer Guides | 搜索与页面资料显示有 Story、Sidequest、Collectable 等标签；官方说明页可核验 | 未找到已核实的公开分类 API；条款第3/5节限制系统抓取和构建数据集，脚本只读取说明页 |
| PowerPyx | 攻略站点，公开使用说明页可阅读；本机请求遇证书验证错误 | 未找到已核实的公开分类 API；不把攻略正文当结构化类型接口，也不关闭 TLS 验证 |

“未核实公开 API”不等于断言站点绝不存在内部接口。“本机能请求成功”也不等于已核实全量获取额度。间隔2秒只是这次小样本诊断参数，不是官方许可配额。

## 实际调用与参数

Steam Hunters 的开发者公告确认其提供 API，也提供成就标签功能。为了核验标签是否出现在接口中，进一步从公开客户端找到其引用的官方帮助页，并实际读取：

- [官方 API 目录](https://steamhunters.com/api/Help)
- [成就接口说明](https://steamhunters.com/api/Help/Api/GET-apps-appId-achievements)
- [分组接口说明](https://steamhunters.com/api/Help/Api/GET-GetAchievementGroups-v1_appId_groupBy%5B0%5D_groupBy%5B1%5D_includeMultiplayerGroup)
- [开发者公告](https://www.patreon.com/steamhunters/posts/use-steam-to-by-70014543)

```text
GET https://steamhunters.com/api/apps/{appid}/achievements
GET https://steamhunters.com/api/GetAchievementGroups/v1
    ?appId={appid}
    &groupBy=game,dlcandupdate,dlc
    &includeMultiplayerGroup=true
GET https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/
    ?gameid={appid}
```

分组接口的参数采用官方说明中的 `appId` 和显式 `groupBy`。官方明确支持的选项为 `game`、`dlcandupdate`、`dlc`；不猜测一个名为 Story/Mainline 的 groupBy 参数。

成就 API 的实际字段与帮助页一致：`achievementId`、`apiName`、`name`、`description`、`steamPercentage`、`localPercentage`、`points`、`steamPoints`、`obtainability`。其中 obtainability 表示可获得性，不是内容类型。localPercentage 是该站人群的比例，不能冒充 Steam 全局完成率。

脚本将 apiName/name/steamPercentage 映射为原仓库的 api_name/display_name/percent，并再从 Steam 官方接口按 api_name 关联核验百分数。每条记录的 percent_source 表明实际数值来源；不会按两个接口的排列位置配对。

## 可运行文件

`probe_achievement_types.py` 默认试跑上述两款。只有追加 `--rule-baseline` 时才输出本地描述规则候选。

```powershell
Set-Location D:\PycharmProjects\achievement-analytics\result\LYX
$env:UV_CACHE_DIR = "$PWD\process\runtime\uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run --frozen --no-sync python -X utf8 -B process/probe_achievement_types.py --rule-baseline
```

只选重生：

```powershell
uv run --frozen --no-sync python -X utf8 -B process/probe_achievement_types.py --games ff7-rebirth --rule-baseline
```

只测试 Steam Hunters 与 Steam 官方，跳过其他网站访问诊断：

```powershell
uv run --frozen --no-sync python -X utf8 -B process/probe_achievement_types.py --skip-other-sites
```

上述命令使用已有环境，`--no-sync` 不更新共享依赖。程序默认在 `process/runtime/api_probe/时间戳/` 新建报告目录；不会覆盖旧试跑。自定义 --output-dir 也必须位于 result/LYX。

输出包括：

- `report.json`：请求时间、状态、字段、来源原生类型信息、可选规则候选、按身份匹配统计。
- `achievements.csv`：成就展示名、描述、完成率及来源、原生类型字段、规则候选、章节与路线候选；UTF-8 BOM。

runtime 整个目录已被本模块 .gitignore 忽略，原始成就副本与派生标注不提交 Git。

## 规则候选边界

规则只是试跑对照，不是网站提供的标签：

- “Complete Chapter N.” 可提出主线候选与章节编号，不自动确认必经性和前置嵌套。
- INTERmission 章节另设路线候选，不能与本体章节混在同一漏斗。
- “Complete all chapters on Hard difficulty.” 提出挑战候选，不当普通主线节点。
- 没有命中的成就保留 unknown / uncertain；不是“没有类型”的确定结论。
- 所有命中结果仍为 suggested，不写入 approved，也不声称分类准确率。

试跑能够取得重制版63项、重生61项成就，分别匹配63/63与61/61项官方全局完成率。可选规则找到重制版本体18个章节候选、INTERmission两个章节候选，以及重生14个章节候选。两个样本的成就API都没有原生分类字段。

当前程序不抓单个成就攻略，不向其他站点传递数据库凭据。遇挑战/403/429立即挂起该host；记录Retry-After后停止本轮，不快速重试。网络/5xx最多两次，间隔退避2秒。响应结构错误与访问失败分别记录，不伪装为空数据。

## 验证

```powershell
uv run --frozen --no-sync python -X utf8 -B process/tests/test_api_probe.py
```

10项离线契约验证覆盖：身份键/结构错误、官方百分数按身份匹配、零完成率、类型字段缺失、章节和困难挑战分离、INTERmission路线分离、挑战源挂起、压缩JSON响应、正常Cloudflare背景脚本不误报挑战、工作空间输出限制。

其余第一方资料：

- [TrueSteamAchievements flags 定义](https://truesteamachievements.com/help/achievementflags)
- [Gamer Guides 使用说明](https://www.gamerguides.com/terms)
- [PowerPyx 使用说明](https://www.powerpyx.com/tos/)
- [Steam 全局成就接口](https://partner.steamgames.com/doc/webapi/ISteamUserStats)

下一步如需网站原生语义分类，应获得能返回这些字段的站方接口/导出，或单独评估获准的网页标签获取方案；本次没有把规则推断混成站方数据。
