"""Dashboard 专用持久化输入：首次生成，之后显式刷新。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .database_input import PreparedInput, prepare_database

logger = logging.getLogger(__name__)


def prepare_input(
    cache_root: Path, *, env_file: Path | None = None, refresh: bool = False
) -> PreparedInput:
    """加载持久化版本指针；损坏时明确失败，不静默改换数据版本。"""
    root = Path(cache_root)
    pointer = root / "latest-startup.json"
    if refresh or not pointer.exists():
        prepared = prepare_database(root, env_file=env_file)
        provenance = {
            **prepared.provenance,
            "refresh_policy": "explicit_refresh_only",
            "cache_reused": False,
        }
        return PreparedInput(
            root, prepared.snapshot_version, prepared.graph_version, provenance
        )
    try:
        saved = json.loads(pointer.read_text(encoding="utf-8"))
        snapshot = saved["snapshot_version"]
        graph = saved["graph_version"]
        if not isinstance(snapshot, str) or not re.fullmatch(
            r"recommendation-v1-[0-9a-f]{16}", snapshot
        ):
            raise ValueError("无效快照版本")
        if not isinstance(graph, str) or not re.fullmatch(r"kg-v1-[0-9a-f]{64}", graph):
            raise ValueError("无效图谱版本")
        provenance = {
            **saved,
            "source": "persistent_cache",
            "database_access": False,
            "refresh_policy": "explicit_refresh_only",
            "cache_reused": True,
            "fallback_to_old_cache": False,
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            "持久化缓存指针无效，请检查数据卷或显式 --refresh-data 重新生成"
        ) from exc
    logger.info("复用持久化快照和图谱，仅核验并加载；不重新读取数据库或生成数据")
    return PreparedInput(root, snapshot, graph, provenance)
