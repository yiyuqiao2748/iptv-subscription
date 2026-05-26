"""
Stream Filter
=============
Filters test results:
1. Keep only alive streams
2. Remove foreign/excluded channels
3. Latency-based dedup: same channel keep fastest source
4. Assign group-title categories (Chinese / Pinyin / English patterns)
5. Preserve source group-title from trusted sources (vbskycn)
"""

import logging
import re

from config import (
    EXCLUDE_KEYWORDS,
    ALWAYS_KEEP_KEYWORDS,
    CATEGORY_KEYWORDS,
    DEFAULT_GROUP,
    HUNAN_KEYWORDS,
    MAX_SEGMENT_DURATION,
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
    "电影频道": "🎬 影视剧场", "movie": "🎬 影视剧场",
    "纪实频道": "📖 纪录频道", "纪录频道": "📖 纪录频道", "documentary": "📖 纪录频道",
    "新闻": "📰 新闻资讯", "news": "📰 新闻资讯",
    "影视": "🎬 影视剧场", "drama": "🎬 影视剧场",
    "音乐": "🎵 音乐娱乐", "music": "🎵 音乐娱乐",
    "游戏": "🎮 游戏电竞", "gaming": "🎮 游戏电竞",
    "购物": "🛒 购物频道", "shopping": "🛒 购物频道",
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


def _normalize_for_dedup(name: str) -> str:
    """Normalize channel name for latency dedup grouping."""
    cleaned = re.sub(r'[\s_\-]+', '', name)
    cleaned = cleaned.upper()
    cleaned = re.sub(r'(高清|超清|HD|SD|4K|1080P|720P|标清|流畅|IPV6|IPV4)$', '', cleaned)
    return cleaned


def _is_hunan(name: str) -> bool:
    for kw in HUNAN_KEYWORDS:
        if kw in name:
            return True
    return False


def _is_cctv(name: str) -> bool:
    upper = name.upper()
    return "CCTV" in upper or "央视" in name


def latency_dedup(alive_results: list) -> list:
    """
    For channels with the same name, keep only the fastest source(s).
    - Hunan channels: keep top 2 fastest (backup)
    - CCTV channels: keep top 2 fastest (backup)
    - Others: keep 1 fastest
    Sorts by response_time_ms ascending, then by bandwidth descending as tiebreaker.
    """
    # Group by normalized name
    groups: dict[str, list] = {}
    order: list[str] = []

    for result in alive_results:
        norm = _normalize_for_dedup(result.entry.name)
        matched = False
        for key in order:
            if norm == key or (len(norm) >= 3 and norm in key) or (len(key) >= 3 and key in norm):
                groups[key].append(result)
                matched = True
                break
        if not matched:
            groups[norm] = [result]
            order.append(norm)

    # Within each group, sort by estimated latency (fastest first), keep top N
    kept = []
    for key in order:
        group = groups[key]
        # Sort: trusted first, then lowest estimated latency, then highest bandwidth
        group.sort(key=lambda r: (
            0 if r.entry.trusted else 1,
            r.estimated_latency_s,
            -r.bandwidth_kbps,
        ))

        name = group[0].entry.name
        if _is_hunan(name) or _is_cctv(name):
            max_keep = 2
        else:
            max_keep = 1

        kept.extend(group[:max_keep])

    removed = len(alive_results) - len(kept)
    logger.info(f"  Latency dedup: kept {len(kept)} fastest, removed {removed} slower duplicates")

    return kept


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

    # 0.5: Reject HLS sources with very long segments (high inherent latency)
    if MAX_SEGMENT_DURATION > 0:
        before = len(alive_results)
        alive_results = [
            r for r in alive_results
            if not r.is_hls or r.segment_duration_s <= 0 or r.segment_duration_s <= MAX_SEGMENT_DURATION
        ]
        high_latency_removed = before - len(alive_results)
        if high_latency_removed:
            logger.info(f"  High-latency HLS removed (>{MAX_SEGMENT_DURATION}s segment): {high_latency_removed}")

    # 0.6: Latency-based dedup — keep only fastest source per channel
    alive_results = latency_dedup(alive_results)

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
        "📰 新闻资讯": 3,
        "👶 少儿卡通": 4,
        "⚽ 体育频道": 5,
        "🎬 影视剧场": 6,
        "🎵 音乐娱乐": 7,
        "🎮 游戏电竞": 8,
        "📖 纪录频道": 9,
        "🛒 购物频道": 10,
        "🗺 地方频道": 11,
        "📺 其他频道": 12,
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
