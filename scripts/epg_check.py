#!/usr/bin/env python3
"""量一件事：某个 EPG 地址能不能给我们的订阅表配上节目单。

为什么要它（计划书 P3）：`aptv.m3u` 头部那行 `x-tvg-url` 是从上游播放列表**抄来的**
（`src/cli.py` 里 `epg = epg_urls[0]`），抄的是 `Guovin/iptv-api` 的 **master 分支**
（经 `gh-proxy.com` 转发），而 master 上根本没有 `output/epg/epg.gz` ——
2026-09-21 拿订阅表里原样那一串量过：404，响应体 14 字节。换成能下载的 gd 分支那一份，
它又是 2026-08-07 生成的快照、里面只有 8/7~8/8 两天的节目，而那个仓库喂 EPG 用的
`config/epg.txt` 现在整份被注释掉了（它自己那套「请求失败就把地址前加 `#` 停用」的机制
把唯一那条地址划掉的）。于是「EPG 对齐」不能靠猜，得有个量尺。

四个数字一个都不能少。只看 HTTP 200 会骗人（那份过期快照照样 200），
只看「今天有没有节目」也会骗人（erw 那份有今天的节目，可 2026-09-21 那时我们的 `tvg-id`
还是 `CCTV-1` 这种写法，一条都按 id 配不上，全靠 display-name 才救得回来）；
**只看「配上几个台」同样会骗人** —— 2026-09-22 晚上拿同一份缓存量两张表，
两张都是 `69/98`，可一张是「0 按 id + 69 靠台名」（电视现在订阅的那张，2.19 那一层还没落进去），
另一张是「69 按 id + 0 靠台名」（对齐之后重出的那一张）。合计数一模一样，来历完全不同。
所以除了命中率，这里还印两张独立证据：`provenance()`（那个拆分读出来的来历）
和 `header_url()`（表头部那行 `x-tvg-url`，它由另一条代码路径决定）。

配对的那套规则（归一化、受控前缀）只有一份实现，在 `src/check/epg.py`；
`config/epg.yaml` 也只有一份读法，在 `src/cli.py` 的 `load_epg_config()`（2.44 起这里不再
自己 `yaml.safe_load` 一遍 —— 两份读法在四种配置形状上给出四种答案，其中两种是冒充）。
这里只负责取数据、按订阅表对一遍、把结果打印成人话。

用法：

    .venv/bin/python scripts/epg_check.py                       # 查「配置里那两条 + 默认候选」
    .venv/bin/python scripts/epg_check.py http://x/e.xml.gz     # 查指定地址（本地文件也行）
    .venv/bin/python scripts/epg_check.py data/cache/epg.xml    # 只问「现在这张表出自哪一轮」：不发一个请求
    .venv/bin/python scripts/epg_check.py --playlist data/output/hunan.m3u data/cache/epg.xml  # 换成湖南那张表来量
    .venv/bin/python scripts/epg_check.py --config /tmp/off.yaml  # 换一份配置读（那行「在用/关着」跟着变）
    .venv/bin/python scripts/epg_check.py --self-test  # 不问 EPG，只问这把尺自己还咬得动吗（种 14 格，一个请求都不发）

出口提醒：这台电脑挂着全局代理时，发出去的请求走的是那条隧道（计划书 2.8 / 2.16），
所以「境内 EPG 服务能拿到」在这里**只能证明服务活着**，不能证明家里那张 Wi-Fi 拿得到 ——
最后一步要电视那边（或干净出口）再确认一次。这一句只在真的发了请求时才印（见 `is_remote`）。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from baseline_guard import guard as guard_names          # noqa: E402  顿号那道闸（几把基线尺共用）
from run_doctests import (DOCTEST_FLAG, SELF_TEST_FLAG, add_doctest_flag,      # noqa: E402
                          arg_door_answered, arg_door_exit, run_own)
# `--doctest` 那一旗的口径只有一份；2.79 起「这一遍答哪一扇」也只有一份
from doc_num import hide_tmp, read_doc                   # noqa: E402
from src.check.epg import align_all, coverages, load_bytes, parse_tv # noqa: E402
from src.cli import load_epg_config                        # noqa: E402
from src.parse.m3u import parse_m3u                        # noqa: E402

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


def from_config(path: Path) -> tuple[list[str], str]:
    """`config/epg.yaml` 里那两条地址，加一句「配置现在让不让它们进表」。

    这里以前**另写一份** YAML 读取（`yaml.safe_load(...).get("epg")` + `cfg.get("url")`），
    和 build 用的 `load_epg_config()` 一人一份。两份读法在四种配置形状上给出四种答案，
    而体检那句「配置里在用 …」对前两种都照印不误（整张对照表在计划书 2.44）：

      * `enabled: false` —— build 整层关掉，这里当没看见，照样印「在用」；
      * YAML 写坏了 —— 这里返回空，冒充成「配置里没写地址」；
      * `epg:` 写成一行字符串 —— 这里**崩栈**（那句 `except Exception` 在 try 外面），
        build 那边却安静地当「没启用」；
      * `url:` 排成两行 —— 这里 `str()` 成 `"['a', 'b']"` 当一个地址用。

    现在只有一份实现：地址和状态都由 `load_epg_config()` 给，这里只把它的 `state`
    原样交出去。这样「尺子说在用、产品其实没在用」这一类分歧从结构上就没有立足点。

    >>> urls, state = from_config(ROOT / "config" / "epg.yaml")
    >>> state, urls[0]
    ('在用', 'https://e.erw.cc/e.xml.gz')
    >>> len(urls)                                   # url + backup_url 两条
    2
    >>> from_config(ROOT / "config" / "definitely-missing.yaml")
    ([], '文件不在')
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "off.yaml"
    ...     _ = p.write_text("epg:\\n  url: http://x/e.xml\\n  enabled: false\\n",
    ...                      encoding="utf-8")
    ...     from_config(p)
    (['http://x/e.xml'], '关着')
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p2 = pathlib.Path(d) / "e.yaml"
    ...     _ = p2.write_text("epg:\\n  url: [oops\\n   bad: x\\n", encoding="utf-8")
    ...     from_config(p2)                       # 坏 YAML：不再冒充「没配置」，也不再崩
    ([], 'YAML 读不出来')
    """
    cfg = load_epg_config(path)
    return ([u for u in (cfg["url"], cfg["backup_url"]) if u], cfg["state"])


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
    for u in from_config(config)[0] + DEFAULT_SOURCES:
        if u not in out:
            out.append(u)
    return out


def rows_and_header(path: Path) -> tuple[list[tuple[str, str]], str, str]:
    """读一张订阅表，一次给齐三样：[(tvg-id, 台名)]、头部那行节目单地址、读不进来时的为什么。

    为什么要新加这一层，而不是让 `main()` 先 `read_doc` 再分别调 `read_channels()`
    和 `header_url()`：那两个各自 `read_text` 一遍，于是「读进来」这一族要在两处各防一次，
    而中间文件被换掉（同步盘把冲突副本塞回来）就会崩在第二遍上 —— 2.62 修的正是这一族，
    2.63 量到这一层以前**根本没防**：`--playlist` 指到目录崩 `IsADirectoryError`、
    指到非 UTF-8 的文件崩 `UnicodeDecodeError`，两下都是整段 traceback、退码 1，
    而 1 在这把尺上是「一个候选都不能用」。屏幕上一行结论都没印，退码却在下判决。

    第三种（文件不在）以前这一层已经会说人话，但说的是自己那一句，和 `doc_num.read_doc`
    那三种不是一份 —— 现在三种都从 `read_doc` 出来，一句话只有一份。

    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "a.m3u"
    ...     _ = p.write_text('#EXTM3U x-tvg-url="https://e.erw.cc/e.xml.gz"\\n'
    ...                      '#EXTINF:-1 tvg-id="81",湖南卫视\\nhttp://a/1.m3u8\\n', encoding="utf-8")
    ...     rows_and_header(p)
    ([('81', '湖南卫视')], 'https://e.erw.cc/e.xml.gz', '')
    >>> with tempfile.TemporaryDirectory() as d:
    ...     rows_and_header(pathlib.Path(d))                 # 指到目录：不是文档
    ([], '', '那是个目录，不是文档')
    >>> rows_and_header(ROOT / "config" / "definitely-missing.m3u")
    ([], '', '文件不在')
    """
    text, why = read_doc(path)
    if text is None:
        return [], "", why
    m3u = parse_m3u(text)
    rows, seen = [], set()
    for e in m3u.entries:
        if (e.tvg_id, e.name) in seen:
            continue
        seen.add((e.tvg_id, e.name))
        rows.append((e.tvg_id, e.name))
    return rows, m3u.x_tvg_url, ""


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
    真正读文件的那一截在 `rows_and_header()`，这一层只是「只看台列表」的那个视图。

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
    rows, _url, _why = rows_and_header(path)
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


def header_url(path: Path) -> str:
    """这张表头部 `x-tvg-url` 写的是哪条地址（电视自己去取的就是这一行；没写就返回空串）。

    为什么单独取出来印：它是「这张表出自哪一轮」的**第二条证据**，而且和 `tvg-id` 那一列
    互相独立 —— id 由 `apply_ids()` 改，头部由 `epg_header_url()` 决定，两条代码路径。
    2026-09-22 晚上磁盘上这张就是这么认出来的：头部还是上游抄来的那条 404，
    而 id 一列也确实是台名（见 `provenance`）。

    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "a.m3u"
    ...     _ = p.write_text('#EXTM3U x-tvg-url="https://e.erw.cc/e.xml.gz"\\n'
    ...                      '#EXTINF:-1 tvg-id="81",湖南卫视\\nhttp://a/1.m3u8\\n', encoding="utf-8")
    ...     header_url(p)
    'https://e.erw.cc/e.xml.gz'
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "b.m3u"
    ...     _ = p.write_text('#EXTM3U\\n#EXTINF:-1,湖南卫视\\nhttp://a/1.m3u8\\n', encoding="utf-8")
    ...     header_url(p)
    ''
    """
    return rows_and_header(path)[1]


def provenance(by_id: int, by_name: int) -> str:
    """从「按 id 配上几个 / 靠台名救回几个」这个**拆分**读出这张表出自哪一轮。

    为什么不能只看合计数：2026-09-22 晚上拿同一份节目单缓存量两张表，
    **合计都是 69/98**，可 `data/output/aptv.m3u` 是 0 按 id + 69 靠台名（2.19 那一层
    还没落进去的那一轮），`/tmp/r226/aptv.m3u` 是 69 按 id + 0 靠台名（对齐之后重出的那份）。
    同一个合计数、两种完全不同的来历 —— 光印「69 个台有节目单」，读到的人就会以为
    电视上那张已经生效了。这一层以前只把两个数分开印在括号里，没人会去读那个括号。

    说的是「相对**这一份**节目单」，不是绝对真理：一张按 112114 那份对齐的表，
    拿 erw 来量同样会给出「0 按 id」，那也正是这句话的字面意思。

    >>> provenance(69, 0)
    '这张表的 id 就是这一份节目单那一套（69 个全按 id 配上）—— 2.19 那一层已经落进这张表'
    >>> provenance(0, 69)
    '没有一个 id 来自这一份节目单（69 个全靠台名救回）—— 这张表出自 2.19 那一层生效之前，或者它是按另一份节目单出的'
    >>> provenance(40, 29)
    '混着的：40 个带这一份的 id、29 个还得靠台名 —— 像是换了节目单之后没重出全'
    >>> provenance(0, 0)
    '一个台都没配上，看不出这张表的来历'
    """
    if not by_id and not by_name:
        return "一个台都没配上，看不出这张表的来历"
    if not by_name:
        return (f"这张表的 id 就是这一份节目单那一套（{by_id} 个全按 id 配上）"
                "—— 2.19 那一层已经落进这张表")
    if not by_id:
        return (f"没有一个 id 来自这一份节目单（{by_name} 个全靠台名救回）"
                "—— 这张表出自 2.19 那一层生效之前，或者它是按另一份节目单出的")
    return f"混着的：{by_id} 个带这一份的 id、{by_name} 个还得靠台名 —— 像是换了节目单之后没重出全"


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


def exit_code(n_targets: int, ok: int, *, drift_skipped: bool = False,
              id_changed: bool = False) -> int:
    """一个候选都没落进「可用」时退 1 —— 别的脚本要拿这个当门。

    为什么要改：这条脚本从 2.19 起只印结论、永远退 0，那会儿它是人肉看的一份报告，
    「0 个能用」也是一条有用的信息。2.30 把它挂进 `scripts/selfcheck.py` 之后，同一句
    「结论：1 个候选里，0 个既今天有节目…」头顶着一个 ✓，就成了这个项目最不接受的那种绿
    （另外三把尺说不通就退非 0，只有它退 0）。
    没查任何候选仍然算 0：那只可能是 `--against` 单跑漂移，那不是「查了、都说不能用」。

    2.63 起多一个入参：`--against` 那张表整个读不进来时（`drift_skipped`），
    哪怕 EPG 这几个候选都可用也不给 0 —— 那是 2.62 立的口径，**量到了、但有一块没量到**
    就是 1，不能和「都量到了、都没毛病」共用一个绿。至于「表压根读不进来」那种
    什么都没量到的，在 `main()` 里直接退 2，不走这个函数。

    >>> exit_code(4, 1)      # 四个候选里有一个能用
    0
    >>> exit_code(4, 0)      # 一个都用不了
    1
    >>> exit_code(0, 0)      # 一条候选都没查，不是失败
    0
    >>> exit_code(4, 4, drift_skipped=True)    # 全可用，可 id 漂移那一段没量
    1
    >>> exit_code(4, 0, drift_skipped=True)    # 两块毛病叠着，还是 1，不多挡一档
    1
    >>> exit_code(0, 0, drift_skipped=True)    # 「一条候选都没查」这一支回不来（见上）
    1
    >>> exit_code(4, 4, id_changed=True)       # 全可用，可量到了台名换 id —— 那也是 1，不是 0
    1
    >>> exit_code(4, 4, id_changed=False)      # 量过了、一个都没变：这才是 0
    0
    >>> exit_code(4, 0, drift_skipped=True, id_changed=True)   # 三块叠着仍只退 1（没有 3 这一档）
    1

    2.64 起多第三个入参：`--against` 给的是好表、而那一段**量到了**「有台名的 tvg-id 变了」。
    那一格以前退 0 —— 它是 `exit_code` 里唯一一个「量到了毛病却不进判决」的出口，
    `--against` 那句 help 自己写着「跨天重出表时这里应该是 0」，可屏幕上报出「变了 1 个」
    的时候退码还是 0，`selfcheck` 那一层读起来就是「查过，没问题」。
    """
    if drift_skipped or id_changed:
        return 1
    return 1 if n_targets and not ok else 0


def provenance_of(lines: list[str]) -> str:
    """从一段体检输出里把「来历」那句的**短句**摘出来（结论行要用）。

    为什么要从自己印出来的行里再摘一遍，而不是让 `report()` 顺手返回一个结构：
    这一支脚本的 `report()` 就是一条“给人看的一段字”，把它改成返回 dict 会牵动
    `usable()`（它就是读那几行字的）。这里宁可复用那行字，也不要为了少一次字符串处理
    把“打印格式”和“判定数据”重新搅在一起 —— 2.30 的 `conclusion()` 是同一个取舍。

    >>> provenance_of(["  这张表的来历：没有一个 id 来自这一份节目单（69 个全靠台名救回）"
    ...                 "—— 这张表出自 2.19 那一层生效之前，或者它是按另一份节目单出的"])
    '没有一个 id 来自这一份节目单（69 个全靠台名救回）'
    >>> provenance_of(["  这张表的来历：这张表的 id 就是这一份节目单那一套（69 个全按 id 配上）"
    ...                 "—— 2.19 那一层已经落进这张表"])
    '这张表的 id 就是这一份节目单那一套（69 个全按 id 配上）'
    >>> provenance_of(["## 一个候选", "  ✗ 取不到"])      # 取不到的那段没有这行
    ''
    """
    for line in lines:
        if line.startswith("  这张表的来历："):
            return line.split("：", 1)[1].split("——")[0].strip()
    return ""


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
           f"再靠台名救回 {by_name} 个，合计 {by_id + by_name}/{len(rows)}",
           f"  这张表的来历：{provenance(by_id, by_name)}"]
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


def config_line(rel: str, urls: list[str], state: str) -> str:
    """「候选：N 条」后面那半句：配置到底让不让这条地址进表，说清楚。

    2.44 之前这一句只分「有地址 / 没地址」两档，于是 `enabled: false` 印出来和「在用」
    一模一样 —— 拿一份关掉的配置当场跑，屏幕上还是
    「配置里在用 `…/epg.yaml`：https://e.erw.cc/e.xml.gz」，
    而 build 那边那一列 tvg-id 已经整个退回上游写法了。
    话说得比它量的范围大，和 2.29 那个「99 个台」是同一个形状。

    注意「关着」那一档仍然把地址留在候选里：尺子该继续量它（哪天要打开，得先知道它活着），
    只是不许再让人以为它现在进表。

    >>> print(config_line("config/epg.yaml", ["http://a", "http://b"], "在用"))
    ，配置里在用 `config/epg.yaml`：http://a，后备 http://b
    >>> print(config_line("config/epg.yaml", ["http://a"], "在用"))
    ，配置里在用 `config/epg.yaml`：http://a
    >>> print(config_line("config/epg.yaml", ["http://a"], "关着"))
    ，配置 `config/epg.yaml` 写着 http://a，但 `enabled: false`：这一层现在整个没参与，下面照量它、只当候选
    >>> print(config_line("config/epg.yaml", [], "文件不在"))
    ，配置 `config/epg.yaml` 不在，只查默认候选
    >>> print(config_line("config/epg.yaml", [], "YAML 读不出来"))
    ，配置 `config/epg.yaml` 那份 YAML 读不出来（不是没写，是写坏了），只查默认候选
    >>> print(config_line("config/epg.yaml", [], "没写地址"))
    ，配置 `config/epg.yaml` 没读到地址，只查默认候选
    >>> print(config_line("config/epg.yaml", [], "关着"))
    ，配置 `config/epg.yaml` 没读到地址，只查默认候选

    最后那格是**手搓出来的输入**：`from_config()` 给不出「关着但没有地址」
    （`state` 那五态是按顺序判的，`url` 空就先落进「没写地址」）。这里照样说一句实话，
    是因为这一格函数不该知道自己只会被那一种组合喂到 —— 而「写着 、但 `enabled: false`」
    那种带空位的句子只会让人以为少了什么，不如退回那句「没读到地址」。
    """
    if state == "在用" and urls:
        return (f"，配置里在用 `{rel}`：{urls[0]}"
                + (f"，后备 {urls[1]}" if len(urls) > 1 else ""))
    if state == "关着" and urls:
        return (f"，配置 `{rel}` 写着 {'、'.join(urls)}，"
                "但 `enabled: false`：这一层现在整个没参与，下面照量它、只当候选")
    if state == "文件不在":
        return f"，配置 `{rel}` 不在，只查默认候选"
    if state == "YAML 读不出来":
        return f"，配置 `{rel}` 那份 YAML 读不出来（不是没写，是写坏了），只查默认候选"
    return f"，配置 `{rel}` 没读到地址，只查默认候选"


# ============================== 2.64：这把尺的回归基线 ==============================
#
# 为什么要单独一档：2.63 把「读不进来」那一族改成人话之后，那些形状**只活在 doctest 里**，
# 而 `scripts/selfcheck.py` 默认只喂一份本地缓存给这把尺（`epg_offline` 那一步）——
# 也就是说「--playlist 指到目录要退 2」「--against 读不进来要退 1」这些改对了的事没有任何闸守着。
# 装这一档的时候当场量出两处判决漏了（见 `exit_code` 的 `id_changed`、`main()` 里配置那一格），
# 都是 doctest 看不见、只有跑整屏才现形的那类。形状照 2.56—2.59、2.62、2.64 的 table_drift：
# 种进临时沙盒、跑**真的 `main()`**、逐格对退码与句子。沙盒全在 `tempfile` 里，
# `data/output/` 与 `data/cache/` 一个字节都不动，而且下面那个 `no_network` 保证一个请求都不发。

TODAY = "20260923"        # 基线里的「今天」钉死在这一天：跟着本机时钟走的话，这档到 2027 年自己会红

HDR = '#EXTM3U x-tvg-url="https://e.erw.cc/e.xml.gz"\n'
ONE = HDR + '#EXTINF:-1 tvg-id="81" group-title="g",湖南卫视\nhttp://a/1.m3u8\n'
DRIFTED = HDR + '#EXTINF:-1 tvg-id="999" group-title="g",湖南卫视\nhttp://a/1.m3u8\n'
TWIN = HDR + ('#EXTINF:-1 tvg-id="81" group-title="g",湖南卫视\nhttp://a/1.m3u8\n'
              '#EXTINF:-1 tvg-id="999" group-title="g",湖南卫视\nhttp://b/2.m3u8\n')
NON_UTF8 = b"#EXTM3U\n" + bytes([0xFF, 0xFE, 0x41])   # 头一行是表，第八个字节起不是 UTF-8


def epg_xml(*chans: tuple[str, str, str]) -> str:
    """拼一份最小 XMLTV：每个入参是 (频道 id, display-name, 哪天有条目)，日期给空串就没条目。

    >>> e = parse_tv(epg_xml(("81", "湖南卫视", TODAY)))
    >>> e.progs, e.ids, dict(e.days), e.generator
    (1, ['81'], {'20260923': 1}, 'g264')
    >>> parse_tv(epg_xml(("qqq", "央视某台", "20260807"))).days["20260807"]
    1
    >>> parse_tv(epg_xml()).progs, parse_tv(epg_xml()).ids       # 一份空单：不是报错页，是没内容
    (0, [])

    第三格那种「有 channel 却没有 programme」是刻意分开的两档：`coverages()` 对二者的说法
    不一样（一个是「一条节目都没有」，一个是「今天只有 N 个台有条目」），基线要能分辨。
    """
    body = "".join(f'<channel id="{cid}"><display-name lang="zh">{name}</display-name></channel>'
                   for cid, name, _day in chans)
    progs = "".join(f'<programme channel="{cid}" start="{day}120000 +0800">'
                    f'<title lang="zh">节目</title></programme>'
                    for cid, _name, day in chans if day)
    return f'<tv generator-info-name="g264">{body}{progs}</tv>'


# 每格都先种这一批：九件东西把「表 / 单 / 配置」三类各摆几种形状，格子自己只补要多的那件
FIXTURES: tuple[tuple[str, str], ...] = (
    ("表.m3u", ONE),
    ("同表.m3u", ONE),
    ("漂移表.m3u", DRIFTED),
    ("同名表.m3u", TWIN),
    ("好单.xml", epg_xml(("81", "湖南卫视", TODAY))),
    ("陌生单.xml", epg_xml(("zzz", "湖南卫视", TODAY))),
    ("别人单.xml", epg_xml(("qqq", "央视某台", TODAY))),
    ("旧单.xml", epg_xml(("81", "湖南卫视", "20260807"))),
    ("关配置.yaml", f"epg:\n  url: {{T}}/好单.xml\n  enabled: false\n"),
    ("坏配置.yaml", "epgs:\n  url: http://x/e.xml\n"),
)


@contextlib.contextmanager
def no_network():
    """把 `urlopen` 换成一个「一碰就抛」的替身：`--self-test` 这一档一个请求都不许发出去。

    为什么要专门设这一道：这一支脚本**不给参数就会去下载四个候选**（`DEFAULT_SOURCES`），
    而基线那 14 格跑的是真的 `main()`。少这一道，「跑一遍基线」等于往境外发十几个请求，
    而这台挂着全局代理的开发机上它们还会多半成功 —— 那档既慢又假（2.8／2.16 讲的正是这个），
    而且哪天断网它就整片红，红的还不是判据。

    它只保证「想发就炸」：抛 `AssertionError`，被 `report()` 那个 `except Exception` 收成一行人话
    （寅那一格就是拿这件事当证据的），所以每格不必各自防。

    >>> import urllib.request
    >>> before = urllib.request.urlopen
    >>> with no_network():
    ...     urllib.request.urlopen is before
    False
    >>> urllib.request.urlopen is before        # 出得来：替身不许留给后面的步骤
    True
    >>> with no_network():
    ...     try:
    ...         urllib.request.urlopen("https://e.erw.cc/e.xml.gz")
    ...     except AssertionError as e:
    ...         print(e)
    --self-test 这一档一个请求都不许发
    """
    def refuse(*_a: object, **_kw: object) -> bytes:
        raise AssertionError("--self-test 这一档一个请求都不许发")

    before = urllib.request.urlopen
    urllib.request.urlopen = refuse                 # type: ignore[assignment]
    try:
        yield
    finally:
        urllib.request.urlopen = before             # type: ignore[assignment]


class Cell(NamedTuple):
    """一格基线：沙盒里种什么、用什么参数问它、期望屏幕上出现什么、不许出现什么。

    `files` 是**这一格额外要的文件**（共用的那十件由 `FIXTURES` 先种好），键是沙盒里的相对路径，
    值里的 `{T}` 在落盘前换成这一轮沙盒的真路径（配置里那条本地地址要用它）；`dirs` 造成目录、
    `bins` 造成非 UTF-8 的件。`argv` 里 `{T}` 跑之前换成真路径，`has`／`lacks` 里写 `<T>`，
    因为屏幕上那串临时路径跑之前谁也不知道（`hide_tmp` 负责抹回来）。
    """
    who: str
    what: str
    rc: int
    files: tuple[tuple[str, str], ...] = ()
    dirs: tuple[str, ...] = ()
    bins: tuple[str, ...] = ()
    argv: tuple[str, ...] = ()
    has: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()
    once: tuple[str, ...] = ()


def targets_local(*names: str) -> tuple[str, ...]:
    """候选位置该写的样子：把沙盒里的件名换成 `{T}/件名`，一格可能要两三条。

    为什么单独一层：`--self-test` 所有格都必须用本地件当候选，一写漏就变成真去下载
    —— 而 `no_network` 会把那件事**变成屏幕上的一行字**而不是报错，所以更要靠这一层少写错。

    >>> print(" ".join(targets_local("好单.xml")))
    {T}/好单.xml
    >>> print(" ".join(targets_local("好单.xml", "旧单.xml")))
    {T}/好单.xml {T}/旧单.xml
    """
    return tuple(f"{{T}}/{n}" for n in names)


def argv_of(*rest: object, playlist: str = "表.m3u") -> tuple[str, ...]:
    """拼一格用的 argv：`--playlist` 与钉死的 `--today` 打头，剩下的逐格自己写。

    `rest` 里既可以塞一个 `targets_local(...)` 出来的元组，也可以塞裸的串（`--against` 那种），
    混着写也行 —— 拼完一律摊平，格子里就不用管第几个位置是参数、哪几个是候选。
    `playlist` 做成**关键字**参数正是因为这一点：候选永远写在末尾，第一件东西不该是表名。
    第一遍我把它写在首位，八格整整齐齐把 `('--target',)` 当成了表名去读，退一色 2。

    >>> print(" ".join(argv_of(targets_local("好单.xml"))))
    --playlist {T}/表.m3u --today 20260923 {T}/好单.xml
    >>> print(" ".join(argv_of("--against", "{T}/漂移表.m3u", targets_local("好单.xml"),
    ...                        playlist="同名表.m3u")))
    --playlist {T}/同名表.m3u --today 20260923 --against {T}/漂移表.m3u {T}/好单.xml
    """
    flat: list[str] = []
    for item in rest:
        flat.extend([str(x) for x in item] if isinstance(item, tuple) else [str(item)])
    return ("--playlist", f"{{T}}/{playlist}", "--today", TODAY, *flat)


def argv_cfg(which: str) -> tuple[str, ...]:
    """不给候选、只给 `--config` 的那两格：那种走「配置里那两条 + 默认候选」这一支。

    >>> print(" ".join(argv_cfg("坏配置.yaml")))
    --playlist {T}/表.m3u --today 20260923 --config {T}/坏配置.yaml
    """
    return argv_of() + ("--config", f"{{T}}/{which}")


BASELINE: tuple[Cell, ...] = (
    # ———— 甲／乙／丙：三个常态读数。0 = 全对，1 = 量到了毛病，且三种 1 各有各的说法 ————
    Cell("甲_本地单子全按id配上", "常态：不发请求、台台按 id 对上，退 0 且「来历」那一句要说得出口",
         0, argv=argv_of(targets_local("好单.xml")),
         has=("按 tvg-id 配上 1 个", "合计 1/1",
              "这张表的 id 就是这一份节目单那一套（1 个全按 id 配上）",
              "结论：1 个候选里，1 个", "这一轮一个请求都没发"),
         lacks=("改 id 就能配上", "一个请求都不许发", "Traceback", "取不到")),
    Cell("乙_旧快照没有今天", "200 也拿得到、可里面没今天：那是「量到了、不能用」，退 1",
         1, argv=argv_of(targets_local("旧单.xml")),
         has=("没有今天的内容（覆盖 1 天：20260807，距今 47 天）", "结论：1 个候选里，0 个"),
         # 「今天有节目」这四个字不算判据：结论行「既今天有节目、又配得上」里原样带着它，
         # 所以这一格要 lack 的是带括号那一档（`coverages()` 的 docstring 里同一条坑）。
         lacks=("今天有节目（", "✗ 取不到", "Traceback", "第一个可用的那份")),
    Cell("丙_取不到的候选", "文件不在的那一条要塌成一行字，而且结论里不许冒充「第一个可用的那份」",
         1, argv=argv_of(targets_local("并不存在.xml")),
         has=("✗ 取不到：FileNotFoundError", "结论：1 个候选里，0 个"),
         lacks=("Traceback", "第一个可用的那份")),
    # ———— 丁／戊／己：2.63 那一族「分母整个读不进来」。三种读法各钉一格，退的都是 2 ————
    Cell("丁_表指到目录", "`--playlist` 指到目录：以前崩 `IsADirectoryError` 退 1（=「候选全不能用」）",
         2, dirs=("目录.m3u",), argv=argv_of(targets_local("好单.xml"), playlist="目录.m3u"),
         has=("订阅表读不进来，不量了：<T>/目录.m3u —— 那是个目录，不是文档",),
         lacks=("Traceback", "IsADirectoryError", "结论：", "候选：")),
    Cell("戊_表不是UTF-8", "同一族第二种：改名没用，所以那句也不许写成「那是个目录」",
         2, bins=("坏件.m3u",), argv=argv_of(targets_local("好单.xml"), playlist="坏件.m3u"),
         has=("读不出来：",), lacks=("那是个目录", "文件不在", "Traceback", "UnicodeDecodeError")),
    Cell("己_表根本不在", "第三种：这一档 2.63 之前就会说人话，留着它是为了钉「三种只有一份说法」",
         2, argv=argv_of(targets_local("好单.xml"), playlist="没这个.m3u"),
         has=("文件不在",), lacks=("那是个目录", "读不出来", "Traceback")),
    # ———— 庚／辛：同一个合计数、两种来历（2.31 那一课），加上一格「一个都没配上」 ————
    Cell("庚_全靠台名救回", "与甲同一个「合计 1/1」，来历却完全相反 —— 只看合计数就会读反的那一格",
         0, argv=argv_of(targets_local("陌生单.xml")),
         has=("按 tvg-id 配上 0 个", "再靠台名救回 1 个", "合计 1/1",
              "没有一个 id 来自这一份节目单（1 个全靠台名救回）", "改 id 就能配上的：湖南卫视"),
         lacks=("2.19 那一层已经落进这张表", "Traceback")),
    Cell("辛_一个台都没配上", "单子有今天的节目、可一个台都对不上：`usable()` 那种「合计 0」不算可用",
         1, argv=argv_of(targets_local("别人单.xml")),
         has=("今天有节目（1 个台有条目）", "合计 0/1",
              "一个台都没配上，看不出这张表的来历", "配不上的 1 个：湖南卫视",
              "结论：1 个候选里，0 个"),
         lacks=("改 id 就能配上", "Traceback", "第一个可用的那份")),
    # ———— 壬／癸／子：`--against` 那一层。癸是 2.64 当场量出来的第一处漏判 ————
    Cell("壬_against读不进来且候选也坏", "两笔账各说各的：这一格在 2.64 之前只报候选那句，「有一项没量」被吞掉",
         1, dirs=("目录.m3u",),
         argv=argv_of("--against", "{T}/目录.m3u", targets_local("旧单.xml")),
         has=("！--against 那张表读不进来：<T>/目录.m3u —— 那是个目录，不是文档",
              "这一屏有一项没量", "结论：1 个候选里，0 个"),
         once=("这一屏有一项没量",), lacks=("这一屏量到了", "Traceback")),
    Cell("癸_against量到台名换id", "**2.64 补的那处漏判**：屏幕上报「变了 1 个」，退码以前是 0",
         1, argv=argv_of("--against", "{T}/漂移表.m3u", targets_local("好单.xml")),
         has=("**1 个的 tvg-id 变了**", "这一屏量到了 1 个台名的 tvg-id 变了", "结论：1 个候选里，1 个"),
         lacks=("tvg-id 一个都没变", "这一屏有一项没量", "Traceback")),
    Cell("子_against一个都没变", "对照格：跨天重出表要的就是这一格的样子",
         0, argv=argv_of("--against", "{T}/同表.m3u", targets_local("好单.xml")),
         has=("**tvg-id 一个都没变**", "结论：1 个候选里，1 个"),
         lacks=("这一屏量到了", "这一屏有一项没量", "Traceback")),
    # ———— 丑／寅：`--config` 那一层。丑是 2.64 当场量出来的第二处：什么都没量到却退 1 ————
    Cell("丑_配置读不动", "地址全从配置里读，读不动就一个候选都没有 —— 那是 2，不是 1",
         2, argv=argv_cfg("坏配置.yaml"),
         has=("配置读不动，不量了：", "一个候选都没查"),
         lacks=("Traceback", "结论：", "候选：", "YAML 读不出来")),
    Cell("寅_关着的那条照样量", "配置写着 `enabled: false`：句子要说「没参与」，而默认那四条在这档里必须炸",
         0, argv=argv_cfg("关配置.yaml"),
         has=("但 `enabled: false`", "下面照量它、只当候选",
              "取不到：AssertionError: --self-test 这一档一个请求都不许发", "结论：5 个候选里，1 个"),
         lacks=("配置里在用", "Traceback", "这一轮一个请求都没发")),
    # ———— 卯：表本身有 2.14 那种「同名两 id」，分母要说清是按 (id, 台名) 数的 ————
    Cell("卯_同名两种id", "同一个台名两种 id：那种台在命中率里是隐形的，得点名且算两个台",
         0, argv=argv_of(targets_local("好单.xml"), playlist="同名表.m3u"),
         has=("⚠️ 1 个台名在这张表里有两种以上的 tvg-id", "这种台算两个", "我们这张表 2 个频道",
              "合计 2/2"),
         lacks=("每个台名只有一种 tvg-id", "Traceback")),
)


def run_cell(cell: Cell, base: Path) -> tuple[str, str, str]:
    """跑一格：`(判定, 给人看的那句, 抹过沙盒路径的原文)`，判定是 `ok` / `bad` / `崩`。

    走的是真的 `main()` 而不是中间函数：退码、stderr 上那行点名、结论那一句，全是这一格要看的
    东西（2.56 起的同一取舍）。stdout 与 stderr 收进**同一个**缓冲区再比 —— 这一把尺最要紧的
    三句话里有两句在 stderr 上（「订阅表读不进来」「配置读不动」）。
    """
    for rel, body in FIXTURES + cell.files:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body.replace("{T}", str(base)), encoding="utf-8")
    for rel in cell.dirs:
        (base / rel).mkdir(parents=True, exist_ok=True)
    for rel in cell.bins:
        (base / rel).write_bytes(NON_UTF8)
    argv = [a.replace("{T}", str(base)) for a in (cell.argv or argv_of())]
    buf = io.StringIO()
    try:
        with no_network(), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
    except Exception as e:                        # 尺自己炸了不许读成「这格没过」以外的任何东西
        return "bad", f"跑这一格时抛了 {type(e).__name__}: {e}", ""
    text = hide_tmp(buf.getvalue(), base)
    good, why = check_cell(cell, rc, text)
    return ("ok", "", text) if good else ("bad", why, text)


def check_cell(cell: Cell, rc: int, text: str) -> tuple[bool, str]:
    """这一格对上了没有：退码、该出现的句子、不该出现的句子、只许出现一次的句子。

    `lacks` 与 `has` 一样重要：这一族的毛病正是「同一件事有几种说法，而它们会互相冒充」——
    「读不出来：」那一格若写成「文件不在」，退码照样对、句子照样有，只有 `lacks` 拦得住。
    """
    if rc != cell.rc:
        return False, f"退码：期望 {cell.rc}，实际 {rc}"
    for s in cell.has:
        if s not in text:
            return False, f"屏幕上没有那句：{s}"
    for s in cell.lacks:
        if s in text:
            return False, f"多说了那句：{s} —— 误伤"
    for s in cell.once:
        if text.count(s) != 1:
            return False, f"那句出现了 {text.count(s)} 次，期望恰好 1 次：{s}"
    return True, ""


def sloppy_cells(cells: tuple[Cell, ...]) -> list[str]:
    """格子自己写歪的地方（占位符串错位、同一句又 `has` 又 `lacks`、一句都没钉）。

    为什么要有：`{T}` 是给 argv 用的，写进 `has` 就是作者把两个占位符弄混了 —— 那一格会
    **永远红**，红得像判据坏了。`has` 与 `lacks` 撞同一句则永远不可能满足。这两种都在跑之前
    拦掉，别让人去怀疑那把尺（2.58 的 `ragged_cells` 同一层）。

    >>> sloppy_cells((Cell("好", "x", 0, has=("合计 1/1",), lacks=("取不到",)),))
    []
    >>> for why in sloppy_cells((Cell("坏", "x", 0, has=("{T}/a",)),)): print(why)
    坏：`has` 里写了 `{T}`，argv 才用这个占位符，屏幕上的路径要写 `<T>`
    >>> for why in sloppy_cells((Cell("撞", "x", 0, has=("一句",), lacks=("一句",)),)): print(why)
    撞：同一句既是 `has` 又是 `lacks`，这一格永远不可能过
    >>> for why in sloppy_cells((Cell("空", "x", 0),)): print(why)
    空：这一格一句都没钉，只比退码 —— 那是「跑过一遍」不是「量过一件事」
    """
    out: list[str] = []
    for c in cells:
        if any("{T}" in s for s in c.has + c.lacks + c.once):
            out.append(f"{c.who}：`has` 里写了 `{{T}}`，argv 才用这个占位符，"
                       "屏幕上的路径要写 `<T>`")
        if set(c.has) & set(c.lacks):
            out.append(f"{c.who}：同一句既是 `has` 又是 `lacks`，这一格永远不可能过")
        if not (c.has or c.lacks or c.once):
            out.append(f"{c.who}：这一格一句都没钉，只比退码 —— 那是「跑过一遍」不是「量过一件事」")
    return out


def self_test(cells: tuple[Cell, ...] | None = None) -> int:
    """`--self-test`：每格一个**新**沙盒，逐格对期望；结论行带「扫了」那个词给 `selfcheck` 挑。

    每格单独一个临时目录是 2.63 踩的第 5 条换来的：同一秒内字节数相同的两份改动写进同一个文件名，
    `import` 与文件系统都会拿到上一格的东西（那遍整批作废）。退码：0 = 每格都符合期望；
    1 = 有格子不符（逐格点名）；2 = 一格都没跑起来，或基线自己写歪了。
    """
    cells = BASELINE if cells is None else cells
    bad_names = guard_names([c.who for c in cells])
    if bad_names:
        print(bad_names)
        return 2
    sloppy = sloppy_cells(cells)
    if sloppy:
        print("基线自己有格子写歪了，改的是基线、不是判据：\n  " + "\n  ".join(sloppy))
        return 2
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    for cell in cells:
        with tempfile.TemporaryDirectory(prefix="epg-check-selftest-") as td:
            verdict, why, text = run_cell(cell, Path(td))
        ran += 1
        if verdict != "ok":
            bad += 1
            fails.append((cell, why, text))
            continue
        print(f"  ✓ {cell.who:<22} {cell.what}")
    if fails:
        print(f"\n—— 以下 {len(fails)} 格不符期望（每格把自己那一遍的原文摊出来）——")
        for cell, why, text in fails:
            print(f"  ✗ {cell.who:<22} {cell.what}\n      {why}")
            for line in text.strip().splitlines():
                print(f"      | {line}")
    print(f"\n扫了基线 {len(cells)} 格：{bad} 格不符期望"
          + (" —— 那把尺还咬得动" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="EPG 可用性与命中率体检（只读，不写任何产物）")
    ap.add_argument("targets", nargs="*", default=None,
                    help="EPG 地址或本地文件；不给就查默认那几个候选")
    ap.add_argument("--playlist", default=str(ROOT / "data" / "output" / "aptv.m3u"),
                    help="拿哪张订阅表来对命中率（默认 aptv.m3u）")
    ap.add_argument("--today", default="", help="按哪天判「今天有没有节目」，YYYYMMDD；默认本机今天")
    ap.add_argument("--timeout", type=int, default=40)
    ap.add_argument("--config", default=str(ROOT / "config" / "epg.yaml"),
                    help="用 build 那同一个读法（src.cli.load_epg_config）取 url / backup_url，"
                         "并照它的状态印一句（默认 config/epg.yaml）")
    ap.add_argument("--against", default="",
                    help="再拿另一张订阅表对一遍「同一个台名的 tvg-id 变了几个」"
                         "（跨天重出表时这里应该是 0；量到了变动就退 1，2.64 起）")
    ap.add_argument("--self-test", action="store_true",
                    help="不问 EPG，只问这把尺自己还咬得动吗：往临时沙盒里种基线那几格表，"
                         "一格一格看退码和屏幕上的句子对不对得上（一个请求都不发，也不需要 --playlist 真的存在）")
    add_doctest_flag(ap)
    args = ap.parse_args(argv)
    door_rc = arg_door_exit(args, argv)   # 2.80：那一判要读 argv —— 薄门旁边跟了字也点名
    if door_rc is not None:
        return door_rc
    answered = arg_door_answered(args)
    if answered == DOCTEST_FLAG:
        return run_own(sys.modules[__name__])   # 2.69：先答说明书，一个请求都不发
    if answered == SELF_TEST_FLAG:
        return self_test()

    cfg = Path(args.config)
    try:
        targets = candidates(args.targets, cfg)
    except ValueError as e:
        # 2.36 那条规矩：配置读不进去要说人话。这里和 build 共用同一个读法，
        # 所以「键名写歪」「地址排成两行」这些年在 build 那边怎么拦，在这边就怎么拦。
        print(f"配置读不动，不量了：{e}", file=sys.stderr)
        # 2.64：退码以前是 1，可这一支什么都没量到 —— 候选地址就存在这份配置里，
        # 配置读不动 = 分母是空的，跟「量到了、四个候选都不能用」不是一件事。
        # 装基线那格（丑）之前没人撞见过，因为平时都喂命令行地址（`selfcheck` 的 `epg` 那步就是这么跑的）。
        print("一个候选都没查：地址是从这份配置里读的 —— 按 2.62 立的口径退 2（什么都没量到），"
              "1 留给「量到了、但有一处毛病」。", file=sys.stderr)
        return 2
    path = Path(args.playlist)
    channels, head_url, why = rows_and_header(path)
    if why:
        # 这张表是这一整屏的分母：它读不进来，下面那些「配上几个台」一个都不成立 ——
        # 「这把尺什么都没量到」那一档按 2.62 立的口径是退 **2**。以前只认「不在」那一档
        # （而且退 1），指到目录和非 UTF-8 直接崩栈，三种都落在 1 = 「候选全不能用」那一档上。
        print(f"订阅表读不进来，不量了：{path} —— {why}", file=sys.stderr)
        return 2
    drift_skipped = False
    today = args.today or datetime.now().strftime("%Y%m%d")
    changed: list = []          # `--against` 量到的「台名换了 id」；没给 --against 就是空
    if args.against:
        other = Path(args.against)
        other_rows, _other_url, other_why = rows_and_header(other)
        if other_why:
            # 这一段量不到，可 EPG 那几个候选照样量 —— 那是「量到了、有一块没量到」，退 1（见收尾）
            print(f"！--against 那张表读不进来：{other} —— {other_why} —— id 漂移那一段这次没量",
                  file=sys.stderr)
            drift_skipped = True
        else:
            d = id_drift(channels, other_rows)
            changed = d["changed"]
            print(f"id 漂移：{path} 相对 {other}")
            print("\n".join(drift_lines(d)))
            print()
    print(f"对表：{path.name}（{len(channels)} 个频道）  今天：{today}")
    print(f"这张表头部写的节目单地址：{head_url or '（没写）'}"
          "　—— 电视自己去取的就是这一行，它和下面那行「来历」是两条独立的代码路径")
    if args.targets:
        print(f"候选：命令行给的 {len(targets)} 条（--config 这次没用上）")
    else:
        in_use, state = from_config(cfg)
        rel = cfg.relative_to(ROOT) if str(cfg).startswith(str(ROOT) + "/") else cfg
        print(f"候选：{len(targets)} 条" + config_line(str(rel), in_use, state))
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
        print("这张表里每个台名只有一种 tvg-id（没有 2.14 那种「同名两 id」；"
              "至于这些 id 是谁定的，看每个候选下面那行「这张表的来历」）")
    print()
    ok = 0
    prov = ""
    for t in targets:
        lines = report(t, channels, today, timeout=args.timeout)
        print("\n".join(lines))
        if usable(lines):
            ok += 1
            prov = prov or provenance_of(lines)   # 只认第一个**可用**的候选，取不到的不说
    print(f"结论：{len(targets)} 个候选里，{ok} 个既今天有节目、又配得上我们表里的台。"
          + (f" 这张表相对第一个可用的那份：{prov}。" if prov else ""))
    rc = exit_code(len(targets), ok, drift_skipped=drift_skipped, id_changed=bool(changed))
    # 两档「退 1 却不是候选的错」各自说一句，互不看对方在不在。
    # 以前那一句带着一道「只有我一个原因」的门（`exit_code(len(targets), ok) != rc`），
    # 于是候选也全坏的时候「有一项没量」就整个不说 —— 那是把两笔账并成一笔，
    # 和 2.62 那把尺上的「分母被动过却要装作只有一件事」同形。2.64 起门拆掉。
    if drift_skipped:
        print("这一屏有一项没量：id 漂移（上面那条「读不进来」）—— 所以退 1，不是 0。")
    if changed:
        print(f"这一屏量到了 {len(changed)} 个台名的 tvg-id 变了 —— 电视上的收藏、隐藏都挂在 id 上，"
              "所以退 1，不是 0（哪怕上面那些候选全都可用）。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
