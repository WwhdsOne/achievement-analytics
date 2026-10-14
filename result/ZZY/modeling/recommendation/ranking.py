"""三种透明标签排序；不改变默认推荐基线。"""

from __future__ import annotations

import heapq
import math

from .evaluation import TagIndex

METHODS = ('jaccard', 'coverage', 'idf')


class RankingIndex(TagIndex):
    """复用相同候选与倒排索引，按指定方法排序并提供逐项分数解释。"""

    def neighbors(self, query: set[str], exclude: int | None = None, k: int = 5,
                  method: str = 'jaccard') -> list[dict]:
        """仅返回正交集；IDF语料排除种子全部贡献，未知请求保留。"""
        if method not in METHODS or not 1 <= k <= 100 or not query:
            raise ValueError('方法、非空标签集合或k无效')
        query = {tag.strip().casefold() for tag in query if isinstance(tag, str) and tag.strip()}
        if not query:
            raise ValueError('至少需要一个非空标签')
        seed_labels = self.labels.get(exclude, set())
        n = len(self.rows) - int(exclude in self.rows)
        weights = {tag: math.log((n + 1) / (self.frequency[tag] - int(tag in seed_labels) + 1)) + 1
                   for tag in self.frequency.keys() | query} if method == 'idf' else {}
        candidates = set().union(*(self.postings.get(tag, set()) for tag in query))
        candidates.discard(exclude)
        ranked = []
        for appid in candidates:
            labels = self.labels[appid]
            shared = query & labels
            union = query | labels
            coverage = len(shared) / len(query)
            if method == 'idf':
                numerator = math.fsum(weights[t] for t in sorted(shared))
                denominator = math.fsum(weights[t] for t in sorted(union))
            else:
                numerator, denominator = len(shared), len(union)
            score = numerator / denominator
            order = (-coverage, -score, appid) if method == 'coverage' else (-score, appid)
            ranked.append((order, appid, score, numerator, denominator))
        results = []
        for _, appid, score, numerator, denominator in heapq.nsmallest(k, ranked):
            labels = self.labels[appid]
            shared = query & labels
            missing = query - labels
            def contribution(tag: str) -> dict:
                return {'tag': tag, 'weight': weights.get(tag, 1),
                        'document_frequency': self.frequency[tag] - int(tag in seed_labels)}

            contributions = [contribution(t) for t in sorted(shared)]
            results.append({
                'appid': appid, 'name': self.rows[appid].get('name_zh') or self.rows[appid]['name_en'],
                'method': method, 'score': score, 'numerator': numerator, 'denominator': denominator,
                'shared_tags': sorted(shared), 'missing_requested_tags': sorted(missing),
                'query_coverage': len(shared) / len(query), 'intersection_count': len(shared),
                'union_count': len(query | labels), 'candidate_tag_count': len(labels),
                'shared_tag_contributions': contributions,
                'union_tag_contributions': [contribution(t) for t in sorted(query | labels)],
                'idf_reference_games': n if method == 'idf' else None,
                'reason': ('请求标签覆盖率优先，其次集合Jaccard，再按appid' if method == 'coverage'
                           else 'IDF加权交集/并集，再按appid' if method == 'idf'
                           else '共同标签数/并集标签数，再按appid'),
            })
        return results
