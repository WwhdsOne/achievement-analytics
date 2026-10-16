package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// resolveRecommendationURL 按显式 URL、环境配置、默认值的顺序选择推荐服务。
func resolveRecommendationURL(explicit string) (string, error) {
	if explicit != "" {
		return explicit, nil
	}
	host := strings.TrimSpace(os.Getenv("RECOMMENDATION_HOST"))
	if host == "" {
		host = "127.0.0.1"
	}
	if strings.ContainsAny(host, "/?#@[] \t\r\n") {
		return "", fmt.Errorf("RECOMMENDATION_HOST 只填写主机名或 IP，不包含协议、端口或路径")
	}
	if strings.Contains(host, ":") && net.ParseIP(host) == nil {
		return "", fmt.Errorf("RECOMMENDATION_HOST 不包含端口，端口请填写 RECOMMENDATION_PORT")
	}
	port := strings.TrimSpace(os.Getenv("RECOMMENDATION_PORT"))
	if port == "" {
		port = "8605"
	}
	n, err := strconv.Atoi(port)
	if err != nil || n < 1 || n > 65535 {
		return "", fmt.Errorf("RECOMMENDATION_PORT 必须是1–65535的整数")
	}
	return "http://" + net.JoinHostPort(host, strconv.Itoa(n)), nil
}

// recommendationHandler 只转发 ZZY 的三个只读接口，保留算法结果与版本字段。
func recommendationHandler(target string) (http.HandlerFunc, error) {
	upstream, err := url.Parse(target)
	if err != nil || upstream == nil || upstream.Scheme != "http" || upstream.Host == "" || upstream.User != nil || upstream.RawQuery != "" || upstream.Fragment != "" || (upstream.Path != "" && upstream.Path != "/") {
		return nil, fmt.Errorf("推荐服务需要不含路径、凭据和查询参数的 http 地址，如 http://127.0.0.1:8605")
	}
	client := &http.Client{Timeout: 45 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
	return func(w http.ResponseWriter, r *http.Request) {
		endpoint := strings.TrimPrefix(r.URL.Path, "/api/research/recommendation/")
		if endpoint != "meta" && endpoint != "search" && endpoint != "recommend" {
			writeError(w, http.StatusNotFound, "没有这个成果接口")
			return
		}
		if len(r.URL.RawQuery) > 4096 {
			writeError(w, http.StatusBadRequest, "请求参数过长")
			return
		}
		u := *upstream
		u.Path, u.RawQuery = "/api/"+endpoint, r.URL.RawQuery
		req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, u.String(), nil)
		if err != nil {
			writeError(w, http.StatusBadRequest, "请求参数无效")
			return
		}
		resp, err := client.Do(req)
		if err != nil {
			writeError(w, http.StatusServiceUnavailable, "推荐服务暂未就绪，请稍后重试。")
			return
		}
		defer resp.Body.Close()
		const maxResponse = 16 << 20
		body, err := io.ReadAll(io.LimitReader(resp.Body, maxResponse+1))
		if err != nil || len(body) > maxResponse || !json.Valid(body) || !strings.HasPrefix(resp.Header.Get("Content-Type"), "application/json") || resp.StatusCode >= 500 || resp.StatusCode < 200 || (resp.StatusCode >= 300 && resp.StatusCode < 400) {
			writeError(w, http.StatusBadGateway, "推荐结果暂时无法读取，请稍后重试。")
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.WriteHeader(resp.StatusCode)
		_, _ = w.Write(body)
	}, nil
}
