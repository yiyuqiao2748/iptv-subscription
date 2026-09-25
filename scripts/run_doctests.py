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
    .venv/bin/python scripts/run_doctests.py --across     # 整册判决面积：只数不判（2.76）
    .venv/bin/python scripts/run_doctests.py --each --root=/tmp/那棵树 --timeout=2
    .venv/bin/python scripts/run_doctests.py --root=/tmp/那棵树   # 收集器也换一棵树量（2.75）

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

2.76 把上面那道闸往外推到**整册**：`--across` 那一档逐件读源码原文（AST 摊 `Cell(has=…)` 里的
字面截语，不导入、不跑、也**不认豁免表**），报「判决 N 句：钉住 M、缺口 K」。**只数不判** ——
今天整册那 278 句缺口（09-25 18:2x 现量，见 `计划书.md` §2.76）一句都不判，判死它等于把这一屏每一遍变成噪音；退码只量「读没读到」
（2.62 那三档：全读到 0、有件读不通 1、一件都没读到 2）。缺口要逐句点名得递一个文件名当过滤器，
而没递时那一屏自己说一句「上面没有逐句点名」。同步盘的冲突副本在这一档是**跳过并自报**，
与 面 A 那一档的**退 2** 是两种取舍，各自的原因写在 `across_rows` 上面。
"""

from __future__ import annotations

import ast
import contextlib
import doctest
import importlib.util
import io
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import types
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 「这一遍量的是哪一棵」递给被量件的那一位。为什么走环境变量而不是命令行旗标：
# 收这个旗标的是每一件自己的收尾（`run_own(sys.modules["__main__"])`），递参数就得让
# 30 件各自接一位「我在哪棵树上」—— 那是把一份规矩抄 30 遍（§2.58），抄漏的那一件不会红，
# 只会静默报一个错名字。换树的读数和它自己那一句判决在 `label_of` 上面那段。
MEASURED_ROOT_ENV = "RUN_DOCTESTS_ROOT"

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


def module_paths(root: pathlib.Path = ROOT) -> list[pathlib.Path]:
    """`root` 那棵树里参与收集的每一个 .py：排好序、去掉包标记。

    2.75 起「哪几级算在册」这一位可以换一棵树（收集器也接 `--root=`），所以遍历和
    「给人看的名字」分成两件事：换树时**有什么文件**按那棵树算、**叫什么**按那棵树相对算，
    两头都要拿到路径（`main` 要在沙盒里按路径导，见 `import_at`）。以前这两件事揉在
    `modules` 一段里，换树就得从名字反推路径 —— 那是把「剥 `.py`、拼点号」那本账抄两遍
    （2.58），而抄错的那一处不会红，只会静默量不到东西。

    >>> len(module_paths()) > len(module_paths(ROOT / "src"))          # 整棵比单一级多
    True
    >>> module_paths(pathlib.Path("/tmp/没有这样一棵树"))               # 两棵子目录都不在
    []
    >>> [p.name for p in module_paths() if p.name == "__init__.py"]
    []
    """
    return sorted(p for p in list((root / "src").rglob("*.py")) + list((root / "scripts").glob("*.py"))
                  if p.name != "__init__.py")


def module_name(path: pathlib.Path, root: pathlib.Path = ROOT) -> str:
    """这一个文件在册子里的名字：`src/` 下给带包的点号名，`scripts/` 下给裸名。

    >>> module_name(ROOT / "src" / "check" / "prober.py")
    'src.check.prober'
    >>> module_name(ROOT / "scripts" / "run_doctests.py")
    'run_doctests'
    """
    dotted = str(path.relative_to(root)).removesuffix(".py").replace("/", ".")
    return dotted if dotted.startswith("src.") else dotted.rsplit(".", 1)[-1]


def modules(pattern: str = "", root: pathlib.Path = ROOT) -> list[str]:
    """`root` 那棵树里 src/ 和 scripts/ 下的可导入模块名（名字按那一棵相对算）。

    scripts/ 里的文件按裸名导入（它们不是包，各自靠 `sys.path.insert(ROOT)` 找 src）。

    >>> "src.check.prober" in modules()
    True
    >>> "serve_lan" in modules("serve")
    True
    >>> [m for m in modules() if m.endswith("__init__")]     # 包标记不参与
    []
    >>> modules("good", pathlib.Path("/tmp/没有这样一棵树"))   # 换一棵不存在的树：一个名字都不给
    []
    """
    out = []
    for path in module_paths(root):
        name = module_name(path, root)
        if pattern and pattern not in name:
            continue
        out.append(name)
    return out


def sandbox_tag(path: pathlib.Path) -> str:
    """拿不到真名时，沙盒里那一份文件的临时模块名：由**路径**拼出来，每格、每遍都不一样。

    为什么不给它一个裸文件名当模块名：见 `import_at` 那一段 —— 裸名会撞上仓库 `sys.path`
    里那一级，也会撞上同一进程里上一格留下的缓存。这一位如今只服务「那一份根本不在被量的
    树里」那一档（换一棵树的正路在 `host_tree`）。

    >>> sandbox_tag(pathlib.Path("/tmp/一/scripts/good.py"))
    '_沙盒__tmp_一_scripts_good_py'
    >>> sandbox_tag(pathlib.Path("/tmp/x")).startswith("_沙盒_")
    True
    """
    return "_沙盒_" + "".join(ch if ch.isalnum() else "_" for ch in str(path))


HOST_SLOTS: list[str] = []      # 换树那一遍插进 `sys.path` 的那几级：换下一棵前先拔掉


def host_tree(root: pathlib.Path, first: str) -> None:
    """把「这一遍量的是哪一棵」变成**真的导入根**，并清掉缓存里那一名的旧货。

    为什么光按路径读文件不够（2.75 第一次跑「面 A 进沙盒」量出来的）：按路径端上来只解决
    「读的是哪一个文件」，没解决「它请的邻居是哪一个」。副本里那些件做的是**绝对导入**
    （`src.check.prober` 里 `from src.check.scope import …`、`scripts/*.py` 收尾那句
    `from run_doctests import run_own`、以及用例自己 `import src.check.prober as P`），
    这些名字由 `sys.path` 与 `sys.modules` 决定 —— 于是文件体是副本的、邻居是仓库的，
    那一遍量的是**两棵树拼起来的东西**（§2.55 那笔「用例数是从两份代码里凑的」换到导入这一层）。
    同一处的现量：`src/check/prober.py` 那 23 条失败全部出自这里 —— 它的用例往 `P._get`
    上装假答案，装进了仓库那一份，而被量的 `l3_roll` 在副本的全局里找 `_get`，
    假答案一个字都没递进去，三条本该 `rolling`／`stuck` 的读数全成了 `dead`。

    两件事按顺序做，缺一件都不算换根：
    * 把那一棵和它的 `scripts/` 插到 `sys.path` 最前面（上一遍插的那几级先拔掉 ——
      沙盒每格一个新目录，留着的话「这一棵里没有的名字」会去上一格那棵里找）；
    * 把 `first` 那一名（含它的子模块）从 `sys.modules` 里清掉。不清这一步，插再多路径
      也没用：`importlib` 先看缓存，命中的还是仓库那一份。

    换根之后**不马上拔**：被量的那一件在自己的用例里还要晚一步 import（`own()` 那样的
    函数体里的导入），拔早了那一记又回到仓库那一级去了。一整遍收完由 `unhost` 拔。
    """
    unhost()
    for slot in (str(root), str(root / "scripts")):
        if slot not in sys.path:
            sys.path.insert(0, slot)
            HOST_SLOTS.append(slot)
    for key in [k for k in sys.modules if k.split(".")[0] == first]:
        sys.modules.pop(key, None)


def unhost() -> None:
    """把换树那遍插进 `sys.path` 的那几级拔回去 —— 量完一棵，不该留下它的影子。

    为什么要这一句而不是留着：这一位的对面是「同一进程里连着量好几棵」（`--self-test`
    那几格 A1…A7 就是），留着的话下一格里「这一棵没有的名字」会去**上一格那棵**里找，
    而那正是 §2.55 拦住的样子。缓存那一头（`sys.modules`）不归它管：清它是换根那一步的事。
    """
    for slot in HOST_SLOTS:
        while slot in sys.path:
            sys.path.remove(slot)
    HOST_SLOTS.clear()


def load_by_path(path: pathlib.Path):
    """按路径硬读一份源码当模块 —— 只在它拿不到真名时走这一支。

    `spec_from_file_location` 给不出 loader 时**抛**而不是静默回一个空模块：那一档的意思是
    「这个文件我读不出模块形状」，把它读成「这文件一条用例都没有」等于换了一种读法（2.50）。
    抛出去的话由 `main` 那句「✗ 导入失败」摊到屏幕上。
    """
    spec = importlib.util.spec_from_file_location(sandbox_tag(path), path)
    if spec is None or spec.loader is None:
        raise ValueError(f"读不出这个文件的模块形状：{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                # 先登记再 exec：包里的循环导入才走得通
    spec.loader.exec_module(mod)
    return mod


def import_at(path: pathlib.Path, name: str, root: pathlib.Path = ROOT):
    """把树上那一个文件变成一个能 `testmod` 的模块。

    仓库那一棵按**模块名**导（`src.check.prober` 要靠包机制走通它的兄弟导入），这一位
    与 2.75 之前逐字相同。

    换一棵树时先问一句：**那一份文件在不在那一棵里面**。在 —— 那一棵就是导入根
    （`host_tree`，理由全写在那一段里）。不在 —— 只能按路径端上来、模块名由路径拼
    （`sandbox_tag`）：这一支今天只有一个实例，就是下面那条「拿仓库里的件配一棵不存在的树」
    的用例，它要的是「读不出真名」那一档的行为，不是换树那一档的。

    >>> import_at(ROOT / "scripts" / "baseline_guard.py", "baseline_guard").__name__
    'baseline_guard'
    >>> m = import_at(ROOT / "scripts" / "baseline_guard.py", "用不上", pathlib.Path("/tmp/那棵"))
    >>> m.__name__.startswith("_沙盒_"), m.sep_names(["甲、乙"])
    (True, ['甲、乙'])
    >>> before = list(sys.path)
    >>> with tempfile.TemporaryDirectory() as d:                       # 换根那支：自导入要命中副本
    ...     t = pathlib.Path(d)
    ...     (t / "scripts").mkdir()
    ...     _ = (t / "scripts" / "selfname.py").write_text(
    ...         "TOP = __file__\\n\\ndef own() -> str:\\n"
    ...         "    import selfname                 # 用例里那种自导入：名字指向谁，这里量的就是谁\\n"
    ...         "    return selfname.TOP\\n", encoding="utf-8")
    ...     mod = import_at(t / "scripts" / "selfname.py", "selfname", t)
    ...     mod.own() == str(t / "scripts" / "selfname.py")
    True
    >>> unhost()
    >>> sys.path == before
    True
    """
    if root == ROOT:
        return importlib.import_module(name)
    if not path.is_relative_to(root):
        return load_by_path(path)
    host_tree(root, name.split(".")[0])
    return importlib.import_module(name)


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
    """这一件给人看的名字：能给**被量那棵树**内的相对路径就给，给不了退到模块名。

    为什么要绕这两层：那一句「合计」要是印成绝对路径，这一行就成了全屏最长的噪音；
    而 `__file__` 在 `-c`、在交互式解释器里根本没有，硬取会裸崩 —— 这一支是收尾时说话的，
    不该在收尾那一步把进程带走。

    「相对**哪**一棵」由 `RUN_DOCTESTS_ROOT` 说（下面那一支），不写死本仓库：换一棵树量时
    被量的文件不在本仓库里，`relative_to(ROOT)` 必然 `ValueError`，退到模块名就只剩
    `analyze_upstream.py` 这种裸名 —— 而收集器比的是它自己那本册子里的 `scripts/…` 全名，
    于是 18 件好好的东西全被读成「量的不是自己：它报 analyze_upstream.py」
    （17:0x 现量：`--each --root=/tmp/clean275` 那一遍 30 件、18 件有毛病，全部出自这一处）。
    这一位不是新发明：`--root=` 早就有，只是从来没有传到**被量件**那一头去。

    >>> import types
    >>> m = types.ModuleType("m"); m.__file__ = str(ROOT / "scripts/x.py")
    >>> with measured_tree():                         # 谁都没递这一位：本仓库
    ...     label_of(m)
    'scripts/x.py'
    >>> with measured_tree():
    ...     label_of(types.ModuleType("__main__"))    # 没有 __file__：退到模块名
    '__main__'
    >>> with measured_tree("/tmp/那棵"):              # 换了根：那一份的相对名字按那一棵算
    ...     label_of(types.SimpleNamespace(__file__="/tmp/那棵/scripts/x.py"))
    'scripts/x.py'
    >>> with measured_tree():                         # 没换根、那份又不在本仓库：裸名
    ...     label_of(types.SimpleNamespace(__file__="/tmp/那棵/scripts/x.py"))
    'x.py'
    """
    f = getattr(mod, "__file__", None)
    if f:
        try:
            return str(pathlib.Path(f).resolve().relative_to(measured_root()))
        except ValueError:                          # 不在被量那棵树里（临时目录、别人的树）
            return pathlib.Path(f).name
    return getattr(mod, "__name__", "<没有名字的件>")


def measured_root() -> pathlib.Path:
    """这一遍「量的是哪一棵」：`--root=` 由收这一位的人递进环境，没递就是本仓库。

    为什么读环境变量而不是函数参数：调用方是**被量件自己**的收尾（每一件都写
    `run_own(sys.modules["__main__"])`），要它们各自接一位「我在哪棵树上」，等于把同一份
    规矩抄进 30 件里（§2.58），而抄漏的那一件只会静默报一个错名字、不会红。
    `resolve()` 过一次：`/tmp` 在 macOS 上是 `/private/tmp` 的替身，两头都归一化才比得出。
    """
    got = os.environ.get(MEASURED_ROOT_ENV)
    return pathlib.Path(got).resolve() if got else ROOT


@contextlib.contextmanager
def measured_tree(root: object = None):
    """临时把「这一遍量的是哪一棵」立起来（不递＝立成「谁都没递」那一档），用完原样收回。

    为什么本件的用例非得自己立一次，而不是直接假设环境是干净的：`--each` 那一遍里
    被量件的用例**就是带着这一位跑的**（那正是这一位存在的理由），于是同一句
    `label_of(m)` 在仓库那一遍和沙盒那一遍会读出两个答案 —— 例子不把条件钉住，
    它就会在另一棵树上变成一条假失败（§2.67 那一族换了个载体又长出来一次：这次
    读例子不是字面量，是**环境**）。
    """
    keep = os.environ.pop(MEASURED_ROOT_ENV, None)
    if root is not None:
        os.environ[MEASURED_ROOT_ENV] = str(root)
    try:
        yield
    finally:
        os.environ.pop(MEASURED_ROOT_ENV, None)
        if keep is not None:
            os.environ[MEASURED_ROOT_ENV] = keep


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
    * `MEASURED_ROOT_ENV` —— 「这一遍量的是哪一棵」传到被量件那一头，它报自己名字时
      才报得出**这一棵**的相对路径（规矩写在 `label_of` 上面那一段，这里只递不改写）。

    退码那一位**只有天花板这一档会是 `None`**（真进程被信号打死时 `subprocess` 给的是
    负数，拿 `-1` 当哨兵会跟 SIGHUP 撞车 —— 本节头一版就是这么写的）。
    「超过 N 秒没回来」那一句话在这里一个字都不拼：它归 `each_verdict` 说（2.58
    「一条规矩两个人各写一遍」——上一版在这里拼好了塞进 `out`，于是它永远到不了屏幕）。
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", MEASURED_ROOT_ENV: str(base)}
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
    '在册范围不是本仓库，是 /tmp/沙盒 —— 上面那些行的「N 件」说的都是这一棵，不是仓库'
    """
    if root == ROOT:
        return ""
    return f"在册范围不是本仓库，是 {root} —— 上面那些行的「N 件」说的都是这一棵，不是仓库"


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


