"""把文档里抄来的那些数，逐个再算一遍（计划书 2.28）。

为什么要有这一条：`docs/真机验收单.md` 里那串数（39 个可疑台、24 没备选、14 换过去仍是专网、
0 换得到公网、tvgslb 22 个台、试播包 17 条覆盖 94 个台……）全是我从表和报告里**抄**进去的。
2.27 给了「表换没换」一道闸，但闸只说「这两份文件不是一张表」，它说不出**哪一句文档因此作废**。
表一换、这些数还躺在原处读起来像刚量过的 —— 这一层就是来收这笔账的。

怎么用它：文档里每个抄来的数后面挂一个 `〔数:<键>〕`，键说的是「这个数从哪张表、哪个算法来的」。
脚本重新从 `data/output/` 数一遍，再把写下来的数和算出来的数并排比。它不生成表、不联网。

    ./.venv/bin/python -X utf8 scripts/doc_num.py            # 验收：文档里的数还算不算数
    ./.venv/bin/python -X utf8 scripts/doc_num.py --list     # 现在每个键算出来是多少（抄数时对着它写）

退出码：**0 = 每一处都对得上**；**1 = 有数对不上、或有个标记我接不住**（写歪的括号、
不认识的键、括号前面没贴着数 —— 这三种都算失败，理由和 2.27 那条一样：**静默跳过就是假绿**）；
**2 = 一处都没比成**（文档里没有标记，或 `data/output/` 里的表读不出来）。

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
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from probe_pack import (base_of, channel_groups, focus_by_host,  # noqa: E402
                        host_of, load_results, load_stats)
from src.check.scope import PUBLIC, load_reachability            # noqa: E402
from src.cli import REACH_FILE, second_line_options              # noqa: E402
from src.output.writer import OutputChannel                      # noqa: E402

DEFAULT_DOCS = ("docs/真机验收单.md", "docs/电视订阅接入.md")
TABLES = {"aptv": "aptv.m3u", "hunan": "hunan.m3u"}
PACK = "probe-pack.m3u"

# 括号里的键只认这些字符。全角冒号、空格、漏写表名都会落到 `bad-key`，不会静悄悄不算。
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


def check_files(docs: list[Path], values: dict[str, int]) -> tuple[list[tuple], list[str]]:
    """把每篇文档里的标记逐个对一遍，返回 `(逐行结果, 每篇几处)`。

    每行结果是六元组 `(位置, 键, 写下来的数, 算出来的数, 毛病, 为什么)`，`毛病` 空串就是对上了。
    键最多三段（`表:量:主机`），少于三段在 `parse_marks` 那关就已经算 `bad-key`，这里不再判。
    """
    rows: list[tuple] = []
    counts: list[str] = []
    for path in docs:
        if not path.exists():
            counts.append(f"{path}（文件不在）")
            continue
        disp = path.relative_to(ROOT) if str(path).startswith(str(ROOT)) else path
        marks = parse_marks(path.read_text(encoding="utf-8"))
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
    return rows, counts


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
    args = ap.parse_args(argv)

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
    rows, counts = check_files(docs, values)
    absent = [str(d) for d in docs if not d.exists()]
    if absent:
        # 点名要查的文档不在，就等于它里面每一个 〔数:…〕 都没查 —— 别跟着别篇的成绩退 0。
        # 最坏的一种绿是「文档改了个名，这一层少一篇覆盖，屏幕上照旧全部对得上」：
        # 真机验收单那 28 处会整篇消失，而它正是这六步唯一能对上的那一份。
        # （`--docs` 里给个不存在的名字，只可能是手打错了或文档搬家了，两种都不该由它替我说「没问题」。）
        for d in absent:
            print(f"！点名的文档不在：{d} —— 它那些标记一个都没查到，不算通过", file=sys.stderr)
        return 2
    print(f"以 {as_of(base)} 为准")
    if missing:
        for m in missing:
            print(f"！缺：{m}")
    if not rows:
        print(f"{'、'.join(counts) or '没有一篇文档读得到'}："
              "一个 〔数:…〕 标记都没有 —— 这不算通过。", file=sys.stderr)
        return 2
    for line in render(rows):
        print(line)
    bad = [r for r in rows if r[4]]
    diffs = [r for r in rows if r[4] == "diff"]
    print(f"\n比了 {len(rows)} 处（{'、'.join(counts)}）："
          f"{'对得上 ' + str(len(rows) - len(bad)) + ' 处' if bad else '全部对得上'}"
          + (f"，**对不上 {len(diffs)} 处**" if diffs else "")
          + (f"，接不住的标记 {len(bad) - len(diffs)} 处" if len(bad) - len(diffs) else ""))
    if bad:
        print("对不上不等于算错了：先跑 `scripts/table_drift.py` 问一句「表换没换」，"
              "换了就按新表重抄这些数，没换就是我抄错了或者键挂错了。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
