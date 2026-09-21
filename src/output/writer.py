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
    hosts: list[dict] | None = None,
) -> str:
    """生成人读的 markdown 报告，方便你一眼看出哪些台有、哪些台还缺。

    hosts 是 host_summary() 的输出，传了才渲染「实测逐主机」一节：

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
