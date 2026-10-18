"""Shared numbered figure names and output routing, separate from numeric artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prepare_metrics import ROOT, digest, owned_path

FIGURES = ROOT / "figures"
TYPE_FIGURES = {
    "type_coverage_heatmap": "02_type_coverage",
    "type_progress_heatmap": "03_type_progress",
    "type_progress_distribution": "04_type_distribution",
    "multilabel_coverage_heatmap": "05_tag_coverage",
    "multilabel_progress_heatmap": "06_tag_progress",
    "stage_contrast_cases": "07_stage_cases",
}

COHORT_SOURCE = "样本来源：2026-10-13冻结1000款游戏快照 → 198款有效主线曲线 → 183款完整三节点。"


def add_footer(fig: Any, lines: list[str]) -> None:
    """Put source and metric notes on four bottom lines, fitted inside the figure width."""
    if len(lines) != 4:
        raise ValueError("图下注释应包含来源、分组、数据定义和解释四行")
    renderer = fig.canvas.get_renderer()
    for index, line in enumerate(lines):
        item = fig.text(0.04, 0.12 - index * 0.032, line, fontsize=9, color="#58636B", va="bottom")
        width = item.get_window_extent(renderer).width
        available = fig.bbox.width * 0.92
        if width > available:
            item.set_fontsize(9 * available / width)


def figure_directory(data_output: Path, default_output: Path) -> Path:
    """Use the shared gallery by default and isolate custom-run figures beside its data."""
    folder = FIGURES if data_output == default_output else data_output / "figures"
    return owned_path(folder)


def comparison_name(appids: list[int], view: str) -> str:
    """Give the five-game demo a short name and other ordered selections a stable suffix."""
    if appids == [1593500, 220240, 367520, 489830, 424840] and view == "both":
        return "01_game_stages"
    return f"01_game_stages_{digest([appids, view])[:10]}_{view}"
