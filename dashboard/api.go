// api.go — 六个只读接口。JSON 结构必须与前端契约逐字段对齐
// （前端 `index.html` / `analysis.js` 直接读这些键，改名字就是静默白屏）。
//
// 三条最容易被忽略、踩了就静默出错的约定：
//  1. **可空列一律用指针**。前端用 `Number.isFinite` 判有效，把 NULL 落成 0 会被当成
//     「有 0 个成就」而不是「无数据」。
//  2. **空列表要序列化成 `[]` 而不是 `null`**。Go 的 nil 切片会变成 null，前端遍历即报错。
//     所以所有列表字段都显式初始化成空切片。
//  3. **`ingest_progress` 必须用下面那份 9 列显式列表**，不能 `SELECT *`：视图的物理列序是
//     `source, kind, daily_quota, monthly_quota, total, …`，按位置取会整体错位。
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ── SQL：逐条对应原 Python 版的查询，只去掉写路径 ────────────────────────────

const (
	sqlStatusCounts = `SELECT status, count(*) FROM fetch_tasks GROUP BY status`
	sqlTaskTotal    = `SELECT count(*) FROM fetch_tasks`
	sqlGamesTotal   = `SELECT count(*) FROM games`

	// 逐源进度。显式 9 列，理由见文件头第 3 条
	sqlSources = `SELECT source, total, ok, empty, skipped, error, exhausted, pending, actionable
	              FROM ingest_progress WHERE total > 0 ORDER BY source`

	sqlCntAchievements      = `SELECT count(*) FROM achievements`
	sqlCntAchievementsNamed = `SELECT count(*) FROM achievements WHERE display_name IS NOT NULL`
	sqlCntGamesWithAch      = `SELECT count(DISTINCT appid) FROM achievements`
	sqlCntAppdetails        = `SELECT count(*) FROM steam_appdetails`
	sqlCntSteamspy          = `SELECT count(*) FROM steamspy_games`
	sqlCntRawg              = `SELECT count(*) FROM rawg_games`
	sqlCntGameTags          = `SELECT count(*) FROM game_tags`
	sqlCntGamesWithTags     = `SELECT count(DISTINCT appid) FROM game_tags WHERE source = 'steamspy'`
	sqlMappingUnresolved    = `SELECT count(*) FROM mapping_issues WHERE NOT resolved`

	sqlVersions = `SELECT version, built_at, note FROM dataset_versions
	               ORDER BY built_at DESC NULLS LAST LIMIT 5`

	sqlGame             = `SELECT appid, name_en, name_zh FROM games WHERE appid = $1`
	sqlGameTasks        = `SELECT source, status, attempts, last_error FROM fetch_tasks WHERE appid = $1`
	sqlGameAchievements = `SELECT position, api_name, display_name, percent::float8
	                       FROM achievements WHERE appid = $1 ORDER BY position`
	sqlGameCntAppdetails = `SELECT count(*) FROM steam_appdetails WHERE appid = $1`
	sqlGameCntSteamspy   = `SELECT count(*) FROM steamspy_games WHERE appid = $1`
	sqlGameCntRawg       = `SELECT count(*) FROM rawg_games WHERE appid = $1`
	sqlGameCntTags       = `SELECT count(*) FROM game_tags WHERE appid = $1`
	sqlGameLastLog       = `SELECT max(fetched_at) FROM ingest_log WHERE appid = $1`

	sqlGameAppdetails = `SELECT type, is_free, price_cents, release_date, developers, publishers,
	                     valve_genres, valve_categories, recommendations
	                     FROM steam_appdetails WHERE appid = $1`
	sqlGameSteamspy = `SELECT owners, ccu, positive, negative, average_forever, median_forever
	                   FROM steamspy_games WHERE appid = $1`
	// rating 是 NUMERIC，显式 ::float8 免得走 pgtype.Numeric 再转一道
	sqlGameRawg = `SELECT metacritic, rating::float8, ratings_count, genres, playtime, added_count,
	               status_yet, status_owned, status_beaten, status_toplay, status_dropped, status_playing
	               FROM rawg_games WHERE appid = $1`

	sqlGenres         = `SELECT genre, count(*) AS n FROM steam_appdetails, unnest(valve_genres) AS genre GROUP BY 1 ORDER BY 2 DESC`
	sqlGenresCoverage = `SELECT count(*) FROM steam_appdetails WHERE array_length(valve_genres, 1) > 0`
	sqlTags           = `SELECT tag, count(*) AS games, coalesce(sum(votes), 0) AS votes FROM game_tags WHERE source = 'steamspy' GROUP BY tag ORDER BY games DESC`
	sqlTagsCoverage   = `SELECT count(DISTINCT appid) FROM game_tags WHERE source = 'steamspy'`
)

