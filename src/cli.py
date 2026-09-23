"""命令行入口。

用法：

    python -m src.cli build                  # 用 data/cache 里的上游缓存离线生成
    python -m src.cli build --fresh          # 联网抓 config/sources.yaml 里启用的源
    python -m src.cli build --verify         # 生成前实测线路（probe:false 的源跳过）
    python -m src.cli build --source <url或文件>   # 临时换上游，忽略 sources.yaml

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

注意：联网抓取与 --verify 实测都从本机出口出去，所以测量点是谁必须先说清楚。
代理客户端的 TUN 一开，DNS 就被换成 fake-IP、出口跑到境外机房，对国内运营商类地址
全是假阴性（计划书 2.8）。跑 --verify 前会先做体检并把警告打在屏幕上，
出口身份和逐条结果一起写进 data/output/probe.json。
2026-09-21 起：TUN 关掉后本机出口就是家里的联通宽带，与 Apple TV 同一张网，
这时的实测数字可以直接当判据。

体检报警的那一轮 `--verify` 只写履历，产物（两张 m3u + probe.json + report.md）关进
`data/output/untrusted/`，`data/output/` 保持上一轮可信版本 —— 因为 `--verify` 会删线路，
而局域网服务正把 `data/output/` 当订阅目录发给电视（见 `artifact_dir()`）。
确实要在别的测量点上出表就加 `--allow-untrusted`。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
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
    AUDIO, INTRANET, PUBLIC, RANK, Reachability, load_reachability)
from src.keys import check_keys, check_version  # noqa: E402
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
        # 关掉的源也查：那条源迟早要开回来，写歪的键不会自己变对
        for warn in check_keys(s, where=f"{path} 第 {i + 1} 条源", known=SOURCE_KEYS,
                               notes=SOURCE_NOTES):
            print(f"⚠️ {warn}", file=sys.stderr)
        if not s.get("enabled", True):
            continue
        missing = [k for k in ("id", "url") if not s.get(k)]
        if missing:
            raise ValueError(f"{path} 第 {i + 1} 条源缺 {' 和 '.join(missing)}"
                             f"（现在只有 {sorted(s)}），先修配置再出表")
        cache = CACHE_DIR / f"{s['id']}.m3u"
        target = s["url"] if (fresh or not cache.exists()) else str(cache)
        out.append({"id": s["id"], "target": target, "cache": cache, "url": s["url"],
                    "probe": bool(s.get("probe", True)),
                    "priority": int(s.get("priority", i + 1))})
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
}
# `backup_url` 在名单上但不是这里读的：`scripts/epg_check.py` 拿它当第二条候选（2.30）。
# `note` 是写给人看的为什么。


def load_epg_config(path: Path) -> dict:
    """读 `config/epg.yaml` 里那一节；文件不在或被写坏了就当「没启用」。

    「没地址就等于没启用」是同一件事的两种说法，所以只写一条判据（`enabled` 由 `url` 参与决定）。
    这样默认值是安全的：新克隆的仓库里没有这个文件，生成行为跟 P3 之前逐字节一致。

    >>> c = load_epg_config(EPG_FILE)
    >>> c["enabled"], c["url"].startswith("http")     # 不钉死是哪条地址，见下
    (True, True)
    >>> c["cache"].name
    'epg.xml'
    >>> n = load_epg_config(ROOT / "config" / "definitely-missing.yaml")
    >>> n["enabled"], n["url"]        # 不抛，只是什么都不做
    (False, '')
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d) / "e.yaml"
    ...     _ = p.write_text("epg:\\n  url: http://x/e.xml\\n  enabled: false\\n", encoding="utf-8")
    ...     load_epg_config(p)["enabled"]
    False

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

    名单与这段代码对得上吗（2.42）—— `backup_url` 在名单上却不在 `EPG_NOTES` 里，
    是因为它由 `scripts/epg_check.py` 读、而不是这儿，那种「给人看的 / 别人读的」键不算漂。

    >>> from src.keys import drift_of
    >>> drift_of(load_epg_config, known=EPG_KEYS + EPG_TOP_KEYS,
    ...          notes={**EPG_NOTES, **EPG_TOP_NOTES})
    []
    """
    try:
        top = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        top = {}
    if not isinstance(top, dict):
        top = {}
    cfg = top.get("epg") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    # 键名守卫只在「这份文件真的读出来了」之后才谈：读不出来还是老行为（当没启用）。
    # 不然新克隆的仓库会因为一份本来就可选的配置出不了表 —— 那是跟上面那句「默认值安全」
    # 直接冲突的。写坏了 YAML 的那格同理：形状都不在，谈不上键名。
    if top:
        check_version(top, where=str(path))
        for warn in check_keys(top, where=str(path), known=EPG_TOP_KEYS,
                               notes=EPG_TOP_NOTES):
            print(f"⚠️ {warn}", file=sys.stderr)
    if cfg:
        for warn in check_keys(cfg, where=f"{path} 的 epg 段", known=EPG_KEYS, notes=EPG_NOTES):
            print(f"⚠️ {warn}", file=sys.stderr)
    url = str(cfg.get("url") or "").strip()
    return {
        "url": url,
        "cache": ROOT / str(cfg.get("cache") or "data/cache/epg.xml"),
        "enabled": bool(cfg.get("enabled", True)) and bool(url),
        "caveat": str(cfg.get("caveat") or "").strip(),
    }


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
    """
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
                       workers: int, *, verifying: bool) -> list[str]:
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


