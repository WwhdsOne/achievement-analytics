package main

import (
	"context"
	"crypto/rand"
	"math/big"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

// 探索直接读取现有源表；不运行分析脚本、不抓取外部站点、不写共享库。
// 排名按 SteamSpy 好评+差评数量，缺失任一项时回退到商店搜索的评价数。
// hltb_* 三列是 HowLongToBeat 时长分解（名称匹配导入，覆盖不全，NULL 表示无数据）。
const exploreBase = `SELECT g.appid, g.name_en, g.name_zh,
 CASE WHEN s.positive IS NOT NULL AND s.negative IS NOT NULL
      THEN s.positive::bigint + s.negative ELSE ss.review_count::bigint END AS reviews,
 CASE WHEN s.positive IS NOT NULL AND s.negative IS NOT NULL
      THEN CASE WHEN s.positive::bigint+s.negative > 0 THEN 100.0*s.positive/(s.positive::bigint+s.negative) END
      ELSE CASE WHEN ss.review_count > 0 THEN ss.review_percent::float8 END END AS approval,
 d.is_free, d.price_cents, d.release_date::text, d.developers,
 (SELECT count(*) FROM achievements ac WHERE ac.appid = g.appid) AS ach_count,
 h.main_hours::float8, h.extra_hours::float8, h.completionist_hours::float8
 FROM games g LEFT JOIN steamspy_games s USING(appid)
 LEFT JOIN store_search_games ss USING(appid) LEFT JOIN steam_appdetails d USING(appid)
 LEFT JOIN hltb_games h USING(appid)`

const exploreReviews = `CASE WHEN s.positive IS NOT NULL AND s.negative IS NOT NULL
 THEN s.positive::bigint+s.negative ELSE ss.review_count::bigint END`

type exploreGame struct {
	AppID           int      `json:"appid"`
	Name            string   `json:"name"`
	NameZh          *string  `json:"name_zh"`
	Reviews         *int64   `json:"reviews"`
	Approval        *float64 `json:"approval"`
	IsFree          *bool    `json:"is_free"`
	PriceCents      *int64   `json:"price_cents"`
	Release         *string  `json:"release_date"`
	Developers      []string `json:"developers"`
	AchCount        int64    `json:"ach_count"`
	HltbMain        *float64 `json:"hltb_main"`
	HltbExtra       *float64 `json:"hltb_extra"`
	HltbCompletion  *float64 `json:"hltb_completionist"`
}

type exploreTag struct {
	Tag   string `json:"tag"`
	Votes *int64 `json:"votes"`
}

type sharedAchievement struct {
	AppID       int     `json:"appid"`
	Game        string  `json:"game"`
	DisplayName string  `json:"display_name"`
	Description *string `json:"description"`
	Percent     float64 `json:"percent"`
}

type exploreDetails struct {
	Game       []exploreGame       `json:"games"`
	Tags       []exploreTag        `json:"tags"`
	Related    []exploreGame       `json:"related"`
	Shared     []sharedAchievement `json:"shared"`
	Unresolved bool                `json:"mapping_unresolved"`
}

type exploreCacheEntry struct {
	Games []exploreGame
	Until time.Time
}

// 固定的三个发现列表缓存五分钟；锁合并并发缓存重建，避免反复聚合两百万成就。
var exploreCache = struct {
	sync.Mutex
	Entries map[string]exploreCacheEntry
}{Entries: map[string]exploreCacheEntry{}}

// exploreGames 执行参数化查询，保留空值并保证列表以 [] 序列化。
func (a *api) exploreGames(ctx context.Context, query string, args ...any) ([]exploreGame, error) {
	rows, err := a.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	games := []exploreGame{}
	for rows.Next() {
		var g exploreGame
		if err := rows.Scan(&g.AppID, &g.Name, &g.NameZh, &g.Reviews, &g.Approval,
			&g.IsFree, &g.PriceCents, &g.Release, &g.Developers, &g.AchCount,
			&g.HltbMain, &g.HltbExtra, &g.HltbCompletion); err != nil {
			return nil, err
		}
		if g.Developers == nil {
			g.Developers = []string{}
		}
		games = append(games, g)
	}
	return games, rows.Err()
}

// discover 缓存只读发现列表。随机入口使用 popular 的前500名，前端不呈现此筛选条件。
func (a *api) discover(ctx context.Context, mode string) ([]exploreGame, error) {
	exploreCache.Lock()
	defer exploreCache.Unlock()
	if entry, ok := exploreCache.Entries[mode]; ok && time.Now().Before(entry.Until) {
		return entry.Games, nil
	}
	query := exploreBase
	switch mode {
	case "popular":
		query += " WHERE " + exploreReviews + " > 0 ORDER BY reviews DESC NULLS LAST, g.appid LIMIT 500"
	case "free":
		query += " WHERE d.is_free = true AND " + exploreReviews + " > 0 ORDER BY reviews DESC NULLS LAST, g.appid LIMIT 8"
	case "achievements":
		query += ` JOIN (SELECT appid FROM achievements GROUP BY appid ORDER BY count(*) DESC, appid LIMIT 8) top_ach ON top_ach.appid=g.appid
		 ORDER BY ach_count DESC, g.appid`
	}
	games, err := a.exploreGames(ctx, query)
	if err == nil {
		exploreCache.Entries[mode] = exploreCacheEntry{games, time.Now().Add(5 * time.Minute)}
	}
	return games, err
}

// handleExplore 提供搜索、发现与游戏附加详情；所有操作是限时 SELECT。
func (a *api) handleExplore(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()
	if raw := r.URL.Query().Get("appid"); raw != "" {
		id, err := strconv.Atoi(raw)
		if err != nil || id <= 0 || int64(id) > 2147483647 {
			writeError(w, 400, "请输入有效的 AppID")
			return
		}
		a.exploreDetails(w, ctx, id)
		return
	}
	mode := r.URL.Query().Get("mode")
	if mode == "search" {
		q := strings.TrimSpace(r.URL.Query().Get("q"))
		if q == "" || len([]rune(q)) > 100 {
			writeError(w, 400, "请输入 1–100 字的游戏名")
			return
		}
		// % 和 _ 按字面搜索，避免用户输入变成全库通配符。
		q = strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(q)
		games, err := a.exploreGames(ctx, exploreBase+` WHERE (g.name_en ILIKE $1 OR g.name_zh ILIKE $1)
		 ORDER BY reviews DESC NULLS LAST, g.appid LIMIT 20`, "%"+q+"%")
		if err != nil {
			fail(w, err)
			return
		}
		writeJSON(w, 200, map[string]any{"games": games})
		return
	}
	if mode != "popular" && mode != "free" && mode != "achievements" && mode != "random" {
		writeError(w, 400, "未知的探索方式")
		return
	}
	cacheMode := mode
	if mode == "random" {
		cacheMode = "popular"
	}
	games, err := a.discover(ctx, cacheMode)
	if err != nil {
		fail(w, err)
		return
	}
	if mode == "random" && len(games) > 0 {
		index, err := rand.Int(rand.Reader, big.NewInt(int64(len(games))))
		if err != nil {
			fail(w, err)
			return
		}
		games = []exploreGame{games[index.Int64()]}
	} else if mode == "popular" && len(games) > 12 {
		games = games[:12]
	}
	writeJSON(w, 200, map[string]any{"games": games})
}

// exploreDetails 提供标签、开发商作品与同名成就；映射有疑义时不生成具名故事。
func (a *api) exploreDetails(w http.ResponseWriter, ctx context.Context, id int) {
	games, err := a.exploreGames(ctx, exploreBase+" WHERE g.appid=$1", id)
	if err != nil {
		fail(w, err)
		return
	}
	if len(games) == 0 {
		writeError(w, 404, "游戏尚未收录")
		return
	}
	resp := exploreDetails{Game: games, Tags: []exploreTag{}, Related: []exploreGame{}, Shared: []sharedAchievement{}}
	if err := a.pool.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM mapping_issues WHERE appid=$1 AND NOT resolved)", id).Scan(&resp.Unresolved); err != nil {
		fail(w, err)
		return
	}
	rows, err := a.pool.Query(ctx, "SELECT tag, votes FROM game_tags WHERE appid=$1 AND source='steamspy' ORDER BY votes DESC NULLS LAST, tag LIMIT 12", id)
	if err != nil {
		fail(w, err)
		return
	}
	for rows.Next() {
		var tag exploreTag
		if err := rows.Scan(&tag.Tag, &tag.Votes); err != nil {
			rows.Close()
			fail(w, err)
			return
		}
		resp.Tags = append(resp.Tags, tag)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		fail(w, err)
		return
	}
	if len(games[0].Developers) > 0 {
		resp.Related, err = a.exploreGames(ctx, exploreBase+` WHERE g.appid<>$1 AND d.developers && $2::text[]
		 ORDER BY reviews DESC NULLS LAST, g.appid LIMIT 6`, id, games[0].Developers)
		if err != nil {
			fail(w, err)
			return
		}
	}
	if !resp.Unresolved {
		// 只比较当前游戏最常见的一个具名成就；最多列三款其他游戏，避免泛化出“难度”结论。
		rows, err := a.pool.Query(ctx, `WITH selected AS (
		 SELECT display_name FROM achievements WHERE appid=$1 AND nullif(trim(display_name),'') IS NOT NULL
		 ORDER BY percent DESC, position LIMIT 1)
		 SELECT ac.appid, coalesce(nullif(g.name_zh,''),g.name_en), ac.display_name, ac.description, ac.percent::float8
		 FROM achievements ac JOIN games g USING(appid) JOIN selected s ON s.display_name=ac.display_name
		 WHERE ac.appid<>$1 AND NOT EXISTS(SELECT 1 FROM mapping_issues mi WHERE mi.appid=ac.appid AND NOT mi.resolved)
		 ORDER BY ac.percent DESC, ac.appid, ac.position LIMIT 3`, id)
		if err != nil {
			fail(w, err)
			return
		}
		for rows.Next() {
			var ach sharedAchievement
			if err := rows.Scan(&ach.AppID, &ach.Game, &ach.DisplayName, &ach.Description, &ach.Percent); err != nil {
				rows.Close()
				fail(w, err)
				return
			}
			resp.Shared = append(resp.Shared, ach)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			fail(w, err)
			return
		}
	}
	writeJSON(w, 200, resp)
}