// 六个源在「逐源落地」里的展示顺序，与 Python 版一致（不是按字母序）
var gameSourceOrder = []string{
	"appdetails_en", "appdetails_zh", "global_ach", "community_ach", "steamspy", "rawg",
}

// ── 响应结构体 ────────────────────────────────────────────────────────────
// 字段顺序刻意与 Python 版一致，便于与基线做逐字段比对。

type sourceProgress struct {
	Source     string `json:"source"`
	Total      int64  `json:"total"`
	Ok         int64  `json:"ok"`
	Empty      int64  `json:"empty"`
	Skipped    int64  `json:"skipped"`
	Error      int64  `json:"error"`
	Exhausted  int64  `json:"exhausted"`
	Pending    int64  `json:"pending"`
	Actionable int64  `json:"actionable"`
	Missing    int64  `json:"missing"`
}

type tableCounts struct {
	Achievements      int64 `json:"achievements"`
	AchievementsNamed int64 `json:"achievements_named"`
	GamesWithAch      int64 `json:"games_with_ach"`
	SteamAppdetails   int64 `json:"steam_appdetails"`
	SteamspyGames     int64 `json:"steamspy_games"`
	RawgGames         int64 `json:"rawg_games"`
	GameTags          int64 `json:"game_tags"`
	GamesWithTags     int64 `json:"games_with_tags"`
}

type versionRow struct {
	Version string  `json:"version"`
	BuiltAt *string `json:"built_at"`
	Note    *string `json:"note"`
}

type progressResp struct {
	Total             int64            `json:"total"`
	Games             int64            `json:"games"`
	ByStatus          map[string]int64 `json:"by_status"`
	Sources           []sourceProgress `json:"sources"`
	Tables            tableCounts      `json:"tables"`
	MappingUnresolved int64            `json:"mapping_unresolved"`
	DatasetVersions   []versionRow     `json:"dataset_versions"`
	Remaining         int64            `json:"remaining"`
	Finished          bool             `json:"finished"`
}

type gameTask struct {
	Source   string  `json:"source"`
	Status   string  `json:"status"`
	Attempts int     `json:"attempts"`
	Error    *string `json:"error"`
}

type gameSource struct {
	Source   string  `json:"source"`
	Status   string  `json:"status"`
	Attempts int     `json:"attempts"`
	Error    *string `json:"error"`
	Data     bool    `json:"data"`
	Missing  bool    `json:"missing"`
	Verdict  string  `json:"verdict"`
}

type achievementRow struct {
	Position    int     `json:"position"`
	APIName     string  `json:"api_name"`
	DisplayName string  `json:"display_name"`
	Percent     float64 `json:"percent"`
}

type gameCounts struct {
	Achievements int64 `json:"achievements"`
	Appdetails   int64 `json:"appdetails"`
	Steamspy     int64 `json:"steamspy"`
	Rawg         int64 `json:"rawg"`
	Tags         int64 `json:"tags"`
}

type appdetailsRow struct {
	Type            *string  `json:"type"`
	IsFree          *bool    `json:"is_free"`
	PriceCents      *int64   `json:"price_cents"`
	ReleaseDate     *string  `json:"release_date"`
	Developers      []string `json:"developers"`
	Publishers      []string `json:"publishers"`
	ValveGenres     []string `json:"valve_genres"`
	ValveCategories []string `json:"valve_categories"`
	Recommendations *int64   `json:"recommendations"`
}

type steamspyRow struct {
	Owners         *string `json:"owners"`
	CCU            *int64  `json:"ccu"`
	Positive       *int64  `json:"positive"`
	Negative       *int64  `json:"negative"`
	AverageForever *int64  `json:"average_forever"`
	MedianForever  *int64  `json:"median_forever"`
}

