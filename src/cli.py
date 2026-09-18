"""命令行入口。

用法：

    python -m src.cli build                  # 用 data/cache 里的上游缓存离线生成
    python -m src.cli build --fresh          # 联网抓 config/sources.yaml 里启用的源
    python -m src.cli build --verify         # 生成前实测线路（probe:false 的源跳过）
    python -m src.cli build --source <url或文件>   # 临时换上游，忽略 sources.yaml

产物在 data/output/：aptv.m3u（全量）、hunan.m3u（只有湖南本地）、report.md。

注意：联网抓取与 --verify 实测都从本机出口出去。这台开发机的出口被隧道接管，
对国内运营商内网类地址会给出假阴性，测出来的可用率只能当参考。
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import urllib.request
from collections import Counter, defaultdict
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

from src.check.prober import ProbeResult, probe_many  # noqa: E402
from src.match.matcher import load_index  # noqa: E402
from src.match.normalize import quality_hint  # noqa: E402
from src.output.writer import OutputChannel, format_m3u, format_report  # noqa: E402
from src.parse.m3u import Entry, parse_m3u  # noqa: E402

SOURCES_FILE = ROOT / "config" / "sources.yaml"
CACHE_DIR = ROOT / "data" / "cache"
HUNAN_GROUPS = ("hunan_local", "changsha", "shizhou", "jinying")
_RANK = {"4K": 4, "FHD": 3, "HD": 2, "SD": 1, "": 0}

# 带签名/鉴权参数的私有流：URL 里绑死了抓取方的 IP、账号哈希和有效期，
# 别人拿到一定播不了（咪咕那类），而且属于计划书划定的红线（不盗链需鉴权私有流），
# 一律不进订阅列表。
_AUTH_URL = re.compile(
    r"SecurityKey=|ddCalcu=|msisdn=|assertID=|auth_key=|wsTime=|txypb=|"
    r"token=|[?&]u=[0-9a-f]{16,}", re.I)


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
              source_priority: dict[str, int] | None = None):
    """归位 + 合并多线路 + 同源收敛 + 排序 + 截断（可选实测过滤）。

    max_per_host 用来治「一个频道的 5 条线路其实全来自同一个失效主机」——
    实测湖南线路里 64% 来自 stream1.freetv.fun 这一个已不可用的域名。

    skip_verify 里的来源 id 是「开发机测不准」的运营商内网源，实测时原样保留。

    source_priority 决定同一频道里线路的先后：APTV 默认播第一条，所以
    家里宽带同运营商的源必须排在最前，其次才是清晰度。
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
            key=lambda e: (prio.get(e.source, 99),
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
    return channels, unmatched, excluded, dead


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
    if not entries:
        print("没有解析到任何条目，检查网络或上游地址。", file=sys.stderr)
        return 1

    index = load_index(args.config)
    channels, unmatched, excluded, dead = aggregate(
        entries, index, args.max_lines,
        verify=args.verify, timeout=args.timeout, workers=args.workers,
        max_per_host=args.max_per_host,
        skip_verify=[s["id"] for s in sources if not s.get("probe", True)],
        source_priority={s["id"]: s.get("priority", i + 1) for i, s in enumerate(sources)},
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

    report = format_report(
        sources=[f"{s['id']} ← {s['target']}" for s in sources],
        total_entries=len(entries),
        channels=channels,
        unmatched=unmatched,
        defined_but_empty=empty,
        epg_url=epg,
        verify_note=(f"--verify 实测剔除失效 {dead} 条" if args.verify else
                     "本次未做线路实测，列表里的线路可用性以 Apple TV 实际播放为准"),
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")

    print(f"\n输出到 {out_dir}")
    print(f"  aptv.m3u  : {len(channels)} 个频道 / {sum(len(c.urls) for c in channels)} 条线路")
    print(f"  hunan.m3u : {len(hunan)} 个频道 / {sum(len(c.urls) for c in hunan)} 条线路")
    if lean:
        print("  诊断用副产物：hunan-lean.m3u（无台标无 EPG）、test.m3u（前 4 个台）")
    print(f"  丢弃：黑名单 {excluded} 条，未匹配 {sum(unmatched.values())} 条"
          + (f"，实测失效 {dead} 条" if args.verify else ""))
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
