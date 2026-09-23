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

    def _hit(self, host: str, rules: tuple[str, ...]) -> bool:
        for rule in rules:
            r = rule.lower()
            if r.startswith("."):
                if host.endswith(r) or host == r[1:]:
                    return True
            elif r.endswith(":"):
                if host.startswith(r):
                    return True
            elif host == r:
                return True
        return False

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
        parts = urlsplit(url)
        if parts.scheme.lower() in _NON_HTTP:
            return INTRANET
        host = (parts.hostname or url).lower()
        if self._hit(host, self.audio_rules):
            return AUDIO
        if self._hit(host, self.rules):
            return INTRANET
        return PUBLIC

    def rank(self, url: str) -> int:
        return RANK[self.scope(url)]


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