type rawgRow struct {
	Metacritic    *int64   `json:"metacritic"`
	Rating        *float64 `json:"rating"`
	RatingsCount  *int64   `json:"ratings_count"`
	Genres        []string `json:"genres"`
	Playtime      *int64   `json:"playtime"`
	AddedCount    *int64   `json:"added_count"`
	StatusYet     *int64   `json:"status_yet"`
	StatusOwned   *int64   `json:"status_owned"`
	StatusBeaten  *int64   `json:"status_beaten"`
	StatusToplay  *int64   `json:"status_toplay"`
	StatusDropped *int64   `json:"status_dropped"`
	StatusPlaying *int64   `json:"status_playing"`
}

type gameResp struct {
	AppID            int              `json:"appid"`
	Name             *string          `json:"name"`
	NameZh           *string          `json:"name_zh"`
	InFrame          bool             `json:"in_frame"`
	Tasks            []gameTask       `json:"tasks"`
	Sources          []gameSource     `json:"sources"`
	MissingSources   []string         `json:"missing_sources"`
	AchievementsList []achievementRow `json:"achievements_list"`
	Counts           gameCounts       `json:"counts"`
	Appdetails       *appdetailsRow   `json:"appdetails"`
	Steamspy         *steamspyRow     `json:"steamspy"`
	Rawg             *rawgRow         `json:"rawg"`
	LastFetchedAt    *string          `json:"last_fetched_at"`
}

type genreItem struct {
	Genre string `json:"genre"`
	Count int64  `json:"count"`
}

type genresResp struct {
	GamesWithGenres int64       `json:"games_with_genres"`
	Genres          []genreItem `json:"genres"`
}

type tagItem struct {
	Tag   string `json:"tag"`
	Games int64  `json:"games"`
	Votes int64  `json:"votes"`
}

type tagsResp struct {
	GamesWithTags int64     `json:"games_with_tags"`
	Tags          []tagItem `json:"tags"`
}

// ── 服务 ──────────────────────────────────────────────────────────────────

type api struct {
	pool       *pgxpool.Pool
	reportPath string
}

// isoTime 输出与 Python `datetime.isoformat()` 一致的字符串：
// 微秒为 0 时整段省略，非 0 时固定 6 位（**不裁掉末尾的 0**）；
// UTC 写作 `+00:00` 而不是 Go 默认的 `Z`。
//
// ⚠️ 必须先 `.UTC()`：pgx 解 timestamptz 时走的是 time.Unix，返回的是**本地时区**的
// time.Time。不归一化的话，同一个时刻在不同 TZ 的机器上会渲染成不同偏移
// （本机实测输出 `+08:00`，与 Python 的 `+00:00` 不一致）。前端虽然用
// `new Date(...)` 按浏览器时区显示、不受影响，但同一份数据在两个后端上给出不同
// 字符串是没必要的隐患。
func isoTime(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond() == 0 {
		return t.Format("2006-01-02T15:04:05-07:00")
	}
	return t.Format("2006-01-02T15:04:05.000000-07:00")
}

func isoTimePtr(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := isoTime(*t)
	return &s
}

// writeJSON 统一出口。SetEscapeHTML(false) 是为了和 Python 的输出一致：
// 默认会把 `&`、`<`、`>` 转成 \u0026 之类，虽然仍是合法 JSON，但没必要。
func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(payload)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// fail 收口查询错误：记日志 + 回 500 JSON（截断到 300 字符，与 Python 版一致）。
func fail(w http.ResponseWriter, err error) {
	if len(err.Error()) > 300 {
		writeError(w, http.StatusInternalServerError, err.Error()[:300])
		return
	}
	writeError(w, http.StatusInternalServerError, err.Error())
}

// ── /api/progress ─────────────────────────────────────────────────────────

