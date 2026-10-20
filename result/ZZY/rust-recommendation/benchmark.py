"""在本机 Docker 中测量 Rust 磁盘推荐，不访问数据库或 AI，不修改快照。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlencode
from urllib.request import urlopen


def main() -> None:
    """复用 Python 基线相同的容器外采样器与真实请求，保留统一统计口径。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="achievement-recommendation-rust:memory-bench")
    parser.add_argument("--name", default="achievement-recommendation-rust-memory-bench")
    parser.add_argument("--port", type=int, default=18607)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "runtime")
    args = parser.parse_args()
    helper = Path(__file__).resolve().parents[1] / "deploy/benchmark_memory.py"
    spec = importlib.util.spec_from_file_location("python_memory_baseline", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docker, api = module.docker, module.api
    context = json.loads(docker("context", "inspect"))[0]
    endpoint = context["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix://"):
        raise RuntimeError("拒绝远端 Docker")
    socket_path = endpoint.removeprefix("unix://")
    if docker("ps", "-aq", "--filter", f"name=^/{args.name}$"):
        raise RuntimeError("同名容器已存在，拒绝覆盖")
    data = args.data_dir.resolve()
    if not (data / "recommendation.sqlite.sha256").is_file():
        raise RuntimeError("请先导入完整 SQLite 数据库及摘要")
    image = json.loads(docker("image", "inspect", args.image))[0]
    samples: list[dict] = []
    phase = "startup"
    stopped = threading.Event()

    def monitor() -> None:
        """每 0.5 秒从本机引擎读取 cgroup，不向被测容器启动监控程序。"""
        while not stopped.is_set():
            try:
                stats = api(socket_path, f"/containers/{args.name}/stats?stream=false&one-shot=true")
                memory = stats.get("memory_stats", {})
                usage = memory.get("usage", 0)
                raw = memory.get("stats", {})
                cache = raw.get("inactive_file", raw.get("total_inactive_file", 0))
                if usage:
                    samples.append({"phase": phase, "usage": usage, "cache": cache, "working": max(0, usage-cache)})
            except (OSError, RuntimeError, ValueError):
                pass
            stopped.wait(0.5)

    def process_rss() -> dict:
        """Docker top 由引擎执行，无需向 scratch 镜像加入 ps/Python。"""
        lines = docker("top", args.name, "-eo", "pid,rss,comm").splitlines()[1:]
        return {"rss_bytes": sum(int(line.split()[1])*1024 for line in lines if line.strip()), "processes": len(lines)}

    thread = threading.Thread(target=monitor, daemon=True)
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix="recommendation-rust-scratch-") as scratch:
            start = time.monotonic()
            docker("run", "-d", "--name", args.name, "--cpus", "1", "--cpuset-cpus", "0,1",
                   "--memory", "256m", "--memory-swap", "256m", "--read-only",
                   "-p", f"127.0.0.1:{args.port}:8606",
                   "--mount", f"type=bind,source={data},target=/data,readonly",
                   "--mount", f"type=bind,source={scratch},target=/tmp",
                   args.image, "serve", "--db", "/data/recommendation.sqlite", "--host", "0.0.0.0", "--port", "8606")
            created = True
            thread.start()
            base = f"http://127.0.0.1:{args.port}"
            last_notice = start
            while True:
                try:
                    with urlopen(base+"/api/meta", timeout=2) as response:
                        meta = json.load(response)
                    break
                except OSError:
                    if time.monotonic()-start > 180:
                        raise TimeoutError("Rust 启动超时")
                    if time.monotonic()-last_notice > 20:
                        state = api(socket_path, f"/containers/{args.name}/json")["State"]
                        if not state["Running"]:
                            raise RuntimeError(f"容器退出 {state['ExitCode']} oom={state['OOMKilled']}")
                        print(f"PROGRESS startup {time.monotonic()-start:.0f}s", flush=True)
                        last_notice = time.monotonic()
                    time.sleep(0.5)
            startup = time.monotonic()-start
            print(f"PROGRESS ready {startup:.3f}s", flush=True)
            assert meta["data_loading"]["database_access"] is False
            assert meta["data_loading"]["source"] == "persistent_sqlite"
            phase = "idle"
            time.sleep(10)
            idle_rss = process_rss()
            phase = "measurement"
            searches = [module.request(base, "/api/search?"+urlencode({"q": q, "limit": 5})) for q in ("空洞骑士", "艾尔登法环", "星露谷物语")]
            paths = ["/api/recommend?"+urlencode({"appids":ids,"top_k":5,"path_limit":8,**filters}) for ids,filters in [
                ("367520",{}),("413150",{}),("1245620",{}),("367520,413150",{}),
                ("367520,413150",{"year_min":2020,"year_max":2025}),("1245620,367520",{})]]
            phase = "serial"
            serial = [module.request(base,path) for path in paths]
            print("PROGRESS serial complete", flush=True)
            serial_rss = process_rss()
            phase = "concurrent_4"
            with ThreadPoolExecutor(max_workers=4) as executor:
                concurrent = list(executor.map(lambda path: module.request(base,path),paths+paths[:2]))
            concurrent_rss = process_rss()
            phase = "idle_after_queries"
            time.sleep(10)
            final_rss = process_rss()
            stopped.set(); thread.join(timeout=10)
            assert all(x["sha256"] == next(s["sha256"] for s in serial if s["path"]==x["path"]) for x in concurrent)
            result = {"date":"2026-10-20","image":args.image,"image_id":image["Id"],
                "architecture":image["Architecture"],"image_inspect_size_bytes":image["Size"],
                "image_disk_usage_display":docker("image","ls",args.image,"--format","{{.Size}}"),
                "cpu_limit":1,"cpuset":"0,1","memory_limit_bytes":256*1024**2,
                "sampling_seconds":0.5,"startup_seconds":round(startup,3),
                "sqlite_bytes":(data/"recommendation.sqlite").stat().st_size,
                "data_loading":meta["data_loading"],"candidate_games":meta["candidate_games"],
                "phases":{p:module.phase_summary(samples,p) for p in ("startup","idle","serial","concurrent_4","idle_after_queries")},
                "process_memory":{"idle":idle_rss,"after_serial":serial_rss,"after_concurrent":concurrent_rss,"final":final_rss},
                "searches":searches,"serial_requests":serial,"concurrent_requests":concurrent,
                "notes":"ARM64；SQLite只读存盘；根文件系统只读；临时目录磁盘挂载；4个客户端并发由服务逐请求处理；无数据库/AI凭据。"}
            print("RESULT_JSON="+json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        stopped.set()
        if thread.is_alive(): thread.join(timeout=10)
        if created: docker("rm","-f",args.name)


if __name__ == "__main__":
    main()
