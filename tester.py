"""
Async Speed / Connectivity Tester
==================================
Tests each stream URL for connectivity and responsiveness using aiohttp.
For HLS (.m3u8) streams: parses manifest, probes first .ts segment for real throughput.
Marks each stream: alive / dead / timeout.
"""

import asyncio
import re
import time
import logging
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientTimeout, ClientError

from config import TEST_TIMEOUT, TEST_CONCURRENT, TEST_RETRY, TEST_MIN_BITRATE
from scanner import StreamEntry

logger = logging.getLogger("tester")

# Result status constants
STATUS_ALIVE = "alive"
STATUS_DEAD = "dead"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"
STATUS_SLOW = "slow"  # connected but bandwidth too low


class TestResult:
    """Result of testing a single stream."""

    __slots__ = ("entry", "status", "response_time_ms", "http_status", "error",
                 "bandwidth_kbps", "segment_duration_s", "is_hls")

    def __init__(self, entry: StreamEntry, status: str, response_time_ms: float = 0,
                 http_status: int = 0, error: str = "", bandwidth_kbps: float = 0,
                 segment_duration_s: float = 0, is_hls: bool = False):
        self.entry = entry
        self.status = status
        self.response_time_ms = response_time_ms
        self.http_status = http_status
        self.error = error
        self.bandwidth_kbps = bandwidth_kbps
        self.segment_duration_s = segment_duration_s
        self.is_hls = is_hls

    @property
    def is_alive(self) -> bool:
        return self.status == STATUS_ALIVE

    @property
    def estimated_latency_s(self) -> float:
        """Estimated playback latency in seconds based on source type."""
        if self.is_hls and self.segment_duration_s > 0:
            # HLS latency ≈ 3 * segment_duration (buffer 3 segments)
            return self.segment_duration_s * 3
        elif self.is_hls:
            return 10.0  # default HLS assumption
        else:
            # Direct stream (RTP, RTSP, etc.)
            return self.response_time_ms / 1000.0 + 1.0


