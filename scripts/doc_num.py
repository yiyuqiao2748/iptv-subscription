"""把文档里抄来的那些数，逐个再算一遍（计划书 2.28）。

为什么要有这一条：`docs/真机验收单.md` 里那串数（39 个可疑台、24 没备选、14 换过去仍是专网、
0 换得到公网、tvgslb 22 个台、试播包 17 条覆盖 94 个台……）全是我从表和报告里**抄**进去的。
2.27 给了「表换没换」一道闸，但闸只说「这两份文件不是一张表」，它说不出**哪一句文档因此作废**。
表一换、这些数还躺在原处读起来像刚量过的 —— 这一层就是来收这笔账的。

怎么用它：文档里每个抄来的数后面挂一个 `〔数:<键>〕`，键说的是「这个数从哪张表、哪个算法来的」。
脚本重新从 `data/output/` 数一遍，再把写下来的数和算出来的数并排比。它不生成表、不联网。

    ./.venv/bin/python -X utf8 scripts/doc_num.py            # 验收：文档里的数还算不算数
    ./.venv/bin/python -X utf8 scripts/doc_num.py --list     # 现在每个键算出来是多少（抄数时对着它写）

退出码：**0 = 每一处都对得上**；**1 = 有数对不上、或有个标记我接不住、或点名要查的文档里
有读不到的一篇**（写歪的括号、不认识的键、括号前面没贴着数 —— 这三种都算失败，理由和 2.27
那条一样：**静默跳过就是假绿**）；**2 = 一处都没比成**（文档里没有标记、点名的那些一篇都没读到、
或 `data/output/` 里的表读不出来）。
**2.58 追记**：那三档的分界改成了「量到东西没有」，不是「有没有毛病」—— 以前「点名的文档
有一篇不在」直接退 2，连带把其余几篇比出来的结果**一个字都不印**（14:26 探针 `B7` 那格量到：
两篇里一篇不在、另一篇比了 2 处，屏幕上只有一句「点名的文档不在」）。这和 2.57 给命令尺修的那条
同形：2 = 「这把尺这次什么都没量到」，它比完了 2 处就不是。同一遍还量到 `--docs` 指到目录
或非 UTF-8 的文件会**裸崩**（`IsADirectoryError`／`UnicodeDecodeError`，退码 1 但不是判决）——
那是 2.36 那两条之外的第三种「读进来」，现在它落到上面那个「读不到」那一档里说人话。

键的认法：`<表>:<量>`，表是 `aptv` / `hunan` / `pack` / `probe`，例子 —— `aptv:suspect`（全量表第一线可疑的
台数）、`hunan:no-alt`（湖南表里没有备选线路的台数）、`aptv:focus:tvgslb.hn.chinamobile.com`
（全量表里第一线挂在这家主机上的台数）。`probe:` 那一族不是表上的数，是**那一轮实测**的数
（`probe:host-lines:<主机>` / `probe:host-passed:<主机>`，就是报告「实测逐主机」那张表的分子分母）——
文档抄那句「整族失效的主机比如 X 0/36」时，36 说的是那一轮量过几条，不是表里剩几条。
所以「算出来不一样」有两种意思，脚本会分开说：
数真的过期了（表换过一轮），或者表还没换、是我抄错了（`table_drift.py` 会帮你分清）。
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import io
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from baseline_guard import guard as guard_names  # noqa: E402  三把基线尺共用那道顿号闸
from run_doctests import add_doctest_flag, run_own   # noqa: E402  `--doctest` 那一旗的口径只有一份
from probe_pack import (base_of, channel_groups, focus_by_host,  # noqa: E402
                        host_of, load_results, load_stats)
from src.check.scope import PUBLIC, load_reachability            # noqa: E402
from src.cli import REACH_FILE, second_line_options              # noqa: E402
from src.output.writer import OutputChannel                      # noqa: E402

DEFAULT_DOCS = ("docs/真机验收单.md", "docs/电视订阅接入.md")
TABLES = {"aptv": "aptv.m3u", "hunan": "hunan.m3u"}
PACK = "probe-pack.m3u"

# 括号里那半截只认这些字符：**键里面**的全角冒号、空格、漏写表名都会落到 `bad-key`，
# 不会静悄悄不算。（注意分界：`〔数：…〕` 那个**前缀**冒号两种都收 —— 键照样认得出来，
# 2.58 的探针在这一格上押错过一次，见 `parse_marks` 里那条用例。）
BRACKET = re.compile(r"〔数[:：]?([^〕]*)〕")
# 数字和括号之间只许有空格、`**`（加粗闭合）和一个量词：隔了别的字就算「没贴着数」。
# 放量词是因为中文写「24 个」最自然，而 `**24 个**〔数:…〕` 要是必须写成 `24〔…〕 个`，
# 这一页读起来就没法人看了。认出来的数永远是括号前**最近**那个数字，所以放宽度量词
# 不会让谁悄悄对上号 —— 挂错了键就是「写的 3、算出来的 39」，照样红给你看。
ATTACHED = re.compile(r"(\d+)\s*(?:个|条|台|家)?\**$")
# 键 = `表:量` 或 `表:量:主机`。段与段之间只许半角冒号：写成中文冒号会被当成键的一部分，
# 于是落到 `bad-key` 点名（而不是悄悄不算）。
GOOD_KEY = re.compile(r"^[a-z][a-z0-9_-]*(:[a-z0-9_.-]+)+$")

METRIC_DOC = {
    "channels": "表里几个台",
    "lines": "表里几条线路",
    "public-lines": "公网线路条数",
    "intranet-lines": "运营商专网线路条数",
    "public-passed": "公网线路里本轮实测通过几条",
    "no-public-channels": "一条公网线路都没有的台数",
    "suspect": "第一线可疑（专网/没测过）的台数",
    "no-alt": "其中没有第二条线路的台数",
    "same-host": "其中有备选但备选在同一家机房的台数",
    "other-intranet": "其中换到别家、别家仍是专网的台数",
    "other-audio": "其中换过去是纯音频电台的台数",
    "other-public": "其中换得到公网电视线路的台数",
    "first-public": "第一线是公网线路的台数",
    "first-intranet": "第一线是运营商专网的台数",
    "focus": "第一线挂在这家主机上的台数（键的最后一段是主机名）",
    "focus-hosts": "第一线一共落在几家主机上",
    "items": "试播包几条",
    "cover": "试播包覆盖全量表多少个台的第一线",
    "families": "试播包里几个主机族",
    # 下面这两个不在任何一张表上，在 probe.json 那份「实测逐主机」汇总里（键的第一段是 `probe`）。
    "host-lines": "本轮实测里挂在某家主机名下的线路条数（报告那张表的分母）",
    "host-passed": "其中实测连通的条数（同表分子；0 就是整族失效）",
}

# 每张「表」出自哪个文件 —— 取不到值时那句「整个没读出来」要点名文件，不能印成默认那张。
SOURCES = TABLES | {"pack": PACK, "probe": "probe.json"}


def parse_marks(text: str) -> list[tuple[int, int | None, str, str]]:
    """扫一篇文档，返回 `(行号, 写下来的数, 键, 毛病)`。

    「毛病」有三种，都不是可以自己划过去的事：`no-number`（括号前面没贴着数字 —— 那这个数
    根本没进对账）、`bad-key`（键里有中文冒号、大写、漏了表名，认不出来）、空串（格式没问题，
    交给 `lookup` 判键认不认）。
    一个数字带两个标记、标记落在句首都不算毛病：只比括号前面那串数字，别的不管。
    反引号包起来的那种是**举例子**（文档开头教人认这个记号时总要举一个），不当声明、不查。

    >>> parse_marks("第一线可疑的 39〔数:aptv:suspect〕 个台里，**0**〔数:aptv:other-public〕 个换得到公网")
    [(1, 39, 'aptv:suspect', ''), (1, 0, 'aptv:other-public', '')]
    >>> parse_marks("没有标记的 226 条")
    []
    >>> parse_marks("写歪了〔数：aptv:lines〕")
    [(1, None, 'aptv:lines', 'no-number')]
    >>> parse_marks("键里混进中文〔数:aptv：lines〕")
    [(1, None, 'aptv：lines', 'bad-key')]
    >>> parse_marks("漏了表名〔数:suspect〕")
    [(1, None, 'suspect', 'bad-key')]
    >>> parse_marks("数字和括号中间有空格也算 24 〔数:aptv:no-alt〕")
    [(1, 24, 'aptv:no-alt', '')]
    >>> parse_marks("**24 个**〔数:aptv:no-alt〕没有备选")
    [(1, 24, 'aptv:no-alt', '')]
    >>> # 量词只放过一个：中间夹了别就不认，宁可报「没贴着数」也不去猜是哪个数
    >>> parse_marks("24 个台〔数:aptv:no-alt〕")
    [(1, None, 'aptv:no-alt', 'no-number')]
    >>> # 2.58 钉住的一种设计：前缀那个冒号写成全角，**不算毛病**（键认得出来就行）；
    >>> # 反过来，全角冒号落在键**里面**就是 bad-key —— 两格长得很像，别押错。
    >>> parse_marks("线路 226〔数：aptv:lines〕 条")
    [(1, 226, 'aptv:lines', '')]
    >>> parse_marks("线路 226〔数:aptv：lines〕 条")
    [(1, None, 'aptv：lines', 'bad-key')]
    >>> parse_marks("有些数字后面挂着 `〔数:aptv:suspect〕` 这种东西")     # 举例子，不查
    []
    >>> # 但同一行里真数该查还是查 —— 跳过例子不等于跳过整行
    >>> parse_marks("如 `〔数:aptv:lines〕` 这种，写着 226〔数:aptv:lines〕 条")
    [(1, 226, 'aptv:lines', '')]
    """
    out: list[tuple[int, int | None, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in BRACKET.finditer(line):
            if line[:m.start()].count("`") % 2:            # 在反引号里 = 举例，不是声明
                continue
            key = m.group(1).strip()
            att = ATTACHED.search(line[:m.start()])
            if not key or not GOOD_KEY.match(key):
                out.append((lineno, None, key, "bad-key"))
            elif not att:
                out.append((lineno, None, key, "no-number"))
            else:
                out.append((lineno, int(att.group(1)), key, ""))
    return out


def lookup(values: dict[str, int], table: str, metric: str, arg: str) -> tuple[int | None, str]:
    """按键取「现在算出来的那个数」。取不到就返回 (None, 为什么)，为什么这句要印出来。

    键分三段是给带主机名那一族留的：`aptv:focus:<主机>` 和 `probe:host-lines:<主机>`，
    其余键都是两段。
    同一份表算不出这个键（比如表文件不在）时，报的是**表**而不是**键**，
    不然读的人会以为是自己键名写错了。

    >>> v = {"aptv:channels": 98, "hunan:suspect": 37, "aptv:focus:tvgslb.hn.chinamobile.com": 22}
    >>> lookup(v, "aptv", "channels", "")
    (98, '')
    >>> lookup(v, "aptv", "focus", "tvgslb.hn.chinamobile.com")
    (22, '')
    >>> # 表里有别的数、只是这一族不挂台：说「没有这个族」，不是说表没读出来
    >>> lookup(v, "hunan", "focus", "tvgslb.hn.chinamobile.com")
    (None, 'hunan 表里没有第一线挂在 `tvgslb.hn.chinamobile.com` 上的台（`--list` 看现在有哪些族）')
    >>> # 整张表都没读出来（文件不在）时先说表，别让人以为是自己键名打错了
    >>> lookup({"pack:items": 17}, "aptv", "focus", "tvgslb.hn.chinamobile.com")
    (None, 'aptv 那张表整个没读出来（aptv.m3u 不在或读不了）')
    >>> lookup(v, "jiangxi", "channels", "")
    (None, '不认识的表 `jiangxi`（只有 aptv / hunan / pack / probe）')
    >>> lookup(v, "aptv", "nope", "")
    (None, '没有这个量 `nope`（--list 看全部）')
    >>> # probe 那族键说的是「实测过的线路」，不是「表里第一线挂谁的台」—— 两句不能混
    >>> lookup({"probe:host-lines:a.example": 36}, "probe", "host-passed", "a.example")
    (None, 'probe.json 里没有 `a.example` 名下实测过的线路（`--list` 看现在有哪几家）')
    >>> lookup({"probe:host-lines:a.example": 36}, "probe", "channels", "")
    (None, '没有这个量 `channels`（--list 看全部）')
    >>> # 整份记录读不出来时说的是 probe.json，不是「表」：它不是表，是那一轮实测的快照
    >>> lookup({"aptv:channels": 98}, "probe", "host-lines", "a.example")
    (None, 'probe 那一份实测记录读不出来（probe.json 不在或读不了）')
    """
    if table not in SOURCES:
        return None, f"不认识的表 `{table}`（只有 {' / '.join(SOURCES)}）"
    key = f"{table}:{metric}" + (f":{arg}" if arg else "")
    if key in values:
        return values[key], ""
    if not any(k.startswith(f"{table}:") for k in values):
        src = SOURCES.get(table, "")
        if table == "probe":
            return None, f"probe 那一份实测记录读不出来（{src} 不在或读不了）"
        return None, f"{table} 那张表整个没读出来（{src} 不在或读不了）"
    if arg:
        if metric.startswith("host-"):
            return None, (f"probe.json 里没有 `{arg}` 名下实测过的线路"
                          "（`--list` 看现在有哪几家）")
        return None, f"{table} 表里没有第一线挂在 `{arg}` 上的台（`--list` 看现在有哪些族）"
    return None, f"没有这个量 `{metric}`（--list 看全部）"


def table_metrics(groups: list[tuple[str, list[str]]], results: dict, reach) -> dict[str, int]:
    """一张表能算出来的那些数（键名不带表名前缀，由调用方加）。

    专网/公网按 `reach` 判，`no-public-channels` 说的是「这个台的**每一条**线路都不是公网」，
    和 `suspect`（只看第一线）是两回事 —— 湖南表上它俩都是 37，全量表上都是 39，
    看着像同一个数，其实一个是「一线都没有」、一个是「第一线不可靠」。

    >>> from src.check.scope import Reachability
    >>> r = Reachability([".chinamobile.com"], [".qingting.fm"])
    >>> g = [("甲", ["http://t.hn.chinamobile.com/1"]),
    ...      ("乙", ["http://t.hn.chinamobile.com/2", "http://t.hn.chinamobile.com:8089/3"]),
    ...      ("丙", ["http://pub.example/4", "http://ls.qingting.fm/5"]),
    ...      ("丁", ["http://new.example/6"])]
    >>> m = table_metrics(g, {"http://pub.example/4": None}, r)
    >>> [m[k] for k in ("channels", "lines", "public-lines", "intranet-lines", "no-public-channels")]
    [4, 6, 2, 3, 2]
    >>> # 没给逐条判决时不算「谁没测过」，可疑只剩下专网那一层；电台那条第一线不算公网
    >>> [(m[k], m[k2]) for k, k2 in (("suspect", "no-alt"), ("same-host", "other-public"))]
    [(3, 2), (1, 0)]
    >>> # 给了判决：`丁` 那条没见过的新公网线也进可疑（它是「没测过」不是「专网」），
    >>> # 而 `丙` 的第一线本轮测过、是公网 —— 它照样不算可疑
    >>> table_metrics(g, {"http://t.hn.chinamobile.com/1": None,
    ...                   "http://t.hn.chinamobile.com/2": None,
    ...                   "http://t.hn.chinamobile.com:8089/3": None,
    ...                   "http://pub.example/4": None}, r)["suspect"]
    3
    """
    och = [OutputChannel(n, "", "", None, list(u)) for n, u in groups]
    fb = second_line_options(och, results, reach)
    scopes = Counter(reach.scope(u) for _, us in groups for u in us)
    first_scopes = Counter(reach.scope(us[0]) for _, us in groups if us)
    passed = sum(1 for _, us in groups for u in us
                 if reach.scope(u) == PUBLIC and getattr(results.get(u), "ok", False))
    no_public = sum(1 for _, us in groups
                    if us and all(reach.scope(u) != PUBLIC for u in us))
    return {"channels": len(groups), "lines": sum(len(u) for _, u in groups),
            "public-lines": scopes.get(PUBLIC, 0),
            "intranet-lines": scopes.get("iptv_intranet", 0),
            "public-passed": passed, "no-public-channels": no_public,
            "first-public": first_scopes.get(PUBLIC, 0),
            "first-intranet": first_scopes.get("iptv_intranet", 0),
            "suspect": fb["channels"], "no-alt": fb["no_alt"], "same-host": fb["same_host"],
            "other-intranet": fb["other_intranet"], "other-audio": fb["other_audio"],
            "other-public": fb["other_public"]}


def pack_metrics(pack: list[tuple[str, list[str]]],
                 main: list[tuple[str, list[str]]]) -> dict[str, int]:
    """试播包那两个数：几条、覆盖全量表多少个台的第一线。

    覆盖按**主机族**算，和 `probe_pack.py` 选条的口径一致：包里那条线只是这一族的代表，
    电视上点它，判的是「这一族的第一线行不行」。

    >>> pack_metrics([("① 甲族", ["http://a/1"]), ("② 乙族", ["http://b/2"])],
    ...              [("台一", ["http://a/1"]), ("台二", ["http://a:8080/9"]),
    ...               ("台三", ["http://c/3"])])
    {'items': 2, 'families': 2, 'cover': 2}
    >>> # 包里有整族失效的那种（一个台的第一线都不挂）→ items 涨、cover 不涨
    >>> pack_metrics([("① 甲族", ["http://a/1"]), ("② 孤儿族", ["http://z/9"])],
    ...              [("台一", ["http://a/1"])])["cover"]
    1
    """
    fams = {base_of(host_of(us[0])) for _, us in pack if us}
    return {"items": len(pack), "families": len(fams),
            "cover": sum(1 for _, us in main if us and base_of(host_of(us[0])) in fams)}


def probe_metrics(stats: dict[str, dict]) -> dict[str, int]:
    """那一轮实测里，每家主机名下量了几条、连通几条（报告「实测逐主机」那张表的口径）。

    为什么要另开一张「表」，不挂到 `aptv:` 下面：文档里那句
    「整族失效的主机比如 `stream1.freetv.fun` 0/36」，那个 36 **不在 `aptv.m3u` 里** ——
    今天量过：这张表里这家主机名下 **0 条**（它整族连不上，删线路那一步早删干净了），
    而 report.md 与 `probe.json` 的逐主机汇总里都是 36。挂错对象不是「数对不上」，
    是「查了个不相干的数还退 0」，所以它得有自己的键名和自己的文件。

    数直接取 `load_stats` 那份汇总，不从 `probe.json` 的逐条 URL 重新分组：
    报告印的就是前者，重新分组等于给同一个数造第二套算法（两套哪天分叉了没人知道）。

    >>> probe_metrics({"a.example": {"total": 36, "ok": 0}, "b.example": {"total": 19, "ok": 13}})
    {'host-lines:a.example': 36, 'host-passed:a.example': 0, 'host-lines:b.example': 19, 'host-passed:b.example': 13}
    >>> probe_metrics({})          # 没实测过就没有这一族键，标记落到「读不出来」那句
    {}
    >>> probe_metrics({"c.example": {}})          # 有这一族但汇总里是空的：0 条，不是缺键
    {'host-lines:c.example': 0, 'host-passed:c.example': 0}
    """
    out: dict[str, int] = {}
    for host, row in stats.items():
        out[f"host-lines:{host}"] = int(row.get("total") or 0)
        out[f"host-passed:{host}"] = int(row.get("ok") or 0)
    return out


def compute_values(base: Path) -> tuple[dict[str, int], list[str]]:
    """从 `data/output/`（或 `--base` 指的那批文件）把每个键重新算一遍。

    返回 `(值, 缺了什么)`。读不出来的表**不进** `values`，于是引用它的每个标记都落到
    「那张表整个没读出来」那句 —— 而不是悄悄少比几处。
    """
    reach = load_reachability(REACH_FILE)
    results = load_results(base / "probe.json")
    values: dict[str, int] = {}
    missing: list[str] = []
    for table, fn in TABLES.items():
        p = base / fn
        if not p.exists():
            missing.append(str(p))
            continue
        groups = channel_groups(p.read_text(encoding="utf-8"))
        values.update({f"{table}:{k}": v
                       for k, v in table_metrics(groups, results, reach).items()})
        focus = focus_by_host(groups, results, reach)
        for host, row in focus.items():
            values[f"{table}:focus:{host}"] = row["channels"]
        # 「第一线只落在 N 家主机上」是集中度那一节开头那句话，同样是抄来的数。
        # 它不叫 `focus`：那个名字留给带主机名的那一族键，混在一起 `lookup` 会说谎。
        values[f"{table}:focus-hosts"] = len(focus)
    pp = base / PACK
    aptv = base / TABLES["aptv"]
    if pp.exists() and aptv.exists():
        pack = channel_groups(pp.read_text(encoding="utf-8"))
        main = channel_groups(aptv.read_text(encoding="utf-8"))
        values.update({f"pack:{k}": v for k, v in pack_metrics(pack, main).items()})
    else:
        missing.append(str(pp))
    if not results:
        missing.append(f"{base / 'probe.json'}（没有逐条判决，`public-passed` 会是 0）")
    # probe 那族键（`host-lines` / `host-passed`）读的是同一份文件里的逐主机汇总，
    # 但它是**另一份东西**：逐条判决说的是「这条线能不能连」，那张表说的是「这一族共几条」。
    values.update({f"probe:{k}": v
                   for k, v in probe_metrics(load_stats(base / "probe.json")).items()})
    return values, missing


def as_of(base: Path) -> str:
    """这批数是跟着哪一轮表数的：印产物目录 + 两张表的 mtime。

    为什么要在意：这个脚本只能说「文档写的数 == 现在这张表算出来的数」，
    说不出「现在这张表是哪一轮测的」—— 那是 `--replay`/`--verify` 的事，
    但把时间摆出来，读的人就知道有没有必要先重跑一次。
    """
    ts = []
    for fn in TABLES.values():
        p = base / fn
        if p.exists():
            ts.append(datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M"))
    return f"{base.name}/（{'、'.join(sorted(set(ts)))}）" if ts else f"{base.name}/（表不在）"


def read_doc(path: Path) -> tuple[str | None, str]:
    """把点名要查的文档读进来 —— 读不进来时返回 `(None, 为什么)`，**不裸崩**。

    2.36 那条规矩（「读进来」那两处裸崩改成人话）管的是配置与表；这一处是同一族里的第三种：
    命令行上点名的文档。它比前两处更容易撞上，因为 `--docs` 是手打的 —— 指到目录、
    指到一张图片，都只是手指头的事。2.58 的探针量到：`--docs docs` 崩 `IsADirectoryError`、
    指到非 UTF-8 的文件崩 `UnicodeDecodeError`，两下都是整段 traceback，退码 1 但不是判决。

    毛病分三种说法，因为**下一步做的事不一样**：不在（打错名或搬家了）、不是文件（指到目录了）、
    读不出（编码不是 UTF-8 —— 那是文件内容的事，改名没用）。

    >>> read_doc(Path("docs/真机验收单.md"))[0] is not None
    True
    >>> read_doc(Path("docs"))[1]
    '那是个目录，不是文档'
    >>> read_doc(Path("docs/nope-没有这一篇.md"))[1]
    '文件不在'
    """
    if not path.exists():
        return None, "文件不在"
    if not path.is_file():
        return None, "那是个目录，不是文档"
    try:
        return path.read_text(encoding="utf-8"), ""
    except (OSError, UnicodeDecodeError) as e:
        return None, f"读不出来：{str(e).splitlines()[0]}"


def check_files(docs: list[Path], values: dict[str, int]) -> tuple[list[tuple], list[str], list[tuple]]:
    """把每篇文档里的标记逐个对一遍，返回 `(逐行结果, 每篇几处, 读不到的那几篇)`。

    每行结果是六元组 `(位置, 键, 写下来的数, 算出来的数, 毛病, 为什么)`，`毛病` 空串就是对上了。
    键最多三段（`表:量:主机`），少于三段在 `parse_marks` 那关就已经算 `bad-key`，这里不再判。

    第三个返回值是 2.58 补的：以前它没有出口 —— 文件不在的那篇只在 `counts` 里留一个
    「（文件不在）」，而 `main()` 靠重新 `exists()` 一遍才判出退码，「读不出来」那一类则压根
    进不来（当场崩）。现在三种读不到都在这一格里，由 `main()` 决定怎么说、退几。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmp:            # 不拿真文档当样例：它 28 处会变
    ...     good = Path(tmp) / "好文档.md"
    ...     _ = good.write_text("线路 226〔数:aptv:lines〕 条\\n", encoding="utf-8")
    ...     rows, counts, unread = check_files([good, Path(tmp) / "不在.md"], {"aptv:lines": 226})
    ...     ([(r[1], r[2], r[3], r[4]) for r in rows], counts, [u[1] for u in unread])
    ([('aptv:lines', 226, 226, '')], ['好文档.md 1 处', '不在.md 一处都没读到'], ['文件不在'])
    """
    rows: list[tuple] = []
    counts: list[str] = []
    unread: list[tuple] = []
    for path in docs:
        disp = path.relative_to(ROOT) if str(path).startswith(str(ROOT)) else path
        text, why = read_doc(path)
        if text is None:
            counts.append(f"{disp.name} 一处都没读到")
            unread.append((disp, why))
            continue
        marks = parse_marks(text)
        counts.append(f"{disp.name} {len(marks)} 处")
        for lineno, num, key, problem in marks:
            where = f"{disp}:{lineno}"
            if problem:
                rows.append((where, key, num, None, problem, ""))
                continue
            parts = key.split(":")
            got, why = lookup(values, parts[0], parts[1], parts[2] if len(parts) > 2 else "")
            if got is None:
                rows.append((where, key, num, None, "unknown-key", why))
            elif num == got:
                rows.append((where, key, num, got, "", ""))
            else:
                rows.append((where, key, num, got, "diff", why))
    return rows, counts, unread


def render(rows: list[tuple]) -> list[str]:
    """一行一个标记，先说不对的、再说对得上的（对得上的也要印，否则不知道它查没查）。"""
    order = {"diff": 0, "bad-key": 1, "no-number": 2, "unknown-key": 3, "": 4}
    out = []
    for where, key, num, got, problem, why in sorted(rows, key=lambda r: (order[r[4]], r[0])):
        kwd = (key.split(":")[1] if ":" in key else key)
        doc = METRIC_DOC.get(kwd, "")
        if problem == "diff":
            out.append(f"✗ {where}  `{key}`  写的 {num}，现在算出来 {got} —— "
                       f"{doc}。表换过一轮就该重抄这一句（哪张表换的说给 `table_drift.py` 问）")
        elif problem == "unknown-key":
            out.append(f"✗ {where}  `{key}`  算不出来：{why or '没有这个键（`--list` 看全部）'}")
        elif problem == "bad-key":
            out.append(f"✗ {where}  〔数:{key}〕 这个标记本身有问题：键要么写成中文冒号了、"
                       "要么漏了表名（认 `aptv:` / `hunan:` / `pack:` / `probe:` 开头的小写键）")
        elif problem == "no-number":
            out.append(f"✗ {where}  `{key}`  前面没贴着数字：这个标记对不上任何数，等于没查")
        else:
            out.append(f"✓ {where}  `{key}`  {num}")
    return out


def render_list(values: dict[str, int]) -> list[str]:
    """`--list`：现在算出来的每个键和它的数，抄数时对着这一屏写标记。"""
    out = []
    for key in sorted(values, key=lambda k: (k.count(":"), k)):
        parts = key.split(":")
        doc = (f"第一线挂在 `{parts[2]}` 上的台数" if parts[1] == "focus"
               else METRIC_DOC.get(parts[1], ""))
        out.append(f"{key:<46} {values[key]:>4}  {doc}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="对账：文档里抄来的数，还算不算数")
    ap.add_argument("--docs", default=",".join(DEFAULT_DOCS),
                    help="查哪几篇文档，逗号分隔（默认 " + "、".join(DEFAULT_DOCS) + "）")
    ap.add_argument("--base", default=str(OUT_DIR),
                    help="以哪一批表为准，默认 data/output（订阅进电视的那批产物）")
    ap.add_argument("--list", action="store_true",
                    help="只印现在算出来的每个键是多少，不对文档")
    ap.add_argument("--self-test", action="store_true", dest="self_test",
                    help=f"往临时目录里种 {len(BASELINE)} 格已知好坏的文档，问这把尺自己还咬不咬得动")
    add_doctest_flag(ap)
    args = ap.parse_args(argv)
    if args.doctest:
        return run_own(sys.modules[__name__])   # 2.69：先答说明书，一篇文档都不读
    if args.self_test:
        return self_test()           # 先跑掉：这一档一个字都不该读仓库里那三篇文档

    base = Path(args.base)
    values, missing = compute_values(base)
    if args.list:
        if not values:
            print(f"{base} 里一张表都读不出来，没有可列的数。", file=sys.stderr)
            return 2
        print(f"# 以 {as_of(base)} 为准")
        for line in render_list(values):
            print(line)
        for m in missing:
            print(f"！缺：{m}", file=sys.stderr)
        return 0
    docs = [ROOT / d.strip() if not Path(d.strip()).is_absolute() else Path(d.strip())
            for d in args.docs.split(",") if d.strip()]
    if not values:
        # 一张表都读不出来 = 一处都比不成。把 44 行「算不出来」印出来看着像在工作，
        # 其实什么都没验 —— 这种情形按 2.27 那条同一个口径退 2。
        for m in missing:
            print(f"！缺：{m}", file=sys.stderr)
        print(f"{base} 里一张表都读不出来，没有可对账的数。", file=sys.stderr)
        return 2
    rows, counts, unread = check_files(docs, values)
    print(f"以 {as_of(base)} 为准")
    if missing:
        for m in missing:
            print(f"！缺：{m}")
    for line in render(rows):
        print(line)
    bad = [r for r in rows if r[4]]
    diffs = [r for r in rows if r[4] == "diff"]
    if not rows:
        # 一处都没比成：要么点名的那些一篇都没读到，要么读到的里面一个标记都没有。
        # 「没读到」那一半在 2.58 以前是先退 2 再说的（下面那截压根不印）—— 顺序反过来
        # 才会有混合格：两篇里一篇不在、另一篇比了 2 处、其中一处还真对不上，屏幕上却只留
        # 「点名的文档不在」那一句，成绩被吞了。
        for disp, why in unread:
            print(f"！没读到：{disp} —— {why}", file=sys.stderr)
        head = "、".join(counts) or "没有一篇文档读得到"
        if unread:
            print(f"{head} —— 点名的 {len(docs)} 篇里有 {len(unread)} 篇没读到，"
                  "这一轮一处都没比成：不算通过。", file=sys.stderr)
        else:
            print(f"{head}：一个 〔数:…〕 标记都没有 —— 这不算通过。", file=sys.stderr)
        return 2
    print(f"\n比了 {len(rows)} 处（{'、'.join(counts)}）："
          f"{'对得上 ' + str(len(rows) - len(bad)) + ' 处' if bad else '全部对得上'}"
          + (f"，**对不上 {len(diffs)} 处**" if diffs else "")
          + (f"，接不住的标记 {len(bad) - len(diffs)} 处" if len(bad) - len(diffs) else ""))
    if unread:
        # 2.58 之前这里退 2（= 「这一把尺瞎了」），可它刚刚把其余几篇逐个比完了。
        # 按 2.57 给命令尺立的口径改：量到了东西就退 1，退 2 只留给「一处都没比成」。
        # 不变的是那条 2.32 立下来的底线：**最坏的一种绿是「文档改了个名，这一层少一篇覆盖，
        # 屏幕上照旧全部对得上」** —— 真机验收单那 28 处会整篇消失，而它是六步唯一能对上的那一份。
        # 所以少一篇永远不退 0，只退 1；`--docs` 里给个不存在的名字，只可能是手打错了或搬家了，
        # 两种都不该由它替我说「没问题」。
        for disp, why in unread:
            print(f"！没读到：{disp} —— {why}，它那些标记一个都没查到")
        n = len(unread)
        print(f"上面那句「{'对得上 ' + str(len(rows) - len(bad)) + ' 处' if bad else '全部对得上'}」"
              f"只覆盖读到的那 {len(counts) - n} 篇，另有 {n} 篇没查 —— 这一轮不是「文档里的数都对」。")
    if bad:
        print("对不上不等于算错了：先跑 `scripts/table_drift.py` 问一句「表换没换」，"
              "换了就按新表重抄这些数，没换就是我抄错了或者键挂错了。")
        return 1
    return 1 if unread else 0


# ——————————————————————————————————————————————————————————
# 基线（§2.58）：这一把尺自己还咬得动吗
#
# 为什么要有这一档：`selfcheck` 上那条 ✓ 底下印的是「比了 74 处：全部对得上」。这句话有两种
# 读法 —— 文档里的数真的都对，或者这把尺瞎了。§2.56 给 `names` 装过这一层、§2.57 给命令尺装过，
# 这一节递给第三把尺。14:26 那遍 22 格探针还量出它**已经**有第三种错法（比 §2.57 那条更狠）：
# 点名的两篇里有一篇不在时，它把另一篇比出来的 2 处**一个字都不印**，只留一句「点名的文档不在」。
# ——————————————————————————————————————————————————————————

DOC = "假文档.md"
SANDBOX = "<沙盒>"                       # argv 模板里指代本格沙盒，跑之前换成真路径
SPEC = re.compile(r"\{([^{}]+)\}")
TABLES_ONLY = ("aptv.m3u", "hunan.m3u", "probe-pack.m3u")
TABLES_FULL = TABLES_ONLY + ("probe.json",)
BIN_BODY = bytes(range(0, 256))           # 什么都不是的一份字节流：UTF-8 一定读不出（B9 那一格）


class Cell(NamedTuple):
    """一格基线：种什么、用什么参数问它、期望屏幕上出现什么。

    格子里所有 `{…}` 都在跑之前由 `resolve` 换成**这一轮的真值**（见 `unresolvable`），
    所以表换一轮、主机换了家，期望跟着动，格子不会因此变红 —— 这里量的是判据。
    """
    who: str
    what: str
    rc: int
    files: tuple[tuple[str, str], ...] = ()     # 沙盒里的文档：名字 → 内容模板
    bins: tuple[str, ...] = ()                  # 要造的非 UTF-8 件（只给名字）
    copies: tuple[str, ...] = ()                # 从 `data/output/` 拷进 `<沙盒>/tables/` 的那些
    argv: tuple[str, ...] = ()                  # 空 = 只查 `<沙盒>/假文档.md`
    has: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()


def split_spec(spec: str) -> tuple[str, int]:
    """`aptv:lines+1` → `("aptv:lines", 1)`；`aptv:no-alt-24` → `("aptv:no-alt", -24)`。

    键名里不含 `+`，所以「尾巴上是 `±数字`」这个判据够用。真的碰上带连字符数字结尾的主机名，
    拆错了也只会落到 `unresolvable` 那一闸上大声退 2，不会悄悄拿个凭空的数去比。

    >>> split_spec("aptv:lines")
    ('aptv:lines', 0)
    >>> split_spec("aptv:lines+1")
    ('aptv:lines', 1)
    >>> split_spec("aptv:no-alt-24")
    ('aptv:no-alt', -24)
    """
    m = re.match(r"^(.*?)([+-]\d+)$", spec)
    return (spec, 0) if not m else (m.group(1), int(m.group(2)))


def pick(pattern: str, values: dict[str, int]) -> str | None:
    """按键名排序后**第一个**撞上 glob 的键 —— 给「哪家主机都行」那一类格子用。

    >>> pick("aptv:focus:*", {"aptv:focus:b.example": 1, "aptv:focus:a.example": 2})
    'aptv:focus:a.example'
    >>> pick("aptv:focus:zzz", {"aptv:focus:a.example": 2}) is None
    True
    """
    return next((k for k in sorted(values) if fnmatch.fnmatchcase(k, pattern)), None)


def resolve(spec: str, values: dict[str, int]) -> str:
    """一个 `{…}` 换成这一轮的真值。`@` 开头要的是**键名**，否则要值。

    >>> v = {"aptv:lines": 226, "aptv:focus:1.2.3.4": 7, "aptv:focus:9.9.9.9": 2}
    >>> resolve("aptv:lines", v), resolve("aptv:lines+1", v), resolve("aptv:lines-6", v)
    ('226', '227', '220')
    >>> resolve("@aptv:focus:*", v)              # 键名本身：要写进 〔数:…〕 里
    'aptv:focus:1.2.3.4'
    >>> resolve("aptv:focus:*", v)               # 同一家的那个值
    '7'
    """
    want_name = spec.startswith("@")
    key, off = split_spec(spec[1:] if want_name else spec)
    if "*" in key or "?" in key:
        hit = pick(key, values)
        if hit is None:
            raise KeyError(spec)
        return hit if want_name else str(values[hit] + off)
    if key not in values:
        raise KeyError(spec)
    return key if want_name else str(values[key] + off)


def fill(text: str, values: dict[str, int]) -> str:
    """把一段模板里所有 `{键}` 换掉。文档内容、期望句、参数模板都走它。

    >>> fill("写着 {aptv:lines}〔数:aptv:lines〕 条", {"aptv:lines": 226})
    '写着 226〔数:aptv:lines〕 条'
    >>> fill("写的 {aptv:lines+1}，现在算出来 {aptv:lines}", {"aptv:lines": 226})
    '写的 227，现在算出来 226'
    """
    return SPEC.sub(lambda m: resolve(m.group(1), values), text)


def ragged_cells(cells: Sequence[Cell]) -> list[str]:
    """格子字面量本身写歪的地方 —— 与 `unresolvable` 同档：**跑任何一格之前先问这一条**。

    为什么要单独有一道：`files=(("m.md", "正文"))` 少一个逗号时，那是个**两串字符的元组**、
    不是「一篇文档」。14:44 我自己就写歪过一处，`specs_of` 拆它拆出的是
    `ValueError: too many values to unpack (expected 2)` —— 一句中文都没有，也说不清是哪格。
    闸先咬住靶子的形状，崩就没机会冒充成尺子的判决。

    >>> ragged_cells([Cell("A", "x", 0, files=(("m.md", "正文"),))])
    []
    >>> ragged_cells([Cell("A", "x", 0, files=(("m.md", "正文")))])
    ['A：files 少一个逗号（`(("名", "正文"))` 是两串字符，不是一篇文档）']
    >>> ragged_cells([Cell("B", "y", 0, files=(("m.md", "正文"),), has="印这句")])
    ['B：has 得是元组而不是一个字符串']
    """
    bad: list[str] = []
    for c in cells:
        if any(isinstance(x, str) for x in c.files):
            bad.append(f"{c.who}：files 少一个逗号（`((\"名\", \"正文\"))` 是两串字符，不是一篇文档）")
        else:
            bad += [f"{c.who}：files 里有一项不是 (文件名, 正文) 两样：{x!r}"
                    for x in c.files if len(x) != 2]
        for fld in ("bins", "copies", "argv", "has", "lacks"):
            if isinstance(getattr(c, fld), str):
                bad.append(f"{c.who}：{fld} 得是元组而不是一个字符串")
    return bad


def specs_of(cells: Sequence[Cell]) -> list[str]:
    """这批格子里出现过的所有 `{…}`，去重排序 —— 期望句里挂的数也算。

    >>> [s for s in specs_of([Cell("A", "x", 0, files=(("m.md", "数 {aptv:lines}"),),
    ...                            has=("算出来 {aptv:lines+1}",))])]
    ['aptv:lines', 'aptv:lines+1']
    """
    out = set()
    for c in cells:
        for body in [t for _, t in c.files] + list(c.has) + list(c.lacks):
            out.update(SPEC.findall(body))
    return sorted(out)


def unresolvable(cells: Sequence[Cell], values: dict[str, int]) -> list[str]:
    """基线点名却点不到的那些 `{…}`。**跑任何一格之前先问这一条**。

    为什么：这一档的期望值全是现取的（226 是今天的表算出来的，不是钉在文件里的）。键要是
    改了名、或那家主机这一轮不在了，格子会拿一个凭空的数去比 —— 红了也说不清是尺坏了还是键变了。
    形状与 §2.57 那道顿号闸一样：先量靶子，靶子不对就一格都不跑。

    >>> unresolvable([Cell("A", "x", 0, files=(("m.md", "{aptv:lines} 与 {aptv:nope}"),))],
    ...              {"aptv:lines": 226})
    ['aptv:nope']
    >>> unresolvable([Cell("A", "x", 0, files=(("m.md", "{aptv:lines}"),))],
    ...              {"aptv:lines": 226})
    []
    """
    bad = []
    for s in specs_of(cells):
        try:
            resolve(s, values)
        except KeyError:
            bad.append(s)
    return sorted(set(bad))


def hide_tmp(text: str, base: Path) -> str:
    """沙盒路径换成 `<T>`：临时目录名每跑一遍换一个，留着它「两遍逐字节相同」就没法看。

    与 §2.57 那条同形，也带同一条边界：**拆掉它这 26 格仍然全绿**（期望句里没有一个带路径），
    所以钉住它的是这一条用例和「两遍逐字节相同」那一次，不是基线本身。

    >>> hide_tmp("✗ /tmp/x-91/B1_数写错/假文档.md:1", Path("/tmp/x-91"))
    '✗ <T>/B1_数写错/假文档.md:1'
    """
    return text.replace(str(base), "<T>")


BASELINE: tuple[Cell, ...] = (
    # ———— G 组：这些情形**不许**报错。它们红了就是尺在瞎咬 ————
    Cell("G1_两键全对", "常态：抄来的数都算得出，退 0 且要说比了几处",
         0, files=((DOC, "线路 {aptv:lines}〔数:aptv:lines〕 条、台数 {aptv:channels}〔数:aptv:channels〕 个。"),),
         has=("比了 2 处", "全部对得上")),
    Cell("G2_前缀全角冒号", "14:26 探针在这一格押错过：`〔数：…〕` 那个前缀冒号是**收**的",
         0, files=((DOC, "线路 {aptv:lines}〔数：aptv:lines〕 条"),),
         has=("全部对得上",), lacks=("这个标记本身有问题",)),
    Cell("G3_加粗带量词", "「**24 个**〔数:…〕」这种写法最自然，不许逼人改写",
         0, files=((DOC, "**{aptv:no-alt} 个**〔数:aptv:no-alt〕没有备选线路"),),
         has=("比了 1 处", "全部对得上")),
    Cell("G4_反引号举例", "举例子那个标记不进对账，同一句里的真数该查还查",
         0, files=((DOC, "教人认这个记号时写 `〔数:aptv:lines〕`，写着 {aptv:lines}〔数:aptv:lines〕 条"),),
         has=("比了 1 处", "全部对得上")),
    Cell("G5_三段focus键", "键名带主机那一族：现挑一家，键名和值都从同一处取",
         0, files=((DOC, "挂在 {@aptv:focus:*} 上 {aptv:focus:*}〔数:{@aptv:focus:*}〕 个台"),),
         has=("全部对得上",)),
    Cell("G6_probe族键", "`probe:` 那一族读的是实测记录，不是表 —— 它得算得出来",
         0, files=((DOC, "那家主机名下 {probe:host-lines:*}〔数:{@probe:host-lines:*}〕 条"),),
         has=("全部对得上",)),
    Cell("G7_两篇都对", "分母按篇分开报：两篇各自几处要说得出",
         0, files=((DOC, "线路 {aptv:lines}〔数:aptv:lines〕 条"),
                   ("另一篇.md", "台数 {aptv:channels}〔数:aptv:channels〕 个")),
         argv=("--docs", f"{SANDBOX}/{DOC},{SANDBOX}/另一篇.md"),
         has=("比了 2 处", f"{DOC} 1 处", "另一篇.md 1 处")),
    Cell("G8_一篇零标记", "读到了、但那篇一个标记都没有：那个 0 必须印在分母里",
         0, files=((DOC, "线路 {aptv:lines}〔数:aptv:lines〕 条"), ("没标记.md", "这一篇一个标记都没有。")),
         argv=("--docs", f"{SANDBOX}/{DOC},{SANDBOX}/没标记.md"),
         has=("比了 1 处", "没标记.md 0 处")),
    Cell("G9_list档", "`--list` 只印现在算出来的数，它自己那套键得在",
         0, argv=("--list",), has=("表里几条线路", "aptv:lines")),
    Cell("G10_只有表没实测", "base 里少了 `probe.json`：表那一半不许连坐",
         0, files=((DOC, "线路 {aptv:lines}〔数:aptv:lines〕 条"),), copies=TABLES_ONLY,
         argv=("--docs", f"{SANDBOX}/{DOC}", "--base", f"{SANDBOX}/tables"),
         has=("全部对得上",), lacks=("算不出来",)),
    # ———— B 组：已知坏法，各点一名。哪一格不再报错，就是那一层判据掉了 ————
    Cell("B1_数写错", "diff 那一层：写的和算出来的并排印出来",
         1, files=((DOC, "写着 {aptv:lines+1}〔数:aptv:lines〕 条"),),
         has=("写的 {aptv:lines+1}，现在算出来 {aptv:lines}", "对不上 1 处"),
         lacks=("全部对得上",)),
    Cell("B2_键里全角冒号", "全角落在键**里面**：静默跳过就是假绿，所以它算毛病",
         1, files=((DOC, "线路 {aptv:lines}〔数:aptv：lines〕 条"),),
         has=("这个标记本身有问题", "接不住的标记 1 处")),
    Cell("B3_漏表名", "bad-key 另一种：没有 `表:` 前缀",
         1, files=((DOC, "线路 {aptv:lines}〔数:lines〕 条"),), has=("漏了表名",)),
    Cell("B4_括号前没数", "no-number：这个数压根没进对账",
         1, files=((DOC, "括号〔数:aptv:lines〕 前面没有数"),), has=("前面没贴着数字",)),
    Cell("B5_键不认识", "unknown-key：格式对、键取不到值，要说出为什么",
         1, files=((DOC, "挂着 7〔数:aptv:no-such-g258〕 个"),), has=("算不出来", "没有这个量")),
    Cell("B6_唯一一篇不在", "一处都没比成 → 退 2，这一格本来就对",
         2, argv=("--docs", f"{SANDBOX}/不存在.md"),
         has=("没读到", "文件不在", "一处都没比成")),
    Cell("B7_混合格印成绩", "**本节改的那格**：其余篇比了 2 处就须印出来，退 1 不是退 2",
         1, files=((DOC, "线路 {aptv:lines}〔数:aptv:lines〕 条、台数 {aptv:channels}〔数:aptv:channels〕 个"),),
         argv=("--docs", f"{SANDBOX}/{DOC},{SANDBOX}/不存在.md"),
         has=("比了 2 处", "没读到", "只覆盖读到的那 1 篇"),
         lacks=("一处都没比成",)),
    Cell("B8_目录当文档", "`--docs` 手打指到目录：要人话，不许 traceback",
         2, argv=("--docs", SANDBOX), has=("那是个目录，不是文档",), lacks=("Traceback",)),
    Cell("B9_非UTF8文档", "读不出的编码：同一族第三种，也不许裸崩",
         2, bins=("坏件.bin",), argv=("--docs", f"{SANDBOX}/坏件.bin"),
         has=("读不出来",), lacks=("Traceback",)),
    Cell("B10_空base", "一张表都读不出来 = 一处都没比成，退 2",
         2, files=((DOC, "线路 {aptv:lines}〔数:aptv:lines〕 条"),),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--base", f"{SANDBOX}/空表"),
         has=("一张表都读不出来",)),
    Cell("B11_list配空base", "`--list` 在表读不出来时也不许退 0",
         2, argv=("--list", "--base", f"{SANDBOX}/空表"), has=("没有可列的数",)),
    Cell("B12_同键两条一对一错", "同一行两个标记：对的那条不许被顶掉，错的那条不许放过",
         1, files=((DOC, "对的 {aptv:lines}〔数:aptv:lines〕 条、错的 {aptv:lines+7}〔数:aptv:lines〕 条"),),
         has=("对得上 1 处", "对不上 1 处")),
    Cell("B13_三篇都不在", "几篇没读到要说得出数",
         2, argv=("--docs", f"{SANDBOX}/甲不在.md,{SANDBOX}/乙不在.md,{SANDBOX}/丙不在.md"),
         has=("有 3 篇没读到",)),
    Cell("B14_坏件混好文档", "读不出与不在走同一档：有成绩就退 1",
         1, files=((DOC, "线路 {aptv:lines}〔数:aptv:lines〕 条"),), bins=("坏件.bin",),
         argv=("--docs", f"{SANDBOX}/{DOC},{SANDBOX}/坏件.bin"),
         has=("比了 1 处", "读不出来")),
    Cell("B15_缺实测时probe键", "那一族读不到就明说读不到，别退 0",
         1, files=((DOC, "那家主机名下 1〔数:{@probe:host-lines:*}〕 条"),), copies=TABLES_ONLY,
         argv=("--docs", f"{SANDBOX}/{DOC}", "--base", f"{SANDBOX}/tables"),
         has=("读不出来", "接不住的标记 1 处")),
    Cell("B16_提示句跟着错值走", "对不上时要给下一步：先问表换没换",
         1, files=((DOC, "写着 {aptv:channels+3}〔数:aptv:channels〕 个"),),
         has=("table_drift.py", "表换没换")),
)


def build_cell(cell: Cell, base: Path, values: dict[str, int]) -> Path:
    """按格子说的那样种一个沙盒：文档、二进制件、从 `data/output/` 拷的那几张表。"""
    d = base / cell.who
    d.mkdir(parents=True, exist_ok=True)
    (d / "空表").mkdir(exist_ok=True)
    for name, body in cell.files:
        (d / name).write_text(fill(body, values), encoding="utf-8")
    for name in cell.bins:
        (d / name).write_bytes(BIN_BODY)
    if cell.copies:
        t = d / "tables"
        t.mkdir(exist_ok=True)
        for name in cell.copies:
            shutil.copy2(OUT_DIR / name, t / name)
    return d


def run_cell(cell: Cell, base: Path, values: dict[str, int]) -> tuple[str, str, str]:
    """跑一格：返回 `(判决, 为什么, 那一遍的原文)`。判决是 `ok`／`bad`／`崩`。"""
    d = build_cell(cell, base, values)
    argv = list(cell.argv) or ["--docs", f"{d}/{DOC}"]
    argv = [a.replace(SANDBOX, str(d)) for a in argv]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
    except SystemExit as e:                        # 有人把 main 改成 raise SystemExit
        rc = e.code if isinstance(e.code, int) else 99
    except BaseException as e:                     # noqa: BLE001 —— 崩了就是要被看见
        return "崩", f"{type(e).__name__}: {str(e).splitlines()[0][:70]}", ""
    text = hide_tmp(out.getvalue() + "\n" + err.getvalue(), base)
    if rc != cell.rc:
        return "bad", f"退码该 {cell.rc}、实际 {rc}", text
    miss = [fill(s, values) for s in cell.has if fill(s, values) not in text]
    if miss:
        return "bad", f"该印却没印：{miss}", text
    hits = [fill(s, values) for s in cell.lacks if fill(s, values) in text]
    if hits:
        return "bad", f"不该印却印了：{hits}", text
    return "ok", "", text


def self_test() -> int:
    """`--self-test`：往临时目录里种 26 格已知好坏的文档，逐格对预先写死的期望。

    结论行带着「扫了」那个词（`scripts/selfcheck.py` 的 `conclusion()` 靠它挑句子），
    过的一格一行流水、不符期望的**留在最后** —— 与 §2.57 那档同形，理由也同形：
    `selfcheck.run_script()` 失败时只摊末尾 14 行。

    退码：0 = 每格符合；1 = 有格子不符（逐格点名）；2 = 一格都没跑起来，或靶子先不对
    （名字带顿号、格子字面量写歪、`{键}` 点不到真值）。
    """
    bad_names = guard_names([c.who for c in BASELINE])
    if bad_names:
        print(bad_names)
        return 2
    ragged = ragged_cells(BASELINE)
    if ragged:
        print("基线自己有格子写歪了，改的是基线、不是判据：\n  " + "\n  ".join(ragged))
        return 2
    values, _missing = compute_values(OUT_DIR)
    holes = unresolvable(BASELINE, values)
    if holes:
        print("基线要点名却点不到的键：`data/output/` 这批表算不出这些数了 —— "
              "改的是基线，不是判据：" + "、".join(holes))
        return 2
    if not values:
        print("一格都没跑起来：`data/output/` 里一张表都读不出来，基线没有可比的对象。这不算过")
        return 2
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    with tempfile.TemporaryDirectory(prefix="doc-num-selftest-") as td:
        base = Path(td)
        for cell in BASELINE:
            verdict, why, text = run_cell(cell, base, values)
            ran += 1
            if verdict != "ok":
                bad += 1
                fails.append((cell, f"{'裸崩 ' if verdict == '崩' else ''}{why}", text))
                continue
            print(f"  ✓ {cell.who:<22} {cell.what}")
        if fails:
            print(f"\n—— 以下 {len(fails)} 格不符期望（每格把自己那一遍的原文摊出来）——")
            for cell, why, text in fails:
                print(f"  ✗ {cell.who:<22} {cell.what}\n      {why}")
                for line in text.strip().splitlines():
                    print(f"      | {line}")
    print(f"\n扫了基线 {len(BASELINE)} 格：{bad} 格不符期望"
          + (" —— 那把尺还咬得动" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())