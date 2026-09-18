"""开发期工具：摸清上游 m3u 的真实结构，为 config/channels.yaml 提供依据。

用法：
    python scripts/analyze_upstream.py [m3u路径或URL ...]

默认分析 调研样本/iptv-api_gd_result.m3u。
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows 控制台默认 GBK，打印分组名里的 emoji 会直接抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.parse.m3u import parse_m3u  # noqa: E402

DEFAULT = ROOT / "调研样本" / "iptv-api_gd_result.m3u"
KEYWORDS = ("湖南", "长沙", "金鹰", "株洲", "湘潭", "岳阳", "衡阳", "常德",
            "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "邵阳", "湘西")


def load(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        import urllib.request

        req = urllib.request.Request(path_or_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    return Path(path_or_url).read_text(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    targets = argv or [str(DEFAULT)]
    for target in targets:
        text = load(target)
        pl = parse_m3u(text, source=Path(target).stem)
        print(f"\n{'=' * 60}\n{target}\n条目 {len(pl)} 条，跳过 {pl.skipped} 行，EPG={pl.x_tvg_url or '无'}")

        groups = Counter(e.group for e in pl.entries)
        print(f"\n--- 分组（共 {len(groups)} 个）---")
        for g, n in groups.most_common():
            print(f"  {n:5d}  {g or '(无分组)'}")

        by_group: dict[str, set[str]] = defaultdict(set)
        for e in pl.entries:
            by_group[e.group].add(e.name)

        print("\n--- 含湖南地名的条目：名称 -> 所属分组 ---")
        hits: dict[str, list[str]] = defaultdict(list)
        for name, grp in [(e.name, e.group) for e in pl.entries]:
            if any(k in name for k in KEYWORDS):
                hits[name].append(grp)
        for name in sorted(hits):
            print(f"  {name:<16} {sorted(set(hits[name]))}")

        print("\n--- 央视/卫视频道组内的名称（前 40）---")
        for g in by_group:
            if "央视" in g or "卫视" in g:
                names = sorted(by_group[g])
                print(f"  [{g}] 共 {len(names)} 个频道名：")
                print("    " + "、".join(names[:40]))

        urls = Counter(e.url for e in pl.entries)
        print(f"\n--- 重复 url 数：{sum(1 for c in urls.values() if c > 1)}（同一条线路被多个频道名复用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
