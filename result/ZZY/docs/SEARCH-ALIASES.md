# 中文名、常用译名和简称搜索

2026-10-14：联合推荐页 `/` 与标签基线页 `/baseline/` 共用本地 AppID 别名表。首批覆盖44款游戏、114个搜索词；这是人工维护的搜索词数量，不是全库中文名称覆盖率。

示例：

| 搜索词 | 对应游戏 | AppID |
|---|---|---|
| 艾尔登法环、老头环 | ELDEN RING | 1245620 |
| 空洞骑士 | Hollow Knight | 367520 |
| 星露谷物语、星露谷 | Stardew Valley | 413150 |
| 黑暗之魂3、黑魂3、魂3 | DARK SOULS III | 374320 |
| 博德之门3、博德3、BG3 | Baldur's Gate 3 | 1086940 |
| 欧洲卡车模拟2、欧卡2 | Euro Truck Simulator 2 | 227300 |

输入中文、英文、译名、简称或 AppID，结果按原来的方式显示游戏，不额外显示别名标记或说明。中文简称与正式名称只对应同一条游戏，不创建重复记录。支持子串匹配、大小写忽略、全半角和连续空白标准化，保持原来的 AppID 排序和分页。宽泛的搜索词可能命中多款，须按名称和 AppID 选择。

别名仅用于搜索，不覆盖数据库名称、不修改数据库、不参加评分，也不改变候选资格、年份过滤或种子数量。联合搜索保留资格不足的游戏及原因；标签基线仍只搜索有效候选。当前输入中没有对应 AppID 时，不会凭空生成游戏。

## 如何补充

修改 `result/ZZY/modeling/recommendation/game_aliases.json`，在 `games` 中按 Steam AppID 添加：

```json
"367520": {
  "name_en": "Hollow Knight",
  "aliases": ["空洞骑士"]
}
```

`name_en` 只用于人工核对身份，搜索以运行数据中的名称及 `aliases` 为准。先核对 AppID 与具体版本，区分续作、DLC、原版和重制版；不要把系列简称随意绑定到某款。更新 JSON 后重新生成 `reports/source-map.json` 中该文件的 SHA256，再重启服务。启动入口会检查来源摘要，避免打包漏文件或旧摘要混用。无需建表、SQL 更新或重新训练。

可在个人目录运行以下命令刷新别名文件摘要（不会改共享数据库）：

```powershell
uv run python -c "import hashlib,json; from pathlib import Path; p=Path('reports/source-map.json'); m=json.loads(p.read_text(encoding='utf-8')); n='modeling/recommendation/game_aliases.json'; e=next(e for e in m['files'] if e['path']==n); e['sha256']=hashlib.sha256(Path(n).read_bytes()).hexdigest(); p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')"
```

## 验证与边界

- 开发副本：141项搜索、图谱评分、多游戏、查询接口及页面契约回归通过。
- 私有交付模块：15项新增行为测试通过；覆盖中文简称、与名称合并去重、分页、缺失 AppID、资格不足、英文与数字兼容、全半角、搜索后原始名称与评分不受污染。
- 本机冻结快照完整实测：114个词全部通过 HTTP 命中；3款示例单游戏推荐的 AppID/分数与原图谱评分器一致；桌面1440×1000和手机390×844各5项搜索选择、联合推荐、布局与标签基线操作通过，无浏览器错误。共127项检查，33份私有来源摘要通过。实测脚本为 `tests/check_search_aliases.py`，摘要见 `reports/search-alias-verification.json`。

验证输入是已有50,925款游戏的冻结快照，不是本次实时云库抽取；数据库加载代码未改。本次没有数据库访问、Git提交、推送或统一小组网站集成。冷门游戏仍需后续补充。既有导航和数据库验收文档保留为历史证据，不把旧“31份源码原样”说明当成本次新搜索功能的验收。

复测（pytest 与 Playwright 是开发验收工具，未新增运行时依赖）：

```powershell
# 在小组仓库根目录；使私有模块可导入
$env:PYTHONPATH=(Resolve-Path result/ZZY).Path
uv run python -X utf8 -m pytest result/ZZY/tests/test_search_aliases.py --import-mode=importlib --basetemp result/ZZY/runtime/pytest-aliases -q
uv run --with playwright python -X utf8 result/ZZY/tests/check_search_aliases.py --data-root result/ZZY/data/processed/recommendation
```

浏览器脚本使用本机 Google Chrome；第二条要求显式本地快照和图谱目录齐全，只读读取该输入，临时启动本机随机端口并在结束后关闭。

最新界面复测：按用户要求保留原搜索框与结果样式，移除额外别名说明和匹配标记；完整127项检查再次通过，桌面/手机均确认无额外别名标记。
