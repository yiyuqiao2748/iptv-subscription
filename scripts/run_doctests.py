"""跑全项目的 doctest。

这个项目不另设 tests/ 目录，逻辑的样例都写在函数自己的 docstring 里
（`classify`、`latency_tier`、`build` 这些最容易写错的排序/判定函数靠它兜住）。

为什么单独一个脚本：`python -m doctest 文件名` 会漏掉带 `import src.xxx` 的模块，
而 `python -m doctest -v` 之类的手工命令我在这个项目里跑错过一次 ——
遍历写歪了，收集到 **0 个用例**，输出照样一片绿。所以这里把「一个用例都没收到」
直接判成失败；同理，`src/` 下混进「不是合法模块名」的文件（同步盘的冲突副本）也判失败，
见 `strays`。

    .venv/bin/python scripts/run_doctests.py          # 全部
    .venv/bin/python scripts/run_doctests.py prober   # 只跑名字里含 prober 的文件
    .venv/bin/python scripts/run_doctests.py --each   # 每件起一个子进程，真跑它自己的那一份
    .venv/bin/python scripts/run_doctests.py --doctest  # 只跑本件这一份用例
    .venv/bin/python scripts/run_doctests.py --self-test  # 往沙盒里种假件，量 `--each` 这条跑法
    .venv/bin/python scripts/run_doctests.py --each --root=/tmp/那棵树 --timeout=2

2.68 起这里还多管一件事：**别的脚本自己那条 `--doctest` 支路怎么说结果**。那些支路以前
一律写成 `raise SystemExit(doctest.testmod(verbose=False).failed)` —— 量到 31 条也好、
一条都没量到也好，屏幕上都是 0 字节，而「一条都没量到」还照样退 0。
`run_own` 就是那一支的正确写法（`own_line` 是它要说的那句话）。放在这里而不是各写一份，
理由和 2.58 把「顿号闸」挪进 `baseline_guard` 一样：口径只有一份，下一把尺不必再抄一遍注释。

2.69 再把这条支路往外推一步：`doctest_gate` 是「认得这面旗」的那一道门，一件脚本只要在
收尾处问它一句，`--doctest` 就答自己的用例数，而不是把旗当成一个路径、一个子命令、
或者一份 argparse 的「未识别的参数」。跑全量那一遍会在末尾印整棵树的形状
（`survey_routes`），而「挂了号却没人应答」那种件由 `dead_flag_doors` 静态拦一道。

2.70 量的是这一句的**反面**：静态认出来的「走通」到底跑不跑得起来。`--each` 那一档
为每一件起一个子进程、把它那一串参数原样递过去（只递 `--doctest`），再核对三件事：
它答没答（那一句「合计」）、答的数跟静态那把 `example_count` 对不对得上、它报的
「量的件」是不是它自己。每一件都挂在 `scripts/work_guard.py` 底下跑，于是
「递 `--doctest` 给它会不会顺便去干自己的活」也成了一个读数而不是一段担心 ——
那一族最坏的形状（§2.68 的 `M16`：字还在、路已死）由 `each_verdict` 点名。

2.74 量的是这一档**自己的**那一句：`--each` 屏幕上那十几句话（「字还在、路已死」
「它去干了自己的活」「那把尺判错了」……）今天一句都没有实例 —— 仓库里此刻没有一件那样歪的 .py，
而「今天没有实例」与「判据整层不响」在同一屏上长得一模一样（§2.71 那笔账，这次轮到
收集器自己欠）。所以 `--self-test` 那一档往临时目录里种假件、真起子进程、一格钉一句，
再配一道预跑闸 `coverage_gaps`：一句判决没人钉了就红在**跑之前**（退 2、一句都没跑），
而不是等到某一天那一句判决没字了才发现。这道闸量的是**句子**不是**格子**：一句被两格同时
钉着的格子，删掉它不响（09-25 14:42 逐格删了一遍现数，一半响一半不响 —— 那个数不写在散文里，
由 `gate_blindness` 算给屏幕；格子少没少另有 `claims` 拿 `selfcheck.py:steps` 那句话钉）。
同一节把「册上共几件」那份写了三遍的账收成一遍
（见 `each_file` 与 `survey_routes` 各自那条用例），并给 `--each` 添了 `--root=`／`--timeout=`
两旗 —— 没有这两旗，「换一棵树来量」与「一件不返回」那两格就只能停在说明书里。
"""

from __future__ import annotations

import ast
import contextlib
import doctest
import importlib
import io
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 在册范围：「哪几级目录里的 .py 算这一本册子」。写一份而不是五处，理由是 2.58 那条
# （同一份规矩两个人各写一遍，迟早漂）—— 这一位以前在四个函数的默认值里各抄一次，
# 而 `--each` 与 `survey_routes` 必须用**同一棵**树，否则静态普查跟实跑普查数的是两堆件。
DEFAULT_DIRS: tuple[pathlib.Path, ...] = (ROOT / "scripts", ROOT / "src")

# `--each` 那一档里一件的天花板。为什么要有：递 `--doctest` 给一件「会起监听」的脚本，
# 最坏的读法不是它报错，是它**不返回** —— 那一遍整屏就停在那一行上，
# 而屏幕上没有任何一行说「这一件我量完了」。09-25 10:43 实测 30 件全跑一遍 real
# **3.43—3.55 秒**（现读四遍 3.55／3.47／3.48／3.43，平均一件 0.11 秒；上一节的 29 件那一遍
# 是 03:27 的 3.0 秒），所以 60 秒**不是**按比例放出来的余量 —— 它是
# 「一件卡住 = 它在等一个永远不来的东西」（起监听、等 stdin）那一族的兜底：给到一分钟，
# 让它自己超时、屏幕上那一行照样落下来，而不是整屏停在那一件上。
# 那三个数是**那时候**的：2.74 在同一棵树上重量，本节 4.15／4.22／4.16、`git show HEAD`
# 那一遍 4.53／4.51／4.45（14:51:49—14:52:15 交错三遍，六遍退码全 0）—— 同一时刻两棵树
# 差不到 0.4 秒，而两棵都比上午那句慢 0.7—1.1 秒。也就是说「一天之内这一遍慢了三成」
# 是真的，「本节把它跑慢了」不是（§2.50：屏幕上的数要说清是谁在什么时刻量的）。
# 天花板跟着这个数放：0.15 秒一件的东西给 60 秒，是**形状**的兜底，不是比例的余量。
EACH_TIMEOUT = 60


def modules(pattern: str = "") -> list[str]:
    """src/ 和 scripts/ 下的可导入模块名。

    scripts/ 里的文件按裸名导入（它们不是包，各自靠 `sys.path.insert(ROOT)` 找 src）。

    >>> "src.check.prober" in modules()
    True
    >>> "serve_lan" in modules("serve")
    True
    >>> [m for m in modules() if m.endswith("__init__")]     # 包标记不参与
    []
    """
    out = []
    for path in sorted(list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))):
        if path.name == "__init__.py":
            continue
        dotted = str(path.relative_to(ROOT)).removesuffix(".py").replace("/", ".")
        name = dotted if dotted.startswith("src.") else dotted.rsplit(".", 1)[-1]
        if pattern and pattern not in name:
            continue
        out.append(name)
    return out


def strays(names: list[str]) -> list[str]:
    """把「文件名不是合法模块名」的那几个挑出来。

    为什么这件事要拦下来而不是放过：09-23 下午 `src/` 下自己多出一个 `cli 2.py`
    （同步盘判定冲突，把**旧内容**另存成带空格的名字），遍历照收，`importlib` 也真能按
    那个带空格的名字把它导进来 —— 于是这把尺报了 **949 个用例、0 个失败（25 个模块）**，
    而真实的数是 804 / 23。多的 145 条全来自那份旧代码，它内部自洽，所以一条都不失败：
    绿是真的绿，量的却不是当前这份代码。数字一说谎，后面所有「用例 804」的记述都不能信。

    `import src.cli` 永远不会用到 `cli 2.py`，所以它出现在这里只有一种解释：该弄走。

    >>> strays(["src.cli", "src.cli 2", "serve_lan"])
    ['src.cli 2']
    >>> strays(["src.check.prober", "run_doctests"])
    []
    """
    return [n for n in names if not all(p.isidentifier() for p in n.split("."))]


def flag_of(attempted: int, failed: int) -> str:
    """逐模块那一行开头的那个符号。

    以前只分「有没有失败」两档，于是 `· name 0 个用例` 和 `· name 129 个用例` 长得一样：
    一个模块一条用例都没收到，收集器照样给它一个圆点。09-25 01:04 我拿一份现写的普查脚本
    量各文件的用例数，五个文件报 0（`code_claims` 报 0，真值 31）—— 那一屏里 0 和「都对」
    同形，而**这两个读法要办的事完全相反**：前者是该去查脚本，后者是该往下走。

    >>> flag_of(129, 0)
    '·'
    >>> flag_of(129, 2)
    '✗'
    >>> flag_of(0, 0)                                      # 什么都没收到：不给圆点
    '✗'
    """
    return "✗" if (failed or not attempted) else "·"


def label_of(mod) -> str:
    """这一件给人看的名字：能给仓库内的相对路径就给，给不了退到模块名。

    为什么要绕这两层：那一句「合计」要是印成绝对路径，这一行就成了全屏最长的噪音；
    而 `__file__` 在 `-c`、在交互式解释器里根本没有，硬取会裸崩 —— 这一支是收尾时说话的，
    不该在收尾那一步把进程带走。

    >>> import types
    >>> m = types.ModuleType("m"); m.__file__ = str(ROOT / "scripts/x.py")
    >>> label_of(m)
    'scripts/x.py'
    >>> label_of(types.ModuleType("__main__"))             # 没有 __file__：退到模块名
    '__main__'
    """
    f = getattr(mod, "__file__", None)
    if f:
        try:
            return str(pathlib.Path(f).resolve().relative_to(ROOT))
        except ValueError:                          # 不在本仓库里（临时目录、别的树）
            return pathlib.Path(f).name
    return getattr(mod, "__name__", "<没有名字的件>")


def own_line(name: str, attempted: int, failed: int) -> str:
    """跑完「自己那一份用例」之后要印的那一句。

    三条分支都得当场能说话，因为这一句的用处就是把两种读法分开：
    有失败 → 报失败；全过 → 报「全过」并且报**量到了多少条**（那个数就是这一支的证据）；
    一条都没收到 → 大声，而且不许听起来像前两种。

    >>> own_line("scripts/unmarked_nums.py", 50, 0)
    '合计 50 个用例，0 个失败（量的件：scripts/unmarked_nums.py）'
    >>> own_line("scripts/code_claims.py", 31, 3)
    '合计 31 个用例，3 个失败（量的件：scripts/code_claims.py）'
    >>> own_line("__main__", 0, 0)
    '一条用例都没收到（量的件：__main__）—— 这不算过：0 个用例和「全过」在这一屏上同形，要么这一件真没写用例，要么量的不是这一件'
    """
    if not attempted:
        return (f"一条用例都没收到（量的件：{name}）—— 这不算过："
                "0 个用例和「全过」在这一屏上同形，要么这一件真没写用例，要么量的不是这一件")
    return f"合计 {attempted} 个用例，{failed} 个失败（量的件：{name}）"


def run_own(mod) -> int:
    r"""跑 `mod` 自己那份用例，收尾印一句，退码按 2.62 那三档。

    **`mod` 必须点名递进来**：`doctest.testmod()` 不递参数时取的是 `sys.modules['__main__']`，
    于是「从别的件里调 `main(['--doctest'])`」量的是**那个调用方**的用例。09-25 01:11:55 拿一份
    三条线的驱动件量过（`/tmp/drv268.py`）：`code_claims.main(["--doctest"])` 退 0、印 0 字节，
    而它跑的既不是 code_claims 的 31 条、也不是 0 条 —— 是本件（一条用例都没有）的 0 条。
    下面那道 `testmod()` 的闸钉的就是这一件事。

    退码：**0** = 全过；**1** = 有用例失败（diff 由 doctest 自己印，在 stdout，
    所以这一句排在最后）；**2** = 一条都没收到（那是「没量到」，不是「都对」）。

    >>> import contextlib, io, types
    >>> def probe(doc):                                   # 现造一个只有说明书的件
    ...     m = types.ModuleType("假件"); m.__doc__ = doc; return m
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):             # 全过：报数，退 0
    ...     rc = run_own(probe(">>> 1 + 1\n2\n"))
    >>> rc, buf.getvalue().strip()
    (0, '合计 1 个用例，0 个失败（量的件：假件）')
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):             # 一条都没收到：大声，退 2
    ...     rc = run_own(probe("这一件一句用例都没写"))
    >>> rc, buf.getvalue().startswith("一条用例都没收到")
    (2, True)
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):             # 有用例失败：退 1
    ...     rc = run_own(probe(">>> 1 + 1\n3\n"))
    >>> rc, buf.getvalue().strip().splitlines()[-1]       # diff 在前、这一句在最后
    (1, '合计 1 个用例，1 个失败（量的件：假件）')
    """
    res = doctest.testmod(mod, verbose=False)
    print(own_line(label_of(mod), res.attempted, res.failed))
    if not res.attempted:
        return 2
    return 1 if res.failed else 0