def own_options(raw: list[str]) -> tuple[pathlib.Path, str, list[str]]:
    """认收集器那一档后面的字：`--root=<路径>` 换树、不像旗的字当过滤器、认不出的那些挑出来。

    为什么不与 `each_options` 合成一份：那一句要把 `--timeout=` 递进 `run_each`，而收集器
    **不起子进程** —— 「一件的天花板」在这一档没有意义。两半各认各的，好处是那一旗递到
    这里就落进「认不出」那一堆、由登记处那句当场点名，而不是被安静地吃掉（2.74 给 `--each`
    记过的那笔账：「一句打错的旗标换来一屏看着像沙盒、其实是仓库的读数」在这一档同样成立）。

    这一句最要紧的产物和 `each_options` 一样是**认不出的那一半**：凡是带 `-` 又不认识的字，
    既不丢、也不当成过滤器。

    >>> root, pattern, bad = own_options([])
    >>> (root == ROOT, pattern, bad)
    (True, '', [])
    >>> root, pattern, bad = own_options(["--root=/tmp/x", "prober"])
    >>> (str(root), pattern, bad)
    ('/tmp/x', 'prober', [])
    >>> own_options(["--timeout=5"])[2]                    # 天花板只管 `--each` 那一档
    ['--timeout=5']
    >>> own_options(["--nope"])[2]
    ['--nope']
    >>> own_options(["--root="])[2]                        # 空路径：不许退化成「用默认」
    ['--root=']
    """
    root, pattern, bad = ROOT, "", []
    for a in raw:
        if not a.startswith("-"):
            pattern = a
            continue
        key, eq, val = a.partition("=")
        if key == "--root" and eq and val:
            root = pathlib.Path(val)
        else:
            bad.append(a)
    return root, pattern, bad


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

# 被量件那一头问「这一遍量的是哪一棵」（2.75）：这一位**不许有兜底** —— 少了这一记，
# 这一格就退化成「假件自己算自己的名字」，而那条算错的路（报裸名）恰好是它要拦的那一条。
# 两头都 `realpath`：macOS 上 `/var` 是 `/private/var` 的替身，临时目录一边拿到带 `private`
# 的、环境里那一位不带，`relpath` 就会拼出一长串 `../`（这一格头一遍红就红在这里，
# 而真的 `label_of` 两边都 `resolve()` —— 同一条规矩在假件里再写一遍，第一次写漏的那一格
# 就是它，§2.58 那笔账当场收回来自家身上）。
ENV_TAIL = 'if __name__ == "__main__":\n' \
           '    root = os.path.realpath(os.environ["RUN_DOCTESTS_ROOT"])   # 没收这一位就炸\n' \
           '    raise SystemExit(run_own(sys.modules["__main__"],\n' \
           '            os.path.relpath(os.path.realpath(__file__), root)))\n'

# ———— 面 A（收集器自己那一档）在沙盒里要的三种件 ————
# `--each` 那一档只收「写了用例的 .py」，而 面 A 按**文件**收：零用例的那一件在 面 A 这一档
# 有实例（它要说「其中 N 个模块一条用例都没收到」），在 `--each` 那一档会整格空转 ——
# 这一族区别写在 `sloppy_cells` 的那一条判据里（2.75 之前那条判据两边共用，会把 面 A 的格子
# 当成写歪）。
LIB_SRC = '"""这一件一句用例都没写：面 A 那一档要的正是这种 0。"""\n\nx = 1\n'
BOOM_IMPORT = 'import 没有这样一件模块\n'            # 导入就炸：比 doctest 炸更该拦下来的一档
BOOM_TAIL = 'raise ValueError("它跑到一半就炸了")    # 连那道门都没走到：只留 stderr 那一行\n'

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
    spawn: str = ""                           # 非空 = 起子进程跑沙盒里这一份，而不是 in-process `main()`


CELL_SRC = "scripts/good.py"                  # 绝大多数格子里那一件假件待的地方
CELL_LIB = "scripts/lib.py"                   # 纯库那一件：同一棵沙盒，另一档
CELL_SELF = "scripts/run_doctests.py"         # 「拿本件自己当被量件」那几格种的地方（2.75）
# `files` 里那一格不写源码、写这个记号：种成一个**目录**。2.76 之前 `files` 只能种文件，
# 于是「在册清单里有一个目录顶着 .py 的名字」那一种坏法（同步盘的占位符长得就是这样）
# 只有 `survey_file` 自己的用例量得到，`--across` 那一屏的「读不到」那一句没有实例。
# 为什么不用断掉的软链：那要多一个 `os.symlink`、又在「不同步盘怎么摆」上多一个变量，
# 而这一档要的就是「路径在、档不在」这一个形状。
AS_DIR = "\x00目录"                           # 源码里不会出现这一串，所以它只能当记号用

# 跑一份沙盒里的本件副本（`Cell.spawn`）的天花板，和那道「不许往下套娃」的记号。
# 正常那一遍在**一道预跑闸**前就退了，连格子都没开始跑（17:0x 现量：酉 0.13 秒、戌 0.15 秒）。
# 天花板不是按比例放的余量，是留给「那一刀没种下去」这一种红法 —— 那种时候副本会去跑整条
# 基线（每格真起子进程，17:0x 现量：整条 28 格 2.5 秒），而屏幕上要留下一行「超过了 N 秒没回来」，
# 不是一格吊死在那儿。
SPAWN_TIMEOUT = 30

# 起副本时递进环境的一个记号：副本再跑到 `spawn` 那种格子时**直接报不符**，不再起下一层。
# 为什么要有它：2.75 头一遍那一刀下在了说明书上（见 `cut_once`），闸当然不响，副本就自己去
# 跑整条基线 —— 而那条基线里也有这两格 spawn，于是它起的副本又跑基线、又起副本。
# 16:47 现量：机器上 964 个这种进程、load average 591，父进程被超时杀掉后它们没人收
# （`communicate` 等的是管道，管道握在孙子手里），整台机器一起慢下来。
DEPTH_ENV = "RUN_DOCTESTS_SPAWNED"


def cut_once(src: str, old: str, new: str) -> str:
    """下一刀，且只下在打算下的那一处：那一截在源码里必须**恰好出现一次**。

    为什么要有这一道：2.75 头一遍种的那两刀都是「文本上的第一处」，两处都下歪了 ——
    `self_copy` 找「没到屏幕上」，第一处命中在 `parse_guard` 的说明书里（那句判决在它的
    代码之前先被说明文提了一次），源码里那句判决一个字没动，那道闸当然不响；
    `silly_exemption` 要插的那张表的声明行，第一处命中是**它自己的函数体**（锚抄在了
    下刀的那一句里），那条豁免从没进过表。两格各挂满一分钟才说一句「大概没种下去」。
    格子内里是空的、却要点开才知道 —— 这一道就是让它**不开也响**。

    >>> try:
    ...     cut_once("一句话、两句话", "句话", "句话！")
    ... except ValueError as e:
    ...     print(str(e).split("：")[0])
    这一截在源码里出现 2 次，刀不敢下
    >>> cut_once("甲乙丙", "乙", "丁")
    '甲丁丙'
    >>> cut_once("这一刀已经下过了：丁", "乙", "丁")
    '这一刀已经下过了：丁'
    """
    n = src.count(old)
    if n == 1:
        return src.replace(old, new)
    if not n and new in src:
        return src                       # 这就是那一刀种出来的那一棵副本：不再下第二刀
    raise ValueError(f"这一截在源码里出现 {n} 次，刀不敢下：{old[:60]!r}"
                     " —— 那一截要么改过名了，要么写在了说明书里")


def copy_namespace(src: str):
    """把一份源码副本 exec 成模块对象（不起子进程、不跑格子），让两道预跑闸先在内存里量一遍。

    为什么要有它：`酉`／`戌` 量的是「副本里那道闸响不响」，可**刀有没有下在打算下的那一处**
    不必等子进程 —— 现算一遍就有读数。上面那两处下歪的头一遍各挂了一分钟，量的那一层却
    连「闸问过没有」都没走到。

    >>> mod = copy_namespace(self_copy())
    >>> len(mod.own_sites()) == len(own_sites())
    True
    >>> mod.CELL_SELF
    'scripts/run_doctests.py'
    """
    mod = types.ModuleType("一份源码副本")
    mod.__file__ = __file__
    exec(compile(src, "<一份源码副本>", "exec"), mod.__dict__)
    return mod


# 那一刀种在哪一句上：`each_verdict` 里「护栏那一句没到屏幕上」那一句改一处 ——
# 那句话今天还说得出口，可没有任何格子钉它。**认的是带 `problems.append(` 开头的整截**
# （带缩进、不带说明书），因为那五个字在 `parse_guard` 的说明书里先出现过一次。
# 锚是把两截**拼**出来的：整截抄在这里，这一行登记处自己就是第二处命中 ——
# `cut_once` 当场不敢下刀（§2.67 那一族，这次长在了刀自己身上）。
UNPIN_OLD = "        problems.append(" + '"护栏那一句没到屏幕上'
UNPIN_CUT = (UNPIN_OLD, UNPIN_OLD.replace("幕上", "外了"))

# 种进豁免表头上的那一条：线索词故意写成源码里没有一句判决认它。
SILLY_ENTRY = ('    ("这一句谁都没写过：它不在源码里的任何一句判决上",\n'
               '     "本格要的就是「豁免表自己有一条白登记」被读出来"),\n')


def self_copy(old: str = "", new: str = "") -> str:
    """本件源码的原文，或下一刀之后的那份**副本** —— 种进沙盒量那道「没格钉着」的闸。

    为什么读文件而不是抄一份字符串：手抄的那份副本会在下一次改动之后变成旧内容，而这两格
    量的是「源码里有一句判决没人钉」—— 它必须跟着源码走（正是 2.75 换掉手抄名单的那个理由
    长在自己身上）。

    为什么那一刀是「把一句判决改一处」而不是「删掉一格」：删一格要动 AST、要重排
    `BASELINE`，而 §2.74 记下的病灶本来就不是「格子少了一格」，是**改动判决话的时候没人提醒**。
    改一处造的就是那一刀：那句话今天还在源码里、说得出口，可没有任何格子钉它 ——
    那道闸必须当场响、退 2、而且**一格都不跑**（`lacks` 里那句「扫了基线」钉的正是「没跑」）。
    这一族和变异机 `M16`（字还在、路已死）同一个形状，只是这次咬的是**闸**。

    >>> len(self_copy()) == len(pathlib.Path(__file__).read_text(encoding="utf-8"))
    True

    不给刀时原样返回：种进沙盒的就是本件此刻的源码。下一条例子量的是**刀在内存里就先响一次**
    —— 不必等子进程起起来，那道闸在源码副本上已经读出「那句判决没人钉」。

    >>> coverage_gaps(BASELINE, own_sites())
    []
    >>> bool(coverage_gaps(BASELINE, verdict_sites(self_copy(*UNPIN_CUT))))
    True
    """
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    return cut_once(src, old, new) if old else src


def silly_exemption(src: str) -> str:
    """往一份源码的豁免表**头上**插一条谁都不认的：那一格量的是豁免闸读不读得出白登记。

    两道闸得各有一格钉，不能拿「没格钉着」那一格当两件事的证据 —— 那正是 §2.58 那一族
    （一条规矩两个人各写一遍）换到「两道闸共用一格」上的形状：豁免闸若哪天不响，
    屏幕上没有一行会知道。

    锚是把那张表的名字拼出来的：整截抄在这里，第一次命中的就是下面这一句本体（§2.67 那一族
    —— 举例的字面量会被自己的尺读到），那条豁免就从没进过表。

    下面两条一起才算这条例子说完了：那条豁免**真的进了表**（不是插进了某一段说明书），
    而豁免闸在内存里就读得出它是白登记。

    >>> silly = copy_namespace(silly_exemption(self_copy()))
    >>> len(silly.NOT_PINNABLE) - len(NOT_PINNABLE)
    1
    >>> bool(exemption_audit(BASELINE, own_sites(), silly.NOT_PINNABLE))
    True
    """
    head = "\n" + "NOT_PINNABLE" + ": tuple[tuple[str, str], ...] = (\n"
    return cut_once(src, head, head + SILLY_ENTRY)


def neighbor(rel: str) -> str:
    """沙盒里要有的邻居：本件 import 谁，那一棵里就得有什么（否则副本连门都进不去）。

    `--self-test` 第一行就是 `from baseline_guard import guard` —— 沙盒那一棵里没有它，
    那一格量到的就不是「闸响不响」，是一次 `ModuleNotFoundError`。

    >>> "def guard(" in neighbor("scripts/baseline_guard.py")
    True
    """
    return (ROOT / rel).read_text(encoding="utf-8")


ACROSS_FLAG = "--across"       # 2.76：跨件判决普查。登记在 `refusal` 那一句里，定义在 `run_across`


