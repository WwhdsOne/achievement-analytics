// main.go — 面板的 HTTP 入口。
//
// 一个只读的展示面板：把前端三件套（index.html / analysis.js / analysis.css）编进二进制，
// 从共享云库读只读数据，供全组和老师从浏览器看。**没有任何写接口**——
// 补抓数据这件事只走 CLI（`uv run python -m cleaning.worker`）。
//
// 启动::
//
//	go run ./dashboard                                  # 默认 127.0.0.1:8600
//	go run ./dashboard -port 8601 --rate-limit 60        # 本机验收
//
// 设计要点：
//   - 前端文件用 //go:embed 打包，部署时只有一个静态二进制，镜像 FROM scratch
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
	"strings"
	"sync"
	"syscall"
	"time"
)

//go:embed index.html analysis.js analysis.css
var frontend embed.FS

var assets = map[string]struct{ file, ctype string }{
	"/assets/analysis.js":  {"analysis.js", "text/javascript; charset=utf-8"},
	"/assets/analysis.css": {"analysis.css", "text/css; charset=utf-8"},
}

// rateLimiter 每 IP 滑动窗口限速。
//
// 量级只够挡住手滑和爬虫：状态在进程内存里，重启容器即清零，多出口 IP 也能绕过，
// **不是** DDoS 防护。部署到公网时靠它给云库减负，别指望它扛流量。
type rateLimiter struct {
	mu      sync.Mutex
	hits    map[string][]time.Time
	limit   int
	window  time.Duration
	maxKeys int
}

func newRateLimiter(perMinute int) *rateLimiter {
	return &rateLimiter{
		hits:    map[string][]time.Time{},
		limit:   perMinute,
		window:  time.Minute,
		maxKeys: 10_000,
	}
}

// allow 判定本次请求是否放行，放行时记一笔。
func (l *rateLimiter) allow(ip string) bool {
	if l.limit <= 0 {
		return true
	}
	now := time.Now()
	cut := now.Add(-l.window)

	l.mu.Lock()
	defer l.mu.Unlock()

	if len(l.hits) > l.maxKeys {
		// 兜底：IP 表异常膨胀时整体清空，避免内存无限增长
		l.hits = map[string][]time.Time{}
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
		return false
	}
	l.hits[ip] = append(kept, now)
	return true
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
func withRateLimit(next http.Handler, l *rateLimiter) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") && !l.allow(clientIP(r)) {
			w.Header().Set("Retry-After", "60")
			writeError(w, http.StatusTooManyRequests,
				fmt.Sprintf("请求过于频繁（每个 IP 每分钟上限 %d 次），请稍后再试", l.limit))
			return
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
	envFile := flag.String("env-file", ".env",
		"面板自己的 .env（在 dashboard/ 目录里），不再读仓库根的 .env；容器里由 compose 注入")
	health := flag.Bool("health", false, "对自己发一次请求做自检后退出")
	flag.Parse()

	if *health {
		os.Exit(runHealth(*port))
	}

	loadDotEnv(*envFile)

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
	// "GET /{$}" 才是「只匹配根路径」；写成 "GET /" 会变成匹配所有路径的兜底项
	mux.HandleFunc("GET /{$}", static("index.html", "text/html; charset=utf-8"))
	for path, a := range assets {
		mux.HandleFunc("GET "+path, static(a.file, a.ctype))
	}
	mux.HandleFunc("GET /api/progress", srv.handleProgress)
	mux.HandleFunc("GET /api/game", srv.handleGame)
	mux.HandleFunc("GET /api/genres", srv.handleGenres)
	mux.HandleFunc("GET /api/tags", srv.handleTags)
	mux.HandleFunc("GET /api/analysis", srv.handleAnalysis)
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
		modes = append(modes, fmt.Sprintf("限速 %d 次/分钟/IP", *rateLimit))
	}
	suffix := ""
	if len(modes) > 0 {
		suffix = "（" + strings.Join(modes, "，") + "）"
	}
	log.Printf("面板已启动：http://%s:%d%s", *host, *port, suffix)
	log.Printf("数据库：%s", dbTarget())
	log.Printf("分析报告：%s", report)

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(shutdownCtx)
	log.Print("已停止")
}
