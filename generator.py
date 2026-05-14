"""
M3U Generator
=============
Generates standard M3U playlist files with group-title tags.
Outputs both .m3u (with metadata) and .txt (URLs only).
"""

import logging
from datetime import datetime, timezone, timedelta

from config import OUTPUT_M3U, OUTPUT_TXT, DEFAULT_GROUP
from scanner import StreamEntry

logger = logging.getLogger("generator")

# Beijing timezone (UTC+8)
TZ_CN = timezone(timedelta(hours=8))


def generate_m3u(entries: list, output_path: str = None) -> str:
    """
    Generate a standard M3U playlist with EXTINF and group-title tags.

    Returns the generated M3U content as a string.
    """
    if output_path is None:
        output_path = OUTPUT_M3U

    now = datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append('#EXTM3U')
    lines.append(f'#PLAYLIST:国内IPTV直播源')
    lines.append(f'# Generated: {now} (UTC+8)')
    lines.append(f'# Total channels: {len(entries)}')
    lines.append(f'# Groups: 湖南 | 央视 | 卫视 | 少儿 | 体育 | 影视 | 纪录 | 地方 | 其他')

    current_group = None

    for entry in entries:
        group = entry.attrs.get("group-title", DEFAULT_GROUP)

        # Emit group separator
        if group != current_group:
            current_group = group
            lines.append("")
            lines.append(f"# ===== {group} =====")

        # EXTINF line with group-title
        lines.append(
            f'#EXTINF:-1 group-title="{group}",{entry.name}'
        )
        # URL line
        lines.append(entry.url)

    content = "\n".join(lines) + "\n"

    # Write to file
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"  M3U written: {output_path} ({len(entries)} channels)")
    except OSError as e:
        logger.error(f"  Failed to write M3U: {e}")

    return content


def generate_txt(entries: list, output_path: str = None) -> str:
    """
    Generate a simple text file: one URL per line.
    Includes a comment line with channel name before each URL.

    Returns the generated text content.
    """
    if output_path is None:
        output_path = OUTPUT_TXT

    now = datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append(f"# 国内IPTV直播源 - Generated: {now} (UTC+8)")
    lines.append(f"# Total: {len(entries)} channels")

    current_group = None

    for entry in entries:
        group = entry.attrs.get("group-title", DEFAULT_GROUP)

        if group != current_group:
            current_group = group
            lines.append("")
            lines.append(f"# ===== {group} =====")

        lines.append(f"# {entry.name}")
        lines.append(entry.url)

    content = "\n".join(lines) + "\n"

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"  TXT written: {output_path}")
    except OSError as e:
        logger.error(f"  Failed to write TXT: {e}")

    return content


def generate(entries: list) -> tuple:
    """
    Generate both M3U and TXT output files.

    Returns (m3u_content, txt_content).
    """
    logger.info("=" * 60)
    logger.info("STEP 5: GENERATING M3U PLAYLIST")
    logger.info("=" * 60)

    m3u_content = generate_m3u(entries)
    txt_content = generate_txt(entries)

    logger.info(f"  Total channels in playlist: {len(entries)}")
    return m3u_content, txt_content