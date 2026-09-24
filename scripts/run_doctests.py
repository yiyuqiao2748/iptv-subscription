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
    .venv/bin/python scripts/run_doctests.py --doctest  # 只跑本件这一份用例

2.68 起这里还多管一件事：**别的脚本自己那条 `--doctest` 支路怎么说结果**。那些支路以前
一律写成 `raise SystemExit(doctest.testmod(verbose=False).failed)` —— 量到 31 条也好、
一条都没量到也好，屏幕上都是 0 字节，而「一条都没量到」还照样退 0。
`run_own` 就是那一支的正确写法（`own_line` 是它要说的那句话）。放在这里而不是各写一份，
理由和 2.58 把「顿号闸」挪进 `baseline_guard` 一样：口径只有一份，下一把尺不必再抄一遍注释。

2.69 再把这条支路往外推一步：`doctest_gate` 是「认得这面旗」的那一道门，一件脚本只要在
收尾处问它一句，`--doctest` 就答自己的用例数，而不是把旗当成一个路径、一个子命令、
或者一份 argparse 的「未识别的参数」。跑全量那一遍会在末尾印整棵树的形状
（`survey_routes`），而「挂了号却没人应答」那种件由 `dead_flag_doors` 静态拦一道。
"""

from __future__ import annotations

import ast
import doctest
import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


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


def dead_flag_doors(dirs: tuple[pathlib.Path, ...] = (ROOT / "scripts",
                                                       ROOT / "src")) -> list[str]:
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


def survey_routes(dirs: tuple[pathlib.Path, ...] = (ROOT / "scripts", ROOT / "src")) -> dict[str, list[str]]:
    """整棵树按 `route_shape` 分档，键是那一档、值是 `相对路径 用例数` 的名单。

    跟收集器同一套取舍：`__init__.py` 不看（它没有用例可言），文件名不像模块名的不看
    （同步盘冲突副本 —— 见 `no_bare_testmod` 那段理由），一条用例都没写的也不看
    （它没有「这条路通不通」这个问题）。
    用例数写在名单里而不是只报件数：这一档真正要说的是「多少个用例只有收集器跑得动」。

    >>> found = survey_routes()
    >>> sum(len(v) for v in found.values())                                # 每一档加起来 = 有用例的件数
    28
    >>> sorted(found)                                                      # 接线之后只剩两档有件
    ['没有入口', '走通']
    >>> [k for k in (ROUTE_ARGPARSE, ROUTE_NO_FLAG, ROUTE_AS_ARG) if k in found]
    []
    >>> len(found[ROUTE_RUNS]) + len(found[ROUTE_NO_DOOR])                 # 28 = 接了门 + 纯库
    28
    >>> all(s.startswith("src/") for s in found[ROUTE_NO_DOOR])            # 没有入口的全是库
    True
    >>> len(found[ROUTE_NO_DOOR])                                          # 11 件、只有收集器跑得动
    11
    >>> [k for k, v in found.items() if any("run_doctests" in s for s in v)]
    ['走通']

    这里**故意不钉用例条数**、也不钉 `走通` 那一档的名单：本件自己就在被数的那一堆里，
    而「接了门的件」是要往外长的（01:55:51 那一份普查里这一档只有 3 件，本节接完是 17 件），
    把那一串名字写死在这里，下一件接门时就红一格 ——
    红理由是「你多接了一件」，那是 2.68 记过的同一种自指。
    上面凡是打集合的地方都过一道 `sorted`：字符串的哈希每个进程重新播种，
    直接印 set 会让同一棵树的两遍跑出两种顺序（2.67 的「两遍必须同数」在这一层里同样成立）。
    """
    by: dict[str, list[str]] = {}
    for path in sorted(sum((list(d.rglob("*.py")) for d in dirs), [])):
        if path.name == "__init__.py" or not path.stem.isidentifier():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        n = example_count(src)
        if not n:
            continue
        by.setdefault(route_shape(src), []).append(f"{path.relative_to(ROOT)} {n}")
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


def main(argv: list[str]) -> int:
    for p in (str(ROOT), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)

    # 这支脚本只收一个位置参数（模块名的子串），没有 `--help`。递给它一个旗标，
    # 它会当成过滤器去匹配、匹配不到，然后回一句「检查 src/ 和 scripts/ 还在不在」——
    # 那句诊断是**错的**（目录好好的，是我参数给错了）。09-24 我自己踩过一次，见 2.56。
    if argv and argv[0].startswith("-"):
        print(f"✗ 我不收旗标（给的是 {argv[0]!r}）。唯一的参数是模块名里的一个子串：\n"
              f"    .venv/bin/python scripts/run_doctests.py            # 全部\n"
              f"    .venv/bin/python scripts/run_doctests.py prober     # 只跑名字含 prober 的",
              file=sys.stderr)
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
