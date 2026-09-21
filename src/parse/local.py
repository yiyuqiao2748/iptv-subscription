"""读取 config/sources_local.yaml —— 手工核对过的补充线路。

为什么不把这些台塞进 sources.yaml 的聚合源里：
聚合源是别人维护的、会整体更新，下次刷新就把我们的手工成果冲掉了；
而且手工条目必须带上「来源 + 核实日期 + 有效期」这些聚合源结构里放不下的信息
（计划书 §十一 承诺：权利人提出异议就从 sources_local.yaml 立即移除该源）。

这里只负责把 YAML 变成 Entry，不做任何判断。手写的线路照样要过
.aggregate() 里的鉴权红线、照样参与 --verify 实测、照样按可达范围排序 ——
「我确认过它能播」的保质期是以周计的，不能因为条目来自这个文件就免检。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from src.parse.m3u import Entry

SOURCE_ID = "local"


def is_expired(expires: str, today: dt.date | None = None) -> bool:
    """有效期到了就该停用（留个日期比悄悄失效好，报告里能看出是过期而不是没测）。

    日期写错按未过期处理，不静默丢条目；告警由 parse_channels() 打印，
    这个函数保持无副作用，好测。

    >>> is_expired("")                                   # 没填就不管
    False
    >>> is_expired("2026-09-20", dt.date(2026, 9, 21))   # 昨天到期
    True
    >>> is_expired("2026-12-31", dt.date(2026, 9, 21))
    False
    >>> is_expired("还没到时候", dt.date(2026, 9, 21))    # 日期写错按未过期处理
    False
    """
    text = str(expires or "").strip()
    if not text:
        return False
    try:
        end = dt.date.fromisoformat(text)
    except ValueError:
        return False
    return end < (today or dt.date.today())


def parse_channels(text: str) -> tuple[list[Entry], list[str]]:
    """YAML 正文 -> (Entry 列表, 被跳过的原因)。

    name / url 缺一就跳过：宁可不进表，也不要往用户的第一线塞半条线路。

    >>> entries, skipped = parse_channels('''
    ... channels:
    ...   - name: 湘潭新闻综合
    ...     url: http://live.hnxttv.com:9601/live/xwzh/800K/tzwj_video.m3u8
    ...     group: shizhou
    ...   - name: 缺地址的台
    ... ''')
    >>> [(e.name, e.url, e.source, e.group) for e in entries]
    [('湘潭新闻综合', 'http://live.hnxttv.com:9601/live/xwzh/800K/tzwj_video.m3u8', 'local', 'shizhou')]
    >>> skipped
    ['第 2 条：缺 url']
    """
    cfg = yaml.safe_load(text) or {}
    out: list[Entry] = []
    skipped: list[str] = []
    for i, raw in enumerate(cfg.get("channels") or []):
        raw = raw or {}
        name = str(raw.get("name") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not name or not url:
            skipped.append(f"第 {i + 1} 条：缺 {'url' if name else 'name'}")
            continue
        exp = str(raw.get("expires") or "").strip()
        if exp:
            try:
                dt.date.fromisoformat(exp)
            except ValueError:
                print(f"    ⚠️ {name} 的 expires={exp!r} 不是 YYYY-MM-DD，按未过期处理")
        if is_expired(exp):
            skipped.append(f"第 {i + 1} 条 {name}：有效期 {exp} 已过")
            continue
        out.append(Entry(
            name=name, url=url,
            tvg_id=str(raw.get("tvg_id") or "").strip(),
            group=str(raw.get("group") or "").strip(),
            source=SOURCE_ID, seq=i,
            extras={"note": str(raw.get("note") or "")},
        ))
    return out, skipped


def load_local(path: Path | str) -> list[Entry]:
    """读文件；不存在就返回空表 —— 手工补充源是可选件，不该让主流程报错。"""
    p = Path(path)
    if not p.exists():
        return []
    entries, skipped = parse_channels(p.read_text(encoding="utf-8"))
    for why in skipped:
        print(f"    跳过 config/sources_local.yaml {why}")
    return entries
