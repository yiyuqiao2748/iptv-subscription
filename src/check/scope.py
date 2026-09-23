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
        {'tier': 'iptv_intranet', 'any': 3, 'own': 1}
        >>> cov["rules"]["tvgslb.hn.chinamobile.com"]["any"], cov["rules"]["tvgslb.hn.chinamobile.com"]["own"]
        (2, 2)
        >>> cov["rules"][".qingting.fm"]["own"]                  # 电台那条抓到了
        1
        >>> cov["tiers"]["iptv_intranet"]                        # 档级：3 条规则，归它们 3 条
        {'rules': 3, 'own': 3}
        >>> cov["code_intranet"], cov["total"]        # 组播那条不欠任何规则，单独记一格
        (1, 6)
        >>> r.coverage([])["rules"]["2409:"]          # 一堆地址都没有：各条都是 0，不是崩
        {'tier': 'iptv_intranet', 'any': 0, 'own': 0}
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
        code = 0
        for url in urls:
            parts = urlsplit(url)
            if parts.scheme.lower() in _NON_HTTP:
                code += 1                 # 组播由代码定档；算进去会把「0 命中」读成假非 0
                continue
            host = (parts.hostname or url).lower()
            for rule in seen:
                if self._matches(rule, host):
                    any_n[rule] = any_n.get(rule, 0) + 1
            own = self._classify(url)[1]
            if own is not None:
                own_n[own] = own_n.get(own, 0) + 1
        per_rule = {rule: {"tier": tier, "any": any_n.get(rule, 0), "own": own_n.get(rule, 0)}
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
        * `shadow` —— 字面命中、可一条都不归它：排在它前面的那条整个盖住了它，改不改都不动本轮的表；
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
                         "own_table": own_t, "own_first": own_f, "state": state})
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


def dead_tier_lines(rows: Iterable[dict], n_up: int, no_public_n: int) -> list[str]:
    """整档全 0 时屏幕上那几句话 —— 放在这里而不是 `cmd_build` 里，是为了能被 doctest 钉住（2.50）。

    判据只有一条：按**整档**喊，不按条（逐条的 0 有三种意义、两种无害，见 `dead_tiers`）。
    「后果」那半句按档分着写：内网档摊开是「所有台超时」，电台档摊开是「点开只剩声音」，
    拿一句通用的话会把第二种说得像不会发生（2.49 那两格的「怎么改」就是这么分开写的）。

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
    """
    out = []
    for tier in dead_tiers(rows):
        n = sum(1 for x in rows if x["tier"] == tier)
        out.append(
            f"⚠️ 范围规则：`{tier}` 这一档 {n} 条规则在本轮 {n_up} 条上游线路里命中的全是 0"
            f" —— 这一档等于没配上\n"
            f"   后果：{_DEAD_WHY.get(tier, '这一档的判档从此不再影响排序')}\n"
            f"   也可能是今天这批线路里就是没有它要判的地址（`2408:` 那一类是留着防身的）。\n"
            f"   分辨方法：本轮「一条公网线路都没有的频道」是 {no_public_n} 个 —— "
            f"上一轮还有几十个、这轮变 0，就是前者。逐条的数写在 report.md"
            f"「范围规则各自抓到几条」那一节。")
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
