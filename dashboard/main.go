// main.go — 面板的 HTTP 入口。
//
// 一个只读的展示面板：把前端三件套（index.html / explore.js / explore.css）编进二进制，
// 从共享云库读只读数据，供全组和老师从浏览器看。**没有任何写接口**——
// 补抓数据这件事只走 CLI（`uv run python -m cleaning.worker`）。
//
// 启动::
//
//	go run ./dashboard                                  # 默认 127.0.0.1:8600
//	go run ./dashboard -port 8601 --rate-limit 60        # 本机验收
//
// 设计要点：
//   - 小型前端用 //go:embed 打包；研究原页、原图与报告从持久化只读目录提供
//   - 只读：所有 SQL 都是 SELECT，没有 DDL、没有写库路径
//   - 限速只作用于 /api/* 且**豁免循环地址**，否则容器健康检查会把自己的限速打满
package main

import (
	"context"
	"embed"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

//go:embed index.html explore.js explore.css overview.js research.js research.css clusters.js clusters.css trends.js trends.css retention.js retention.css favicon.png
var frontend embed.FS

var assets = map[string]struct{ file, ctype string }{
	"/assets/explore.js":                                {"explore.js", "text/javascript; charset=utf-8"},
	"/assets/explore.css":                               {"explore.css", "text/css; charset=utf-8"},
	"/assets/overview.js":                               {"overview.js", "text/javascript; charset=utf-8"},
	"/assets/research.js":                               {"research.js", "text/javascript; charset=utf-8"},
	"/assets/research.css":                              {"research.css", "text/css; charset=utf-8"},
	"/assets/clusters.js":                               {"clusters.js", "text/javascript; charset=utf-8"},
	"/assets/clusters.css":                              {"clusters.css", "text/css; charset=utf-8"},
	"/assets/trends.js":                                 {"trends.js", "text/javascript; charset=utf-8"},
	"/assets/trends.css":                                {"trends.css", "text/css; charset=utf-8"},
	"/assets/retention.js":                              {"retention.js", "text/javascript; charset=utf-8"},
	"/assets/retention.css":                             {"retention.css", "text/css; charset=utf-8"},
	"/assets/research/yjh/trend-data.json":              {"trend-data.json", "application/json; charset=utf-8"},
	"/assets/research/yjh/genre-share.png":              {"figures/yjh/genre-share.png", "image/png"},
	"/assets/research/yjh/official-genre.png":           {"figures/yjh/official-genre.png", "image/png"},
	"/assets/research/yjh/theme-growth.png":             {"figures/yjh/theme-growth.png", "image/png"},
	"/assets/research/yjh/player-growth.png":            {"figures/yjh/player-growth.png", "image/png"},
	"/assets/research/ymt/cluster-data.json":            {"cluster-data.json", "application/json; charset=utf-8"},
	"/assets/research/ymt/shape-pca.png":                {"figures/ymt/shape-pca.png", "image/png"},
	"/assets/research/ymt/tier-pca.png":                 {"figures/ymt/tier-pca.png", "image/png"},
	"/favicon.png":                                      {"favicon.png", "image/png"},
	"/assets/research/zzy/current-knowledge-graph.png":  {"figures/zzy/current-knowledge-graph.png", "image/png"},
	"/assets/research/zzy/current-path-explanation.png": {"figures/zzy/current-path-explanation.png", "image/png"},
	"/assets/research/zzy/ai-method-comparison.png":     {"figures/zzy/ai-method-comparison.png", "image/png"},
	"/assets/research/zzy/ai-unknown-bounds.png":        {"figures/zzy/ai-unknown-bounds.png", "image/png"},
}

// rateLimiter 每 IP 滑动窗口限速，外加「反复触发即封禁」。
//
// 量级只够挡住手滑和爬虫：状态在进程内存里，重启容器即清零，多出口 IP 也能绕过，
// **不是** DDoS 防护。部署到公网时靠它给云库减负，别指望它扛流量。
//
// 封禁规则：同一 IP 累计被拒（429）达到 banAfter 次就封禁 banDuration 时长，
// 期间 /api/* 一律拒绝。被拒计数不随窗口滑动清零——短时间两轮触发和一轮爆发
// 超额很多次，在「是爬虫」这件事上证据等价。
type rateLimiter struct {
	mu          sync.Mutex
	hits        map[string][]time.Time
	bans        map[string]time.Time // ip → 封禁到期时刻
	strikes     map[string]int       // ip → 累计被拒次数
	limit       int
	window      time.Duration
	banAfter    int           // 第几次被拒后触发封禁
	banDuration time.Duration // 封禁时长
	maxKeys     int
}

func newRateLimiter(perMinute int) *rateLimiter {
	return &rateLimiter{
		hits:        map[string][]time.Time{},
		bans:        map[string]time.Time{},
		strikes:     map[string]int{},
		limit:       perMinute,
		window:      time.Minute,
		banAfter:    2,
		banDuration: 8 * time.Hour,
		maxKeys:     10_000,
	}
}

// verdict 是一次限速判定的结果。
type verdict struct {
	allow      bool          // 是否放行
	retryAfter int           // 拒绝时建议的 Retry-After 秒数
	banned     bool          // 拒绝是否因为处于封禁期（区别于普通超限）
	remaining  time.Duration // 封禁剩余时长，banned 时才有意义
}

// allow 判定本次请求是否放行，放行时记一笔。
func (l *rateLimiter) allow(ip string) verdict {
	if l.limit <= 0 {
		return verdict{allow: true}
	}
	now := time.Now()

	l.mu.Lock()
	defer l.mu.Unlock()

	// 封禁期内直接拒绝；到期则解除并清空被拒计数，从头再算
	if until, banned := l.bans[ip]; banned {
		if now.Before(until) {
			return verdict{retryAfter: int(until.Sub(now).Seconds()) + 1, banned: true, remaining: until.Sub(now)}
		}
		delete(l.bans, ip)
		delete(l.strikes, ip)
	}

	cut := now.Add(-l.window)
	if len(l.hits) > l.maxKeys {
		// 兜底：IP 表异常膨胀时整体清空，避免内存无限增长
		l.hits = map[string][]time.Time{}
	}
	if len(l.strikes) > l.maxKeys {
		l.strikes = map[string]int{}
	}
	if len(l.bans) > l.maxKeys {
		for k, until := range l.bans { // 先摘掉已到期的，能保住则保住
			if now.After(until) {
				delete(l.bans, k)
			}
		}
		if len(l.bans) > l.maxKeys {
			l.bans = map[string]time.Time{}
		}
	}

	// 原地过滤掉窗口外的记录
	kept := l.hits[ip][:0]
	for _, t := range l.hits[ip] {
		if t.After(cut) {
			kept = append(kept, t)
		}
	}
	if len(kept) >= l.limit {
		l.hits[ip] = kept
		l.strikes[ip]++
		if l.strikes[ip] >= l.banAfter {
			l.bans[ip] = now.Add(l.banDuration)
			delete(l.strikes, ip)
			log.Printf("已封禁 %s：累计触发限速 %d 次，时长 %s", ip, l.banAfter, l.banDuration)
		}
		return verdict{retryAfter: 60}
	}
	l.hits[ip] = append(kept, now)
	return verdict{allow: true}
}

// isLoopback 判断是否本机来源。
//
// 本机请求不计入限速：容器健康检查每 30 秒打一次，服务器上跑浏览器验收脚本时会连发
// 几十个 /api/* 请求——都不该被自己的限速挡住。
func isLoopback(ip string) bool {
	if ip == "127.0.0.1" || ip == "::1" {
		return true
	}
	parsed := net.ParseIP(ip)
	return parsed != nil && parsed.IsLoopback()
}

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// withRateLimit 只对 /api/* 限速：静态资源很便宜，限了会让限流期间的页面渲染残缺。
// 循环地址整段豁免（限速与封禁都不沾）——容器健康检查每 30 秒打一次，
// 服务器本机跑浏览器验收会连发几十个 /api/*，都不能被自己的规则挡住。
func withRateLimit(next http.Handler, l *rateLimiter) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if ip := clientIP(r); strings.HasPrefix(r.URL.Path, "/api/") && !isLoopback(ip) {
			if v := l.allow(ip); !v.allow {
				w.Header().Set("Retry-After", fmt.Sprintf("%d", v.retryAfter))
				if v.banned {
					writeError(w, http.StatusTooManyRequests,
						fmt.Sprintf("已因反复触发限速被临时封禁（每分钟上限 %d 次，触发 %d 次即封禁 %s），约剩 %s 自动解除",
							l.limit, l.banAfter, l.banDuration, v.remaining.Round(time.Minute)))
					return
				}
				writeError(w, http.StatusTooManyRequests,
					fmt.Sprintf("请求过于频繁（每个 IP 每分钟上限 %d 次），累计触发 %d 次将被临时封禁 %s，请稍后再试",
						l.limit, l.banAfter, l.banDuration))
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

// static 从嵌入的文件系统里取前端资源。
func static(name, ctype string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		b, err := frontend.ReadFile(name)
		if err != nil {
			fail(w, err)
			return
		}
		w.Header().Set("Content-Type", ctype)
		_, _ = w.Write(b)
	}
}

// staticTree 从持久化目录按原相对结构提供文件，不列目录。
//
// LYX 的交付页不是单文件：它用相对路径引用 ../docs 与 ../analysis 下的文档、原图和来源
// 明细，所以只能整棵树一起发布，逐个登记到 assets 表反而会断链。
//
// 不能用 http.FileServerFS：它会把以 /index.html 结尾的路径 301 到目录（Go 的内置行为），
// 而这里连目录索引都不提供，重定向过去只会得到一个 404。目录一律 404——静态资源不需要
// 可浏览的文件清单。
func staticTree(dir string) http.HandlerFunc {
	files := os.DirFS(dir)
	return func(w http.ResponseWriter, r *http.Request) {
		name := strings.TrimPrefix(r.URL.Path, "/")
		if name == "" || strings.HasSuffix(name, "/") {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		file, err := files.Open(name)
		if err != nil {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		defer file.Close()
		info, err := file.Stat()
		if err != nil || info.IsDir() {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		seeker, ok := file.(io.ReadSeeker)
		if !ok {
			writeError(w, http.StatusInternalServerError, "静态资源不可读")
			return
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		http.ServeContent(w, r, info.Name(), info.ModTime(), seeker)
	}
}

// runHealth 对自己发一次请求做自检，供容器健康检查使用。
//
// 镜像 FROM scratch，里面没有 shell、没有 curl，所以健康检查只能由二进制自己完成。
// 探的是 /api/progress：面板的价值就在于能读到云库，只探静态页等于没探。
func runHealth(port int) int {
	url := fmt.Sprintf("http://127.0.0.1:%d/api/progress", port)
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		fmt.Fprintln(os.Stderr, "健康检查失败：", err)
		return 1
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode != http.StatusOK {
		fmt.Fprintf(os.Stderr, "健康检查失败：HTTP %d\n", resp.StatusCode)
		return 1
	}
	return 0
}

// resolveReport 选出一个存在的分析报告路径。
//
// 面板有两种跑法，工作目录不同：容器里 CWD 是 /app、报告挂在 /app/data/processed/；
// 本机是从 `dashboard/` 目录运行、报告在仓库根的 data/processed/。所以 --report 留空时
// 按候选顺序找第一个存在的，并把选中的路径打出来——不靠猜，日志里能看到用了哪个。
// 都不存在时返回默认值，让 /api/analysis 正常返回 503 提示，而不是启动就失败。
func resolveReport(explicit string) string {
	if explicit != "" {
		return explicit
	}
	candidates := []string{
		"data/processed/analysis-report.json",    // 容器内
		"../data/processed/analysis-report.json", // 本机从 dashboard/ 运行
	}
	for _, p := range candidates {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return candidates[0]
}

func main() {
	host := flag.String("host", "127.0.0.1", "监听地址（默认仅本机）")
	port := flag.Int("port", 8600, "监听端口")
	rateLimit := flag.Int("rate-limit", 0,
		"每个 IP 每分钟对 /api/* 的请求上限；0 = 不限速（默认，本机开发用）")
	reportPath := flag.String("report", "",
		"分析报告路径；留空则自动在候选路径里找（容器内与本机两种跑法都能用）")
	contentDir := flag.String("content-dir", ".", "研究静态内容目录；本机默认 dashboard/，容器使用持久化版本目录")
	envFile := flag.String("env-file", ".env",
		"面板自己的 .env（在 dashboard/ 目录里），不再读仓库根的 .env；容器里由 compose 注入")
	recommendationURL := flag.String("recommendation-url", "", "覆盖 RECOMMENDATION_HOST/PORT 的完整内网 HTTP 地址")
	health := flag.Bool("health", false, "对自己发一次请求做自检后退出")
	flag.Parse()

	if *health {
		os.Exit(runHealth(*port))
	}

	loadDotEnv(*envFile)
	download := newDataDownload()
	recommendationTarget, err := resolveRecommendationURL(*recommendationURL)
	if err != nil {
		log.Fatal(err)
	}
	recommendation, err := recommendationHandler(recommendationTarget)
	if err != nil {
		log.Fatal(err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	pool, err := newPool(ctx)
	if err != nil {
		log.Fatalf("创建连接池失败：%v", err)
	}
	defer pool.Close()

	report := resolveReport(*reportPath)
	srv := &api{pool: pool, reportPath: report}
	mux := http.NewServeMux()
	mux.Handle("GET /download/data", download)
	// "GET /{$}" 才是「只匹配根路径」；写成 "GET /" 会变成匹配所有路径的兜底项
	mux.HandleFunc("GET /{$}", static("index.html", "text/html; charset=utf-8"))
	for path, a := range assets {
		if strings.HasPrefix(a.file, "figures/") || strings.HasSuffix(a.file, "-data.json") {
			file := a.file
			mux.HandleFunc("GET "+path, func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("X-Content-Type-Options", "nosniff")
				http.ServeFile(w, r, filepath.Join(*contentDir, file))
			})
		} else {
			mux.HandleFunc("GET "+path, static(a.file, a.ctype))
		}
	}
	// LYX 的交付页连同附件按原目录结构提供，页内 ../ 相对链接才能解析
	mux.Handle("GET /assets/research/lyx/", http.StripPrefix("/assets/research/lyx", staticTree(filepath.Join(*contentDir, "lyx"))))
	mux.HandleFunc("GET /api/progress", srv.handleProgress)
	mux.HandleFunc("GET /api/game", srv.handleGame)
	mux.HandleFunc("GET /api/explore", srv.handleExplore)
	mux.HandleFunc("GET /api/overview", srv.handleOverview)
	mux.HandleFunc("GET /api/genres", srv.handleGenres)
	mux.HandleFunc("GET /api/tags", srv.handleTags)
	mux.HandleFunc("GET /api/analysis", srv.handleAnalysis)
	mux.HandleFunc("GET /api/research/recommendation/", recommendation)
	// 兜底：未匹配的路径与方法。**必须是合法 JSON**——前端多处先 res.json() 再判
	// res.ok，回空 body 会直接抛异常。这里也是「补抓接口已删除」的落点：POST
	// /api/game/crawl 会落到这里返回 404。
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusNotFound, "not found")
	})

	httpSrv := &http.Server{
		Addr:              fmt.Sprintf("%s:%d", *host, *port),
		Handler:           withRateLimit(mux, newRateLimiter(*rateLimit)),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		if err := httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("监听 %s 失败：%v", httpSrv.Addr, err)
		}
	}()

	modes := []string{}
	if *rateLimit > 0 {
		modes = append(modes,
			fmt.Sprintf("限速 %d 次/分钟/IP", *rateLimit),
			"触发 2 次即封禁 8 小时（重启清零）")
	}
	suffix := ""
	if len(modes) > 0 {
		suffix = "（" + strings.Join(modes, "，") + "）"
	}
	log.Printf("面板已启动：http://%s:%d%s", *host, *port, suffix)
	log.Printf("数据库：%s", dbTarget())
	log.Printf("分析报告：%s", report)
	log.Printf("研究静态内容：%s", *contentDir)
	log.Printf("推荐服务：%s", recommendationTarget)

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(shutdownCtx)
	log.Print("已停止")
}
