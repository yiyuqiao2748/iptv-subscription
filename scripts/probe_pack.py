"""生成「试播包」：每个流主机族挑一条代表线路，编号 ①②③…

这张表回答的是「电脑测出来的通，电视上真出画吗」。

前提变了要说明一下：早先两台开发机都挂着代理客户端，TUN 抢走 DNS 和路由，
本机实测全是假数字，唯一可信的测量设备是电视。2026-09-21 把 TUN 关掉后
出口变成家里联通骨干，和 Apple TV 同一张网，电脑实测已经能当判据了。
所以试播包不再负责「哪些主机族连得上」—— 那个问题 probe.json 已经答完，
这里只挑**实测通过**的主机族，让电视确认剩下的那一层：
L1/L2 通了但码率、延迟、缓冲够不够，跨洋中转能不能撑住直播。
整族失效的主机（比如 stream1.freetv.fun 0/17）直接不放进表里，不浪费遥控器的点击。

2.24 换了挑法：以前按**线路数**排（一个主机在上游列表里出现几次），
现在按**它挂着几个台的第一线**排。理由是 APTV 只播每个台的第一条线路，
所以「这 16 次点击覆盖多少个台」才是这张表该优化的东西 ——
一个族哪怕塞了 40 条线路，只要没一个台把它排第一，点它就不替任何台判分。
线路多但只当备选的族会往后掉、掉出 `--top` 的在终端点名说，不静默消失。

2.25 补上掉出去那一堆的去向：单独列一份**备选池**（在表里只当第二三条线路、一个台的第一线都没挂的族），
并且顺手量清「在电视上点第 2 条线路」这条退路对多少个台真的成立。第一轮的答复是否定的
（计划书 2.25）：第一线可疑的 39 个台里 24 个没有备选、1 个的备选还在同一家机房、
14 个从湖南联通专网出口换到湖南移动专网门户，**能换到公网线路的 0 个** ——
所以别在电视上靠换线路救湖南那批台，那 28 条备选线路备的全是第一线本来就通的台。

    python scripts/probe_pack.py                   # 从 aptv.m3u 生成 probe-pack.m3u
    python scripts/probe_pack.py --top 12          # 只挑第一线台数最多的 12 个主机族
    python scripts/probe_pack.py --keep-dead       # 连实测全灭的族也放进来
    python scripts/probe_pack.py --out /tmp/new.m3u  # 出到别处，先跟 data/output 那份比一比
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"
sys.path.insert(0, str(ROOT))

from src.check.scope import load_reachability                # noqa: E402
# weak_first_line / second_line_options 的算法本体在 src/cli.py（计划书 2.26）：
# 那两处现在 report.md 也要用，留一份实现就不止是一处口径。
# 这里只留一个把 (name, urls) 元组喂进去的薄壳，见 suspect_first_lines。
from src.cli import (REACH_FILE, first_line_focus, load_probe, second_line_options,  # noqa: E402
                     weak_first_line)
# _SCOPE_LABEL 是报告里那张「范围 → 人话」的表；这里直接用它，
# 免得试播包和 report.md 对同一个主机族说出两种口径。
from src.output.writer import _SCOPE_LABEL, OutputChannel, one_line     # noqa: E402

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

# 主机 → 人话名字。判读时只看这个标签就够，不用认 IP。
FAMILY = {
    "tvgslb.hn.chinamobile.com": "湖南移动IPTV门户",
    "58.20.64.92": "湖南联通IPTV出口",
    "stream1.freetv.fun": "freetv公网CDN·实测整族失效",
    "php.jdshipin.com": "京东云公网中转",
    "live.264788.xyz": "264788中转·实测是整段MP4录像",
    "gslbmgsplive.miguvideo.com": "咪咕公网",
    "ottrrs.hl.chinamobile.com": "黑龙江移动",
    "rrs01.hw.gmcc.net": "移动全球 multicast 网关",
    "cctvtxyh5c.liveplay.myqcloud.com": "★腾讯云CDN·公网基准",
    "hls-qhmh.lanzhousobey.cn": "兰州公网",
    "iptv.huuc.edu.cn": "高校网源·教育网限定",
    "iptv.666230.xyz": "666230中转",
    "zby.130519.xyz": "130519中转·实测整族失效",
    # ↓ 2026-09-20 查过归属：按可达范围排序后顶上第一线的湖南/央视线路，
    #   主机大多落在美国机房的转发包月里。它们算「公网」不等于「国内宽带连得上」，
    #   所以试播包必须把国籍显示出来。
    #   2026-09-21 家里联通实测补一句：这批并没有全灭（41/42、38/38 全通），
    #   但最快也要 845ms 以上，国内官方流是 47~210ms。所以国籍的作用从
    #   「能不能连上」变成了「值不值得当第一线」，排序上按延迟分了档。
    "63.141.230.178": "美国Nocix中转",
    "107.150.60.122": "美国Nocix中转",
    "74.91.26.218": "美国Nocix中转",
    "204.12.221.218": "美国WholeSale中转",
    "38.75.136.137": "美国GTHost中转",
    "198.204.228.26": "美国中转",
    "173.208.212.130": "美国中转",
    "192.151.150.154": "美国中转",
    # ↓ 2026-09-21 实测里跑得快的一批：都是电视台自己的公网分发，
    #   延迟 47~210ms，比美国中转（845~1271ms）快一个数量级。
    #   湖南卫视那条就是湖南广电官方流 —— P5 要找的就是这类地址。
    "hlsal-ldvt.qing.mgtv.com": "★湖南广电官方公网",
    "live.hnxttv.com": "★湘潭广电官方公网",
    "120.76.248.139": "阿里云公网(国内)",
    "ali-m-l.cztv.com": "浙江广电官方公网",
    "play1-qk.nmtv.cn": "内蒙古广电公网",
    "txmov2.a.kwimgs.com": "快手CDN·疑似循环录像",
}

# 优先挑这些台做代表：认得出来、也确实是用户想看的
PREFERRED = ("湖南卫视", "湖南经视", "长沙新闻综合", "CCTV-1", "CCTV1",
             "中央电视", "湖南卫视-高清", "CCTV-4", "北京卫视")


# 基准族：价值不在「一次替几个台判分」，在「这一档到底行不行」，所以不管排到第几名都要在表里。
#   myqcloud：央视内容的腾讯云分发、URL 不带鉴权参数，能动就说明电视出公网没问题
#             （2026-09-21 它自己实测失效了，已不进订阅表，这里就自然留不下）
#   mgtv：湖南广电官方公网流，190ms。这台要是电视上能稳播，
#         P5 的方向就定了 —— 去把湖南各台的官方公网分发一个个挖出来，而不是找中转。
#   hnxttv：湘潭广电官方公网流，47ms，而且是这轮第一个靠手工源补进来的台。
#           它和 mgtv 一起构成「官方分发」这一档的对照组：国内、快、真直播。
# 2.24 换成按集中度排序之后，这两个官方流各只有 1 个台、必然掉出前 14 名，
# 所以「补回来」这件事比从前更必要 —— 不然表里就只剩中转了。
FORCE = ("cctvtxyh5c.liveplay.myqcloud.com", "hlsal-ldvt.qing.mgtv.com",
         "live.hnxttv.com")

# 对照组：不测供给，测**我的判据**。264788 那条电脑侧 L3 判成「整段 MP4 录像」，
# 它在订阅表里一条第一线都没挂上（按新排序会被切掉），但它正好是
# 「电视上看着像不像直播」这个问题的唯一样本，所以留着。
CONTROL = ("live.264788.xyz",)

# 排序之后再补进来，编号才不会随上游文件顺序抖
ALWAYS = FORCE + CONTROL


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else url


def base_of(host: str) -> str:
    """去掉端口和中括号，让 `58.20.64.92:9999` 和 probe.json 里的 `58.20.64.92` 对得上。

    带中括号的 IPv6 先整段摘出来再剥端口：直接 `split(":")` 会把
    `[2409:8087:100:2::1]:8080` 切成 `2409` —— 那是把两家机房当成一家，
    而且 `first_line_focus` 用 `urlsplit().hostname`  keyed，两边对不上就成了「一个台都没挂」。
    （2026-09-22 这张表里还没有 IPv6 主机，但上游随时可能塞进来。）

    >>> base_of("58.20.64.92:9999"), base_of("live.hnxttv.com")
    ('58.20.64.92', 'live.hnxttv.com')
    >>> base_of("[2409:8087:100:2::1]:8080")
    '2409:8087:100:2::1'
    """
    if host.startswith("["):
        head, _, _ = host.partition("]")
        return head[1:].lower()
    return host.split(":")[0].strip("[]").lower()


def port_of(host: str) -> str:
    """`112.30.73.119:229` → `"229"`；没端口 → 空串（IPv6 只认 `]` 后面那截）。

    >>> port_of("112.30.73.119:229"), port_of("live.hnxttv.com"), port_of("[2409:1::2]:8080")
    ('229', '', '8080')
    >>> port_of("[2409:1::2]")
    ''
    """
    if host.startswith("["):
        _, sep, rest = host.partition("]")
        return rest[1:] if sep and rest.startswith(":") else ""
    _, sep, port = host.partition(":")
    return port if sep else ""


def where(base: str, items: list[tuple[str, str]]) -> str:
    """把这一族用到的端口写进括号里：合并成一行之后，端口不能再靠编号区分。

    >>> where("112.30.73.119", [("CCTV-3", "http://112.30.73.119:229/a"),
    ...                         ("CCTV-5", "http://112.30.73.119:9901/b")])
    '112.30.73.119:229/9901'
    >>> where("120.76.248.139", [("CCTV-13", "http://120.76.248.139/a")])   # 没端口就不加戏
    '120.76.248.139'
    """
    ports = {p for p in (port_of(host_of(u)) for _, u in items) if p}
    return f"{base}:{'/'.join(sorted(ports))}" if ports else base


def family_label(host: str) -> str:
    return FAMILY.get(base_of(host), host)


def load_stats(path: Path = OUT_DIR / "probe.json") -> dict[str, dict]:
    """读 build --verify 落盘的实测结果，键是去端口的主机名。

    >>> load_stats(Path("/does/not/exist.json"))     # 没实测过就返回空，主流程照常出表
    {}
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for h in data.get("hosts") or []:
        base = base_of(str(h.get("host", "")))
        c = out.setdefault(base, {"total": 0, "ok": 0, "ms": 0})
        c["total"] += int(h.get("total") or 0)
        c["ok"] += int(h.get("ok") or 0)
        if h.get("best_ms"):
            c["ms"] = h["best_ms"] if not c["ms"] else min(c["ms"], h["best_ms"])
    return out


