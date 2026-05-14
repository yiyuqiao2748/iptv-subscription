"""
Async Speed / Connectivity Tester
==================================
Tests each stream URL for connectivity and responsiveness using aiohttp.
Marks each stream: alive / dead / timeout.
"""

import asyncio
import time
import logging

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

    __slots__ = ("entry", "status", "response_time_ms", "http_status", "error", "bandwidth_kbps")

    def __init__(self, entry: StreamEntry, status: str, response_time_ms: float = 0,
                 http_status: int = 0, error: str = "", bandwidth_kbps: float = 0):
        self.entry = entry
        self.status = status
        self.response_time_ms = response_time_ms
        self.http_status = http_status
        self.error = error
        self.bandwidth_kbps = bandwidth_kbps

    @property
    def is_alive(self) -> bool:
        return self.status == STATUS_ALIVE


async def test_single_stream(
    session: aiohttp.ClientSession,
    entry: StreamEntry,
    semaphore: asyncio.Semaphore,
) -> TestResult:
    """
    Test a single stream URL for basic connectivity.
    Uses a semaphore to limit concurrency.
    """
    async with semaphore:
        for attempt in range(TEST_RETRY + 1):
            try:
                start = time.monotonic()
                timeout = ClientTimeout(total=TEST_TIMEOUT, connect=TEST_TIMEOUT - 1)

                # Perform a HEAD request first (lighter), fallback to GET
                try:
                    async with session.head(
                        entry.url,
                        timeout=timeout,
                        allow_redirects=True,
                        ssl=False,
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

                # HEAD failed or unstable, try GET with bandwidth measurement
                start = time.monotonic()
                async with session.get(
                    entry.url,
                    timeout=timeout,
                    allow_redirects=True,
                    ssl=False,
                ) as resp:
                    # Read data for up to 2 seconds to measure bandwidth
                    total_bytes = 0
                    read_end = start + 2.0  # 2-second bandwidth window
                    try:
                        while time.monotonic() < read_end:
                            chunk = await asyncio.wait_for(
                                resp.content.read(16384),
                                timeout=1.0,
                            )
                            if not chunk:
                                break
                            total_bytes += len(chunk)
                    except asyncio.TimeoutError:
                        pass

                    elapsed_ms = (time.monotonic() - start) * 1000
                    # Calculate bandwidth: bytes / seconds
                    download_time = max(elapsed_ms / 1000.0, 0.5)  # at least 0.5s to avoid division by tiny numbers
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
                        # Connected but no data
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
                    return TestResult(
                        entry=entry,
                        status=STATUS_TIMEOUT,
                        error="Connection timed out",
                    )
                await asyncio.sleep(0.5)

            except ClientError as e:
                if attempt >= TEST_RETRY:
                    return TestResult(
                        entry=entry,
                        status=STATUS_ERROR,
                        error=str(e)[:100],
                    )
                await asyncio.sleep(0.5)

            except OSError as e:
                return TestResult(
                    entry=entry,
                    status=STATUS_ERROR,
                    error=str(e)[:100],
                )

            except Exception as e:
                return TestResult(
                    entry=entry,
                    status=STATUS_ERROR,
                    error=f"{type(e).__name__}: {str(e)[:80]}",
                )

        # Should not reach here
        return TestResult(entry=entry, status=STATUS_DEAD, error="All retries exhausted")


async def test_all_streams(entries: list) -> list:
    """
    Test all streams concurrently using aiohttp.
    Returns list of TestResult objects.

    NOTE: On Windows, this function must be called from within a running
    event loop created by asyncio.run().
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

        # Process in batches to show progress
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

    logger.info(f"  Testing complete in {total_time:.1f}s")
    logger.info(f"  Alive: {alive} | Dead: {dead}")
    logger.info(f"  Success rate: {alive / len(results) * 100:.1f}%" if results else "  No streams tested")

    return results