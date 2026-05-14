"""
Deduplication & Merging
=======================
Removes duplicate stream URLs and merges channels with the same name.
Hunan channels get special treatment: keep up to 3 alternative sources.
"""

import re
import logging
from difflib import SequenceMatcher

from config import (
    HUNAN_KEYWORDS,
    HUNAN_MAX_DUPES,
    OTHER_MAX_DUPES,
)
from scanner import StreamEntry

logger = logging.getLogger("dedup")


def is_hunan_channel(name: str) -> bool:
    """Check if a channel name matches Hunan-related keywords."""
    for kw in HUNAN_KEYWORDS:
        if kw in name:
            return True
    return False


def normalize_name(name: str) -> str:
    """Normalize a channel name for fuzzy comparison."""
    # Remove common suffixes/prefixes
    cleaned = re.sub(r'[\s_\-]+', '', name)
    cleaned = cleaned.upper()
    cleaned = re.sub(r'(高清|超清|HD|SD|4K|1080P|720P|标清|流畅)$', '', cleaned)
    cleaned = re.sub(r'(IPV6|IPV4|V6|V4)$', '', cleaned)
    return cleaned


def names_are_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    """Check if two channel names likely refer to the same channel."""
    na = normalize_name(a)
    nb = normalize_name(b)
    if na == nb:
        return True
    # Check if one contains the other
    if len(na) >= 3 and na in nb:
        return True
    if len(nb) >= 3 and nb in na:
        return True
    # Sequence similarity
    ratio = SequenceMatcher(None, na, nb).ratio()
    return ratio >= threshold


def deduplicate(entries: list) -> list:
    """
    Deduplicate streams:
    1. Remove exact URL duplicates
    2. For channels with same/similar names, keep best N sources
       (N=3 for Hunan, N=1 for others)
    3. Remove obviously bad names (empty, too short, etc.)

    Returns filtered list of StreamEntry objects.
    """
    logger.info("=" * 60)
    logger.info("STEP 2: DEDUPLICATION")
    logger.info("=" * 60)

    initial_count = len(entries)

    # 1. Remove exact URL duplicates
    seen_urls = set()
    url_deduped = []
    for entry in entries:
        url_key = entry.url_hash()
        if url_key not in seen_urls:
            seen_urls.add(url_key)
            url_deduped.append(entry)

    url_removed = initial_count - len(url_deduped)
    logger.info(f"  Exact URL duplicates removed: {url_removed}")
    logger.info(f"  After URL dedup: {len(url_deduped)} streams")

    # 2. Remove streams with empty/bad names
    named_entries = []
    for entry in url_deduped:
        name = entry.name.strip()
        if not name or len(name) < 2 or name == "Unknown":
            continue
        named_entries.append(entry)

    name_removed = len(url_deduped) - len(named_entries)
    logger.info(f"  Nameless entries removed: {name_removed}")
    logger.info(f"  After name filter: {len(named_entries)} streams")

    # 3. Group by similar channel name, keep limited copies
    groups: dict[str, list] = {}  # canonical_name -> [entries]
    canonical_order = []

    for entry in named_entries:
        # Find matching group
        matched = False
        for canon in canonical_order:
            if names_are_similar(entry.name, canon):
                groups[canon].append(entry)
                matched = True
                break
        if not matched:
            # New group
            groups[entry.name] = [entry]
            canonical_order.append(entry.name)

    # 4. Within each group, sort trusted first, then limit copies
    final_entries = []
    hunan_groups = 0
    trusted_kept = 0
    untrusted_kept = 0
    for canon in canonical_order:
        group = groups[canon]
        is_hunan = is_hunan_channel(canon)
        if is_hunan:
            hunan_groups += 1
            max_copies = HUNAN_MAX_DUPES
        else:
            max_copies = OTHER_MAX_DUPES

        # Trusted (vbskycn verified) entries always come first
        trusted = [e for e in group if e.trusted]
        untrusted = [e for e in group if not e.trusted]
        # Within same trust level, prefer entries WITH group-title (better metadata)
        trusted.sort(key=lambda e: 0 if e.attrs.get("group-title") else 1)
        untrusted.sort(key=lambda e: 0 if e.attrs.get("group-title") else 1)

        kept = trusted + untrusted
        kept = kept[:max_copies]
        trusted_kept += sum(1 for e in kept if e.trusted)
        untrusted_kept += sum(1 for e in kept if not e.trusted)
        final_entries.extend(kept)

    logger.info(f"  Channel groups formed: {len(canonical_order)}")
    logger.info(f"  Hunan channel groups: {hunan_groups}")
    logger.info(f"  Trusted (vbskycn) kept: {trusted_kept}")
    logger.info(f"  Untrusted kept: {untrusted_kept}")
    logger.info(f"  After group dedup: {len(final_entries)} streams")
    logger.info(f"  Total removed: {initial_count - len(final_entries)}")

    return final_entries