def load_results(path: Path = OUT_DIR / "probe.json") -> dict[str, object]:
    """probe.json 里那一份**逐条线路**的判决（`build --verify` 那一轮写的）。

    `load_stats` 拿的是逐主机汇总（够说「这个族通不通」），但要说
    「这个台的第一线电脑测过没有」得落到 URL 那一层 —— 2.23 的
    `first_line_focus` 要的就是这个形状，而 `src.cli.load_probe` 已经会读它，
    所以这里不重写一遍 JSON 解析。

    >>> load_results(Path("/does/not/exist.json"))     # 没实测过就返回空，主流程照常出表
    {}
    """
    try:
        return load_probe(path)[0]
    except Exception:
        return {}


def channel_groups(text: str) -> list[tuple[str, list[str]]]:
    """把 m3u 读回成 (频道名, [线路…])，分组口径和 APTV 一致：连续两条一模一样的 `#EXTINF` 是同一个台。

    为什么不能像旧的 `read_pairs` 那样一行一对读完就算：APTV 只播每个台的**第一条**线路，
    「一个主机挂着几个台的第一线」这件事只有先分组才算得出来。
    分组必须看整行属性而不是只看台名 —— 同名不同 id 的两个桶在电视上是两个台。

    >>> text = ('#EXTM3U\\n'
    ...         '#EXTINF:-1 tvg-id="81",湖南卫视\\nhttp://a/1.m3u8\\n'
    ...         '#EXTINF:-1 tvg-id="81",湖南卫视\\nhttp://b/2.m3u8\\n'
    ...         '#EXTINF:-1 tvg-id="1",CCTV-1综合\\nhttp://a/3.m3u8\\n')
    >>> channel_groups(text)
    [('湖南卫视', ['http://a/1.m3u8', 'http://b/2.m3u8']), ('CCTV-1综合', ['http://a/3.m3u8'])]
    >>> # 台名相同、属性不同：电视上就是两个台，这里也不合并
    >>> channel_groups('#EXTINF:-1 tvg-id="1",湖南经视\\nhttp://a/1\\n'
    ...                '#EXTINF:-1 tvg-id="2",湖南经视\\nhttp://b/1')
    [('湖南经视', ['http://a/1']), ('湖南经视', ['http://b/1'])]
    >>> # 台名取逗号后面那段（APTV 界面上看到的就是它）
    >>> channel_groups('#EXTINF:-1 tvg-id="9" tvg-name="湘潭新闻综合",湘潭新闻综合\\nhttp://c/1')[0][0]
    '湘潭新闻综合'
    """
    out: list[tuple[str, list[str]]] = []
    tag: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            name = line.split(",", 1)[1] if "," in line else ""
            if tag != line:                      # 属性变了 = 换台了，开一个新桶
                out.append((name, []))
            tag = line
        elif tag is not None and line.startswith("http"):
            out[-1][1].append(line)              # 每条 #EXTINF 后面恰好跟一条地址
    return [(n, urls) for n, urls in out if urls]


