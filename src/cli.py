"""命令行入口。

用法：

    python -m src.cli build                  # 用 data/cache 里的上游缓存离线生成
    python -m src.cli build --fresh          # 联网抓 config/sources.yaml 里启用的源
    python -m src.cli build --verify         # 生成前实测线路（probe:false 的源跳过）
    python -m src.cli build --source <url或文件>   # 临时换上游，忽略 sources.yaml

产物在 data/output/：aptv.m3u（全量）、hunan.m3u（只有湖南本地）、report.md、probe.json（实测过才有）。

`config/sources.yaml` 是别人维护的聚合源，`config/sources_local.yaml` 是手工核对过的补充线路
（带出处和有效期），两边都会读；`--skip-local` 只在前者里找问题时用。

同一频道的多条线路按「可达范围」+「实测延迟」排先后（范围规则在 config/reachability.yaml），
公网且快的排第一，因为 APTV 默认只播第一条；运营商 IPTV 内网地址和电台冒充项退居备选。

每轮 `--verify` 的主机汇总还会追加到 `data/output/probe-history.jsonl`（一行一轮，
30 分钟内连跑算同一轮）。不带 `--verify` 时靠这份履历排序：上一轮整族连不上的往后压、
上一轮量到过延迟的按那时补位 —— 否则「这次没实测」会让上一轮确认的官方流被来源优先级挤掉。
判据只认体检没报警的那些轮，参照出口见 `judgment_egress()` 的说明；`--ignore-history` 可整个关掉。

注意：联网抓取与 --verify 实测都从本机出口出去，所以测量点是谁必须先说清楚。
代理客户端的 TUN 一开，DNS 就被换成 fake-IP、出口跑到境外机房，对国内运营商类地址
全是假阴性（计划书 2.8）。跑 --verify 前会先做体检并把警告打在屏幕上，
出口身份和逐条结果一起写进 data/output/probe.json。
2026-09-21 起：TUN 关掉后本机出口就是家里的联通宽带，与 Apple TV 同一张网，
这时的实测数字可以直接当判据。

体检报警的那一轮 `--verify` 只写履历，产物（两张 m3u + probe.json + report.md）关进
`data/output/untrusted/`，`data/output/` 保持上一轮可信版本 —— 因为 `--verify` 会删线路，
而局域网服务正把 `data/output/` 当订阅目录发给电视（见 `artifact_dir()`）。
确实要在别的测量点上出表就加 `--allow-untrusted`。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlsplit

# Windows 控制台默认 GBK，输出 emoji 分组名会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.check import history as hist  # noqa: E402
from src.check.env import egress_hint, measurement_warnings  # noqa: E402
from src.check.prober import ProbeResult, is_fake_live, probe_many  # noqa: E402
from src.check.scope import (  # noqa: E402
    AUDIO, INTRANET, PUBLIC, RANK, Reachability, load_reachability)
from src.match.matcher import load_index  # noqa: E402
from src.match.normalize import quality_hint  # noqa: E402
from src.output.writer import OutputChannel, format_m3u, format_report  # noqa: E402
from src.parse.local import SOURCE_ID as LOCAL_ID  # noqa: E402
from src.parse.local import load_local  # noqa: E402
from src.parse.m3u import Entry, parse_m3u  # noqa: E402

SOURCES_FILE = ROOT / "config" / "sources.yaml"
LOCAL_SOURCES_FILE = ROOT / "config" / "sources_local.yaml"
REACH_FILE = ROOT / "config" / "reachability.yaml"
HISTORY_FILE = ROOT / "data" / "output" / "probe-history.jsonl"
CACHE_DIR = ROOT / "data" / "cache"
HUNAN_GROUPS = ("hunan_local", "changsha", "shizhou", "jinying")
_RANK = {"4K": 4, "FHD": 3, "HD": 2, "SD": 1, "": 0}
_LATENCY_TIERS = ((400, 0), (1000, 1))    # 毫秒 -> 档位；超过上限算 2

# 带签名/鉴权参数的私有流：URL 里绑死了抓取方的 IP、账号哈希和有效期，
# 别人拿到一定播不了（咪咕那类），而且属于计划书划定的红线（不盗链需鉴权私有流），
# 一律不进订阅列表。
_AUTH_URL = re.compile(
    r"SecurityKey=|ddCalcu=|msisdn=|assertID=|auth_key=|wsTime=|txypb=|"
    r"token=|accountinfo=|[?&]u=[0-9a-f]{16,}", re.I)


def latency_tier(r: ProbeResult | None) -> int:
    """把实测延迟压成三档，作为可达范围之后的第二个排序键。

    没实测（返回 None）给中间档 1，不偏袒也不惩罚。
    只分档不按原始毫秒排，是因为单次抖动几毫秒很常见，直接用毫秒会让整张表顺序乱跳。

    >>> latency_tier(None), latency_tier(ProbeResult(True, 200, 210, 3)), \
        latency_tier(ProbeResult(True, 200, 1271, 3))
    (1, 0, 2)
    """
    if r is None:
        return 1
    for limit, tier in _LATENCY_TIERS:
        if r.ms < limit:
            return tier
    return 2


def judgment_egress(egress: str, warns: list[str], runs: list[dict], *, measured: bool) -> str:
    """本轮排序该用哪个出口当判据。

    规则之所以不是「当前出口」那么直白：这张表是给电视用的，而电视永远待在家里那张
    Wi-Fi 上，它不会跟着开发机的代理跑。所以只有一种情况才用当前出口：
    本轮真在实测（`--verify`）**且**体检没报警。其余一律退回历史里最近一次体检干净的出口；
    离线生成（不带 `--verify`）时当前出口根本不构成任何测量，用它等于没依据。
    真发生过：TUN 开着重出一次离线表，上一轮确认 378ms 的湖南广电官方流就整个消失了。

    >>> clean = [{"at": "t1", "egress": "119.39.40.124 CN", "warnings": []}]
    >>> judgment_egress("119.39.40.124 CN", [], clean, measured=True)  # 本轮体检干净：用本轮
    '119.39.40.124 CN'
    >>> judgment_egress("139.x JP", ["TUN 已开启"], clean, measured=True)  # 本轮测了但不可信
    '119.39.40.124 CN'
    >>> judgment_egress("139.x JP", [], clean, measured=False)            # 离线：只认历史
    '119.39.40.124 CN'
    >>> judgment_egress("139.x JP", ["TUN 已开启"], [], measured=True)     # 没有可信历史：不猜
    ''
    """
    if measured and egress and not warns:
        return egress
    return hist.current_egress("", runs)


UNTRUSTED = "untrusted"


def artifact_dir(out_dir: Path | str, *, warns: list[str], measured: bool,
                 force: bool = False) -> tuple[Path, bool]:
    """这一轮的产物该落在哪个目录，以及是不是被隔离了。

    `judgment_egress()` 已经保证「体检报警的轮次不参与排序判据」，但那只管到排序为止：
    `--verify` 还会**实测剔除失效线路**并覆盖 `aptv.m3u` / `hunan.m3u` / `probe.json` /
    `report.md`，而 `scripts/serve_lan.py` 正把 `data/output/` 当订阅目录发给电视。
    于是 2026-09-21 夜发生过一次：TUN 开着补跑一轮实测（73 条被假阴性判死），
    电视拿到的那张表当场换成了境外机房视角的版本 —— 履历没错，错在产物。

    所以报警的那一轮只写履历（留着看变化），产物关进 `out_dir/untrusted/`，
    `data/output/` 保持上一轮可信版本原样不动。真要在外网出口上出表就 `force=True`。

    >>> def probe(warns, measured, force=False, out="/o"):
    ...     d, q = artifact_dir(out, warns=warns, measured=measured, force=force)
    ...     return (d.name, q)
    >>> probe([], True)                       # 体检干净的实测：照常落在 data/output
    ('o', False)
    >>> probe(["TUN 已开启"], True)             # 报警的实测：隔离
    ('untrusted', True)
    >>> probe(["TUN 已开启"], True, force=True)  # 明知故犯的出口
    ('o', False)
    >>> probe(["TUN 已开启"], False)            # 离线生成没做实测，无本轮结果可污染
    ('o', False)
    >>> str(artifact_dir("/o/sub", warns=["w"], measured=True)[0]).replace("\\\\", "/")
    '/o/sub/untrusted'
    """
    base = Path(out_dir)
    if measured and warns and not force:
        return base / UNTRUSTED, True
    return base, False


def host_latency(rep: dict[str, hist.HostRep]) -> dict[str, int]:
    """主机 -> 上一轮可信实测的最好延迟。只收「至少通过过一次」的主机。

    >>> r = hist.HostRep
    >>> sorted(host_latency({"a": r("a", 1, 1, 3, 3, 210, "x", 0),
    ...                      "b": r("b", 1, 0, 3, 0, 0, "x", 1)}).items())
    [('a', 210)]
    """
    return {name: rep.best_ms for name, rep in rep.items() if rep.ok_runs and rep.best_ms}


def effective_tier(url: str, r: ProbeResult | None, hist_ms: dict[str, int]) -> int:
    """排序用的延迟档：本轮实测 > 上一轮同主机的实测 > 没听说过。

    为什么需要第二级：离线生成（不带 `--verify`）时所有线路都没有本轮实测，
    原来全部落在中间档 1，于是 mgtv 那条湖南广电官方流（实测 378ms）会被
    来源优先级挤到第三条之后 —— 2026-09-21 实测过一轮之后，离线重出一次表，
    那条线直接从 `aptv.m3u` 里消失了。用上一轮的延迟补位，就是不让表里最好的一条
    线路因为「这次没空重测」而被换掉。本轮只要测过，就完全不听历史的。

    >>> m = {"fast.example": 210, "slow.example": 1326}
    >>> effective_tier("http://fast.example/a.m3u8", None, m)      # 上轮 210ms -> 最快档
    0
    >>> effective_tier("http://slow.example/a.m3u8", None, m)      # 上轮 1326ms -> 最慢档
    2
    >>> effective_tier("http://new.example/a.m3u8", None, m)       # 没历史：不偏袒
    1
    >>> effective_tier("http://fast.example/a.m3u8", ProbeResult(True, 200, 1500, 3), m)
    2
    """
    if r is not None:
        return latency_tier(r)
    ms = hist_ms.get(urlsplit(url).hostname or "")
    return latency_tier(ProbeResult(True, 200, ms, 1)) if ms else 1


def history_strike(url: str, r: ProbeResult | None, stale: frozenset[str]) -> int:
    """这一轮没实测、但上一轮整族连不上的主机，往后压一档。

    它存在的唯一理由：`build` 不带 `--verify` 时手里没有任何实测信息，
    上一轮已经确认 0/35 的 `stream1.freetv.fun` 会凭来源优先级又爬回频道第一位。
    只要本轮测过（r 不是 None），历史就闭嘴 —— 现场的数永远比记忆可信，
    中转主机「今天全灭明天全通」两种方向都发生过。

    >>> live = ProbeResult(True, 200, 900, 3)
    >>> stale = frozenset({"dead.example"})
    >>> history_strike("http://dead.example/a.m3u8", live, stale)     # 本轮说能播，就听本轮
    0
    >>> history_strike("http://dead.example/a.m3u8", None, stale)     # 没实测 + 上轮全灭
    1
    >>> history_strike("http://good.example/a.m3u8", None, stale)
    0
    """
    if r is not None:
        return 0
    return 1 if (urlsplit(url).hostname or "") in stale else 0


def roll_strike(url: str, r: ProbeResult | None, rolls: dict[str, str]) -> int:
    """L3 验过「隔十几秒重取，分片窗口一动不动」的那条线路，本轮没重测时往后压一档。

    为什么不并入主机那一档（`fake_strike`）：一个主机可以有三十八条线路，
    L3 一次只盯得住几个台的第一线。整族判断要「通了的全是录像」才成立，
    而这一条是逐条的确凿证据 —— 少一个精度，那条 2026-09-21 的残留列表就会
    继续顶着同主机另外几条一起占位。同样只在没重测时生效。

    >>> rolls = {"http://a.example/stuck.m3u8": "stuck", "http://a.example/live.m3u8": "rolling"}
    >>> roll_strike("http://a.example/stuck.m3u8", None, rolls)
    1
    >>> roll_strike("http://a.example/live.m3u8", None, rolls)      # 上次验过在滚：不惩罚
    0
    >>> roll_strike("http://a.example/stuck.m3u8",                  # 本轮重测过，听本轮的
    ...               ProbeResult(True, 200, 90, 4, "", "live"), rolls)
    0
    >>> roll_strike("http://a.example/new.m3u8", None, rolls)       # L3 没看过：不猜
    0
    """
    if r is not None:
        return 0
    return 1 if rolls.get(url) == "stuck" else 0


def fake_strike(url: str, r: ProbeResult | None, fake: frozenset[str]) -> int:
    """上一轮确认「通了的全是循环录像」的主机，本轮没实测时往后压一档。

    和 `history_strike()` 是两个不同的病：那个是连不上（电视上超时），
    这个连得上、有画，播出来是几小时前的节目，而且往往比真直播还快 ——
    2026-09-21 实测到快手 CDN 一条 1259 分片的录像挂在湖南卫视名下，延迟比官方流还低。
    所以它必须排在真直播后面，但**不删**：一个台只剩录像和够不着的内网地址时，
    有画可看比超时强，代价是在报告里点名说清楚它不是直播。

    同样地，本轮只要测过就听本轮的（`is_fake_live(r)` 那一档会直接判它）。

    >>> fake = frozenset({"loop.example"})
    >>> fake_strike("http://loop.example/a.m3u8", None, fake)          # 没实测 + 上轮全是录像
    1
    >>> fake_strike("http://loop.example/a.m3u8",                     # 本轮重测：真在滚动
    ...               ProbeResult(True, 200, 100, 3, "", "live"), fake)
    0
    >>> fake_strike("http://other.example/a.m3u8", None, fake)
    0
    """
    if r is not None:
        return 0
    return 1 if (urlsplit(url).hostname or "") in fake else 0


def load_sources(path: Path, *, fresh: bool) -> list[dict]:
    """读 config/sources.yaml 里启用的源，解析成本地缓存路径或远端 URL。

    默认优先用 data/cache/<id>.m3u（可离线复现），没有缓存才联网；
    --fresh 强制联网，抓到的内容会回写缓存。

    `probe: false` 的源（运营商内网源）不参与 --verify 实测：
    它们的可达性取决于看电视那张网，开发机上测出来全红是假阴性。
    """
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out = []
    for i, s in enumerate(cfg.get("sources") or []):
        if not s.get("enabled", True):
            continue
        cache = CACHE_DIR / f"{s['id']}.m3u"
        target = s["url"] if (fresh or not cache.exists()) else str(cache)
        out.append({"id": s["id"], "target": target, "cache": cache, "url": s["url"],
                    "probe": bool(s.get("probe", True)),
                    "priority": int(s.get("priority", i + 1))})
    return out


def fetch(target: str, timeout: int = 60) -> str:
    """读上游。本地文件直接读，URL 走 urllib（自动使用系统代理设置）。"""
    if target.startswith(("http://", "https://")):
        url = quote(target, safe=":/?&=%#[]@!$'()*+,;")   # 上游路径里有中文
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    return Path(target).read_text(encoding="utf-8", errors="replace")


def collect(sources: Iterable[dict | str]) -> tuple[list[Entry], list[str]]:
    """sources 元素可以是 load_sources() 的 dict，也可以是裸路径/URL（--source 传入）。"""
    entries: list[Entry] = []
    epg_urls: list[str] = []
    for src in sources:
        if isinstance(src, str):
            src = {"id": src.rsplit("/", 1)[-1][:40], "target": src, "cache": None}
        text = fetch(src["target"])
        tag = src["id"]
        pl = parse_m3u(text, source=tag)
        entries.extend(pl.entries)
        if pl.x_tvg_url:
            epg_urls.append(pl.x_tvg_url)
        if src.get("cache") is not None and src["target"].startswith("http"):
            cache: Path = src["cache"]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        via = "缓存" if not src["target"].startswith("http") else "联网"
        print(f"  {tag}（{via}）: {len(pl)} 条（跳过 {pl.skipped} 行畸形数据）")
    return entries, epg_urls


def aggregate(entries: list[Entry], index, max_lines: int, *,
              verify: bool = False, timeout: int = 12, workers: int = 20,
              max_per_host: int = 2, skip_verify: Iterable[str] = (),
              source_priority: dict[str, int] | None = None,
              reach: Reachability,
              stale_hosts: frozenset[str] = frozenset(),
              fake_hosts: frozenset[str] = frozenset(),
              rolls: dict[str, str] | None = None,
              hist_ms: dict[str, int] | None = None):
    """归位 + 合并多线路 + 同源收敛 + 排序 + 截断（可选实测过滤）。

    max_per_host 用来治「一个频道的 5 条线路其实全来自同一个失效主机」——
    实测湖南线路里 64% 来自 stream1.freetv.fun 这一个已不可用的域名。

    skip_verify 里的来源 id 是「开发机测不准」的运营商内网源，实测时原样保留。

    排序主键是可达范围，其次才是实测延迟、来源优先级和清晰度：APTV 默认只播第一条线路，
    所以「电视够不到的地址」必须让位给公网线路。上一版把来源优先级当主键，
    覆盖最全的 hn_unicom/hn_mobile 于是吃掉了 39/39 个湖南频道的第一顺位，
    真机观感就是整张表全超时。内网线路不删，只是排到后面当备选。

    延迟档是 2026-09-21 补的第二键。同一批公网线路里，美国机房中转（845~1271ms）
    和湖南广电官方公网流 hlsal-ldvt.qing.mgtv.com（210ms）当时是并列的，
    结果 max_lines=3 把那条最该留的官方流挤掉了 —— 只判「通不通」不够，
    还得让快的排前面，尤其是电视要拿它连续播几个小时。

    假直播（循环录像）在可达范围同一档内被压到真直播后面，见 prober.is_fake_live：
    实测到 txmov2.a.kwimgs.com 有条 1259 分片的录像挂在湖南卫视名下，
    它比真直播还快，只按延迟排会把录像顶到第一位。不删，是因为对只有录像和内网
    地址的台来说，有画可看比超时强；但这类频道会在使用报告里点名。

    stale_hosts / hist_ms 来自实测履历（data/output/probe-history.jsonl），都只影响
    本轮没测过的线路：前者把上一轮整族连不上的往后压，后者把上一轮量到过的主机按
    那时的延迟补进档位 —— 否则离线重出表时全部线路同为"未知"，
    上一轮确认 378ms 的湖南广电官方流会被来源优先级挤掉（见 effective_tier）。

    fake_hosts / rolls 是同一份履历里的「内容」判据（history.fake_hosts / merge_rolls）：
    前者是上一轮这个主机通了的线路全是循环录像，后者是 L3 逐条验过的「列表不动」。
    它们排在可达范围与「本轮实测是录像」之后、延迟档之前 ——
    录像通常比真直播快，只用延迟当第二键会被顶到第一位去。
    """
    skip_verify = set(skip_verify)
    prio = source_priority or {}
    rolls = rolls or {}
    hist_ms = hist_ms or {}
    buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"lines": [], "seen": set(), "tvg_id": "", "logo": "", "order": 0, "group_title": ""}
    )
    unmatched: Counter[str] = Counter()
    excluded = 0
    private = 0

    for e in entries:
        if _AUTH_URL.search(e.url):
            private += 1
            continue                      # 鉴权私有流：换 IP 换时间必播不动
        res = index.resolve(e)
        if res is None:
            if index.is_excluded(e):
                excluded += 1
            else:
                unmatched[e.name] += 1
            continue

        bucket = buckets[(res.group, res.name)]
        if e.url in bucket["seen"]:
            continue                      # 同一频道的重复 url 没有意义
        bucket["seen"].add(e.url)
        bucket["lines"].append(e)
        bucket["tvg_id"] = bucket["tvg_id"] or res.tvg_id
        bucket["logo"] = bucket["logo"] or e.logo
        bucket["group_title"] = index.group_title(res.group)
        bucket["order"] = min(bucket["order"], res.order) if bucket["lines"][:-1] else res.order

    if private:
        print(f"\n剔除鉴权私有流 {private} 条（URL 里绑了别人的 IP 和时效，红线不收录）")

    results: dict[str, ProbeResult] = {}
    if verify:
        urls = sorted({e.url for b in buckets.values() for e in b["lines"]
                       if e.source not in skip_verify})
        print(f"\n实测 {len(urls)} 条线路（本机出口直连）...")
        results = dict(zip(urls, probe_many(urls, timeout, workers)))
        print(f"  可用 {sum(1 for r in results.values() if r.ok)}/{len(urls)}")
        # 分源统计：某些源（如湖南移动）只在对应运营商网络内可达，
        # 在开发机上全红不代表电视上不能用，必须分开看。
        stat: dict[str, Counter] = defaultdict(Counter)
        for b in buckets.values():
            for e in b["lines"]:
                stat[e.source]["all"] += 1
                r = results.get(e.url)
                if r is not None and r.ok:
                    stat[e.source]["ok"] += 1
        for src, c in stat.items():
            tag = "跳过实测（运营商内网源）" if src in skip_verify else f"可用 {c['ok']}/{c['all']}"
            print(f"    {src}: {tag}")

    dead = 0
    stale_hits = 0
    channels: list[OutputChannel] = []
    for (group, name), b in buckets.items():
        ordered = sorted(
            b["lines"],
            key=lambda e: (reach.rank(e.url),
                           history_strike(e.url, results.get(e.url), stale_hosts),
                           is_fake_live(results.get(e.url)),
                           roll_strike(e.url, results.get(e.url), rolls),
                           fake_strike(e.url, results.get(e.url), fake_hosts),
                           effective_tier(e.url, results.get(e.url), hist_ms),
                           prio.get(e.source, 99),
                           -_RANK.get(quality_hint(f"{e.name} {e.url}"), 0),
                           e.seq),
        )
        host_used: Counter[str] = Counter()
        kept: list[Entry] = []
        for e in ordered:
            if len(kept) >= max_lines:
                break
            r = results.get(e.url)
            if r is not None and not r.ok:
                dead += 1
                continue
            host = urlsplit(e.url).hostname or e.url[:16]
            if host_used[host] >= max_per_host:
                continue                  # 同源收敛；这不是失效，不计入 dead
            host_used[host] += 1
            kept.append(e)
        if not kept:
            continue
        if history_strike(kept[0].url, results.get(kept[0].url), stale_hosts):
            stale_hits += 1        # 这个台实在没有更好的选择了，第一线还是那台已死的

        channels.append(
            OutputChannel(
                name=name,
                group_title=b["group_title"],
                tvg_id=b["tvg_id"],
                logo=b["logo"],
                urls=[e.url for e in kept],
                order=(index.groups[group]["order"], b["order"]),
            )
        )

    channels.sort(key=lambda c: c.order)
    return channels, unmatched, excluded, dead, results, stale_hits


def host_summary(results: dict[str, ProbeResult], reach: Reachability,
                 src_of: dict[str, list[str]] | None = None) -> list[dict]:
    """把逐条实测按主机汇总：回答「哪个主机族在家里这张网里是死的、哪些是活的但放的是录像」。

    这一步是实测真正的产出。只报「可用 215/330」没法定下一步 ——
    2026-09-21 那次汇总才看清：美国中转族 128/131 全活，
    而 stream1.freetv.fun 0/17 整族失效（DNS 已被换到一个不服务的美图 IP），
    于是不用电视实测就能断定「湖南经视等台的公网线路其实不存在」。

    `vod` 那一列是同一件事的第二半：连着且有分片、内容却是循环录像的条数。
    它决定的是「离线重出表时这个主机还能不能占第一线」，见 history.fake_hosts。

    `src_of` 是 2.17 加的第三半：**这一族是谁塞进来的**。没有它，报告说得出
    「`stream1.freetv.fun` 0/36 整族失效」却说不出该动 `sources.yaml` 里哪一行。
    一台主机可以挂在多个源下（聚合源之间互相抄），所以是个列表，原样存进履历。

    返回按（可达范围、失效数倒序）排好的行：host/scope/total/ok/best_ms/vod/srcs。

    >>> r = Reachability([".dead.example"])
    >>> res = {"http://a.example/1.m3u8": ProbeResult(True, 200, 100, 3, "", "live"),
    ...        "http://a.example/2.m3u8": ProbeResult(True, 200, 120, 900, "", "vod"),
    ...        "http://dead.example/x.m3u8": ProbeResult(False, 0, 5000, 0, "timeout")}
    >>> for row in host_summary(res, r):
    ...     print(row["host"], row["scope"], f"{row['ok']}/{row['total']}", row["vod"], row["srcs"])
    a.example public 2/2 1 []
    dead.example iptv_intranet 0/1 0 []
    >>> rows = host_summary(res, r, {"http://a.example/1.m3u8": ["gd"],
    ...                              "http://dead.example/x.m3u8": ["gd", "local"]})
    >>> [(x["host"], x["srcs"]) for x in rows]      # 同一主机的来源去重后按名字排
    [('a.example', ['gd']), ('dead.example', ['gd', 'local'])]
    """
    agg: dict[str, dict] = {}
    src_of = src_of or {}
    for url, r in results.items():
        host = urlsplit(url).hostname or url[:16]
        a = agg.setdefault(host, {"host": host, "scope": reach.scope(url),
                                  "total": 0, "ok": 0, "best_ms": 0, "vod": 0, "srcs": set()})
        a["srcs"] |= set(src_of.get(url) or [])
        a["total"] += 1
        if r.ok:
            a["ok"] += 1
            a["best_ms"] = r.ms if not a["best_ms"] else min(a["best_ms"], r.ms)
            if is_fake_live(r):
                a["vod"] += 1
    for a in agg.values():
        a["srcs"] = sorted(a["srcs"])
    return sorted(agg.values(),
                  key=lambda a: (RANK[a["scope"]], -a["total"], a["host"]))


def load_lean_fn():
    """取 scripts/lean_playlist.lean()：裸订阅表的生成逻辑只保留一份实现。

    scripts/ 不是包，所以按文件路径加载；文件不在就返回 None，
    主流程照常出 aptv.m3u / hunan.m3u，不因诊断用的附属文件而失败。
    """
    path = ROOT / "scripts" / "lean_playlist.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("lean_playlist", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.lean


def cmd_build(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="src.cli build", description="生成 APTV 订阅列表")
    ap.add_argument("--source", action="append", dest="sources",
                    help="临时指定上游（URL 或本地文件），可重复；给了它就忽略 sources.yaml")
    ap.add_argument("--sources-file", default=str(SOURCES_FILE))
    ap.add_argument("--config", default=str(ROOT / "config" / "channels.yaml"))
    ap.add_argument("--out", default=str(ROOT / "data" / "output"))
    ap.add_argument("--max-lines", type=int, default=3, help="每个频道最多保留几条线路")
    ap.add_argument("--max-per-host", type=int, default=2, help="同一频道内同一主机最多几条")
    ap.add_argument("--verify", action="store_true", help="生成前实测每条线路，剔除失效")
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--fresh", action="store_true", help="强制联网抓最新上游，忽略本地缓存")
    ap.add_argument("--skip-local", action="store_true",
                    help="不读 config/sources_local.yaml（排查手工源本身时用）")
    ap.add_argument("--history", default=str(HISTORY_FILE),
                    help="实测履历 jsonl：离线生成时靠它给已知失效主机降档、给已知快的主机补位"
                         "（默认 data/output/probe-history.jsonl）")
    ap.add_argument("--ignore-history", action="store_true",
                    help="完全不看履历，只按本轮（或无本轮）的结果排 —— 复现旧行为、排查降档本身时用")
    ap.add_argument("--allow-untrusted", action="store_true",
                    help="明知故犯：体检报警也照旧覆盖 data/output/（默认会把产物关进 untrusted/）")
    args = ap.parse_args(argv)

    sources = (
        [{"id": s.rsplit("/", 1)[-1][:40], "target": s, "cache": None} for s in args.sources]
        if args.sources
        else load_sources(Path(args.sources_file), fresh=args.fresh)
    )
    if not sources:
        print("config/sources.yaml 里没有启用的源。", file=sys.stderr)
        return 1
    print(f"读取 {len(sources)} 个上游：")
    entries, epg_urls = collect(sources)
    local_lines: list[Entry] = [] if args.skip_local else load_local(LOCAL_SOURCES_FILE)
    if local_lines:
        print(f"  {LOCAL_ID}（手工核对）: {len(local_lines)} 条 ← config/sources_local.yaml")
        entries += local_lines
    if not entries:
        print("没有解析到任何条目，检查网络或上游地址。", file=sys.stderr)
        return 1

    index = load_index(args.config)
    reach = load_reachability(REACH_FILE)

    # 实测履历：判据只认「体检没报警」的那些轮，而参照出口由 judgment_egress() 定
    # （表是给电视用的，开发机代理在哪不影响这个依据）。
    # 出口身份现查一次就够，屏幕、probe.json、落盘、体检都用它，别重复查。
    history_path = Path(args.history)
    runs = hist.load_history(history_path)
    egress = egress_hint()
    warns = measurement_warnings(egress) if args.verify else []   # 只查一次，后面几处复用
    if not runs and not history_path.exists():
        old = Path(args.out) / "probe.json"
        try:
            adopted = hist.adopt_probe(json.loads(old.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            adopted = None
        if adopted:
            hist.append_run(history_path, adopted)
            runs = hist.load_history(history_path)
            print(f"已把上一版留下的 {old.name} 补为第 1 轮履历（{adopted['at'][:16]}）")
    point = judgment_egress(egress, warns, runs, measured=bool(args.verify))
    # 报警那一轮的产物不进订阅目录（理由见 artifact_dir()）；履历照旧追加。
    trusted_dir = Path(args.out)
    out_dir, quarantined = artifact_dir(trusted_dir, warns=warns, measured=bool(args.verify),
                                        force=args.allow_untrusted)
    try:
        trusted_rel = trusted_dir.relative_to(ROOT)
    except ValueError:
        trusted_rel = trusted_dir
    rep = hist.reputation(runs, current_egress=point) if not args.ignore_history else {}
    stale = hist.demote_hosts(rep) if not args.ignore_history else frozenset()
    fake = hist.fake_hosts(rep) if not args.ignore_history else frozenset()
    # L3 是逐条的结论（分片窗口动不动），单独合成一份，不走主机那一档
    rolls = hist.merge_rolls(runs, current_egress=point) if not args.ignore_history else {}
    rep_now = rep            # 落盘新那一轮之后会被换成最新的履历，用来判"该划掉谁"
    dropped = len(hist.untrusted_runs(runs, current_egress=point))
    # 来源 -> 现在的 priority：既给频道内排序用，也给 2.17 的「建议调到几」当基准
    src_prio = {**{s["id"]: s.get("priority", i + 1) for i, s in enumerate(sources)},
                LOCAL_ID: 0}   # 手工源是人工确认过出处的，同条件下优先

    if args.verify:
        for warn in warns:
            print(f"⚠️  {warn}")
        print()
    if rep and not args.verify:
        n_stuck = sum(1 for v in rolls.values() if v == "stuck")
        print(f"\n实测履历（{history_path.name}）：{len(runs)} 轮里 {len(rep)} 个主机有"
              f"「出口 {point}」的可信记录 → {len(stale)} 个整族失效主机往后压、"
              f"{len(fake)} 个「只出循环录像」的主机往后压、"
              + (f"{n_stuck} 条线路按 L3 让位、" if n_stuck else "")
              + f"{len(host_latency(rep))} 个按上一轮延迟补位"
              + (f"，另有 {dropped} 轮因测量点不对未采用" if dropped else "")
              + "；本轮未实测，这些判据顶上")
    channels, unmatched, excluded, dead, results, stale_hits = aggregate(
        entries, index, args.max_lines,
        verify=args.verify, timeout=args.timeout, workers=args.workers,
        max_per_host=args.max_per_host,
        skip_verify=[s["id"] for s in sources if not s.get("probe", True)],
        source_priority=src_prio,
        reach=reach,
        stale_hosts=stale,
        fake_hosts=fake,
        rolls=rolls,
        hist_ms=host_latency(rep),
    )

    present = {c.name for c in channels}
    empty = [(r.name, index.group_title(r.group)) for r in index.rules if r.name not in present]

    out_dir.mkdir(parents=True, exist_ok=True)
    epg = epg_urls[0] if epg_urls else ""

    full = format_m3u(channels, epg)
    (out_dir / "aptv.m3u").write_text(full, encoding="utf-8")

    hunan_titles = {index.group_title(gid) for gid in HUNAN_GROUPS}
    hunan = [c for c in channels if c.group_title in hunan_titles]
    hunan_text = format_m3u(hunan, epg)
    (out_dir / "hunan.m3u").write_text(hunan_text, encoding="utf-8")

    # 诊断用副产物：局域网订阅失败时用来区分「网络不通」和「App 抓台标/EPG 卡住」
    lean = load_lean_fn()
    if lean:
        (out_dir / "hunan-lean.m3u").write_text(lean(hunan_text), encoding="utf-8")
        (out_dir / "test.m3u").write_text(lean(hunan_text, limit=4), encoding="utf-8")

    # 可达范围拆分：运营商 IPTV 内网线路要在对应运营商的 IPTV 专网里才连得上，
    # 家庭 Wi-Fi 上表现为超时；电台地址则是上游挂在电视频道名下的冒充项。
    scope_stats = Counter(reach.scope(c.urls[0]) for c in channels)
    line_scope = Counter(reach.scope(u) for c in channels for u in c.urls)
    no_public = [c.name for c in channels
                 if all(reach.scope(u) != PUBLIC for u in c.urls)]
    # 第一线是循环录像的频道：电视默认就播这一条，必须点名。
    # 证据分三级，写清楚是哪一级看出来的：本轮实测的分片数最硬，L3 的「列表不动」次之，
    # 整族那种只是「上一轮这主机全是录像」，本轮没重测时才用。
    stuck_urls = {u for u, v in rolls.items() if v == "stuck"}
    fake_live = []
    for c in channels:
        first = c.urls[0]
        host = urlsplit(first).hostname or first[:20]
        r = results.get(first)
        if is_fake_live(r):
            fake_live.append(f"{c.name}（{host} "
                             + (f"{r.segments} 片循环）" if r.segments else "整段视频文件）"))
        elif r is None and first in stuck_urls:
            fake_live.append(f"{c.name}（{host} L3 验过：分片窗口不动）")
        elif r is None and host in fake:
            fake_live.append(f"{c.name}（{host} 上一轮整族只出录像，本轮未重测）")

    # 实测结果落盘：probe.json 是这一轮的快照（会被下一轮覆盖），
    # probe-history.jsonl 是它攒下来的履历 —— 离线生成、趋势判断都看后者。
    # 两边都记 egress + 体检警告，因为换一个测量点这些数字就不是同一个意思了。
    # src_of：这条地址是哪个上游塞进来的，2.17 起跟着履历一起攒，
    # 不然报告只能说出「这一族全灭」，说不出「所以该动 sources.yaml 里哪一行」。
    url_srcs: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        if e.source:
            url_srcs[e.url].add(e.source)
    src_of = {u: sorted(s) for u, s in url_srcs.items()}
    hosts = host_summary(results, reach, src_of) if args.verify else []
    if args.verify:
        at = datetime.now().astimezone().isoformat(timespec="seconds")
        (out_dir / "probe.json").write_text(json.dumps({
            "at": at,
            "egress": egress,
            "measurement_warnings": warns,
            "hosts": hosts,
            "lines": {u: {"ok": r.ok, "http": r.http, "ms": r.ms,
                          "segments": r.segments, "kind": r.kind, "error": r.error}
                      for u, r in results.items()},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        new_run = hist.append_run(history_path, {
            "at": at, "egress": egress, "warnings": warns, "hosts": hosts})
        runs = hist.load_history(history_path)
        # 判「该划掉谁」用最新这一轮，但报告里"本轮降档/补位了几个主机"说的是
        # 刚才 aggregate 真正用到的那份履历 —— 本轮实测过的线路根本不看历史，两者不能混。
        rep_now = hist.reputation(runs, current_egress=point)
        print(f"\n实测已记入 {history_path.name}："
              + ("新起一轮" if new_run else "与上一轮同一时段，已合并")
              + f"（累计 {len(runs)} 轮，判据出口：{point or '未知'}）")

    trend = hist.run_totals(runs, current_egress=point)
    # 主机那一层的「该划掉谁」摊到上游源那一层，再落成能抄进 sources.yaml 的一行（2.17）
    srs = hist.source_reputation(rep_now, min_runs=2)
    sugg = hist.priority_suggestions(srs, current=src_prio, min_runs=2)
    history_note = {
        "runs": len(runs),
        "used": len(trend),
        "dropped": len(hist.untrusted_runs(runs, current_egress=point)),
        "egress": point,
        "build_egress": egress if egress != point else "",
        "totals": trend,
        "blacklist": [asdict(r) for r in hist.blacklist(rep_now)],
        "sources": [asdict(x) for x in sorted(srs.values(), key=lambda x: (-x.lines, x.source))],
        "suggestions": [asdict(x) for x in sugg],
        "unattributed": hist.unattributed_hosts(rep_now),
        # 事后补记过来源的那几轮（scripts/backfill_srcs.py）：报告得说清这些出处不是测出来的。
        # 只数真被采用的轮 —— 报警那轮补没补记过，跟这张表没关系。
        "srcs_backfilled": sorted({str(r.get("at") or "")[:16] for r in runs
                                   if r.get("srcs_note") and hist.trustworthy(r, point)}),
        "never_measured": [str(s["id"]) for s in sources if not s.get("probe", True)],
        "demote": sorted(stale),
        "fake": sorted(fake),
        "rolls": {"checked": len(rolls),
                  "stuck": sum(1 for v in rolls.values() if v == "stuck")},
        "latency_hosts": len(host_latency(rep)),
        "stale_first_lines": stale_hits,
        "verified": bool(args.verify),
    } if runs or args.verify else None

    verify_note = (f"--verify 实测剔除失效 {dead} 条" if args.verify else
                   "本次未做线路实测，列表里的线路可用性以 Apple TV 实际播放为准")
    if quarantined:
        verify_note += (f"。⚠️ 本轮体检报警（出口 {egress or '未取到'}），被剔的那些多半是假阴性，"
                        f"所以这份表只落在 {UNTRUSTED}/ 里当排查用，"
                        f"{trusted_rel} 那张仍是上一轮可信版本")
    report = format_report(
        sources=[f"{s['id']} ← {s['target']}" for s in sources] + (
            [f"{LOCAL_ID} ← {LOCAL_SOURCES_FILE.relative_to(ROOT)}"
             f"（手工核对 {len(local_lines)} 条）"] if local_lines else []),
        total_entries=len(entries),
        channels=channels,
        unmatched=unmatched,
        defined_but_empty=empty,
        epg_url=epg,
        verify_note=verify_note,
        line_scope=line_scope,
        no_public=no_public,
        fake_live=fake_live,
        hosts=hosts,
        history=history_note,
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")

    print(f"\n输出到 {out_dir}")
    if quarantined:
        print(f"  ⚠️ 体检报警的这一轮不碰订阅目录：上面这些文件写在 {UNTRUSTED}/ 里，"
              f"{trusted_rel} 保持上一轮可信版本 —— 局域网服务发的还是那张表。")
        print("  要给电视换表：关掉代理客户端的 TUN/系统代理再跑一次 build --verify"
              "（明知故犯就加 --allow-untrusted）")
    print(f"  aptv.m3u  : {len(channels)} 个频道 / {sum(len(c.urls) for c in channels)} 条线路")
    print(f"  hunan.m3u : {len(hunan)} 个频道 / {sum(len(c.urls) for c in hunan)} 条线路")
    if lean:
        print("  诊断用副产物：hunan-lean.m3u（无台标无 EPG）、test.m3u（前 4 个台）")
    print(f"  可达范围：公网 {line_scope[PUBLIC]} 条 / 运营商内网 {line_scope[INTRANET]} 条 / "
          f"电台冒充 {line_scope[AUDIO]} 条；第一线是公网线路的 {scope_stats[PUBLIC]}/{len(channels)} 个频道")
    if no_public:
        print(f"  ⚠️ 一条公网线路都没有的频道 {len(no_public)} 个（Wi-Fi 上大概率播不动）："
              + "、".join(no_public))
    if fake_live:
        print(f"  ⚠️ 第一线是循环录像的频道 {len(fake_live)} 个（有画但不是直播）："
              + "、".join(fake_live))
    if hosts:
        print(f"  实测出口：{egress or '未取到'}（详情见 {out_dir / 'probe.json'}）")
        bad = [h for h in hosts if h["ok"] < h["total"]]
        for h in bad[:8]:
            print(f"    ⚠️ {h['host']:<34} 可用 {h['ok']}/{h['total']}"
                  + ("  ← 整族失效，这个主机提供的公网线路等于不存在" if not h["ok"] else ""))
        if len(bad) > 8:
            print(f"    …另有 {len(bad) - 8} 个主机有失败线路")
        alive = [h for h in hosts if h["ok"] == h["total"]]
        print(f"    其余 {len(alive)} 个主机全通（合计 {sum(h['total'] for h in alive)} 条），"
              f"最快 {min((h['best_ms'] for h in alive), default=0)}ms")
    if history_note and history_note["runs"] and not args.verify:
        h = history_note
        print(f"  实测履历：{h['runs']} 轮（采用 {h['used']} 轮，判据出口 {h['egress'] or '未知'}）"
              + (f"，{h['dropped']} 轮因测量点不对未采用" if h["dropped"] else "")
              + f"；据此往后压 {len(h['demote'])} 个整族失效主机"
              + (f"、{len(h['fake'])} 个只出录像的主机" if h.get("fake") else "")
              + f"、补位 {h['latency_hosts']} 个"
              + (f"，第一线仍落在已失效主机上的台 {h['stale_first_lines']} 个"
                 if h["stale_first_lines"] else ""))
        if h["blacklist"]:
            print("    ⚠️ 连续两轮以上从没通过过的："
                  + "、".join(f"{r['host']}（{r['runs']} 轮全灭）" for r in h["blacklist"][:6])
                  + " —— 它们贡献的「公网线路」等于不存在")
        moves = [g for g in h["suggestions"]
                 if g["to_prio"] != g["from_prio"] or g["enabled"] is False]
        if h["sources"]:
            print(f"  源级趋势：{len(h['sources'])} 个源在可信轮次里留了记录"
                  + (f"，{len(moves)} 个够得上动手的标准：" + "、".join(
                        f"`{g['source']}` "
                        + ("整源关掉" if g["enabled"] is False
                           else f"{g['from_prio']}→{g['to_prio']}")
                        for g in moves[:4]) if moves else "，没有一个够得上动手的标准"))
            print("    能直接抄进 `config/sources.yaml` 的那几行在 report.md"
                  " 的「按上游源摊开」那一节 —— 代码不自己改这个文件")
        elif h["unattributed"]:
            print(f"  源级趋势：还摊不开 —— 履历里 {h['unattributed']} 个主机族没记来源"
                  "（2.17 之前的轮次），在家里补跑一次 build --verify 就齐了")
    print(f"  丢弃：黑名单 {excluded} 条，未匹配 {sum(unmatched.values())} 条"
          + (f"，实测失效 {dead} 条" if args.verify else ""))
    if not args.verify:
        print("  注意：本次未实测"
              + ("，已按实测履历排序（只覆盖被测过的主机，新线路按未知处理）；"
                 "但离线生成不删失效线路，第二三条备选里仍会混着已知连不上的。" if stale else
                 "，产物里会混着已知失效的线路，而且会把上一轮 `--verify` 生成的表覆盖掉。")
              + "要给电视订阅前，建议补跑一次 `build --verify`。")
    if empty:
        print(f"  ⚠️ 配置里有但没匹配到线路的频道 {len(empty)} 个：" + "、".join(n for n, _ in empty))
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"build"}:
        print(__doc__)
        return 0
    return cmd_build(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
