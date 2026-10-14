# ZZY个人目录交付实施计划

**Goal:** 在最新main基准上准备仅修改result/ZZY的可运行交付，保留已验证的评分、来源和数据版本。

**Architecture:** 原推荐模块按字节复制到个人目录内的私有modeling/recommendation包。run.py只给本进程增加个人包搜索路径，提供serve、baseline、check、evaluate入口。默认数据路径位于个人目录，支持显式外部只读data-root。源码摘要绑定保持有效；正式人工流程仍在旧研究快照留档，当前交付复现AI辅助指标。

**Tech Stack:** Python 3.13、标准库HTTP服务、现有SQLAlchemy依赖、已有冻结JSON/GZIP图谱；不改共享依赖和数据库。

- [x] 1. 以刚获取的main提交abcbd81e创建独立装配副本，保留原开发目录、原System32项目和其他成员文件。已确认新run.py不存在，旧117文件包暂停。
- [x] 2. 根据AST相对导入闭包复制17个原模块和四组静态资源，所有原文件按SHA逐字节核对；新增run.py与本地AI分析入口，所有写出限个人runtime目录。
- [x] 3. 编写个人README、report、experiments、运行/数据/API/上传文档，保存两份既有AI指标及来源摘要；绘制带样本范围说明的结果图。
- [x] 4. 实际执行help、离线数据check和AI指标复现；启动迁移后的页面，核对版本与原版一致，读取单/多游戏、年份、搜索、错误响应并检查路径来源。按当前AGENTS做真实检查，不新增pytest用例。
- [x] 5. 只收录result/ZZY的代码/报告/图表，数据与运行日志忽略；生成新版代码ZIP及独立数据ZIP，验证CRC、SHA与main基准变更范围，无Git暂存/提交/推送。
- [x] 6. 保留可预览的装配副本与运行地址，更新旧开发入口指向新版，T5.1本地准备完成、组员独立运行保持待验收。

可核对命令：

```powershell
python result/ZZY/run.py --help
python result/ZZY/run.py check --data-root <冻结输入目录>
python result/ZZY/run.py evaluate --input-dir <协议排名及AI原始表目录> --output-dir result/ZZY/runtime/replay-new
python result/ZZY/run.py serve --data-root <冻结输入目录> --port 8606
git status --short
```

占位路径仅用于解释输入位置；实际执行和交付说明将记录可复制的具体命令。数据从现有本地冻结输入读取，不重新抽样或访问共享库。首次真实启动应复现原query-view版本，代码与页面文件不作行为调整。