def focus_by_host(channels: list[tuple[str, list[str]]], results: dict,
                  reach) -> dict[str, dict]:
    """集中度按**去端口**的主机名索引，好跟 `base_of` / probe.json 对上。

    >>> g = [("湘潭新闻综合", ["http://live.hnxttv.com:9601/live/x.m3u8",
    ...                        "http://58.20.64.92:9999/bak.ts"]),
    ...      ("湖南经视", ["http://tvgslb.hn.chinamobile.com:8089/a.ts"])]
    >>> [(r["host"], r["channels"], r["alone"]) for r in focus_by_host(g, {}, None).values()]
    [('live.hnxttv.com', 1, 0), ('tvgslb.hn.chinamobile.com', 1, 1)]
    >>> # 带端口的主机名查得到同一个族：湘潭那条在表里叫 `live.hnxttv.com:9601`
    >>> sorted(focus_by_host(g, {}, None)) == sorted("live.hnxttv.com tvgslb.hn.chinamobile.com".split())
    True
    >>> # 只当备选的主机不会出现在这里 —— 它一个台的第一线都不挂
    >>> "58.20.64.92" in focus_by_host(g, {}, None)
    False
    """
    chans = [OutputChannel(name=n, group_title="", tvg_id="", urls=list(urls))
             for n, urls in channels]
    return {r["host"]: r for r in first_line_focus(chans, results, None, reach)}


_NO_FOCUS = {"channels": 0, "alone": 0, "alt_lines": 0, "unmeasured": 0, "scope": ""}


