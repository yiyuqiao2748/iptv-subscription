"""线路可用性探测。

P0/P2 共用。与 Apple TV 的真实播放路径保持一致是这里的第一原则：
探测默认**不走代理**，因为 Apple TV 上不会挂代理，只有直连能播的线路才是真可用。
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    http: int
    ms: int
    segments: int
    error: str = ""

    @property
    def score_hint(self) -> int:
        """P0 阶段的粗略质量分：可用加分，越快越高。P2 会换成三层探测 + 实测码率。"""
        if not self.ok:
            return -1
        return 100 - min(self.ms // 50, 60) + min(self.segments, 20)


def _opener(direct: bool):
    """direct=True 时显式禁用代理，模拟 Apple TV 的直连环境。"""
    if direct:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def probe(url: str, timeout: int = 12, direct: bool = True) -> ProbeResult:
    """两级检测：L1 连通 + L2 结构。

    L2 必须看到真实分片，因为实测中存在返回 200 但播放列表为空、
    或返回 HTML 错误页的假活源。
    """
    started = time.monotonic()
    body = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with _opener(direct).open(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read(65536).decode("utf-8", errors="replace")
            http = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        http = e.code
    except Exception as e:  # 超时 / DNS / 连接重置，一律判失效
        return ProbeResult(False, 0, int((time.monotonic() - started) * 1000), 0,
                           type(e).__name__)

    ms = int((time.monotonic() - started) * 1000)

    if "#EXTM3U" not in body:
        # 裸 .ts 分片直链：有体量就算可用
        ok = http == 200 and len(body) > 1024
        return ProbeResult(ok, http, ms, 0, "" if ok else "非播放列表且体量过小")

    segs = sum(1 for line in body.splitlines()
               if line.strip() and not line.strip().startswith("#"))
    if http != 200 or segs == 0:
        return ProbeResult(False, http, ms, segs, "空播放列表" if segs == 0 else f"HTTP {http}")
    return ProbeResult(True, http, ms, segs)


def probe_many(urls: list[str], timeout: int = 12, workers: int = 20,
               direct: bool = True) -> list[ProbeResult]:
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda u: probe(u, timeout, direct), urls))
