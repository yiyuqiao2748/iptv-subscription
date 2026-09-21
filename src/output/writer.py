"""输出 m3u 与运行报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

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


def _history_section(h: dict) -> list[str]:
    """渲染「主机可用性履历」：每轮趋势 + 该从候选里划掉谁。

    单独成函数只为了让 format_report 保持可读；判据都在 src/check/history.py。
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
    bits = []
    if h.get("demote"):
        bits.append(f"把 {len(h['demote'])} 个整族失效的主机往后压了档："
                    + "、".join(f"`{x}`" for x in h["demote"][:8])
                    + ("…" if len(h["demote"]) > 8 else ""))
    if h.get("latency_hosts"):
        bits.append(f"{h['latency_hosts']} 个主机按上一轮实测延迟补了位"
                    "（不补的话，本轮没实测，最好的那条会被来源优先级挤掉）")
    if bits:
        out += ["", "> 本轮生成用到履历的地方：" + "；".join(bits) + "。"]
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
    ...         "verified": False}
    >>> r = format_report(**{**kw, "hosts": [], "history": hist})
    >>> "从来没通过过的主机" in r and "dead.example" in r.split("各分组频道")[0]
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
                  "而是一个 QuickTime/MP4 文件。这类地址 TCP 通、有内容、"
                  "往往还比真直播快，L2 只看「有没有分片」时会被当成可用线路 —— "
                  "比超时更坏，因为用户会以为这个台就这样。它们已在本表里被排到真直播后面，"
                  "只剩录像可播的才留在第一位。"]

    if hosts:
        dead_all = [h for h in hosts if not h["ok"]]
        lines += ["", "## 实测逐主机（本机出口直连）", "",
                  "| 主机 | 范围 | 可用 | 最快 |", "|---|---|---|---|"]
        for h in hosts:
            name, _ = _SCOPE_LABEL.get(h["scope"], (h["scope"], ""))
            # ✅ 全通 / ⚠️ 部分失效 / ❌ 整族连不上，三种不能混成一个符号
            mark = "✅" if h["ok"] == h["total"] else ("❌" if not h["ok"] else "⚠️")
            lines.append(f"| `{h['host']}` | {name} | {h['ok']}/{h['total']} {mark} | "
                         f"{str(h['best_ms']) + 'ms' if h['best_ms'] else '—'} |")
        if dead_all:
            who = "、".join(f"`{h['host']}`（{h['total']} 条）" for h in dead_all)
            lines += ["", f"> ⚠️ 全部线路失效的主机：{who}。",
                      "> 挂在这些主机上的频道，**公网线路等于不存在**，"
                      "电视上只会看到超时 —— 不用真机再确认一遍。"]
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