def build(channels: list[tuple[str, list[str]]], top: int,
          stats: dict[str, dict] | None = None, keep_dead: bool = False,
          results: dict | None = None, reach=None,
          ) -> tuple[str, list[dict], list[str], list[str]]:
    """按「挂着几个台的第一线」挑代表线路，同分再按线路数、族名。

    ALWAYS（基准 + 对照组）里的族只有一两条线路、往往一条第一线都不挂，取 top 会被切掉，
    所以取完按族名排序补一次 —— 不排的话补进来的先后跟上游文件顺序走，编号会莫名抖动。
    比对要用去端口的主机名 —— 湘潭那条是 `live.hnxttv.com:9601`，
    拿 `host in FORCE` 直接比会漏，试播包就少了一个对照组。
    2.24 起「一族」在整张表里统一成**去端口**的主机名（`base_of`）：以前 `:229` 和 `:9901`
    在包里是两行两个编号，而 `probe.json`、`report.md`、集中度全都把它们当一族。

    >>> g = ([("湘潭新闻综合", ["http://live.hnxttv.com:9601/live/x.m3u8"]),
    ...       ("湖南卫视", ["http://hlsal-ldvt.qing.mgtv.com/a.m3u8"])]
    ...      + [(f"CCTV-{i}综合", [f"http://1.1.1.1:80/{i}.m3u8", "http://2.2.2.2/x.ts"])
    ...         for i in range(4)])
    >>> legend = build(g, top=1)[1]
    >>> # ① 是 4 个台共用的第一线；mgtv / hnxttv 各只有 1 个台，但它们是基准（★），补回来了
    >>> [l["mark"] + l["family"][:1] for l in legend]
    ['①1', '②★', '③★']
    >>> [l["first"] for l in legend]
    [4, 1, 1]
    >>> # 代表频道得是「第一线就在这台主机上」的那个台：2.2.2.2 全是备选线路，只能退回那批 CCTV 里
    >>> # 认得出的一个（`PREFERRED` 里的 CCTV-1 赢，不是按出现顺序的 CCTV-0）
    >>> [l["channel"] for l in build(g, top=0)[1] if l["host"] == "2.2.2.2"]
    ['CCTV-1综合']
    >>> # 线路数不再决定名次：b 族 4 条线路挂 2 个台的第一线，a 族 1 条线路挂 1 个台 —— b 在前
    >>> g2 = [("台一", ["http://a/1", "http://b/1", "http://b/2"]),
    ...       ("台二", ["http://b/3"]), ("台三", ["http://b/4"])]
    >>> [l["host"] for l in build(g2, top=0)[1]]
    ['b', 'a']
    >>> # 同一台机房两个端口 = 一行一个编号，端口列在括号里
    >>> g3 = [("台一", ["http://a:229/1"]), ("台二", ["http://a:9901/2"]), ("台三", ["http://b/3"])]
    >>> [(l["host"], l["first"], l["family"]) for l in build(g3, top=0)[1] if l["host"] == "a"]
    [('a', 2, 'a（a:229/9901，2 条）')]
    >>> # 对照组（`CONTROL`）一个第一线台数都不挂也留在表里：它验的是「我判成录像的那条像不像直播」
    >>> g4 = [("台一", ["http://a/1"]), ("台二", ["http://b/1", "https://live.264788.xyz/rec"])]
    >>> [(l["host"], l["first"]) for l in build(g4, top=1)[1]]
    [('a', 1), ('live.264788.xyz', 0)]
    >>> build(g4, top=1)[3]                    # 「被切掉」那份名单里不会把对照组也算进去
    ['b（b，1 条线路｜第一线 1 个台）']
    >>> # 对照组没进集中度表（0 个台），但「它是公网还是内网」照样要说清楚 —— 去问代表地址本人
    >>> from src.check.scope import Reachability
    >>> [(l["host"], l["first"], l["scope"]) for l in build(g4, top=1, reach=Reachability())[1]]
    [('a', 1, '公网'), ('live.264788.xyz', 0, '公网')]
    >>> [l["scope"] for l in build(g4, top=1)[1]]      # 不给 reach 配置就留空，不糊一个「公网」
    ['', '']
    >>> # 「没实测过」只有给了逐条判决时才说：b 族 2 个台里 b/4 不在判决里，a 族那一条也不在
    >>> [l["unmeasured"] for l in build(g2, top=0, results={"http://b/3": None})[1]]
    [1, 1]
    >>> [l["unmeasured"] for l in build(g2, top=0)[1]]      # 没有逐条记录 → 不给这列下结论
    [None, None]
    >>> # 切掉的族会点名，不静默消失（基准族不算被切：它们一定会补回来）
    >>> build(g2, top=1)[3]
    ['a（a，1 条线路｜第一线 1 个台）']
    """
    by_host: dict[str, list[tuple[str, str]]] = {}
    for name, urls in channels:
        for url in urls:
            by_host.setdefault(base_of(host_of(url)), []).append((name, url))

    focus = focus_by_host(channels, results or {}, reach)
    first_urls = {urls[0] for _, urls in channels if urls}

    ordered = sorted(by_host.items(),
                     key=lambda kv: (-focus.get(kv[0], _NO_FOCUS)["channels"],
                                     -len(kv[1]), family_label(kv[0])))
    cut: list[str] = []
    if top:
        # 基准与对照组不算「被切」—— 它们一定会补回来，写在这里只会让人以为表里没有
        cut = [_family_line(b, items, focus) for b, items in ordered[top:] if b not in ALWAYS]
        ordered = ordered[:top]
    # 基准族与对照组哪怕只有 1 条线路、一个第一线台数都不挂，也要在表里；
    # 补进来时按主机名排序，免得编号跟着上游文件的行序抖
    picked = {b for b, _ in ordered}
    ordered += sorted(((b, items) for b, items in by_host.items()
                       if b in ALWAYS and b not in picked), key=lambda kv: kv[0])

    # 电脑已经实测过的主机族：整族连不上的不必再让电视点一次
    stats = stats or {}
    skipped: list[str] = []
    if stats and not keep_dead:
        kept = []
        for base, items in ordered:
            st = stats.get(base)
            if st and st["total"] and not st["ok"] and base not in FORCE:
                skipped.append(f"{family_label(base)}（{base} 实测 0/{st['total']}）")
                continue
            kept.append((base, items))
        ordered = kept

    lines = ["#EXTM3U"]
    legend: list[dict] = []
    for i, (base, items) in enumerate(ordered):
        mark = CIRCLED[i] if i < len(CIRCLED) else f"#{i + 1}"
        # 代表频道从这个族**真的挂了第一线**的那些台里挑，优先挑认得出来的：
        # 点这一条就是在点第一线，不会挑中一条只在备选位上躺着的线路。
        cands = [(n, u) for n, u in items if u in first_urls] or items
        pref, url = next(((n, u) for n, u in cands
                          if any(p in n for p in PREFERRED)), cands[0])
        row = focus.get(base, _NO_FOCUS)
        n_first, n_unmeasured = row["channels"], row["unmeasured"]
        # 集中度表里没有这个族 = 它一条第一线都没挂（对照组就是这种），
        # 但「它是公网还是内网」跟台数无关，直接问代表地址本人。
        scope = row["scope"] or (reach.scope(url) if reach else "")
        st = stats.get(base)
        note = f"{st['ok']}/{st['total']} 通" if st else "未实测"
        if st and st.get("ms"):
            note += f"·{st['ms']}ms"
        # 电视上看到的那一行：台数写进名字里，用户口述「第二个能动」时不用翻终端
        short = f"·{n_first}台" if n_first >= 2 else ""
        # 这里是第二处自己拼 `#EXTINF` 的地方（第一处在 src/output/writer.py），
        # 所以过同一个 one_line()：`pref` 是从真表里抄来的台名，它带引号或换行时
        # 这行一样会破结构 —— 规则只有一份，不然两处会各自烂。
        disp = one_line(f"{mark} {family_label(base)}{short}｜{pref}")
        lines.append(f'#EXTINF:-1 tvg-name="{one_line(pref)}" '
                     f'group-title="🔍 试播包",{disp}')
        lines.append(url)
        legend.append({"mark": mark, "host": base, "url": url,
                       "family": f"{family_label(base)}（{where(base, items)}，{len(items)} 条）",
                       "label": family_label(base), "channel": pref, "note": note,
                       "first": n_first, "alone": row["alone"], "alt_lines": row["alt_lines"],
                       "unmeasured": n_unmeasured if results else None,
                       "scope": _SCOPE_LABEL.get(scope, (scope, ""))[0] if scope else ""})

    return "\n".join(lines) + "\n", legend, skipped, cut


