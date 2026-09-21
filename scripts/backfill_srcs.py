#!/usr/bin/env python3
"""给 2.17 之前那几轮履历补上「这一族是哪个上游塞进来的」（`hosts[].srcs`）。

为什么需要它：履历制是 append-only 的，`srcs` 这个字段从 2.17 起才随每轮落盘，
所以在家里再跑出两轮可信实测之前，「按上游源摊开」那张表是空的 —— 报告只能说
「26 个主机族全灭」，说不出「所以该动 sources.yaml 里哪一行」。

为什么这件事不算伪造数据：`srcs` 不是一条**测量**，它是「这条 URL 出自哪个上游」，
由上游播放列表的内容决定。同一个缓存文件现在能算出来的映射，13:00 那轮跑的时候
一样算得出来 —— 当时只是没往文件里写。真正会出错的情况是**缓存本身变了**
（上游换线路、或者手工源被编辑过），所以这个脚本先做对账：

  履历里出现过、但在当前缓存里找不到出处的 Host，一律不填，并在报告里点名。
  这些主机族可能是上游已经撤掉的旧线路，硬猜一个来源比留空更糟。

用法（默认只预览，不动文件）：

    .venv/bin/python scripts/backfill_srcs.py            # 对账 + 预览
    .venv/bin/python scripts/backfill_srcs.py --write    # 确认无误后落盘（自动留 .bak）

写完记得重跑一次离线生成，让 report.md 里那张表跟着变：

    .venv/bin/python -m src.cli build
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.check import history as hist          # noqa: E402
from src.cli import (                          # noqa: E402
    HISTORY_FILE, LOCAL_SOURCES_FILE, SOURCES_FILE,
    collect, load_local, load_sources,
)

# 补记字段时写进履历的一句说明：让任何后来翻 jsonl 的人都知道这些数字从哪来
NOTE = ("srcs 由 scripts/backfill_srcs.py 在 {when} 事后补记："
        "来源不是测出来的，是把当时的上游缓存重算了一遍（{filled}/{rows} 行有出处，"
        "{unknown} 行在当前缓存里找不到，留空不猜）")


def host_sources(entries) -> dict[str, list[str]]:
    """主机族 -> 贡献它的上游源 id（去重、按名字排）。

    >>> class E:
    ...     def __init__(self, url, source): self.url, self.source = url, source
    >>> hs = host_sources([E("http://a.example/1.m3u8", "gd"), E("http://a.example/2.m3u8", "local"),
    ...                    E("http://b.example/x", ""), E("", "gd")])
    >>> sorted(hs.items())
    [('a.example', ['gd', 'local']), ('b.example', [])]
    """
    acc: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        host = urlsplit(e.url).hostname if e.url else ""
        if not host:
            continue
        acc.setdefault(host, set())
        if e.source:
            acc[host].add(str(e.source))
    return {h: sorted(s) for h, s in acc.items()}


def plan(runs: list[dict], host_srcs: dict[str, list[str]], *,
         when: str = "", note: str = NOTE) -> tuple[list[dict], dict]:
    """算出补记之后的轮次，外加一份对账账目。不修改传进来的 runs。

    一行都不猜：`host_srcs` 里没有这个主机，或者它在当前缓存里确实「无出处」（空列表），
    都保持原样。已经记过来源的行也不覆盖 —— 本轮实测记的是实测，比事后重算硬。

    >>> runs = [{"at": "T1", "hosts": [{"host": "a.example", "total": 2},
    ...                                {"host": "gone.example", "total": 1}]},
    ...         {"at": "T2", "hosts": [{"host": "a.example", "total": 2, "srcs": ["gd"]}]}]
    >>> new, rep = plan(runs, {"a.example": ["gd", "local"], "b.example": []}, when="现在")
    >>> new[0]["hosts"][0]["srcs"]
    ['gd', 'local']
    >>> new[0]["hosts"][1].get("srcs")           # 当前缓存里找不到 → 不填
    >>> new[1]["hosts"][0]["srcs"]               # 实测记过的不动
    ['gd']
    >>> new[0]["srcs_note"].startswith("srcs 由") and new[1].get("srcs_note") is None
    True
    >>> rep["filled"], rep["rows"], rep["unknown"]
    (1, 3, ['gone.example'])
    >>> plan(runs, {"a.example": ["gd"]})[1]["changed_rounds"]     # 只有一轮被改过
    ['T1']
    >>> runs[0]["hosts"][0].get("srcs") is None       # 传进来的东西没被改
    True
    """
    out: list[dict] = []
    unknown: list[str] = []
    filled = rows = 0
    changed: list[int] = []
    for run in runs:
        hosts = run.get("hosts") or []
        new_hosts = []
        round_filled = 0
        for h in hosts:
            rows += 1
            name = str(h.get("host") or "")
            if h.get("srcs") or not host_srcs.get(name):
                new_hosts.append(dict(h))
                if not h.get("srcs") and name:
                    unknown.append(name)
                continue
            new_hosts.append({**h, "srcs": list(host_srcs[name])})
            round_filled += 1
            filled += 1
        new_run = {**run, "hosts": new_hosts}
        if round_filled:
            changed.append(len(out))
        out.append(new_run)
    # 说明里那几个数得是**最终**账目，所以整轮处理完再补写，不能边算边写
    for i in changed:
        out[i]["srcs_note"] = note.format(when=when, filled=filled, rows=rows,
                                          unknown=len(unknown))
    return out, {"rows": rows, "filled": filled, "unknown": sorted(set(unknown)),
                 "changed_rounds": [str(out[i].get("at") or f"#{i}") for i in changed],
                 "rounds": len(runs)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="给旧履历补记 srcs（默认只预览）")
    ap.add_argument("--history", default=str(HISTORY_FILE))
    ap.add_argument("--write", action="store_true", help="确认预览无误后落盘")
    args = ap.parse_args(argv)

    path = Path(args.history)
    runs = hist.load_history(path)
    if not runs:
        print(f"{path} 里没有履历，不用补。", file=sys.stderr)
        return 1
    sources = load_sources(SOURCES_FILE, fresh=False)
    entries, _ = collect(sources)
    entries += load_local(LOCAL_SOURCES_FILE)
    hs = host_sources(entries)
    # 手工源那条地址在 entries 里带的就是 LOCAL_ID（load_local 给的），和 src.cli 同口径
    new, rep = plan(runs, hs, when=datetime.now().astimezone().isoformat(timespec="minutes"))
    print(f"履历 {rep['rounds']} 轮 / {rep['rows']} 行主机记录，"
          f"当前缓存能对上出处的 {rep['filled']} 行")
    for r in runs:
        have = sum(1 for h in (r.get("hosts") or []) if h.get("srcs"))
        print(f"  {r.get('at', '?')[:16]}  已记 {have}/{len(r.get('hosts') or [])}")
    if rep["unknown"]:
        print(f"  对不上出处的 {len(rep['unknown'])} 族（不填）："
              + "、".join(rep["unknown"][:8])
              + ("…" if len(rep["unknown"]) > 8 else ""))
    if rep["changed_rounds"]:
        print(f"  会改到 {len(rep['changed_rounds'])} 轮："
              + "、".join(x[:16] for x in rep["changed_rounds"]))
    else:
        print("  没有需要补的（要么全记过了，要么全都对不上出处）")
        return 0
    if not args.write:
        print("\n以上是预览。确认没问题再加 --write。")
        return 0
    bak = path.with_suffix(path.suffix + ".bak")
    bak.write_bytes(path.read_bytes())
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new),
                    encoding="utf-8")
    print(f"\n已写入 {path.name}（原文备份在 {bak.name}）。"
          "重跑一次 `python -m src.cli build` 让 report.md 用上它。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
