#!/usr/bin/env python3
"""文档里写下来的命令行与脚本名 —— 还能不能照抄。只跑 `--help`，不做任何实测、不写任何产物。

    .venv/bin/python scripts/check_doc_cmds.py            # 扫默认那两份文档
    .venv/bin/python scripts/check_doc_cmds.py --verbose  # 连每条命令的判定一起打印

为什么值得有这样一个东西：这个项目的失效模式里有一条是「文档说 A、代码做 B」
（计划书 2.19 收口补的三件小事就是为了堵它）。而**能照抄执行的命令行**是文档里最容易漂的一层：
改一个 flag 名，用例照样全绿、报告照样能出，只有照着文档敲命令的人会撞在 `unrecognized arguments` 上。
2026-09-22 加 `--replay` 之后这条尤其现实 —— 计划书 §14 和接入文档里各有一份命令清单，
往后每加一个开关都要跟着改两处，人总会漏。

它查三层：
  * 命令层 —— 长参数（`--xxx`）在不在 `--help` 里、那个脚本 / 子命令还存在吗；
  * 引用层 —— 正文里出现的 `scripts/xxx.py` 名字（哪怕在句子里、不在命令块里）到底有没有这个文件；
  * 钟那一层（2.45）—— 这一条命令**今天**照抄会不会撞在「那份记录太旧」那道闸上。
    只读 `probe.json` 的时间戳 + 履历，不发请求、不写任何东西；判决用的是
    `src.cli.replay_gate()` 本身（和屏幕上那句同一个函数）。

例外的写法：一段文字想拿**错的**命令当例子（2.21 讲那个「打错子命令也退 0」的坑时就得写出
`src.cli bulid`），用 `<!-- check-doc-cmds: off -->` / `on` 把那段圈起来 —— 渲染出来看不见，
总结行也会写明有几段被圈掉了，不让这个口子悄悄吞掉整篇文档。

但这个口子本身要配对：`off` 忘了关、或者**只是正文里把这对标记原样抄了一遍**（2.40 就是写文档时
抄出来的，那一下把后面 24 条命令全圈走了，总结句还是「0 条对不上；该查的都查了」），
由 `skip_imbalance` 当场判错。段数写在括号里是不够的 —— 会去核对分母的人本来就少。

位置参数、参数的取值对不对，它不管 —— 那类漂移要靠用例，不靠这把尺。
唯一碰取值的是钟那一层：它只问「这行里的 `--replay` 今天读得到一份能用的记录吗」，
而且答案是从 argparse 和 `replay_gate()` 那里要的，不是自己算小时数。

退码：**0** = 扫到的每一条都没问题；**1** = 有对不上的（命令、脚本名、或 off/on 没配上）；
**2** = **一条都没扫到**
（2.32 补的那一格：文档被清空、文件名给错、版式改了让正则落空，三种都是这把尺自己瞎了，
不能让「扫了 0 条、0 条对不上」冒充「查过了、没问题」）。
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 「会自己过期的命令」那一层要复用 `src.cli` 里的 `build_parser()` / `replay_gate()`
# （见 `clock_inputs` 的说明：同一件事不许有两个算法），所以这里得能 import 到 src。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def commands_in(text: str) -> list[tuple[int, str]]:
    """文档正文里的命令行 [(行号, python 之后那截)]。

    行内注释要先切掉：``# 说明`` 里再出现一条命令、或者干脆提到另一个 flag 是常事
    （「# 同上，但把结论写回履历（--to-history）」这种写法会把 not-flag 当成 not-there）。
    整行是注释的（注释掉的那条命令）同样不算数。
    反过来，中文行文里用反引号包起来的命令也要收 —— 它是给人照抄的。

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
    """
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        code = line.lstrip()
        if code.startswith("#"):
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
        out.append((no, (m.group("body") if m else body).strip()))
    return out


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="check_doc_cmds", description=__doc__.splitlines()[0])
    ap.add_argument("docs", nargs="*", default=None,
                    help=f"要扫的文档（默认 {'、'.join(DEFAULT_DOCS)}）")
    ap.add_argument("--verbose", action="store_true", help="每条命令的判定都打出来")
    args = ap.parse_args(argv)

    paths = [Path(d) for d in (args.docs or DEFAULT_DOCS)]
    n = bad = skipped = 0
    miss: list[tuple[str, int, str]] = []
    loose: list[tuple[str, int, str, int]] = []
    refs: set[str] = set()
    clocks: list[tuple[str, int, tuple[str, str]]] = []
    prose = 0
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for doc in paths:
        raw = (ROOT / doc).read_text(encoding="utf-8") if not doc.is_absolute() \
            else doc.read_text(encoding="utf-8")
        skipped += raw.count(SKIP_OFF)
        loose += [(str(doc), no, why, hid) for no, why, hid in skip_imbalance(raw)]
        text = strip_skipped(raw)
        refs |= script_refs(text)
        prose += len(prose_clocks(text))
        miss += [(str(doc), no, why) for no, why in unrecognized(text)]
        for no, body in commands_in(text):
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
    if args.verbose:
        for name in undocumented(scripts, refs):
            print(f"    scripts/{name} 存着，但 {'、'.join(str(p) for p in paths)} 里没提过")
        for d, no, why in miss:
            print(f"    没认出来：{d}:{no}  {why}")
    # 「哪支脚本没进文档」只有把**全套**文档一起扫才有意义：单扫一份的话
    # 另外几份里提到过的一律会被误报成没人知道，那条提醒就成噪音了。
    hidden = undocumented(scripts, refs) if not args.docs else []
    # 顺序要紧：`loose` 排在 `miss` 前面 —— 一个没关的 off 会把后面的行全挖空，
    # 于是「写了 python 却没认成」那个数也跟着少，两个一起说只会把人引到小的那个上。
    tail = ("；有 off/on 没配上，上面那个数是从少了命令的分母算的" if loose
            else f"；还有 {len(miss)} 行写了 python 却没认成命令，一条都没查 —— 见 --verbose" if miss
            else "；该查的都查了" if n else "；这一轮一条都没扫到，上面那些 0 全是空的")
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
    if not n:
        print("（三种可能：文档被清空了、`docs` 参数给错了、版式改了让 `commands_in` 全落空 —— "
              "加 --verbose 看一眼是哪种）")
        return 2
    return 1 if (bad or dead or loose) else 0


if __name__ == "__main__":
    sys.exit(main())