def backup_pool(channels: list[tuple[str, list[str]]], results: dict | None = None,
                stats: dict[str, dict] | None = None, reach=None) -> list[dict]:
    """表里**只当备选**的主机族（一个台的第一线都没挂），按「能救几个可疑的第一线」排。

    2.24 把选条逻辑换成第一线集中度之后，这些族全部掉出了试播包 —— 这是对的（点它们不替任何台
    判分），但顺手把另一件事的信息也扔了：真机验收里如果说「湖南卫视能动、湖南经视不动」，
    下一步要回答的是**经视能不能换到第 2 条线、换过去落在谁家**，候选池就是这里这几族。
    所以单独列一份，不动表本身。挂过任何一个台的第一线的族不在这里 —— 它已经在集中度那一列里了。

    `served` 是这个族给几个台当了备选；`weak` 是其中第一线值得担心的有几个（`src/cli.py::weak_first_line`）——
    weak 高才值得讨论换线，weak 0 说明它备的那些台第一线本来就挺好，这条线路留着只是占位。
    `note` 里的实测分数只数**这张表里**这个族的线路：`probe.json` 记的是上游抓来时的条数
    （美国 GTHost 上游 40 条、进表 21 条），照抄会说出「21 条线路的族实测 40/40」这种话。

    >>> from src.check.prober import ProbeResult
    >>> from src.check.scope import Reachability
    >>> g = ([("台一", ["http://i.example/1", "http://b/1", "http://b/2", "http://m/9"]),
    ...       ("台二", ["http://j/1", "http://b/3"]), ("台三", ["http://k/1"])])
    >>> # 只列出 b（3 条线路给 2 个台当备选）和 m（1 条给台一）；j/k 挂了第一线，不是备选池
    >>> [(r["host"], r["lines"], r["served"], r["weak"]) for r in backup_pool(g)]
    [('b', 3, 2, 0), ('m', 1, 1, 0)]
    >>> # 台一的第一线是专网，所以它那两个备选族都 weak=1；台二的第一线测过且是公网 → 0
    >>> [(r["host"], r["weak"]) for r in backup_pool(g, reach=Reachability([".example"]))]
    [('b', 1), ('m', 1)]
    >>> # weak 排在线路数前面：few 只有 1 条，但它备的那个台第一线是专网
    >>> res = {"http://pub/1": ProbeResult(True, 200, 80, 3, "", "live")}
    >>> g3 = ([("台一", ["http://i.example/1", "http://few/9"])]
    ...       + [(f"台{i}", ["http://pub/1", "http://many/8"]) for i in range(2, 6)])
    >>> [(r["host"], r["lines"], r["weak"]) for r in backup_pool(g3, res, None, Reachability([".example"]))]
    [('few', 1, 1), ('many', 4, 0)]
    >>> # 「可疑」还分得清是哪种：b 备的两个台里，台一是专网、台二没进这一轮判决
    >>> [(r["host"], r["intranet"], r["unmeasured"])
    ...  for r in backup_pool(g, {"http://nope/1": None}, None, Reachability([".example"]))]
    [('b', 1, 1), ('m', 1, 0)]
    >>> # 实测按表里的线路数，不按上游条数；没测到的那些条要说明，全灭就当场说「换过去也没用」
    >>> all_dead = {f"http://b/{i}": ProbeResult(False, 0, 0, 0, "timeout") for i in (1, 2, 3)}
    >>> [(r["host"], r["note"], r["dead"]) for r in backup_pool(g, results=all_dead)]
    [('b', '0/3 通·整族失效，换过去也没用', True), ('m', '表里 1 条都没测过', False)]
    >>> [(r["host"], r["note"])
    ...  for r in backup_pool(g, results={"http://b/1": ProbeResult(True, 200, 80, 3, "", "live")})]
    [('b', '1/1 通·另 2 条没测过'), ('m', '表里 1 条都没测过')]
    >>> # 离线生成没有逐条判决，只能退回上游整族的汇总 —— 带个 † 说明它对不上表里的条数
    >>> [r["note"] for r in backup_pool(g, stats={"b": {"total": 40, "ok": 40, "ms": 900}})]
    ['40/40 通†·900ms', '未实测']
    """
    results = results or {}
    stats = stats or {}
    first_bases = {base_of(host_of(urls[0])) for _, urls in channels if urls}

    agg: dict[str, dict] = {}
    for idx, (name, urls) in enumerate(channels):
        first = urls[0] if urls else ""
        for url in urls[1:]:
            base = base_of(host_of(url))
            if base in first_bases:
                continue          # 它给别的台挂过第一线 —— 那是集中度那一列的话，不在这里说
            a = agg.get(base)
            if a is None:
                a = agg[base] = {"host": base, "label": family_label(base), "lines": 0,
                                 "served": 0, "weak": 0, "intranet": 0, "unmeasured": 0,
                                 "seen": set(), "urls": [], "examples": []}
            a["lines"] += 1
            a["urls"].append(url)
            if idx not in a["seen"]:
                a["seen"].add(idx)
                a["served"] += 1
                if name not in a["examples"]:
                    a["examples"].append(name)
                why = weak_first_line(first, results, reach)
                if why:
                    a["weak"] += 1
                    a["intranet" if why == "专网" else "unmeasured"] += 1

    for a in agg.values():
        a["measured"] = sum(1 for u in a["urls"] if u in results)
        ok = sum(1 for u in a["urls"] if getattr(results.get(u), "ok", False))
        a["dead"] = bool(a["measured"]) and ok == 0
        if results:
            rest = (f"·另 {a['lines'] - a['measured']} 条没测过"
                    if a["measured"] < a["lines"] else "")
            a["note"] = (f"表里 {a['lines']} 条都没测过" if not a["measured"]
                         else f"{ok}/{a['measured']} 通" + rest
                         + ("·整族失效，换过去也没用" if a["dead"] else ""))
        else:                       # 离线：没有逐条判决，只能引用上游整族的汇总，如实标 †
            st = stats.get(a["host"])
            a["note"] = (f"{st['ok']}/{st['total']} 通†"
                         + (f"·{st['ms']}ms" if st.get("ms") else "")) if st else "未实测"
        a.pop("seen")
    return sorted(agg.values(), key=lambda a: (-a["weak"], -a["lines"], a["host"]))


