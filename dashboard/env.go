// env.go — 极简 .env 读取。
//
// 本机读取 dashboard 自己的 .env。**已存在的环境变量优先**，
// 所以容器里由 compose 的 env_file 注入的值不会被
// 本文件覆盖；部署环境根本没有 .env 文件，直接静默跳过。
package main

import (
	"bufio"
	"os"
	"strings"
)

// loadDotEnv 把指定 .env 的 KEY=value 塞进环境变量，只补齐缺失的键。
//
// 格式按项目 .env 的实际写法：一行一个 KEY=value，`#` 开头是注释。
// 不做 shell 展开、不支持多行值——项目 .env 没有这些用法，不需要为它们写解析器。
func loadDotEnv(path string) {
	f, err := os.Open(path)
	if err != nil {
		return // 没有 .env 是正常情况（容器里靠 env_file 注入）
	}
	defer f.Close()

	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		if key == "" {
			continue
		}
		if _, exists := os.LookupEnv(key); exists {
			continue // 环境变量优先
		}
		// 去掉两端引号：.env 里允许写成 KEY="value"
		value = strings.Trim(strings.TrimSpace(value), `"'`)
		_ = os.Setenv(key, value)
	}
}
