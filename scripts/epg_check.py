#!/usr/bin/env python3
"""量一件事：某个 EPG 地址能不能给我们的订阅表配上节目单。

为什么要它（计划书 P3）：`aptv.m3u` 头部那行 `x-tvg-url` 是从上游播放列表**抄来的**
（`src/cli.py` 里 `epg = epg_urls[0]`），抄的是 `Guovin/iptv-api` 的 **master 分支**
（经 `gh-proxy.com` 转发），而 master 上根本没有 `output/epg/epg.gz` ——
2026-09-21 拿订阅表里原样那一串量过：404，响应体 14 字节。换成能下载的 gd 分支那一份，
它又是 2026-08-07 生成的快照、里面只有 8/7~8/8 两天的节目，而那个仓库喂 EPG 用的
`config/epg.txt` 现在整份被注释掉了（它自己那套「请求失败就把地址前加 `#` 停用」的机制
把唯一那条地址划掉的）。于是「EPG 对齐」不能靠猜，得有个量尺。

三个数字一个都不能少。只看 HTTP 200 会骗人（那份过期快照照样 200），
只看「今天有没有节目」也会骗人（erw 那份有今天的节目，但 channel id 是 `1`、`81` 这种数字，
我们的 `tvg-id="CCTV-1"` 一条都按 id 配不上，全靠 display-name 才救得回来）。

配对的那套规则（归一化、受控前缀）只有一份实现，在 `src/check/epg.py`，
这里只负责取数据、按订阅表对一遍、把结果打印成人话。

用法：

    .venv/bin/python scripts/epg_check.py                       # 查「配置里在用的那条 + 默认候选」
    .venv/bin/python scripts/epg_check.py http://x/e.xml.gz     # 查指定地址（本地文件也行）
    .venv/bin/python scripts/epg_check.py --playlist data/output/hunan.m3u <url>...

出口提醒：这台电脑挂着全局代理时，发出去的请求走的是那条隧道（计划书 2.8 / 2.16），
所以「境内 EPG 服务能拿到」在这里**只能证明服务活着**，不能证明家里那张 Wi-Fi 拿得到 ——
最后一步要电视那边（或干净出口）再确认一次。这一句只在真的发了请求时才印（见 `is_remote`）。
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.check.epg import align_all, coverages, load_bytes     # noqa: E402
from src.parse.m3u import parse_m3u                            # noqa: E402

DEFAULT_SOURCES = [
    # 上游头部自己声明的那条（master 分支，经 gh-proxy）：留着它，是为了让「404」这一行
    # 每次都能被重量出来 —— 2026-09-21 量的是订阅表里原样那一串，404，14 字节响应体
    "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api"
    "/refs/heads/master/output/epg/epg.gz",
    "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/epg/epg.gz",
    # config/epg.yaml 现在用的就是这条（http 版同样 200，但订阅表头部写 https 更稳）
    "https://e.erw.cc/e.xml.gz",
    "https://epg.112114.xyz/pp.xml",
]


def from_config(path: Path) -> list[str]:
    """`config/epg.yaml` 里在用的那条 + 后备那条，排在候选最前面。

    为什么要读它：`backup_url` 这一行如果没有代码看，它就是一句写在配置里的客套话 ——
    换成后备地址这件事早晚要做，那把尺子得先认识它。
    配置文件不在（新克隆、或者 --config 指错了）就返回空，不抛。

    >>> from_config(ROOT / "config" / "epg.yaml")
    ['https://e.erw.cc/e.xml.gz', 'https://epg.112114.xyz/pp.xml']
    >>> from_config(ROOT / "config" / "definitely-missing.yaml")
    []
    """
    try:
        import yaml

        cfg = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("epg") or {}
    except Exception:                     # 文件不在/YAML 写坏了/没装 pyyaml：都当「没配置」
        return []
    return [str(u).strip() for u in (cfg.get("url"), cfg.get("backup_url")) if u]


def candidates(args_targets: list[str] | None, config: Path) -> list[str]:
    """命令行给的就用它；没给就「配置里那两条 + 默认那几个候选」，按出现顺序去重。

    >>> len(set(candidates(None, ROOT / "config" / "epg.yaml"))) == len(candidates(None, ROOT / "config" / "epg.yaml"))
    True
    >>> candidates(["http://x"], ROOT / "config" / "definitely-missing.yaml")
    ['http://x']
    """
    if args_targets:
        return list(args_targets)
    out: list[str] = []
    for u in from_config(config) + DEFAULT_SOURCES:
        if u not in out:
            out.append(u)
    return out


def read_channels(path: Path) -> list[tuple[str, str]]:
    """订阅表 -> [(tvg-id, 显示名)]，一条线路一行（按 (id, 台名) 去重）。

    去重的键是 **(tvg-id, 台名) 而不是台名**，这一点不是洁癖：2.19 之后 `tvg-id` 是从节目单
    反推的，同一个台名的第 1、2、3 条备选线本来就是同一个 id（`apply_ids()` 按频道改），
    所以「按台名去重」和「按线路去重」在正常表上数出来是一样的。不一样的是**漂移的时候**：
    一张表里同名不同 id（2.14 那条老毛病）若被按台名合并，这里就只剩第一条的 id，
    量出来的命中率是在量一个电视根本看不到的东西。所以这里宁可数出两个台，
    再由 `drift()` 把这件事点名出来。

    读表用的是项目自己的 m3u 解析器（`src/parse/m3u.py`），不是这里另写一份 ——
    体检吃的是**生成出来的那张表**，解析口径必须和 APTV 看到的一致。

    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "s.m3u"
    ...     _ = p.write_text('#EXTM3U\\n'
    ...         '#EXTINF:-1 tvg-id="CCTV-1" tvg-name="CCTV-1综合" group-title="g",CCTV-1综合\\n'
    ...         'http://a/1.m3u8\\n'
    ...         '#EXTINF:-1 tvg-id="CCTV-1综合" group-title="g",CCTV-1综合\\n'
    ...         'http://b/2.m3u8\\n'
    ...         '#EXTINF:-1 tvg-id="CCTV-1" group-title="g",CCTV-1综合\\n'
    ...         'http://c/3.m3u8\\n', encoding="utf-8")
    ...     read_channels(p)
    [('CCTV-1', 'CCTV-1综合'), ('CCTV-1综合', 'CCTV-1综合')]
    """
    rows, seen = [], set()
    for e in parse_m3u(path.read_text(encoding="utf-8")).entries:
        if (e.tvg_id, e.name) in seen:
            continue
        seen.add((e.tvg_id, e.name))
        rows.append((e.tvg_id, e.name))
    return rows


def drift(channels: list[tuple[str, str]]) -> dict[str, list[str]]:
    """同名却有两个以上 `tvg-id` 的台 —— 2.14 那条「谁先创建频道桶谁定 id」的漂移在这里现形。

    为什么单独量：这种台在命中率里是**隐形的**。它可能两个 id 都配上、也可能一个都没配上，
    两种都会给出一个数而不给出原因。而它恰恰是 2.19 那一层要消灭的东西，所以每次体检都该
    看见它，别等哪天换回 `--no-epg` 时才想起来。

    >>> drift([("CCTV-1", "CCTV-1综合"), ("CCTV-1综合", "CCTV-1综合"), ("湖南卫视", "湖南卫视")])
    {'CCTV-1综合': ['CCTV-1', 'CCTV-1综合']}
    >>> drift([("1", "a"), ("1", "a"), ("2", "b")])      # 同一台的多条备选线，不算漂移
    {}
    """
    per: dict[str, list[str]] = {}
    for tid, name in channels:
        ids = per.setdefault(name, [])
        if tid not in ids:
            ids.append(tid)
    return {n: ids for n, ids in per.items() if len(ids) > 1}


def fetch(target: str, timeout: int = 40) -> bytes:
    """本地文件直接读，URL 走 urllib。"""
    if is_remote(target):
        req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()
    return Path(target).read_bytes()


def is_remote(target: str) -> bool:
    """这一条候选要不要发一个请求出去 —— 「出口提醒」该不该印，就看这个。

    为什么要单独拎出来：那句提醒以前是**无条件**印的，等于替这台机器的出口状态下了结论
    （2.30 把它挂进 `scripts/selfcheck.py`、只喂一份本地缓存时，它当场成了一句假话：
    一个请求都没发，却在说「境内服务拿得到只证明它活着」）。
    这和 2.29 那个「99 个台」是同一个形状的东西 —— **话说得比它量的范围大**。

    >>> is_remote("https://e.erw.cc/e.xml.gz")
    True
    >>> is_remote("data/cache/epg.xml")
    False
    """
    return target.startswith("http")


def id_map(channels: list[tuple[str, str]]) -> dict[str, str]:
    """台名 -> 它在这张表里的 tvg-id（同名多写法时留第一次见到的那个）。

    >>> id_map([("81", "湖南卫视"), ("x", "湖南卫视"), ("1", "CCTV-1综合")])
    {'湖南卫视': '81', 'CCTV-1综合': '1'}
    """
    out: dict[str, str] = {}
    for tid, name in channels:
        out.setdefault(name, tid)
    return out


def id_drift(new: list[tuple[str, str]], old: list[tuple[str, str]]) -> dict:
    """两张订阅表之间，同一个台名的 `tvg-id` 变了多少个。

    为什么要单独量这一件事：`tvg-id` 是 APTV 眼里**频道的身份**（收藏、隐藏、节目单都挂在它上面）。
    2.19 那一层把整列 id 换成节目单里的写法，收益是「有节目条」，代价是风险换了地方 ——
    万一那份节目单的 id 每天重排（数字 id 的服务完全可能这么干），我们就会**每天给电视换一次台身份**。
    报告里「70/99 有节目单」看不出来这件事，这里量得出来：跨天重出表时 `changed` 应该是 0。

    >>> a = id_drift([("81", "湖南卫视"), ("1", "CCTV-1综合")], [("湖南卫视", "湖南卫视"), ("1", "CCTV-1综合")])
    >>> a["common"], a["changed"], a["only_new"], a["only_old"]
    (2, [('湖南卫视', '湖南卫视', '81')], [], [])
    >>> id_drift([("81", "a")], [("81", "a")])["changed"]      # 一模一样：0
    []
    >>> d = id_drift([("1", "新台")], [("9", "旧台")])          # 两版差台，不算漂移
    >>> d["only_new"], d["only_old"], d["changed"]
    (['新台'], ['旧台'], [])
    """
    n, o = id_map(new), id_map(old)
    common = sorted(set(n) & set(o))
    return {
        "total_new": len(n), "total_old": len(o), "common": len(common),
        "changed": [(k, o[k], n[k]) for k in common if o[k] != n[k]],
        "only_new": sorted(set(n) - set(o)), "only_old": sorted(set(o) - set(n)),
    }


def drift_lines(d: dict) -> list[str]:
    """把 `id_drift()` 打成人话，并且直接把「能不能安全重出表」说出来。

    >>> print("\\n".join(drift_lines(id_drift([("81","a")], [("a","a")]))))
    - 两版共 1 个台名：**1 个的 tvg-id 变了**：a（`a`→`81`）
    >>> print("\\n".join(drift_lines(id_drift([("81","a"),("1","b")], [("81","a"),("2","b")]))))
    - 两版共 2 个台名：**1 个的 tvg-id 变了**：b（`2`→`1`）
    """
    ch = d["changed"]
    head = (f"- 两版共 {d['common']} 个台名："
            + (f"**{len(ch)} 个的 tvg-id 变了**：" if ch else "**tvg-id 一个都没变**"))
    out = [head + ("、".join(f"{k}（`{o}`→`{n}`）" for k, o, n in ch[:10])
                   + ("…" if len(ch) > 10 else "") if ch else "")]
    if d["only_new"] or d["only_old"]:
        out.append(f"- 台名本身有进出：新版多 {d['only_new'][:8]}／少 {d['only_old'][:8]}"
                   "（这是线路增删，不是 id 漂移）")
    return out


def usable(lines: list[str]) -> bool:
    """这段体检结论算不算「可用」：今天有节目，且至少配上我们一个台。

    >>> usable(["覆盖 1 天：20260921，今天有节目", "合计 3/98"])
    True
    >>> usable(["没有今天的内容（覆盖 1 天：20260807，距今 45 天）", "合计 43/98"])
    False
    >>> usable(["今天有节目（覆盖 2 天）", "合计 0/98"])      # 一个台都配不上，等于没有
    False
    """
    txt = " ".join(lines)
    return "今天有节目" in txt and "合计 0/" not in txt


def exit_code(n_targets: int, ok: int) -> int:
    """一个候选都没落进「可用」时退 1 —— 别的脚本要拿这个当门。

    为什么要改：这条脚本从 2.19 起只印结论、永远退 0，那会儿它是人肉看的一份报告，
    「0 个能用」也是一条有用的信息。2.30 把它挂进 `scripts/selfcheck.py` 之后，同一句
    「结论：1 个候选里，0 个既今天有节目…」头顶着一个 ✓，就成了这个项目最不接受的那种绿
    （另外三把尺说不通就退非 0，只有它退 0）。
    没查任何候选仍然算 0：那只可能是 `--against` 单跑漂移，那不是「查了、都说不能用」。

    >>> exit_code(4, 1)      # 四个候选里有一个能用
    0
    >>> exit_code(4, 0)      # 一个都用不了
    1
    >>> exit_code(0, 0)      # 一条候选都没查，不是失败
    0
    """
    return 1 if n_targets and not ok else 0


def report(target: str, channels: list[tuple[str, str]], today: str,
           timeout: int = 40) -> list[str]:
    """一个地址一段话：活没活着、今天有没有、我们的台有几个配得上、靠哪一列配上的。"""
    try:
        doc, note = load_bytes(fetch(target, timeout=timeout))
    except Exception as e:                       # 网络/解压失败都要变成一行字，不要 traceback
        return [f"## {target}", f"  ✗ 取不到：{type(e).__name__}: {e}", ""]
    rows = align_all(channels, doc)
    by_id = sum(1 for r in rows if r["how"] == "id")
    by_name = sum(1 for r in rows if r["how"] == "name")
    changed = [r for r in rows if r["how"] == "name"]
    out = [f"## {target}",
           f"  {note}；generator={doc.generator or '（未声明）'}",
           f"  频道 {doc.n_channels} 个、节目 {doc.progs} 条 —— {coverages(doc, today)}",
           f"  我们这张表 {len(rows)} 个频道：按 tvg-id 配上 {by_id} 个，"
           f"再靠台名救回 {by_name} 个，合计 {by_id + by_name}/{len(rows)}"]
    if changed:
        out.append("  改 id 就能配上的：" + "、".join(
            f"{r['name']}（{r['old_id']}→{r['new_id']}）" for r in changed[:8])
            + ("…" if len(changed) > 8 else ""))
    miss = [r["name"] for r in rows if not r["how"]]
    if miss:
        out.append(f"  配不上的 {len(miss)} 个：" + "、".join(miss[:20])
                   + ("…" if len(miss) > 20 else ""))
    out.append("")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="EPG 可用性与命中率体检（只读，不写任何产物）")
    ap.add_argument("targets", nargs="*", default=None,
                    help="EPG 地址或本地文件；不给就查默认那几个候选")
    ap.add_argument("--playlist", default=str(ROOT / "data" / "output" / "aptv.m3u"),
                    help="拿哪张订阅表来对命中率（默认 aptv.m3u）")
    ap.add_argument("--today", default="", help="按哪天判「今天有没有节目」，YYYYMMDD；默认本机今天")
    ap.add_argument("--timeout", type=int, default=40)
    ap.add_argument("--config", default=str(ROOT / "config" / "epg.yaml"),
                    help="读这份配置里的 url / backup_url 当作候选（默认 config/epg.yaml）")
    ap.add_argument("--against", default="",
                    help="再拿另一张订阅表对一遍「同一个台名的 tvg-id 变了几个」"
                         "（跨天重出表时这里应该是 0）")
    args = ap.parse_args(argv)

    cfg = Path(args.config)
    targets = candidates(args.targets, cfg)
    path = Path(args.playlist)
    if not path.exists():
        print(f"订阅表不在：{path}", file=sys.stderr)
        return 1
    channels = read_channels(path)
    if args.against:
        other = Path(args.against)
        if not other.exists():
            print(f"--against 那张表不在：{other}", file=sys.stderr)
            return 1
        print(f"id 漂移：{path} 相对 {other}")
        print("\n".join(drift_lines(id_drift(channels, read_channels(other)))))
        print()
    today = args.today or datetime.now().strftime("%Y%m%d")
    print(f"对表：{path.name}（{len(channels)} 个频道）  今天：{today}")
    if args.targets:
        print(f"候选：命令行给的 {len(targets)} 条（--config 这次没用上）")
    else:
        in_use = from_config(cfg)
        rel = cfg.relative_to(ROOT) if str(cfg).startswith(str(ROOT) + "/") else cfg
        print(f"候选：{len(targets)} 条"
              + (f"，配置里在用 `{rel}`：{in_use[0]}"
                 if in_use else f"，配置 `{rel}` 没读到地址，只查默认候选")
              + (f"，后备 {in_use[1]}" if len(in_use) > 1 else ""))
    if any(is_remote(t) for t in targets):
        print("（下面这些「拿得到」是从**这台电脑**发请求量的：出口若挂着全局代理，"
              "它只证明那个服务活着，不证明家里那张 Wi-Fi 拿得到；"
              "出口干不干净看 `build --verify` 屏幕上那三行体检警告，别看这里）")
    else:
        print("（这一轮一个请求都没发：读的全是本地文件，所以下面那些数跟出口状态无关）")
    bad = drift(channels)
    if bad:                      # 这一层是「表本身有问题」，跟哪个 EPG 无关，所以先说
        print(f"⚠️ {len(bad)} 个台名在这张表里有两种以上的 tvg-id（2.14 那条漂移）："
              + "、".join(f"{n}（{'/'.join(ids)}）" for n, ids in list(bad.items())[:6])
              + ("…" if len(bad) > 6 else "")
              + " —— 下面按 (id, 台名) 数，这种台算两个")
    else:
        print("这张表里每个台名只有一种 tvg-id（对齐之后 id 由节目单说了算，不该再有漂移）")
    print()
    ok = 0
    for t in targets:
        lines = report(t, channels, today, timeout=args.timeout)
        print("\n".join(lines))
        ok += 1 if usable(lines) else 0
    print(f"结论：{len(targets)} 个候选里，{ok} 个既今天有节目、又配得上我们表里的台。")
    return exit_code(len(targets), ok)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
