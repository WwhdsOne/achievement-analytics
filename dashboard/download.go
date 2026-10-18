package main

import (
	"crypto/hmac"
	"crypto/sha1"
	"encoding/base64"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"
)

const archiveName = "achievement-analytics-data.tar.gz"
const archiveBucket = "achievement-analytics"
const archiveURL = "https://achievement-analytics.oss-cn-beijing.aliyuncs.com/" + archiveName

// dataDownload streams the private OSS archive and counts starts per IP/calendar day.
type dataDownload struct {
	mu            sync.Mutex
	day           string
	hits          map[string]int
	keyID, secret string
	client        *http.Client
}

// newDataDownload loads server-only credentials; missing credentials leave a useful 503.
func newDataDownload() *dataDownload {
	d := &dataDownload{
		hits:  make(map[string]int),
		keyID: os.Getenv("OSS_ACCESS_KEY_ID"), secret: os.Getenv("OSS_ACCESS_KEY_SECRET"),
		client: &http.Client{
			Transport: &http.Transport{
				Proxy:                 http.ProxyFromEnvironment,
				DialContext:           (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
				ResponseHeaderTimeout: 30 * time.Second, TLSHandshakeTimeout: 10 * time.Second,
				IdleConnTimeout: 90 * time.Second, DisableCompression: true,
			},
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}
	return d
}

// reserve atomically reserves a start; the returned function refunds an upstream failure.
func (d *dataDownload) reserve(ip string) (func(), int, int) {
	d.mu.Lock()
	defer d.mu.Unlock()
	now := time.Now().In(time.FixedZone("Asia/Shanghai", 8*60*60))
	day := now.Format("2006-01-02")
	if d.day != day {
		d.day, d.hits = day, make(map[string]int)
	}
	if d.hits[ip] >= 5 {
		next := time.Date(now.Year(), now.Month(), now.Day()+1, 0, 0, 0, 0, now.Location())
		return nil, http.StatusTooManyRequests, int(next.Sub(now).Seconds()) + 1
	}
	// Never evict current-day counters: that would permit more than five starts.
	if _, exists := d.hits[ip]; !exists && len(d.hits) >= 100_000 {
		return nil, http.StatusServiceUnavailable, 60
	}
	d.hits[ip]++
	return func() {
		d.mu.Lock()
		defer d.mu.Unlock()
		if d.day == day {
			d.hits[ip]--
		}
	}, 0, 0
}

// ServeHTTP authenticates to OSS without exposing a reusable download URL to clients.
func (d *dataDownload) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", "GET")
		writeError(w, http.StatusMethodNotAllowed, "请使用 GET 下载数据")
		return
	}
	if d.keyID == "" || d.secret == "" {
		writeError(w, http.StatusServiceUnavailable, "数据下载暂未配置，请稍后再试")
		return
	}
	refund, status, retry := d.reserve(clientIP(r))
	if status != 0 {
		w.Header().Set("Retry-After", strconv.Itoa(retry))
		message := "每个 IP 每天最多下载 5 次，今日次数已用完，请在北京时间明天零点后再试"
		if status == http.StatusServiceUnavailable {
			message = "下载服务繁忙，请稍后再试"
		}
		writeError(w, status, message)
		return
	}
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, archiveURL, nil)
	if err != nil {
		refund()
		writeError(w, http.StatusBadGateway, "暂时无法读取数据文件")
		return
	}
	date := time.Now().UTC().Format(http.TimeFormat)
	req.Header.Set("Date", date)
	mac := hmac.New(sha1.New, []byte(d.secret))
	_, _ = io.WriteString(mac, "GET\n\n\n"+date+"\n/"+archiveBucket+"/"+archiveName)
	req.Header.Set("Authorization", "OSS "+d.keyID+":"+base64.StdEncoding.EncodeToString(mac.Sum(nil)))
	resp, err := d.client.Do(req)
	if err != nil {
		refund()
		writeError(w, http.StatusBadGateway, "暂时无法读取数据文件，本次未扣次数，请稍后重试")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		refund()
		log.Printf("数据下载：OSS 返回 HTTP %d", resp.StatusCode)
		writeError(w, http.StatusBadGateway, "暂时无法读取数据文件，本次未扣次数，请稍后重试")
		return
	}
	w.Header().Set("Content-Type", "application/gzip")
	w.Header().Set("Content-Disposition", `attachment; filename="`+archiveName+`"`)
	if resp.ContentLength >= 0 {
		w.Header().Set("Content-Length", strconv.FormatInt(resp.ContentLength, 10))
	}
	w.WriteHeader(http.StatusOK)
	if _, err := io.Copy(w, resp.Body); err != nil {
		log.Print("数据下载传输中断（本次已计数）")
	}
}
