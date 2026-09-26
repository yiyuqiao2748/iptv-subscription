"""命令行入口。

用法：

    python -m src.cli build                  # 用 data/cache 里的上游缓存离线生成
    python -m src.cli build --fresh          # 联网抓 config/sources.yaml 里启用的源
    python -m src.cli build --verify         # 生成前实测线路（probe:false 的源跳过）
    python -m src.cli build --source <url或文件>   # 临时换上游，忽略 sources.yaml
    python -m src.cli build --no-epg --no-egress-check   # 连本机出口也不问：这一轮一次网也不出

产物在 data/output/：aptv.m3u（全量）、hunan.m3u（只有湖南本地）、report.md、probe.json（实测过才有）。

`config/sources.yaml` 是别人维护的聚合源，`config/sources_local.yaml` 是手工核对过的补充线路
（带出处和有效期），两边都会读；`--skip-local` 只在前者里找问题时用。

`config/epg.yaml` 管节目单那一列（计划书 2.19）：它那条地址写进订阅表头部的 `x-tvg-url`，
是**电视自己去取**的；节目单本身优先读 `data/cache/epg.xml`，缓存里没有今天才联网。
取回来只干一件事 —— 把每个频道的 `tvg-id` 换成「这份节目单里到底有」的那个写法
（规则在 `src/check/epg.py`，逐台的对账结果在 report.md 的「EPG 对齐」一节）。
取不到就是空单，一个 id 都不改；`--no-epg` 回到 P3 之前那种「头部抄上游第一条、
id 由谁先创建频道桶决定」的行为。

同一频道的多条线路按「可达范围」+「实测延迟」排先后（范围规则在 config/reachability.yaml），
公网且快的排第一，因为 APTV 默认只播第一条；运营商 IPTV 内网地址和电台冒充项退居备选。

每轮 `--verify` 的主机汇总还会追加到 `data/output/probe-history.jsonl`（一行一轮，
30 分钟内连跑算同一轮）。不带 `--verify` 时靠这份履历排序：上一轮整族连不上的往后压、
上一轮量到过延迟的按那时补位 —— 否则「这次没实测」会让上一轮确认的官方流被来源优先级挤掉。
判据只认体检没报警的那些轮，参照出口见 `judgment_egress()` 的说明；`--ignore-history` 可整个关掉。

`report.md` 里「范围规则各自抓到几条」那一节的七行另外落在旁边的 `data/output/rule-history.jsonl`
（2.51）：一行一轮、**每轮都写**（不实测也写，那七行不吃网络）、**不按时段合并**。
它只干一件事 —— 让「上一轮还抓到、这轮归 0」由工具自己发现，而不是靠人记得上一轮。
它是**参考不是判据**：比出什么都不改动表上一个字节，也不剔一条线路，所以它不进 `probe-history.jsonl`
（量过：并进去会让 `blacklist()` 从 26 族变 27 族，见 `src/check/history.py` 那段注释）。

注意：联网抓取与 --verify 实测都从本机出口出去，所以测量点是谁必须先说清楚。
代理客户端的 TUN 一开，DNS 就被换成 fake-IP、出口跑到境外机房，对国内运营商类地址
全是假阴性（计划书 2.8）。跑 --verify 前会先做体检并把警告打在屏幕上，
出口身份和逐条结果一起写进 data/output/probe.json。
2026-09-21 起：TUN 关掉后本机出口就是家里的联通宽带，与 Apple TV 同一张网，
这时的实测数字可以直接当判据。
问出口那一趟（`egress_hint()` → ipinfo.io）**每轮都跑**，连 `--no-epg` 的纯离线重出也算 ——
在出口不对的时刻它只是一句没用的话，而拿量具量一次 build 就多出一趟外网。
`--no-egress-check` 关的是这一趟：一轮离线重出因此可以「一次网也不出」，屏幕上那句
「本机当前出口」跟着换成「没问」（为什么不能印成「未取到」见 `egress_of()`）。

体检报警的那一轮 `--verify` 只写履历，产物（两张 m3u + probe.json + report.md）关进
`data/output/untrusted/`，`data/output/` 保持上一轮可信版本 —— 因为 `--verify` 会删线路，
而局域网服务正把 `data/output/` 当订阅目录发给电视（见 `artifact_dir()`）。
确实要在别的测量点上出表就加 `--allow-untrusted`。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import socket
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, NamedTuple
from urllib.parse import quote, unquote, urlsplit

# Windows 控制台默认 GBK，输出 emoji 分组名会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.check import history as hist  # noqa: E402
from src.check.env import egress_hint, measurement_warnings  # noqa: E402
from src.check.epg import (  # noqa: E402
    Epg, apply_ids, coverages, gzip_decompress, load_bytes, today_ok)
from src.check.prober import ProbeResult, is_fake_live, probe_many  # noqa: E402
from src.check.scope import (  # noqa: E402
    AUDIO, INTRANET, PUBLIC, RANK, Reachability, config_fingerprint, dead_tier_lines,
    diff_alert_lines, diff_rule_rounds, load_reachability, pool_fingerprint, reach_order_note)
from src.keys import (  # noqa: E402
    _NOT_SET, check_keys, check_version, flag_value, order_value, shape_word, text_value)
from src.match.matcher import load_index  # noqa: E402
from src.match.normalize import quality_hint  # noqa: E402
from src.output.writer import (  # noqa: E402
    OutputChannel, format_m3u, format_report, write_artifacts)
from src.parse.local import SOURCE_ID as LOCAL_ID  # noqa: E402
from src.parse.local import load_local  # noqa: E402
from src.parse.m3u import Entry, parse_m3u  # noqa: E402

SOURCES_FILE = ROOT / "config" / "sources.yaml"
LOCAL_SOURCES_FILE = ROOT / "config" / "sources_local.yaml"
REACH_FILE = ROOT / "config" / "reachability.yaml"
EPG_FILE = ROOT / "config" / "epg.yaml"
HISTORY_FILE = ROOT / "data" / "output" / "probe-history.jsonl"
CACHE_DIR = ROOT / "data" / "cache"
HUNAN_GROUPS = ("hunan_local", "changsha", "shizhou", "jinying")
_RANK = {"4K": 4, "FHD": 3, "HD": 2, "SD": 1, "": 0}
_LATENCY_TIERS = ((400, 0), (1000, 1))    # 毫秒 -> 档位；超过上限算 2

# 带签名/鉴权参数的私有流：URL 里绑死了抓取方的 IP、账号哈希和有效期，
# 别人拿到一定播不了（咪咕那类），而且属于计划书划定的红线（不盗链需鉴权私有流），
# 一律不进订阅列表。
_AUTH_URL = re.compile(
    r"SecurityKey=|ddCalcu=|msisdn=|assertID=|auth_key=|wsTime=|txypb=|"
    r"token=|accountinfo=|[?&]u=[0-9a-f]{16,}", re.I)


def latency_tier(r: ProbeResult | None) -> int:
    """把实测延迟压成三档，作为可达范围之后的第二个排序键。

    没实测（返回 None）给中间档 1，不偏袒也不惩罚。
    只分档不按原始毫秒排，是因为单次抖动几毫秒很常见，直接用毫秒会让整张表顺序乱跳。

    >>> latency_tier(None), latency_tier(ProbeResult(True, 200, 210, 3)), \
        latency_tier(ProbeResult(True, 200, 1271, 3))
    (1, 0, 2)
    """
    if r is None:
        return 1
    for limit, tier in _LATENCY_TIERS:
        if r.ms < limit:
            return tier
    return 2


def judgment_egress(egress: str, warns: list[str], runs: list[dict], *, measured: bool) -> str:
    """本轮排序该用哪个出口当判据。

    规则之所以不是「当前出口」那么直白：这张表是给电视用的，而电视永远待在家里那张
    Wi-Fi 上，它不会跟着开发机的代理跑。所以只有一种情况才用当前出口：
    本轮真在实测（`--verify`）**且**体检没报警。其余一律退回历史里最近一次体检干净的出口；
    离线生成（不带 `--verify`）时当前出口根本不构成任何测量，用它等于没依据。
    真发生过：TUN 开着重出一次离线表，上一轮确认 378ms 的湖南广电官方流就整个消失了。

    >>> clean = [{"at": "t1", "egress": "119.39.40.124 CN", "warnings": []}]
    >>> judgment_egress("119.39.40.124 CN", [], clean, measured=True)  # 本轮体检干净：用本轮
    '119.39.40.124 CN'
    >>> judgment_egress("139.x JP", ["TUN 已开启"], clean, measured=True)  # 本轮测了但不可信
    '119.39.40.124 CN'
    >>> judgment_egress("139.x JP", [], clean, measured=False)            # 离线：只认历史
    '119.39.40.124 CN'
    >>> judgment_egress("139.x JP", ["TUN 已开启"], [], measured=True)     # 没有可信历史：不猜
    ''
    """
    if measured and egress and not warns:
        return egress
    return hist.current_egress("", runs)


EGRESS_SKIPPED = "没问（--no-egress-check）"      # 屏幕上那一格：这一轮压根没去问
EGRESS_MISSING = "未取到"                        # 屏幕上那一格：问了、没问到（网络问题）


def egress_of(no_check: bool, hint: str) -> str:
    """屏幕上那句「本机当前出口」该印什么。

    为什么要单独一位：`build` 每跑一次都花一趟 HTTPS 去问 ipinfo.io（`env.EGRESS_URL`），
    而离线重出（不带 `--verify`）的那一轮**并不拿它量任何东西** —— 11:44 那份普查
    （`/tmp/probe281b_1144.log`，18 档全在仓库的一份副本里跑、产物 `--out` 指到沙盒）量到：
    停在门口的 11 档一条这类动作都没看见，而走完 `collect` 的 7 档每档的护栏行里都有
    「出门 ... -> ipinfo.io」。给这一趟一个不出的法，一轮离线重出才算真的一次网也不出。
    为什么这一位要认三档而不是两档：问到（`hint` 有字）、问了没问到（`hint` 是空串 —— 
    `egress_hint()` 超时或失败就静默回空串）、这一轮选择不问（递了 `--no-egress-check`），
    是三件不同的事。把第二件印成空行，下次排查网络的人就看不见「问过、没问到」这条线索；
    把第三件印成「未取到」，他就会被误导成网络问题。所以两边各有各的一句话。

    >>> egress_of(True, "")
    '没问（--no-egress-check）'
    >>> egress_of(False, "119.39.40.124 CN AS4837")
    '119.39.40.124 CN AS4837'
    >>> egress_of(False, "")                       # 问了、没问到：仍是那句「未取到」
    '未取到'
    """
    return EGRESS_SKIPPED if no_check else (hint or EGRESS_MISSING)


UNTRUSTED = "untrusted"


def artifact_dir(out_dir: Path | str, *, warns: list[str], measured: bool,
                 force: bool = False) -> tuple[Path, bool]:
    """这一轮的产物该落在哪个目录，以及是不是被隔离了。

    `judgment_egress()` 已经保证「体检报警的轮次不参与排序判据」，但那只管到排序为止：
    `--verify` 还会**实测剔除失效线路**并覆盖 `aptv.m3u` / `hunan.m3u` / `probe.json` /
    `report.md`，而 `scripts/serve_lan.py` 正把 `data/output/` 当订阅目录发给电视。
    于是 2026-09-21 夜发生过一次：TUN 开着补跑一轮实测（73 条被假阴性判死），
    电视拿到的那张表当场换成了境外机房视角的版本 —— 履历没错，错在产物。

    所以报警的那一轮只写履历（留着看变化），产物关进 `out_dir/untrusted/`，
    `data/output/` 保持上一轮可信版本原样不动。真要在外网出口上出表就 `force=True`。

    >>> def probe(warns, measured, force=False, out="/o"):
    ...     d, q = artifact_dir(out, warns=warns, measured=measured, force=force)
    ...     return (d.name, q)
    >>> probe([], True)                       # 体检干净的实测：照常落在 data/output
    ('o', False)
    >>> probe(["TUN 已开启"], True)             # 报警的实测：隔离
    ('untrusted', True)
    >>> probe(["TUN 已开启"], True, force=True)  # 明知故犯的出口
    ('o', False)
    >>> probe(["TUN 已开启"], False)            # 离线生成没做实测，无本轮结果可污染
    ('o', False)
    >>> str(artifact_dir("/o/sub", warns=["w"], measured=True)[0]).replace("\\\\", "/")
    '/o/sub/untrusted'
    """
    base = Path(out_dir)
    if measured and warns and not force:
        return base / UNTRUSTED, True
    return base, False


def host_latency(rep: dict[str, hist.HostRep]) -> dict[str, int]:
    """主机 -> 上一轮可信实测的最好延迟。只收「至少通过过一次」的主机。

    >>> r = hist.HostRep
    >>> sorted(host_latency({"a": r("a", 1, 1, 3, 3, 210, "x", 0),
    ...                      "b": r("b", 1, 0, 3, 0, 0, "x", 1)}).items())
    [('a', 210)]
    """
    return {name: rep.best_ms for name, rep in rep.items() if rep.ok_runs and rep.best_ms}


def effective_tier(url: str, r: ProbeResult | None, hist_ms: dict[str, int]) -> int:
    """排序用的延迟档：本轮实测 > 上一轮同主机的实测 > 没听说过。

    为什么需要第二级：离线生成（不带 `--verify`）时所有线路都没有本轮实测，
    原来全部落在中间档 1，于是 mgtv 那条湖南广电官方流（实测 378ms）会被
    来源优先级挤到第三条之后 —— 2026-09-21 实测过一轮之后，离线重出一次表，
    那条线直接从 `aptv.m3u` 里消失了。用上一轮的延迟补位，就是不让表里最好的一条
    线路因为「这次没空重测」而被换掉。本轮只要测过，就完全不听历史的。

    >>> m = {"fast.example": 210, "slow.example": 1326}
    >>> effective_tier("http://fast.example/a.m3u8", None, m)      # 上轮 210ms -> 最快档
    0
    >>> effective_tier("http://slow.example/a.m3u8", None, m)      # 上轮 1326ms -> 最慢档
    2
    >>> effective_tier("http://new.example/a.m3u8", None, m)       # 没历史：不偏袒
    1
    >>> effective_tier("http://fast.example/a.m3u8", ProbeResult(True, 200, 1500, 3), m)
    2
    """
    if r is not None:
        return latency_tier(r)
    ms = hist_ms.get(urlsplit(url).hostname or "")
    return latency_tier(ProbeResult(True, 200, ms, 1)) if ms else 1


def history_strike(url: str, r: ProbeResult | None, stale: frozenset[str]) -> int:
    """这一轮没实测、但上一轮整族连不上的主机，往后压一档。

    它存在的唯一理由：`build` 不带 `--verify` 时手里没有任何实测信息，
    上一轮已经确认 0/35 的 `stream1.freetv.fun` 会凭来源优先级又爬回频道第一位。
    只要本轮测过（r 不是 None），历史就闭嘴 —— 现场的数永远比记忆可信，
    中转主机「今天全灭明天全通」两种方向都发生过。

    >>> live = ProbeResult(True, 200, 900, 3)
    >>> stale = frozenset({"dead.example"})
    >>> history_strike("http://dead.example/a.m3u8", live, stale)     # 本轮说能播，就听本轮
    0
    >>> history_strike("http://dead.example/a.m3u8", None, stale)     # 没实测 + 上轮全灭
    1
    >>> history_strike("http://good.example/a.m3u8", None, stale)
    0
    """
    if r is not None:
        return 0
    return 1 if (urlsplit(url).hostname or "") in stale else 0


def roll_strike(url: str, r: ProbeResult | None, rolls: dict[str, str]) -> int:
    """L3 验过「隔十几秒重取，分片窗口一动不动」的那条线路，本轮没重测时往后压一档。

    为什么不并入主机那一档（`fake_strike`）：一个主机可以有三十八条线路，
    L3 一次只盯得住几个台的第一线。整族判断要「通了的全是录像」才成立，
    而这一条是逐条的确凿证据 —— 少一个精度，那条 2026-09-21 的残留列表就会
    继续顶着同主机另外几条一起占位。同样只在没重测时生效。

    >>> rolls = {"http://a.example/stuck.m3u8": "stuck", "http://a.example/live.m3u8": "rolling"}
    >>> roll_strike("http://a.example/stuck.m3u8", None, rolls)
    1
    >>> roll_strike("http://a.example/live.m3u8", None, rolls)      # 上次验过在滚：不惩罚
    0
    >>> roll_strike("http://a.example/stuck.m3u8",                  # 本轮重测过，听本轮的
    ...               ProbeResult(True, 200, 90, 4, "", "live"), rolls)
    0
    >>> roll_strike("http://a.example/new.m3u8", None, rolls)       # L3 没看过：不猜
    0
    """
    if r is not None:
        return 0
    return 1 if rolls.get(url) == "stuck" else 0


def fake_strike(url: str, r: ProbeResult | None, fake: frozenset[str]) -> int:
    """上一轮确认「通了的全是循环录像」的主机，本轮没实测时往后压一档。

    和 `history_strike()` 是两个不同的病：那个是连不上（电视上超时），
    这个连得上、有画，播出来是几小时前的节目，而且往往比真直播还快 ——
    2026-09-21 实测到快手 CDN 一条 1259 分片的录像挂在湖南卫视名下，延迟比官方流还低。
    所以它必须排在真直播后面，但**不删**：一个台只剩录像和够不着的内网地址时，
    有画可看比超时强，代价是在报告里点名说清楚它不是直播。

    同样地，本轮只要测过就听本轮的（`is_fake_live(r)` 那一档会直接判它）。

    >>> fake = frozenset({"loop.example"})
    >>> fake_strike("http://loop.example/a.m3u8", None, fake)          # 没实测 + 上轮全是录像
    1
    >>> fake_strike("http://loop.example/a.m3u8",                     # 本轮重测：真在滚动
    ...               ProbeResult(True, 200, 100, 3, "", "live"), fake)
    0
    >>> fake_strike("http://other.example/a.m3u8", None, fake)
    0
    """
    if r is not None:
        return 0
    return 1 if (urlsplit(url).hostname or "") in fake else 0


# 源清单允许的键，连同「这个键一改，表上就有东西跟着变」那句话一起交给 `src/keys.py`。
# 为什么名单写在这儿而不是 keys.py 里：谁被读是读它的那段代码的事，放在一起才看得出漂没漂
# —— 而「看得出」从 2.42 起是一条真用例（`load_sources` 末尾那句 `drift_of`），不是排版。
SOURCES_TOP_KEYS = ["version", "sources"]
SOURCES_TOP_NOTES = {"sources": "这一轮有哪几个上游"}
SOURCE_KEYS = ["id", "url", "enabled", "priority", "probe", "note"]
SOURCE_NOTES = {
    "id": "缓存文件名、报告里的源名、履历里的出处",
    "url": "去哪儿抓这份列表",
    "enabled": "这条源参不参与出表",
    "priority": "同一频道里谁排第一条（不写就是按这里的先后）",
    "probe": "它进不进 --verify 实测",
}
# `url` 和 `id` 被读成品体不明的东西时，那句「该怎么改」和节目单那份不是一句话，
# 所以从 `text_value()` 的默认值里分出来各写各的（2.46）：这一份的 `url` 排成两条是
# 「再加一条源」，而 `id` 根本不是地址 —— 它是文件名，改名是会命中不到缓存的。
_SOURCE_URL_ADVICE = ("要抓两条就分成两条源（各自一个 `id`、各自一份缓存）；这一格是当地址用的，"
                      "老读法把列表原样交给 `fetch()`，缓存命中时表上一点看不出来，"
                      "而缓存一删、或者哪天跑了 `--fresh`，它就在下一层当场 AttributeError")
_SOURCE_ID_ADVICE = ("`id` 是缓存文件名（`data/cache/<id>.m3u`）和报告里的源名，得写成文字："
                     "`0123` 那种带前导零的写法 YAML 1.1 按八进制读，读出来是 83 —— "
                     "名字自己换了一个，`data/cache/0123.m3u` 从此命中不到")


def load_sources(path: Path, *, fresh: bool) -> list[dict]:
    """读 config/sources.yaml 里启用的源，解析成本地缓存路径或远端 URL。

    默认优先用 data/cache/<id>.m3u（可离线复现），没有缓存才联网；
    --fresh 强制联网，抓到的内容会回写缓存。

    `probe: false` 的源（运营商内网源）不参与 --verify 实测：
    它们的可达性取决于看电视那张网，开发机上测出来全红是假阴性。

    读不了 / 写歪了都抛 `OSError` 或 `ValueError`，**不静默跳过那一条**：
    少一个源在表上是看不出来的（那些台会安静地变成「本来就没有」），
    所以宁可停下让人去修配置。以前这里连形状都不查 —— 一条源漏写 `url`
    就是裸 `KeyError: 'url'`（2.36 实测），YAML 少个缩进是 `ParserError` 崩栈。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     good = Path(d) / "s.yaml"
    ...     _ = good.write_text(chr(10).join(
    ...         ["sources:", "  - id: a", "    url: http://x/a.m3u", "  - id: off",
    ...          "    url: http://x/off", "    enabled: false"]), encoding="utf-8")
    ...     [(s["id"], s["probe"]) for s in load_sources(good, fresh=False)]
    [('a', True)]
    >>> with tempfile.TemporaryDirectory() as d:                 # 漏写 url
    ...     bad = Path(d) / "s.yaml"
    ...     _ = bad.write_text("sources:\\n  - id: a\\n", encoding="utf-8")
    ...     try:
    ...         load_sources(bad, fresh=False)
    ...     except ValueError as e:
    ...         print(str(e).split(" 第 1 条源缺 ")[1])   # 前半截是那个临时文件的路径
    url（现在只有 ['id']），先修配置再出表

    键名写歪也停下来（2.39）。这份文件里最贵的一类错不是漏写 —— 漏写有上面那句「缺 url」
    接住 —— 是**看起来像写了**：`enable: false` 少两个字母，那条源照样进表，
    而人以为已经把它关了。`src/keys.py` 里把哪些键算「一改就有东西跟着变」写明了。

    >>> with tempfile.TemporaryDirectory() as d:                # enabled 写成了 enable
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text("sources:\\n  - id: a\\n    url: http://x/a\\n    enable: false\\n",
    ...                      encoding="utf-8")
    ...     try:
    ...         load_sources(p, fresh=False)
    ...     except ValueError as e:
    ...         print("最像是 `enabled`" in str(e), "参不参与出表" in str(e))
    True True

    2.46：同一把刀刮到 `config/sources.yaml` 上。那一节量的是节目单那份配置，
    而这一份有一模一样的三格 —— 老读法是 `not s.get("enabled", True)`、`bool(s.get("probe", True))`、
    `int(s.get("priority", i + 1))`，三句都**几乎总能出一个值**。拿四种写法各演一遍（数字都是当场跑的）：

    * `enabled: "false"` —— 加了引号的关，`bool("false")` 是**真**：那条源照样进表。
      在用的那份配置上把 `hn_mobile` 这么写，出表退 0、屏幕上写着「读取 3 个上游」，
      `aptv.m3u` 226 条、`hunan.m3u` 58 条，**与基线一字不差**；而照人本意真关掉它的那一遍是
      「读取 2 个上游」、186 / 22。一个引号差出 40 条线路（湖南那张 36 条）和 22 个台，
      表上没有任何一处说这事。
    * `enabled:`（写了没填）—— `not None` 是真 → 那条源整个不进表；而节目单那份同样一个空值
      被 `flag_value` 猜成「开」。**同一个空位在两份配置里读成相反的意思**，所以这里停下来问。
    * `probe: "false"` —— 也是真，于是那 100 条线路被放进实测池；离线能看到的一句是
      `report.md` 里那条「`probe: false` 的源（`hn_unicom`、`hn_mobile`）从不实测」
      悄悄少了 `hn_mobile`（只剩 `hn_unicom`），屏幕上那句「候选 350 条」变成「候选 450 条、
      其余 100 条按未知处理」。
    * `priority:` 空着 —— `int(None)` 是 **TypeError**，不在 `cmd_build` 接住的那两种里：
      实测退 1、stdout 一个字没有、`--out` 那个目录根本没建，屏幕上只有一段 traceback。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:                 # 加引号的关：现在算关
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text('sources:\\n  - id: a\\n    url: http://x/a\\n    enabled: "false"\\n',
    ...                      encoding="utf-8")
    ...     load_sources(p, fresh=False)
    []
    >>> with tempfile.TemporaryDirectory() as d:                 # 加引号的 probe：不进实测池
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text('sources:\\n  - id: a\\n    url: http://x/a\\n    probe: "false"\\n',
    ...                      encoding="utf-8")
    ...     [(s["id"], s["probe"]) for s in load_sources(p, fresh=False)]
    [('a', False)]
    >>> with tempfile.TemporaryDirectory() as d:                 # 写了没填：停下来，不猜
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text("sources:\\n  - id: a\\n    url: http://x/a\\n    enabled:\\n",
    ...                      encoding="utf-8")
    ...     try:
    ...         load_sources(p, fresh=False)
    ...     except ValueError as e:
    ...         print("的 `enabled` 写了却没填值" in str(e), type(e).__name__)
    True ValueError
    >>> with tempfile.TemporaryDirectory() as d:                 # 小数不再被砍成整数
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text("sources:\\n  - id: a\\n    url: http://x/a\\n    priority: 1.5\\n",
    ...                      encoding="utf-8")
    ...     try:
    ...         load_sources(p, fresh=False)
    ...     except ValueError as e:
    ...         print("会把它砍成 1" in str(e))
    True
    >>> with tempfile.TemporaryDirectory() as d:                 # 那句英文不再是唯一的说明
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text("sources:\\n  - id: a\\n    url: http://x/a\\n    priority: 前三\\n",
    ...                      encoding="utf-8")
    ...     try:
    ...         load_sources(p, fresh=False)
    ...     except ValueError as e:
    ...         print("invalid literal" in str(e), "不是一个整数" in str(e))
    False True
    >>> with tempfile.TemporaryDirectory() as d:                 # `priority:` 空着：不再 TypeError
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text("sources:\\n  - id: a\\n    url: http://x/a\\n    priority:\\n",
    ...                      encoding="utf-8")
    ...     try:
    ...         load_sources(p, fresh=False)
    ...     except ValueError as e:
    ...         print("写了却没填值" in str(e))
    True
    >>> with tempfile.TemporaryDirectory() as d:                 # 两条地址排成列表：停在这一层
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text("sources:\\n  - id: a\\n    url:\\n      - http://x/a\\n"
    ...                      "      - http://x/b\\n", encoding="utf-8")
    ...     try:
    ...         load_sources(p, fresh=False)
    ...     except ValueError as e:
    ...         print("读出来是一个列表" in str(e), "分成两条源" in str(e))
    True True
    >>> with tempfile.TemporaryDirectory() as d:                 # `id: 0123` 会被读成 83
    ...     p = Path(d) / "s.yaml"
    ...     _ = p.write_text("sources:\\n  - id: 0123\\n    url: http://x/a\\n", encoding="utf-8")
    ...     try:
    ...         load_sources(p, fresh=False)
    ...     except ValueError as e:
    ...         print(str(e).split("读出来是")[1].split("（")[0], "——", "八进制" in str(e))
    一个数字 —— True

    上面那些「停下来」都不该动到在用的那份配置 —— 这一格是真文件，它必须一个字都不用改：

    >>> real = load_sources(SOURCES_FILE, fresh=False)
    >>> bool(real) and all(isinstance(s["id"], str) and isinstance(s["priority"], int)
    ...                    and isinstance(s["probe"], bool) for s in real)
    True

    上面那两份名单和这段代码说的是不是同一批键 —— 这一条不问配置，问这把闸自己（2.42）。
    名单写在这段代码旁边还只是排版上的旁边，「旁边」得有一条用例盯着才不作废：

    >>> from src.keys import drift_of
    >>> drift_of(load_sources, known=SOURCE_KEYS + SOURCES_TOP_KEYS,
    ...          notes={**SOURCE_NOTES, **SOURCES_TOP_NOTES})
    []
    """
    text = Path(path).read_text(encoding="utf-8")
    cfg = yaml.safe_load(text)
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} 读出来不是「sources: […]」那种结构（是 "
                         f"{type(cfg).__name__}），这一份不能当源清单用")
    check_version(cfg, where=str(path))
    for warn in check_keys(cfg, where=str(path), known=SOURCES_TOP_KEYS,
                           notes=SOURCES_TOP_NOTES):
        print(f"⚠️ {warn}", file=sys.stderr)
    out = []
    for i, s in enumerate(cfg.get("sources") or []):
        if not isinstance(s, dict):
            raise ValueError(f"{path} 第 {i + 1} 条源不是字典（是 {type(s).__name__}）")
        where = f"{path} 第 {i + 1} 条源"
        # 关掉的源也查：那条源迟早要开回来，写歪的键不会自己变对
        for warn in check_keys(s, where=where, known=SOURCE_KEYS, notes=SOURCE_NOTES):
            print(f"⚠️ {warn}", file=sys.stderr)
        if not flag_value(s.get("enabled", _NOT_SET), where=where, key="enabled"):
            continue
        sid = text_value(s.get("id"), where=where, key="id",
                         what="一串文字", advice=_SOURCE_ID_ADVICE)
        url = text_value(s.get("url"), where=where, key="url",
                         advice=_SOURCE_URL_ADVICE)
        missing = [k for k, v in (("id", sid), ("url", url)) if not v]
        if missing:
            raise ValueError(f"{path} 第 {i + 1} 条源缺 {' 和 '.join(missing)}"
                             f"（现在只有 {sorted(s)}），先修配置再出表")
        cache = CACHE_DIR / f"{sid}.m3u"
        target = url if (fresh or not cache.exists()) else str(cache)
        out.append({"id": sid, "target": target, "cache": cache, "url": url,
                    "probe": flag_value(s.get("probe", _NOT_SET), where=where, key="probe"),
                    "priority": order_value(s.get("priority", _NOT_SET), where=where,
                                            key="priority", default=i + 1)})
    return out


def local_path(target: str) -> Path:
    """把「本地文件那种写法」折成一个 Path。

    为什么单独有这一层：`fetch()` 只认 `http(s)://` 前缀，剩下的一律当路径，
    而 `Path("file:///tmp/a.m3u")` 会把三个斜杠吃掉一个，报出来的错是
    `No such file or directory: 'file:/tmp/a.m3u'` —— **那个路径不存在，
    可用户写的文件是存在的**，照着报错去找文件会找错地方（2.36 实测）。
    有人往 `config/sources.yaml` 里粘 `file://` 地址是常态（浏览器里复制就是这么个形状），
    所以这里替他把它折回来，而不是要求他先改成纯路径。

    >>> local_path("file:///tmp/a/b.m3u")
    PosixPath('/tmp/a/b.m3u')
    >>> local_path("/tmp/a/b.m3u")
    PosixPath('/tmp/a/b.m3u')
    >>> local_path("./a.m3u")
    PosixPath('a.m3u')
    >>> local_path("file:///tmp/%E6%B9%96%E5%8D%97.m3u")   # 百分号转义要还原
    PosixPath('/tmp/湖南.m3u')
    """
    if target.startswith("file://"):
        return Path(unquote(urlsplit(target).path))
    return Path(target)


def fetch(target: str, timeout: int = 60) -> str:
    """读上游。本地文件直接读，URL 走 urllib（自动使用系统代理设置）。

    读不到就抛 `OSError`（文件不存在、是个目录、没权限），**不在这里降级** ——
    少了谁、为什么少，得由知道「这一轮一共有几个源、各指望它出什么」的那一层来说
    （见 `collect()`）。
    """
    if target.startswith(("http://", "https://")):
        url = quote(target, safe=":/?&=%#[]@!$'()*+,;")   # 上游路径里有中文
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    return local_path(target).read_text(encoding="utf-8", errors="replace")


def fetch_bytes(target: str, timeout: int = 60) -> bytes:
    """`fetch` 的字节版，给节目单用（那份可能是 .gz，不能先按文本解）。

    本地路径照读 —— 不是为了绕过网络，是为了 `load_epg()` 那串样例能在不联网的情况下
    把「缓存新/缓存旧/取不到」三条分支都走一遍。
    """
    if target.startswith(("http://", "https://")):
        url = quote(target, safe=":/?&=%#[]@!$'()*+,;")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()
    return local_path(target).read_bytes()


def epg_header_url(cfg: dict, upstream_urls: list[str]) -> str:
    """订阅表头部 `x-tvg-url` 该写哪条地址（电视自己去取的就是这一行）。

    两条规矩：
      * 未启用才回到「抄上游播放列表的第一条」—— 那是 P3 之前的行为，原样留着，
        但要知道它实测 404（计划书 2.19），所以这条路只是为了「什么都没配」时不改变产物；
      * 启用但地址不是 http(s) —— **不写**。本地路径是给 `load_epg()` 做实验用的，
        电视拿不到，写进头部就是一句谎话；宁可不写。

    >>> epg_header_url({"enabled": True, "url": "https://e.erw.cc/e.xml.gz"}, ["http://抄来的"])
    'https://e.erw.cc/e.xml.gz'
    >>> epg_header_url({"enabled": True, "url": "/tmp/local.xml"}, ["http://抄来的"])
    ''
    >>> epg_header_url({"enabled": False, "url": "https://e.erw.cc/e.xml.gz"}, ["http://抄来的"])
    'http://抄来的'
    >>> epg_header_url({"enabled": False, "url": ""}, [])
    ''
    """
    if not cfg.get("enabled"):
        return upstream_urls[0] if upstream_urls else ""
    url = str(cfg.get("url") or "")
    return url if url.startswith(("http://", "https://")) else ""


EPG_TOP_KEYS = ["version", "epg"]
EPG_TOP_NOTES = {"epg": "tvg-id 照哪一份节目单对"}
EPG_KEYS = ["url", "backup_url", "cache", "enabled", "caveat", "note"]
EPG_NOTES = {
    "url": "节目单从哪儿取，tvg-id 就照着谁对",
    "enabled": "对 id 这一层开不开（关掉就是所有台退回上游写法）",
    "cache": "取回来的节目单落在哪儿，离线重出与「今天够不够新」都读它",
    "backup_url": "换成后备节目单时抄哪一条（`scripts/epg_check.py` 拿它当第二条候选）",
}
# `note` 是写给人看的为什么。
# `backup_url` 从 2.44 起由这里读、跟着 `url` 一起交出去：以前是 build 和
# `scripts/epg_check.py` 各写一份 YAML 读取，两份读法量出四种分歧（那一节有表）。


def load_epg_config(path: Path) -> dict:
    """读 `config/epg.yaml` 里那一节；文件不在或被写坏了就当「没启用」。

    「没地址就等于没启用」是同一件事的两种说法，所以只写一条判据（`enabled` 由 `url` 参与决定）。
    这样默认值是安全的：新克隆的仓库里没有这个文件，生成行为跟 P3 之前逐字节一致。

    >>> c = load_epg_config(EPG_FILE)
    >>> c["enabled"], c["url"].startswith("http")     # 不钉死是哪条地址，见下
    (True, True)
    >>> c["cache"].name, c["state"]
    ('epg.xml', '在用')
    >>> c["backup_url"] != ""                          # 换节目单时抄的那一条，2.44 起在这儿读
    True
    >>> n = load_epg_config(ROOT / "config" / "definitely-missing.yaml")
    >>> n["enabled"], n["url"]        # 不抛，只是什么都不做
    (False, '')
    >>> n["state"]                     # 「没启用」底下那几种各有各的修法，2.44 起分开说
    '文件不在'
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("epg:\\n  url: http://x/e.xml\\n  enabled: false\\n", encoding="utf-8")
    ...     load_epg_config(p)["state"]
    '关着'
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("version: 1\\nepg:\\n  url: [oops\\n   bad indent: x\\n",
    ...                      encoding="utf-8")          # YAML 本身就写坏了
    ...     load_epg_config(p)["state"]
    'YAML 读不出来'
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("version: 1\\nepg: https://x/e.xml\\n", encoding="utf-8")
    ...     try:
    ...         load_epg_config(p)
    ...     except ValueError as e:
    ...         print("epg` 那一格" in str(e))
    True

    真配置那条只钉「启用 ⇒ 地址是 http(s)」这一件事，不钉它是 `e.erw.cc` ——
    这套设计的卖点就是「换节目单 = 改一行」（`config/epg.yaml` 的 note 里记着为什么是那条），
    把地址写进断言里等于每换一次地址就先修一次测试。

    「不抛」只对**读不出来**的那几种；文件明明在、键名写歪是另一件事（2.39）。
    `enabledd: false` 以前等于「节目单还开着」，而写的人以为已经关了 —— 现在停下来。

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("epg:\\n  url: http://x/e.xml\\n  enabledd: false\\n", encoding="utf-8")
    ...     try:
    ...         load_epg_config(p)
    ...     except ValueError as e:
    ...         print("最像是 `enabled`" in str(e))
    True

    顶层 `epg:` 写成 `epgs:` 以前是彻底安静：`.get("epg")` 拿到空，于是这被读成
    「没配地址 = 没启用」，出表照出，只是 tvg-id 全退回上游写法。

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("epgs:\\n  url: http://x/e.xml\\n", encoding="utf-8")
    ...     try:
    ...         load_epg_config(p)
    ...         print("没拦")
    ...     except ValueError:
    ...         print("拦下了")
    拦下了

    2.44 补上的两格：形状和真假。这两格都是「长得像没写、其实写了个错的」，
    而它们的共同点是**表上看不出来** —— 一格的后果跑到了 `aptv.m3u` 的第一行（头部那行
    `x-tvg-url` 没了），另一格跑到了电视的节目单上（以为关了，其实一直开着）。

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("epg:\\n  url:\\n  - http://x/e.xml\\n  - http://y/e.xml\\n",
    ...                      encoding="utf-8")      # 换行缩进 = YAML 读成列表
    ...     try:
    ...         load_epg_config(p)
    ...     except ValueError as e:
    ...         print(str(e).split("`")[1], "拦下了")
    url 拦下了
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text('epg:\\n  url: http://x/e.xml\\n  enabled: "false"\\n',
    ...                      encoding="utf-8")      # 引号包住的 false
    ...     load_epg_config(p)["enabled"]
    False

    停下来那句还要能被 `stop_config` 直接接住：文件路径只出现一次，「读不了：」后面紧跟的是
    「epg 段」而不是「**的** epg 段」—— 2.44 第一次实测印出来的正是后者，因为 `where` 里那个
    「的」字跟着路径一起被 `stop_message` 剥了一半（它只认开头那段相同的文件路径）。

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("epg:\\n  url:\\n    - http://x/e.xml\\n", encoding="utf-8")
    ...     try:
    ...         load_epg_config(p)
    ...     except ValueError as e:
    ...         msg = stop_message("节目单配置", str(p), str(e), "先修那一行")
    ...         print(msg.count(str(p)), msg.split("读不了：")[1].split("（")[0])
    1 epg 段 的 `url` 读出来是一个列表

    名单与这段代码对得上吗（2.42）。`backup_url` 从 2.44 起也进 `EPG_NOTES` 了：
    以前它由 `scripts/epg_check.py` 另写一份 YAML 读取去拿，两份读法量出四种分歧，
    现在只留这一处，所以它和 `url` 一样得由这段代码读到才算数。

    >>> from src.keys import drift_of
    >>> drift_of(load_epg_config, known=EPG_KEYS + EPG_TOP_KEYS,
    ...          notes={**EPG_NOTES, **EPG_TOP_NOTES})
    []
    """
    missing = not Path(path).exists()
    broken = False
    try:
        top = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        top, broken = {}, True
    if not isinstance(top, dict):
        top = {}
    raw_epg = top.get("epg")
    cfg = raw_epg if isinstance(raw_epg, dict) else {}
    # 键名守卫只在「这份文件真的读出来了」之后才谈：读不出来还是老行为（当没启用）。
    # 不然新克隆的仓库会因为一份本来就可选的配置出不了表 —— 那是跟上面那句「默认值安全」
    # 直接冲突的。写坏了 YAML 的那格同理：形状都不在，谈不上键名。
    if top:
        check_version(top, where=str(path))
        for warn in check_keys(top, where=str(path), known=EPG_TOP_KEYS,
                               notes=EPG_TOP_NOTES):
            print(f"⚠️ {warn}", file=sys.stderr)
    if cfg:
        for warn in check_keys(cfg, where=f"{path} epg 段", known=EPG_KEYS, notes=EPG_NOTES):
            print(f"⚠️ {warn}", file=sys.stderr)
    # `where` 里带路径、但**不带「的」**：`stop_message` 会把理由开头那段相同的文件路径剥掉
    # （见它的第三格），跟着的要是「的 epg 段」，屏幕上就剩下「读不了：的 epg 段 …」。
    # 上面 `load_sources` 那处 `{path} 第 N 条源` 是同一个形状，照它写。
    where = f"{path} epg 段"
    if top and not isinstance(raw_epg, (dict, type(None))):
        raise ValueError(
            f"{path} `epg` 那一格读出来是{shape_word(raw_epg)}（{raw_epg!r}），不是一组键 —— "
            "地址要写成下一行的 `url: …`。这一格读不出键就等于「没配地址」，"
            "也就是把节目单安静地关掉：表上那一列 tvg-id 整列退回上游写法，而屏幕上看不出来")
    url = text_value(cfg.get("url"), where=where, key="url")
    on = flag_value(cfg.get("enabled", _NOT_SET), where=where, key="enabled")
    return {
        "url": url,
        "backup_url": text_value(cfg.get("backup_url"), where=where, key="backup_url"),
        "cache": ROOT / (text_value(cfg.get("cache"), where=where, key="cache")
                         or "data/cache/epg.xml"),
        "enabled": on and bool(url),
        # 「这份配置到底让不让节目单进表」的一句话来历。build 里那句「未启用」以前把
        # 文件不在 / YAML 写坏了 / 真的没写地址 全洗成同一句（2.44），而它们的修法不一样。
        "state": ("文件不在" if missing else "YAML 读不出来" if broken else
                  "没写地址" if not url else "关着" if not on else "在用"),
        "caveat": text_value(cfg.get("caveat"), where=where, key="caveat"),
    }


def epg_off_note(cfg: dict, no_epg: bool) -> str:
    """未启用那一行的**为什么**：把「没启用」底下那几种各有各的修法分开说。

    2.44 之前这一句写死成「config/epg.yaml 没写地址、或加了 --no-epg」。前面那半是猜的：
    文件在、YAML 写坏了，屏幕上照样是「没写地址」，而修法是两回事（一个是去补一行，
    一个是去改缩进）。`load_epg_config()` 现在带着 `state`，这句就能照着说。

    >>> epg_off_note({"state": "文件不在"}, False)
    'config/epg.yaml 不在'
    >>> epg_off_note({"state": "YAML 读不出来"}, False)
    'config/epg.yaml 那份 YAML 读不出来（不是没写，是写坏了）'
    >>> epg_off_note({"state": "关着"}, False)
    'config/epg.yaml 里写着 `enabled: false`'
    >>> epg_off_note({"state": "没写地址"}, False)
    'config/epg.yaml 没写 url'
    >>> epg_off_note({"state": "在用"}, True)          # 配置开着，是命令行关的
    '加了 --no-epg（配置本身是在用的）'
    >>> epg_off_note({"state": "关着"}, True)
    'config/epg.yaml 里写着 `enabled: false`、又加了 --no-epg'
    >>> epg_off_note({"state": "在用"}, False)   # 手搓：`在用` 走到不到这一句（见下面那段）
    '说不清是哪儿关的'

    最后一格同样是**手搓出来的输入**：`enabled` 与 `state` 由同一处算出来，
    「在用」必然 `enabled=True`，而调用方只在 `enabled` 为假时才问这一句。
    留一个「说不清」而不是留一个空括号，是因为这句话会被印成「未启用（），tvg-id 保持上游写法」——
    那种空位比说错更难看，而它出现的唯一原因是这两格不再由同一段代码保证。
    """
    why = {"文件不在": "config/epg.yaml 不在",
           "YAML 读不出来": "config/epg.yaml 那份 YAML 读不出来（不是没写，是写坏了）",
           "关着": "config/epg.yaml 里写着 `enabled: false`",
           "没写地址": "config/epg.yaml 没写 url"}.get(cfg.get("state") or "", "")
    if no_epg and why:
        return f"{why}、又加了 --no-epg"
    return why or ("加了 --no-epg（配置本身是在用的）" if no_epg else "说不清是哪儿关的")


def load_epg(cfg: dict, *, today: str, force: bool = False,
             timeout: int = 60) -> tuple[Epg, dict]:
    """按「缓存优先、缓存里没有今天就重取」拿节目单，返回 (节目单, 一份来历)。

    为什么规则写成「够不够新」而不是「用户有没有让我联网」：节目单是**有时效**的东西，
    昨天那份的 `tvg-id` 对今天照样能用，但它自己覆盖不到今天，电视上就是空节目单。
    `today_ok()` 量得出这件事（它 = `has_today()` 且不是 `thin_today()` 那种「有日期、
    只剩几个台」的瘦今天，2.33），所以取不取网看它，不看 `--fresh`；`--fresh` 只是顺带强制重取。

    三条退路都是同一条原则：这一层只负责让 id 对得上，EPG 挂了、取回来是报错页、
    缓存读不出来，任何一种都**不许影响出表**（`apply_ids()` 拿到空单什么都不改）。

    >>> import pathlib, tempfile
    >>> xml = ('<tv><channel id="CCTV1"><display-name lang="zh">CCTV1</display-name></channel>'
    ...        '<programme channel="CCTV1" start="20260921000000 +0800"></programme></tv>')
    >>> with tempfile.TemporaryDirectory() as d:
    ...     src = pathlib.Path(d) / "e.xml"
    ...     _ = src.write_text(xml, encoding="utf-8")
    ...     cfg = {"enabled": True, "url": str(src), "cache": pathlib.Path(d) / "epg.xml"}
    ...     doc, info = load_epg(cfg, today="20260921")
    ...     doc.ids, info["via"], info["ok"], info["refreshed"]
    ...     doc2, info2 = load_epg(cfg, today="20260921")      # 第二次不再联网，读缓存
    ...     doc2.ids, info2["via"], info2["refreshed"]
    ...     doc3, info3 = load_epg(cfg, today="20261231")      # 缓存没有今天 -> 重取
    ...     info3["ok"], info3["coverage"]
    ...     cfg = {**cfg, "url": str(pathlib.Path(d) / "gone.xml")}
    ...     doc4, info4 = load_epg(cfg, today="20260921", force=True)
    ...     doc4.ids, info4["ok"], "FileNotFound" in info4["error"], info4["via"]
    (['CCTV1'], '联网', True, True)
    (['CCTV1'], '缓存（epg.xml）', False)
    (False, '没有今天的内容（覆盖 1 天：20260921，距今 101 天）')
    (['CCTV1'], True, True, '缓存（epg.xml，联网失败后退回）')

    缓存里「有今天」但今天只剩一个台（2.33 那种被截断的取回）不算 good —— 重取，
    重取回来还是瘦的就照实说瘦，不复用「今天有节目」那五个字：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     chans = "".join(f'<channel id="x{i}"><display-name>X{i}</display-name></channel>'
    ...                     for i in range(40))
    ...     progs = "".join(f'<programme channel="x{i}" start="20260920000000 +0800"></programme>'
    ...                     for i in range(40))
    ...     thin = ('<tv>' + chans + progs +
    ...             '<programme channel="x1" start="20260921000000 +0800"></programme></tv>')
    ...     src = pathlib.Path(d) / "e.xml"
    ...     _ = src.write_text(thin, encoding="utf-8")
    ...     cache = pathlib.Path(d) / "epg.xml"
    ...     _ = cache.write_text(thin, encoding="utf-8")
    ...     cfg = {"enabled": True, "url": str(src), "cache": cache}
    ...     doc, info = load_epg(cfg, today="20260921")
    ...     info["via"], info["ok"], info["coverage"]
    ('联网', False, '今天只有 1 个台有条目（另外那天 40 个 —— 这份单子像被截断了）')
    """
    info: dict = {"url": cfg.get("url", ""), "via": "未取到", "note": "",
                  "error": "", "coverage": "", "ok": False, "refreshed": False}
    if not cfg.get("enabled") or not cfg.get("url"):
        return Epg(), {**info, "via": "未启用"}

    cache = Path(cfg["cache"])
    cached: Epg | None = None
    cached_note = ""
    if cache.exists():
        try:
            cached, cached_note = load_bytes(cache.read_bytes())
        except OSError as e:
            info["error"] = f"缓存读不出来：{type(e).__name__}: {e}"

    if cached is not None and today_ok(cached, today) and not force:
        return cached, {**info, "via": f"缓存（{cache.name}）", "note": cached_note,
                        "coverage": coverages(cached, today), "ok": True}

    try:
        raw = fetch_bytes(cfg["url"], timeout=timeout)
        if raw[:2] == b"\x1f\x8b":
            raw = gzip_decompress(raw)        # 缓存一律存解开的，后来的人才好直接看
        doc, note = load_bytes(raw)
    except Exception as e:                    # 取节目单失败不许带崩整张表
        if cached is None:
            return Epg(), {**info, "error": f"{type(e).__name__}: {e}"}
        return cached, {**info, "via": f"缓存（{cache.name}，联网失败后退回）",
                        "note": cached_note, "error": f"{type(e).__name__}: {e}",
                        "coverage": coverages(cached, today), "ok": today_ok(cached, today)}

    if not doc.ids:                           # 报错页/空单：不覆盖缓存，也不改任何 id
        msg = f"取回来了但一条频道都没有：{note}"
        if cached is not None:
            return cached, {**info, "via": f"缓存（{cache.name}，新取的那份是空单）",
                            "note": cached_note, "error": msg,
                            "coverage": coverages(cached, today),
                            "ok": today_ok(cached, today)}
        return Epg(), {**info, "note": note, "error": msg}

    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    except OSError as e:                      # 缓存写不进去不影响这一轮用这份节目单
        info["error"] = f"缓存没写成：{type(e).__name__}: {e}"
    return doc, {**info, "via": "联网", "note": note, "coverage": coverages(doc, today),
                 "ok": today_ok(doc, today), "refreshed": True}


PROBE_FILE = ROOT / "data" / "output" / "probe.json"


def load_probe(path: Path | str) -> tuple[dict[str, ProbeResult], dict]:
    """把上一轮 `--verify` 落盘的 probe.json 读回成「一份本轮实测结果」。

    为什么值得有这条路：probe.json 里躺着的是**逐条线路**的判决（350 条的
    `ok/http/ms/kind`），而 `aggregate()` 的删线路、延迟分档、录像降档吃的就是这个形状的东西。
    于是「换一行配置就想看到效果」不必再等一个干净出口 —— 那 350 条判决是家里联通测出来的，
    拿过来重出表，测的地方和当时一模一样。
    它**不是一次新的实测**，所以既不追加履历也不覆盖 probe.json（`replay_gate()` 会把这层意思说清楚）。

    返回 (结果表, 这一轮的来历 {at, egress, warnings, hosts})；文件坏掉/格式不对就抛，
    由调用方决定是报错还是当没这份记录。`hosts` 是那一轮的逐主机汇总 —— 一起带回来，
    报告里那张「逐主机可用性」表才不会在一次沿用记录的生成里凭空消失（它和判决同源，
    不是一次新的测量，所以表头会写明它是哪一轮的）。

    「格式不对」一律抛 `ValueError`，别把 `AttributeError` 漏到调用方那里去
    （现码就漏过：`lines` 的某一条不是字典 → `'str' object has no attribute 'get'`
    崩栈，而调用方 catch 的是 OSError/ValueError —— 2.36 实测）。
    **一条判决都没有要单独问一句**：那是另一类问题（这份记录没量过任何东西），
    所以留成空字典返回，由 `replay_gate()` 用人话拒绝，而不是在这里冒充「读不出来」。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "probe.json"
    ...     _ = p.write_text('{"at": "2026-09-21T21:18:13+08:00", "egress": "1.2.3.4 CN",'
    ...         ' "measurement_warnings": [], "hosts": [{"host": "a", "total": 2, "ok": 1}],'
    ...         ' "lines": {"http://a/1": {"ok": true, "ms": 120, "kind": "live"},'
    ...         '  "http://a/2": {"ok": false, "http": 404}}}', encoding="utf-8")
    ...     res, meta = load_probe(p)
    >>> [(u, r.ok, r.ms, r.http) for u, r in sorted(res.items())]
    [('http://a/1', True, 120, 0), ('http://a/2', False, 0, 404)]
    >>> meta["at"][:16], meta["egress"], meta["warnings"], meta["hosts"]
    ('2026-09-21T21:18', '1.2.3.4 CN', [], [{'host': 'a', 'total': 2, 'ok': 1}])
    >>> with tempfile.TemporaryDirectory() as d2:      # 某一条判决写成了字符串
    ...     p2 = Path(d2) / "bad.json"
    ...     _ = p2.write_text('{"at": "x", "lines": {"http://a/1": "不是字典"}}', encoding="utf-8")
    ...     try:
    ...         load_probe(p2)
    ...     except ValueError as e:
    ...         print(str(e).split(" 里 ")[1])   # 前半截是那个临时文件的路径
    1 条判决不是字典，例如 http://a/1 —— 本工具写的每一条都是 {"ok": …, "ms": …} 那种形状
    >>> with tempfile.TemporaryDirectory() as d3:      # lines 在，但一条判决都没有
    ...     p3 = Path(d3) / "empty.json"
    ...     _ = p3.write_text('{"at": "x", "lines": {}}', encoding="utf-8")
    ...     res3, _ = load_probe(p3)
    >>> len(res3)                                      # 读得出来，是空的 —— 交给 replay_gate 拒绝
    0
    """
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or "lines" not in doc:
        raise ValueError(f"{path} 里没有找到 lines 那一段（不是本工具写的 probe.json？）")
    lines = doc["lines"]
    if not isinstance(lines, dict):
        raise ValueError(f"{path} 里的 lines 不是「地址 → 判决」那种字典（是 "
                         f"{type(lines).__name__}），这一份不能当本轮实测结果用")
    bad = [u for u, v in lines.items() if not isinstance(v, dict)]
    if bad:
        raise ValueError(f"{path} 里 {len(bad)} 条判决不是字典，例如 {bad[0]} —— "
                         "本工具写的每一条都是 {\"ok\": …, \"ms\": …} 那种形状")
    results = {u: ProbeResult(bool(v.get("ok")), int(v.get("http") or 0), int(v.get("ms") or 0),
                              int(v.get("segments") or 0), str(v.get("error") or ""),
                              str(v.get("kind") or ""))
               for u, v in lines.items()}
    meta = {"at": str(doc.get("at") or ""), "egress": str(doc.get("egress") or ""),
            "warnings": [str(w) for w in (doc.get("measurement_warnings") or [])],
            "hosts": [dict(h) for h in (doc.get("hosts") or []) if isinstance(h, dict)]}
    return results, meta


def replay_gate(meta: dict, *, point: str, now: str, max_age_hours: int = 48,
                force: bool = False, n_lines: int | None = None) -> tuple[bool, str]:
    """这份记录能不能当本轮判决用，以及为什么不能（`point` 是本轮排序的参照出口）。

    三道门一道都不能省，因为它们各自对应一次真翻过的车：

      * **那一轮体检报过警** —— 2.16 那次是 TUN 开着跑的，73 条被假阴性判死。
        拿这样一份记录重出表，等于把已经关进 `untrusted/` 的错误又请回订阅目录，
        所以直接拒绝（`--allow-untrusted` 才能明知故犯）。
      * **它的出口不是本轮参照出口** —— 境外判的「连不上」对家里那张 Wi-Fi 不算数（2.8）。
        参照出口本身就是从履历里挑出来的可信出口，所以这一条也顺带挡住了「拿旧出口的记录顶新出口」。
      * **它太旧**（默认 48 小时） —— 沿用久了表会冻在旧世界上：上游换 IP、主机复活都看不见了。
        这条是刻意保守的：履历里的主机级判据没有时间闸，线路级这把要有。

    另外三格是 2.36 补的，都关于「那个时间/那份记录到底能不能算」：
    时间读不出、**只有一头带时区**（以前在这里 `TypeError` 崩栈）、**写着未来**（以前负数直接
    通过 48 小时那道闸），以及传了 `n_lines` 时问一句**里面到底有几条判决**。

    >>> ok, why = replay_gate({"at": "2026-09-21T21:18:13+08:00", "egress": "1.2.3.4 CN",
    ...                        "warnings": []}, point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")
    >>> ok, why
    (True, '')
    >>> replay_gate({"at": "2026-09-21T21:18:13+08:00", "egress": "9.9.9.9 JP",
    ...              "warnings": ["TUN 已开启"]}, point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")
    (False, '那一轮（21:18）体检报过警，它判死的线路多半是假阴性（2.16）：TUN 已开启')
    >>> replay_gate({"at": "2026-09-21T21:18:13+08:00", "egress": "9.9.9.9 JP",
    ...              "warnings": []}, point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")
    (False, '那一轮的出口是 9.9.9.9 JP，与本轮参照出口 1.2.3.4 CN 不是一个测量点')
    >>> replay_gate({"at": "2026-09-21T21:18:13+08:00", "egress": "1.2.3.4 CN",
    ...              "warnings": []}, point="1.2.3.4 CN", now="2026-09-24T08:00:00+08:00")
    (False, '那份记录已经 59 小时了（上限 48）——沿用太久表会冻在旧世界上，跑一轮 --verify 吧')
    >>> replay_gate({"at": "坏日期", "egress": "1.2.3.4 CN", "warnings": []},
    ...             point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")
    (False, '那份记录上读不出时间（at="坏日期"），不知道多旧就不用')

    少写时区（手改过、或者别的机器写的）—— 以前是崩栈：

    >>> replay_gate({"at": "2026-09-21T21:18:13", "egress": "1.2.3.4 CN", "warnings": []},
    ...             point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")[1].split("，")[0]
    '那份记录和本轮时刻有一边没带时区（at="2026-09-21T21:18:13"'
    >>> replay_gate({"at": "2026-09-21", "egress": "1.2.3.4 CN", "warnings": []},
    ...             point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")[0]
    False

    写着未来的记录：负数年龄过不了「太旧」那道闸，但它比「太旧」更值得单独问一句。
    差几十分钟的时钟抖动放过（`timespec="seconds"` 本身就有可能把它凑成微小负数）：

    >>> replay_gate({"at": "2026-09-22T18:00:00+08:00", "egress": "1.2.3.4 CN",
    ...              "warnings": []}, point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")
    (False, '那份记录写着未来（at="2026-09-22T18:00:00+08:00"，比本轮时刻还 10 小时）—— 这台机器的钟或时区不对，一份对不上表的时刻不能当本轮判决用')
    >>> replay_gate({"at": "2026-09-22T08:30:00+08:00", "egress": "1.2.3.4 CN",
    ...              "warnings": []}, point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00")[0]
    True

    几条判决这件事，`n_lines` 传进来才问（不传 = 不知道，就不拿它当理由）：

    >>> replay_gate({"at": "2026-09-21T21:18:13+08:00", "egress": "1.2.3.4 CN",
    ...              "warnings": []}, point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00",
    ...             n_lines=0)
    (False, '那份记录里一条逐条判决都没有（lines 是空的）—— 沿用它等于什么都不沿用，这一轮不会有线路被判死。要的就是这个效果就别传 --replay')
    >>> replay_gate({"at": "2026-09-21T21:18:13+08:00", "egress": "1.2.3.4 CN",
    ...              "warnings": []}, point="1.2.3.4 CN", now="2026-09-22T08:00:00+08:00",
    ...             n_lines=350)[0]
    True
    >>> replay_gate({"at": "2026-09-21T21:18:13+08:00", "egress": "9.9.9.9 JP",
    ...              "warnings": ["TUN"]}, point="1.2.3.4 CN", now="2026-09-24T08:00:00+08:00",
    ...             force=True)
    (True, '明知故犯：--allow-untrusted 越过了上面三道门')
    """
    if force:
        return True, "明知故犯：--allow-untrusted 越过了上面三道门"
    at = str(meta.get("at") or "")
    try:
        then, here = datetime.fromisoformat(at), datetime.fromisoformat(now)
    except ValueError:
        return False, f'那份记录上读不出时间（at="{at}"），不知道多旧就不用'
    if (then.tzinfo is None) != (here.tzinfo is None):
        # 一头带时区一头不带，减法本身就不合法（现码在这里抛 TypeError 崩栈，2.36 实测）。
        # **不猜**：猜它是本地时区还是 UTC，最坏差 8 小时 —— 而这把闸的整数值就是 48。
        return False, (f'那份记录和本轮时刻有一边没带时区（at="{at}"，now="{now}"），'
                       '减不出相差几小时。把那个时间补成 `…+08:00` 那种写法，'
                       '或者跑一轮真正的 --verify')
    age_h = (here - then).total_seconds() / 3600
    if age_h < -1:
        return False, (f'那份记录写着未来（at="{at}"，比本轮时刻还 {-age_h:.0f} 小时）—— '
                       '这台机器的钟或时区不对，一份对不上表的时刻不能当本轮判决用')
    if n_lines == 0:
        return False, ('那份记录里一条逐条判决都没有（lines 是空的）—— 沿用它等于什么都不沿用，'
                       '这一轮不会有线路被判死。要的就是这个效果就别传 --replay')
    warns = meta.get("warnings") or []
    if warns:
        return False, (f"那一轮（{at[11:16]}）体检报过警，它判死的线路多半是假阴性（2.16）："
                       f"{warns[0]}")
    egress = str(meta.get("egress") or "")
    if point and egress and egress.split()[:2] != point.split()[:2]:
        return False, f"那一轮的出口是 {egress}，与本轮参照出口 {point} 不是一个测量点"
    if age_h > max_age_hours:
        return False, (f"那份记录已经 {age_h:.0f} 小时了（上限 {max_age_hours}）"
                       "——沿用太久表会冻在旧世界上，跑一轮 --verify 吧")
    return True, ""


class UnreadableSource(RuntimeError):
    """一个上游整个读不到。

    和「读到了但里面有几行畸形」不是一类事，危害的**方向**也不同：
    畸形行丢的是几条线路，屏幕上会写「跳过 N 行」；这一类丢的是**一整个源**，
    而表上完全看不出区别 —— 少掉的那些频道看起来就像「本来就没有台」。
    2.32 那条老教训的另一个方向：不能量不到东西还报绿。
    所以这里选择**停下来**，而不是「剩下的源够用就接着出表」。
    """


def collect(sources: Iterable[dict | str]) -> tuple[list[Entry], list[str]]:
    """读所有上游并解析。读不到的那些一起点名（不读一个崩一个），全读不到也要停。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:                 # 一个正常读到的源
    ...     p = Path(d) / "a.m3u"
    ...     body = chr(10).join(['#EXTM3U', '#EXTINF:-1 tvg-id="h1",湖南卫视', 'http://a/1.m3u8'])
    ...     _ = p.write_text(body, encoding="utf-8")
    ...     got, urls = collect([str(p)])
      a.m3u（缓存）: 1 条（跳过 0 行畸形数据）
    >>> [e.name for e in got], urls
    (['湖南卫视'], [])
    >>> try:                                                     # 一个不存在的源：停下来点名
    ...     collect(["./does-not-exist.m3u"])
    ... except UnreadableSource as e:
    ...     print(f"停了：{str(e).splitlines()[0]}")
      does-not-exist.m3u: ⚠️ 读不到（No such file or directory）
    停了：1 个上游整个读不到（不是里面几行畸形，是这一路一条都没读到）：
    """
    entries: list[Entry] = []
    epg_urls: list[str] = []
    unreadable: list[str] = []
    for src in sources:
        if isinstance(src, str):
            src = {"id": src.rsplit("/", 1)[-1][:40], "target": src, "cache": None}
        tag = src["id"]
        try:
            text = fetch(src["target"])
        except OSError as e:
            # 先记下来，别在这里 return —— 一次跑要让人看见**所有**读不到的源，
            # 不然修一个撞一个，三次跑才知道配置里有三处写歪了。
            why = e.strerror or type(e).__name__
            unreadable.append(f"  {tag} ← {src['target']}：{why}")
            print(f"  {tag}: ⚠️ 读不到（{why}）")
            continue
        pl = parse_m3u(text, source=tag)
        entries.extend(pl.entries)
        if pl.x_tvg_url:
            epg_urls.append(pl.x_tvg_url)
        if src.get("cache") is not None and src["target"].startswith("http"):
            cache: Path = src["cache"]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        via = "缓存" if not src["target"].startswith("http") else "联网"
        print(f"  {tag}（{via}）: {len(pl)} 条（跳过 {pl.skipped} 行畸形数据）")
    if unreadable:
        raise UnreadableSource(
            f"{len(unreadable)} 个上游整个读不到（不是里面几行畸形，是这一路一条都没读到）：\n"
            + "\n".join(unreadable)
            + "\n  表少一整个源是**看不出来**的：那些台会安静地变成「本来就没有」。"
              "先确认路径（`--source` 要的是文件本身），或者把这一条从 "
              "config/sources.yaml 里注掉再来。")
    return entries, epg_urls


def aggregate(entries: list[Entry], index, max_lines: int, *,
              verify: bool = False, timeout: int = 12, workers: int = 20,
              max_per_host: int = 2, skip_verify: Iterable[str] = (),
              source_priority: dict[str, int] | None = None,
              reach: Reachability,
              stale_hosts: frozenset[str] = frozenset(),
              fake_hosts: frozenset[str] = frozenset(),
              rolls: dict[str, str] | None = None,
              hist_ms: dict[str, int] | None = None,
              preset: dict[str, ProbeResult] | None = None):
    """归位 + 合并多线路 + 同源收敛 + 排序 + 截断（可选实测过滤）。

    max_per_host 用来治「一个频道的 5 条线路其实全来自同一个失效主机」——
    实测湖南线路里 64% 来自 stream1.freetv.fun 这一个已不可用的域名。

    skip_verify 里的来源 id 是「开发机测不准」的运营商内网源，实测时原样保留。

    排序主键是可达范围，其次才是实测延迟、来源优先级和清晰度：APTV 默认只播第一条线路，
    所以「电视够不到的地址」必须让位给公网线路。上一版把来源优先级当主键，
    覆盖最全的 hn_unicom/hn_mobile 于是吃掉了 39/39 个湖南频道的第一顺位，
    真机观感就是整张表全超时。内网线路不删，只是排到后面当备选。

    延迟档是 2026-09-21 补的第二键。同一批公网线路里，美国机房中转（845~1271ms）
    和湖南广电官方公网流 hlsal-ldvt.qing.mgtv.com（210ms）当时是并列的，
    结果 max_lines=3 把那条最该留的官方流挤掉了 —— 只判「通不通」不够，
    还得让快的排前面，尤其是电视要拿它连续播几个小时。

    假直播（循环录像）在可达范围同一档内被压到真直播后面，见 prober.is_fake_live：
    实测到 txmov2.a.kwimgs.com 有条 1259 分片的录像挂在湖南卫视名下，
    它比真直播还快，只按延迟排会把录像顶到第一位。不删，是因为对只有录像和内网
    地址的台来说，有画可看比超时强；但这类频道会在使用报告里点名。

    stale_hosts / hist_ms 来自实测履历（data/output/probe-history.jsonl），都只影响
    本轮没测过的线路：前者把上一轮整族连不上的往后压，后者把上一轮量到过的主机按
    那时的延迟补进档位 —— 否则离线重出表时全部线路同为"未知"，
    上一轮确认 378ms 的湖南广电官方流会被来源优先级挤掉（见 effective_tier）。

    fake_hosts / rolls 是同一份履历里的「内容」判据（history.fake_hosts / merge_rolls）：
    前者是上一轮这个主机通了的线路全是循环录像，后者是 L3 逐条验过的「列表不动」。
    它们排在可达范围与「本轮实测是录像」之后、延迟档之前 ——
    录像通常比真直播快，只用延迟当第二键会被顶到第一位去。

    `preset` 是「本轮不实测，但把上一轮可信实测的**逐条**判决当本轮结果用」（`--replay`，
    见 `load_probe()` / `replay_gate()`）。它和 `verify` 只有一条区别：**它不产生新的测量**，
    所以既不写 `probe.json` 也不追加履历；相同的是删线、延迟分档、录像降档走的是同一套代码，
    所以「沿用记录重出的表」和「当场测出来的表」在口径上可以逐字节对得上（这正是它的验收方式）。
    没有记录的线路（那一轮之后上游新塞进来的）仍然按未知处理，不惩罚也不优待。
    """
    skip_verify = set(skip_verify)
    prio = source_priority or {}
    rolls = rolls or {}
    hist_ms = hist_ms or {}
    buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"lines": [], "seen": set(), "tvg_id": "", "logo": "", "order": 0, "group_title": ""}
    )
    unmatched: Counter[str] = Counter()
    excluded = 0
    private = 0

    for e in entries:
        if _AUTH_URL.search(e.url):
            private += 1
            continue                      # 鉴权私有流：换 IP 换时间必播不动
        res = index.resolve(e)
        if res is None:
            if index.is_excluded(e):
                excluded += 1
            else:
                unmatched[e.name] += 1
            continue

        bucket = buckets[(res.group, res.name)]
        if e.url in bucket["seen"]:
            continue                      # 同一频道的重复 url 没有意义
        bucket["seen"].add(e.url)
        bucket["lines"].append(e)
        bucket["tvg_id"] = bucket["tvg_id"] or res.tvg_id
        bucket["logo"] = bucket["logo"] or e.logo
        bucket["group_title"] = index.group_title(res.group)
        bucket["order"] = min(bucket["order"], res.order) if bucket["lines"][:-1] else res.order

    if private:
        print(f"\n剔除鉴权私有流 {private} 条（URL 里绑了别人的 IP 和时效，红线不收录）")

    results: dict[str, ProbeResult] = dict(preset) if preset else {}
    if verify:
        urls = sorted({e.url for b in buckets.values() for e in b["lines"]
                       if e.source not in skip_verify})
        print(f"\n实测 {len(urls)} 条线路（本机出口直连）...")
        results = dict(zip(urls, probe_many(urls, timeout, workers)))
        print(f"  可用 {sum(1 for r in results.values() if r.ok)}/{len(urls)}")
        # 分源统计：某些源（如湖南移动）只在对应运营商网络内可达，
        # 在开发机上全红不代表电视上不能用，必须分开看。
        stat: dict[str, Counter] = defaultdict(Counter)
        for b in buckets.values():
            for e in b["lines"]:
                stat[e.source]["all"] += 1
                r = results.get(e.url)
                if r is not None and r.ok:
                    stat[e.source]["ok"] += 1
        for src, c in stat.items():
            tag = "跳过实测（运营商内网源）" if src in skip_verify else f"可用 {c['ok']}/{c['all']}"
            print(f"    {src}: {tag}")
    elif results:
        # 沿用上一轮的逐条判决：说清楚「哪几条真有记录」，剩下的按未知处理。
        # 这句话不能省 —— 少了它，屏幕上看到的「可用 n/m」就变成了一次没发生过的测量。
        urls = sorted({e.url for b in buckets.values() for e in b["lines"]
                       if e.source not in skip_verify})
        hit = [u for u in urls if u in results]
        print(f"\n本轮不实测：沿用上一轮的逐条判决 —— 候选 {len(urls)} 条里 "
              f"{len(hit)} 条有记录（可用 {sum(1 for u in hit if results[u].ok)} 条），"
              f"其余 {len(urls) - len(hit)} 条按未知处理")

    dead = 0
    stale_hits = 0
    channels: list[OutputChannel] = []
    for (group, name), b in buckets.items():
        ordered = sorted(
            b["lines"],
            key=lambda e: (reach.rank(e.url),
                           history_strike(e.url, results.get(e.url), stale_hosts),
                           is_fake_live(results.get(e.url)),
                           roll_strike(e.url, results.get(e.url), rolls),
                           fake_strike(e.url, results.get(e.url), fake_hosts),
                           effective_tier(e.url, results.get(e.url), hist_ms),
                           prio.get(e.source, 99),
                           -_RANK.get(quality_hint(f"{e.name} {e.url}"), 0),
                           e.seq),
        )
        host_used: Counter[str] = Counter()
        kept: list[Entry] = []
        for e in ordered:
            if len(kept) >= max_lines:
                break
            r = results.get(e.url)
            if r is not None and not r.ok:
                dead += 1
                continue
            host = urlsplit(e.url).hostname or e.url[:16]
            if host_used[host] >= max_per_host:
                continue                  # 同源收敛；这不是失效，不计入 dead
            host_used[host] += 1
            kept.append(e)
        if not kept:
            continue
        if history_strike(kept[0].url, results.get(kept[0].url), stale_hosts):
            stale_hits += 1        # 这个台实在没有更好的选择了，第一线还是那台已死的

        channels.append(
            OutputChannel(
                name=name,
                group_title=b["group_title"],
                tvg_id=b["tvg_id"],
                logo=b["logo"],
                urls=[e.url for e in kept],
                order=(index.groups[group]["order"], b["order"]),
            )
        )

    channels.sort(key=lambda c: c.order)
    return channels, unmatched, excluded, dead, results, stale_hits


def host_summary(results: dict[str, ProbeResult], reach: Reachability,
                 src_of: dict[str, list[str]] | None = None) -> list[dict]:
    """把逐条实测按主机汇总：回答「哪个主机族在家里这张网里是死的、哪些是活的但放的是录像」。

    这一步是实测真正的产出。只报「可用 215/330」没法定下一步 ——
    2026-09-21 那次汇总才看清：美国中转族 128/131 全活，
    而 stream1.freetv.fun 0/17 整族失效（DNS 已被换到一个不服务的美图 IP），
    于是不用电视实测就能断定「湖南经视等台的公网线路其实不存在」。

    `vod` 那一列是同一件事的第二半：连着且有分片、内容却是循环录像的条数。
    它决定的是「离线重出表时这个主机还能不能占第一线」，见 history.fake_hosts。

    `src_of` 是 2.17 加的第三半：**这一族是谁塞进来的**。没有它，报告说得出
    「`stream1.freetv.fun` 0/36 整族失效」却说不出该动 `sources.yaml` 里哪一行。
    一台主机可以挂在多个源下（聚合源之间互相抄），所以是个列表，原样存进履历。

    返回按（可达范围、失效数倒序）排好的行：host/scope/total/ok/best_ms/vod/srcs。

    >>> r = Reachability([".dead.example"])
    >>> res = {"http://a.example/1.m3u8": ProbeResult(True, 200, 100, 3, "", "live"),
    ...        "http://a.example/2.m3u8": ProbeResult(True, 200, 120, 900, "", "vod"),
    ...        "http://dead.example/x.m3u8": ProbeResult(False, 0, 5000, 0, "timeout")}
    >>> for row in host_summary(res, r):
    ...     print(row["host"], row["scope"], f"{row['ok']}/{row['total']}", row["vod"], row["srcs"])
    a.example public 2/2 1 []
    dead.example iptv_intranet 0/1 0 []
    >>> rows = host_summary(res, r, {"http://a.example/1.m3u8": ["gd"],
    ...                              "http://dead.example/x.m3u8": ["gd", "local"]})
    >>> [(x["host"], x["srcs"]) for x in rows]      # 同一主机的来源去重后按名字排
    [('a.example', ['gd']), ('dead.example', ['gd', 'local'])]
    """
    agg: dict[str, dict] = {}
    src_of = src_of or {}
    for url, r in results.items():
        host = urlsplit(url).hostname or url[:16]
        a = agg.setdefault(host, {"host": host, "scope": reach.scope(url),
                                  "total": 0, "ok": 0, "best_ms": 0, "vod": 0, "srcs": set()})
        a["srcs"] |= set(src_of.get(url) or [])
        a["total"] += 1
        if r.ok:
            a["ok"] += 1
            a["best_ms"] = r.ms if not a["best_ms"] else min(a["best_ms"], r.ms)
            if is_fake_live(r):
                a["vod"] += 1
    for a in agg.values():
        a["srcs"] = sorted(a["srcs"])
    return sorted(agg.values(),
                  key=lambda a: (RANK[a["scope"]], -a["total"], a["host"]))


def first_line_focus(channels: list[OutputChannel], results: dict[str, ProbeResult],
                     src_of: dict[str, list[str]] | None,
                     reach: Reachability | None) -> list[dict]:
    """按「第一线主机」把一张表摊开：一个主机挂着几个台，其中几个台连备选都没有。

    为什么单独量这一件事：上面两张表都只说「哪条线路通了」，没人说过**这些第一线落在几家主机上**。
    2026-09-21 那张表是手工数出来的（计划书 2.22），因为「真机点开哪个台最值」这个问题
    答不了 —— 一个台通了不代表它的邻居也通，一个台死了却很可能带走一片。这里把它变成算出来的。

    `results` 是逐条判决（本轮实测或 `--replay` 沿用来的）。**空 dict 时 `unmeasured` 全是 0**，
    意思是「没有任何判决可依据」，不是「全都测过」，也不是「全都测过所以安全」：
    纯离线生成没有逐条记录，那一栏本来就说不准，宁可不写。
    `src_of` / `reach` 可以给 `None` —— 只想问「哪家挂着几个台」的调用方（试播包 `scripts/probe_pack.py`）
    不需要来源和可达范围，那两个字段就留空，而不是拿默认值糊一个出来。

    返回按（第一线台数倒序、主机名）排好的行：
    host/scope/channels/alone/unmeasured/alt_lines/sources/examples。

    >>> from src.output.writer import OutputChannel
    >>> reach = Reachability([".chinamobile.com"])
    >>> ch = [OutputChannel("湖南经视", "📍 湖南", "", "",
    ...                     ["http://a.chinamobile.com/1", "http://b.example/2"]),
    ...       OutputChannel("娄底新闻", "📍 市州", "", "", ["http://a.chinamobile.com/3"]),
    ...       OutputChannel("湘潭新闻", "📍 市州", "", "", ["http://c.example/4"])]
    >>> src = {"http://a.chinamobile.com/1": ["hn_mobile"], "http://a.chinamobile.com/3": ["hn_mobile"],
    ...        "http://c.example/4": ["iptv_api_gd"]}
    >>> rows = first_line_focus(ch, {}, src, reach)
    >>> for r in rows:
    ...     print(r["host"], r["scope"], r["channels"], r["alone"], r["unmeasured"],
    ...           r["alt_lines"], r["sources"], r["examples"])
    a.chinamobile.com iptv_intranet 2 1 0 1 ['hn_mobile'] ['湖南经视', '娄底新闻']
    c.example public 1 1 0 0 ['iptv_api_gd'] ['湘潭新闻']
    >>> res = {"http://c.example/4": ProbeResult(True, 200, 90, 3, "", "live"),
    ...        "http://a.chinamobile.com/1": ProbeResult(True, 200, 80, 3, "", "live")}
    >>> [r["unmeasured"] for r in first_line_focus(ch, res, src, reach)]
    [1, 0]
    >>> # 「备选线路 0 条」＝换机位也换不出去，跟通不通无关：所以它和上面那列各管一头
    >>> [r["alone"] for r in first_line_focus(ch, res, src, reach)]
    [1, 1]
    >>> [(r["host"], r["scope"], r["sources"]) for r in first_line_focus(ch, {}, None, None)]
    [('a.chinamobile.com', '', []), ('c.example', '', [])]
    """
    host_of = lambda u: urlsplit(u).hostname or u[:16]
    src_of = src_of or {}
    agg: dict[str, dict] = {}
    for c in channels:
        if not c.urls:
            continue
        first = c.urls[0]
        host = host_of(first)
        a = agg.setdefault(host, {"host": host, "scope": reach.scope(first) if reach else "",
                                  "channels": 0, "alone": 0, "unmeasured": 0, "alt_lines": 0,
                                  "sources": set(), "examples": []})
        a["channels"] += 1
        a["sources"] |= set(src_of.get(first) or [])
        if len(a["examples"]) < 3:
            a["examples"].append(c.name)
        # 备选：这个台的线路里，落在**别的主机**上的那些条。一条都没有 = 换机位也换不出去。
        alts = [u for u in c.urls if host_of(u) != host]
        a["alt_lines"] += len(alts)
        if not alts:
            a["alone"] += 1
        if results and first not in results:
            a["unmeasured"] += 1
    for a in agg.values():
        a["sources"] = sorted(a["sources"])
    return sorted(agg.values(), key=lambda a: (-a["channels"], a["host"]))


SCOPE_WORD = {"iptv_intranet": "IPTV 专网", "audio_only": "纯音频电台"}


def weak_first_line(url: str, results: dict, reach: Reachability | None) -> str:
    """这条第一线值不值得替它担心，返回一个短标签；不担心返回空串。

    两种「可疑」：**专网地址**（家里 Wi-Fi 上必然播不动，计划书 2.8 真机验过），
    和**这一轮压根没有逐条判决**的地址（`probe: false` 的手工源就是这种，电脑从没测过它）。
    没有逐条判决时既不能说「全都测过」，也不能反过来把每条都算成没测过：
    所以 `results` 为空时只按专网判，少判的那一层由调用方声明（见 `report.md` 那一节）。

    >>> from src.check.scope import Reachability
    >>> r = Reachability([".chinamobile.com"])
    >>> weak_first_line("http://a.chinamobile.com/1", {}, r)
    '专网'
    >>> weak_first_line("http://a.example/1", {"http://a.example/1": None}, r)
    ''
    >>> weak_first_line("http://a.example/1", {"http://b/2": None}, r)
    '没测过'
    >>> weak_first_line("http://a.example/1", {}, r)          # 一份判决都没有 → 不下「没测过」的结论
    ''
    >>> weak_first_line("http://a.example/1", {"http://b/2": None}, None)   # 没给 reach 就不判专网
    '没测过'
    >>> weak_first_line("", {}, r)                            # 连第一线都没有的台
    ''
    """
    if not url:
        return ""
    if reach is not None and reach.scope(url) == "iptv_intranet":
        return "专网"
    if results and url not in results:
        return "没测过"
    return ""


def second_line_options(channels: list[OutputChannel], results: dict,
                        reach: Reachability | None) -> dict:
    """第一线可疑的那些台，**点第 2 条线路救得回来吗** —— 按换过去落在哪里分五类。

    为什么要有这一层：报告和验收单里长期写着「这个台不动就点第二条线」，
    而 2026-09-21 那轮真机上湖南那批台整表超时（计划书 2.8）。这两件事同时对，
    就说明「有第二条线」不等于「换得出去」，得把换过去的落点分类算出来。
    2026-09-22 第一次量（计划书 2.25）：39 个可疑的台里 24 个压根没有备选、1 个备选在同一家机房、
    14 个从湖南联通专网出口换到湖南移动专网门户，**换得到公网电视线路的 0 个** ——
    把表加宽到每台 6 条线路再算还是 0（多出来那条是蜻蜓 FM 电台）。
    所以这句话现在写在报告里，不用再靠人记。

    三个判据各自会读反的地方：
    - 同一家机房算「换了等于没换」：比的是去端口的主机名，`tvgslb:8089` → `tvgslb:9901` 还在那台机器上。
    - **电台不算救回来**：`audio_only` 那批主机电脑实测能通、有声音，但那是电台冒充的电视位，
      换过去没画面，所以单列一类、不进 `switchable`。
    - 「换到别家是不是专网/电台」得靠 `reach` 判，没给配置就落进 `other_unknown`
      且 `scope_known=False`，让渲染那一层改口，不硬下「没有救法」的结论。

    >>> from src.check.scope import Reachability
    >>> def C(name, *urls):
    ...     return OutputChannel(name, "", "", "", list(urls))
    >>> r = Reachability([".example"])
    >>> g = [C("台一", "http://i.example/1"),
    ...      C("台二", "http://i.example/2", "http://i.example:9901/3"),
    ...      C("台三", "http://i.example/4", "http://pub/5"),
    ...      C("台四", "http://ok/6", "http://pub/7")]
    >>> s = second_line_options(g, {}, r)
    >>> (s["channels"], s["no_alt"], s["same_host"], s["other_public"], s["switchable"])
    (3, 1, 1, 1, ['台三'])
    >>> s["reasons"], s["lands"], s["scope_known"]
    ({'专网': 3}, [], True)
    >>> # 换过去那一家按**台**数、不按线路数，并记下它是专网还是电台
    >>> s2 = second_line_options([C("台一", "http://i.example/1", "http://k.example/2",
    ...                             "http://k.example:8080/3")], {}, r)
    >>> (s2["other_intranet"], s2["lands"], s2["land_kind"])
    (1, [('k.example', 1)], {'k.example': 'IPTV 专网'})
    >>> s3 = second_line_options([C("台一", "http://i.example/1", "http://ls.qingting.fm/2")],
    ...                          {}, Reachability([".example"], [".qingting.fm"]))
    >>> (s3["other_audio"], s3["other_public"], s3["switchable"])
    (1, 0, [])
    >>> # 没有逐条判决时不下「没测过」的结论（`weak_first_line`），只剩下专网那一层
    >>> second_line_options(g, {}, r)["channels"] == second_line_options(g, {"http://ok/6": None}, r)["channels"]
    True
    >>> s4 = second_line_options(g, {"http://ok/6": None}, None)      # 没给 reach：换到别家的判不了
    >>> (s4["channels"], s4["no_alt"], s4["same_host"], s4["other_unknown"], s4["scope_known"])
    (3, 1, 1, 1, False)
    """
    out = {"channels": 0, "no_alt": 0, "same_host": 0, "other_intranet": 0, "other_audio": 0,
           "other_public": 0, "other_unknown": 0, "reasons": {}, "switchable": [],
           "lands": {}, "land_kind": {}, "scope_known": reach is not None}
    host_of = lambda u: urlsplit(u).hostname or u[:16]
    for c in channels:
        urls = c.urls
        if not urls:
            continue
        why = weak_first_line(urls[0], results, reach)
        if not why:
            continue
        out["channels"] += 1
        out["reasons"][why] = out["reasons"].get(why, 0) + 1
        base = host_of(urls[0])
        alts: dict[str, str] = {}          # 备选按主机名收：同一主机多条线路算一个台
        for u in urls[1:]:
            alts.setdefault(host_of(u), reach.scope(u) if reach else "")
        others = {b: s for b, s in alts.items() if b != base}
        if not alts:
            out["no_alt"] += 1
            continue
        if not others:
            out["same_host"] += 1          # 有备选，但全在挂第一线的那一家上
            continue
        if reach is None:
            out["other_unknown"] += 1
            continue
        scopes = set(others.values())
        bucket = ("other_public" if scopes - {"iptv_intranet", "audio_only"}
                  else "other_audio" if "audio_only" in scopes else "other_intranet")
        out[bucket] += 1
        if bucket == "other_public":
            out["switchable"].append(c.name)
        else:
            want = "iptv_intranet" if bucket == "other_intranet" else "audio_only"
            for b, s in others.items():
                if s == want:
                    out["lands"][b] = out["lands"].get(b, 0) + 1
                    out["land_kind"][b] = SCOPE_WORD.get(s, s)
    out["lands"] = sorted(out["lands"].items(), key=lambda kv: (-kv[1], kv[0]))
    return out


def load_lean_fn():
    """取 scripts/lean_playlist.lean()：裸订阅表的生成逻辑只保留一份实现。

    scripts/ 不是包，所以按文件路径加载；文件不在就返回 None，
    主流程照常出 aptv.m3u / hunan.m3u，不因诊断用的附属文件而失败。

    加载前先把 `scripts/` 那一格插进 `sys.path`：那一份文件开头要向同一格里的邻居要门口
    那几样（§2.69 立的「一旗一个写法」），而那个邻居**只有把 `scripts/` 当搜索路径
    才找得着**。以前只有「把本件当脚本跑」那一头有这一级（`__main__` 收尾插的），
    **同一个进程里 import 起来调 `main()` 的人**没有 —— 于是 `build` 一路走到出表前一步，
    由 `cmd_build` 在这里裸抛 `ModuleNotFoundError`（§2.85 那遍 A/B 的对照辛抓到，
    那一遍沙盒种好了、源也读进来了，屏幕停在「节目单：未启用」之后一句没有）。
    同一种「换一棵树要先把它那一格插进去」的药 `run_doctests.host` 已经立过（§2.75），
    这里照同一味，不重抄那份道理。

    >>> import sys
    >>> saved = [p for p in sys.path if p.endswith("/scripts")]     # 假装是「import 起来调」的那个人
    >>> for p in saved:
    ...     sys.path.remove(p)
    >>> try:
    ...     got = load_lean_fn()
    ... except ModuleNotFoundError as e:
    ...     got = f"★在这儿裸崩了：{e}"
    ... finally:
    ...     sys.path[:0] = saved
    >>> callable(got)
    True
    """
    slot = str(ROOT / "scripts")
    if slot not in sys.path:            # 只插一次；已经在就不动（别人的顺序比我的偏好要紧）
        sys.path.insert(0, slot)
    path = ROOT / "scripts" / "lean_playlist.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("lean_playlist", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.lean


def build_arg_problems(max_lines: int, max_per_host: int, timeout: int,
                       workers: int, *, verifying: bool,
                       try_reach: str = "", out_is_default: bool = False) -> list[str]:
    """那几个数字取到「什么都能干掉」的值时，先说清楚再去碰网络和磁盘。

    2.37 实测：`--max-lines 0`（手一抖把 10 打成 0）走完整条 `build` 是
    **退 0、无警告、四张表各自剩下一行表头**（453 行的 aptv.m3u 变成 127 字节），
    `--max-per-host 0`、`--max-lines -1` 一样。`--workers 0` 在 `--verify` 那一支
    是 `ValueError: max_workers must be greater than 0` 崩栈；`--timeout 0` 更阴 ——
    它不崩，它把每一条线路都判成超时，于是那一轮既写进 `probe.json` 也追加进履历，
    接下来几轮离线生成都照着一份「全军覆没」的记录降档。
    合成一份全死的记录跑 `--replay` 能复现这条后果：349 条被判死、
    公网线路归零，退码还是 0（本轮实测过的那 350 条全灭，其余没记录的按未知保留）。

    数字只在它管得着的地方管：`--timeout` / `--workers` 只有实测那一支会用到，
    离线重出表时它们根本没参与，所以不拦（拦了反而挡住「先离线试试配置」这条路）。

    `--try-reach`（2.53 的试算）走的是同一道闸，因为它是同一种坏法：**拿一份没打算
    用上的规则，出张表，盖在订阅目录上**。候选规则出的表跟真表差多少，屏幕上不会说
    （挪得巧时两遍逐字节相同，谁也不知道这一轮到底比的是哪份配置），而它退 0 时无声无息。
    所以这一条只认「换个 `--out`」，不给 `--allow-untrusted` 那种明知故犯的口子 ——
    那个 flag 管的是「判决可不可信」，这里管的是「这张表是不是拿来播的」，两回事。

    >>> build_arg_problems(3, 2, 12, 20, verifying=True)
    []
    >>> build_arg_problems(0, 2, 12, 20, verifying=False)
    ['--max-lines 是 0：每个频道保留 0 条线路，等于一张空表。要试配置就换个 --out，别拿订阅目录试']
    >>> build_arg_problems(3, -1, 12, 20, verifying=False)
    ['--max-per-host 是 -1：同一主机允许 -1 条，没有任何一条线路留得下来']
    >>> build_arg_problems(3, 2, 0, 0, verifying=False)      # 不实测就不管这两个
    []
    >>> print(*build_arg_problems(3, 2, 0, 0, verifying=True), sep="\\n")
    --timeout 是 0：每条线路都会被判成超时，那一轮记录等于「全军覆没」，别把它写进履历
    --workers 是 0：线程池开不出来（实测那一支会直接 ValueError 崩）
    >>> build_arg_problems(3, 2, 12, 20, verifying=False,
    ...                    try_reach="/tmp/候选.yaml", out_is_default=True)
    ['--try-reach 换的是范围规则，出来的那张表也跟着变：这种表不许盖掉 data/output/ 里那张能播的。加一个 --out /tmp/试算 再跑']
    >>> build_arg_problems(3, 2, 12, 20, verifying=False,
    ...                    try_reach="/tmp/候选.yaml", out_is_default=False)     # 换个目录就放行
    []
    >>> build_arg_problems(3, 2, 12, 20, verifying=False, out_is_default=True)   # 没试算就不关这件事
    []
    """
    bad: list[str] = []
    if max_lines < 1:
        bad.append(f"--max-lines 是 {max_lines}：每个频道保留 {max_lines} 条线路，等于一张空表。"
                   f"要试配置就换个 --out，别拿订阅目录试")
    if max_per_host < 1:
        bad.append(f"--max-per-host 是 {max_per_host}：同一主机允许 {max_per_host} 条，"
                   f"没有任何一条线路留得下来")
    if verifying:
        if timeout < 1:
            bad.append(f"--timeout 是 {timeout}：每条线路都会被判成超时，"
                       f"那一轮记录等于「全军覆没」，别把它写进履历")
        if workers < 1:
            bad.append(f"--workers 是 {workers}：线程池开不出来（实测那一支会直接 ValueError 崩）")
    if try_reach and out_is_default:
        bad.append("--try-reach 换的是范围规则，出来的那张表也跟着变：这种表不许盖掉 "
                   "data/output/ 里那张能播的。加一个 --out /tmp/试算 再跑")
    return bad


def history_record_note(new_run: bool, cleared: list[str]) -> str:
    """履历记完之后那句「新起一轮 / 合并了、顺带清掉了什么」。

    单独抽出来是因为 `--verify` 那一支要联网测两百多秒，而这句话是该不是该说、
    说得对不对，跟联网没关系 —— 钉在这儿就能离线验，不用等一个干净出口。

    2.37 量到的形状：`build --verify` 判成同一轮时是**整行替换**（2.15 的规矩：
    换了时刻的观测要重新验），而那一行里可能带着 `scripts/verify_lines.py` 回填的
    `rolls`（L3 每条要等一个间隔）和 `scripts/backfill_srcs.py` 补的出处备注。
    原来 stdout 只有「与上一轮同一时段，已合并（上一行里本轮没测的字段留着）」——
    那句话是**错的**：字段没留着，被整行换掉了；`rolls` 要再等一个干净出口才回得来。

    >>> history_record_note(True, [])
    '新起一轮'
    >>> history_record_note(False, ["rolls 2 条 L3 结论", "srcs_note"])
    '与上一轮同一时段，已合并，顺带清掉上一行的 rolls 2 条 L3 结论、srcs_note'
    >>> history_record_note(False, [])          # 上一行本来就没有旁路补记
    '与上一轮同一时段，已合并'
    """
    if new_run:
        return "新起一轮"
    return ("与上一轮同一时段，已合并"
            + (f"，顺带清掉上一行的 {'、'.join(cleared)}" if cleared else ""))


def stop_message(what: str, path, reason: str, extra: str) -> str:
    """「这一份配置读不了」那两行怎么拼 —— 路径只说一遍。

    键名守卫（src/keys.py）那些整句开头本来就带着文件名：警告是直接打在终端上的，
    不说清是哪一份就得让人回头猜。可同一句被 `stop_config` 接住时，它前面又印了一遍
    `⚠️ 源清单 <路径> 读不了：` —— 于是 2.39 装完闸第一次实测，屏幕上那条绝对路径出现了两次，
    真正把要改的那一行顶到了行尾。这里剥掉开头那截相同的。

    >>> stop_message("源清单", "config/sources.yaml", "第 1 条缺 url", "少一个源看不出来")
    '⚠️ 源清单 config/sources.yaml 读不了：第 1 条缺 url\\n   这一轮不出表 —— 少一个源看不出来'
    >>> print(stop_message("源清单", "/tmp/a.yaml",
    ...                    "/tmp/a.yaml 第 2 条源：`enable` 我们不读", "x"))
    ⚠️ 源清单 /tmp/a.yaml 读不了：第 2 条源：`enable` 我们不读
       这一轮不出表 —— x
    >>> stop_message("范围规则", "r.yaml", "r.yaml: 这档规则没了", "x")   # 紧跟冒号的也剥
    '⚠️ 范围规则 r.yaml 读不了：这档规则没了\\n   这一轮不出表 —— x'
    """
    p = str(path)
    if reason.startswith(p):
        reason = reason[len(p):].lstrip("： :")
    return (f"⚠️ {what} {p} 读不了：{reason}\n"
            f"   这一轮不出表 —— {extra}")


def stop_config(what: str, path, e: Exception, extra: str) -> int:
    """配置读不了 / 键名写歪时那句同样的人话，四份配置共用一套说法。

    为什么要有这一层：这几处停下来的理由完全一样 —— 带着坏配置出表，缺的东西**在表上
    看不出来**（少一个源、少一档范围、少一条手工线路，都只是「本来就没有」）。
    写四遍就会漂四遍，漂掉的那一句正好是让人知道该改哪一行。

    只印 `Exception` 的第一行：YAML 的报错自带一段缩进提示，全塞进来会把「先修配置」
    那句顶出屏幕。怎么拼那两行见 `stop_message`。

    >>> stop_config("源清单", "config/sources.yaml", ValueError("第 1 条缺 url"), "少一个源看不出来")
    1
    """
    reason = (str(e).strip().splitlines() or [type(e).__name__])[0]
    print(stop_message(what, path, reason, extra), file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    """`build` 那一条命令的参数表。单独成一个函数，是为了让**别人也能拿它解析同一行命令**。

    2.45 的起因就是这件事没人能做：`scripts/check_doc_cmds.py` 想知道「文档里这行今天照抄会退几」，
    只能自己写正则去猜 `--replay` 读的是哪份记录、上限是多少 —— 而 `--replay` 是
    `nargs="?"`：`--replay --out /tmp/x` 里 `--out` **不是**它的取值（下一个 token 以 `-` 开头，
    argparse 用 `const`），写正则的人十次里有八次会把 `--out` 当成记录路径。
    那一晚我第一次量这件事就错了两次，所以这里把解析交给 argparse，不交给正则。

    >>> ap = build_parser()
    >>> ap.parse_args(["--replay"]).replay == str(PROBE_FILE)
    True
    >>> ap.parse_args(["--replay", "--out", "/tmp/x"]).replay == str(PROBE_FILE)   # --out 不是它的值
    True
    >>> ap.parse_args(["--replay", "data/output/untrusted/probe.json"]).replay
    'data/output/untrusted/probe.json'
    >>> ap.parse_args(["--replay"]).replay_max_age, ap.parse_args([]).replay_max_age
    (48, 48)
    >>> ap.parse_args(["--replay", "--replay-max-age", "6"]).replay_max_age   # 同一条命令里给它换上限
    6
    >>> ap.parse_args([]).replay      # 不带 --replay：空串，不是 None —— 闸只看这个
    ''
    >>> ap.parse_args([]).no_egress_check, ap.parse_args(["--no-egress-check"]).no_egress_check
    (False, True)
    >>> egress_of(ap.parse_args([]).no_egress_check, "1.2.3.4 CN")   # 不递那一旗：照旧印问到的
    '1.2.3.4 CN'
    """
    ap = argparse.ArgumentParser(prog="src.cli build", description="生成 APTV 订阅列表")
    ap.add_argument("--source", action="append", dest="sources",
                    help="临时指定上游（URL 或本地文件），可重复；给了它就忽略 sources.yaml")
    ap.add_argument("--sources-file", default=str(SOURCES_FILE))
    ap.add_argument("--config", default=str(ROOT / "config" / "channels.yaml"))
    ap.add_argument("--try-reach", metavar="PATH", default="",
                    help="拿另一份范围规则**试算**：这一条挪个位置、删掉，那张表会怎么变（计划书 2.53）。"
                         "config/ 一个字都不改，且必须另给一个 --out —— 候选规则出的表不许盖掉"
                         "订阅目录里那张能播的表")
    ap.add_argument("--out", default=str(ROOT / "data" / "output"))
    ap.add_argument("--max-lines", type=int, default=3, help="每个频道最多保留几条线路")
    ap.add_argument("--max-per-host", type=int, default=2, help="同一频道内同一主机最多几条")
    ap.add_argument("--verify", action="store_true", help="生成前实测每条线路，剔除失效")
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--fresh", action="store_true", help="强制联网抓最新上游，忽略本地缓存")
    ap.add_argument("--skip-local", action="store_true",
                    help="不读 config/sources_local.yaml（排查手工源本身时用）")
    ap.add_argument("--history", default=str(HISTORY_FILE),
                    help="实测履历 jsonl：离线生成时靠它给已知失效主机降档、给已知快的主机补位"
                         "（默认 data/output/probe-history.jsonl）。"
                         "只影响这一份；规则履历（2.51 的 rule-history.jsonl）跟着 --out 走，"
                         "因为它跟着那一轮的产物一起挪")
    ap.add_argument("--ignore-history", action="store_true",
                    help="完全不看履历，只按本轮（或无本轮）的结果排 —— 复现旧行为、排查降档本身时用")
    ap.add_argument("--merge-minutes", type=int, default=hist.MERGE_WINDOW_MIN, metavar="分钟",
                    help="两轮实测隔得比这个数近，就算同一次跑：合并成履历里的一行，"
                         "而不是两行（默认 30）。0 = 每跑一次算一轮，谁也不顶掉谁 —— "
                         "隔一会儿补跑一次 L3、不想让上一行被整行换掉的时候用它")
    ap.add_argument("--allow-untrusted", action="store_true",
                    help="明知故犯：体检报警也照旧覆盖 data/output/（默认会把产物关进 untrusted/）")
    ap.add_argument("--replay", nargs="?", const=str(PROBE_FILE), default="",
                    help="本轮不实测，把上一轮可信实测的逐条判决当本轮结果用"
                         "（默认 data/output/probe.json）：于是换配置、换节目单都能重出那张实测表，"
                         "不必等一个干净出口。既不写 probe.json 也不追加履历")
    ap.add_argument("--replay-max-age", type=int, default=48, metavar="小时",
                    help="那份记录最多能旧到多少小时（默认 48）；超了就直接拒绝")
    ap.add_argument("--epg-file", default=str(EPG_FILE),
                    help="节目单配置（默认 config/epg.yaml：里面那条地址会写进订阅表头部，"
                         "节目单本身优先从它的 cache 读，缓存里没有今天才联网）")
    ap.add_argument("--no-epg", action="store_true",
                    help="完全不读节目单：不改任何 tvg-id，头部地址回到「抄上游第一条」的老行为")
    ap.add_argument("--no-egress-check", action="store_true", dest="no_egress_check",
                    help="本轮不去问本机出口是谁（默认每跑一次 build 都要花一趟 HTTPS 问 "
                         "ipinfo.io，连 --no-epg 也算这一趟）。离线重出、拿假源试表时用它，"
                         "那一轮就一次网也不出；屏幕上「本机当前出口」那一句会明说「没问」。"
                         "别拿它配 --verify：体检靠的就是知道出口在不在家里那张网上")
    return ap


def cmd_build(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    # 这两个是互相矛盾的两种「本轮的线路判决从哪来」，在碰网络之前先拦掉：
    # 再往下每一步（读上游、取节目单）都要花时间，而这个组合根本给不出答案。
    if args.verify and args.replay:
        print("--verify 与 --replay 只能选一个：前者是当场测，后者是沿用记录", file=sys.stderr)
        return 1
    # 数字取歪了要在这里说，不能等到写盘那一刻：`--max-lines 0` 以前能把
    # data/output/ 四张表各自盖成一行表头，然后退 0（见 build_arg_problems）。
    # `--try-reach` 那份表是不是「拿来播的」也在这里问：判据是 `--out` 有没有离开默认目录。
    problems = build_arg_problems(args.max_lines, args.max_per_host, args.timeout,
                                  args.workers, verifying=bool(args.verify),
                                  try_reach=args.try_reach,
                                  out_is_default=Path(args.out) == Path(str(ROOT / "data" / "output")))
    if problems:
        for p in problems:
            print(f"⚠️ {p}", file=sys.stderr)
        print("   这一轮不出表。", file=sys.stderr)
        return 1
    # `--out` 指到一个普通文件上，以前是算完整张表、走到 mkdir 才崩一句
    # FileExistsError（16 行崩栈，2.37 实测）—— 早问一句就好。
    out_hint = Path(args.out)
    if out_hint.exists() and not out_hint.is_dir():
        print(f"⚠️ --out {out_hint} 是一个文件，不是放产物的目录。\n"
              f"   这一轮不出表 —— 换个目录，或者先把那个文件挪走", file=sys.stderr)
        return 1
    # 试算那份候选文件根本不存在时，要在读上游之前说：否则先白跑一遍缓存/网络，
    # 最后才告诉你路径打错了（`--config` 那份的账早在 2.37 就还过，这一条是同一格）。
    if args.try_reach and not Path(args.try_reach).is_file():
        print(f"⚠️ --try-reach {args.try_reach} 不是一份读得进来的文件（要它存在、是普通文件）。\n"
              f"   这一轮不出表；config/reachability.yaml 一个字都没动。", file=sys.stderr)
        return 1

    # 频道配置决定表上有哪些台，所以它要在**读整批上游条目之前**先读进来。
    # （这里不写条数：那批数是缓存里有多少条就是多少条，而「1868」和「1869」在本仓库
    #  分别是「三份缓存」与「含手工源的池子」两个口径 —— 2.53 抄数时撞上，注释只指口径名。）
    # 以前它在 collect 之后：一份合法、只是缺 `hunan_local` 分组的配置，会先把上游
    # 读完、把 aptv.m3u 盖成 7 行，然后才崩在 group_title() 的 KeyError 上（2.37 实测）。
    try:
        index = load_index(args.config)
    except (OSError, ValueError, yaml.YAMLError) as e:
        # load_index 已经把「不在 / 是目录 / 不是 UTF-8 / 不是 YAML / 结构不对」统一成
        # ValueError 了；留 OSError 是兜底，别让它哪天又从别的口子漏出去变成崩栈。
        reason = (str(e).strip().splitlines() or [type(e).__name__])[0]
        # 那几条「摸不到文件」的句子自带路径，再复述一遍就是同一个路径印两次。
        why = (f"⚠️ {reason}" if str(args.config) in reason
               else f"⚠️ 频道配置 {args.config} 读不了：{reason}")
        print(f"{why}\n"
              f"   这一轮不出表 —— 表上的台全部来自这份名单，先修它", file=sys.stderr)
        return 1
    lacking = index.lacking_groups(HUNAN_GROUPS)
    if lacking:
        print(f"⚠️ 频道配置 {args.config} 的 groups 里缺少 {'、'.join(lacking)} —— "
              f"hunan.m3u 就是按这四个分组切的\n"
              f"   这一轮不出表 —— 那张是电视上真正在用的，不能安静地不出；"
              f"换 `--config` 时把 groups 一起带上", file=sys.stderr)
        return 1

    try:
        sources = (
            [{"id": s.rsplit("/", 1)[-1][:40], "target": s, "cache": None} for s in args.sources]
            if args.sources
            else load_sources(Path(args.sources_file), fresh=args.fresh)
        )
    except (OSError, ValueError, yaml.YAMLError) as e:
        # 源清单读不了不是「少看几个源」的小事：接着往下走表照出，只是那些台安静地不见了。
        # 以前这里是裸崩（文件不在 → FileNotFoundError 崩栈，条目缺 url → KeyError）。
        return stop_config("源清单", args.sources_file, e,
                           "少一个源在表上是看不出来的，先修配置（`--sources-file` 换一份）")
    if not sources:
        # 这句以前写死成「config/sources.yaml」：`--sources-file` 指到别处时它指着**没有的那一份**
        # 说话（2.82 体内那一格第一次跑到这里就撞上了）。停在门口的话报错了门，比不说还糟。
        print(f"{args.sources_file} 里没有启用的源。", file=sys.stderr)
        return 1
    # 手工线路在碰上游之前读 —— 2.37 给 channels.yaml 立过同一条规矩：读不进去这件事
    # 该在花掉那几分钟抓网络之前说。停下来的是**键名**那一档（`expires` 写歪 = 永不过期，
    # src/keys.py）；2.47 起**值的形状**写坏只停那一条线路（理由进 `skipped`、印在屏幕上），
    # 因为这一份的其余各条是各自核对过的 —— 分档的理由在 `parse_channels` 的 docstring 里。
    try:
        local_lines = [] if args.skip_local else load_local(LOCAL_SOURCES_FILE)
    except (OSError, ValueError, yaml.YAMLError) as e:
        return stop_config("手工线路", LOCAL_SOURCES_FILE, e,
                           "那些核对过的第一线会安静地消失。先修配置；"
                           "这轮确实不要它们，传 --skip-local")
    print(f"读取 {len(sources)} 个上游：")
    try:
        entries, epg_urls = collect(sources)
    except UnreadableSource as e:
        print(f"⚠️ {e}", file=sys.stderr)
        return 1
    if local_lines:
        print(f"  {LOCAL_ID}（手工核对）: {len(local_lines)} 条 ← config/sources_local.yaml")
        entries += local_lines
    if not entries:
        print("没有解析到任何条目，检查网络或上游地址。", file=sys.stderr)
        return 1

    # `index` 在碰网络之前就读好了（2.37：它读不进去时最晚在这里说，见函数开头）
    # `--try-reach`（2.53）只换掉「读哪一份规则」这一件事：判档、排序、窗口全走同一条代码，
    # 所以它答的是「这张表会怎么变」，不是「另一套逻辑会怎么算」。
    reach_file = Path(args.try_reach) if args.try_reach else REACH_FILE
    try:
        reach = load_reachability(reach_file)
    except (OSError, ValueError, yaml.YAMLError) as e:
        return stop_config("范围规则", reach_file, e,
                           "少一档规则，运营商内网地址就会跑去占第一线 —— 真机上正是这么坏的（2.9）"
                           + ("；这一份是 --try-reach 给的候选文件，跟 config/ 里那份无关"
                              if args.try_reach else ""))
    if args.try_reach:
        # 这句话是这一轮的全部前提：表上那些「公网/专网」的判法来自一份**不打算用上的**文件。
        # 少了它，看的人会把试算出来的那张表当成部署事实（2.44 那种「两个读法」的病，反过来）。
        # 顺带把 config 那一份也读一遍：不是为了用它判档，是为了「挪了什么」这句答得出来，
        # 也是为了不让一份读不进来的正式配置藏在这次试算后面。
        try:
            base_reach = load_reachability(REACH_FILE)
            note = reach_order_note(base_reach, reach)
        except (OSError, ValueError, yaml.YAMLError) as e:
            note = f"`config/reachability.yaml` 这一份读不进来（{type(e).__name__}），比不了"
        n_rules = len(reach.rules) + len(reach.audio_rules)
        print(f"\n⚠️ 本轮是**试算**：范围规则读的是 `{reach_file}`（{n_rules} 条），"
              f"不是 `config/reachability.yaml`。\n"
              f"   这一动：{note}\n"
              f"   它只回答「挪一下会怎样」，不回答「电视上现在是什么」；"
              f"产物在 `{args.out}`，`config/` 与订阅目录都没动。")

    # P3（计划书 2.19）：`tvg-id` 由「选定的节目单里到底有哪个 id」决定，不再由谁先创建频道桶决定。
    # 节目单取不到就是空单，`apply_ids()` 拿到空单什么都不改 —— 这一层不能变成新的失效面。
    today = datetime.now().strftime("%Y%m%d")
    try:
        epg_cfg = load_epg_config(Path(args.epg_file))
    except (OSError, ValueError, yaml.YAMLError) as e:
        return stop_config("节目单配置", args.epg_file, e,
                           "它只管 tvg-id 对得上谁，写歪的键安静走默认值就是"
                           "「以为关了其实没关」。先修那一行（`--epg-file` 可以指另一份）")
    if args.no_epg:
        epg_cfg["enabled"] = False
    epg_doc, epg_info = load_epg(epg_cfg, today=today, force=args.fresh)
    if epg_cfg["enabled"]:
        print(f"\n节目单（{epg_info['via']}，{epg_info['url']}）："
              f"{epg_doc.n_channels} 个频道、{epg_doc.progs} 条节目 —— "
              f"{epg_info['coverage'] or '一条节目都没有'}"
              + (f"；⚠️ {epg_info['error']}" if epg_info["error"] else ""))
    else:
        print(f"\n节目单：未启用（{epg_off_note(epg_cfg, args.no_epg)}），"
              "tvg-id 保持上游写法")

    # 实测履历：判据只认「体检没报警」的那些轮，而参照出口由 judgment_egress() 定
    # （表是给电视用的，开发机代理在哪不影响这个依据）。
    # 出口身份现查一次就够，屏幕、probe.json、落盘、体检都用它，别重复查。
    # `--no-egress-check` 省掉的是这一趟：省下来的空串不进屏幕（那里印「没问」），只进
    # 落盘的那份来历（`egress: ""`）—— 「没问」与「没问到」在履历里本来就是同一个形状，
    # 分辨它靠的是同一行的 `mode`（offline / verify / replay），不是靠猜。
    history_path = Path(args.history)
    hist_problems: list[str] = []
    runs = hist.load_history(history_path, problems=hist_problems)
    for p in hist_problems:
        # 履历读不出行只影响排序（不删台），所以报一句就往下走 —— 但不能不报：
        # 不报的话这份履历读不出来和「履历里就是没有可信轮次」长成同一个样子（2.32 同族）。
        print(f"⚠️ 实测履历：{p}", file=sys.stderr)
    egress = "" if args.no_egress_check else egress_hint()
    egress_says = egress_of(args.no_egress_check, egress)   # 屏幕上那一句：没问 ≠ 没问到
    warns = measurement_warnings(egress) if args.verify else []   # 只查一次，后面几处复用
    # --replay：本轮不实测，但把上一轮那一份**逐条**判决当本轮结果用。于是判据出口、
    # 体检警告、该不该隔离，全部换成「那一轮」的 —— 本机现在的出口在这一轮不构成任何测量
    # （它此刻可能正挂在代理隧道上，而表是电视要用的）。
    replay: dict[str, ProbeResult] = {}
    replay_meta: dict = {"at": "", "egress": "", "warnings": [], "hosts": []}
    point_egress, measured = egress, bool(args.verify)
    if args.replay:
        try:
            replay, replay_meta = load_probe(Path(args.replay))
        except json.JSONDecodeError as e:      # 它是 ValueError 的子类，必须先接住
            print(f"⚠️ --replay 那份记录不是 JSON：{args.replay}"
                  f"（{str(e).splitlines()[0]}）", file=sys.stderr)
            return 1
        except (OSError, ValueError) as e:
            # OSError = 文件不在/没权限；ValueError = `load_probe()` 里那些「读得出来
            # 但不是给人用的形状」—— 它们的句子本身已经带着路径，这里不再重复一遍。
            print(f"⚠️ --replay 那份记录读不了：{str(e).splitlines()[0]}", file=sys.stderr)
            return 1
        warns = list(replay_meta["warnings"])
        point_egress = replay_meta["egress"] or egress
        measured = True
    if not runs and not history_path.exists():
        old = Path(args.out) / "probe.json"
        try:
            adopted = hist.adopt_probe(json.loads(old.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            adopted = None
        if adopted:
            # merge_minutes=0：这一支在 `history_path` 不存在时才走，本来没有可合并的行；
            # 写成 0 是不让这个前提变成依赖 —— 哪天真有一行了，补记也不该顶掉它。
            hist.append_run(history_path, adopted, merge_minutes=0)
            runs = hist.load_history(history_path)
            print(f"已把上一版留下的 {old.name} 补为第 1 轮履历（{adopted['at'][:16]}）")
    point = judgment_egress(point_egress, warns, runs, measured=measured)
    replay_at = str(replay_meta["at"])[:16].replace("T", " ")   # 报给人看的时刻，别带那个 T
    if args.replay:
        # 原来是 `if replay:` —— 一份「读得出来但一条判决都没有」的记录会让这个条件不成立，
        # 于是 --replay 静默变成「什么都没沿用」的普通离线生成，退码还是 0（2.36 实测）。
        # 现在只要传了这个 flag 就必须过闸，闸问的第一批问题里就包括「里面到底有几条」。
        gate_ok, gate_why = replay_gate(
            replay_meta, point=point, max_age_hours=args.replay_max_age,
            now=datetime.now().astimezone().isoformat(timespec="seconds"),
            force=args.allow_untrusted, n_lines=len(replay))
        if not gate_ok:
            print(f"⚠️ 那份记录不能用：{gate_why}\n"
                  f"   （要硬来就加 --allow-untrusted，或者跑一轮真正的 --verify）", file=sys.stderr)
            return 1
        print(f"\n线路判决沿用 {args.replay}：{replay_at} 那一轮"
              f"（出口 {replay_meta['egress']}，{len(replay)} 条逐条判决）"
              + (f"；⚠️ {gate_why}" if gate_why else "")
              + f"；本轮不写 {Path(args.replay).name}、也不把这一轮当实测记进履历"
                f"（履历空时会把那份记录补成第 1 轮，那是补档不是记本轮）")
    # 报警那一轮的产物不进订阅目录（理由见 artifact_dir()）；履历照旧追加。
    trusted_dir = Path(args.out)
    out_dir, quarantined = artifact_dir(trusted_dir, warns=warns, measured=measured,
                                        force=args.allow_untrusted)
    try:
        trusted_rel = trusted_dir.relative_to(ROOT)
    except ValueError:
        trusted_rel = trusted_dir
    rep = hist.reputation(runs, current_egress=point) if not args.ignore_history else {}
    stale = hist.demote_hosts(rep) if not args.ignore_history else frozenset()
    fake = hist.fake_hosts(rep) if not args.ignore_history else frozenset()
    # L3 是逐条的结论（分片窗口动不动），单独合成一份，不走主机那一档
    rolls = hist.merge_rolls(runs, current_egress=point) if not args.ignore_history else {}
    rep_now = rep            # 落盘新那一轮之后会被换成最新的履历，用来判"该划掉谁"
    dropped = len(hist.untrusted_runs(runs, current_egress=point))
    # 来源 -> 现在的 priority：既给频道内排序用，也给 2.17 的「建议调到几」当基准
    src_prio = {**{s["id"]: s.get("priority", i + 1) for i, s in enumerate(sources)},
                LOCAL_ID: 0}   # 手工源是人工确认过出处的，同条件下优先

    if args.verify:
        for warn in warns:
            print(f"⚠️  {warn}")
        print()
    if rep and not args.verify:
        n_stuck = sum(1 for v in rolls.values() if v == "stuck")
        print(f"\n实测履历（{history_path.name}）：{len(runs)} 轮里 {len(rep)} 个主机有"
              f"「出口 {point}」的可信记录 → {len(stale)} 个整族失效主机往后压、"
              f"{len(fake)} 个「只出循环录像」的主机往后压、"
              + (f"{n_stuck} 条线路按 L3 让位、" if n_stuck else "")
              + f"{len(host_latency(rep))} 个按上一轮延迟补位"
              + (f"，另有 {dropped} 轮因测量点不对未采用" if dropped else "")
              + ("；本轮未实测，这些判据顶上" if not replay else
                 "；本轮的逐条判决来自 --replay，这些只是补位用的历史延迟"))
    channels, unmatched, excluded, dead, results, stale_hits = aggregate(
        entries, index, args.max_lines,
        verify=args.verify, timeout=args.timeout, workers=args.workers,
        max_per_host=args.max_per_host,
        skip_verify=[s["id"] for s in sources if not s.get("probe", True)],
        source_priority=src_prio,
        reach=reach,
        stale_hosts=stale,
        fake_hosts=fake,
        rolls=rolls,
        hist_ms=host_latency(rep),
        preset=replay or None,
    )

    # 一个台都没归上 —— 这就是要出张空表了。以前这里不问：四张表各自盖成一行表头，
    # 退 0，屏幕上只有一句「aptv.m3u : 0 个频道 / 0 条线路」。
    # 空表盖掉订阅目录里那张能播的表，比崩一下严重得多（2.37）。
    if not channels:
        print(f"⚠️ 本轮一个台都没归上：上游 {len(entries)} 条线路里，没有一条对得上 "
              f"{args.config} 的名单（未匹配 {sum(unmatched.values())} 条、剔除 {excluded} 条"
              + (f"、实测失效 {dead} 条" if args.verify or replay else "") + "）\n"
              f"   这一轮不出表 —— {trusted_rel} 里那张保持原样。"
              f"要的就是「看看现在有哪些台」就换个 --out 再跑", file=sys.stderr)
        return 1
    # 判决全灭是同一件事的另一种长相：台还有（都是没测过的），可用线路一条不剩。
    # 2.37 拿一份合成的「全死」记录跑 `--replay` 量到过：350 条判决全 ok=False 时，
    # 那张表从 453 行变成 303 行、公网线路归 0，退码还是 0。
    # 一次测量不可能让每一条线路同时死，所以这只能判成「这一轮没量成」。
    if results and not any(r.ok for r in results.values()) and not args.allow_untrusted:
        print(f"⚠️ 本轮的线路判决把测过的 {len(results)} 条全判成不能用"
              + (f"（{replay_at} 那一轮的记录）" if replay else "（本轮实测）")
              + f"，剩下 {len(channels)} 个台靠的是「从没测过」的线路\n"
              f"   这一轮不出表 —— 换个出口重测，或者看看 `--timeout` 是不是给小了。"
              f"明知这份结果就是要用，加 --allow-untrusted", file=sys.stderr)
        return 1

    present = {c.name for c in channels}
    empty = [(r.name, index.group_title(r.group)) for r in index.rules if r.name not in present]

    # 从这里开始**只算不写**：所有产物先进这个字典，最后一道 `write_artifacts()` 一次性换上去。
    # 分开的理由见 writer.py：算第二份的时候崩，不该把第一份留在半截状态。
    artifacts: dict[str, str] = {}
    # 头部那行是**电视自己去取节目单**用的地址：启用 config/epg.yaml 就用它，
    # 没启用才回到「抄上游播放列表的第一条」（那条实测 404，见 2.19）。
    epg = epg_header_url(epg_cfg, epg_urls)
    align = apply_ids(channels, epg_doc)

    full = format_m3u(channels, epg)
    artifacts["aptv.m3u"] = full

    hunan_titles = {index.group_title(gid) for gid in HUNAN_GROUPS}
    hunan = [c for c in channels if c.group_title in hunan_titles]
    # hunan.m3u 是电视上真正在用的那张，所以命中率单独按台名切一份出来对账
    hn_names = {c.name for c in hunan}
    align["hunan"] = sum(1 for r in align["rows"] if r["name"] in hn_names and r["how"])
    align["hunan_total"] = sum(1 for r in align["rows"] if r["name"] in hn_names)
    hunan_text = format_m3u(hunan, epg)
    artifacts["hunan.m3u"] = hunan_text

    # 诊断用副产物：局域网订阅失败时用来区分「网络不通」和「App 抓台标/EPG 卡住」
    lean = load_lean_fn()
    if lean:
        artifacts["hunan-lean.m3u"] = lean(hunan_text)
        artifacts["test.m3u"] = lean(hunan_text, limit=4)

    # 可达范围拆分：运营商 IPTV 内网线路要在对应运营商的 IPTV 专网里才连得上，
    # 家庭 Wi-Fi 上表现为超时；电台地址则是上游挂在电视频道名下的冒充项。
    scope_stats = Counter(reach.scope(c.urls[0]) for c in channels)
    line_scope = Counter(reach.scope(u) for c in channels for u in c.urls)
    no_public = [c.name for c in channels
                 if all(reach.scope(u) != PUBLIC for u in c.urls)]
    # 范围规则各自抓到几条（计划书 2.50）：同一批规则去问三层 —— 上游池子 / 进了表的 / 每个台的第一条。
    # 为什么要问「上游」而不是只问表：「命中 0 条」在这一格有三种意义（被窗口挤掉、被前一条规则盖住、
    # 今天就没有这类地址），只回问表会把前两种读成「这条规则坏了」—— 那是 §2.49 收尾时记下的那一格。
    up_urls = [e.url for e in entries]
    table_urls = [u for c in channels for u in c.urls]
    first_urls = [c.urls[0] for c in channels]
    cov_up = reach.coverage(up_urls)
    cov_first = reach.coverage(first_urls)   # 只为拿 `code_intranet`：第一线里有几条是组播（不欠规则）
    rule_rows = reach.rule_states(up_urls, table_urls, first_urls)
    # 这一轮「是哪一种跑法」也要记进去（2.51）：那三层的数里只有「上游候选」不欠判决，
    # 进表 / 第一线是排序的产物，而排序看判决 —— 不记下跑法，下一轮就没法说这两列能不能比。
    round_mode = "verify" if args.verify else ("replay" if replay else "offline")
    round_at = datetime.now().astimezone().isoformat(timespec="seconds")
    reach_rules = {"rows": rule_rows, "n_up": len(up_urls), "n_up_uniq": len(set(up_urls)),
                   "n_table": len(table_urls), "n_first": len(first_urls),
                   "no_public_n": len(no_public), "code_first": cov_first["code_intranet"],
                   "max_lines": args.max_lines, "max_per_host": args.max_per_host,
                   "code_up": cov_up["code_intranet"], "dup": cov_up["dup"],
                   # 下面这几行就是落进 rule-history.jsonl 的那份来历（2.51）。
                   # 两个内容指纹各管一头：`fingerprint` 回答「这批线路是不是同一批」，
                   # `cfg_fingerprint` 回答「规则表改过没有」—— 两个都说没变而数变了，
                   # 剩下的唯一解释就是判定代码变了（那正是这一节最不该自己犯的错）。
                   "at": round_at, "mode": round_mode, "egress": egress, "warnings": warns,
                   "replay_at": replay_at if replay else "",
                   "fingerprint": pool_fingerprint(up_urls),
                   # 「本轮判档读的是哪一份」也是观测，得跟指纹一起落进履历那一行：
                   # 试算那几轮的表跟正式那一份不同源，下一轮比对时那句「规则文件改过了」
                   # 必须说得出改的是哪一份（2.53）。没挂 `--try-reach` 时它是仓库里那个相对路径。
                   "cfg_name": (str(reach_file.relative_to(ROOT)) if reach_file.is_relative_to(ROOT)
                                else str(reach_file)),
                   "cfg_fingerprint": config_fingerprint(reach_file),
                   "chan_fingerprint": config_fingerprint(args.config),
                   # 排序窗口也进那一份履历：`--max-lines 2` 跑一次，进表那一列必然往下掉，
                   # 不记下参数就会把它读成「规则不管用了」。
                   "params": [args.max_lines, args.max_per_host]}
    # 先扣下要落盘的那一行，再往上加只给本轮渲染用的两个键。
    # 顺序是有意义的：`no_diff` 和 `diff` 是「这一轮比出来/比不了」的话，不是观测；
    # 写进履历，下一轮的上一轮里就自带一份上上轮的 diff，那句话会跨轮长青。
    rule_row = dict(reach_rules)
    # 跟上一轮比（2.51）：把「上一轮还抓到、这轮归 0」这一格从人的记忆里搬进工具。
    # 这份履历是**参考不是判据**：读不读得到都不改这张表上一个字节（那一条有闸，见计划书）。
    rule_hist_path = hist.rule_history_path(out_dir)
    # 报告里那句「数落在哪儿」要说的是**这一轮真正落的那一个**，不是写死的 `data/output/…`：
    # 沙盒跑（`--out /tmp/一份表`）和体检报警被隔离的那一轮，那份文件都不在 `data/output/`。
    # 放在 `rule_row` 那份快照之后：它是渲染材料，不是观测，不进履历。
    reach_rules["hist_name"] = rule_hist_path.name
    prev_round: dict | None = None
    if args.ignore_history:
        reach_rules["no_diff"] = "`--ignore-history`：本轮不比对上一轮"
    else:
        rr_problems: list[str] = []
        rr = hist.load_rule_history(rule_hist_path, problems=rr_problems)
        for p in rr_problems:
            print(f"⚠️ 规则履历：{p}", file=sys.stderr)
        if rr:
            prev_round = rr[-1]
            # 有几行没读进来、但**最近一轮还是读到了**：那就照比，另把缺的那部分单独说清楚。
            # 这里不能顺手写 `no_diff` —— 那样报告里「本轮比不了」和下面那段「### 跟上一轮比」
            # 会同时印出来，自己打自己（改错实验 P4b 抓的就是这一格）。
            if rr_problems:
                reach_rules["hist_partial"] = "；".join(rr_problems)
        elif "no_diff" not in reach_rules:
            reach_rules["no_diff"] = (
                "上一轮那一行读不进来（屏幕上那一句 ⚠️ 说的就是它）" if rr_problems
                else f"{rule_hist_path.name} 里还没有更早的一次"
                     "（这一节是 2.51 装上的，从下一次跑开始比）")
    rule_diff = diff_rule_rounds(prev_round, reach_rules)
    reach_rules["diff"] = rule_diff
    # 屏幕上喊两种：整档全 0（2.50 那一条），和跨轮从有到无（2.51 这一条）。
    # 那几句话本身放在 scope.py，因为钉住它们只需要几条 doctest ——
    # 留在 cmd_build 里就是一句改错了也没人管的裸 print（2.50 同一条纪律）。
    notes = dead_tier_lines(rule_rows, len(up_urls), len(no_public), diff=rule_diff)
    alerts = diff_alert_lines(rule_diff)
    if notes or alerts:
        print("\n\n".join(notes + alerts), file=sys.stderr)

    # 第一线是循环录像的频道：电视默认就播这一条，必须点名。
    # 证据分三级，写清楚是哪一级看出来的：本轮实测的分片数最硬，L3 的「列表不动」次之，
    # 整族那种只是「上一轮这主机全是录像」，本轮没重测时才用。
    stuck_urls = {u for u, v in rolls.items() if v == "stuck"}
    fake_live = []
    for c in channels:
        first = c.urls[0]
        host = urlsplit(first).hostname or first[:20]
        r = results.get(first)
        if is_fake_live(r):
            fake_live.append(f"{c.name}（{host} "
                             + (f"{r.segments} 片循环）" if r.segments else "整段视频文件）"))
        elif r is None and first in stuck_urls:
            fake_live.append(f"{c.name}（{host} L3 验过：分片窗口不动）")
        elif r is None and host in fake:
            fake_live.append(f"{c.name}（{host} 上一轮整族只出录像，本轮未重测）")

    # 实测结果落盘：probe.json 是这一轮的快照（会被下一轮覆盖），
    # probe-history.jsonl 是它攒下来的履历 —— 离线生成、趋势判断都看后者。
    # 两边都记 egress + 体检警告，因为换一个测量点这些数字就不是同一个意思了。
    # src_of：这条地址是哪个上游塞进来的，2.17 起跟着履历一起攒，
    # 不然报告只能说出「这一族全灭」，说不出「所以该动 sources.yaml 里哪一行」。
    url_srcs: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        if e.source:
            url_srcs[e.url].add(e.source)
    src_of = {u: sorted(s) for u, s in url_srcs.items()}
    hosts = (host_summary(results, reach, src_of) if args.verify
             else list(replay_meta["hosts"]) if replay else [])
    # 第一线主机集中度（计划书 2.23）：两张表各量一遍。全量那张回答「这台死了带走几个台」，
    # 湖南那张才是电视上真正在订阅的，两边的答案不一样（2026-09-21 那版：22 台 / 20 台）。
    # fallback 是同一批台的下一问：换第二条线路救不救得回来（2.25 量出来是 0 个，2.26 搬进报告）。
    focus = [{"label": "aptv.m3u 全量",
              "total": len(channels), "measured": bool(results),
              "rows": first_line_focus(channels, results, src_of, reach),
              "fallback": second_line_options(channels, results, reach)},
             {"label": "hunan.m3u 湖南本地",
              "total": len(hunan), "measured": bool(results),
              "rows": first_line_focus(hunan, results, src_of, reach),
              "fallback": second_line_options(hunan, results, reach)}]
    if args.verify:
        # 一轮一个时刻：这个 `at` 与上面 `reach_rules["at"]` 是同一个数（2006 那两行取的），
        # 于是 `probe-history.jsonl` 那一行和 `rule-history.jsonl` 那一行能靠 `at` 对上 ——
        # 原来这里再取一次 `datetime.now()`，两行的时刻差着实测那几十秒，
        # 「同一轮的两种观测」在文件里就成了两个时刻。
        at = round_at
        artifacts["probe.json"] = json.dumps({
            "at": at,
            "egress": egress,
            "measurement_warnings": warns,
            "hosts": hosts,
            "lines": {u: {"ok": r.ok, "http": r.http, "ms": r.ms,
                          "segments": r.segments, "kind": r.kind, "error": r.error}
                      for u, r in results.items()},
        }, ensure_ascii=False, indent=1)
        # 追加履历失败不该把这一轮实测一起毁掉：表照出、probe.json 照写（它们排在后面那个
        # 写段里），只是履历这一轮没记上。append_run 自己是「读不进来就不动文件」的，
        # 所以这里不会留下半截履历。
        hist_again: list[str] = []      # 重读履历查出来的**新**问题；上面那批已经报过了
        cleared: list[str] = []         # 合并那一行时被整行换掉的旁路补记（2.37）
        try:
            new_run = hist.append_run(history_path, {
                "at": at, "egress": egress, "warnings": warns, "hosts": hosts},
                merge_minutes=args.merge_minutes, cleared=cleared)
            runs = hist.load_history(history_path, problems=hist_again)
        except (RuntimeError, OSError, ValueError) as e:
            print(f"⚠️ 这一轮没记进履历：{e}\n"
                  f"   表和 probe.json 照出，但离线生成少一轮可依据的记录", file=sys.stderr)
        else:
            for p in hist_again:
                print(f"⚠️ 实测履历：{p}", file=sys.stderr)
            # 判「该划掉谁」用最新这一轮，但报告里"本轮降档/补位了几个主机"说的是
            # 刚才 aggregate 真正用到的那份履历 —— 两者不能混。
            rep_now = hist.reputation(runs, current_egress=point)
            print(f"\n实测已记入 {history_path.name}："
                  f"{history_record_note(new_run, cleared)}"
                  f"（累计 {len(runs)} 轮，判据出口：{point or '未知'}）")

    trend = hist.run_totals(runs, current_egress=point)
    # 主机那一层的「该划掉谁」摊到上游源那一层，再落成能抄进 sources.yaml 的一行（2.17）
    srs = hist.source_reputation(rep_now, min_runs=2)
    sugg = hist.priority_suggestions(srs, current=src_prio, min_runs=2)
    history_note = {
        "runs": len(runs),
        "used": len(trend),
        "dropped": len(hist.untrusted_runs(runs, current_egress=point)),
        "egress": point,
        "build_egress": egress if egress != point else "",
        "totals": trend,
        "blacklist": [asdict(r) for r in hist.blacklist(rep_now)],
        "sources": [asdict(x) for x in sorted(srs.values(), key=lambda x: (-x.lines, x.source))],
        "suggestions": [asdict(x) for x in sugg],
        "unattributed": hist.unattributed_hosts(rep_now),
        # 事后补记过来源的那几轮（scripts/backfill_srcs.py）：报告得说清这些出处不是测出来的。
        # 只数真被采用的轮 —— 报警那轮补没补记过，跟这张表没关系。
        "srcs_backfilled": sorted({str(r.get("at") or "")[:16] for r in runs
                                   if r.get("srcs_note") and hist.trustworthy(r, point)}),
        "never_measured": [str(s["id"]) for s in sources if not s.get("probe", True)],
        "demote": sorted(stale),
        "fake": sorted(fake),
        "rolls": {"checked": len(rolls),
                  "stuck": sum(1 for v in rolls.values() if v == "stuck")},
        "latency_hosts": len(host_latency(rep)),
        "stale_first_lines": stale_hits,
        "verified": bool(args.verify),
        # --replay 是第三种状态：判决齐全但不是当场量的。报告要能分辨这三层，
        # 否则「本轮实测过」和「本轮沿用了实测过的记录」会长成同一句话。
        "replay": replay_at if replay else "",
    } if runs or args.verify else None

    verify_note = (f"--verify 实测剔除失效 {dead} 条" if args.verify else
                   (f"本轮没有重新实测：线路判决沿用 {replay_at} 那一轮"
                    f"（出口 {replay_meta['egress'] or '未知'}，{len(replay)} 条逐条记录），"
                    f"按它剔除失效 {dead} 条" if replay else
                    "本次未做线路实测，列表里的线路可用性以 Apple TV 实际播放为准"))
    # 「逐主机」那一节的表头后缀：--replay 时那些数字来自被沿用的那一轮，不写明的话
    # 报告读起来就像本轮又联网测了一遍（本轮真的一个请求都没发）。
    # 出口这里只留 IP + 国家码那两段：整条 BGP 描述已经在上面一行说过一遍了，
    # 而这一处是标题，别让它比表格还长。
    hosts_note = (f"沿用 {replay_at} 那一轮落在 {Path(args.replay).name} 里的记录，"
                  f"出口 {' '.join((replay_meta['egress'] or '未知').split()[:2])}，本轮未联网"
                  if replay else "")
    # 「EPG 对齐」那一节的材料：来历（哪来的、覆盖到哪、有没有取砸）+ 逐台的对账结果。
    # 未启用时也要写一节：报告得能看出这一轮**没有**对齐这回事，而不是读起来像漏了。
    epg_note = {**epg_info,
                "enabled": bool(epg_cfg["enabled"]),
                "header": epg,
                "epg_channels": epg_doc.n_channels,
                "epg_progs": epg_doc.progs,
                "days": dict(epg_doc.days),
                "generator": epg_doc.generator,
                "align": align,
                "caveat": epg_cfg.get("caveat", "")}
    if quarantined:
        verify_note += (f"。⚠️ 本轮体检报警（出口 {egress_says}），被剔的那些多半是假阴性，"
                        f"所以这份表只落在 {UNTRUSTED}/ 里当排查用，"
                        f"{trusted_rel} 那张仍是上一轮可信版本")
    report = format_report(
        sources=[f"{s['id']} ← {s['target']}" for s in sources] + (
            # 那份手工线路的名字要说得出在哪：`run_cell` 里第四道腿（`cell_bend`）会把它指进沙盒，
            # 那时候它不在仓库底下 —— 拿 `relative_to(ROOT)` 直接折会抛 `ValueError`（崩在出表那一步，
            # 不是判不过）。与上面 `cfg_name` 那一处同一个形状（2.53）。
            [f"{LOCAL_ID} ← {(str(LOCAL_SOURCES_FILE.relative_to(ROOT))
                             if LOCAL_SOURCES_FILE.is_relative_to(ROOT)
                             else LOCAL_SOURCES_FILE)}"
             f"（手工核对 {len(local_lines)} 条）"] if local_lines else []),
        total_entries=len(entries),
        channels=channels,
        unmatched=unmatched,
        defined_but_empty=empty,
        epg_url=epg,
        epg_note=epg_note,
        verify_note=verify_note,
        line_scope=line_scope,
        no_public=no_public,
        fake_live=fake_live,
        focus=focus,
        reach_rules=reach_rules,
        hosts=hosts,
        hosts_note=hosts_note,
        history=history_note,
    )
    artifacts["report.md"] = report
    # 到这一行之前，目录里一个字节都没动过。上面任何一步算不出来就崩在这里之前，
    # 订阅目录保持上一版原样（2.37：以前是 aptv.m3u 已经盖下去、才崩在下一份）。
    write_artifacts(out_dir, artifacts)

    # 规则那一节的七行落在**旁边**那份（`rule-history.jsonl`），2.51。
    # 排在 write_artifacts 之后：表没写下去就不该留下一行履历 —— 那一行是要给下一轮比的，
    # 比到一轮根本没出表的观测，等于把「上一轮还抓到」这句建在流沙上。
    # 为什么不并进 `probe-history.jsonl`：量过（09-24 06:31，`/tmp/g251/pool251.py`）——
    # 那种行没有 `hosts`，`load_history` 会跳过；一旦给 `hosts` 补上空表让它过闸，
    # `blacklist()` 从 26 族变 27 族（`m.italkbbtv.com` 被同一轮判决数了两次就判死），
    # 趋势也从 2 轮变 3 轮。两份各存一份才不动那两把尺。
    # 落盘失败只报一句：表已经写好了，履历缺这一轮不影响订阅。
    try:
        hist.append_rule_round(rule_hist_path, rule_row)
        rule_hist_note = f"（规则那一节的 7 行已记入 {rule_hist_path.name}，下一轮起有得比）"
    except OSError as e:
        rule_hist_note = ""
        print(f"⚠️ 规则履历这一轮没记上：{e}\n"
              f"   表照出，只是下一轮比不了「上一轮还抓到、这轮归 0」", file=sys.stderr)

    print(f"\n输出到 {out_dir}")
    if quarantined:
        print(f"  ⚠️ 体检报警的这一轮不碰订阅目录：上面这些文件写在 {UNTRUSTED}/ 里，"
              f"{trusted_rel} 保持上一轮可信版本 —— 局域网服务发的还是那张表。")
        print("  要给电视换表：关掉代理客户端的 TUN/系统代理再跑一次 build --verify"
              "（明知故犯就加 --allow-untrusted）")
    print(f"  aptv.m3u  : {len(channels)} 个频道 / {sum(len(c.urls) for c in channels)} 条线路")
    print(f"  hunan.m3u : {len(hunan)} 个频道 / {sum(len(c.urls) for c in hunan)} 条线路")
    if lean:
        print("  诊断用副产物：hunan-lean.m3u（无台标无 EPG）、test.m3u（前 4 个台）")
    if align["total"] and epg_note["enabled"]:
        print(f"  EPG 对齐：{align['total']} 个台里 {align['hit_id'] + align['hit_name']} 个有节目单"
              f"（按 tvg-id 直接对上 {align['hit_id']} 个、靠台名救回 {align['hit_name']} 个），"
              f"{len(align['changed'])} 个台的 tvg-id 被改写；"
              f"hunan.m3u 那 {align['hunan_total']} 个台里 {align['hunan']} 个有节目单")
    if epg_note["enabled"] and epg_info["error"]:
        print(f"    ⚠️ {epg_info['error']} —— 节目单只是「有更好」，这一轮照旧出表")
    print(f"  可达范围：公网 {line_scope[PUBLIC]} 条 / 运营商内网 {line_scope[INTRANET]} 条 / "
          f"电台冒充 {line_scope[AUDIO]} 条；第一线是公网线路的 {scope_stats[PUBLIC]}/{len(channels)} 个频道")
    print(f"  范围规则：{len(rule_rows)} 行 × 三层数写进 report.md，"
          + (f"本轮的数已记入 {rule_hist_path.name}（2.51：下一轮起「上一轮还抓到、这轮归 0」由它自己发现）"
             if rule_hist_note else
             "本轮**没记上**那份履历（原因见上面那句 ⚠️），下一轮比不了"))
    if no_public:
        print(f"  ⚠️ 一条公网线路都没有的频道 {len(no_public)} 个（Wi-Fi 上大概率播不动）："
              + "、".join(no_public))
    if fake_live:
        print(f"  ⚠️ 第一线是循环录像的频道 {len(fake_live)} 个（有画但不是直播）："
              + "、".join(fake_live))
    for v in focus:
        # 两张表各说一行，所以两行都得写明**是谁**（2.82）：下面那一支原本不带 label，
        # 于是 aptv 与 hunan 的数一样时屏幕上就是两行一字不差的「第一线集中度：…」——
        # 与 §2.66／§2.67 修过的那两处同一种病（只报数、不说是谁）。report.md 里那张
        # 表一直带 label（`src/output/writer.py` 的 views），所以这个洞只在屏幕上。
        rows = [r for r in v["rows"] if r["channels"] >= 2]
        if not rows:
            print(f"  第一线集中度（{v['label']}）：那 {v['total']} 个台一家主机都不共用")
            continue
        top = rows[0]
        print(f"  第一线集中度（{v['label']}）：{v['total']} 个台只落在 {len(v['rows'])} 家主机上，"
              f"`{top['host']}` 一家挂着 {top['channels']} 个台的第一线"
              + (f"（其中 {top['alone']} 个台全部线路都在它上面，换线路也换不出去）"
                 if top["alone"] else "")
              + (f"，这 {top['unmeasured']} 个台的第一线电脑从没测过"
                 if v["measured"] and top["unmeasured"] else ""))
    if hosts:
        if replay:
            print(f"  线路判决来自 {replay_at} 那一轮（出口 {replay_meta['egress'] or '未知'}，"
                  f"详情见 {args.replay}）；本机当前出口 {egress_says}，"
                  "这一轮没拿它量过任何东西")
        else:
            print(f"  实测出口：{egress_says}（详情见 {out_dir / 'probe.json'}）")
        bad = [h for h in hosts if h["ok"] < h["total"]]
        for h in bad[:8]:
            print(f"    ⚠️ {h['host']:<34} 可用 {h['ok']}/{h['total']}"
                  + ("  ← 整族失效，这个主机提供的公网线路等于不存在" if not h["ok"] else ""))
        if len(bad) > 8:
            print(f"    …另有 {len(bad) - 8} 个主机有失败线路")
        alive = [h for h in hosts if h["ok"] == h["total"]]
        print(f"    其余 {len(alive)} 个主机全通（合计 {sum(h['total'] for h in alive)} 条），"
              f"最快 {min((h['best_ms'] for h in alive), default=0)}ms")
    if history_note and history_note["runs"] and not args.verify:
        h = history_note
        print(f"  实测履历：{h['runs']} 轮（采用 {h['used']} 轮，判据出口 {h['egress'] or '未知'}）"
              + (f"，{h['dropped']} 轮因测量点不对未采用" if h["dropped"] else "")
              + f"；据此往后压 {len(h['demote'])} 个整族失效主机"
              + (f"、{len(h['fake'])} 个只出录像的主机" if h.get("fake") else "")
              + f"、补位 {h['latency_hosts']} 个"
              + (f"，第一线仍落在已失效主机上的台 {h['stale_first_lines']} 个"
                 if h["stale_first_lines"] else ""))
        if h["blacklist"]:
            print("    ⚠️ 连续两轮以上从没通过过的："
                  + "、".join(f"{r['host']}（{r['runs']} 轮全灭）" for r in h["blacklist"][:6])
                  + " —— 它们贡献的「公网线路」等于不存在")
        moves = [g for g in h["suggestions"]
                 if g["to_prio"] != g["from_prio"] or g["enabled"] is False]
        if h["sources"]:
            print(f"  源级趋势：{len(h['sources'])} 个源在可信轮次里留了记录"
                  + (f"，{len(moves)} 个够得上动手的标准：" + "、".join(
                        f"`{g['source']}` "
                        + ("整源关掉" if g["enabled"] is False
                           else f"{g['from_prio']}→{g['to_prio']}")
                        for g in moves[:4]) if moves else "，没有一个够得上动手的标准"))
            print("    能直接抄进 `config/sources.yaml` 的那几行在 report.md"
                  " 的「按上游源摊开」那一节 —— 代码不自己改这个文件")
        elif h["unattributed"]:
            print(f"  源级趋势：还摊不开 —— 履历里 {h['unattributed']} 个主机族没记来源"
                  "（2.17 之前的轮次），在家里补跑一次 build --verify 就齐了")
    print(f"  丢弃：黑名单 {excluded} 条，未匹配 {sum(unmatched.values())} 条"
          + (f"，实测失效 {dead} 条" if args.verify else
             (f"，按 {replay_at} 那轮的判决剔掉失效 {dead} 条" if replay else "")))
    if replay:
        print("  注意：本轮一条线路都没联网测。表是按那份记录剔过死线的，"
              f"但「这些线路还活着」只在 {replay_at} 那一刻成立 —— "
              "换配置重出表用它（不用等干净出口），判断线路本身好坏还是要 --verify")
    if not args.verify and not replay:
        print("  注意：本次未实测"
              + ("，已按实测履历排序（只覆盖被测过的主机，新线路按未知处理）；"
                 "但离线生成不删失效线路，第二三条备选里仍会混着已知连不上的。" if stale else
                 "，产物里会混着已知失效的线路，而且会把上一轮 `--verify` 生成的表覆盖掉。")
              + "要给电视订阅前，建议补跑一次 `build --verify`。")
    if empty:
        print(f"  ⚠️ 配置里有但没匹配到线路的频道 {len(empty)} 个：" + "、".join(n for n, _ in empty))
    return 0


# ---------------------------------------------------------------------------
# 体内的格子门（2.82）：`src/cli.py` 那 76 句判决的第一批钉子
#
# 为什么这一堆要长在**本件体内**：`run_doctests.survey_file` 数「这句屏幕话今天有没有
# 格子钉」时，读的是**同一个文件**里的 `Cell(` 字面（2.76 起的那把跨件普查），所以格子
# 放在别处只会钉住别处。本件体内原本一个 `Cell(` 都没有 —— 面 C 那句「`src/cli.py`
# 判决 76 句：钉住 0」说的就是这件事（计划书 §2.81「下一步」第（1）条）。
#
# 这一堆的**安全边界**是从 §2.81 那次事故里直接抄出来的，五条都写在下面的闸里：
#   1. 每一格都得把「五份输入 + 一份产物」指进自己那棵临时树，**跑之前**先过
#      `cell_guards` 那道闸；不合格就整片不跑（退 2），不是「跑起来再说」。
#   2. 出网那三样（`--fresh`、单递的 `--verify`、不带 `--no-egress-check` 的默认）
#      由同一道闸拦死：开发机上出口是别人的隧道，量到的每一个数都是假的，而且
#      「问一次本机出口」本身就是一趟 HTTPS（`--help` 里写着「连 --no-epg 也算这一趟」）。
#   3. 上游只递**本地文件**（`--source`）或一份全关掉的源清单：就算哪天「退场在
#      `collect` 之前」那道判断被改坏，最坏也只走到「没有启用的源」那一句停下。
#   4. 每一格跑之前跑之后各数一次 `data/` 整棵的指纹（`data_fingerprint`），动了就判
#      这格不符 —— 那次事故里「被覆盖了」是第二天靠文档尺读出来的，这里要它当场就有对照。
#   5. §2.84 补的：闸的账本必须跟着 parser 长。上面那两本只登了「五份输入 + 一份产物」，
#      于是 `--source` 指着仓库产物、`--try-reach` 指着仓库规则、**空着的** `--replay`
#      （默认就是仓库那份真记录）这三种写法在闸眼里一路静默 —— 现在它们进第二本账
#      `CELL_LOCAL_PATH_FLAGS`，而「有没有旗标漏登」由 `cell_ledger_covers_parser` 自己问。
#
# 口径与另外几把共用的那一族一样（`run_doctests`／`table_drift`／`lean_playlist` 各带
# 一份 `Cell`，2.65 立的先例：互相 import 就是绕环，而本件是被 `run_doctests` 面 A 真
# import 的那一件）。退码：**0** 每格都符合期望；**1** 至少一格不符；**2** 一格都没跑
# 成（名单是空的、或者那道预跑闸拦下了）。
# ---------------------------------------------------------------------------

SELF_TEST_FLAG = "--self-test"          # 与 `run_doctests.SELF_TEST_FLAG` 同一串字

CELL_URL_PLACEHOLDER = "http://example.invalid/用不上的上游"
# 这一句先前写着「在册那 17 种源全写着 `enabled: false`」，是**把「17 格」听成了「17 种源」**——
# 两个数都不是那个意思。19:14:21 那一遍拿代码自己复量（直接读 `BASELINE` 与 `cell_files`）读到的是：
# `--self-test` 在册 **17** 格里，自己写 `sources.yaml` 的 **0** 格，于是 17 格种的全是下面那份
# `CELL_SOURCES_ALL_OFF`（一条 `enabled: false`）、种了启用源的 **0** 格 —— 这才是「没有一格真去读
# 这个地址」的来路。仓库那份 `config/sources.yaml` 是**另一件事**：5 条源、3 条写着 `enabled: true`，
# 而那 17 格的 `--sources-file` 指着沙盒，一寸都碰不到它。

# §2.87 那格「闸眼里合格、只有线拦得住」的摆法用的地址 —— **故意是回环字面量，不是上面那个名字**。
# 两处理由，都是量出来的，不是想出来的：
#   * `scripts/work_guard.py` 那柄护栏（§2.70 的「不许去干自己的活」）在 `urllib.Request` 与
#     `http.client.connect` 这两处就记账了，比这根线**高一层**。19:13 那一遍把下面这个常量的值
#     换成 `CELL_URL_PLACEHOLDER` 各跑一遍 `work_guard.py … src/cli.py --doctest`，两遍都看见
#     `http.client.connect 1`、`urllib.Request 1` 这两条，可判决分了两档：名字那一遍
#     「落在仓库里 **2** 条：出门 urllib.Request -> example.invalid、出门 http.client.connect -> …」
#     **退 1**，回环这一遍「落在仓库里 **0** 条（被量件退 0）」**退 0**。也就是这根线明明当场拒了、
#     护栏仍按「本件想联网」判它不过 —— `local_host("127.0.0.1")` 说「哪儿都没去」，护栏看见的才是
#     一趟被拒的回环尝试，不再是一趟真出门。
#   * 万一这根线被谁摘掉（变异电池里就有这一把），名字一律要问 DNS、那一问在开代理的机器上
#     是真上墙的（`work_guard.py:458-460` 写死了这条），而 `127.0.0.1:1` 一个字节都不出机器。
#     19:10:30 那一遍电池里唯一一把摘掉整根线的（W01）读到的正是这个分别：外面那根只记不放的线
#     记到 `getaddrinfo 127.0.0.1` **1** 次，不是 `example.invalid`。
CELL_URL_LOOPBACK = "http://127.0.0.1:1/用不上的上游"


class Cell(NamedTuple):
    """一格：种哪几份配置、把哪些字递给 `main()`、屏幕上该有什么、盘上该留下什么。

    与 `run_doctests.Cell` 那一族差三处：本件的格子不种 .py 源码（`files` 种的是配置
    与清单），没有 `spawn`（每一格跑的是**本件自己的 `main()`**，在同一个进程里），
    多两位 `wrote`／`absent` —— 因为这一件是唯一一件**会写文件**的那一族，
    「屏幕上说了」和「盘上落了」是两件事（§2.81 那次事故正是这句话的形状）。

    >>> Cell(who="举例", what="说人话的一格", rc=1).argv
    ()
    >>> [a.replace("{T}", "/tmp/x") for a in ("--out", "{T}/out")]
    ['--out', '/tmp/x/out']
    """

    who: str                                  # 格子名
    what: str                                 # 给人看的那一句：这一格量的是哪件事
    rc: int                                   # 期望退码
    argv: tuple[str, ...] = ()                # 递给 `main()` 的原样一串（含 "build"）
    files: tuple[tuple[str, str], ...] = ()   # (相对沙盒树的路径, 内容)
    has: tuple[str, ...] = ()                 # 屏幕上必须有的那几截
    lacks: tuple[str, ...] = ()               # 屏幕上不许有的那几截
    wrote: tuple[str, ...] = ()               # 跑完之后沙盒里必须**非空**的那几件
    absent: tuple[str, ...] = ()              # 跑完之后沙盒里必须**不存在**的那几件


# 沙盒里用得上的那几份配置。
#
# 为什么 `channels` 一条都不能省：`load_index`（`src/match/matcher.py`）明确拒空名单
# —— 「channels 一条规则都没有 —— 表上的台全部来自这份名单，沿用它等于出一张空表」。
# 这一条是 2.82 第一次跑 `--self-test` 抓到的：两格想量的分别是 `lacking_groups` 与
# 「没有启用的源」，结果双双**提前**撞在这道读档关上，屏幕上印的是别处的话。
# 格子要的是**退场的位置对不对**，所以它得先合法，才轮得到后面那几句。
CELL_GROUP_TITLES = {
    "hunan_local": "湖南本地",
    "changsha": "长沙",
    "shizhou": "市州台",
    "jinying": "金鹰",
}


def cell_channels_yaml(group_ids: tuple[str, ...] = tuple(CELL_GROUP_TITLES),
                       rules: tuple[tuple[str, str], ...] = ()) -> str:
    """按给定分组造一份**读得进来**的频道配置；不写 `rules` 时每组配一条假台目。

    >>> cell_channels_yaml(("hunan_local",)).count("- {name:")
    1
    >>> "id: jinying" in cell_channels_yaml(("hunan_local", "jinying"))
    True
    >>> "id: changsha" in cell_channels_yaml(("hunan_local", "jinying"))
    False
    >>> "查无此台" in cell_channels_yaml(("hunan_local",), rules=(("查无此台", "hunan_local"),))
    True
    """
    rules = rules or tuple((f"例子台{i + 1}", g) for i, g in enumerate(group_ids))
    lines = ["version: 1", "groups:"]
    for gid in group_ids:
        lines += [f"  - id: {gid}", f"    title: {CELL_GROUP_TITLES[gid]}"]
    lines.append("channels:")
    lines += [f"  - {{name: {name}, group: {rule_group}}}" for name, rule_group in rules]
    return "\n".join(lines) + "\n"


CELL_CHANNELS_OK = cell_channels_yaml()
CELL_FAKE_CHANNELS = cell_channels_yaml(
    rules=(("湖南卫视", "hunan_local"), ("湖南经视", "hunan_local"), ("长沙新闻", "changsha")))
CELL_SOURCES_ALL_OFF = (
    "version: 1\n"
    "sources:\n"
    "  - id: off\n"
    f"    url: {CELL_URL_PLACEHOLDER}\n"
    "    enabled: false\n"
)
CELL_EPG_OFF = f"epg:\n  url: {CELL_URL_PLACEHOLDER}\n  enabled: false\n"
# 一份「启用」的源清单 —— §2.87 那根线唯一能当场开火的摆法：三扇开关全递、五个路径旗全指沙盒，
# 在**闸眼里是合规格**的（普查 戊 的 B4 那一串读到「闸：放行」），可 `collect` 照样要去取那一条
# 上游。闸与兜底读的都是 argv，全仓库没有一处读「种进沙盒的那份配置」，所以这一串两道腿都看不见。
# 那两个引号是必需的：`id: on` 在 YAML 里读出来是布尔 True，§2.46 那道形状闸会先把它吃掉。
CELL_SOURCES_ON = (
    "version: 1\n"
    "sources:\n"
    '  - id: "on"\n'
    f"    url: {CELL_URL_LOOPBACK}\n"
    "    enabled: true\n"
)
# 一份「假上游」：四条线路、三个对得上名单、一个对不上。地址全指向 127.0.0.1，
# 因为这一格**不实测**（`--verify` 由预跑闸拦着），这些地址从来不会被拨一次。
CELL_FAKE_M3U = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="x1",湖南卫视\nhttp://127.0.0.1:8080/hnws.m3u8\n'
    '#EXTINF:-1 tvg-id="x2",湖南经视\nhttp://127.0.0.1:8080/hnjs.m3u8\n'
    '#EXTINF:-1 tvg-id="x3",长沙新闻\nhttp://127.0.0.1:8081/cs.m3u8\n'
    '#EXTINF:-1 tvg-id="x4",上游有但名单里没有的台\nhttp://127.0.0.1:8082/nope.m3u8\n'
)
# 一份「全灭」的沿用记录：只覆盖前两条，第三条留成「从没测过」—— 少了这一条，
# 表会在「一个台都没归上」那一扇就停，永远走不到「判决全灭」那一扇。
# 这里点名用那两格的 `who`，不用行号：行号跟着文件长，而这一件天天在长（§2.82）。
CELL_PROBE_ALL_DEAD = (
    '{"at": "2026-09-20T12:00:00+08:00", "egress": "", "lines": {\n'
    '  "http://127.0.0.1:8080/hnws.m3u8": {"ok": false, "http": 0, "ms": 0},\n'
    '  "http://127.0.0.1:8080/hnjs.m3u8": {"ok": false, "http": 0, "ms": 0}}}\n'
)
CELL_PROBE_EMPTY = '{"at": "2026-09-20T12:00:00+08:00", "egress": "", "lines": {}}\n'

# 每一格都要带上的那一串：五份输入指进沙盒、两份产物目录指进沙盒、三扇出网的门关上。
CELL_ARGS_BASE = ("--config", "{T}/channels.yaml", "--sources-file", "{T}/sources.yaml",
                  "--epg-file", "{T}/epg.yaml", "--history", "{T}/hist.jsonl",
                  "--skip-local", "--no-epg", "--no-egress-check")
CELL_TAIL = CELL_ARGS_BASE + ("--out", "{T}/out")


def cell_files(cell: Cell) -> tuple[tuple[str, str], ...]:
    """这一格要种的文件：那三份配置都种上，除非它自己写了同名的一份。

    为什么默认要替每一格种好 `channels.yaml`／`sources.yaml`／`epg.yaml`：沙盒里那份源
    清单**全是关掉的**、节目单**是关掉的**，所以任何一格走漏到 `collect` 之前，先撞上
    「没有启用的源」那一句停下，而这一句在仓库里不落一个字。

    >>> [rel for rel, _ in cell_files(Cell(who="x", what="y", rc=1))]
    ['channels.yaml', 'epg.yaml', 'sources.yaml']
    >>> [rel for rel, _ in cell_files(Cell(who="x", what="y", rc=1,
    ...     files=(("channels.yaml", "a"), ("fake.m3u", "b"))))]
    ['channels.yaml', 'epg.yaml', 'fake.m3u', 'sources.yaml']
    """
    out = {"channels.yaml": CELL_CHANNELS_OK, "sources.yaml": CELL_SOURCES_ALL_OFF,
           "epg.yaml": CELL_EPG_OFF}
    out.update(dict(cell.files))
    return tuple(sorted(out.items()))


def cell_argv(cell: Cell, tree: Path) -> list[str]:
    """把 `{T}` 换成这一格那棵沙盒树的绝对路径。

    >>> cell_argv(Cell(who="x", what="y", rc=1, argv=("--out", "{T}/out")), Path("/tmp/a"))
    ['--out', '/tmp/a/out']
    """
    return [a.replace("{T}", str(tree)) for a in cell.argv]


def cell_argv_words(cell: Cell) -> list[str]:
    """把 `--旗=值` 那一式摊开成两个字，让闸只需认一种摆法。

    argparse 两式同义（`--out x` 与 `--out=x`），而闸原先按整词比 —— 于是
    `--out=data/output` 在闸眼里是「没递 --out」（那句还是假的），在 argparse 眼里
    是「产物写进仓库」。这一句先把这一族折成同一形状，上面那本账才谈得上「每一处都查」。

    >>> cell_argv_words(Cell(who="x", what="y", rc=1,
    ...     argv=("build", "--out={T}/out", "--replay-max-age=6")))
    ['build', '--out', '{T}/out', '--replay-max-age', '6']
    >>> cell_argv_words(Cell(who="x", what="y", rc=1, argv=("build", "--source=a=b.m3u")))
    ['build', '--source', 'a=b.m3u']
    """
    out: list[str] = []
    for a in cell.argv:
        if a.startswith("--") and "=" in a:
            flag, _, val = a.partition("=")
            out.extend([flag, val])
        else:
            out.append(a)
    return out


def cell_flag_value(argv: list[str], i: int) -> str:
    """第 `i` 位那个旗标的值：递在末位、或后面紧接着又是一个旗标 —— 都算「没值」。

    后面是旗标时 argparse（`nargs="?"` 那一族）不会把它吃成值，所以「空着」与
    「后面跟了旗标」是同一件事：这一位**没递值**，走的是那一版默认。

    >>> cell_flag_value(["build", "--out", "{T}/out"], 1)
    '{T}/out'
    >>> cell_flag_value(["build", "--replay", "--out", "{T}/out"], 1)   # 后面是旗标
    ''
    >>> cell_flag_value(["build", "--out"], 1)                         # 递在末位
    ''
    """
    nxt = argv[i + 1] if i + 1 < len(argv) else ""
    return "" if nxt.startswith("-") else nxt


# 预跑闸的账本：路径类的旗标必须指进沙盒，开关类的必须递，出网的那几样必须不递。
CELL_PATH_FLAGS = (
    ("--out", "会把产物写进默认目录（那次事故盖的就是这一份）"),
    ("--config", "会读仓库里那份真频道配置"),
    ("--sources-file", "会读仓库那份真源清单：那一遍就出网了"),
    ("--epg-file", "会读仓库那份节目单配置（缓存没有就是今天联网抓）"),
    ("--history", "会往 data/output/probe-history.jsonl 上追加"),
)
CELL_SWITCHES = (
    ("--skip-local", "会把仓库那份手工线路读进来：那些是真核对过的第一线地址"),
    ("--no-epg", "会去取节目单（优先读缓存，缓存没有就联网）"),
    ("--no-egress-check", "会花一趟 HTTPS 问本机出口是谁"),
)
# 第二本账：**不递没事、一递就必须指进沙盒**的那几样。§2.84 之前闸只查上面那本，
# 于是「`--source` 指着仓库产物」「`--replay` 不带值」这两种写法在闸眼里是静默的 ——
# 而 `--replay` 不带值取的就是仓库那份真记录（`--help` 与本件 1722 行都钉着这个默认）。
# 第三样字「能不能不递值」：`--replay` 是 `nargs="?"`，空着走默认，所以空着就要点名；
# `--source`／`--try-reach` 必须带值，空着的那一种 argparse 自己就退 2，落不到「读仓库」这一族。
CELL_LOCAL_PATH_FLAGS = (
    ("--source", "会把仓库那份真产物当上游读进来：量的就不是种下去的假件了", False),
    ("--try-reach", "会读仓库那份候选规则：规则一变，那一格说的话就跟着变", False),
    ("--replay", "不带值的那一版取的是仓库那份 data/output/probe.json", True),
)


def cell_guards(cells: Iterable[Cell]) -> list[str]:
    """**跑之前**那道闸：每一格都得把输入输出指进沙盒、把出网的门关上，否则整片不跑。

    为什么不等到跑起来再靠 `data/` 那把指纹：指纹是**事后**的账，那次事故里最贵的一句
    话就是「等看见的时候已经盖掉了」；而出网这一头根本没有事后账可看（代理此刻开着，
    量到的一切都是假的，见 §2.81）。这一道只看 argv，不起进程、不碰盘，所以它拦下的
    那一遍一个字都不会写、一个包都不会发。

    §2.84 把这本账补全了三处：同一个旗标递**好几遍**时每一遍都查（argparse 后写的算，
    只看第一处等于查那个不生效的）、`--旗=值` 那一式折成同一形状、以及第二本账
    `CELL_LOCAL_PATH_FLAGS`（`--source`／`--try-reach`／`--replay`：不递没事、一递就得进沙盒，
    而 `--replay` **空着**那一版取的就是仓库那份真记录）。

    >>> bad = cell_guards([Cell(who="甲", what="y", rc=1, argv=("build",))])
    >>> len(bad), bad[0]
    (8, '甲：没递 --out —— 会把产物写进默认目录（那次事故盖的就是这一份）')
    >>> print("\\n".join(bad[1:]))
    甲：没递 --config —— 会读仓库里那份真频道配置
    甲：没递 --sources-file —— 会读仓库那份真源清单：那一遍就出网了
    甲：没递 --epg-file —— 会读仓库那份节目单配置（缓存没有就是今天联网抓）
    甲：没递 --history —— 会往 data/output/probe-history.jsonl 上追加
    甲：没递 --skip-local —— 会把仓库那份手工线路读进来：那些是真核对过的第一线地址
    甲：没递 --no-epg —— 会去取节目单（优先读缓存，缓存没有就联网）
    甲：没递 --no-egress-check —— 会花一趟 HTTPS 问本机出口是谁
    >>> cell_guards([Cell(who="甲", what="y", rc=1,
    ...     argv=("build",) + CELL_ARGS_BASE + ("--out", "/tmp/elsewhere/out"))])
    ['甲：`--out` 没指进这一格的沙盒（递的是 /tmp/elsewhere/out）']
    >>> cell_guards([Cell(who="甲", what="y", rc=1, argv=("build",) + CELL_TAIL)])
    []
    >>> cell_guards([Cell(who="乙", what="拼错的子命令，压根不出表", rc=2, argv=("bulid",))])
    []
    >>> cell_guards([Cell(who="丙", what="单递 --verify：那一格真去实测", rc=1,
    ...     argv=("build", "--verify") + CELL_TAIL)])
    ['丙：递了 --verify 又没配 --replay —— 那一格会真的动手测每条线路（出网）']
    >>> cell_guards([Cell(who="丁", what="两扇一起递：门口就停，量的是那一句", rc=1,
    ...     argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_TAIL)])
    []
    >>> cell_guards([Cell(who="戊", what="递 --fresh：那一格联网抓上游", rc=1,
    ...     argv=("build", "--fresh") + CELL_TAIL)])
    ['戊：递了 --fresh —— 那一格会联网抓上游，格子只在离线里跑']
    >>> cell_guards([Cell(who="己", what="`--out` 递在末位、后面没值", rc=1,
    ...     argv=("build",) + CELL_ARGS_BASE + ("--out",))])
    ['己：`--out` 没指进这一格的沙盒（递的是 空）']
    >>> cell_guards([Cell(who="庚", what="同一个旗标递两遍：argparse 后写的算，两处都得查",
    ...     rc=1, argv=("build", "--config", "{T}/c.yaml", "--sources-file", "{T}/s.yaml",
    ...                 "--epg-file", "{T}/e.yaml", "--history", "{T}/h.jsonl",
    ...                 "--skip-local", "--no-epg", "--no-egress-check",
    ...                 "--out", "{T}/out", "--config", "config/channels.yaml"))])
    ['庚：`--config` 没指进这一格的沙盒（递的是 config/channels.yaml）']
    >>> cell_guards([Cell(who="辛", what="`--source` 指着仓库那份真产物", rc=1,
    ...     argv=("build", "--source", "data/output/hunan.m3u") + CELL_TAIL)])
    ['辛：`--source` 没指进这一格的沙盒（递的是 data/output/hunan.m3u —— 会把仓库那份真产物当上游读进来：量的就不是种下去的假件了）']
    >>> cell_guards([Cell(who="壬", what="`--replay` 空着：默认就是仓库那份真记录", rc=1,
    ...     argv=("build", "--replay") + CELL_TAIL)])
    ['壬：`--replay` 没指进这一格的沙盒（递的是 空 —— 不带值的那一版取的是仓库那份 data/output/probe.json）']
    >>> cell_guards([Cell(who="癸", what="`--旗=值` 那一式：合规的写法别再被读成没递", rc=1,
    ...     argv=("build", "--config={T}/c.yaml", "--sources-file={T}/s.yaml",
    ...           "--epg-file={T}/e.yaml", "--history={T}/h.jsonl",
    ...           "--skip-local", "--no-epg", "--no-egress-check", "--out={T}/out"))])
    []
    >>> cell_guards([Cell(who="子", what="`--try-reach` 指着仓库那份候选规则", rc=1,
    ...     argv=("build", "--try-reach", "config/reachability.yaml") + CELL_TAIL)])
    ['子：`--try-reach` 没指进这一格的沙盒（递的是 config/reachability.yaml —— 会读仓库那份候选规则：规则一变，那一格说的话就跟着变）']
    """
    bad: list[str] = []
    for cell in cells:
        argv = cell_argv_words(cell)
        if not argv or argv[0] != "build":
            continue                      # 不走 `cmd_build` 的那几格没有产物目录可管
        for flag, why in CELL_PATH_FLAGS:
            spots = [i for i, a in enumerate(argv) if a == flag]
            if not spots:
                bad.append(f"{cell.who}：没递 {flag} —— {why}")
            for i in spots:
                val = cell_flag_value(argv, i)
                if "{T}" not in val:
                    bad.append(f"{cell.who}：`{flag}` 没指进这一格的沙盒（递的是 {val or '空'}）")
        for flag, why, bare in CELL_LOCAL_PATH_FLAGS:
            for i, a in enumerate(argv):
                if a != flag:
                    continue
                val = cell_flag_value(argv, i)
                if not val and not bare:
                    continue      # 那种写法 argparse 自己就退 2，读不到仓库，不归这一族
                if "{T}" not in val:
                    bad.append(f"{cell.who}：`{flag}` 没指进这一格的沙盒（递的是 "
                               f"{val or '空'} —— {why}）")
        for sw, why in CELL_SWITCHES:
            if sw not in argv:
                bad.append(f"{cell.who}：没递 {sw} —— {why}")
        if "--verify" in argv and "--replay" not in argv:
            bad.append(f"{cell.who}：递了 --verify 又没配 --replay —— "
                       "那一格会真的动手测每条线路（出网）")
        if "--fresh" in argv:
            bad.append(f"{cell.who}：递了 --fresh —— 那一格会联网抓上游，格子只在离线里跑")
    return bad


def cell_ledger_covers_parser() -> list[str]:
    """`build` 那把 parser 里**默认值落在仓库**的旗标，闸的三本账是否本本都认得它。

    应该是空表。它盯的不是「哪句判决没写」，是「旗标会长、账本不会自己长」这一族：
    §2.84 那个洞就是这么来的 —— `--replay` 的默认值是仓库那份真记录（`build_parser`
    里 `const=str(PROBE_FILE)`，本件 1722 行那条 doctest 还钉着它），可闸的账本里没有它，
    于是「`--replay` 空着递进来」这一格在闸眼里一路静默走到真数据上。
    这一道把它换成一句读数：**新增一个默认落进仓库的旗标、又没登记进账本，这里就点名。**

    走的是**活的** `build_parser()`，不是再抄一份名单：口径只有一份（§2.42 那一族的取舍）。

    >>> cell_ledger_covers_parser()
    []
    >>> sorted(f for f, *_ in CELL_PATH_FLAGS)          # 那五样都必须落进仓库，才轮得到点名
    ['--config', '--epg-file', '--history', '--out', '--sources-file']
    """
    named = ({f for f, *_ in CELL_PATH_FLAGS} | {f for f, *_ in CELL_SWITCHES}
             | {f for f, *_ in CELL_LOCAL_PATH_FLAGS})
    root = str(ROOT)
    bad: list[str] = []
    for act in build_parser()._actions:             # noqa: SLF001  旗标的登记处只有这一份
        for opt in act.option_strings:
            if not opt.startswith("--") or opt in named:
                continue
            for val in (act.default, act.const):
                if isinstance(val, str) and val and (val.startswith(root)
                                                     or val.startswith(("config/", "data/"))):
                    bad.append(f"{opt} 的默认值落在仓库（{val}），可它不在这三本账里")
                    break
    return bad


def data_fingerprint() -> tuple[tuple[str, int, int], ...]:
    """仓库 `data/` 整棵的「名字＋字节＋修改时刻」，读不到就跳过那一个。

    为什么从 `data/output/` 扩到整棵 `data/`：这一批格子里有会**走通到出表**的那几格，
    而沿用的那份记录、履历、缓存都在 `data/` 的别处 —— 只盯 output 等于只盯上一次事故
    的形状，下一次换个目录坏就没账了。

    >>> isinstance(data_fingerprint(), tuple)
    True
    """
    root = ROOT / "data"
    rows = []
    if not root.is_dir():
        return ()
    for p in sorted(root.rglob("*")):
        try:
            st = p.stat()
        except OSError:                       # 正在被同步盘搬走：那一格算「看不见」
            continue
        if p.is_file():
            rows.append((str(p.relative_to(root)), st.st_size, st.st_mtime_ns))
    return tuple(rows)


def hide_tmp(text: str, base: Path) -> str:
    """把临时目录那截路径从读数里抹掉，免得 `has` 里写死的字跟着机器走。

    >>> hide_tmp("写在 /tmp/pytest-of-x/out 里", Path("/tmp/pytest-of-x"))
    '写在 <沙盒>/out 里'
    """
    return text.replace(str(base), "<沙盒>")


# §2.87 的第三道腿：真跑期间身上带的一根线。要换掉的出口分两处 —— `socket` 模块上的
# `getaddrinfo`（一次 DNS 查询**本身**就是一趟外发，戊 量到 B4 那一串就是先摸到它），和
# `socket.socket` 上的两个方法（TCP 握手那一步）。这两处各是谁撑着，由**逐槽摘掉**读出来的
# （`/tmp/mut287g.out` 19:32:44：W03 只把两个方法清空 → 外面记到 `connect 192.0.2.1`＋
# `connect_ex 192.0.2.1` 各 1 次；W04 只把 `getaddrinfo` 清空 → 记到 `getaddrinfo 127.0.0.1`＋
# `getaddrinfo localhost` 各 1 次；W10 只摘 `connect_ex` → 记到它 1 次）—— 三把各漏各的，
# 谁也不是多余的那一个。早先 乙 那遍（`/tmp/census287b.out` 18:37:03）问的是另一件事：只拒
# `connect`＋`connect_ex` 那一层，上面三层（`create_connection`／`getaddrinfo`／`urlopen`）
# 各记到 **3** 次、一共 12 次；只拒 `create_connection` 则 `getaddrinfo` **0** 次、`urlopen`
# 仍 **3** 次 —— 本节头一版把后一条记成了「`getaddrinfo` 仍漏 3 次」，19:19 复量时才对着原文件
# 读出是 0（`create_connection` 在它上游，拒在前头它就再没响过）；写进这里的只能是量的那一个。
# `scripts/work_guard.py:56-63` 那张 03:55:42／03:56:21 两遍
# 量出来的层表对得上：`create_connection()` 发的是 `getaddrinfo` ＋ `connect`，所以接住这两处
# 就接住了从 `urllib`、`http.client` 与裸 `socket()` 走过来的路子 —— 唯独不握手的 `sendto`
# （直接扔 UDP 数据报）在这两处之外，本件没有那种用法（哪天有了就得再添槽）。
# 但那张表说的是**审计层**（PEP 578 的钩子在 C 里面补发事件名），**属性层是另一回事**：
# 只把 `socket.socket.connect` 换掉时，`connect_ex(("192.0.2.1", 443))` 一次都不经过它、
# 直落 C 并返回 0（量于 §2.87 的本机 3.12.14，下面那条例子钉着它）—— 所以 `connect_ex`
# 得单列，不能当 `connect` 的同义词省掉。
CELL_WIRE_ENTRY = ("getaddrinfo",)
CELL_WIRE_METHODS = ("connect", "connect_ex")


def cell_wire_name(arg: object) -> str:
    """把一次外发的「去哪」那一个参数折成「谁」：`(host, port)` 摊平、`Request` 认它的 URL。

    递进来的是**哪一个**参数由 `cell_wire` 按槽位定：模块函数（`getaddrinfo`）的第一个就是，
    而 `socket.socket` 上的方法头一个是 socket 自己 —— 越过它，不然点出来的会是
    `<socket.socket fd=3, family=2, ...>` 这么一截，谁也没去成却报了个名（自己量到的，见 §2.87）。

    >>> cell_wire_name(("raw.githubusercontent.com", 443))
    'raw.githubusercontent.com:443'
    >>> cell_wire_name(("/tmp/sock",))               #  Unix 域套接字：第一个字就是路径
    '/tmp/sock'
    >>> cell_wire_name("127.0.0.1")
    '127.0.0.1'
    """
    if hasattr(arg, "full_url"):
        return str(arg.full_url)
    if isinstance(arg, tuple):
        return ":".join(str(x) for x in arg[:2] if x != "")
    return str(arg)


@contextlib.contextmanager
def cell_wire(sink: list[str]):
    """真跑那一小段时间里，把 `socket` 的出口换成「先记进 `sink`，再当场拒」。

    为什么要在这**体内**再装一根线：仓库外面那根只跟着量具走。`scripts/work_guard.py` 那柄
    PEP 578 审计钩护的是「`run_doctests` 逐件真跑」那一族**子进程**；而 `run_cell` 是在
    `--self-test`／`--doctest` 这同一进程里跑格子的，那柄钩子够不着。至于量具那一侧临时套的
    只记不放的线，别人照抄 `python -m src.cli --self-test`、或者只跑 `--doctest`，身上是一根
    都没有的 —— 而 §2.86 量到：闸与兜底两条腿一起不在时，`--doctest` 那一扇门会真发三趟
    HTTPS（`self_test` 说明书里那一格 `argv=("build",)`，读的是仓库那份真源清单）。
    这一根线跟着代码走，不跟着量具走。

    它**不读**那三本账、也不读 `cell_guards`：装的是「想出门」这一味，不是「旗标对不对」。
    它对在册那些格子是一个字都不改 —— 拿 HEAD 与工作树各跑两扇门逐行比（`/tmp/cmp287.py`，
    19:30:56 那一遍：件 3469 行 → 3696 行）：self-test 那一屏 20 行里 **0** 行不同，doctest 那一屏
    4 行里只不同 2 行 —— 就是「合计 N 个用例」那一行的两面（261 → 280）；两棵树各自跑两扇门，
    四遍都想出门 **0** 次、退 **0**。
    反过来**摘掉**它屏幕才变：电池里 W01 那一把（只把 `run_cell` 里那处接线去掉）读到
    `--doctest` 红 **1** 例、`--self-test` 那一屏照旧**一个字没改**（就是上面 19:30:56 那遍量的
    那 0 行差），而外面那根只记不放的线记到 `getaddrinfo 127.0.0.1` **1** 次（19:32:44 那一遍；
    19:10:30 那一遍除行号与后来新加的那一栏外同读）。注意红的那一例在哪儿：是本件下面
    `run_cell` 里那一格「闸放行、只有线拦得住」，**不是**上面那几条例子 —— 那几条直接调
    `cell_wire`，不经过 `run_cell` 那处接线，所以接线整根断掉它们仍然全绿。钉住「接线」这一处
    的就是那**一**条例子，这是本节最小的那块覆盖，边界写在 §2.87。

    线记的是**「谁」**，不是「哪一口」：`getaddrinfo` 的第一个参数就是主机名（端口在第二位，
    说的是想要哪种地址族的结果，不是「去哪」），`connect` 递的才是 `(host, port)` ——
    所以那两槽一个记成 `localhost`、一个记成 `192.0.2.1:443`，读得清谁在前谁在后。
    例子故意用 `localhost` 与 TEST-NET 的字面量：万一这根线被谁摘掉，`localhost` 由 `/etc/hosts`
    就地答、数字地址根本不问 DNS，两步都不会上墙；换个公网名字（`work_guard.py:458-460` 写着
    「名字一律要问 DNS」）就等于把「线被摘掉」变成一次真出门。

    >>> refusals: list[str] = []
    >>> import socket
    >>> with cell_wire(refusals):                     # 线在身上时：谁摸谁被点名
    ...     try:
    ...         socket.getaddrinfo("localhost", 80)
    ...     except OSError as e:
    ...         print("拒了：", e)
    拒了： 这一格不许出门（getaddrinfo localhost）
    >>> refusals
    ['getaddrinfo localhost']
    >>> with cell_wire(refusals):                     # 另一槽：绕开查名、直接握手（拿 IP 字面量
    ...     s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   #   就不必经 `getaddrinfo`）
    ...     try:
    ...         s.connect(("192.0.2.1", 443))                     # 故意用 UDP：connect 只登记
    ...     except OSError as e:
    ...         print("拒了：", e)                                #   对端，一个包都不发、不等握手
    拒了： 这一格不许出门（connect 192.0.2.1:443）
    >>> refusals                     # 记的是地址，不是那个 socket 自己（方法槽越过头一个参数）
    ['getaddrinfo localhost', 'connect 192.0.2.1:443']
    >>> with cell_wire(refusals):                     # 第三个名字也不能省：只接 `connect` 接不住它
    ...     s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ...     try:
    ...         s.connect_ex(("192.0.2.1", 443))
    ...     except OSError as e:
    ...         print("拒了：", e)
    拒了： 这一格不许出门（connect_ex 192.0.2.1:443）
    >>> saved = socket.getaddrinfo                   # 出了那一小段，原样还回去
    >>> with cell_wire([]):
    ...     pass
    >>> socket.getaddrinfo is saved
    True
    """
    import socket

    saved: list[tuple[object, str, object, int]] = [
        (socket, n, getattr(socket, n), 0) for n in CELL_WIRE_ENTRY]
    saved += [(socket.socket, n, getattr(socket.socket, n), 1)
              for n in CELL_WIRE_METHODS]      # 1：方法头一个参数是 socket 自己

    def make(name: str, offset: int):
        def trip(*a: object, **k: object) -> object:      # 只记不放：点名进 sink，再抛
            target = cell_wire_name(a[offset] if len(a) > offset else "")
            sink.append(f"{name} {target}")
            raise OSError(f"这一格不许出门（{name} {target}）")
        return trip

    try:
        for owner, name, _old, offset in saved:
            setattr(owner, name, make(name, offset))
        yield sink
    finally:
        for owner, name, old, _offset in saved:
            setattr(owner, name, old)


def cell_wire_note(refusals: list[str]) -> str:
    """线点名之后那句话：几次、都是谁（最多摊三个，全在 `sink` 里，一句话说得完）。

    空的那一侧返回空串，而不是「想出门 0 次」—— 这句话是**给失败那一格配的说明**，
    没想出门的格子不该被安上这么一句（`run_cell` 里两处都是先 `if refusals` 再拼它，
    而判「过不过」读的仍是 `refusals` 这个列表本身，不是这句话）。

    >>> cell_wire_note(["getaddrinfo 127.0.0.1", "connect 192.0.2.1:443"])
    '线：这一格想出门 2 次（getaddrinfo 127.0.0.1、connect 192.0.2.1:443）—— 被体内那根线当场拒了'
    >>> cell_wire_note([])
    ''
    """
    if not refusals:
        return ""
    return (f"线：这一格想出门 {len(refusals)} 次（{'、'.join(refusals[:3])}）"
            "—— 被体内那根线当场拒了")


# 第四道腿的名单：这些模块级常量是 `build_parser()` 里那些默认值的来路。`ROOT` 故意不在
# 名单上 —— 它是 §2.70 那把护栏与 `run_cell` 里那道指纹闸的锚，拧了它两把尺读的就是沙盒了。
CELL_BEND_NAMES = ("SOURCES_FILE", "LOCAL_SOURCES_FILE", "REACH_FILE", "EPG_FILE",
                   "HISTORY_FILE", "PROBE_FILE", "CACHE_DIR")


def cell_bend_map(tree: Path) -> dict[str, Path]:
    """真跑那一格时，哪几条「仓库默认的绝对路径」临时指进这棵沙盒。

    为什么要有这一道：闸与兜底读的都是 argv，一串字里没写那个旗标，取的就是仓库那一份
    （§2.87 收尾时量到的那 3 次出门就是这么来的 —— 说明书里那一格故意什么都不递）。
    第三道腿是在**出手那一刻**拦它，这一道更早：让它根本没有仓库那一份可读、可写、可缓存。

    >>> m = cell_bend_map(Path("/tmp/沙盒"))
    >>> tuple(m) == CELL_BEND_NAMES
    True
    >>> all(str(v).startswith("/tmp/沙盒/") for v in m.values())
    True
    >>> [k for k, v in m.items() if str(v).startswith(str(ROOT))]      # 一条都不许串回仓库
    []
    >>> [n for n in CELL_BEND_NAMES if n not in globals()]     # 常量被人改了名要当场红在这里
    []
    """
    return {
        "SOURCES_FILE": tree / "sources.yaml",
        "LOCAL_SOURCES_FILE": tree / "sources_local.yaml",
        "REACH_FILE": tree / "reachability.yaml",
        "EPG_FILE": tree / "epg.yaml",
        "HISTORY_FILE": tree / "hist.jsonl",
        "PROBE_FILE": tree / "probe.json",
        "CACHE_DIR": tree / "cache",
    }


def cell_bend_gaps() -> list[str]:
    """那本名单**够不着**的旗标：默认值不从常量来、而是从 `ROOT` 现拼的那几条。

    够不着只有一种来源：`build_parser()` 里写成 `str(ROOT / ...)` 的默认 —— 要盖住它就得拧
    `ROOT`，而 `ROOT` 是 §2.70 的锚。这两条由第二道腿看着：`--out`、`--config` 不递就不跑。
    这一句不是许愿：名单里新加一条、或者 `build_parser()` 新添一个指着仓库的默认，
    下面那条例子就会把名字摊出来，而不是安静地少盖一处。

    >>> cell_bend_gaps()
    ['--config', '--out']
    """
    covered = {str(globals()[n]) for n in CELL_BEND_NAMES if n in globals()}
    gaps: list[str] = []
    for act in build_parser()._actions:           # noqa: SLF001  量具读自己的旗标登记处
        for value in (getattr(act, "default", None), getattr(act, "const", None)):
            if not isinstance(value, str) or not value:
                continue
            try:
                points_at_repo = Path(value).is_relative_to(ROOT)
            except (ValueError, OSError):         # 相对路径、非法字符：不是仓库那一份
                continue
            if points_at_repo and value not in covered:
                gaps.append(act.option_strings[0])
                break
    return gaps


@contextlib.contextmanager
def cell_bend(tree: Path):
    """把上面那张名单临时接到模块级常量上，出这一小段再原样装回去。

    只在这一小段在身上（和第三道腿同一个位置）：`--self-test` 那一扇里在册格子要读的仓库
    默认，跟真跑那一格时读的必须是同一个东西，否则量的就不是那串字了。

    下面那条例子读的是 `live` 而不是裸的名字 —— doctest 拿到的是模块 `__dict__` 的**一份
    拷贝**，拧的是真那一份，例子读不见（头一遍我按裸名写，屏幕上回来的是 `False False`）。

    >>> import tempfile
    >>> live = __import__("importlib").import_module(cell_bend.__module__).__dict__
    >>> before = (str(live["SOURCES_FILE"]), str(live["CACHE_DIR"]), str(live["REACH_FILE"]))
    >>> with tempfile.TemporaryDirectory() as d:
    ...     with cell_bend(Path(d)) as bent:
    ...         print(str(live["SOURCES_FILE"]) == f"{d}/sources.yaml",
    ...               str(live["CACHE_DIR"]) == f"{d}/cache")
    ...     print((str(live["SOURCES_FILE"]), str(live["CACHE_DIR"]),
    ...            str(live["REACH_FILE"])) == before, len(bent))
    True True
    True 7
    >>> [n for n in ("CELL_PATH_FLAGS", "CELL_SWITCHES", "cell_guards") if n in cell_bend.__code__.co_names]
    []

    这一拧**盖全了没有**：下面那两行问的是同一件事的两面 —— 没拧的时候模块级有几个常量指着仓库、
    名单外剩哪一个；拧上之后还剩几个（答：一条都不剩）。哪天有人新加一条 `X = ROOT / ...`
    而没进名单，头那一行会先把那个名字摊出来。
    >>> repo = [n for n, v in live.items() if n.isupper() and isinstance(v, (str, Path))
    ...         and str(v).startswith(str(ROOT))]
    >>> len(repo), [n for n in repo if n not in CELL_BEND_NAMES]
    (8, ['ROOT'])
    >>> with tempfile.TemporaryDirectory() as d:
    ...     with cell_bend(Path(d)):
    ...         sorted(n for n, v in live.items() if n.isupper() and isinstance(v, (str, Path))
    ...                and str(v).startswith(str(ROOT) + "/"))
    []
    """
    saved = [(n, globals()[n]) for n in CELL_BEND_NAMES]
    for name, path in cell_bend_map(tree).items():
        globals()[name] = path
    try:
        yield [n for n, _ in saved]
    finally:
        for name, old in saved:
            globals()[name] = old


def run_cell(cell: Cell, base: Path) -> tuple[str, str, str]:
    """跑一格：`(判定, 给人看的那句, 抹过临时路径的原文)`，判定是 `ok`／`bad`／`skip`。

    走真的 `main()`，不是又调一遍 `build_arg_problems`：那几句判决长在 `cmd_build` 的
    出口上，只调判据就把门口那一层绕开了（与另外几把尺同一口径）。

    **§2.85 的兜底**：真跑之前，本函数体内自己再问一遍「产物要落在哪儿、argv 里那些词指着
    谁」。判据一个字都不读 `cell_guards` 那三本账 —— 只认换好值的 argv、自己这颗沙盒树、
    `SUBCOMMANDS` 与 `ROOT`。为什么要两道各写一遍：闸是**在册**的（旗标会长、账本得有人登记，
    `cell_ledger_covers_parser` 盯的就是这一族漂移），兜底只盯一味药 —— 写在 argv 里的路径
    落不落得进沙盒。§2.84 那台变异机上，一把 `cell_guards → return []` 的刀让说明书里
    `argv=("build",)` 那一格一路走到底、真发了一趟 HTTPS（护栏记到 17 条动作、三条点名
    `ipinfo.io`），要拦的就是那一步。两扇门：写门（`--out` 没钉进沙盒，取的就是仓库默认
    目录）与读门（argv 里任何一个带 `/` 的词展开后落在仓库里 —— 不必认得那是哪个旗标）。
    拦下来时**一个字节都不写、一个包都不出**：判据排在种文件之前。这一句也不是许愿 ——
    `/tmp/zero285.py` 那遍 A/B（16:55，跑在 /tmp 的副本树里，`socket` 那一层换成
    **只记不放**的线）量的是八串：兜底在位的那一遍，八串全部「走进真跑 0 次、沙盒里多出
    0 个件、落进仓库 `data/` 0 项、想出门 0 次」；只把体内那句 `if stop:` 摘掉、同一棵树
    再跑一遍，同一批读成 **8 次／33 个／5 项／3 次**。两遍数字一模一样的串是 **0** 串，
    所以那些「0」每一个都是兜底改写的走向，不是一句「量具没连上」——「拦不拦都一样」
    正是 §2.83 那条「不红时印不印」在这一节的形状。

    同一味药还要在**闸也没了**的那一棵树上量一遍（`/tmp/mut285.py`，跑在 16:58—17:01 之间）：三棵副本树、
    同一个 `argv=("build",)`（就是 §2.84 说明书里那一格，一个字没改）、同一根只记不放的线。
    干净那一棵退 2、屏幕上出现闸那句；只把 `cell_guards` 改成开口就 `return []`（兜底不动）
    读成 **走进真跑 0 次、想出门 0 次**、改由兜底喊停、整扇退 1；闸与兜底一起摘（等于
    §2.84 那一版的行为）同一格读成 **1 次／3 次**，屏幕上却是一个 `✓`。§2.84 写在边界里的
    那句「复发口子本节没有堵：谁再跑一次 M1 的 doctest 门，还是会出网」到这一遍可以收口。
    （同一格在三棵树上「落进仓库」都读 0 —— 那一档两遍一模一样，说的是这一串本身走不到
    写表那一步，不是兜底改写的走向；本节不把它算进兜底的功劳。）上面那两句「到这一遍可以
    收口」到 §2.86 的验收电池里要补一个条件：那只对**只摘闸**那一档成立，把闸与兜底**两条腿
    一起摘**掉还剩 3 次真 HTTPS 出门（`self_test` 说明书里 `argv=("build",)` 那一格，读的是
    仓库那份真源清单）—— 那一档由本节下面那根线接住。

    **§2.87 的第三道腿**（`cell_wire`，就套在下面 `main()` 那一句外面）：真跑那一小段时间里
    在身上再套一根线 —— 把 `socket.getaddrinfo` 与 `socket.socket` 的 `connect`／`connect_ex`
    换成「先点名进 `refusals`、再当场拒」。它补的不是上面那道兜底的缺口，是**两条腿共有的一块
    盲区**：闸与兜底读的都是 argv，而「这一格到底出不出网」还由**种进沙盒的那份配置**说了算。
    普查（`/tmp/census287e.py` → `census287e.out`）量到六串摆法里有一串 —— 三扇开关全递、五个
    路径旗全指沙盒，在闸眼里是**合规格**的、兜底也放行 —— 照样摸了一次它自己那条启用的上游
    （那一遍种的是 `example.invalid`；下面那格现在种回环字面量，理由写在 `CELL_URL_LOOPBACK`
    头上）；把线摘掉，同一串判 **ok、那一句是空的**（体外那根量具替它记下了：六串各一次）。所以这里
    加的是一条判据：`refusals` 非空 ⇒ 这一格判不过，**退码对上了也不过**。
    同一遍还量到一件事：干净那一棵树上它一次都不开火（在册那些格子不碰网络，屏幕上没有一个字
    是它写的），所以钉它的不是 `--self-test` 那一扇，是下面那条例子（它从 `run_cell` 直接进，
    不经过闸）。19:32:44 那一遍验收电池（`/tmp/mut287.py` → `/tmp/mut287g.out`：**12** 把单刀＋
    **3** 把组合＝**15** 把 × 两扇门＝**30** 行读数）里那一栏「线句」把它说清了。那一栏数的是
    doctest 报失败时 **`Got:` 那一面**里「线：这一格想出门」出现几次 —— 只按整屏数会连
    `Expected:` 的回声一起数进去（19:17:30 那一遍就是：W01 把线整个摘掉，屏幕上仍读到 1 次，那一句
    是失败报告替它回显的期望值，不是线说的）。三行对照：**干净** 线句 **0**／回声外也 0（它在
    册的格子里一个字都不写）；**W01**（只摘这处接线）线句 **0**、而外面那根只记不放的线记到
    `getaddrinfo 127.0.0.1` **1** 次 —— 那一次今天由例子红着说；**N01＋N11＋W01**（三条腿全摘）
    屏幕新增点名 **17** 句、线句仍 **0**，外头却记到 **4** 次（`getaddrinfo 127.0.0.1` 1 次＋
    `getaddrinfo raw.githubusercontent.com` **3** 次），那 3 次全走在 `redirect_stdout` 底下、
    屏幕上没有一句说过它们。也就是说：那几趟真出门**从来没有**被哪一扇门的屏幕报过，能报的只有
    这根线；而它唯一一次「只开口不拦人」（W07 只记不拒）也正是靠这一栏读出来的（线句 **1**、
    想出门 **0** —— 那个 0 是量具的盲区，见 §2.87 边界）。
    §2.88 把上面那一行的 4 次改小了：第四道腿（`cell_bend`）在真跑那一格之前就把「仓库那一份」
    换成「沙盒那一份」，所以那 3 次不是被拦下来的，是**根本没走到**；同样这三把刀现在只剩那一
    次故意的 `127.0.0.1`。要把那 3 次请回来，得连第四道腿一起摘 —— 电池里那一行叫「四腿全摘」。

    下面那五条例子摆的全是「该被拒」的写法，每一条都故意带上 `--verify` 与 `--replay`
    那一对 —— 兜底哪天被人删了，它们最坏停在「只能选一个」那一句上。这句话不是许愿：
    16:35 的预检（`/tmp/preflight285.py`，挂在只记不拦的护栏底下、跑在 /tmp 的副本树里）
    量到甲丙丁三串各退 1、`--out` 空着那一串退 2（那是 argparse 自己拦的）、落进仓库 0 件、
    出门 0 行；同一遍的对照「不带那一对、又不递 `--out`」往 `data/output/` 落了 **6 件** ——
    所以那几行「0 件」不是空话。戊／己两串由 16:55 那遍 A/B 量到（摘掉兜底那一遍：举手 1、
    屏幕上出现那句、落进仓库 0 项）。而**庚那种「一个字都不递、开关一个都不带」的写法
    故意不做成例子**：例子是会在别人机器上照跑的，它一删兜底就会走到仓库那一份 —— A/B 那一遍拿
    只记不放的线量到的企图是 3 次 `raw.githubusercontent.com:443`，而 §2.84 的
    15:31 那一遍（真出门、护栏只记不拦）记下的是 3 趟 `ipinfo.io:443`。要拦的就是那一步。

    最后一条例子（数字取成非数字）钉的不是兜底，是**接住 `SystemExit`** 那一句：
    `argparse` 读不下去一串字时是抛码走人、不返回，而这一格只认返回码，所以一格坏 argv
    会把**整扇** `--self-test` 打死在途中。这一条不是推想：A/B 的第一遍（16:51，那棵树里
    还没有这一句 catch）里乙那一串在没有兜底的那一版让整个子进程退 **2**、一句结果都没
    回来；补上 catch 之后 16:55 重跑，同一串读成「退码：期望 1，实际 2」—— 门还开着，
    后面的格子照跑。坏 argv 因此从「砸门」变成「可钉的一格」。
    同一遍里辛那一串（不带那一对、又不递 `--out`）在摘掉兜底的那一版往 `data/` 落了
    **5 项**，被本函数自己那道指纹闸当场喊出「这一格动了仓库 `data/` 里的东西」。
    上面 16:35 那遍预检对同一族写法量到的是 **6 件**：那一遍数的是「副本树里多出或改动的
    件」，这一遍数的是「`data/` 指纹里对不上的项」（指纹连修改时刻一起比），两把尺各量各的，
    本节没有把它们对成同一个数 —— 要用的时候注意是哪一个。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     verdict, why, text = run_cell(Cell(who="举例", what="互斥那一档", rc=1,
    ...         argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_TAIL),
    ...         Path(d))
    >>> verdict, "只能选一个" in text
    ('ok', True)
    >>> with tempfile.TemporaryDirectory() as d:      # 退码对了，盘上却没有那一件：判不符
    ...     verdict, why, _ = run_cell(Cell(who="举例", what="空口无凭", rc=0,
    ...         argv=("build", "--source", "{T}/fake.m3u") + CELL_TAIL,
    ...         files=(("fake.m3u", CELL_FAKE_M3U), ("channels.yaml", CELL_FAKE_CHANNELS)),
    ...         wrote=("out/没有这一件.m3u",)), Path(d))
    >>> verdict, why
    ('bad', '说好了要落的件没落（或落成了空文件）：out/没有这一件.m3u')
    >>> with tempfile.TemporaryDirectory() as d:      # 写门·没递：以前这一串一路走到仓库默认目录
    ...     v, why, _ = run_cell(Cell(who="举例", what="`--out` 没递", rc=1,
    ...         argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_ARGS_BASE),
    ...         Path(d))
    >>> v, why
    ('bad', '兜底：`--out` 没递 —— 取的是仓库默认的产物目录，这一格不跑')
    >>> with tempfile.TemporaryDirectory() as d:      # 写门·递在末位没值：argparse 取默认，同一条路
    ...     v, why, _ = run_cell(Cell(who="举例", what="`--out` 空着", rc=1,
    ...         argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_ARGS_BASE
    ...               + ("--out",)), Path(d))
    >>> v, why
    ('bad', '兜底：`--out` 递在末位或后面紧跟旗标 —— 取的是仓库默认的产物目录，这一格不跑')
    >>> with tempfile.TemporaryDirectory() as d:      # 写门·指到沙盒外（同一颗临时目录的另一头）
    ...     v, why, _ = run_cell(Cell(who="举例", what="`--out` 在沙盒外", rc=1,
    ...         argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_ARGS_BASE
    ...               + ("--out", str(Path(d) / "elsewhere"))), Path(d))
    >>> v, why
    ('bad', '兜底：`--out` 不在这颗沙盒底下（<沙盒>/elsewhere）—— 这一格不跑')
    >>> with tempfile.TemporaryDirectory() as d:      # 同一个旗标递两遍：后写的那条也算（写门）
    ...     v, why, _ = run_cell(Cell(who="举例", what="两条 `--out`，后写的在仓库", rc=1,
    ...         argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_TAIL
    ...               + ("--out", "data/output")), Path(d))
    >>> v, why
    ('bad', '兜底：`--out` 不在这颗沙盒底下（data/output）—— 这一格不跑')
    >>> with tempfile.TemporaryDirectory() as d:      # 读门：一个旗标名都不必认得，只看词落在哪
    ...     v, why, _ = run_cell(Cell(who="举例", what="`--source` 指着仓库产物", rc=1,
    ...         argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_TAIL
    ...               + ("--source", "data/output/hunan.m3u")), Path(d))
    >>> v, why
    ('bad', '兜底：data/output/hunan.m3u 指着仓库里的东西 —— 这一格不跑')
    >>> with tempfile.TemporaryDirectory() as d:      # 第三道腿·闸放行的那一串：沙盒里源是启用的
    ...     v, why, text = run_cell(Cell(who="举例", what="想取沙盒里那条启用上游", rc=1,
    ...         argv=("build",) + CELL_TAIL,
    ...         files=(("sources.yaml", CELL_SOURCES_ON),)), Path(d))
    >>> v, why                       # 退码对上了也不过：那一格期望 1、真跑的也是 1，
    ('bad', '线：这一格想出门 1 次（getaddrinfo 127.0.0.1）—— 被体内那根线当场拒了')
    >>> "127.0.0.1" in text          # 屏幕上那句降级话照旧由 `collect` 说（线只管点名）
    True
    >>> [n for n in ("CELL_PATH_FLAGS", "CELL_SWITCHES", "CELL_LOCAL_PATH_FLAGS",
    ...              "cell_guards")                  # 那根线不读账本，也不问闸（独立第三条腿）
    ...  if n in cell_wire.__code__.co_names]
    []
    >>> "cell_bend" in run_cell.__code__.co_names    # 第四道腿确实接在下面真跑那一小段上
    True
    >>> with tempfile.TemporaryDirectory() as d:      # 不走 `cmd_build` 的那几格：兜底不开火
    ...     v, why, _ = run_cell(Cell(who="举例", what="拼错的子命令", rc=2,
    ...         argv=("bulid",), has=("未知的子命令",)), Path(d))
    >>> v, why
    ('ok', '')
    >>> with tempfile.TemporaryDirectory() as d:      # `argparse` 抛码走人：接住，别把整扇门打死
    ...     v, why, text = run_cell(Cell(who="举例", what="数字取成非数字", rc=2,
    ...         argv=("build", "--max-lines", "很多") + CELL_TAIL), Path(d))
    >>> v, "invalid int value" in text
    ('ok', True)
    >>> [n for n in ("CELL_PATH_FLAGS", "CELL_SWITCHES", "CELL_LOCAL_PATH_FLAGS",     # 兜底不读账本
    ...              "cell_guards", "cell_argv_words", "cell_flag_value")
    ...  if n in run_cell.__code__.co_names]
    []
    """
    tree = base / "tree"
    argv = cell_argv(cell, tree)
    refusals: list[str] = []               # §2.87 那根线的点名册：真跑那一小段时间里谁摸过出口
    # ———— §2.85 的兜底：只认 argv 与这棵树，不读 `cell_guards` 那三本账（理由见说明书）————
    w: list[str] = []
    for a in argv:                      # `--旗=值` 折成两个字：与闸同一形状，**故意重抄一份**
        w += a.split("=", 1) if a.startswith("--") and "=" in a else [a]
    stop = ""
    if w and w[0] in SUBCOMMANDS:       # 不走 `cmd_build` 的那几格没有产物目录可管
        here = tree.resolve()
        spots = [i for i, a in enumerate(w) if a == "--out"]
        nxt = w[spots[-1] + 1] if spots and spots[-1] + 1 < len(w) else ""
        val = "" if not spots or nxt.startswith("-") else nxt
        if not val:                     # 写门·没值：argparse 就用起手的默认目录
            stop = ("兜底：`--out` " + ("没递" if not spots else "递在末位或后面紧跟旗标")
                    + " —— 取的是仓库默认的产物目录，这一格不跑")
        elif here != Path(val).resolve() and here not in Path(val).resolve().parents:
            stop = (f"兜底：`--out` 不在这颗沙盒底下（{hide_tmp(val, base)}）"
                    "—— 这一格不跑")
        else:                           # 写门锁住了，才轮得到读门
            for a in w:
                if a.startswith("-") or "/" not in a:
                    continue
                q = (Path(a) if Path(a).is_absolute() else Path.cwd() / a).resolve()
                if q == here or here in q.parents:
                    continue
                if q == ROOT or ROOT in q.parents:
                    stop = f"兜底：{a} 指着仓库里的东西 —— 这一格不跑"
                    break
    if stop:
        return "bad", stop, ""
    tree.mkdir(parents=True, exist_ok=True)
    try:
        for rel, body in cell_files(cell):
            p = tree / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
    except OSError as e:
        return "skip", f"种不出来，这一格没验成：{e}", ""
    before = data_fingerprint()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with cell_wire(refusals), cell_bend(tree):     # 第三／四道腿：只在这一小段在身上
                rc = main(list(argv))
    except SystemExit as e:                       # `argparse` 读不下去一串字时是「抛码走人」，不返回。
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        # 不接住它，一整扇 `--self-test` 会被一格坏 argv 打死（§2.85 那遍 A/B 里，摘掉兜底
        # 那一遍的乙就是这么让子进程退 2、一句 RESULT 都没回来）。接住之后这一格照旧按
        # 「退码对不对」判 —— 坏 argv 从「砸门」变成「可钉的一格」。
    except Exception as e:                        # noqa: BLE001  本件炸了算「跑过但不过」
        return "bad", (f"跑这一格时抛了 {type(e).__name__}: {e}"
                       + (f"；{cell_wire_note(refusals)}" if refusals else "")), ""
    text = hide_tmp(buf.getvalue(), base)
    if refusals:                                  # 想出门 = 这一格没过，退码对上了也不过（戊 量到）
        return "bad", cell_wire_note(refusals), text
    if data_fingerprint() != before:
        return "bad", "这一格动了仓库 `data/` 里的东西（名字/字节/修改时刻对不上）", text
    if rc != cell.rc:
        return "bad", f"退码：期望 {cell.rc}，实际 {rc}", text
    for frag in cell.has:
        if frag not in text:
            return "bad", f"少了那句：{frag}", text
    for frag in cell.lacks:
        if frag in text:
            return "bad", f"多说了那句：{frag} —— 误伤", text
    for rel in cell.wrote:
        p = tree / rel
        if not p.is_file() or p.stat().st_size == 0:
            return "bad", f"说好了要落的件没落（或落成了空文件）：{rel}", text
    for rel in cell.absent:
        if (tree / rel).exists():
            return "bad", f"这一格不该落盘，落了：{rel}", text
    return "ok", "", text


# 跑之前写死的期望（不是「跑一遍看看像什么再抄下来」；`has` 里每一截都能在
# §2.81 那张 18 档表里指到「哪一句」。行号本节故意不写：它跟着文件长，
# 而这一件天天在长 —— 抄一个没人重算的数，就是本册 §2.60 那把尺要抓的那一种病。
BASELINE: tuple[Cell, ...] = (
    Cell(who="互斥", what="`--verify` 与 `--replay` 一起递：碰网络之前先拦", rc=1,
         argv=("build", "--verify", "--replay", "{T}/probe.json") + CELL_TAIL,
         has=("--verify 与 --replay 只能选一个",), lacks=("这一轮不出表。",)),
    Cell(who="max-lines 0", what="`--max-lines 0`：那张等于空表的数字在写盘之前就被拦下",
         rc=1, argv=("build", "--max-lines", "0") + CELL_TAIL,
         has=("这一轮不出表。", "--max-lines 是 0")),
    Cell(who="max-per-host 0", what="`--max-per-host 0`：同一主机留 0 条也是同一种坏法",
         rc=1, argv=("build", "--max-per-host", "0") + CELL_TAIL,
         has=("这一轮不出表。", "--max-per-host")),
    Cell(who="out 是文件", what="`--out` 指到一个普通文件上：不许走到 mkdir 才崩",
         rc=1, argv=("build", "--config", "{T}/channels.yaml", "--sources-file",
                     "{T}/sources.yaml", "--epg-file", "{T}/epg.yaml", "--history",
                     "{T}/hist.jsonl", "--skip-local", "--no-epg", "--no-egress-check",
                     "--out", "{T}/blocked"),
         files=(("blocked", "我不是目录\n"),), has=("是一个文件，不是放产物的目录",)),
    Cell(who="try-reach 不在", what="`--try-reach` 那份候选规则根本不存在",
         rc=1, argv=("build", "--try-reach", "{T}/nope.yaml") + CELL_TAIL,
         has=("不是一份读得进来的文件",)),
    Cell(who="config 不在", what="`--config` 指到不存在的路径",
         rc=1, argv=("build", "--config", "{T}/nope.yaml", "--sources-file",
                     "{T}/sources.yaml", "--epg-file", "{T}/epg.yaml", "--history",
                     "{T}/hist.jsonl", "--skip-local", "--no-epg", "--no-egress-check",
                     "--out", "{T}/out"),
         has=("表上的台全部来自这份名单",)),
    Cell(who="config 不是 YAML", what="`--config` 那份 YAML 本身读不进来",
         rc=1, argv=("build", "--config", "{T}/channels.yaml", "--sources-file",
                     "{T}/sources.yaml", "--epg-file", "{T}/epg.yaml", "--history",
                     "{T}/hist.jsonl", "--skip-local", "--no-epg", "--no-egress-check",
                     "--out", "{T}/out"),
         files=(("channels.yaml", "version: 1\ngroups: [\n"),),
         has=("表上的台全部来自这份名单",)),
    Cell(who="config 缺分组", what="合法但少三个 hunan 分组的频道配置：先说再走",
         rc=1, argv=("build", "--config", "{T}/channels.yaml", "--sources-file",
                     "{T}/sources.yaml", "--epg-file", "{T}/epg.yaml", "--history",
                     "{T}/hist.jsonl", "--skip-local", "--no-epg", "--no-egress-check",
                     "--out", "{T}/out"),
         files=(("channels.yaml", cell_channels_yaml(("hunan_local",))),),
         has=("就是按这四个分组切的",)),
    Cell(who="源清单不在", what="`--sources-file` 指到不存在的路径（走 `stop_config` 那一句）",
         rc=1, argv=("build", "--config", "{T}/channels.yaml", "--sources-file",
                     "{T}/nope.yaml", "--epg-file", "{T}/epg.yaml", "--history",
                     "{T}/hist.jsonl", "--skip-local", "--no-epg", "--no-egress-check",
                     "--out", "{T}/out"),
         has=("读不了：", "这一轮不出表 —— ")),
    Cell(who="源全关掉", what="源清单读得进来但一条启用的都没有",
         rc=1, argv=("build", "--config", "{T}/channels.yaml", "--sources-file",
                     "{T}/sources.yaml", "--epg-file", "{T}/epg.yaml", "--history",
                     "{T}/hist.jsonl", "--skip-local", "--no-epg", "--no-egress-check",
                     "--out", "{T}/out"),
         has=("里没有启用的源",),
         # 这一条 `lacks` 钉的是本节修掉的那个 bug：那句话以前写死成 `config/sources.yaml`，
         # 于是 `--sources-file` 指到别处时它指着**没有的那一份**说话。只钉「没有启用的源」
         # 抓不到它 —— 换回写死那份，句尾一模一样。要抓就得钉句首那个名字。
         lacks=("config/sources.yaml 里没有启用的源",)),
    Cell(who="走通到出表", what="一份假上游走完整条路：四张表落盘，屏幕上说的是谁",
         rc=0, argv=("build", "--source", "{T}/fake.m3u") + CELL_TAIL,
         files=(("fake.m3u", CELL_FAKE_M3U), ("channels.yaml", CELL_FAKE_CHANNELS)),
         has=("读取 1 个上游", "输出到", "aptv.m3u  : 3 个频道", "hunan.m3u : 3 个频道",
              "丢弃：黑名单 0 条，未匹配 1 条", "第一线集中度（aptv.m3u 全量）",
              "第一线集中度（hunan.m3u 湖南本地）", "节目单：未启用"),
         lacks=("本轮一个台都没归上", "线路判决把测过的"),
         wrote=("out/aptv.m3u", "out/hunan.m3u", "out/hunan-lean.m3u", "out/test.m3u",
                "out/report.md")),
    Cell(who="一个台都没归上", what="名单与上游对不上：不许拿一张空表盖掉订阅目录",
         rc=1, argv=("build", "--source", "{T}/fake.m3u") + CELL_TAIL,
         files=(("fake.m3u", CELL_FAKE_M3U),),
         has=("本轮一个台都没归上", "这一轮不出表 —— "),
         absent=("out",)),
    Cell(who="判决全灭", what="沿用的记录把测过的全判成不能用：剩下来的台靠「没测过」",
         rc=1, argv=("build", "--source", "{T}/fake.m3u", "--replay", "{T}/probe.json",
                     "--replay-max-age", "1000000") + CELL_TAIL,
         files=(("fake.m3u", CELL_FAKE_M3U), ("channels.yaml", CELL_FAKE_CHANNELS),
                ("probe.json", CELL_PROBE_ALL_DEAD)),
         has=("线路判决沿用", "全判成不能用", "这一轮不出表 —— "),
         absent=("out",)),
    Cell(who="沿用空记录", what="--replay 那份记录里一条判决都没有：闸要拦住，不许静默降级",
         rc=1, argv=("build", "--source", "{T}/fake.m3u", "--replay", "{T}/probe.json",
                     "--replay-max-age", "1000000") + CELL_TAIL,
         files=(("fake.m3u", CELL_FAKE_M3U), ("probe.json", CELL_PROBE_EMPTY)),
         has=("那份记录不能用", "一条逐条判决都没有"),
         lacks=("线路判决沿用",), absent=("out",)),
    Cell(who="子命令拼错", what="`bulid`：拼错的子命令退 2，不顺手退 0", rc=2,
         argv=("bulid",), has=("未知的子命令",)),
    Cell(who="没给子命令", what="一个字都不递：那是想看用法说明，退 0", rc=0,
         argv=(), has=(), lacks=("未知的子命令",)),
    Cell(who="薄门不收字", what="`--self-test` 旁边递了字：整扇不答，点名那些字（2.77 那一族）",
         rc=2, argv=(SELF_TEST_FLAG, "--out"), has=("这一扇体内不收任何参数",)),
)


class GuardCase(NamedTuple):
    """给闸出的一道题：这一串 argv 递进去，**必须**点名，而且必须喊出 `must` 里那几截话。

    与 `Cell` 差在一件事：`Cell` 是「跑一格，对屏幕与盘上的期望」，`GuardCase` **根本不跑**。
    它比的只有 `cell_guards` 那张嘴 —— 所以它没有 `rc`／`files`／`has`／`wrote` 那一整排
    字段，那些字段在这里全没有意义（这一档不起进程、不碰盘、不出网）。

    >>> GuardCase(who="举例", argv=("build",), must=("x",)).argv
    ('build',)
    """

    who: str                                  # 题号：这道题摆的是哪一种坏法
    argv: tuple[str, ...]                     # 递给 `cell_guards` 的原样一串
    must: tuple[str, ...]                     # 闸的点名叫里必须有那几截（一句都不许多）


# §2.86：闸自己那一档的题目本。九串的来路分两笔（17:54 那一遍现量，`/tmp/head286.out`）：
# §2.84 那次普查（`/tmp/hole284.out`，15:52）量到的**六样危险摆法**里，有四样在这里原样各占一串
# —— ①`--replay` 空着递＝第 6 串、②`--source` 指着仓库产物＝第 5 串、③`--try-reach` 指着仓库
# 规则＝第 9 串、④`--旗=值` 那一式＝第 4 串；第五样「同一个旗标递两遍」在这里换成了 `--out`
# （第 3 串，同一族、换了旗标名），第六样「`--source` 递两条、第二条在仓库」今天没进本子。
# 剩下四串（第 1、2、7、8）在 §2.84 之前闸就点得名 —— 留着它们是因为题目本要盖的是闸的**每一扇**
# 门，不只是它新学的那几样。同一遍量到：这九串递给 `HEAD`（`862cf38`，已含 §2.84 的三样补全）
# 与盘上这一版，两版各点 9／9、**静默 0 串**。每串的 `must` 抄的是闸**印在屏幕上的原话**（不是
# 旗标名，也不是账本里那句理由的副本 —— 见下面说明书里「为什么允许手抄」那一段）：17:55:49 那一遍
# （`/tmp/must286.out`）把两样并排印了一遍，闸共点 16 条、16 条全落在某一截 `must` 里、一条不多。
CELL_GUARD_CASES: tuple[GuardCase, ...] = (
    GuardCase(who="什么都不递", argv=("build",),
              must=("没递 --out", "没递 --config", "没递 --sources-file", "没递 --epg-file",
                    "没递 --history", "没递 --skip-local", "没递 --no-epg",
                    "没递 --no-egress-check")),
    GuardCase(who="`--out` 指着仓库产物目录", argv=("build",) + CELL_ARGS_BASE
              + ("--out", "data/output"),
              must=("`--out` 没指进这一格的沙盒", "data/output")),
    GuardCase(who="同一个 `--out` 递两遍、后写的在仓库", argv=("build",) + CELL_TAIL
              + ("--out", "data/output"),
              must=("`--out` 没指进这一格的沙盒", "data/output")),
    GuardCase(who="`--旗=值` 那一式", argv=("build",) + CELL_ARGS_BASE + ("--out=data/output",),
              must=("`--out` 没指进这一格的沙盒", "data/output")),
    GuardCase(who="`--source` 指着仓库那份真产物", argv=("build",) + CELL_TAIL
              + ("--source", "data/output/hunan.m3u"),
              must=("`--source` 没指进这一格的沙盒", "data/output/hunan.m3u")),
    GuardCase(who="`--replay` 空着递", argv=("build", "--replay") + CELL_TAIL,
              must=("`--replay` 没指进这一格的沙盒", "递的是 空", "data/output/probe.json")),
    GuardCase(who="递了 `--fresh`", argv=("build",) + CELL_TAIL + ("--fresh",),
              must=("递了 --fresh",)),
    GuardCase(who="单递 `--verify`、没配 `--replay`", argv=("build", "--verify") + CELL_TAIL,
              must=("递了 --verify 又没配 --replay",)),
    GuardCase(who="`--try-reach` 指着仓库那份候选规则", argv=("build",) + CELL_TAIL
              + ("--try-reach", "config/reachability.yaml"),
              must=("`--try-reach` 没指进这一格的沙盒", "config/reachability.yaml")),
)


def cell_guard_covers_ledger(cases: Iterable[GuardCase] = CELL_GUARD_CASES) -> list[str]:
    """**考题本覆没覆到那三本账**：账本里每一个旗标名，至少被一串题的某截 `must` **整词**提到。

    它与 `cell_ledger_covers_parser` 是一对姊妹：那一道问「账本 ↔ `build_parser()`」（闸有没有
    漏掉一个真存在的旗标），这一道问「账本 ↔ 题目本」（考题有没有漏掉闸已经认的一扇门）。它钉的
    是**这一档自己的来路**：`must` 是手抄的（上面「为什么允许手抄」那一段说清了什么时候允许），
    而手抄唯一的代价就是「抄的人漏了一行」—— 账本**添**一条而没人跟着抄，`must` 那一条判据会红；
    账本**减**一条而考题跟着少一截，今天没人看。这一道补的就是那半句。

    「整词」那条不是装饰：`--source` 恰好是 `--sources-file` 的前缀。18:02 那一遍
    （`/tmp/word286.out`：11 个旗标名、题目本 23 截 `must`）量到 `--source` 按整词提到 **1** 截、
    按子串提到 **2** 截 —— 多出来那一截就是「没递 --sources-file」。下面第三条例子钉的正是这个差，
    它与 §2.83 当年拒掉「别名子串匹配」是同一个道理：一个名字是另一个的前缀时，子串数会替人撒谎。

    >>> cell_guard_covers_ledger()
    []
    >>> len(cell_guard_covers_ledger([GuardCase(who="只提一个旗标", argv=("build",),
    ...                                         must=("没递 --out",))]))
    10
    >>> got = cell_guard_covers_ledger([GuardCase(who="只有子串", argv=("build",),
    ...     must=("没递 --sources-file",))])
    >>> any("`--source`" in x for x in got), any("--sources-file" in x for x in got)
    (True, False)
    >>> [n for n in ("run_cell", "cell_guards", "subprocess")     # 它连闸都不问，只比名单
    ...  if n in cell_guard_covers_ledger.__code__.co_names]
    []
    """
    got = [c for c in cases]
    names = [f[0] for f in CELL_PATH_FLAGS] + [f[0] for f in CELL_SWITCHES] \
        + [f[0] for f in CELL_LOCAL_PATH_FLAGS]
    return [f"考题本没盖到：账本里的 `{n}` 没有任何一串题提到它"
            f"（{len(got)} 串题的 must 里整词都找不到）"
            for n in names
            if not any(re.search(re.escape(n) + r"(?![-\w])", frag) for c in got for frag in c.must)]


def cell_guard_cases(cases: Iterable[GuardCase] = CELL_GUARD_CASES,
                     compliant: Iterable[Cell] = BASELINE) -> list[str]:
    """**闸自己那一档**：把 `CELL_GUARD_CASES` 那九串一句句递给闸，看它点不点名。应该是空表。

    这一档为什么必须存在：§2.84 量过「把 `cell_guards` 摘掉，`--self-test` 那一扇一把都听不见」
    （十六把里只有 M9 那一把「不分子命令全查」响，因为那 17 格本来就全过闸 —— 闸坐在它们
    **上游**，所以这一扇只看得见过火，看不见不及格）。那道口子是 §2.84 自己划的，而且是两句：
    边界第（2）条「要让 `--self-test` 也能钉这道闸，缺一类格子」，下一步第（3）条「**造一类
    『故意坏』的格子**，让 `--self-test` 也进这道闸的量程」。§2.85 接的是它的第（1）条（那道兜底），
    第（3）条原样留在原地没人接 —— 本节接的就是它。先量那句话有多重，两件事都是量出来的不是想出来的：

    **甲 那一类格子加不进 `BASELINE`。** 闸的拒是**整批**的（`self_test` 里一条不合规就
    `return 2`），17:33 那一遍（`/tmp/census286c.out`）往 `BASELINE` 上添一格「故意坏」的读到
    退 **2**、屏幕上 **0** 行 ✓、那句「扫了基线」的结论行**根本不印**、闸只点了那一格自己的
    **8** 条 —— 也就是说那一格一加，`BASELINE` 里原本那 17 个从此不再跑，那三处写着
    「17 格」的话（`selfcheck` 的两处与 `code_claims` 的一处）跟着一起变成假话。
    所以这一档**自成一批**，不进 `BASELINE`。

    **乙 这一档不能靠「跑一格看它被拦」来钉。** `run_cell` 那一侧有 §2.85 的兜底，但兜底
    **只认路径**：同一遍普查里三串「路径全合规、只坏在出网旗标」的摆法被兜底放行、真走进了
    `cmd_build`，其中单递 `--verify` 那一串被只记不放的线量到想出门 **6** 次（`127.0.0.1`、
    `tvgslb.hn.chinamobile.com`、`www.baidu.com`、`www.qq.com`），`--fresh` 配一条启用的源
    那一串想出门 **1** 次（`example.invalid`）。那两种摆法也正是 §2.84 记下的「以前没人钉」
    那两把真漏 —— M6_摘fresh闸 对的是下面第 7 串、M10_摘末位没值 对的是第 6 串那句
    「递的是 空」。所以这一档只问 `cell_guards` 那张嘴：**一次格子都不跑**。
    下面那条例子把这件事钉成结构（`co_names` 里不许出现 `run_cell`）：它与 §2.85 给兜底装的
    那条例子是同一条道理 —— 「这一档不会去干别人的活」不写进例子，就只是一句许愿。

    **丙 这一档也不替兜底看门。** 电池最后一行是一把「两条腿一起摘」（`N01` 与 `N11` 同装）：
    17:47 头一遍（`/tmp/mut286d.out`）、17:48 追问是哪一格（`/tmp/which286.out`）、18:01 整遍复跑
    （`/tmp/mut286e.out`）三遍同读 —— `--self-test` 那 17 格照旧读到 **0** 次想出门，而 doctest
    那一扇门读到 **3** 次 `raw.githubusercontent.com`：那三次来自 `run_cell` 说明书里那几串
    「本该被兜底拒掉」的例子，两条腿都没了它们就走进 `cmd_build` 去抓节目单。闸好的时候这一档
    是绿的，它看不见那一步。

    判据三条，缺一算不对：这一串**得被点名**；`must` 里每一截都得出现在某一条点名叫里；
    而闸点名的**每一条**都得能被某一截 `must` 对上 —— 第三条管的是「账上多了一条而没人预期」，
    第二条管的是「账上少了一条」，两条合起来才敢让 `must` 是手抄的。最后本函数尾巴上还接了
    第四道（`cell_guard_covers_ledger`）：那三本账里每一个旗标名都得被**在册那份**题目本提到 ——
    它不读传进来的 `cases`，所以上面那几例「故意做坏的考题」不会被它污染。

    为什么允许手抄：§2.42 那条「不抄第二份名单」管的是**代码自己要用那份名单**的场合
    （抄了就等于造一处会忘记改的地方）；这里的 `must` 是**给闸出的考题**，与 `BASELINE` 里
    那些 `has` 同一性质 —— 它不需要与账本自动同步，它需要的是「账本动了而没人改考题 ⇒ 这一档红」。
    漂移那一族今天由两姊妹各看一头：「账本 ↔ `build_parser()`」归 `cell_ledger_covers_parser`，
    「账本 ↔ 题目本」归本函数尾巴上那道（判据只认整词，`--source` 不算 `--sources-file` 的账）。

    两个参数**都有默认值**，而默认值就是本节要钉的那两样东西。它们存在的唯一理由是「判据自己
    得能被单独钉住」：18:01 那一遍电池（`/tmp/mut286e.out`）量到，把这一档自己的判据摘掉任何一处
    —— N13 少喊／N14 多喊／N15 过火／N16 第四道的接线／N17 整词那条界线 —— `--self-test` 那一扇
    **一律不响**（退 **0**），因为闸此刻是好的、摘判据不改变屏幕上的任何读数；响的全是 doctest
    那一扇，红用例 **1／3／1／1／1** 例，而这五处红的例子全在这两份说明书里（N17 那一例在
    `cell_guard_covers_ledger` 的第三例）。有了这两个口子，同一件事不必等一把坏刀才显形。

    >>> cell_guard_cases()
    []
    >>> len(CELL_GUARD_CASES) >= 8 and all(c.must and c.argv for c in CELL_GUARD_CASES)
    True
    >>> len({c.who for c in CELL_GUARD_CASES}) == len(CELL_GUARD_CASES)   # 题号不许重复
    True
    >>> all(cell_guards([Cell(who=c.who, what="", rc=1, argv=c.argv)]) for c in CELL_GUARD_CASES)
    True
    >>> [n for n in ("run_cell", "self_test", "subprocess", "tempfile")    # 这一档一个格子都不跑
    ...  if n in cell_guard_cases.__code__.co_names]
    []
    >>> bad = cell_guard_cases([GuardCase(who="考题本身", argv=("build", "--verify") + CELL_TAIL,
    ...                                   must=("这句闸不会说的话",))])
    >>> len(bad), "该点名的那句" in bad[0], "闸多喊了一条" in bad[1]
    (2, True, True)
    >>> bad2 = cell_guard_cases([GuardCase(who="多出来的一条", argv=("build",) + CELL_TAIL
    ...                                     + ("--fresh", "--verify"), must=("递了 --fresh",))])
    >>> len(bad2), "闸多喊了一条" in bad2[0]
    (1, True)
    >>> bad3 = cell_guard_cases([], compliant=(Cell(who="甲", what="没指进沙盒", rc=1,
    ...                                              argv=("build",)),))
    >>> len(bad3), bad3[0].startswith("闸过火：那一批 1 格里 1 格被冤枉")
    (1, True)
    >>> len(cell_guard_cases([GuardCase(who="只提一个旗标", argv=("build",),   # 第四道不读 `cases`
    ...                                 must=("没递 --out",))]))               # 只 7 句「多喊」
    7
    >>> "cell_guard_covers_ledger" in cell_guard_cases.__code__.co_names       # 尾巴上那一道接上了
    True
    """
    bad: list[str] = []
    for case in cases:
        named = cell_guards([Cell(who=case.who, what="", rc=1, argv=case.argv)])
        if not named:
            bad.append(f"闸自己：{case.who} —— 这一串闸一个字都没点，它以为这一串是合规的")
            continue
        for frag in case.must:
            if not any(frag in line for line in named):
                bad.append(f"闸自己：{case.who} —— 该点名的那句「{frag}」没出现（闸点了 {len(named)} 条）")
        for line in named:
            if not any(frag in line for frag in case.must):
                bad.append(f"闸自己：{case.who} —— 闸多喊了一条没人预期的话：{line}")
    batch = list(compliant)                # 先落成一串：`Iterable` 迭代两遍会空
    wrong = [c for c in batch if cell_guards([c])]
    if wrong:
        bad.append(f"闸过火：那一批 {len(batch)} 格里 {len(wrong)} 格被冤枉"
                   f" —— 头一格是「{wrong[0].who}」")
    bad += cell_guard_covers_ledger()      # 读的是**在册那份**题目本，不是传进来的 `cases`
    return bad


def self_test(cells: tuple[Cell, ...] | None = None) -> int:
    """`--self-test`：逐格把 `BASELINE` 那一整片跑一遍，对**跑之前**写死的期望。

    顺序是定过的：过的一格一行先流水，不符期望的留在最后（跑整条基线的工具失败时只摊出
    末尾几行，把 ✗ 挤在 ✓ 中间，那句 ✗ 到人眼前就只剩一个「退 1」）。
    §2.86 在这一扇最前面加了一档「闸自己」：它只问 `cell_guards` 那张嘴与那三本账的名字，
    一次格子都不跑；干净时占流水第一行，不干净时摊在最后那一段里，**不算进「扫了基线 N 格」那个 N**。

    >>> len({c.who for c in BASELINE}) == len(BASELINE)      # 格子名不许重复（顿号那道闸管不着）
    True
    >>> all(c.has or c.lacks or c.wrote or c.absent for c in BASELINE)   # 不许有「什么都对不上」的格
    True
    >>> cell_guards(BASELINE)                                 # 写下来的每一格都得过自己的闸
    []
    >>> with tempfile.TemporaryDirectory() as d:              # 闸拦下的那一遍：整片不跑，退 2
    ...     buf = io.StringIO()
    ...     with contextlib.redirect_stdout(buf):
    ...         rc = self_test([Cell(who="甲", what="没指进沙盒", rc=1, argv=("build",))])
    >>> rc, "这一片不跑" in buf.getvalue(), "没递 --out" in buf.getvalue()
    (2, True, True)
    """
    cells = BASELINE if cells is None else cells
    if not cells:
        print("一格都没有：`BASELINE` 是空的。这不算过")
        return 2
    g_bad = cell_guard_cases(compliant=cells)      # 过火那一半问的是**这一遍真要用到的那一批**
    if not g_bad:
        print(f"  ✓ {'闸自己':<18} {len(CELL_GUARD_CASES)} 串坏摆法各被点了名、"
              f"这一批 {len(cells)} 格一个都没冤枉、那三本账里 "
              f"{len(CELL_PATH_FLAGS) + len(CELL_SWITCHES) + len(CELL_LOCAL_PATH_FLAGS)} "
              f"个旗标名题目本全提到（这一档只问闸那张嘴，一次格子都不跑）")
    guards = cell_guards(cells)
    if guards:
        print("这一片不跑，先把那几格改成指进沙盒、关上出网的门：")
        for g in guards:
            print(f"  · {g}")
        for line in g_bad:            # 闸过火时那一档跟着摊出来，否则它被这一句挤到人眼看不见的地方
            print(f"  ✗ {line}")
        return 2
    ran = bad = skipped = 0
    fails: list[tuple[Cell, str, str]] = []
    for cell in cells:
        with tempfile.TemporaryDirectory(prefix="cli-selftest-") as td:
            verdict, why, text = run_cell(cell, Path(td))
        if verdict == "skip":
            skipped += 1
            continue
        ran += 1
        if verdict == "bad":
            bad += 1
            fails.append((cell, why, text))
            continue
        print(f"  ✓ {cell.who:<18} {cell.what}")
    if fails:
        print(f"\n—— 以下 {len(fails)} 格不符期望（每格把自己那一遍的原文摊出来）——")
        for cell, why, text in fails:
            print(f"  ✗ {cell.who:<18} {cell.what}\n      {why}")
            for line in text.strip().splitlines():
                print(f"      | {line}")
    if g_bad:
        print(f"\n—— 闸自己这一档：{len(CELL_GUARD_CASES)} 串里 {len(g_bad)} 处不对"
              "（那一档不跑格子，只对 `cell_guards` 那张嘴）——")
        for line in g_bad:
            print(f"  ✗ {line}")
    print(f"\n扫了基线 {len(cells)} 格：{bad} 格不符期望"
          + (" —— 那几扇门还认得路" if ran and not bad and not g_bad else " —— 上面逐格点名了")
          + (f"（另有 {skipped} 格没验成）" if skipped else ""))
    if not ran:
        print("一格都没跑起来：临时目录建不起来，或者每一格都被 `run_cell` 跳过了。这不算过")
        return 2
    return 1 if (bad or g_bad) else 0


SUBCOMMANDS = ("build",)


def main(argv: list[str]) -> int:
    """入口：只有 `build` 一个子命令。

    没给子命令（或 `-h`）就打印上面那份用法说明并退 0 —— 那是「人想看帮助」。
    **拼错的子命令退 2**，不再顺手退 0：以前 `python -m src.cli bulid --verify` 也退 0，
    于是它前面挂的 `&&` 会照样往下走，屏幕上滚过的还是那段人写的说明，
    没有任何一处告诉你说这条命令其实根本没跑（计划书 2.21 那把尺拿假文档试出来的就是它）。

    >>> main(["bulid", "--verify"])      # 拼错：非 0；那句说明走 stderr，doctest 看不见
    2
    >>> import contextlib, io
    >>> with contextlib.redirect_stdout(io.StringIO()): a, b = main([]), main(["-h"])
    >>> (a, b)                           # 想看用法说明的两条路仍是 0
    (0, 0)
    """
    # 2.82：本件自己的回归基线走这一扇薄门（与另外十把尺同一口径：一屏只答一扇，
    # 递在旁边的字当场点名，不静默少跑一整片格子）。
    if argv and argv[0] == SELF_TEST_FLAG:
        if len(argv) > 1:
            print(f"{SELF_TEST_FLAG} 这一扇体内不收任何参数（多递的是 "
                  f"{'、'.join(argv[1:])}）；只想跑用例就递 --doctest", file=sys.stderr)
            return 2
        return self_test()
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    if argv[0] not in SUBCOMMANDS:
        print(f"未知的子命令 {argv[0]!r}（只认 {'、'.join(SUBCOMMANDS)}）；"
              "看用法说明跑 python -m src.cli --help", file=sys.stderr)
        return 2
    return cmd_build(argv[1:])


if __name__ == "__main__":
    # `src.cli` 的入口是自己手写的子命令分派（没有 argparse），所以它认这一旗走
    # `run_doctests.doctest_gate` 那道门 —— 与另外 11 件「挂进 parser」的写法不同，
    # 理由写在那一件的说明书里。`scripts/` 得先进搜索路径：这一件是按包跑的（`-m src.cli`）。
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_doctests import doctest_gate                       # noqa: E402
    rc = doctest_gate(sys.argv[1:])
    raise SystemExit(rc if rc is not None else main(sys.argv[1:]))
