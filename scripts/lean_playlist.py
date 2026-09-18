"""把订阅表压成「裸表」：去掉台标和 EPG 声明，只留频道名 + 流地址。

用途只有一个：APTV 添加订阅失败时，判断是不是 App 在导入阶段去抓
x-tvg-url 的节目单或几十张台标图片超时导致的，而不是网络不通。

    python scripts/lean_playlist.py                    # 生成 data/output/hunan-lean.m3u
    python scripts/lean_playlist.py --in aptv.m3u --limit 5
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"

_ATTR_LOGO = re.compile(r'\s+tvg-logo="[^"]*"')
_ATTR_EPG = re.compile(r'^#EXTM3U\s+x-tvg-url="[^"]*"')


def lean(text: str, *, limit: int = 0) -> str:
    """去掉台标与 EPG 声明；limit>0 时只保留前 N 个频道（含其全部线路）。

    >>> out = lean('#EXTM3U x-tvg-url="http://a/epg.gz"\\n'
    ...            '#EXTINF:-1 tvg-logo="http://l.png" group-title="g",湖南卫视\\n'
    ...            'http://s/1.m3u8\\n', limit=1)
    >>> '#EXTM3U\\n' in out and 'tvg-logo' not in out and 'x-tvg-url' not in out
    True
    """
    kept: list[str] = []
    seen: list[str] = []
    skip = False                       # 当前这条线路要不要整条丢掉
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            kept.append("#EXTM3U")
            continue
        if line.startswith("#EXTINF"):
            name = line.split(",", 1)[1] if "," in line else ""
            if limit and name not in seen:
                if len(seen) >= limit:
                    skip = True        # 已经攒够 N 个台，新台整条（含地址行）不要
                    continue
                seen.append(name)
            skip = False
            kept.append(_ATTR_LOGO.sub("", line))
            continue
        if line.startswith("#"):
            continue                   # 其它注释行（#EXTGRP 等）一并丢掉
        if skip:
            continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成不带台标/EPG 的裸订阅表")
    ap.add_argument("--in", dest="src", default="hunan.m3u")
    ap.add_argument("--out", dest="dst", default="")
    ap.add_argument("--limit", type=int, default=0, help="只保留前 N 个频道，0=全部")
    args = ap.parse_args()

    src = OUT_DIR / args.src
    if not src.exists():
        print(f"找不到 {src}，先跑：{sys.executable} -m src.cli build", file=sys.stderr)
        return 1
    dst = OUT_DIR / (args.dst or src.stem + "-lean.m3u")
    dst.write_text(lean(src.read_text(encoding="utf-8"), limit=args.limit),
                   encoding="utf-8")
    n_ch = sum(1 for l in dst.read_text(encoding="utf-8").splitlines()
               if l.startswith("#EXTINF"))
    print(f"已生成 {dst}（{n_ch} 条线路，无台标、无 EPG 声明）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
