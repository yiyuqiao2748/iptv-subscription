"""生成「试播包」：每个流主机族挑一条代表线路，编号 ①②③…

这张表回答的是「电脑测出来的通，电视上真出画吗」。

前提变了要说明一下：早先两台开发机都挂着代理客户端，TUN 抢走 DNS 和路由，
本机实测全是假数字，唯一可信的测量设备是电视。2026-09-21 把 TUN 关掉后
出口变成家里联通骨干，和 Apple TV 同一张网，电脑实测已经能当判据了。
所以试播包不再负责「哪些主机族连得上」—— 那个问题 probe.json 已经答完，
这里只挑**实测通过**的主机族，让电视确认剩下的那一层：
L1/L2 通了但码率、延迟、缓冲够不够，跨洋中转能不能撑住直播。
整族失效的主机（比如 stream1.freetv.fun 0/17）直接不放进表里，不浪费遥控器的点击。

    python scripts/probe_pack.py                 # 从 aptv.m3u 生成 probe-pack.m3u
    python scripts/probe_pack.py --top 12        # 只挑线路数最多的 12 个主机族
    python scripts/probe_pack.py --keep-dead     # 连实测全灭的族也放进来
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"

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


# 不管线路多少都要测的主机族 —— 都是只有 1~2 条线路、按线路数排序会被切掉的关键对照组：
#   myqcloud：央视内容的腾讯云分发、URL 不带鉴权参数，能动就说明电视出公网没问题
#             （2026-09-21 它自己实测失效了，已不进订阅表，这里就自然留不下）
#   mgtv：湖南广电官方公网流，190ms。这台要是电视上能稳播，
#         P5 的方向就定了 —— 去把湖南各台的官方公网分发一个个挖出来，而不是找中转。
#   hnxttv：湘潭广电官方公网流，47ms，而且是这轮第一个靠手工源补进来的台。
#           它和 mgtv 一起构成「官方分发」这一档的对照组：国内、快、真直播。
FORCE = ("cctvtxyh5c.liveplay.myqcloud.com", "hlsal-ldvt.qing.mgtv.com",
         "live.hnxttv.com")


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else url


def base_of(host: str) -> str:
    """去掉端口和中括号，让 `58.20.64.92:9999` 和 probe.json 里的 `58.20.64.92` 对得上。"""
    return host.split(":")[0].strip("[]").lower()


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


def read_pairs(path: Path) -> list[tuple[str, str]]:
    """从 m3u 里取出 (频道名, 流地址) 序列。"""
    out: list[tuple[str, str]] = []
    name = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            name = line.split(",", 1)[1] if "," in line else ""
        elif name and line.startswith("http"):
            out.append((name, line))
            name = None
    return out


def build(pairs: list[tuple[str, str]], top: int,
          stats: dict[str, dict] | None = None, keep_dead: bool = False,
          ) -> tuple[str, list[tuple[str, str, str, str]], list[str]]:
    """按主机族挑代表线路。

    FORCE 里的族只有一两条线路，按线路数取 top 会被切掉，所以取完再补一次。
    比对要用去端口的主机名 —— 湘潭那条是 `live.hnxttv.com:9601`，
    拿 `host in FORCE` 直接比会漏，试播包就少了一个对照组。

    >>> pairs = ([("湘潭新闻综合", "http://live.hnxttv.com:9601/live/x.m3u8"),
    ...           ("湖南卫视", "http://hlsal-ldvt.qing.mgtv.com/a.m3u8")]
    ...          + [("CCTV-1综合", f"http://1.1.1.1:80/{i}.m3u8") for i in range(20)])
    >>> _, legend, _ = build(pairs, top=1)
    >>> sorted(l[2] for l in legend)
    ['CCTV-1综合', '湖南卫视', '湘潭新闻综合']
    """
    by_host: dict[str, list[tuple[str, str]]] = {}
    for name, url in pairs:
        by_host.setdefault(host_of(url), []).append((name, url))

    ordered = sorted(by_host.items(),
                     key=lambda kv: (-len(kv[1]), family_label(kv[0])))
    if top:
        ordered = ordered[:top]
    # 基准主机族哪怕只有 1 条线路也要在表里
    picked = {h for h, _ in ordered}
    ordered += [(h, items) for h, items in by_host.items()
                if base_of(h) in FORCE and h not in picked]

    # 电脑已经实测过的主机族：整族连不上的不必再让电视点一次
    stats = stats or {}
    skipped: list[str] = []
    if stats and not keep_dead:
        kept = []
        for host, items in ordered:
            st = stats.get(base_of(host))
            if st and st["total"] and not st["ok"] and base_of(host) not in FORCE:
                skipped.append(f"{family_label(host)}（{base_of(host)} 实测 0/{st['total']}）")
                continue
            kept.append((host, items))
        ordered = kept

    lines = ["#EXTM3U"]
    legend: list[tuple[str, str, str, str]] = []
    for i, (host, items) in enumerate(ordered):
        mark = CIRCLED[i] if i < len(CIRCLED) else f"#{i + 1}"
        pref, url = next(((n, u) for n, u in items
                          if any(p in n for p in PREFERRED)), items[0])
        label = f"{mark} {family_label(host)}｜{pref}"
        st = stats.get(base_of(host))
        note = f"{st['ok']}/{st['total']} 通" if st else "未实测"
        if st and st.get("ms"):
            note += f"·{st['ms']}ms"
        lines.append(f'#EXTINF:-1 tvg-name="{pref}" '
                     f'group-title="🔍 试播包",{label}')
        lines.append(url)
        legend.append((mark, f"{family_label(host)}（{host}，{len(items)} 条）", pref, note))

    return "\n".join(lines) + "\n", legend, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="生成试播包")
    ap.add_argument("--in", dest="src", default="aptv.m3u")
    ap.add_argument("--out", dest="dst", default="probe-pack.m3u")
    ap.add_argument("--top", type=int, default=14, help="挑线路最多的 N 个主机族，0=全部")
    ap.add_argument("--keep-dead", action="store_true",
                    help="连实测整族失效的主机族也放进来（默认剔掉，省遥控器点击）")
    args = ap.parse_args()

    src = OUT_DIR / args.src
    if not src.exists():
        print(f"找不到 {src}，先跑：{sys.executable} -m src.cli build", file=sys.stderr)
        return 1

    stats = load_stats()
    text, legend, skipped = build(read_pairs(src), args.top, stats, args.keep_dead)
    (OUT_DIR / args.dst).write_text(text, encoding="utf-8")

    print(f"已生成 data/output/{args.dst}（{len(legend)} 条，逐个点开试）"
          + ("" if stats else "  ← 没有 data/output/probe.json，全部按未实测处理"))
    if skipped:
        print(f"\n已剔除 {len(skipped)} 个整族失效的主机族（电脑实测连不上，不必让电视再试）：")
        for s in skipped:
            print(f"  - {s}")
        print("  要看它们：--keep-dead")
    print()
    print(f"{'编号':<4} {'主机族':<38} {'电脑实测':<16} 代表频道")
    for mark, fam, ch, note in legend:
        print(f"{mark:<5} {fam:<40} {note:<16} {ch}")
    print("\n判读：这一列「通」只代表电脑直连拿到了播放列表和分片。"
          "电视上黑屏/卡住 = 这台机房到家的路太长或码率太高，"
          "那种主机族要在 config/reachability.yaml 里单独降一档。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
