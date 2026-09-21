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

注意：联网抓取与 --verify 实测都从本机出口出去，所以测量点是谁必须先说清楚。
代理客户端的 TUN 一开，DNS 就被换成 fake-IP、出口跑到境外机房，对国内运营商类地址
全是假阴性（计划书 2.8）。跑 --verify 前会先做体检并把警告打在屏幕上，
出口身份和逐条结果一起写进 data/output/probe.json。
2026-09-21 起：TUN 关掉后本机出口就是家里的联通宽带，与 Apple TV 同一张网，
这时的实测数字可以直接当判据。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
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
              reach: Reachability):
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
    """
    skip_verify = set(skip_verify)
    prio = source_priority or {}
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
    channels: list[OutputChannel] = []
    for (group, name), b in buckets.items():
        ordered = sorted(
            b["lines"],
            key=lambda e: (reach.rank(e.url), is_fake_live(results.get(e.url)),
                           latency_tier(results.get(e.url)),
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
    return channels, unmatched, excluded, dead, results


def host_summary(results: dict[str, ProbeResult], reach: Reachability) -> list[dict]:
    """把逐条实测按主机汇总：回答「哪个主机族在家里这张网里是死的」。

    这一步是实测真正的产出。只报「可用 215/330」没法定下一步 ——
    2026-09-21 那次汇总才看清：美国中转族 128/131 全活，
    而 stream1.freetv.fun 0/17 整族失效（DNS 已被换到一个不服务的美图 IP），
    于是不用电视实测就能断定「湖南经视等台的公网线路其实不存在」。

    返回按（可达范围、失效数倒序）排好的行：host/scope/total/ok/best_ms。
    """
    agg: dict[str, dict] = {}
    for url, r in results.items():
        host = urlsplit(url).hostname or url[:16]
        a = agg.setdefault(host, {"host": host, "scope": reach.scope(url),
                                  "total": 0, "ok": 0, "best_ms": 0})
        a["total"] += 1
        if r.ok:
            a["ok"] += 1
            a["best_ms"] = r.ms if not a["best_ms"] else min(a["best_ms"], r.ms)
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
    if args.verify:
        for warn in measurement_warnings():
            print(f"⚠️  {warn}")
        print()
    channels, unmatched, excluded, dead, results = aggregate(
        entries, index, args.max_lines,
        verify=args.verify, timeout=args.timeout, workers=args.workers,
        max_per_host=args.max_per_host,
        skip_verify=[s["id"] for s in sources if not s.get("probe", True)],
        source_priority={**{s["id"]: s.get("priority", i + 1) for i, s in enumerate(sources)},
                         LOCAL_ID: 0},   # 手工源是人工确认过出处的，同条件下优先
        reach=reach,
    )

    present = {c.name for c in channels}
    empty = [(r.name, index.group_title(r.group)) for r in index.rules if r.name not in present]

    out_dir = Path(args.out)
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
    # segments=0 的那种是「响应体整个就是个 MP4 文件」，同样不是直播。
    fake_live = []
    for c in channels:
        r = results.get(c.urls[0])
        if not is_fake_live(r):
            continue
        host = urlsplit(c.urls[0]).hostname or c.urls[0][:20]
        fake_live.append(f"{c.name}（{host} "
                         + (f"{r.segments} 片循环）" if r.segments else "整段视频文件）"))

    # 实测结果落盘：probe.json 是 P2 黑名单/历史趋势的原始数据，
    # 也是试播包（scripts/probe_pack.py）判「这个主机族值不值得让电视点一下」的依据。
    hosts = host_summary(results, reach) if args.verify else []
    if args.verify:
        (out_dir / "probe.json").write_text(json.dumps({
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "egress": egress_hint(),
            "measurement_warnings": measurement_warnings(),
            "hosts": hosts,
            "lines": {u: {"ok": r.ok, "http": r.http, "ms": r.ms,
                          "segments": r.segments, "kind": r.kind, "error": r.error}
                      for u, r in results.items()},
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    report = format_report(
        sources=[f"{s['id']} ← {s['target']}" for s in sources] + (
            [f"{LOCAL_ID} ← {LOCAL_SOURCES_FILE.relative_to(ROOT)}"
             f"（手工核对 {len(local_lines)} 条）"] if local_lines else []),
        total_entries=len(entries),
        channels=channels,
        unmatched=unmatched,
        defined_but_empty=empty,
        epg_url=epg,
        verify_note=(f"--verify 实测剔除失效 {dead} 条" if args.verify else
                     "本次未做线路实测，列表里的线路可用性以 Apple TV 实际播放为准"),
        line_scope=line_scope,
        no_public=no_public,
        fake_live=fake_live,
        hosts=hosts,
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")

    print(f"\n输出到 {out_dir}")
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
        print(f"  实测出口：{egress_hint() or '未取到'}（详情见 data/output/probe.json）")
        bad = [h for h in hosts if h["ok"] < h["total"]]
        for h in bad[:8]:
            print(f"    ⚠️ {h['host']:<34} 可用 {h['ok']}/{h['total']}"
                  + ("  ← 整族失效，这个主机提供的公网线路等于不存在" if not h["ok"] else ""))
        if len(bad) > 8:
            print(f"    …另有 {len(bad) - 8} 个主机有失败线路")
        alive = [h for h in hosts if h["ok"] == h["total"]]
        print(f"    其余 {len(alive)} 个主机全通（合计 {sum(h['total'] for h in alive)} 条），"
              f"最快 {min((h['best_ms'] for h in alive), default=0)}ms")
    print(f"  丢弃：黑名单 {excluded} 条，未匹配 {sum(unmatched.values())} 条"
          + (f"，实测失效 {dead} 条" if args.verify else ""))
    if not args.verify:
        print("  注意：本次未实测，产物里会混着已知失效的线路，而且会把上一轮"
              " `--verify` 生成的表覆盖掉。要给电视订阅前，建议补跑一次 `build --verify`。")
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
