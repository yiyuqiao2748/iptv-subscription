"""测量点体检：判断「本机实测」这四个字此刻有没有意义。

计划书 2.8 已经在这上面吃过一次亏：Windows 开发机的 DNS 被虚拟网卡接管，
249 条湖南线路被判成失效，实际是隧道掐断而不是源失效。2026-09-20 换到 macOS
开发机是同一个病 —— 直查阿里 DNS 223.5.5.5 也返回 198.18.1.33，出口 IP 在日本机房。

所以只要跑 --verify，先做这个体检再报数字，避免下一轮又拿假阴性做判据。

2026-09-21 反过来验证了一次：关掉代理客户端的 TUN 后 fake-IP 探针归零，
出口变成 119.39.40.124（CN / AS4837 联通骨干），和 Apple TV 所在的
192.168.31.x 是同一张网 —— 这时本机实测才等于电视实测。egress_hint() 就是
把这件事固化成证据写进 probe.json，免得再靠人记住「这次测的数字能不能信」。
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


def measurement_warnings() -> list[str]:
    """本机出口能不能用来判定「线路能不能播」。能则返回空列表。"""
    hits = fake_ip_answers()
    if not hits:
        return []
    sample = "、".join(f"{h} → {ip}" for h, ip in hits[:3])
    return [
        f"本机 DNS 被虚拟网卡接管（fake-IP 段 {FAKE_IP_NET}）：{sample}",
        "出口不是家庭宽带，实测对国内运营商类地址会给出假阴性 —— "
        "下面「可用 n/m」只能当参考，别据此删源。",
        "要拿到可信数字：临时关掉代理客户端的虚拟网卡/TUN 模式再跑，"
        "或改到与电视同网段的设备上执行（计划书 2.8 第 4 条：NAS 容器）。",
    ]


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
