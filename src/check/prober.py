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


# 「连不上」底下那几种能确定说法的异常。只列确定得了的：认不出的一律退回类型名。
_DEAD_WHY = {
    "ConnectionRefusedError": "端口没人听",
    "ConnectionResetError": "连上就被对方断了",
    "BrokenPipeError": "连上就被对方断了",
    "gaierror": "域名解析不出来",
}


def why_dead(e: BaseException) -> str:
    """把「根本连不上」那一族异常翻成一句结论；翻不出就照旧报类型名。

    为什么补这一格：`probe()` 那个兜底 except 以前把**类型名**当结论写进了 `probe.json`。
    21:18 那轮 350 条判决里 116 条失效，其中 **99 条** 的全部信息就是 `URLError` 一个词
    （另两种常见的 `ConnectionResetError` 4 条、`TimeoutError` 2 条也一样），
    而「域名解析不出来」「那个端口没人听」「对方地址根本不是 http」是三件完全不同的事，
    在 `probe.json` 和 `verify_lines.py` 的输出里长得一模一样。
    2.41 那 54 条专网线当时就是这一族，**现在回头问不出它们是上面哪一种了** ——
    记下来的东西不够具体，等于没记。

    这一格和 2.36 在 `src/check/history.py` 里立的是同一条规矩：读不进来要说清是**哪一种**
    读不进来。宁缺毋滥：认不出的照旧报 `type(e).__name__`，
    不要编一句「大概是超时」—— 那是把没查到的东西写成查到的。

    >>> import socket, urllib.error as ue
    >>> why_dead(ue.URLError(ConnectionRefusedError(61, "Connection refused")))
    '端口没人听'
    >>> why_dead(ue.URLError(socket.gaierror(-2, "Name or service not known")))
    '域名解析不出来'
    >>> why_dead(ue.URLError(ConnectionResetError(54, "Connection reset by peer")))
    '连上就被对方断了'
    >>> why_dead(TimeoutError())
    '连上没响应（超时）'
    >>> why_dead(ue.URLError("unknown url type: rtmp"))     # reason 是个字符串，不是异常
    '这种地址本机测不了（不是 http）'
    >>> why_dead(ue.URLError("什么奇怪说法"))                # 字符串但认不出：留着原文，不换成中文
    'URLError:什么奇怪说法'
    >>> why_dead(ue.URLError(OSError(51, "Network is unreachable")))   # 认不出的退回类型名
    'URLError'
    >>> why_dead(ValueError("别的什么东西"))
    'ValueError'
    >>> why_dead(ue.HTTPError("http://x/y.m3u8", 404, "Not Found", None, None))
    'HTTP 404'

    最后那一条不是随手加的：`HTTPError` 是 `URLError` 的**子类**（`URLError` 又是 `OSError` 的），
    所以「服务器明确回了 404」这种最该留住状态码的情形，恰好是最容易被 `except URLError` 吃掉的
    —— `probe()` 里那两个 except 的先后不能反，`l3_roll()` 那一个则必须自己认得这件事。
    """
    if isinstance(e, urllib.error.HTTPError):     # 必须在 URLError 之前问：它是 URLError 的子类
        return f"HTTP {e.code}"
    node: BaseException = e
    if isinstance(e, urllib.error.URLError):
        if isinstance(e.reason, str):
            if "unknown url type" in e.reason:
                return "这种地址本机测不了（不是 http）"
            return f"URLError:{e.reason}"
        if isinstance(e.reason, BaseException):
            node = e.reason
    if isinstance(node, TimeoutError):        # socket.timeout 在 3.10 起就是这个的别名
        return "连上没响应（超时）"
    return _DEAD_WHY.get(type(node).__name__, type(e).__name__)



