"""读取 config/sources_local.yaml —— 手工核对过的补充线路。

为什么不把这些台塞进 sources.yaml 的聚合源里：
聚合源是别人维护的、会整体更新，下次刷新就把我们的手工成果冲掉了；
而且手工条目必须带上「来源 + 核实日期 + 有效期」这些聚合源结构里放不下的信息
（计划书 §十一 承诺：权利人提出异议就从 sources_local.yaml 立即移除该源）。

这里只负责把 YAML 变成 Entry，不做任何判断 —— 判断全在 `src/keys.py`：2.39 起问
「这一格写的是谁」（键名写歪），2.47 起问「这一格写的是个什么东西」（值的形状，
`str()` 会把列表洗成一个看起来能用的台名）。手写的线路照样要过
.aggregate() 里的鉴权红线、照样参与 --verify 实测、照样按可达范围排序 ——
「我确认过它能播」的保质期是以周计的，不能因为条目来自这个文件就免检。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from src.keys import _NOT_SET, check_keys, check_version, date_value, text_value
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

# 2.47：这一格该写成个什么东西，各写一句「怎么改」。
# 为什么每格单独一句：`url` 挂两条的修法和 `tvg_id` 挂两条的修法不是一个动作，
# 抄一句通用建议等于把人赶到错的那一行去（2.46 给 `sources.yaml` 记过同一件事）。
# 这四句只在「值的形状不对」时说；键名写歪另有一套（上面那份 `CHANNEL_NOTES`）。
_NAME_ADVICE = ("这一格是电视台的名字，得写成一行文字（`name: 湖南卫视`）；"
                "名字是匹配频道名单的那把钥匙，写成两条时老读法把 "
                "`['湖南卫视', '湖南经视']` 整串当名字，两个台都不认得它")
_URL_ADVICE = ("这一格是一条地址，得写成一行文字（`url: http://…/1.m3u8`）；"
               "要两条线路就分成两条（各自一个 `name`），换行写行首得加 `- `。"
               "老读法 `str()` 一下就把这一格交给下游：2.47 实测 `url: 12345` 变成表里的一行 "
               "`12345`，排成两条则洗成 `['http://…', 'http://…']` —— 都不是谁核对过的那一条")
_TVG_ADVICE = ("这一格是电子节目单里这个台的名字（`tvg_id: hunan`），得写成一行文字；"
               "写成两条时老读法把 `['hunan', 'hn']` 整串当 id，"
               "而带前导零的那种（`0123`）会被 YAML 按八进制读成 83 —— id 自己换了一个")
_GROUP_ADVICE = ("这一格是「认不上频道名时归到哪一组」（`group: shizhou`），一行文字；"
                 "写成两条时老读法把整串当组名，电视上就多出一个 `['shizhou', 'hunantv']` 分组")


def is_expired(expires: str, today: dt.date | None = None) -> bool:
    """有效期到了就该停用（留个日期比悄悄失效好，报告里能看出是过期而不是没测）。

    从 2.47 起这一层的「认不出来按未过期处理」只是**第二道防线**：日期那一格在
    `src.keys.date_value()` 里就问过形状了（`2026-1-5`、`true`、排成两条那种到不了这里，
    而 `2026-01-05 12:00:00` 会被它归一成 `2026-01-05` 再交下来 —— 那一格是本轮实测里
    唯一「日期早就过了却还在表上」的活例子）。留着一个宽松兜底的理由：这个函数无副作用、
    好测，而哪天有别的调用方直接扔一个字符串进来，它也不该把一条线路判死。

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

    值的形状分两档（2.47，`src/keys.py` 的那几个助手）。`name` / `url` / `expires`
    写坏形状 = **这一条不进表**，理由进 `skipped`；`tvg_id` / `group` 写坏形状 =
    **降级成空 + 印一行警告**，线路照样进表。分档看的是「这条线路还能不能看」：
    名字或地址不对，它在表上就是个假样子（27 格普查里实测：台名排成两条时进表的名字是
    `['湖南卫视', '湖南经视']`，`url: 12345` 真的当地址进了表）；而 id、组名不对，
    线路照样播，缺的只是对节目单、归分组 —— 为元数据扔一条活线路是拿第一线陪葬。
    两档都不再是「安静地换个意思」，也不再是那句「按未过期处理」。

    `expires` 空着是**这份文件自己定的规矩**，不是这里猜的：`config/sources_local.yaml`
    第 18 行写着「有效期，留空表示不限」，而真配置那一条写的就是 `expires: ""`。
    所以这一格不套用 2.46 那条「没写 / 写了没填 要分开」：没写、空着、`null`、一对引号
    四种读法在这里合并成「不设停用日」。第一版按「写了没填就停下来」处理，
    当场把家里唯一那条手工线路从表里删掉了 —— 下面拿真配置跑的那一格钉的就是这件事。

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

    认不出的键只警告：下面这条只带一个 `note`（写给人看、在名单上），所以一句话都没有。

    >>> parse_channels("channels:\\n  - name: 湘潭\\n    url: http://a/1.m3u8\\n    note: 自己试过\\n")[1]
    []

    值的形状，两档各一格。`name` 排成两条：以前那串列表字面量就是台名，进了表、
    屏幕上一个字都没有；现在这一条不进表，理由里说得清是哪一个键、读成了什么。

    >>> entries, skipped = parse_channels('''
    ... channels:
    ...   - name:
    ...       - 湖南卫视
    ...       - 湖南经视
    ...     url: http://a/1.m3u8
    ... ''')
    >>> (entries, len(skipped))
    ([], 1)
    >>> ("读出来是一个列表" in skipped[0], "不是一串文字" in skipped[0], "第 1 条" in skipped[0])
    (True, True, True)

    `url` 排成两条顺带更正了那句理由：以前它落在「多半是 YAML 折行」上，
    把人支去查一处根本不存在的折行（真折行是上面那一格，两句现在分得开了）。

    >>> _, dropped = parse_channels("channels:\\n  - name: 两条\\n    url:\\n"
    ...                             "      - http://a/1.m3u8\\n      - http://b/2.m3u8\\n")
    >>> dropped[0].split(" —— ")[0]
    "第 1 条 的 `url` 读出来是一个列表（['http://a/1.m3u8', 'http://b/2.m3u8']），不是一串地址"
    >>> "要两条线路就分成两条" in dropped[0]
    True

    停用日带时刻：以前印一句「按未过期处理」就把它放进表，而那一天已经过去 8 个月。

    >>> parse_channels("channels:\\n  - name: 带时刻\\n    url: http://a/1.m3u8\\n"
    ...                "    expires: 2026-01-05 12:00:00\\n")[1]
    ['第 1 条 带时刻：有效期 2026-01-05 已过']

    留空那一种照旧是「不限」（真配置写的就是 `expires: ""`，那份文件的第 18 行说的）。

    >>> parse_channels('channels:\\n  - name: 留空\\n    url: http://a/1.m3u8\\n    expires: ""\\n')[0][0].name
    '留空'

    另一档：`tvg_id` 排成两条时线路照样能看，所以它留下、那一格丢成空，警告照印。
    （这一格把 stdout 收进罐子 —— 印出来的话也是产物，不只是返回值对。）

    >>> import contextlib, io
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):
    ...     kept, drop = parse_channels("channels:\\n  - name: 两条id\\n    url: http://a/1.m3u8\\n"
    ...                                 "    tvg_id:\\n      - hunan\\n      - hn\\n")
    ...
    >>> ([(x.name, x.tvg_id, x.group) for x in kept], drop)
    ([('两条id', '', '')], [])
    >>> ("tvg_id" in buf.getvalue(), "照样进表" in buf.getvalue())
    (True, True)

    同档的还有 `group`：它是「认不上频道名时归哪一组」，坏了不影响这条能不能看，
    所以也是留线路、丢组名，加一行警告。

    >>> buf2 = io.StringIO()
    >>> with contextlib.redirect_stdout(buf2):
    ...     g, gs = parse_channels("channels:\\n  - name: 两条group\\n    url: http://a/1.m3u8\\n"
    ...                            "    group:\\n      - shizhou\\n      - hunantv\\n")
    ...
    >>> ([(x.name, x.group) for x in g], gs, "group" in buf2.getvalue())
    ([('两条group', '')], [], True)

    真配置那一份过一遍闸：每一条都进表、一条都不许被形状闸跳掉。
    2.47 的第一版就是这一格撞红的 —— 它把 `expires: ""` 当成「写了没填」停下来，
    于是家里唯一那条手工线路从表上消失了（量出来的那一句在计划书 §2.47）。
    这一格故意只问条数、不钉台名：往这份文件里再加一条线路不该把用例撞红。

    >>> real = Path(__file__).resolve().parents[2] / "config" / "sources_local.yaml"
    >>> body = real.read_text(encoding="utf-8")
    >>> n = len(yaml.safe_load(body)["channels"])
    >>> entries, skipped = parse_channels(body, where=str(real))
    >>> (len(entries) == n > 0, skipped)
    (True, [])

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
        at = f"第 {i + 1} 条"
        # 名字、地址、停用日这三格写坏了**只停这一条**：理由进 `skipped`，屏幕上印得出来。
        # 这里和 `load_sources`（2.46，一处坏值退 1、整场不出表）故意不对称：那一份只有三行
        # 聚合源，读法一坏整张表的来历就不干净了；这一份其余各条是各自核对过的，
        # 凭第 7 条少打一个引号把前 6 条一起扔掉，是拿用户的第一线陪葬。
        try:
            name = text_value(raw.get("name"), where=at, key="name",
                              what="一串文字", advice=_NAME_ADVICE)
            url = text_value(raw.get("url"), where=at, key="url",
                             what="一串地址", advice=_URL_ADVICE)
            exp = date_value(raw.get("expires", _NOT_SET), where=at, key="expires")
        except ValueError as e:
            # 那句话自己带「第 N 条 的 `name` …」，不再冠一遍 `第 N 条：`（会重复）
            skipped.append(str(e))
            continue
        for warn in check_keys(raw, where=f"{at} {name or '（没名字）'}",
                               known=CHANNEL_KEYS, notes=CHANNEL_NOTES):
            print(f"    ⚠️ {warn}")
        if not name or not url:
            skipped.append(f"{at}：缺 {'url' if name else 'name'}")
            continue
        if any(c.isspace() for c in url):
            skipped.append(f"{at} {name}：url 里有空白，多半是 YAML 折行")
            continue
        if is_expired(exp):
            skipped.append(f"{at} {name}：有效期 {exp} 已过")
            continue
        # `tvg_id` / `group` 与上面三格不同档：这两格坏了线路照样能看，缺的只是
        # 「对哪个台」「归哪一组」，所以降级成空 + 印一行警告，而不是扔一条活线路出表。
        try:
            tvg = text_value(raw.get("tvg_id"), where=f"{at} {name}", key="tvg_id",
                             what="一串 id", advice=_TVG_ADVICE)
        except ValueError as e:
            print(f"    ⚠️ {e}；这一格按空处理，线路照样进表")
            tvg = ""
        try:
            group = text_value(raw.get("group"), where=f"{at} {name}", key="group",
                               what="一串组名", advice=_GROUP_ADVICE)
        except ValueError as e:
            print(f"    ⚠️ {e}；这一格按空处理，线路照样进表")
            group = ""
        out.append(Entry(
            name=name, url=url,
            tvg_id=tvg,
            group=group,
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
