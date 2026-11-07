"""只读查询云库，寻找 SteamSpy 前十标签相似而好评率不同的游戏。"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from sqlalchemy import text

from cleaning.db import get_engine


def main() -> None:
    """比较至少一千条评价、至少十个有效标签的游戏，不写数据库。"""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout='30s'"))
            games = {
                row.appid: dict(row._mapping)
                for row in conn.execute(text("""
                    SELECT g.appid, g.name_en, g.name_zh, s.positive, s.negative,
                           s.fetched_at
                    FROM games g JOIN steamspy_games s USING(appid)
                    WHERE s.positive >= 0 AND s.negative >= 0
                      AND s.positive::bigint+s.negative >= 1000
                """))
            }
            tags: dict[int, list[str]] = defaultdict(list)
            for row in conn.execute(text("""
                SELECT t.appid,t.tag FROM game_tags t
                JOIN steamspy_games s USING(appid)
                WHERE t.source='steamspy' AND t.kind='theme'
                  AND t.votes > 0 AND s.positive >= 0 AND s.negative >= 0
                  AND s.positive::bigint+s.negative >= 1000
                ORDER BY t.appid,t.votes DESC,t.tag
            """)):
                if len(tags[row.appid]) < 10:
                    tags[row.appid].append(row.tag)
    finally:
        engine.dispose()
    sets = {appid: set(values) for appid, values in tags.items() if len(values) == 10}
    pairs = []
    similar_count = 0
    for a, b in combinations(sets, 2):
        common = sets[a] & sets[b]
        if len(common) < 8:
            continue
        similar_count += 1
        ga, gb = games[a], games[b]
        pa = 100 * ga['positive'] / (ga['positive'] + ga['negative'])
        pb = 100 * gb['positive'] / (gb['positive'] + gb['negative'])
        gap = abs(pa - pb)
        if gap >= 25:
            pairs.append((len(common), gap, a, b, pa, pb, sorted(common)))
    print(f'Eligible games: {len(sets)}; pairs sharing >=8/10 tags and gap >=25pp: {len(pairs)}')
    print(f'All pairs sharing >=8/10 tags: {similar_count}; descriptive fraction: {len(pairs)/similar_count:.2%}')
    for n, gap, a, b, pa, pb, common in sorted(pairs, reverse=True)[:10]:
        print(f'COMMON={n}/10 JACCARD={n/(20-n):.3f} GAP={gap:.2f}pp')
        for appid, rate in [(a, pa), (b, pb)]:
            g = games[appid]
            print(f"  {appid} {g['name_en']} / {g['name_zh']} | {rate:.2f}% | n={g['positive']+g['negative']} | fetched={g['fetched_at']} | tags={tags[appid]}")
        print(f'  Shared: {common}')


if __name__ == '__main__':
    main()
