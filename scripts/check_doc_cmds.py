#!/usr/bin/env python3
"""文档里写下来的命令行与脚本名 —— 还能不能照抄。只跑 `--help`，不做任何实测、不写任何产物。

    .venv/bin/python scripts/check_doc_cmds.py            # 扫默认那两份文档
    .venv/bin/python scripts/check_doc_cmds.py --verbose  # 连每条命令的判定一起打印
    .venv/bin/python scripts/check_doc_cmds.py --self-test  # 往临时文件里种已知好坏的文档，问它自己

为什么值得有这样一个东西：这个项目的失效模式里有一条是「文档说 A、代码做 B」
（计划书 2.19 收口补的三件小事就是为了堵它）。而**能照抄执行的命令行**是文档里最容易漂的一层：
改一个 flag 名，用例照样全绿、报告照样能出，只有照着文档敲命令的人会撞在 `unrecognized arguments` 上。
2026-09-22 加 `--replay` 之后这条尤其现实 —— 计划书 §14 和接入文档里各有一份命令清单，
往后每加一个开关都要跟着改两处，人总会漏。

它查四层：
  * 完整层（2.54）—— 这一行**是不是一条能照抄的完整命令**：代码块里行尾的 `\\` 按 shell 的
    规矩跟下一行接起来，接不上（后面是空行 / 文末 / 版式 / 另一条命令 / 一句中文）或者引号
    少一边，就单独点名并判错，**不拿半截去问 `--help`**；
  * 命令层 —— 长参数（`--xxx`）在不在 `--help` 里、那个脚本 / 子命令还存在吗；
  * 引用层 —— 正文里出现的 `scripts/xxx.py` 名字（哪怕在句子里、不在命令块里）到底有没有这个文件；
  * 钟那一层（2.45）—— 这一条命令**今天**照抄会不会撞在「那份记录太旧」那道闸上。
    只读 `probe.json` 的时间戳 + 履历，不发请求、不写任何东西；判决用的是
    `src.cli.replay_gate()` 本身（和屏幕上那句同一个函数）。

完整层排在最前面是有原因的：没有它，后面两层量的是**半条**命令。2.53 收尾时量到一条
断成两行的写法（`--try-reach` 那条）：第一层看不见第二行的参数名，钟那一层更妙 ——
`--replay` 是 `nargs="?"`，那个孤零零的 `\\` 被 argparse 当成了记录路径，于是屏幕上印出
「那把闸要读的记录 /仓库/\\ 不在，猜不了」，听起来像「记录丢了」，其实是命令断了。
**总结句当时照样是「142 条、0 条对不上；该查的都查了」。**

例外的写法：一段文字想拿**错的**命令当例子（2.21 讲那个「打错子命令也退 0」的坑时就得写出
`src.cli bulid`），用 `<!-- check-doc-cmds: off -->` / `on` 把那段圈起来 —— 渲染出来看不见，
总结行也会写明有几段被圈掉了，不让这个口子悄悄吞掉整篇文档。

但这个口子本身要配对：`off` 忘了关、或者**只是正文里把这对标记原样抄了一遍**（2.40 就是写文档时
抄出来的，那一下把后面 24 条命令全圈走了，总结句还是「0 条对不上；该查的都查了」），
由 `skip_imbalance` 当场判错。段数写在括号里是不够的 —— 会去核对分母的人本来就少。

位置参数、参数的取值对不对，它不管 —— 那类漂移要靠用例，不靠这把尺。
唯一碰取值的是钟那一层：它只问「这行里的 `--replay` 今天读得到一份能用的记录吗」，
而且答案是从 argparse 和 `replay_gate()` 那里要的，不是自己算小时数。
完整层（2.54）也是**按行**看的，不是 shell 词法器：`a && b` 那种一行两条命令、嵌套引号
（`"it's"`）、引号里再放中文顿号，它都只当一条命令处理 —— 它会漏，但它不误伤。

退码：**0** = 扫到的每一条都没问题；**1** = 有对不上的（命令、脚本名、off/on 没配上、
或者**不像一条完整的命令**的那几行）；
**2** = **一条都没扫到、并且三层里没有任何一层点得出名字**
（2.32 补的那一格：文档被清空、文件名给错、版式改了让正则落空，三种都是这把尺自己瞎了，
不能让「扫了 0 条、0 条对不上」冒充「查过了、没问题」。
2.54 给「断掉的命令」开了第一条例外，2.57 把剩下两条补上：`off` 没关、散文里点了
一个不存在的脚本名 —— 那两种 0 都是**文档的错**，屏幕上明明印着 ✗，退 2 会把
「尺找到了东西」说成「尺没找到东西」，13:34 逐格量到的现状就是这个。
**2.62 补的是读的那一层**：点名的文档不在、指的是目录、里面不是 UTF-8 —— 以前这三件事
是一整段 traceback（19:12:58 第一次复现、19:38:55 逐种复现：`并不存在的文档.md`／`docs`／
一个 `.pyc` 分别摊出 14／14／12 行，三种都崩在 `main()` 那句裸 `read_text` 上），
既不是判定也没有退码可言 —— 而那个退码是 **1**，正好是「量到了、有毛病」那一档。
现在三种各有自己那句话（借
`doc_num.read_doc`，与数尺／报数尺同一族，第三种说法都不另写），并且**部分读到 = 退 1**
（那一篇文档整个不在分母里）、**一篇都没读到 = 退 2**。
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from baseline_guard import sep_names            # noqa: E402  顿号那道闸的判据（三把尺共用）
# 2.62：「读进来」那一层不另写一套 —— 三种说法和那张「什么都不是」的字节流都从数尺那边拿
# （`unmarked_nums` 与 `code_claims` 早就是它的邻居了，同一件事不许有两个算法）。
from doc_num import BIN_BODY, read_doc          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# 「会自己过期的命令」那一层要复用 `src.cli` 里的 `build_parser()` / `replay_gate()`
# （见 `clock_inputs` 的说明：同一件事不许有两个算法），所以这里得能 import 到 src。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:      # 为了 import `baseline_guard`（2.58 那道共用的闸）
    sys.path.insert(0, str(ROOT / "scripts"))

# `.venv/bin/python` 与 Windows 那台的 `.venv/Scripts/python.exe` 都算。
# 注意 `(?:bin|Scripts)/` 那个斜杠：写成 `Scripts/` 而漏掉 bin 的，会只匹配到 Windows 那一行。
PY = r"(?:\./)?\.venv/(?:bin|Scripts)/[Pp]ython(?:\.exe)?"
# 一条命令 = python 之后紧跟 `-m src.cli <子命令> …` 或 `scripts/<名字>.py …`
CMD = re.compile(rf"{PY}\s+(?P<body>(?:-m\s+\S+\s+\S+\s*)?[\w./-]+\.py\b.*|scripts/\S+)")
SCRIPT = re.compile(r"[\w./-]+\.py\b")
# 正文里的脚本引用（不带路径前缀那段单独抓，句子中间的 `scripts/epg_check.py` 也算）
SCRIPT_REF = re.compile(r"scripts/([A-Za-z0-9_-]+)\.py")
# §9 那种花括号写法：`scripts/{serve_lan,probe_pack}.py` —— 一行提到八支脚本，
# 不展开的话它们全都算「没提过」，这把尺会自己造出三个假警报。
SCRIPT_BRACE = re.compile(r"scripts/\{([^}]*)\}\.py")
LONG_FLAG = re.compile(r"--[a-z][a-z0-9-]*")

# 解释器自己的参数。`-X utf8` 是本仓库文档里的标准跑法（Windows 控制台默认 GBK），
# 但它必须**在判断「这是不是我们的命令」之前**剥掉：以前不剥，
# `-X utf8 scripts/x.py` 走到 `body.startswith("scripts/")` 那一句就落空了 ——
# 命令被静悄悄跳过、不报错也不计入总数（2.23 写验收表时撞上：整张表 5 条命令一条都没查）。
OPT = re.compile(r"^(?:-X\s+\S+|-[BuOY]\w*)\s+")

# 例子段落：讲一个 bug 的时候必须把**错的**命令和**不存在的**脚本名写出来，
# 一把尺不认「这一段是例句」的话，它会把自己文档里的例句报成漂移（2.21 当天就撞了 7 个）。
# 用 HTML 注释标区间，渲染出来看不见，也不用另发明一种行内语法。
SKIP_OFF = "<!-- check-doc-cmds: off -->"
SKIP_ON = "<!-- check-doc-cmds: on -->"

DEFAULT_DOCS = ["计划书.md", "docs/电视订阅接入.md", "docs/真机验收单.md"]

# 2.54 那一层要用的三样：行尾的续行反斜杠、代码块的围栏、以及「这一截里有中文吗」。
CONT = re.compile(r"\\\s*$")
FENCE = "```"
CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")


def fence_flags(lines: list[str]) -> list[bool]:
    """每一行**在不在** ``` 围栏里（围栏那两行自己算 False）。

    为什么要在意这个：只有代码块里的行尾反斜杠才是 shell 的续行。正文里一句话以 `\\` 收尾
    多半是排版（markdown 拿它当硬换行），把它接下行的中文并进命令，量出来的是一条世界上
    不存在的命令 —— 那比不查更糟。**行内**那些用反引号包的命令一律算「不在围栏里」。

    >>> fence_flags(["a", "```", "x", "```", "b"])
    [False, False, True, False, False]
    >>> fence_flags(["```", "x", "``` ", "y", "```"])       # 收口带空格也认
    [False, True, False, False, False]
    """
    out: list[bool] = []
    on = False
    for line in lines:
        if line.lstrip().startswith(FENCE):
            on = not on
            out.append(False)
            continue
        out.append(on)
    return out


def quote_flaw(body: str) -> str:
    """引号有没有少一边；没有就说空串。

    为什么单独判：参数名对不对是「能不能跑起来」的事，引号没闭合是**这条命令不会执行** ——
    照抄的人按回车，终端只会给他一个 `>`。那一行以前一路通过，还留在那儿当「该查的都查了」。

    走法不是「数奇偶」：`--note "it's 对"` 里的单引号只有一个，数奇偶会把它报成没闭合
    （那是**误伤**，而误伤的代价是以后没人信这把尺）。所以按 shell 的规矩走一遍：
    `\\X` 整对跳过、进了哪种引号就只认那一种的收尾。反引号（命令替换）不管 —— 量过，
    仓库那三份文档的命令里没有反引号套反引号的写法。

    >>> quote_flaw("scripts/x.py --note 你好")
    ''
    >>> quote_flaw('scripts/x.py --note "没关')
    '双引号少了一边（照抄进终端，这条命令不会执行，它只会给你一个 `>`）'
    >>> quote_flaw("scripts/x.py --note '没关")
    '单引号少了一边（照抄进终端，这条命令不会执行，它只会给你一个 `>`）'
    >>> B = chr(92)                                    # 反斜杠本身：不写进转义汤
    >>> quote_flaw('scripts/x.py --note "a' + B + '"b"')      # 被挡住的那个不算收尾
    ''
    >>> quote_flaw('scripts/x.py --note "a' + B + '"')        # 剩下这个才是真没关
    '双引号少了一边（照抄进终端，这条命令不会执行，它只会给你一个 `>`）'
    >>> quote_flaw('scripts/x.py --note "it\\'s 对"')          # 双引号里的单引号：不误伤
    ''
    >>> quote_flaw('scripts/x.py --a "一" --b \\'二\\'')        # 两种各自成对：平
    ''
    """
    NAME = {'"': "双", "'": "单"}
    open_q = ""
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":                      # 转义：连它后面那个字符一起跳过
            i += 2
            continue
        if open_q:
            if ch == open_q:
                open_q = ""
        elif ch in NAME:
            open_q = ch
        i += 1
    return f"{NAME[open_q]}引号少了一边（照抄进终端，这条命令不会执行，它只会给你一个 `>`）" \
        if open_q else ""


def join_cont(lines: list[str], i: int, body: str, *, fenced: bool) -> tuple[str, str]:
    """把写在几行上的一条命令接成一整截：返回 `(接好的命令, 毛病)`，毛病空串＝接得完整。

    `i` 是**原文行下标**（0 起），`body` 是那一行已经剥好的那截。规则照 shell：
    行尾一个 `\\` 表示下一行还是这条命令。接不上就是文档的错，得点名，不能让那条命令
    安静地留在统计里 —— 2.53 收尾时量到「尺没拦一条断成两行的命令」，这一层就是为它加的。

    五种接不上，各说各的：不在代码块里 / 后面是空行 / 后面是文件末尾 / 后面是版式
    （围栏收口、那对 off/on 标记）/ 后面紧跟另一条命令。最后一种额外说：
    续行那一句里有中文 —— 那不是参数，是把说明文字写进了命令里。

    >>> B = chr(92)                                    # 反斜杠本身：不写进转义汤
    >>> tail = "a --replay " + B
    >>> join_cont([tail, "  --out /tmp/x"], 0, tail, fenced=True)
    ('a --replay --out /tmp/x', '')
    >>> join_cont([tail, "  --out /tmp/x", "  --no-epg"], 0, tail, fenced=True)
    ('a --replay --out /tmp/x', '')
    >>> join_cont([tail, "  --out /tmp/x " + B, "  --no-epg"], 0, tail, fenced=True)
    ('a --replay --out /tmp/x --no-epg', '')
    >>> join_cont([tail, "  --no-epg " + B], 0, tail, fenced=True)
    ('a --replay --no-epg', '行尾的反斜杠后面是文件末尾，没有下一行可接')
    >>> join_cont([tail, ""], 0, tail, fenced=True)
    ('a --replay', '行尾的反斜杠后面是一个空行')
    >>> join_cont([tail, "```"], 0, tail, fenced=True)
    ('a --replay', '行尾的反斜杠后面是「```」，那是版式不是命令')
    >>> join_cont([tail, ".venv/bin/python scripts/y.py"], 0, tail, fenced=True)
    ('a --replay', '行尾的反斜杠后面紧跟的是另一条命令（少了一个换行？）')
    >>> join_cont([tail, "这一轮一个请求都不发"], 0, tail, fenced=True)
    ('a --replay', '续行那一句里有中文：那不是参数，是把说明文字写进了命令里')
    >>> join_cont(["跑 " + tail, "后面这句是正文"], 0, tail, fenced=False)
    ('a --replay', '它在代码块外面，行尾的反斜杠不算续行（那是排版，不是命令）')
    >>> join_cont(["a --out /tmp/x"], 0, "a --out /tmp/x", fenced=True)   # 没有反斜杠：原样
    ('a --out /tmp/x', '')
    """
    if not CONT.search(lines[i]):
        return body, ""
    parts = [CONT.sub("", body).rstrip()]
    if not fenced:
        return " ".join(parts), "它在代码块外面，行尾的反斜杠不算续行（那是排版，不是命令）"
    j = i + 1
    while True:
        if j >= len(lines):
            return " ".join(parts), "行尾的反斜杠后面是文件末尾，没有下一行可接"
        nxt = re.split(r"\s#", lines[j], maxsplit=1)[0].strip()
        if not nxt:
            return " ".join(parts), "行尾的反斜杠后面是一个空行"
        if nxt.startswith(FENCE):
            return " ".join(parts), f"行尾的反斜杠后面是「{FENCE}」，那是版式不是命令"
        if SKIP_OFF in nxt or SKIP_ON in nxt:
            return " ".join(parts), "行尾的反斜杠后面是那对 check-doc-cmds 标记"
        if re.search(PY, nxt):
            return " ".join(parts), "行尾的反斜杠后面紧跟的是另一条命令（少了一个换行？）"
        piece = CONT.sub("", nxt).rstrip()
        if CJK.search(piece):
            return " ".join(parts), "续行那一句里有中文：那不是参数，是把说明文字写进了命令里"
        parts.append(piece)
        if not CONT.search(nxt):
            return " ".join(parts), ""
        j += 1


def read_commands(text: str) -> list[tuple[int, str, str]]:
    """文档里的命令 [(起始行, 接成一整截的命令, 毛病)]；毛病空串＝这像一条完整的命令。

    「查之前先问这条是不是一个完整的命令」是 2.54 加的一层。它管的正是那一种**两边都不报错**
    的失效：一条命令断在行尾，尺拿半截去问 `--help`，参数名照旧对得上，而真正的漂移写在
    第二行上、这一层以前看不见；更糟的是那半截还会把 `\\` 当成某个参数的取值
    （`--replay \\` 里 argparse 老实收下了那个反斜杠，钟那一层于是报
    「要读的记录 /仓库/\\ 不在」——听起来像「记录丢了」，其实是命令断了）。

    >>> B = chr(92)                                    # 反斜杠本身：不写进转义汤
    >>> doc = ("```\\n.venv/bin/python -m src.cli build --replay " + B + "\\n"
    ...        "  --out /tmp/x\\n```\\n")
    >>> read_commands(doc)
    [(2, '-m src.cli build --replay --out /tmp/x', '')]
    >>> read_commands("```\\n.venv/bin/python -m src.cli build --replay " + B + "\\n\\n```")
    [(2, '-m src.cli build --replay', '行尾的反斜杠后面是一个空行')]
    >>> read_commands(".venv/bin/python scripts/x.py --note '没关")[0][2]
    '单引号少了一边（照抄进终端，这条命令不会执行，它只会给你一个 `>`）'
    >>> read_commands("跑 `.venv/bin/python scripts/x.py --list` 就行")
    [(1, 'scripts/x.py --list', '')]
    """
    lines = text.splitlines()
    fence = fence_flags(lines)
    out = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        # 只切「空格 + #」那种行尾注释：URL 里的 `a#b` 不该被咬掉
        code = re.split(r"\s#", line, maxsplit=1)[0]
        hit = re.search(rf"{PY}\s+(?P<body>.*)", code)
        if not hit:
            continue
        body = hit.group("body").strip()
        # 先剥解释器参数，再判断这是不是我们那两类命令（见 OPT 那段说明）
        while (lead := OPT.match(body)):
            body = body[lead.end():].strip()
        if not (body.startswith("-m ") or body.startswith("scripts/") or "./" in body[:9]):
            continue
        # 反引号 / 中文标点包着的行内命令：截到脚本名或子命令那段为止
        if "`" in body:
            body = body.split("`")[0].strip()
        m = CMD.search(body)
        body = (m.group("body") if m else body).strip()
        body, flaw = join_cont(lines, i, body, fenced=fence[i])
        out.append((i + 1, body.strip(), flaw or quote_flaw(body)))
    return out


def commands_in(text: str) -> list[tuple[int, str]]:
    """文档正文里的命令行 [(行号, python 之后那截)]。

    行内注释要先切掉：``# 说明`` 里再出现一条命令、或者干脆提到另一个 flag 是常事
    （「# 同上，但把结论写回履历（--to-history）」这种写法会把 not-flag 当成 not-there）。
    整行是注释的（注释掉的那条命令）同样不算数。
    反过来，中文行文里用反引号包起来的命令也要收 —— 它是给人照抄的。

    2.54 起它是 `read_commands()` 的一层薄壳（把「毛病」那一截剥掉），**断掉的命令也在里面**：
    它被 `unrecognized()` 用来判断「这行写了 python 却没认成」，而一条断掉的命令是**认成了**、
    只是不完整 —— 那件事由 `✗ …这条不像一条完整的命令` 那一行去说，比塞进「没认出来」更准。

    >>> cmds = commands_in("跑这个：\\n.venv/bin/python scripts/x.py --out /tmp/a   # 注释\\n")
    >>> cmds
    [(2, 'scripts/x.py --out /tmp/a')]
    >>> commands_in("重新生成跑 `.venv/bin/python scripts/probe_pack.py`，它会在终端打印")
    [(1, 'scripts/probe_pack.py')]
    >>> commands_in(".venv/bin/python -m src.cli build --replay --out /tmp/rep   # 沿用记录")
    [(1, '-m src.cli build --replay --out /tmp/rep')]
    >>> commands_in("# .venv/bin/python -m src.cli build --gone-flag")   # 注释掉的命令不查
    []
    >>> commands_in("uv pip install -r requirements.txt")      # 不是本工具的命令，不收
    []
    >>> commands_in(".venv/bin/python -X utf8 scripts/x.py --out /tmp/a")
    [(1, 'scripts/x.py --out /tmp/a')]
    >>> commands_in(".venv/bin/python -X utf8 -m src.cli build --verify")
    [(1, '-m src.cli build --verify')]
    >>> commands_in(".venv/bin/python -u scripts/x.py")        # 单个字母的开关也剥
    [(1, 'scripts/x.py')]
    >>> commands_in("```\\n.venv/bin/python scripts/x.py \\\\\\n  --out /tmp/a\\n```")
    [(2, 'scripts/x.py --out /tmp/a')]
    """
    return [(no, body) for no, body, _ in read_commands(text)]



def unrecognized(text: str) -> list[tuple[int, str]]:
    """写了 `.venv/bin/python` 却没被 `commands_in()` 认出来的行 —— 让「跳过」这件事可数。

    为什么非加不可：2.23 那一节的验收表里写了 5 条命令，跑这把尺却仍报「33 条、0 漂」——
    因为当时它不认解释器参数 `-X utf8`，那 5 条整条被跳过。
    跳过的东西不会报错，只会让「0 漂」这句话慢慢变成假话。**「没查到错」和「没查」是两件事**，
    从今天起这把尺不许把它们混起来。

    >>> unrecognized("跑这个：.venv/bin/python -X utf8 scripts/x.py --out /tmp/a")
    []
    >>> unrecognized("跑这个：.venv/bin/python -m src.cli build --replay")
    []
    >>> for no, why in unrecognized("解释器在 .venv/bin/python 那儿"):
    ...     print(no, why)
    1 解释器在 .venv/bin/python 那儿
    >>> unrecognized("# .venv/bin/python --version")        # 注释行不管
    []
    """
    got = {no for no, _ in commands_in(text)}
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#") or no in got or not re.search(PY, line):
            continue
        out.append((no, re.split(r"\s#", line, maxsplit=1)[0].strip()[:72]))
    return out


def targets(body: str) -> list[str] | None:
    """把一截命令翻译成「该问谁的 --help」；认不出目标就返回 None（跳过，不算错）。

    >>> targets("-m src.cli build --replay")
    ['-m', 'src.cli', 'build']
    >>> targets("scripts/epg_check.py --playlist /tmp/a --against /tmp/b")
    ['scripts/epg_check.py']
    >>> targets("scripts/x.py`，")                       # 行内命令的尾巴已经截干净
    ['scripts/x.py']
    """
    toks = body.split()
    if not toks:
        return None
    if toks[0] == "-m" and len(toks) >= 3:
        return ["-m", toks[1], toks[2]]
    m = SCRIPT.match(toks[0])
    return [m.group(0)] if m else None


def subcommands(src_text: str) -> set[str]:
    """一个手动分发 argv 的入口模块里，真正认得的子命令名。

    为什么要单独问这一层：`src.cli` 没用 argparse 的 subparser，子命令是自己分发 argv 的。
    今天之前它连「拼错的子命令」都当「人想看帮助」处理 —— 打印用法、退 0（计划书 2.21 里
    拿一份故意写错的文档试出来就是这么漏的，那一条现在改成了退 2）。
    就算改过，这一层也不靠那个退出码活着：它直接读 `def cmd_*`，管的是「文档写的子命令存不存在」。

    >>> sorted(subcommands("def cmd_build(a):\\n\\ndef cmd_lean(b):"))
    ['build', 'lean']
    >>> subcommands("import argparse\\nap = argparse.ArgumentParser()\\n")   # 没有 cmd_*：规则不适用
    set()
    """
    return set(re.findall(r"^def cmd_(\w+)\(", src_text, re.M))


def strip_skipped(text: str) -> str:
    """把 `SKIP_OFF`/`SKIP_ON` 之间那些行挖成空行（行号原样保留，报告里的位置还是准的）。

    没有配对的 `on` 就挖到文末 —— 这是**挖内容**那一半的宽容：漏写收尾标记不该凭空造出一堆
    「脚本不存在」的假错。但漏写本身必须单独判错，见 `skip_imbalance`（2.40：写 2.39 那节时把
    这对标记**原样抄进正文当说明**，于是从那一行起到文末的 24 条命令一条都没查，退码照旧 0）。

    >>> strip_skipped("a\\n" + "<!-- check-doc-cmds: off -->" + "\\nscripts/gone.py\\n"
    ...               + "<!-- check-doc-cmds: on -->" + "\\nb\\n").splitlines()
    ['a', '', '', '', 'b']
    >>> commands_in(strip_skipped("x\\n<!-- check-doc-cmds: off -->\\n"
    ...                           ".venv/bin/python -m src.cli bulid\\n"))
    []
    """
    keep, on = [], True
    for line in text.splitlines():
        if SKIP_OFF in line:
            on = False
            keep.append("")
            continue
        if SKIP_ON in line:
            on = True
            keep.append("")
            continue
        keep.append(line if on else "")
    return "\n".join(keep)


def skip_imbalance(text: str) -> list[tuple[int, str, int]]:
    """off / on 没配上的地方：[(行号, 说法, 被这块吞掉的命令条数)]，按行号排。

    为什么「没配上」要**单独判错**，而不是像以前那样只在总结里报个段数：一个多出来的
    `off`（最典型就是像 2.40 那样把它当词儿抄进正文）会让那行往后所有命令都不进统计，
    而总结句照旧是「0 条对不上；该查的都查了」。**分母缩水这件事，一句括号里的段数挡不住** ——
    数一数才知道少了 24 条的人，和没数的人，看到的都是同一句绿。

    认三种：到文末都没关、一个 `off` 还没关就被下一个 `off` 顶掉（该改的是**前一个**，
    所以行号报前一个，别把人引到那个来收尾的标记上）、先出现 `on`（那行白写，
    说明有一段本来想圈的结果圈反了）。每种都算出这一段里被吞掉的命令条数。

    >>> skip_imbalance("a\\n<!-- check-doc-cmds: off -->\\nx\\n<!-- check-doc-cmds: on -->\\nb")
    []
    >>> skip_imbalance("x\\n<!-- check-doc-cmds: off -->\\n"
    ...                ".venv/bin/python -m src.cli build --replay\\n")
    [(2, 'off 到文末都没关', 1)]
    >>> skip_imbalance("<!-- check-doc-cmds: on -->\\nx")
    [(1, 'on 之前没有 off（这段是圈反了还是多写的？）', 0)]
    >>> skip_imbalance("<!-- check-doc-cmds: off -->\\n.venv/bin/python scripts/x.py\\n"
    ...                "<!-- check-doc-cmds: off -->\\n.venv/bin/python scripts/y.py\\n"
    ...                "<!-- check-doc-cmds: on -->")
    [(1, '这行的 off 没关，被第 3 行的 off 顶掉', 1)]
    """
    lines = text.splitlines()
    open_at: int | None = None
    out: list[tuple[int, str, int]] = []

    def inside(a: int, b: int) -> int:
        """第 a 行到第 b 行之间（含两端之外）还有几条命令 —— 报的是「这一段白扫了」。"""
        return len(commands_in("\n".join(lines[a:b - 1])))

    for no, line in enumerate(lines, 1):
        if SKIP_OFF in line:
            if open_at is not None:
                out.append((open_at, f"这行的 off 没关，被第 {no} 行的 off 顶掉",
                            inside(open_at, no)))
            open_at = no
        elif SKIP_ON in line:
            if open_at is None:
                out.append((no, "on 之前没有 off（这段是圈反了还是多写的？）", 0))
            else:
                open_at = None
    if open_at is not None:
        out.append((open_at, "off 到文末都没关", inside(open_at, len(lines) + 1)))
    return sorted(out)


def script_refs(text: str) -> set[str]:
    """整篇文档里提到过的脚本名（句子中间的也算，不限于命令块；花括号写法展开）。

    >>> sorted(script_refs("跑 `scripts/a.py`，另见 scripts/b.py 那一节"))
    ['a.py', 'b.py']
    >>> script_refs("重新生成 scripts/probe-pack.py")   # 连字符写的：照抄会 FileNotFound
    {'probe-pack.py'}
    >>> sorted(script_refs("另有 scripts/{serve_lan,probe_pack}.py"))
    ['probe_pack.py', 'serve_lan.py']
    """
    refs = {f"{n}.py" for n in SCRIPT_REF.findall(text)}
    for group in SCRIPT_BRACE.findall(text):
        refs |= {f"{n.strip()}.py" for n in group.split(",") if n.strip()}
    return refs


def dead_refs(refs: set[str], present: set[str]) -> list[str]:
    """文档写了、但 `scripts/` 里根本没这个文件的名字。

    这是今天真差一点就写进去的那类错：`--replay` 那条 discussion 里把新工具打成了
    `scripts/probe-pack.py`（文件叫 `probe_pack.py`）。命令层的检查抓不到它 ——
    它出现在句子里的时候根本不是一条命令。

    >>> dead_refs({"probe_pack.py", "gone.py"}, {"probe_pack.py", "run_doctests.py"})
    ['gone.py']
    >>> dead_refs({"probe-pack.py"}, {"probe_pack.py"})
    ['probe-pack.py']
    """
    return sorted(refs - present)


def undocumented(present: set[str], refs: set[str], *, skip: tuple = ("_",)) -> list[str]:
    """`scripts/` 里存着、但扫到的这些文档一个字没提的脚本。

    只提醒、不算错：一次性验证脚本可以只活在计划书某一节的命令里；
    但**从没进过任何文档**的脚本半年后没人知道它是干什么的，那是白写的信号。
    下划线开头的（`__init__.py`）直接跳过。

    >>> undocumented({"a.py", "b.py", "__init__.py"}, {"a.py"})
    ['b.py']
    >>> undocumented({"a.py"}, {"a.py", "gone.py"})
    []
    """
    return sorted(n for n in present - refs if not n.startswith(skip))


def importable(dotted: str) -> bool:
    """这个点名的模块解释器找不找得到 —— 用来分清「stdlib/第三方」和「仓库里改名了」。

    为什么要有这一条：`-m` 那一支以前在模块文件不存在时把源码读成空串，
    于是「既没有 cmd_* 也没有 argparse」成立，直接 return ""（= 没问题）。
    结果是**把 `src/cli.py` 改名，文档里那十几条 `-m src.cli …` 会全绿**，
    而它们照抄进终端是一条都跑不了的。这一层不跑真命令，只把「根本不存在」这件事报出来。

    >>> importable("http.server")     # 标准库里的：算找得到
    True
    >>> importable("src.goneone")     # 父包在、子模块不在
    False
    >>> importable("no.such.pkg.deep")  # 连父包都没有，find_spec 会抛，不许它抛穿
    False
    """
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 第三层：会自己过期的命令
# ---------------------------------------------------------------------------

def clock_inputs(body: str, *, root: Path = ROOT) -> dict | None:
    """这条命令带不带「那份记录能有多旧」那个钟；带着的话它读哪份记录、上限几小时。

    不带的（包括不带 `--replay` 的 build、别的脚本、以及 argparse 直接拒掉的坏行）返回 None。
    解析走 `src.cli.build_parser()` —— 这是它存在的一个理由：`--replay` 是 `nargs="?"`，
    `--replay --out /tmp/x` 里 `--out` **不是**记录路径，正则看不懂这一条。

    >>> from pathlib import Path
    >>> c = clock_inputs("-m src.cli build --replay --out /tmp/x")
    >>> c["record"] == str(ROOT / "data/output/probe.json"), c["budget"], c["force"]
    (True, 48, False)
    >>> c = clock_inputs("-m src.cli build --replay data/output/untrusted/probe.json --out /tmp/x",
    ...                  root=Path("/repo"))
    >>> c["record"], c["budget"]
    ('/repo/data/output/untrusted/probe.json', 48)
    >>> clock_inputs("-m src.cli build --replay --replay-max-age 6 --out /tmp/x")["budget"]
    6
    >>> clock_inputs("-m src.cli build --replay --allow-untrusted")["force"]
    True
    >>> clock_inputs("-m src.cli build --verify --replay")["contradiction"]
    True
    >>> clock_inputs("-m src.cli build --out /tmp/x") is None            # 没带 --replay：没这个钟
    True
    >>> clock_inputs("scripts/epg_check.py --replay") is None            # 不是 build：不归它管
    True
    >>> clock_inputs("-m src.cli build --replay --no-such-flag") is None  # argparse 自己拒的，上层报
    True
    """
    tg = targets(body)
    if tg is None or tg[:3] != ["-m", "src.cli", "build"] or "--replay" not in body:
        return None
    try:
        from src.cli import build_parser
    except ImportError:
        return None
    try:
        args = build_parser().parse_args(body.split()[3:])
    except SystemExit:          # 参数本身就不合法：那由「参数名在不在」那一层报，这里不插手
        return None
    if args.verify and args.replay:
        # build 在碰任何东西之前就退 1；它跟「记录多旧」是两件事，分开说清楚。
        return {"record": "", "budget": args.replay_max_age, "force": False,
                "history": str(args.history), "contradiction": True}
    rec = Path(args.replay)
    return {
        "record": str(rec if rec.is_absolute() else root / rec),
        "budget": args.replay_max_age,
        "force": bool(args.allow_untrusted),
        "history": str(args.history),
        "contradiction": False,
    }


def prose_clocks(text: str) -> list[int]:
    """散文里提到 `build --replay`、但没写成一条能照抄的命令 —— 行号列表。

    为什么单独数：上面那一层的入口是「这行有 `.venv/bin/python` 前缀」，
    而 `docs/真机验收单.md:90` 那种是一个**步骤**里的散文（「跑一次 `build --replay` 就有」）。
    钟对它一样在走，判决却量不到 —— 不说出来，「带钟的 20 条」就成了一个看着很齐的分母。
    这一层只数，不判：散文里没有完整的参数，猜哪份记录、几小时上限都是编。

    >>> prose_clocks("跑一次 `build --replay` 就有（计划书 2.23）")
    [1]
    >>> prose_clocks(".venv/bin/python -m src.cli build --replay --out /tmp/x")   # 那是命令，不算散文
    []
    >>> prose_clocks("`build --replay --no-epg` 也行")
    [1]
    """
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        if "build --replay" not in line and "`--replay`" not in line:
            continue
        if re.search(PY, line):
            continue                    # 带解释器前缀的走命令那一层，这里只数散文
        if line.lstrip().startswith("#"):
            continue                    # 注释掉的那条命令是「谁都没让它跑」，不算照抄入口
        out.append(no)
    return out


def clock_verdict(cfg: dict, *, now: str, root: Path = ROOT) -> tuple[str, str]:
    """照抄这条命令今天会怎样：`(类别, 一句话)`。类别 ∈ `过` / `退` / `问不出`。

    判决用的是 `src.cli.replay_gate()` 本身 —— build 屏幕上那句就是它印的，
    这把尺不复述规则，所以两边不会各说一套（计划书 2.44 治的就是「两个读法」）。
    时间从外面传进来（`now`）、记录从 `root` 下面找 —— 这两个都不许在函数里现取，
    否则这一格的用例明天自己就红了。

    >>> cfg = {"record": "probe.json", "budget": 48, "force": False,
    ...        "history": "", "contradiction": False}
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     root = Path(d)
    ...     _ = (root / "probe.json").write_text(
    ...         '{"at": "2026-09-21T21:18:13+08:00", "egress": "1.2.3.4 CN",'
    ...         ' "measurement_warnings": [], "lines": {"http://a/1": {"ok": true}}}',
    ...         encoding="utf-8")
    ...     print(clock_verdict(cfg, now="2026-09-22T08:00:00+08:00", root=root))
    ...     print(clock_verdict({**cfg, "budget": 6}, now="2026-09-22T08:00:00+08:00", root=root))
    ...     print(clock_verdict({**cfg, "force": True}, now="2026-09-24T08:00:00+08:00", root=root))
    ...     print(clock_verdict({**cfg, "record": "gone.json"},
    ...                         now="2026-09-22T08:00:00+08:00", root=root)[1].rsplit("/", 1)[-1])
    ...     print(clock_verdict({**cfg, "contradiction": True},
    ...                         now="2026-09-22T08:00:00+08:00", root=root)[0])
    ...     # 记录上没写出口、也没报警：那种命令只有真跑才会去问「当前出口」（要发请求），
    ...     # 这把尺一个字都不发，所以它报「问不出」而不是拿空出口去比出一道门。
    ...     _ = (root / "noeg.json").write_text(
    ...         '{"at": "2026-09-21T21:18:13+08:00", "lines": {"http://a/1": {"ok": true}}}',
    ...         encoding="utf-8")
    ...     print(clock_verdict({**cfg, "record": "noeg.json"},
    ...                         now="2026-09-22T08:00:00+08:00", root=root)[0])
    ...     # 同一份记录，但那一轮报过警：参照出口走履历（本地文件，不发请求），所以照样判得出来
    ...     _ = (root / "warn.json").write_text(
    ...         '{"at": "2026-09-21T21:18:13+08:00", "measurement_warnings": ["TUN 已开启"],'
    ...         ' "lines": {"http://a/1": {"ok": true}}}', encoding="utf-8")
    ...     print(clock_verdict({**cfg, "record": "warn.json"},
    ...                         now="2026-09-22T08:00:00+08:00", root=root))
    ...     _ = (root / "bad.json").write_text("不是 JSON", encoding="utf-8")
    ...     print(clock_verdict({**cfg, "record": "bad.json"},
    ...                         now="2026-09-22T08:00:00+08:00", root=root))
    ('过', '那份记录 1 条判决、上限 48 小时，今天能过')
    ('退', '那份记录已经 11 小时了（上限 6）——沿用太久表会冻在旧世界上，跑一轮 --verify 吧')
    ('过', '它加了 `--allow-untrusted`：三道门全越过（1 条判决），不算量过钟')
    gone.json 不在，猜不了
    退
    问不出
    ('退', '那一轮（21:18）体检报过警，它判死的线路多半是假阴性（2.16）：TUN 已开启')
    ('问不出', '那份记录读不了：Expecting value: line 1 column 1 (char 0)')
    """
    if cfg.get("contradiction"):
        return "退", "先撞 `--verify` 与 `--replay` 只能选一个那句拒绝（跟钟无关）"
    from src.cli import judgment_egress, load_probe, replay_gate
    from src.check import history as hist

    path = Path(cfg["record"])
    path = path if path.is_absolute() else root / path
    if not path.exists():
        return "问不出", f"那把闸要读的记录 {path} 不在，猜不了"
    try:
        replay, meta = load_probe(path)
    except (OSError, ValueError) as e:
        return "问不出", f"那份记录读不了：{str(e).splitlines()[0]}"
    warns = list(meta.get("warnings") or [])
    if not meta.get("egress") and not warns:
        # 记录自己没写出口时，build 拿的是「本机当前出口」—— 那是要发一次请求才知道的事，
        # 这把尺一个字都不该发（也更不该猜）。剩下那三种落点（有出口 / 有报警走履历）都不用网络。
        return "问不出", "那份记录没写出口，这一条要照抄才会去问当前出口 —— 我不猜"
    # `Path("")` 是「当前目录」，`.exists()` 为真 —— 履历没给路径时不去 open 一个目录。
    # 说清楚它守到什么程度：`hist.load_history()` 自己读到目录也只是返回 `[]`（量过），
    # 所以这一格换成 `exists()` 用例**不会红**（2.45 改错实验 N5：拆了仍 62 条全绿）。
    # 留着是因为「不拿目录当文件读」这件事该由这里说，而不是等下面那层替它兜。
    hpath = Path(cfg["history"]) if cfg["history"] else None
    runs = hist.load_history(hpath) if hpath is not None and hpath.is_file() else []
    point = judgment_egress(str(meta.get("egress") or ""), warns, runs, measured=True)
    ok, why = replay_gate(meta, point=point, now=now, max_age_hours=cfg["budget"],
                          force=cfg["force"], n_lines=len(replay))
    if cfg["force"]:
        return "过", f"它加了 `--allow-untrusted`：三道门全越过（{len(replay)} 条判决），不算量过钟"
    return ("过" if ok else "退"), (why or f"那份记录 {len(replay)} 条判决、上限 {cfg['budget']} 小时，今天能过")


def clock_summary(rows: list[tuple[str, int, tuple[str, str]]], *, prose: int = 0) -> tuple[str, list[str]]:
    """把带钟的命令收成「总结行里那一句 + 逐行明细」。没一条带钟 → `("", [])`（不印废话）。

    为什么只报不判错：**时间过了一点不是文档的错**。48 是那道闸的默认上限，到点就是到点；
    让这把尺每 48 小时红一次，它第二天就变成没人看的噪音了。但它必须**印在总结行上** ——
    2026-09-23 21:18 之后，文档里 20 条这样的命令照抄全退 1，而总结行是
    「140 条命令、0 条对不上；该查的都查了」，每个字都对，没有一句有用。

    总结行只放「几条 + 哪几种理由」（同一条理由不重复印），具体是哪几行进明细，`--verbose` 才印。

    **这句话里必须带着「照抄」两个字**：`scripts/selfcheck.py` 的 `conclusion()` 是从一屏输出的
    末尾往前找那批结论词，找到哪句印哪句。这一句是**另外一行**，不带那个词的话 selfcheck 里
    被印出来的永远只是上面那句「扫了 141 条…0 条对不上」—— 也就是把这一节的发现藏回原地。
    词写在 `head` 里而不是各分支里，是为了让这个不变量**结构上成立**（「问不出」那一档第一版
    就没有「照抄」），下面那格循环就是钉这件事的。

    >>> clock_summary([])
    ('', [])
    >>> clock_summary([], prose=2)[0]
    '没一条写成可照抄的命令，但另有 2 处散文里写着 `build --replay` —— 那个钟对它们一样在走，只是量不到判决'
    >>> clock_summary([("docs/a.md", 3, ("过", "能过"))], prose=1)[0]
    '带着「记录能有多旧」那个钟、能照抄来量的 1 条：全能过；另有 1 处散文里写着 `build --replay`（量不到判决）'
    >>> clause, detail = clock_summary([
    ...     ("docs/a.md", 3, ("退", "那份记录已经 49 小时了（上限 48）")),
    ...     ("docs/a.md", 9, ("过", "那份记录 350 条判决、上限 72 小时，今天能过"))])
    >>> clause
    '带着「记录能有多旧」那个钟、能照抄来量的 2 条：1 条会退 1（那份记录已经 49 小时了 ×1）、1 条能过'
    >>> detail
    ['    会退 1：docs/a.md:3 ← 那份记录已经 49 小时了（上限 48）']
    >>> clock_summary([("docs/a.md", 3, ("过", "能过")), ("docs/b.md", 9, ("过", "能过"))])[0]
    '带着「记录能有多旧」那个钟、能照抄来量的 2 条：全能过'
    >>> clock_summary([("docs/a.md", 3, ("问不出", "那份记录不在，猜不了"))])[0]
    '带着「记录能有多旧」那个钟、能照抄来量的 1 条：1 条问不出（那份记录不在，猜不了 ×1）'
    >>> clock_summary([("a.md", 1, ("退", "那份记录已经 49 小时了（上限 48）")),
    ...                ("b.md", 2, ("退", "那份记录已经 49 小时了（上限 6）")),
    ...                ("c.md", 3, ("退", "那份记录已经 49 小时了（上限 1）"))])[0]
    '带着「记录能有多旧」那个钟、能照抄来量的 3 条：3 条会退 1（那份记录已经 49 小时了 ×3）'
    >>> clock_summary([("a.md", 1, ("退", '那一轮（19:22）体检报过警，它判死的线路多半是假阴性（2.16）：'
    ...                                     '本机 DNS 被虚拟网卡接管（fake-IP 段 198.18.0.0/15）：a → 198.18.0.51'))])[0]
    '带着「记录能有多旧」那个钟、能照抄来量的 1 条：1 条会退 1（那一轮（19:22）体检报过警，它判死的线路多半是假阴性（2.16） ×1）'
    >>> all("照抄" in clock_summary(r, prose=p)[0] for r, p in (          # selfcheck 靠这个词找它
    ...     ([(("a.md", 1, ("退", "…")))], 0), ([(("a.md", 1, ("过", "…")))], 0),
    ...     ([(("a.md", 1, ("问不出", "…")))], 0), ([], 3)))
    True
    """
    more = (f"；另有 {prose} 处散文里写着 `build --replay`（量不到判决）" if rows and prose else
            "" if not prose else
            f"没一条写成可照抄的命令，但另有 {prose} 处散文里写着 `build --replay` "
            "—— 那个钟对它们一样在走，只是量不到判决")
    if not rows:
        return more, []
    bad = [(d, n, w) for d, n, (k, w) in rows if k == "退"]
    ask = [(d, n, w) for d, n, (k, w) in rows if k == "问不出"]
    good = [r for r in rows if r[2][0] == "过"]
    head = f"带着「记录能有多旧」那个钟、能照抄来量的 {len(rows)} 条："
    detail = [f"    {label}：{d}:{n} ← {w}" for label, group in
              (("会退 1", bad), ("问不出", ask)) for d, n, w in group]
    if not bad and not ask:
        return head + "全能过" + more, detail
    def gist(w: str) -> str:
        """总结行里那条理由只留「哪一类」：破折号后面是补救建议、冒号后面是逐台明细、
        「上限」那个数每条命令可以不一样 —— 三种都挤进总结行就没人读得完。全句在 `--verbose`。"""
        return re.sub(r"（上限 \d+）", "", w.split("——")[0].split("：")[0]).strip()

    def by_kind(group):
        seen: dict[str, int] = {}
        for _, _, w in group:
            seen[gist(w)] = seen.get(gist(w), 0) + 1
        return "、".join(f"{g} ×{c}" for g, c in seen.items())

    bits = []
    if bad:
        bits.append(f"{len(bad)} 条会退 1（{by_kind(bad)}）")
    if ask:
        bits.append(f"{len(ask)} 条问不出（{by_kind(ask)}）")
    if good:
        bits.append(f"{len(good)} 条能过")
    return head + "、".join(bits) + more, detail


def check_one(target: list[str], body: str, *, verbose: bool = False) -> str:
    """一条命令的结论：空串＝没问题，否则说清哪儿不对。

    三种「不算错」的情况要写明，否则这把尺会自己制造恐慌：

      * 目标脚本根本没写 argparse（`run_doctests.py` 就是）—— 它不认 `--help`，
        但文档里那行照抄是能跑的，所以不能报「参数不存在」；
      * `--help` 都跑不出来（脚本被删了 / 子命令写错）—— 这个**是真错**；
      * 只查长参数，短参数与取值不管。

    >>> check_one(["scripts/nope.py"], "scripts/nope.py --x")     # 文件不存在：真错
    '找不到 scripts/nope.py（脚本被删了还是文档写错了？）'
    """
    base = [sys.executable] + (["-m"] + target[1:] if target[0] == "-m" else [target[0]])
    if target[0] == "-m":
        mod = ROOT / (target[1].replace(".", "/") + ".py")
        if not mod.exists() and not importable(target[1]):
            return (f"-m {target[1]} 这个模块仓库里没有、解释器也找不到"
                    "（改了名？文档没跟着改，这条照抄会直接报错）")
        text = mod.read_text(encoding="utf-8") if mod.exists() else ""
        names = subcommands(text)
        sub = target[2] if len(target) > 2 else ""
        if names and sub and sub not in names and sub.replace("-", "_") not in names:
            return (f"{target[1]} 没有「{sub}」这个子命令（只认 {'、'.join(sorted(names))}）"
                    "—— 它自己现在会退 2（2.21），这一层仍按 `def cmd_*` 判，两道闸各管各的")
        if not names and "argparse" not in text:
            if verbose:
                print(f"    （{target[1]} 既没有 cmd_* 也没有 argparse：无从判断）")
            return ""
    script = ROOT / target[0] if target[0] != "-m" else None
    if script is not None and not script.exists():
        return f"找不到 {target[0]}（脚本被删了还是文档写错了？）"
    if script is not None and "argparse" not in script.read_text(encoding="utf-8"):
        if verbose:
            print(f"    （{target[0]} 没有 argparse，不认 --help：只核对文件在不在）")
        return ""
    r = subprocess.run(base + ["--help"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    known = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return f"{target[0]} --help 跑不出来：{known.strip().splitlines()[-1] if known.strip() else '无输出'}"
    missing = [f for f in sorted(set(LONG_FLAG.findall(body))) if f not in known]
    if missing:
        return f"用到了 {target[-1]} 不认识的参数 {missing}"
    if verbose:
        print("    ok")
    return ""


# ---------------------------------------------------------------------------
# 回归基线：往临时文件里种已知好坏的文档，问这把尺自己说了什么
# ---------------------------------------------------------------------------
#
# 为什么要有这一档（2.57，做法是从 2.56 原样递过来的）：它今天报「扫了 143 条命令、
# 13 个脚本名：0 条命令、0 个脚本名对不上」，那句和 2.56 里「扫了 792 个名字、0 个拦得住」
# 是同一族的话 —— 至少有三种读法：仓库真干净、这篇文档压根没被扫（退 2 拦着，看得见）、
# 或者**判据整层不咬**（`LONG_FLAG` 少写一个横杠、`dead_refs` 的减号反了、`is_blind` 恒真）。
# 第三种在屏幕上和前一种长得一模一样。分辨的办法只有一个：喂它已知坏掉的文档，
# 看它点不点名。这一档就是这个「喂」，并且它跑在仓库里、随 `selfcheck` 一起跑。
#
# 期望是从 `/tmp/g257/probe_3.log`（09-24 13:34 那遍现状）**冻结**来的：先量它今天说什么、
# 再把它说过的话钉成期望。三格的期望被本节那次退码修改动过（`B9`、`B13`、`B15`），
# 各自的 `what` 里写明「改前实测退几」，不混在「它一直如此」里。

B = chr(92)          # 反斜杠本身：不写进转义汤（2.54 起的写法）

DOC = "假文档.md"     # 种出来的那份文档的名字（报告里的路径以它结尾）


class Cell(NamedTuple):
    """一格期望：种什么文档、该退几、必须说哪几句、不许说哪几句。"""

    who: str                                  # 格子名（沿用现状探针的编号）
    what: str                                 # 这一格在钉什么
    body: str = ""                            # 种进临时文件的文档正文（`{T}` = 临时目录本身）
    rec: str = ""                             # 额外种一份探针记录（带钟那一格要）
    bins: tuple[str, ...] = ()                # 额外种进去的**非 UTF-8** 件（只给名字，2.62 那格要）
    args: tuple[str, ...] = ()                # 非空 = 这一格自己带全套命令行（不再自动塞那份文档）
    rc: int = 0
    scanned: int | None = None                # 结论里那个「扫了 N 条命令」；None = 这一格不钉数
    refs: int | None = None                   # 「、M 个脚本名」那个分母
    has: tuple[str, ...] = ()                 # 必须出现（至少一次）
    once: tuple[str, ...] = ()                # 必须**恰好**出现一次
    lacks: tuple[str, ...] = ()               # 必须不出现


BASELINE: tuple[Cell, ...] = (
    # —— G 组：这些**不许**报错。它们钉的是分母，以及「三种不算错」到底算不算不算错 ——
    Cell("G1_代码块里一条合法命令", "对照格：它必须干净，后面所有「误伤」判断都拿它当基准",
         "# t\n\n```bash\n.venv/bin/python scripts/epg_check.py --playlist data/output/aptv.m3u\n```\n",
         rc=0, scanned=1, refs=1, has=("该查的都查了",), lacks=("✗", "不认识的参数")),
    Cell("G2_散文里反引号包着的命令", "行内命令也进分母（2.21 加的那一半），漏一条就少查一条",
         "# t\n\n跑 `.venv/bin/python scripts/doc_num.py` 就行\n",
         rc=0, scanned=1, lacks=("一条都没扫到",)),
    Cell("G3_旗标名对但取值不存在", "取值不管那一半：它不许插嘴说「目录不存在」",
         "# t\n\n```bash\n.venv/bin/python scripts/table_drift.py --against /tmp/nope-g257-dir\n```\n",
         rc=0, scanned=1, lacks=("不认识的参数",)),
    Cell("G4_整行注释掉的命令", "注释里的坏旗标不进统计 —— 那要进就是误伤",
         "# t\n\n```bash\n# .venv/bin/python -m src.cli bulid --no-such-flag\n```\n",
         rc=2, scanned=0, has=("这一轮一条都没扫到", "三种可能"),
         lacks=("没有「bulid」这个子命令", "不认识的参数")),
    Cell("G5_行尾注释里提到别的旗标", "「# 同上（--to-history）」那种写法不许被当成参数",
         "# t\n\n```bash\n.venv/bin/python scripts/epg_check.py --playlist data/output/aptv.m3u"
         "   # 同上（--to-history）\n```\n",
         rc=0, scanned=1, lacks=("--to-history",)),
    Cell("G6_URL 里就有 #", "切行尾注释只能切「空格 + #」：`a#b` 不是注释",
         "# t\n\n```bash\n.venv/bin/python scripts/epg_check.py --playlist https://x/a#b\n```\n",
         rc=0, scanned=1, lacks=("不认识的参数", "不像一条完整的命令")),
    Cell("G7_off/on 配平的例句", "2.40 那对逃生标记正常用时的样子：圈掉的不查，配上了不判错",
         "# t\n\n<!-- check-doc-cmds: off -->\n\n```bash\n.venv/bin/python scripts/nope_g257.py\n```\n\n"
         "<!-- check-doc-cmds: on -->\n\n```bash\n.venv/bin/python "
         "scripts/epg_check.py --playlist data/output/aptv.m3u\n```\n",
         rc=0, scanned=1, has=("另有 1 段标了 off 的例子没查",), lacks=("off/on 没配上",)),
    Cell("G8_短参不查", "只查长参数那一半：`-o` 报出来就是误伤",
         "# t\n\n```bash\n.venv/bin/python scripts/lean_playlist.py -o /tmp/x\n```\n",
         rc=0, scanned=1, lacks=("不认识的参数",)),
    Cell("G9_整篇被一对 off/on 圈光", "退 2 的**第四种**成因（2.57 之前那句提示只列三种）",
         "# t\n\n<!-- check-doc-cmds: off -->\n\n```bash\n.venv/bin/python "
         "scripts/epg_check.py --playlist data/output/aptv.m3u\n```\n\n"
         "<!-- check-doc-cmds: on -->\n",
         rc=2, scanned=0, has=("四种可能", "该扫的命令全被那对 off/on 圈掉了"),
         once=("四种可能",), lacks=("三种可能",)),
    Cell("G10_写了 python 却没认成命令", "那一层只印、不进退码也不进「瞎」：散文里正常提到解释器很常见",
         "# t\n\n```bash\n.venv/bin/python scripts/epg_check.py --playlist data/output/aptv.m3u\n```\n\n"
         "解释器在 .venv/bin/python 那儿。\n",
         rc=0, scanned=1, has=("还有 1 行写了 python 却没认成命令",), lacks=("✗",)),
    # —— B 组：已知坏掉的文档必须点名。这一组是这把尺的靶子，全绿不等于它咬得动 ——
    Cell("B1_长旗标不存在", "命令层最主的那条判据",
         "# t\n\n```bash\n.venv/bin/python scripts/stray_names.py --no-such-flag\n```\n",
         rc=1, scanned=1, has=("不认识的参数 ['--no-such-flag']",), once=("不认识的参数",)),
    Cell("B2_脚本不存在", "两层各报一次、数不许并成一个",
         "# t\n\n```bash\n.venv/bin/python scripts/nope_g257.py --out /tmp/x\n```\n",
         rc=1, scanned=1, refs=1, has=("找不到 scripts/nope_g257.py", "1 条命令、1 个脚本名对不上"),
         once=("文档里写了 scripts/nope_g257.py",)),
    Cell("B3_子命令拼错", "`src.cli` 自己分发 argv，这一层直接读 `def cmd_*`",
         "# t\n\n```bash\n.venv/bin/python -m src.cli bulid --replay\n```\n",
         rc=1, has=("没有「bulid」这个子命令",)),
    Cell("B4_模块整个不存在", "`-m` 那一支的另一半：改名要撞在这格上",
         "# t\n\n```bash\n.venv/bin/python -m src.nope_g257 build\n```\n",
         rc=1, has=("这个模块仓库里没有",)),
    Cell("B5_续行断在空行", "2.54 那一层：断掉的命令不许拿半截去问 --help，也不进分母",
         f"# t\n\n```bash\n.venv/bin/python -m src.cli build --replay {B}\n\n```\n",
         rc=1, scanned=0, has=("行尾的反斜杠后面是一个空行", "还有 1 条不像一条完整的命令"),
         lacks=("三种可能", "四种可能")),
    Cell("B6_续行那句是中文", "五种接不上的第四种：说明文字写进了命令里",
         f"# t\n\n```bash\n.venv/bin/python -m src.cli build --replay {B}\n这一轮一个请求都不发\n```\n",
         rc=1, scanned=0, has=("续行那一句里有中文",)),
    Cell("B7_续行紧跟另一条命令", "第五种：少了一个换行；而第二条**照样要被扫**（别把两个错并成一个）",
         f"# t\n\n```bash\n.venv/bin/python -m src.cli build --replay {B}\n"
         ".venv/bin/python scripts/doc_num.py\n```\n",
         rc=1, scanned=1, has=("紧跟的是另一条命令",)),
    Cell("B8_引号少一边", "它照抄进终端不会执行，只会给一个 `>`",
         '# t\n\n```bash\n.venv/bin/python scripts/epg_check.py --playlist "没关\n```\n',
         rc=1, scanned=0, has=("双引号少了一边",)),
    Cell("B9_off 没关", "分母那一半：一个没关的 off 把后面全挖空。**期望被 2.57 动过：改前实测退 2**",
         "# t\n\n<!-- check-doc-cmds: off -->\n\n```bash\n.venv/bin/python scripts/nope_g257.py\n```\n",
         rc=1, scanned=0, has=("off/on 没配上", "这一段里 1 条命令一条都没查",
                               "上面那个数是从少了命令的分母算的"),
         lacks=("三种可能", "四种可能")),
    Cell("B10_目标脚本没有 argparse", "三种「不算错」里的第一种：`run_doctests` 不认 --help，照抄却能跑",
         "# t\n\n```bash\n.venv/bin/python scripts/run_doctests.py --no-such-flag\n```\n",
         rc=0, scanned=1, lacks=("不认识的参数",)),
    Cell("B11_带钟且越过三道门", "钟那一层要进末句，而末句必须带 `照抄` 那个词（2.45）；判决不进退码",
         "# t\n\n```bash\n.venv/bin/python -m src.cli build --replay {T}/probe.json --allow-untrusted\n```\n",
         rec=('{"at": "2026-09-21T21:18:13+08:00", "egress": "1.2.3.4 CN",'
              ' "measurement_warnings": [], "lines": {"http://a/1": {"ok": true}}}'),
         rc=0, scanned=1, refs=0, has=("能照抄来量的 1 条", "全能过"), lacks=("✗",)),
    Cell("B12_一篇只有散文", "2.32 那一格：什么都没扫到要退 2，而且那几种可能得写出来",
         "# t\n\n这一段里一条命令都没有，只讲道理。\n",
         rc=2, scanned=0, refs=0, has=("这一轮一条都没扫到", "三种可能")),
    Cell("B13_散文里一个不存在的脚本名", "引用层单独在场。**期望被 2.57 动过：改前实测退 2 + 那句「三种可能」**",
         "# t\n\n这支脚本叫 `scripts/nope_g257.py`，改配置时记得跑它。\n",
         rc=1, scanned=0, refs=1, has=("文档里写了 scripts/nope_g257.py", "1 个脚本名对不上",
                                       "但引用层点名了 1 个对不上的脚本名"),
         lacks=("上面那些 0 全是空的", "三种可能", "四种可能")),
    Cell("B14_两条断掉的命令", "群提示只印一次，条数要说清是几条（分母要说得出口）",
         f"# t\n\n```bash\n.venv/bin/python -m src.cli build --replay {B}\n\n"
         '.venv/bin/python scripts/epg_check.py --playlist "没关\n```\n',
         rc=1, scanned=0, has=("还有 2 条不像一条完整的命令",),
         once=("要么接成一行",)),
    Cell("B15_断命令＋没关的 off", "两种「分母被动过」叠在一起：off 先把那半截一起挖走，所以只点得出一个名",
         f"# t\n\n<!-- check-doc-cmds: off -->\n\n```bash\n.venv/bin/python -m src.cli build --replay {B}\n"
         "```\n",
         rc=1, scanned=0, has=("off/on 没配上", "这一段里 1 条命令一条都没查"),
         lacks=("三种可能", "四种可能", "这条不像一条完整的命令")),
    # —— 2.62：「读进来」那一层。三格各自钉一种读不到的原因，再加一格「读到了一篇、少了一篇」——
    # 这一组的靶子不是文档写错了，是**命令行给的东西**：它比上面任何一层都容易撞，因为那是手打的。
    # 改之前这三种都是整段 traceback（19:38:55 逐种复现：14／14／12 行，退码都是 1 ——
    # 跟「量到了、有毛病」同一档，而它什么都没量到），既没有判决也没有退码可言。
    Cell("B16_两篇里一篇不在", "读到了一篇就得把另一篇的账说出来：那一篇整个不在分母里，退 1",
         "# t\n\n```bash\n.venv/bin/python scripts/epg_check.py --playlist data/output/aptv.m3u\n```\n",
         args=("{T}/" + DOC, "{T}/并不存在.md"),
         rc=1, scanned=1, refs=1, has=("！没读到：<T>/并不存在.md —— 文件不在",
                               "另有 1 篇没读到（上面那些数只覆盖读到的 1 篇）"),
         lacks=("一篇都没读到", "该查的都查了", "三种可能", "四种可能", "Traceback")),
    Cell("B17_两篇都不在", "一篇都没读到 = 这把尺什么都没量到：退 2，跟「读到但没命令」同一档",
         args=("{T}/甲不在.md", "{T}/乙不在.md"),
         rc=2, has=("！没读到：<T>/甲不在.md —— 文件不在", "点名的 2 篇一篇都没读到"),
         lacks=("Traceback", "该查的都查了", "扫了 0 条命令", "三种可能")),
    Cell("B18_点名的是目录", "2.36 那一族的第二种读法：`IsADirectoryError` 不许再裸崩",
         args=("{T}",),
         rc=2, has=("那是个目录，不是文档", "点名的 1 篇一篇都没读到"),
         lacks=("Traceback", "IsADirectoryError", "文件不在")),
    Cell("B19_里面不是UTF-8", "同一族第三种：编码不是 UTF-8 —— 改名没用，所以那句话也不许写成「文件不在」",
         args=("{T}/坏件.bin",), bins=("坏件.bin",),
         rc=2, has=("读不出来：", "点名的 1 篇一篇都没读到"),
         lacks=("Traceback", "UnicodeDecodeError", "文件不在", "那是个目录")),
)


def hide_tmp(text: str, base: Path) -> str:
    """把临时目录名抹成 `<T>` 再印 —— 不然两遍输出必然不同（2.55 踩的第 7 条）。

    归一由**代码**做并且钉了用例，所以它不再是「比之前先跑一把 `sed`」那种手艺（2.56 同）。

    >>> from pathlib import Path
    >>> hide_tmp("✗ /var/folders/xx/T/g257_abcd/假文档.md:4 找不到\\n扫了 1 条命令",
    ...          Path("/var/folders/xx/T/g257_abcd"))
    '✗ <T>/假文档.md:4 找不到\\n扫了 1 条命令'
    >>> hide_tmp("没有路径", Path("/tmp/x"))
    '没有路径'
    """
    return text.replace(str(base), "<T>")


def check_cell(cell: Cell, rc: int, text: str) -> tuple[bool, str]:
    """这一格符合期望吗：`(符合, 不符的那句)`。四种不符分开报，因为**修法不一样**。

    顺序是定过的：退码第一（尺崩了或者判据错了，后面那些句子怎么都是白说），
    然后「少了那句」、「多说了那句」（一个是指据/处置提示没落地，一个是误伤），
    再「恰好一次」，最后才数分母 —— 分母那两个数（命令条数、脚本名条数）错了，
    通常意味着上面某层整层不咬，那是最贵的一种坏，所以放在最后单独钉。

    >>> c = Cell("T", "试", rc=1, scanned=1, refs=1,
    ...          has=("不认识的参数",), once=("文档里写了",), lacks=("该查的都查了",))
    >>> good = "✗ <T>/假文档.md:4 用到了不认识的参数 ['--x']\\n    文档里写了 a.py\\n扫了 1 条命令、1 个脚本名\\n"
    >>> check_cell(c, 1, good)
    (True, '')
    >>> check_cell(c, 0, good)
    (False, '退码：期望 1，实际 0')
    >>> check_cell(c, 1, good.replace("不认识的参数", "别的话"))
    (False, '少了那句：不认识的参数')
    >>> check_cell(c, 1, good + "该查的都查了\\n")
    (False, '多说了那句：该查的都查了 —— 误伤')
    >>> check_cell(c, 1, good + "文档里写了 b.py\\n")
    (False, '那句出现了 2 次，期望恰好 1 次：文档里写了')
    >>> check_cell(c, 1, good.replace("扫了 1 条命令", "扫了 9 条命令"))
    (False, '扫到的命令数：期望 1，实际那句不是')
    >>> check_cell(c, 1, good.replace("1 个脚本名", "9 个脚本名"))
    (False, '脚本名分母：期望 1，实际那句不是')
    """
    if rc != cell.rc:
        return False, f"退码：期望 {cell.rc}，实际 {rc}"
    for s in cell.has:
        if s not in text:
            return False, f"少了那句：{s}"
    for s in cell.lacks:
        if s in text:
            return False, f"多说了那句：{s} —— 误伤"
    for s in cell.once:
        if text.count(s) != 1:
            return False, f"那句出现了 {text.count(s)} 次，期望恰好 1 次：{s}"
    if cell.scanned is not None and f"扫了 {cell.scanned} 条命令" not in text:
        return False, f"扫到的命令数：期望 {cell.scanned}，实际那句不是"
    if cell.refs is not None and f"、{cell.refs} 个脚本名" not in text:
        return False, f"脚本名分母：期望 {cell.refs}，实际那句不是"
    return True, ""


def run_cell(cell: Cell, base: Path) -> tuple[str, str, str]:
    """跑一格：`(判定, 给人看的那句, 抹过临时路径的原文)`，判定是 `ok` / `bad`。

    走的是真的 `main()`（不是又一遍 `commands_in`）：退码、结论行、那句尾的 `tail`、
    那几句处置提示，全都是这一格要看的东西 —— 只调中间函数就把 `main()` 那三层绕开了。
    这一点和 2.56 一样有个副作用：`main()` 里那个 `now` 是每格重取的，
    所以钟那一格的判决跟着真时间走（`B11` 用 `--allow-untrusted` 绕开，见它的 `rec`）。

    2.62 起 `args` 的语义换了一次：从「往自动那份文档后面追加」改成「这一格自己带全套」
    （跟 `doc_num.run_cell` 里 `list(cell.argv) or […]` 同一形状）。理由是「点名的文档不在」
    那一格要的就是**一篇都读不开**的 argv：自动塞进去的那一份会把退码从 2 拉回 1，
    那一格于是比的是一件没发生过的事（2.59 的 `braced_cells` 拦的是同一种靶子）。
    改之前那些格没有一格设过 `args`，所以这一改对它们是零影响 —— 中立性两遍量在 §2.62。
    要拿种出来的那份文档当靶子，自己在 `args` 里写 `{T}/假文档.md`。
    """
    if cell.rec:
        (base / "probe.json").write_text(cell.rec, encoding="utf-8")
    doc = base / DOC
    doc.write_text(cell.body.replace("{T}", str(base)), encoding="utf-8")
    for name in cell.bins:                    # 「里面不是 UTF-8」那一格：那份件什么都不是
        (base / name).write_bytes(BIN_BODY)
    argv = [a.replace("{T}", str(base)) for a in cell.args] or [str(doc)]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
    except Exception as e:                        # 尺自己炸了算「跑过但不过」，不许吞
        return "bad", f"跑这一格时抛了 {type(e).__name__}: {e}", ""
    text = hide_tmp(buf.getvalue(), base)
    good, why = check_cell(cell, rc, text)
    return ("ok", "", text) if good else ("bad", why, text)


def sep_conflicts(cells: tuple[Cell, ...]) -> list[str]:
    """格子名里带了「、」的那些 —— 它们会让最后一行「不符的格」分不开。

    为什么要有这一格：那一行是 `、".join(...)` 出来的，分隔符就是顿号。13:47 那遍拆解实验
    被自己咬了一口：`B11_带钟、且越过三道门` 里那颗顿号一出现，读输出的脚本（和我）就把
    一格数成了两格，那一轮的「判错」三处里有一处是这件事。名字是我起的，闸也得我来装：
    现在带顿号的名字当场退 2，不再等到读的时候才发现分不开。

    2.58 把「什么算撞了分隔符」这条规矩挪进 `scripts/baseline_guard.py`（三把基线尺共用一份），
    这里只剩一层委托：格子名换成字符串，判据在那一边。

    >>> sep_conflicts((Cell("A_好", "x"), Cell("B、坏", "y"), Cell("C\\n坏", "z")))
    ['B、坏', 'C\\n坏']
    >>> sep_conflicts(BASELINE)          # 今天这 29 个名字都读得开
    []
    """
    return sep_names(c.who for c in cells)


def self_test(cells: tuple[Cell, ...] | None = None) -> int:
    """`--self-test` 那一档：每一格种一份临时文档、跑一遍这把尺、逐格对期望。

    结论行带着「扫了」那个词（`scripts/selfcheck.py` 的 `conclusion()` 靠它挑句子）。
    **顺序是定过的**：过的一格一行先流水，不符期望的那些**留在最后** ——
    `selfcheck.run_script()` 失败时只摊出末尾 14 行，把 ✗ 排在 29 行 ✓ 中间，
    那条 ✗ 到了人眼前就只剩一个「退 1」。

    退码：0 = 每格都符合期望；1 = 有格子不符（逐格点名）；2 = 一格都没跑起来。
    """
    cells = BASELINE if cells is None else cells
    knames = sep_conflicts(cells)
    if knames:
        print("格子名里不许有顿号或换行，那一行「不符的格」是靠顿号分的，分不开就等于没有："
              + "、".join(knames))
        return 2
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    for cell in cells:
        with tempfile.TemporaryDirectory(prefix="doc-cmds-selftest-") as td:
            verdict, why, text = run_cell(cell, Path(td))
        ran += 1
        if verdict == "bad":
            bad += 1
            fails.append((cell, why, text))
            continue
        print(f"  ✓ {cell.who:<26} {cell.what}")
    if fails:
        print(f"\n—— 以下 {len(fails)} 格不符期望（每格把自己那一遍的原文摊出来）——")
        for cell, why, text in fails:
            print(f"  ✗ {cell.who:<26} {cell.what}\n      {why}")
            for line in text.strip().splitlines():
                print(f"      | {line}")
    print(f"\n扫了基线 {len(cells)} 格：{bad} 格不符期望"
          + (" —— 那把尺还咬得动" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：`BASELINE` 是空的，或者临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


def is_blind(n: int, broken: list, loose: list, dead: list) -> bool:
    """这把尺**自己**瞎了吗 —— 「一条命令都没扫到」并且「三层里没有任何一层点得出名字」。

    为什么这一格要单独成一个函数：2.32 加退 2 时只想到了「文档被清空」那一族 0；
    2.54 给「断掉的命令」开了第一条例外（那种 0 是文档的错），而 `loose`（`off` 没关）与
    `dead`（散文里点出一个不存在的脚本名）是**同样形状**的两种例外，当时没补。
    13:34 逐格量到的现状：一篇只有「这支脚本叫 `scripts/nope_g257.py`」的文档，屏幕上印着
    「文档里写了 scripts/nope_g257.py，但 scripts/ 里没有这个文件」，退码却是 2，
    尾句还是「上面那些 0 全是空的」—— 而那句话旁边就站着一个 1。

    `miss`（写了 `.venv/bin/python` 却没认成命令）**不**算例外，正相反：那一句就是
    「版式改了让正则落空」的征兆本身，是这一档要抓的东西。它也不进退码（认不出来的
    可能是散文里正常提到解释器），两层各管各的。

    >>> is_blind(0, [], [], [])
    True
    >>> is_blind(0, ["一条断掉的命令"], [], [])        # 2.54 那条例外
    False
    >>> is_blind(0, [], ["off 没关"], [])              # 分母被挖空，但它自己报了
    False
    >>> is_blind(0, [], [], ["nope.py"])               # 引用层点名的（2.57 补的两条之一）
    False
    >>> is_blind(12, [], [], [])                       # 扫到了命令，谈不上瞎
    False
    """
    return not n and not broken and not loose and not dead


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="check_doc_cmds", description=__doc__.splitlines()[0])
    ap.add_argument("docs", nargs="*", default=None,
                    help=f"要扫的文档（默认 {'、'.join(DEFAULT_DOCS)}）")
    ap.add_argument("--verbose", action="store_true", help="每条命令的判定都打出来")
    ap.add_argument("--self-test", action="store_true", dest="self_test",
                    help=f"往临时文件里种已知好坏的 {len(BASELINE)} 格文档，逐格核对这把尺说了什么")
    args = ap.parse_args(argv)
    if args.self_test:
        # 这一档不读任何真文档，所以它排在 `paths` 之前；`docs` 参数一起给了也不生效（明说了）。
        return self_test()

    paths = [Path(d) for d in (args.docs or DEFAULT_DOCS)]
    n = bad = skipped = got = 0
    unread: list[tuple[str, str]] = []
    miss: list[tuple[str, int, str]] = []
    loose: list[tuple[str, int, str, int]] = []
    broken: list[tuple[str, int, str, str]] = []
    refs: set[str] = set()
    clocks: list[tuple[str, int, tuple[str, str]]] = []
    prose = 0
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for doc in paths:
        # 「读进来」这一道 2.62 才装上：以前这两行是一句裸 `read_text`，点名的文档不在、
        # 指的是目录、里面不是 UTF-8，三种都抛整段 traceback（19:12:58 复现）。判据不重写一份，
        # 借数尺的 `read_doc`；这里只加本尺自己的那半句：读不到的那一篇**整个不在分母里**，
        # 所以它跟 `loose`／`broken` 是同一类东西（都改分母），而不是「某条命令对不上」。
        raw, why = read_doc(ROOT / doc if not doc.is_absolute() else doc)
        if raw is None:
            unread.append((str(doc), why))
            print(f"！没读到：{doc} —— {why}", file=sys.stderr)
            continue
        got += 1
        skipped += raw.count(SKIP_OFF)
        loose += [(str(doc), no, why, hid) for no, why, hid in skip_imbalance(raw)]
        text = strip_skipped(raw)
        refs |= script_refs(text)
        prose += len(prose_clocks(text))
        miss += [(str(doc), no, why) for no, why in unrecognized(text)]
        for no, body, flaw in read_commands(text):
            # 最前面这一道：先问「这是不是一条完整的命令」，再问参数名。
            # 断掉的命令不许拿半截去问 `--help` —— 那样它会以「0 条对不上」的身份进统计，
            # 而真正写在第二行上的漂移一条都没查（2.53 收尾量到，本节修）。
            if flaw:
                broken.append((str(doc), no, body, flaw))
                continue
            tg = targets(body)
            if tg is None:
                continue
            n += 1
            why = check_one(tg, body, verbose=args.verbose)
            if why:
                bad += 1
                print(f"{doc}:{no} {why}\n    $ {body}")
            elif args.verbose:
                print(f"{doc}:{no}    $ {body}")
            # 第三层：这条命令带不带那个钟，带着的话今天照抄会怎样。
            # 放在 `why` 之后：参数名本身就不对的行由上面那句报，不重复。
            cfg = clock_inputs(body)
            if cfg is not None:
                verdict = clock_verdict(cfg, now=now)
                clocks.append((str(doc), no, verdict))
                if args.verbose:
                    print(f"    钟：{verdict[0]} — {verdict[1]}")

    # 引用层：这一层不看命令，只看「文档里提到的脚本文件在不在」。
    # 一个名字可能两层都报（命令里写错、句子里也写错），所以两层的数分开列、不合并成一句。
    scripts = {p.name for p in (ROOT / "scripts").glob("*.py")}
    dead = dead_refs(refs, scripts)
    for name in dead:
        print(f"文档里写了 scripts/{name}，但 scripts/ 里没有这个文件"
              "（打错了还是删了没改文档？）")
    # 这一层在最底下那句总结之外报，因为它改的是**分母**：一个没关的 off 会让上面的 `n`
    # 本身就少，「扫了 115 条、0 条对不上」那句越是干净越不能信。
    for doc, no, why, hid in loose:
        print(f"✗ {doc}:{no} off/on 没配上：{why}"
              + (f"，这一段里 {hid} 条命令一条都没查" if hid else ""))
    if loose:
        print("   补上收尾的 on；如果那只是正文里提了一句这个标记，把它写成不带 HTML 注释的样子"
              "（计划书 2.21 那节自己提到它时就是这么写的）")
    # 「不像一条完整的命令」也单独印、单独判错：它改的同样是分母（那几条压根没进 `n`），
    # 而且它是**文档**的错，不是出口的事 —— 修法只有两种：接成一行，或者用那对标记圈起来。
    for doc, no, body, flaw in broken:
        print(f"✗ {doc}:{no} 这条不像一条完整的命令：{flaw}\n    $ {body}")
    if broken:
        print("   要么接成一行（一把尺查的就是「照抄这一行会怎样」），要么把断掉的那半截写成别的样式；"
              "拿它当例句就用 check-doc-cmds 那对标记圈起来")
    if args.verbose:
        for name in undocumented(scripts, refs):
            print(f"    scripts/{name} 存着，但 {'、'.join(str(p) for p in paths)} 里没提过")
        for d, no, why in miss:
            print(f"    没认出来：{d}:{no}  {why}")
    # 「哪支脚本没进文档」只有把**全套**文档一起扫才有意义：单扫一份的话
    # 另外几份里提到过的一律会被误报成没人知道，那条提醒就成噪音了。
    hidden = undocumented(scripts, refs) if not args.docs else []
    # 一篇都没读到：这一档跟「读到了但里面没命令」不是一件事，得单独立一句、当场退 2。
    # 位置要紧 —— 它排在上面那三层**之后**、总结句之前：2.57 那条教训是「已经点名的东西
    # 不许被『尺没找到东西』盖掉」，这里能点名的都点完了，被跳过的只剩最后那两句
    # （总结句与「哪支脚本没进文档」）—— 而那两句在没有分母的情况下本来就是说谎。
    # `dead`/`loose`/`broken` 都在循环里填，所以「一篇都没读到」时它们必然全空，
    # 早退不会藏掉任何一条名字；`B16` 那几格把这个依赖钉住了。
    if unread and not got:
        print(f"点名的 {len(paths)} 篇一篇都没读到 —— 一条命令都没扫到，这一屏不是「文档没问题」。",
              file=sys.stderr)
        return 2
    # 顺序要紧：`loose` 排在 `miss` 前面 —— 一个没关的 off 会把后面的行全挖空，
    # 于是「写了 python 却没认成」那个数也跟着少，两个一起说只会把人引到小的那个上。
    # 最后那两分支是 2.57 分出来的：`dead` 非空时那句「上面那些 0 全是空的」是假话 ——
    # 13:34 量到的原话是「0 条命令、1 个脚本名对不上；这一轮一条都没扫到，上面那些 0 全是空的」，
    # 一句话里左边那个 1 当场推翻右边那句「全是空的」。
    # `unread` 排在最前面是 2.62 加的：它是这四种里最大的一个洞（整篇不在，而不是那几行没查），
    # 而且它排在 `loose` 之前不会撞 2.57 那条 —— 少一篇文档不会让「off 没配上」跟着少。
    tail = (f"；另有 {len(unread)} 篇没读到（上面那些数只覆盖读到的 {got} 篇）" if unread
            else "；有 off/on 没配上，上面那个数是从少了命令的分母算的" if loose
            else f"；还有 {len(broken)} 条不像一条完整的命令（上面逐条点名了），那几条没查" if broken
            else f"；还有 {len(miss)} 行写了 python 却没认成命令，一条都没查 —— 见 --verbose" if miss
            else "；该查的都查了" if n
            else "；这一轮一条都没扫到，上面那些 0 全是空的" if not dead
            else f"；命令层一条都没扫到（那两个 0 是空的），但引用层点名了 {len(dead)} 个对不上的脚本名")
    # 「哪些名字对得上」之外，还要说「哪些今天照抄跑不动」—— 后者是会不会自己过期决定的，
    # 所以它排在最后。但**光是最后一行不够**：`selfcheck.conclusion()` 是从末尾往前找
    # `CONCLUSION` 那批词的，这一句里必须带着其中一个词（「照抄」），否则 selfcheck 里
    # 被印出来的还是上面那句「0 条对不上」，这一层的发现当场被藏回去（2.45 量出来的，
    # 两边各钉了一格用例，改错实验 N11/N12 一边拆一头）。
    clause, cdetail = clock_summary(clocks, prose=prose)
    if args.verbose:
        for line in cdetail:
            print(line)
    print(f"\n扫了 {n} 条命令、{len(refs)} 个脚本名：{bad} 条命令、{len(dead)} 个脚本名对不上"
          + (f"（另有 {skipped} 段标了 off 的例子没查）" if skipped else "")
          + tail + (f"\n{clause}" if clause else ""))
    if hidden:
        print("（只提醒，没算进上面那个数）这几支脚本这些文档里没提过："
              + "、".join(f"scripts/{x}" for x in hidden))
    # 「一条命令都没扫到」不能算过：那要么文档被清空了、要么给的文件名不对、
    # 要么版式改了让正则全落空 —— 三种都是这把尺自己瞎了，不是文档没问题。
    # 另外几把尺早就有这一格（selfcheck 的 2、doc_num 的 2），2.32 把它补到这条上。
    # 2.54 给它开第一条例外、2.57 把剩下两条补齐（见 `is_blind`）：**上面已经逐条点名了
    # 东西，就不许再说「尺没找到东西」**。那句提示也跟着分两种：`off/on` 圈掉整篇时
    # 那是第四种成因，不写出来人就只会去翻前三种。
    if is_blind(n, broken, loose, dead):
        print("（" + ("四" if skipped else "三") + "种可能：文档被清空了、`docs` 参数给错了、"
              "版式改了让 `commands_in` 全落空"
              + ("、该扫的命令全被那对 off/on 圈掉了" if skipped else "")
              + " —— 加 --verbose 看一眼是哪种）")
        return 2
    # 走到这里 `unread` 只可能是「读到了一些、少了几篇」那一种（全没读到在上面就退 2 了），
    # 判 1 的理由跟 `loose`／`broken` 完全同形：上面每一个数都少算了一篇文档。
    return 1 if (bad or dead or loose or broken or unread) else 0


if __name__ == "__main__":
    sys.exit(main())
