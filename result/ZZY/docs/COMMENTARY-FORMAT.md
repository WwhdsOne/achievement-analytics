# 点评格式（2026-10-15）

点评展示为一句结论、两条推荐理由、一句挑选提醒；依据不足时只显示一条理由。引用的匹配依据默认折叠，可点击展开。多选时提示词要求明确各理由对应的已选游戏。

模型返回 summary、reasons、caution，每条理由携带真实 evidence_ids。后端检查字段、单行文本、长度、理由数量和引用范围；旧单段输出拒绝展示。缓存版本为 grounded-game-commentary-v2-structured，避免复用旧格式。

修改后需要重启当前推荐服务，再刷新页面并生成点评：页面资源、提示词和内存缓存均在服务启动时加载。沿用原有启动方式即可。

评分、候选集合、数据库读取方式不变。格式校验与引用范围检查不能证明模型语义完全正确。

## 本轮验证

- 49 项 Python 单元及关联回归测试、5 项本机接口测试、8 项 JavaScript 展示测试通过。
- 浏览器验证 13 项检查：分栏、依据折叠/展开、单理由回退、旧格式拒绝、切换候选、取消、失败重试、文本渲染、缓存提示、清空与 390px 布局等。
- 浏览器使用原冻结数据中的 13 款游戏构成界面测试样本，点评响应由浏览器模拟，没有调用真实 DeepSeek。没有据此声称完整快照评估或真实模型质量改善。
- 浏览器记录：reports/commentary-format-browser.json；截图：runtime/commentary-format/。

执行方式（工作区根目录，使用已配置的 Python 虚拟环境与 Playwright）：

```powershell
$env:PYTHONPATH=(Resolve-Path './交付版-用户发现/result/ZZY').Path
& './achievement-analytics/.venv/Scripts/python.exe' -X utf8 -m pytest './交付版-用户发现/result/ZZY/tests' -q --basetemp='.pytest-commentary-format-full'
node --test './交付版-用户发现/result/ZZY/tests/test_discovery.cjs'
```

浏览器辅助服务 tests/serve_commentary_preview.py 仅读取指定冻结快照并在 runtime 中生成小样本，明确禁用真实外部点评调用。浏览器脚本 tests/check_deepseek_v9.cjs 通过 DISCOVERY_URL 指定该服务地址。
