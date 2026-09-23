"""输出 m3u 与运行报告。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.check.history import Suggestion  # 建议行的格式只有一份实现（2.17）
from src.check.scope import (  # 「跟上一轮比」那一段的措辞只有一份实现（2.51）
    diff_rule_rounds, rule_diff_lines)  # 前者只给下面的 doctest 当「形状由生产者给」的样板

_M3U_ATTRS = ("tvg-id", "tvg-name", "tvg-logo", "group-title")

# 一行里装不下的字符：控制符（含 \r \n）、U+2028/29 这两行分隔符。
_CTRL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")
_MULTI_SPACE = re.compile(r" {2,}")


def one_line(value: object) -> str:
    """把一个要写进 m3u 的值压成「待在一行里、且不顶破属性引号」的字符串。

    三件事，按危害排：

    1. 换行 -> 空格。不压掉的话一条 `#EXTINF` 会裂成几行，多出来的那半截被播放器
       当成一条线路地址 —— 那是**往表里凭空加台**，比台名难看严重得多。
    2. 双引号 -> 单引号。属性是 `k="v"` 拼出来的，值里一个 `"` 就把后面所有属性顶错位；
       m3u 没有反斜杠转义这一说（各家都是拿正则找下一个 `"`），所以只能换个字符。
    3. 首尾空白去掉、连续空白收成一个空格（台名本来就有空格，`CCTV 1` 不动）。

    全项目**自己拼 `#EXTINF` 的只有两处**：这里的 `extinf()`，和
    `scripts/probe_pack.py` 里那张试播包（2.35 起它 import 这个函数，规则只有一份）。

    >>> one_line('CCTV"1')
    "CCTV'1"
    >>> one_line("湖南\\n卫视为单位")
    '湖南 卫视为单位'
    >>> one_line("  金鹰纪实  ")
    '金鹰纪实'
    >>> one_line("湖南\t综合")
    '湖南 综合'
    >>> one_line('http://e/x.xml"y')
    "http://e/x.xml'y"
    >>> one_line(None), one_line("")
    ('', '')
    >>> one_line("湖南\u2028本地")        # 行分隔符也算换行
    '湖南 本地'
    >>> one_line("金鹰纪实“高清”")        # 全角弯引号不动：顶破属性的是半角 "
    '金鹰纪实“高清”'
    """
    text = _MULTI_SPACE.sub(" ", _CTRL.sub(" ", str(value if value is not None else "")))
    return text.replace('"', "'").strip()


def write_artifacts(out_dir: Path | str, files: dict[str, str]) -> list[Path]:
    """把**已经全部算好了**的产物一份一份原子替换进目录，返回写出去的路径。

    为什么要有这么一道（2.37 实测出来的）：`build` 原来是算一份写一份，
    于是「算第二份的时候崩」会把第一份留在半截状态。一份合法、只是没有
    `hunan_local` 分组的频道配置，就把 `aptv.m3u` 从 453 行盖成 7 行，
    然后才崩在下一句 `group_title()` —— 而 `data/output/` 是电视正在订阅的那个目录，
    盖掉的上一版不会自己回来。收成一个写段之后：任何一步算不出来，
    目录里一个字节都不动；真的开始写了，每份也是 `.tmp` + `os.replace` 换上去，
    单个文件没有「写了一半」这个状态（磁盘满只留下一个 `.tmp`，旧表还在原位）。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d)
    ...     _ = write_artifacts(p, {"a.m3u": "#EXTM3U\\n", "b.md": "x\\n"})
    ...     (p / "a.m3u").read_text(), sorted(x.name for x in p.iterdir())
    ('#EXTM3U\\n', ['a.m3u', 'b.md'])

    目录不存在会建出来，`.tmp` 不留残渣：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "sub" / "out"
    ...     len(write_artifacts(p, {"a.m3u": "#EXTM3U\\n"})), p.is_dir(), sorted(x.name for x in p.iterdir())
    (1, True, ['a.m3u'])

    旧的长内容整份换掉，不留半截：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "aptv.m3u"
    ...     _ = p.write_text("A" * 5000)
    ...     _ = write_artifacts(d, {"aptv.m3u": "B" * 10})
    ...     p.read_text()
    'BBBBBBBBBB'

    没有内容要写就是这个函数什么都不做（连目录都不碰），别拿它当「清空目录」用：

    >>> import os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "out"
    ...     write_artifacts(p, {}), p.exists()
    ([], False)
    """
    out_dir = Path(out_dir)
    if not files:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in files.items():
        dst = out_dir / name
        tmp = out_dir / f"{name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, dst)                    # 同一个目录里换，是原子的
        written.append(dst)
    return written


# 报告里的可达范围表：key 与 config/reachability.yaml 的分档同名
_SCOPE_LABEL = {
    "public": ("公网", "Wi-Fi 直连，能播就能看"),
    "iptv_intranet": ("运营商 IPTV 内网", "要对应运营商的 IPTV 专网，家庭 Wi-Fi 上表现为超时"),
    "audio_only": ("纯音频电台", "上游挂在电视频道名下，点开只有声音"),
}


@dataclass(slots=True)
class OutputChannel:
    name: str
    group_title: str
    tvg_id: str
    logo: str = ""
    urls: list[str] = field(default_factory=list)
    order: tuple = ()

    def extinf(self) -> str:
        """渲染一条 `#EXTINF`。

        值全部过 `one_line()`：这一行的结构靠 `k="v"` 和「一行一条」撑着，
        台名里冒出一个 `"` 或换行就是**破结构**，不是难看（2.35 复现过）。

        >>> ch = OutputChannel(name="湖南卫视", group_title="湖南本地", tvg_id="hunan1")
        >>> print(ch.extinf())
        #EXTINF:-1 tvg-id="hunan1" tvg-name="湖南卫视" group-title="湖南本地",湖南卫视
        >>> ch = OutputChannel(name='CCTV"1', group_title="央视", tvg_id="cctv1")
        >>> print(ch.extinf())                       # 引号换掉，后面那个属性才没被顶错位
        #EXTINF:-1 tvg-id="cctv1" tvg-name="CCTV'1" group-title="央视",CCTV'1
        >>> print(OutputChannel(name="湖南\\n卫视为单位", group_title="", tvg_id="").extinf())
        #EXTINF:-1 tvg-name="湖南 卫视为单位",湖南 卫视为单位
        >>> print(OutputChannel(name="\\n", group_title="", tvg_id="").extinf())
        #EXTINF:-1 ,
        """
        vals = (one_line(v) for v in (self.tvg_id, self.name, self.logo, self.group_title))
        attrs = " ".join(f'{k}="{v}"' for k, v in zip(_M3U_ATTRS, vals) if v)
        return f"#EXTINF:-1 {attrs},{one_line(self.name)}"


def format_m3u(channels: Iterable[OutputChannel], epg_url: str = "") -> str:
    """渲染 m3u 文本。

    同名频道连续出现即为 APTV 的多线路；这里每个 OutputChannel 只输出一条，
    多线路靠调用方把同一频道的多条 url 合并进 urls 实现。

    两条性质都是「结构」而不是「好看」：头部一行、一条线路恰好两行（`#EXTINF` + 地址）。
    地址本身不加工（判断线路好坏不归这里管），但 `strip()` 掉首尾空白，
    空地址不写 —— 写了就是凭空多出一行会被当成地址的东西。

    >>> a = OutputChannel(name="湖南卫视", group_title="湖南本地", tvg_id="hunan1",
    ...                   urls=["http://x/1.m3u8", "http://y/2.m3u8"])
    >>> b = OutputChannel(name="金鹰卡通", group_title="金鹰系", tvg_id="",
    ...                   logo="http://l/p.png", urls=["http://z/3.m3u8"])
    >>> print(format_m3u([a, b], epg_url="https://e.erw.cc/e.xml.gz"), end="")
    #EXTM3U x-tvg-url="https://e.erw.cc/e.xml.gz"
    #EXTINF:-1 tvg-id="hunan1" tvg-name="湖南卫视" group-title="湖南本地",湖南卫视
    http://x/1.m3u8
    #EXTINF:-1 tvg-id="hunan1" tvg-name="湖南卫视" group-title="湖南本地",湖南卫视
    http://y/2.m3u8
    #EXTINF:-1 tvg-name="金鹰卡通" tvg-logo="http://l/p.png" group-title="金鹰系",金鹰卡通
    http://z/3.m3u8
    >>> len(format_m3u([a]).strip().splitlines())    # 2 条线路 = 1 头 + 4 行
    5
    >>> format_m3u([]) == "#EXTM3U" + chr(10)        # 空表：一行头部，且以换行结尾
    True
    >>> lone = OutputChannel(name="x", group_title="", tvg_id="", urls=[])
    >>> format_m3u([lone]) == "#EXTM3U" + chr(10)    # 一个台没有线路 = 除了头部什么都不写
    True
    >>> one = OutputChannel(name="x", group_title="", tvg_id="", urls=["http://x/1.m3u8"])
    >>> print(format_m3u([one], epg_url='http://e/x.xml"y'), end="")   # 头部同样不许被顶破
    #EXTM3U x-tvg-url="http://e/x.xml'y"
    #EXTINF:-1 tvg-name="x",x
    http://x/1.m3u8

    写出去的东西拿**本项目自己的解析器**读回来（另一条实现，不是自己印证自己）：

    >>> from src.parse.m3u import parse_m3u
    >>> nasty = [OutputChannel(name='CCTV"1\\n综合', group_title='央"视', tvg_id="cctv1",
    ...                        urls=["http://x/1.m3u8", "  ", "http://y/2.m3u8"])]
    >>> pl = parse_m3u(format_m3u(nasty, epg_url="https://e/x.gz"))
    >>> [(e.name, e.tvg_id, e.group, e.url) for e in pl.entries]
    [("CCTV'1 综合", 'cctv1', "央'视", 'http://x/1.m3u8'), ("CCTV'1 综合", 'cctv1', "央'视", 'http://y/2.m3u8')]
    >>> pl.x_tvg_url, pl.skipped                     # 头部完好；那个空地址没变成一条假线路
    ('https://e/x.gz', 0)
    """
    head = f'#EXTM3U x-tvg-url="{one_line(epg_url)}"' if epg_url else "#EXTM3U"
    out = [head]
    for ch in channels:
        for url in ch.urls:
            u = str(url).strip()
            if not u:
                continue
            out.append(ch.extinf())
            out.append(u)
    out.append("")
    return "\n".join(out)


def _stamp(at: str) -> str:
    """`2026-09-21T13:00:40+08:00` -> `2026-09-21 13:00`。"""
    return str(at)[:16].replace("T", " ")


_VERDICT_LABEL = {
    "drop": "**建议关掉**", "demote": "建议往后挪", "promote": "建议往前挪",
    "keep": "不动", "thin": "先看一轮",
}


def _source_section(h: dict) -> list[str]:
    """把主机那一层的「该划掉谁」摊到上游源上，并给出能直接抄的 `sources.yaml` 行。

    判据全在 `history.priority_suggestions()`，这里只负责说人话。
    一条都不建议的时候也要把「为什么没有」讲出来 —— 空表容易被读成「功能没跑」。

    >>> S = dict(source="gd", verdict="demote", from_prio=3, to_prio=5,
    ...          why="最近一轮 4/41 能播，11 族两轮以上全灭", enabled=True, confirmed=True)
    >>> h = {"sources": [{"source": "gd", "hosts": 12, "runs": 3, "lines": 41, "ok_last": 4,
    ...                   "dead_hosts": 12, "sentenced": 11, "fake_hosts": 0, "best_ms": 0,
    ...                   "shared": 1}],
    ...      "suggestions": [S], "unattributed": 7}
    >>> sec = _source_section(h)
    >>> "按上游源摊开" in "\\n".join(sec)
    True
    >>> "3→5" in "\\n".join(sec) and "`gd`" in "\\n".join(sec)
    True
    >>> "```yaml" in sec                     # 有可抄的行才开代码块
    True
    >>> "# - id: gd" in sec                  # 每段前面点名它属于哪个源
    True
    >>> sum(1 for x in sec if x.startswith("    priority"))
    1
    >>> "2.17 之前" in "\\n".join(sec)        # 没记来源的那些要如实说出来
    True
    >>> keep = {**h, "suggestions": [{**S, "verdict": "keep", "to_prio": 3}]}
    >>> "没有任何一个源达到动手的标准" in "\\n".join(_source_section(keep))
    True
    >>> bfb = {**h, "srcs_backfilled": ["2026-09-21T13:00"]}
    >>> "事后补记" in "\\n".join(_source_section(bfb))      # 出处是重算的，得说清楚
    True
    >>> "事后补记" in "\\n".join(_source_section(keep))     # 没补记就不提
    False
    >>> both = {**h, "never_measured": ["gd", "carrier"]}
    >>> sec = "\\n".join(_source_section(both))
    >>> "`carrier`" in sec and "`gd`）" not in sec
    True
    >>> _source_section({"sources": [], "suggestions": []})
    []
    """
    srs = h.get("sources") or []
    sugg = h.get("suggestions") or []
    by_src = {g["source"]: g for g in sugg}
    out: list[str] = []
    if srs:
        out += ["", f"### 按上游源摊开（{len(srs)} 个源在可信轮次里留了记录）", "",
                "| 源 | 主机族 | 观测轮数 | 最近一轮能播 | 全灭族 | 已判死 | 与他人共用 | 最快 | 建议 |",
                "|---|---|---|---|---|---|---|---|---|"]
        for s in srs:
            g = by_src.get(s["source"]) or {}
            mark = _VERDICT_LABEL.get(g.get("verdict", ""), "—")
            if g and not g.get("confirmed", True):
                mark += "（只一轮，先别动）"
            out.append(f"| `{s['source']}` | {s['hosts']} | {s['runs']} | "
                       f"{s['ok_last']}/{s['lines']} | {s['dead_hosts']} | {s['sentenced']} | "
                       f"{s['shared']} | {str(s['best_ms']) + 'ms' if s['best_ms'] else '—'} | "
                       f"{mark} |")
    moves = [g for g in sugg if g["to_prio"] != g["from_prio"] or g.get("enabled") is False]
    if srs:
        if moves:
            out += ["", "要动就照抄这几行（每个源一段，贴回 `config/sources.yaml` 对应 `- id:` "
                    "那一块，缩进已经对好了）——**代码不会自己改这个文件**，"
                    "改完重跑一次生成来对账：", "", "```yaml"]
            for g in moves:
                out += [f"# - id: {g['source']}"] + Suggestion(**g).yaml_lines()
            out += ["```"]
        else:
            out += ["", "> 没有任何一个源达到动手的标准：要么只看过一轮，"
                    "要么可用率卡在两头都不够的中间（<1/5 才建议往后挪，≥4/5 且 500ms 内才建议往前挪）。"
                    "这张表只提建议，划源仍然是人做的事（计划书 §14）。"]
    bf = h.get("srcs_backfilled") or []
    if srs and bf:
        out += ["", f"> 出处这一列有 {len(bf)} 轮（{'、'.join(bf)}）是**事后补记**的："
                "「这条地址出自哪个上游」不是测出来的，是把当时那份上游缓存重算了一遍"
                "（`scripts/backfill_srcs.py`，对不上出处的宁可留空）。"
                "能播几条、几毫秒那些数字仍是当时实测的。"]
    if h.get("unattributed"):
        out += ["", f"> 另有 {h['unattributed']} 个主机族在履历里**没有来源记录**"
                "（2.17 之前那几轮的存量），它们不进上面这张表、也不会被建议动 —— "
                "在家里补跑一次 `build --verify` 就全补上了。"]
    # 已经在这张表里的源不再列入「从不实测」：那只可能是它以前开着 probe、后来关掉了，
    # 同一份报告里不能既说它没数据又说它 49 族全灭。
    nm = [x for x in (h.get("never_measured") or []) if x not in {s["source"] for s in srs}]
    if srs and nm:
        out += ["", f"> `probe: false` 的源（{'、'.join(f'`{x}`' for x in nm)}）**从不实测**，"
                "所以根本不在这张表里 —— 它们是运营商 IPTV 专网，电脑侧量不到，"
                "该由真机判（计划书 2.9/2.12）。别把「表里没它」读成「它没问题」。"]
    return out


def _history_section(h: dict) -> list[str]:
    """渲染「主机可用性履历」：每轮趋势 + 该从候选里划掉谁。

    单独成函数只为了让 format_report 保持可读；判据都在 src/check/history.py。

    >>> base = {"runs": 2, "used": 2, "egress": "U", "totals": [], "blacklist": [],
    ...         "sources": [], "suggestions": [], "demote": ["a.example"], "fake": [],
    ...         "rolls": {"checked": 0, "stuck": 0}, "latency_hosts": 3,
    ...         "stale_first_lines": 0, "verified": False}
    >>> off = "\\n".join(_history_section(base))
    >>> "本轮生成用到履历的地方" in off and "会被来源优先级挤掉" in off
    True
    >>> on = "\\n".join(_history_section({**base, "verified": True}))
    >>> "本轮生成用到履历的地方" in on          # 实测那一轮不能这么写
    False
    >>> "每条线路都实测过" in on and "挤掉）" not in on
    True
    >>> rep = "\\n".join(_history_section({**base, "replay": "2026-09-21 21:18"}))
    >>> "沿用 2026-09-21 21:18" in rep and "挤掉）" not in rep   # 逐条判决有了，不需要延迟补位那句
    True
    >>> "每条线路都实测过" in rep               # 沿用记录 ≠ 当场测过
    False
    """
    out = ["", "## 主机可用性履历（离线生成时靠它排序）", ""]
    who = f"- 累计 **{h['runs']} 轮**实测，采用 {h['used']} 轮（判据出口 `{h['egress'] or '未知'}`）"
    if h.get("dropped"):
        who += f"，另有 {h['dropped']} 轮未采用"
    if h.get("build_egress"):
        who += (f"；本轮在 `{h['build_egress']}` 上生成，"
                "排序依据仍是判据出口那一次 —— 表最终在电视那张网上播，"
                "开发机的代理不改变这个依据")
    out.append(who)
    out.append("")
    out.append("> 判据只采用「和电视同网、当时体检没报警」的那些轮：换一个测量点，"
               "同一批数字的含义就变了。代理客户端的 TUN 一开，出口跑到境外机房、"
               "DNS 换成 fake-IP，那轮对国内源全是假阴性（计划书 2.8/2.10）。"
               "这种轮次照样存着好看变化，但绝不参与判断。")
    if h.get("totals"):
        out += ["", "| 时间 | 出口 | 实测可用 |", "|---|---|---|"]
        for r in h["totals"]:
            out.append(f"| {_stamp(r['at'])} | `{r.get('egress', '')}` | "
                       f"{r['ok']}/{r['total']} |")
    dead = h.get("blacklist") or []
    if dead:
        out += ["", f"### 从来没通过过的主机（{len(dead)} 个，建议从候选里划掉）", "",
                "| 主机 | 观测轮数 | 最近一轮 |", "|---|---|---|"]
        for r in dead:
            out.append(f"| `{r['host']}` | {r['runs']} 轮全灭 | {r['ok_last']}/{r['total']} |")
        out += ["", "> 只要某一轮里它有一条线路能播，就不算在这里面 —— 中转类主机"
                "「今天全灭、明天全通」是常态（腾讯云那族公网基准 2026-09-21 就从全通掉到整族失效）。"
                "所以要两轮以上从没通过过才判它死刑。",
                "> 划掉的动作是人做的：把 `config/sources.yaml` 里贡献这些主机的源 "
                "`enabled: false` 或调高 `priority`，代码不自动删源。"]
    out += _source_section(h)
    # 这一段在「本轮没实测」时才是排序的真正依据：`--verify` 那一轮每条线路都量过了，
    # 履历判据只落在 `probe: false` 那几条压根没测的线路上，写成「本轮靠它排序」就是假话。
    # 第三种状态是 `--replay`（`h["replay"]` = 沿用那一轮的时间戳）：每条线路都有判决，
    # 但那些判决不是当场量的 —— 所以既不能写「本轮每条线路都实测过」，也不该说
    # 「没实测所以要靠延迟补位」（记录里就带着每条的毫秒数）。
    measured = bool(h.get("verified"))
    replayed = str(h.get("replay") or "")
    bits = []
    if h.get("demote"):
        bits.append(f"把 {len(h['demote'])} 个整族失效的主机往后压了档："
                    + "、".join(f"`{x}`" for x in h["demote"][:8])
                    + ("…" if len(h["demote"]) > 8 else ""))
    if h.get("fake"):
        bits.append(f"把 {len(h['fake'])} 个「连得上但只放循环录像」的主机往后压了档："
                    + "、".join(f"`{x}`" for x in h["fake"][:8])
                    + ("…" if len(h["fake"]) > 8 else "")
                    + "（同一个主机在报告里被点名成"
                      "「第一线是循环录像」时，说明这个台实在没有更好的线路可换）")
    rolls = h.get("rolls") or {}
    if rolls.get("checked"):
        bits.append(f"L3 逐条验过 {rolls['checked']} 条线路的分片窗口，"
                    f"其中 {rolls.get('stuck', 0)} 条一动不动，已单独让它们让位"
                    "（整族那一档要求「通了的全是录像」，一条不动不够）")
    if h.get("latency_hosts"):
        bits.append(f"{h['latency_hosts']} 个主机按上一轮实测延迟补了位"
                    + ("" if (measured or replayed) else
                       "（不补的话，本轮没实测，最好的那条会被来源优先级挤掉）"))
    if bits:
        lead = ("> 履历里另有这些判据" if measured else "> 本轮生成用到履历的地方")
        out += ["", lead + "：" + "；".join(bits) + "。"]
        if measured:
            out[-1] += ("（本轮每条线路都实测过，所以它们只作用在 `probe: false` "
                        "那几条压根没测的线路上）")
        elif replayed:
            out[-1] += (f"（本轮的逐条线路判决沿用 {replayed} 那一轮的记录，不是当场测的，"
                        "所以它们只补在那份记录里没有的线路上）")
        if h.get("stale_first_lines"):
            out[-1] += (f"第一线仍落在已知失效主机上的频道 {h['stale_first_lines']} 个 —— "
                        "那些台只有这一条公网线路，没有更好的可以换。")
    return out


def _epg_section(e: dict | None) -> list[str]:
    """渲染「EPG 对齐」：`tvg-id` 那一列是从哪份节目单反推的、配上多少、改了哪些台。

    三种情况必须分开写，因为在局域网订阅里它们是三种完全不同的故障：

      * **未启用** —— 这一轮没有对齐这回事，`tvg-id` 还是上游「谁先到谁说了算」；
      * **取不到 / 取回来是空单** —— 一个 id 都不改。这是 `apply_ids()` 的安全性质，
        不写明的话，读的人会以为「上游 EPG 一挂就把电视的表搞坏了」；
      * **正常** —— 配上多少、靠哪一列配上的、改了哪几个台。

    「按 id」和「靠台名」两个数要分开报，这是硬要求：erw 那份节目单的 channel id 是 `1`、`81`
    这种纯数字，我们上游抄来的 `tvg-id="CCTV-1综合"` 按 id 一条都对不上，全靠 display-name 救回来
    （计划书 2.19）。只报一个合计就把「这份 EPG 的 id 写法有多不讲理」这件事藏起来了。

    >>> e = {"enabled": True, "url": "http://e.erw.cc/e.xml.gz",
    ...      "header": "http://e.erw.cc/e.xml.gz", "via": "联网",
    ...      "note": "312000 字节（gzip，解出 2400000 字节）", "error": "",
    ...      "coverage": "今天有节目（覆盖 3 天：20260919~20260921）", "ok": True,
    ...      "days": {"20260919": 156, "20260920": 157, "20260921": 18046},
    ...      "epg_channels": 521, "epg_progs": 18359, "generator": "erw",
    ...      "align": {"total": 98, "hit_id": 3, "hit_name": 66,
    ...                "changed": [("CCTV-1综合", "CCTV-1综合", "1"),
    ...                            ("CCTV-10科教", "CCTV-10科教", "10")],
    ...                "miss": ["湘潭新闻综合"], "rows": [], "hunan": 10, "hunan_total": 39}}
    >>> sec = "\\n".join(_epg_section(e))
    >>> "EPG 对齐" in sec and "69/98" in sec
    True
    >>> "按 tvg-id 直接对上 3 个" in sec and "靠台名救回 66 个" in sec
    True
    >>> "312000 字节" in sec and "erw" in sec                      # 来历要能查回去
    True
    >>> "hunan.m3u 那 39 个台里 10 个" in sec
    True
    >>> "20260921 18046 条" in sec and "其实只有最新那天有内容" in sec
    True
    >>> even = "\\n".join(_epg_section({**e, "days": {"20260920": 9000, "20260921": 9300}}))
    >>> "其实只有最新那天" not in even        # 分布均匀时不下那句判断
    True
    >>> 'x-tvg-url="http://e.erw.cc/e.xml.gz"' in sec       # 头部写的是电视取到的那条地址
    True
    >>> any("没有" in l and "x-tvg-url" in l               # 地址不是 http(s) 就宁可不写
    ...     for l in _epg_section({**e, "header": ""}))
    True
    >>> sec.count("| `CCTV-1综合` |") + sec.count("| CCTV-10科教 |")   # 逐台一张表
    2
    >>> "湘潭新闻综合" in sec and "没配上" in sec
    True
    >>> off = "\\n".join(_epg_section({**e, "enabled": False}))
    >>> "未启用" in off and "谁先创建频道桶" in off
    True
    >>> dead = "\\n".join(_epg_section({**e, "ok": False, "epg_channels": 0, "epg_progs": 0,
    ...                                 "days": {}, "coverage": "", "via": "未取到",
    ...                                 "error": "URLError: 连不上",
    ...                                 "align": {**e["align"], "hit_id": 0, "hit_name": 0,
    ...                                           "changed": [], "miss": ["湖南卫视"],
    ...                                           "hunan": 0, "hunan_total": 39}}))
    >>> "一个 tvg-id 都没改" in dead and "URLError" in dead
    True
    >>> "69/98" not in dead                        # 拿不到的时候不许报命中率
    True
    >>> _epg_section(None), _epg_section({})        # 没材料 = 不渲染，跟「未启用」不是一回事
    ([], [])
    >>> "EPG 对齐" in "\\n".join(_epg_section({"enabled": False}))
    True
    """
    if not e:
        return []
    if not e.get("enabled"):
        return ["", "## EPG 对齐（tvg-id 怎么来的）", "",
                "> 这一轮**未启用**（`config/epg.yaml` 没写地址，或者加了 `--no-epg`）："
                "`tvg-id` 还是上游「谁先创建频道桶谁说了算」的写法，"
                "订阅表头部的 `x-tvg-url` 也是抄上游第一条"
                "（2026-09-21 量过：抄来的那条 404，所以这一段本身就是一个提醒）。"
                "启用之后这一段会改成逐台对账（计划书 2.19）。"]

    a = e.get("align") or {}
    total = a.get("total", 0)
    hit = a.get("hit_id", 0) + a.get("hit_name", 0)
    # 头部这一行是给电视看的，跟本机这一份不是一回事：地址不是 http(s) 时宁可不写
    hdr = e.get("header", "")
    hdr_line = (f"- 头部 `x-tvg-url=\"{hdr}\"` 由电视自己去取，本机这一份只用来决定 `tvg-id`"
                if hdr else
                "- 头部**没有** `x-tvg-url`：配置里的地址不是 http(s)，"
                "电视取不到，写进去就是谎话（`epg_header_url()`）")
    out = ["", "## EPG 对齐（tvg-id 怎么来的）", "",
           f"- 节目单：`{e.get('url', '')}` —— 本轮 **{e.get('via', '未取到')}**"
           + (f"，{e['note']}" if e.get("note") else "")
           + (f"，generator `{e['generator']}`" if e.get("generator") else ""),
           f"- 里面 {e.get('epg_channels', 0)} 个频道、{e.get('epg_progs', 0)} 条节目 —— "
           f"{e.get('coverage') or '一条节目都没有'}"]
    days = e.get("days") or {}
    if days:
        # 「覆盖 3 天」这种说法会骗人：各家节目单常常只有今天，另两天是跨午夜的尾巴。
        # 所以把逐天的条数摊开，并且只在「今天占绝对多数」时才下那句判断。
        newest = max(days)
        per = "、".join(f"{d} {n} 条" for d, n in sorted(days.items()))
        rest = sum(v for k, v in days.items() if k != newest)
        tail = ("；**其实只有最新那天有内容**，另两天是跨午夜的尾巴，明天还没有"
                if len(days) > 1 and days.get(newest, 0) and rest < days[newest] * 0.05 else "")
        out.append(f"- 节目条数按天：{per}{tail}")
    if e.get("error"):
        out.append(f"- ⚠️ {e['error']}")
    if not e.get("ok") and not a.get("hit_id") and not a.get("hit_name"):
        out += ["", f"所以这一轮**一个 tvg-id 都没改**：{total} 个台里 0 个配上节目单，"
                "因为根本没有能对照的名单。这是刻意的 —— 上游 EPG 挂掉时这一层不该把"
                "已经在电视上用着的表搞乱，`apply_ids()` 拿到空单什么都不动。",
                "", hdr_line, "",
                "> 本机取不到不代表电视取不到，反之亦然（计划书 2.8："
                "这台开发机的出口和电视那张 Wi-Fi 不是同一个测量点）。"
                "要换成后备地址就改 `config/epg.yaml` 的 `url`（里面记着四个候选的量过的数字），"
                "或者整层关掉 `enabled: false`。"]
        if e.get("caveat"):
            out += ["", f"> {e['caveat']}"]
        return out

    out += [f"- 我们这张表 {total} 个台：按 tvg-id 直接对上 {a.get('hit_id', 0)} 个、"
            f"靠台名救回 {a.get('hit_name', 0)} 个 → **{hit}/{total} 有节目单**",
            f"- hunan.m3u 那 {a.get('hunan_total', 0)} 个台里 {a.get('hunan', 0)} 个"
            "（湖南的市州台在公开节目单里基本不存在，和计划书 2.12「没有公开线路」是同一批台）",
            hdr_line]

    changed = a.get("changed") or []
    if changed:
        out += ["", f"### 被改写 id 的台（{len(changed)} 个）", "",
                "| 频道 | 原来（上游先到的写法） | 现在（节目单里的写法） |", "|---|---|---|"]
        out += [f"| {n} | `{o}` | `{i}` |" for n, o, i in changed[:30]]
        if len(changed) > 30:
            out.append(f"| …另有 {len(changed) - 30} 个 | | |")
        out += ["", "> 以前这些台的 id 取决于哪个上游先创建频道桶："
                "`CCTV-1` 与 `CCTV-1综合` 是同一条线路的两种写法，先到者定，"
                "所以换一批上游、换一个顺序就会换一批 id。"
                "现在只看「这份节目单里到底有哪个 id」，与到达顺序无关。"]

    miss = a.get("miss") or []
    if miss:
        out += ["", f"### 没配上节目单的台（{len(miss)} 个，电视上不会有节目）", "",
                "、".join(miss[:40]) + ("…" if len(miss) > 40 else ""), "",
                "> 两种原因混在这里：一种是这份节目单确实没有这个台（湖南市州台、"
                "各家地面频道大多是这种），另一种是我们的台名和它的 display-name 差太远、"
                "对不上（`src/check/epg.py` 的前缀规则故意不做中文前缀，"
                "免得把「长沙新闻」当成「长沙新闻综合」——那是两个台）。"
                "换一份节目单、或者往 `config/channels.yaml` 里补 alias，都是人在看这张表之后决定。"]
    if e.get("caveat"):
        out += ["", f"> {e['caveat']}"]
    return out


def _fallback_lines(fb: dict, measured: bool = False) -> list[str]:
    """把「点第 2 条线路救得回来吗」那五类写成一句结论（数字来自 `src.cli.second_line_options`）。

    为什么这句话要进报告：验收单上一版写着「这个台不动就点第二条线」，而 2026-09-21 真机上
    湖南那批台整表超时（计划书 2.8）—— 两件同时成立，说明「有第二线」不等于「换得出去」。
    2.25 第一次把它量成数字（39 个可疑的台里 0 个换得到公网电视线路），2.26 把结论搬进报告：
    讲的是这张表的结构，本来就该和「第一线主机集中度」并排，不该每次都要跑一遍试播包脚本才看得到。

    三处容易糊过去的地方：`other_public` 那一项**永远写**（0 才是这一句的结论）；
    电台（`audio_only`）不算救回来 —— 它电脑实测通、有声音，但电视上没画面；
    `scope_known` 为假时不下「没有救法」的结论，只说「判不了」。
    `measured` 管的是 0 个可疑时有没有资格说「都测过」：没有逐条判决时只按可达范围判过，
    话说满了就是把「没查」写成「没问题」。

    >>> F = lambda **kw: dict({"channels": 0, "no_alt": 0, "same_host": 0, "other_intranet": 0,
    ...                        "other_audio": 0, "other_public": 0, "other_unknown": 0,
    ...                        "reasons": {}, "switchable": [], "lands": [], "land_kind": {},
    ...                        "scope_known": True}, **kw)
    >>> print("\\n".join(_fallback_lines(F(), measured=True)))
    - **换第二条线路救得回来吗**：这张表没有一个台需要靠换线路救 —— 每个台的第一线都在本轮判决里，且没有一条落在 IPTV 专网上。
    >>> print("\\n".join(_fallback_lines(F())))        # 没判决时不说「测过」，只说按范围没查出台
    - **换第二条线路救得回来吗**：这张表没有一个台需要靠换线路救 —— 本轮没有逐条判决，按可达范围看第一线不在 IPTV 专网上。
    >>> # 2026-09-22 那张表的形状：一个换不到公网，就把「没有这条救法」写死
    >>> b = F(channels=2, no_alt=1, other_intranet=1, reasons={"专网": 2},
    ...       lands=[("k.example", 1)], land_kind={"k.example": "IPTV 专网"})
    >>> print("\\n".join(_fallback_lines(b)))
    - **换第二条线路救得回来吗**：第一线可疑的 2 个台（专网 2）里，1 个根本没有备选线路、1 个换到别家可那一家仍是 IPTV 专网、**0 个换得到公网电视线路**。
      - 换过去落在：`k.example`（IPTV 专网）1 个台
      - 所以**这张表里没有「换线路」这条救法**：这些台要么没有第二线，要么第二线还在那几家专网出口上。要救得去别处找线路（计划书 P5），或走机顶盒／专网 VLAN。
    >>> # 电台那一类单列：换过去只有声音，不算救回来
    >>> a = F(channels=1, other_audio=1, reasons={"没测过": 1},
    ...       lands=[("ls.qingting.fm", 1)], land_kind={"ls.qingting.fm": "纯音频电台"})
    >>> "1 个换过去是纯音频电台" in "\\n".join(_fallback_lines(a))
    True
    >>> # 真换得到的那些台要点名，让他们去电视上点第二线，而不是说「没有救法」
    >>> c = F(channels=1, other_public=1, reasons={"专网": 1}, switchable=["经视"])
    >>> s = "\\n".join(_fallback_lines(c))
    >>> "换得到公网电视线路的是这几个台**：经视" in s      # 点名，让他们去电视上点第二线
    True
    >>> "没有「换线路」这条救法" not in s                   # 有救法就不写那句结论
    True
    >>> # 没配可达范围：换到别家的落点判不了，就不能硬说这张表没有救法
    >>> u = F(channels=1, other_unknown=1, reasons={"专网": 1}, scope_known=False)
    >>> s = "\\n".join(_fallback_lines(u))
    >>> "判不了" in s and "这条救法" not in s
    True
    """
    head = f"- **换第二条线路救得回来吗**："
    if not fb["channels"]:
        return [head + ("这张表没有一个台需要靠换线路救 —— 每个台的第一线都在本轮判决里，"
                        "且没有一条落在 IPTV 专网上。" if measured else
                        "这张表没有一个台需要靠换线路救 —— 本轮没有逐条判决，"
                        "按可达范围看第一线不在 IPTV 专网上。")]
    kinds = "、".join(f"{k} {n}" for k, n in sorted(fb["reasons"].items()))
    parts = [(f"{fb['no_alt']} 个根本没有备选线路", fb["no_alt"]),
             (f"{fb['same_host']} 个的备选还在同一家机房", fb["same_host"]),
             (f"{fb['other_intranet']} 个换到别家可那一家仍是 IPTV 专网", fb["other_intranet"]),
             (f"{fb['other_audio']} 个换过去是纯音频电台（有声音、没画面）", fb["other_audio"]),
             (f"{fb['other_unknown']} 个换到别家（可达范围没配，判不了那一家）", fb["other_unknown"]),
             # 这一项**永远写**：0 才是这一整段的结论
             (f"**{fb['other_public']} 个换得到公网电视线路**", True)]
    out = [head + f"第一线可疑的 {fb['channels']} 个台（{kinds}）里，"
                  + "、".join(t for t, n in parts if n) + "。"]
    if fb["lands"]:
        out.append("  - 换过去落在：" + "、".join(
            f"`{b}`（{fb['land_kind'].get(b, '范围未知')}）{n} 个台"
            for b, n in fb["lands"][:3])
            + (f"（共 {len(fb['lands'])} 家，只列前 3）" if len(fb["lands"]) > 3 else ""))
    if fb["switchable"]:
        out.append("  - **换得到公网电视线路的是这几个台**：" + "、".join(fb["switchable"][:8])
                   + ("…" if len(fb["switchable"]) > 8 else "")
                   + " —— 真机上这几个台值得点第 2 条线路。")
    elif fb["scope_known"]:
        out.append("  - 所以**这张表里没有「换线路」这条救法**：这些台要么没有第二线，"
                   "要么第二线还在那几家专网出口上。要救得去别处找线路（计划书 P5），"
                   "或走机顶盒／专网 VLAN。")
    else:
        out.append("  - 换到别家的那些台落在公网还是专网，这一轮判不了（没配可达范围）—— "
                   "先补 `config/reachability.yaml` 再决定要不要动排序。")
    return out


def _focus_section(views: list[dict] | None) -> list[str]:
    """渲染「第一线主机集中度」：一张表里第一线落在几家主机上、每家挂着几个台。

    为什么要单独一节：前面那些表都是**逐条**的（这条通、那条是录像），
    而电视上的判断是**逐台**的 —— APTV 只播第一线，所以一家主机的死活直接就是
    它名下那几个台的死活。这两层之间那座桥以前没人搭，于是「真机该先点哪个台」
    只能靠人拿正则去数 m3u（计划书 2.22 就是这么量出来的）。

    两列特别容易读反，所以宁可写长一点：

      * **换线路也换不出去** —— 这个台名下一条线路都不在别的主机上，这才是供给侧的单点。
        光看「挂着几个台」会把我们自己定的排序规则（`--max-per-host` 每条表最多留 2 条、
        循环录像压后）也算成上游的功劳。
      * **第一线没实测过** —— 这条地址在逐条判决里没有记录。**只在真有判决的时候才出这一列**：
        纯离线生成时每个台都「没实测过」，那张表会把「本轮没测」说成「这几家主机都有问题」。
        2026-09-21 那轮 `--verify` 因为 `probe: false` 没给运营商内网发过一个请求，所以这一列
        非 0 的那几行意思是「真机那一次是它们这辈子第一次被判分」。

    >>> views = [{"label": "aptv.m3u", "total": 3, "measured": True,
    ...           "rows": [{"host": "a.cm", "scope": "iptv_intranet", "channels": 2,
    ...                     "alone": 1, "unmeasured": 2, "alt_lines": 1,
    ...                     "sources": ["hn_mobile"], "examples": ["湖南经视", "娄底新闻"]}]}]
    >>> s = "\\n".join(_focus_section(views))
    >>> "第一线主机集中度" in s and "`a.cm`" in s
    True
    >>> "| 2 个台 | 1 | 2 | 1 条 | `hn_mobile` |" in s      # 列的顺序就是表头的顺序
    True
    >>> "运营商 IPTV 内网" in s                              # 范围用读者看得懂的词
    True
    >>> "湖南经视" in s                                       # 例子：告诉你点开哪个台最值
    True
    >>> s2 = "\\n".join(_focus_section([{**views[0], "measured": False}]))
    >>> "没实测过" not in s2                                  # 没判决就不拿这一列吓人
    True
    >>> "\\n".join(_focus_section(None))
    ''
    >>> only1 = [{"label": "x", "total": 3, "measured": False,
    ...           "rows": [{"host": f"h{i}", "scope": "public", "channels": 1, "alone": 1,
    ...                     "unmeasured": 0, "alt_lines": 0, "sources": [], "examples": ["t"]}
    ...                    for i in range(3)]}]
    >>> "一家主机都不共用" in "\\n".join(_focus_section(only1))    # 全是一对一：直说，不硬凑表
    True
    >>> # 2.26：这一节还要回答「换第二条线路救得回来吗」（计划书 2.25 量出来的那五类）
    >>> fb = {"channels": 39, "no_alt": 24, "same_host": 1, "other_intranet": 14,
    ...       "other_audio": 0, "other_public": 0, "other_unknown": 0, "reasons": {"专网": 39},
    ...       "switchable": [], "lands": [("tvgslb.hn.chinamobile.com", 14)],
    ...       "land_kind": {"tvgslb.hn.chinamobile.com": "IPTV 专网"}, "scope_known": True}
    >>> s3 = "\\n".join(_focus_section([{**views[0], "fallback": fb}]))
    >>> "换第二条线路救得回来吗" in s3 and "24 个根本没有备选线路" in s3
    True
    >>> "**0 个换得到公网电视线路**" in s3          # 这一项永远写：0 才是结论
    True
    >>> "tvgslb.hn.chinamobile.com`（IPTV 专网）14 个台" in s3
    True
    >>> "这张表里没有「换线路」这条救法" in s3
    True
    >>> "救得回来吗" in "\\n".join(_focus_section([views[0]]))   # 没给 fallback 就不硬编一句
    False
    >>> s4 = "\\n".join(_focus_section([{**views[0], "fallback": dict(
    ...     fb, channels=0, no_alt=0, same_host=0, other_intranet=0, other_public=0,
    ...     reasons={}, lands=[])}]))
    >>> "没有一个台需要靠换线路救" in s4                        # 0 个可疑也要说出来
    True
    >>> # 集中度那张表不列了（一家主机都不共用），这一问照样要回答 —— 它不靠那张表活着
    >>> "救得回来吗" in "\\n".join(_focus_section([{**only1[0], "fallback": fb}]))
    True
    """
    if not views:
        return []
    out = ["", "## 第一线主机集中度（一家主机死了会带走几个台）"]
    measured_any = False
    for v in views:
        rows = [r for r in (v.get("rows") or []) if r["channels"] >= 2][:10]
        total = v.get("total") or sum(r["channels"] for r in (v.get("rows") or []))
        if not rows:
            out += ["", f"- {v.get('label', '')}：{total} 个台的第一线一家主机都不共用，"
                        "没有哪个台会替别人背判分。"]
        else:
            has_ms = bool(v.get("measured"))
            measured_any = measured_any or has_ms
            head = ("| 第一线主机 | 范围 | 挂着几个台 | 其中换线路也换不出去 |"
                    + (" 第一线没实测过 |" if has_ms else "") + " 备选线路 | 来源 |")
            sep = "|---|---|---:|---:|" + ("---:|" if has_ms else "") + "---:|---|"
            out += ["", f"### {v['label']}（{total} 个台）", "", head, sep]
            for r in rows:
                name, _ = _SCOPE_LABEL.get(r["scope"], (r["scope"], ""))
                cells = [f"`{r['host']}`", name, f"{r['channels']} 个台",
                         str(r["alone"]) if r["alone"] else "—"]
                if has_ms:
                    cells.append(str(r["unmeasured"]) if r["unmeasured"] else "—")
                cells += [f"{r['alt_lines']} 条",
                          "、".join(f"`{s}`" for s in r["sources"]) or "—"]
                out.append("| " + " | ".join(cells) + " |")
            top = rows[0]
            ex = "、".join(top["examples"]) + ("…" if top["channels"] > len(top["examples"]) else "")
            out += ["", f"- 集中度最高的是 `{top['host']}`：{top['channels']} 个台的第一线都是它"
                        f"（{ex}）。真机点开其中任意一个，等于一次替这 {top['channels']} 个台判分。"]
            rest = total - sum(r["channels"] for r in rows)
            if rest > 0:
                out += ["", f"（另有 {rest} 个台的第一线不在上表这 {len(rows)} 家上，没列进来。"
                            + ("表只列挂着两个台以上的、前 10 家。" if len(rows) >= 10 else "") + "）"]
        # 2.26：紧跟着这张表回答「换第二条线路救得回来吗」—— 一家主机死了带走几个台是风险面，
        # 「那这几个台有没有第二条线可换」才是供给侧。没给 fallback 就不硬编一句（见上面的用例）。
        fb = v.get("fallback")
        if fb:
            out += [""] + _fallback_lines(fb, bool(v.get("measured")))
    out += ["", "> **两列别读反**：「挂着几个台」是**风险面** —— 这一家一死，"
              "这几个台的默认线路一起没；而「供给侧有没有退路」看「换线路也换不出去」，"
              "共用本身有一部分是我们自己的排序造成的（`--max-per-host`、录像压后）。"]
    if measured_any:
        out += ["> 「第一线没实测过」= 这条地址在这一轮的逐条判决（`probe.json`）里根本没有记录："
                "`probe: false` 的那几个源一个请求都没发过（计划书 2.22）。"
                "这一栏非 0 的那几行，真机点开一次就是它名下那批台第一次被判分 —— "
                "`docs/真机验收单.md` 第 4 步的样本优先从这里挑。"]
    out += ["", "> 数字来自本轮生成的这张表，不来自实测；换上游、换排序参数都会动它。"]
    return out


# 每一条范围规则的「说法」：那一列只描述事实，好坏交给表底下那三句。
_STATE_NOTE = {
    "first": "有台子的第一线就是它管出来的",
    "table": "进了表、没占住第一线",
    "out": "上游有货、表里没有",
    "shadow": "被排在前面的规则整个盖住",
    "none": "上游一条都没命中",
}


def _cell(text: str) -> str:
    """规则原文进 markdown 表格：一个 `|` 能把整张表断开，而这一格正是「内容错」那把尺要量的。

    >>> _cell("a.com")
    'a.com'
    >>> _cell("a|b")
    'a\\\\|b'
    """
    return str(text).replace("|", "\\|")


def _reach_rule_section(meta: dict | None) -> list[str]:
    """渲染「范围规则各自抓到几条」：config 里那几条规则一条一行，摆出它在三层的数（2.50）。

    为什么要有这一节：§2.49 那道闸问的是**形状**（这一格是不是「一段名单」），
    它看不见「形状对、内容错」—— `。chinamobile.com` 那个点是全角的、
    `http://tvgslb…` 带了协议前缀、域名搬家了、同一条写了两遍，全都方方正正地过闸。
    这一节问的是**效果**：这一条今天到底匹到几条线路、匹到的那些进没进表、有没有压住某个台的第一线。

    它要回答的是 §2.49 收尾时留下的那句：「命中 0 条」在这一格**有几种**意义。
    量完是三种，全靠那三层数把它们分开（括号里是 09-24 05:18 那一轮真跑出来的数）：

      * **上游 0**（`none`）—— 这批线路里没有它要判的地址，或者这条本身写错了。
        三种里只有这一种值得去动 `config/reachability.yaml`（本轮只有 `2408:` 一条：0 / 1869）。
      * **上游有货、表里没有**（`out`）—— 被窗口挡的：每个频道最多留 `--max-lines` 条、
        同一频道内同一主机最多 `--max-per-host` 条，都是我们自己的排序；或者是那些线路所在的台
        根本不在名单里。真配置里五条是这一种，最典型的是 `.qingting.fm`（上游 22 条、表里 0 条）
        和 `2409:`（上游 67 条、摊在 29 家主机上、表里 0 条）—— 它们**都在起作用**，
        2.49 之前这句话只能靠人拿正则去数 m3u 才敢说。
      * **字面命中、归它 0**（`shadow`）—— 排在它前面那条规则把它整个盖住了，
        它没坏、只是轮不到它。本轮一条都没有，但 `.chinamobile.com` 已经很接近：
        字面 210 条、归它 18 条，另外 192 条全落在 `tvgslb.hn.chinamobile.com` 那一条精确匹配里。
        这一格留着的理由就是最后这半句：**「命中几条」和「归它几条」是两个问题**，
        只问前者会把一条吃不到分的规则读成一条在起作用的规则，反过来也一样。

    所以「0 命中就提醒」那把尺不能按**条**装（三种 0 里两种无害），只按**整档**装：
    一档里每条都是 `none` 时 `src/cli.py` 往屏幕喊一句，而这一档在这张表里会连成一排 0。
    这正是 §2.49 那个「报警跟着规则一起哑掉」的替代品 ——
    上一节那句「一条公网线路都没有的 39 个频道」是**拿规则量的**，规则摊开了它自己就归 0（实测 39 → 0），
    而这一节的「上游候选」那一列不欠任何规则：它是拿这批规则去问上游池子，
    规则坏成什么样，它都会把 0 写在那些行上。

    >>> # 这五行就是 2026-09-24 05:18 那一轮真跑出来的数（上游 1869 条 / 进表 226 条 / 第一线 98 条）
    >>> rows = [{"tier": "iptv_intranet", "rule": "tvgslb.hn.chinamobile.com",
    ...          "any_up": 192, "own_up": 192, "own_table": 41, "own_first": 22, "state": "first"},
    ...         {"tier": "iptv_intranet", "rule": ".chinamobile.com",
    ...          "any_up": 210, "own_up": 18, "own_table": 0, "own_first": 0, "state": "out"},
    ...         {"tier": "iptv_intranet", "rule": "58.20.64.92",
    ...          "any_up": 57, "own_up": 57, "own_table": 18, "own_first": 17, "state": "first"},
    ...         {"tier": "iptv_intranet", "rule": "2408:",
    ...          "any_up": 0, "own_up": 0, "own_table": 0, "own_first": 0, "state": "none"},
    ...         {"tier": "audio_only", "rule": ".qingting.fm",
    ...          "any_up": 22, "own_up": 22, "own_table": 0, "own_first": 0, "state": "out"}]
    >>> meta = {"rows": rows, "n_up": 1869, "n_up_uniq": 1804, "n_table": 226, "n_first": 98,
    ...         "no_public_n": 39, "max_lines": 3, "max_per_host": 2, "code_up": 3}
    >>> s = "\\n".join(_reach_rule_section(meta))
    >>> "范围规则各自抓到几条" in s
    True
    >>> "去重之后上游是 1804 条" in s                        # 口径写明：数的是条目，不是去重后的主机
    True
    >>> "写进 aptv 那张表的 226 条（另外三张表是它的子集" in s   # 「进表」是哪一批：05:41 逐张量过
    True
    >>> "| 运营商 IPTV 内网 | `tvgslb.hn.chinamobile.com` | 192 | 41 | 22 |" in s
    True
    >>> "| 运营商 IPTV 内网 | `.chinamobile.com` | 18（字面 210） | 0 | 0 | 上游有货、表里没有 |" in s
    True
    >>> s.count("上游一条都没命中"), s.count("上游有货、表里没有")
    (1, 3)
    >>> "每个频道最多留 3 条" in s                          # 窗口是参数，写死的那个数会骗人
    True
    >>> "1 条规则在上游共归它 22 条" in s                    # 档级那句：本轮的数
    True
    >>> "交叉核对：「第一线」那一列合计 39 台，与那句「一条公网线路都没有的频道」39 个" in s
    True
    >>> "对不上" in "\\n".join(_reach_rule_section({**meta, "no_public_n": 41}))  # 两把尺不咬合就明说
    True
    >>> "0 台（规则管的）" not in s
    True
    >>> "\\n".join(_reach_rule_section(None))
    ''
    >>> "一条规则都没配上" in "\\n".join(_reach_rule_section({**meta, "rows": []}))
    True
    >>> "239.130" in "\\n".join(_reach_rule_section({**meta, "code_up": 12}))  # 组播那条另算一句
    True
    >>> "交叉核对" not in "\\n".join(_reach_rule_section({k: v for k, v in meta.items()
    ...                                                   if k != "no_public_n"}))  # 没给那句就不核对
    True
    >>> "同一条写了两遍" in "\\n".join(_reach_rule_section({**meta, "dup": ["2408:"]}))
    True
    >>> "同一条写了两遍" not in "\\n".join(_reach_rule_section(meta))
    True
    >>> shadow = {**rows[1], "own_up": 0, "state": "shadow"}   # 字面全被前一条盖住（本轮没有这一种）
    >>> "| 运营商 IPTV 内网 | `.chinamobile.com` | 0（字面 210） | 0 | 0 | 被排在前面的规则整个盖住 |" \\
    ...     in "\\n".join(_reach_rule_section({**meta, "rows": [shadow]}))
    True
    >>> prev = {**meta, "at": "2026-09-24T05:49:00+08:00", "mode": "offline", "egress": "",
    ...         "fingerprint": "7eae708d153a", "cfg_fingerprint": "aaaa11112222", "rows": rows}
    >>> cur = {**prev, "at": "2026-09-24T06:20:00+08:00", "rows": [
    ...     rows[0], {**rows[1], "own_up": 0, "state": "shadow"}, rows[2], rows[3], rows[4]]}
    >>> s2 = "\\n".join(_reach_rule_section({**meta, "diff": diff_rule_rounds(prev, cur)}))
    >>> "### 跟上一轮比：2026-09-24 05:49" in s2                   # 2.51：比出来的那一段排在七行之后
    True
    >>> s2.index("### 跟上一轮比") > s2.index("形状闸（2.49）")
    True
    >>> "`iptv_intranet` / `.chinamobile.com`：上游候选 18 条 → 0 条" in s2
    True
    >>> "没有可比对的上一次" not in s2                            # 有得比就不说那句
    True
    >>> "> 没有可比对的上一次：首轮。" in "\\n".join(              # 没得比：把为什么印出来
    ...     _reach_rule_section({**meta, "no_diff": "首轮"}))
    True
    """
    if meta is None:
        return []
    rows = meta.get("rows") or []
    out = ["", "## 范围规则各自抓到几条（这一档今天到底有没有在起作用）", ""]
    if not rows:
        return out + ["- `config/reachability.yaml` 里一条规则都没配上（文件不在，或者两格都留了空）："
                      "本轮所有 http 线路一律按**公网**排，运营商内网地址会重新占住第一线 —— "
                      "计划书 2.9 那个「订阅加得上、湖南台全部超时」就是这个形状。"]
    out += ["| 档 | 规则 | 上游候选 | 进表 | 第一线 | 说法 |",
            "|---|---|---:|---:|---:|---|"]
    for x in rows:
        name, _ = _SCOPE_LABEL.get(x["tier"], (x["tier"], ""))
        own, any_ = x["own_up"], x["any_up"]
        up = str(own) if any_ == own else f"{own}（字面 {any_}）"
        out.append(f"| {name} | `{_cell(x['rule'])}` | {up} | {x['own_table']} | "
                   f"{x['own_first']} | {_STATE_NOTE.get(x['state'], x['state'])} |")
    out += ["",
            f"> 三列是同一条规则看到的三层：**上游候选** = 本轮抓到的 {meta.get('n_up', 0)} 条原始线路地址；"
            f"**进表** = 写进 aptv 那张表的 {meta.get('n_table', 0)} 条"
            "（另外三张表是它的子集，四张并起来去重还是这些）；"
            f"**第一线** = 表上每个台的第一条、共 {meta.get('n_first', 0)} 条 —— "
            "APTV 只自动播这一条。三层数的都是**条目**："
            "同一条地址在两个源里各出现一次算两条（去重之后上游是 "
            f"{meta.get('n_up_uniq', meta.get('n_up', 0))} 条），因为那个窗口本身就是按条目切的。"]
    out += ["", "> **三种 0 别读成一种**：「上游候选」写 0 = 这批线路里没有它要判的地址，"
            "或者这一条本身写错了（全角点、带了 `http://`、域名搬家）—— "
            "**只有这一种值得去改配置**；"
            "「上游有货、表里没有」= 被排序窗口挡的（每个频道最多留 "
            f"{meta.get('max_lines', 3)} 条、同一频道内同一主机最多 {meta.get('max_per_host', 2)} 条，"
            "都是我们自己的规则），或者是那些线路所在的台根本不在名单里；"
            "「0（字面 N）」= 排在它前面那条规则把它整个盖住了，它没坏、只是轮不到它。"]
    tiers: dict[str, dict] = {}
    for x in rows:
        t = tiers.setdefault(x["tier"], {"rules": 0, "own": 0, "dead": 0})
        t["rules"] += 1
        t["own"] += x["own_up"]
        t["dead"] += 1 if not x["own_up"] and not x["any_up"] else 0
    parts = [f"**{_SCOPE_LABEL.get(k, (k, ''))[0]}**：{v['rules']} 条规则在上游共归它 {v['own']} 条"
             + (f"，其中 {v['dead']} 条规则上游 0 命中" if v["dead"] else "")
             for k, v in tiers.items()]
    out += ["", "> 本轮的数：" + "；".join(parts) + "。"]
    code = meta.get("code_up") or 0
    if code:
        out += ["", f"> 另有 {code} 条上游地址是非 http 协议（rtp/udp 组播、rtmp/srt 推流），"
                    "由代码直接定成内网，不欠上面任何一条规则（所以「各条规则归它的」加起来"
                    "不等于表上的内网线路数）。它们长这样：`rtp://@239.130.1.6:6002`。"]
    if meta.get("dup"):
        out += ["", "> ⚠️ 同一条写了两遍：" + "、".join(f"`{_cell(r)}`" for r in meta["dup"])
                + " —— 形状没问题，后面那条永远轮不到（`_classify` 记给第一个匹配上的）。"]
    npr = meta.get("no_public_n")
    if npr is not None:
        by_rule = sum(x["own_first"] for x in rows)
        code_first = meta.get("code_first") or 0
        s = by_rule + code_first
        who = (f"{by_rule} 台（规则管的）+ {code_first} 台（组播，代码定档）" if code_first
               else f"{by_rule} 台")
        tail = ("**是同一个数** —— 两把尺咬住了：一个台只要没有公网线路，"
                "它的第一线就必然归这一节的某一行管。" if s == npr else
                f"**对不上**，差 {abs(npr - s)} 台 —— 先查排序是不是还按范围分先后（`RANK`），"
                "以及「第一线」那一层取的是不是同一批地址。")
        out += ["", f"> 交叉核对：「第一线」那一列合计 {who}，"
                    f"与那句「一条公网线路都没有的频道」{npr} 个{tail}"]
    out += ["", "> 这一节是「一条公网线路都没有的频道」那一句的**独立佐证**：那一句是拿规则量的，"
            "规则整档摊开时它自己就归 0（计划书 2.49 实测：39 → 0，报警跟着规则一起哑掉）；"
            "而这一节的「上游候选」那一列是拿规则去问上游池子，规则坏成什么样它都还写着。"
            "形状闸（2.49）管的是写错的形状，这一节管的是写对内容之外的错。"]
    out += _reach_diff_lines(meta)
    return out


def _reach_diff_lines(meta: dict) -> list[str]:
    """那一节末尾的「跟上一轮比」（2.51）—— 措辞在 `scope.rule_diff_lines`，这里只管有没有得比。

    比不了时必须把**为什么**印出来：首轮、`--ignore-history`、上一轮那份读不出，
    是三件不同的事，读报告的人要能分清「这一节刚开始量」和「履历坏了」。
    一句空话都不能省 —— 少了这一格，`report.md` 里「没有这一段」和「比了，什么都没变」
    长得一模一样，那就是 2.32 那一格说过的「把没量印成没变」。

    反过来那一格也要有：**读进来了一部分**（坏了几行、最近一轮还在）时不能说「比不了」，
    但也不能当那几行不存在。所以那是独立的一句话，印在比对段之前 ——
    「比了」和「那份全不全」是两件事，混成一句就总有一句是假的。

    >>> prev = {"at": "2026-09-24T05:49:00+08:00", "mode": "offline", "egress": "",
    ...         "fingerprint": "7eae708d153a", "cfg_fingerprint": "a", "n_up": 1869,
    ...         "n_up_uniq": 1804, "no_public_n": 39,
    ...         "rows": [{"tier": "iptv_intranet", "rule": ".a.com", "any_up": 210,
    ...                   "own_up": 18, "own_table": 0, "own_first": 0, "state": "out"}]}
    >>> row = dict(prev["rows"][0])
    >>> d = diff_rule_rounds(prev, {**prev, "rows": [{**row, "own_up": 0}]})
    >>> s = "\\n".join(_reach_diff_lines({"diff": d}))
    >>> s.startswith("\\n### 跟上一轮比：2026-09-24 05:49") and "上游候选 18 条 → 0 条" in s
    True
    >>> "rule-history.jsonl" in s and "参考不是判据" in s   # 落哪、能不能改动表，写在同一格
    True
    >>> _reach_diff_lines({"no_diff": "`--ignore-history`：本轮不比对上一轮"})[1]
    '> 没有可比对的上一次：`--ignore-history`：本轮不比对上一轮。'
    >>> "为什么" in "\\n".join(_reach_diff_lines({}))       # 连原因都没给：也要留一句，不许静默消失
    True
    >>> partial = "\\n".join(_reach_diff_lines({"diff": d, "hist_partial": "第 1 行不是 JSON"}))
    >>> "只读到一部分" in partial and "第 1 行不是 JSON" in partial
    True
    >>> "本轮比不了" not in partial                          # 比了，就不能说比不了
    True
    >>> partial.index("只读到一部分") < partial.index("### 跟上一轮比")   # 先说缺，再说比
    True
    """
    diff = meta.get("diff")
    note = ([f"\n> 那份履历这一轮只读到一部分：{meta['hist_partial']}。"
             "下面比的是**最近一轮读得进来的**那些行。"]
            if meta.get("hist_partial") else [])
    if diff:
        return note + rule_diff_lines(diff, meta.get("hist_name") or "rule-history.jsonl")
    why = meta.get("no_diff") or ("这一节是计划书 2.51 才装上的，原因没记在这一轮的行里 —— "
                                  "为什么、以及「比了但什么都没变」，两件事别混着读")
    return ["", f"> 没有可比对的上一次：{why}。"]


def format_report(
    *,
    sources: list[str],
    total_entries: int,
    channels: list[OutputChannel],
    unmatched: dict[str, int],
    defined_but_empty: list[tuple[str, str]],
    epg_url: str,
    epg_note: dict | None = None,
    verify_note: str = "",
    line_scope: dict[str, int] | None = None,
    no_public: list[str] | None = None,
    fake_live: list[str] | None = None,
    focus: list[dict] | None = None,
    reach_rules: dict | None = None,
    hosts: list[dict] | None = None,
    hosts_note: str = "",
    history: dict | None = None,
) -> str:
    """生成人读的 markdown 报告，方便你一眼看出哪些台有、哪些台还缺。

    hosts 是 host_summary() 的输出，传了才渲染「实测逐主机」一节；
    `hosts_note` 是那一节的表头后缀 —— `--replay` 时那些数字来自被沿用的那一轮，
    不写明的话报告读起来就像本轮又联网测了一遍（本轮真的一个请求都没发）。
    history 是 src/check/history.py 算出来的履历摘要，传了才渲染趋势那一节；
    focus 是 first_line_focus() 按表算出来的第一线主机集中度（计划书 2.23），
    一个元素一张表（全量 / 湖南），传了才渲染那一节 —— 没传就不硬凑。
    reach_rules 是 `reach.rule_states()` 的三层数（2.50），传了才渲染「范围规则各自抓到几条」：
    那一节回答的是「config 里这几条规则今天各抓到几条」，与「这一档有没有在起作用」是同一个问题的两种问法。
    epg_note 是 `load_epg()` + `apply_ids()` 的材料，传了才渲染「EPG 对齐」那一节 ——
    **未启用时也要传**，那一节会写明「这一轮没有对齐这回事」，否则读报告的人分不清
    「没启用」和「功能坏了没渲染」。

    >>> h = [{"host": "dead.example", "scope": "public", "total": 3, "ok": 0, "best_ms": 0},
    ...      {"host": "live.example", "scope": "public", "total": 2, "ok": 2, "best_ms": 480}]
    >>> kw = dict(sources=[], total_entries=0, channels=[], unmatched={},
    ...           defined_but_empty=[], epg_url="", hosts=h)
    >>> out = format_report(**kw)
    >>> note = [l for l in out.splitlines() if "全部线路失效" in l][0]
    >>> "dead.example" in note and "live.example" not in note   # 只点全灭的那族
    True
    >>> "实测逐主机" not in format_report(**{**kw, "hosts": []})  # 没实测就不编
    True
    >>> "其中 2 条是循环录像" in format_report(**{**kw, "hosts": [{**h[1], "vod": 2}]})
    True
    >>> [l for l in format_report(**{**kw, "hosts_note": "沿用 21:18 那一轮，本轮未联网"}).splitlines()
    ...  if l.startswith("## 逐主机")][0]
    '## 逐主机可用性（沿用 21:18 那一轮，本轮未联网）'
    >>> "实测逐主机（本机出口直连）" in format_report(**kw)   # 不传后缀＝本轮自己测的
    True
    >>> "有循环录像的主机" not in format_report(**{**kw, "hosts": h})   # 没这项就不加一节
    True
    >>> f = format_report(**{**kw, "hosts": [], "fake_live": ["湖南卫视（a.com 1259 片循环）"]})
    >>> [l for l in f.splitlines() if "湖南卫视" in l and "循环" in l]
    ['- 湖南卫视（a.com 1259 片循环）']
    >>> "循环录像" not in format_report(**{**kw, "hosts": [], "fake_live": []})
    True
    >>> "EPG 对齐" not in format_report(**{**kw, "hosts": []})     # 没传材料就不加这一节
    True
    >>> "第一线主机集中度" not in format_report(**{**kw, "hosts": []})   # 没传 focus 同上
    True
    >>> one = {"label": "aptv.m3u", "total": 2, "measured": False,
    ...        "rows": [{"host": "a", "scope": "public", "channels": 2, "alone": 0,
    ...                   "unmeasured": 0, "alt_lines": 3, "sources": ["gd"],
    ...                   "examples": ["x", "y"]}]}
    >>> f2 = format_report(**{**kw, "hosts": [], "focus": [one]})
    >>> "第一线主机集中度" in f2 and "aptv.m3u（2 个台）" in f2
    True
    >>> "范围规则各自抓到几条" not in format_report(**{**kw, "hosts": []})  # 没传 reach_rules 就不加
    True
    >>> f3 = format_report(**{**kw, "hosts": [], "reach_rules": {
    ...     "rows": [{"tier": "audio_only", "rule": ".qingting.fm", "any_up": 22, "own_up": 22,
    ...               "own_table": 0, "own_first": 0, "state": "out"}],
    ...     "n_up": 1869, "n_table": 226, "n_first": 98, "max_lines": 3, "max_per_host": 2}})
    >>> "范围规则各自抓到几条" in f3 and "纯音频电台" in f3      # 传了才渲染，与 focus 同一套路
    True
    >>> "一条规则都没配上" in format_report(                    # 传了但一条规则都没配上：也要说一句话
    ...     **{**kw, "hosts": [], "reach_rules": {"rows": []}})
    True
    >>> "未启用" in format_report(**{**kw, "hosts": [], "epg_note": {"enabled": False}})
    True
    >>> hist = {"runs": 3, "used": 2, "dropped": 1, "egress": "119.39.40.124 CN",
    ...         "totals": [{"at": "2026-09-21T13:00:40+08:00", "egress": "U",
    ...                     "ok": 218, "total": 331}],
    ...         "blacklist": [{"host": "dead.example", "runs": 2, "ok_runs": 0,
    ...                        "total": 35, "ok_last": 0, "best_ms": 0,
    ...                        "last_at": "2026-09-21T13:00:40+08:00", "dead_streak": 2}],
    ...         "demote": ["dead.example"], "latency_hosts": 7, "stale_first_lines": 4,
    ...         "fake": ["loop.example"], "rolls": {"checked": 30, "stuck": 3},
    ...         "verified": False}
    >>> r = format_report(**{**kw, "hosts": [], "history": hist})
    >>> "从来没通过过的主机" in r and "dead.example" in r.split("各分组频道")[0]
    True
    >>> "只放循环录像" in r and "loop.example" in r      # 连得上但放录像的，单独一档
    True
    >>> "L3 逐条验过 30 条" in r and "3 条一动不动" in r   # 逐条那种精度也要说出来
    True
    >>> "1 轮" in r                                    # 被排除的轮次要说明
    True
    >>> "补了位" in r and "7 个主机" in r              # 上一轮的延迟拿来补位
    True
    >>> r2 = format_report(**{**kw, "hosts": [],
    ...                        "history": {**hist, "build_egress": "139.x JP"}})
    >>> "开发机的代理" in r2                    # 本轮出口和判据出口不一致要讲明白
    True
    >>> "主机可用性履历" not in format_report(**{**kw, "hosts": [], "history": None})
    True
    >>> "主机可用性履历" not in format_report(
    ...     **{**kw, "hosts": [], "history": {**hist, "runs": 0, "used": 0, "dropped": 0,
    ...                                      "totals": [], "blacklist": []}})
    True
    """
    lines: list[str] = ["# 生成报告", ""]
    lines.append(f"- 上游条目：{total_entries} 条，来自 {len(sources)} 个源")
    for s in sources:
        lines.append(f"  - {s}")
    lines.append(f"- 输出频道：{len(channels)} 个，线路 {sum(len(c.urls) for c in channels)} 条")
    lines.append(f"- EPG：{epg_url or '未获取到'}")
    if verify_note:
        lines.append(f"- 线路可用性：{verify_note}")

    by_group: dict[str, list[OutputChannel]] = {}
    for ch in channels:
        by_group.setdefault(ch.group_title, []).append(ch)

    if line_scope:
        lines += ["", "## 线路的可达范围", "", "| 范围 | 线路数 | 在电视上的表现 |", "|---|---|---|"]
        for key, count in sorted(line_scope.items(), key=lambda kv: -kv[1]):
            name, note = _SCOPE_LABEL.get(key, (key, ""))
            lines.append(f"| {name} | {count} | {note} |")
        lines += ["", "> 每个频道都会把公网线路排在第一条，APTV 默认播第一条，"
                  "所以内网线路是「手动切换备选」而不是默认路径。"
                  "电台地址排在最后，避免点开只出声音。"]
        if no_public:
            lines += ["", f"### 一条公网线路都没有的 {len(no_public)} 个频道（Wi-Fi 上不用试）", "",
                      "、".join(no_public), "",
                      "> 这些台目前唯一的来源是运营商 IPTV 内网，或只有电台同播（见 config/reachability.yaml）。"
                      "要在电视上看，只能走 IPTV 机顶盒那个 VLAN，或者等 P5 找到它们的公网视频流。"]

    lines += _reach_rule_section(reach_rules)

    if fake_live:
        lines += ["", "### 但第一条线路是循环录像的频道（有画，不是直播）", ""]
        lines += [f"- {c}" for c in fake_live]
        lines += ["", "> 判据：播放列表里有 `#EXT-X-ENDLIST`、分片数以百计"
                  "（阈值见 src/check/prober.py 的 VOD_SEGMENTS），或者响应体根本不是播放列表"
                  "而是一个 QuickTime/MP4 文件；括号里写「L3 验过」的那几条是另一种 —— "
                  "分片只有几个、但隔十几秒重取两次窗口一步都没走，L2 那种判据看不穿它。"
                  "这类地址 TCP 通、有内容、"
                  "往往还比真直播快，L2 只看「有没有分片」时会被当成可用线路 —— "
                  "比超时更坏，因为用户会以为这个台就这样。它们已在本表里被排到真直播后面，"
                  "只剩录像可播的才留在第一位。"]

    lines += _focus_section(focus)

    if hosts:
        dead_all = [h for h in hosts if not h["ok"]]
        vod_any = [h for h in hosts if h.get("vod")]
        head = (f"## 逐主机可用性（{hosts_note}）" if hosts_note
                else "## 实测逐主机（本机出口直连）")
        lines += ["", head, "",
                  "| 主机 | 范围 | 可用 | 最快 |", "|---|---|---|---|"]
        for h in hosts:
            name, _ = _SCOPE_LABEL.get(h["scope"], (h["scope"], ""))
            # ✅ 全通 / ⚠️ 部分失效 / ❌ 整族连不上，三种不能混成一个符号
            mark = "✅" if h["ok"] == h["total"] else ("❌" if not h["ok"] else "⚠️")
            use = f"{h['ok']}/{h['total']} {mark}"
            if h.get("vod"):
                use += f"（其中 {h['vod']} 条是循环录像）"
            lines.append(f"| `{h['host']}` | {name} | {use} | "
                         f"{str(h['best_ms']) + 'ms' if h['best_ms'] else '—'} |")
        if dead_all:
            who = "、".join(f"`{h['host']}`（{h['total']} 条）" for h in dead_all)
            lines += ["", f"> ⚠️ 全部线路失效的主机：{who}。",
                      "> 挂在这些主机上的频道，**公网线路等于不存在**，"
                      "电视上只会看到超时 —— 不用真机再确认一遍。"]
        if vod_any:
            who = "、".join(f"`{h['host']}`（{h['vod']}/{h['ok']} 条）" for h in vod_any)
            lines += ["", f"> ⚠️ 有循环录像的主机：{who}。",
                      "> 连得上、有画，播出来的却是几个钟头前的节目。通了的线路**全**落在"
                      "这一栏里的主机，下一轮离线生成会被往后压（`history.fake_hosts`），"
                      "本轮实测过则当场就压。"]
        lines += ["", "> 这一栏决定 P5 的取向：整族失效的主机要从候选里划掉；"
                  "而「跨洋中转全通」说明公网这条路真的能用，"
                  "剩下的缺口就是纯粹的找源问题，不是排序问题。"]

    if history and history.get("runs"):
        lines += _history_section(history)

    lines += _epg_section(epg_note)

    lines += ["", "## 各分组频道与线路数", "", "| 分组 | 频道 | 线路数 |", "|---|---|---|"]
    for grp, chs in by_group.items():
        for ch in chs:
            lines.append(f"| {grp} | {ch.name} | {len(ch.urls)} |")

    if defined_but_empty:
        lines += ["", "## ⚠️ 配置里有、但这次一条线路都没匹配到", ""]
        lines += [f"- {grp} / {name}" for name, grp in defined_but_empty]
        lines += ["", "> 这些台在公开聚合源里目前没有可用线路，需要走 P5 手工补源。"]

    if unmatched:
        lines += ["", "## 未匹配的上游频道名（出现次数 Top 30）", ""]
        lines += [f"- {name} ×{n}" for name, n in sorted(unmatched.items(), key=lambda kv: -kv[1])[:30]]

    lines.append("")
    return "\n".join(lines)
