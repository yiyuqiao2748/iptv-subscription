"""流地址的可达范围：区分「公网能连」与「只有运营商 IPTV 专网才连得上」。

为什么要有这一步：APTV 只会自动播某个频道的第一条线路，第二条要遥控器手动切。
把覆盖最全、但电视够不到的运营商内网地址排到第一顺位，观感就是「所有台都超时」。

范围只决定同一频道内的先后，不删线路 —— **一条**判错最多少排在前面，代价很小。
但「整档没读到」不是同一回事：那一档规矩一条都不匹配时，内网地址会全部重新占住第一线，
2.49 量到的正是这一格（代价写在上面，也写在 config/reachability.yaml 那份文件的注释里 ——
那句「判错的代价很小」说的是一条规则判错，不是一档规则消失）。
规则表在 config/reachability.yaml，改判不用动代码。
但**键名不能写歪**：`iptv_intrane` 少两个字母等于这一档整个没了，
而那种事在表上是看不出来的（该往后压的照样占第一线），所以 `load_reachability()` 会停下来。
**值也不能写成一行**：`iptv_intranet: .chinamobile.com`（少写方括号）会被逐个字符摊开成
十六条一个字符的规矩，一家主机都匹配不上 —— 后果与键名写歪完全相同（这一档等于没有），
所以那一句同样拦下来（2.49 实测：四张表行数一字不差，而 351 条线路里 138 条的第一线换了地址
（按主机数 136 条）、其中 94 条从公网翻进专网；两格一起少写方括号是 147 条 / 142 条。
这些数**按表上第几个条目**数 —— 拿「表:台名」去重会把同名的第二三格并掉，147 条并成 57 个，
方向永远朝「没事」偏，见 §2.49「口径」）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import yaml

from src.keys import _NOT_SET, check_keys, check_version, str_list_value

REACH_KEYS = ["version", "iptv_intranet", "audio_only"]
# 这两档的键写歪就是整档失效，而表上完全看不出少了一档（2.9 那个真机故障的形状）。
REACH_NOTES = {
    "iptv_intranet": "哪些主机名只有看电视那张网够得着，要往后压",
    "audio_only": "哪些是电台 CDN —— 认不出来它就像直播一样排到第一线",
}

# 「怎么改」那半句，两档各说各的后果（2.49）。写之前先避开断言要用的词：
# 这一族的诊断句里会出现「名单」「一条」，advice 里再写那些会把断言断成假话。
_INTRANET_ADVICE = (
    "这一格是「哪些主机只有看电视那张网够得着」的名单，得写成列表"
    "（一行一条 `  - .chinamobile.com`，或一行 `[.a.com, .b.com]`）。"
    "2.49 实测：`iptv_intranet: .chinamobile.com` 会被逐个字符读成 16 条一个字符的规矩，"
    "一家主机都匹配不上，于是内网地址全被判成「Wi-Fi 直连」、重新排回第一线 —— "
    "09-20 那次真机「订阅加得上、湖南台全部超时」正是这个形状，而出表退 0、什么都不说")
_AUDIO_ADVICE = (
    "这一格是「哪些是电台 CDN」的名单，得写成列表（一行一条 `  - .qingting.fm`）。"
    "2.49 实测：写成一行会被逐个字符读成 12 条一个字符的规矩，电台地址就没人往后压了 —— "
    "它不像内网那样超时，而是点开只出声音，更容易骗过人，同样什么都不会说")

PUBLIC = "public"
INTRANET = "iptv_intranet"
AUDIO = "audio_only"

# 整档全 0 时屏幕那句话里「后果」那一半，两档各说各的（2.50，与 `_INTRANET_ADVICE` 同一分法）。
_DEAD_WHY = {
    INTRANET: "内网地址会被全判成「Wi-Fi 直连」、重新排回第一线 —— 09-20 那次真机"
              "「订阅加得上、湖南台全部超时」就是这个形状（2.49 实测：少写方括号摊成 16 条一个字符的规矩，"
              "四张表行数一字不差）",
    AUDIO: "电台地址没人往后压，点开只剩声音 —— 不像超时那样会让人怀疑线路"
           "（2.49 实测：那一格摊成 12 条一个字符的规矩，屏幕上什么都不说）",
}

# 同一频道内排序用的主键，数字小的排前面：
# 公网视频最可能直接播出来；运营商内网视频要专网，但内容是对的；
# 纯音频排最后，因为它冒充的是「这个台」，播出来只有声音更容易骗过人。
RANK = {PUBLIC: 0, INTRANET: 1, AUDIO: 2}

# 组播/推流协议：Apple TV 走 Wi-Fi 播不了，且属计划书划定的红线
_NON_HTTP = frozenset({"rtp", "rtmp", "rtsp", "udp", "srt"})


class Reachability:
    def __init__(self, intranet_rules: Iterable[str] = (), audio_rules: Iterable[str] = ()):
        self.rules = tuple(r.strip() for r in intranet_rules if r and r.strip())
        self.audio_rules = tuple(r.strip() for r in audio_rules if r and r.strip())

    def _matches(self, rule: str, host: str) -> bool:
        """一条规矩匹不匹配这个主机。`_classify` 与 `coverage` 都走这里 ——
        「这条规则抓到几条」和「这条线路判成哪一档」不允许各说一套（2.50）。"""
        r = rule.lower()
        if r.startswith("."):
            return host.endswith(r) or host == r[1:]
        if r.endswith(":"):
            return host.startswith(r)
        return host == r

    def _classify(self, url: str) -> tuple[str, str | None]:
        """(档位, 归给哪一条规则)。规则一条都没碰上时，第二格是 `None`。

        归因走的是 `scope()` 同一圈 for：电台档先查（蜻蜓 FM 挂着一个电视频道名，
        它同时像两条名单时按电台算），再查内网档，同档内按文件里的书写顺序。
        **第一个匹配上的那条**才算抓到 —— 两条都记会把一条不起作用的规则读成两条都在起作用
        （2.49 的边界；2.50 量到：本轮 `.chinamobile.com` 字面命中 210 条上游线路，
        其中 192 条的主机就是 `tvgslb.hn.chinamobile.com`，归它自己的只有 18 条）。

        >>> r = Reachability(["tvgslb.hn.chinamobile.com", ".chinamobile.com"], [".qingting.fm"])
        >>> r._classify("http://tvgslb.hn.chinamobile.com:8089/x.m3u8")   # 归第一条
        ('iptv_intranet', 'tvgslb.hn.chinamobile.com')
        >>> r._classify("http://gw.hn.chinamobile.com/x.m3u8")            # 第二条才轮得上
        ('iptv_intranet', '.chinamobile.com')
        >>> r._classify("rtp://@239.130.1.6:6002")               # 组播由代码定档，不欠任何规则
        ('iptv_intranet', None)
        """
        parts = urlsplit(url)
        if parts.scheme.lower() in _NON_HTTP:
            return INTRANET, None                 # 组播/推流由代码直接定档，不看名单
        host = (parts.hostname or url).lower()
        for tier, rules in ((AUDIO, self.audio_rules), (INTRANET, self.rules)):
            for rule in rules:
                if self._matches(rule, host):
                    return tier, rule
        return PUBLIC, None

    def coverage(self, urls: Iterable[str]) -> dict:
        """这一堆地址里，每条规则各抓到几条（2.50）。

        两个数不是一回事：`any` 是**字面命中**（含被别的规则盖住的），`own` 是**归它的**
        （`_classify` 里第一条匹配上的那条才拿分）。它们不一样本身就是结论 ——
        2.50 量到：真配置里 `.chinamobile.com` 字面命中 210 条，可其中 192 条的主机就是上一条
        精确匹配那一家，`own` 只剩 18 —— 只问「有没有命中」会把一条几乎吃不到分的规则
        读成一条在起作用的规则，反过来也一样（`2409:` 归它 67 条，却一条都没挤进表）。

        口径：数的是**条目**，同一条地址在两个源里各出现一次就记两次
        （本轮 1869 条、去重是 1804 条）。这一格不先去重，因为窗口是按条目切的。

        为什么问的那一堆得是**上游候选**而不是只有表：**「命中 0 条」有两种意义**（§2.49 的边界）。
        电台那条 `.qingting.fm` 上游抓得到 22 条，只是被「每个频道最多留 3 条」（`--max-lines`）
        那个窗口挤出了表 —— 它**在起作用**；`2409:` 更典型：上游 67 条、摊在 29 家主机上，
        表上却一条都看不见，光回问表会把它读成一条废规则。真「没东西可判」的是 `2408:`
        （上游 0 / 表 0 / 第一线 0，IPv6 那两条里今天只有另一段有货）——
        **没东西可判**不等于坏了。只回问表会把前两种读成第三种，
        于是「这条规则该不该删」变成一个凭表回答不了的问题。

        >>> r = Reachability(["tvgslb.hn.chinamobile.com", ".chinamobile.com", "2409:"],
        ...                  [".qingting.fm"])
        >>> urls = ["http://tvgslb.hn.chinamobile.com:8089/a.m3u8",
        ...         "http://tvgslb.hn.chinamobile.com:8089/b.m3u8",
        ...         "http://gw.hn.chinamobile.com/c.m3u8",
        ...         "http://ls.qingting.fm/live/4877.m3u8",
        ...         "http://107.150.60.122/live/hnwshd.m3u8",
        ...         "rtp://@239.130.1.6:6002"]
        >>> cov = r.coverage(urls)
        >>> cov["rules"][".chinamobile.com"]      # 字面 3 条，其中 2 条被上一条盖住，归它 1 条
        {'tier': 'iptv_intranet', 'any': 3, 'own': 1, 'eaten_by': {'tvgslb.hn.chinamobile.com': 2}}
        >>> cov["rules"]["tvgslb.hn.chinamobile.com"]["eaten_by"]   # 它排第一，没人抢得到它
        {}
        >>> # 没被抢的时候是空的，不许是 None 或缺键（缺了键，下面那句括号就没得印）
        >>> r.coverage(["http://gw.hn.chinamobile.com/c.m3u8"])["rules"][".chinamobile.com"]["eaten_by"]
        {}
        >>> cov["rules"]["tvgslb.hn.chinamobile.com"]["any"], cov["rules"]["tvgslb.hn.chinamobile.com"]["own"]
        (2, 2)
        >>> cov["rules"][".qingting.fm"]["own"]                  # 电台那条抓到了
        1
        >>> cov["tiers"]["iptv_intranet"]                        # 档级：3 条规则，归它们 3 条
        {'rules': 3, 'own': 3}
        >>> cov["code_intranet"], cov["total"]        # 组播那条不欠任何规则，单独记一格
        (1, 6)
        >>> r.coverage([])["rules"]["2409:"]          # 一堆地址都没有：各条都是 0，不是崩
        {'tier': 'iptv_intranet', 'any': 0, 'own': 0, 'eaten_by': {}}
        >>> Reachability(["a.com", "a.com"]).coverage([])["dup"]   # 同一条写了两遍（形状对、内容错）
        ['a.com']
        """
        tiers = {"iptv_intranet": self.rules, "audio_only": self.audio_rules}
        order = [(tier, rule) for tier in ("iptv_intranet", "audio_only") for rule in tiers[tier]]
        seen: dict[str, int] = {}
        for _, rule in order:
            seen[rule] = seen.get(rule, 0) + 1
        urls = list(urls)
        any_n: dict[str, int] = {}
        own_n: dict[str, int] = {}
        # 「谁抢的」（2.52）：某条规则字面命中的那些地址，实际被判给了谁。以前只说
        # 「被排在前面的那条盖住了」，不说是哪一条 —— 那一格 2.50 留在边界里。
        eats: dict[str, dict[str, int]] = {}
        code = 0
        for url in urls:
            parts = urlsplit(url)
            if parts.scheme.lower() in _NON_HTTP:
                code += 1                 # 组播由代码定档；算进去会把「0 命中」读成假非 0
                continue
            host = (parts.hostname or url).lower()
            hits = [rule for rule in seen if self._matches(rule, host)]
            for rule in hits:
                any_n[rule] = any_n.get(rule, 0) + 1
            own = self._classify(url)[1]
            if own is not None:
                own_n[own] = own_n.get(own, 0) + 1
                for rule in hits:
                    if rule != own:
                        got = eats.setdefault(rule, {})
                        got[own] = got.get(own, 0) + 1
        per_rule = {rule: {"tier": tier, "any": any_n.get(rule, 0), "own": own_n.get(rule, 0),
                           # 按条数从多到少、条数相同按名单里的先后 —— 顺序必须可重跑复现
                           "eaten_by": dict(sorted(
                               eats.get(rule, {}).items(),
                               key=lambda kv: (-kv[1], [r for _, r in order].index(kv[0]))))}
                    for tier, rule in order}
        return {"rules": per_rule,
                "tiers": {tier: {"rules": len(tiers[tier]),
                                 "own": sum(v["own"] for v in per_rule.values()
                                            if v["tier"] == tier)}
                          for tier in tiers},
                "code_intranet": code, "total": len(urls),
                "dup": sorted(r for r, n in seen.items() if n > 1)}

    def rule_states(self, up: Iterable[str], table: Iterable[str],
                    first: Iterable[str]) -> list[dict]:
        """一条规则一行，摆出它在「上游候选 / 进表 / 第一线」三层的数，和一个说法（2.50）。

        说法只有五种，每一种都能被那三层的数解释：

        * `first` —— 它压住的线路里，有台子的第一线就是它管出来的（这一档在那几个台上是唯一来源）；
        * `table` —— 进了表、没占住第一线：这正是这两档名单该干的活；
        * `out`   —— 上游归它、表里没有：被「每台 3 格 / 每家 2 条」那个窗口或者名单挡在外面，**不是坏了**；
        * `shadow` —— 字面命中、可一条都不归它：那些地址全被判给了别条规则（`eaten_by` 里点名，2.52），
          改不改都不动本轮的表；
        * `none`  —— 连上游都没抓到一起：内容不对（全角点、带协议前缀、域名过期、摊成单字），
          或者今天这批线路里就是没有它要判的那种地址。

        为什么 `shadow` 和 `none` 必须分开（2.49 的那条边界）：真配置里 `.chinamobile.com`
        字面命中一堆、归它 0 条，那是被上一条精确匹配盖住 —— 读成 `none` 就等于宣布一条
        没坏的法律是废法，而人真会去删它。

        >>> r = Reachability(["tvgslb.hn.chinamobile.com", ".chinamobile.com", "2409:"],
        ...                  [".qingting.fm"])
        >>> up = ["http://tvgslb.hn.chinamobile.com:8089/a.m3u8",
        ...       "http://gw.hn.chinamobile.com/c.m3u8",
        ...       "http://ls.qingting.fm/live/4877.m3u8",
        ...       "http://107.150.60.122/live/hnwshd.m3u8"]
        >>> for x in r.rule_states(up, up[:1], up[:1]):
        ...     print(x["rule"], x["state"])                # 三条内网规矩各有各的三种下场
        tvgslb.hn.chinamobile.com first
        .chinamobile.com out
        2409: none
        .qingting.fm out
        >>> x = r.rule_states(up, up[:2], up[:1])[1]        # gw 那条挤进表了，但没占住第一线
        >>> x["own_up"], x["own_table"], x["own_first"], x["state"]
        (1, 1, 0, 'table')
        >>> y = r.rule_states(up[:1], [], [])[1]            # 上游只有 tvgslb 那一条：第二条被盖住
        >>> (y["any_up"], y["own_up"], y["state"])
        (1, 0, 'shadow')
        >>> y["eaten_by"]                                   # 那句「被前面那条盖住」从此有名字（2.52）
        {'tvgslb.hn.chinamobile.com': 1}
        >>> all(x["any_up"] - x["own_up"] == sum(x["eaten_by"].values())   # 括号里那句必须对上差额
        ...     for x in r.rule_states(up, up, up))
        True
        >>> z = Reachability(["tvgslb.hn.chinamobile.com"], [".chinamobile.com"])
        >>> z.rule_states(up[:1], [], [])[0]["eaten_by"]   # 抢它的电台规则，在配置里写在**后面**
        {'.chinamobile.com': 1}
        >>> dead_tiers(r.rule_states(up, [], []))           # 表整个空的：内网档还有抓到东西的规则
        []
        >>> dead_tiers(r.rule_states(up[:1], [], []))       # 内网档有 shadow/out：不算死
        ['audio_only']
        >>> dead_tiers(Reachability(["2409:"], []).rule_states(up, up, up))
        ['iptv_intranet']
        """
        cu, ct, cf = self.coverage(up), self.coverage(table), self.coverage(first)
        rows = []
        for rule, v in cu["rules"].items():
            own_t, own_f = ct["rules"][rule]["own"], cf["rules"][rule]["own"]
            state = ("first" if own_f else "table" if own_t else
                     "out" if v["own"] else "shadow" if v["any"] else "none")
            rows.append({"tier": v["tier"], "rule": rule, "any_up": v["any"], "own_up": v["own"],
                         "own_table": own_t, "own_first": own_f, "state": state,
                         # 「字面命中、归它 0」里那 0 是**谁**造成的（2.52）：2.50 的边界第 2 条
                         # 欠的就是这个名字。差额 = 这些条数之和，上面有一行 doctest 钉着。
                         "eaten_by": v["eaten_by"]})
        return rows

    def scope(self, url: str) -> str:
        """判一条流地址属于哪个可达范围。

        >>> r = Reachability([".chinamobile.com", "58.20.64.92", "2409:"], [".qingting.fm"])
        >>> r.scope("http://tvgslb.hn.chinamobile.com:8089/x.m3u8")   # 后缀匹配
        'iptv_intranet'
        >>> r.scope("http://58.20.64.92:9999/tsfile/live/1000_1.m3u8")  # 精确匹配
        'iptv_intranet'
        >>> r.scope("http://[2409:8087:8:21::18]:6610/x.m3u8")        # IPv6 网段前缀
        'iptv_intranet'
        >>> r.scope("rtp://@239.130.1.6:6002")                        # 组播一律算内网
        'iptv_intranet'
        >>> r.scope("http://ls.qingting.fm/live/4877.m3u8")           # 电台冒充电视
        'audio_only'
        >>> r.scope("http://107.150.60.122/live/hnwshd.m3u8")         # 公网
        'public'
        """
        return self._classify(url)[0]

    def rank(self, url: str) -> int:
        return RANK[self.scope(url)]


def dead_tiers(rows: Iterable[dict]) -> list[str]:
    """整档一条都没抓到的那些档名 —— 这是 `report.md` 那一节唯一值得朝屏幕上喊一句的部分。

    为什么问「整档」而不是「某条」：一条规则 0 命中可以有很多无害的理由（本轮真跑的七行里就有三种
    不坏的 0：`2408:` 上游 0 —— 今天这批线路里没有那一段 IPv6 地址，它是留着防身的；
    `.chinamobile.com` 归它 18 条却表里 0 —— 被窗口挡的；`2409:` 上游 67 条同样表里 0；
    再往「被前一条盖住」那一种算 `shadow`，也不在这道里报），而**整档每条都是 `none`** 只剩两种：
    这一档摊开了（§2.49 那一族），或者整档内容集体过期。两种都是「这一档等于没配」，
    也就是 2.9 那个真机故障的形状。
    所以逐条的数进 `report.md`，整档的 0 才上屏幕 —— 否者每一轮都要喊三句没用的。

    空名单（`iptv_intranet: []`）不算：那是显式的「一条都不要」（§2.48 的三分法），
    不是坏了。

    >>> rows = Reachability(["2409:", "。chinamobile.com"], [".qingting.fm"]).rule_states(
    ...     ["http://ls.qingting.fm/a.m3u8"], [], [])
    >>> [(x["rule"], x["state"]) for x in rows]
    [('2409:', 'none'), ('。chinamobile.com', 'none'), ('.qingting.fm', 'out')]
    >>> dead_tiers(rows)                     # 内网档两条全 0，电台档在上游抓到了
    ['iptv_intranet']
    >>> dead_tiers(Reachability([".a.com"], []).rule_states(["http://x.a.com/y"], [], []))
    []
    >>> dead_tiers([])                       # 两档都空着：没东西可判，也就没人「死了」
    []
    """
    seen: dict[str, bool] = {}
    for x in rows:
        seen.setdefault(x["tier"], True)
        seen[x["tier"]] = seen[x["tier"]] and x["state"] == "none"
    return [tier for tier, all_none in seen.items() if all_none]


def dead_tier_lines(rows: Iterable[dict], n_up: int, no_public_n: int, *,
                    diff: dict | None = None) -> list[str]:
    """整档全 0 时屏幕上那几句话 —— 放在这里而不是 `cmd_build` 里，是为了能被 doctest 钉住（2.50）。

    判据只有一条：按**整档**喊，不按条（逐条的 0 有三种意义、两种无害，见 `dead_tiers`）。
    「后果」那半句按档分着写：内网档摊开是「所有台超时」，电台档摊开是「点开只剩声音」，
    拿一句通用的话会把第二种说得像不会发生（2.49 那两格的「怎么改」就是这么分开写的）。

    `diff` 是 `diff_rule_rounds()` 摆出来的上一轮（2.51）。有了它，最后那半句
    「上一轮还有几十个、这轮变 0」就从**人的记忆**变成了**量出来的两个数** ——
    那句本来就是 2.50 留在边界里的最后一格靠人记着的分辨方法。
    传不进来（首轮、`--ignore-history`、那份履历读不出）时照旧给方法不给数，不能装成量过了。

    >>> rows = Reachability(["9999:"], ["。qingting.fm"]).rule_states([], [], [])
    >>> lines = dead_tier_lines(rows, n_up=1869, no_public_n=0)
    >>> len(lines), lines[0].startswith("⚠️ 范围规则：`iptv_intranet` 这一档 1 条规则")
    (2, True)
    >>> "`audio_only`" in lines[1] and "只剩声音" in lines[1]        # 两档各有各的后果
    True
    >>> "1869 条" in lines[0] and "全部超时" in lines[0] and "只剩声音" not in lines[0]
    True
    >>> "是 0 个" in lines[0]                                  # 那把跟着哑掉的尺，本轮是几个
    True
    >>> dead_tier_lines(Reachability([".a.com"], []).rule_states(     # 内网档抓到了：一句都不该有
    ...     ["http://x.a.com/y"], [], []), 1, 0)
    []
    >>> mixed = Reachability([".a.com", "9999:"], []).rule_states(   # 同档里一条抓到、一条 0：也不该有
    ...     ["http://x.a.com/y"], [], [])
    >>> [(x["rule"], x["state"]) for x in mixed], dead_tier_lines(mixed, 1, 0)
    ([('.a.com', 'out'), ('9999:', 'none')], [])
    >>> "防身" in lines[0]                        # 「今天就是没这类地址」那一种可能也摆在同一句里
    True

    有了上一轮，那一句改成拿数说话（括号里就是 2.51 在沙盒里量到的那一组）：

    >>> d = {"prev_at": "2026-09-24T05:49:00+08:00", "prev_mode": "replay",
    ...      "tier_own_prev": {"iptv_intranet": 332}, "tier_n_prev": {"iptv_intranet": 6},
    ...      "pool_same": True, "cfg_same": True,
    ...      "fingerprint": "7eae708d153a", "no_public_prev": 39, "no_public_cur": 0}
    >>> w = dead_tier_lines(rows, 1869, 0, diff=d)[0]
    >>> "抓到 332 条" in w and "05:49" in w
    True
    >>> "这一档 6 条规则在上游抓到 332 条，本轮这 1 条命中的全是 0" in w   # 上一轮 6 条 / 本轮 1 条各说各的
    True
    >>> "这一档 1 条规则在上游抓到" not in w                # 拿本轮条数配上一轮总数 = 一句假话（M8）
    True
    >>> "T05:49" not in w                                    # 时刻的写法与报告里那一节一致
    True
    >>> "从 39 个变成 0 个" in w and "几十个" not in w      # 不用再靠人记着上一轮是几个
    True
    >>> "一条不差" in w and "判定代码" in w                  # 池子、规则文件都没变 → 剩判定代码
    True
    >>> w.count("那一节。")                                  # 那一半句只说一遍（原来串了两遍）
    1
    >>> "一条不差" not in dead_tier_lines(rows, 1869, 0, diff={**d, "pool_same": False})[0]
    True
    >>> "先确认抓取" in dead_tier_lines(rows, 1869, 0, diff={**d, "pool_same": False})[0]
    True
    >>> "config/reachability.yaml` 改过" in dead_tier_lines(  # 池子没变、规则文件变了：不赖代码
    ...     rows, 1869, 0, diff={**d, "cfg_same": False})[0]
    True
    >>> dead_tier_lines(rows, 1869, 0)[0].count("那一节。")    # 没上一轮时同样只说一遍
    1
    >>> "05:49" not in dead_tier_lines(rows, 1869, 0, diff={**d, "tier_own_prev": {}})[0]
    True
    """
    rows = list(rows)
    out = []
    tail = ("   逐条的数、以及跟上一轮比出来的变化，写在 report.md"
            "「范围规则各自抓到几条」那一节。")
    for tier in dead_tiers(rows):
        n = sum(1 for x in rows if x["tier"] == tier)
        was = (diff or {}).get("tier_own_prev", {}).get(tier) if diff else None
        if was:
            npr = (diff or {}).get("no_public_prev")
            npn = (diff or {}).get("no_public_cur", no_public_n)
            npv = (diff or {}).get("tier_n_prev", {}).get(tier)
            at = str((diff or {}).get("prev_at") or "")[:16].replace("T", " ")
            how = (f"   不用靠记忆分辨：上一轮（{at}）这一档 {npv if npv is not None else n} "
                   f"条规则在上游抓到 {was} 条，本轮这 {n} 条命中的全是 0；"
                   f"「一条公网线路都没有的频道」也从 {npr} 个变成 {npn} 个。\n"
                   + _pool_evidence(diff) + "\n" + tail)
        else:
            how = (f"   也可能是今天这批线路里就是没有它要判的地址（`2408:` 那一类是留着防身的）。\n"
                   f"   分辨方法：本轮「一条公网线路都没有的频道」是 {no_public_n} 个 —— "
                   f"上一轮还有几十个、这轮变 0，就是前者。\n" + tail)
        out.append(
            f"⚠️ 范围规则：`{tier}` 这一档 {n} 条规则在本轮 {n_up} 条上游线路里命中的全是 0"
            f" —— 这一档等于没配上\n"
            f"   后果：{_DEAD_WHY.get(tier, '这一档的判档从此不再影响排序')}\n"
            f"{how}")
    return out


def _indented(text: str, pad: str = "   ") -> str:
    """把一段多行的话整体缩进 —— 屏幕上那几个子条目是靠缩进分组的。

    为什么不用 `.strip()`：它只去掉整段**首尾**的空白，所以第一行的缩进没了、第二行还带着，
    屏幕上就是一段歪的（09-24 06:44 第一次跑 D 那一轮时看见的形状）。

    >>> _indented("   甲\\n   乙")
    '   甲\\n   乙'
    >>> _indented("   甲\\n   乙", "     ")
    '     甲\\n     乙'
    >>> _indented("")
    ''
    """
    return "\n".join(pad + ln.strip() for ln in text.strip().splitlines() if ln.strip())


def _pool_evidence(diff: dict | None) -> str:
    """「是规则变了还是上游少给了」那一句 —— 三样指纹凑齐才能把话说死（2.51）。

    写成一句是因为它有三个方向，漏一个就会把人带到错的那上去：
    池子没变 + 规则文件没变 + 数变了 ⇒ 变的是**判定代码**（这一格 2.50 那把尺自己就该撞上）；
    池子没变 + 规则文件变了 ⇒ 是这次改配置改坏的，去 diff `config/reachability.yaml`；
    池子变了 ⇒ 先别谈规则对不对，上游少抓了一个源能把五条规则一起打成 0。

    >>> _pool_evidence({"pool_same": True, "cfg_same": True, "fingerprint": "7eae708d153a"})
    '   这批线路与上一轮**一条不差**（指纹 7eae708d153a），`config/reachability.yaml` **也没变** ——\\n   那就是判定代码变了，去查 src/check/scope.py 最近的改动。'
    >>> _pool_evidence({"pool_same": True, "cfg_same": False, "fingerprint": "7eae708d153a"}).count("改过")
    1
    >>> "先确认抓取" in _pool_evidence({"pool_same": False, "cfg_same": True,
    ...                                 "fp_prev": "7eae708d153a", "fingerprint": "aaaa5d3a"})
    True
    >>> _pool_evidence(None)
    ''
    """
    if not diff:
        return ""
    fp = str(diff.get("fingerprint") or "")
    if not diff.get("pool_same"):
        return (f"   上游池子本身也变了（指纹 {diff.get('fp_prev')} → {fp}）："
                f"先确认抓取有没有出问题，再谈这一档的规则对不对。")
    if diff.get("cfg_same"):
        return (f"   这批线路与上一轮**一条不差**（指纹 {fp}），"
                f"`config/reachability.yaml` **也没变** ——\n"
                f"   那就是判定代码变了，去查 src/check/scope.py 最近的改动。")
    return (f"   这批线路与上一轮**一条不差**（指纹 {fp}），所以不是上游少给了 —— "
            f"是 `config/reachability.yaml` 改过，去 diff 那一格。")


# ---------------------------------------------------------------------------
# 2.51：把上面那一节每轮的数落成一份履历，「上一轮还抓到、这轮归 0」由工具自己发现。
#
# 为什么非要落一份：2.50 收尾时「边界」第 1、5 两条说的是同一件事 ——
# 「命中 0 条」这一格里「今天就是没这类地址」和「这条规则写错了」在上游那一层是**同一个 0**，
# 工具只能把两种可能摆在一起，分辨靠人记得「上一轮这里不是 0」。而那一节每轮都算好了七行，
# 算完就随 `report.md` 被覆盖掉了。存下来，下一轮就能自己比。
#
# 为什么**不**塞进 `probe-history.jsonl` 同一行（这是量出来的，不是顺手选的）：
# 那一行只在 `--verify` 时写，而这一节离线轮也要写。把离线轮塞进去 = 给主机履历凭空加一轮，
# 09-24 06:04 拿真履历量过：把那三次离线重出各记一行进去，`blacklist()` 从 26 族变 27 族
# （新判死的是 `m.italkbbtv.com`）—— 同一份 09-21 21:18 的实测被数成两轮独立观测，
# 而「要两轮才判死刑」那道防线（`blacklist` 的 `min_runs`）就是拿来防这个的。


def pool_fingerprint(urls: Iterable[str]) -> str:
    """这批线路本身的指纹：去重、排序、sha256 前 12 位。

    取 12 位就够：这一格只回答「两次跑看到的是不是同一批地址」，不是防篡改。
    真值（2026-09-24 06:04，`data/cache/` 那三份 09-20 21:04 的缓存 + 手工源）：
    整池 1869 条 / 去重 1804 条 = `7eae708d153a`；
    只去掉手工源那 1 条（去重 1803 条）就变成 `7d0ad38309be` —— 一条地址的进出足以换掉它。

    >>> pool_fingerprint(["http://a/x", "http://b/y"]) == pool_fingerprint(["http://b/y", "http://a/x"])
    True
    >>> pool_fingerprint(["http://a/x"]) == pool_fingerprint(["http://a/x", "http://a/x"])
    True
    >>> len(pool_fingerprint([]))
    12
    >>> pool_fingerprint(["http://a/x"]) != pool_fingerprint(["http://a/y"])
    True
    """
    return hashlib.sha256("\n".join(sorted({str(u) for u in urls}))
                          .encode("utf-8")).hexdigest()[:12]


def config_fingerprint(path: str | Path) -> str:
    """一份配置文件的内容指纹（同样取 12 位）。读不到给空串，不抛 —— 这不是能停下的事。

    >>> config_fingerprint("/does/not/exist.yaml")
    ''
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "r.yaml"
    ...     _ = p.write_text("iptv_intranet: [.a.com]\\n", encoding="utf-8")
    ...     before = config_fingerprint(p)
    ...     _ = p.write_text("iptv_intranet: [.a.com, .b.com]\\n", encoding="utf-8")
    ...     before != config_fingerprint(p), len(before)
    (True, 12)
    """
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    except (OSError, ValueError):
        return ""


def verdict_source(row: dict) -> str:
    """这一轮的「线路判决」是从哪来的 —— 决定进表 / 第一线那两层能不能跨轮比。

    三层里只有「上游候选」不欠任何判决：它是拿规则去问抓回来的那批地址。
    另外两层是**排序的产物**，而排序看判决：`--verify` 当场剔掉的线路、`--replay`
    沿用那份记录里的判决剔掉的线路、纯离线轮一条都不剔（2.50 量过：226 条 vs 351 条）。
    所以拿「上一轮的进表 41 条」比「本轮的进表 0 条」之前，得先确认这两轮是**同一种跑法**，
    否则喊出来的是一把手艺不精的尺（计划书 2.10 那句「换一个测量点这些数字就不是同一个意思」
    在规则这一层同样成立）。

    >>> verdict_source({"mode": "offline"})                    # 本轮不判：所有线路都进表
    'offline'
    >>> verdict_source({"mode": "replay", "replay_at": "2026-09-21 21:18"})
    'replay@2026-09-21 21:18'
    >>> verdict_source({"mode": "verify", "egress": "119.39.40.124 CN"})
    'verify@119.39.40.124 CN'
    >>> verdict_source({"mode": "verify", "egress": ""})       # 出口查不到 → 不装成可比
    'unknown'
    >>> verdict_source({})
    'unknown'
    """
    mode = str(row.get("mode") or "")
    if mode == "offline":
        return "offline"
    if mode == "replay":
        at = str(row.get("replay_at") or "")
        return f"replay@{at}" if at else "unknown"
    if mode == "verify":
        eg = str(row.get("egress") or "")
        return f"verify@{eg}" if eg else "unknown"
    return "unknown"


def _pair_rules(prev: list[dict], cur: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """同一档里把两轮的规则配成对：先按字面，配不上的按**位置**。

    为什么要有「按位置」这一半：2.50 那一族的典型坏法就是把一条规则的**字面**改坏
    （`.chinamobile.com` → `。chinamobile.com`）。只按字面配，屏幕上会得到「删了一条、
    多了一条」两句正确的废话；按位置配，得到的是「第 2 格被改了字面，18 条 → 0 条」，
    那才是能照着去 diff 的那一句。

    只在两边各剩一条时才配（`len == 1`）：剩两条以上就是「删了两条、加了两条」，
    这时候硬按顺序配对是猜，而猜错的方向是「把一次正常的换血说成一次改错」。

    >>> p = lambda name, **kw: {"rule": name, **kw}
    >>> pairs, added, removed = _pair_rules([p("a"), p("b")], [p("a"), p("B")])
    >>> [(x[0]["rule"], x[1]["rule"]) for x in pairs]
    [('a', 'a'), ('b', 'B')]
    >>> pairs, added, removed = _pair_rules([p("a"), p("b"), p("c")], [p("a")])
    >>> [(x[0]["rule"], x[1]["rule"]) for x in pairs], [x["rule"] for x in added], [x["rule"] for x in removed]
    ([('a', 'a')], [], ['b', 'c'])
    >>> pairs, added, removed = _pair_rules([p("a")], [p("a"), p("a")])   # 同一条写了两遍：第二格算新增
    >>> [(x[0]["rule"], x[1]["rule"]) for x in pairs], len(added)
    ([('a', 'a')], 1)
    """
    cur_by_name: dict[str, int] = {}
    for i, x in enumerate(cur):
        cur_by_name.setdefault(str(x.get("rule")), i)
    pairs: list[tuple[dict, dict]] = []
    used: set[int] = set()
    left_prev: list[dict] = []
    for x in prev:
        i = cur_by_name.get(str(x.get("rule")))
        if i is not None and i not in used:
            used.add(i)
            pairs.append((x, cur[i]))
        else:
            left_prev.append(x)
    left_cur = [x for i, x in enumerate(cur) if i not in used]
    if len(left_prev) == 1 and len(left_cur) == 1:
        pairs.append((left_prev[0], left_cur[0]))
        return pairs, [], []
    return pairs, left_cur, left_prev


def _transition(prev_row: dict, cur_row: dict, layer: str) -> dict | None:
    """一条规则在一层上的变化：只报「从有到无 / 从无到有 / 数变了」这三种。

    >>> a = {"any_up": 210, "own_up": 18, "own_table": 0, "own_first": 0}
    >>> b = {"any_up": 210, "own_up": 0, "own_table": 0, "own_first": 0}
    >>> _transition(a, b, "up")["kind"]
    '归0'
    >>> _transition(b, a, "up")["kind"]                       # 反方向也要报：那条被修好了
    '新抓到'
    >>> _transition(a, b, "table") is None                    # 两层都是 0：没变化就不占一行
    True
    >>> _transition({"any_up": 1, "own_up": 5, "own_table": 5, "own_first": 0},
    ...             {"any_up": 1, "own_up": 2, "own_table": 5, "own_first": 0}, "up")["kind"]
    '数变了'
    """
    key = {"up": "own_up", "table": "own_table", "first": "own_first"}[layer]
    a, b = int(prev_row.get(key) or 0), int(cur_row.get(key) or 0)
    if a == b:
        return None
    kind = "归0" if (a and not b) else "新抓到" if (b and not a) else "数变了"
    return {"layer": layer, "kind": kind, "prev": a, "cur": b}


LAYERS = {"up": "上游候选", "table": "进表", "first": "第一线"}


def eaten_clause(eaten: dict | None, limit: int = 3) -> str:
    """把「字面命中那些没归它的地址」说成一句带名字的话（2.52）。

    为什么单独一个函数：同一件事有三处要说 —— `report.md` 那张表「上游候选」那一格的括号、
    屏幕上与报告里那句「从有到无」、以及 2.51 那份履历读回来的行。写三遍就会有一遍不点名，
    而「不点名」正是 2.50 边界第 2 条欠着的那格。

    「排在它前面那条」这种说法在这儿一律不写：`_classify` 先扫 `audio_only` 再扫
    `iptv_intranet`，档内的先后才起作用 —— 一条内网规则可以被配置里写在它**后面**的电台规则
    判走（`rule_states` 的 `z` 那一格就是）。点名之后这一格由读者自己看得见，不必信那句概括。

    >>> eaten_clause({"tvgslb.hn.chinamobile.com": 192})
    '192 条判给了 `tvgslb.hn.chinamobile.com`'
    >>> eaten_clause({"a.com": 3, "b.com": 2})           # 多家：按条数从多到少排，顺序由 `coverage` 定
    '3 条判给了 `a.com`、2 条判给了 `b.com`'
    >>> eaten_clause({"a.com": 3, "b.com": 2, "c.com": 1, "d.com": 1})   # 四家以上收口，别撑爆那一格
    '3 条判给了 `a.com`、2 条判给了 `b.com`、1 条判给了 `c.com`，共 7 条摊在 4 家上'
    >>> eaten_clause({}), eaten_clause(None)              # 没被抢 / 旧履历缺这个键：都是空串，不编名字
    ('', '')
    >>> eaten_clause({"x": 0, "y": 2})                    # 0 条的那家不进句子
    '2 条判给了 `y`'
    >>> eaten_clause({"x": "3", "y": None, "z": [1], "w": True})   # 坏值一律当没有，不崩也不猜
    ''
    """
    items: list[tuple[str, int]] = []
    for k, v in (eaten or {}).items():
        # 这一格的值可能是从履历 JSON 读回来的：只认正整数，"3" / null / 列表 / 布尔都不猜
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            continue
        items.append((str(k), v))
    if not items:
        return ""
    s = "、".join(f"{n} 条判给了 `{k}`" for k, n in items[:limit])
    if len(items) > limit:
        s += f"，共 {sum(n for _, n in items)} 条摊在 {len(items)} 家上"
    return s


def diff_rule_rounds(prev: dict | None, cur: dict) -> dict | None:
    """把本轮那一节和上一轮那一节摆在一起，问四件事（2.51）。

    1. 有没有哪条规则**上一轮在上游还抓到东西、本轮归 0** —— 这是唯一值得上屏幕的那种；
    2. 这个 0 该算在谁头上：上游池子换了（`fingerprint`）、规则文件改了（`cfg_fingerprint`）、
       还是判定代码变了（两个指纹都说没变，数却变了）；
    3. 进表 / 第一线那两层**能不能比**（判决来源不同就不比，见 `verdict_source`）；
    4. 「一条公网线路都没有的频道」那个数塌了没有 —— 它是 §2.49 那句会跟着规则一起哑掉的报警。

    没有上一轮（首轮、`--ignore-history`、那份履历读不出）时返回 None，
    调用方要明说「比不了」，不能把「没量」印成「没变」。

    >>> prev = {"at": "2026-09-24T05:49:00+08:00", "mode": "replay",
    ...         "replay_at": "2026-09-21 21:18", "egress": "CN", "warnings": [],
    ...         "fingerprint": "7eae708d153a", "cfg_fingerprint": "aaaa11112222",
    ...         "n_up": 1869, "n_up_uniq": 1804, "no_public_n": 39,
    ...         "rows": [{"tier": "iptv_intranet", "rule": ".chinamobile.com",
    ...                   "any_up": 210, "own_up": 18, "own_table": 0, "own_first": 0,
    ...                   "state": "out"},
    ...                  {"tier": "iptv_intranet", "rule": "tvgslb.hn.chinamobile.com",
    ...                   "any_up": 192, "own_up": 192, "own_table": 41, "own_first": 22,
    ...                   "state": "first"}]}
    >>> row = lambda n, own, table, first, any_=None: {
    ...     "tier": "iptv_intranet", "rule": n, "any_up": any_ if any_ is not None else own,
    ...     "own_up": own, "own_table": table, "own_first": first,
    ...     "state": ("first" if first else "table" if table else
    ...               "out" if own else "shadow" if (any_ or 0) else "none")}
    >>> cur = {**prev, "at": "2026-09-24T06:20:00+08:00",
    ...        "rows": [row(".chinamobile.com", 0, 0, 0, 210),
    ...                 row("tvgslb.hn.chinamobile.com", 192, 41, 22, 192)]}
    >>> d = diff_rule_rounds(prev, cur)
    >>> [(x["rule"], x["layer"], x["kind"], x["prev"], x["cur"]) for x in d["items"]]
    [('.chinamobile.com', 'up', '归0', 18, 0)]
    >>> d["pool_same"], d["cfg_same"], d["table_comparable"]
    (True, True, True)
    >>> d["tier_own_prev"]                              # 档级那份数：整档全 0 那一句要用
    {'iptv_intranet': 210}
    >>> d["dead_now"]                                   # 本轮还没整档全 0
    []
    >>> d["no_public_prev"], d["no_public_cur"]
    (39, 39)
    >>> [x["cur_eaten_by"] for x in d["items"]]      # 上面那份「上一轮」是 2.51 形状，不带名字
    [{}]
    >>> d5 = diff_rule_rounds(prev, {**cur, "rows": [
    ...     {**cur["rows"][0], "eaten_by": {"tvgslb.hn.chinamobile.com": 210}},
    ...     *cur["rows"][1:]]})
    >>> _item_text(d5["items"][0])                   # 有了名字，屏幕上那句话就点得出是谁抢的
    '`iptv_intranet` / `.chinamobile.com`：上游候选 18 条 → 0 条（不是它坏了：这轮它字面还命中 210 条，其中 210 条判给了 `tvgslb.hn.chinamobile.com`）'
    >>> cur2 = {**prev, "rows": [row("。chinamobile.com", 0, 0, 0, 0),
    ...                          row("tvgslb.hn.chinamobile.com", 192, 41, 22, 192)]}
    >>> d2 = diff_rule_rounds(prev, cur2)
    >>> [(x["rule"], x["prev_rule"], x["kind"]) for x in d2["items"]]   # 新字面在前，旧的记在 prev_rule
    [('。chinamobile.com', '.chinamobile.com', '归0')]
    >>> d2["dead_now"]                                  # 内网档还有一条抓到东西：不算整档死
    []
    >>> cur3 = {**prev, "rows": [row("。chinamobile.com", 0, 0, 0, 0)],
    ...        "no_public_n": 0}
    >>> d3 = diff_rule_rounds(prev, cur3)
    >>> d3["dead_now"], d3["no_public_prev"], d3["no_public_cur"]
    (['iptv_intranet'], 39, 0)
    >>> [(x["rule"], x["kind"]) for x in d3["items"]]   # 一档同时少两条、多一条：不猜哪条对哪条
    [('。chinamobile.com', '多了一条'), ('.chinamobile.com', '少了一条'), ('tvgslb.hn.chinamobile.com', '少了一条')]
    >>> cur4 = {**cur, "mode": "offline", "fingerprint": "bbbb22223333"}
    >>> d4 = diff_rule_rounds(prev, cur4)
    >>> d4["table_comparable"], d4["pool_same"], d4["cfg_same"]
    (False, False, True)
    >>> [(x["rule"], x["layer"]) for x in d4["items"]]  # 不可比的那两层一条都不记
    [('.chinamobile.com', 'up')]
    >>> diff_rule_rounds(None, cur) is None
    True
    """
    if not prev or not isinstance(prev, dict) or not prev.get("rows"):
        return None
    prev_rows = list(prev.get("rows") or [])
    cur_rows = list(cur.get("rows") or [])
    vs_prev, vs_cur = verdict_source(prev), verdict_source(cur)
    # 排序窗口也是那两层的输入：`--max-lines 2` 跑一次会把进表那一列整个压下去，
    # 参数不记下来就会被读成「这条规则不管用了」（上游那一层不吃这个参数，所以照旧可比）。
    params_prev = list(prev.get("params") or [])
    params_cur = list(cur.get("params") or [])
    # 只有**两轮都记了**参数才谈得上「窗口换了」：上一轮那份里没有这个键
    # （手写 fixture、或旧版本落的一行）时不该被判成「参数变了」。
    params_same = (params_prev == params_cur
                   if params_prev and params_cur else True)
    comparable = vs_prev == vs_cur and vs_prev != "unknown" and params_same
    items: list[dict] = []
    tiers: list[str] = []
    for r in prev_rows + cur_rows:
        t = str(r.get("tier") or "")
        if t and t not in tiers:
            tiers.append(t)
    for tier in tiers:
        pp = [r for r in prev_rows if str(r.get("tier")) == tier]
        cc = [r for r in cur_rows if str(r.get("tier")) == tier]
        pairs, added, removed = _pair_rules(pp, cc)
        for a, b in pairs:
            edited = str(a.get("rule")) != str(b.get("rule"))
            deltas = [d for d in (_transition(a, b, layer)
                                  for layer in ("up", "table", "first"))
                      if d and (d["layer"] == "up" or comparable)]
            if not deltas:
                if edited:                    # 只改了字面、三层数一字没动
                    items.append({"tier": tier, "rule": b.get("rule"), "prev_rule": a.get("rule"),
                                  "layer": "up", "kind": "改了字面", "edited": True,
                                  "prev": int(a.get("own_up") or 0), "cur": int(b.get("own_up") or 0)})
                continue
            for d in deltas:
                items.append({"tier": tier, "rule": b.get("rule"), "prev_rule": a.get("rule"),
                              "prev_any": int(a.get("any_up") or 0),
                              "cur_any": int(b.get("any_up") or 0), "edited": edited,
                              # 本轮这一格归 0 的**那一种**原因也要带上（2.51 补）：
                              # 「字面命中、一条都没判给它」和「它自己不争气」在数上长得一样，
                              # 但屏幕上那句话的落点完全不同 —— 前者是别人抢走了，后者是内容错了。
                              "cur_state": str(b.get("state") or ""),
                              # 抢走它的是哪几条，2.52：没有这一格，那句话只能停在「被盖住了」，
                              # 而「谁盖的」正是决定「要不要动名单顺序」的那个信息。
                              "cur_eaten_by": dict(b.get("eaten_by") or {}), **d})
        for x in added:
            items.append({"tier": tier, "rule": x.get("rule"), "prev_rule": "", "layer": "list",
                          "kind": "多了一条", "edited": False,
                          "prev": None, "cur": int(x.get("own_up") or 0)})
        for x in removed:
            items.append({"tier": tier, "rule": x.get("rule"), "prev_rule": "", "layer": "list",
                          "kind": "少了一条", "edited": False,
                          "prev": int(x.get("own_up") or 0), "cur": None})
    # 整档全 0 是**新**摊开的才算：上一轮就全 0 的那一档不是这一轮的事（它一直摊着）。
    prev_dead = set(dead_tiers(prev_rows))
    dead_now = [t for t in tiers if t in set(dead_tiers(cur_rows)) and t not in prev_dead]
    return {
        "items": items,
        "prev_at": str(prev.get("at") or ""), "prev_mode": str(prev.get("mode") or ""),
        "prev_egress": str(prev.get("egress") or ""),
        "prev_replay_at": str(prev.get("replay_at") or ""),
        "prev_warnings": len(prev.get("warnings") or []),
        "cur_at": str(cur.get("at") or ""), "cur_mode": str(cur.get("mode") or ""),
        "cur_egress": str(cur.get("egress") or ""),
        "table_comparable": comparable, "params_same": params_same,
        "params_prev": list(params_prev), "params_cur": list(params_cur),
        "verdict_prev": vs_prev, "verdict_cur": vs_cur,
        "pool_same": bool(prev.get("fingerprint")) and prev.get("fingerprint") == cur.get("fingerprint"),
        "fingerprint": str(cur.get("fingerprint") or ""),
        "fp_prev": str(prev.get("fingerprint") or ""),
        "n_up_prev": int(prev.get("n_up") or 0), "n_up_cur": int(cur.get("n_up") or 0),
        "uniq_prev": int(prev.get("n_up_uniq") or 0), "uniq_cur": int(cur.get("n_up_uniq") or 0),
        "cfg_same": bool(prev.get("cfg_fingerprint"))
                    and prev.get("cfg_fingerprint") == cur.get("cfg_fingerprint"),
        "chan_same": bool(prev.get("chan_fingerprint"))
                     and prev.get("chan_fingerprint") == cur.get("chan_fingerprint"),
        "tier_own_prev": {t: sum(int(x.get("own_up") or 0) for x in prev_rows
                                 if str(x.get("tier")) == t) for t in tiers},
        # 上一轮那一档**有几条规则**：整档全 0 那一句要分开说「上一轮 6 条抓到 337」和
        # 「本轮这 1 条全是 0」。只印本轮那个数，M8（6 条摊成 1 条）会读成
        # 「上一轮那 1 条抓到 337 条」—— 一句话里两个数不同口径（09-24 07:33 量到的）。
        "tier_n_prev": {t: sum(1 for x in prev_rows if str(x.get("tier")) == t) for t in tiers},
        "dead_now": dead_now,
        "no_public_prev": int(prev.get("no_public_n") or 0),
        "no_public_cur": int(cur.get("no_public_n") or 0),
    }


def _item_text(x: dict) -> str:
    """一条变化写成一行 —— 报告里那一串、屏幕上那几句都用它，两处不能各说各话。

    >>> _item_text({"tier": "iptv_intranet", "rule": ".chinamobile.com", "layer": "up",
    ...             "kind": "归0", "prev": 18, "cur": 0, "prev_any": 210, "cur_any": 210,
    ...             "edited": False})
    '`iptv_intranet` / `.chinamobile.com`：上游候选 18 条 → 0 条'
    >>> _item_text({"tier": "iptv_intranet", "rule": "。chinamobile.com", "prev_rule": ".chinamobile.com",
    ...             "layer": "table", "kind": "归0", "prev": 41, "cur": 0, "edited": True})
    '`iptv_intranet` / `.chinamobile.com` → `。chinamobile.com`（这一格被改了字面）：进表 41 条 → 0 条'
    >>> _item_text({"tier": "audio_only", "rule": ".qingting.fm", "prev_rule": "", "layer": "list",
    ...             "kind": "少了一条", "prev": 22, "cur": None, "edited": False})
    '`audio_only` / `.qingting.fm`：这一轮名单里没有了（上一轮上游候选 22 条）'
    >>> _item_text({"tier": "iptv_intranet", "rule": "x", "prev_rule": "y", "layer": "up",
    ...             "kind": "改了字面", "prev": 5, "cur": 5, "edited": True})
    '`iptv_intranet` / `y` → `x`（这一格被改了字面）：上游候选 5 条 → 5 条，数没变'
    >>> _item_text({"tier": "iptv_intranet", "rule": "tvgslb.hn.chinamobile.com", "prev_rule": "",
    ...             "layer": "up", "kind": "归0", "prev": 192, "cur": 0, "prev_any": 192,
    ...             "cur_any": 192, "edited": False, "cur_state": "shadow",
    ...             "cur_eaten_by": {".chinamobile.com": 192}})
    '`iptv_intranet` / `tvgslb.hn.chinamobile.com`：上游候选 192 条 → 0 条（不是它坏了：这轮它字面还命中 192 条，其中 192 条判给了 `.chinamobile.com`）'
    >>> _item_text({"tier": "iptv_intranet", "rule": "tvgslb.hn.chinamobile.com", "prev_rule": "",
    ...             "layer": "up", "kind": "归0", "prev": 192, "cur": 0, "prev_any": 192,
    ...             "cur_any": 192, "edited": False, "cur_state": "shadow"})
    '`iptv_intranet` / `tvgslb.hn.chinamobile.com`：上游候选 192 条 → 0 条（不是它坏了：这轮它字面还命中 192 条，可那些地址一条都没判给它，也没记下是哪条规则判走的）'
    >>> _item_text({"tier": "iptv_intranet", "rule": ".a", "prev_rule": "", "layer": "up",
    ...             "kind": "归0", "prev": 18, "cur": 0, "prev_any": 210, "cur_any": 0,
    ...             "edited": False, "cur_state": "none"})
    '`iptv_intranet` / `.a`：上游候选 18 条 → 0 条（字面 210 → 0）'

    「上游字面命中数」不进「进表」「第一线」那两行 —— 每一行只说自己那一层的数（M10 量到的）：

    >>> for layer in ("up", "table", "first"):
    ...     print(_item_text({"tier": "iptv_intranet", "rule": "x", "prev_rule": "", "layer": layer,
    ...                       "kind": "归0", "prev": 192, "cur": 0, "prev_any": 192, "cur_any": 192,
    ...                       "edited": False, "cur_state": "shadow",
    ...                       "cur_eaten_by": {".hn.chinamobile.com": 192}}))
    `iptv_intranet` / `x`：上游候选 192 条 → 0 条（不是它坏了：这轮它字面还命中 192 条，其中 192 条判给了 `.hn.chinamobile.com`）
    `iptv_intranet` / `x`：进表 192 条 → 0 条
    `iptv_intranet` / `x`：第一线 192 条 → 0 条
    >>> _item_text({"tier": "iptv_intranet", "rule": "x", "prev_rule": "", "layer": "table",
    ...             "kind": "归0", "prev": 41, "cur": 0, "prev_any": 192, "cur_any": 0,
    ...             "edited": False, "cur_state": "none"}).count("字面")     # 那句「字面」也不跨层
    0
    """
    who = f"`{x['tier']}` / `{x['rule']}`"
    if x.get("edited") and x.get("prev_rule"):
        who = f"`{x['tier']}` / `{x['prev_rule']}` → `{x['rule']}`（这一格被改了字面）"
    if x["layer"] == "list":
        return (f"{who}：这一轮名单里没有了（上一轮上游候选 {x['prev']} 条）"
                if x["kind"] == "少了一条"
                else f"{who}：这一轮名单里新加的（本轮上游候选 {x['cur']} 条）")
    where = LAYERS.get(x["layer"], x["layer"])
    if x["kind"] == "改了字面":
        return f"{who}：{where} {x['prev']} 条 → {x['cur']} 条，数没变"
    # 「字面」与「不是它坏了：这轮字面还命中 N 条」引的都是**上游**那一层的数，
    # 所以只跟上层的行走：挂在「进表 41 → 0」「第一线 22 → 0」后面就是拿上游的数解释表里的数
    # —— 2.50 追记骂过的那一格（把表那一层的 118 条写进上游那句）的同一个形状，方向相反。
    # M10 那一轮三行重复尾巴把它摆出来的；同一条规则的三层各占一行，上游那一行会说，
    # 不必每行都背一遍别的层的数。（`list` 那两行除外：它明说了「上一轮**上游候选** N 条」，
    # 那是名单那一层唯一能给的数，且它自己标了层。）
    same_layer = x["layer"] == "up"
    tail = (f"（字面 {x['prev_any']} → {x['cur_any']}）"
            if same_layer and "prev_any" in x and x["prev_any"] != x["cur_any"] else "")
    if x["kind"] == "归0" and x.get("cur_state") == "shadow" and same_layer:
        # 名字有就说名字（2.52），没有就明说「没记下是谁」—— 不能退回那句「排在它前面那条」：
        # `_classify` 先扫电台档，配置里写在后面的电台规则一样能判走一条内网规则。
        n = eaten_clause(x.get("cur_eaten_by"))
        tail += (f"（不是它坏了：这轮它字面还命中 {x.get('cur_any', 0)} 条，"
                 + (f"其中 {n}" if n else "可那些地址一条都没判给它，也没记下是哪条规则判走的") + "）")
    return f"{who}：{where} {x['prev']} 条 → {x['cur']} 条{tail}"


def rule_diff_lines(diff: dict | None, hist_name: str = "rule-history.jsonl") -> list[str]:
    """`report.md` 里「跟上一轮比」那一段（2.51）。

    三条纪律：**比不了要说**（没有上一轮时这里返回空，由调用方印「没有可比对的上一次：为什么」，
    不能把「没量」印成「没变」，同 2.32 那一格）；
    **不可比要说是哪两层不可比、为什么**（判决来源换了或排序窗口换了，那两列本来就跟着走）；
    **一条都没变也印一句**（这一节每轮都在量，量到「没变化」也是量到了）。

    >>> prev = {"at": "2026-09-24T05:49:00+08:00", "mode": "replay",
    ...         "replay_at": "2026-09-21 21:18", "egress": "CN", "warnings": [],
    ...         "fingerprint": "7eae708d153a", "cfg_fingerprint": "aaaa11112222",
    ...         "n_up": 1869, "n_up_uniq": 1804, "no_public_n": 39, "rows": [
    ...             {"tier": "iptv_intranet", "rule": ".chinamobile.com", "any_up": 210,
    ...              "own_up": 18, "own_table": 0, "own_first": 0, "state": "out"}]}
    >>> row = {"tier": "iptv_intranet", "rule": ".chinamobile.com", "any_up": 210,
    ...        "own_up": 18, "own_table": 0, "own_first": 0, "state": "out"}
    >>> d = diff_rule_rounds(prev, {**prev, "at": "2026-09-24T06:20:00+08:00", "rows": [row]})
    >>> s = "\\n".join(rule_diff_lines(d))
    >>> "一条都没有" in s and "05:49" in s
    True
    >>> "一条不差" in s                                       # 池子指纹相同，说得出来
    True
    >>> "上一层" not in s                                      # 没有的话不硬凑一段
    True
    >>> bad = diff_rule_rounds(prev, {**prev, "rows": [{**row, "own_up": 0}]})
    >>> s2 = "\\n".join(rule_diff_lines(bad))
    >>> "上游候选 18 条 → 0 条" in s2
    True
    >>> rule_diff_lines(None) == []                            # 没有上一轮：由调用方说那句话
    True
    >>> "出口" not in s                                        # 沿用记录的那轮：本机出口不是那批判决的来源
    True
    >>> vd = diff_rule_rounds({**prev, "mode": "verify", "egress": "119.39.40.124 CN"},
    ...                       {**prev, "mode": "offline", "egress": "38.207.137.208 JP"})
    >>> "出口 `119.39.40.124 CN`" in "\\n".join(rule_diff_lines(vd))   # 实测轮：出口就是要说的
    True
    >>> "`38.207.137.208`" not in "\\n".join(rule_diff_lines(vd))      # 只说上一轮的，本轮的出口不相干
    True
    >>> "本轮是 `offline`" in "\\n".join(rule_diff_lines(vd))       # 跑法换了就走「不比」那一条
    True
    >>> "**不比**" in "\\n".join(rule_diff_lines(vd))
    True
    >>> "rule-history.jsonl`（与 `report.md` 同一层" in s        # 落哪儿：只说文件名，目录跟着 --out 走
    True
    >>> "x.jsonl" in "\\n".join(rule_diff_lines(d, "x.jsonl"))
    True
    >>> w = diff_rule_rounds({**prev, "params": [3, 2]},
    ...                      {**prev, "params": [2, 1], "at": "2026-09-24T06:20:00+08:00",
    ...                       "rows": [{**row, "own_table": 0, "own_first": 0}]})
    >>> s3 = "\\n".join(rule_diff_lines(w))
    >>> "排序窗口换了" in s3 and "3 2" in s3 and "2 1" in s3      # 那两列的变动先赖参数，不赖规则
    True
    >>> "同一份判决" not in s3
    True
    >>> "按上面那句**没比**" in s3                                # 「一条都没有」不能盖住没比的那两层
    True
    >>> w["params_prev"], w["params_cur"]                       # 两轮各自的参数要留到渲染那一步
    ([3, 2], [2, 1])
    >>> diff_rule_rounds(prev, {**prev, "rows": [row]})["params_prev"]
    []
    """
    if not diff:
        return []
    at = str(diff.get("prev_at") or "")[:16].replace("T", " ")
    src = {"verify": "`--verify` 当场实测", "replay": "`--replay` 沿用记录",
           "offline": "纯离线（不剔任何线路）"}.get(diff["prev_mode"], diff["prev_mode"])
    cur_src = {"verify": "`--verify` 当场实测", "replay": "`--replay` 沿用记录",
               "offline": "纯离线（不剔任何线路）"}.get(diff["cur_mode"], diff["cur_mode"])
    # 出口只在 `--verify` 那一轮才有意义：它标的是「这批判决从哪张网量出来的」。
    # 沿用记录的轮次本机出口照旧记进行里（万一有人拿它对照），但不印在这一句上 ——
    # 09-24 06:39 第一次跑就露了馅：`--replay` 沿用的是 09-21 那批 CN 出口的判决，
    # 标题里却写「出口 38.207.137.208 JP」，读起来像这一轮拿日本那条线测过什么东西。
    egr = (f"，出口 `{diff['prev_egress']}`"
           if diff["prev_egress"] and diff["prev_mode"] == "verify" else "")
    out = ["", f"### 跟上一轮比：{at} 那一次（{src}{egr}"
               + (f"，那一次体检报了 {diff['prev_warnings']} 句" if diff["prev_warnings"] else "")
               + "）", ""]
    pool = ("这批线路与上一轮**一条不差**" if diff["pool_same"] else
            f"这批线路**换了**：上一轮 {diff['n_up_prev']} 条（去重 {diff['uniq_prev']}）"
            f" → 本轮 {diff['n_up_cur']} 条（去重 {diff['uniq_cur']}），"
            f"指纹 {diff['fp_prev']} → {diff['fingerprint']}")
    cfg = ("`config/reachability.yaml` **没变**" if diff["cfg_same"]
           else "`config/reachability.yaml` **改过了**（内容指纹不同）")
    chan = ("" if diff["chan_same"] else
            "；`config/channels.yaml` 也改过了（名单一变，进表那两层跟着动）")
    if diff["table_comparable"]:
        cmp_note = f"可比（两轮是同一份判决：{cur_src}）"
    elif not diff["params_same"]:
        cmp_note = (f"**不比** —— 排序窗口换了：上一轮 `--max-lines`/`--max-per-host` 是 "
                    f"{' '.join(str(x) for x in diff['params_prev'])}，"
                    f"本轮是 {' '.join(str(x) for x in diff['params_cur'])}，"
                    f"那两列本来就跟着窗口走")
    else:
        cmp_note = (f"**不比** —— 上一轮的判决来自 `{diff['verdict_prev']}`，"
                    f"本轮是 `{diff['verdict_cur']}`，那两列本来就会因跑法不同而不同")
    out += [f"- {pool}；{cfg}{chan}。",
            f"- 进表 / 第一线那两层：{cmp_note}。"]
    items = diff["items"]
    if not items:
        out += ["- 变化：一条都没有。" + (
            "七行 × 那几层全部对得上上一轮" if diff["table_comparable"] else
            "可比的那一层（上游候选）七行全部对得上上一轮 —— "
            "进表 / 第一线那两层按上面那句**没比**，所以这句不等于「三层都没变」")
            + f"（「一条公网线路都没有的频道」两轮都是 {diff['no_public_cur']} 个）。"]
    else:
        out += [f"- 变化 {len(items)} 条（逐条）："]
        out += [f"  - {_item_text(x)}" for x in items]
    if diff["no_public_prev"] != diff["no_public_cur"]:
        out += [f"- 那把会跟着规则一起哑掉的尺：「一条公网线路都没有的频道」"
                f"{diff['no_public_prev']} 个 → {diff['no_public_cur']} 个"
                + (" —— 规则摊开时它自己就归 0，所以这一格不能单独当判据（2.49）。"
                   if diff["no_public_cur"] == 0 else "。")]
    if diff["dead_now"]:
        out += ["- ⚠️ 这一轮**新摊开**的档：" + "、".join(f"`{t}`" for t in diff["dead_now"])
                + "（上一轮这些档在上游还有抓到东西），屏幕上那一句就是它。"]
    out += ["", f"> 这一段每轮的数落在 `{hist_name}`（与 `report.md` 同一层，一行一轮，只追加不重写）。"
            "它是**参考不是判据**：比出什么都不改这张表上一个字节，也不剔一条线路。"]
    return out


def diff_alert_lines(diff: dict | None, limit: int = 5) -> list[str]:
    """屏幕上要喊的那几条 —— 只喊「上游候选那一层从有到无」（2.51，改错实验 M6 之后加了第二种）。

    为什么只喊这一种：2.50 已经量过，逐条的 0 有三种意义、两种无害，所以那一节的报警
    按**整档**装。但「**跨轮**从有到无」不一样 —— 上一轮它抓到过 18 条，这一轮 0 条，
    那三种无害的解释里当场就排除了「今天就是没这类地址」这一种（除非池子也换了，
    那一句会跟着一起喊）。所以这一档可以按条喊，代价是每一句都得带上归因。

    「从有到无」有两条路走到，改错实验 M6（两档名单互换）量出来的就是第二条：

      * **规则还在、抓不到了**（`归0`）—— 字面被改了、域名搬家了、被前一条盖住了。
      * **规则本身不在了**（`少了一条`，且上一轮它还抓到过）—— 有人重写了那份 YAML，
        少抄了一行。它的后果和上面那条**一模一样**（那一档范围重新占住第一线），
        而这一种在旧实现里屏幕上**一个字都不喊**：那一行不再出现在 `rows` 里，
        于是它连「归 0」都算不上，只在 report.md 那 14 行里躺着。
        这不就是本节要抓的那件事吗 —— 「上一轮还抓到、这轮归 0」，只不过归 0 的方式是被人删掉的。
        所以它现在也喊，标题里点明「其中 N 条是这一轮名单里没有了」。
        上一轮本来就 0 条的那些（真配置里的 `2408:`）删掉了**不喊**：没有的东西失去不叫失去。

    进表 / 第一线那两层的归 0 **不上屏幕**：它们还多一个来源（判决、窗口、台名名单），
    写在 report.md 里让人对着看就够 —— 与 2.50 那条「逐条的数进报告、整档的 0 上屏幕」同一分法。
    同一条分法管到这里：**整档这一轮新摊开**时那句由 `dead_tier_lines` 喊（它带档级的数），
    这里就不再把同一档的逐条各喊一遍 —— 一个坏掉的档位屏幕上只出现一次。

    >>> r = lambda n, any_, own, table=0, first=0: {
    ...     "tier": "iptv_intranet", "rule": n, "any_up": any_, "own_up": own,
    ...     "own_table": table, "own_first": first,
    ...     "state": ("first" if first else "table" if table else "out" if own
    ...               else "shadow" if any_ else "none")}
    >>> prev = {"at": "2026-09-24T05:49:00+08:00", "mode": "offline", "egress": "",
    ...         "fingerprint": "7eae708d153a", "cfg_fingerprint": "aaaa11112222",
    ...         "n_up": 1869, "n_up_uniq": 1804, "no_public_n": 39,
    ...         "rows": [r(".chinamobile.com", 210, 18), r("2409:", 67, 67),
    ...                  r("tvgslb.hn.chinamobile.com", 192, 30, 12, 5)]}
    >>> d = diff_rule_rounds(prev, {**prev, "rows": [r(".chinamobile.com", 210, 0),
    ...                                              r("2409:", 67, 67),
    ...                                              r("tvgslb.hn.chinamobile.com", 192, 30, 12, 5)]})
    >>> s = "\\n".join(diff_alert_lines(d))
    >>> s.startswith("⚠️ 跟上一次比（2026-09-24 05:49）：有一条范围规则")
    True
    >>> "18 条 → 0 条" in s and "一条不差" in s        # 归因那半句是必须的，不然等于没喊
    True
    >>> "2409:" not in s                                # 没掉下去的那条不喊
    True
    >>> "不比" not in s                                  # 表层不可比不在屏幕上说
    True
    >>> [l[:3] for l in s.splitlines()[1:] if l.strip()] == ["   "] * len(
    ...     [l for l in s.splitlines()[1:] if l.strip()])   # 标题以外全是缩进着的子条目，不歪
    True
    >>> d2 = diff_rule_rounds(prev, {**prev, "rows": [r(".chinamobile.com", 210, 0),
    ...                                               r("2409:", 0, 0),
    ...                                               r("tvgslb.hn.chinamobile.com", 192, 30, 12, 5)],
    ...                               "fingerprint": "bbbb22223333", "n_up": 100,
    ...                               "no_public_n": 0})
    >>> a2 = "\\n".join(diff_alert_lines(d2))
    >>> a2.count("→ 0 条"), "2 条范围规则" in a2         # 两条一起掉：两条都列出来，归因只说一遍
    (2, True)
    >>> "上游池子本身也变了" in a2                       # 池子换了 → 那句改成先查抓取
    True
    >>> "39 个变成 0 个" in a2                           # 那把跟着哑掉的尺塌了，也上屏幕
    True
    >>> cur3 = {**prev, "rows": [r(".chinamobile.com", 0, 0), r("2409:", 0, 0),
    ...                          r("tvgslb.hn.chinamobile.com", 0, 0)], "no_public_n": 0}
    >>> d3 = diff_rule_rounds(prev, cur3)
    >>> a3 = diff_alert_lines(d3)
    >>> [l for l in a3 if "→ 0 条" in l], d3["dead_now"]  # 整档摊开：逐条的让给档级那一句
    ([], ['iptv_intranet'])
    >>> len(a3), "39 个变成 0 个" in a3[0]                # 屏幕上仍有话，但不是重复喊
    (1, True)
    >>> "命中的全是 0" in "\\n".join(                     # 而档级那一句确实接手了这一轮
    ...     dead_tier_lines(cur3["rows"], cur3["n_up"], cur3["no_public_n"], diff=d3))
    True
    >>> d4 = diff_rule_rounds(prev, {**prev, "rows": [r("2409:", 67, 67)]})   # M6：删掉两条
    >>> a4 = "\\n".join(diff_alert_lines(d4))
    >>> "2 条全是这一轮名单里没有了" in a4, d4["items"][0]["prev"]   # 标题把「怎么没的」说在明处
    (True, 18)
    >>> a4.count("这一轮名单里没有了")                 # 标题一句 + 两条各一句
    3
    >>> mixed = diff_rule_rounds(prev, {**prev, "rows": [r(".chinamobile.com", 210, 0),
    ...                                                  r("2409:", 67, 67)]})
    >>> a5 = "\\n".join(diff_alert_lines(mixed))
    >>> a5.count("→ 0 条"), a5.count("这一轮名单里没有了")   # 一条归 0、一条被删：两回事都在
    (1, 2)
    >>> "其中 1 条是这一轮名单里没有了" in a5
    True
    >>> "2408:" not in "\\n".join(diff_alert_lines(diff_rule_rounds(   # 本来就 0 条的被删：不喊
    ...     {**prev, "rows": prev["rows"] + [r("2408:", 0, 0)]},
    ...     {**prev, "rows": list(prev["rows"])})))
    True
    >>> ten = [r(f".x{i}.com", 9, 9) for i in range(10)]
    >>> cur4 = [ten[0]] + [r(f".x{i}.com", 9, 0) for i in range(1, 10)]
    >>> many = "\\n".join(diff_alert_lines(diff_rule_rounds(
    ...     {**prev, "rows": ten}, {**prev, "rows": cur4})))
    >>> len([l for l in many.splitlines() if "→ 0 条" in l]), "另有 4 条" in many
    (5, True)
    >>> diff_alert_lines(None)
    []
    """
    if not diff:
        return []
    # 整档摊开由 `dead_tier_lines` 那一句喊（它带档级的数），这里就只喊没摊开的档里
    # 逐条掉下去的那些 —— 同一件事不在屏幕上说两遍，2.50 那条「整档的才上屏幕」的分法照旧。
    gone = [x for x in diff["items"]
            if x["tier"] not in diff["dead_now"]
            and ((x["kind"] == "归0" and x["layer"] == "up")
                 or (x["kind"] == "少了一条" and x["prev"]))]
    out: list[str] = []
    if gone:
        at = str(diff.get("prev_at") or "")[:16].replace("T", " ")
        dropped = sum(1 for x in gone if x["kind"] == "少了一条")
        how = ("" if not dropped else
               f"（{len(gone)} 条全是这一轮名单里没有了的那类）" if dropped == len(gone) else
               f"，其中 {dropped} 条是这一轮名单里没有了")
        n = "有一条" if len(gone) == 1 else f"有 {len(gone)} 条"
        head = f"⚠️ 跟上一次比（{at}）：{n}范围规则在上游候选那一层从有到无{how}"
        out.append(head + "：\n" + "\n".join(f"   - {_item_text(x)}" for x in gone[:limit])
                   + (f"\n   （另有 {len(gone) - limit} 条同样在掉，"
                      f"逐条写在 report.md「跟上一轮比」那一段）" if len(gone) > limit else ""))
        out.append(_indented(_pool_evidence(diff)))
    if diff["no_public_prev"] and not diff["no_public_cur"]:
        out.append(f"⚠️ 「一条公网线路都没有的频道」从 {diff['no_public_prev']} 个变成 0 个 —— "
                   f"§2.49 说过那句报警会跟着规则一起哑掉：这一档要是同时出现在上面，就是它。")
    return out


def load_reachability(path: str | Path) -> Reachability:
    """读规则表。文件不在 = 全表按公网排（老行为），键名写歪 = 停下来。

    「不在」和「写歪」分开放是因为它们对人的意义不同：前者是这份表还没建（新克隆），
    后者是建了、而且他以为生效了。

    >>> import tempfile, pathlib
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "r.yaml"
    ...     _ = p.write_text("iptv_intranet:\\n  - .example.com\\n", encoding="utf-8")
    ...     load_reachability(p).scope("http://a.example.com/x.m3u8")
    'iptv_intranet'
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "r.yaml"
    ...     _ = p.write_text("iptv_intranet: [.example.com]\\naudio_onlyx: [x]\\n",
    ...                      encoding="utf-8")
    ...     try:
    ...         load_reachability(p)
    ...     except ValueError as e:
    ...         print("audio_only" in str(e))
    True

    值的形状（2.49）。这一族的坏法与 `sources.yaml` 那一种不是一种：这里没有 `str()` 洗值，
    `cfg.get(...) or []` 之后直接交给 `Reachability.__init__` 去 `for r in rules`，
    所以「少写一个方括号」不是洗成一个假字符串，而是**逐字符摊开**。
    下面这几格就是普查量到的那几格（`/tmp/census249.py` 的 C02 / C04 / C05 / C09 / C10 / C15 / C20）：

    >>> def read(body):                      # 读到什么：停下来就给那句话，否则给规则本身
    ...     with tempfile.TemporaryDirectory() as d:
    ...         p = pathlib.Path(d) / "r.yaml"
    ...         _ = p.write_text(body, encoding="utf-8")
    ...         try:
    ...             return load_reachability(p)
    ...         except ValueError as e:
    ...             return str(e)
    >>> def n(body):                         # 放过的那种：直接看它读到几条内网规矩
    ...     r = read(body)
    ...     return r if isinstance(r, str) else len(r.rules)
    >>> "读成 16 条" in read("version: 1\\niptv_intranet: .chinamobile.com\\n")  # 一条规矩变 16 个字符
    True
    >>> s = read("version: 1\\niptv_intranet: .chinamobile.com\\n")   # 句首给文件名，不给整条路径
    >>> s.startswith("r.yaml 的 `iptv_intranet`")
    True
    >>> "没填" in read("version: 1\\niptv_intranet: #\\n")                       # 老读法读成「这一档没有」
    True
    >>> n("version: 1\\niptv_intranet: []\\n"), n("version: 1\\n")        # 空列表 / 整格没写：同一件事
    (0, 0)
    >>> "第 2 条读出来是一个字典" in read("version: 1\\niptv_intranet:\\n  - a.com\\n  - 2409:\\n")
    True
    >>> "第 2 条是空的" in read('version: 1\\niptv_intranet:\\n  - a.com\\n  - ""\\n')
    True
    >>> "不能当范围规则用" in read("- .chinamobile.com\\n- .qingting.fm\\n")  # 整份不是「键：名单」的结构
    True
    >>> "湖南台全部超时" in read("version: 1\\niptv_intranet: .chinamobile.com\\n")  # 内网那句后果也钉住
    True
    >>> r = read("version: 1\\naudio_only: .qingting.fm\\n")            # 两格的「怎么改」各说各的后果
    >>> "12 条" in r and "只出声音" in r and "全部超时" not in r
    True

    真在用的那一份过得过这道闸（闸不能只挡临时文件 —— 沙盒里那份被改过，这里立刻红）：
    6 条内网规矩、1 条电台，移动门户仍判内网。

    >>> live = load_reachability(Path(__file__).resolve().parents[2] / "config" / "reachability.yaml")
    >>> len(live.rules), len(live.audio_rules)
    (6, 1)
    >>> live.scope("http://tvgslb.hn.chinamobile.com:8089/x.m3u8")
    'iptv_intranet'

    名单和这段代码读的是同一批键（2.42）—— 这一档规则整档少掉，表上只是「那些该往后压的台
    没往后压」，看不出来，所以这一条盯的是闸自己别睡着。

    >>> from src.keys import drift_of
    >>> drift_of(load_reachability, known=REACH_KEYS, notes=REACH_NOTES)
    []
    """
    p = Path(path)
    if not p.exists():
        return Reachability()
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"{p} 读出来是 {type(cfg).__name__}，不是「iptv_intranet: […]」"
                         "那种结构，这一份不能当范围规则用")
    check_version(cfg, where=str(p))
    for warn in check_keys(cfg, where=str(p), known=REACH_KEYS, notes=REACH_NOTES):
        print(f"⚠️ {warn}", file=sys.stderr)
    # `where` 用文件名而不是整条路径：`stop_message` 会把句首重复的路径剥掉（它前面已经印过一遍），
    # 剥完剩下一个开头的「的」字就不像人话了。文件名不会被剥，单看也认得出是哪一份。
    return Reachability(
        str_list_value(cfg.get("iptv_intranet", _NOT_SET), where=p.name,
                       key="iptv_intranet", advice=_INTRANET_ADVICE),
        str_list_value(cfg.get("audio_only", _NOT_SET), where=p.name,
                       key="audio_only", advice=_AUDIO_ADVICE))
