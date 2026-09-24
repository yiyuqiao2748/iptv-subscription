r"""数一遍文档里「写了数、却没挂标记」的地方（计划书 2.59）—— **报数，不拦候选**。

为什么要有它：`doc_num.py` 那条 ✓ 印的是「比了 74 处：全部对得上」，而 74 说的是**已经挂了
`〔数:…〕` 的那些处**。一篇文档里另外还写着多少个「数字＋量词」没挂？2.58 在「边界」里量过
一处不合 —— 一篇文档里的数一个都没挂时，正查那一遍只印一句「一个标记都没有」，74 那行整行
消失 —— 也就是说「写了 30 个数、挂了 1 个」与「写了 2 个数、挂了 1 个」在这一屏上是同一句话。
这一把尺量的就是那个分母本身。

它跟数尺共用同一套认标记的规矩（`doc_num.BRACKET` 与 `doc_num.ATTACHED`）。这不是省事，是
这一节踩的第一条：写它之前那两遍探针按「数字后面紧跟括号」数出甲 **59** 处（15:48），按位置
复用数尺那两条正则数出 **74** 处（15:50）。差的 15 处这一遍逐条数过（16:23）：**11 处**夹的是
收尾那两个星号（`167**〔数:…]`）、**4 处**是量词加星号一起夹着（`24 个**〔数:…]`）——
都是合法写法，probe4 那种贴法一条都不认。一把只报处数的尺，分母先跟隔壁那把对不上，
它报出来的每个数都得打个折。所以这里有一条硬检查：**我数到的标记处数必须等于数尺数到的**
（`cross_check`），不一致是退 2，不是「少几条」。

为什么不拦候选，是设计而不是没做完：16:22 那一遍把「同一行别处有标记 ＋ 这个值又是文档里挂过的
数」这一档 5 条逐条读过原文 —— `电视订阅接入.md:150` 那两句「1 个的备选还在同一家机房」
「14 个换过去仍是专网出口」和 `:498` 那句「两家加起来 39 个台」是**该挂**（:150 那一句里同一批
24/1/14/0 只挂了 24 和 0，:498 那句自己写着「跟上面那句 39〔数:aptv:suspect〕 是同一批人」）；
`:137` 的「**22 个全部**」是同一行那个 22 的重述、`真机验收单.md:117` 的「第 3 步那 20 个」今天有
两个键都算得出 20，挂哪个要人来定 —— 这 2 条机器不该替人决定。做成闸就等于把四成误伤写成规矩。
还有一条更硬的理由：**这一档的名单随判据动，不随文档动**。同一批文档、同一批位置、同一套筛子，
只把「这个值文档里挂过标记」换成「这个值今天算得出」：丁 从 5 条涨到 **7** 条（多出来的正是
`:479 16 条` 与 `:534 10 个`，一条没少），戊 从 32 涨到 **53**、己 从 72 掉到 **49** —— 三桶之和
仍是 109，动的全是桶与桶之间那条界（16:53 那一遍现测）。一把会点名的尺，名单先由它怎么定义决定，
才由文档写什么决定。
什么时候可以升成闸：判据先改成「同值 ＋ 同量词 ＋ 同一句」，把那 2 条误伤切出去再说。

    ./.venv/bin/python -X utf8 scripts/unmarked_nums.py                 # 报现状（离线，不写任何文件）
    ./.venv/bin/python -X utf8 scripts/unmarked_nums.py --all           # 连只报数的那两档一起摊开
    ./.venv/bin/python -X utf8 scripts/unmarked_nums.py --self-test     # 往临时目录里种已知形状的文档
    ./.venv/bin/python -X utf8 scripts/unmarked_nums.py --doctest       # 只跑它自己的用例

退出码：**0 = 量到了，且点名的每一篇都读到了**（点几条候选都不改退码）；
**1 = 量到了，但有一篇没读到** —— 这一屏每一行处数因此只覆盖读到那几篇，分母缺一块。
这一档的 1 只此一种：它不为「文档里有数没挂」而红，它为「我少看了一篇」而红。
**2 = 一个字都没量到** —— 点名的文档全没读到、一个标记都没有、这批表算不出任何数、
或**我跟数尺对同一批标记数出了两个数**。
"""
from __future__ import annotations

import argparse
import contextlib
import doctest
import io
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"
if str(ROOT / "scripts") not in sys.path:      # 为了 import doc_num（它自己也是这么找邻居的）
    sys.path.insert(0, str(ROOT / "scripts"))

import doc_num  # noqa: E402
# 格子那一套（`Cell`／种沙盒／把临时路径换成 `<T>`／跑之前先量靶子）是 2.56~2.58 三把尺共用过的
# 形状。第四把再抄一份 `hide_tmp`，就成了 2.58 刚收掉的那种毛病：一条规矩四个人各写一遍。
from doc_num import (DOC, SANDBOX, Cell, build_cell,  # noqa: E402
                     fill, hide_tmp, ragged_cells, unresolvable)