def across_src(pinned: int = 0, gaps: int = 0) -> str:
    """`--across` 那几格的假件：一份「屏幕上会说话、自己带着格子」的 .py 源码。

    为什么这一份可以这么随便（不写用例、也不定义 `Cell`）：这一档**读的是源码原文**，
    它从不执行假件 —— 「写了用例才入册」是 `--each` 那一档的取舍（2.70），「import 得到」
    是 面 A 的（2.75 之前 面 A 连换树都做不到）。这一档只要 AST 过得去。

    `pinned` 那几句是「它自己某一格的 `has` 摊得出来」的；`gaps` 那几句故意换了措辞，
    它自己那些格子里没有一截对得上。两组各写各的字面句，因为**摊得出其中一句就等于
    摊得出同形的每一句** —— 拿同一句当两种情形，缺口那一列永远是 0（§2.67 那一族，
    这次是「假件自己把要量的东西抹平」）。

    >>> example_count(across_src(1, 1))                    # 一条用例都没写：这一档不看这个
    0
    >>> len(verdict_sites(across_src(1, 2)))               # 三句判决：一句钉得住、两句钉不住
    3
    >>> len(cell_phrases(across_src(1, 2)))                # 只有钉得住那一句留下的那一截
    1
    >>> cell_phrases(across_src(0, 1))                     # 一句都没钉的假件：连 `Cell` 都不种
    []
    """
    body = "".join(f'print("甲{i} 那句判决在这一件自己的屏幕上说得出口")\n'
                   for i in range(pinned))
    body += "".join(f'print("乙{i} 那一句换了措辞，它自己那些格子对不上这句，所以它在屏幕上'
                    f'说的这一句要一直说到 60 字开外才截得下来，而这一句要的就是那一种形状")\n'
                    for i in range(gaps))
    door = ('Cell("甲_钉得住上面那一句", "一句", 0,\n'
            '     has=("那句判决在这一件自己的屏幕上",))\n') if pinned else ""
    return ('"""给 `--across` 那几格种的假件：会说话，带着自己的格子。"""\n'
            + body + door)


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
    Cell("申_它崩在护栏之前", "静态认它有入口、它却炸在门之前：护栏那句读不到、stderr 上有话",
         1, files=((CELL_SRC, fake(1, RUNS_TAIL)), ("scripts/boom.py", fake(1, BOOM_TAIL + RUNS_TAIL))),
         has=("✗ scripts/boom.py", "没答（静态：走通，退 2）", "字还在、路已死",
              "它那边的 stderr 第一行：", "合计 2 件：答 1 件、没答 1 件", "1 件有毛病"),
         lacks=("护栏那一句没到屏幕上", "护栏那一句一件都没读到", "只有收集器跑得动它")),
    Cell("卯_一件不返回", "天花板那一档：一件卡住不许拖着整屏 —— 掐掉它、那一行照样落下来",
         1, files=((CELL_SRC, fake(1, RUNS_TAIL)), ("scripts/sleeper.py", fake(1, SLEEP_TAIL))),
         argv=("--each", "--root={T}", "--timeout=1"),
         has=("超过 1 秒没回来", "被 1 秒的天花板掐掉", "合计 2 件：答 1 件、没答 1 件",
              "1 件有毛病"),
         lacks=("一件都没读到", "子进程连 work_guard 都没跑起来", "字还在、路已死")),
    # ———— 亥：换一棵树量时，「量的是哪一棵」要传到**被量件**那一头 ————
    # 这一格钉的不是措辞，是一条**递旗的路**：`--root=` 只走到收集器自己那一句「不是本仓库」
    # 是不够的 —— 被量件收尾时也要能问出同一位，不然它报的「量的件」是按本仓库算的相对路径，
    # 换树那一遍 30 件里 18 件会被读成「量的不是自己」（17:2x 现量，见 `label_of` 上面那段）。
    # 假件里那一记 `os.environ[...]` **故意不给兜底**：路断了这一格就炸成「字还在、路已死」，
    # 而不是安静地退回一个裸名。
    Cell("亥_量的是哪一棵递下去了", "换一棵树量：那一位要传到被量件收尾，它才报得出这一棵的相对名字",
         0, files=((CELL_SRC, fake(1, ENV_TAIL)),),
         has=("答 1／静态 1", "量的件=scripts/good.py"),
         lacks=("量的不是自己", "字还在、路已死", "护栏那一句没到屏幕上")),
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
         has=("我不收这个旗标", "--each", "--self-test", "--doctest", "--across",
              "--root=", "--timeout="),
         lacks=("Traceback", "一件都没找到")),
    Cell("未_打错的旗标", "`--each` 后面打错一个字母：不许当成没给过滤器去跑仓库那一整册",
         2, argv=("--each", "--rooot={T}"),
         has=("我不收这个旗标", "--rooot"), lacks=("逐件真跑", "合计")),
    # ———— A1…A6：收集器**自己那一面**（面 A）—— 2.75 起它也能换一棵树，于是那一面第一次有实例 ————
    # 这一族以前一格都没有：`run_cell` 走的是 in-process `main()`，而 面 A 只认仓库那一棵，
    # 所以「一格子要是钉住了它，别的格子全跟着红」。添了 `--root=` 之后，那六句判决
    # （没找到／不是模块名／导入炸／逐件那一行／0 个用例／合计）句句能在沙盒里说出来。
    Cell("A1_沙盒里正常收一棵", "面 A 换一棵树：逐件那一行、那句合计、那句形状，全对着沙盒说",
         0, argv=("--root={T}",), files=((CELL_SRC, fake(2, RUNS_TAIL)),),
         has=("· good", "合计 2 个用例，0 个失败（1 个模块）", "这条路的形状", "走通 1 件"),
         lacks=("✗", "收集到 0 个用例", "一个模块都没找到")),
    Cell("A2_其中一件白跑", "有一件一条用例都没收到：那句「全过不包括它们」必须点名是谁",
         1, argv=("--root={T}",),
         files=((CELL_SRC, fake(1, RUNS_TAIL)), ("scripts/lib.py", LIB_SRC)),
         has=("✗ lib", "个模块一条用例都没收到", "合计 1 个用例，0 个失败（2 个模块）"),
         lacks=("收集到 0 个用例",)),
    Cell("A3_一件用例都没收到", "整棵一棵用例都没有：那是「什么都没量到」，不是「全过」→ 退 2",
         2, argv=("--root={T}",), files=(("scripts/lib.py", LIB_SRC),),
         has=("✗ 收集到 0 个用例 —— 这不算通过，八成是遍历写歪了。",),
         lacks=("个模块一条用例都没收到", "合计 0 个用例")),
    Cell("A4_那棵树里没有模块", "换了一棵空的：那一句要说**在册范围**，不能喊「检查本仓库的 src」",
         2, argv=("--root={T}",),
         has=("一个模块都没找到", "这一遍一个用例都收不到", "里没有 scripts/ 或 src/"),
         lacks=("逐件真跑", "我不收这个旗标")),
    Cell("A5_沙盒里也有冲突副本", "2.55 那道文件名闸在沙盒里同样响：用例数不许从两份代码里凑",
         2, argv=("--root={T}",), files=(("scripts/good 2.py", fake(1, RUNS_TAIL)),),
         has=("这个不是能导入的模块名", "同步盘的冲突副本", "'good 2'"),
         lacks=("合计 1 个用例",)),
    Cell("A6_导入就炸的那一件", "一件 import 就抛：那一行要报它是谁、炸在哪，且不许读成「0 个用例」",
         1, argv=("--root={T}",),
         files=((CELL_SRC, fake(1, RUNS_TAIL)), ("scripts/boom.py", BOOM_IMPORT)),
         has=("✗ 导入失败 boom: ModuleNotFoundError", "合计 1 个用例，1 个失败（2 个模块）"),
         lacks=("收集到 0 个用例",)),
    Cell("A7_那一件的用例红了", "面 A 的「量到了、有毛病」那一档：逐件那一行要说得出失败几条（壬 的 面 A 版）",
         1, argv=("--root={T}",),
         files=((CELL_SRC, fake(1, RUNS_TAIL, ">>> 6 + 1\n8\n")),),
         has=("✗ good", "个用例，失败", "合计 2 个用例，1 个失败（1 个模块）"),
         lacks=("收集到 0 个用例", "个模块一条用例都没收到")),
    # ———— 酉／戌：两道**预跑闸**自己咬得动吗 —— 拿本件源码的副本当被量件（`spawn` 那一位）————
    # 沙盒里种的是本件自己（改过一处）＋它 import 的那两个邻居；那一遍在闸上就退了，
    # 一格都不跑 —— `lacks` 里那句「扫了基线」钉的就是「一格都没跑」。
    #
    # 酉 那一截期望为什么带着报信自己的标点（「：「护栏那一句…」）：光写「没到屏外了」五个字，
    # 这一格就**自己把那句判决钉回去了** —— 名单是本件的 `has` 摊出来的，副本里那句判决的字面
    # 里正好含着这五个字，那道闸于是说「有格钉着」。（§2.67 那一族第三次长出来：这次长的
    # 是「举例的字面量被自己的尺读到」，而读它的正是那把量字面量的尺。）
    Cell("酉_改了一处没人钉", "§2.74 那一刀的实物：把一句判决改一处，那道闸当场响、且一格都不跑",
         2, argv=("--self-test",), spawn=CELL_SELF,
         files=((CELL_SELF, self_copy(*UNPIN_CUT)),
                ("scripts/baseline_guard.py", neighbor("scripts/baseline_guard.py")),
                ("scripts/work_guard.py", neighbor("scripts/work_guard.py"))),
         has=("源码里有一句判决没格钉着", "：「护栏那一句没到屏外了",
              "没有一格钉着它，也没有一条豁免认下它"),
         lacks=("扫了基线", "逐件真跑")),
    Cell("戌_豁免表白登记", "豁免表里多一条谁都不认的：那一头也要有一行读数，不能只靠上一条",
         2, argv=("--self-test",), spawn=CELL_SELF,
         files=((CELL_SELF, silly_exemption(self_copy())),
                ("scripts/baseline_guard.py", neighbor("scripts/baseline_guard.py")),
                ("scripts/work_guard.py", neighbor("scripts/work_guard.py"))),
         has=("豁免表自己有毛病", "今天不认源码里任何一句判决"),
         lacks=("源码里有一句判决没格钉着", "扫了基线")),
    # ———— R1…R8：`--across` 那一档（2.76）———— 把判决闸摊到整册上，只数不判。
    #
    # 这一族量的不是「缺口少不少」—— 那一头今天整册 278 句，判死它只会把每一遍都变成噪音。
    # 这一族钉的是**那一屏自己会不会说谎**：三种「一件都没读到」的 2、读不通那一档的 1、
    # 只数不判那句 0、跳过冲突副本要自报、点名要递过滤器才点名。
    # 每一格都种在沙盒里，所以「30 件」那一整册在这一族里一格都不出现：这一族量的
    # 是那一屏在**无事可报、有事不判、读不到**三种形状下各说哪一句。
    Cell("R1_across只数不判", "两件、有缺口：那一屏要说三个数，还要自己说一句「缺口不是毛病」→ 退 0",
         0, argv=(ACROSS_FLAG, "--root={T}"),
         files=((CELL_SRC, across_src(1, 2)), ("scripts/lib.py", across_src(1, 0))),
         has=("跨件判决普查", "· scripts/good.py 判决 3 句：钉住 1、缺口 2",
              "· scripts/lib.py 判决 1 句：钉住 1、缺口 0", "句：钉住",
              "合计 2 件里读到 2 件：判决 4 句、钉住 2、缺口 2", "只数不判",
              "上面没有逐句点名", "在册范围不是本仓库"),
         lacks=("✗", "逐句点了名", "同步盘的冲突副本", "一件都没读到")),
    Cell("R2_across递过滤器才点名", "缺口要点名得递过滤器：那一屏要说「按过滤器 …」，还要自报截到几字",
         0, argv=(ACROSS_FLAG, "--root={T}", "good"),
         files=((CELL_SRC, across_src(1, 2)), ("scripts/lib.py", across_src(1, 0))),
         has=("这一遍按过滤器 'good' 把 2 句缺口逐句点了名",
              "第 3 行（屏幕）：「乙0 那一句换了措辞",
              "它自己那些格子里没有一截摊得出这句", "截到 60 字，原句 67 字",
              "字，原句", "· scripts/good.py 判决 3 句：钉住 1、缺口 2"),
         lacks=("上面没有逐句点名", "· scripts/lib.py")),
    Cell("R3_across一件读不通", "一件 AST 过不去、一件读到了：那是「有毛病」的 1，不是「什么都没量到」的 2",
         1, argv=(ACROSS_FLAG, "--root={T}"),
         files=((CELL_SRC, across_src(1, 0)), ("scripts/boom.py", "def f(:\n")),
         has=("✗ scripts/boom.py 读不通（SyntaxError 第 1 行）",
              "合计 2 件里读到 1 件：判决 1 句、钉住 1、缺口 0", "件里读到"),
         lacks=("一件都没读到", "跨件判决普查（1 件")),
    Cell("R4_across全都读不通", "在册的两件一件都没读到：那不许是 0，也不许是 1 —— 什么都没量到，退 2",
         2, argv=(ACROSS_FLAG, "--root={T}"),
         files=(("scripts/boom.py", "def f(:\n"), ("scripts/nul.py", "x = 1" + chr(0))),
         has=("跨件判决普查（2 件", "✗ scripts/boom.py 读不通（SyntaxError 第 1 行）",
              "✗ scripts/nul.py 读不通（SyntaxError）",
              "上面 2 件一件都没读到", "件一件都没读到"),
         lacks=("合计", "只数不判", "上面没有逐句点名")),
    Cell("R5_across冲突副本跳过并自报", "2.55 那一族在 跨件普查 这一档的形状：跳过、但要在收尾说一句是谁",
         0, argv=(ACROSS_FLAG, "--root={T}"),
         files=((CELL_SRC, across_src(1, 1)), ("scripts/good 2.py", across_src(0, 9))),
         has=("跳过 1 份文件名不是模块名的 .py（同步盘的冲突副本）：good 2",
              "它们不进上面那些数", "合计 1 件里读到 1 件：判决 2 句、钉住 1、缺口 1"),
         lacks=("读不通", "一件都没读到", "判决 11 句")),
    Cell("R6_across那棵树里没有在册范围", "换了一棵根本没有 `scripts/` 的树：那一句要说范围，不甩给过滤器",
         2, argv=(ACROSS_FLAG, "--root={T}"),
         has=("一件都没读到", "里没有 scripts/ 或 src/", "这一遍什么都没量到"),
         lacks=("跨件判决普查", "过滤器 'good'")),
    Cell("R7_across过滤器没挑中", "过滤器给得太严：一件都没读到，那一句要说出用的是哪个过滤器、哪几级在册",
         2, argv=(ACROSS_FLAG, "--root={T}", "没有这样一个件"),
         files=((CELL_SRC, across_src(1, 0)), ("src/app.py", across_src(1, 0))),
         has=("一件都没读到（过滤器 '没有这样一个件'", "在册范围 scripts/、src/",
              "这一遍什么都没量到"),
         lacks=("跨件判决普查", "合计")),
    Cell("R8_across也认旗标登记处", "`--across` 后面打错一个字母：不许当成没给过滤器去跑整册",
         2, argv=(ACROSS_FLAG, "--rooot={T}"),
         files=((CELL_SRC, across_src(1, 0)),),
         # 那一格下面钉的必须是**登记处那一句**，不是「屏幕上出现过 `--across` 这四个字」：
         # 同一屏的示例行里也写着 `--across`，只钉那四个字的话，把登记处整句抹掉这一格照样绿
         # （18:3x 那一刀现量：那时满册 37 格一格不红，只有 `refusal` 自己的三条用例咬得住）。
         has=("我不收这个旗标", "--rooot", "`--across`（跨件判决普查，只数不判）"),
         lacks=("跨件判决普查（", "合计")),
    # 这一格是变异台量出来的：18:4x 那一遍把 `survey_file` 里「读不到（X）」那一句 `except`
    # 拆掉（M5），那时满册 37 格全绿、只有 `survey_file` 自己那条用例红 —— 因为 `R3`／`R4` 种的都是
    # 「档在、AST 过不去」，那走的是 `SyntaxError` 那一支，而「路径在册、档根本打不开」那一支
    # 在格子里今天没有实例（§2.71）。种一个目录顶着 .py，走的就是那一支。
    Cell("R9_across那份不是档", "在册清单里有一个目录顶着 .py 的名字：那一行要说「读不到」，且那是 1 不是 2",
         1, argv=(ACROSS_FLAG, "--root={T}"),
         files=((CELL_SRC, across_src(1, 1)), ("scripts/占位.py", AS_DIR)),
         has=("✗ scripts/占位.py 读不到（IsADirectoryError）", "跨件判决普查（2 件",
              "合计 2 件里读到 1 件：判决 2 句、钉住 1、缺口 1"),
         lacks=("读不通", "上面 2 件一件都没读到", "一件都没读到（过滤器")),
    # ———— T1…T5：字递在一扇薄门旁边（2.77），外加一格钉界线 ————
    # 这几格钉的不是措辞，是「递了没人答的那个字有没有到屏幕上」。18 个组合同一张表跑过三棵
    # 树：改前那一棵（`/tmp/prefix277`＝HEAD，表在 `/tmp/probe277e.log`）**10 个静默**退 0
    # （6 个两扇一起递、4 个薄门旁边跟了字）；本节最后一版（`/tmp/final277`，表在
    # `/tmp/probe277f.log`）静默 **0** 个 —— 10 行走门口这一句、6 行走登记处、2 行是
    # `--each`／`--across` 换树那两正当退 0 且带 `scope_note`。那 10 个里最贵的一支是
    # `--doctest --root=<树>` —— 屏幕上给的是**仓库**那一棵，且没有 `scope_note` 来报这一句。
    # `T5` 是这一族里唯一不归门口管的一格：它钉的是「薄门之外那一头走登记处」这条界线。
    # 除 `T2` 之外都在门口就退了（`T5` 连门口都没进），一扇门的体内都没到，所以
    # in-process 就够；`T2` 为什么非得 `spawn`，见它自己那条注释（19:4x 那台变异台拿命换来的）。
    Cell("T1_两扇门一起递", "`--doctest` 与 `--across` 一起递：答一扇，另一扇要点名，且一扇都不许跑",
         2, argv=(DOCTEST_FLAG, ACROSS_FLAG),
         has=("一屏只答一扇门", "答的是 '--doctest'", "'--across' 没答",
              "整册的判决面积：`--across`（只数不判）"),
         lacks=("跨件判决普查（", "个用例", "我不收这个旗标")),
    Cell("T2_薄门前面那扇也不答", "`--self-test` 在前、`--doctest` 在后：答的是 argv[0] 那一扇，基线一格都不跑",
         2, argv=(SELF_TEST_FLAG, DOCTEST_FLAG), spawn=CELL_SELF,
         # 这一格必须 `spawn`，不能 in-process —— 19:4x 现量：把门口那句拆掉（变异台 K1）
         # 之后，in-process 的那一遍会去调 `self_test()`，而 `self_test()` 里又有这一格，
         # 于是基线套着基线一层层往下种，本节那台跑到第六分钟才掐掉。走 `spawn` 就有一道
         # 2.75 装好的安全带接着：副本里的这一格看到 `DEPTH_ENV` 直接报不符，不再往下种。
         files=((CELL_SELF, self_copy()),
                ("scripts/baseline_guard.py", neighbor("scripts/baseline_guard.py")),
                ("scripts/work_guard.py", neighbor("scripts/work_guard.py"))),
         has=("一屏只答一扇门", "答的是 '--self-test'", "每件一个子进程，读的就是那棵树"),
         lacks=("扫了基线", "个用例", "Traceback")),
    Cell("T3_换树那一旗在薄门旁边", "`--doctest --root=<树>`：那一旗在这一档不起作用，屏幕上不许读成「量的是那棵树」",
         2, argv=(DOCTEST_FLAG, "--root={T}"),
         has=("这一扇的体内不收任何参数", "递在它旁边的 '--root=", "没人答",
              "这一遍量的还是本件自己"),
         lacks=("个用例", "在册范围不是本仓库", "合计")),
    Cell("T4_过滤器递在薄门旁边", "位置参数递到 `--doctest` 旁边：它不是这一档的过滤器，要说没人答",
         2, argv=("prober", DOCTEST_FLAG),
         has=("这一扇的体内不收任何参数", "'prober' 没人答"),
         lacks=("个用例", "我不收这个旗标")),
    Cell("T5_那条界线归登记处", "`--across` 在前、`--doctest` 在后：答的那扇自己收旗，那个字归登记处点名，不归门口那一句",
         2, argv=(ACROSS_FLAG, DOCTEST_FLAG),
         files=((CELL_SRC, across_src(1, 1)),),
         # 这一格钉的是**两条出口之间那条界线**：`door_clash` 只接管薄门那一头，所以递在
         # `--across` 旁边的陌生旗走的是它自己的 parser（`R8` 那条通路、登记处那一句）。
         # `has` 里那三截都出自登记处，`lacks` 里那两截出自门口那一句 —— 两句在屏幕上换过来
         # 这一格就红。为什么不用「屏幕上出现过 `--across` 四个字」当证据，见 `R8` 上面那段。
         has=("我不收这个旗标", "给的是 '--doctest'",
              "`--across`（跨件判决普查，只数不判）"),
         lacks=("一屏只答一扇门（答的是", "这一扇的体内不收任何参数",
                "跨件判决普查（", "合计")),
)


