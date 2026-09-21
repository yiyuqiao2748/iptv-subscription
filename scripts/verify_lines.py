"""验收工具：实测 m3u 里每条线路是否真能播。

三级检测，按需取用（L3 要等，默认关）：
  L1 连通：HTTP 状态码 + 首字节耗时
  L2 结构：响应体是合法 m3u8（含 #EXTM3U）且至少有一个分片/子列表，
          并分清真直播 / 多码率索引 / 循环录像（classify 的 kind）
  L3 滚动：隔 N 秒重取，分片窗口向前推进才算真在直播（--roll 20）

用法：
    python scripts/verify_lines.py data/output/hunan.m3u
    python scripts/verify_lines.py data/output/aptv.m3u --sample 40
    python scripts/verify_lines.py data/output/hunan.m3u --roll 20   # 只看每频道第一线
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.check.prober import is_fake_live, l3_roll, probe_many  # noqa: E402
from src.parse.m3u import parse_m3u  # noqa: E402

_VERDICT = {"rolling": "✅ 真直播", "stuck": "❌ 列表不动（残留/循环）",
            "vod": "❌ 录播（ENDLIST）", "master": "— 索引，未判定",
            "dead": "❌ 取不到"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("m3u")
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--sample", type=int, default=0, help="只测前 N 条线路，0 表示全测")
    ap.add_argument("--via-proxy", action="store_true",
                    help="允许走系统代理（默认直连，模拟 Apple TV 的真实环境）")
    ap.add_argument("--roll", type=int, default=0, metavar="SEC",
                    help="L3：对每个频道的第一线隔 SEC 秒重取，比对分片窗口是否滚动")
    args = ap.parse_args(argv)

    entries = parse_m3u(Path(args.m3u).read_text(encoding="utf-8"), source="out").entries
    if args.sample:
        entries = entries[: args.sample]

    print(f"检测 {len(entries)} 条线路（并发 {args.workers}，超时 {args.timeout}s，"
          f"{'经代理' if args.via_proxy else '直连'}）...\n")
    results = probe_many([e.url for e in entries], args.timeout, args.workers,
                         direct=not args.via_proxy)

    by_channel: dict[str, list[tuple]] = {}
    for e, r in zip(entries, results):
        by_channel.setdefault(e.name, []).append((e, r))

    total_ok = 0
    for name, items in by_channel.items():
        oks = [r for _, r in items if r.ok]
        total_ok += len(oks)
        best = min((r.ms for r in oks), default=-1)
        flag = "✅" if oks else "❌"
        detail = "、".join(
            f"{r.ms}ms/{r.segments}片/{r.kind or '?'}" if r.ok else f"✗{r.http or r.error}"
            for _, r in items
        )
        # 第一线是循环录像时单独标出来：电视播的就是这一条
        fake = " ⚠️假直播" if is_fake_live(items[0][1]) else ""
        print(f"  {flag} {name:<12} 可用 {len(oks)}/{len(items)}  最快 {best}ms{fake}   [{detail}]")

    n = len(entries)
    print(f"\n合计：{total_ok}/{n} 条线路可用（{total_ok / max(n, 1):.0%}），"
          f"覆盖 {sum(1 for items in by_channel.values() if any(r.ok for _, r in items))}"
          f"/{len(by_channel)} 个频道")

    if args.roll:
        firsts = [(name, items[0][0].url) for name, items in by_channel.items()
                  if items[0][1].ok]
        print(f"\nL3 滚动检测：{len(firsts)} 个频道的第一线，间隔 {args.roll}s 重取比对分片窗口")
        with ThreadPoolExecutor(max_workers=max(len(firsts), 1)) as pool:
            verdicts = list(pool.map(
                lambda t: (t[0], l3_roll(t[1], args.roll, args.timeout,
                                         not args.via_proxy)),
                firsts))
        for name, v in verdicts:
            print(f"  {_VERDICT.get(v['verdict'], v['verdict']):<22} {name}"
                  + (f"  ({v['error']})" if v["error"] else ""))
        rolling = sum(1 for _, v in verdicts if v["verdict"] == "rolling")
        print(f"\n  真直播 {rolling}/{len(verdicts)}；"
              "stuck 的那批要盯 —— L2 全过但列表不动，多半是循环录像或早已停推。")
        return 0 if rolling / max(len(verdicts), 1) >= 0.5 else 1
    return 0 if total_ok / max(n, 1) >= 0.5 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