from baseline_guard import guard as guard_names  # noqa: E402

FENCE = re.compile(r"^\s*```")
NUM = re.compile(r"\d[\d,]*")
# 量词表**不是**判据，是筛子：真判据是「这个值是不是文档里挂过的数」。表里没写的那些字
# 落 丙（那一行自己会说要什么），所以这张屏不假装「数都分完桶了」。
# 这里试过给「数字后面紧跟一个不在表里的汉字」单独报一行，删了：它量出来的是**所有**跟在
# 数字后面的汉字（`2026-09-21 在电脑上` 会报出一个「在」字），一行把 在/之/后 列成
# 「没照到的量词」，比不报更糟 —— 它教读的人不信这张屏。用例记在 `G13`。
UNIT = "个条台家处次种项类路款张页字步天点行"
# 分钟/秒说的是钟点和时长，不是表上的数（`aptv:focus-hosts` 今天正好 20，跟「隔 20 秒重取」
# 同值 —— 最便宜的一种误伤），所以这两个字单独一桶，永不点名。
TIME_UNIT = "分秒"
# 「第 3 步」「1~4 步」是**编号**，不是「表里几个台」那类数。15:50 那遍 14 条候选里混着 3 条
# 「第 4 步／第 5 步／第 3 步」，全是指向另一页的序号。这道闸只作用在带量词的数字上（见 `scan_line`）。
ORDINAL = re.compile(r"(第|~|-|～)\s*$")
SKIP_WHY = {"ordinal": "序数（第 N 步／区间）", "code": "反引号里（举例与命令）",
            "time": "分钟/秒"}


class Hit(NamedTuple):
    """一处「写了数、没挂标记」。`mates` = 同一行挂着的 `(键, 数)`，`keys` = 今天算得出这个值
    的键。两个都带上，读的人才能一眼看出这条是「该问为什么不挂」还是「撞上别的数了」。"""
    doc: str
    line: int
    value: int
    unit: str
    mates: tuple[tuple[str, int], ...] = ()
    keys: tuple[str, ...] = ()

    def one(self) -> str:
        """一行话：位置、写下来的数、现在哪个键算得出它、同一行那个标记标的是几。"""
        here = ("　同一行挂着 " + "、".join(f"`{k}`={v}" for k, v in self.mates)
                if self.mates else "")
        got = "/".join(self.keys[:3]) + (f" 等 {len(self.keys)} 个键" if len(self.keys) > 3 else "")
        return (f"   {self.doc}:{self.line}  {self.value} {self.unit}"
                f"　算得出这个值的键：{got or '没有'}{here}")


class Ledger(NamedTuple):
    """一屏的账。`yi` 是个性质不是个数 —— 乙 由定义就是那三桶之和，配平不会自己崩。"""
    marks: int            # 甲：挂了标记、且数尺也数到同一批位置
    digits: int           # 读到的数字 token 总数（围栏内的不算读）
    ding: list[Hit]       # 乙·丁：同一行有标记 + 值撞得上
    wu: list[Hit]         # 乙·戊：值撞得上、同一行没标记
    ji: list[Hit]         # 乙·己：这个值文档里没挂过
    other: int            # 丙：数字后面既没量词也没标记
    skips: Counter        # ordinal / code / time

    @property
    def yi(self) -> int:
        return len(self.ding) + len(self.wu) + len(self.ji)

    @property
    def balanced(self) -> bool:
        return self.marks + self.yi + self.other + sum(self.skips.values()) == self.digits


def in_code(line: str, at: int) -> bool:
    """这个位置在反引号里面吗 —— 与 `doc_num.parse_marks` 同一句算法，不另写一份。

    >>> in_code("写着 `226 条` 这种东西", 6)
    True
    >>> in_code("写着 `226 条` 这种东西", 11)
    False
    """
    return line[:at].count("`") % 2 == 1


def marks_at(line: str) -> list[tuple[int, int, int, str]]:
    """这一行里**贴着数字**的标记：`(数字起点, 数字终点, 那个数, 键)`。

    数字和括号之间只许有空格、`**` 和一个量词 —— 这条规矩是 `doc_num.ATTACHED` 定的，这里
    原样拿它来用，两把尺对「什么算挂了标记」因此不会有第二种读法。反引号里的是举例子，
    数尺不查，这里也不算挂过。

    >>> marks_at("写着 226〔数:aptv:lines〕 条")
    [(3, 6, 226, 'aptv:lines')]
    >>> marks_at("**24 个**〔数:aptv:no-alt〕没有备选")
    [(2, 4, 24, 'aptv:no-alt')]
    >>> marks_at("教人认这个记号时写 `〔数:aptv:lines〕`")      # 举例子：不算挂过
    []
    >>> marks_at("一个标记都没有")
    []
    >>> marks_at("括号〔数:aptv:lines〕 前面没有数")            # 数尺会数到它，这里数不到
    []
    """
    out = []
    for m in doc_num.BRACKET.finditer(line):
        if in_code(line, m.start()):
            continue
        att = doc_num.ATTACHED.search(line[:m.start()])
        if att:
            out.append((att.start(1), att.end(1), int(att.group(1)), m.group(1).strip()))
    return out


