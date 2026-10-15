"""Player-facing titles, kept separate from original names and scoring reports."""
from __future__ import annotations

import json
from pathlib import Path
import re

NAME_PATH = Path(__file__).with_name('display_names_zh.json')
DISPLAY_NAMES = json.loads(NAME_PATH.read_text(encoding='utf-8'))['games']


def display_title(row: dict) -> dict[str, str]:
    """Return display-only names without mutating source fields or ranking data."""
    localized = DISPLAY_NAMES.get(str(row['appid']))
    chinese = row.get('name_zh') or ''
    english = row.get('name_en') or row.get('name') or ''
    if localized:
        primary, source = localized, 'curated_common_chinese_name'
    elif isinstance(chinese, str) and re.search(r'[\u3400-\u9fff]', chinese):
        primary, source = chinese, 'snapshot_chinese_name'
    else:
        primary, source = english or chinese or f"Game {row['appid']}", 'original_name_fallback'
    return {'display_name': primary, 'display_name_en': english, 'display_name_source': source}
