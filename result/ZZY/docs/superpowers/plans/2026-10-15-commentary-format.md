# Commentary Format Implementation Plan

**Goal:** 将已确认的短评格式应用于当前交付包。

**Architecture:** 后端返回严格校验的结构化点评；页面按固定栏目渲染，保留按需调用和缓存。没有数据库或评分改动。

**Tech Stack:** Python、httpx、原生 JavaScript、pytest、Playwright。

- [x] 修改 tests/test_deepseek_commentary.py 与 tests/test_deepseek_http.py 的模型响应样例，新增格式、长度及引用拒绝用例；使用项目虚拟环境执行 pytest，确认新结构暂时失败。
- [x] 修改 process/deepseek_commentary.py：summary/reasons/caution 契约、每理由引用校验、prompt version 升级、结果去重引用。通过上述 pytest。
- [x] 修改 query_view_assets/commentary.js、discovery.html、discovery.css：三个栏目、短理由列表、折叠引用与复位，所有模型文本使用 textContent。
- [x] 更新 tests/check_deepseek_v9.cjs 的模拟响应和断言；验证折叠、异步切换、取消、失败、缓存提示、注入文本和移动端布局。
- [x] 同步 reports/source-map.json 中本次修改文件的摘要，执行 run.verify_sources() 启动源码校验与相关现有测试（数据和评分模块未改，本轮不重复全图谱验证）；保存本轮验证结果和页面截图。

用户已批准设计，直接在本会话执行；保持其他未跟踪目录，不提交或推送。