def _family_line(base: str, items: list[tuple[str, str]], focus: dict[str, dict]) -> str:
    """描述一个被 `--top` 切掉的主机族：线路数 + 第一线台数，让人看得出切掉的是哪种。"""
    n = focus.get(base, _NO_FOCUS)["channels"]
    return (f"{family_label(base)}（{where(base, items)}，{len(items)} 条线路｜第一线 {n} 个台"
            f"{'' if n else '，只当备选'}）")


def suspect_first_lines(channels: list[tuple[str, list[str]]], results: dict | None = None,
                        reach=None) -> dict:
    """第一线值得担心的那些台，它们的备选**换得出去吗** —— 按换过去落在哪里分五类。

    这是 `backup_pool` 的边界：池子只说「谁家还剩着备用线路」，但如果第一线可疑的那批台
    换过去还是同一家机房、或者换到的那一家也是专网，那「在电视上点第 2 条线路」这句建议
    对它们就不成立。2026-09-22 第一次量（计划书 2.25）：39 个可疑的台里
    24 个压根没有备选、1 个备选在同一家机房、14 个从湖南联通专网出口换到湖南移动专网门户
    —— **换得到公网电视线路的是 0 个**。所以那张表里根本没有「换线路」这条救法。

    判据（同一家机房算没换、电台不算救回来、没配 `reach` 就落 `other_unknown` 且
    `scope_known=False`）都写在 `src/cli.py::second_line_options` 的说明里，这里不复制一份：
    2.26 起报告也要回答这个问题，两处一份实现才不会出现两种口径。
    这个函数只是层薄壳 —— 试播包这一路的数据形状是 `(台名, [线路…])`（`channel_groups` 读回来的），
    而 cli 那一层吃 `OutputChannel`，所以搬过去的是算法，不是调用方。

    >>> from src.check.scope import Reachability
    >>> g = [("台一", ["http://i.example/1"]),
    ...      ("台二", ["http://i.example/2", "http://i.example:9901/3"]),
    ...      ("台三", ["http://i.example/4", "http://pub/5"]),
    ...      ("台六", ["http://j.example/6", "http://k.example/7"]),
    ...      ("台四", ["http://ok/8", "http://pub/9"]),
    ...      ("台五", ["http://new/10", "http://pub/11"])]
    >>> r = Reachability([".example"])
    >>> s = suspect_first_lines(g, reach=r)
    >>> (s["channels"], s["no_alt"], s["same_host"], s["other_intranet"], s["other_public"])
    (4, 1, 1, 1, 1)
    >>> s["reasons"], s["switchable"], s["lands"], s["scope_known"]
    ({'专网': 4}, ['台三'], [('k.example', 1)], True)
    >>> # 没有逐条判决时不下「没测过」的结论，只剩下专网那一层（`weak_first_line`）
    >>> suspect_first_lines(g, reach=r)["channels"]
    4
    >>> s2 = suspect_first_lines(g, {"http://i.example/2": None, "http://ok/8": None}, r)
    >>> (s2["channels"], s2["reasons"], s2["switchable"])      # 台五的第一线公网、但这一轮没测过
    (5, {'专网': 4, '没测过': 1}, ['台三', '台五'])
    >>> s3 = suspect_first_lines(g, {"http://i.example/1": None})   # 没给 reach：换到别家的判不了
    >>> (s3["channels"], s3["other_unknown"], s3["scope_known"], s3["switchable"])
    (5, 4, False, [])
    >>> # 换过去那一家按**台**数，不按线路数：这一个台在 k.example 上有两条备选，仍是「1 个台」
    >>> s4 = suspect_first_lines([("台一", ["http://i.example/1", "http://k.example/2",
    ...                                     "http://k.example:8080/3"])], reach=r)
    >>> (s4["other_intranet"], s4["lands"])
    (1, [('k.example', 1)])
    >>> # 电台那条不算救回来：`台一` 换到蜻蜓 FM 只有声音，`台二` 换到 pub 才算
    >>> r2 = Reachability([".example"], [".qingting.fm"])
    >>> sa = suspect_first_lines([("台一", ["http://i.example/1", "http://ls.qingting.fm/2"]),
    ...                           ("台二", ["http://i.example/3", "http://pub/4"])], reach=r2)
    >>> (sa["other_audio"], sa["other_public"], sa["lands"], sa["land_kind"], sa["switchable"])
    (1, 1, [('ls.qingting.fm', 1)], {'ls.qingting.fm': '纯音频电台'}, ['台二'])
    >>> # 一条线路都没有的台（连第一线都没有）不该被算进来
    >>> suspect_first_lines([("空台", [])], reach=r)["channels"]
    0
    """
    return second_line_options(
        [OutputChannel(n, "", "", "", list(u)) for n, u in channels], results or {}, reach)


