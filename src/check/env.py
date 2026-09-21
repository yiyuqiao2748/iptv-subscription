"""测量点体检：判断「本机实测」这四个字此刻有没有意义。

计划书 2.8 已经在这上面吃过一次亏：Windows 开发机的 DNS 被虚拟网卡接管，
249 条湖南线路被判成失效，实际是隧道掐断而不是源失效。2026-09-20 换到 macOS
开发机是同一个病 —— 直查阿里 DNS 223.5.5.5 也返回 198.18.1.33，出口 IP 在日本机房。

所以只要跑 --verify，先做这个体检再报数字，避免下一轮又拿假阴性做判据。

2026-09-21 反过来验证了一次：关掉代理客户端的 TUN 后 fake-IP 探针归零，
出口变成 119.39.40.124（CN / AS4837 联通骨干），和 Apple TV 所在的
192.168.31.x 是同一张网 —— 这时本机实测才等于电视实测。egress_hint() 就是
把这件事固化成证据写进 probe.json，免得再靠人记住「这次测的数字能不能信」。

同一天夜里又被咬了一口：fake-IP 只是 TUN 的一种形态。代理客户端不接管 DNS 时探针全绿、
体检一条都不报，可出口还在境外机房，那一轮照样全是假阴性 —— 而它的产物会直接覆盖掉
上一轮可信的订阅表。所以警告改成两条独立证据（fake-IP + 出口国家码），
配合 `cli.artifact_dir()` 把报警轮次的产物关进 `data/output/untrusted/`。
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request

# Clash / Surge 一类客户端的 fake-IP 池：RFC 2544 基准测试段，真实公网地址不会落在这里，
# 命中即说明 DNS 被虚拟网卡接管，本机发出的连接并不走家庭宽带。
FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")

# 探针用国内地址：fake-IP 模式下它们同样会被换成 198.18.x.x
PROBE_HOSTS = ("tvgslb.hn.chinamobile.com", "www.baidu.com", "www.qq.com")

# 出口身份查询：ipinfo 给结构化字段，拿不到就留空，不让它拖慢生成
EGRESS_URL = "https://ipinfo.io/geo"


def resolve(host: str) -> list[str]:
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})
    except OSError:
        return []


def fake_ip_answers(hosts: tuple[str, ...] = PROBE_HOSTS) -> list[tuple[str, str]]:
    """返回 (主机, 假地址) 列表。DNS 解析失败的跳过，不算证据。"""
    hits = []
    for h in hosts:
        for ip in resolve(h):
            if ipaddress.ip_address(ip) in FAKE_IP_NET:
                hits.append((h, ip))
    return hits


def foreign_country(egress: str) -> str:
    """从出口身份里取出国家码，非 CN 时原样返回；取不到或就是 CN 则返回空串。

    为什么还要看出口国家：`fake_ip_answers()` 只抓得住「DNS 被虚拟网卡接管」这一种形态。
    代理客户端换成系统代理 / 命名代理规则、或者直接放行 DNS 时，探针拿到的是真地址、
    一条警告都不报，但流量照样出境 —— 2026-09-21 那次「出口写着 JP 却只靠 fake-IP 被抓到」
    就是靠运气。国家码这一步是第二条独立的证据，不依赖 DNS 有没有被接管。

    >>> foreign_country("178.253.245.42 JP AS50385 HaloCloud Network")
    'JP'
    >>> foreign_country("119.39.40.124 CN AS4837 CHINA UNICOM")
    ''
    >>> foreign_country("")                 # ipinfo 没答出来：不猜
    ''
    >>> foreign_country("unparseable text")
    ''
    >>> foreign_country("1.2.3.4 CN AS4837 CHINA UNICOM Backbone")
    ''
    """
    for tok in (egress or "").split():
        if len(tok) == 2 and tok.isalpha() and tok.isupper():
            return "" if tok == "CN" else tok
    return ""


def measurement_warnings(egress: str = "") -> list[str]:
    """本机出口能不能用来判定「线路能不能播」。能则返回空列表。

    `egress` 传进来就多一道保险（见 `foreign_country()`）；不传只查 fake-IP。
    """
    out: list[str] = []
    hits = fake_ip_answers()
    if hits:
        sample = "、".join(f"{h} → {ip}" for h, ip in hits[:3])
        out += [
            f"本机 DNS 被虚拟网卡接管（fake-IP 段 {FAKE_IP_NET}）：{sample}",
            "出口不是家庭宽带，实测对国内运营商类地址会给出假阴性 —— "
            "下面「可用 n/m」只能当参考，别据此删源。",
            "要拿到可信数字：临时关掉代理客户端的虚拟网卡/TUN 模式再跑，"
            "或改到与电视同网段的设备上执行（计划书 2.8 第 4 条：NAS 容器）。",
        ]
    cc = foreign_country(egress)
    if cc and not hits:
        out += [
            f"出口国家是 {cc}（不是国内宽带），即便 DNS 没被接管，这一轮对国内源也不作数 —— "
            f"下面「可用 n/m」只能当参考，别据此删源。",
            "要拿到可信数字：关掉代理再跑，或改到与电视同网段的设备上执行（计划书 2.8 第 4 条）。",
        ]
    return out


def egress_hint(timeout: int = 6) -> str:
    """本机出口是谁，形如 `119.39.40.124 CN AS4837`；查不到返回空串。

    强制直连，避免系统代理把查询转发到远端后得到一个「假出口」。
    """
    req = urllib.request.Request(EGRESS_URL, headers={"User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:  # noqa: S310
            d = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:  # 网络不通/超时：留空即可，不阻断生成
        return ""
    return " ".join(str(x) for x in (d.get("ip"), d.get("country"), d.get("org")) if x)
