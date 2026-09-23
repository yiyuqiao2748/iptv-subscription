"""线路可用性探测。

P0/P2 共用。与 Apple TV 的真实播放路径保持一致是这里的第一原则：
探测默认**不走代理**，因为 Apple TV 上不会挂代理，只有直连能播的线路才是真可用。

L2 不只看「有没有分片」，还要分得出这条 m3u8 到底是什么（ProbeResult.kind）：

  live    直播列表 —— 分片少且滚动，没有 ENDLIST
  master  多码率索引 —— 里面是变体地址而不是分片，需要再跟一跳才能确认真流
  vod     录播/循环 —— 有 ENDLIST，或分片成百上千。挂在电视频道名下就是假直播，
          2026-09-21 实测到一条 1259 分片的快手 CDN 录像挂在湖南卫视名下，
          只验「有分片」会被当成可用线路，比超时更坏（用户以为这个台就这样）。
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"

# 分片数超过这个值就当录播：直播滑动窗口一般 3~10 片，卫视回看也就几十片，
# 上千片只可能是整档节目。留足够余量，避免把长窗口直播误杀。
VOD_SEGMENTS = 300

# 判为假直播的 kind。master:vod 是「多码率索引 → 变体是录像」，同样不是直播。
FAKE_KINDS = ("vod", "master:vod")


def quoted_url(url: str) -> str:
    """把 URL 里的非 ASCII 字符转义，其他部分原样保留。

    上游确实存在中文路径（iptv-api 的 `.../芒果影视.m3u8`、`?A$电信高清720P`），
    urllib 直接抛 UnicodeEncodeError，于是这些线路在实测里被记成失效 —— 假阴性。
    抓取侧 fetch() 早就做了这件事，探测侧漏了。

    >>> quoted_url("http://1.2.3.4/湖南.m3u8")
    'http://1.2.3.4/%E6%B9%96%E5%8D%97.m3u8'
    >>> quoted_url("http://1.2.3.4/a.m3u8?x=1&y=%E5%B7%B2%E7%BB%8F%E8%BD%AC%E4%B9%89")  # 已转义的不二次编码
    'http://1.2.3.4/a.m3u8?x=1&y=%E5%B7%B2%E7%BB%8F%E8%BD%AC%E4%B9%89'
    >>> quoted_url("rtp://@239.1.1.1:6002")     # 非 http 原样返回
    'rtp://@239.1.1.1:6002'
    """
    if not url.startswith(("http://", "https://")):
        return url
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((
        parts.scheme,
        parts.netloc.encode("idna").decode("ascii") if any(
            ord(c) > 127 for c in parts.netloc) else parts.netloc,
        urllib.parse.quote(parts.path, safe="/%:@&=+$,;~!*'()"),
        urllib.parse.quote(parts.query, safe="/%:@&=+$,;~!*'()"),
        parts.fragment,
    ))


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    http: int
    ms: int
    segments: int
    error: str = ""
    kind: str = ""                 # live / master / vod / raw，空串表示没测出来


def classify(body: str) -> tuple[str, int]:
    """从播放列表正文判断它是哪种流、有多少分片。

    >>> classify("#EXTM3U\\n#EXT-X-TARGETDURATION:10\\n#EXTINF:10,\\na.ts\\nb.ts\\n")
    ('live', 2)
    >>> classify("#EXTM3U\\n#EXT-X-STREAM-INF:BANDWIDTH=500000\\n/lo.m3u8\\n")   # 多码率索引
    ('master', 1)
    >>> classify("#EXTM3U\\n#EXTINF:10,\\na.ts\\n#EXT-X-ENDLIST\\n")             # 录播：有 ENDLIST
    ('vod', 1)
    >>> classify("#EXTM3U\\n" + "".join(f"#EXTINF:10,\\ns{i}.ts\\n" for i in range(400)))
    ('vod', 400)
    """
    segs = sum(1 for line in body.splitlines()
               if line.strip() and not line.strip().startswith("#"))
    if "#EXT-X-STREAM-INF" in body:
        return "master", segs
    if "#EXT-X-ENDLIST" in body or segs >= VOD_SEGMENTS:
        return "vod", segs
    return "live", segs


def is_fake_live(r: "ProbeResult | None") -> bool:
    """这条线路是不是「假直播」：连得上、有分片，但内容是循环录像。

    只用于降档，不用于删除 —— 一个台如果只有循环录像和够不着的内网地址，
    留录像至少还有画，但要在使用报告里点名，让人知道它不是直播。

    >>> is_fake_live(ProbeResult(True, 200, 300, 1259, "", "vod"))
    True
    >>> is_fake_live(ProbeResult(True, 200, 100, 3, "", "live"))
    False
    >>> is_fake_live(None)                       # 没实测过，不冤枉它
    False
    """
    return r is not None and r.kind in FAKE_KINDS


def segment_window(body: str) -> list[str]:
    """播放列表里的分片名序列，用来比对窗口是否向前滚动。

    >>> segment_window("#EXTM3U\\n#EXT-X-MEDIA-SEQUENCE:5\\n#EXTINF:10,\\na.ts\\nb.ts\\n")
    ['a.ts', 'b.ts']
    """
    return [line.strip() for line in body.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def roll_verdict(first: str, second: str) -> str:
    """L3 的判据：隔几秒重取，分片窗口往前走才是真直播。

    L2 识不破的一类假活源是「只有 3~5 个分片、但永远不动」——
    它没有 ENDLIST、分片也不多，classify() 会当成 live，
    实际是一段循环的录像或者早已停推的残留列表。

    >>> roll_verdict("#EXTM3U\\na1.ts\\n", "#EXTM3U\\na2.ts\\n")
    'rolling'
    >>> roll_verdict("#EXTM3U\\na1.ts\\n", "#EXTM3U\\na1.ts\\n")
    'stuck'
    >>> roll_verdict("#EXTM3U\\na1.ts\\n#EXT-X-ENDLIST\\n", "#EXTM3U\\na1.ts\\n#EXT-X-ENDLIST\\n")
    'vod'
    >>> roll_verdict("#EXTM3U\\n#EXT-X-STREAM-INF:x\\n/lo.m3u8\\n", "#EXTM3U\\n#EXT-X-STREAM-INF:x\\n/lo.m3u8\\n")
    'master'
    """
    if "#EXT-X-STREAM-INF" in first:
        return "master"          # 索引本身当然不动，要看变体 —— 交给 l3_roll 跟一跳
    if "#EXT-X-ENDLIST" in first:
        return "vod"
    return "rolling" if segment_window(first) != segment_window(second) else "stuck"


def raw_kind(body: str) -> str:
    """不是 m3u8 的响应体到底是什么容器：ts / flv / mp4 / html / bin。

    原来只要「有 #EXTM3U 之外还有 1KB 以上」就算裸分片直链可用，结果 2026-09-21 实测到
    `live.264788.xyz/channel/cctv17?streamid=<32位哈希>` 返回的是
    `\\x00\\x00\\x00\\x14ftypqt` 开头的 62KB **QuickTime 文件** —— 整段录像挂在
    CCTV-17 名下，又是假直播。用容器头分一下就能分开「裸 TS 流」和「一个视频文件」。

    传进来的正文是 `decode(errors="replace")` 之后的文本，二进制会被换成 U+FFFD，
    所以这里只看头部那几个仍在 ASCII 范围内的字节（`ftyp`、`G`、`FL`、`<`），够用。

    >>> raw_kind("\\x00\\x00\\x00\\x14ftypqt  \\x00more")
    'mp4'
    >>> raw_kind("G\\xff\\xff" + "\\x00" * 40)            # 0x47 = MPEG-TS 同步字节
    'ts'
    >>> raw_kind("FLV\\x00\\x01\\x05")
    'flv'
    >>> raw_kind("<!DOCTYPE html>\\n<html><body>502 Bad Gateway</body></html>")
    'html'
    >>> raw_kind('{"code":404,"msg":"not found"}')
    'bin'
    """
    head = body[:64]
    if "ftyp" in head[:16]:                   # MP4 / MOV / M4V：偏移 4 起是容器标识
        return "mp4"
    if head.lstrip().startswith(("<!DOC", "<html", "<HTML")):
        return "html"
    if body[:1] == "G":                       # 0x47 = MPEG-TS 同步字节
        return "ts"
    if body[:2] == "FL":
        return "flv"
    return "bin"


def _opener(direct: bool):
    """direct=True 时显式禁用代理，模拟 Apple TV 的直连环境。"""
    if direct:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _el(started: float) -> int:
    """自 started 起经过的毫秒数。"""
    return int((time.monotonic() - started) * 1000)


def _get(url: str, timeout: int, direct: bool) -> tuple[int, str]:
    """取回 (状态码, 正文)。异常交给调用方判。"""
    req = urllib.request.Request(quoted_url(url), headers={"User-Agent": UA})
    with _opener(direct).open(req, timeout=timeout) as resp:  # noqa: S310
        return getattr(resp, "status", 200), resp.read(65536).decode("utf-8", errors="replace")


def _first_variant(body: str) -> str:
    """多码率索引里的第一个变体地址（找不到返回空串）。"""
    return next((line.strip() for line in body.splitlines()
                 if line.strip() and not line.strip().startswith("#")), "")


def _media_body(url: str, timeout: int, direct: bool) -> str:
    """拿到真正的分片列表正文：master 跟一跳变体，其余原样返回。"""
    body = _get(url, timeout, direct)[1]
    if "#EXTM3U" in body and classify(body)[0] == "master":
        variant = _first_variant(body)
        if variant:
            return _get(urllib.parse.urljoin(url, variant), timeout, direct)[1]
    return body


def l3_roll(url: str, gap: int = 20, timeout: int = 12, direct: bool = True) -> dict:
    """L3：隔 gap 秒重取一次，比对分片窗口。返回 {verdict, segments, error}。

    verdict 为 rolling（真在推流）/ stuck（列表不动）/ vod（有 ENDLIST）/ dead（取不到）。

    这一步每次要付 gap 秒的等待，所以不进 build --verify 的主流程
    （330 条线路全做 L3 要多等十几分钟），只在验收和核对手工源时对少量线路做。
    """
    try:
        first = _media_body(url, timeout, direct)
    except Exception as e:
        return {"verdict": "dead", "segments": 0, "error": type(e).__name__}
    time.sleep(gap)
    try:
        second = _media_body(url, timeout, direct)
    except Exception as e:
        return {"verdict": "dead", "segments": len(segment_window(first)),
                "error": f"重取失败:{type(e).__name__}"}
    return {"verdict": roll_verdict(first, second),
            "segments": len(segment_window(second)), "error": ""}


def probe(url: str, timeout: int = 12, direct: bool = True) -> ProbeResult:
    """两级检测：L1 连通 + L2 结构（并分清真直播 / 多码率索引 / 录播）。

    L2 必须看到真实分片，因为实测中存在返回 200 但播放列表为空、
    或返回 HTML 错误页的假活源。master 会再跟一跳取变体，
    否则一条 张家界公共 那种多码率索引只会被数出「1 个分片」，看不出它是能播的。

    变体取不到就判整条失效，不留「按可用但标记」的余地：2026-09-21 对
    gctxyc.liveplay.myqcloud.com 做过对照 —— 同一个 UA 下 index.m3u8 返回 200，
    不存在的 /gc/xxx.m3u8 返回干净的 404，而它索引里的 zjjjjdl_1_md.m3u8 是
    连接被重置。也就是说这台 CDN 认得这个流名但后端没人推流，
    播放器同样出不来画，留着只会占掉频道第一位。
    """
    started = time.monotonic()
    try:
        http, body = _get(url, timeout, direct)
    except urllib.error.HTTPError as e:
        http, body = e.code, ""
    except Exception as e:  # 超时 / DNS / 连接重置，一律判失效
        return ProbeResult(False, 0, int((time.monotonic() - started) * 1000), 0,
                           type(e).__name__)

    ms = int((time.monotonic() - started) * 1000)

    if "#EXTM3U" not in body:
        # 不是播放列表：只有裸分片流（TS/FLV）才算可用，
        # MP4 是整段录像、HTML 是错误页，两者都不能当直播线路。
        rk = raw_kind(body)
        if http != 200 or len(body) <= 1024:
            return ProbeResult(False, http, ms, 0, "非播放列表且体量过小", "")
        if rk == "html":
            return ProbeResult(False, http, ms, 0, "返回的是网页，不是流", "")
        if rk == "bin":
            return ProbeResult(False, http, ms, 0, "认不出容器（不是 ts/flv/m3u8）", "")
        # ts / flv 是裸流；mp4 标成 vod，让它走「假直播降档 + 报告点名」那条路
        return ProbeResult(True, http, ms, 0, "", "vod" if rk == "mp4" else "raw")

    kind, segs = classify(body)

    if kind == "master":
        variant = _first_variant(body)
        if not variant:
            return ProbeResult(False, http, ms, 0, "索引里没有变体", "master")
        try:
            v_http, v_body = _get(urllib.parse.urljoin(url, variant), timeout, direct)
        except Exception as e:  # 拿到位就是没流，判失效见下方说明
            return ProbeResult(False, http, _el(started), segs,
                               f"变体不可达:{type(e).__name__}", "master")
        v_kind, v_segs = classify(v_body) if "#EXTM3U" in v_body else ("raw", 0)
        if v_http != 200 or v_segs == 0:
            return ProbeResult(False, v_http, _el(started), v_segs,
                               f"变体 HTTP {v_http}" if v_http != 200 else "变体为空",
                               f"master:{v_kind}")
        return ProbeResult(True, v_http, _el(started), v_segs, "", f"master:{v_kind}")

    ok = http == 200 and segs > 0
    return ProbeResult(ok, http, ms, segs,
                       "" if ok else ("空播放列表" if segs == 0 else f"HTTP {http}"), kind)


def probe_many(urls: list[str], timeout: int = 12, workers: int = 20,
               direct: bool = True) -> list[ProbeResult]:
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda u: probe(u, timeout, direct), urls))