def _parse_m3u8_segments(manifest_text: str, manifest_url: str) -> tuple:
    """
    Parse M3U8 manifest for:
    - target_duration (float, seconds)
    - first .ts segment URL (absolute)
    - is_live (bool) - True if #EXT-X-ENDLIST is NOT present
    """
    target_duration = 0.0
    first_segment = None
    lines = manifest_text.splitlines()

    for line in lines:
        line = line.strip()
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = float(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass

    # Find first segment URL (line that's not a tag and looks like a URL)
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http://") or line.startswith("https://"):
            first_segment = line
            break
        elif line.endswith(".ts") or line.endswith(".m4s") or "/" in line:
            # Relative URL - resolve against manifest URL
            first_segment = urljoin(manifest_url, line)
            break

    return target_duration, first_segment


async def _probe_hls_segment(
    session: aiohttp.ClientSession,
    manifest_url: str,
    timeout: ClientTimeout,
) -> tuple:
    """
    Download M3U8 manifest, then probe the first .ts segment.
    Returns (segment_duration_s, segment_bps, error_str).
    """
    try:
        # 1. Download manifest
        async with session.get(manifest_url, timeout=timeout, allow_redirects=True, ssl=False) as resp:
            if resp.status != 200:
                return 0, 0, f"Manifest HTTP {resp.status}"
            manifest_text = await resp.text()

        if "#EXTM3U" not in manifest_text[:200]:
            return 0, 0, "Not a valid M3U8"

        target_duration, segment_url = _parse_m3u8_segments(manifest_text, manifest_url)

        if not segment_url:
            return target_duration, 0, "No segment URL found"

        # 2. Download first segment, measure speed
        seg_start = time.monotonic()
        total_bytes = 0
        # Read for up to 3 seconds or 512KB (whichever comes first)
        async with session.get(segment_url, timeout=timeout, allow_redirects=True, ssl=False) as resp:
            if resp.status not in (200, 206):
                return target_duration, 0, f"Segment HTTP {resp.status}"
            while total_bytes < 512 * 1024:
                try:
                    chunk = await asyncio.wait_for(resp.content.read(32768), timeout=1.5)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                except asyncio.TimeoutError:
                    break

        seg_elapsed = max(time.monotonic() - seg_start, 0.1)
        seg_bps = (total_bytes * 8) / seg_elapsed  # bits per second

        return target_duration, seg_bps, ""

    except asyncio.TimeoutError:
        return 0, 0, "HLS probe timeout"
    except Exception as e:
        return 0, 0, str(e)[:80]


async def test_single_stream(
    session: aiohttp.ClientSession,
    entry: StreamEntry,
    semaphore: asyncio.Semaphore,
) -> TestResult:
    """
    Test a single stream URL.
    For HLS: probe manifest + first segment for real throughput.
    For direct streams: HEAD then GET with bandwidth measurement.
    """
    async with semaphore:
        for attempt in range(TEST_RETRY + 1):
            try:
                timeout = ClientTimeout(total=TEST_TIMEOUT, connect=TEST_TIMEOUT - 1)
                is_hls = ".m3u8" in entry.url.lower()

                # --- HLS streams: probe segments ---
                if is_hls:
                    start = time.monotonic()
                    seg_duration, seg_bps, err = await _probe_hls_segment(session, entry.url, timeout)
                    elapsed_ms = (time.monotonic() - start) * 1000

                    if err and seg_bps == 0:
                        return TestResult(
                            entry=entry,
                            status=STATUS_DEAD,
                            response_time_ms=round(elapsed_ms, 1),
                            error=err,
                            is_hls=True,
                        )

                    bw_kbps = seg_bps / 1000.0
                    if bw_kbps >= TEST_MIN_BITRATE:
                        return TestResult(
                            entry=entry,
                            status=STATUS_ALIVE,
                            response_time_ms=round(elapsed_ms, 1),
                            bandwidth_kbps=round(bw_kbps, 1),
                            segment_duration_s=seg_duration,
                            is_hls=True,
                        )
                    else:
                        return TestResult(
                            entry=entry,
                            status=STATUS_SLOW,
                            response_time_ms=round(elapsed_ms, 1),
                            error=f"Segment {bw_kbps:.0f}kbps < {TEST_MIN_BITRATE}kbps",
                            bandwidth_kbps=round(bw_kbps, 1),
                            segment_duration_s=seg_duration,
                            is_hls=True,
                        )

                # --- Non-HLS streams (RTP, RTSP, direct HTTP) ---
                # Try HEAD first
                start = time.monotonic()
                try:
                    async with session.head(
                        entry.url, timeout=timeout, allow_redirects=True, ssl=False,
                    ) as resp:
                        elapsed = (time.monotonic() - start) * 1000
                        if 200 <= resp.status < 500 or resp.status in (302, 301):
                            return TestResult(
                                entry=entry,
                                status=STATUS_ALIVE,
                                response_time_ms=round(elapsed, 1),
                                http_status=resp.status,
                            )
                except (ClientError, asyncio.TimeoutError, OSError):
                    pass

                # HEAD failed, try GET with bandwidth measurement
                start = time.monotonic()
                async with session.get(
                    entry.url, timeout=timeout, allow_redirects=True, ssl=False,
                ) as resp:
                    total_bytes = 0
                    read_end = start + 2.0
                    try:
                        while time.monotonic() < read_end:
                            chunk = await asyncio.wait_for(
                                resp.content.read(16384), timeout=1.0,
                            )
                            if not chunk:
                                break
                            total_bytes += len(chunk)
                    except asyncio.TimeoutError:
                        pass

                    elapsed_ms = (time.monotonic() - start) * 1000
                    download_time = max(elapsed_ms / 1000.0, 0.5)
                    bw_kbps = (total_bytes * 8) / download_time / 1000.0

                    if 200 <= resp.status < 500 and total_bytes > 0:
                        if bw_kbps >= TEST_MIN_BITRATE:
                            return TestResult(
                                entry=entry,
                                status=STATUS_ALIVE,
                                response_time_ms=round(elapsed_ms, 1),
                                http_status=resp.status,
                                bandwidth_kbps=round(bw_kbps, 1),
                            )
                        else:
                            return TestResult(
                                entry=entry,
                                status=STATUS_SLOW,
                                response_time_ms=round(elapsed_ms, 1),
                                http_status=resp.status,
                                error=f"Bandwidth {bw_kbps:.0f}kbps < {TEST_MIN_BITRATE}kbps",
                                bandwidth_kbps=round(bw_kbps, 1),
                            )
                    elif 200 <= resp.status < 500:
                        return TestResult(
                            entry=entry,
                            status=STATUS_DEAD,
                            response_time_ms=round(elapsed_ms, 1),
                            http_status=resp.status,
                            error="No data received",
                        )
                    else:
                        return TestResult(
                            entry=entry,
                            status=STATUS_DEAD,
                            http_status=resp.status,
                            error=f"HTTP {resp.status}",
                        )

            except asyncio.TimeoutError:
                if attempt >= TEST_RETRY:
                    return TestResult(entry=entry, status=STATUS_TIMEOUT, error="Connection timed out")
                await asyncio.sleep(0.5)

            except ClientError as e:
                if attempt >= TEST_RETRY:
                    return TestResult(entry=entry, status=STATUS_ERROR, error=str(e)[:100])
                await asyncio.sleep(0.5)

            except OSError as e:
                return TestResult(entry=entry, status=STATUS_ERROR, error=str(e)[:100])

            except Exception as e:
                return TestResult(entry=entry, status=STATUS_ERROR, error=f"{type(e).__name__}: {str(e)[:80]}")

        return TestResult(entry=entry, status=STATUS_DEAD, error="All retries exhausted")


async def test_all_streams(entries: list) -> list:
    """
    Test all streams concurrently using aiohttp.
    Returns list of TestResult objects.
    """
    logger.info("=" * 60)
    logger.info("STEP 3: CONNECTIVITY TESTING")
    logger.info("=" * 60)
    logger.info(f"  Streams to test: {len(entries)}")
    logger.info(f"  Concurrency: {TEST_CONCURRENT}")
    logger.info(f"  Timeout per stream: {TEST_TIMEOUT}s")
    logger.info(f"  Retries: {TEST_RETRY}")

    semaphore = asyncio.Semaphore(TEST_CONCURRENT)
    connector = aiohttp.TCPConnector(
        limit=TEST_CONCURRENT + 20,
        limit_per_host=5,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
        force_close=False,
    )
    timeout = ClientTimeout(total=TEST_TIMEOUT + 2, connect=TEST_TIMEOUT)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    ) as session:
        tasks = [test_single_stream(session, entry, semaphore) for entry in entries]

        results = []
        total = len(entries)
        batch_size = max(1, min(200, TEST_CONCURRENT * 3))
        alive_count = 0
        dead_count = 0

        start_time = time.monotonic()

        for i in range(0, total, batch_size):
            batch = tasks[i : i + batch_size]
            batch_results = await asyncio.gather(*batch)
            results.extend(batch_results)

            batch_alive = sum(1 for r in batch_results if r.is_alive)
            alive_count += batch_alive
            dead_count += len(batch_results) - batch_alive

            elapsed = time.monotonic() - start_time
            tested = min(i + batch_size, total)
            pct = tested / total * 100
            logger.info(
                f"  Progress: {tested}/{total} ({pct:.1f}%) | "
                f"Alive: {alive_count} | Dead: {dead_count} | "
                f"Time: {elapsed:.1f}s"
            )

    total_time = time.monotonic() - start_time
    alive = sum(1 for r in results if r.is_alive)
    dead = len(results) - alive

    # Log latency stats for alive streams
    hls_alive = [r for r in results if r.is_alive and r.is_hls]
    direct_alive = [r for r in results if r.is_alive and not r.is_hls]
    if hls_alive:
        avg_dur = sum(r.segment_duration_s for r in hls_alive) / len(hls_alive)
        fast = sum(1 for r in hls_alive if r.segment_duration_s <= 2)
        slow = sum(1 for r in hls_alive if r.segment_duration_s > 5)
        logger.info(f"  HLS streams: {len(hls_alive)} alive, avg segment {avg_dur:.1f}s, fast(<=2s): {fast}, slow(>5s): {slow}")
    if direct_alive:
        avg_ms = sum(r.response_time_ms for r in direct_alive) / len(direct_alive)
        logger.info(f"  Direct streams: {len(direct_alive)} alive, avg response {avg_ms:.0f}ms")

    logger.info(f"  Testing complete in {total_time:.1f}s")
    logger.info(f"  Alive: {alive} | Dead: {dead}")
    logger.info(f"  Success rate: {alive / len(results) * 100:.1f}%" if results else "  No streams tested")

    return results
