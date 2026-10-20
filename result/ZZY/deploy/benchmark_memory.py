"""在本机 Docker 中测量现有 Python 服务，复用只读缓存，不访问数据库或 AI。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
from pathlib import Path
import socket
import statistics
import subprocess
import threading
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen


def docker(*args: str) -> str:
    """只执行参数列表，不通过 shell，也不打印运行时环境变量。"""
    return subprocess.check_output(["docker", *args], text=True).strip()


class LocalDocker(http.client.HTTPConnection):
    """只允许连接本机 Unix socket 的 Docker API。"""

    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=5)
        self.path = path

    def connect(self) -> None:
        """通过 Unix socket 连接本机引擎。"""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def api(socket_path: str, path: str) -> dict:
    """读取 Docker 元数据，不展开或输出容器环境。"""
    connection = LocalDocker(socket_path)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        payload = response.read()
        if response.status != 200:
            raise RuntimeError(f"Docker API 返回 {response.status}")
        return json.loads(payload)
    finally:
        connection.close()


def process_memory(name: str) -> dict:
    """读取服务 PID 1 的 RSS 与进程高水位；辅助进程不计入这个 RSS。"""
    code = """import json
from pathlib import Path
keys={'VmRSS','VmHWM','RssAnon','RssFile','RssShmem','Threads'}
out={}
for line in Path('/proc/1/status').read_text().splitlines():
 key,_,value=line.partition(':')
 if key in keys:
  parts=value.split();out[key]=int(parts[0])*(1024 if len(parts)>1 and parts[1]=='kB' else 1)
