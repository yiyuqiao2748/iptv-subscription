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

from src.keys import check_keys, check_version
from src.parse.m3u import Entry

SOURCE_ID = "local"

# 这份文件允许的键，逐条说清它管什么 —— 这份名单就是 `src/keys.py` 那道守卫的弹药，
# 代码里 `raw.get("x")` 读了谁、以及「写给人看所以没人读」的谁，都在这里对齐一次。
# （「对齐一次」以前只是一句承诺，2.42 起 `parse_channels` 里那条用例每天量它一遍。）
TOP_KEYS = ["version", "channels"]
TOP_NOTES = {"channels": "这些手工核对过的线路进不进表"}
CHANNEL_KEYS = ["name", "url", "group", "tvg_id", "expires", "added", "note"]
# 值是一句人话，会原样出现在报错里：写歪了这些键，表上会安静地少掉什么。
CHANNEL_NOTES = {
    "name": "这条线路叫什么、频道名单认不认得它",
    "url": "这条线路的真实地址（没地址它本来就不该进表）",
    "group": "认不上名字时它归到哪一组",
    "tvg_id": "电子节目单把它对到哪个台",
    "expires": "这条线路哪天停用（写歪就是永不过期）",
}


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


def parse_channels(text: str, *,
                   where: str = "config/sources_local.yaml") -> tuple[list[Entry], list[str]]:
    """YAML 正文 -> (Entry 列表, 被跳过的原因)。

    name / url 缺一就跳过：宁可不进表，也不要往用户的第一线塞半条线路。

    `where` 只用在顶层那两句上（`version` / `channels` 写歪）：条目级的说法本来就短，
    而顶层那两句会被 `stop_config` 接住 —— 它前面已经印过一次文件路径，两边写的是同一个
    字符串才不会重复（2.39 装完闸第一次实测，屏幕上那条绝对路径出现了两次）。

    url 还必须是**一行**：`strip()` 只去首尾，中间剩下的空白是 YAML 折行弄出来的，
    那条地址已经不是任何人测过的那一条了。字面块 `|` 更糟 —— 里面如果有换行，
    写进 m3u 就是凭空多出一行地址（2.35 复现过：1 头 + 2 线路的表变成 4 行）。
    这里拦下来比让 writer 悄悄改掉诚实：理由会打印，条目不会假装存在。

    键名写歪也拦（`src/keys.py`，2.39）：`expires` 少个 s 就是「这条线路永不过期」，
    表上什么都不会少，少的是一次本该发生的停用 —— 那种错只有在这里说才来得及。
    认不出又不确定是不是笔误的，只印一行警告，不拦出表。

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
    >>> parse_channels("channels:\\n  - name: 折行的\\n    url: \\"http://a/1.m3u8\\n      x.m3u8\\"\\n")[1]
    ['第 1 条 折行的：url 里有空白，多半是 YAML 折行']
    >>> parse_channels("channels:\\n  - name: 两行\\n    url: |\\n      http://a/1.m3u8\\n      http://b/2.m3u8\\n")[0]
    []
    >>> parse_channels('''
    ... channels:
    ...   - 湘潭新闻综合          # 漏了 `- name:` 那种写法，整条只是个字符串
    ...   - name: 好的
    ...     url: http://a/1.m3u8
    ... ''')[1]
    ['第 1 条不是「name + url」那种字典（是 str）']

    致命的近亲键：抛话，且这一份一条都不进表（半份名单比没名单更难查）。

    >>> try:
    ...     parse_channels("channels:\\n  - name: 湘潭\\n    url: http://a/1.m3u8\\n    expire: 2026-12-31\\n")
    ... except ValueError as e:
    ...     print(str(e))
    第 1 条 湘潭：`expire` 我们不读，最像是 `expires` 写歪了 —— 它管的是这条线路哪天停用（写歪就是永不过期）

    顶层写成 `channel:`（少了 s）以前是静默出一张没有手工线路的表。

    >>> try:
    ...     parse_channels("channel:\\n  - name: 湘潭\\n    url: http://a/1.m3u8\\n")
    ... except ValueError as e:
    ...     print("`channel`" in str(e) and "`channels`" in str(e))
    True

    顶层那两句带的是真文件名（`load_local` 把路径传进来）—— 句首与 `stop_config` 要印的
    那个字符串同一个，才不会「这条路径屏幕上出现两遍」：

    >>> try:
    ...     parse_channels("channel:\\n  - name: 湘潭\\n    url: http://a/1.m3u8\\n",
    ...                    where="/tmp/x/sources_local.yaml")
    ... except ValueError as e:
    ...     print(str(e))
    /tmp/x/sources_local.yaml：`channel` 我们不读，最像是 `channels` 写歪了 —— 它管的是这些手工核对过的线路进不进表

    认不出的键只警告：下面这条的 `note` 是写给人看的（在名单上），所以只有 `expire_date` 那句话。

    >>> parse_channels("channels:\\n  - name: 湘潭\\n    url: http://a/1.m3u8\\n    note: 自己试过\\n")[1]
    []

    顶上那句「都在这里对齐一次」现在有东西盯着了（2.42）：名单少了格子会被念成
    「这键没人读」，名单多了格子（没人读的行为键）才是真危险 —— 那一种写歪照样静默。

    >>> from src.keys import drift_of
    >>> drift_of(parse_channels, known=TOP_KEYS + CHANNEL_KEYS,
    ...          notes={**CHANNEL_NOTES, **TOP_NOTES})
    []
    """
    cfg = yaml.safe_load(text) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    check_version(cfg, where=where)
    for warn in check_keys(cfg, where=where, known=TOP_KEYS, notes=TOP_NOTES):
        print(f"    ⚠️ {warn}")
    out: list[Entry] = []
    skipped: list[str] = []
    for i, raw in enumerate(cfg.get("channels") or []):
        if not isinstance(raw, dict):
            # 以前这里往下走就是裸 `AttributeError: 'str' object has no attribute 'get'`：
            # 一条写漏了 `- name:` 缩进的线路，崩栈比它被跳过更难懂。
            skipped.append(f"第 {i + 1} 条不是「name + url」那种字典（是 "
                           f"{type(raw).__name__}）")
            continue
        name = str(raw.get("name") or "").strip()
        for warn in check_keys(raw, where=f"第 {i + 1} 条 {name or '（没名字）'}",
                               known=CHANNEL_KEYS, notes=CHANNEL_NOTES):
            print(f"    ⚠️ {warn}")
        url = str(raw.get("url") or "").strip()
        if not name or not url:
            skipped.append(f"第 {i + 1} 条：缺 {'url' if name else 'name'}")
            continue
        if any(c.isspace() for c in url):
            skipped.append(f"第 {i + 1} 条 {name}：url 里有空白，多半是 YAML 折行")
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
        ))
    return out, skipped


def load_local(path: Path | str) -> list[Entry]:
    """读文件；不存在就返回空表 —— 手工补充源是可选件，不该让主流程报错。"""
    p = Path(path)
    if not p.exists():
        return []
    entries, skipped = parse_channels(p.read_text(encoding="utf-8"), where=str(p))
    for why in skipped:
        print(f"    跳过 {p} {why}")
    return entries