# ————————————————————————————————————————————————————————————————
# 那一屏能说的每一句话 —— **由本件源码自己认出来**，不再抄一份挂在代码旁边。
#
# 2.74 那份 `VERDICT_LINES` 是手抄的：同一份规矩在两个地方各写一遍（§2.58 那一族），而它坏的
# 方向不是「会漂」那么轻 —— 往 `each_verdict` 里添一句新判决，名单不响、格子不响、那道预跑闸
# 也不响，于是那句判决从那天起就是「今天没有实例的判决」（§2.71）。本节先量了这件事的面积：
# 手抄那份 16 句，源码里说得出口的是 24 句（15:2x 现数，逐条见下面 `own_sites()` 跑出来的那一屏），
# 差的那 8 句里有面 A 的「✗ 收集到 0 个用例」、有逐件那一行前半截「没答（静态：…」，
# 全都是**今天没有任何一格钉着**的。所以这里删掉那份手抄名单，改成 AST 现认（`verdict_sites`）。
#
# 为什么用 AST 而不按行扫：本件的 docstring 里全是**举例用的假屏幕**（`each_verdict` 那一条就有
# 十几行 `'✗ scripts/x.py …'`），按行扫会把它们一句句读成判决 —— §2.67／§2.73 那一族
# 「举例的字面量会被自己的尺读到」换到这一把尺上是致命的：它会造出一批永远钉不上的判决，
# 然后逼我把判据调松。
MINPIN = 2                        # 字面块剃掉两头标点后至少这么长才算「一句话」
PINCENTER = 4                     # 一截期望要从这句话的**字面**里摊出几个字，才算它钉的是这一句
QUOTE_CUT = 60                    # 点名那一句判决时限到这么多字 —— 截了就在后面自报原句几字（2.61）
CHUNK_TRIM = " \t（），、：；。「」『』`'\"·…|/\\<>="
PUNCTUAL = re.compile(r"[\s—–·…、，。：；（）「」『』|/\\<>=+*—\-]*")

Site = tuple[str, int, tuple[str, ...]]       # (种类, 源码行号, 剃过的字面块)

SITE_WHERE = {                              # 四种位置：句子从哪四个地方出得去
    "毛病": "`problems.append(...)`",
    "读数": "`note =` 与 `note +=`",
    "屏幕": "`print(...)`",
    "收尾": "`return <一句拼好的屏幕话>`",
}


def trim_chunk(text: str) -> str:
    """f-string 的字面块两头常挂着半个括号或一个空格 —— 那不是话，比之前先剃掉。

    >>> trim_chunk("、量的件=")
    '量的件'
    >>> trim_chunk(" 件；")
    '件'
    >>> trim_chunk("✗ 这个不是能导入的模块名：")
    '✗ 这个不是能导入的模块名'
    """
    return text.strip().strip(CHUNK_TRIM)


def pin_cover(chunks: tuple[str, ...], phrase: str, need: int = 0) -> int:
    r"""这一截期望是不是从这句话的字面里**按原顺序**摊出来的 —— 摊出来几个字（摊不出回 0）。

    一句判决在源码里被插值切成几块（`f"没答（静态：{route}，退 {rc}）"` 是三块），屏幕上是
    这几块中间填上东西之后的样子；格子里钉的那一截是那一行里的**任意一段** —— 可以从一块
    字面的中间起、到另一块的中间止。所以「钉住了」的判据既不是「字面块像不像」，
    也不是「那一截完不完整包含某一块」，而是：**存在一种填法，让屏幕上那一句包含这一截**。

    本节一开始拿最长公共子串比，量出来的是一批假判决：逐件那一行的前半截切出来全是
    「答 」「／静态 」 这种两三字的块，重叠永远到不了四个字，于是一句明明钉住了的话
    被报成没实例（15:2x 现量）。第二版改成「连续几块拼一个正则窗口」，漏在另一头：
    格子里钉的常常是一块字面的**前缀**（`"在册范围不是本仓库"` 对源码里的
    「在册范围不是本仓库，是 」），窗口要求整块出现 —— 16:0x 那一遍报了 31 句「没归宿」，
    其中一半是这一处。两头都不是判据太严或太松，是**问错了问题**。

    为什么还要数「摊出几个字」：「合计 」 那种块在哪儿都可能出现，拿它当钉住等于什么都没钉
    —— 门槛就是 `PINCENTER`；同一句里若有一种对齐摊得出更多字，取那一种（不是先找到的那种）。

    两头都必须**站在字面上**，这一条是判据的要害：插值那头可以吞下任意字，
    所以「一截期望只有一头挨着字面、另一头飘在插值里」的对齐一律不算钉住 ——
    16:2x 那一遍就这么放过了一句假判决（`"用例里有 1 个失败"` 曾被当成钉住了
    「合计 {a} 个用例，{b} 个失败（量的件：{n}）」，因为它以 「 个失败」 结尾，
    而那句的头一块字面 「 个用例，」 根本没有出现在这一截里）。三式各钉一种写法：
    **R1** 整截落在同一块字面里；**R2** 起点在一块字面里、终点在另一块字面里、
    中间那几块整块按序出现；**R3** 从某块字面的**头**起、越过它（后面那截是插值）。

    >>> pin_cover(("没答（静态：", "，退", "）"), "没答（静态：没有入口，退 2）")   # R2：头 6 ＋ 中 2 ＋ 尾 1
    9
    >>> pin_cover(("在册范围不是本仓库，是 ", " —— 上面那两行的「N 件」说的都是这一棵"),
    ...           "在册范围不是本仓库")                     # R1：整截落在同一块字面里
    9
    >>> pin_cover(("答 ", "／静态 ", "、量的件=", "、护栏 ", " 条"),
    ...           "答 2／静态 2、量的件=x、护栏 ")           # R2：中间那几块整块、按序出现
    15

    下面三条是**不算钉住**的那三种，各钉一条判据的反面：头站在字面上、尾飘在插值里，只数得
    起头那一块；两头都不在字面上，一个子也数不进来；只有一块字面，R3 要的「越过它」没处越。
    （第三例递成 `("…：", "", "…")` 才有的谈 —— 那个空块是 `_string_bits` 留的插值记号。）

    >>> pin_cover(("答 ", "／静态 ", "、量的件=", "、护栏 ", " 条"), "答 2／静态 2")
    2
    >>> pin_cover(("合计 ", " 个用例，", " 个失败（量的件：", "）"), "用例里有 1 个失败")
    0
    >>> pin_cover(("它去干了自己的活：",), "它去干了自己的活：写 touched.txt")
    0
    >>> pin_cover(("它去干了自己的活：", "", "那一头"), "它去干了自己的活：写 touched.txt")
    9
    >>> pin_cover(("量的不是自己：它报 ", "（{x}）"), "量的不是自己：它报 不是它自己")
    10
    >>> pin_cover(("没答（静态：", "，退", "）"), "没答（静态：没有入口，退 2）", need=8)
    9
    >>> pin_cover(("没答（静态：", "，退", "）"), "答 2", need=8)      # 够不上门槛：立刻收工
    0
    """
    if not phrase or not chunks:
        return 0
    last = len(chunks) - 1
    best = 0

    def stronger(cov: int) -> int:
        nonlocal best
        best = max(best, cov)
        return best

    for i, c in enumerate(chunks):
        if not c:
            continue                                      # 空块是「这里有个插值」的记号，不是字面
        if phrase in c:                                   # R1
            stronger(len(phrase))
        if i < last and phrase.startswith(c) and len(phrase) > len(c):
            stronger(len(c))                              # R3：整块开头 + 越进插值
        if need and best >= need:                         # `need=0` 是「把三种对齐都摊一遍」
            return best
    for i in range(len(chunks)):
        for j in range(i + 1, len(chunks)):                   # R2：两头都站在字面上
            head, mid, tail = chunks[i], chunks[i + 1:j], chunks[j]
            middle = sum(len(m) for m in mid)
            for a in range(len(head)):                        # 起点在这块字面里
                pre = head[a:]
                if not phrase.startswith(pre):
                    continue
                for b in range(1, len(tail) + 1):             # 终点落在那块字面里
                    suf = tail[:b]
                    if not phrase.endswith(suf) or len(pre) + len(suf) > len(phrase):
                        continue
                    body = phrase[len(pre):len(phrase) - len(suf)]
                    pos = 0
                    for m in mid:                             # 中间那几块整块、按序
                        idx = body.find(m, pos)
                        if idx < 0:
                            break
                        pos = idx + len(m)
                    else:
                        stronger(len(pre) + middle + len(suf))
                        if need and best >= need:
                            return best
    return best


def _string_bits(node: ast.expr) -> list[str]:
    """一个串表达式里的字面块，**按屏幕上的顺序**排；每个插值位留一个空串当记号。

    为什么要留那个空块：`f"它去干了自己的活：{detail}"` 屏幕上那一截后面**还有字**，
    而字面只有一块 —— 不留记号，「这一句到这儿就说完了」与「后面是插值」就分不开，
    于是 `pin_cover` 的 R3 那一式没处站（16:2x 现量：丑 那一格明明钉得住，报成没归宿）。
    拼接与三元都拆开，因为判决话常那么写；拆到一个不是串的表达式（`str(n)`、一个变量）
    也留一个空块：那里屏幕上确实有字。

    >>> _string_bits(ast.parse('f"合计 {n} 件"', mode="eval").body)
    ['合计 ', '', ' 件']
    >>> _string_bits(ast.parse('"前" + str(n) + "后"', mode="eval").body)
    ['前', '', '后']
    >>> _string_bits(ast.parse('0', mode="eval").body)
    ['']
    """
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else [""]
    if isinstance(node, ast.JoinedStr):
        return [v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else ""
                for v in node.values]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_bits(node.left) + _string_bits(node.right)
    if isinstance(node, ast.IfExp):
        return _string_bits(node.body) + _string_bits(node.orelse)
    return [""]


def _site_of(kind: str, node: ast.AST, bits: list[str]) -> Site | None:
    """一处判决：留**没剃过的**字面块（钉的时候要比的是屏幕上的原话），
    但「这一处算不算一句话」按剃过标点的版本问 —— 两头各用各的。
    """
    said = [trim_chunk(b) for b in bits if b]
    if not any(len(c) >= MINPIN and not PUNCTUAL.fullmatch(c) for c in said):
        return None                                   # 全是标点和空格：那不是一句话
    return (kind, node.lineno, tuple(bits))


