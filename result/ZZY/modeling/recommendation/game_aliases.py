"""本地人工维护的搜索别名；只按 AppID 绑定，不参与推荐或覆盖原始名称。"""
from __future__ import annotations

import json
from pathlib import Path
import unicodedata

ALIAS_PATH = Path(__file__).with_suffix(".json")
_data = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
ALIASES = {int(appid): tuple(entry["aliases"]) for appid, entry in _data["games"].items()}
# 保留原标签基线的八款示例，扩充搜索词不扩充首页按钮数量。
FAMILIAR_APPIDS = frozenset((1245620, 413150, 646570, 367520, 632470, 255710, 620, 227300))


def normalize_search(value: str) -> str:
    """统一全半角、大小写和连续空白；保留字段内部的词边界。"""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def search_fields(row: dict) -> tuple[str, ...]:
    """各名称、AppID 与别名单独匹配，避免拼接字段形成虚假命中。"""
    values = [row.get("name_zh"), row.get("name_en"), row.get("appid")]
    values.extend(ALIASES.get(row["appid"], ()))
    return tuple(normalize_search(str(value)) for value in values if value is not None)


def matched_aliases(appid: int, normalized: str) -> list[str]:
    """返回命中的原始别名副本；空查询不声称命中某个别名。"""
    return [alias for alias in ALIASES.get(appid, ()) if normalized and normalized in normalize_search(alias)]