def print_pool(pool: list[dict], has_results: bool = True, top: int | None = None,
               sus: dict | None = None) -> None:
    """把备选池印出来：2.24 之后这些族不在试播包里，但「换线路」这件事的候选只有它们。

    最后那段（`sus`）是这个池子的边界：它说的是**最需要救的那批台**（第一线是专网或没测过）
    在不在池子里有救。空池时前面整段都不印，但这段照样要说 —— 池子越空，「换线路没用」越该讲清楚。
    没有逐条判决时讲清楚「可疑」少判了哪一层，别让人把 `weak` 当成全集。
    `--top 0` 时这些族本来就在上面那张表里（第一线 0 个台），说明一句，免得以为是两份不同的东西。

    >>> ROW = {"label": "美国中转", "host": "1.2.3.4", "lines": 3, "served": 2,
    ...        "weak": 2, "intranet": 1, "unmeasured": 1, "note": "2/3 通",
    ...        "examples": ["湖南卫视", "CCTV-1综合"]}
    >>> print_pool([ROW])
    备选池（在表里只当第二三条线路、一个台的第一线都没挂的主机族；要把哪个台换到第二线，候选只在这里）：
      美国中转（1.2.3.4，3 条线路｜给 2 个台当备选：湖南卫视、CCTV-1综合）—— 2/3 通｜第一线可疑 2 个（专网 1、没测过 1）
    >>> print_pool([])
    >>> # weak 0 也要说出来：它的意思是「这条备选留着只当占位」，不是「这条不重要」
    >>> print_pool([dict(ROW, label="x", host="h", lines=1, served=1, weak=0, intranet=0,
    ...                 unmeasured=0, note="未实测", examples=["a"])], has_results=False)
    备选池（在表里只当第二三条线路、一个台的第一线都没挂的主机族；要把哪个台换到第二线，候选只在这里）：
      x（h，1 条线路｜给 1 个台当备选：a）—— 未实测｜没备到可疑的第一线
      这一轮没有逐条判决（probe.json 不在或离线生成），「可疑」只按专网地址判，「没测过」那一类没算进来
    >>> print_pool([dict(ROW, label="y", lines=1, served=1, weak=0, intranet=0, unmeasured=0,
    ...                 note="1/1 通", examples=[])], top=0)
    备选池（在表里只当第二三条线路、一个台的第一线都没挂的主机族；要把哪个台换到第二线，候选只在这里）：
      y（1.2.3.4，1 条线路｜给 1 个台当备选）—— 1/1 通｜没备到可疑的第一线
      （--top 0 时它们就在上面那张表里，「第一线」那列写着 0 个台）
    >>> from src.check.scope import Reachability
    >>> r = Reachability([".example"])
    >>> # 2026-09-22 那张表就是这个形状：池子里一条线路都没备到可疑的台，可疑的台又换不到公网
    >>> sus = suspect_first_lines([("台一", ["http://i.example/1"]),
    ...                            ("台二", ["http://j.example/2", "http://j.example:9901/3"])],
    ...                            reach=r)
    >>> print_pool([dict(ROW, weak=0, intranet=0, unmeasured=0)], sus=sus)
    备选池（在表里只当第二三条线路、一个台的第一线都没挂的主机族；要把哪个台换到第二线，候选只在这里）：
      美国中转（1.2.3.4，3 条线路｜给 2 个台当备选：湖南卫视、CCTV-1综合）—— 2/3 通｜没备到可疑的第一线
      换线路这条退路对第一线可疑的 2 个台（专网 2）成立到什么程度：1 个一条备选线路都没有、1 个的备选全在同一家机房、0 个换得到公网电视线路
        也就是说上面这 3 条备选线路备的全是第一线本来就通的台 —— 想在电视上「点第 2 条线路」救那些播不动的台，这张表里没有这条救法（要救得去别处找线路：P5）。
    >>> # 换到别家但别家也是专网 → 点名落在哪家；真换得到公网的 → 点名是哪几个台
    >>> sus2 = suspect_first_lines([("台一", ["http://i.example/1", "http://pub/2"]),
    ...                             ("台二", ["http://j.example/3", "http://k.example/4"])],
    ...                            reach=r)
    >>> print_pool([], sus=sus2)
    备选池：这张表里没有「一条第一线都不挂」的主机族 —— 每条线路都在给某个台挂第一线。
      换线路这条退路对第一线可疑的 2 个台（专网 2）成立到什么程度：1 个换到别家、可那一家也是专网、1 个换得到公网电视线路
        换不到公网电视线路的那些，换过去落在：k.example（k.example，IPTV 专网）1 个台
        真换得到公网线路的这些台：台一
    >>> # 电台那条要说清楚是电台：电脑实测它通，可电视上点开没有画面，不能算「换得到公网」
    >>> sus3 = suspect_first_lines([("台一", ["http://i.example/1", "http://ls.qingting.fm/2"])],
    ...                            reach=Reachability([".example"], [".qingting.fm"]))
    >>> print_pool([], sus=sus3)
    备选池：这张表里没有「一条第一线都不挂」的主机族 —— 每条线路都在给某个台挂第一线。
      换线路这条退路对第一线可疑的 1 个台（专网 1）成立到什么程度：1 个换过去只有电台（有声音、没画面）、0 个换得到公网电视线路
        换不到公网电视线路的那些，换过去落在：ls.qingting.fm（ls.qingting.fm，纯音频电台）1 个台
        也就是说这张表里没给它们留任何一条能换的第二线 —— 想在电视上「点第 2 条线路」救那些播不动的台，这张表里没有这条救法（要救得去别处找线路：P5）。
    """
    if not pool and not (sus and sus["channels"]):
        return
    if pool:
        print("备选池（在表里只当第二三条线路、一个台的第一线都没挂的主机族；"
              "要把哪个台换到第二线，候选只在这里）：")
    else:
        print("备选池：这张表里没有「一条第一线都不挂」的主机族 —— 每条线路都在给某个台挂第一线。")
    for a in pool:
        ex = "、".join(a["examples"][:3]) + ("…" if len(a["examples"]) > 3 else "")
        served = f"{a['served']} 个台当备选" + (f"：{ex}" if ex else "")
        if a["weak"]:
            kinds = "、".join(f"{cn} {a[k]}" for k, cn in (("intranet", "专网"),
                                                          ("unmeasured", "没测过")) if a[k])
            weak = f"第一线可疑 {a['weak']} 个（{kinds}）"
        else:
            weak = "没备到可疑的第一线"
        print(f"  {a['label']}（{a['host']}，{a['lines']} 条线路｜给 {served}）"
              f"—— {a['note']}｜{weak}")
    if any("†" in a["note"] for a in pool):
        print("  † 这个分数是上游整族的实测条数（本机没有逐条判决，对不上表里这几条），仅供参考")
    if not has_results:
        print("  这一轮没有逐条判决（probe.json 不在或离线生成），「可疑」只按专网地址判，"
              "「没测过」那一类没算进来")
    if top == 0:
        print("  （--top 0 时它们就在上面那张表里，「第一线」那列写着 0 个台）")
    if sus and sus["channels"]:
        kinds = "、".join(f"{k} {v}" for k, v in sorted(sus["reasons"].items()))
        parts = [(f"{sus['no_alt']} 个一条备选线路都没有", sus["no_alt"]),
                 (f"{sus['same_host']} 个的备选全在同一家机房", sus["same_host"]),
                 (f"{sus['other_intranet']} 个换到别家、可那一家也是专网", sus["other_intranet"]),
                 (f"{sus['other_audio']} 个换过去只有电台（有声音、没画面）", sus["other_audio"]),
                 (f"{sus['other_unknown']} 个换到别家（没配可达范围，判不了那一家）",
                  sus["other_unknown"]),
                 # 「换得到公网线路」这一项**永远写**：0 才是这一整段的结论
                 (f"{sus['other_public']} 个换得到公网电视线路", True)]
        detail = "、".join(t for t, n in parts if n)
        print(f"  换线路这条退路对第一线可疑的 {sus['channels']} 个台（{kinds}）成立到什么程度：{detail}")
        if sus["lands"]:
            print("    换不到公网电视线路的那些，换过去落在："
                  + "、".join(f"{family_label(b)}（{b}，{sus['land_kind'].get(b, '范围未知')}）{n} 个台"
                             for b, n in sus["lands"][:3]))
        if sus["switchable"]:
            print("    真换得到公网线路的这些台：" + "、".join(sus["switchable"][:8])
                  + ("…" if len(sus["switchable"]) > 8 else ""))
        elif sus["scope_known"]:
            head = (f"也就是说上面这 {sum(a['lines'] for a in pool)} 条备选线路"
                    "备的全是第一线本来就通的台"
                    if pool else "也就是说这张表里没给它们留任何一条能换的第二线")
            print(f"    {head} —— 想在电视上「点第 2 条线路」救那些播不动的台，"
                  "这张表里没有这条救法（要救得去别处找线路：P5）。")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成试播包")
    ap.add_argument("--in", dest="src", default="aptv.m3u")
    ap.add_argument("--out", dest="dst", default="probe-pack.m3u")
    ap.add_argument("--top", type=int, default=14,
                    help="挑「挂着最多台第一线」的 N 个主机族，0=全部")
    ap.add_argument("--keep-dead", action="store_true",
                    help="连实测整族失效的主机族也放进来（默认剔掉，省遥控器点击）")
    args = ap.parse_args()

    src = OUT_DIR / args.src
    if not src.exists():
        print(f"找不到 {src}，先跑：{sys.executable} -m src.cli build", file=sys.stderr)
        return 1

    channels = channel_groups(src.read_text(encoding="utf-8"))
    stats, results = load_stats(), load_results()
    reach = load_reachability(REACH_FILE)
    text, legend, skipped, cut = build(channels, args.top, stats, args.keep_dead,
                                        results, reach)
    dst = OUT_DIR / args.dst
    dst.write_text(text, encoding="utf-8")

    # 覆盖面可以直接相加：这一版的行**就是**去端口的主机族（`srs.iyb983.cn` 和它的 `:443`
    # 早先是两行两个编号，现在是一行），所以不存在同一个族被算两遍。
    covered = sum(l["first"] for l in legend)
    n_fam = len({base_of(host_of(u)) for _, urls in channels for u in urls})
    print(f"已生成 {dst}（{len(legend)} 条，逐个点开试）"
          + ("" if stats else "  ← 没有 data/output/probe.json，全部按未实测处理"))
    print(f"这 {len(legend)} 条覆盖 {covered}/{len(channels)} 个台的第一线"
          + ("" if covered == len(channels)
             else f"，剩下 {len(channels) - covered} 个台的第一线在被切掉的族里"
                  f"（--top 0 = 全 {n_fam} 族都在表里）"))

    if skipped:
        print(f"\n已剔除 {len(skipped)} 个整族失效的主机族（电脑实测连不上，不必让电视再试）：")
        for s in skipped:
            print(f"  - {s}")
        print("  要看它们：--keep-dead")
    if cut:
        print(f"\n被 --top {args.top} 切掉的 {len(cut)} 个主机族（★基准与对照组不在名单里，它们一定会补回来）：")
        for c in cut:
            print(f"  - {c}")
        print("  上面写着「第一线 0 个台」的那些只当备选，不点也不影响电视上能看的台；"
              "写着 1 个台的就是上面那句「剩下」的来处 —— 要看它们：--top 0")
    print()
    print(f"{'编号':<4} {'第一线':<14} {'范围':<16} {'电脑实测':<14} 主机族｜代表频道")
    for l in legend:
        first = f"{l['first']} 个台" + (f"（{l['unmeasured']} 没测过）" if l["unmeasured"] else "")
        print(f"{l['mark']:<5} {first:<16} {l['scope'] or '—':<18} {l['note']:<16} "
              f"{l['family']}｜{l['channel']}")
    alone = [l for l in legend if l["alone"]]
    if alone:
        print("\n「换线路也换不出去」（这个台全部线路都在同一家主机上，点它不通就是真没得看）的台数："
              + "、".join(f"{l['label']} {l['alone']} 个" for l in alone))
    pool = backup_pool(channels, results, stats, reach)
    sus = suspect_first_lines(channels, results, reach)
    if pool or sus["channels"]:
        print()                       # 两段都没有就不留一个孤零零的空行
        print_pool(pool, bool(results), args.top, sus)
    print("\n判读：这一列「通」只代表电脑直连拿到了播放列表和分片。"
          "电视上黑屏/卡住 = 这台机房到家的路太长或码率太高，"
          "那种主机族要在 config/reachability.yaml 里单独降一档。")
    print("编号是按「挂着几个台的第一线」排的，换上游或换排序参数就会变 —— "
          "报结果时说主机族的名字（湖南移动IPTV门户），别说编号。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