def unit_at(line: str, end: int) -> str:
    """数字后面紧挨着的那个字是不是量词。是就返回那个字，不是就返回空串。

    隔一个空格算 —— 这一树文档里「226 条」就是带空格写的，不算它就等于把主流写法全落进 丙。

    >>> unit_at("226 条", 3)
    '条'
    >>> unit_at("226条线路", 3)
    '条'
    >>> unit_at("20 秒", 2)                                   # 时长：不是量词，另有一桶
    ''
    >>> unit_at("2026 年", 4)
    ''
    >>> unit_at("写着 226", 6)                                # 后面什么都没有
    ''
    """
    m = re.match(rf"\s*([{UNIT}])", line[end:])
    return m.group(1) if m else ""


def scan_line(line: str) -> tuple[list[tuple[int, str]], Counter]:
    """这一行的数字怎么分。返回 `(候选们, 跳过的账)`。

    候选 = `(值, 量词)`，认不出量词时那个字是空串（那一类落 丙）；被标记吃掉的数字不在里面。
    跳过的那几类也进 `digits` 那个总数 —— 不然这张屏上「没点名」就没有分母可对。
    **序数那道闸只作用在带量词的数字上**：先问有没有量词，再问是不是编号。反过来的顺序会把
    `2026-09-21` 里那两个连字符后面的数报成「序数 2 处」（`G6`／`G13` 两格钉着这两条）。

    >>> scan_line("写着 226 条")
    ([(226, '条')], Counter())
    >>> scan_line("写着 226〔数:aptv:lines〕 条")             # 那个数被标记吃掉了
    ([], Counter())
    >>> scan_line("只能验第 1~4 步")                           # 4 是编号；1 没量词，落 丙
    ([(1, '')], Counter({'ordinal': 1}))
    >>> scan_line("隔 20 秒重取")
    ([], Counter({'time': 1}))
    >>> scan_line("命令里写 `--top 0` 那一条")
    ([], Counter({'code': 1}))
    >>> scan_line("2026-09-21 在电脑上实测")                    # 日期：三个数都没有量词
    ([(2026, ''), (9, ''), (21, '')], Counter())
    """
    taken = [(s, e) for s, e, _v, _k in marks_at(line)]
    out: list[tuple[int, str]] = []
    skip: Counter = Counter()
    for n in NUM.finditer(line):
        if any(n.start() >= s and n.end() <= e for s, e in taken):
            continue
        if in_code(line, n.start()):
            skip["code"] += 1
            continue
        nxt = re.sub(r"^\s*", "", line[n.end():])[:1]
        value = int(n.group().replace(",", ""))
        if nxt in TIME_UNIT:
            skip["time"] += 1
            continue
        unit = unit_at(line, n.end())
        if not unit:
            out.append((value, ""))
            continue
        if ORDINAL.search(line[:n.start()]):
            skip["ordinal"] += 1
            continue
        out.append((value, unit))
    return out, skip


def group_by_value(values: dict[str, int]) -> dict[int, tuple[str, ...]]:
    """值 → 今天算得出它的那些键。两段键排在三段键前面，其余按名字。

    为什么要排：16:11 那遍 `电视订阅接入.md:150` 那个「1 个」，屏幕上排第一的是
    `aptv:focus:192.151.150.154` —— 一家主机上的台数，而那句话说的是「备选在同一家机房的台数」，
    真键是 `aptv:same-host`。三段的 `focus:` / `host-lines:` 一族有几十个键，值天然挤在
    1~30 这一片，把表级的那一族顶到前面去，点名的那几行才读得出意思。
    这与 `doc_num.render_list` 用的是同一个排法（`k.count(":")`）。

    >>> group_by_value({"aptv:focus:a.example": 1, "aptv:same-host": 1, "aptv:lines": 226})
    {1: ('aptv:same-host', 'aptv:focus:a.example'), 226: ('aptv:lines',)}
    """
    out: dict[int, list[str]] = {}
    for k, v in values.items():
        out.setdefault(v, []).append(k)
    return {v: tuple(sorted(ks, key=lambda k: (k.count(":"), k))) for v, ks in out.items()}