def cmd_build(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="src.cli build", description="生成 APTV 订阅列表")
    ap.add_argument("--source", action="append", dest="sources",
                    help="临时指定上游（URL 或本地文件），可重复；给了它就忽略 sources.yaml")
    ap.add_argument("--sources-file", default=str(SOURCES_FILE))
    ap.add_argument("--config", default=str(ROOT / "config" / "channels.yaml"))
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
                         "（默认 data/output/probe-history.jsonl）")
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
    args = ap.parse_args(argv)
    # 这两个是互相矛盾的两种「本轮的线路判决从哪来」，在碰网络之前先拦掉：
    # 再往下每一步（读上游、取节目单）都要花时间，而这个组合根本给不出答案。
    if args.verify and args.replay:
        print("--verify 与 --replay 只能选一个：前者是当场测，后者是沿用记录", file=sys.stderr)
        return 1
    # 数字取歪了要在这里说，不能等到写盘那一刻：`--max-lines 0` 以前能把
    # data/output/ 四张表各自盖成一行表头，然后退 0（见 build_arg_problems）。
    problems = build_arg_problems(args.max_lines, args.max_per_host, args.timeout,
                                  args.workers, verifying=bool(args.verify))
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

    # 频道配置决定表上有哪些台，所以它要在**读那 1868 条上游之前**先读进来。
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
        print("config/sources.yaml 里没有启用的源。", file=sys.stderr)
        return 1
    # 手工线路在碰上游之前读 —— 2.37 给 channels.yaml 立过同一条规矩：读不进去这件事
    # 该在花掉那几分钟抓网络之前说。它也不再是「跳过那一行」的宽容路径：`expires` 写歪
    # 就是永不过期（src/keys.py），那种错只能停下来。
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
    try:
        reach = load_reachability(REACH_FILE)
    except (OSError, ValueError, yaml.YAMLError) as e:
        return stop_config("范围规则", REACH_FILE, e,
                           "少一档规则，运营商内网地址就会跑去占第一线 —— 真机上正是这么坏的（2.9）")

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
        print("\n节目单：未启用（config/epg.yaml 没写地址、或加了 --no-epg），"
              "tvg-id 保持上游写法")

    # 实测履历：判据只认「体检没报警」的那些轮，而参照出口由 judgment_egress() 定
    # （表是给电视用的，开发机代理在哪不影响这个依据）。
    # 出口身份现查一次就够，屏幕、probe.json、落盘、体检都用它，别重复查。
    history_path = Path(args.history)
    hist_problems: list[str] = []
    runs = hist.load_history(history_path, problems=hist_problems)
    for p in hist_problems:
        # 履历读不出行只影响排序（不删台），所以报一句就往下走 —— 但不能不报：
        # 不报的话这份履历读不出来和「履历里就是没有可信轮次」长成同一个样子（2.32 同族）。
        print(f"⚠️ 实测履历：{p}", file=sys.stderr)
    egress = egress_hint()
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
        at = datetime.now().astimezone().isoformat(timespec="seconds")
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
        verify_note += (f"。⚠️ 本轮体检报警（出口 {egress or '未取到'}），被剔的那些多半是假阴性，"
                        f"所以这份表只落在 {UNTRUSTED}/ 里当排查用，"
                        f"{trusted_rel} 那张仍是上一轮可信版本")
    report = format_report(
        sources=[f"{s['id']} ← {s['target']}" for s in sources] + (
            [f"{LOCAL_ID} ← {LOCAL_SOURCES_FILE.relative_to(ROOT)}"
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
        hosts=hosts,
        hosts_note=hosts_note,
        history=history_note,
    )
    artifacts["report.md"] = report
    # 到这一行之前，目录里一个字节都没动过。上面任何一步算不出来就崩在这里之前，
    # 订阅目录保持上一版原样（2.37：以前是 aptv.m3u 已经盖下去、才崩在下一份）。
    write_artifacts(out_dir, artifacts)

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
    if no_public:
        print(f"  ⚠️ 一条公网线路都没有的频道 {len(no_public)} 个（Wi-Fi 上大概率播不动）："
              + "、".join(no_public))
    if fake_live:
        print(f"  ⚠️ 第一线是循环录像的频道 {len(fake_live)} 个（有画但不是直播）："
              + "、".join(fake_live))
    for v in focus:
        rows = [r for r in v["rows"] if r["channels"] >= 2]
        if not rows:
            print(f"  第一线集中度：{v['label']} 那 {v['total']} 个台一家主机都不共用")
            continue
        top = rows[0]
        print(f"  第一线集中度：{v['total']} 个台只落在 {len(v['rows'])} 家主机上，"
              f"`{top['host']}` 一家挂着 {top['channels']} 个台的第一线"
              + (f"（其中 {top['alone']} 个台全部线路都在它上面，换线路也换不出去）"
                 if top["alone"] else "")
              + (f"，这 {top['unmeasured']} 个台的第一线电脑从没测过"
                 if v["measured"] and top["unmeasured"] else ""))
    if hosts:
        if replay:
            print(f"  线路判决来自 {replay_at} 那一轮（出口 {replay_meta['egress'] or '未知'}，"
                  f"详情见 {args.replay}）；本机当前出口 {egress or '未取到'}，"
                  "这一轮没拿它量过任何东西")
        else:
            print(f"  实测出口：{egress or '未取到'}（详情见 {out_dir / 'probe.json'}）")
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
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    if argv[0] not in SUBCOMMANDS:
        print(f"未知的子命令 {argv[0]!r}（只认 {'、'.join(SUBCOMMANDS)}）；"
              "看用法说明跑 python -m src.cli --help", file=sys.stderr)
        return 2
    return cmd_build(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
