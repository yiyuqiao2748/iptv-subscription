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
    python scripts/verify_lines.py data/output/aptv.m3u --roll 20 --to-history
        ↑ 把 L3 的结论回填进实测履历，下次离线生成就不再让那批录像台占第一线。
          L3 每条要多等一个间隔，进不了 `build --verify` 的主流程，所以单独跑、单独存。
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.check import history as hist  # noqa: E402
from src.check.env import egress_hint, measurement_warnings  # noqa: E402
from src.check.prober import is_fake_live, l3_roll, probe_many  # noqa: E402
from src.parse.m3u import parse_m3u  # noqa: E402

_VERDICT = {"rolling": "✅ 真直播", "stuck": "❌ 列表不动（残留/循环）",
            "vod": "❌ 录播（ENDLIST）", "master": "— 索引，未判定",
            "dead": "❌ 取不到"}

# 回填只认这三种结论：rolling 是「确认在直播」，stuck/vod 是「确认不是直播」。
# dead（取不到）和 master（没跟到变体）说明不了内容，不能拿它们去清除已有的结论。
_JUDGED = {hist.ROLL_LIVE, *hist.ROLL_DEAD}


def roll_verdicts(pairs: list[tuple[str, dict]]) -> dict[str, str]:
    """筛出拿到内容结论的那些条：`{线路 url: verdict}`，交给 history.record_roll。

    `dead`（取不到）和 `master`（没跟到变体）说明不了内容，直接丢掉 ——
    履历里那一条保持上一次的判断，不被「这次没测出来」抹掉。

    >>> u = lambda h, p: f"http://{h}/{p}.m3u8"
    >>> sorted(roll_verdicts([(u("a", 1), {"verdict": "stuck"}),
    ...                       (u("b", 1), {"verdict": "rolling"}),
    ...                       (u("c", 1), {"verdict": "dead"}),
    ...                       (u("d", 1), {"verdict": "vod"}),
    ...                       (u("e", 1), {"verdict": "master"}),
    ...                       (u("f", 1), {})]).items())
    [('http://a/1.m3u8', 'stuck'), ('http://b/1.m3u8', 'rolling'), ('http://d/1.m3u8', 'vod')]
    """
    return {url: str(v.get("verdict") or "") for url, v in pairs
            if str(v.get("verdict") or "") in _JUDGED}


def write_roll_history(pairs: list[tuple[str, dict]], *, path: Path) -> int:
    """把 L3 的结论回填进履历里最近一轮可信实测。返回 0 表示真的写进去了。

    为什么要在这一层卡测量点：`record_roll()` 只认「那一轮」可不可信，
    而回填还有第二个前提 —— **现在**这一个出口得和那一轮是同一个。
    TUN 开着跑 L3，「列表不动」更可能是隧道掐了而不是源停了，写进去就等于
    把家里能播的主机判成录像台（计划书 2.8 那个坑的第三种踩法）。
    """
    verdicts = roll_verdicts(pairs)
    if not verdicts:
        print("\n  没有一条线路拿到内容结论（全是取不到或没跟到变体），履历不动。")
        return 1
    egress = egress_hint()
    warns = measurement_warnings(egress)   # 传出口：fake-IP 之外还看出口国家码
    if warns:
        print(f"\n⚠️ 没有回写履历：{warns[0]}")
        print("   代理在出口（TUN 或系统代理）一开，「列表不动」更可能是隧道掐了而不是源停了，"
              "写进去会把家里能播的主机冤枉掉。要么把代理整个关掉重跑，要么就别加 --to-history。")
        return 2
    runs = hist.load_history(path)
    at = datetime.now().astimezone().isoformat(timespec="seconds")
    done = hist.record_roll(runs, verdicts, current_egress=egress, at=at)
    if done["status"] != "ok":
        print(f"\n⚠️ 没有回写履历：{path.name} 里找不到出口为 `{egress or '未知'}` "
              "且体检干净的那一轮。先在同一个出口跑一次 `build --verify` 再回填。")
        return 3
    hist.save_history(path, runs)
    stuck = sum(1 for v in verdicts.values() if v != hist.ROLL_LIVE)
    print(f"\n已把 L3 结论写回 {path.name}（出口 `{egress}`）："
          f"逐条记 {done['checked']} 条，其中 {stuck} 条列表不动")
    if done["hosts"]:
        print("   整族「通了的全是录像」，下次离线生成会让位："
              + "、".join(f"`{h}`" for h in done["hosts"]))
    if done["unknown"]:
        print("   这些主机不在那一轮的实测表里，整族那一档记不上（逐条结论照样有效）："
              + "、".join(f"`{h}`" for h in done["unknown"]))
    return 0


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
    ap.add_argument("--to-history", action="store_true",
                    help="把 --roll 的结论回填进实测履历（需和 build 时用同一个出口，"
                         "代理 TUN 开着会拒绝写入）")
    ap.add_argument("--history", default=str(ROOT / "data" / "output" / "probe-history.jsonl"))
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

        def one(pair):
            name, url = pair
            return name, url, l3_roll(url, args.roll, args.timeout, not args.via_proxy)

        # 并发跑：每条 l3_roll 内部要 sleep(gap)，串行做等于把间隔乘上台数。
        with ThreadPoolExecutor(max_workers=max(len(firsts), 1)) as pool:
            verdicts = list(pool.map(one, firsts))
        for name, _url, v in verdicts:
            print(f"  {_VERDICT.get(v['verdict'], v['verdict']):<22} {name}"
                  + (f"  ({v['error']})" if v["error"] else ""))
        rolling = sum(1 for _, _, v in verdicts if v["verdict"] == "rolling")
        print(f"\n  真直播 {rolling}/{len(verdicts)}；"
              "stuck 的那批要盯 —— L2 全过但列表不动，多半是循环录像或早已停推。")
        if args.to_history:
            write_roll_history([(url, v) for _n, url, v in verdicts],
                               path=Path(args.history))
        return 0 if rolling / max(len(verdicts), 1) >= 0.5 else 1
    if args.to_history:
        print("⚠️ --to-history 只对 L3 的结论有意义：加上 --roll 20 才有东西可回填。")
    return 0 if total_ok / max(n, 1) >= 0.5 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