func (a *api) handleProgress(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	byStatus := map[string]int64{}
	rows, err := a.pool.Query(ctx, sqlStatusCounts)
	if err != nil {
		fail(w, err)
		return
	}
	for rows.Next() {
		var status string
		var n int64
		if err := rows.Scan(&status, &n); err != nil {
			rows.Close()
			fail(w, err)
			return
		}
		byStatus[status] = n // 只为存在的状态建键，与 Python 的 dict 推导一致
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		fail(w, err)
		return
	}

	resp := progressResp{
		ByStatus:        byStatus,
		Sources:         []sourceProgress{},
		DatasetVersions: []versionRow{},
	}
	if err := a.pool.QueryRow(ctx, sqlTaskTotal).Scan(&resp.Total); err != nil {
		fail(w, err)
		return
	}
	if err := a.pool.QueryRow(ctx, sqlGamesTotal).Scan(&resp.Games); err != nil {
		fail(w, err)
		return
	}

	srcRows, err := a.pool.Query(ctx, sqlSources)
	if err != nil {
		fail(w, err)
		return
	}
	for srcRows.Next() {
		var s sourceProgress
		if err := srcRows.Scan(&s.Source, &s.Total, &s.Ok, &s.Empty, &s.Skipped,
			&s.Error, &s.Exhausted, &s.Pending, &s.Actionable); err != nil {
			srcRows.Close()
			fail(w, err)
			return
		}
		s.Missing = s.Total - s.Ok
		resp.Sources = append(resp.Sources, s)
	}
	srcRows.Close()
	if err := srcRows.Err(); err != nil {
		fail(w, err)
		return
	}

	// 落库产物：逐表真实行数
	counts := []struct {
		sql string
		dst *int64
	}{
		{sqlCntAchievements, &resp.Tables.Achievements},
		{sqlCntAchievementsNamed, &resp.Tables.AchievementsNamed},
		{sqlCntGamesWithAch, &resp.Tables.GamesWithAch},
		{sqlCntAppdetails, &resp.Tables.SteamAppdetails},
		{sqlCntSteamspy, &resp.Tables.SteamspyGames},
		{sqlCntRawg, &resp.Tables.RawgGames},
		{sqlCntGameTags, &resp.Tables.GameTags},
		{sqlCntGamesWithTags, &resp.Tables.GamesWithTags},
		{sqlMappingUnresolved, &resp.MappingUnresolved},
	}
	for _, c := range counts {
		if err := a.pool.QueryRow(ctx, c.sql).Scan(c.dst); err != nil {
			fail(w, err)
			return
		}
	}

	verRows, err := a.pool.Query(ctx, sqlVersions)
	if err != nil {
		fail(w, err)
		return
	}
	defer verRows.Close()
	for verRows.Next() {
		var (
			v       versionRow
			builtAt *time.Time
		)
		if err := verRows.Scan(&v.Version, &builtAt, &v.Note); err != nil {
			fail(w, err)
			return
		}
		v.BuiltAt = isoTimePtr(builtAt)
		resp.DatasetVersions = append(resp.DatasetVersions, v)
	}
	if err := verRows.Err(); err != nil {
		fail(w, err)
		return
	}

	resp.Remaining = byStatus["pending"] + byStatus["error"]
	resp.Finished = byStatus["pending"] == 0
	writeJSON(w, http.StatusOK, resp)
}

// ── /api/game ─────────────────────────────────────────────────────────────

