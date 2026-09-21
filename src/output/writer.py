"""输出 m3u 与运行报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from src.check.history import Suggestion  # 建议行的格式只有一份实现（2.17）

_M3U_ATTRS = ("tvg-id", "tvg-name", "tvg-logo", "group-title")

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
        attrs = " ".join(
            f'{k}="{v}"'
            for k, v in zip(_M3U_ATTRS, (self.tvg_id, self.name, self.logo, self.group_title))
            if v
        )
        return f"#EXTINF:-1 {attrs},{self.name}"


def format_m3u(channels: Iterable[OutputChannel], epg_url: str = "") -> str:
    """渲染 m3u 文本。

    同名频道连续出现即为 APTV 的多线路；这里每个 OutputChannel 只输出一条，
    多线路靠调用方把同一频道的多条 url 合并进 urls 实现。
    """
    head = f'#EXTM3U x-tvg-url="{epg_url}"' if epg_url else "#EXTM3U"
    out = [head]
    for ch in channels:
        for url in ch.urls:
            out.append(ch.extinf())
            out.append(url)
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
    measured = bool(h.get("verified"))
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
                    + ("" if measured else
                       "（不补的话，本轮没实测，最好的那条会被来源优先级挤掉）"))
    if bits:
        lead = ("> 履历里另有这些判据" if measured else "> 本轮生成用到履历的地方")
        out += ["", lead + "：" + "；".join(bits) + "。"]
        if measured:
            out[-1] += ("（本轮每条线路都实测过，所以它们只作用在 `probe: false` "
                        "那几条压根没测的线路上）")
        if h.get("stale_first_lines"):
            out[-1] += (f"第一线仍落在已知失效主机上的频道 {h['stale_first_lines']} 个 —— "
                        "那些台只有这一条公网线路，没有更好的可以换。")
    return out


def format_report(
    *,
    sources: list[str],
    total_entries: int,
    channels: list[OutputChannel],
    unmatched: dict[str, int],
    defined_but_empty: list[tuple[str, str]],
    epg_url: str,
    verify_note: str = "",
    line_scope: dict[str, int] | None = None,
    no_public: list[str] | None = None,
    fake_live: list[str] | None = None,
    hosts: list[dict] | None = None,
    history: dict | None = None,
) -> str:
    """生成人读的 markdown 报告，方便你一眼看出哪些台有、哪些台还缺。

    hosts 是 host_summary() 的输出，传了才渲染「实测逐主机」一节；
    history 是 src/check/history.py 算出来的履历摘要，传了才渲染趋势那一节。

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
    >>> "有循环录像的主机" not in format_report(**{**kw, "hosts": h})   # 没这项就不加一节
    True
    >>> f = format_report(**{**kw, "hosts": [], "fake_live": ["湖南卫视（a.com 1259 片循环）"]})
    >>> [l for l in f.splitlines() if "湖南卫视" in l and "循环" in l]
    ['- 湖南卫视（a.com 1259 片循环）']
    >>> "循环录像" not in format_report(**{**kw, "hosts": [], "fake_live": []})
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

    if hosts:
        dead_all = [h for h in hosts if not h["ok"]]
        vod_any = [h for h in hosts if h.get("vod")]
        lines += ["", "## 实测逐主机（本机出口直连）", "",
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