def _template_builders(tree: ast.AST, parents: dict) -> set[str]:
    """只作为「种下去的文件内容」出现过的那些函数 —— 它们造的是**源码**，不是屏幕话。

    判据是形状而不是名单：一个函数如果在整份文件里的每一处调用都落在某层 `Cell(...)` 的参数里，
    它造出来的串就只会落进沙盒那份假件里（`fake`／`liar`／`wrong_label` 三个都是这一族）。
    不排掉它们，名单里就混进 「合计 {count} 个用例，0 个失败（量的件：%s）」 这种**给假件抄的**
    模板 —— 那一句在本件的屏幕上永远不出现，于是这道闸会永远要求我钉一句钉不上的话。

    「落在某层 `Cell` 里」问的是**整条往上之路**，不是最近那层调用：`liar(2)` 的最近调用是
    `fake(…)`，按最近算它就不算「待在格子里」，于是 16:0x 那一遍仍把 `liar` 的 return 读成了
    一句判决 —— 嵌套一层的造源件全在这一条上漏。

    >>> src = ast.parse('print(scope_note(r))\\nCell(files=((P, fake(1, liar(2)))),)\\n')
    >>> parents = {c: p for p in ast.walk(src) for c in ast.iter_child_nodes(p)}
    >>> sorted(_template_builders(src, parents))
    ['fake', 'liar']
    """
    callers: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            in_cell = any(isinstance(p, ast.Call) and isinstance(p.func, ast.Name)
                          and p.func.id == "Cell" for p in _upward(node, parents))
            callers.setdefault(node.func.id, set()).add("Cell" if in_cell else "别的")
    return {name for name, kinds in callers.items() if kinds == {"Cell"}}


def _upward(node: ast.AST, parents: dict):
    """从这一个节点一路走到树根（`parents` 是本件自己算的那份 `{子: 父}`）。"""
    while node in parents:
        node = parents[node]
        yield node


def _enclosing_call_name(node: ast.AST, parents: dict) -> str | None:
    """离这个节点最近的那层调用是谁（`Cell(...)` 里的那些串都归它）。"""
    for p in _upward(node, parents):
        if isinstance(p, ast.Call) and isinstance(p.func, ast.Name):
            return p.func.id
    return None


def _enclosing_function(node: ast.AST, parents: dict) -> str | None:
    for p in _upward(node, parents):
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return p.name
    return None


def _in_sink(node: ast.AST, sinks: set, parents: dict) -> bool:
    """这一个节点（或它的任一祖先）在不在「上屏幕」的那几棵子树里。"""
    return id(node) in sinks or any(id(p) in sinks for p in _upward(node, parents))


def _screen_sinks(tree: ast.AST) -> set:
    """屏幕的入口有哪几处：`print(...)`、`problems.append(...)`、`note =` 与 `note +=`。
    入口的**整棵子树**都算 —— 判决话常是 `print(f"…{survey_line(by)}…")` 这种套了两层的写法。
    """
    sinks: set = set()
    for node in ast.walk(tree):
        into_screen = (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "print") or (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append" and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "problems") or (
            isinstance(node, (ast.Assign, ast.AugAssign)) and _is_note(node))
        if into_screen:
            sinks.update(id(n) for n in ast.walk(node))
    return sinks


def _screen_mouths(tree: ast.AST, parents: dict) -> set[str]:
    """返回值会**上屏幕**的那些函数名 —— 它们才是「这张嘴说得出口的话」真正的出口。

    为什么要有这一条：`flag_answer` 那句 `return "没有应答"` 说的是**档名**，不是说出口的话
    —— 它递出去的值只被 `how == "没有应答"` 这样拿去比，从没上过任何一屏。把它当判决，
    就是要求一格去钉一句本件永远不会说出口的话；而那种要求只会把判据越调越松
    （本节一开始就差点这么办：16:0x 那一遍里 `flag_answer` 一个人贡献了四句「没归宿」）。
    认法跟着**数据**走、不跟名字走（本节不留一份函数名单，理由同上面删掉的那份手抄判决表）：
    `print` / `problems.append` / `note` 那三处子树里出现的调用算出口，一层局部别名
    （`line = survey_line(...)` 之后 `print(line)`）跟着算，出口函数自己 `return` 出去的调用也算。
    三层各钉一类写法，少一层就有一类函数被认错。

    递 `{}` 当父母表的那两例只量「调用」：`print` 自己也在嘴里，那是这一把尺的读法
    —— 它认的是「这一处子树里有嘴」，不是「哪一个函数是嘴」。

    >>> sorted(_screen_mouths(ast.parse('print(say())'), {}))
    ['print', 'say']
    >>> sorted(_screen_mouths(ast.parse('print(a)\\nproblems.append(b)\\nnote = c'), {}))
    ['print']

    别名那一层要有真的父母表才能顺着名字往上走（`_in_sink` 问的是祖先）：

    >>> src = ast.parse('how = classify(s)\\nprint("x" if how else how)')
    >>> parents = {c: p for p in ast.walk(src) for c in ast.iter_child_nodes(p)}
    >>> sorted(_screen_mouths(src, parents))
    ['classify', 'print']
    >>> src = ast.parse('how = classify(s)\\nif how == "没有应答":\\n    pass')
    >>> parents = {c: p for p in ast.walk(src) for c in ast.iter_child_nodes(p)}
    >>> sorted(_screen_mouths(src, parents))     # 只拿去比：从不上屏幕
    []
    """
    sinks = _screen_sinks(tree)
    mouths: set[str] = set()
    alias: dict[str, set[str]] = {}               # 局部名 -> 它的值从哪个调用拿的
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and _in_sink(node, sinks, parents):
            mouths.add(node.func.id)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            alias.setdefault(node.targets[0].id, set()).add(node.value.func.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) \
                and node.id in alias and _in_sink(node, sinks, parents):
            mouths |= alias[node.id]
    for _ in range(len(alias) + 3):               # 「出口函数 return 出去的也算出口」套到不再涨
        grew = set(mouths)
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and node.value is not None \
                    and _enclosing_function(node, parents) in mouths:
                grew.update(c.func.id for c in ast.walk(node.value)
                            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name))
        if grew == mouths:
            break
        mouths = grew
    return mouths


def verdict_sites(src: str) -> list[Site]:
    """从一份源码认出「这张嘴说得出口的每一句」：四种位置、全靠 AST、不扫一行正文。

    每一句带自己的行号，所以名单不是「我记得的那些话」而是**代码现在的形状**：添一句判决
    就得当场多一个格子钉它（或登记一条豁免并写明为什么钉不了），删一句判决则那句豁免会
    变成白登记（下面 `exemption_audit`）。两头都是本节要的读数。

    >>> for kind, line, chunks in verdict_sites(
    ...     'if x:\\n    problems.append(f"字还在、路已死：静态说「{r}」")\\n'):
    ...     print(kind, line, chunks)
    毛病 2 ('字还在、路已死：静态说「', '', '」')
    >>> for kind, line, chunks in verdict_sites('print(f"扫了基线 {n} 格", file=sys.stderr)'):
    ...     print(kind, line, chunks)
    屏幕 1 ('扫了基线 ', '', ' 格')
    >>> verdict_sites('def f():\\n    "假屏幕里写着 ✗ 举例"\\n    return "合计 {n} 件"')
    [('收尾', 3, ('合计 {n} 件',))]
    >>> verdict_sites("print('a')")            # 一个字的块不算一句话
    []
    >>> verdict_sites('print("合计 " + str(n) + " 件")')      # 那个空块记的是插值位
    [('屏幕', 1, ('合计 ', '', ' 件'))]
    >>> verdict_sites('def f():\\n    return "走通" if n else "没有入口"\\nf()')
    []

    最后那一条分两种情形，写在两行上：`return` 的值只被拿去比 → 名单里没有它；而**没人调用过**
    的那一个 `return` 没有证据说它上不了屏幕 → 照样进名单（宁可多问一格，也不放过一句假判决）。

    >>> verdict_sites('def f():\\n    return "这一句谁都没调用过"')
    [('收尾', 2, ('这一句谁都没调用过',))]
    """
    tree = ast.parse(src)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    templates = _template_builders(tree, parents)     # 造源码的那几个函数不算屏幕话
    mouths = _screen_mouths(tree, parents)            # 值到不了屏幕的函数说的是档名，不是话
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    docbits = set()                     # docstring 里那些「举例的假屏幕」不进名单
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docbits.add(id(body[0].value))

    found: dict[int, Site] = {}
    def offer(site: Site | None) -> None:
        if site is None:
            return
        seen = found.get(site[1])
        if seen is None:
            found[site[1]] = site
        else:                           # 同一行两处（一条 print 跨几行拼接）：并成一句
            found[site[1]] = (seen[0], seen[1], seen[2] + site[2])

    for node in ast.walk(tree):
        if id(node) in docbits:
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "append" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "problems" and node.args:
            offer(_site_of("毛病", node, _string_bits(node.args[0])))
        elif isinstance(node, (ast.Assign, ast.AugAssign)) and _is_note(node):
            offer(_site_of("读数", node, _string_bits(node.value)))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "print":
            bits = [b for a in list(node.args) + [kw.value for kw in node.keywords
                    if kw.arg not in ("sep", "end", "file")] for b in _string_bits(a)]
            offer(_site_of("屏幕", node, bits))
        elif isinstance(node, ast.Return) and node.value is not None:
            who = _enclosing_function(node, parents)
            if who is None or who in templates or (who in called and who not in mouths):
                continue                # 造源码的模板、或只拿去比的档名：不是这一屏说的话
            offer(_site_of("收尾", node, _string_bits(node.value)))
    return [found[k] for k in sorted(found)]


def _is_note(node: ast.Assign | ast.AugAssign) -> bool:
    """`note =` / `note +=` 那一位 —— 逐件那一行「——」前面那半截（读数话）。"""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(isinstance(t, ast.Name) and t.id == "note" for t in targets)


def own_sites() -> list[Site]:
    """本件源码里现在说得出口的那些句子（读 `__file__`，不读任何抄本）。"""
    return verdict_sites(pathlib.Path(__file__).read_text(encoding="utf-8"))


# 源码里说得出口、而**这一把尺天生钉不了**的那几句 —— 每一句都得写明为什么。
# 这一张表不是「漏网的口子」：它跟上面那道闸是一件事的两头，写在这里是为了让
# 「钉不了」这件事自己留下一个读数。它若变成白登记（今天没有一句判决靠它），下面
# `exemption_audit` 当场红 —— 一句豁免被格子钉上了，说明那一格能钉，这条豁免就该删。
NOT_PINNABLE: tuple[tuple[str, str], ...] = (
    ("扫了基线", "这一句由 `--self-test` 自己印，而本件没有一格跑 `--self-test`（拿自己当格子"
                 "会绕环）——钉它的是 `selfcheck.py` 那一屏，和 `claims` 拿 `steps()` 那句"
                 "「种 N 格」对 `len(BASELINE)`"),
    ("基线自己有格子写歪了", "这是 `--self-test` 的**预跑闸**那一屏，同上一条：本件的格子跑不到自己"),
    ("上面逐格点名了", "`--self-test` 那一屏的收尾，同「扫了基线」"),
    ("不符的格", "`--self-test` 那一屏的收尾，同「扫了基线」"),
    ("一格都没跑起来", "`--self-test` 那一屏：临时目录建不起来时才会走到，本件的格子没有一格跑自己"),
    ("以下", "`—— 以下 N 格不符期望` 那一行，同「扫了基线」"),
    ("每格把自己那一遍的原文摊出来", "同上"),
    # 2.75 头一遍把名单换成源码现认之后，`own_line` 那两句是量出来**只剩**的两条豁免：
    # 其余每一句要么有格子钉（面 A 那六格、`申`、`酉`、`戌`），要么本来就没有实例。
    ("0 个用例和「全过」在这一屏上同形",
     "`--doctest` 那一档收尾的一句（`own_line` 的 0 条那一支）。格子拿不到它：那一句只在"
     "「跑本件自己那份用例」时说话，而 `--self-test` 的一格若这么跑，就是把 面 A 那一整遍"
     "搬进 面 B —— 两面的红绿焊成一处之后，`selfcheck.py` 里「`doctests` 绿、`doctests-test` 红"
     "只有一种意思」那条读法当场作废。今天真跑它的是 `run_own` 与 `doctest_gate` 那四条用例，"
     "递的是真模块、真分支（0／1／2 三档各一），不是假输出"),
    (" 个失败（量的件：",
     "同上一条，是 `own_line` 的另一支（有失败／全过共用那一行）：`--doctest` 那一档的收尾。"
     "它在别的件的屏幕上每一遍都说（那二十九件走的是同一个函数），但在本件的 `--self-test` "
     "里一格都拿不到，理由与上一条逐字相同"),
)


def _pins(site: Site, phrases: list[str]) -> str:
    """这一句被哪一截钉住了（返回那一截，钉不住回空串）。判据在 `pin_cover` 里，不在这里。"""
    for h in phrases:
        if pin_cover(site[2], h, PINCENTER) >= PINCENTER:
            return h
    return ""


def _aims(fragment: str, site: Site) -> bool:
    """一条豁免认的是**哪一句**：线索词必须是那句某个字面块里的一段连续字。
    豁免与格子的判据故意不一样：格子要摊得出原文（钉一段真的话），豁免只是「这一句我认，理由是下面」，
    让它抄一遍整句只会得到一份新的手抄名单 —— 那正是本节删掉的东西。

    下面三条例子一起把「短线索词」那一档说清楚：`都没跑起来` 五个字同时落在两句不相干的话上
    （第二、三条），那一档由 `exempt_map` 拒收、由 `exemption_audit` 点名；写成六个字的
    `一格都没跑起来` 就吞不到护栏那一句了（第四条）—— 线索词写得越具体，含糊那一档越进不来。

    >>> _aims("扫了基线", ("屏幕", 1, ("扫了基线", "格不符期望")))
    True
    >>> _aims("都没跑起来", ("毛病", 2, ("护栏那一句没到屏幕上（子进程连 work_guard 都没跑起来？",)))
    True
    >>> _aims("都没跑起来", ("屏幕", 3, ("一格都没跑起来：临时目录建不起来。这不算过",)))
    True
    >>> _aims("一格都没跑起来", ("毛病", 2, ("护栏那一句没到屏幕上（子进程连 work_guard 都没跑起来？",)))
    False
    """
    return any(fragment in chunk for chunk in site[2])


def exempt_map(sites: list[Site],
               table: tuple[tuple[str, str], ...] = NOT_PINNABLE) -> dict[int, str]:
    """每条豁免认到的那一行 —— 只有一条线索词**恰好认到一句**时才认。
    认到两句的豁免在这里不生效（那句子照样进 `coverage_gaps` 被点名），
    并由 `exemption_audit` 单独报「含糊」。

    >>> exempt_map([("屏幕", 9, ("扫了基线",))])
    {9: '扫了基线'}
    >>> exempt_map([("屏幕", 9, ("扫了基线", "格不符期望")), ("毛病", 3, ("扫了基线 也在这儿",))])
    {}

    第二条才是「含糊」：那一条线索词认到两句，于是两句都拿不到豁免（它们照旧进
    `coverage_gaps` 被点名），而 `exemption_audit` 另外报一句「同时认到 N 句」。

    >>> exempt_map([("屏幕", 9, ("扫了基线",)), ("毛病", 3, ("一格都没跑起来",))])
    {9: '扫了基线', 3: '一格都没跑起来'}
    """
    out = {}
    for frag, _why in table:
        hit = [s for s in sites if _aims(frag, s)]
        if len(hit) == 1:
            out[hit[0][1]] = frag
    return out


