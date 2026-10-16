"""供 Go dashboard 调用的独立推荐服务，首次读库，之后复用持久化输入。"""

from __future__ import annotations

import argparse
import logging
from http.server import ThreadingHTTPServer
from pathlib import Path

from modeling.recommendation.graph_recommender import GraphRecommender
from modeling.recommendation.knowledge_graph_inspector import GraphInspector
from modeling.recommendation.snapshot import load_snapshot
from process.dashboard_cache import prepare_input
from process.site_service import make_handler

logger = logging.getLogger(__name__)


def main() -> int:
    """完整核验持久化快照与图谱；仅首次或显式刷新时读库生成。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8605)
    parser.add_argument(
        "--host", default="127.0.0.1", help="默认仅本机；跨机使用私网监听地址"
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--refresh-data", action="store_true", help="显式从共享库刷新持久化快照和图谱"
    )
    parser.add_argument(
        "--prepare-only", action="store_true", help="仅准备并核验持久化数据，然后退出"
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(__file__).resolve().parent / "runtime/dashboard",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口需要在 1–65535 之间")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        # 原交付包的 source-map 绑定打包时的逐文件字节；集成入口直接使用
        # 当前源码生成的图谱绑定，并保留 GraphInspector 的完整数据校验。
        inputs = prepare_input(
            args.cache_root, env_file=args.env_file, refresh=args.refresh_data
        )
        inspector = GraphInspector(
            inputs.data_root / "kg" / inputs.graph_version,
            snapshots=inputs.data_root / "snapshots",
        )
        if inspector.manifest["binding"]["snapshot_version"] != inputs.snapshot_version:
            raise ValueError(
                "持久化快照和图谱版本不一致，请检查数据卷或显式 --refresh-data"
            )
        _, metadata = load_snapshot(
            inputs.snapshot_version, inputs.data_root / "snapshots"
        )
        if args.prepare_only:
            logger.info("持久化输入已准备并完整核验，未启动HTTP服务")
            return 0
        handler = make_handler(GraphRecommender(inspector), metadata, inputs.provenance)
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except (OSError, ValueError, KeyError) as exc:
        logger.error("推荐服务无法启动：%s", exc)
        return 1
    logger.info("Dashboard 推荐服务已启动：http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
