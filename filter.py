"""
Stream Filter
=============
Filters test results:
1. Keep only alive streams
2. Remove foreign/excluded channels
3. Ensure Hunan + CCTV are always kept
4. Assign group-title categories
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


def is_excluded(name: str) -> bool:
    """
    Check if a channel name should be excluded (foreign channels, etc.).
    But: if name matches ALWAYS_KEEP_KEYWORDS, it should never be excluded.
    """
    # Always-keep check first
    for kw in ALWAYS_KEEP_KEYWORDS:
        if kw.lower() in name.lower():
            return False

    # Exclusion check
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in name.lower():
            return True

    return False


def assign_group(name: str) -> str:
    """
    Assign a group-title based on channel name keywords.
    Checks in order: Hunan first, then CCTV, Satellite, Local, fallback.
    """
    for group, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return group
    return DEFAULT_GROUP


def filter_streams(test_results: list) -> list:
    """
    Filter test results:
    1. Keep only alive streams
    2. Remove excluded channels
    3. Assign group categories
    4. Sort by group priority (Hunan > CCTV > Satellite > Local > Other)

    Returns list of StreamEntry objects ready for M3U generation.
    """
    logger.info("=" * 60)
    logger.info("STEP 4: FILTERING & CATEGORIZING")
    logger.info("=" * 60)

    total = len(test_results)
    alive_results = [r for r in test_results if r.status == STATUS_ALIVE]
    slow_results = [r for r in test_results if r.status == STATUS_SLOW]

    dead_count = total - len(alive_results) - len(slow_results)
    logger.info(f"  Dead streams removed: {dead_count}")
    logger.info(f"  Slow streams removed (bandwidth < threshold): {len(slow_results)}")
    logger.info(f"  Alive streams: {len(alive_results)}")

    # Filter excluded channels
    filtered = []
    excluded_count = 0
    for result in alive_results:
        if is_excluded(result.entry.name):
            logger.debug(f"  Excluded: {result.entry.name}")
            excluded_count += 1
        else:
            # Assign group
            group = assign_group(result.entry.name)
            result.entry.attrs["group-title"] = group
            filtered.append(result)

    logger.info(f"  Foreign/excluded channels removed: {excluded_count}")
    logger.info(f"  Passed filter: {len(filtered)}")

    # Sort by group priority
    group_order = {
        "🏠 湖南频道": 0,
        "📺 央视频道": 1,
        "📡 卫视频道": 2,
        "🗺 地方频道": 3,
        "📺 其他频道": 4,
    }

    def sort_key(result: TestResult):
        group = result.entry.attrs.get("group-title", DEFAULT_GROUP)
        priority = group_order.get(group, 99)
        # Within same group, sort by name
        return (priority, result.entry.name)

    filtered.sort(key=sort_key)

    # Extract the StreamEntry objects
    entries = [r.entry for r in filtered]

    # Log category breakdown
    cat_counts = {}
    for entry in entries:
        g = entry.attrs.get("group-title", DEFAULT_GROUP)
        cat_counts[g] = cat_counts.get(g, 0) + 1

    logger.info("  --- Category breakdown ---")
    for cat in ["🏠 湖南频道", "📺 央视频道", "📡 卫视频道", "🗺 地方频道", "📺 其他频道"]:
        if cat in cat_counts:
            logger.info(f"    {cat}: {cat_counts[cat]} channels")

    logger.info(f"  Final stream count: {len(entries)}")
    return entries