def gap_line(site: Site) -> str:
    """点名一句判决的那半截：`第 N 行（种类）：「……」`，截了要自报原句几字（2.61）。

    从 `coverage_gaps` 里抽出来的，因为 2.76 的 `--across` 那一档要点名**别件**的同一批句子：
    「截到 60 字、自报原句几字」这一条规矩写两遍迟早漂（§2.58）。两档各接自己的后半截
    （本件说「没有一格钉着它」，跨件说「它自己那些格子里没有一截摊得出这句」），
    因为那两句话的**主语不一样** —— 一个是「我的格子没钉住我的判决」，一个是「那件自己的
    格子钉不住它自己的判决」。

    >>> gap_line(("毛病", 7, ("那把尺判错了",)))
    '第 7 行（毛病）：「那把尺判错了」'
    >>> gap_line(("屏幕", 12, ("甲", "乙" * 70))).endswith("截到 60 字，原句 72 字）」")
    True
    >>> gap_line(("屏幕", 12, ("甲", "乙" * 70))).startswith("第 12 行（屏幕）：「甲／乙乙乙")
    True
    """
    said = "／".join(b for b in site[2] if b).replace("\n", "↵")
    return (f"第 {site[1]} 行（{site[0]}）：「{said[:QUOTE_CUT]}"
            + (f"……（截到 {QUOTE_CUT} 字，原句 {len(said)} 字）」" if len(said) > QUOTE_CUT
               else "」"))


def coverage_gaps(cells: tuple[Cell, ...] = BASELINE,
                  sites: list[Site] | None = None) -> list[str]:
    """源码里说得出口、却没有任何一格钉住（也没有一条豁免认下）的那几句 —— 应该为空。

    与 2.74 那一版的同名叫一件事，但判的方向换了：上一版问「名单里每句有没有格钉」，
    名单是我手抄的，所以**问不出「源码里还有一句没人抄进名单」**；这一版问「源码里每句
    有没有格钉」，那一头当场没了。

    >>> coverage_gaps((Cell("好", "x", 0, has=("字还在、路已死：静态说「走通」，它一个字都没答",)),),
    ...               [("毛病", 7, ("字还在、路已死：静态说", "，它一个字都没答"))])
    []
    >>> coverage_gaps((), [("毛病", 7, ("那把尺判错了",))])      # 一个格子都没有
    ['第 7 行（毛病）：「那把尺判错了」 —— 没有一格钉着它，也没有一条豁免认下它']
    >>> coverage_gaps(BASELINE, own_sites())        # 本件此刻：源码认出的判决全有归宿
    []

    上面最后一条与 `exemption_audit` 末尾那条各自「应为空」，中间夹着一条恒等式，2.76 之前
    **没有任何一把尺量它**：本件的缺口集合 == 本件的豁免集合。它今天成立，而且从这两句推得出来
    （这一句空 ⇒ 每句要么有钉要么有豁免；那一句空 ⇒ 每条豁免认到的那句还没被钉住），
    可「推得出来」和「量过」是两件事 —— 19:0x 那一遍就是靠现算才发现两边的行号名单逐字相同。
    下面这一条把恒等式直接摆出来量，不再靠上面两句的语义：

    >>> 判决 = own_sites()
    >>> 钉住的句面 = [h for c in BASELINE for h in c.has]
    >>> 缺口 = {s[1] for s in 判决 if not _pins(s, 钉住的句面)}
    >>> 豁免 = set(exempt_map(判决))
    >>> (len(判决), len(缺口), len(豁免), 缺口 == 豁免)
    (51, 7, 7, True)
    """
    sites = own_sites() if sites is None else sites
    phrases = [h for c in cells for h in c.has]
    allow = exempt_map(sites)
    return [f"{gap_line(site)} —— 没有一格钉着它，也没有一条豁免认下它"
            for site in sites
            if not _pins(site, phrases) and site[1] not in allow]


def exemption_audit(cells: tuple[Cell, ...] = BASELINE,
                    sites: list[Site] | None = None,
                    table: tuple[tuple[str, str], ...] = NOT_PINNABLE) -> list[str]:
    """豁免表自己三种坏法，一种都不许留：白登记、含糊、已被格子钉住（豁免变成推托）。

    为什么这一头也要查：豁免表是这道闸唯一的「允许没有实例」的口子。口子不开不行
    （`--self-test` 那一屏天生没有格子），但**开着的口子必须自己报数**。

    三种坏法对应三件事：
    * **白登记** —— 那条线索词今天不认源码里任何一句（判决被删了，豁免留在那儿变成化石）；
    * **含糊** —— 它同时认到两句以上，那这两句都得不到豁免（`coverage_gaps` 会点名它们）；
    * **多余** —— 它认到的那一句已经有格子钉住了，豁免就该删。

    今天这一张表里只有第一条有实例（`戌` 那一格拿一份多插了一条的表真跑过一遍），
    后两条只有下面这些递进来的假名单当例子 —— 一句实话：那两条的**报法**有例子，
    本件源码里现成的**犯法**没有。它不进名单要求，是因为这些话是 `return` 出去的字符串、
    不是屏幕上的句子（`verdict_sites` 认的是嘴，不认返回值）。

    >>> only = (("扫了基线", "自证"),)
    >>> exemption_audit((), [("屏幕", 1, ("扫了基线", "格不符期望"))], only)   # 在起作用
    []
    >>> exemption_audit((Cell("好", "x", 0, has=("扫了基线 99 格：0 格不符期望",)),),
    ...                 [("屏幕", 1, ("扫了基线", "格不符期望"))],
    ...                 only)                             # 已被格子钉住，豁免多余
    ['豁免「扫了基线」已经多余：第 1 行那一句有格子钉它了 —— 删掉这条豁免']
    >>> exemption_audit((), [("屏幕", 1, ("别的句子",))], only)      # 源码里没这句话
    ['豁免「扫了基线」今天不认源码里任何一句判决 —— 那句话没在源码里，或在格子里改过名了']
    >>> two = (("一格都没跑起来", "自证"),)
    >>> exemption_audit((), [("屏幕", 1, ("一格都没跑起来：临时目录建不起来",)),
    ...                      ("毛病", 2, ("护栏没跑起来？一格都没跑起来",))], two)
    ['豁免「一格都没跑起来」同时认到 2 句（第 1、2 行） —— 一条豁免只许认一句，写得更具体些']
    >>> exemption_audit(BASELINE, own_sites())          # 本件此刻：每条豁免都在起作用
    []
    """
    sites = own_sites() if sites is None else sites
    phrases = [h for c in cells for h in c.has]
    out = []
    for frag, _why in table:
        hit = [s for s in sites if _aims(frag, s)]
        if not hit:
            out.append(f"豁免「{frag}」今天不认源码里任何一句判决"
                       " —— 那句话没在源码里，或在格子里改过名了")
        elif len(hit) > 1:
            out.append(f"豁免「{frag}」同时认到 {len(hit)} 句"
                       f"（第 {'、'.join(str(s[1]) for s in hit)} 行）"
                       " —— 一条豁免只许认一句，写得更具体些")
        elif _pins(hit[0], phrases):
            out.append(f"豁免「{frag}」已经多余：第 {hit[0][1]} 行那一句有格子钉它了"
                       " —— 删掉这条豁免")
    return out


def gate_blindness(cells: tuple[Cell, ...] = BASELINE,
                   sites: list[Site] | None = None) -> list[str]:
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
    >>> gate_blindness(two, [("毛病", 3, ("那把尺判错了",))])   # 两句都靠这一句：删谁都不响
    ['甲', '乙']
    >>> gate_blindness(two, [("毛病", 3, ("那把尺判错了",)),
    ...                       ("毛病", 4, ("只有乙钉着的那句",))])   # 后一句只有乙钉
    ['甲']
    >>> gate_blindness((), [("毛病", 3, ("那把尺判错了",))])    # 一格都没有：没有格子可谈
    []
    """
    sites = own_sites() if sites is None else sites
    return [c.who for c in cells if not coverage_gaps(tuple(d for d in cells if d is not c), sites)]


def sloppy_cells(cells: tuple[Cell, ...]) -> list[str]:
    """格子自己写歪的地方：占位符串错位、同一句又 `has` 又 `lacks`、一句都没钉、
    种的假件根本不入册。

    最后那一条是本件特有的一族：`each_file` 只认「写了用例、文件名像模块名」的 .py，
    所以一格若种了一份零用例的假件，它会**整格空转** —— 一件都没挑出来、退 2、
    而那句 2 看着像判据在响。跑之前先按同一把尺（`example_count`）量一遍种下去的东西。
    那一条只问 `--each` 那一面的格子：面 A 按文件收，零用例的那一件正是它要说的一句话
    （判据分开写在 `runs_each` 里，2.75）。

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
            if not example_count(src) and runs_each(c):
                out.append(f"{c.who}：种的假件 {rel} 一条用例都没写 —— 它不入册，这一格会整格空转")
    return out


def runs_each(cell: Cell) -> bool:
    """这一格跑的是 `--each` 那一面，还是收集器自己那一面（面 A）。

    为什么「种的假件入不入册」要问这一位：`each_file` 只收「写了用例的 .py」，所以零用例的
    假件在 `--each` 那一面会让整格空转；而 面 A 按**文件**收 —— 那正是它「其中 N 个模块一条
    用例都没收到」那一档存在的理由，零用例的那一件在 面 A 这一面**有实例**。
    2.75 之前这条判据两边共用一个形状，于是 `A2`／`A3` 两格一添上来就被这道闸当成写歪。

    `spawn` 那一类（跑沙盒里的本件副本）天生不在 面 A 也不在 `--each` 那一屏上：它种的
    是本件自己和它的邻居，那些文件都有用例，走不到这一条。

    >>> runs_each(Cell("x", "y", 0, argv=("--each", "--root=某棵树")))
    True
    >>> runs_each(Cell("x", "y", 0, argv=("--root=某棵树",)))     # 面 A：收的是文件，不是用例数
    False
    >>> runs_each(Cell("x", "y", 0, argv=("--self-test",), spawn=CELL_SELF))
    False
    """
    return bool(cell.argv) and cell.argv[0] == EACH_FLAG


