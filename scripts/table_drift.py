"""回答一句话：`report.md` 说的那张表，还是不是电视上正在订阅的那张表。

为什么要有这个检查（计划书 2.27）：报告里的「第一线主机集中度」和「换第二条线路救得回来吗」
都只描述**它生成时那张表**。而 `data/output/aptv.m3u` 是订阅进电视的那一份 ——
我改了排序、换了节目单对账、上游抽风之后重出一遍，报告读起来仍然像在同一张表上说话。
2.26 那天为了确认这件事，手工 `diff` 了一次（结论：线路序列逐字节相同，差异全在 `tvg-id`），
一次性的手工比对不构成保障 —— 同样的问题值得随时能问第二遍。

它不生成任何东西：**只读两份已经存在的表**。所以标准用法是两行，
第二行的 `/tmp/r226` 由第一行产出（`--replay` 本轮不联网测任何东西，产物另指，
`data/output/` 一个字都不动）：

    ./.venv/bin/python -X utf8 -m src.cli build --replay --out /tmp/r226
    ./.venv/bin/python -X utf8 scripts/table_drift.py --against /tmp/r226

同一套东西顺手还能答另一问：**试播包旧没旧**（它是从那张表派生出来的）。
先 `probe_pack.py --in /tmp/r226/aptv.m3u --out /tmp/p227/probe-pack.m3u` 从重出那份表再跑一遍包，然后：

    ./.venv/bin/python -X utf8 scripts/table_drift.py --against /tmp/p227 --files probe-pack.m3u

退出码：**0 = 两张表是同一张表**（线路级一字不差）；**1 = 换表了**，
并把换了谁点名（第一线换了算最重，台多了/少了次之，只动第 2、3 条线再次之）；
**1 还管第二种**：某一张**在、却读不进来**（指到的是目录、里面不是 UTF-8）—— 那一条比不了，
「量到了但覆盖缺一块」不是「量过了、没问题」；2 = 一张都没比成或参数不对 ——
跳过的那些**不算一致**，「全跳过 + 报绿」是这种检查最坏的失败方式。
「文件名两边都有才比」那条**不算**读不进来：那是要比的东西压根没被点名，屏幕上说得出「另 N 张没比」。
属性差异（`tvg-id`、`tvg-logo`、头部那行节目单地址）**不算换表**，
但一定写出来：它解释的是「那几百行 diff 到底是什么」，不是可以忽略的噪声。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from baseline_guard import guard as guard_names   # noqa: E402  顿号那道闸（几把基线尺共用）
from doc_num import hide_tmp, read_doc            # noqa: E402
from probe_pack import channel_groups             # noqa: E402
from run_doctests import (DOCTEST_FLAG, SELF_TEST_FLAG, add_doctest_flag,       # noqa: E402
                          arg_door_answered, arg_door_exit, run_own)
# `--doctest` 那一旗的口径只有一份；2.79 起「这一遍答哪一扇」也只有一份

# `read_doc` 不是这里另写的一份：那三种读法（不在 / 是目录 / 不是 UTF-8）在 2.36、2.58、2.62
# 里一处一处补进 `doc_num`，共用一份才不会再出现「同一件事在两个脚本里说法不同」。
# 这一族以前的样子：`pa.read_text(encoding="utf-8")` 直接崩，整段 traceback，退码 1 ——
# 而 1 在这把尺上是「换表了」，一个崩溃就这样冒充了一个判定（2.62 立的口径）。


def diff_tables(a: list[tuple[str, list[str]]],
                b: list[tuple[str, list[str]]]) -> dict:
    """两张表按「台名顺序 + 每台的线路序列」比，只答一件事：线路级换没换。

    为什么按位置比而不是按台名建索引：同名不同 id 的两个桶在电视上是两个台
    （`channel_groups` 的分组口径就是照 APTV 抄的），按台名建 dict 会把它们并成一个，
    恰好把「多出来一个台」这种漂移读成没变。顺序本身就是表的一部分 —— APTV 里那是两个频道位。

    只在一侧出现的台进 `added` / `removed`，不再逐条比线路（位置都错开了，比出来的「第 3 条不同」没意义）。
    每个台的两条线路**数**可以不一样长（`--max-lines` 改大就是这种），多出来/少掉的条数记进
    `extra_a` / `extra_b` —— 不记的话「每台从 3 条加到 6 条」这种漂移会被逐条比对整个看不见。

    >>> d = diff_tables([("湖南卫视", ["http://a/1", "http://b/2"]),
    ...                  ("经视", ["http://c/3"])],
    ...                 [("湖南卫视", ["http://a/1", "http://b/2"]),
    ...                  ("经视", ["http://c/3"])])
    >>> (d["lines_same"], d["lines_a"], d["channels_a"], d["name_seq_same"])
    (True, 3, 2, True)
    >>> # 第一线换了：最重手，电视上默认播的就不是同一条流了
    >>> d2 = diff_tables([("湖南卫视", ["http://a/1"])], [("湖南卫视", ["http://x/9"])])
    >>> (d2["lines_same"], d2["first_changes"], d2["line_changes"])
    (False, [('湖南卫视', 'http://a/1', 'http://x/9')], [('湖南卫视', 1, 'http://a/1', 'http://x/9')])
    >>> # 只动备选线路也算换表（判分面没变，但报告说「这张表有几条备选」时说的不是同一张）
    >>> db = diff_tables([("湖南卫视", ["http://a/1", "http://b/2"])],
    ...                  [("湖南卫视", ["http://a/1", "http://z/8"])])
    >>> (db["first_changes"], db["alt_changes"], db["alt_channels"])
    ([], 1, 1)
    >>> # 加宽：一条地址都没换，只是每个台多留了几条 —— 仍然是换表，但要说清换了什么
    >>> dw = diff_tables([("湖南卫视", ["http://a/1"])],
    ...                  [("湖南卫视", ["http://a/1", "http://b/2", "http://c/3"])])
    >>> (dw["lines_same"], dw["line_changes"], dw["extra_b"], dw["alt_channels"])
    (False, [], 2, 1)
    >>> # 多个台 / 少个台：位置从那里开始全错，就不逐条比了
    >>> d3 = diff_tables([("甲", ["http://a/1"])], [("甲", ["http://a/1"]), ("乙", ["http://b/2"])])
    >>> (d3["lines_same"], d3["added"], d3["removed"], d3["line_changes"])
    (False, ['乙'], [], [])
    >>> # 同名不同 id 是两个台：这里两份都是两个「湖南卫视」，位置比出来就是两条独立记录
    >>> d4 = diff_tables([("湖南卫视", ["http://a/1"]), ("湖南卫视", ["http://b/2"])],
    ...                  [("湖南卫视", ["http://a/1"])])
    >>> (d4["channels_a"], d4["channels_b"], d4["lines_same"])
    (2, 1, False)
    """
    out = {"channels_a": len(a), "channels_b": len(b),
           "lines_a": sum(len(u) for _, u in a), "lines_b": sum(len(u) for _, u in b),
           "names_a": [n for n, _ in a], "names_b": [n for n, _ in b],
           "line_changes": [], "first_changes": [], "alt_changes": 0, "alt_channels": 0,
           "extra_a": 0, "extra_b": 0, "added": [], "removed": []}
    out["name_seq_same"] = out["names_a"] == out["names_b"]
    if out["name_seq_same"]:
        for (n, ua), (_, ub) in zip(a, b):
            alt_hit = len(ua) != len(ub)          # 条数不等也算「这个台的备选部分变了」
            for i, (x, y) in enumerate(zip(ua, ub), 1):
                if x == y:
                    continue
                out["line_changes"].append((n, i, x, y))
                if i == 1:
                    out["first_changes"].append((n, x, y))
                else:
                    out["alt_changes"] += 1
                    alt_hit = True
            short = min(len(ua), len(ub))
            out["extra_a"] += len(ua) - short
            out["extra_b"] += len(ub) - short
            out["alt_channels"] += 1 if alt_hit else 0
    else:
        kb = {n for n, _ in b}
        ka = {n for n, _ in a}
        out["added"] = [n for n in out["names_b"] if n not in ka]
        out["removed"] = [n for n in out["names_a"] if n not in kb]
    out["lines_same"] = (out["name_seq_same"] and not out["line_changes"]
                         and out["lines_a"] == out["lines_b"])
    return out


def strip_attrs(line: str) -> str:
    """去掉 `tvg-id` / `tvg-logo` 这两个「我们这层写进去的」属性，看这行还剩什么。

    为什么单摘这两个：它们是 P3（EPG 对齐）的产物，换一份节目单就会整批变，
    而它们**不改变能播的内容**。其余属性（`group-title`、台名）变了就是分组/命名真的动了。

    >>> strip_attrs('#EXTINF:-1 tvg-id="81" tvg-logo="https://x/y.png" group-title="📍 湖南",湖南卫视')
    '#EXTINF:-1 group-title="📍 湖南",湖南卫视'
    >>> strip_attrs('#EXTINF:-1 tvg-id="湖南卫视",湖南卫视')     # 只剩 id：去掉就是干净的一行
    '#EXTINF:-1 ,湖南卫视'
    """
    out = line
    for key in ("tvg-id", "tvg-logo"):
        pre, _, rest = out.partition(f'{key}="')
        if rest:
            out = pre + rest.partition('"')[2]
    return " ".join(out.split())


def attribute_delta(a_text: str, b_text: str) -> dict:
    """那几百行 `diff` 到底是什么：把**行级**差异按「谁改的」分类。

    分四类是因为只有一类要紧：`lines`（线路本身，`http` 开头）变了才叫换表；
    `ids` 是 EPG 对账换写法，`other_attrs` 是分组/台名，`header` 是头部那行节目单地址。
    行数不等时多出来的那段整体算 `other_attrs` 并记在 `len_diff`，不假装对齐得上一一归类。

    >>> a = ('#EXTM3U x-tvg-url="http://old/e.xml.gz"\\n'
    ...      '#EXTINF:-1 tvg-id="x",湖南卫视\\nhttp://a/1\\n')
    >>> b = ('#EXTM3U x-tvg-url="http://new/e.xml.gz"\\n'
    ...      '#EXTINF:-1 tvg-id="81",湖南卫视\\nhttp://a/1\\n')
    >>> attribute_delta(a, b)                                   # 只有头部和 tvg-id 动了
    {'lines': 0, 'ids': 1, 'other_attrs': 0, 'header': 1, 'len_diff': 0}
    >>> # 台名（逗号后面那段）变了不算属性噪声 —— 那是分组/命名真的动了
    >>> attribute_delta('#EXTINF:-1 tvg-id="1",湖南卫视\\n', '#EXTINF:-1 tvg-id="1",湖南卫视HD\\n')['other_attrs']
    1
    >>> attribute_delta('#EXTINF:-1 tvg-id="1",湖南卫视\\nhttp://a/1\\n',
    ...                 '#EXTINF:-1 tvg-id="1",湖南卫视\\nhttp://b/1\\n')['lines']
    1
    """
    la, lb = a_text.splitlines(), b_text.splitlines()
    d = {"lines": 0, "ids": 0, "other_attrs": 0, "header": 0, "len_diff": abs(len(la) - len(lb))}
    for x, y in zip(la, lb):
        if x == y:
            continue
        if x.startswith("http") or y.startswith("http"):
            d["lines"] += 1
        elif x.startswith("#EXTM3U") or y.startswith("#EXTM3U"):
            d["header"] += 1
        elif strip_attrs(x) == strip_attrs(y):
            d["ids"] += 1
        else:
            d["other_attrs"] += 1
    return d


def verdict(name: str, d: dict, att: dict) -> str:
    """一张表一行话：先给结论，再给那几百行差异的解释。

    措辞故意分成两种开头（「同一张表」/「**换表了**」），因为这一行的唯一用途就是
    让人决定「报告里那些数还作不作数」。属性差异跟在后面，不当结论也不藏起来。
    换表那半边还要分清新是哪一种：**第一线换了**才影响电视上默认播的东西，
    备选条数变了（比如 `--max-lines` 从 3 加到 6）动的是「有没有退路」那一层。

    >>> D = {"lines_same": True, "channels_a": 98, "channels_b": 98, "lines_a": 226, "lines_b": 226,
    ...      "line_changes": [], "first_changes": [], "alt_changes": 0, "alt_channels": 0,
    ...      "extra_a": 0, "extra_b": 0, "added": [], "removed": []}
    >>> print(verdict("aptv.m3u", D, {"lines": 0, "ids": 187, "other_attrs": 0,
    ...                               "header": 1, "len_diff": 0}))
    aptv.m3u：同一张表 —— 226 条线路一字不差；另有 187 行只是 tvg-id／tvg-logo 变了（节目单对账换了写法，能播的东西没换），头部节目单地址变了 1 行
    >>> d2 = dict(D, lines_same=False, first_changes=[("湖南卫视", "http://a/1", "http://b/2")],
    ...           line_changes=[("湖南卫视", 1, "http://a/1", "http://b/2")])
    >>> print(verdict("hunan.m3u", d2, {"lines": 2, "ids": 0, "other_attrs": 0, "header": 0,
    ...                                  "len_diff": 0}))
    hunan.m3u：**换表了** —— 1 个台的第一线换了（湖南卫视：`http://a/1` → `http://b/2`）
    >>> # 只动第 2、3 条线：还是换表，但不说成「默认播的变了」
    >>> only_bak = dict(D, lines_same=False, alt_changes=1, alt_channels=1,
    ...                 line_changes=[("湖南卫视", 2, "http://a/2", "http://b/9")])
    >>> print(verdict("hunan.m3u", only_bak, {"lines": 1, "ids": 0, "other_attrs": 0,
    ...                                       "header": 0, "len_diff": 0}))
    hunan.m3u：**换表了** —— 1 个台的第 2 条及以后不同（换地址 1 处、多 0 条、少 0 条）
    >>> # 加宽（`--max-lines` 3 → 6）：一条地址没换，但每个台多出三条 —— 这是那种最容易读错的
    >>> wide = dict(D, lines_same=False, lines_b=452, alt_channels=98, extra_b=226)
    >>> print(verdict("hunan.m3u", wide, {"lines": 0, "ids": 0, "other_attrs": 0, "header": 0,
    ...                                   "len_diff": 226}))
    hunan.m3u：**换表了** —— 98 个台的第 2 条及以后不同（换地址 0 处、多 226 条、少 0 条）
    >>> "多了 1 个台：新台" in verdict("hunan.m3u", dict(D, lines_same=False, added=["新台"]),
    ...                                {"lines": 1, "ids": 0, "other_attrs": 0, "header": 0,
    ...                                 "len_diff": 0})
    True
    """
    if d["lines_same"]:
        tail = ""
        if att["ids"]:
            tail += (f"；另有 {att['ids']} 行只是 tvg-id／tvg-logo 变了"
                     "（节目单对账换了写法，能播的东西没换）")
        if att["header"]:
            tail += f"，头部节目单地址变了 {att['header']} 行"
        if att["other_attrs"]:
            tail += f"；还有 {att['other_attrs']} 行分组/台名也动了"
        return f"{name}：同一张表 —— {d['lines_a']} 条线路一字不差{tail}"
    bits = []
    if d["first_changes"]:
        ex = "、".join(f"{n}：`{x}` → `{y}`" for n, x, y in d["first_changes"][:3])
        bits.append(f"{len(d['first_changes'])} 个台的第一线换了（{ex}"
                    + ("…）" if len(d["first_changes"]) > 3 else "）"))
    if d.get("alt_changes") or d.get("alt_channels"):
        bits.append(f"{d['alt_channels']} 个台的第 2 条及以后不同"
                    f"（换地址 {d.get('alt_changes', 0)} 处、"
                    f"多 {d.get('extra_b', 0)} 条、少 {d.get('extra_a', 0)} 条）")
    if d["added"]:
        bits.append(f"多了 {len(d['added'])} 个台：" + "、".join(d["added"][:5]))
    if d["removed"]:
        bits.append(f"少了 {len(d['removed'])} 个台：" + "、".join(d["removed"][:5]))
    if not bits:
        bits.append(f"台数或顺序对不上（{d['channels_a']} 个台 / {d['lines_a']} 条 ↔ "
                    f"{d['channels_b']} 个台 / {d['lines_b']} 条）")
    return f"{name}：**换表了** —— " + "；".join(bits)


def empty_pair(d: dict) -> bool:
    """两边都是空表：这一对「比了等于没比」。

    为什么单独有这一条：`lines_same` 的定义是「频道序列一致 + 没有线路改动 + 两边线路数相等」，
    两份空文件在这三条上全成立，于是它给「同一张表 —— 0 条线路一字不差」并且退 0。
    那正是这把尺最不该给的一种绿：**上游抽风把两张表都写成空的**，跟「上一轮和这一轮是同一张表」
    是两回事，前者是产物坏了，后者才是它要回答的问题。

    >>> empty_pair({"lines_a": 0, "lines_b": 0})
    True
    >>> empty_pair({"lines_a": 226, "lines_b": 226})
    False
    >>> empty_pair({"lines_a": 0, "lines_b": 251})    # 只有一边空：那是「换表了」，不是「没比」
    False
    """
    return not d["lines_a"] and not d["lines_b"]


HDR = '#EXTM3U x-tvg-url="https://e.erw.cc/e.xml.gz"\n'
ONE = HDR + '#EXTINF:-1 tvg-id="81" group-title="g",湖南卫视\nhttp://a/1.m3u8\n'
TWO = HDR + '#EXTINF:-1 tvg-id="81" group-title="g",湖南卫视\nhttp://z/9.m3u8\n'
EMPTY_TABLE = "#EXTM3U\n"
NON_UTF8 = b"#EXTM3U\n" + bytes([0xFF, 0xFE, 0x41])   # 头一行是表，第八个字节起不是 UTF-8


def outcome(checked: int, drift: int, unread: int) -> int:
    """这一轮该退几：2 = 一张都没比成，1 = 换表了**或**有点名却读不进来的，0 = 都读到且一张没换。

    为什么把这三档判断从一个数里拎出来单独钉：`main()` 以前只分「有没有 drift」和
    「比成了几张」，退码是散在收尾那三段 `return` 里的 —— 于是 2.63 那种「读不进来也算一块没量到」
    根本没有一个地方能钉住它（只能在屏幕上手量一遍，下次改回去也没人知道）。
    口径同 2.62：**2 = 这把尺这次什么都没量到；1 = 量到了、但有毛病或覆盖缺一块；0 = 全对且全读到**。

    >>> outcome(2, 0, 0)          # 两张都读到、一张没换
    0
    >>> outcome(2, 1, 0)          # 换表了
    1
    >>> outcome(1, 0, 1)          # 读到那张没换，可另一张点名要读却读不进来 —— 不给 0
    1
    >>> outcome(0, 0, 2)          # 一张都没比成，读不进来那两条并到 2 里（2 比 1 更该先说）
    2
    >>> outcome(0, 0, 0)          # 一个文件都没点名（`--files ""`）：也是什么都没量到
    2
    """
    if not checked:
        return 2
    return 1 if (drift or unread) else 0


# ============================== 2.64：这把尺的回归基线 ==============================
#
# 为什么要单独一档：2.63 把三档退码（2 = 什么都没量到／1 = 量到了但有一块没量到／0 = 全对且全读到）
# 立起来之后，那些形状**只活在 12 条 doctest 里** —— 而这一支脚本在 `scripts/selfcheck.py` 里
# 默认根本不跑（`drift` 那一步要人给 `--against`）。也就是说「改对了」这件事当时没有任何闸守着：
# 谁把 `unread` 从退码里摘掉，屏幕上、退码上、自检里都不会有人响。
# 这一档补的就是那一块，形状照 2.56—2.59、2.62：种进临时沙盒、跑**真的 `main()`**、逐格对退码与句子。
# 沙盒全在 `tempfile` 里，`data/output/` 一个字节都不动，也不发一个请求。


class Cell(NamedTuple):
    """一格基线：沙盒里种什么、用什么参数问它、期望屏幕上出现什么、不许出现什么。

    `files` 的键是**沙盒里的相对路径**（`基准/aptv.m3u`），值是表的内容；`dirs` 那些名字造成目录
    （`--files` 点到它就是「在、却读不进来」那一档），`bins` 造成非 UTF-8 的件。
    `argv` 里 `{T}` 在跑之前换成这一轮沙盒的真路径；`has`／`lacks` 里写 `<T>`，
    因为屏幕上那串临时路径跑之前谁也不知道（`hide_tmp` 负责抹回来）。
    """
    who: str
    what: str
    rc: int
    files: tuple[tuple[str, str], ...] = ()
    dirs: tuple[str, ...] = ()
    bins: tuple[str, ...] = ()
    argv: tuple[str, ...] = ()
    has: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()
    once: tuple[str, ...] = ()


A, B = "基准", "重出"        # 沙盒里那两个目录名：`--dir` 那一边、`--against` 那一边


def argv_of(*files: str) -> tuple[str, ...]:
    """拼一格用的 argv：两个目录固定在沙盒里，只有 `--files` 那一串逐格不同。

    >>> print(" ".join(argv_of("aptv.m3u")))
    --dir {T}/基准 --against {T}/重出 --files aptv.m3u
    >>> print(" ".join(argv_of("aptv.m3u", "坏件.m3u")))
    --dir {T}/基准 --against {T}/重出 --files aptv.m3u,坏件.m3u
    """
    return ("--dir", f"{{T}}/{A}", "--against", f"{{T}}/{B}", "--files", ",".join(files))


BASELINE: tuple[Cell, ...] = (
    # ———— 甲／乙：判据本身。这两格 2.63 量过「改前改后逐字节相同」，现在钉住它 ————
    Cell("甲_一张线路都没换", "常态：比成了、一张没换，退 0 且那句「完全一致」要说得出覆盖了谁",
         0, files=((f"{A}/aptv.m3u", ONE), (f"{B}/aptv.m3u", ONE)), argv=argv_of("aptv.m3u"),
         has=("aptv.m3u：同一张表 —— 1 条线路一字不差",
              "线路级完全一致：报告里那些数说的就是这一张表"),
         lacks=("Traceback", "读不进来", "没比", "换表了")),
    Cell("乙_第一线换了", "最重手那种漂移：电视上默认播的那条流变了，1 = 换表了",
         1, files=((f"{A}/aptv.m3u", ONE), (f"{B}/aptv.m3u", TWO)), argv=argv_of("aptv.m3u"),
         has=("**换表了** —— 1 个台的第一线换了", "1 张表和基准不是一张表"),
         lacks=("线路级完全一致", "读不进来", "Traceback")),
    # ———— 丙／丁／戊：2.63 那一族「在、却读不进来」。三格各自钉一种读法 ————
    Cell("丙_点名的那张是目录", "`--files` 点到目录：以前整段 traceback 退 1（=「换表了」），现在 1 = 有一块没量到",
         1, files=((f"{A}/aptv.m3u", ONE), (f"{B}/aptv.m3u", ONE)),
         dirs=(f"{A}/是目录.m3u", f"{B}/是目录.m3u"), argv=argv_of("aptv.m3u", "是目录.m3u"),
         has=("！是目录.m3u：读不进来 —— <T>/基准/是目录.m3u —— 那是个目录，不是文档",
              "另有 1 张读不进来（是目录.m3u）", "上面那句不覆盖它们"),
         lacks=("Traceback", "IsADirectoryError", "线路级完全一致")),
    Cell("丁_点名的那张不是UTF8", "同一族第二种：改名没用，所以那句也不许写成「那是个目录」",
         1, files=((f"{A}/aptv.m3u", ONE), (f"{B}/aptv.m3u", ONE)),
         bins=(f"{A}/坏件.m3u", f"{B}/坏件.m3u"), argv=argv_of("aptv.m3u", "坏件.m3u"),
         has=("！坏件.m3u：读不进来 —— <T>/基准/坏件.m3u —— 读不出来：",
              "另有 1 张读不进来（坏件.m3u）"),
         lacks=("Traceback", "UnicodeDecodeError", "那是个目录", "文件不在")),
    Cell("戊_两张都读不进来", "2 = 这把尺这次什么都没量到 —— 它以前退 1，等于凭空指控产物换表了",
         2, dirs=(f"{A}/是目录.m3u", f"{B}/是目录.m3u"),
         bins=(f"{A}/坏件.m3u", f"{B}/坏件.m3u"), argv=argv_of("是目录.m3u", "坏件.m3u"),
         has=("一张表都没比成", "另有 2 张读不进来"),
         lacks=("同一张表", "线路级", "Traceback")),
    # ———— 己／庚／辛：三种「不进退码」与「退 2」的分界，2.63 的量现在有人守着 ————
    Cell("己_只有一边有这个名", "老规矩：这种是压根没被点名，屏幕上说得出「另 N 张没比」，不进退码",
         0, files=((f"{A}/aptv.m3u", ONE), (f"{B}/aptv.m3u", ONE)),
         argv=argv_of("aptv.m3u", "没这个名.m3u"),
         has=("没这个名.m3u：跳过（<T>/基准/没这个名.m3u 不在）",
              "比了的 1 张线路级一致、另 1 张没比", "没比的：没这个名.m3u"),
         lacks=("读不进来", "Traceback"), once=("：跳过（",)),
    Cell("庚_两边都是空表", "两边都 0 条线路：比了等于没比，那一对着陆在 2 而不是 0",
         2, files=((f"{A}/空.m3u", EMPTY_TABLE), (f"{B}/空.m3u", EMPTY_TABLE)),
         argv=argv_of("空.m3u"),
         has=("两边都是 0 条线路 —— 比了等于没比，这一对不算数", "一张表都没比成",
              "或者有但两边都是空的"),
         lacks=("同一张表", "线路级完全一致", "Traceback")),
    Cell("辛_against不是目录", "参数那一档：目录给错了也是「什么都没量到」，退 2 并说清下一步跑什么",
         2, files=((f"{A}/aptv.m3u", ONE),),
         argv=("--dir", "{T}/基准", "--against", "{T}/没有这个目录", "--files", "aptv.m3u"),
         has=("找不到 <T>/没有这个目录",), lacks=("Traceback", "同一张表")),
    # ———— 壬：那三种读法的**同屏**版：一句话只有一份（`doc_num.read_doc`），三种毛病一起点 ————
    Cell("壬_三种读法同屏", "跳过／是目录／不是 UTF-8 同时点名：三种说法各一句，且退码只由「读不进来」那一类抬",
         1, files=((f"{A}/aptv.m3u", ONE), (f"{B}/aptv.m3u", ONE)),
         dirs=(f"{A}/是目录.m3u", f"{B}/是目录.m3u"), bins=(f"{A}/坏件.m3u", f"{B}/坏件.m3u"),
         argv=argv_of("aptv.m3u", "是目录.m3u", "坏件.m3u", "不在.m3u"),
         has=("：跳过（", "那是个目录，不是文档", "读不出来：",
              "另有 2 张读不进来", "上面那句不覆盖它们"),
         lacks=("Traceback", "线路级完全一致")),
)


def run_cell(cell: Cell, base: Path) -> tuple[str, str, str]:
    """跑一格：`(判定, 给人看的那句, 抹过沙盒路径的原文)`，判定是 `ok` / `bad` / `崩`。

    走的是真的 `main()` 而不是中间函数：退码、那句「上面那句不覆盖它们」、stderr 上那行点名，
    全是这一格要看的东西（2.56 起的同一取舍）。stdout 与 stderr 收进**同一个**缓冲区再比，
    因为这把尺最要紧的三句话里有两句在 stderr 上。
    """
    for rel in cell.dirs:
        (base / rel).mkdir(parents=True, exist_ok=True)
    for rel, body in cell.files:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body.replace("{T}", str(base)), encoding="utf-8")
    for rel in cell.bins:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(NON_UTF8)
    argv = [a.replace("{T}", str(base)) for a in (cell.argv or argv_of("aptv.m3u"))]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
    except Exception as e:                        # 尺自己炸了不许读成「这格没过」以外的任何东西
        return "bad", f"跑这一格时抛了 {type(e).__name__}: {e}", ""
    text = hide_tmp(buf.getvalue(), base)
    good, why = check_cell(cell, rc, text)
    return ("ok", "", text) if good else ("bad", why, text)


def check_cell(cell: Cell, rc: int, text: str) -> tuple[bool, str]:
    """这一格对上了没有：退码、该出现的句子、不该出现的句子、只许出现一次的句子。

    `lacks` 与 `has` 一样重要：这一族的毛病正是「同一件事有三种说法，而它们会互相冒充」
    —— 「读不出来：」那一格若写成「文件不在」，退码照样对、句子照样有，只有 `lacks` 拦得住。
    """
    if rc != cell.rc:
        return False, f"退码：期望 {cell.rc}，实际 {rc}"
    for s in cell.has:
        if s not in text:
            return False, f"屏幕上没有那句：{s}"
    for s in cell.lacks:
        if s in text:
            return False, f"多说了那句：{s} —— 误伤"
    for s in cell.once:
        if text.count(s) != 1:
            return False, f"那句出现了 {text.count(s)} 次，期望恰好 1 次：{s}"
    return True, ""


def sloppy_cells(cells: tuple[Cell, ...]) -> list[str]:
    """格子自己写歪的地方（占位符串错位、同一句又 `has` 又 `lacks`、一句都没钉）。

    为什么要有：`{T}` 是给 argv 用的，写进 `has` 就是作者把两个占位符弄混了 —— 那一格会
    **永远红**，红得像判据坏了。`has` 与 `lacks` 撞同一句则是永远不可能满足。这两种都在跑之前
    拦掉，别让人去怀疑那把尺（2.58 的 `ragged_cells` 同一层）。

    >>> sloppy_cells((Cell("好", "x", 0, has=("同一张表",), lacks=("读不进来",)),))
    []
    >>> for why in sloppy_cells((Cell("坏", "x", 0, has=("{T}/a",)),)): print(why)
    坏：`has` 里写了 `{T}`，argv 才用这个占位符，屏幕上的路径要写 `<T>`
    >>> for why in sloppy_cells((Cell("撞", "x", 0, has=("一句",), lacks=("一句",)),)): print(why)
    撞：同一句既是 `has` 又是 `lacks`，这一格永远不可能过
    >>> for why in sloppy_cells((Cell("空", "x", 0),)): print(why)
    空：这一格一句都没钉，只比退码 —— 那是「跑过一遍」不是「量过一件事」
    """
    out: list[str] = []
    for c in cells:
        if any("{T}" in s for s in c.has + c.lacks + c.once):
            out.append(f"{c.who}：`has` 里写了 `{{T}}`，argv 才用这个占位符，"
                       "屏幕上的路径要写 `<T>`")
        both = set(c.has) & set(c.lacks)
        if both:
            out.append(f"{c.who}：同一句既是 `has` 又是 `lacks`，这一格永远不可能过")
        if not (c.has or c.lacks or c.once):
            out.append(f"{c.who}：这一格一句都没钉，只比退码 —— 那是「跑过一遍」不是「量过一件事」")
    return out


def self_test(cells: tuple[Cell, ...] | None = None) -> int:
    """`--self-test`：每格一个**新**沙盒，逐格对期望；结论行带「扫了」那个词给 `selfcheck` 挑。

    每格单独一个临时目录是 2.63 踩的第 5 条换来的：同一秒内、字节数相同的两份改动写进
    同一个文件名，`import` 与文件系统都会拿到上一格的东西（那遍整批作废）。
    退码：0 = 每格都符合期望；1 = 有格子不符（逐格点名）；2 = 一格都没跑起来，或基线自己写歪了。
    """
    cells = BASELINE if cells is None else cells
    bad_names = guard_names([c.who for c in cells])
    if bad_names:
        print(bad_names)
        return 2
    sloppy = sloppy_cells(cells)
    if sloppy:
        print("基线自己有格子写歪了，改的是基线、不是判据：\n  " + "\n  ".join(sloppy))
        return 2
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    for cell in cells:
        with tempfile.TemporaryDirectory(prefix="table-drift-selftest-") as td:
            verdict, why, text = run_cell(cell, Path(td))
        ran += 1
        if verdict != "ok":
            bad += 1
            fails.append((cell, why, text))
            continue
        print(f"  ✓ {cell.who:<22} {cell.what}")
    if fails:
        print(f"\n—— 以下 {len(fails)} 格不符期望（每格把自己那一遍的原文摊出来）——")
        for cell, why, text in fails:
            print(f"  ✗ {cell.who:<22} {cell.what}\n      {why}")
            for line in text.strip().splitlines():
                print(f"      | {line}")
    print(f"\n扫了基线 {len(cells)} 格：{bad} 格不符期望"
          + (" —— 那把尺还咬得动" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="比对两张已生成的表：报告说的是不是电视上那张")
    ap.add_argument("--against", default="", metavar="目录",
                    help="离线重出的那份表所在的目录（`build --replay --out /tmp/…` 的产物；"
                         "`--self-test` 那一档不需要它）")
    ap.add_argument("--dir", default=str(OUT_DIR),
                    help="基准目录，默认 data/output（订阅进电视的那批产物）")
    ap.add_argument("--files", default="aptv.m3u,hunan.m3u",
                    help="比哪几张表，逗号分隔；两边都有这个文件名才比")
    ap.add_argument("--self-test", action="store_true", dest="self_test",
                    help="往临时沙盒里种已知的表，逐格对退码与屏幕上那几句（计划书 2.64）")
    add_doctest_flag(ap)
    args = ap.parse_args(argv)
    door_rc = arg_door_exit(args)      # 2.79：两扇一起递时不再静默，那句门口话与收集器同一份
    if door_rc is not None:
        return door_rc
    answered = arg_door_answered(args)

    if answered == DOCTEST_FLAG:
        return run_own(sys.modules[__name__])   # 2.69：先答说明书，一张表都不比
    if answered == SELF_TEST_FLAG:
        return self_test()
    if not args.against:
        ap.error("--against 是必需的：这把尺问的是「两边是不是同一张表」，得有两边"
                 "（自己跟自己比永远报绿）")

    b_dir, a_dir = Path(args.against), Path(args.dir)
    if not b_dir.is_dir():
        print(f"找不到 {b_dir}：先跑 ./.venv/bin/python -X utf8 -m src.cli build --replay --out {b_dir}",
              file=sys.stderr)
        return 2
    drift = checked = 0
    skipped: list[str] = []
    unread: list[str] = []
    for fn in [f.strip() for f in args.files.split(",") if f.strip()]:
        pa, pb = a_dir / fn, b_dir / fn
        ta, wa = read_doc(pa)
        tb, wb = read_doc(pb)
        # 「不在」和「在、却读不进来」是两件事，分两档走：前者是这一对压根没被点名
        # （`--files` 那句 help 早就这么约定的），屏幕上说得出「另 N 张没比」，不进退码；
        # 后者是手指头指错了地方（那是个目录）或那份东西不是 UTF-8 —— 它被点名了、却没读成，
        # 算覆盖缺一块，要进退码（2.62 立的口径：1 = 量到了但有一块没量到）。
        if wa == "文件不在" or wb == "文件不在":
            print(f"{fn}：跳过（{pa if wa == '文件不在' else pb} 不在）")
            skipped.append(fn)
            continue
        if ta is None or tb is None:
            bad, why = (pa, wa) if ta is None else (pb, wb)
            print(f"！{fn}：读不进来 —— {bad} —— {why}", file=sys.stderr)
            unread.append(fn)
            continue
        d = diff_tables(channel_groups(ta), channel_groups(tb))
        att = attribute_delta(ta, tb)
        if empty_pair(d):
            # 两份都是空的：不算比过、不算一致，也不给「同一张表」那句话留位置（见 empty_pair）
            print(f"{fn}：两边都是 0 条线路 —— 比了等于没比，这一对不算数")
            skipped.append(fn)
            continue
        if att["len_diff"]:
            d["lines_same"] = False       # 行数都不等，别信「同一张表」
        print(verdict(fn, d, att))
        checked += 1
        if not d["lines_same"]:
            drift += 1
    code = outcome(checked, drift, len(unread))
    if not checked:
        # 一张都没比成功，就不能说「完全一致」—— 那是最容易在自动化里蒙混过关的一种假绿
        sys.stdout.flush()            # 不然这行会插到上面那几条「跳过」前面，读起来像先报错再干活
        print(f"一张表都没比成（`--against` 那个目录里没有 {args.files} 中的任何一个，"
              "或者有但两边都是空的"
              + (f"，另有 {len(unread)} 张读不进来" if unread else "") + "）", file=sys.stderr)
        return code
    if drift:
        print(f"\n{drift} 张表和基准不是一张表 —— 报告里那些「集中度」「换线路」的数，"
              "说的已经不是电视上这份了，按新表重读一遍再据此决定。")
        return code
    if unread:
        # 一张没换 ≠ 都读进来了：那几张的名字点过、内容没读到，这句不能替它们说话
        print(f"\n比了的 {checked} 张线路级一致，另有 {len(unread)} 张读不进来（"
              f"{'、'.join(unread)}）—— 上面那句不覆盖它们。")
        return code
    # 「完全」只能在真的一张没落空时印：比了 1 张、跳过 1 张，说「线路级完全一致」是替没比的那张说话。
    head = ("线路级完全一致" if not skipped else
            f"比了的 {checked} 张线路级一致、另 {len(skipped)} 张没比")
    print(f"\n{head}：报告里那些数说的就是这一张表。"
          "（它不判断线路好坏，也不产生新表 —— 上面那句「同一张表」只到今天比过的这些文件为止。）"
          + (f" 没比的：{'、'.join(skipped)}" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
