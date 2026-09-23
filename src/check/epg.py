"""EPG（节目单）那一侧的对齐：输出里的 `tvg-id` 要能在节目单里真找得到。

为什么要这一层（计划书 P3）：`tvg-id` 是 APTV 拿去和 XMLTV 的 `<channel id>` 对接的唯一钥匙，
可它以前是**顺手抄来的** —— 同一个频道在上游有好几种写法（`CCTV-1` 与 `CCTV-1综合`），
谁第一个创建频道桶谁就决定输出里那个 id（`src/cli.py` 里 `bucket["tvg_id"] = bucket["tvg_id"] or res.tvg_id`）。
2026-09-21 量过：13 个央视台因此带着中文后缀，而节目单里全是 `CCTV-1`/`CCTV10` 那种写法，
**这些台本来能配上节目单，被自己的 id 写法挡掉了**。

于是这里定的规矩：`tvg-id` 不再由源的到达顺序决定，而是由「选定的节目单里到底有哪个 id」决定 ——
挑得到就用节目单的写法，挑不到才沿用上游的，并且每一次替换都要能在报告里回看出是哪一条规则命中的。
所以这个模块只做「对得上对不上」的判断，不猜：

  * 全等（归一化之后）优先；
  * 只有**纯 ASCII 的台号**（CCTV 系）允许前缀认，因为它们的后缀是栏目名（`CCTV-10科教` 就是 `CCTV10`）；
  * 中文名不做前缀，免得把「长沙新闻」当成「长沙新闻综合」——那是两个台；
  * `CCTV-5+` 这种带加号的台号不许被前缀认到 `CCTV5` 上，尾巴必须是纯中文才算栏目名后缀。

节目单本身怎么来的、地址是谁写的，见 `config/epg.yaml` 与 `scripts/epg_check.py`。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

_ATTR = re.compile(r'([a-zA-Z-]+)="([^"]*)"')
# 一个 <channel> 块到哪为止：常见写法是「<channel id>…<display-name>…</channel>」，
# 但也见过自闭合的，所以拿「下一个 channel/programme 标签」当块尾，不指望 </channel> 一定在。
_CHANNEL = re.compile(r'<channel\b([^>]*)>(.*?)(?=<channel\b|<programme\b|</tv>|\Z)', re.S)
# <programme> 块只取属性那一段：`start=` 和 `channel=` 谁在前各家不一样（2.34），
# 所以属性各自搜，不写成一个顺序敏感的大正则。
_PROGRAMME = re.compile(r'<programme\b([^>]*)>')
_START = re.compile(r'\bstart="(\d{8})')
_CHAN = re.compile(r'\bchannel="([^"]*)"')
_CJK = re.compile(r'[一-鿿]{1,4}$')


@dataclass
class Epg:
    """一份 XMLTV 节目单被扫出来的样子（只留配对频道用得上的那几列）。"""

    ids: list[str] = field(default_factory=list)
    display: dict[str, str] = field(default_factory=dict)   # channel id -> display-name
    days: Counter = field(default_factory=Counter)           # "YYYYMMDD" -> 节目条数
    day_chans: dict[str, set] = field(default_factory=dict)  # "YYYYMMDD" -> 那天真有条目的 channel id
    progs: int = 0
    generator: str = ""

    @property
    def n_channels(self) -> int:
        return len(self.ids)


def parse_tv(text: str) -> Epg:
    """扫 XMLTV：收 channel 的 id 与 display-name，收 programme 覆盖了哪几天。

    用正则不用 ElementTree：最大的一份 2.5MB，整棵 DOM 建出来只为数几个属性不值当；
    各家 EPG 的写法差别也就是缩进与实体引用，抓 `id=` 和 `start="YYYYMMDD"` 两种形态够用。

    >>> e = parse_tv('''<?xml version="1.0"?><tv generator-info-name="demo">
    ...   <channel id="CCTV-1"><display-name lang="zh">CCTV1</display-name></channel>
    ...   <channel id="湖南卫视"><display-name lang="zh">湖南卫视</display-name></channel>
    ...   <programme channel="CCTV-1" start="20260921000000 +0800"><title lang="zh">新闻</title></programme>
    ...   <programme channel="湖南卫视" start="20260921200000 +0800"><title lang="zh">歌手</title></programme>
    ...   <programme channel="湖南卫视" start="20260922000000 +0800"><title lang="zh">重播</title></programme>
    ... </tv>''')
    >>> e.ids
    ['CCTV-1', '湖南卫视']
    >>> e.display["CCTV-1"]
    'CCTV1'
    >>> dict(e.days)
    {'20260921': 2, '20260922': 1}
    >>> {d: sorted(v) for d, v in e.day_chans.items()}
    {'20260921': ['CCTV-1', '湖南卫视'], '20260922': ['湖南卫视']}
    >>> e.progs, e.generator
    (3, 'demo')

    `start=` 和 `channel=` 的先后不固定（`e.erw.cc` 那份是 start 在前的），所以两个属性
    各自在整段属性里搜，不指望谁排在谁前面：

    >>> dict(parse_tv('<tv><programme start="20260921000000 +0800" channel="a"/></tv>').days)
    {'20260921': 1}

    自闭合的 channel 也要收到 id，不能因为等不到 `</channel>` 就把后面整段吞进去：

    >>> parse_tv('<tv><channel id="a"/><programme channel="a" start="20260921000000 +0800"/>'
    ...          '<channel id="b"><display-name lang="zh">B</display-name></channel></tv>').ids
    ['a', 'b']

    拿回来的可能是一段 HTML 报错页，那种情况当空单处理，不抛异常：

    >>> parse_tv("<html>502 Bad Gateway</html>").ids
    []
    """
    e = Epg()
    g = re.search(r'generator-info-name="([^"]*)"', text[:2000])
    if g:
        e.generator = g.group(1)
    for attrs, body in _CHANNEL.findall(text):
        cid = dict(_ATTR.findall(attrs)).get("id", "").strip()
        if not cid:
            continue
        dn = re.search(r'<display-name[^>]*>([^<]*)</display-name>', body)
        e.ids.append(cid)
        e.display[cid] = (dn.group(1).strip() if dn else "")
    e.progs = len(re.findall(r'<programme\b', text))
    for attrs in _PROGRAMME.findall(text):
        st = _START.search(attrs)
        if not st:
            continue                       # 没有 start 的节目块进不了按天的账
        day = st.group(1)
        e.days[day] += 1
        ch = _CHAN.search(attrs)
        if ch:
            e.day_chans.setdefault(day, set()).add(ch.group(1))
    return e


def norm(name: str) -> str:
    """频道名归一，用来把「CCTV-10」和「CCTV10」、「XX 频道」和「XX」对上。

    >>> norm("CCTV-10"), norm("CCTV 10"), norm("cctv10")
    ('cctv10', 'cctv10', 'cctv10')
    >>> norm("  湖南卫视 ")
    '湖南卫视'
    >>> norm("CCTV-5+")               # 加号是台号的一部分，不归一掉
    'cctv5+'
    >>> norm("长沙女性频道")
    '长沙女性'
    """
    s = re.sub(r"[\s_\-()（）\[\]【】]+", "", name or "").lower()
    return s.replace("频道", "")


def prefix_ok(target: str, key: str) -> bool:
    """`key` 能不能作为 `target` 的前缀认下来。规则见模块开头那四条。

    央视系允许（后缀是栏目名，且键是纯台号）：

    >>> prefix_ok("cctv10科教", "cctv10")
    True
    >>> prefix_ok("cctv1综合", "cctv1")
    True

    中文名不许前缀 —— 「长沙新闻」和「长沙新闻综合」在湖南广电里是两个不同的频道：

    >>> prefix_ok("长沙新闻综合", "长沙新闻")
    False

    带加号的不许退到不带加号的那个台上（CCTV-5+ 是赛事版，CCTV-5 是体育）：

    >>> prefix_ok("cctv5+赛事", "cctv5")
    False

    尾巴太长也不认（超过 4 个汉字就不是栏目名了，多半是另一个台）：

    >>> prefix_ok("cctv10科教环球记录", "cctv10")
    False
    """
    if key == target or not target.startswith(key):
        return False
    if not key.isascii():
        return False                       # 只有纯台号（CCTV 系）配前缀
    tail = target[len(key):]
    if tail.startswith("+"):
        return False                       # 加号属于台号，不是栏目名
    return bool(_CJK.match(tail))


def best_key(target: str, keys) -> str:
    """归一后的台名对节目单的键做「全等 → 受控前缀」两级匹配，返回命中的键（没有就空串）。

    >>> best_key("cctv10科教", {"cctv1": "1", "cctv10": "10"})     # 两个前缀都算对，取最长
    'cctv10'
    >>> best_key("cctv1综合", {"cctv1": "1", "cctv10": "10"})
    'cctv1'
    >>> best_key("cctv5+赛事", {"cctv5": "5"})                     # 宁缺勿错
    ''
    >>> best_key("湖南卫视", {"cctv": "x", "湖南卫视": "hn"})       # 全等优先
    '湖南卫视'
    >>> best_key("湘潭新闻综合", {"cctv1": "1", "湖南卫视": "hn"})
    ''
    """
    if target in keys:
        return target
    cands = [k for k in keys if len(k) >= 4 and prefix_ok(target, k)]
    return max(cands, key=len) if cands else ""


def build_index(epg: Epg) -> dict[str, str]:
    """节目单 -> {归一化键: 节目单里那个 channel id}。display-name 和 id 各算一个键。

    两个都塞是因为各家写法不一：112114 那份 id 是 `CCTV10`、display-name 也是 `CCTV10`；
    erw 那份 id 是数字 `1`、display-name 才是 `CCTV1` —— 只索引 id 的话后者一条都配不上。

    >>> e = parse_tv('<tv><channel id="81"><display-name lang="zh">湖南卫视</display-name>'
    ...              '</channel><channel id="CCTV1"><display-name lang="zh">CCTV1</display-name>'
    ...              '</channel></tv>')
    >>> sorted(build_index(e).items())
    [('81', '81'), ('cctv1', 'CCTV1'), ('湖南卫视', '81')]

    （`81` 也会成为一个键：erw 那份的 id 就是纯数字，归一化之后仍然是它自己。
    留着它没有害处 —— 我们的台名不会是「81」，`best_key` 也就撞不上。）
    """
    out: dict[str, str] = {}
    for cid, dn in epg.display.items():
        for key in (norm(dn), norm(cid)):
            if key:
                out.setdefault(key, cid)
    return out


def align_channel(name: str, tvg_id: str, index: dict[str, str],
                  idset: set[str] | None = None) -> tuple[str, str]:
    """一个频道在这份节目单里该用哪个 id，以及是怎么对上的（`id`/`name`/空）。

    >>> idx = {"cctv10": "CCTV10", "湖南卫视": "湖南卫视"}
    >>> ids = {"CCTV10", "湖南卫视"}
    >>> align_channel("CCTV-10科教", "CCTV-10科教", idx, ids)
    ('CCTV10', 'name')
    >>> align_channel("湖南卫视", "湖南卫视", idx, ids)
    ('湖南卫视', 'id')
    >>> align_channel("湘潭新闻综合", "湘潭新闻综合", idx, ids)
    ('', '')

    节目单里已经有我们手上这个 id 了，就不动手 —— 替换只发生在「对得上另一个写法」时：

    >>> align_channel("CCTV-1", "CCTV-1", {"cctv-1": "CCTV-1"}, {"CCTV-1"})
    ('CCTV-1', 'id')
    """
    idset = idset if idset is not None else set(index.values())
    if tvg_id and tvg_id in idset:
        return tvg_id, "id"
    key = best_key(norm(name), index) or best_key(norm(tvg_id), index)
    return (index[key], "name") if key else ("", "")


def align_all(channels: list[tuple[str, str]], epg: Epg) -> list[dict]:
    """整张表对一遍，返回逐台的一行：原来的 id、该用的 id、怎么对上的。

    >>> e = parse_tv('''<tv>
    ...   <channel id="2"><display-name lang="zh">CCTV-10</display-name></channel>
    ...   <channel id="湖南卫视"><display-name lang="zh">湖南卫视</display-name></channel>
    ...   <programme channel="湖南卫视" start="20260921000000 +0800"></programme>
    ... </tv>''')
    >>> rows = align_all([("CCTV-10科教", "CCTV-10科教"), ("湖南卫视", "湖南卫视"),
    ...                   ("湘潭新闻综合", "湘潭新闻综合")], e)
    >>> rows[0]["old_id"], rows[0]["new_id"], rows[0]["how"]        # 央视那个台被换成节目单的写法
    ('CCTV-10科教', '2', 'name')
    >>> rows[1]["old_id"] == rows[1]["new_id"] and rows[1]["how"] == "id"
    True
    >>> rows[2]["new_id"] == rows[2]["old_id"] and rows[2]["how"] == ""
    True

    对不上的那个台 `new_id` 等于 `old_id`、`how` 是空串 —— 「不动」也要留一行，
    报告里得数得出「98 个台里有几个真配上」，不能让它们凭空消失。

    >>> sum(1 for r in rows if r["how"])
    2
    """
    index = build_index(epg)
    idset = set(epg.ids)
    return [{"name": n, "old_id": t, "new_id": nid or t, "how": how}
            for t, n in channels
            for nid, how in [align_channel(n, t, index, idset)]]


def apply_ids(channels: list, doc: Epg) -> dict:
    """按节目单改写这些频道的 `tvg_id`（原地），返回一份能对账的统计。

    这是「谁先创建频道桶谁决定 id」的替代者：改写只取决于节目单里有没有这个台，
    与上游到达顺序无关 —— 同一份节目单进来，湖南联通先到的那张表和新湖南先到的那张表
    会得到同一个 id。

    最关键的一条是**空单什么都不动**：节目单取不到、或者取回来是份 HTML 报错页时
    （`Epg()` 就是那种情况），输出必须和没有这一层之前逐字节一致。
    不然「EPG 对齐」这个功能本身会变成一个新的失效面 —— 上游 EPG 一挂就把电视的表搞乱。

    >>> class C:
    ...     def __init__(self, name, tvg_id): self.name, self.tvg_id = name, tvg_id
    >>> doc = parse_tv('<tv>'
    ...   '<channel id="CCTV10"><display-name lang="zh">CCTV10</display-name></channel>'
    ...   '<channel id="湖南卫视"><display-name lang="zh">湖南卫视</display-name></channel>'
    ...   '</tv>')
    >>> cs = [C("CCTV-10科教", "CCTV-10科教"), C("湖南卫视", "湖南卫视"),
    ...       C("湘潭新闻综合", "湘潭新闻综合")]
    >>> st = apply_ids(cs, doc)
    >>> [c.tvg_id for c in cs]
    ['CCTV10', '湖南卫视', '湘潭新闻综合']
    >>> st["hit_id"], st["hit_name"], st["miss"]
    (1, 1, ['湘潭新闻综合'])
    >>> st["changed"]
    [('CCTV-10科教', 'CCTV-10科教', 'CCTV10')]
    >>> apply_ids(cs, Epg())["changed"], [c.tvg_id for c in cs]
    ([], ['CCTV10', '湖南卫视', '湘潭新闻综合'])
    """
    rows = align_all([(c.tvg_id, c.name) for c in channels], doc)
    changed, miss = [], []
    for c, r in zip(channels, rows):
        if r["how"] == "name" and r["new_id"] != c.tvg_id:
            changed.append((c.name, c.tvg_id, r["new_id"]))
            c.tvg_id = r["new_id"]
        elif not r["how"]:
            miss.append(c.name)
    return {"rows": rows,
            "hit_id": sum(1 for r in rows if r["how"] == "id"),
            "hit_name": sum(1 for r in rows if r["how"] == "name"),
            "changed": changed, "miss": miss, "total": len(rows)}


def has_today(epg: Epg, today: str) -> bool:
    """这份节目单覆盖不覆盖 `today`（YYYYMMDD）。空单一律算不覆盖。

    >>> e = parse_tv('<tv><channel id="a"/><programme channel="a" start="20260921000000 +0800"/>'
    ...              '</tv>')
    >>> has_today(e, "20260921"), has_today(e, "20260922"), has_today(Epg(), "20260921")
    (True, False, False)
    """
    return bool(epg.days) and today in epg.days


def channels_on(epg: Epg, day: str) -> int:
    """那天**真有条目**的频道有几个（跟 `n_channels` 不是一件事：那是单子声明了多少个台）。

    >>> e = parse_tv('<tv><channel id="a"/><channel id="b"/><channel id="c"/>'
    ...              '<programme channel="a" start="20260921000000 +0800"/>'
    ...              '<programme channel="b" start="20260921010000 +0800"/>'
    ...              '<programme channel="a" start="20260922000000 +0800"/></tv>')
    >>> channels_on(e, "20260921"), channels_on(e, "20260922"), channels_on(e, "20260923")
    (2, 1, 0)
    >>> channels_on(Epg(), "20260921")
    0
    """
    return len(epg.day_chans.get(day, ()))


THIN_FLOOR = 40      # 一份本来就没几个台的单子（各家自制的测试单）不去判它


def thin_today(epg: Epg, today: str, *, floor: int = THIN_FLOOR, ratio: int = 4) -> bool:
    """`today` 有节目，但满得可疑：另一天有 `floor` 个台以上，今天还不到它的 `1/ratio`。

    为什么要有这一条（2.33 量出来的）：`e.erw.cc` 那份单子写着「覆盖 3 天」，按天数完是
    今天 518 个台 / 17 764 条、另外两天各 **5** 个台 / 157 条 —— 那 5 个是山西台，我们表里
    一个都没有。也就是说对表里那 98 个台，这份单子**只有今天**。形状反过来那天就是事故现场：
    `has_today()` 只看日期在不在集合里，一份被截断的取回会被当好的一整天地用，
    而 98 个台的节目条一起消失。这一条量的就是「有日期，有没有内容」。

    >>> big = "".join(f'<programme channel="x{i}" start="20260920000000 +0800"/>'
    ...               for i in range(40))
    >>> e = parse_tv('<tv>' + big + '<programme channel="x1" start="20260921000000 +0800"/></tv>')
    >>> thin_today(e, "20260921")                      # 昨天 40 个台、今天 1 个
    True
    >>> thin_today(e, "20260920")                      # 满的那天是今天，没什么可疑
    False
    >>> e2 = parse_tv('<tv><programme channel="a" start="20260921000000 +0800"/>'
    ...               '<programme channel="b" start="20260921010000 +0800"/></tv>')
    >>> thin_today(e2, "20260921")                    # 只有今天，没得比 —— 2.33 那份真单子的形状
    False
    >>> thin_today(e2, "20260921", floor=1)           # 门槛挪到 1 个台也不点燃：今天之外根本没有别的日子
    False
    >>> thin_today(Epg(), "20260921")                 # 空单归 has_today 管，不在这儿判
    False
    """
    if not has_today(epg, today):
        return False
    best = max((channels_on(epg, d) for d in epg.days if d != today), default=0)
    return best >= floor and channels_on(epg, today) * ratio < best


def today_ok(epg: Epg, today: str) -> bool:
    """这一份今天能不能用：有今天的日期，且今天不是那种「只剩几个台」的瘦今天。

    `load_epg()` 拿它当「要不要重取」的判据 —— 只看 `has_today()` 的话，一份被截断的
    取回会被当好的一整天地用（2.33），而那种单子恰好让 98 个台的节目条一起消失。

    >>> big = "".join(f'<programme channel="x{i}" start="20260920000000 +0800"/>'
    ...               for i in range(40))
    >>> e = parse_tv('<tv>' + big + '<programme channel="x1" start="20260921000000 +0800"/></tv>')
    >>> has_today(e, "20260921"), today_ok(e, "20260921")     # 日期对，内容不行
    (True, False)
    >>> e2 = parse_tv('<tv><programme channel="a" start="20260921000000 +0800"/></tv>')
    >>> today_ok(e2, "20260921"), today_ok(e2, "20260922")
    (True, False)
    """
    return has_today(epg, today) and not thin_today(epg, today)


def gap_days(epg: Epg, today: str) -> int:
    """最新一天的节目离 `today` 有多少天（负数=比今天还新）。空单返回 0，不抛。

    >>> e = parse_tv('<tv><channel id="a"/><programme channel="a" start="20260807000000 +0800"/>'
    ...              '</tv>')
    >>> gap_days(e, "20260921")
    -45
    >>> gap_days(Epg(), "20260921")
    0
    """
    if not epg.days:
        return 0
    try:
        last = datetime.strptime(max(epg.days), "%Y%m%d")
        now = datetime.strptime(today, "%Y%m%d")
    except ValueError:
        return 0
    return (last - now).days


def span(days: list[str]) -> str:
    """日期区间的写法：一天就写一次，多天写 `首~末`。

    >>> span(["20260921"])
    '20260921'
    >>> span(["20260921", "20260922"])
    '20260921~20260922'
    """
    return days[0] if len(days) == 1 else f"{days[0]}~{days[-1]}"


def coverages(epg: Epg, today: str) -> str:
    """一句话说明这份节目单**今天到底有多少内容**。

    「覆盖 N 天」那种写法被 2.33 量过一次就作废了：e.erw.cc 那份写「覆盖 3 天」，
    实际只有今天有内容，读了的人以为有三天可翻。所以现在报的是台数，不是天数。

    >>> e = parse_tv('<tv><channel id="a"></channel>'
    ...              '<programme channel="a" start="20260921000000 +0800"></programme></tv>')
    >>> coverages(e, "20260921")
    '今天有节目（1 个台有条目）'

    有别的日子的话，把最满的那天摊出来，不写成区间：

    >>> e3 = parse_tv('<tv>'
    ...              '<programme channel="a" start="20260921000000 +0800"></programme>'
    ...              '<programme channel="b" start="20260921000000 +0800"></programme>'
    ...              '<programme channel="a" start="20260920000000 +0800"></programme>'
    ...              '<programme channel="a" start="20260922000000 +0800"></programme></tv>')
    >>> coverages(e3, "20260921")
    '今天有节目（2 个台有条目；其余 2 天最多 1 个台）'

    被截断的那种取回（今天只剩几个台）不复用「今天有节目」这五个字，否则 `usable()`
    那种子串判据会把反面读成正面：

    >>> big = "".join(f'<programme channel="x{i}" start="20260920000000 +0800"/>'
    ...               for i in range(40))
    >>> e4 = parse_tv('<tv>' + big +
    ...               '<programme channel="x1" start="20260921000000 +0800"/></tv>')
    >>> coverages(e4, "20260921")
    '今天只有 1 个台有条目（另外那天 40 个 —— 这份单子像被截断了）'
    >>> "今天有节目" in coverages(e4, "20260921")
    False

    >>> e2 = parse_tv('<tv><channel id="a"></channel>'
    ...                '<programme channel="a" start="20260807000000 +0800"></programme></tv>')
    >>> coverages(e2, "20260921")
    '没有今天的内容（覆盖 1 天：20260807，距今 45 天）'
    >>> coverages(parse_tv("<tv></tv>"), "20260921")
    '一条节目都没有'

    正反两句话刻意不共用子串：「没有今天的内容」里含「有今天」四个字，
    所以判「可用」不能拿「有没有今天」这种问法去 `in`，那样两条分支永远都算通过。

    >>> "今天有节目" in "没有今天的内容（覆盖 1 天：20260807，距今 45 天）"
    False

    没有今天的那一支**故意不改**：它说的「覆盖 N 天」在这里就是字面的「这单子有几天」，
    不误导人；而且 `真机验收单.md` 与计划书 2.31／2.32 都原样引过这句话，动它等于让那些
    记录里引的句子失效。
    """
    if not epg.days:
        return "一条节目都没有"
    days = sorted(epg.days)
    if not has_today(epg, today):
        return (f"没有今天的内容（覆盖 {len(days)} 天：{span(days)}，"
                f"距今 {abs(gap_days(epg, today))} 天）")
    n = channels_on(epg, today)
    others = [d for d in days if d != today]
    if thin_today(epg, today):
        return (f"今天只有 {n} 个台有条目（另外那天 {max(channels_on(epg, d) for d in others)} 个"
                " —— 这份单子像被截断了）")
    if not others:
        return f"今天有节目（{n} 个台有条目）"
    return (f"今天有节目（{n} 个台有条目；其余 {len(others)} 天最多 "
            f"{max(channels_on(epg, d) for d in others)} 个台）")


def load_bytes(raw: bytes) -> tuple[Epg, str]:
    """字节流 -> (节目单, 一行来历说明)。gzip 自动解，非 XMLTV 的响应体当空单。

    >>> e, note = load_bytes(b'<?xml version="1.0"?><tv><channel id="a"></channel></tv>')
    >>> e.ids, note
    (['a'], '56 字节')
    >>> import gzip as _g
    >>> e2, note2 = load_bytes(_g.compress(b'<tv><channel id="b"/></tv>'))
    >>> e2.ids, "gzip" in note2
    (['b'], True)
    >>> load_bytes(b"<html>502 Bad Gateway</html>")[0].ids
    []
    """
    note = f"{len(raw)} 字节"
    if raw[:2] == b"\x1f\x8b":
        raw = gzip_decompress(raw)
        note += f"（gzip，解出 {len(raw)} 字节）"
    text = raw.decode("utf-8", errors="replace")
    head = text[:400]
    if "<tv" not in head and "<?xml" not in head:
        return Epg(), note + "，返回的不是 XMLTV：" + head[:60].replace("\n", " ")
    return parse_tv(text), note


def gzip_decompress(raw: bytes) -> bytes:
    """标准库那一层，单拎出来是为了让上面那行「解出多少字节」的样例好写。

    >>> import gzip as _g
    >>> gzip_decompress(_g.compress(b"hi"))
    b'hi'
    """
    import gzip
    return gzip.decompress(raw)
