"""
Stream Filter
=============
Filters test results:
1. Keep only alive streams
2. Remove foreign/excluded channels
3. Assign group-title categories (Chinese / Pinyin / English patterns)
4. Preserve source group-title from trusted sources (vbskycn)
"""

import logging

from config import (
    EXCLUDE_KEYWORDS,
    ALWAYS_KEEP_KEYWORDS,
    CATEGORY_KEYWORDS,
    DEFAULT_GROUP,
)
from scanner import StreamEntry
from tester import TestResult, STATUS_ALIVE, STATUS_SLOW

logger = logging.getLogger("filter")

# Map external group names to our standard group names (case-insensitive)
GROUP_ALIAS_MAP = {
    "央视频道": "📺 央视频道", "cctv": "📺 央视频道",
    "湖南频道": "🏠 湖南频道", "hunan": "🏠 湖南频道",
    "卫视频道": "📡 卫视频道", "卫星": "📡 卫视频道", "satellite": "📡 卫视频道",
    "地方频道": "🗺 地方频道", "local": "🗺 地方频道", "地面": "🗺 地方频道",
    "少儿频道": "👶 少儿卡通", "卡通": "👶 少儿卡通", "kids": "👶 少儿卡通", "儿童频道": "👶 少儿卡通",
    "体育频道": "⚽ 体育频道", "sports": "⚽ 体育频道",
    "其他频道": "📺 其他频道", "other": "📺 其他频道",
    "电影频道": "🎬 影视频道", "movie": "🎬 影视频道",
    "纪实频道": "📖 纪录频道", "纪录频道": "📖 纪录频道", "documentary": "📖 纪录频道",
}


def is_excluded(name: str) -> bool:
    for kw in ALWAYS_KEEP_KEYWORDS:
        if kw.lower() in name.lower():
            return False
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in name.lower():
            return True
    return False


def assign_group(name: str, source_group: str = "") -> str:
    """
    Assign group-title. Priority:
    1. Source group (mapped to standard) if present
    2. Keyword matching against channel name (case-insensitive for pinyin support)
    """
    # 1. Try source group mapping
    if source_group:
        for alias, standard in GROUP_ALIAS_MAP.items():
            if alias.lower() in source_group.lower():
                return standard

    # 2. Keyword matching (case-insensitive)
    name_lower = name.lower()
    for group, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in name_lower:
                return group
    return DEFAULT_GROUP


def filter_streams(test_results: list) -> list:
    """
    Filter test results:
    1. Keep alive streams (including those with existing group-title)
    2. Remove excluded channels
    3. Assign group categories (preserve source group from trusted origins)
    4. Sort by group priority

    Returns list of StreamEntry objects ready for M3U generation.
    """
    logger.info("=" * 60)
    logger.info("STEP 4: FILTERING & CATEGORIZING")
    logger.info("=" * 60)

    total = len(test_results)
    alive_results = [r for r in test_results if r.status == STATUS_ALIVE]
    slow_results = [r for r in test_results if r.status == STATUS_SLOW]

    dead_count = total - len(alive_results) - len(slow_results)
    logger.info(f"  Dead removed: {dead_count}")
    logger.info(f"  Slow removed: {len(slow_results)}")
    logger.info(f"  Alive: {len(alive_results)}")

    filtered = []
    excluded_count = 0
    for result in alive_results:
        if is_excluded(result.entry.name):
            excluded_count += 1
            continue

        source_group = result.entry.attrs.get("group-title", "")
        group = assign_group(result.entry.name, source_group)
        result.entry.attrs["group-title"] = group
        filtered.append(result)

    logger.info(f"  Excluded (foreign): {excluded_count}")
    logger.info(f"  Passed filter: {len(filtered)}")

    # Sort by group priority
    group_order = {
        "🏠 湖南频道": 0,
        "📺 央视频道": 1,
        "📡 卫视频道": 2,
        "👶 少儿卡通": 3,
        "⚽ 体育频道": 4,
        "🎬 影视频道": 5,
        "📖 纪录频道": 6,
        "🗺 地方频道": 7,
        "📺 其他频道": 8,
    }

    def sort_key(result: TestResult):
        group = result.entry.attrs.get("group-title", DEFAULT_GROUP)
        priority = group_order.get(group, 99)
        return (priority, result.entry.name)

    filtered.sort(key=sort_key)
    entries = [r.entry for r in filtered]

    # Category breakdown
    cat_counts = {}
    for entry in entries:
        g = entry.attrs.get("group-title", DEFAULT_GROUP)
        cat_counts[g] = cat_counts.get(g, 0) + 1

    logger.info("  --- Category breakdown ---")
    for cat in group_order:
        if cat in cat_counts:
            logger.info(f"    {cat}: {cat_counts[cat]}")
    if DEFAULT_GROUP in cat_counts:
        logger.info(f"    {DEFAULT_GROUP}: {cat_counts[DEFAULT_GROUP]}")

    logger.info(f"  Final: {len(entries)} channels")
    return entries
