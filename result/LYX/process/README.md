# 当前DeepSeek处理程序

只保留DataAgent.py、game_intro.py、deepseek_transport.py、local_database.py、datacache.py五个模块。完整数据准备沿革、prompt契约、命令、门槛、写库保护、超时和清理后的缓存行为见[PROCESS](../docs/PROCESS.md)。本地库字段见[DATABASE_LYX](../docs/DATABASE_LYX.md)。

`datacache.csv`和`failure_data.csv`是仍由程序维护的活跃累计产物，继续Git忽略。旧runtime、网页获取逻辑、一次性导入/迁移入口已清理；离线plan不创建runtime，未来显式classify/check-connection会创建新的运行数据。清理没有执行分类，也没有修改数据库。

当前分析与数据交接位于[analysis](../analysis/README.md)，不依赖本目录运行历史。这里没有远端数据库连接、网页采集、建表/改表或旧版本缓存回放入口。
