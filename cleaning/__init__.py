"""cleaning — 数据清洗与反作弊模块

输入: data/raw/
输出: data/processed/

核心职责:
- schema 统一（见 schema.py）
- 时间戳反作弊（乱序 / 秒级全解锁 / 早于购买时间）
- 玩家 ID 哈希化
"""
