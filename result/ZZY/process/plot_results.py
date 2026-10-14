"""Generate descriptive figures from saved AI evaluation metrics."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    """Plot complete-query means and all-query missing-label bounds."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    home = Path(__file__).resolve().parents[1]
    original = json.loads((home / 'reports/ai-original.json').read_bytes())
    conservative = json.loads((home / 'reports/ai-sensitivity.json').read_bytes())
    methods = ('tag_jaccard', 'graph_full', 'graph_no_developer', 'graph_no_genre')
    labels = ('Tag Jaccard', 'Full graph', 'No developer', 'No genre')
    output = home / 'figures'
    output.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, ax = plt.subplots(figsize=(9, 5.5), layout='constrained')
    for offset, metric, color, title in ((-.19, 'P@5', '#177c86', 'Relevant: label 1 or 2'),
                                         (.19, 'strict_P@5', '#c4783f', 'Strict: label 2')):
        values = [original['methods'][m][metric] for m in methods]
        bars = ax.bar([i + offset for i in range(4)], values, width=.36, color=color, label=title)
        ax.bar_label(bars, labels=[f'{v:.1%}' for v in values], padding=4, fontsize=10)
    ax.set(xticks=range(4), xticklabels=labels, ylim=(0, .85), ylabel='Mean fraction in Top-5',
           title='AI-label exploratory comparison\n14 shared complete queries; not human evaluation')
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.legend(frameon=False, loc='upper left')
    ax.grid(axis='y', alpha=.2); ax.set_axisbelow(True)
    fig.savefig(output / 'ai-method-comparison.png', dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 5.5), layout='constrained')
    for offset, result, color, label in ((-.13, original, '#177c86', 'Original AI labels'),
                                         (.13, conservative, '#c4783f', 'Missing-evidence rows = unknown')):
        for i, method in enumerate(methods):
            low, high = result['methods'][method]['all_query_P@5_bounds']
            ax.plot([low, high], [i + offset] * 2, color=color, linewidth=4,
                    marker='|', markersize=13, label=label if i == 0 else None)
    ax.set(yticks=range(4), yticklabels=labels, xlim=(.35, .85), xlabel='P@5 bounds over all 24 queries',
           title='Unknown-label bounds (not confidence intervals)\nAI-generated exploratory labels')
    ax.xaxis.set_major_formatter(PercentFormatter(1)); ax.invert_yaxis()
    fig.legend(frameon=False, loc='outside lower center', fontsize=10)
    ax.grid(axis='x', alpha=.2)
    fig.savefig(output / 'ai-unknown-bounds.png', dpi=180)
    plt.close(fig)
    print('Saved 2 descriptive figures in result/ZZY/figures')


if __name__ == '__main__':
    main()
