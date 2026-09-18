"""输出 m3u 与运行报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

_M3U_ATTRS = ("tvg-id", "tvg-name", "tvg-logo", "group-title")


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
) -> str:
    """生成人读的 markdown 报告，方便你一眼看出哪些台有、哪些台还缺。"""
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