def bucketize(docs: Sequence[tuple[str, str]], values: dict[str, int]) -> Ledger:
    """两遍扫完这几篇文档，切出 甲 / 乙·丁戊己 / 丙。**纯函数**：文本给进来，不碰磁盘。

    为什么必须两遍：一个值「在文档里挂没挂过」要看全部几篇 —— 先例可以在另一篇上。

    >>> v = {"aptv:lines": 226, "aptv:no-alt": 24, "aptv:same-host": 1}
    >>> docs = [("甲.md", "24〔数:aptv:no-alt〕 个台里 24 个全部没备选\\n")]
    >>> led = bucketize(docs, v)
    >>> (led.marks, led.yi, [h.value for h in led.ding], [h.value for h in led.wu])
    (1, 1, [24], [])
    >>> led.ding[0].mates                       # 同一行那个标记标的也是 24，所以这条叫「重述」
    (('aptv:no-alt', 24),)
    >>> led.ding[0].keys                        # 而今天算得出 24 的键就是那一个
    ('aptv:no-alt',)
    >>> # 值撞得上、同一行没有标记：落 戊（弱一档，只说明这个数在别处挂过 —— 先例可以在另一篇）
    >>> two = [("甲.md", "线路 226〔数:aptv:lines〕 条\\n"), ("乙.md", "另外那 226 条\\n")]
    >>> [(h.doc, h.value) for h in bucketize(two, v).wu]
    [('乙.md', 226)]
    >>> # 文档里没挂过这个值：落 己，不点名（16:22 那遍量的正是「撞得上」这一档的误伤率）
    >>> led2 = bucketize([("丙.md", "24〔数:aptv:no-alt〕 个台里 69 个会换\\n")], v)
    >>> ([h.value for h in led2.ji], led2.ding)
    ([69], [])
    >>> # 一个标记都没有：甲 0、丁戊全空 —— 「没量到」由 `main` 判，不在这里
    >>> led3 = bucketize([("丁.md", "写着 5 条\\n")], v)
    >>> (led3.marks, led3.yi, led3.ding, led3.wu, [h.value for h in led3.ji])
    (0, 1, [], [], [5])
    >>> # 配平：甲 + 乙 + 丙 + 跳过 = 读到的数字
    >>> led4 = bucketize([("戊.md", "第 3 步：写着 5 条，另有 7 个、`0 个`\\n")], v)
    >>> (led4.marks, led4.yi, led4.other, dict(led4.skips), led4.digits, led4.balanced)
    (0, 2, 0, {'ordinal': 1, 'code': 1}, 4, True)
    >>> # 围栏里面的一个字都不读（`G8` 钉的就是这一条）
    >>> bucketize([("己.md", "a\\n```\\n226 条\\n```\\n")], v).digits
    0
    """
    by_val = group_by_value(values)
    per_doc: list[tuple[str, list[object]]] = []
    keyed_vals: set[int] = set()
    marks = digits = other = 0
    skips: Counter = Counter()
    for name, text in docs:
        lines: list[object] = []
        inside = False
        for line in text.splitlines():
            if FENCE.match(line):
                inside = not inside
                lines.append(None)
                continue
            if inside:
                lines.append(None)
                continue
            mk = marks_at(line)
            toks, sk = scan_line(line)
            marks += len(mk)
            keyed_vals.update(v for _s, _e, v, _k in mk)
            digits += len(mk) + len(toks) + sum(sk.values())
            skips.update(sk)
            lines.append((mk, toks))
        per_doc.append((name, lines))
    ding: list[Hit] = []
    wu: list[Hit] = []
    ji: list[Hit] = []
    for name, lines in per_doc:
        for lineno, cell in enumerate(lines, 1):
            if cell is None:
                continue
            mk, toks = cell                      # type: ignore[misc]
            mates = tuple((k, v) for _s, _e, v, k in mk)
            for val, unit in toks:
                if not unit:
                    other += 1
                    continue
                h = Hit(name, lineno, val, unit, mates, by_val.get(val, ()))
                if val not in keyed_vals:
                    ji.append(h)
                elif mates:
                    ding.append(h)
                else:
                    wu.append(h)
    return Ledger(marks, digits, ding, wu, ji, other, skips)