print(json.dumps(out))
"""
    return json.loads(docker("exec", name, "/app/.venv/bin/python", "-c", code))


def request(base: str, path: str) -> dict:
    """执行本机只读请求，报告大小、耗时与摘要，不保存游戏明细。"""
    start = time.monotonic()
    with urlopen(base + path, timeout=180) as response:
        body = response.read()
        payload = json.loads(body)
    results = payload.get("ranking", {}).get("results")
    if path.startswith("/api/recommend?"):
        assert isinstance(results, list), "真实推荐请求应包含 ranking.results"
    result = {
        "path": path,
        "seconds": round(time.monotonic() - start, 4),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    if results is not None:
        assert len(results) == 5, "真实推荐请求应当返回 5 款游戏"
        result["appids"] = [game["appid"] for game in results]
    return result


def phase_summary(samples: list[dict], phase: str) -> dict:
    """按阶段汇总 Docker working-set 口径及未扣缓存的容器用量。"""
    rows = [row for row in samples if row["phase"] == phase]
    if not rows:
        return {"samples": 0}
    return {
        "samples": len(rows),
        "docker_working_set_min_bytes": min(row["working"] for row in rows),
        "docker_working_set_median_bytes": int(statistics.median(row["working"] for row in rows)),
        "docker_working_set_peak_bytes": max(row["working"] for row in rows),
        "cgroup_usage_peak_bytes": max(row["usage"] for row in rows),
        "inactive_file_peak_bytes": max(row["cache"] for row in rows),
    }


def main() -> None:
    """启动独立本机容器，测启动、空闲、串行与并发请求，最后清理测试容器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="achievement-recommendation:memory-bench")
    parser.add_argument("--name", default="achievement-recommendation-memory-bench")
    parser.add_argument("--port", type=int, default=18605)
    parser.add_argument("--startup-timeout", type=int, default=1200)
    parser.add_argument(
        "--cache-root", type=Path,
        default=Path(__file__).resolve().parents[1] / "runtime/dashboard",
    )
    args = parser.parse_args()
    context = json.loads(docker("context", "inspect"))[0]
    endpoint = context["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix://"):
        raise RuntimeError("内存测量只允许本机 Unix socket，拒绝远端 Docker")
    socket_path = endpoint.removeprefix("unix://")
    cache = args.cache_root.resolve()
    pointer = cache / "latest-startup.json"
    pointer_before = hashlib.sha256(pointer.read_bytes()).hexdigest()
    saved = json.loads(pointer.read_text())
    image = json.loads(docker("image", "inspect", args.image))[0]
    engine = api(socket_path, "/info")
    if engine["MemTotal"] < 5 * 1024**3:
        raise RuntimeError("本次测量需 Docker VM 至少 5 GiB 可用上限")
    if docker("ps", "-aq", "--filter", f"name=^/{args.name}$"):
        raise RuntimeError("同名测试容器已存在，请先检查，脚本不会覆盖它")
    samples: list[dict] = []
    phase = "startup"
    stopped = threading.Event()
    start = time.monotonic()
    created = False

    def monitor() -> None:
        """从容器外采样，不向被测容器额外启动监控进程。"""
        while not stopped.is_set():
            try:
                stats = api(socket_path, f"/containers/{args.name}/stats?stream=false&one-shot=true")
                memory = stats.get("memory_stats", {})
                usage = memory.get("usage", 0)
                raw = memory.get("stats", {})
                cache_bytes = raw.get("inactive_file", raw.get("total_inactive_file", 0))
                if usage:
                    samples.append({"phase": phase, "usage": usage, "cache": cache_bytes, "working": max(0, usage - cache_bytes)})
            except (OSError, RuntimeError, ValueError):
                pass
            stopped.wait(0.5)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    try:
        docker(
            "run", "-d", "--name", args.name, "--cpus", "1", "--cpuset-cpus", "0,1",
            "--memory", "4g", "--memory-swap", "4g", "--read-only",
            "-p", f"127.0.0.1:{args.port}:8605",
            "--mount", f"type=bind,source={cache},target=/runtime,readonly",
            args.image, "--host", "0.0.0.0", "--port", "8605", "--cache-root", "/runtime",
        )
        created = True
        monitor_thread.start()
        base = f"http://127.0.0.1:{args.port}"
        last_notice = start
        while True:
            try:
                with urlopen(base + "/api/meta", timeout=2) as response:
                    meta = json.loads(response.read())
                break
            except (URLError, TimeoutError, OSError):
                if time.monotonic() - start > args.startup_timeout:
                    raise TimeoutError("推荐服务启动超时")
                if time.monotonic() - last_notice >= 20:
                    state = api(socket_path, f"/containers/{args.name}/json")["State"]
                    if not state["Running"]:
                        raise RuntimeError(f"测试容器已退出：code={state['ExitCode']} oom={state['OOMKilled']}")
                    working = samples[-1]["working"] / 1024**2 if samples else 0
                    print(f"PROGRESS startup {time.monotonic()-start:.0f}s working_set={working:.1f} MiB", flush=True)
                    last_notice = time.monotonic()
                time.sleep(1)
        startup_seconds = round(time.monotonic() - start, 3)
        print(f"PROGRESS ready {startup_seconds}s；开始空闲和请求测量", flush=True)
        phase = "idle"
        time.sleep(10)
        phase = "measurement"
        ready_rss = process_memory(args.name)
        searches = [request(base, "/api/search?" + urlencode({"q": term, "limit": 5})) for term in ("空洞骑士", "艾尔登法环", "星露谷物语")]
        paths = [
            "/api/recommend?" + urlencode({"appids": ids, "top_k": 5, "path_limit": 8, **filters})
            for ids, filters in [
                ("367520", {}), ("413150", {}), ("1245620", {}),
                ("367520,413150", {}), ("367520,413150", {"year_min": 2020, "year_max": 2025}),
                ("1245620,367520", {}),
            ]
        ]
        phase = "serial"
        serial = [request(base, path) for path in paths]
        phase = "measurement"
        serial_rss = process_memory(args.name)
        print("PROGRESS 串行请求完成；开始 4 并发请求", flush=True)
        phase = "concurrent_4"
        with ThreadPoolExecutor(max_workers=4) as executor:
            concurrent = list(executor.map(lambda path: request(base, path), paths + paths[:2]))
        phase = "measurement"
        concurrent_rss = process_memory(args.name)
        phase = "idle_after_queries"
        time.sleep(10)
        phase = "measurement"
        final_rss = process_memory(args.name)
        stopped.set()
        monitor_thread.join(timeout=10)
        assert hashlib.sha256(pointer.read_bytes()).hexdigest() == pointer_before
        provenance = meta["data_loading"]
        assert provenance["database_access"] is False
        assert provenance["cache_reused"] is True
        result = {
            "date": "2026-10-20", "image": args.image, "image_id": image["Id"],
            "image_inspect_size_bytes": image["Size"], "image_architecture": image["Architecture"],
            "image_disk_usage_display": docker("image", "ls", args.image, "--format", "{{.Size}}"),
            "docker_server_version": engine["ServerVersion"],
            "docker_vm_memory_bytes": engine["MemTotal"], "cpu_limit": 1,
            "cpuset": "0,1", "memory_limit_bytes": 4 * 1024**3,
            "sampling_seconds": 0.5, "startup_seconds": startup_seconds,
            "snapshot_version": saved["snapshot_version"], "graph_version": saved["graph_version"],
            "cache_pointer_unchanged": True,
            "candidate_games": meta.get("candidate_games"),
            "data_provenance": {key: provenance.get(key) for key in ("database_access", "cache_reused", "source")},
            "phases": {name: phase_summary(samples, name) for name in ("startup", "idle", "serial", "concurrent_4", "idle_after_queries")},
            "pid1_memory": {"ready": ready_rss, "after_serial": serial_rss, "after_concurrent": concurrent_rss, "final": final_rss},
            "searches": searches, "serial_requests": serial, "concurrent_requests": concurrent,
            "docker_stats_definition": "memory_stats.usage - inactive_file (cgroup v2); cgroup usage also reported",
            "measurement_notes": "本机 ARM64；复用已有缓存；采样器在容器外；measurement 阶段的辅助进程不进入各业务阶段汇总；未调用点评或提供数据库/AI凭据。",
        }
        print("RESULT_JSON=" + json.dumps(result, ensure_ascii=False), flush=True)
    except Exception:
        if created:
            print("STARTUP_LOG=" + docker("logs", "--tail", "12", args.name), flush=True)
        raise
    finally:
        stopped.set()
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=10)
        if created:
            docker("rm", "-f", args.name)


if __name__ == "__main__":
    main()
