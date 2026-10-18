# 上传最新版v10

当前交付为 `ZZY-site-v10.zip`：包含结构化点评、可配置网站来源和新增POST接口文档；单服务四页面、中文搜索和默认只读数据库启动均保留。只上传展开后的 `result/ZZY/`，个人缓存、.env和密码不上传。v9及更早包保留为历史版本，README保持原样。组长接入见 `docs/API.md`。

## 网页上传

1. 解压新版代码ZIP，得到result文件夹，里面只有ZZY。
2. 登录GitHub，打开仓库首页 https://github.com/WwhdsOne/achievement-analytics ，确认main。
3. 从仓库根页面选择 Add file → Upload files，把整个result文件夹拖入。
4. 核对路径为result/ZZY/run.py、result/ZZY/process/database_input.py等，未多一层result；保留.gitattributes和.gitignore。数量以delivery-manifest.json为准。
5. 提交说明可填写 `ZZY: 推荐页改为面向玩家的游戏发现界面`，按小组规则提交。
6. 打开result/ZZY/README.md确认新说明为默认数据库启动。上传是覆盖同名文件，不会自动删除旧文件。

不上传ZIP本身，而是展开后的目录；数据、runtime、虚拟环境和凭据均不在新版包内。保留.gitattributes供后续Git使用，计算源码字节与v5一致。

## 已准备的本地Git副本

原开发目录、System32原项目保留，不在其中git add全部文件。之前的upload-work/zzy-main-v2曾暂存v2，本次如要用Git上传，须先换成新版文件并重新核对范围；不要直接提交旧暂存内容。此次改造只本地准备，没有执行commit或push。

默认运行者使用小组已有数据库.env，执行 `uv run python result/ZZY/run.py serve`；首次自动准备图谱，等待打印地址。详细见RUN.md。
