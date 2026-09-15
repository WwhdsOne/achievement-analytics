"""cleaning.schema — 数据 schema 定义

所有 schema 变更必须同步更新本文件并通知全组（AGENTS.md 规定）。

使用方式:
    from cleaning.schema import STEAM_ACHIEVEMENT_SCHEMA
    # 在清洗流程中用 schema 校验 DataFrame 字段与类型
"""

# ── Steam 成就数据 schema ─────────────────────────────────

STEAM_ACHIEVEMENT_SCHEMA: dict[str, str] = {
    "steamid": "int64",          # 玩家 Steam ID（processed 层为哈希值）
    "appid": "int64",            # 游戏 App ID
    "achievement_name": "str",   # 成就 API 名称
    "achieved": "int8",          # 0 = 未解锁, 1 = 已解锁
    "unlocktime": "int64",       # Unix timestamp（0 表示未解锁）
}

# ── Steam 玩家游戏库 schema ───────────────────────────────

STEAM_OWNED_GAMES_SCHEMA: dict[str, str] = {
    "steamid": "int64",
    "appid": "int64",
    "playtime_forever": "int64",   # 总游玩时长（分钟）
    "playtime_2weeks": "int64",    # 近两周游玩时长（分钟），可为 0
}

# ── SteamSpy 游戏信息 schema ──────────────────────────────

STEAMSPY_GAME_SCHEMA: dict[str, str] = {
    "appid": "int64",
    "name": "str",
    "owners": "str",               # 估算销量区间，如 "1,000,000 .. 2,000,000"
    "average_forever": "int64",    # 平均游玩时长（分钟）
    "median_forever": "int64",     # 中位游玩时长（分钟）
    "ccu": "int64",                # 峰值同时在线
    "price": "str",                # 价格（美分），可为 "0"
    "tags": "str",                 # JSON 格式标签
}


# TODO: PSN 奖杯 schema（W2-3 视反爬情况定义）
# TODO: 小黑盒 schema
