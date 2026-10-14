// db.go — 连接共享云库。变量名与 crawler/config.py 保持一致。
package main

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// dsn 由 POSTGRES_* 拼连接串。
//
// ⚠️ 默认 sslmode=disable：项目用的是**自建库**，不支持 SSL，设成 require 会直接连不上
// （2026-09-18 实测）。只有显式设了 POSTGRES_SSLMODE 才用它的值，迁移到托管云库时才需要。
func dsn() string {
	q := url.Values{}
	q.Set("sslmode", "disable")
	if m := os.Getenv("POSTGRES_SSLMODE"); m != "" {
		q.Set("sslmode", m)
	}

	host := envOr("POSTGRES_HOST", "localhost")
	port := envOr("POSTGRES_PORT", "5432")
	user := envOr("POSTGRES_USER", "analyst")

	u := url.URL{
		Scheme:   "postgres",
		Host:     fmt.Sprintf("%s:%s", host, port),
		Path:     "/" + envOr("POSTGRES_DB", "achievement_analytics"),
		RawQuery: q.Encode(),
	}
	if pw := os.Getenv("POSTGRES_PASSWORD"); pw != "" {
		u.User = url.UserPassword(user, pw)
	} else {
		u.User = url.User(user)
	}
	return u.String()
}

// newPool 建连接池。
//
// 上限刻意压得很小：云库的连接数是**全组共享预算**，面板只是只读展示，
// 不该和 worker 抢连接——实测连接被占满时面板会直接 500
// （`FATAL: sorry, too many clients already`）。
func newPool(ctx context.Context) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn())
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 4
	cfg.MinConns = 0
	cfg.MaxConnIdleTime = 5 * time.Minute
	cfg.MaxConnLifetime = 30 * time.Minute
	// 空闲连接会被中间设备掐断，定期探活让池自己换掉死连接
	cfg.HealthCheckPeriod = time.Minute
	return pgxpool.NewWithConfig(ctx, cfg)
}

// dbTarget 返回「连的是哪个库」的可读描述（host:port/db），用于启动日志。
//
// 刻意**不含密码**：启动日志经常被整段贴出来排查问题。
// 面板有两种跑法（本机连公网地址、容器里连 127.0.0.1），所以把实际生效的目标打出来，
// 一眼就能确认 .env 填对了没有。
func dbTarget() string {
	return fmt.Sprintf("%s:%s/%s",
		envOr("POSTGRES_HOST", "localhost"),
		envOr("POSTGRES_PORT", "5432"),
		envOr("POSTGRES_DB", "achievement_analytics"))
}

// envOr 读环境变量，空则用默认值。
func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