DOCTEST_FLAG = "--doctest"


def add_doctest_flag(ap) -> None:
    """给一把握关挂上 `--doctest` 这一旗，让它在 `--help` 里看得见。

    为什么要共享这一句而不是每件自己写：`--help` 是这仓库里唯一一份**公开的旗标登记处** ——
    命令尺（2.45／2.54 那一把）拿文档里每一条长参数去问的就是这里。门只写在收尾、
    `--help` 里没有这一旗，那句话在尺子眼里就是「文档里写了照抄会失败」：
    `unmarked_nums` 的注释里记着同一条约束（「写进 argparse 只为了一句：文档尺会拿 `--help`
    核对每一条长参数」）。这一句把那本账接过来，一件不必再抄一遍理由。

    挂两遍不放过：argparse 当场 `ArgumentError`。两个入口比一个入口糟（2.68 收尾删掉的
    那一条重复支路就是这一族），所以让它响，不静默幂等。

    >>> import argparse
    >>> ap = argparse.ArgumentParser(prog="x.py")
    >>> add_doctest_flag(ap)
    >>> ap.parse_args(["--doctest"])
    Namespace(doctest=True)
    >>> ap.parse_args([]).doctest
    False
    >>> add_doctest_flag(ap)                                   # 挂第二遍：响
    Traceback (most recent call last):
        ...
    argparse.ArgumentError: argument --doctest: conflicting option string: --doctest
    """
    ap.add_argument(DOCTEST_FLAG, action="store_true",
                    help="只跑本文件说明书里的那些用例（不是 --self-test 的那些基线格子）")


def doctest_gate(argv: list[str], mod=None) -> int | None:
    r"""`--doctest` 的那一道门：旗在就跑用例并把退码递回去，旗不在返回 `None`。

    用在**没有 argparse** 的那两件上（`run_doctests` 自己只收一个子串、`src.cli` 是自己
    手写的子命令分派）。有 argparse 的件走另一条：`add_doctest_flag` 把旗挂进 parser，
    收尾一句 `if args.doctest: return run_own(...)`。两种写法并存不是没收干净，是
    「这一旗该在哪一层被认」本来就跟着那件收不收参数走 —— 收集器自己不认任何长参数，
    给它挂一个 parser 等于为了一个旗重写它的入口。

    为什么是「返回退码」而不是在门里自己 `raise SystemExit`：那样这一件事的门就**测不了**了 ——
    测它的那条例子得跑在 `__main__` 里，而它一跑就把整个收集器带走。递退码出来，
    例子可以拿一个假件喂 `mod`，本件的其余用例不必陪葬。这一族病和
    `run_own` 那句「`mod` 必须点名递进来」是同一个：收尾那一步的可见性不能靠运气。

    和 `--self-test` 不是一回事：那一旗跑的是各把尺的**基线格子**（沙盒里种假件），
    这一旗跑的是**说明书里的例子**。

    >>> import contextlib, io, types
    >>> def fake(doc):                                    # 现造一件只有说明书的
    ...     m = types.ModuleType("假件"); m.__doc__ = doc; return m
    >>> doctest_gate(["docs/x.md"], mod=fake(">>> 1 + 1\n2\n")) is None   # 没递旗：门不拦
    True
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):             # 旗在、外面还跟着真参数
    ...     rc = doctest_gate(["--doctest", "docs/x.md"], mod=fake(">>> 1 + 1\n2\n"))
    >>> rc, buf.getvalue().strip()
    (0, '合计 1 个用例，0 个失败（量的件：假件）')
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):             # 旗在、可这一件没写例子：退 2
    ...     rc = doctest_gate(["--doctest"], mod=fake("全是话，一条例子都没有"))
    >>> rc, buf.getvalue().startswith("一条用例都没收到")
    (2, True)
    """
    if DOCTEST_FLAG not in argv:
        return None
    return run_own(sys.modules["__main__"] if mod is None else mod)


