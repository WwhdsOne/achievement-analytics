package main

import (
	"context"
	"net/http"
	"sync"
	"time"
)

// 所有聚合来自当前源表：一个语句得到一致的统计快照，不写库、不改结构。
// 成就先按游戏聚合，以一次扫描同时计算总量、分布与稀有数量。
const sqlOverview = `WITH ach AS (
 SELECT appid, count(*) AS n,
 count(*) FILTER (WHERE percent < 1) AS rare,
 count(*) FILTER (WHERE percent >= 50) AS common
 FROM achievements GROUP BY appid
), reviews AS (
 SELECT g.appid, CASE WHEN s.positive IS NOT NULL AND s.negative IS NOT NULL
 THEN s.positive::bigint+s.negative ELSE ss.review_count::bigint END AS n
 FROM games g LEFT JOIN steamspy_games s USING(appid)
 LEFT JOIN store_search_games ss USING(appid)
), ranked AS (
 SELECT n, row_number() OVER (ORDER BY n DESC, appid) AS pos, count(*) OVER () AS total
 FROM reviews WHERE n >= 0
), tags AS (
 SELECT count(*) AS relations, count(DISTINCT appid) AS games, count(DISTINCT tag) AS distinct_tags
 FROM game_tags WHERE source='steamspy'
), payments AS (
 SELECT count(*) FILTER (WHERE d.is_free) AS free,
 count(*) FILTER (WHERE NOT d.is_free) AS paid,
 count(*) FILTER (WHERE d.is_free IS NULL) AS unknown
 FROM games g LEFT JOIN steam_appdetails d USING(appid)
)
SELECT
 (SELECT count(*) FROM games),
 (SELECT coalesce(sum(n),0)::bigint FROM ach), (SELECT count(*) FROM ach),
 (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n)::float8 FROM ach),
 (SELECT count(*) FROM ach WHERE n >= 1000),
 (SELECT coalesce(sum(rare),0)::bigint FROM ach), (SELECT coalesce(sum(common),0)::bigint FROM ach),
 tags.relations, tags.games, tags.distinct_tags,
 (SELECT count(*) FROM ranked),
 (SELECT coalesce(sum(n),0)::bigint FROM ranked),
 (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n)::float8 FROM ranked),
 (SELECT count(*) FROM ranked WHERE pos <= ceil(total*0.01)),
 (SELECT coalesce(sum(n),0)::bigint FROM ranked WHERE pos <= ceil(total*0.01)),
 (SELECT count(*) FROM ranked WHERE n = 0),
 (SELECT count(*) FROM ranked WHERE n BETWEEN 1 AND 99),
 (SELECT count(*) FROM ranked WHERE n BETWEEN 100 AND 999),
 (SELECT count(*) FROM ranked WHERE n BETWEEN 1000 AND 9999),
 (SELECT count(*) FROM ranked WHERE n >= 10000),
 payments.free, payments.paid, payments.unknown
FROM tags CROSS JOIN payments`

type overviewCounts struct {
	Games              int64    `json:"games"`
	Achievements       int64    `json:"achievements"`
	GamesWithAch       int64    `json:"games_with_achievements"`
	MedianAch          *float64 `json:"median_achievements"`
	ThousandAchGames   int64    `json:"thousand_achievement_games"`
	RareAchievements   int64    `json:"rare_achievements"`
	CommonAchievements int64    `json:"common_achievements"`
	TagRelations       int64    `json:"tag_relations"`
	GamesWithTags      int64    `json:"games_with_tags"`
	DistinctTags       int64    `json:"distinct_tags"`
}

type overviewReviews struct {
	Games      int64    `json:"games"`
	Total      int64    `json:"total"`
	Median     *float64 `json:"median"`
	TopGames   int64    `json:"top_games"`
	TopReviews int64    `json:"top_reviews"`
	Zero       int64    `json:"zero"`
	Under100   int64    `json:"one_to_99"`
	Under1000  int64    `json:"hundred_to_999"`
	Under10000 int64    `json:"thousand_to_9999"`
	Over10000  int64    `json:"ten_thousand_plus"`
}

type overviewPayments struct {
	Free    int64 `json:"free"`
	Paid    int64 `json:"paid"`
	Unknown int64 `json:"unknown"`
}

type overviewResponse struct {
	Counts      overviewCounts   `json:"counts"`
	Reviews     overviewReviews  `json:"reviews"`
	Payments    overviewPayments `json:"payments"`
	GeneratedAt string           `json:"generated_at"`
}

// 总览缓存只有一个条目，合并冷启动请求；不会增加数据库连接池上限。
var overviewCache = struct {
	sync.Mutex
	Data  *overviewResponse
	Until time.Time
}{}

// overview 聚合当前库并缓存五分钟；所有空中位数保留为 null。
func (a *api) overview(ctx context.Context) (*overviewResponse, error) {
	overviewCache.Lock()
	defer overviewCache.Unlock()
	if overviewCache.Data != nil && time.Now().Before(overviewCache.Until) {
		return overviewCache.Data, nil
	}
	resp := &overviewResponse{}
	c, r, p := &resp.Counts, &resp.Reviews, &resp.Payments
	err := a.pool.QueryRow(ctx, sqlOverview).Scan(
		&c.Games, &c.Achievements, &c.GamesWithAch, &c.MedianAch, &c.ThousandAchGames,
		&c.RareAchievements, &c.CommonAchievements, &c.TagRelations, &c.GamesWithTags, &c.DistinctTags,
		&r.Games, &r.Total, &r.Median, &r.TopGames, &r.TopReviews,
		&r.Zero, &r.Under100, &r.Under1000, &r.Under10000, &r.Over10000,
		&p.Free, &p.Paid, &p.Unknown,
	)
	if err != nil {
		return nil, err
	}
	resp.GeneratedAt = isoTime(time.Now().UTC())
	overviewCache.Data, overviewCache.Until = resp, time.Now().Add(5*time.Minute)
	return resp, nil
}

// handleOverview 提供只读的数据全景，不触发抓取或任何建模实验。
func (a *api) handleOverview(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()
	resp, err := a.overview(ctx)
	if err != nil {
		fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}
