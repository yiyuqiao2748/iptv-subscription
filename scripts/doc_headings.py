r"""量一遍文档的标题结构：编号连着排没有、层级跳没跳档、别的件指过来的节号还在不在（计划书 §2.72）。

为什么要有它：上一节那次提交把 `## 三、总体架构` 那一行整条删掉了，它在仓库里躺了一整节，
**没有任何一把尺说话**（2.71「顺带量到的一处退步」记的就是这件事，并把它排进本节第一条）。
那一层里读文档的几把尺各读别的东西 —— `numbers` 只读挂了〔数:…〕标记的数、`doc-cmds` 只读命令行、
`unmarked` 读「数字＋量词」、`names` 只读文件名、`claims` 读 .py 的 docstring。
「这一行是一条标题、它编的号对不对」那一层，本节之前一把尺都没有。

它第一遍就量到了一件比那次丢行更老的事。`计划书.md:349` 那句话把 `src/parse/local.py`
指到一个 `5.3` 上（前面顶着「计划书」三个字，所以这一层读得到），而文档里**没有 `### 5.3`**
—— 第五章一条带编号的小节都没有（09:55:45 那遍现数：`## 五` 的孩子 0 条），那一章整章就是
「三级来源」那张表，今天四行：L1 主力／L1.5 湖南专项／L2 备用／L3 手工。那句「第三级」
说的是表里 L3 那一行 —— 它挂在一个从来没有存在过的节号上。那一行出自 `10d530e`
（09-21 14:31，§2.11 写的），到本节现数是 **3 天 19 小时**、中间写过六十节。
它不是「该有却没有」，它是**一句指着不存在的东西的话** —— 而那正是这一层唯一的读法能抓的东西。
本节按它自己的说法把那一句改成了人话（现在写的是「第五章那张表里的 L3 那一行」），改完
`计划书.md` 在引用层一处都不红了。那一遍屏幕上剩下的另两处是本件自己 forward-reference 本节
（第 1 行那句题注与「基线」那一段的标题各一处），它们等的就是下面这一节 —— 装一把读文档结构的尺，
第一件事是它自己写的话得对得上。

本件自己不写那句原话（那个前缀加那两个数字），因为这一层的判据是**「带前缀的节号必须真在文档里」**，
而它读 .py 的源码 —— 一把尺在自己的文件里留一处它自己判为断链的话，仓库从此绿不回来。
§2.67 那条「举例的字面量会被自己的尺读到」在本节现形的就是这一种，那一条的改法也是这一种：
换成读得懂的人话，**不是**给引用层开豁免、也不是把那一格 `--skip` 掉。往沙盒里种的那一句
由 `DEAD` 那一支拼出来。

量三层，每一层的判据都带今天的处数（「0」必须是量出来的 0，不是没查）：

  章 `## <中文数字>、`：从「一」起、一次进一、不重号；没带编号的 `##` 落「认不出」那一档，**报数不拦**。
  节 `### N.M`：前缀 `N` 必须等于它所在那一章的号，尾号 `M` 从 1 起、步长 1、不重号；
     没带编号的 `###`（今天 6 条，全在第八章，长 `P0 — 最小可用版` 那样）同样只报数 ——
     那是这个项目第一天就有的版式，不是毛病；把它判成毛病等于替文档规定版式。
  层级：相邻两条标题不许跳两级、`####` 不许出现在还没有 `###` 的章里、`#` 只许一条。
  引用：`计划书 N.M`／`§N.M` 那种带前缀的话，指过去的节必须真在文档里。
     它比的不只文档自己，还有 `scripts/`、`src/`、`docs/` 那些件 —— 仓库里那些说明书每写一句
     「§2.68 的 `M16`」，就多一根钉在文档结构上的钉子。这一层是本件唯一一份**跨层的记性**：
     末尾丢一节，结构那一层看不出断号（序列仍然连着），但那一节被别处引用过时，这一层喊。
     它拿去当靶子的那份件由 `--target` 说，**不由 `--docs` 说**（2.73 装的就是这一层）：
     结构层查三篇、引用层判的是「`计划书.md` 里那些 `### N.M` 还在不在」。这两件事在 2.72 之前
     是同一个参数 —— 那时默认名单只有 `计划书.md` 一篇，两个职责恰好重合，所以没人看得出它们是两份工。
     名单一递进那两篇，靶子当场空掉，空靶子把 38 份件里每一句带前缀的话都判成断链
     （11:34:35 拿 `git show HEAD:` 那份原样重放：「扫了 2 篇文档、18 条标题、比了 212 处引用：
     结构毛病 0 处、引用断链 212 处」退 1 —— 一处文档都没坏）。所以这一层今天多一条闸：
     **靶子里一条编号小节都没有，而引用层真有东西要判，那一层就只数不判、并且拒绝判**（退 2），
     屏幕上那两行写「这一层不敢判」与「断链 未判」，而不是把编出来的条数摊出来。

它不量什么，一并说清（三条都是这一遍量到的现状，不是猜想）：

  · **没带前缀的那种 `N.M` 串一处都不读** —— 本件数它，但一句都不判。今天**靶子那一篇**
    （`计划书.md`）正文里有 1838 处，其中「文档里没有对应 `### N.M`」的 257 处（11:44:30 那遍，
    用本件自己那两条正则现数）采样过最集中的几个号：`58.20` 39 处、`74.91` 6 处是
    `58.20.64.92`／`74.91.26.218` 那两台出口 IP 的**打头两拍**，`3.12` 21 处是 Python 版本，
    `0.5`／`0.6`／`3.9` 是时长与概率。
    读进来，这一屏当场多出 257 处假断链 —— 2.72 第一遍真读到的那 3 处（改完 349 那句话之后剩 2 处、
    那一节正文落地之后剩 0 处）就埋在里面。
    代价一并说清：正文里「见 2.11、2.12」那种不写前缀的话本件读不到（靶子自己带前缀的只有 51 处）。
    `BARE` 那个回顾只挡得住 IP **中间**的那一拍（前面顶着 `.`），挡不住打头的那一对，所以这一档
    量的是「有多少不读」，不是「读得干净」。
    **它跟着靶子走、不跟 `--docs`**（2.73）：今天 `--docs` 是三篇、那三篇的 `N.M` 串合计 1891 处，
    可屏幕上那一句说的是靶子那一篇的 1838 处 —— 那一行的 label 因此从「没带前缀的那种」改成
    「靶子里没带前缀的那种」，否则「扫了三篇」配「1838」就是一句把两批件混在一起的话。
    自数一遍记在这里：正文里为了说清这一档而写下的那几个号，自己也被这一档数进去了 ——
    2.72 落地之前那一遍（10:50:51）是 1778 处、`58.20` 38、`3.12` 20、`74.91` 5，落地之后（10:55:48）
    涨成 1809 处、39、21、6，而 `3.0` 原本不在前十二名里。**那一节当时就写着「下一节再抄一次上面
    那几个数，那一句必须重新数」，2.73 就是那个下一节，于是重数出两笔**：11:35:39（本节正文落地之前）
    是 1812 处、无对应 249 处 —— 与上面那句 1809 差 3，那 3 处正是 2.72 的正文自己涨的，而本件说明书里
    那句当时没人量、也没有过期闸拦（`GRID` 只钉「N 格」，「N 处」这一族从头到尾没人看）；
    11:43:35 与 11:44:30（本节正文落地之后）是 1838 处、无对应 257 处，而 `58.20` 39、`3.12` 21、
    `74.91` 6 三个号一个没动。这一档只数不判，所以涨了不碍事；
    碍事的是**下一节再抄一次上面那几个数** —— 那一句必须重新数。
  · **`####` 那 356 条自由标题不查编号** —— 它们本来就没号（「为什么挑它」「判据」这一类），
    本节只查它们挂在谁底下。
  · **「上一轮这里有、这一轮没了」本节仍然看不见** —— 除了引用那一层恰好覆盖到的那些节。
    真做跨轮要落一份履历件，而那会让一条只读文本的对账尺变成**会写文件的件**（2.65 数过谁在写）。

    ./.venv/bin/python -X utf8 scripts/doc_headings.py                 # 量仓库自己（离线，不写任何文件）
    ./.venv/bin/python -X utf8 scripts/doc_headings.py --docs 计划书.md  # 结构层只查点名的那几篇
    ./.venv/bin/python -X utf8 scripts/doc_headings.py --target 计划书.md # 引用层拿它当靶子（默认就是它）
    ./.venv/bin/python -X utf8 scripts/doc_headings.py --refs 计划书.md   # 引用层只比文档自己
    ./.venv/bin/python -X utf8 scripts/doc_headings.py --all             # 把「认不出」那一档逐条摊开
    ./.venv/bin/python -X utf8 scripts/doc_headings.py --self-test       # 往临时目录里种已知坏形状的文档
    ./.venv/bin/python -X utf8 scripts/doc_headings.py --doctest         # 只跑它自己的用例

退出码（2.62 那三档）：**0 = 每一层都量到了、且没有毛病**；**1 = 量到了，但有毛病**
（断号／重号／串章／跳档／孤悬／断链），**或点名的文档与引用件里有一份没读到**
（这一屏每一行数因此只覆盖读到的那几篇，靶子那侧同理）；**2 = 一个字都没量到** —— 点名的文档全没读到、
读到的一篇标题都没有、`--refs` 给了空名单（那一层等于没比，不许混进「比了 0 处」那种绿）、
**或靶子里一条编号小节都没有而那 N 份件里真写着带前缀的引用**（2.73 那一档：那一层**不敢判**，
屏幕上那一句因此是「引用断链 未判」，不是「0 处」）。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:      # 邻居们互相 import，与 2.56~2.60 同一手法
    sys.path.insert(0, str(ROOT / "scripts"))

import doc_num  # noqa: E402
from doc_num import (DOC, SANDBOX, Cell, build_cell, hide_tmp,  # noqa: E402
                     ragged_cells, unresolvable)
from unmarked_nums import braced_cells          # noqa: E402  花括号那道闸只有一份
from baseline_guard import guard as guard_names  # noqa: E402
from run_doctests import add_doctest_flag, run_own  # noqa: E402  `--doctest` 那面旗的口径只有一份
from code_claims import to_int                  # noqa: E402  中文数字→整数，认不出返回 None（不猜）
from stray_names import RED as NAME_RED        # noqa: E402  「这一档名字要跳过」= 只有 red 那一档
from stray_names import classify as classify_name  # noqa: E402  「这是同步盘掉进来的副本」只判一次

FENCE = re.compile(r"^\s*```")
HEAD = re.compile(r"^(#{1,6}) (.*)$")
CHAPTER = re.compile(r"^([零一二三四五六七八九十百千]+)、")
SECTION = re.compile(r"^(\d+)\.(\d+)(\s|$)")
CITE = re.compile(r"(?:计划书|§)\s*(\d+)\.(\d{1,2})")
BARE = re.compile(r"(?<![\d§.])(\d{1,2})\.(\d{1,2})(?![\d])")
DEFAULT_DOCS = "计划书.md,docs/真机验收单.md,docs/电视订阅接入.md"
DEFAULT_TARGET = "计划书.md"
DEFAULT_REFS = "计划书.md,scripts,src,docs"
NAMED = 6          # 「认不出」那一档默认摊几条
# 往沙盒里种的那一句「指着不存在的节」的话。它**不能**在本件里写成一行活的话 ——
# `cites_in` 读 .py 的源码，而本节不给引用层开任何一种豁免，所以一个假节号写在这里，
# 这把尺先在自家判一处断链，仓库从此绿不回来（缘由见模块那段）。拼出来的是同一句。
DEAD = "计划书 " + "5.3"
# 格子里没写 `argv` 时走这一串。三层两份名单、一个都不许留给仓库（缘由见 `targetless`）：
# 那一条的第 3 个例子正是钉住这条默认串的地方 —— 删掉里面的 `--target`，用例当场红。
DEFAULT_CELL_ARGV = ("--docs", f"{SANDBOX}/{DOC}", "--refs", f"{SANDBOX}/{DOC}",
                     "--target", f"{SANDBOX}/{DOC}")


class Heading(NamedTuple):
    line: int
    level: int
    title: str


class Found(NamedTuple):
    """一篇文档的结构账。毛病按**层**分开存，因为屏幕上每一层要各报自己的处数 ——
    一个 `bad` 总数配三行「照见 N 条」，读的人分不出那一层空了、哪一层响了。
    `unnamed_*` 是认不出编号的那些，只报数、不拦。"""
    doc: str
    heads: int
    levels: Counter
    chapters: int                  # 照见编号的 `##`
    sections: int                  # 照见 `N.M` 的 `###`
    bad_ch: tuple[str, ...] = ()
    bad_sec: tuple[str, ...] = ()
    bad_lvl: tuple[str, ...] = ()
    unnamed_ch: tuple[str, ...] = ()
    unnamed_sec: tuple[str, ...] = ()
    fenced_hash: int = 0           # 围栏里以 `#` 开头、没照进来的行数

    @property
    def bad(self) -> tuple[str, ...]:
        return self.bad_ch + self.bad_sec + self.bad_lvl

    @property
    def unnamed(self) -> tuple[str, ...]:
        return self.unnamed_ch + self.unnamed_sec

    @property
    def balanced(self) -> bool:
        """`##` 那一层的条数 == 认得出编号的 + 认不出的；`###` 同理。

        这两条**不是恒等式**，所以它当得上一句「配平」：`levels` 是 `headings_of` 拿 `HEAD`
        一条正则照出来的行级计数，而 `chapters`/`sections`/`unnamed_*` 走的是 `survey` 里
        那一次按级别分派 + `CHAPTER`/`SECTION` 两条正则。两边对不上，说明有一行标题
        哪一档都没进去 —— 那这一屏上面每一个「照见 N 条」都少了几条，读数不能读。
        今天这一棵树上它恒为真，而恒为真的东西钉不住格子（`main` 里没有一条路径能让它假），
        所以它由下面三条断言钉着，不由基线钉着 —— 与 `hide_tmp` 那一笔同形。

        >>> ok = Found("a.md", 4, Counter({1: 1, 2: 1, 3: 2}), 1, 2, unnamed_sec=("x",))
        >>> ok.balanced                                   # ## 1 = 1+0；### 2 = 2+0… 少了那条 x
        False
        >>> Found("a.md", 4, Counter({1: 1, 2: 1, 3: 2}), 1, 1, unnamed_sec=("x",)).balanced
        True
        >>> Found("a.md", 1, Counter({2: 1}), 0, 0, unnamed_ch=("x",)).balanced
        True
        """
        return (self.chapters + len(self.unnamed_ch) == self.levels.get(2, 0)
                and self.sections + len(self.unnamed_sec) == self.levels.get(3, 0))


@dataclass
class Cites:
    """引用那一层的账。`refs` 是读到并扫过的件数，`empty` 区分两种 0。

    为什么是 `dataclass` 而不是 `NamedTuple`：这一本账要**边扫边记**（`per_file[k]=n`、
    `dangling.append`、`main` 里回填 `copies`）。`Ledger`（`unmarked_nums`）也是 NamedTuple
    加一个 `field(default_factory=Counter)`，但它每次都是把 `bydoc` 当参数显式传进去的，
    那个默认值一辈子没被用过 —— 拿过来照抄就会撞上 `'Field' object does not support item
    assignment`（本件第一次跑 `--doctest` 撞的就是它：四格红，退 1）。
    """
    tokens: int = 0
    per_file: Counter = field(default_factory=Counter)
    dangling: list[str] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    copies: list[str] = field(default_factory=list)
    bare: int = 0                  # 没带前缀的那种串（本节不读，只报分母）
    asked: int = 0                 # 点名要读的件数
    target_secs: int = 0           # 靶子里那些 `### N.M` 的条数 —— 「断链 0 处」的分母
    target_names: list[str] = field(default_factory=list)    # 靶子点名的那几篇
    target_unread: list[str] = field(default_factory=list)   # 点名了、没读到的靶子
    no_target: str = ""            # 非空 = 这一层不敢判，里面就是「为什么不敢」

    @property
    def no_list(self) -> bool:
        return self.asked == 0

    @property
    def refused(self) -> bool:
        """有引用可判、可靶子里一条编号小节都没有 —— 于是这一层一个字都没判。

        「0 处断链」在这一格上是**不敢判**的 0，不是**量出来干净**的 0（2.50 那一族）。
        只在 `tokens` 不为 0 时才成立：靶子空、而全仓库也真的一处引用都没写，那一句
        「比了个空」是量出来的，不需要拒绝。

        >>> c = Cites(tokens=212, target_secs=0); c.no_target = "靶子里一条编号小节都没有"; c.refused
        True
        >>> Cites(tokens=0, target_secs=0, no_target="靶子空").refused
        False
        """
        return bool(self.no_target) and self.tokens > 0


def headings_of(text: str) -> tuple[list[Heading], int]:
    """照成标题的行，与围栏里那些「以 `#` 开头、没照进来」的行数。

    为什么围栏那一跳不是形式主义：`计划书.md` 里贴着一份节目单原文，那三行是
    `#EXTM3U`／`#EXTINF` —— 它们后面没有空格，本来也照不成标题（09:55:11 现数：
    围栏里以 `#` 开头 3 行、其中照得成标题形状的 0 行）。这一跳留着不为那三行，
    为的是**谁在代码块里贴一段 markdown 示例**（`### 9.9` 那样），它不该进结构账。

    >>> hs, fenced = headings_of("# 甲\\n## 一、章\\n正文\\n### 1.1 节\\n")
    >>> [(h.level, h.line, h.title) for h in hs]
    [(1, 1, '甲'), (2, 2, '一、章'), (3, 4, '1.1 节')]
    >>> fenced
    0
    >>> hs, fenced = headings_of("题\\n```\\n### 9.9 举例\\n## 九、举例\\n```\\n### 1.1 真\\n")
    >>> [h.title for h in hs], fenced
    (['1.1 真'], 2)
    >>> headings_of("  ```\\n# 不算标题\\n```\\n# 算")[0][0].level
    1
    >>> headings_of("没有一行标题")[0]
    []
    """
    out: list[Heading] = []
    fenced = 0
    inside = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
            continue
        if inside:
            if line.startswith("#"):
                fenced += 1
            continue
        m = HEAD.match(line)
        if m:
            out.append(Heading(n, len(m.group(1)), m.group(2)))
    return out, fenced


def survey(text: str, doc: str) -> Found:
    """把一篇文档切成三层账：章、节、层级。纯函数，不碰磁盘。

    >>> f = survey("# 题\\n## 一、甲\\n### 1.1 节\\n## 二、乙\\n### 2.1 节\\n", "a.md")
    >>> (f.heads, f.chapters, f.sections, f.bad, f.unnamed, f.balanced)
    (5, 2, 2, (), (), True)
    >>> f.levels == {1: 1, 2: 2, 3: 2}
    True
    >>> g = survey("# 题\\n## 附录\\n### P0 — 第一天\\n", "a.md")
    >>> (g.chapters, g.sections, len(g.unnamed_ch), len(g.unnamed_sec), g.bad)
    (0, 0, 1, 1, ())
    >>> h = survey("# 题\\n## 一、甲\\n## 三、丙\\n", "a.md")      # 毛病进的是章那一格
    >>> (h.bad_ch, h.bad_sec, h.bad_lvl)
    (('a.md:第 3 行 `## 三、丙`：前一章是 1，这一章是 3 —— 缺了「二」（断号）',), (), ())
    """
    hs, fenced = headings_of(text)
    ch_items: list[tuple[int, int | None, str]] = []
    sec_items: list[tuple[int, int | None, tuple[int, int] | None, str]] = []
    chapter: int | None = None
    for h in hs:
        if h.level == 2:
            m = CHAPTER.match(h.title)
            num = to_int(m.group(1)) if m else None
            ch_items.append((h.line, num, h.title))
            chapter = num
        elif h.level == 3:
            m = SECTION.match(h.title)
            pair = (int(m.group(1)), int(m.group(2))) if m else None
            sec_items.append((h.line, chapter, pair, h.title))
    unnamed_ch = tuple(f"{doc}:第 {line} 行 `## {title[:26]}` 没带中文编号"
                       for line, n, title in ch_items if n is None)
    unnamed_sec = tuple(f"{doc}:第 {line} 行 `### {title[:26]}` 没带 `N.M` 编号"
                        for line, _c, p, title in sec_items if p is None)
    return Found(doc, len(hs), Counter(h.level for h in hs),
                 sum(1 for _l, n, _t in ch_items if n is not None),
                 sum(1 for _l, _c, p, _t in sec_items if p is not None),
                 tuple(judge_chapters(ch_items, doc)), tuple(judge_sections(sec_items, doc)),
                 tuple(judge_levels(hs, doc)), unnamed_ch, unnamed_sec, fenced)


def judge_chapters(items: Sequence[tuple[int, int | None, str]], doc: str) -> list[str]:
    """章号：从「一」起、一次进一、不重号。认不出的一律不在这里说话（它只报数）。

    >>> judge_chapters([(1, 1, '一'), (9, 2, '二'), (20, 3, '三')], "a.md")
    []
    >>> print(judge_chapters([(1, 1, '一'), (9, 2, '二'), (20, 4, '四')], "a.md")[0])
    a.md:第 20 行 `## 四`：前一章是 2，这一章是 4 —— 缺了「三」（断号）
    >>> print(judge_chapters([(1, 1, '一'), (9, 1, '一')], "a.md")[0])
    a.md:第 9 行 `## 一`：与前面某一章同号 1（重号）
    >>> print(judge_chapters([(1, 2, '二'), (9, 3, '三')], "a.md")[0])
    a.md:第 1 行 `## 二`：第一章是 2，不是从「一」起（首号）
    >>> judge_chapters([(1, 1, '一'), (9, None, '附录'), (20, 2, '二')], "a.md")
    []
    >>> judge_chapters([(1, None, '附录')], "a.md")          # 一条号都没有：这一层没量到
    []
    """
    out: list[str] = []
    seen: list[int] = []
    first = True
    for line, num, title in items:
        if num is None:
            continue
        if first:
            if num != 1:
                out.append(f"{doc}:第 {line} 行 `## {title[:24]}`：第一章是 {num}，"
                           "不是从「一」起（首号）")
            first = False
        elif num in seen:
            out.append(f"{doc}:第 {line} 行 `## {title[:24]}`：与前面某一章同号 {num}（重号）")
        elif num != seen[-1] + 1:
            gap = (f" —— 缺了「{'、'.join(cjk(c) for c in range(seen[-1] + 1, num))}」"
                   if num > seen[-1] + 1 else " —— 号往回走了")
            out.append(f"{doc}:第 {line} 行 `## {title[:24]}`：前一章是 {seen[-1]}，"
                       f"这一章是 {num}{gap}（断号）")
        seen.append(num)
    return out


def cjk(n: int) -> str:
    """整数 → 中文数字（只到九十九，章号够用）；越界返回十进制串。

    `code_claims.to_int` 管进去，这一支管出来 —— 两句都要，屏幕才能把「缺了三」写成「缺了三」
    而不是「缺了 3」。

    >>> cjk(3), cjk(11), cjk(20), cjk(100)
    ('三', '十一', '二十', '100')
    """
    d = "一二三四五六七八九"
    if not 1 <= n <= 99:
        return str(n)
    if n < 10:
        return d[n - 1]
    tens, ones = divmod(n, 10)
    return ("十" if tens == 1 else d[tens - 1] + "十") + (d[ones - 1] if ones else "")


def judge_sections(items: Sequence[tuple[int, int | None, tuple[int, int] | None, str]],
                   doc: str) -> list[str]:
    """节号：前缀必须等于所在那一章，尾号每章内部从 1 起、步长 1、不重号。

    两种坏法分开说，因为下一步做的事不一样：`串章` 是**这条标题写错了章**（或搬家没改号），
    `断号` 是**有一节没了**。

    >>> it = [(2, 2, (2, 1), '2.1'), (3, 2, (2, 2), '2.2')]
    >>> judge_sections(it, "a.md")
    []
    >>> print(judge_sections([(2, 4, (5, 1), '5.1')], "a.md")[0])
    a.md:第 2 行 `### 5.1`：它写在第四章底下，号却是 5.1（串章）
    >>> print(judge_sections([(2, 2, (2, 1), '2.1'), (3, 2, (2, 3), '2.3')], "a.md")[0])
    a.md:第 3 行 `### 2.3`：前一节尾号是 1，这一节是 3（断号）
    >>> print(judge_sections([(2, 2, (2, 1), '2.1'), (3, 2, (2, 1), '2.1')], "a.md")[0])
    a.md:第 3 行 `### 2.1`：尾号 1 在这一章里已经出现过（重号）
    >>> print(judge_sections([(2, 2, (2, 2), '2.2')], "a.md")[0])
    a.md:第 2 行 `### 2.2`：第二章的第一节尾号是 2，不是 1（首号）
    >>> judge_sections([(2, None, (2, 1), '2.1')], "a.md")      # 上面没有章号：这一条不判
    []
    >>> judge_sections([(2, 2, None, 'P0 —')], "a.md")          # 认不出：不在这里说话
    []
    """
    out: list[str] = []
    tails: dict[int, list[int]] = {}
    for line, chapter, pair, title in items:
        if pair is None:
            continue
        a, b = pair
        if chapter is not None and a != chapter:
            out.append(f"{doc}:第 {line} 行 `### {title[:24]}`：它写在第{cjk(chapter)}章底下，"
                       f"号却是 {a}.{b}（串章）")
            continue
        if chapter is None:
            continue
        seen = tails.setdefault(chapter, [])
        if not seen:
            if b != 1:
                out.append(f"{doc}:第 {line} 行 `### {title[:24]}`："
                           f"第{cjk(chapter)}章的第一节尾号是 {b}，不是 1（首号）")
        elif b in seen:
            out.append(f"{doc}:第 {line} 行 `### {title[:24]}`：尾号 {b} 在这一章里已经出现过（重号）")
        elif b != seen[-1] + 1:
            out.append(f"{doc}:第 {line} 行 `### {title[:24]}`：前一节尾号是 {seen[-1]}，"
                       f"这一节是 {b}（断号）")
        seen.append(b)
    return out


def judge_levels(hs: Sequence[Heading], doc: str) -> list[str]:
    """层级：`#` 只许一条、第一条就得是它、相邻两条不许跳两级、`####` 不许孤悬。

    「跳档」与「孤悬」能在同一处同时冒出来（`##` 直接接 `####` 就是两处：既少一级、
    那一章也还没有 `###`）—— 两条都留着，因为它们下一步要做的事不一样：
    前者是**漏了一级结构**，后者是**这一章的正文没分节**。

    >>> judge_levels([Heading(1, 1, 'a'), Heading(2, 2, '一、'), Heading(3, 3, '1.1')], "a.md")
    []
    >>> for x in judge_levels([Heading(1, 2, '一、'), Heading(9, 4, '小节')], "a.md"): print(x)
    a.md:第 1 行：这一篇有 0 条 `#` 一级标题（该只有一条）
    a.md:第 1 行：第一条标题不是 `#` 一级，而是 `##`
    a.md:第 1→9 行：`##` 直接跳到 `####`，中间少 1 级（跳档）
    a.md:第 9 行 `#### 小节`：这一章里一条 `###` 都没有（孤悬）
    >>> print(judge_levels([Heading(1, 1, 'a'), Heading(2, 1, 'b')], "a.md")[0])
    a.md:第 1 行：这一篇有 2 条 `#` 一级标题（该只有一条）
    >>> print(judge_levels([Heading(3, 3, 'x')], "a.md")[0])
    a.md:第 3 行：这一篇有 0 条 `#` 一级标题（该只有一条）
    >>> print(judge_levels([Heading(3, 3, 'x')], "a.md")[1])
    a.md:第 3 行：第一条标题不是 `#` 一级，而是 `###`
    >>> judge_levels([], "a.md")
    []
    """
    out: list[str] = []
    if not hs:
        return out
    ones = [h for h in hs if h.level == 1]
    if len(ones) != 1:
        out.append(f"{doc}:第 {(ones[0] if ones else hs[0]).line} 行：这一篇有 {len(ones)} 条"
                   " `#` 一级标题（该只有一条）")
    if hs[0].level != 1:
        out.append(f"{doc}:第 {hs[0].line} 行：第一条标题不是 `#` 一级，而是"
                   f" `{'#' * hs[0].level}`")
    has_sec = False
    at_chapter = False
    prev: Heading | None = None
    for h in hs:
        if prev is not None and h.level - prev.level >= 2:
            out.append(f"{doc}:第 {prev.line}→{h.line} 行：`{'#' * prev.level}` 直接跳到"
                       f" `{'#' * h.level}`，中间少 {h.level - prev.level - 1} 级（跳档）")
        if h.level == 2:
            at_chapter, has_sec = True, False
        elif h.level == 3:
            has_sec = True
        elif h.level >= 4 and at_chapter and not has_sec:
            out.append(f"{doc}:第 {h.line} 行 `{'#' * h.level} {h.title[:24]}`："
                       "这一章里一条 `###` 都没有（孤悬）")
        prev = h
    return out


def have_sections(text: str) -> set[tuple[int, int]]:
    """这一篇文档里真存在的 `N.M` 小节号 —— 引用那一层的靶子。

    >>> sorted(have_sections("### 2.1 a\\n#### 2.9 不算\\n### 4.1 b\\n"))
    [(2, 1), (4, 1)]
    """
    return {(int(m.group(1)), int(m.group(2)))
            for h in headings_of(text)[0] if h.level == 3 for m in [SECTION.match(h.title)] if m}


def load_docs(spec: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """逗号分隔的文档名单 → `(读到的 [(显示名, 原文)], 没读到的 [(显示名, 为什么)])`。

    结构层（`--docs`）与引用层的靶子（`--target`）**走这一条读法**，不各写一遍循环：
    两边都要「点名了三篇、读到两篇」那种分母，两边都说人话而不裸崩（2.36 那一族）。
    读到但一条标题都没有的，仍然算 `got` —— 那是**结构层**的事，由 `main` 去挑；
    靶子那一层要的只是原文里有几条 `### N.M`，一条标题都没有的文档照样能当靶子读。

    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as td:
    ...     p = pathlib.Path(td) / "甲.md"
    ...     _ = p.write_text("# 题\\n## 一、甲\\n", encoding="utf-8")
    ...     got, unread = load_docs(f"{p},  {td}/乙.md ")
    >>> [n.split("/")[-1] for n, _t in got], [n.split("/")[-1] for n, _w in unread]
    (['甲.md'], ['乙.md'])
    >>> unread[0][1]
    '文件不在'
    >>> load_docs("")[0] == [] and load_docs("")[1] == []
    True
    """
    got: list[tuple[str, str]] = []
    unread: list[tuple[str, str]] = []
    for item in [s.strip() for s in spec.split(",") if s.strip()]:
        p = Path(item)
        if not p.is_absolute():
            p = ROOT / p
        disp = str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p)
        text, why = doc_num.read_doc(p)
        if text is None:
            unread.append((disp, why))
        else:
            got.append((disp, text))
    return got, unread


def cites_in(text: str) -> list[tuple[int, tuple[int, int], str]]:
    """这一份件里那些**带前缀**的节号引用：`(行号, (章, 节), 那一句)`。

    只认带 `计划书`／`§` 前缀的，是有代价的一条界（见模块那段「它不量什么」）：
    靶子正文里 1838 处没带前缀的 `N.M` 串装着出口 IP 打头的两拍、Python 版本和时长，
    读进来当场多出 257 处假断链 —— 2.72 第一遍真读到的那 3 处就埋在里面（11:44:30 现数）。
    代价也钉住：`>>>` 那些示例行**照样读** —— 本件不给引用开豁免（2.66 对命令尺定过一次了）。

    >>> cites_in("见 计划书 2.8 那一条")
    [(1, (2, 8), '计划书 2.8')]
    >>> cites_in("§2.68 的 `M16`\\n而 3.12 是版本\\n")
    [(1, (2, 68), '§2.68')]
    >>> fenced = "```\\n这是一段举例\\n```\\n"      # 那个假号写成 `"§2" + ".9"`，见 `DEAD` 那一段
    >>> cites_in(fenced + "§2" + ".9 出围栏了\\n" + fenced)      # 夹在两块围栏中间的那一行算引用
    [(4, (2, 9), '§2.9')]
    >>> cites_in("```\\n" + "§2" + ".9 在围栏里\\n```")
    []
    """
    out: list[tuple[int, tuple[int, int], str]] = []
    inside = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
            continue
        if inside:
            continue
        for m in CITE.finditer(line):
            out.append((n, (int(m.group(1)), int(m.group(2))), m.group()))
    return out


def ref_paths(spec: str) -> tuple[list[Path], list[str], list[str]]:
    """`--refs` 那串换成要读的件。返回 `(件, 跳过的冲突副本, 点名了但没给东西)`。

    目录递归、只收 `.py`／`.md`；`计划书 2.md`／`check_doc_cmds 2.py` 那种同步盘刚掉进来的
    副本**不读** —— 判据不自己写一份，拿 `stray_names.classify` 的（一条规矩两个人各写一遍，
    正是 2.58 收掉过的那种毛病）。只跳 `red` 那一档：`note` 说的是「名字里有空格，照抄要加引号」，
    那类件**内容照样要读**，把它们当副本跳过等于给引用层开一个看不见的洞。

    >>> paths, copies, _ = ref_paths("docs")
    >>> all(p.suffix in (".py", ".md") for p in paths)
    True
    >>> len(copies) >= 0
    True
    >>> ref_paths("")[0] == [] and ref_paths("")[2] == []
    True
    >>> classify_name("湖南 卫视.m3u")[0] == NAME_RED      # note 那一档不算副本：它的件要读
    False
    """
    got: list[Path] = []
    copies: list[str] = []
    empty: list[str] = []
    for item in [s.strip() for s in spec.split(",") if s.strip()]:
        p = Path(item)
        if not p.is_absolute():
            p = ROOT / p
        if p.is_dir():
            found = sorted(list(p.rglob("*.py")) + list(p.rglob("*.md")))
            if not found:
                empty.append(item)
            for f in found:
                if classify_name(f.name)[0] == NAME_RED:
                    copies.append(str(f.relative_to(ROOT)))
                    continue
                got.append(f)
        elif classify_name(p.name)[0] == NAME_RED:
            copies.append(str(item))
        else:
            got.append(p)
    return got, copies, empty


def check_cites(have: set[tuple[int, int]], files: Sequence[Path],
                base_bare_from: str = "", target_empty: str = "") -> Cites:
    """比对：每一份件里那些带前缀的引用，指过去的节还在不在。

    `base_bare_from` 是**靶子那几篇**的原文 —— 只为量那个「不读」的分母，一句判据都不靠它。
    它**不**进 `asked`：那个数是「点名要读的件数」，拿一份没点名的原文去充它，
    `--refs` 给了空名单那一格（`B11`）就会被它顶成「读到了件」。

    `target_empty` 是「靶子为什么是空的」那一句（`--target` 一个字都没给／点名的靶子一篇没读到／
    读到了可里面一条编号小节都没有）。靶子空的时候这一层**只数不判**：`tokens` 照记，
    `dangling` 一格不添 —— 11:09:42 那一遍把 `--docs` 指到两篇没有 `### N.M` 的文档上，
    空靶子当场把全仓库的引用判成 212 处断链，那是尺在编，不是文档在坏。

    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as td:
    ...     a = pathlib.Path(td) / "假件.py"
    ...     _ = a.write_text(f"见 {DEAD} 的第三级\\n而 §2.1 是真的\\n", encoding="utf-8")
    ...     led = check_cites({(2, 1)}, [a])
    >>> (led.asked, led.tokens, len(led.dangling), dict(led.per_file) == {str(a): 2})
    (1, 2, 1, True)
    >>> DEAD in led.dangling[0] and '文档里没有 `### 5.3`' in led.dangling[0]
    True
    >>> # 读不到的件不进 `per_file`，但必须进 `unread` —— 否则那句「比了 N 处」缺了一块还不知道
    >>> with tempfile.TemporaryDirectory() as td:
    ...     led2 = check_cites(set(), [pathlib.Path(td) / "不在.md"])
    >>> (led2.asked, led2.tokens, len(led2.per_file), len(led2.unread))
    (1, 0, 0, 1)
    >>> check_cites({(2, 1)}, []).asked          # 空名单：这一层一个字都没比
    0
    >>> with tempfile.TemporaryDirectory() as td:      # 空靶子：那 212 处假断链的最小形状
    ...     a = pathlib.Path(td) / "假件.py"
    ...     _ = a.write_text("见 §2.1\\n§2.2 也算一处\\n", encoding="utf-8")
    ...     led3 = check_cites(set(), [a], target_empty="读到了，可里面一条编号小节都没有")
    >>> (led3.tokens, led3.dangling, led3.refused, led3.target_secs)
    (2, [], True, 0)
    >>> led3.no_target
    '读到了，可里面一条编号小节都没有'
    """
    led = Cites(bare=len(BARE.findall(base_bare_from)) if base_bare_from else 0,
                asked=len(files), target_secs=len(have))
    if not have:
        led.no_target = target_empty or "靶子里一条 `### N.M` 都没有"
    for p in files:
        text, why = doc_num.read_doc(p)
        disp = str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p)
        if text is None:
            led.unread.append(f"{disp} —— {why}")
            continue
        cs = cites_in(text)
        led.per_file[disp] = len(cs)
        led.tokens += len(cs)
        for line, pair, said in cs:
            if pair not in have and not led.no_target:
                led.dangling.append(f"{disp}:{line} 写着「{said}」，可{have_note(have, pair)}")
    return led



def have_note(have: set[tuple[int, int]], pair: tuple[int, int]) -> str:
    """「指过去的那一节不存在」这句话里，把**为什么不存在**说清楚。

    光说「没有 `### 5.3`」不够：第五章不是「5.3 被删了」，它**从来没有带编号的小节** ——
    一句「第三级」指的是一张表的第三行。两种读法要做的下一步不一样。

    >>> have_note({(2, 1), (2, 2)}, (2, 9))
    '文档里没有 `### 2.9`（第二章有 2 条编号小节，最大到 2.2）'
    >>> have_note({(2, 1)}, (5, 3))
    '文档里没有 `### 5.3`（第五章一条编号小节都没有）'
    """
    a, b = pair
    mine = sorted(x for x in have if x[0] == a)
    if not mine:
        return (f"文档里没有 `### {a}.{b}`（第{cjk(a)}章一条编号小节都没有）"
                if a <= 99 else f"文档里没有 `### {a}.{b}`")
    return (f"文档里没有 `### {a}.{b}`（第{cjk(a)}章有 {len(mine)} 条编号小节，"
            f"最大到 {a}.{max(y for _x, y in mine)}）")


def shares(counts: Mapping[str, int], keep: int) -> str:
    """把「哪一份件里写了几句引用」收成一句尾巴，只摊前 `keep` 名。

    为什么要有这一句（2.66/2.67 那个形状在本件里又管用一次）：那一屏原来只说「出自 38 份件」，
    而这一层的价值全在**是谁**上 —— 今天那一句是「`计划书.md` 51、`scripts/doc_headings.py` 28、
    `docs/电视订阅接入.md` 25」（11:45:21 现数），说的是「跨层的记性主要写在哪几件里」，
    38 这一个字答不了；而第二名是本件自己 —— 一把读引用的尺，自己就是引用的一个大户，
    2.73 之后它超过那篇说明书排到了第二（那一节往自己的说明书里写了七句带前缀的引用）。
    （`selfcheck.py` 只在第 21 名、2 句 —— 打前那把尺自己几乎不引用文档，这一层是给说明书装的。）

    为什么不抄 `unmarked_nums.split`：那一句要把**每一篇**都摊出来，好让
    「各篇加起来 == 这一行报的总数」当场可验（它那边只有个位数篇）。这里今天 38 份件，
    全摊比它要替的那句长十倍，所以只摊前几名、其余报份数 + 最大的那份 ——
    代价明说：**这一句不配平**，它是「是谁」，不是「一共几个」。

    >>> shares({"a.py": 43, "b.py": 26, "c.py": 3, "d.py": 1}, 2)
    '，其中 a.py 43、b.py 26（另有 2 份没摊，最大的那份 3 处）'
    >>> shares({"a.py": 1}, 6)
    '，其中 a.py 1'
    >>> shares({}, 6)
    ''
    >>> shares({"b.py": 2, "a.py": 2}, 6)         # 一样多时按名字排，不按插入顺序
    '，其中 a.py 2、b.py 2'
    """
    if not counts:
        return ""
    ranked = sorted(counts.items(), key=lambda t: (-t[1], t[0]))
    top, rest = ranked[:keep], ranked[keep:]
    tail = f"（另有 {len(rest)} 份没摊，最大的那份 {rest[0][1]} 处）" if rest else ""
    return "，其中 " + "、".join(f"{n} {c}" for n, c in top) + tail


def render(docs: Sequence[Found], cites: Cites, *, unread_docs: Sequence[tuple[str, str]],
           show_all: bool) -> list[str]:
    """那一屏：每一层各占一行、每一行都带着今天的处数，最后一行是给 `selfcheck` 挑走的结论。

    每一层自己报自己的「照见 / 认不出 / 毛病」三个数，不写「见上面那句毛病数」那种话 ——
    那一层今天 0 实例时，「见上面」指的是一个压根没出现的东西，读的人无从知道它查过。

    顶上第二、第三行分成「本篇 …」与「靶子 …」两句，是因为 11:09:42 那一遍：`--docs` 一个名字
    同时管着「结构层查谁」和「引用层拿谁的节号当真」，指到两篇没有 `### N.M` 的文档上，
    引用层就没了靶子。所以靶子单独一行、单独报几条编号小节，与被查那几篇不重叠时明说；
    结论那一句末尾也带着「靶子 N 条编号小节」—— 「断链 0 处」配不上一个空靶子。
    """
    out = ["文档的标题结构 —— 编号连着排没有、层级跳没跳、引用指得到指不到",
           f"本篇 {'、'.join(d.doc for d in docs)}",
           f"靶子 {'、'.join(cites.target_names) if cites.target_names else '（`--target` 一个字都没给）'}"
           f"：{cites.target_secs} 条 `### N.M`"
           + (" —— 与被查那几篇不重叠，引用判的是另一篇的节号"
              if cites.target_names and not (set(cites.target_names)
                                             & {d.doc for d in docs}) else "")
           + (f" · 引用层读了 {len(cites.per_file)} 份件" if cites.per_file
              else " · 引用层一份都没读"),
           ""]

    for d in docs:
        out.append(f"   {d.doc}  照成标题 {d.heads} 条 · 毛病 {len(d.bad)} 处"
                   + (" ← 逐条点名" if d.bad else ""))
        out.append(f"   章 `## <中文数字>、`：照见 {d.chapters} 条 · 编号认不出 {len(d.unnamed_ch)} 条"
                   "（只报数、不拦）· 毛病 " + str(len(d.bad_ch)) + " 处")
        out.append(f"   节 `### N.M`：照见 {d.sections} 条 · 编号认不出 {len(d.unnamed_sec)} 条"
                   "（只报数、不拦）· 毛病 " + str(len(d.bad_sec)) + " 处")
        out.append(f"   层级：毛病 {len(d.bad_lvl)} 处 · 围栏里以 `#` 开头没照进来的"
                   f" {d.fenced_hash} 行")
        out.append("   各级：" + " · ".join(f"{'#' * k} {v}"
                                            for k, v in sorted(d.levels.items())))
        if not d.balanced:
            out.append(f"   配平：`##` {d.levels.get(2, 0)} 条 ≠ 认得出 {d.chapters}"
                       f" + 认不出 {len(d.unnamed_ch)}（`###` 那层同理）—— 不合："
                       "有一行标题哪一档都没进去，这一屏上面每一个「照见 N 条」都少了几条")
        else:
            out.append(f"   配平：`##` {d.levels.get(2, 0)} 条 = 认得出 {d.chapters}"
                       f" + 认不出 {len(d.unnamed_ch)}；`###` {d.levels.get(3, 0)} 条 = 认得出"
                       f" {d.sections} + 认不出 {len(d.unnamed_sec)}")
        if d.bad:
            out += [f"   ✗ {b}" for b in d.bad]
        if d.unnamed:
            shown = d.unnamed if show_all else d.unnamed[:NAMED]
            out.append(f"   编号认不出的那 {len(d.unnamed)} 条（默认摊 "
                       f"{min(NAMED, len(d.unnamed))} 条，`--all` 摊全）：")
            out += [f"     · {u}" for u in shown]
            if len(d.unnamed) > len(shown):
                out.append(f"     · …另有 {len(d.unnamed) - len(shown)} 条没摊")
    out.append("")
    if cites.no_list:
        out.append("   引用：`--refs` 给了空名单 —— 这一层今天一个字都没比（不是「都对」）")
    elif cites.refused:
        out.append(f"   引用：**这一层不敢判** —— {cites.no_target}，"
                   f"那 {cites.tokens} 处带前缀的引用无处可判")
        out.append("   断链 未判 —— 这一格空着是**没判**，不是干净（两种 0 不同形）")
    elif not cites.tokens:
        out.append(f"   引用：读了 {len(cites.per_file)} 份件，一处带前缀的节号引用都没有 —— "
                   "这一层比了个空，但没有断链")
    else:
        out.append(f"   引用：比了 {cites.tokens} 处 —— 出自 {len(cites.per_file)} 份件"
                   + shares(cites.per_file, NAMED))
        out.append(f"   断链 {len(cites.dangling)} 处"
                   + (" ← 逐条点名" if cites.dangling else " —— 一处都没断"))
        out += [f"   ✗ {x}" for x in cites.dangling]
    if cites.target_unread:
        out.append(f"   靶子有 {len(cites.target_unread)} 篇没读到："
                   + "、".join(cites.target_unread[:NAMED])
                   + (f" …另有 {len(cites.target_unread) - NAMED} 篇"
                      if len(cites.target_unread) > NAMED else "")
                   + f" —— 上面那句「{cites.target_secs} 条 `### N.M`」只覆盖读到的那些靶子")
    if cites.bare:
        out.append(f"   靶子里没带前缀的那种 `N.M` 串 {cites.bare} 处，本节一处都不读"
                   "（那是版本、时长、IP 尾巴 —— 见模块那段边界）")

    if cites.copies:
        out.append(f"   跳过同步盘冲突副本 {len(cites.copies)} 份："
                   + "、".join(cites.copies[:NAMED])
                   + (f" …另有 {len(cites.copies) - NAMED} 份" if len(cites.copies) > NAMED else ""))
    if cites.unread:
        out.append(f"   引用层有 {len(cites.unread)} 份没读到：" + "、".join(cites.unread[:NAMED])
                   + (" …" if len(cites.unread) > NAMED else "")
                   + " —— 上面那句「比了 N 处」只覆盖读到的那些件")
    if unread_docs:
        out.append("")
        out.append(f"   点名的 {len(docs) + len(unread_docs)} 篇里有 {len(unread_docs)} 篇没读到："
                   + "、".join(f"{n}（{w}）" for n, w in unread_docs)
                   + " —— 这一屏不是「整个仓库的标题结构」。")
    bad = sum(len(d.bad) for d in docs)
    link = (f"引用断链 {len(cites.dangling)} 处" if not cites.refused else "引用断链 未判")
    out += ["", f"扫了 {len(docs)} 篇文档、{sum(d.heads for d in docs)} 条标题、"
          f"比了 {cites.tokens} 处引用：结构毛病 {bad} 处、{link}、"
          f"靶子 {cites.target_secs} 条编号小节"
          + (f"，{len(unread_docs)} 篇没读到" if unread_docs else "")
          + (f"，{len(cites.unread)} 份引用件没读到" if cites.unread else "")
          + (f"，{len(cites.target_unread)} 篇靶子没读到" if cites.target_unread else "")]
    return out



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="文档的标题结构：编号连着排没有、引用指不指得到")
    ap.add_argument("--docs", default=DEFAULT_DOCS,
                    help=f"结构层查哪几篇文档，逗号分隔（默认 {DEFAULT_DOCS}）")
    ap.add_argument("--target", default=DEFAULT_TARGET, dest="target",
                    help=f"引用层拿哪几篇的 `### N.M` 当真，逗号分隔（默认 {DEFAULT_TARGET}）")
    ap.add_argument("--refs", default=DEFAULT_REFS,
                    help=f"引用层比哪几份件，逗号分隔、目录递归（默认 {DEFAULT_REFS}）")
    ap.add_argument("--all", action="store_true", dest="show_all",
                    help="把「认不出编号」那一档逐条摊开")
    ap.add_argument("--self-test", action="store_true", dest="self_test",
                    help=f"往临时目录里种 {len(BASELINE)} 格已知形状的文档，问这把尺判得对不对")
    ap.add_argument("--doctest", action="store_true",
                    help="只跑它自己的 doctest（读 `args.doctest`，所以这一屏不读任何文档）")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.doctest:
        return run_own(sys.modules[__name__])   # 2.69：答在 `main()` 里，不在收尾那一道
    if args.self_test:
        return self_test()                      # 先跑掉：这一档一个字都不该读仓库里那几篇
    docs = [s.strip() for s in args.docs.split(",") if s.strip()]
    if not docs:
        print("--docs 里一个名字都没给：这一屏没有可读的东西，也不算量过。", file=sys.stderr)
        return 2
    got, unread = load_docs(args.docs)
    found: list[Found] = []
    for disp, text in got:
        led = survey(text, disp)
        if not led.heads:
            unread.append((disp, "读到了，可一条标题都没照见"))
            continue
        found.append(led)
    for disp, why in unread:
        print(f"！没读到：{disp} —— {why}", file=sys.stderr)
    if not found:
        print(f"点名的 {len(docs)} 篇一篇都没读到标题 —— 一个字都没量到，不算通过。", file=sys.stderr)
        return 2
    # 引用层的靶子单独一份名单：它不跟着 `--docs` 走（缘由见 `render` 那段与 `check_cites`）。
    got_t, unread_t = load_docs(args.target)
    have: set[tuple[int, int]] = set()
    base_text = ""
    for _disp, text in got_t:
        have |= have_sections(text)
        base_text += text
    if not [s for s in args.target.split(",") if s.strip()]:
        why_t = "`--target` 一个字都没给，靶子是空的"
    elif not got_t:
        why_t = f"点名的 {len(unread_t)} 篇靶子一篇都没读到"
    elif not have:
        why_t = f"靶子那 {len(got_t)} 篇里一条 `### N.M` 都没有"
    else:
        why_t = ""
    files, copies, empty_dirs = ref_paths(args.refs)
    cites = check_cites(have, files, base_text, why_t)
    cites.copies = copies
    cites.target_names = [d for d, _t in got_t]
    cites.target_unread = [f"{d}（{w}）" for d, w in unread_t]
    for d in empty_dirs:
        print(f"！`--refs` 里那个目录一份件都没有：{d}", file=sys.stderr)
    for line in render(found, cites, unread_docs=unread, show_all=args.show_all):
        print(line)
    bad = sum(len(d.bad) for d in found)
    if cites.no_list:
        print("引用层一个字节都没读 —— 结构那一层量到了，可这一屏说的是两层，不是三层。",
              file=sys.stderr)
        return 2
    if cites.no_target and not cites.refused:
        print("靶子一条编号小节都没有 —— 今天没有一处引用要判，所以这一格没响；"
              "下一句 `§N.M` 写进任何一份件，它就大声退 2。", file=sys.stderr)
    if cites.refused:
        print(f"引用层一个字都没判 —— {cites.no_target}。结构那一层量到了，"
              "可「断链 0 处」是判不出来的 0，这一屏不许读成两层都对。", file=sys.stderr)
        return 2
    return 1 if (bad or cites.dangling or unread or cites.unread
                 or cites.target_unread) else 0



# ——————————————————————————————————————————————————————————
# 基线（§2.72）：这把尺判得对不对
#
# 为什么要有这一档：这一把尺今天量到的毛病是 0 处结构、1 处断链，而「0 处」有两种读法 ——
# 文档真干净，或者判据整层不咬。断号那一支在今天的文档里**一个实例都没有**（2.71 给 NET 那一族
# 记的是同一笔账），所以这一档不只是回归测试，它是这一屏上「那几条判据在响」的唯一证据。
# ——————————————————————————————————————————————————————————

CH1 = "## 一、甲\n"
CH2 = "## 二、乙\n"
CH3 = "## 三、丙\n"
S1 = "### 1.1 头一节\n"
S2 = "### 1.2 第二节\n"
T1 = "### 2.1 乙章的头一节\n"
# 一份「两章两节、编号全对」的最小文档。引用那几格要用它：假件里那句 `§2.1` 在沙盒里
# 必须真有对应的小节，否则 G5 那种「该退 0」的格子会红在断链上，量的就不是判据了。
# 而 `§2.1` 写在本件里也**恰好**是这份仓库真有的节号 —— 引用层读 .py 的源码，
# 本件里凡是假号都得走 `DEAD` 那一支，这一句不必。
OK = "# 题\n" + CH1 + S1 + CH2 + T1
# 「整篇一条编号章都没有」那一族：`## 1.`、`## 2.` 这种步骤号版式。今天仓库里就有两篇这样写的
# （11:15:25 现数：`docs/真机验收单.md` 8 条 `##` 全认不出、`docs/电视订阅接入.md` 2 条 `##`
# 加 6 条 `###` 全认不出，两篇的 `### N.M` 都是 0 条）—— 本节把这两篇递进默认名单，
# 于是「认不出全部」从设想变成每一遍自检都会路过的常态，得有格子钉住它不等于「有毛病」。
STEP1 = "## 1. 点第一个台\n"
STEP2 = "## 2. 点第二个台\n"
NO_NUM = "# 真机验收单\n" + STEP1 + STEP2

BASELINE: tuple[Cell, ...] = (
    # ———— G 组：这些情形**不许**报错。它们红了就是尺在瞎咬 ————
    Cell("G1_章连着", "一二三连着排：退 0，且那句「毛病 0 处」要说出口",
         0, files=((DOC, "# 题\n" + CH1 + CH2 + CH3),),
         has=["照成标题 4 条 · 毛病 0 处", "章 `## <中文数字>、`：照见 3 条"]),
    Cell("G2_节连着", "一章底下 1.1、1.2 连着：节那一行报几条、配平那行报每一级几条",
         0, files=((DOC, "# 题\n" + CH1 + S1 + S2),),
         has=["节 `### N.M`：照见 2 条 · 编号认不出 0 条（只报数、不拦）· 毛病 0 处",
              "各级：# 1 · ## 1 · ### 2",
              "配平：`##` 1 条 = 认得出 1 + 认不出 0；`###` 2 条 = 认得出 2 + 认不出 0"]),
    Cell("G3_认不出只报数", "没编号的 `##`／`###` 落「认不出」那一档，一条都不许判成毛病",
         0, files=((DOC, "# 题\n## 附录、来头\n" + CH1 + "### P0 — 第一天\n"),),
         has=["章 `## <中文数字>、`：照见 1 条 · 编号认不出 1 条",
              "节 `### N.M`：照见 0 条 · 编号认不出 1 条",
              "编号认不出的那 2 条", "毛病 0 处"],
         lacks=["✗"]),
    Cell("G4_围栏里的不读", "代码块里那段 markdown 示例不许进结构账（今天的文档里正是节目单）",
         0, files=((DOC, "# 题\n" + CH1 + "```\n### 9.9 举例\n## 九、举例\n```\n" + S1),),
         has=["节 `### N.M`：照见 1 条", "各级：# 1 · ## 1 · ### 1",
              "配平：`##` 1 条 = 认得出 1 + 认不出 0；`###` 1 条 = 认得出 1 + 认不出 0",
              "围栏里以 `#` 开头没照进来的 2 行"]),
    Cell("G5_引用都对", "带前缀的引用指着真存在的节：断链 0 处，且那一句要说「一处都没断」",
         0, files=((DOC, OK), ("假件.py", "见 §2.1 那一节\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/假件.py"),
         has=["引用：比了 1 处 —— 出自 1 份件，其中", "假件.py 1",
              "断链 0 处 —— 一处都没断"]),
    Cell("G6_结论那句带分母", "selfcheck 只印最后一行 —— 「比了几处」不挂到结论句上就等于没挂",
         0, files=((DOC, OK), ("假件.py", "见 §2.1\n§2.1 也提一次\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/假件.py"),
         has=["扫了 1 篇文档、5 条标题、比了 2 处引用：结构毛病 0 处、引用断链 0 处、"
              "靶子 2 条编号小节"]),
    Cell("G7_几份件各几处", "引用层的分母要拆得开：哪一份件里写了几句（2.66/2.67 那个形状）",
         0, files=((DOC, OK), ("甲件.py", "见 §2.1\n§2.1 也提一次\n"),
                   ("乙件.py", "只有这里提了一次 §2.1\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/甲件.py,{SANDBOX}/乙件.py"),
         has=["比了 3 处 —— 出自 2 份件，其中", "甲件.py 2", "乙件.py 1",
              "断链 0 处 —— 一处都没断"]),
    Cell("G8_靶子与被查分开", "**11:09:42 那一遍的形状**：被查那篇一条编号小节都没有，靶子另有其人 —— 引用层照判，退 0",
         0, files=((DOC, OK), ("无编号.md", NO_NUM), ("假件.py", "见 §2.1 那一节\n")),
         argv=("--docs", f"{SANDBOX}/无编号.md", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/假件.py"),
         has=["靶子 ", "与被查那几篇不重叠", "引用层读了 1 份件",
              "断链 0 处 —— 一处都没断", "引用断链 0 处、靶子 2 条编号小节"]),
    Cell("G9_整篇没编号章", "真机验收单那种版式：`## 1.`、`## 2.` 全落「认不出」，一条都不许判成毛病",
         0, files=((DOC, NO_NUM), ("靶子.md", OK)),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/靶子.md",
               "--refs", f"{SANDBOX}/靶子.md"),
         has=["章 `## <中文数字>、`：照见 0 条 · 编号认不出 2 条",
              "结构毛病 0 处、引用断链 0 处、靶子 2 条编号小节"],
         lacks=["✗"]),

    # —— 以下每一格钉一条「今天的文档里 0 实例」的判据：没有这些格子，那几条判据等于没测 ——
    Cell("B1_章断号_真事故重放", "**上一节那次提交的样子**：`## 三、总体架构` 整行没了",
         1, files=((DOC, "# 题\n" + CH1 + CH2 + CH3.replace("三、丙", "四、丁")),),
         has=["缺了「三」（断号）", "结构毛病 1 处"]),
    Cell("B2_章重号", "同一个号出现两次（搬家改错了、或复制粘贴）",
         1, files=((DOC, "# 题\n" + CH1 + CH2 + CH1.replace("一、甲", "一、又一份甲")),),
         has=["与前面某一章同号 1（重号）"]),
    Cell("B3_章不从一开始", "第一篇就是「二」（首号）—— 头部丢一章",
         1, files=((DOC, "# 题\n" + CH2 + CH3),), has=["不是从「一」起（首号）"]),
    Cell("B4_节串章", "二章底下写着 `### 5.1`",
         1, files=((DOC, "# 题\n" + CH1 + S1 + CH2 + "### 5.1 跑错了\n"),),
         has=["它写在第二章底下，号却是 5.1（串章）", "节 `### N.M`：照见 2 条",
              "结构毛病 1 处"]),
    Cell("B5_节断号", "1.1 之后直接 1.3 —— 中间那一节整行没了",
         1, files=((DOC, "# 题\n" + CH1 + S1 + "### 1.3 第三节\n"),),
         has=["前一节尾号是 1，这一节是 3（断号）"]),
    Cell("B6_节重号", "两节同号 1.1",
         1, files=((DOC, "# 题\n" + CH1 + S1 + S1.replace("头一节", "另一头一节")),),
         has=["尾号 1 在这一章里已经出现过（重号）"]),
    Cell("B7_节不从头号", "一章的第一节写着 1.2 —— 头部丢一节",
         1, files=((DOC, "# 题\n" + CH1 + "### 1.2 第二节\n"),),
         has=["第一章的第一节尾号是 2，不是 1（首号）"]),
    Cell("B8_跳档", "`##` 直接到 `####`，中间少一级",
         1, files=((DOC, "# 题\n" + CH1 + "#### 小节\n"),),
         has=["`##` 直接跳到 `####`，中间少 1 级（跳档）"]),
    Cell("B9_孤悬的四级", "这一章里一条 `###` 都没有，`####` 却来了（同一处两句：跳档也算它）",
         1, files=((DOC, "# 题\n" + CH1 + S1 + "#### 好\n" + CH2 + "#### 坏\n"),),
         has=["这一章里一条 `###` 都没有（孤悬）", "`##` 直接跳到 `####`",
              "层级：毛病 2 处"]),
    Cell("B10_两条一级", "一篇文档两个 `#`（拼了两份东西）",
         1, files=((DOC, "# 题\n# 又一个题\n" + CH1),),
         has=["这一篇有 2 条 `#` 一级标题（该只有一条）"]),
    Cell("B11_没有一级标题", "整篇从 `##` 起：那一句要把「几条」和「第一条是几级」各说一句",
         1, files=((DOC, CH1 + S1),),
         has=["这一篇有 0 条 `#` 一级标题（该只有一条）", "第一条标题不是 `#` 一级，而是 `##`"]),
    Cell("B12_摊不完要报数", "「认不出」那一档比 `--all` 关掉时摊的条数多：少了哪几条要说出来（2.61 那一课）",
         0, files=((DOC, "# 题\n" + CH1 + "".join(f"### P{i} — 第一天\n" for i in range(8))),),
         has=["编号认不出的那 8 条", "…另有 2 条没摊"],
         lacks=["### P7"]),
    Cell("B13_引用断链", "**本节第一遍真量到的那一种**：指着一个文档里没有的节号（那句原话由 `DEAD` 拼）",
         1, files=((DOC, "# 题\n" + CH1 + S1), ("假件.py", f"见 {DEAD} 的第三级\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/假件.py"),
         has=["断链 1 处 ← 逐条点名", f"假件.py:1 写着「{DEAD}」",
              "文档里没有 `### 5.3`（第五章一条编号小节都没有）",
              "结构毛病 0 处、引用断链 1 处"],
         lacks=["该只有一条"]),
    Cell("B14_引用件不在", "点名的引用件读不到：结构那一层照样量到了，退 1 且那句分母要说",
         1, files=((DOC, OK),),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/不在.py"),
         has=["引用层有 1 份没读到", "文件不在", "1 份引用件没读到"]),
    Cell("B15_引用层空名单", "`--refs` 给空串：那一层一个字都没读，不许读成「比了 0 处」那种绿",
         2, files=((DOC, OK),), argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
                                      "--refs", ""),
         has=["`--refs` 给了空名单 —— 这一层今天一个字都没比（不是「都对」）"]),
    Cell("B16_比了个空", "给了件、可里面一处带前缀的引用都没有：退 0，但那句话要说清",
         0, files=((DOC, OK), ("假件.py", "这里谁都没引用\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/假件.py"),
         has=["一处带前缀的节号引用都没有 —— 这一层比了个空，但没有断链"]),
    Cell("B17_文档不在", "点名两篇、只读到一篇：退 1，且每一行数只覆盖读到的那一篇",
         1, files=((DOC, "# 题\n" + CH1),),
         argv=("--docs", f"{SANDBOX}/{DOC},{SANDBOX}/不在.md", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/{DOC}"),
         has=["点名的 2 篇里有 1 篇没读到", "1 篇没读到"]),
    Cell("B18_文档是目录", "2.36 那一族的第三种读法：不许裸崩",
         2, argv=("--docs", str(SANDBOX)), has=["那是个目录", "一篇都没读到标题"],
         lacks=["Traceback"]),
    Cell("B19_文档是二进制", "同一族另一支异常，也只说人话",
         2, bins=("坏件.bin",), argv=("--docs", f"{SANDBOX}/坏件.bin"),
         has=["读不出来"], lacks=["Traceback"]),
    Cell("B20_空文档", "读到一篇但一条标题都没有：那是「没量到」，不是「都对」",
         2, files=((DOC, "这一篇一行标题都没写。\n"),),
         has=["读到了，可一条标题都没照见", "一篇都没读到标题"]),
    Cell("B21_docs给空串", "参数取坏值时不许去读仓库里那一篇",
         2, argv=("--docs", ""), has=["--docs 里一个名字都没给"]),
    # ———— 靶子那一档：引用层的「存在」是谁说了算。上一组钉的是判据咬不咬，这一组钉的是它敢不敢咬 ————
    Cell("B22_空靶子不敢判", "被查与靶子同一篇、里面一条编号小节都没有，可外面有引用：只数不判，退 2",
         2, files=((DOC, NO_NUM), ("假件.py", "见 §2.1\n§2.2 也算一处\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", f"{SANDBOX}/{DOC}",
               "--refs", f"{SANDBOX}/假件.py"),
         has=["引用：**这一层不敢判** —— 靶子那 1 篇里一条 `### N.M` 都没有，"
              "那 2 处带前缀的引用无处可判",
              "断链 未判 —— 这一格空着是**没判**，不是干净",
              "结构毛病 0 处、引用断链 未判、靶子 0 条编号小节"],
         lacks=["一处都没断"]),
    Cell("B23_靶子给空串", "`--target` 给空串：`B15` 的姊妹格 —— 靶子这一侧也不许读成「比了 0 处」那种绿",
         2, files=((DOC, OK), ("假件.py", "见 §2.1\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target", "", "--refs", f"{SANDBOX}/假件.py"),
         has=["`--target` 一个字都没给，靶子是空的", "那 1 处带前缀的引用无处可判",
              "靶子 （`--target` 一个字都没给）"],
         lacks=["一处都没断"]),
    Cell("B24_靶子读不到", "点名的靶子有一篇读不到：判是照判了，可那句分母缺了一块 → 退 1",
         1, files=((DOC, OK), ("假件.py", "见 §2.1 那一节\n")),
         argv=("--docs", f"{SANDBOX}/{DOC}", "--target",
               f"{SANDBOX}/{DOC},{SANDBOX}/不在.md", "--refs", f"{SANDBOX}/假件.py"),
         has=["靶子有 1 篇没读到：", "文件不在", "1 篇靶子没读到"]),
)


def targetless(cells: Sequence[Cell]) -> list[str]:
    """哪些格子把引用层的靶子留给了默认值 —— **跑任何一格之前先问这一条**。

    为什么要有这一道：`--target` 的默认值是仓库里那一篇 `计划书.md`（1160 KB、85 条编号小节）。
    沙盒里那篇三行的假文档要是靠它当靶子，格子量的就不再是判据，而是「今天仓库里有没有
    `### 2.1`」—— 文档添一节、删一节，沙盒跟着红，而红的原因没人猜得到。这一道与
    `ragged_cells`、`braced_cells` 同档：它咬的是基线自己写歪的地方，不是尺的判决。

    没写参数的格子按 `DEFAULT_CELL_ARGV` 问 —— 否则把那条默认串里的 `--target` 删掉，
    全仓库没有一格会红（沙盒里那些假文档没有一处带前缀的引用，空靶子因此一声不响）。

    >>> targetless([Cell("A", "x", 0, argv=("--docs", "d", "--refs", "r"))])
    ['A：这一格会让引用层去读仓库里那一篇（`--target` 没给）']
    >>> targetless([Cell("B", "y", 0, argv=("--refs", "r", "--target", "t"))])
    []
    >>> targetless([Cell("C", "z", 0), Cell("D", "w", 0, argv=("--docs", "d"))])
    []
    >>> targetless([Cell("E", "v", 0, argv=("--docs", "d", "--target", ""))])
    []
    """
    return [c.who + "：这一格会让引用层去读仓库里那一篇（`--target` 没给）"
            for c in cells
            if "--refs" in (c.argv or DEFAULT_CELL_ARGV)
            and "--target" not in (c.argv or DEFAULT_CELL_ARGV)]


def run_cell(cell: Cell, base: Path) -> tuple[str, str, str]:
    """跑一格：返回 `(判决, 为什么, 那一遍的原文)`。判决是 `ok`／`bad`／`崩`。

    默认那一串参数里带着 `--docs`／`--refs`／`--target` 三个沙盒路径，不是随手加的：**这一把尺读
    三层、有两份名单**，少给一半它就去读仓库里那 150 份真件 —— 前一种后果 §2.72 记过（沙盒里那篇
    三行的假文档被真文档的引用判成一堆断链，`G1` 那种「该退 0」的格子全红）；本节添的是后一种：
    `--target` 不给，默认值就是仓库里的 `计划书.md`，于是每一格都在偷偷问「今天仓库里有没有
    `### 2.1`」，那已经不是判据的回归测试了。这一条由 `targetless` 在跑之前闸住。
    """
    d = build_cell(cell, base, {})
    argv = list(cell.argv) or [a.replace(SANDBOX, str(d)) for a in DEFAULT_CELL_ARGV]
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
    miss = [s for s in cell.has if s not in text]
    if miss:
        return "bad", f"该印却没印：{miss}", text
    hits = [s for s in cell.lacks if s in text]
    if hits:
        return "bad", f"不该印却印了：{hits}", text
    return "ok", "", text


def self_test() -> int:
    """`--self-test`：往临时目录里种一批已知形状的文档，逐格对**跑之前**写死的期望。

    过的一格一行流水、不符期望的连自己那一遍的原文一起摊到最后 —— 与 §2.56~2.65 那八档同形，
    理由也同形：`selfcheck.run_script()` 失败时只摊末尾 14 行。

    退码：0 = 每格符合；1 = 有格子不符（逐格点名）；2 = 一格都没跑起来，或靶子先不对
    （格子写歪、`--refs` 那类参数把沙盒占位符写成花括号）。
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
    holes = unresolvable(BASELINE, {})
    if holes:
        print("基线要点名却点不到的键（这一把尺不读表，出现这一句就是格子写歪了）："
              + "、".join(holes))
        return 2
    leaky = targetless(BASELINE)
    if leaky:
        print("有格子把引用层的靶子留给了仓库里那一篇，改的是基线、不是判据：\n  "
              + "\n  ".join(leaky))
        return 2
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    with tempfile.TemporaryDirectory(prefix="doc_headings-selftest-") as td:
        base = Path(td)
        for cell in BASELINE:
            verdict, why, text = run_cell(cell, base)
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
          + (" —— 那把尺判得对" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
