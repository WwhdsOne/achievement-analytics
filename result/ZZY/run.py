"""ZZY个人入口：默认启动时只读小组数据库；离线复现须显式选择。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
from pathlib import Path
import sys

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME))
SNAPSHOT = 'recommendation-v1-c58f1d57439d2c28'
GRAPH = 'kg-v1-f088d9b7c48edf0be3aa475f95ee744a62e70b5a4807861fe85541bdbbe84bc9'
DATA = HOME / 'data/processed/recommendation'
CACHE = HOME / 'runtime/database'


def file_sha(path: Path) -> str:
    """Stream a SHA256 without reading large graph files into memory."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sources() -> int:
    """Ensure relocated calculation modules and page assets are unchanged."""
    source_map = json.loads((HOME / 'reports/source-map.json').read_bytes())
    for entry in source_map['files']:
        if file_sha(HOME / entry['path']) != entry['sha256']:
            raise ValueError('源码/页面摘要变化：' + entry['path'])
    return len(source_map['files'])


def data_check(inputs) -> dict:
    """Check local snapshot, graph byte digests and their bound calculation sources."""
    from modeling.recommendation.snapshot import load_snapshot
    source_files = verify_sources()
    rows, metadata = load_snapshot(inputs.snapshot_version, inputs.data_root / 'snapshots')
    folder = inputs.data_root / 'kg' / inputs.graph_version
    graph = json.loads((folder / 'manifest.json').read_bytes())
    if graph['version'] != inputs.graph_version or graph['binding']['snapshot_sha256'] != metadata['sha256']:
        raise ValueError('图谱/快照版本不匹配')
    for name, entry in graph['files'].items():
        if file_sha(folder / name) != entry['sha256']:
            raise ValueError('图谱文件摘要变化：' + name)
    bound = graph['binding']
    module_dir = HOME / 'modeling/recommendation'
    expected = bound['builder_sha256'] | {'baseline.py': bound['candidate_rules_sha256'],
                                         'snapshot.py': bound['snapshot_loader_sha256']}
    for name, digest in expected.items():
        if file_sha(module_dir / name) != digest:
            raise ValueError('图谱绑定源码变化：' + name)
    return {'status': 'ok', 'kind': 'input_bytes_and_source_binding_check',
            'snapshot_games': len(rows), 'source_files_verified': source_files,
            'snapshot_version': inputs.snapshot_version, 'graph_version': inputs.graph_version,
            **graph['statistics'], 'data_loading': inputs.provenance,
            'formal_human_evaluation': False}


def serve(inputs, port: int, baseline: bool) -> int:
    """Start a loopback-only service using explicit read-only local inputs."""
    from http.server import ThreadingHTTPServer
    verify_sources()
    if baseline:
        from modeling.recommendation import web
        from modeling.recommendation.snapshot import load_snapshot
        rows, metadata = load_snapshot(inputs.snapshot_version, inputs.data_root / 'snapshots')
        metadata = {**metadata, 'data_loading': copy.deepcopy(inputs.provenance)}
        handler = web.make_handler(web.RecommendationService(rows, metadata))
    else:
        from modeling.recommendation.graph_recommender import GraphRecommender
        from modeling.recommendation.knowledge_graph_inspector import GraphInspector
        from modeling.recommendation.snapshot import load_snapshot
        from process.site_service import make_handler
        inspector = GraphInspector(inputs.data_root / 'kg' / inputs.graph_version,
                                   snapshots=inputs.data_root / 'snapshots')
        _, metadata = load_snapshot(inputs.snapshot_version, inputs.data_root / 'snapshots')
        handler = make_handler(GraphRecommender(inspector), metadata, inputs.provenance)
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    print(f'ZZY推荐演示 http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def load_input(args):
    from process.database_input import PreparedInput, prepare_database
    if args.source == 'database':
        if args.data_root is not None:
            raise ValueError('--data-root 仅用于 --source snapshot；数据库缓存请用 --cache-root')
        return prepare_database(args.cache_root or CACHE, env_file=args.env_file,
                                with_graph=args.command != 'baseline')
    if args.env_file is not None or args.cache_root is not None:
        raise ValueError('--env-file/--cache-root 仅用于数据库模式')
    return PreparedInput((args.data_root or DATA).resolve(), SNAPSHOT, GRAPH,
                         {'source': 'frozen_snapshot', 'database_access': False,
                          'refresh_policy': 'explicit_offline_replay_no_database_access'})


def main() -> int:
    """数据库默认只读；历史 AI 评价和显式离线入口不连接数据库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('serve', 'baseline', 'check'):
        sub = commands.add_parser(name, help={'serve': '统一推荐页', 'baseline': '原标签基线页', 'check': '离线输入与源码校验'}[name])
        sub.add_argument('--source', choices=('database', 'snapshot'), default='database')
        sub.add_argument('--env-file', type=Path, help='已有小组数据库 .env；默认仓库根 .env')
        sub.add_argument('--cache-root', type=Path, help='数据库自动生成的本地缓存目录')
        sub.add_argument('--data-root', type=Path, help='显式离线模式的旧输入目录')
        if name != 'check':
            sub.add_argument('--port', type=int, default=8605 if name == 'serve' else 8602)
    evaluate = commands.add_parser('evaluate', help='复现AI辅助指标，独立输出、不生成真人锁')
    evaluate.add_argument('--input-dir', type=Path, default=HOME / 'runtime/evaluation-input')
    evaluate.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        if args.command == 'evaluate':
            verify_sources()
            from process.ai_evaluation import evaluate
            print(json.dumps(evaluate(args.input_dir.resolve(), args.output_dir.resolve()), ensure_ascii=False, indent=2))
            return 0
        if args.command != 'check' and not 1 <= args.port <= 65535:
            raise ValueError('端口需为1–65535')
        verify_sources()
        inputs = load_input(args)
        if args.command == 'check':
            print(json.dumps(data_check(inputs), ensure_ascii=False, indent=2))
            return 0
        return serve(inputs, args.port, args.command == 'baseline')
    except (OSError, ValueError, KeyError) as exc:
        print(f'无法运行：{exc}\n运行与配置步骤见 result/ZZY/docs/RUN.md。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
