"""生成「试播包」：每个流主机族挑一条代表线路，编号 ①②③…

用途：本机 Windows 上有 VPN/TUN 抢路由，测出来的可达性全是假数字，
唯一可信的测量设备就是电视本身。让它逐个点开这张表，把能动的编号报回来，
就知道哪些主机族在家里这张网里根本连不上，从而决定留哪些源。

    python scripts/probe_pack.py                 # 从 aptv.m3u 生成 probe-pack.m3u
    python scripts/probe_pack.py --top 12        # 只挑线路数最多的 12 个主机族
"""

from __future__ import annotations

import argparse
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
    "stream1.freetv.fun": "freetv公网CDN",
    "php.jdshipin.com": "京东云公网中转",
    "live.264788.xyz": "264788公网中转",
    "gslbmgsplive.miguvideo.com": "咪咕公网",
    "ottrrs.hl.chinamobile.com": "黑龙江移动",
    "rrs01.hw.gmcc.net": "移动全球 multicast 网关",
    "cctvtxyh5c.liveplay.myqcloud.com": "★腾讯云CDN·公网基准",
    "hls-qhmh.lanzhousobey.cn": "兰州公网",
    "iptv.huuc.edu.cn": "高校网源",
    "iptv.666230.xyz": "666230中转",
    "zby.130519.xyz": "130519中转",
    "120.76.248.139": "阿里云公网",
}

# 优先挑这些台做代表：认得出来、也确实是用户想看的
PREFERRED = ("湖南卫视", "湖南经视", "长沙新闻综合", "CCTV-1", "CCTV1",
             "中央电视", "湖南卫视-高清", "CCTV-4", "北京卫视")


# 不管线路多少都要测的主机族：这个是「公网到底能不能播」的基准。
# myqcloud 是央视内容的腾讯云分发、URL 不带鉴权参数，能动就说明电视出公网没问题；
# 它只有 1 条线路，按线路数排序会被切掉，所以强制留下。
FORCE = ("cctvtxyh5c.liveplay.myqcloud.com",)


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else url


def family_label(host: str) -> str:
    base = host.split(":")[0].strip("[]")
    return FAMILY.get(base, host)


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


def build(pairs: list[tuple[str, str]], top: int) -> tuple[str, list[tuple[str, str, str]]]:
    by_host: dict[str, list[tuple[str, str]]] = {}
    for name, url in pairs:
        by_host.setdefault(host_of(url), []).append((name, url))

    ordered = sorted(by_host.items(),
                     key=lambda kv: (-len(kv[1]), family_label(kv[0])))
    if top:
        ordered = ordered[:top]
    # 基准主机族哪怕只有 1 条线路也要在表里
    picked = {h for h, _ in ordered}
    ordered += [(h, by_host[h]) for h in FORCE
                if h in by_host and h not in picked]

    lines = ["#EXTM3U"]
    legend: list[tuple[str, str, str]] = []
    for i, (host, items) in enumerate(ordered):
        mark = CIRCLED[i] if i < len(CIRCLED) else f"#{i + 1}"
        pref, url = next(((n, u) for n, u in items
                          if any(p in n for p in PREFERRED)), items[0])
        label = f"{mark} {family_label(host)}｜{pref}"
        lines.append(f'#EXTINF:-1 tvg-name="{pref}" '
                     f'group-title="🔍 试播包",{label}')
        lines.append(url)
        legend.append((mark, f"{family_label(host)}（{host}，{len(items)} 条）", pref))

    return "\n".join(lines) + "\n", legend


def main() -> int:
    ap = argparse.ArgumentParser(description="生成试播包")
    ap.add_argument("--in", dest="src", default="aptv.m3u")
    ap.add_argument("--out", dest="dst", default="probe-pack.m3u")
    ap.add_argument("--top", type=int, default=14, help="挑线路最多的 N 个主机族，0=全部")
    args = ap.parse_args()

    src = OUT_DIR / args.src
    if not src.exists():
        print(f"找不到 {src}，先跑：{sys.executable} -m src.cli build", file=sys.stderr)
        return 1

    text, legend = build(read_pairs(src), args.top)
    (OUT_DIR / args.dst).write_text(text, encoding="utf-8")

    print(f"已生成 data/output/{args.dst}（{len(legend)} 条，逐个点开试）\n")
    print(f"{'编号':<4} {'主机族':<38} 代表频道")
    for mark, fam, ch in legend:
        print(f"{mark:<5} {fam:<40} {ch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
