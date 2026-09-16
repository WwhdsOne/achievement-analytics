"""crawler — 数据采集模块

每个数据源一个模块：
- http.py        共享的限速 / 重试 / 缓存层（各模块共用）
- steam_api.py   Steam 商店 appdetails + 全局完成率 + 社区成就页（全免 key）
- steamspy.py    SteamSpy（免 key，用户标签 / owners / ccu）
- rawg.py        RAWG（需 key，评分 / 时长 / 弃坑率 / 题材标签）
- config.py      统一配置、数据路径与密钥读取
"""
