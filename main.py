"""
IPTV Auto-Subscription Pipeline
================================
Main entry point. Orchestrates the full pipeline:

1. Scanner  → Pull M3U/TXT from public IPTV repos + GitHub Hunan search
2. Dedup    → Remove duplicates, group similar channels, keep Hunan spares
3. Tester   → Async connectivity test for every stream URL
4. Filter   → Remove dead streams, foreign channels; assign group categories
5. Generator → Produce M3U + TXT playlist files
6. Server   → Flask HTTP server serving M3U for APTV subscription
7. Scheduler → Periodic auto-update (default: every 6 hours)

Usage:
    python main.py                    # Run full pipeline + start server
    python main.py --scan-only        # Run pipeline once, then exit
    python main.py --port 8899        # Custom port
    python main.py --interval 2       # Update every 2 hours
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

import config
from scanner import StreamEntry

# ------------------------------------------------------------
# Logging Setup
# ------------------------------------------------------------
def setup_logging(level=logging.INFO):
    """Configure console + rotating file logging."""
    # Force UTF-8 on Windows console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    # Rotating file (10MB x 5 backups)
    log_dir = os.path.join(config.BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "pipeline.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # Quiet noisy libraries
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("waitress").setLevel(logging.WARNING)


TZ_CN = timezone(timedelta(hours=8))

# Activation state (set by main() in desktop mode)
_UNACTIVATED_LIMIT = 50
_is_activated = True  # default: unlimited for non-desktop mode


def inject_fallback_streams(entries: list) -> list:
    """
    Inject known-stable fallback URLs for must-have channels.
    Uses fuzzy matching to check if channel already exists.
    Each fallback channel contributes up to 3 alternate URLs.
    """
    from dedup import is_hunan_channel

    logger = logging.getLogger("pipeline")

    # Build a set of normalized existing names for fuzzy matching
    # IMPORTANT: only strip quality/format suffixes, NOT semantic ones like 卫视/频道/电视台
    existing_names = set()
    for e in entries:
        core_name = e.name.strip().lower()
        # Only remove format/quality markers, not semantic channel-type suffixes
        for suffix in ['hd', '4k', '超高清', '高清', '(576i)', '(720p)', '(1080p)', '(4k)',
                       '[geo-blocked]', '[ipv6]', '[ipv4]']:
            core_name = core_name.replace(suffix, '')
        core_name = core_name.strip().strip('-').strip()
        if len(core_name) >= 2:  # skip garbage like lone "cctv"
            existing_names.add(core_name)

    fallback_source = "fallback_stable"
    fallback_entries = []

    for channel_name, urls in config.FALLBACK_STREAMS.items():
        # Extract core name from fallback channel (strip quality suffixes only)
        core_fallback = channel_name.strip().lower()
        for suffix in ['hd', '4k', '超高清', '高清', '(576i)', '(720p)', '(1080p)', '(4k)']:
            core_fallback = core_fallback.replace(suffix, '')
        core_fallback = core_fallback.strip().strip('-').strip()
        
        # Check if any existing channel matches this fallback
        # Strategy: full name match OR prefix match (not substring, to avoid
        # short fragments like "cctv" from blocking all CCTV variants)
        already_exists = False
        fallback_full = channel_name.strip().lower()
        for existing in existing_names:
            # Full original names match
            if existing == fallback_full:
                already_exists = True
                break
            # Prefix match: one is a prefix of the other AND the shorter is >= 5 chars
            if len(core_fallback) >= 5 and len(existing) >= 5:
                shorter = core_fallback if len(core_fallback) < len(existing) else existing
                longer = existing if len(core_fallback) < len(existing) else core_fallback
                if longer.startswith(shorter):
                    already_exists = True
                    break
        
        if already_exists:
            continue

        # Add fallback URLs for this channel
        for url in urls[:3]:  # max 3 fallback URLs per channel
            group = "🏠 湖南频道" if is_hunan_channel(channel_name) \
                else "📺 央视频道" if "CCTV" in channel_name.upper() \
                else "📺 其他频道"
            entry = StreamEntry(
                name=channel_name,
                url=url,
                source=fallback_source,
                attrs={"group-title": group},
                trusted=True
            )
            fallback_entries.append(entry)

    if fallback_entries:
        logger.info(f"  Injected {len(fallback_entries)} fallback URLs for missing required channels")
    return fallback_entries


# ------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------
async def run_pipeline(skip_test: bool = False) -> dict:
    """
    Execute the full pipeline.
    If skip_test is True, all deduped streams pass connectivity check.
    Returns stats dict with channel counts.
    """
    from scanner import scan_all_sources
    from dedup import deduplicate
    from tester import test_all_streams, TestResult, STATUS_ALIVE
    from filter import filter_streams
    from generator import generate
    from server import update_stats as update_server_stats

    logger = logging.getLogger("pipeline")
    total_start = time.monotonic()

    # Step 1: Scan
    raw_entries = scan_all_sources()
    if not raw_entries:
        logger.warning("No streams found. Check network or source availability.")
        return {"total_scanned": 0, "alive": 0, "final": 0}

    # Step 2: Dedup
    deduped_entries = deduplicate(raw_entries)

    # Step 3: Test (or skip)
    if skip_test:
        logger.info("STEP 3: SKIPPED (--skip-test)")
        results = [TestResult(entry=e, status=STATUS_ALIVE) for e in deduped_entries]
    else:
        results = await test_all_streams(deduped_entries)

    alive_count = sum(1 for r in results if r.is_alive)
    update_server_stats({
        "total_channels": len(results),
        "alive_channels": alive_count,
    })

    # Step 4: Filter (dead + foreign removal, category assignment)
    filtered_entries = filter_streams(results)

    # Step 4.5: Inject fallback streams
    fallback_entries = inject_fallback_streams(filtered_entries)
    filtered_entries.extend(fallback_entries)

    # Step 4.8: Limit channels for unactivated users
    if not _is_activated and len(filtered_entries) > _UNACTIVATED_LIMIT:
        logger.warning(f"  未激活版本：频道数限制为 {_UNACTIVATED_LIMIT}（共 {len(filtered_entries)} 个）")
        filtered_entries = filtered_entries[:_UNACTIVATED_LIMIT]

    # Step 5: Generate M3U + TXT
    generate(filtered_entries)

    total_elapsed = time.monotonic() - total_start
    logger.info("=" * 60)
    logger.info(f"FULL PIPELINE COMPLETE in {total_elapsed:.1f}s")
    logger.info(f"   Source URLs scanned: {len(raw_entries)}")
    logger.info(f"   After dedup:         {len(deduped_entries)}")
    logger.info(f"   Alive streams:       {alive_count}")
    logger.info(f"   Final in M3U:        {len(filtered_entries)}")
    logger.info("=" * 60)

    return {
        "total_scanned": len(raw_entries),
        "after_dedup": len(deduped_entries),
        "alive": alive_count,
        "final": len(filtered_entries),
        "elapsed": round(total_elapsed, 1),
    }


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="IPTV Auto-Subscription Pipeline for APTV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Full pipeline + server + scheduler
  python main.py --desktop          # Desktop mode: tray icon + auto browser
  python main.py --scan-only        # Run once and exit
  python main.py --port 9999        # Custom port
  python main.py --interval 12      # Update every 12 hours
  python main.py --cron "0 */8 * * *"  # Use cron expression
        """,
    )
    parser.add_argument("--scan-only", action="store_true",
                        help="Run pipeline once, then exit (no server)")
    parser.add_argument("--port", type=int, default=8899,
                        help="HTTP server port (default: 8899)")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="HTTP server host (default: 0.0.0.0)")
    parser.add_argument("--interval", type=int, default=6,
                        help="Update interval in hours (default: 6)")
    parser.add_argument("--cron", type=str, default=None,
                        help="Cron expression for updates (overrides --interval)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--no-scheduler", action="store_true",
                        help="Don't start scheduler (server only)")
    parser.add_argument("--skip-test", action="store_true",
                        help="Skip connectivity testing (all streams pass)")
    parser.add_argument("--desktop", action="store_true",
                        help="Desktop mode: system tray + auto-open browser")
    args = parser.parse_args()

    # Auto-enable desktop mode when running as PyInstaller exe
    if getattr(sys, 'frozen', False) and not args.scan_only:
        args.desktop = True

    # Setup
    level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level)
    logger = logging.getLogger("main")

    # Override config from CLI
    import config as cfg
    cfg.SERVER_PORT = args.port
    cfg.SERVER_HOST = args.host
    if args.cron:
        cfg.UPDATE_CRON = args.cron
    else:
        cfg.UPDATE_INTERVAL_HOURS = args.interval

    logger.info("=" * 70)
    logger.info("  📡 IPTV AUTO-SUBSCRIPTION PIPELINE")
    logger.info("=" * 70)
    logger.info(f"  Output M3U: {cfg.OUTPUT_M3U}")
    logger.info(f"  Server:     http://{args.host}:{args.port}{cfg.SUBSCRIPTION_ROUTE}")
    if args.scan_only:
        logger.info("  Mode:       Scan-only (no server)")
    else:
        logger.info(f"  Interval:   {args.interval}h" if not args.cron else f"  Cron:       {args.cron}")
    logger.info("=" * 70)

    # Scan-only mode
    if args.scan_only:
        asyncio.run(run_pipeline(skip_test=args.skip_test))
        logger.info("Scan-only complete. Exiting.")
        return

    # --------------------------------------------------------
    # Desktop mode: single instance check + activation
    # --------------------------------------------------------
    _activated = False
    if args.desktop:
        from desktop import check_single_instance, IPTVDesktop, show_activation_dialog, show_first_run_guide
        if not check_single_instance():
            logger.error("IPTV 订阅服务已在运行中！请勿重复启动。")
            sys.exit(1)
        # Show first-run guide (no-op if already shown)
        show_first_run_guide()
        # Show activation dialog (returns immediately if already activated)
        _activated = show_activation_dialog()

    # Set module-level activation state for pipeline channel limiting
    global _is_activated
    _is_activated = _activated if args.desktop else True

    # --------------------------------------------------------
    # Full mode: Server + Scheduler
    # --------------------------------------------------------
    from server import run_server, update_stats, set_trigger_callback
    from scheduler import IPTVScheduler

    # Create scheduler
    scheduler = IPTVScheduler(
        pipeline_func=run_pipeline,
        server_update_func=update_stats,
    )

    # Wire up server trigger callback
    set_trigger_callback(scheduler.run_now)

    # Start server in a daemon thread
    server_thread = threading.Thread(
        target=run_server,
        kwargs={"host": args.host, "port": args.port},
        daemon=True,
    )
    server_thread.start()

    # Give server a moment to start
    time.sleep(1)

    # Start scheduler (runs first pipeline immediately)
    if not args.no_scheduler:
        scheduler.start(run_immediately=True)
    else:
        # Run once
        logger.info("Running one-time pipeline...")
        asyncio.run(run_pipeline())

    # Desktop mode: GUI window + tray icon (blocks main thread)
    if args.desktop:
        logger.info("Desktop mode active.")
        app = IPTVDesktop(port=args.port, update_cb=scheduler.run_now, activated=_activated)
        app.run()
    else:
        # Keep main thread alive
        try:
            logger.info("Service running. Press Ctrl+C to stop.")
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
            scheduler.stop()
            logger.info("Goodbye! 👋")
            sys.exit(0)


if __name__ == "__main__":
    main()