def bare_testmod_in(src: str) -> bool:
    r"""这段 .py 的**代码**里有没有「没点名量哪个件」的 `testmod()`（说明书里的字不算）。

    只认**位置参数**：`testmod(verbose=False)` 递了一个旗标，可它没说是量谁 ——
    那正是这一道要揪的写法，不能因为它带了字就算干净。

    为什么非走 AST 不可：01:16:05 第一版是正则扫原文，结果它把**自己**揪出来了 ——
    `no_bare_testmod` 那句说明里写着 `doctest.testmod()`（就是要说这个写法），扫原文的闸
    分不清「提到」和「用了」，报了 `['run_doctests.py']`。同一件事 2.60 在另一层里已经付过学费。
    读不通的源算 `True`：连语法都不通的件，不能算它「没有这个写法」。

    >>> bare_testmod_in("doctest.testmod()")
    True
    >>> bare_testmod_in("doctest.testmod(verbose=False)")   # 带了旗标、没点名量谁：一样是病
    True
    >>> bare_testmod_in("doctest.testmod(mod, verbose=False)")
    False
    >>> bare_testmod_in("'''那一句写作 doctest.testmod()，是描述、不是调用'''\n")
    False
    >>> bare_testmod_in("def f(:\n")                       # 读不通：算它一份
    True
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.args:
            continue
        called = node.func
        if isinstance(called, ast.Attribute) and called.attr == "testmod":
            return True
        if isinstance(called, ast.Name) and called.id == "testmod":
            return True
    return False


def no_bare_testmod(dirs: tuple[pathlib.Path, ...] = (ROOT / "scripts",)) -> list[str]:
    """列出「调 `doctest.testmod()` 却没点名量哪个件」的那几份 —— 应该是空表。

    为什么要有这一道：`run_own` 修的那个病（不递参数就量了调用方）在这一层里**看不见**：
    屏幕上的句子照样通顺，退码照样 0，只有跑的人心里那个「我量的是这个文件」是假的。
    2.42 给名单和代码装过同一种闸（两边各写一份、漂了没人响），这一道是它的另一面：
    写法漂回去，这里就红。

    名字不像模块名的（同步盘冲突副本）不看 —— 收集器在它们在场时根本不肯跑，
    这一道再跟着扫一份旧代码，就是 2.55 那一遍「949 条用例从两份代码里凑」的形状。

    >>> no_bare_testmod((ROOT / "scripts",))
    []
    """
    return sorted(p.name for p in sum((list(d.glob("*.py")) for d in dirs), [])
                  if p.stem.isidentifier()
                  and bare_testmod_in(p.read_text(encoding="utf-8")))


ROUTE_RUNS = "走通"
ROUTE_NO_FLAG = "不用旗标"
ROUTE_ARGPARSE = "argparse 拦"
ROUTE_AS_ARG = "当成一个参数"
ROUTE_NO_DOOR = "没有入口"


def _tree(src: str):
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def example_count(src: str) -> int:
    """静态数出这段源里写了多少条 doctest 例子（不导入、不跑）。

    为什么要静态的这一把：2.68 要回答的问题是「有多少用例**只能**靠收集器跑到」，
    那得在**不跑**的前提下把每一件事都算上 —— 而 `testmod` 只会告诉你它跑了几个。
    01:33:16 拿整棵树对过一遍账：静态数 1800 条，收集器同一遍报 1800 个用例，逐件相同。

    递进来的必须是**读得通的 .py 源**，而 `>>> 1 + 1` 那样的例子内壳本身不是合法 Python
    （01:37:36 第一版就这么错过：它解析失败，于是「数出 0 条」和「这一件读不通」同形）。
    所以例子要写在一份件的说明书里，而不是裸着递进去。

    >>> example_count("'''跑一遍：\\n>>> 1 + 1\\n2\\n'''")
    1
    >>> example_count("'''两条：\\n>>> 1 + 1\\n2\\n>>> 2 + 2\\n4\\n'''")
    2
    >>> example_count("def f():\\n    '这里一句例子都没写'\\n    return 1\\n")
    0
    >>> example_count("def f(:\\n")                  # 读不通：也算 0，这一档与上面同形
    0
    """
    tree = _tree(src)
    if tree is None:
        return 0
    parser = doctest.DocTestParser()
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                total += len(parser.get_examples(doc))
    return total


def has_main_block(src: str) -> bool:
    """这份件被直接运行时到底会不会做事（有没有 `if __name__ == "__main__"`）。

    >>> has_main_block('if __name__ == "__main__":\\n    main()\\n')
    True
    >>> has_main_block("def f():\\n    pass\\n")      # 纯库：跑它 = 静默退 0
    False
    """
    tree = _tree(src)
    if tree is None:
        return False
    return any(isinstance(st, ast.If) and "__main__" in ast.dump(st.test) for st in tree.body)


def reads_argv(src: str) -> bool:
    """这份件的代码里碰不碰 `argv`。

    >>> reads_argv("raise SystemExit(main(sys.argv[1:]))")
    True
    >>> reads_argv("def main(argv):\\n    return len(argv)")
    True
    >>> reads_argv("print('我不看参数')")
    False
    """
    tree = _tree(src)
    if tree is None:
        return False
    return any((isinstance(c, ast.Attribute) and c.attr == "argv")
               or (isinstance(c, ast.Name) and c.id == "argv") for c in ast.walk(tree))


OWN_DOORS = ("run_own", "doctest_gate")


def _door_nodes(tree) -> set:
    """门自己那几段函数体里的节点 —— 问「有没有人叫它」时要把这一片挖掉。

    为什么要挖：这两道门的**体内**天生就写着「调用 `run_own`」「把 `DOCTEST_FLAG`
    拿去和 argv 比」 —— 那是门的写法，不是这一件的写法。不挖的话，
    「定义了一道没人叫的门」与「收尾叫了那一声明」在静态上长得一模一样，
    而 2.69 变异机 `N1` 那一刀（把收尾 `rc = doctest_gate(...)` 换成 `rc = None`）
    两面全绿 —— 本节要抓的正是这个形状，它和 §2.68 的 `M16` 是同一种病。
    """
    return {id(n) for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and fn.name in OWN_DOORS for n in ast.walk(fn)}


def calls_outside_door(src: str, names: tuple[str, ...]) -> bool:
    """`names` 里那些名字，有没有在**门的外面**被调用一次。

    >>> calls_outside_door("raise SystemExit(doctest_gate(a))", OWN_DOORS)
    True
    >>> calls_outside_door("def doctest_gate(a):\\n    return run_own(m)", OWN_DOORS)
    False
    >>> calls_outside_door("'''说的是 run_own 这件事'''\\n", OWN_DOORS)   # 说明书里提一句：不算
    False
    """
    tree = _tree(src)
    if tree is None:
        return False
    inside = _door_nodes(tree)
    return any(isinstance(c, ast.Call) and id(c) not in inside
               and ((isinstance(c.func, ast.Name) and c.func.id in names)
                    or (isinstance(c.func, ast.Attribute) and c.func.attr in names))
               for c in ast.walk(tree))


def runs_own_cases(src: str) -> bool:
    """这份件有没有**被走到**「跑自己那份用例」的路（`run_own` 与 `doctest_gate` 都算）。

    为什么要认两道门：`run_own` 是 2.68 之前那三件手写的形状（自己先认旗、再叫号），
    `doctest_gate` 是 2.69 起其余那些件的写法（把认旗这一步也交给共用的一件）。
    两道门后面是同一个 `run_own`，所以这一句问的是「它有没有那一条支路」，不是「它怎么写」。
    2.69 起这一句还多认一层：**只在门体内出现的调用不算**（见 `_door_nodes`）。

    >>> runs_own_cases("from run_doctests import run_own\\nrun_own(m)")
    True
    >>> runs_own_cases("rc = doctest_gate(sys.argv[1:])")
    True
    >>> runs_own_cases("'''说的是 run_own 这件事'''\\n")   # 说明书里提一句：不算
    False
    >>> runs_own_cases("def run_own(m):\\n    return 0\\n")  # 自己定义一个同名件：也不算走过
    False
    """
    return calls_outside_door(src, OWN_DOORS)


def calls_parse_args(src: str) -> bool:
    """这份件有没有把参数交给 `argparse`（`p.parse_args()` 是一种**不提 `argv` 就读 `argv`** 的写法）。

    为什么必须会这一句：`route_shape` 老版本问的是「代码里提没提 argv」，而 `parse_args()`
    从来不提 —— 于是 2.68 那句现状把 `probe_pack`／`serve_lan` 分进了「不看参数」，
    并顺着写出「递 `--doctest` 给它们的语义正好是去干你自己的活」（§2.68 边界第 2 条）。
    01:55:51 真跑那两遍：`usage: probe_pack.py [-h] ...`、131 字节、退 2，
    `data/output/` 一个字节的 mtime 都没动；`serve_lan` 同形（94 字节、一个端口都没听）。
    **那句话是假的**，判据就是这里补的：会拦旗标的那一位不是件自己，是 argparse。

    >>> calls_parse_args("args = p.parse_args()")
    True
    >>> calls_parse_args("args, rest = p.parse_known_args(argv)")
    True
    >>> calls_parse_args("raise SystemExit(main(sys.argv[1:]))")
    False
    >>> calls_parse_args("'''用法里写着 p.parse_args()'''\\n")   # 说明书里提一句：不算
    False
    """
    tree = _tree(src)
    if tree is None:
        return False
    return any(isinstance(c, ast.Call)
               and isinstance(c.func, ast.Attribute)
               and c.func.attr in ("parse_args", "parse_known_args")
               for c in ast.walk(tree))


def has_parser(src: str) -> bool:
    """这份件自己**建了一把 argparse 的关**没有 —— 造 `ArgumentParser`、或调 `parse_args`。

    为什么要有这一句，而不是「文件里提没提 `argparse` 这个词」：命令尺里有一条豁免，
    「目标脚本没有 argparse ⇒ 它不认 `--help`，别报参数不存在」，2.69 之前那一句话写成
    字面量 `not in text`。本节给收集器写了 `add_doctest_flag`（它的说明书里有
    `import argparse`），而收集器自己仍然一把握关都没有 —— 那个字面量判据于是把
    「提了一嘴」读成「有一把关」，豁免再也不成立，`check_doc_cmds` 的 `B10` 当场红了
    （02:18 实测：`run_doctests.py --help` 答的是「我不收旗标」、退 2）。
    跟上面 `_registers_flag` 同一个取舍：**走 AST，只认真会执行的那几种调用**。

    >>> has_parser("ap = argparse.ArgumentParser()")
    True
    >>> has_parser("args = p.parse_args(argv)")
    True
    >>> has_parser("import argparse\\nap = argparse.Namespace()")   # 只有那个词：不算有关
    False
    >>> has_parser("'''用法：p.parse_args()'''\\n")                  # 说明书里提一句：也不算
    False
    >>> has_parser("def f(:\\n")                                     # 读不通：不替它认账
    False
    """
    tree = _tree(src)
    if tree is None:
        return False
    for c in ast.walk(tree):
        if not isinstance(c, ast.Call):
            continue
        f = c.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
        if name in ("ArgumentParser", "parse_args", "parse_known_args"):
            return True
    return False


def docs_claim_flag(src: str) -> bool:
    """这份件的**模块说明书**里写没写 `--doctest` 这一旗。

    只看模块级那一段：那是给人抄的用法。函数 docstring 里提一句「上面那个门怎么写的」
    不算这一件对外承诺了这个旗标。

    >>> docs_claim_flag("'''用法：\\n    python x.py --doctest\\n'''")
    True
    >>> docs_claim_flag("'''只跑全量：\\n    python x.py\\n'''")
    False
    >>> docs_claim_flag("def f(:\\n")                       # 读不通：不替它认账
    False
    """
    tree = _tree(src)
    return tree is not None and DOCTEST_FLAG in (ast.get_docstring(tree) or "")


def _registers_flag(tree) -> bool:
    """代码里有没有把 `--doctest` **挂进 parser**（两种写法：共用那一句 `add_doctest_flag`，
    或自己 `ap.add_argument("--doctest", ...)`）。

    走 AST 而不是扫字面量：说明书里写「用法：`--doctest`」不是挂号。
    """
    for c in ast.walk(tree):
        if not isinstance(c, ast.Call):
            continue
        f = c.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
        if name == "add_doctest_flag":
            return True
        if name == "add_argument" and any(isinstance(a, ast.Constant)
                                         and a.value == DOCTEST_FLAG for a in c.args):
            return True
    return False


def flag_answer(src: str) -> str:
    """这一件是从哪一层应答 `--doctest` 的 —— 三种答法之一，或者「没有应答」。

    为什么要分清答法、而不只问「有没有答」：三种答法的**可达性不一样**。排在
    `parse_args` 后面那一种（读 `args.doctest`）得先过 argparse 那一关，
    而 argparse 遇到缺了的必填位置参数会直接退 2 —— 应答那一行就再也读不到。
    02:14:43 在 `verify_lines` 上撞到的正是这一条：`add_doctest_flag` 挂了、
    `if args.doctest:` 也写了，屏幕上仍是 299 字节的 usage（「required: m3u」）。

    本节后半又加了一条规矩：**「门里写着」不算这一件应答了**（理由见 `_door_nodes`）——
    那一版的答法只认「字面量在不在文件的字符串里」，而 `DOCTEST_FLAG = "--doctest"`
    那一行定义本身就是这样一个字面量，于是「定义了一声明没人叫的门」被读成「应答过」。
    `N1` 那一刀两面全绿量出来的就是这一处。

    >>> flag_answer("if args.doctest:\\n    return 0")
    'parser'
    >>> flag_answer("rc = doctest_gate(argv)")
    '门'
    >>> flag_answer('if "--doctest" in sys.argv:\\n    print(1)')
    '自己比字面量'
    >>> flag_answer("def doctest_gate(a):\\n    if DOCTEST_FLAG not in argv:\\n        return None")
    '没有应答'
    >>> flag_answer('print("这一件不认任何旗")')
    '没有应答'
    """
    tree = _tree(src)
    if tree is None:
        return "没有应答"
    if any(isinstance(n, ast.Attribute) and n.attr == "doctest" for n in ast.walk(tree)):
        return "parser"
    if calls_outside_door(src, OWN_DOORS):
        return "门"
    inside = _door_nodes(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and id(n) not in inside:
            operands = [n.left, *n.comparators]
            if any((isinstance(o, ast.Constant) and o.value == DOCTEST_FLAG)
                   or (isinstance(o, ast.Name) and o.id == DOCTEST_FLAG) for o in operands):
                return "自己比字面量"
    return "没有应答"


def _needs_positional(src: str) -> bool:
    r"""这把握关有没有一个**非递不可**的位置参数（`ap.add_argument("m3u")` 那种）。

    带 `nargs` 或 `default` 的不算：那两种可以一个都不给 ——
    `check_doc_cmds` 的 `[docs ...]` 就是这一种，所以它把应答挂在 `parse_args` 后面走得通。

    >>> _needs_positional('ap.add_argument("m3u")')
    True
    >>> _needs_positional('ap.add_argument("docs", nargs="*")')
    False
    >>> _needs_positional('ap.add_argument("--top", type=int)')
    False
    """
    tree = _tree(src)
    if tree is None:
        return False
    for c in ast.walk(tree):
        if not isinstance(c, ast.Call) or getattr(c.func, "attr", "") != "add_argument":
            continue
        if not c.args or not isinstance(c.args[0], ast.Constant):
            continue
        name = c.args[0].value
        if not isinstance(name, str) or name.startswith("-"):
            continue
        if not any(k.arg in ("nargs", "default") for k in c.keywords):
            return True
    return False


def dead_flag_doors(dirs: tuple[pathlib.Path, ...] = DEFAULT_DIRS) -> list[str]:
    """对 `--doctest` 作了承诺（写进用法、或挂进 parser）、可那一旗到不了应答的件 —— 应该是空表。

    为什么要有这一道：这一族的第一个实例不是假设，是本节当场撞出来的两件之一 ——
    `unmarked_nums` 在 parser 里挂了这一旗（挂号的理由还写着「文档尺会拿 `--help`
    核对每一条长参数」），可 `main()` 里**从来不读 `args.doctest`**，读它的位置在模块收尾。
    命令行那一遍是对的（收尾先拦），而 `main(["--doctest"])` 这一种调法 ——
    基线格子调尺子就是这一种 —— 会越过收尾直接去读那两篇真文档。
    **字还在、路已死**：§2.68 变异机 `M16` 那一刀的形状在这里真发生过一次。

    死法有两种，这一道两种都问（第二种是 02:14:43 在 `verify_lines` 上补进来的）：

    1. 作了承诺、没有人应答；
    2. 应答写了，可它排在 `parse_args` 后面，而这把握关有一个必填位置参数 —— 那一行永远读不到。

    「没有人应答」按 `flag_answer` 那三种答法判，**定义了一道门、可全文件没人叫它** 也算没人应答
    （`N1` 那一刀：把收尾那一句叫门换成 `rc = None`，两面全绿了三次复测才把它接上）。

    名字不像模块名的（同步盘冲突副本）不看，理由同 `no_bare_testmod`。

    >>> dead_flag_doors()
    []
    >>> dead_flag_doors((ROOT / "config",))       # 那里没有 .py：空表，不替它编一个错
    []
    """
    out = []
    for path in sum((list(d.rglob("*.py")) for d in dirs), []):
        if not path.stem.isidentifier():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = _tree(src)
        if tree is None:
            continue                              # 读不通的件不归这一道管：收集器先就走不动
        if not (docs_claim_flag(src) or _registers_flag(tree)):
            continue
        how = flag_answer(src)
        if how == "没有应答" or (how == "parser" and _needs_positional(src)):
            out.append(path.name)
    return sorted(out)


def route_shape(src: str) -> str:
    """直接跑 `python 这份件 --doctest` 会走到哪条路上 —— 五档里的一档。

    这一把尺要量的是**约定到底覆盖了谁**。2.68 那一版是四档、按「代码里提没提 argv」分，
    于是把「`parse_args` 不提 argv 却会退 2」和「`run_own` 不看旗标也照样跑用例」两类都读错了；
    2.69 这一版改问「**这个旗标会被谁拦下**」，五档的判据都对着 01:55:51／01:59:14 两遍实测：

    * `走通` —— 件自己问了那道门，答的是它自己的用例数。
    * `不用旗标` —— 没有门，可它收尾根本不看参数：递什么都跑自己那一份（`baseline_guard`）。
    * `argparse 拦` —— 旗标到不了件自己手里，`parse_args` 先印 usage、退 2：不跑用例，也不干活。
    * `当成一个参数` —— 旗标被当成一个路径／子命令递进去了：最坏的一档，因为件的答复听着像判决。
    * `没有入口` —— 纯库，没有 `if __name__ == "__main__"`：这一档有两种坏法，
      带绝对导入的那件 traceback 退 1，其余的 **0 字节退 0**（01:59:14 实测 11 件里 7 件）。

    判定只看**静态**：这一把认的是「字在不在」，不是「跑起来怎么样」——
    门被写死成永远返回 `None` 时这里照样报 `走通`（那是 §2.68 变异机 `M16` 那一刀的形状，
    本节仍然没有把它接成仓库里的实跑，理由与边界见计划书 §2.69）。
    反过来，「定义了门、可全文件没人叫它」（`N1`）这一把认得出来：2.69 起
    `runs_own_cases` 问的是「门的外面有没有一句调用」，不是「文件里有没有这些字」。

    >>> route_shape('if __name__ == "__main__":\\n    doctest_gate(a)')
    '走通'
    >>> route_shape('if __name__ == "__main__":\\n    run_own(m)')      # 2.68 那三件的旧写法
    '走通'
    >>> route_shape('if __name__ == "__main__":\\n    raise SystemExit(main())\\n')
    '不用旗标'
    >>> route_shape('a = p.parse_args()\\nif __name__ == "__main__":\\n    main()')
    'argparse 拦'
    >>> route_shape('if __name__ == "__main__":\\n    raise SystemExit(main(sys.argv[1:]))')
    '当成一个参数'
    >>> route_shape("def f():\\n    pass\\n")                             # 纯库
    '没有入口'
    >>> route_shape("def f(:\\n")                                         # 读不通：也算没有入口
    '没有入口'
    """
    if not has_main_block(src):
        return ROUTE_NO_DOOR
    if runs_own_cases(src):
        return ROUTE_RUNS
    if calls_parse_args(src):
        return ROUTE_ARGPARSE
    return ROUTE_AS_ARG if reads_argv(src) else ROUTE_NO_FLAG


def survey_routes(dirs: tuple[pathlib.Path, ...] = DEFAULT_DIRS,
                  base: pathlib.Path = ROOT) -> dict[str, list[str]]:
    """整棵树按 `route_shape` 分档，键是那一档、值是 `相对路径 用例数` 的名单。

    在册的件由 `each_file` 那一层定（2.70 起它跟 `--each` 共用同一套取舍 —— 那两个数
    必须能对着读，不然静态普查和实跑普查就是在数两堆件）。
    用例数写在名单里而不是只报件数：这一档真正要说的是「多少个用例只有收集器跑得动」。

    **这一处不再钉「一共几件」**：那个数是 `each_file` 的格子（本节之前它在下面两条例子里
    又抄了一遍，于是 29 → 30 那一涨要改两处，而改漏的那一处不会红 —— 它只会红成
    「这一档少了 1 件」，把人支到判据上去）。这一把只钉**形状**：哪几档有件、没有入口的
    是谁、有几件白跑。

    >>> found = survey_routes()
    >>> sorted(found)                                                      # 接线之后只剩两档有件
    ['没有入口', '走通']
    >>> [k for k in (ROUTE_ARGPARSE, ROUTE_NO_FLAG, ROUTE_AS_ARG) if k in found]
    []
    >>> all(s.startswith("src/") for s in found[ROUTE_NO_DOOR])            # 没有入口的全是库
    True
    >>> len(found[ROUTE_NO_DOOR])                                          # 11 件、只有收集器跑得动
    11
    >>> [k for k, v in found.items() if any("run_doctests" in s for s in v)]
    ['走通']
    >>> [k for k, v in found.items() if any("work_guard" in s for s in v)] # 2.70 新接的那一件
    ['走通']

    这里**故意不钉用例条数**、也不钉 `走通` 那一档的名单：本件自己就在被数的那一堆里，
    而「接了门的件」是要往外长的（01:55:51 那一份普查里这一档只有 3 件，§2.69 接完是 17 件，
    §2.70 又接了一件），把那一串名字写死在这里，下一件接门时就红一格 ——
    红理由是「你多接了一件」，那是 2.68 记过的同一种自指。
    上面凡是打集合的地方都过一道 `sorted`：字符串的哈希每个进程重新播种，
    直接印 set 会让同一棵树的两遍跑出两种顺序（2.67 的「两遍必须同数」在这一层里同样成立）。
    """
    by: dict[str, list[str]] = {}
    for path, n, route in each_file(dirs):
        by.setdefault(route, []).append(f"{path.relative_to(base)} {n}")
    return {k: sorted(v) for k, v in by.items()}


def survey_line(by: dict[str, list[str]]) -> str:
    """把上面那份分档收成一句现状说明（空表返回空串）。

    排序按「这条路有多通」而不是按件数：件数排会让「23 件不通」读成一个排名，
    而这一句的作用只是让下一个人不必再写一份普查脚本。
    每一档后面跟「N 件／M 个用例」两个数：只给件数读不出「多少用例被这一档困住」。

    >>> survey_line({ROUTE_AS_ARG: ["a.py 3", "b.py 4"], ROUTE_RUNS: ["c.py 9"]})
    '这条路的形状（只说现状、不判决）：走通 1 件／9 个用例、当成一个参数 2 件／7 个用例'
    >>> survey_line({})
    ''
    """
    if not by:
        return ""
    order = [ROUTE_RUNS, ROUTE_NO_FLAG, ROUTE_ARGPARSE, ROUTE_AS_ARG, ROUTE_NO_DOOR]
    parts = []
    for key in order + [k for k in sorted(by) if k not in order]:
        rows = by.get(key)
        if not rows:
            continue
        cases = sum(int(r.rsplit(" ", 1)[1]) for r in rows)
        parts.append(f"{key} {len(rows)} 件／{cases} 个用例")
    return "这条路的形状（只说现状、不判决）：" + "、".join(parts)


def zero_note(names: list[str]) -> str:
    """「有模块一条用例都没收到」那一截尾巴；一个都没有时返回空串（不印一句空话）。

    为什么单独抽出来：上面那句「合计」是全过与不全过**共用**的一行，光看它读不出这一档；
    而这一档必须点名 —— 「其中 1 个模块」不给名字的话，下一个读的人还得自己开 `--verbose` 找。
    点名排序按**跑的顺序**（`names` 原序），不按名字：这一屏每一行都是那个顺序，
    突然有一行按拼音排，反而像换了口径。

    >>> zero_note(["analyze_upstream"])
    '其中 1 个模块一条用例都没收到：analyze_upstream —— 上面那句「全过」不包括它们'
    >>> zero_note(["b", "a"])                        # 原序，不重排
    '其中 2 个模块一条用例都没收到：b、a —— 上面那句「全过」不包括它们'
    >>> zero_note([])
    ''
    """
    if not names:
        return ""
    return (f"其中 {len(names)} 个模块一条用例都没收到：" + "、".join(names)
            + " —— 上面那句「全过」不包括它们")


# `--each`：2.70 起本件收的第二个旗。它跟过滤器不是一类东西（一个是「跑法」，一个是「跑谁」），
# 所以必须在下面那句「我不收旗标」之前先摊掉 —— 否则它就是那一屏要报的那件坏事。
EACH_FLAG = "--each"

# 那一句「合计」的形状，抄自 `own_line`。为什么用正则而不是把 `own_line` 反过来解：
# 反向解要拿字符串做等式，而屏幕上那一句前后还有别的字（用例自己的输出、护栏那一句），
# 正则只要求「这一行是这个形状」，才是拿**输出**当证据。两头都写着同一个形状，
# 改一处忘了另一处会立刻红：`each_verdict` 会把那一件读成「一个字都没答」。
ANSWER_RE = re.compile(r"合计 (\d+) 个用例，(\d+) 个失败（量的件：(.*?)）")
ZERO_RE = re.compile(r"一条用例都没收到（量的件：(.*?)）")
# 护栏那一句（`work_guard.guard_line`）。`:(\d+) 条` 后面那一段点名是可选的：
# 0 条的时候它根本不会出现在屏幕上。
GUARD_RE = re.compile(r"落在仓库里 (\d+) 条(?:：(.*?))?（被量件退")
# 护栏那句「被量件根本没跑起来」——它跟「一条都没落在仓库里」不是一回事（见 `guard_line`）。
GUARD_DEAD_RE = re.compile("可被量件根本没跑起来")


def each_file(dirs: tuple[pathlib.Path, ...] = DEFAULT_DIRS
              ) -> list[tuple[pathlib.Path, int, str]]:
    """树上每一件「写了用例的 .py」：`(路径, 静态用例数, 静态那一档)`，按路径排序。

    这一句是 `survey_routes` 与 `each_targets` **共用**的那一层，理由是 2.58 立下的那条
    （口径只有一份，下一把尺不必再抄一遍注释）：那两处对「什么件算在册」的取舍必须一样，
    不然静态普查跟实跑普查会各数出一堆件，而那两个数是不能对比的。
    取舍三条：`__init__.py` 不看（它没有用例可言）；文件名不像模块名的不看（同步盘的冲突
    副本 —— 见 `strays` 那段理由）；一条用例都没写的也不看（它没有「这条路通不通」这个问题）。

    >>> rows = each_file()
    >>> len(rows)                                       # 接完 doc_headings 之后在册的件数
    30
    >>> all(n > 0 for _, n, _ in rows)                  # 没写用例的不入册
    True
    >>> [str(p.relative_to(ROOT)) for p, _, _ in rows if not p.stem.isidentifier()]
    []
    >>> all(isinstance(r, str) for _, _, r in rows)     # 每一件都归了档
    True
    """
    rows: list[tuple[pathlib.Path, int, str]] = []
    for path in sorted(sum((list(d.rglob("*.py")) for d in dirs), [])):
        if path.name == "__init__.py" or not path.stem.isidentifier():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        n = example_count(src)
        if not n:
            continue
        rows.append((path, n, route_shape(src)))
    return rows


def parse_own_line(text: str) -> tuple[str, int, int] | None:
    """从一片输出里读出那一件自己报的 `(量的件, 用例数, 失败数)`；它一个字都没答则 `None`。

    取**最后**一条：一件的说明书里可能嵌着「这一句长什么样」的例子（本件就有），
    拿第一条会把那句例子当成答复。
    「一条用例都没收到」那一支也算答了，而且是**带着名字**答的 —— 它报 0 条，
    跟「没答」不是一回事（见 `own_line` 那段：0 个用例和「全过」不能同形）。

    >>> parse_own_line("合计 174 个用例，0 个失败（量的件：src/cli.py）")
    ('src/cli.py', 174, 0)
    >>> parse_own_line("一条用例都没收到（量的件：__main__）—— 这不算过：0 个用例和「全过」在这一屏上同形")
    ('__main__', 0, 0)
    >>> parse_own_line("护栏：一条这类动作都没看见、落在仓库里 0 条（被量件退 0）") is None
    True
    >>> parse_own_line("合计 1 个用例，0 个失败（量的件：例子）\\n合计 12 个用例，3 个失败（量的件：x）")
    ('x', 12, 3)
    """
    got = ANSWER_RE.findall(text)
    if got:
        n, failed, label = got[-1]
        return label, int(n), int(failed)
    zero = ZERO_RE.findall(text)
    if zero:
        return zero[-1], 0, 0
    return None


def parse_guard(text: str) -> tuple[int | None, str]:
    """读护栏那一句：`(落在仓库里的条数, 那串点名)`；屏幕上没有那一句时条数是 `None`。

    为什么 `None` 不能写成 0：0 是「护栏说了：一条都没落在仓库里」，`None` 是「护栏那句话
    根本没到屏幕上」—— 子进程没起来、被 `EACH_TIMEOUT` 掐了、或者它炸在护栏挂上之前，
    这几种都长一样。把它们读成 0 就是 2.62 那一族「两种 0 同形」。
    同样取最后一条：被量件自己的用例里可能印着一句假的那个形状。

    >>> parse_guard("护栏：看见 2 条（open 2）、落在仓库里 1 条：写 /r/data/x（被量件退 0）")
    (1, '写 /r/data/x')
    >>> parse_guard("护栏：一条这类动作都没看见、落在仓库里 0 条（被量件退 0）")
    (0, '')
    >>> parse_guard("合计 3 个用例，0 个失败（量的件：x）")                 # 护栏那句没来
    (None, '')
    >>> parse_guard("护栏：一条都没看见 —— 可被量件根本没跑起来，这一句读不出「它没干活」")
    (None, '')
    """
    hits = list(GUARD_RE.finditer(text))
    if not hits:
        return None, ""
    m = hits[-1]
    return int(m.group(1)), m.group(2) or ""


def each_targets(pattern: str = "", dirs: tuple[pathlib.Path, ...] = DEFAULT_DIRS,
                 base: pathlib.Path = ROOT
                 ) -> list[tuple[pathlib.Path, int, str]]:
    """`--each` 要跑的那些件：`each_file` 那一堆里相对路径含 `pattern` 的（空串＝全部）。

    >>> len(each_targets()) == len(each_file())                             # 默认就是全册
    True
    >>> [str(p.relative_to(ROOT)) for p, _, _ in each_targets("work_guard")]
    ['scripts/work_guard.py']
    >>> each_targets("没有这样一个件")
    []
    >>> each_targets("x", ())                       # 在册范围是空的：一件都没有（不替你编一个）
    []
    """
    return [row for row in each_file(dirs) if pattern in str(row[0].relative_to(base))]


def each_verdict(rel: str, want: int, route: str, rc: int | None, out: str,
                 cut: int | None = None) -> str:
    """一件跑完之后那一行话。纯函数：跑在 `spawn_each`，判在这里，判的部分全部能拿假输出喂。

    一行分两截，因为这一屏要同时说「读到了什么」和「哪里不对」：前面那一截把子进程那几样
    东西（它自己答的那句、静态那把尺数出来的、护栏那本账）并排摊开 —— **连静态判错的那几行
    也照摊**，摊错了才有得查；后面那一截只装毛病，一条毛病一句话，用「；」接。

    判的是一头一尾两件事：
    * 静态说它答、可它一个字都没答 —— §2.68 `M16` 那一刀的形状，也是本节存在的理由；
    * 静态说它不答、可它答了 —— 那是静态那把尺判错了（§2.69 的 `baseline_guard` 正是这一族，
      当时是 02:46:52 拿眼睛从屏幕上看出来的，今天由这一行说）。
    中间那一层是「答了，可答的不是它自己那份」：条数对不上静态、或者「量的件」报的不是这个
    路径（2.68 那句「`testmod()` 不点名就量了调用方」在这一层的形状）。

    多出来的那一位 `cut` 说的是天花板：递了秒数，就是这一遍自己把那件掐了 —— 那两句
    「它为什么没说话」的猜想在这一档都得闭嘴（护栏那一句和本来的回答**注定**拿不到）。
    这一位是本节头一遍跑基线跑出来的：那一屏把一件卡住的脚本读成了
    「子进程连 work_guard 都没跑起来？」，可它跑起来了、只是没跑完；而 `spawn_each`
    本来就拼了一句「超过 N 秒没回来」，那一句在 `out` 里待着、**从没上过屏幕**。

    >>> GOOD = "合计 12 个用例，0 个失败（量的件：scripts/x.py）\\n" \\
    ...        "护栏：一条这类动作都没看见、落在仓库里 0 条（被量件退 0）"
    >>> each_verdict("scripts/x.py", 12, ROUTE_RUNS, 0, GOOD)
    '· scripts/x.py                       答 12／静态 12、量的件=scripts/x.py、护栏 0 条'
    >>> DEAD = "护栏：一条都没看见 —— 可被量件根本没跑起来，这一句读不出「它没干活」"
    >>> each_verdict("src/y.py", 30, ROUTE_NO_DOOR, 2, DEAD)   # 纯库白跑：那不是毛病
    '· src/y.py                           没答（静态：没有入口，退 2）、只有收集器跑得动它'
    >>> each_verdict("scripts/z.py", 9, ROUTE_RUNS, 2, DEAD)   # 字还在、路已死
    '✗ scripts/z.py                       没答（静态：走通，退 2） —— 字还在、路已死：静态说「走通」，它一个字都没答'
    >>> each_verdict("src/y.py", 12, ROUTE_NO_DOOR, 0, GOOD.replace("scripts/x.py", "src/y.py"))
    '✗ src/y.py                           答 12／静态 12、量的件=src/y.py、护栏 0 条 —— 静态那一档说「没有入口」，可它答了：那把尺判错了'
    >>> each_verdict("scripts/x.py", 12, ROUTE_RUNS, 1,
    ...     "合计 12 个用例，3 个失败（量的件：scripts/x.py）\\n"
    ...     "护栏：看见 1 条（open 1）、落在仓库里 0 条（被量件退 1）")
    '✗ scripts/x.py                       答 12／静态 12、量的件=scripts/x.py、护栏 0 条 —— 用例里有 3 个失败'
    >>> each_verdict("scripts/x.py", 12, ROUTE_RUNS, 1, GOOD)  # 退码说有事、屏幕上却全对
    '✗ scripts/x.py                       答 12／静态 12、量的件=scripts/x.py、护栏 0 条 —— 子进程退 1，可它报的用例全过、护栏也没意见：这一档对不上'
    >>> each_verdict("scripts/x.py", 20, ROUTE_RUNS, 0, GOOD)  # 跑到的比写下来的少
    '✗ scripts/x.py                       答 12／静态 20、量的件=scripts/x.py、护栏 0 条 —— 少 8 条：跑到的跟静态那把尺数出来的不是同一份'
    >>> each_verdict("scripts/x.py", 8, ROUTE_RUNS, 0, GOOD)   # 跑到的比写下来的多
    '✗ scripts/x.py                       答 12／静态 8、量的件=scripts/x.py、护栏 0 条 —— 多 4 条：跑到的跟静态那把尺数出来的不是同一份'
    >>> each_verdict("scripts/x.py", 12, ROUTE_RUNS, 0,
    ...     GOOD.replace("量的件：scripts/x.py", "量的件：__main__"))      # 量错了件
    '✗ scripts/x.py                       答 12／静态 12、量的件=__main__、护栏 0 条 —— 量的不是自己：它报 __main__'
    >>> each_verdict("scripts/x.py", 12, ROUTE_RUNS, 1,
    ...     "合计 12 个用例，0 个失败（量的件：scripts/x.py）\\n"
    ...     "护栏：看见 3 条（open 3）、落在仓库里 2 条：写 data/x、写 config/y（被量件退 0）")
    '✗ scripts/x.py                       答 12／静态 12、量的件=scripts/x.py、护栏 2 条 —— 它去干了自己的活：写 data/x、写 config/y'
    >>> each_verdict("scripts/x.py", 12, ROUTE_RUNS, 2, "")    # 子进程压根没说话
    '✗ scripts/x.py                       没答（静态：走通，退 2） —— 护栏那一句没到屏幕上（子进程连 work_guard 都没跑起来？）；字还在、路已死：静态说「走通」，它一个字都没答'
    >>> each_verdict("scripts/x.py", 12, ROUTE_RUNS, None, "", cut=3)   # 被天花板掐掉
    '✗ scripts/x.py                       没答（静态：走通，被 3 秒的天花板掐掉） —— 超过 3 秒没回来，是这一遍自己掐的：那一个「没答」不是它没答'
    """
    got = parse_own_line(out)
    guard_n, guard_detail = parse_guard(out)
    problems: list[str] = []
    if cut is not None:
        # 天花板那一档：护栏那一句和本来的回答**都注定拿不到**，所以两句猜想在这一档都是假话
        # —— 「子进程连 work_guard 都没跑起来」与「字还在、路已死」都不许说。
        problems.append(f"超过 {cut} 秒没回来，是这一遍自己掐的：那一个「没答」不是它没答")
    elif guard_n is None and not GUARD_DEAD_RE.search(out):
        problems.append("护栏那一句没到屏幕上（子进程连 work_guard 都没跑起来？）")
    elif guard_n:
        problems.append(f"它去干了自己的活：{(guard_detail or f'{guard_n} 条')[:120]}")
    if got is None:
        if cut is None:
            note = f"没答（静态：{route}，退 {rc}）"
            if route == ROUTE_RUNS:
                problems.append(f"字还在、路已死：静态说「{ROUTE_RUNS}」，它一个字都没答")
            else:
                note += "、只有收集器跑得动它"
        else:
            note = f"没答（静态：{route}，被 {cut} 秒的天花板掐掉）"
    else:
        label, attempted, failed = got
        note = (f"答 {attempted}／静态 {want}、量的件={label}、"
                f"护栏 {'?' if guard_n is None else guard_n} 条")
        if attempted != want:
            gap = want - attempted
            problems.append(f"{'少' if gap > 0 else '多'} {abs(gap)} 条："
                            "跑到的跟静态那把尺数出来的不是同一份")
        if label != rel:
            problems.append(f"量的不是自己：它报 {label}")
        if failed:
            problems.append(f"用例里有 {failed} 个失败")
        elif rc and not guard_n:
            # 屏幕上一切都对、子进程却退非 0：那一句「全过」跟退码是两本账，得有一行说这事。
            problems.append(f"子进程退 {rc}，可它报的用例全过、护栏也没意见：这一档对不上")
        if route != ROUTE_RUNS:
            problems.append(f"静态那一档说「{route}」，可它答了：那把尺判错了")
    return ("✗ " if problems else "· ") + f"{rel:<34} {note}" + (
        " —— " + "；".join(problems) if problems else "")


def each_tally(total: int, answered: int, silent: int, bad: int, guarded: int) -> str:
    """那一屏收尾的一句合计。

    「没答」单独报数而不是混在「有毛病」里：那批纯库**本来就不该答**（§2.69 的
    「没有入口」那一档），把它们算成毛病就等于把上一节的读数又判红一遍；
    可它们必须写在屏幕上，因为「册上几件、其中几件这一遍是白跑」只有那一句能说出来。
    这一句里五个数全部来自递进来的参数（没有一个是从说明书里抄的），所以
    「在册件数」这件事在本件里只写在一处：`each_file` 的那条用例。

    >>> each_tally(29, 18, 11, 0, 0)
    '合计 29 件：答 18 件、没答 11 件；用例数与静态全对上、护栏一件都没拦下'
    >>> each_tally(29, 18, 11, 3, 2)
    '合计 29 件：答 18 件、没答 11 件；3 件有毛病，其中 2 件是护栏拦下来的'
    """
    if not bad:
        return (f"合计 {total} 件：答 {answered} 件、没答 {silent} 件；"
                "用例数与静态全对上、护栏一件都没拦下")
    tail = f"，其中 {guarded} 件是护栏拦下来的" if guarded else ""
    return f"合计 {total} 件：答 {answered} 件、没答 {silent} 件；{bad} 件有毛病{tail}"


def spawn_each(path: pathlib.Path, argv: tuple[str, ...] = (DOCTEST_FLAG,),
               base: pathlib.Path = ROOT, timeout: int = EACH_TIMEOUT
               ) -> tuple[int | None, str, str]:
    """在护栏底下起一个子进程真跑这一件，返回（它的退码，它的 stdout，它的 stderr）。

    没有 doctest：这一句要起进程。判据全部在上面那三层（`parse_own_line`／`parse_guard`／
    `each_verdict`），它们都能拿一段假输出喂 —— 这一句只负责「真跑」。
    盯着这一句的是下面 `BASELINE` 那一串格子（2.74 起）：它们是真的往临时目录里种假件、
    真的起子进程，量的就是「这一句递出去的东西到不到得了屏幕上」。

    `base` 是「哪一棵树」：`path` 的相对名字按它算、子进程的 `cwd` 设成它、
    而护栏护的也是它（`--root=` 那一位）。递本仓库时三者与 2.74 之前逐字相同。
    换一棵树时**护栏不换**：仍然用 `ROOT/scripts/work_guard.py` 那一柄 —— 护哪棵树与
    用哪一柄是两件事，而基线要的就是「拿仓库里这一柄真护栏去量沙盒里那一件」。

    两个细节是有原因的：
    * `PYTHONDONTWRITEBYTECODE=1` —— 不递的话子进程往 `.venv` 掉 `.pyc`，
      `names` 那把尺当场涨（2.56 记过的那一格：871 与 891 的差就是这么来的）。
    * `-X utf8` —— 跟这个仓库里每一条写进文档的命令一致；不带的话在
      `LANG` 不是 UTF-8 的 shell 里，那些中文说明书会变成 `UnicodeDecodeError`。

    退码那一位**只有天花板这一档会是 `None`**（真进程被信号打死时 `subprocess` 给的是
    负数，拿 `-1` 当哨兵会跟 SIGHUP 撞车 —— 本节头一版就是这么写的）。
    「超过 N 秒没回来」那一句话在这里一个字都不拼：它归 `each_verdict` 说（2.58
    「一条规矩两个人各写一遍」——上一版在这里拼好了塞进 `out`，于是它永远到不了屏幕）。
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "work_guard.py"),
           f"--root={base}", str(path.relative_to(base)), *argv]
    try:
        p = subprocess.run(cmd, cwd=base, capture_output=True, text=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        def txt(v: str | bytes | None) -> str:
            return v if isinstance(v, str) else (v or b"").decode("utf-8", "replace")
        return None, txt(e.stdout), txt(e.stderr)      # 掐掉之前已经印出来的那些字要留着
    return p.returncode, p.stdout, p.stderr


def roster_dirs(root: pathlib.Path = ROOT) -> tuple[pathlib.Path, ...]:
    """`root` 那棵树里「哪几级算在册范围」：`scripts/` 与 `src/`，不存在的那一级不递。

    为什么不递一份不存在的目录：`each_file` 对空目录回空表，于是「这棵树里根本没有
    `scripts/`」与「有，可里面一件写了用例的都没有」会同形。拿掉不存在的那一级之后，
    两种都会走到「一件都没挑出来」那一句，而**那一句自己把在册范围摊出来**（见 `run_each`）。

    >>> roster_dirs(ROOT) == DEFAULT_DIRS
    True
    >>> roster_dirs(pathlib.Path("/tmp/没有这样一棵树"))
    ()
    """
    return tuple(d for d in (root / "scripts", root / "src") if d.is_dir())


def scope_note(root: pathlib.Path) -> str:
    """换了一棵树来量时，那一屏收尾必须自己说一句「这不是本仓库」。

    为什么要它：`--each` 那一屏每一行都印 `scripts/x.py` 这种相对名字，而沙盒里种的假件
    **也叫** `scripts/x.py` —— 少了这一句，一份沙盒读数能被当成仓库读数抄进履历
    （§2.61 那条「截断要自报」换到「名单出自哪棵树」这一维上的第一次用）。

    >>> scope_note(ROOT)                                       # 默认那一遍：一个字都不许多说
    ''
    >>> scope_note(pathlib.Path("/tmp/沙盒"))
    '在册范围不是本仓库，是 /tmp/沙盒 —— 上面那两行的「N 件」说的都是这一棵，不是仓库'
    """
    if root == ROOT:
        return ""
    return f"在册范围不是本仓库，是 {root} —— 上面那两行的「N 件」说的都是这一棵，不是仓库"


def scope_names(dirs: tuple[pathlib.Path, ...], root: pathlib.Path) -> str:
    """「一件都没挑出来」那一句里的在册范围：给了路径就摊，一级都没有就说人话。

    >>> scope_names(DEFAULT_DIRS, ROOT)
    'scripts/、src/'
    >>> scope_names((), pathlib.Path("/tmp/沙盒"))               # 那两棵子目录都不在
    '/tmp/沙盒 里没有 scripts/ 或 src/'
    """
    if dirs:
        return "、".join(f"{d.relative_to(root)}/" for d in dirs)
    return f"{root} 里没有 scripts/ 或 src/"


def run_each(pattern: str = "", root: pathlib.Path = ROOT, timeout: int = EACH_TIMEOUT) -> int:
    """`--each` 那一档：逐件真跑，屏幕上那一屏就是本件的产物。

    为什么这一档不进 `selfcheck.py`：它要为册上每一件起一个进程（整册一遍的实耗时抄在
    `EACH_TIMEOUT` 那一段注释里，两棵树的对照也在 —— 那里有一份就够，2.58），而自检那一屏
    的规矩是「每一条都要有理由」；更要紧的是
    它会把每一件自己的 stdout 再过一遍 —— 中性那一遍就不中性了。它是**手跑的**：
    改完一批门之后自己去看一眼。（下面 `self_test` 那一串格子走的是同一扇门，只是每格一件假件。）

    `root` 换的是量哪一棵树（`--root=`），`timeout` 换的是一件的天花板（`--timeout=`）：
    两个都是**为了能被量**才递出来的 —— 沙盒里那一格「它不返回」若要钉住，
    没有 `timeout` 就得让基线真等一分钟。

    退码按 2.62 那三档：**2** = 护栏那一句一件都没读到（什么都没量到，包括「护栏没意见」
    这一条都没读到）、或一件都没挑出来；**1** = 有毛病；**0** = 全对且全读到。
    """
    dirs = roster_dirs(root)
    rows = each_targets(pattern, dirs, root)
    if not rows:
        print(f"✗ 一件都没挑出来（过滤器 {pattern!r}、在册范围 {scope_names(dirs, root)}）"
              "—— 这一遍什么都没量到", file=sys.stderr)
        return 2
    print(f"逐件真跑 `{DOCTEST_FLAG}`（{len(rows)} 件，每件一个子进程、"
          f"都挂在 scripts/work_guard.py 底下）")
    bad = answered = silent = guarded_files = no_guard = 0
    for path, want, route in rows:
        rel = str(path.relative_to(root))
        rc, out, err = spawn_each(path, base=root, timeout=timeout)
        line = each_verdict(rel, want, route, rc, out, cut=timeout if rc is None else None)
        print(line)
        if parse_own_line(out) is None:
            silent += 1
        else:
            answered += 1
        n, _ = parse_guard(out)
        if n is None:
            no_guard += 1
            if err.strip():                       # 护栏那句都没读到，stderr 是那唯一的一点线索
                print(f"    它那边的 stderr 第一行："
                      f"{(err.splitlines() or [''])[0][:150]}")
        elif n:
            guarded_files += 1
        if line.startswith("✗"):
            bad += 1
    print(each_tally(len(rows), answered, silent, bad, guarded_files))
    note = scope_note(root)
    if note:
        print(note)
    if no_guard == len(rows):
        print("✗ 护栏那一句一件都没读到 —— 这一遍什么都没量到，不算「全过」")
        return 2
    return 1 if bad else 0


SELF_TEST_FLAG = "--self-test"


def each_options(raw: list[str]) -> tuple[dict, list[str], list[str]]:
    """认 `--each` 后面那几个字：返回（递进 `run_each` 的 kwargs, 位置参数, 认不出的那些）。

    只认 `--root=<路径>` 与 `--timeout=<秒>` 两式，而且**只认带 `=` 的那一种**。不给空格那一式
    留位置的理由和 `work_guard.split_at_target` 是同一条：这一档剩下的字要当过滤器用，
    而 `--root /tmp/x` 里那个路径「不像旗」，它会当场变成过滤器 —— 屏幕上出来一句
    「一件都没挑出来（过滤器 '/tmp/x'）」，把人支到过滤器上去，真正没接上的是我的参数。

    认不出的那一半是这一句最要紧的产物。改之前 `--each` 后面凡是带 `-` 的字都被**丢掉**，
    于是 `--each --rooot=/tmp/沙盒`（打错一个字母）会被当成「没给过滤器」，
    安安稳稳去跑**本仓库那一整册** —— 一句打错的旗标换来一屏看着像沙盒、其实是仓库的读数。
    现在那种字一律退 2 并点名（下面 `未_打错的旗标` 那一格钉的就是它不许跑起来）。

    >>> each_options(["abc"])
    ({}, ['abc'], [])
    >>> each_options(["--root=/tmp/x", "guard"])
    ({'root': PosixPath('/tmp/x')}, ['guard'], [])
    >>> each_options(["--timeout=2"])
    ({'timeout': 2}, [], [])
    >>> each_options(["--rooot=/tmp/x"])                     # 打错：不丢、不当过滤器
    ({}, [], ['--rooot=/tmp/x'])
    >>> each_options(["--timeout=abc"])                      # 秒数不是一个数：也点名
    ({}, [], ['--timeout=abc'])
    >>> each_options(["--root="])                            # 空路径：不许退化成「用默认」
    ({}, [], ['--root='])
    >>> each_options([])
    ({}, [], [])
    """
    opts: dict = {}
    rest: list[str] = []
    bad: list[str] = []
    for a in raw:
        if not a.startswith("-"):
            rest.append(a)
            continue
        key, eq, val = a.partition("=")
        if not eq:
            bad.append(a)
        elif key == "--root" and val:
            opts["root"] = pathlib.Path(val)
        elif key == "--timeout" and val.isdigit():
            opts["timeout"] = int(val)
        else:
            bad.append(a)
    return opts, rest, bad


# ———— 沙盒里那几份假件的收尾 ————
# 每段只写「跑起来做什么」，说明书和那道门由下面的 `fake()` 统一拼上。
# 为什么门要自带一份（而不是 `from run_doctests import run_own`）：护栏特意把仓库那两级
# 从 `sys.path` 里拿掉（`work_guard.run` 的第二条规矩），沙盒里的假件 import 不到本件 ——
# 那正是它该有的样子：一件被量脚本能看见哪些路，由它自己的位置决定，不由我的基线替它铺平。
RUNS_TAIL = 'if __name__ == "__main__":\n' \
            '    raise SystemExit(run_own(sys.modules["__main__"], here()))\n'
DEAD_TAIL = 'WANTS = False                # 变异机 M16 那一刀的形状：门还在、路被按住了\n' \
            'if __name__ == "__main__":\n' \
            '    if WANTS:\n' \
            '        raise SystemExit(run_own(sys.modules["__main__"], here()))\n'
SILENT_TAIL = 'if __name__ == "__main__":\n' \
              '    os._exit(0)            # 整个进程当场没了：连护栏那一句都来不及印\n' \
              '    raise SystemExit(run_own(sys.modules["__main__"], here()))\n'
SLEEP_TAIL = 'if __name__ == "__main__":\n' \
             '    import time\n' \
             '    time.sleep(60)\n' \
             '    raise SystemExit(run_own(sys.modules["__main__"], here()))\n'
WRITE_TAIL = 'if __name__ == "__main__":\n' \
             '    open("touched.txt", "w").write("x")\n' \
             '    raise SystemExit(run_own(sys.modules["__main__"], here()))\n'
EXIT3_TAIL = 'if __name__ == "__main__":\n' \
             '    run_own(sys.modules["__main__"], here())\n' \
             '    raise SystemExit(3)\n'
ZERO_TAIL = 'import types\n' \
            'if __name__ == "__main__":\n' \
            '    raise SystemExit(run_own(types.ModuleType("一份用例都没有的假件"), here()))\n'
LIB_TAIL = ''                                      # 纯库：没有入口，跑它 = 静默退 0
ANSWER_NO_MAIN = 'run_own(sys.modules["__main__"], here())\n'   # 静态说没入口、它却答了

DOOR = '''import doctest, os, sys


def run_own(mod, label):
    res = doctest.testmod(mod)
    print(f"合计 {res.attempted} 个用例，{res.failed} 个失败（量的件：{label}）")
    return 1 if res.failed else (2 if not res.attempted else 0)


def here():
    return os.path.relpath(os.path.abspath(__file__))
'''


def fake(examples: int, tail: str, more_doc: str = "") -> str:
    r"""拼一份沙盒里的假件：`examples` 句**真会过**的用例 + 那道会答的门 + 递进来的收尾。

    为什么要拼、不逐格手写整份源：格子之间的差别只在收尾那几行（答不答、答的数对不对、
    动没动盘），说明书和那道门每一格都一样 —— 写一遍就少一处抄错（2.58 那一族）。

    `examples` 那几句子是 `1 + 1` 配 `2` 这种真会过的，所以「跑到的条数」与
    「静态数出来的条数」天生相等；要造「少 N 条」「多 N 条」那两格，改的是收尾里印出去的
    那个数，不是说明书。这一点要紧：那两格钉的是**两个数不一致**，若让说明书跟着一起改，
    静态那一层也动了，量的就不再是同一件事。

    上面这些源全部待在**普通字符串**里，一句都不写进任何 docstring —— 写进去就会被
    `example_count` 数成本件的用例、被 doctest 当成本件的例子跑一遍（§2.67 那一族：
    举例的字面量会被自己的尺读到，这次读的是自己）。

    >>> example_count(fake(3, ""))                          # 静态那把尺看见几条，就是几条
    3
    >>> has_main_block(fake(1, RUNS_TAIL))                   # 递了收尾：有入口
    True
    >>> has_main_block(fake(1, LIB_TAIL))                    # 什么都没递：纯库
    False
    >>> route_shape(fake(1, RUNS_TAIL))
    '走通'
    >>> route_shape(fake(1, DEAD_TAIL))                      # 门被按住那一格：静态照样认「走通」
    '走通'
    >>> route_shape(fake(1, LIB_TAIL))
    '没有入口'
    >>> route_shape(fake(1, ANSWER_NO_MAIN))                 # 答了、可静态看不见入口
    '没有入口'
    """
    body = "".join(f">>> {i} + 1\n{i + 1}\n" for i in range(1, examples + 1))
    return f'"""{examples} 句用例：\n{body}{more_doc}"""\n{DOOR}{tail}'


def liar(count: int) -> str:
    """收尾里印一个**凭空的**条数、量的件报得对：造「少 N 条」「多 N 条」那一族。

    >>> example_count(fake(2, liar(9)))                     # 静态 2 条，屏幕上报 9
    2
    """
    return ('if __name__ == "__main__":\n'
            f'    print("合计 {count} 个用例，0 个失败（量的件：%s）" % here())\n')


def wrong_label(count: int = 1) -> str:
    """条数对、可「量的件」报的不是它自己：2.68 那句「不点名就量了调用方」在这一层的形状。

    >>> example_count(fake(1, wrong_label(1)))
    1
    """
    return ('if __name__ == "__main__":\n'
            f'    print("合计 {count} 个用例，0 个失败（量的件：不是它自己）")\n')


def hide_tmp(text: str, base: pathlib.Path) -> str:
    """把沙盒那一路径换成 `<T>`，让格子的期望不随临时目录变。

    两种写法都换：`/var/…` 与它 `realpath` 之后的 `/private/var/…` —— macOS 的
    `tempfile` 给前者、`os.getcwd()` 报后者，只换一种会让同一格在两种读数下各红一次。

    >>> hide_tmp("写 /var/x/touched.txt", pathlib.Path("/var/x"))
    '写 <T>/touched.txt'
    """
    for form in {str(base), str(pathlib.Path(base).resolve())}:
        text = text.replace(form, "<T>")
    return text


class Cell(NamedTuple):
    """一格：往沙盒里种哪几份假件、怎么问它、屏幕上该有什么、不该有什么。

    与 `table_drift.Cell`／`lean_playlist.Cell` 同一族（**不在这里 import 它们**：
    `doc_num` 在顶上 import 本件，本件回头 import `doc_num` 就是绕环 —— 那两把也各自
    带了一份，2.65 立过这个先例）。形状只多一位 `files`：这一把种的假件是 .py 源码，
    每一格要的差别全在那几行上。
    """

    who: str                                  # 格子名（顿号那道闸在 `self_test` 里问）
    what: str                                 # 给人看的那一句：这一格量的是哪件事
    rc: int                                   # 期望退码（2.62 那三档）
    files: tuple[tuple[str, str], ...] = ()   # (相对沙盒的路径, 源码)
    argv: tuple[str, ...] = ("--each", "--root={T}")
    has: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()


CELL_SRC = "scripts/good.py"                  # 绝大多数格子里那一件假件待的地方
CELL_LIB = "scripts/lib.py"                   # 纯库那一件：同一棵沙盒，另一档


BASELINE: tuple[Cell, ...] = (
    # ———— 甲／乙／丙：三档「都对」，先钉住那一屏在无事可报时长什么样 ————
    Cell("甲_答了且全对上", "常态：一件答了自己的条数、静态跟它一样、护栏没意见 → 退 0",
         0, files=((CELL_SRC, fake(2, RUNS_TAIL)),),
         has=("逐件真跑", "（1 件", "· scripts/good.py", "答 2／静态 2",
              "合计 1 件：答 1 件、没答 0 件；用例数与静态全对上、护栏一件都没拦下"),
         lacks=("✗", "有毛病", "不是本仓库的")),
    Cell("乙_两件一答一没答", "册上几件由那一遍自己数：一件走通、一件纯库，两个数各归各",
         0, files=((CELL_SRC, fake(1, RUNS_TAIL)), (CELL_LIB, fake(3, LIB_TAIL))),
         has=("（2 件", "合计 2 件：答 1 件、没答 1 件", "只有收集器跑得动它",
              "在册范围不是本仓库"),
         lacks=("✗", "有毛病")),
    Cell("丙_整册都是白跑", "答 0 件、却仍退 0：护栏那一句读到了，这一遍量到的是「它没答」",
         0, files=((CELL_LIB, fake(3, LIB_TAIL)),),
         has=("合计 1 件：答 0 件、没答 1 件", "只有收集器跑得动它"),
         lacks=("✗", "一件都没读到", "有毛病")),
    # ———— 丁／戊：两头都判 —— 静态说它答而它不答，与静态说它不答而它答了 ————
    Cell("丁_字还在路已死", "M16 那一刀的实物：静态认「走通」、跑起来一个字都不答",
         1, files=((CELL_SRC, fake(2, DEAD_TAIL)),),
         has=("✗ scripts/good.py", "字还在、路已死", "1 件有毛病"),
         lacks=("只有收集器跑得动它", "一件都没读到")),
    Cell("戊_静态那把尺判错", "反方向：静态说「没有入口」，可它答了 —— 那是那把尺错了",
         1, files=((CELL_SRC, fake(1, ANSWER_NO_MAIN)),),
         has=("那把尺判错了", "1 件有毛病"),
         lacks=("字还在、路已死",)),
    # ———— 己／庚／辛／壬／癸：答了，可答的不是「它自己那一份全对的用例」 ————
    Cell("己_跑到比写的少", "跑到的条数比静态数出来的少 3 条（新增的例子没接进自己那条路）",
         1, files=((CELL_SRC, fake(5, liar(2))),),
         has=("少 3 条", "跑到的跟静态那把尺数出来的不是同一份"), lacks=("多 3 条",)),
    Cell("庚_跑到比写的多", "反方向：屏幕上比静态多 7 条 —— 静态那把尺漏看了东西",
         1, files=((CELL_SRC, fake(2, liar(9))),),
         has=("多 7 条",), lacks=("少 7 条",)),
    Cell("辛_量的不是自己", "条数全对、可「量的件」报的是别人：2.68 那句「量了调用方」",
         1, files=((CELL_SRC, fake(1, wrong_label(1))),),
         has=("答 1／静态 1", "量的不是自己：它报 不是它自己"),
         lacks=("少 1 条", "多 1 条")),
    Cell("壬_用例里有失败", "一件自己的用例红了：那一行要说得出失败几条，不许读成「没答」",
         1, files=((CELL_SRC, fake(1, RUNS_TAIL, ">>> 6 + 1\n8\n")),),
         has=("用例里有 1 个失败", "答 2／静态 2"),
         lacks=("没答（静态", "少 1 条")),
    # 本格种的假件自己 `raise SystemExit(3)`，屏幕上却读成「退 1」——那不是格子写错：
    # 护栏那一柄按 §2.62 把退码归了档（`verdict_code`：任何非 0 → 1，只有「根本没跑起来」→ 2），
    # 而 `--each` 那一层拿到的正是归过档的那一个。被量件原本那个数在护栏自己那一行里
    # （`…（被量件退 3）`），本件的屏幕不摊它。钉「1」钉的是**这一屏实际说出口的话**；
    # 若要钉 3，得让护栏放行原码或让 `parse_guard` 把那个数摊上来 —— 那是另一件事，本节不做。
    Cell("癸_退码与屏幕对不上", "屏幕上一切全对、被量件却退非 0：那是两本账，得有一行说这事",
         1, files=((CELL_SRC, fake(1, EXIT3_TAIL)),),
         has=("子进程退 1，可它报的用例全过、护栏也没意见：这一档对不上",),
         lacks=("用例里有 1 个失败",)),
    Cell("子_零条不等于没答", "它答了一句「一条用例都没收到」：那是带着名字的 0，不是没开口",
         1, files=((CELL_SRC, fake(1, ZERO_TAIL)),),
         has=("答 0／静态 1", "少 1 条", "跑到的跟静态那把尺数出来的不是同一份"),
         lacks=("只有收集器跑得动它", "没答（静态")),
    # ———— 丑：护栏那一头 —— 它动了盘，屏幕上那一句必须把它读成毛病 ————
    Cell("丑_它去干了自己的活", "递 `--doctest` 给它、它顺手往被护的那棵树里写了个文件",
         1, files=((CELL_SRC, fake(1, WRITE_TAIL)),),
         has=("护栏 1 条", "它去干了自己的活：写 touched.txt", "其中 1 件是护栏拦下来的"),
         lacks=("护栏一件都没拦下",)),
    # ———— 寅／卯：两种「子进程没把话说完」，一档退 2、一档退 1 ————
    Cell("寅_护栏那句没到屏幕上", "整件进程当场没了：护栏、用例一句都没印 → 这一遍什么都没量到，退 2",
         2, files=((CELL_SRC, fake(1, SILENT_TAIL)),),
         has=("护栏那一句没到屏幕上", "字还在、路已死", "护栏那一句一件都没读到"),
         lacks=("用例数与静态全对上",)),
    Cell("卯_一件不返回", "天花板那一档：一件卡住不许拖着整屏 —— 掐掉它、那一行照样落下来",
         1, files=((CELL_SRC, fake(1, RUNS_TAIL)), ("scripts/sleeper.py", fake(1, SLEEP_TAIL))),
         argv=("--each", "--root={T}", "--timeout=1"),
         has=("超过 1 秒没回来", "被 1 秒的天花板掐掉", "合计 2 件：答 1 件、没答 1 件",
              "1 件有毛病"),
         lacks=("一件都没读到", "子进程连 work_guard 都没跑起来", "字还在、路已死")),
    # ———— 辰／巳：两种「什么都没量到」的 2，差别在范围不在过滤器 ————
    Cell("辰_过滤器没挑中", "过滤器给得太严：一句都没量到，那一句要说出用的哪个过滤器",
         2, files=((CELL_SRC, fake(1, RUNS_TAIL)),),
         argv=("--each", "--root={T}", "没有这样一个件"),
         has=("一件都没挑出来", "过滤器 '没有这样一个件'", "这一遍什么都没量到"),
         lacks=("逐件真跑",)),
    Cell("巳_那棵树没有在册范围", "换了一棵根本没有 `scripts/` 的树：范围要说出来，不甩给过滤器",
         2, argv=("--each", "--root={T}"),
         has=("一件都没挑出来", "里没有 scripts/ 或 src/"),
         lacks=("逐件真跑", "Traceback")),
    # ———— 午／未：旗标那一层 —— 这一屏是本件唯一的「旗标登记处」 ————
    Cell("午_不认的旗标", "递一个没收过的旗标：要说清收哪几个，那一句就是本件的登记处",
         2, argv=("--nope",),
         has=("我不收这个旗标", "--each", "--self-test", "--root=", "--timeout="),
         lacks=("Traceback", "一件都没找到")),
    Cell("未_打错的旗标", "`--each` 后面打错一个字母：不许当成没给过滤器去跑仓库那一整册",
         2, argv=("--each", "--rooot={T}"),
         has=("我不收这个旗标", "--rooot"), lacks=("逐件真跑", "合计")),
)


# 那一屏能说的每一句话 —— 每一句都得有至少一格钉着。
# 为什么把名单写下来单独问一句：本节装基线要办的就是 §2.71 那笔账（一条判决今天没有实例
# ＝ 等同没测）。格子写全了没有？光靠一句「我把每一句都钉上了」的人话查不动，
# 而数格子数也查不动（格子多一格、判决少一句，两边照样对得上）。
# 配上下面这道预跑闸，一句判决没人钉了就当场红在**预跑**那一步（退 2、一句都没跑），
# 而不是等到某一天那一句判决没字了才发现。
# 这道闸的**范围**本节先量过再写：它看的是句子，不是格子 —— 删掉一格而那句话别处还有格钉着，
# 它不响（下面 `gate_blindness` 逐格删一遍现数，屏幕上自己报）。本节头一版把这道闸写成
# 「删掉任何一格都会红」，14:42 那一遍探针（删 `丁`）两面全绿，就是这么把它推翻的。
VERDICT_LINES: tuple[str, ...] = (
    "字还在、路已死", "只有收集器跑得动它", "那把尺判错了",
    "跑到的跟静态那把尺数出来的不是同一份", "量的不是自己", "用例里有",
    "可它报的用例全过、护栏也没意见", "它去干了自己的活", "护栏那一句没到屏幕上",
    "一件都没挑出来", "护栏那一句一件都没读到", "用例数与静态全对上、护栏一件都没拦下",
    "是护栏拦下来的", "没回来", "我不收这个旗标", "在册范围不是本仓库",
)


def coverage_gaps(cells: tuple[Cell, ...],
                  lines: tuple[str, ...] = VERDICT_LINES) -> list[str]:
    """那些句话里，没有任何一格在 `has` 里钉过的 —— 应该是空表。

    只往 `has` 里找，不往 `lacks` 里找：`lacks` 钉的是「这句不许出现」，一句从没出现过
    的判决不算有实例。

    >>> coverage_gaps((Cell("好", "x", 0, has=("字还在、路已死", "其余那句")),),
    ...               ("字还在、路已死",))
    []
    >>> coverage_gaps((), ("字还在、路已死",))
    ['字还在、路已死']
    >>> coverage_gaps(BASELINE)                                   # 本件的基线：一句都不许漏
    []
    """
    pinned = "".join("".join(c.has) for c in cells)
    return [line for line in lines if line not in pinned]


def gate_blindness(cells: tuple[Cell, ...],
                   lines: tuple[str, ...] = VERDICT_LINES) -> list[str]:
    """逐格删一遍：删掉哪一格，`coverage_gaps` 不响。返回那些格子的名字。

    为什么量这个：上一节（2.73）记过「两个方向都会漏，而漏的方向不一样」，本节是同一族 ——
    一道「每句判决都有格钉着」的闸，天然看不见**冗余**那一头的格子。它不是毛病：
    同一句判决可以由两格钉（`丁` 量那句话怎么说、`寅` 量它到不到屏幕上），
    所以要钉住的是**这一格独占的东西**。本节把这件事从「闸能不能替我兜住」改成
    「闸自己说它兜住了几格」（下面 `self_test` 结论那一句），漏的那一头交给
    `claims`：它拿 `selfcheck.py:steps` 里「种 N 格」那句对 `len(BASELINE)`，格子一少就红。

    与 `coverage_gaps` 一样是纯内存的算法：每删一格重问一遍那道闸，不起子进程。

    >>> two = (Cell("甲", "x", 0, has=("那把尺判错了",)),
    ...        Cell("乙", "y", 0, has=("那把尺判错了", "只有乙钉着的那句")))
    >>> gate_blindness(two, ("那把尺判错了",))     # 这一句两格都钉：删谁都不响
    ['甲', '乙']
    >>> gate_blindness(two, ("只有乙钉着的那句",))  # 只问那一句：删甲不响，删乙会响
    ['甲']
    >>> gate_blindness((), VERDICT_LINES)          # 一格都没有：没有格子可谈可见不可见
    []
    """
    return [c.who for c in cells
            if not coverage_gaps(tuple(d for d in cells if d is not c), lines)]


def sloppy_cells(cells: tuple[Cell, ...]) -> list[str]:
    """格子自己写歪的地方：占位符串错位、同一句又 `has` 又 `lacks`、一句都没钉、
    种的假件根本不入册。

    最后那一条是本件特有的一族：`each_file` 只认「写了用例、文件名像模块名」的 .py，
    所以一格若种了一份零用例的假件，它会**整格空转** —— 一件都没挑出来、退 2、
    而那句 2 看着像判据在响。跑之前先按同一把尺（`example_count`）量一遍种下去的东西。

    第一条（形状）不是防别人：本节头一版十八格里有**六格**把 `lacks=("一句")` 写掉了逗号，
    而那不是「少一个元组」那么轻 —— 字符串是可迭代的，于是那一格逐**字**去比，
    `lacks=("字还在、路已死",)` 变成「这一屏不许出现『字』这个字符」。写掉逗号的那一版
    在 14:2x 那一遍直接崩在 `TypeError` 上（算它运气好）；把形状写成一条闸之后，
    它连崩都不会崩、只会红得莫名其妙。

    >>> sloppy_cells((Cell("好", "x", 0, files=((CELL_SRC, fake(1, RUNS_TAIL)),),
    ...                    has=("答 1／静态 1",)),))
    []
    >>> for why in sloppy_cells((Cell("坏", "x", 0, has=("{T}/a",), lacks=("没有",)),)):
    ...     print(why)
    坏：`has` 里写了 `{T}`，argv 才用这个占位符，屏幕上的路径要写 `<T>`
    >>> for why in sloppy_cells((Cell("撞", "x", 0, has=("一句",), lacks=("一句",)),)):
    ...     print(why)
    撞：同一句既是 `has` 又是 `lacks`，这一格永远不可能过
    >>> for why in sloppy_cells((Cell("空", "x", 0),)):            # 只比退码：不算量过一件事
    ...     print(why)
    空：这一格一句都没钉，只比退码 —— 那是「跑过一遍」不是「量过一件事」
    >>> for why in sloppy_cells((Cell("散", "x", 0, lacks=("一句")),)):
    ...     print(why)
    散：`lacks` 写的是一句**字符串**而不是一句的元组（少一个逗号）—— 它会逐字去比
    >>> for why in sloppy_cells((Cell("哑", "x", 0, files=((CELL_SRC, "print(1)"),),
    ...                             has=("答",)),)):
    ...     print(why)
    哑：种的假件 scripts/good.py 一条用例都没写 —— 它不入册，这一格会整格空转
    """
    out: list[str] = []
    for c in cells:
        for field in ("has", "lacks"):
            if isinstance(getattr(c, field), str):
                out.append(f"{c.who}：`{field}` 写的是一句**字符串**而不是一句的元组"
                           "（少一个逗号）—— 它会逐字去比")
        if any("{T}" in s for s in tuple(c.has) + tuple(c.lacks)):
            out.append(f"{c.who}：`has` 里写了 `{{T}}`，argv 才用这个占位符，"
                       "屏幕上的路径要写 `<T>`")
        both = set(c.has) & set(c.lacks)
        if both:
            out.append(f"{c.who}：同一句既是 `has` 又是 `lacks`，这一格永远不可能过")
        if not (c.has or c.lacks):
            out.append(f"{c.who}：这一格一句都没钉，只比退码 —— 那是「跑过一遍」不是「量过一件事」")
        for rel, src in c.files:
            if not example_count(src):
                out.append(f"{c.who}：种的假件 {rel} 一条用例都没写 —— 它不入册，这一格会整格空转")
    return out


def run_cell(cell: Cell, base: pathlib.Path) -> tuple[str, str, str]:
    """跑一格：`(判定, 给人看的那句, 抹过沙盒路径的原文)`，判定是 `ok` / `bad`。

    走的是真的 `main()` 而不是 `run_each`：`--each` 那一档怎么被认、`--root=` 怎么递下去、
    那句合计排在哪儿，全是这一格要看的东西（2.56 起的同一取舍）。
    stdout 与 stderr 收进**同一个**缓冲区：那两「件都没挑出来」的句子在 stderr 上。
    """
    for rel, body in cell.files:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    argv = [a.replace("{T}", str(base)) for a in cell.argv]
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
    """这一格对上了没有：退码、该出现的句子、不该出现的句子。

    `lacks` 与 `has` 一样重要：`丑` 那一格若只钉「护栏 1 条」，而不钉「护栏一件都没拦下」
    那句不许出现，那它在护栏压根没意见的一遍里也会过 —— 而那正是本节要拦的形状。
    """
    if rc != cell.rc:
        return False, f"退码：期望 {cell.rc}，实际 {rc}"
    for s in cell.has:
        if s not in text:
            return False, f"屏幕上没有那句：{s}"
    for s in cell.lacks:
        if s in text:
            return False, f"多说了那句：{s} —— 误伤"
    return True, ""


def self_test(cells: tuple[Cell, ...] | None = None) -> int:
    """`--self-test`：往临时目录里种假件，把 `--each` 那一整条路**真跑一遍**。

    与其余那九把基线同一笔账（§2.71）：`--each` 那一屏收尾那句「合计 N 件：答 N 件、没答 N 件；
    用例数与静态全对上」有两种读法 —— 那一屏里每一句判决都句句在响、或者一条都不咬。
    （那句读数里的数**不写在这里**：它是那一遍数出来的，写进说明书就变成一处没人查的化石 ——
    本节的在册件数只钉在 `each_file` 那一条用例里。）
    钉它的不是本件那 100 多条 doctest（它们喂的是**假输出**，跳过了起进程、递旗标、
    读护栏、数合计那四层），是下面这些格子：每格一个新沙盒、种一份假件、起一个真子进程。

    每格单独一个临时目录是 2.63 踩的第 5 条换来的（同一秒、同字节数的两份改动会互相拿到）。

    跑之前三道预跑闸，任何一种都退 2 且**一格都不跑**：格子名带顿号（那一行「不符的格」
    分不开，2.58）、格子自己写歪（`sloppy_cells`）、判决名单里有哪一句没人钉
    （`coverage_gaps`）—— 第三道是本节新添的那一位，理由写在它自己的说明里。

    退码：0 = 每格都符合期望；1 = 有格子不符（逐格点名）；2 = 一格都没跑，或基线自己写歪了。
    """
    from baseline_guard import guard as guard_names   # 在函数里 import：理由见 `Cell` 那段

    cells = BASELINE if cells is None else cells
    bad_names = guard_names([c.who for c in cells])
    if bad_names:
        print(bad_names)
        return 2
    sloppy = sloppy_cells(cells)
    if sloppy:
        print("基线自己有格子写歪了，改的是基线、不是判据：\n  " + "\n  ".join(sloppy))
        return 2
    gaps = coverage_gaps(cells)
    if gaps:
        print("有判决一句都没格钉着（§2.71：今天没有实例的判决等同没测）：\n  "
              + "\n  ".join(gaps))
        return 2
    blind = len(gate_blindness(cells))      # 那道闸自己说不响的那一头，跟着真基线现算
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    for cell in cells:
        with tempfile.TemporaryDirectory(prefix="run-doctests-selftest-") as td:
            verdict, why, text = run_cell(cell, pathlib.Path(td))
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
          + (f" —— {len(VERDICT_LINES)} 句判决各有格子钉着；"
             f"那道预跑闸看的是句子，逐格删一遍它响 {len(cells) - blind} 次、不响 {blind} 次"
             if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


def refusal(given: str, bad: list[str] | None = None) -> str:
    """「这个旗标我不收」那一句 —— 本件唯一的旗标登记处。

    为什么单独抽成一个函数：这一句就是本件的 `--help`。2.69 记过那条理由（命令尺拿文档里
    每一条长参数去问 `--help`，所以「只写在收尾、`--help` 里没有」会被读成「照抄会失败」），
    而本件**故意没有 argparse** —— 它收一个位置参数当过滤器，挂一把握关就得为了两个旗
    重写整个入口（`check_doc_cmds` 里那句「目标脚本没建关」的豁免认的就是这件事）。
    登记处塌缩成这一句之后，「添了旗标忘改这一句」就等于那一旗没人知道存在 ——
    所以 `午_不认的旗标` 那一格逐条钉着它，而不是钉一份 nobody 读的清单。

    `bad` 是 `--each` 后面那几个认不出的字（可以不止一个）；不递时就是开头那一个。

    >>> refusal("--nope").splitlines()[0]
    "✗ 我不收这个旗标（给的是 '--nope'）。收的只有这几个：`--each`（每件一个子进程真跑）、`--self-test`（跑本件的基线）、`--doctest`（只跑本件那份用例）；`--each` 后面还可以跟 `--root=<路径>`（量另一棵树）与 `--timeout=<秒>`（一件的天花板）。"
    >>> refusal("--each", ["--rooot=/tmp/x"]).splitlines()[0]
    "✗ 我不收这个旗标（给的是 '--rooot=/tmp/x'）。收的只有这几个：`--each`（每件一个子进程真跑）、`--self-test`（跑本件的基线）、`--doctest`（只跑本件那份用例）；`--each` 后面还可以跟 `--root=<路径>`（量另一棵树）与 `--timeout=<秒>`（一件的天花板）。"
    >>> refusal("--each", ["--a", "--b"]).splitlines()[0]      # 不止一个：全点出来
    "✗ 我不收这个旗标（给的是 '--a'、'--b'）。收的只有这几个：`--each`（每件一个子进程真跑）、`--self-test`（跑本件的基线）、`--doctest`（只跑本件那份用例）；`--each` 后面还可以跟 `--root=<路径>`（量另一棵树）与 `--timeout=<秒>`（一件的天花板）。"
    """
    names = [given] if bad is None else bad
    return ("✗ 我不收这个旗标（给的是 " + "、".join(repr(a) for a in names) + "）。"
            "收的只有这几个：`--each`（每件一个子进程真跑）、"
            f"`{SELF_TEST_FLAG}`（跑本件的基线）、`{DOCTEST_FLAG}`（只跑本件那份用例）；"
            "`--each` 后面还可以跟 `--root=<路径>`（量另一棵树）与 "
            "`--timeout=<秒>`（一件的天花板）。\n"
            "位置参数不是旗标，是模块名里的一个子串：\n"
            "    .venv/bin/python scripts/run_doctests.py            # 全部\n"
            "    .venv/bin/python scripts/run_doctests.py prober     # 只跑名字含 prober 的\n"
            "    .venv/bin/python scripts/run_doctests.py --each     # 每件一个子进程，真跑\n"
            "    .venv/bin/python scripts/run_doctests.py --self-test  # 往沙盒种假件，量这条跑法")


def main(argv: list[str]) -> int:
    for p in (str(ROOT), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)

    # 这支脚本只收一个位置参数（模块名的子串），加上 2.70 那一档 `--each`、2.74 那两旗。
    # 递给它一个别的旗标，它会当成过滤器去匹配、匹配不到，然后回一句「检查 src/ 和 scripts/
    # 还在不在」—— 那句诊断是**错的**（目录好好的，是我参数给错了）。09-24 我自己踩过一次，见 2.56。
    if argv and argv[0] == SELF_TEST_FLAG:
        return self_test()
    if argv and argv[0] == EACH_FLAG:
        opts, rest, bad = each_options(argv[1:])
        if bad:
            print(refusal(argv[0], bad), file=sys.stderr)
            return 2
        return run_each(rest[0] if rest else "", **opts)
    if argv and argv[0].startswith("-"):
        print(refusal(argv[0]), file=sys.stderr)
        return 2

    names = modules(argv[0] if argv else "")
    if not names:
        print("一个模块都没找到，检查 src/ 和 scripts/ 还在不在。", file=sys.stderr)
        return 1

    odd = strays(names)
    if odd:
        for n in odd:
            print(f"✗ 这个不是能导入的模块名：{n!r}"
                  f" —— 同步盘的冲突副本？先把它弄出这两个目录（`src/` 与 `scripts/`，"
                  f"两边都扫），不然用例数是从两份代码里凑的")
        return 1

    attempted = failed = 0
    quiet: list[str] = []
    for name in names:
        try:
            mod = importlib.import_module(name)
        except Exception as e:  # 导入炸了比 doctest 炸了更该拦下来
            print(f"✗ 导入失败 {name}: {type(e).__name__}: {e}")
            failed += 1
            continue
        result = doctest.testmod(mod, verbose=False)
        attempted += result.attempted
        failed += result.failed
        if not result.attempted:
            quiet.append(name)
        print(f"{flag_of(result.attempted, result.failed)} {name:<24} {result.attempted} 个用例"
              + (f"，失败 {result.failed}" if result.failed else ""))

    if attempted == 0:
        print("\n✗ 收集到 0 个用例 —— 这不算通过，八成是遍历写歪了。")
        return 1
    print(f"\n合计 {attempted} 个用例，{failed} 个失败（{len(names)} 个模块）")
    if not argv:
        # 只在全量那一遍印：这一句说的是整棵树的形状，递了过滤器之后它就不成立了。
        line = survey_line(survey_routes())
        if line:
            print(line)
    note = zero_note(quiet)
    if note:
        print(note)
    return 1 if (failed or quiet) else 0


if __name__ == "__main__":
    rc = doctest_gate(sys.argv[1:])       # 2.69：收集器自己也认这一旗（只跑本件那一份用例）
    raise SystemExit(rc if rc is not None else main(sys.argv[1:]))