def cross_check(mine: int, theirs: int) -> str | None:
    """两把尺对同一批标记数没数出同一个数？不一致就是要说人话的那一句，不是 `None`。

    为什么单独抽出来（2.58「处置句要能被点着跑」的同形）：这一句只在我自己数错的那一遍
    才存在，而那一遍正是这张屏最不能读的一遍 —— 它能出现，就说明上面每一行处数都不可信。

    >>> cross_check(74, 74) is None
    True
    >>> print(cross_check(1, 2))
    两把尺对不上：我数到 1 处挂着标记的数，`doc_num` 数到 2 处 —— 差的那 1 处里，标记前面没贴着数（写歪了、或对不上号）。这一屏每个处数都不可信，先看数尺那一屏。
    >>> print(cross_check(3, 2))
    两把尺对不上：我数到 3 处挂着标记的数，`doc_num` 数到 2 处 —— 差的那 1 处里，标记前面没贴着数（写歪了、或对不上号）。这一屏每个处数都不可信，先看数尺那一屏。
    """
    if mine == theirs:
        return None
    return (f"两把尺对不上：我数到 {mine} 处挂着标记的数，`doc_num` 数到 {theirs} 处 —— "
            f"差的那 {abs(mine - theirs)} 处里，标记前面没贴着数（写歪了、或对不上号）。"
            "这一屏每个处数都不可信，先看数尺那一屏。")


def render(led: Ledger, docs: Sequence[Path], base: Path, *, show_all: bool,
           unread: Sequence[tuple[str, str]] = ()) -> list[str]:
    """那一屏：先配平，再点名，最后一行是给 `selfcheck.conclusion()` 挑走的结论。"""
    out = ["文档里写了数、没挂标记的地方 —— 这一档报数，不拦候选",
           f"以 {doc_num.as_of(base)} 为准 · {'、'.join(p.name for p in docs)}",
           "",
           f"甲 挂了标记、且与数尺数到同一批位置：{led.marks} 处",
           f"乙 数字＋量词、没挂标记：{led.yi} 处 = 丁 {len(led.ding)} + 戊 {len(led.wu)}"
           f" + 己 {len(led.ji)}",
           f"   丁 同一行别处挂着标记、这个值又是文档里挂过的数：{len(led.ding)} 处 ← 逐条点名",
           f"   戊 值对得上、同一行没有标记：{len(led.wu)} 处（只报数：撞值的多半是别的数）",
           f"   己 这个值文档里从没挂过标记：{len(led.ji)} 处（只报数）",
           f"丙 数字后面没有量词、也没标记：{led.other} 处 —— 日期、钟点、编号都在里面，这一档不分它"]
    if led.skips:
        out.append("   跳过的：" + "、".join(
            f"{SKIP_WHY.get(k, k)} {v} 处"
            for k, v in sorted(led.skips.items(), key=lambda t: (-t[1], t[0]))))
    out.append("   配平：甲 + 乙 + 丙 + 跳过 = " + str(led.marks + led.yi + led.other
               + sum(led.skips.values()))
               + (f"，读到的数字 {led.digits} 个" if led.balanced else
                  f" 不等于读到的数字 {led.digits} 个 —— 不合：有数字被两处同时认领，"
                  "这一屏每个处数都别读"))
    if led.ding:
        out.append("")
        out += [h.one() for h in led.ding]
    else:
        out += ["", "   丁 一条都没点到。这一句**不能**读成「文档里的数都挂全了」：还有 "
              f"{len(led.wu)} 处 戊 与 {len(led.ji)} 处 己 只报了数，"
              "那两档里有多少该挂，这把尺说不出。"]
    if show_all:
        for title, items in (("戊", led.wu), ("己", led.ji)):
            if items:
                out.append(f"\n{title} 全部 {len(items)} 处：")
                out += [h.one() for h in items]
    if unread:
        out += ["", f"上面每一行处数只覆盖读到的那 {len(docs) - len(unread)} 篇，"
                    f"另有 {len(unread)} 篇没读到 —— 这一屏不是「文档里就这些数」。"]
    out += ["", f"扫了 {len(docs)} 篇文档：甲 {led.marks} 处、乙 {led.yi} 处"
            f"（点名 {len(led.ding)} 处、另有 {len(led.wu) + len(led.ji)} 处只报数）、"
            f"丙 {led.other} 处、跳过 {sum(led.skips.values())} 处"
            + (f"，{len(unread)} 篇没读到" if unread else "")
            + " —— 候选点几条都不改退码"]
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="文档里写了数却没挂标记的地方：报数，不拦候选")
    ap.add_argument("--docs", default=",".join(doc_num.DEFAULT_DOCS),
                    help="查哪几篇，逗号分隔（默认 " + "、".join(doc_num.DEFAULT_DOCS) + "）")
    ap.add_argument("--base", default=str(OUT_DIR), help="以哪一批表为准，默认 data/output")
    ap.add_argument("--all", action="store_true", dest="show_all",
                    help="把只报数的那两档（戊/己）也逐条摊开")
    ap.add_argument("--self-test", action="store_true", dest="self_test",
                    help=f"往临时目录里种 {len(BASELINE)} 格已知形状的文档，问这把尺分桶分得对不对")
    # `--doctest` 不在 `main()` 里走，它在模块末尾先被拦下（那 22 格是调 `main(argv)`，
    # 让这一支进 `main` 就等于让基线去跑基线）。写进 argparse 只为了一句：文档尺会拿
    # `--help` 核对每一条长参数，不写进来的话，计划书里那条照抄的命令会被判「对不上」。
    ap.add_argument("--doctest", action="store_true",
                    help="只跑它自己的 doctest（在 `main()` 之前拦下，所以这一屏不会读任何文档）")
    return ap.parse_args(argv)