func (a *api) handleGame(w http.ResponseWriter, r *http.Request) {
	appid, err := strconv.Atoi(r.URL.Query().Get("appid"))
	if err != nil || appid <= 0 {
		writeError(w, http.StatusNotFound, "appid 必须是正整数")
		return
	}
	ctx := r.Context()

	var (
		name   *string
		nameZh *string
	)
	gameErr := a.pool.QueryRow(ctx, sqlGame, appid).Scan(&appid, &name, &nameZh)
	if gameErr != nil && !errors.Is(gameErr, pgx.ErrNoRows) {
		fail(w, gameErr)
		return
	}
	hasGame := gameErr == nil

	tasks := []gameTask{}
	taskBySource := map[string]gameTask{}
	taskRows, err := a.pool.Query(ctx, sqlGameTasks, appid)
	if err != nil {
		fail(w, err)
		return
	}
	for taskRows.Next() {
		var t gameTask
		if err := taskRows.Scan(&t.Source, &t.Status, &t.Attempts, &t.Error); err != nil {
			taskRows.Close()
			fail(w, err)
			return
		}
		tasks = append(tasks, t)
		taskBySource[t.Source] = t
	}
	taskRows.Close()
	if err := taskRows.Err(); err != nil {
		fail(w, err)
		return
	}

	// 游戏行与任务行都没有才算不在库中——只有任务没有 games 行的情况是正常返回
	if !hasGame && len(tasks) == 0 {
		writeError(w, http.StatusNotFound, fmt.Sprintf("appid=%d 不在库中", appid))
		return
	}
	// Python 版按 source 排序输出，这里用 Go 的排序保证与它逐字一致（不依赖库的排序规则）
	sort.Slice(tasks, func(i, j int) bool { return tasks[i].Source < tasks[j].Source })

	achievements := []achievementRow{}
	achRows, err := a.pool.Query(ctx, sqlGameAchievements, appid)
	if err != nil {
		fail(w, err)
		return
	}
	for achRows.Next() {
		var ach achievementRow
		if err := achRows.Scan(&ach.Position, &ach.APIName, &ach.DisplayName, &ach.Percent); err != nil {
			achRows.Close()
			fail(w, err)
			return
		}
		achievements = append(achievements, ach)
	}
	achRows.Close()
	if err := achRows.Err(); err != nil {
		fail(w, err)
		return
	}

	resp := gameResp{
		AppID:            appid,
		Name:             name,
		NameZh:           nameZh,
		InFrame:          hasGame,
		Tasks:            tasks,
		Sources:          []gameSource{},
		MissingSources:   []string{},
		AchievementsList: achievements,
	}
	// 成就数用列表长度，与 Python 版一致（不是再查一次 count）
	resp.Counts.Achievements = int64(len(achievements))

	gameCnts := []struct {
		sql string
		dst *int64
	}{
		{sqlGameCntAppdetails, &resp.Counts.Appdetails},
		{sqlGameCntSteamspy, &resp.Counts.Steamspy},
		{sqlGameCntRawg, &resp.Counts.Rawg},
		{sqlGameCntTags, &resp.Counts.Tags},
	}
	for _, c := range gameCnts {
		if err := a.pool.QueryRow(ctx, c.sql, appid).Scan(c.dst); err != nil {
			fail(w, err)
			return
		}
	}

	var lastLog *time.Time
	if err := a.pool.QueryRow(ctx, sqlGameLastLog, appid).Scan(&lastLog); err != nil {
		fail(w, err)
		return
	}
	resp.LastFetchedAt = isoTimePtr(lastLog)

	// 逐源落地。verdict 区分「拿到了 / 该源确实没有 / 还没拿到」三种，避免把
	// 「该源没有这份数据」误报成「缺数据要补抓」
	dataOf := map[string]int64{
		"appdetails_en": resp.Counts.Appdetails, "appdetails_zh": resp.Counts.Appdetails,
		"global_ach": resp.Counts.Achievements, "community_ach": resp.Counts.Achievements,
		"steamspy": resp.Counts.Steamspy, "rawg": resp.Counts.Rawg,
	}
	for _, src := range gameSourceOrder {
		t, hasTask := taskBySource[src]
		row := gameSource{Source: src}
		if hasTask {
			row.Status = t.Status
			row.Attempts = t.Attempts
			row.Error = t.Error
		} else {
			row.Status = "no_task"
		}
		row.Data = dataOf[src] > 0
		row.Missing = row.Status == "pending" || row.Status == "error" ||
			row.Status == "exhausted" || row.Status == "no_task" ||
			(row.Status == "ok" && !row.Data)

		switch {
		case row.Data:
			row.Verdict = "ok"
		case row.Status == "empty" || row.Status == "skipped":
			row.Verdict = "no_data"
		default:
			row.Verdict = "gap"
		}
		resp.Sources = append(resp.Sources, row)
		if row.Missing {
			resp.MissingSources = append(resp.MissingSources, src)
		}
	}

	resp.Appdetails, err = a.gameAppdetails(ctx, appid)
	if err != nil {
		fail(w, err)
		return
	}
	resp.Steamspy, err = a.gameSteamspy(ctx, appid)
	if err != nil {
		fail(w, err)
		return
	}
	resp.Rawg, err = a.gameRawg(ctx, appid)
	if err != nil {
		fail(w, err)
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func (a *api) gameAppdetails(ctx context.Context, appid int) (*appdetailsRow, error) {
	var (
		row         appdetailsRow
		releaseDate *time.Time
	)
	err := a.pool.QueryRow(ctx, sqlGameAppdetails, appid).Scan(
		&row.Type, &row.IsFree, &row.PriceCents, &releaseDate,
		&row.Developers, &row.Publishers, &row.ValveGenres, &row.ValveCategories,
		&row.Recommendations,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if releaseDate != nil {
		s := releaseDate.Format("2006-01-02")
		row.ReleaseDate = &s
	}
	return &row, nil
}

func (a *api) gameSteamspy(ctx context.Context, appid int) (*steamspyRow, error) {
	var row steamspyRow
	err := a.pool.QueryRow(ctx, sqlGameSteamspy, appid).Scan(
		&row.Owners, &row.CCU, &row.Positive, &row.Negative,
		&row.AverageForever, &row.MedianForever,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &row, nil
}

func (a *api) gameRawg(ctx context.Context, appid int) (*rawgRow, error) {
	var row rawgRow
	err := a.pool.QueryRow(ctx, sqlGameRawg, appid).Scan(
		&row.Metacritic, &row.Rating, &row.RatingsCount, &row.Genres, &row.Playtime,
		&row.AddedCount, &row.StatusYet, &row.StatusOwned, &row.StatusBeaten,
		&row.StatusToplay, &row.StatusDropped, &row.StatusPlaying,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &row, nil
}

// ── /api/genres 与 /api/tags ──────────────────────────────────────────────

func (a *api) handleGenres(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	resp := genresResp{Genres: []genreItem{}}

	rows, err := a.pool.Query(ctx, sqlGenres)
	if err != nil {
		fail(w, err)
		return
	}
	defer rows.Close()
	for rows.Next() {
		var g genreItem
		if err := rows.Scan(&g.Genre, &g.Count); err != nil {
			fail(w, err)
			return
		}
		resp.Genres = append(resp.Genres, g)
	}
	if err := rows.Err(); err != nil {
		fail(w, err)
		return
	}
	if err := a.pool.QueryRow(ctx, sqlGenresCoverage).Scan(&resp.GamesWithGenres); err != nil {
		fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func (a *api) handleTags(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	resp := tagsResp{Tags: []tagItem{}}

	rows, err := a.pool.Query(ctx, sqlTags)
	if err != nil {
		fail(w, err)
		return
	}
	defer rows.Close()
	for rows.Next() {
		var t tagItem
		if err := rows.Scan(&t.Tag, &t.Games, &t.Votes); err != nil {
			fail(w, err)
			return
		}
		resp.Tags = append(resp.Tags, t)
	}
	if err := rows.Err(); err != nil {
		fail(w, err)
		return
	}
	if err := a.pool.QueryRow(ctx, sqlTagsCoverage).Scan(&resp.GamesWithTags); err != nil {
		fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// ── /api/analysis ─────────────────────────────────────────────────────────

// reportFile 只取面板需要的三个 metadata 键，story 部分原样透传。
//
// stories 用 json.RawMessage：原样搬运字节，避免数字被 float64 重新格式化
// （成就数、评价数都是大整数，来回转换没有必要引入精度话题）。
type reportFile struct {
	Metadata           map[string]json.RawMessage `json:"metadata"`
	Stories            json.RawMessage            `json:"stories"`
	GeneratedAt        *string                    `json:"generated_at"`
	StoriesGeneratedAt *string                    `json:"stories_generated_at"`
}

// analysisResp 与 Python 版的键序一致（metadata / stories / generated_at）
type analysisResp struct {
	Metadata    map[string]json.RawMessage `json:"metadata"`
	Stories     json.RawMessage            `json:"stories"`
	GeneratedAt *string                    `json:"generated_at"`
}

func (a *api) handleAnalysis(w http.ResponseWriter, r *http.Request) {
	raw, err := os.ReadFile(a.reportPath)
	if err != nil {
		// 报告是派生数据、不入 git，所以缺文件是**预期内**的情况，给前端一句能显示的说明
		writeError(w, http.StatusServiceUnavailable,
			"展示数据尚未生成，请按命令手册生成数据故事后重试。")
		return
	}
	var f reportFile
	if err := json.Unmarshal(raw, &f); err != nil {
		fail(w, err)
		return
	}

	// generated_at 优先取 stories_generated_at（每次刷新故事都会更新它），
	// 没有才退回 generated_at
	generatedAt := f.GeneratedAt
	if f.StoriesGeneratedAt != nil {
		generatedAt = f.StoriesGeneratedAt
	}

	metadata := map[string]json.RawMessage{}
	for _, k := range []string{"version", "games", "built_at"} {
		if v, ok := f.Metadata[k]; ok {
			metadata[k] = v
		} else {
			metadata[k] = json.RawMessage("null") // 缺失键输出 null，与 Python 的 .get(key) 一致
		}
	}
	stories := f.Stories
	if len(stories) == 0 {
		stories = json.RawMessage("null")
	}

	writeJSON(w, http.StatusOK, analysisResp{
		Metadata:    metadata,
		Stories:     stories,
		GeneratedAt: generatedAt,
	})
}
