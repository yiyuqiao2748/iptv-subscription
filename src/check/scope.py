"""流地址的可达范围：区分「公网能连」与「只有运营商 IPTV 专网才连得上」。

为什么要有这一步：APTV 只会自动播某个频道的第一条线路，第二条要遥控器手动切。
把覆盖最全、但电视够不到的运营商内网地址排到第一顺位，观感就是「所有台都超时」。

范围只决定同一频道内的先后，不删线路 —— 判错最多少排在前面，代价很小。
规则表在 config/reachability.yaml，改判不用动代码。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import yaml

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
    p = Path(path)
    if not p.exists():
        return Reachability()
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Reachability(cfg.get("iptv_intranet") or [], cfg.get("audio_only") or [])