def doc_paths(raw: str) -> list[Path]:
    """`--docs` 那串换成路径。相对名字按仓库根算（与 `doc_num` 同一口径）。

    >>> [str(p.relative_to(ROOT)) for p in doc_paths("docs/真机验收单.md, docs/电视订阅接入.md")]
    ['docs/真机验收单.md', 'docs/电视订阅接入.md']
    >>> doc_paths(",,")
    []
    """
    return [ROOT / d.strip() if not Path(d.strip()).is_absolute() else Path(d.strip())
            for d in raw.split(",") if d.strip()]


def read_all(paths: Sequence[Path]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """把点名的几篇读进来。返回 `(读到的, 没读到的)` —— 两种都要说话。

    为什么不许只回正文：2.58 的 `B7` 量到的正是「一篇不在，其余篇的成绩被吞掉」。这一把尺
    更脆 —— 它每一行都是一个处数，一篇没读到就是**那片文档整个不在分母里**。

    >>> read_all([Path("/nonexistent-for-doctests/甲.md")])[1][0][1]
    '文件不在'
    """
    got: list[tuple[str, str]] = []
    unread: list[tuple[str, str]] = []
    for p in paths:
        disp = p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p
        text, why = doc_num.read_doc(p)
        if text is None:
            unread.append((str(disp), why))
        else:
            got.append((str(disp), text))
    return got, unread


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()            # 先跑掉：这一档一个字都不该读仓库里那两篇文档
    paths = doc_paths(args.docs)
    base = Path(args.base)
    if not paths:
        print("--docs 里一个名字都没给：这一屏没有可读的东西，也不算量过。", file=sys.stderr)
        return 2
    values, missing = doc_num.compute_values(base)
    if not values:
        for m in missing:
            print(f"！缺：{m}", file=sys.stderr)
        print(f"{base} 里一张表都读不出来，「值撞不撞得上」这条判据没有可比的对象。",
              file=sys.stderr)
        return 2
    got, unread = read_all(paths)
    for disp, why in unread:
        print(f"！没读到：{disp} —— {why}", file=sys.stderr)
    if not got:
        print(f"点名的 {len(paths)} 篇一篇都没读到 —— 一个数都没量到，不算通过。", file=sys.stderr)
        return 2
    led = bucketize(got, values)
    bad = cross_check(led.marks, len(doc_num.check_files(paths, values)[0]))
    if bad:
        print(bad, file=sys.stderr)
        return 2
    if not led.marks:
        print("、".join(d for d, _ in got) + "：一个 〔数:…〕 标记都没有 —— 丁/戊 两桶要靠"
              "「文档里挂过的数」才有先例可撞，这一轮等于什么都没量到。", file=sys.stderr)
        return 2
    for line in render(led, paths, base, show_all=args.show_all, unread=unread):
        print(line)
    return 1 if unread else 0


# ——————————————————————————————————————————————————————————
# 基线（§2.59）：这把尺分桶分得对不对
#
# 为什么要有这一档：这一把尺**设计上不为候选红**（点多少条都不改退码），于是它那条 ✓ 比
# 前三把的更值得怀疑 —— 「丁 0 处」既可能是文档真的挂全了，也可能是判据整条不咬、
# 或者量词表认不出这一树文档的写法。2.56~2.58 那个形状（往临时目录里种已知好坏的靶子）
# 是唯一能分清它们的办法。格子里所有 `{键}` 跑之前换成这一轮的真值，所以表换一轮、
# 格子不会因此变红：这里量的是判据。
# ——————————————————————————————————————————————————————————

L1 = "写着 {aptv:no-alt}〔数:aptv:no-alt〕 个"
L2 = "写着 {aptv:no-alt}〔数:aptv:no-alt〕 个，另外那 {aptv:no-alt} 个全部"
L3 = "写着 {aptv:lines}〔数:aptv:lines〕 条"

BASELINE: tuple[Cell, ...] = (
    Cell("G1_全挂不点名", "常态：数都挂了标记，乙 0，退 0 且要说「一条都没点到」那句",
         0, files=((DOC, L1),), has=("甲 挂了标记、且与数尺数到同一批位置：1 处",
                                     "乙 数字＋量词、没挂标记：0 处", "丁 一条都没点到")),
    Cell("G2_同行重述点名", "**这一档的正主**：同一行挂过、值又是它 → 逐条点名",
         0, files=((DOC, L2),),
         has=("丁 同一行别处挂着标记、这个值又是文档里挂过的数：1 处",
              f"{DOC}:1  {{aptv:no-alt}} 个", "同一行挂着 `aptv:no-alt`={aptv:no-alt}")),
    Cell("G3_值没挂过落己", "文档里没这个值的先例：只报数，绝不点名（误伤就从这里来）",
         0, files=((DOC, L1 + "，还有 {aptv:lines+1} 条"),),
         has=("己 这个值文档里从没挂过标记：1 处",),
         lacks=("{aptv:lines+1} 条　算得出",)),
    Cell("G4_戊只报数", "值撞得上、同一行没标记：落 戊，默认不摊开",
         0, files=((DOC, L3 + "\n另外那 {aptv:lines} 条"),),
         has=("戊 值对得上、同一行没有标记：1 处",),
         lacks=("戊 全部 1 处：",)),
    Cell("G5_all摊开", "`--all` 才摊：不点名是默认，不是藏",
         0, files=((DOC, L3 + "\n另外那 {aptv:lines} 条"),),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--all"),
         has=("戊 全部 1 处：", f"{DOC}:2  {{aptv:lines}} 条")),
    Cell("G6_序数不点", "「第 N 步」是编号不是数量，一条都不许点",
         0, files=((DOC, L1 + "，第 {aptv:no-alt} 步再看"),),
         has=("序数（第 N 步／区间） 1 处", "乙 数字＋量词、没挂标记：0 处")),
    Cell("G7_反引号不点", "举例那种写法不算候选，但要算进跳过",
         0, files=((DOC, L1 + "，别写 `{aptv:lines} 个` 这种"),),
         has=("反引号里（举例与命令） 1 处", "乙 数字＋量词、没挂标记：0 处")),
    Cell("G8_围栏内不读", "代码块里的数一个字都不读：那条 ✓ 不该由它挣来",
         0, files=((DOC, L1 + "\n```\n{aptv:lines} 条\n```\n"),),
         has=("配平：甲 + 乙 + 丙 + 跳过 = 1，读到的数字 1 个",)),
    Cell("G9_跨篇算先例", "先例可以在另一篇上：两遍扫的那一遍为的就是这个",
         0, files=((DOC, L2), ("另一篇.md", L3 + "\n那边也是 {aptv:lines} 条")),
         argv=("--docs", f"{SANDBOX}/{DOC},{SANDBOX}/另一篇.md", "--all"),
         has=("丁 同一行别处挂着标记、这个值又是文档里挂过的数：1 处",
              "戊 值对得上、同一行没有标记：1 处", "戊 全部 1 处：", "另一篇.md:2")),
    Cell("G10_配平要合", "甲+乙+丙+跳过 必须等于读到的数字，否则那一行说不合",
         0, files=((DOC, L2),), has=("配平：甲 + 乙 + 丙 + 跳过 = 2，读到的数字 2 个",),
         lacks=("不合",)),
    Cell("G11_一行两处都点", "同一行里两个没挂的数都成立 → 两处各一行，不许只报一个",
         0, files=((DOC, L2 + "、{aptv:no-alt} 个台全部"),),
         has=("丁 同一行别处挂着标记、这个值又是文档里挂过的数：2 处",)),
    Cell("G12_分钟秒不点", "「隔 20 秒」与 `focus-hosts` 同值也不许进候选",
         0, files=((DOC, L3 + "，隔 {aptv:focus-hosts} 秒重取"),),
         has=("分钟/秒 1 处", "乙 数字＋量词、没挂标记：0 处")),
    Cell("G13_日期落丙", "日期那种数没量词：落 丙，且不许被序数闸吃掉",
         0, files=((DOC, L1 + "。2026-09-21 量过"),),
         has=("丙 数字后面没有量词、也没标记：3 处", "配平：甲 + 乙 + 丙 + 跳过 = 4")),
    Cell("B1_一篇不在", "量到了但要说出缺一块：退 1，不是退 0（2.58 那条同形）",
         1, files=((DOC, L3),), argv=("--docs", f"{SANDBOX}/{DOC},{SANDBOX}/不在.md"),
         has=("没读到：", "上面每一行处数只覆盖读到的那 1 篇，另有 1 篇没读到",
              "甲 挂了标记、且与数尺数到同一批位置：1 处")),
    Cell("B2_标记写歪", "标记前面没贴着数：数尺数到两处、我只数到一处 → 每个处数都不可信",
         2, files=((DOC, L3 + "，括号〔数:aptv:lines〕 前面没数"),),
         has=("两把尺对不上：我数到 1 处", "`doc_num` 数到 2 处")),
    Cell("B3_一个标记都没有", "丁/戊 两桶没有先例可撞，等于什么都没量到",
         2, files=((DOC, "写着 {aptv:lines} 条"),),
         has=("一个 〔数:…〕 标记都没有",)),
    Cell("B4_文档位置给了目录", "2.36 那一族的第三种读法：不许裸崩",
         2, argv=("--docs", str(SANDBOX)), has=("那是个目录", "点名的 1 篇一篇都没读到"),
         lacks=("Traceback",)),
    Cell("B5_文档是二进制", "同一族另一支异常，也只说人话",
         2, bins=("坏件.bin",), argv=("--docs", f"{SANDBOX}/坏件.bin"),
         has=("读不出来",), lacks=("Traceback",)),
    Cell("B6_空base", "一张表都读不出来 = 值没有可比的对象，退 2",
         2, files=((DOC, L3),), argv=("--docs", f"{SANDBOX}/{DOC}", "--base", f"{SANDBOX}/空表"),
         has=("一张表都读不出来",)),
    Cell("B7_三篇都不在", "几篇没读到要说得出数",
         2, argv=("--docs", f"{SANDBOX}/甲不在.md,{SANDBOX}/乙不在.md,{SANDBOX}/丙不在.md"),
         has=("点名的 3 篇一篇都没读到",)),
    Cell("B8_空文档", "读到一篇空的：没标记 → 退 2，不是「一条都没点到」那种绿",
         2, files=((DOC, "这一篇一个数都没写。"),), has=("一个 〔数:…〕 标记都没有",)),
    Cell("B9_docs给空串", "参数取坏值时不许去读仓库里那两篇",
         2, argv=("--docs", ""), has=("--docs 里一个名字都没给",)),
)


def braced_cells(cells: Sequence[Cell]) -> list[str]:
    """格子里把沙盒占位符写成花括号那些 —— **跑任何一格之前先问这一条**。

    为什么要有一道：16:10 那遍 `B5` 红在 `！没读到：{SANDBOX}/坏件.bin —— 文件不在`。
    退码 2 挣对了、理由全错 —— 那一格要说的是「非 UTF-8 的件不许裸崩」，它却拿去比了一条
    凭空不存在的路径。这种靶子不会让基线变松，它会让基线**指着一件没发生过的事说是发生过**。
    `ragged_cells` 管的是形状（少个逗号），花括号不在它的形状里，所以这里补一道同形的闸。

    >>> braced_cells([Cell("A", "x", 0, argv=("--docs", "<沙盒>/甲.md"))])
    []
    >>> print(braced_cells([Cell("A", "x", 0, argv=("--docs", "{SANDBOX}/甲.md"))])[0])
    A：argv 里把沙盒占位符写成了花括号 —— 该写 <沙盒>（尖括号）。写成花括号它不会被替换，那一格会比的是一条凭空存在的路径
    >>> braced_cells([Cell("A", "x", 0, files=(("m.md", "看 {SANDBOX} 这里"),))]) == []
    True
    """
    out: list[str] = []
    for c in cells:
        for fld in ("argv", "has", "lacks"):
            if any("{SANDBOX}" in s for s in getattr(c, fld)):
                out.append(f"{c.who}：{fld} 里把沙盒占位符写成了花括号 —— 该写 {SANDBOX}"
                           "（尖括号）。写成花括号它不会被替换，那一格会比的是一条凭空存在的路径")
    return out


def run_cell(cell: Cell, base: Path, values: dict[str, int]) -> tuple[str, str, str]:
    """跑一格：返回 `(判决, 为什么, 那一遍的原文)`。判决是 `ok`／`bad`／`崩`。"""
    d = build_cell(cell, base, values)
    argv = list(cell.argv) or ["--docs", f"{d}/{DOC}"]
    argv = [a.replace(SANDBOX, str(d)) for a in argv]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
    except SystemExit as e:                       # 有人把 main 改成 raise SystemExit
        rc = e.code if isinstance(e.code, int) else 99
    except BaseException as e:                    # noqa: BLE001 —— 崩了就是要被看见
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
    """`--self-test`：往临时目录里种 22 格已知形状的文档，逐格对**跑之前**写死的期望。

    结论行带着「扫了」那个词（`scripts/selfcheck.py` 的 `conclusion()` 靠它挑句子），
    过的一格一行流水、不符期望的留在最后 —— 与 §2.56~2.58 那三档同形，理由也同形：
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
    braced = braced_cells(BASELINE)
    if braced:
        print("靶子指着一条凭空存在的路径，改的是基线、不是判据：\n  " + "\n  ".join(braced))
        return 2
    values, _missing = doc_num.compute_values(OUT_DIR)
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
    with tempfile.TemporaryDirectory(prefix="unmarked-selftest-") as td:
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
          + (" —— 那把尺分桶分得对" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    if "--doctest" in sys.argv:
        raise SystemExit(doctest.testmod(verbose=False).failed)
    raise SystemExit(main(sys.argv[1:]))
