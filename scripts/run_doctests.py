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

2.68 起这里还多管一件事：**别的脚本自己那条 `--doctest` 支路怎么说结果**。那些支路以前
一律写成 `raise SystemExit(doctest.testmod(verbose=False).failed)` —— 量到 31 条也好、
一条都没量到也好，屏幕上都是 0 字节，而「一条都没量到」还照样退 0。
`run_own` 就是那一支的正确写法（`own_line` 是它要说的那句话）。放在这里而不是各写一份，
理由和 2.58 把「顿号闸」挪进 `baseline_guard` 一样：口径只有一份，下一把尺不必再抄一遍注释。
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


DOCTEST_FLAG = "--doctest"

ROUTE_RUNS = "走通"
ROUTE_IGNORES = "不看参数"
ROUTE_AS_ARG = "当成一个参数"
ROUTE_NO_DOOR = "根本没有入口"


def _tree(src: str):
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def _docstring_nodes(tree) -> set[int]:
    """docstring 那几颗常量节点的位置 —— 下面的字面量统计要避开它们。

    为什么避开：`no_bare_testmod` 那一刀已经付过一次学费（01:16:05），扫原文的闸分不清
    「提到」和「用了」；这一层同理 —— 一件脚本在说明书里写「用法：`--doctest`」，
    不等于它的代码认得这个开关。
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in node.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    out.add(id(stmt.value))
    return out


def code_strings(src: str) -> set[str]:
    r"""这段 .py 的**代码**里出现过的字符串字面量（docstring 不算）。

    >>> sorted(code_strings('if x == "--doctest":\n    pass\n'))
    ['--doctest']
    >>> code_strings("'''用法：--doctest'''\n")     # 只在说明书里提：不算
    set()
    >>> code_strings("def f(:\n")                    # 读不通：给空集，让它落进最坏那一档
    set()
    """
    tree = _tree(src)
    if tree is None:
        return set()
    skip = _docstring_nodes(tree)
    return {c.value for c in ast.walk(tree)
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and id(c) not in skip}


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


def calls_run_own(src: str) -> bool:
    """这份件有没有用上 `run_own`（写成 `run_own(...)` 或 `x.run_own(...)` 都算）。

    >>> calls_run_own("from run_doctests import run_own\\nrun_own(m)")
    True
    >>> calls_run_own("'''说的是 run_own 这件事'''\\n")   # 说明书里提一句：不算
    False
    """
    tree = _tree(src)
    if tree is None:
        return False
    return any(isinstance(c, ast.Call)
               and ((isinstance(c.func, ast.Name) and c.func.id == "run_own")
                    or (isinstance(c.func, ast.Attribute) and c.func.attr == "run_own"))
               for c in ast.walk(tree))


def route_shape(src: str) -> str:
    """直接跑 `python 这份件 --doctest` 会发生什么 —— 四档里的一档。

    这一把尺要量的是**约定到底覆盖了谁**：2.68 给三条支路换上了 `run_own`，屏幕上就有了
    「合计 N 个用例」这句话，于是它看着像全项目的规矩。01:33:44 拿整棵树量过：
    认这个开关的件是极少数，其余的递 `--doctest` 进去各走各的路，最坏的一档不是「不跑用例」，
    而是**它照干自己的活**（写盘、起服务）—— 那两件事本节没有实测，判定只看静态。

    >>> route_shape('if "--doctest" in a:\\n    run_own(m)\\n')
    '走通'
    >>> route_shape('if __name__ == "__main__":\\n    run_own(m)\\n')     # 不看参数，递什么都跑自己
    '不看参数'
    >>> route_shape('raise SystemExit(main(sys.argv[1:]))')               # 递进去就是个路径
    '当成一个参数'
    >>> route_shape("def f():\\n    pass\\n")                             # 纯库：静默退 0
    '根本没有入口'
    >>> route_shape("def f(:\\n")                                         # 读不通：也算静默那一档
    '根本没有入口'
    """
    if DOCTEST_FLAG in code_strings(src) and calls_run_own(src):
        return ROUTE_RUNS
    if not reads_argv(src):
        return ROUTE_IGNORES if has_main_block(src) else ROUTE_NO_DOOR
    return ROUTE_AS_ARG


def survey_routes(dirs: tuple[pathlib.Path, ...] = (ROOT / "scripts", ROOT / "src")) -> dict[str, list[str]]:
    """整棵树按 `route_shape` 分档，键是那一档、值是 `相对路径 用例数` 的名单。

    跟收集器同一套取舍：`__init__.py` 不看（它没有用例可言），文件名不像模块名的不看
    （同步盘冲突副本 —— 见 `no_bare_testmod` 那段理由），一条用例都没写的也不看
    （它没有「这条路通不通」这个问题）。
    用例数写在名单里而不是只报件数：这一档真正要说的是「多少个用例只有收集器跑得动」。

    >>> found = survey_routes()
    >>> sum(len(v) for v in found.values())                                # 每一档加起来 = 有用例的件数
    28
    >>> [s.rsplit(" ", 1)[0] for s in sorted(found[ROUTE_RUNS])]           # 走通这一档点名到件
    ['scripts/analyze_upstream.py', 'scripts/code_claims.py', 'scripts/unmarked_nums.py']
    >>> [k for k, v in found.items() if any("run_doctests" in s for s in v)]
    ['当成一个参数']

    这里**故意不钉用例条数**：本件自己就在被数的那一堆里，把「60」写进自己的说明书，
    下一遍这条例子就算不上自己了 —— 多写一条用例它就红，而它红的理由是「你多写了一条用例」。
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
    order = [ROUTE_RUNS, ROUTE_IGNORES, ROUTE_AS_ARG, ROUTE_NO_DOOR]
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
    raise SystemExit(main(sys.argv[1:]))