def l3_roll(url: str, gap: int = 20, timeout: int = 12, direct: bool = True) -> dict:
    """L3：隔 gap 秒重取一次，比对分片窗口。返回 {verdict, segments, error}。

    verdict 为 rolling（真在推流）/ stuck（列表不动）/ vod（有 ENDLIST）/ dead（取不到）。

    这一步每次要付 gap 秒的等待，所以不进 build --verify 的主流程
    （330 条线路全做 L3 要多等十几分钟），只在验收和核对手工源时对少量线路做。

    三种「取不到」分得开吗（2.43 起有用了，以前这一整层零用例）：

    >>> import contextlib, urllib.error as ue
    >>> import src.check.prober as P
    >>> @contextlib.contextmanager
    ... def answered(*answers):            # 同 probe 的用例：换一份按顺序作答的假答案
    ...     keep, left = P._get, list(answers)
    ...     def fake(url, timeout, direct):
    ...         a = left.pop(0) if len(left) > 1 else left[0]
    ...         if isinstance(a, BaseException): raise a
    ...         return a
    ...     P._get = fake
    ...     try:
    ...         yield
    ...     finally:
    ...         P._get = keep
    >>> L = "#EXTM3U\\n#EXTINF:10,\\n"
    >>> with answered((200, L + "a1.ts\\n"), (200, L + "a2.ts\\n")):
    ...     l3_roll("http://x/y.m3u8", gap=0)["verdict"]          # 窗口动了
    'rolling'
    >>> with answered((200, L + "a1.ts\\n")):
    ...     l3_roll("http://x/y.m3u8", gap=0)["verdict"]          # 两次一模一样
    'stuck'
    >>> M = "#EXTM3U\\n#EXT-X-STREAM-INF:BANDWIDTH=1\\nlo.m3u8\\n"
    >>> with answered((200, M), (200, L + "a1.ts\\n"), (200, M), (200, L + "a2.ts\\n")):
    ...     l3_roll("http://x/y.m3u8", gap=0)["verdict"]     # 索引要跟一跳，比的是变体的窗口
    'rolling'
    >>> with answered(ue.URLError(ConnectionRefusedError(61, "x"))):
    ...     l3_roll("http://x/y.m3u8", gap=0)                 # 第一次就取不到：没有 segments 可记
    {'verdict': 'dead', 'segments': 0, 'error': '端口没人听'}
    >>> with answered((200, L + "a1.ts\\n"), ue.URLError(ConnectionResetError(54, "x"))):
    ...     l3_roll("http://x/y.m3u8", gap=0)     # 第二次才断：第一次那份窗口仍然留着
    {'verdict': 'dead', 'segments': 1, 'error': '重取失败:连上就被对方断了'}
    """
    try:
        first = _media_body(url, timeout, direct)
    except Exception as e:
        return {"verdict": "dead", "segments": 0, "error": why_dead(e)}
    time.sleep(gap)
    try:
        second = _media_body(url, timeout, direct)
    except Exception as e:
        return {"verdict": "dead", "segments": len(segment_window(first)),
                "error": f"重取失败:{why_dead(e)}"}
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

    可是这一层在 2.43 之前**一条用例都没有**：`classify`／`raw_kind` 那些纯函数各有样例，
    把它们拼成一条判决的这里没有。`_get` 以下（socket、DNS、代理）不是本模块的逻辑，
    而且它的结果随出口变（2.41），所以这里把 `_get` 换成一份「按顺序作答」的假答案，
    逐支钉住 probe 自己的判断；末尾再用两个**真的本地套接字**对一遍
    「假答案和真世界里抛出来的是同一种东西」（127.0.0.1，与走不走代理无关）。

    >>> import contextlib, socket, urllib.error as ue
    >>> import src.check.prober as P
    >>> @contextlib.contextmanager
    ... def answered(*answers):        # 依次让 _get 给出这些答案：(状态, 正文) 或一个异常
    ...     keep, left = P._get, list(answers)
    ...     def fake(url, timeout, direct):
    ...         a = left.pop(0) if len(left) > 1 else left[0]     # 用尽后重复最后一个
    ...         if isinstance(a, BaseException): raise a
    ...         return a
    ...     P._get = fake
    ...     try:
    ...         yield
    ...     finally:
    ...         P._get = keep          # 必须还回去：全项目的用例是同一个进程按顺序跑的
    >>> def brief(r):                  # 判决里的 ms 是流逝时间，不进用例
    ...     return (r.ok, r.http, r.segments, r.kind, r.error)

    正常的一条直播线路，和一支明确回了 404 的（状态码必须留在判决里 —— 上面说的那个顺序）：

    >>> with answered((200, "#EXTM3U\\n#EXTINF:10,\\na.ts\\n")):
    ...     brief(probe("http://x/y.m3u8"))
    (True, 200, 1, 'live', '')
    >>> with answered(ue.HTTPError("http://x/y.m3u8", 404, "Not Found", None, None)):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 404, 0, '', 'HTTP 404，没给出播放列表')

    200 但正文不是播放列表的四种坏法（真数据里各有一批，见 2.43「量到的东西」）：

    >>> with answered((200, "<!DOCTYPE html>" + "<p>维护中</p>" * 200)):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 200, 0, '', '返回的是网页，不是流')
    >>> with answered((200, "x" * 500)):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 200, 0, '', '200 但正文太小，不像一条流')
    >>> with answered((200, "\\x00\\x00\\x00\\x14ftypqt" + "x" * 4000)):     # 整段录像
    ...     brief(probe("http://x/y.m3u8"))
    (True, 200, 0, 'vod', '')
    >>> with answered((200, "G" + "\\xff" * 4000)):                    # 裸 TS 分片流
    ...     brief(probe("http://x/y.m3u8"))
    (True, 200, 0, 'raw', '')

    多码率索引要跟一跳，那一跳的四种结果各判各的：

    >>> M = "#EXTM3U\\n#EXT-X-STREAM-INF:BANDWIDTH=500000\\nlo.m3u8\\n"
    >>> with answered((200, M), (200, "#EXTM3U\\n#EXTINF:10,\\na.ts\\nb.ts\\n")):
    ...     brief(probe("http://x/y.m3u8"))
    (True, 200, 2, 'master:live', '')
    >>> with answered((200, M), (200, "#EXTM3U\\n#EXTINF:10,\\na.ts\\n#EXT-X-ENDLIST\\n")):
    ...     brief(probe("http://x/y.m3u8"))          # 索引 → 变体是录像：`master:vod` 也在 FAKE_KINDS 里
    (True, 200, 1, 'master:vod', '')
    >>> with answered((200, M), (200, "#EXTM3U\\n")):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 200, 0, 'master:live', '变体为空')
    >>> with answered((200, M), (404, "")):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 404, 0, 'master:raw', '变体 HTTP 404')
    >>> with answered((200, M), ue.URLError(ConnectionRefusedError(61, "x"))):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 200, 1, 'master', '变体不可达:端口没人听')
    >>> with answered((200, "#EXTM3U\\n#EXT-X-STREAM-INF:BANDWIDTH=1\\n")):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 200, 0, 'master', '索引里没有变体')

    列表在、但要么空要么不是 200：

    >>> with answered((200, "#EXTM3U\\n")):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 200, 0, 'live', '空播放列表')
    >>> with answered((503, "#EXTM3U\\n#EXTINF:10,\\na.ts\\n")):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 503, 1, 'live', 'HTTP 503')

    兜底那一支是整个产品里出现次数最多的一句话（21:18 那轮 116 条失效里 99 条只写了
    `URLError`），现在它说得出是哪一种：

    >>> with answered(ue.URLError(socket.gaierror(-2, "Name or service not known"))):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 0, 0, '', '域名解析不出来')
    >>> with answered(ue.URLError(ConnectionResetError(54, "x"))):
    ...     brief(probe("http://x/y.m3u8"))
    (False, 0, 0, '', '连上就被对方断了')
    >>> with answered(ue.URLError("unknown url type: rtmp")):   # 上游 1868 条里有 3 条 rtmp
    ...     brief(probe("http://x/y.m3u8"))
    (False, 0, 0, '', '这种地址本机测不了（不是 http）')

    但「一律判失效」不能宽到把按 Ctrl-C 也当成一条线路坏了：

    >>> with answered(KeyboardInterrupt()):
    ...     try:
    ...         probe("http://x/y.m3u8")
    ...     except KeyboardInterrupt:
    ...         print("照原样往上抛，不吞成判决")
    照原样往上抛，不吞成判决

    真套接字这两支核对上面那些异常形状（第二支要等满 1 秒，它就是在量「超时」）：

    >>> srv = socket.socket()
    >>> _ = srv.bind(("127.0.0.1", 0))
    >>> port = srv.getsockname()[1]
    >>> srv.close()
    >>> brief(probe(f"http://127.0.0.1:{port}/x.m3u8", 2))
    (False, 0, 0, '', '端口没人听')
    >>> hole = socket.socket()
    >>> _ = hole.bind(("127.0.0.1", 0))
    >>> _ = hole.listen(1)                      # 握手给，但从不 accept：对方永远不回
    >>> hport = hole.getsockname()[1]
    >>> brief(probe(f"http://127.0.0.1:{hport}/x.m3u8", 1))
    (False, 0, 0, '', '连上没响应（超时）')
    >>> hole.close()
    """
    started = time.monotonic()
    try:
        http, body = _get(url, timeout, direct)
    except urllib.error.HTTPError as e:
        http, body = e.code, ""
    except Exception as e:  # 超时 / DNS / 连接重置，一律判失效
        return ProbeResult(False, 0, _el(started), 0, why_dead(e), "")

    ms = _el(started)

    if "#EXTM3U" not in body:
        # 不是播放列表：只有裸分片流（TS/FLV）才算可用，
        # MP4 是整段录像、HTML 是错误页，两者都不能当直播线路。
        rk = raw_kind(body)
        if http != 200:
            # 这一支以前和下面那格挤成同一句「非播放列表且体量过小」，于是 403/404
            # 在 probe.json 里读起来像「内容有问题」，而真正的事是服务器拒了这个请求。
            return ProbeResult(False, http, ms, 0, f"HTTP {http}，没给出播放列表", "")
        if len(body) <= 1024:
            return ProbeResult(False, http, ms, 0, "200 但正文太小，不像一条流", "")
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
                               f"变体不可达:{why_dead(e)}", "master")
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
    """并发探测一批地址，返回**与入参同序**的一批判决。

    同序这件事有人靠：`cmd_build` 实测那一支是 `dict(zip(urls, probe_many(urls, …)))`，
    顺序错了就是把 A 地址的判决记到 B 地址头上，而**两边的地址都还在**，事后看不出来。
    空表单独一条：那是「这一轮没有要测的」，不能和「全测了、全连不上」混成同一个结果。

    >>> probe_many([])
    []

    下面这条用「正文里有几个分片」把地址编号带出来，所以它真能认出被打乱（三条一模一样的
    结果排在什么顺序都看不出问题 —— 那种用例是假绿）：

    >>> import src.check.prober as P
    >>> keep = P._get
    >>> P._get = lambda url, timeout, direct: (200, "#EXTM3U\\n" + "#EXTINF:10,\\nx.ts\\n" * int(url[-1]))
    >>> [r.segments for r in probe_many([f"http://x/{i}" for i in (3, 1, 2, 1)], timeout=2)]
    [3, 1, 2, 1]
    >>> P._get = keep

    真套接字那一条：一个关掉的端口，三条地址并发跑完，各自都认得出是同一种连不上。

    >>> import socket
    >>> srv = socket.socket()
    >>> _ = srv.bind(("127.0.0.1", 0))
    >>> port = srv.getsockname()[1]
    >>> srv.close()
    >>> [(r.ok, r.error) for r in probe_many([f"http://127.0.0.1:{port}/x.m3u8"] * 3, timeout=2)]
    [(False, '端口没人听'), (False, '端口没人听'), (False, '端口没人听')]
    """
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda u: probe(u, timeout, direct), urls))