def run_cell(cell: Cell, base: pathlib.Path) -> tuple[str, str, str]:
    """跑一格：`(判定, 给人看的那句, 抹过沙盒路径的原文)`，判定是 `ok` / `bad`。

    走的是真的 `main()` 而不是 `run_each`：`--each` 那一档怎么被认、`--root=` 怎么递下去、
    那句合计排在哪儿，全是这一格要看的东西（2.56 起的同一取舍）。
    stdout 与 stderr 收进**同一个**缓冲区：那两「件都没挑出来」的句子在 stderr 上。

    `cell.spawn` 非空时换一种跑法：起一个**子进程**去跑沙盒里那一份（`酉`／`戌` 那两格跑的是
    本件自己的副本）。为什么不能 in-process：被量那一份要把 `ROOT` 认成沙盒、要在自己的
    目录里 import 到 `baseline_guard`，而本进程的 `ROOT` 已经是仓库了 —— 换一棵树只能换一次
    进程（`--each` 那一层量的本来就是同一件事）。

    起副本有两道安全带，都是 2.75 头一遍那一分钟里换来的：`DEPTH_ENV` 让**被种出来的那一遍**
    不再往下种，超时那一刀杀的是**整个进程组**（只杀父进程会留下一堆接班的副本，
    2.75 头一遍刀下歪之后现量到的正是那个形状）。
    """
    for rel, body in cell.files:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if body == AS_DIR:                      # 那一格要的是一个顶着 .py 名的**目录**
            p.mkdir()
            continue
        p.write_text(body, encoding="utf-8")
    argv = [a.replace("{T}", str(base)) for a in cell.argv]
    if cell.spawn:
        if os.environ.get(DEPTH_ENV):
            return "bad", "这一格跑在**被种出来的那一遍**里：副本不许再往下起副本", ""
        cmd = [sys.executable, "-X", "utf8", str(base / cell.spawn), *argv]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", DEPTH_ENV: "1"}
        proc = subprocess.Popen(cmd, cwd=base, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, start_new_session=True)
        try:
            text = "".join(proc.communicate(timeout=SPAWN_TIMEOUT))
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.communicate()
            return "bad", f"跑这一格超过了 {SPAWN_TIMEOUT} 秒没回来（那一刀大概没种下去）", ""
        text = hide_tmp(text, base)
        good, why = check_cell(cell, proc.returncode, text)
        return ("ok", "", text) if good else ("bad", why, text)
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

    跑之前四道预跑闸，任何一种都退 2 且**一格都不跑**：格子名带顿号（那一行「不符的格」
    分不开，2.58）、格子自己写歪（`sloppy_cells`）、源码里有一句判决没人钉
    （`coverage_gaps`，名单由 `verdict_sites` 现认）、豁免表里有一条白登记
    （`exemption_audit`）—— 后两道是本节换掉手抄名单之后新加的那一位，理由写在它们自己的说明里。

    退码：0 = 每格都符合期望；1 = 有格子不符（逐格点名）；2 = 一格都没跑，或基线自己写歪了。
    """
    from baseline_guard import guard as guard_names   # 在函数里 import：理由见 `Cell` 那段

    cells = BASELINE if cells is None else cells
    sites = own_sites()                 # 源码里现在说得出口的那些句子：本节只数一遍
    bad_names = guard_names([c.who for c in cells])
    if bad_names:
        print(bad_names)
        return 2
    sloppy = sloppy_cells(cells)
    if sloppy:
        print("基线自己有格子写歪了，改的是基线、不是判据：\n  " + "\n  ".join(sloppy))
        return 2
    gaps = coverage_gaps(cells, sites)
    if gaps:
        print("源码里有一句判决没格钉着（§2.71：今天没有实例的判决等同没测）：\n  "
              + "\n  ".join(gaps))
        return 2
    wasted = exemption_audit(cells, sites)
    if wasted:
        print("豁免表自己有毛病（改的是豁免表、不是判据）：\n  " + "\n  ".join(wasted))
        return 2
    blind = len(gate_blindness(cells, sites))   # 那道闸自己说不响的那一头，跟着真基线现算
    phrases = [h for c in cells for h in c.has]
    allow = exempt_map(sites)
    pinned = sum(1 for s in sites if _pins(s, phrases))
    exempt = sum(1 for s in sites if not _pins(s, phrases) and s[1] in allow)
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
          + (f" —— 源码认出 {len(sites)} 句判决，格子钉住 {pinned} 句、豁免 {exempt} 句；"
             f"那道预跑闸看的是句子，逐格删一遍它响 {len(cells) - blind} 次、不响 {blind} 次"
             if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


# ———— `--across`：把 2.75 那道判决闸摊到整册上（只数不判）————
# `ACROSS_FLAG` 定义在上面 `across_src` 之前：`BASELINE` 里那九格要拿它拼 argv，而那是它之前的事。


class Survey(NamedTuple):
    """一件在 `--across` 那一屏上占的那一行。

    `broken` 非空 = 这一件**没被读到**（档不在、不是 UTF-8 文本、AST 过不去），那一句人话
    就是它那一行的全部内容。为什么把「没读到」并进同一行而不是另起一列：2.62 那一族的教训
    —— 「什么都没量到」跟「量到了、里面有毛病」同形过一次，那一遍整屏读起来像「30 件全查过了」。
    """

    rel: str                       # 相对**被量那棵树**的路径
    sites: list[Site]              # 这一件的屏幕上说得出口的每一句
    gaps: list[Site]               # 其中「它自己的格子没有一截摊得出」的那几句
    broken: str = ""               # 读不到／读不通时那一句人话；读到了是空串


def cell_phrases(src: str) -> list[str]:
    """AST 摊出一份源码里所有 `Cell(...)` 的 `has=` 字面截语 —— **不导入**那一份。

    为什么不导入：这一档一遍要读 30 件，而「导入一件」在那一档里意味着起子进程、挂护栏、
    给它超时（`--each` 为这三件事各写了一层，2.70）。这里要的只是**源码里的字面量**，
    跑起来只会多出两种坏法（起监听的那一件不返回、会写文件的那一件动了盘）。
    `verdict_sites` 量的也是文本，两头同一口径 —— 拿导入的句子去比对文本里认出的句子，
    两本账永远对不平（2.58）。

    `has=` 里递的是变量、生成式、函数调用（今天整册一件都没有）时，`_string_bits` 回一个
    空块、被滤掉：**漏的方向是多报缺口，不是少报**。这一条要紧，所以不另立计数器。

    >>> cell_phrases('Cell("甲", "x", 0, has=("一截", "另一截"), lacks=("不在此列",))')
    ['一截', '另一截']
    >>> cell_phrases('Cell("甲", "x", 0, has=("整截",))\\nCell("乙", "y", 0)')
    ['整截']
    >>> cell_phrases('print("那句 has= 不是格子里的")')         # 一句 `print` 里的字样：不算
    []
    >>> cell_phrases('Cell("甲", "x", 0, has=f"插值 {n} 之后还有字")')   # f-string 摊字面块
    ['插值 ', ' 之后还有字']
    >>> cell_phrases('Cell("甲", "x", 0, has=拼出来的那一句)')          # 摊不出：回空表
    []
    >>> cell_phrases('Celllet("甲", "x", 0, has=("名字不是 Cell 的那一位",))')   # 只认 `Cell`
    []
    """
    out: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Cell"):
            continue
        for kw in node.keywords:
            if kw.arg != "has":
                continue
            elts = kw.value.elts if isinstance(kw.value, (ast.Tuple, ast.List)) else [kw.value]
            for e in elts:
                out += [b for b in _string_bits(e) if b]
    return out


def survey_file(path: pathlib.Path, root: pathlib.Path = ROOT) -> Survey:
    """读一份源码原文，摊出它的判决与缺口；读不通时回一句人话，不抛。

    五种「没读到」各有一句人话（语法过不去 / 源码里有空字节 / 不是 UTF-8 文本 / 是个目录 /
    档读不开）。为什么这一档非要写这五支：它一遍读 30 件，而 2.36—2.63 那几节量到的同一件事是
    **崩在量具里会被读成「这件没问题」** —— 一把尺在第三件上裸崩，屏幕上留下的只有前两件，
    而收尾那句「合计 2 件」看着像「这一册就 2 件」。

    那几句人话是**从数据那一头**走到屏幕上的（`Survey.broken` 是一个字段，`print` 的参数里
    没有它们的字面量），所以 `verdict_sites` 认不到它们、那道预跑闸不会逼格子钉它们。
    格子仍然钉着三条（`R3`／`R4`／`R9`），但那是我自己加的；这一条看不见的路记在 2.76 的边界里。

    「不抛」这一句有范围：**`path` 得在 `root` 这棵范围里**。第一行 `path.relative_to(root)`
    在范围外是抛 `ValueError` 的（19:03:35 现量：传相对路径 `scripts/good.py`、以及传另一棵树的
    绝对路径 `/tmp/clean276/scripts/doc_num.py`，两支都抛 `'…' is not in the subpath of '…'`），
    而它在 `try` 之前 —— 那一支不在上面五支里。
    今天没有活体实例：唯一的 caller 是 `across_rows` 里那一行，它只递 `module_paths(root)`
    长出来的路径，而那个清单本身就是从 `root` 走出来的。所以这一条是**边界**、不是 bug ——
    要它变成判据，得先决定「递错了范围外的路径」该算谁的（报读不到？还是量具自己瞎了）。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     t = pathlib.Path(d)
    ...     (t / "scripts").mkdir()
    ...     _ = (t / "scripts" / "a.py").write_text(across_src(1, 2), encoding="utf-8")
    ...     s = survey_file(t / "scripts" / "a.py", t)
    ...     (s.rel, len(s.sites), len(s.gaps), s.broken)
    ('scripts/a.py', 3, 2, '')
    >>> with tempfile.TemporaryDirectory() as d:
    ...     t = pathlib.Path(d)
    ...     (t / "scripts").mkdir()
    ...     _ = (t / "scripts" / "b.py").write_text("def f(:\\n", encoding="utf-8")
    ...     _ = (t / "scripts" / "c.py").write_text("x = 1" + chr(0), encoding="utf-8")
    ...     _ = (t / "scripts" / "d.py").write_bytes(b"\\xff\\xfe" + "不是 UTF-8".encode())
    ...     (t / "scripts" / "e.py").mkdir()
    ...     print("\\n".join(
    ...         f"{n} → {survey_file(t / 'scripts' / n, t).broken}"
    ...         for n in ("b.py", "c.py", "d.py", "e.py", "没有这个件.py")))
    b.py → 读不通（SyntaxError 第 1 行）
    c.py → 读不通（SyntaxError）
    d.py → 它不是 UTF-8 文本（UnicodeDecodeError）
    e.py → 读不到（IsADirectoryError）
    没有这个件.py → 读不到（FileNotFoundError）
    """
    rel = str(path.relative_to(root))
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as e:                            # 是个目录、没权限、刚被搬走：都不是「它没话说」
        return Survey(rel, [], [], f"读不到（{type(e).__name__}）")
    except ValueError as e:                         # UnicodeDecodeError ⊂ ValueError
        return Survey(rel, [], [], f"它不是 UTF-8 文本（{type(e).__name__}）")
    try:
        sites = verdict_sites(src)
    except (SyntaxError, ValueError) as e:          # 语法过不去、源码里有空字节：摊不出句子
        # 3.12 现量：空字节抛的是 `SyntaxError`（且 `lineno` 是 None，所以那一句不带「第 N 行」），
        # 不是老版里的 `ValueError`。`ValueError` 这一支今天没有实例，留着的方向是「宁可把这一件
        # 报成读不通，也不要静默少一句」—— 它漏的那一头看得见（屏幕上多一行 ✗），不漏的那一头看不见。
        where = f" 第 {e.lineno} 行" if isinstance(e, SyntaxError) and e.lineno else ""
        return Survey(rel, [], [], f"读不通（{type(e).__name__}{where}）")
    phrases = cell_phrases(src)
    return Survey(rel, sites, [s for s in sites if not _pins(s, phrases)])


def across_rows(root: pathlib.Path = ROOT,
                pattern: str = "") -> tuple[list[Survey], list[str]]:
    """`--across` 要读的那些件，和**跳过并自报**的那几份同步盘冲突副本。

    在册范围走 `module_paths`（跟 面 A 同一套，2.75 立的那条：口径只有一份）。为什么不复用
    `each_file`：它筛的是「写了用例的 .py」，而这一档量的不是用例 —— 一件零用例的库照样在
    屏幕上说话，它那几句判决全在缺口列里（跨件普查里最大的那一列就是 `src/cli.py`，
    它一句格子都没有）。

    冲突副本在这里是**跳过**，在 面 A 那一档是**退 2**（`strays` 那段理由）：那一档数的是
    「用例总数」，掺一份旧代码会把数凑谎；这一档数的是「这一件的屏幕上有没有人钉过这句」，
    旧副本只会多钉一句自己的话、不会把别的件的缺口藏起来 —— 所以它不进数、但也不必把整遍判死。
    跳过必须自报，理由同 2.55：一份不该在那儿的源码会让后面所有读数都不能信。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     t = pathlib.Path(d)
    ...     (t / "scripts").mkdir()
    ...     _ = (t / "scripts" / "a.py").write_text(across_src(1, 1), encoding="utf-8")
    ...     _ = (t / "scripts" / "a 2.py").write_text(across_src(0, 3), encoding="utf-8")
    ...     rows, copies = across_rows(t)
    ...     ([r.rel for r in rows], copies)
    (['scripts/a.py'], ['a 2'])
    >>> across_rows(pathlib.Path("/tmp/没有这样一棵树"))          # 那两棵子目录都不在
    ([], [])
    >>> with tempfile.TemporaryDirectory() as d:
    ...     t = pathlib.Path(d)
    ...     (t / "scripts").mkdir()
    ...     _ = (t / "scripts" / "a.py").write_text(across_src(1, 1), encoding="utf-8")
    ...     [r.rel for r in across_rows(t, "没有这样一个件")[0]]
    []
    """
    rows: list[Survey] = []
    copies: list[str] = []
    for path in module_paths(root):
        name = module_name(path, root)
        if strays([name]):
            copies.append(name)
            continue
        rel = str(path.relative_to(root))
        if pattern and pattern not in rel:
            continue
        rows.append(survey_file(path, root))
    return rows, copies


def across_line(rows: list[Survey]) -> str:
    """`--across` 收尾那一句：三个数各归各，外加「只数不判」这一条自己说一句人话。

    「钉住」不另数：它就是 `判决 − 缺口`。写成第三个独立计数就会多出一种坏法 —— 两个数
    加起来不等于第一个，而屏幕上看不出来（只有数会对不上，2.73 那一族）。
    「N 件里读到 M 件」那两个数都要摊：只摊 M，则「30 件里读到 1 件」与「就 1 件在册」同形。

    >>> one = ("屏幕", 1, ("甲乙丙丁",))
    >>> across_line([Survey("a", [one, one, one], [one]), Survey("b", [], [], "读不到")])
    '合计 2 件里读到 1 件：判决 3 句、钉住 2、缺口 1 —— 这一档只数不判：缺口不是毛病，它只说『今天没有一格量过这句』'
    >>> across_line([Survey("a", [], [])])        # 读到了一件、一句判决都没有：三个 0，不是「没量到」
    '合计 1 件里读到 1 件：判决 0 句、钉住 0、缺口 0 —— 这一档只数不判：缺口不是毛病，它只说『今天没有一格量过这句』'
    """
    read = [r for r in rows if not r.broken]
    sites = sum(len(r.sites) for r in read)
    gaps = sum(len(r.gaps) for r in read)
    return (f"合计 {len(rows)} 件里读到 {len(read)} 件：判决 {sites} 句、钉住 {sites - gaps}、"
            f"缺口 {gaps} —— 这一档只数不判：缺口不是毛病，它只说『今天没有一格量过这句』")


def run_across(pattern: str = "", root: pathlib.Path = ROOT) -> int:
    """`--across` 那一档：把 2.75 那道判决闸摊到整册上，**只数不判**。

    为什么只数不判：2.75 那道闸管的是「本件的屏幕上每句判决有没有格子钉」，而其余那二十九件
    的判决从来就没在这道闸下待过 —— 一判就是一片红（18:2x 现量、18:5x 复核同一组数：整册 380 句判决、102 句钉住、
    278 句缺口；本件自己那一行是 49／42／7，跟 面 B 收尾那句逐字对得上）。一片红跟一句没量过
    是同一件事的两种坏法：前者会把后面每一遍都变成噪音。
    所以这一档先把**面积**摊出来，判据留着（下面 `--each` 那一档仍然一件一件真跑）。
    「今天没有实例」那一头由 `selfcheck.py` 里新装的那一步看着：数在屏幕上，谁都能看见它涨。

    退码按 2.62 那三档：**2** = 一件都没读到（包括「读得到的那些是 0 件」）；**1** = 有几件读不通；
    **0** = 读到了 —— 缺口再多也是 0，那是这一档的取舍，不是它漏了。
    """
    rows, copies = across_rows(root, pattern)
    if not rows:
        print(f"✗ 一件都没读到（过滤器 {pattern!r}、在册范围 {scope_names(roster_dirs(root), root)}）"
              " —— 这一遍什么都没量到", file=sys.stderr)
        return 2
    print(f"跨件判决普查（{len(rows)} 件，读的是源码原文：不导入、不跑、也不认豁免表）")
    for row in rows:
        if row.broken:
            print(f"✗ {row.rel} {row.broken}")
            continue
        print(f"· {row.rel} 判决 {len(row.sites)} 句：钉住 {len(row.sites) - len(row.gaps)}、"
              f"缺口 {len(row.gaps)}")
        if pattern:
            for site in row.gaps:
                print(f"    {gap_line(site)} —— 它自己那些格子里没有一截摊得出这句")
    read = [r for r in rows if not r.broken]
    if not read:
        print(f"✗ 上面 {len(rows)} 件一件都没读到 —— 这一遍什么都没量到，不算「全过」",
              file=sys.stderr)
        return 2
    print(across_line(rows))
    if pattern:
        print(f"这一遍按过滤器 {pattern!r} 把 {sum(len(r.gaps) for r in read)} 句缺口逐句点了名")
    else:
        print("上面没有逐句点名：递一个文件名当过滤器（比如 `good`），那些缺口就逐句摊出来")
    if copies:
        print(f"跳过 {len(copies)} 份文件名不是模块名的 .py（同步盘的冲突副本）："
              + "、".join(copies) + " —— 它们不进上面那些数")
    note = scope_note(root)
    if note:
        print(note)
    return 1 if len(read) < len(rows) else 0


# ————————————————————————————————————————————————————————————————
# 四扇门：一屏只答一扇。2.76 之前「递两扇」与「薄门旁边跟了字」这两种都是**安静**的
# —— 退 0、屏幕上读的是其中一扇，另一扇一个字不提。同一张 18 行的组合表跑过三棵树：
# 改前那一棵（HEAD，`/tmp/probe277e.log`）里 **10 个静默**（6 个两扇一起递、
# 4 个薄门旁边跟了字）；本节最后一版（`/tmp/probe277f.log`）静默 **0** 个 —— 10 行走
# 门口这一句、6 行走登记处（答的那扇自己收词）、2 行正当退 0 且带 `scope_note`。
# 那 10 个里最贵的一支是 `--doctest --root=<树>` —— 用户要量那棵树，屏幕上给他的是
# **仓库**那一棵，且没有 `scope_note` 来报这一句（2.75 换树那一位从此处走的正是那个环境变量）。
# 这一位不收 argv 的任何形态，只做一件事：把「有人递了、这一遍没答」说出口。
DOORS: tuple[str, ...] = (SELF_TEST_FLAG, EACH_FLAG, ACROSS_FLAG, DOCTEST_FLAG)

# 「薄」的是那两扇的**体内不收任何参数**：`self_test()` 与 `run_own(本件)` 都不看 argv，
# 所以递在它们旁边的任何一个字，既没人答、也没人说不答。`--each`／`--across` 不在这一列，
# 也**不归这一位管** —— 它们自己收 `--root=`／`--timeout=`／过滤器，认不出的字早有出口
# （`午`／`未`／`R8` 三格钉着 `refusal` 那一句）。20:12 现量：`--across --doctest` 在本节动手
# **之前**就退 2、点的正是 `'--doctest'` 那三个字，所以这一位只管薄门那一头 ——
# 一条界线一个出口（§2.58），界线本身由 `T5` 钉着。
THIN_DOORS: frozenset[str] = frozenset({SELF_TEST_FLAG, DOCTEST_FLAG})


def door_answered(argv: list[str]) -> str:
    """按 `main` 那一串分发顺序，这一遍真正答的是哪一扇；一扇都不答时回空串。

    为什么要有这一句而不直接在 `main` 里判断：`main` 里那四句 `if` 是**跑法**，
    「哪一扇答」是它的一个读数。两处各写一遍是 §2.58 那一族，所以这一位是唯一的
    读法出口。而它与 `main` 那一串是否真的同口径，今天只有**一格**钉得住 —— 21:01 现量
    （变异台 K9：把 `--doctest` 那一支挪到四句最前，这一位一个字不动）：
    `--across --doctest`／`--each --doctest` 两支回到静默退 0，满册 43 格里只红
    `T5_那条界线归登记处` 一格、面 A 309 条全绿；`T1`—`T4` 仍绿，因为它们在门口就被
    拦下、走不到那四句。这一位自己的 6 条用例钉的是**这一位的读数**，钉不住这一句配对。
    顺序也与 2.69 那条老账有关：其余九把尺里 `--doctest` 排在 `--self-test` 之前（同一棵
    树上 21:00 现量 27 次探测：两扇一起递的 18 次全静默，且 18 次答的都是 doctest，
    逐条见 `/tmp/probe277nine.log`），本件是反过来的 —— 本件这一句读的是 argv[0] 那一扇，
    只有它不是那三扇之一时才轮到 `--doctest`。那一处口径不同本节不在这段里统一，
    连同上面那条配对欠账一起记在 2.77 的边界里。

    >>> door_answered(["--doctest"])
    '--doctest'
    >>> door_answered(["--self-test", "--doctest"])
    '--self-test'
    >>> door_answered(["--doctest", "--self-test"])
    '--doctest'
    >>> door_answered(["prober", "--doctest"])
    '--doctest'
    >>> door_answered(["--each", "--across"])
    '--each'
    >>> door_answered(["--root=/tmp/x"])
    ''
    """
    if argv and argv[0] in (SELF_TEST_FLAG, EACH_FLAG, ACROSS_FLAG):
        return argv[0]
    if DOCTEST_FLAG in argv:
        return DOCTEST_FLAG
    return ""


def door_clash(argv: list[str]) -> tuple[str, tuple[str, ...]] | None:
    """这一遍有没有字递了没人答？有就回（答的那扇, 被丢下的字），没有回 `None`。

    **只管薄门**（`THIN_DOORS` 的注释里记了为什么）：答的是 `--each`／`--across` 时，
    递在它旁边的陌生旗由它自己的 parser 送去登记处点名，这一位一句都不抢 ——
    20:12 现量：那两扇在本节动手之前就会退 2，抢过来只会把一句带名单的话换成一句短的。

    薄门这一头有两种坏法要分开说，因为它们要说的话不一样：
    （一）**两扇门一起递** —— `--doctest --across`：答 doctest，`--across` 没答。
    （二）**薄门旁边跟了字** —— `--doctest --root=<树>`：那一旗在这一档根本不起作用，
      而屏幕上那一遍读的是本件自己，看不出被换过。今天最贵的一种。

    >>> door_clash(["--doctest"]) is None
    True
    >>> door_clash(["--each", "--root=/tmp/x", "--timeout=2"]) is None
    True
    >>> door_clash(["--across", "--rooot=/tmp/x"]) is None   # 打错的旗：那一档自己会点名
    True
    >>> door_clash(["--each", "--across"]) is None           # 两扇一起递，可答的那扇收旗：归登记处
    True
    >>> door_clash([]) is None
    True
    >>> door_clash(["--doctest", "--across"])
    ('--doctest', ('--across',))
    >>> door_clash(["--self-test", "--doctest"])
    ('--self-test', ('--doctest',))
    >>> door_clash(["--doctest", "--root=/tmp/x"])[1]        # 最贵那一支：换树没换
    ('--root=/tmp/x',)
    >>> door_clash(["prober", "--doctest"])
    ('--doctest', ('prober',))
    """
    answered = door_answered(argv)
    if answered not in THIN_DOORS:
        return None
    dropped = tuple(a for a in argv if a != answered)
    return (answered, dropped) if dropped else None


def clash_line(answered: str, dropped: tuple[str, ...]) -> str:
    """被丢下的那几个字怎么说 —— 与 `refusal` 并列的第二句登记话：那一句管「这旗我不收」，
    这一句管「这旗我收了、可这一遍答的不是它」。

    两条出口各自是屏幕上的一句判决：`T1`—`T4` 四格钉的是这一句（`--self-test`／`--doctest`
    薄门旁边那一头），`T5` 钉的是那条界线本身 —— 同一句 `--doctest` 递在 `--across` 旁边
    归登记处、递在 `--doctest` 自己旁边归这一句；
    末尾那一句「想量什么用什么」跟着两条一起走（它自己不是单独一句，所以那道预跑闸看不见它 ——
    §2.76 那条边界讲的正是这种「塞进变量再拼进去」的形状，本节选择让格子多钉一句而不是让闸多认一句）。

    >>> print(clash_line("--doctest", ("--across",)).splitlines()[0])
    ✗ 一屏只答一扇门（答的是 '--doctest'，递进来的 '--across' 没答）。
    >>> print(clash_line("--doctest", ("--root=/tmp/x",)).splitlines()[0])
    ✗ `--doctest` 这一扇的体内不收任何参数：递在它旁边的 '--root=/tmp/x' 没人答，这一遍量的还是本件自己。
    """
    names = "、".join(repr(a) for a in dropped)
    guide = ("    要换一棵树量：`--each --root=<树>`（每件一个子进程，读的就是那棵树）；"
             "整册的判决面积：`--across`（只数不判）。")
    if any(a in DOORS for a in dropped):
        return (f"✗ 一屏只答一扇门（答的是 {answered!r}，递进来的 {names} 没答）。\n" + guide)
    return (f"✗ `{answered}` 这一扇的体内不收任何参数：递在它旁边的 {names} 没人答，"
            "这一遍量的还是本件自己。\n" + guide)


def refusal(given: str, bad: list[str] | None = None) -> str:
    """「这个旗标我不收」那一句 —— 本件唯一的旗标登记处。

    为什么单独抽成一个函数：这一句就是本件的 `--help`。2.69 记过那条理由（命令尺拿文档里
    每一条长参数去问 `--help`，所以「只写在收尾、`--help` 里没有」会被读成「照抄会失败」），
    而本件**故意没有 argparse** —— 它收一个位置参数当过滤器，挂一把握关就得为了两个旗
    重写整个入口（`check_doc_cmds` 里那句「目标脚本没建关」的豁免认的就是这件事）。
    登记处塌缩成这一句之后，「添了旗标忘改这一句」就等于那一旗没人知道存在 ——
    所以 `午_不认的旗标` 那一格逐条钉着它，而不是钉一份 nobody 读的清单。

    2.77 起这一句不再是唯一的登记话：门口那一句（`clash_line`）与它并列 —— 这一句管
    「这个旗我不收」，那一句管「这个旗我收了、可这一遍答的不是它」。**能收的旗名只写在这里**，
    那一句不列名单（它只点名被丢下的那几个字），所以添一扇门只改一处（§2.58）。

    `bad` 是 `--each` 后面那几个认不出的字（可以不止一个）；不递时就是开头那一个。

    >>> refusal("--nope").splitlines()[0]
    "✗ 我不收这个旗标（给的是 '--nope'）。收的只有这几个：`--each`（每件一个子进程真跑）、`--self-test`（跑本件的基线）、`--doctest`（只跑本件那份用例）、`--across`（跨件判决普查，只数不判）；`--root=<路径>` 三档都收，`--timeout=<秒>` 只管 `--each`（收集器不起子进程，没有一件的天花板可言）；一屏只答一扇门：`--doctest`／`--self-test` 这一对薄门体内不收任何参数，把任何别的字递在它们旁边会退 2 点名（2.77）；`--each`／`--across` 自己收旗，它们那一头的陌生旗标由上面那半句点名。"
    >>> refusal("--each", ["--rooot=/tmp/x"]).splitlines()[0]
    "✗ 我不收这个旗标（给的是 '--rooot=/tmp/x'）。收的只有这几个：`--each`（每件一个子进程真跑）、`--self-test`（跑本件的基线）、`--doctest`（只跑本件那份用例）、`--across`（跨件判决普查，只数不判）；`--root=<路径>` 三档都收，`--timeout=<秒>` 只管 `--each`（收集器不起子进程，没有一件的天花板可言）；一屏只答一扇门：`--doctest`／`--self-test` 这一对薄门体内不收任何参数，把任何别的字递在它们旁边会退 2 点名（2.77）；`--each`／`--across` 自己收旗，它们那一头的陌生旗标由上面那半句点名。"
    >>> refusal("--each", ["--a", "--b"]).splitlines()[0]      # 不止一个：全点出来
    "✗ 我不收这个旗标（给的是 '--a'、'--b'）。收的只有这几个：`--each`（每件一个子进程真跑）、`--self-test`（跑本件的基线）、`--doctest`（只跑本件那份用例）、`--across`（跨件判决普查，只数不判）；`--root=<路径>` 三档都收，`--timeout=<秒>` 只管 `--each`（收集器不起子进程，没有一件的天花板可言）；一屏只答一扇门：`--doctest`／`--self-test` 这一对薄门体内不收任何参数，把任何别的字递在它们旁边会退 2 点名（2.77）；`--each`／`--across` 自己收旗，它们那一头的陌生旗标由上面那半句点名。"
    """
    names = [given] if bad is None else bad
    return ("✗ 我不收这个旗标（给的是 " + "、".join(repr(a) for a in names) + "）。"
            "收的只有这几个：`--each`（每件一个子进程真跑）、"
            f"`{SELF_TEST_FLAG}`（跑本件的基线）、`{DOCTEST_FLAG}`（只跑本件那份用例）、"
            f"`{ACROSS_FLAG}`（跨件判决普查，只数不判）；"
            "`--root=<路径>` 三档都收，`--timeout=<秒>` 只管 `--each`"
            "（收集器不起子进程，没有一件的天花板可言）；"
            "一屏只答一扇门：`--doctest`／`--self-test` 这一对薄门体内不收任何参数，"
            "把任何别的字递在它们旁边会退 2 点名（2.77）；"
            "`--each`／`--across` 自己收旗，它们那一头的陌生旗标由上面那半句点名。\n"
            "位置参数不是旗标，是模块名里的一个子串：\n"
            "    .venv/bin/python scripts/run_doctests.py            # 全部\n"
            "    .venv/bin/python scripts/run_doctests.py prober     # 只跑名字含 prober 的\n"
            "    .venv/bin/python scripts/run_doctests.py --each     # 每件一个子进程，真跑\n"
            "    .venv/bin/python scripts/run_doctests.py --self-test  # 往沙盒种假件，量这条跑法\n"
            "    .venv/bin/python scripts/run_doctests.py --across   # 跨件判决普查：只数不判")


def main(argv: list[str]) -> int:
    for p in (str(ROOT), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)

    # 这支脚本收的旗全部登记在 `refusal` 那一句里：`--each`（2.70）、`--self-test`（2.74）、
    # `--doctest`（2.69），加上 2.75 起的 `--root=`、2.76 起的 `--across`。
    # 递给它一个没收过的旗标，以前它会当成过滤器去匹配、匹配不到，然后回一句「检查 src/ 和
    # scripts/ 还在不在」—— 那句诊断是**错的**（目录好好的，是我参数给错了）。09-24 我自己
    # 踩过一次，见 2.56。
    # 2.77 在这四句之前先问一句 `door_clash`：把字递在一扇**薄门**旁边（`--self-test`／
    # `--doctest` 的体内不看 argv），以前是**安静**的（退 0、答那一扇、那些字一个字不提）。
    # 这一句不许改变任何一扇单独递时的答法 —— 它只把「有人递了、这一遍没答」那一半接管过来；
    # 另一半（答的那扇自己收旗、递进来一个它也不收的字）本来就归下面那三句
    # `refusal(argv[0], bad)` 管，两条出口各自一条界线，见 `THIN_DOORS` 上面那段。
    clash = door_clash(argv)
    if clash:
        print(clash_line(*clash), file=sys.stderr)
        return 2
    if argv and argv[0] == SELF_TEST_FLAG:
        return self_test()
    if argv and argv[0] == EACH_FLAG:
        opts, rest, bad = each_options(argv[1:])
        if bad:
            print(refusal(argv[0], bad), file=sys.stderr)
            return 2
        return run_each(rest[0] if rest else "", **opts)
    if argv and argv[0] == ACROSS_FLAG:
        # 同一扇门、同一套取舍：`--root=` 换树、位置参数当过滤器、认不出的字退 2 并点名。
        root, pattern, bad = own_options(argv[1:])
        if bad:
            print(refusal(argv[0], bad), file=sys.stderr)
            return 2
        return run_across(pattern, root)
    if DOCTEST_FLAG in argv:
        # 这一旗以前只在收尾那一句 `doctest_gate(sys.argv[1:])` 里被认，于是「从别的件里调
        # `main(['--doctest'])`」会一路走到下面的旗标登记处。搬进来之后**入口只有一处**
        # （两扇门各认一次是 2.58 那一族），而量的永远是本件那一份用例 —— `run_own` 记过
        # 「不点名就量了调用方」，这一位用 `sys.modules[__name__]` 而不是 `__main__`，
        # 从沙盒里调与从命令行调读的是同一件。
        return run_own(sys.modules[__name__])
    root, pattern, bad = own_options(argv)
    if bad:
        print(refusal(bad[0], bad), file=sys.stderr)
        return 2

    rows = [(module_name(p, root), p) for p in module_paths(root)
            if not pattern or pattern in module_name(p, root)]
    names = [n for n, _ in rows]
    if not names:
        # 那一档换成了「说在册范围」而不是「检查 src/ 和 scripts/」：2.75 起这一档能换一棵树，
        # 而「检查本仓库那两个目录」在量沙盒的一遍里是一句**错诊断**（同一个病换了方向）。
        print(f"✗ 一个模块都没找到（在册范围 {scope_names(roster_dirs(root), root)}）"
              " —— 这一遍一个用例都收不到，不算「全过」", file=sys.stderr)
        return 2

    odd = strays(names)
    if odd:
        for n in odd:
            print(f"✗ 这个不是能导入的模块名：{n!r}"
                  f" —— 同步盘的冲突副本？先把它弄出这两个目录（`src/` 与 `scripts/`，"
                  f"两边都扫），不然用例数是从两份代码里凑的")
        return 2

    attempted = failed = 0
    quiet: list[str] = []
    for name, path in rows:
        try:
            mod = import_at(path, name, root)
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
    unhost()      # 换树那遍插进去的导入根收到这里为止：后面的收尾话不再量 anybody

    if attempted == 0:
        # 2.62 那一档：一个用例都没收到是「什么都没量到」，与「量到了、其中有几条不对」
        # 不是一回事 —— 以前这一句退 1，于是「遍历写歪了」跟「有用例红了」在退码上同形。
        print("\n✗ 收集到 0 个用例 —— 这不算通过，八成是遍历写歪了。")
        return 2
    print(f"\n合计 {attempted} 个用例，{failed} 个失败（{len(names)} 个模块）")
    if not pattern:
        # 只在全量那一遍印：这一句说的是整棵树的形状，递了过滤器之后它就不成立了。
        line = survey_line(survey_routes(roster_dirs(root), root))
        if line:
            print(line)
    note = zero_note(quiet)
    if note:
        print(note)
    note = scope_note(root)
    if note:
        print(note)
    return 1 if (failed or quiet) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
