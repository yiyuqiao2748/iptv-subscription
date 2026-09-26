r"""量一遍「写在代码里的话」—— docstring 里那些报数的句子，那个数今天还对不对（计划书 2.60）。

为什么要有它：2.59 收口时顺手量到一件事 —— 别的尺都在读**文档**，`run_doctests` 会跑说明书里的
例子、可它一个字都不读例子**外面**的那些字。于是 `scripts/selfcheck.py` 里那句「默认十条」的说明，
在步数从四涨到十的过程里连着红了四轮都没人看见（2.55／2.56／2.57 三条追记各改一次，追记写的就是
「上面那句没动」）。那一层里数得出来源的五处，2.59 是**人对着日志一条条改掉的**，不是被闸拦下来的
—— 装闸就是这一节。

为什么不是一把「把 docstring 里每个数都核一遍」的尺：那样写过三遍，一遍比一遍糟。18:04 那遍
甲 49（对 4／不合 45），18:06 那遍把函数 docstring 也扫进去之后 甲 161（对 9／不合 152）。
三条原因都是量出来的（见「边界」）：汉语把「一格／一条／一个」当**冠词**用（那 152 条里 42 条是
「这一格」「每格」「一格都没跑起来」，它们不是数），函数 docstring 里大半是 `>>>` 示例（那是
**读数**不是声明），和「同一句里点名两把尺」。所以这把尺只认两种**能当场算出真值**的形状：

  甲 `N 格`（**只认阿拉伯数字**）—— 真值是 `ALIASES` 里每一位各自 `len(BASELINE)`，现取。
     这一句若用反引号点了主人（`doc-cmds`、`num-test` 那类别名也算），就必须等于**那一位**的格数；
     没点名则只要求它属于真值集合。只认阿拉伯数字这一刀顺带解决了冠词与历史复述：
     汉语写「那一格」「四条默认」从不用阿拉伯数字。
  乙 `默认 N 条` 与 `N 条离线尺` —— 真值是 `selfcheck.steps()` 现算的步数（汉字数字也认，
     因为这一句本来的写法就是「默认十条」）。

它不量什么，把边界一并说清（每一条都是这一遍量到的现状，不是猜想）：
  · docstring 里**没有真值可算**的那些数不量 —— 而且它们**不进任何计数**：结论行那个「跳过」只统计
    被这两种形状逮到、又被豁免的处数（18:34:40 那遍：核 21 处、跳过 doctest 区 6 处、「」内复述
    11 处，而「99 个台」那种连形状都不对的字一个都没被数过）。所以「0 处对不上」说的是
    **这 21 处**，不是「代码散文里的数都对」。
  · `>>>` 示例里的数不量 —— 那是**读数**，核它等于把量具的说明书当判据。
  · 被 「」 括起来的复述不量（2.56 那三条追记全靠这一条豁免）。代价也说清：**把该核对的话塞进
    引号就能躲过这把尺**。这一节认这个代价 —— 「复述当时的措辞」是这一层里唯一「数故意是旧的」
    那一类，误伤的代价（追记整片红）比漏一条的代价大。
  · **函数体里的字符串字面量不在范围内**：`selfcheck.steps()` 那五条步骤说明各写着一个格数
    （15／25／26／22／22），18:34 那一遍一个都没读到。读它们要把任意字符串都扫进来，而那一层里
    满是 `print("比了 N 处")` 这种运行时输出 —— 先把「运行时印的数」和「声明」分开，再说扫不扫。
  · 「九条默认」「两条要点名」那种**数在前、名在后**的写法不认（只认 `默认 N 条` 与 `N 条离线尺`），
    因为它们各自的真值口径今天还不唯一。

    ./.venv/bin/python -X utf8 scripts/code_claims.py                   # 量仓库自己（离线，不写任何文件）
    ./.venv/bin/python -X utf8 scripts/code_claims.py --py a.py,b.py    # 只量点名的那几份
    ./.venv/bin/python -X utf8 scripts/code_claims.py --verbose         # 把跳过的分档也摊开
    ./.venv/bin/python -X utf8 scripts/code_claims.py --self-test       # 往临时目录里种已知的假件
    ./.venv/bin/python -X utf8 scripts/code_claims.py --doctest         # 只跑它自己的用例

退出码：**0 = 每一处引用都对得上**；**1 = 量到了，但有引用对不上，或点名的件有一份没读进来**
（这一屏因此只覆盖读进来的那几份）；**2 = 一处都没查到** —— 点名的 .py 全没读到、没有一个文件里
有这两种形状、或**真值本身取不到**（那是「没查到」，不是「都对」）。
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:      # 邻居们互相 import，与 2.56~2.59 同一手法
    sys.path.insert(0, str(ROOT / "scripts"))

import doc_num  # noqa: E402
from doc_num import (SANDBOX, Cell, build_cell, fill, hide_tmp,  # noqa: E402
                     ragged_cells, unresolvable)
# `braced_cells`（沙盒占位符写成花括号那道闸）只有 `unmarked_nums` 里有一份。第五把再抄一份
# 就是 2.58 刚收掉的那种毛病，所以这里直接拿邻居的。
from unmarked_nums import braced_cells  # noqa: E402
from baseline_guard import guard as guard_names  # noqa: E402
# 「跑自己那份用例、收尾说一句」这一支的口径只有一份（2.68）：`run_doctests` 是收用例的那一个，
# 这句话该由它说。以前这里写的是 `doctest.testmod(verbose=False).failed` —— 量到 31 条和
# 一条都没量到，屏幕上都是 0 字节。
from run_doctests import DOCTEST_FLAG, SELF_TEST_FLAG, arg_door_answered   # noqa: E402
from run_doctests import arg_door_exit, run_own   # noqa: E402

PY = "假件.py"                                   # 沙盒里种的那个「被量的代码」
COPYISH = re.compile(r"\s\d+\.py$")             # `check_doc_cmds 2.py` 那种同步盘冲突副本
CN = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
      "八": 8, "九": 9}
CN_TAIL = "一二三四五六七八九"
NUM = r"(?:[0-9]+|[零一二两三四五六七八九十]+)"
# 「格式／格局／格调／格言」不是「N 格」那个格：零成本的假阳性，钉住。
# **甲只认阿拉伯数字**，这是量出来的不是猜的：18:23:25 那一遍 allowing 汉字后 93 处里 74 处「对不上」，
# 逐条看过去全是「一**格**都没跑起来」「这**一格**的用例」「两**格**的行为」—— 汉字那一半在这个词上
# 基本是冠词/指示形容词，不是在数数（同族还有 `每格`，那个连数都没有）。阿拉伯数字没有这个病：
# 本仓库里没有谁会写「1 格都没跑起来」。代价说清楚：将来谁真用汉字写格数（「二十六格」）这里读不到，
# 那是**漏**不是**错**，而漏的方向是少报，不会把绿的报成红的。
GRID = re.compile(r"(?<!\d)([0-9]+)\s*格(?!式|局|调|言)")
SC_DEFAULT = re.compile(rf"默认\s*({NUM})\s*条")
SC_OFFLINE = re.compile(rf"({NUM})\s*条\s*离线尺")
QUOTE = re.compile(r"「[^」]*」")
SPLIT_SENT = re.compile(r"[。；！？]")
# 一把尺的别名：散文里点主人不会总用模块名。`doc-test` 点的是 `check_doc_cmds`，`names` 点的是
# `stray_names`（那是它在 selfcheck 里那一步的名字）。少一别名，那一处引用就退化成「没点名」。
ALIASES: dict[str, tuple[str, ...]] = {
    "stray_names": ("stray_names", "names"),
    "check_doc_cmds": ("check_doc_cmds", "doc-cmds", "doc-test"),
    "doc_num": ("doc_num", "numbers", "num-test"),
    "unmarked_nums": ("unmarked_nums", "unmarked", "um-test"),
    "code_claims": ("code_claims", "claims", "claims-test"),
    # 2.64 那两把：`epg-test` 点的是 `epg_check`，`drift-test` 点的是 `table_drift`。
    # 漏了它们会怎么样：那两把的说明书里写着 14 格／9 格，而这两个数不在任何一位
    # 已知主人的格数集合里 —— 21:51:26 拿一份 /tmp 副本、只在副本里把下面这两行删掉重跑，
    # 红回来 4 处（`epg_check.py` 的模块与 `no_network`、`selfcheck.py` 追记里那两处），
    # 报的都是`没点名，只要求属于 15/22/26/29`；别名装回去同一份副本退 0（21:52:39）。
    "table_drift": ("table_drift", "drift", "drift-test"),
    "epg_check": ("epg_check", "epg", "epg-test"),
    # 2.65 那一把不一样：`lean_playlist` 不是尺，是 `build` 主路上会写文件的生产件。
    # 别名这一层不区分这两件事 —— `selfcheck` 的散文里写「那 12 格」时点的名字就是 `lean-test`，
    # 少了这一行它就退化成「没点名，只要求属于 15/22/26/29」（2.64 那一遍量到的正是这个形状）。
    "lean_playlist": ("lean_playlist", "lean-test"),
    # 2.72 那一把：`heads` 与 `heads-test` 点的是 `doc_headings`。这一行是本节**量出来**的，
    # 不是照着上面那一族抄的 —— 步骤装完之后 `claims` 全场只报一处对不上（10:36:17 那三遍的
    # 中间那遍：「`selfcheck.py:steps` 说 格 28、真值是 没点名，只要求属于 9/12/14/15/23/26/30/35」），
    # 那 28 格正是刚装好那把尺的真实格数（2.64 那两把的来路一字不差）。
    "doc_headings": ("doc_headings", "heads", "heads-test"),
    # 2.74 那一把：`doctests-test` 点的是 `run_doctests`。它守的与前面九位都不是一层 ——
    # 不是「一把尺的读数」，是「逐件真跑那一档会不会说话」；别名这一层不区分这两件事，
    # 而 `selfcheck` 的散文里写「那 18 格」时点的名字正是 `run_doctests`（2.64/2.72 同一族）。
    "run_doctests": ("run_doctests", "doctests", "doctests-test"),
}


def to_int(tok: str) -> int | None:
    """`十二`／`12`／`两` → 12；认不出返回 None（**不猜**）。

    >>> to_int("12"), to_int("十二"), to_int("二十一"), to_int("两")
    (12, 12, 21, 2)
    >>> to_int("百") is None, to_int("") is None
    (True, True)
    """
    if tok.isdigit():
        return int(tok)
    if "十" in tok:
        head, _, tail = tok.partition("十")
        tens = CN.get(head, 1) if head else 1
        ones = CN.get(tail, 0) if tail else 0
        return 10 * tens + ones
    if len(tok) == 1:
        return CN.get(tok)
    return None


def cn_num(n: int) -> str:
    """12 → `十二`：基线要写「默认十二条」那种形状时用它，别把汉字抄死在格子里。

    抄死的汉字就是这一节要抓的那种东西：明天步数变 13，格子里那句还是「十二」，
    它钉住的就不再是判据。

    >>> cn_num(0), cn_num(9), cn_num(10), cn_num(12), cn_num(21)
    ('零', '九', '十', '十二', '二十一')
    >>> [cn_num(to_int(x)) for x in ("三", "十一", "二十")]
    ['三', '十一', '二十']
    """
    if n == 0:
        return "零"
    tens, ones = divmod(n, 10)
    out = ("" if tens == 1 else CN_TAIL[tens - 1]) + "十" if tens else ""
    return out + (CN_TAIL[ones - 1] if ones else "")


def doctest_flags(text: str) -> list[bool]:
    """逐行标「这一行属于 doctest 区」：`>>>`／`...` 开头，或紧跟其后的非空输出行。

    为什么按行而不是按段：函数 docstring 里示例和说明常常接在同一段里，按段整段豁免
    会把说明一起吞掉。

    >>> doctest_flags("说明一行\\n>>> f(1)\\n2\\n\\n结尾说明")
    [False, True, True, False, False]
    """
    out: list[bool] = []
    prev = False
    for line in text.split("\n"):
        s = line.lstrip()
        cur = s.startswith(">>>") or s.startswith("...") or (prev and s != "")
        out.append(cur)
        prev = cur
    return out


def paragraphs(text: str) -> list[tuple[str, str]]:
    """切成「把硬换行接回去的段」，并给每段配一条**等长**的逐字符标记串（`D` = 来自 doctest 行）。

    为什么要等长标记串：18:04 那遍按行切句，`（15 格、每格先写期望）` 与「搬进仓库」之间隔着一次
    手排折行，那个 15 就掉进了散文。接行会跨行，所以豁免得说清**每个字符**来自哪一行。

    >>> paragraphs("第一段\\n折了的后半\\n\\n>>> 示例 3 格")[0]
    ('第一段折了的后半', '........')
    >>> p, f = paragraphs("说明\\n>>> f()\\n25 格")[0]
    >>> (p, f.count("."), f.count("D"), len(p) == len(f))
    ('说明>>> f()25 格', 2, 11, True)
    """
    lines = [ln.strip() for ln in text.split("\n")]
    flags = doctest_flags(text)
    res: list[tuple[str, str]] = []
    body: list[str] = []
    mark: list[str] = []
    for t, fl in zip(lines, flags):
        if t == "":
            if body:
                res.append(("".join(body), "".join(mark)))
            body, mark = [], []
            continue
        body.append(t)
        mark.append(("D" if fl else ".") * len(t))
    if body:
        res.append(("".join(body), "".join(mark)))
    return res


def quote_spans(sent: str) -> list[tuple[int, int]]:
    """句里 「…」 的跨度 —— 落在里面的数字是在**引用那句话**，不是在报数。

    判据是「这个数自己有没有被括起来」，不是「这句里有没有 「」」。18:06 那遍用了后者，
    结果 629 处被吞掉：一个 `「」` 就够把整句里所有真引用一起豁免。

    >>> quote_spans("那句「四条默认」没动")
    [(2, 8)]
    >>> quote_spans("（默认十条）")
    []
    """
    return [(m.start(), m.end()) for m in QUOTE.finditer(sent)]


def owners_named(sent: str) -> list[str]:
    """这一句用反引号点了哪几把尺的主名（认别名）。

    >>> owners_named("`doc-cmds` 那条 ✓ 说的是 25 格")
    ['check_doc_cmds']
    >>> owners_named("`doc-test`、`num-test` 那两把")
    ['check_doc_cmds', 'doc_num']
    >>> owners_named("没有反引号，也没点名")
    []
    """
    named = []
    for mod, alts in ALIASES.items():
        if any(re.search(rf"`[^`]*\b{re.escape(a)}\b[^`]*`", sent) for a in alts):
            named.append(mod)
    return named


class Claim(NamedTuple):
    """一处引用：哪个件、哪一句、说了几、真值是什么、对不对。"""
    file: str
    kind: str
    value: str
    truth: str
    ok: bool
    ctx: str


def truth_of() -> tuple[dict[str, int], list[str]]:
    """现取真值：`ALIASES` 里每一位各自 `len(BASELINE)`、selfcheck 的步数。

    返回 `(值, 取不到的名字)`。取不到不当 0 —— 一个都不许糊，糊了就等于绿。

    `谁的都不是` 那一颗是给 `B2` 用的假值：它必须**不属于任何一把尺的格数**。
    写死一个加数不行 —— 19:31 那遍 `claims-test` 就是这么红的：`B2` 种的是 `{n格-unmarked_nums+7}`
    即 29，而同一分钟 `check_doc_cmds` 的基线从 25 加到 29，那个「谁的都不是」的数
    当场成了「有人的是」，负例变成正例，格子比的是一件没发生过的事。所以它现算：从 1000 往上
    找第一个不在集合里的（基线长到四位数之前，这一颗都撞不上）。

    >>> v, _ = truth_of()
    >>> v["谁的都不是"] >= 1000
    True
    >>> v["谁的都不是"] not in {x for k, x in v.items() if k.startswith("n格-")}
    True
    """
    vals: dict[str, int] = {}
    holes: list[str] = []
    for mod in ALIASES:
        try:
            m = __import__(mod)
            vals[f"n格-{mod}"] = len(m.BASELINE)        # type: ignore[attr-defined]
        except Exception as exc:                         # noqa: BLE001 —— 取不到要能点名
            holes.append(f"{mod}（BASELINE 读不到：{type(exc).__name__}）")
    sizes = {v for k, v in vals.items() if k.startswith("n格-")}
    vals["谁的都不是"] = next(n for n in range(1000, 10_000) if n not in sizes)
    try:
        sc = __import__("selfcheck")
        default = [x[0] for x in sc.steps(argparse.Namespace(
            port=8787, against="", epg=False, skip=[]))]
        all_with = [x[0] for x in sc.steps(argparse.Namespace(
            port=8787, against="/tmp/x", epg=True, skip=[]))]
        off = [x for x in default if x != "page"]
        vals["步-默认"], vals["步-离线"], vals["步-全挂"] = len(default), len(off), len(all_with)
    except Exception as exc:                             # noqa: BLE001
        holes.append(f"selfcheck（步数读不到：{type(exc).__name__}）")
    return vals, holes


def grid_verdict(val: int, owners: Sequence[str], vals: dict[str, int],
                 grid: frozenset[int]) -> tuple[str, bool]:
    """甲（`N 格`）那一句的 `(给人看的真值, 对不对)`。

    句里用反引号点了主人，就必须等于**那一位**的格数；没点名只要求它落在真值集合里。
    点了主人而那位读不到时宁可判红 —— 「读不到」不是「都对」（那一屏上面还印着真值取不到）。

    >>> V = {"n格-doc_num": 26, "n格-stray_names": 15}
    >>> G = frozenset(V.values())
    >>> grid_verdict(26, ["doc_num"], V, G)
    ('doc_num=26', True)
    >>> grid_verdict(15, ["doc_num"], V, G)
    ('doc_num=26', False)
    >>> grid_verdict(15, [], V, G)
    ('没点名，只要求属于 15/26', True)
    >>> grid_verdict(7, [], V, G)
    ('没点名，只要求属于 15/26', False)
    >>> grid_verdict(26, ["check_doc_cmds"], V, G)
    ('check_doc_cmds=读不到', False)
    """
    if owners:
        parts = [f"{n}={vals[f'n格-{n}']}" if f"n格-{n}" in vals else f"{n}=读不到"
                 for n in owners]
        got = [vals[f"n格-{n}"] for n in owners if f"n格-{n}" in vals]
        return "、".join(parts), val in got
    joined = "/".join(str(v) for v in sorted(grid))
    return f"没点名，只要求属于 {joined}", val in grid


def scan_source(src: str, name: str, vals: dict[str, int]) -> tuple[list[Claim], Counter]:
    """读一个 .py 的 docstring（模块 + 函数），返回 `(引用, 跳过计数)`。"""
    out: list[Claim] = []
    skip: Counter = Counter()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        skip["读不进"] += 1
        out.append(Claim(name, "读不进", "—", f"第 {exc.lineno} 行语法不通", False, ""))
        return out, skip
    docs: list[tuple[str, str]] = []
    top = ast.get_docstring(tree)
    if top:
        docs.append(("模块", top))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node)
            if d:
                docs.append((node.name, d))
    grid = frozenset(v for k, v in vals.items() if k.startswith("n格-"))
    for layer, text in docs:
        for para, flags in paragraphs(text):
            idx = 0
            for piece in (p.strip() for p in SPLIT_SENT.split(para)):
                if not piece:
                    continue
                start = para.find(piece, idx)
                if start < 0:                       # 定位失败不许静默：数进跳过里
                    skip["定位失败"] += 1
                    continue
                idx = start + len(piece)
                for rx, kind in ((GRID, "格"), (SC_DEFAULT, "默认条数"),
                                 (SC_OFFLINE, "离线条数")):
                    for m in rx.finditer(piece):
                        rel = m.start()               # 相对 piece
                        pos = start + rel             # 相对整段（flags 是逐段对齐的）
                        if pos < len(flags) and flags[pos] == "D":
                            skip["doctest 区"] += 1
                            continue
                        if any(a <= rel < b for a, b in quote_spans(piece)):
                            skip["「」内复述"] += 1
                            continue
                        val = to_int(m.group(1))
                        if val is None:
                            skip["数字认不出"] += 1
                            continue
                        ctx = piece[max(0, m.start() - 22):m.end() + 20].strip()
                        if kind == "格":
                            truth, good = grid_verdict(val, owners_named(piece), vals, grid)
                        else:
                            key = "步-默认" if kind == "默认条数" else "步-离线"
                            truth = str(vals.get(key, "真值取不到"))
                            good = key in vals and val == vals[key]
                        out.append(Claim(f"{name}:{layer}", kind, str(val), truth, good, ctx))
    return out, skip


def pick_files(given: Sequence[str]) -> tuple[list[Path], int]:
    """点名的件 → (要扫的清单, 因文件名像同步盘冲突副本而跳过的份数)。

    副本**不扫**而不是扫了报错：它是一份自洽的旧代码，扫它会把「同步盘掉了一件」说成
    「代码里的话写错了」，那是 2.59 傍晚被推翻过的那条路。这里跳过、但把份数印在结论行里，
    点名它由 `stray_names` 负责。

    >>> pick_files(["a.py", "b 2.py", "c.py"])
    ([PosixPath('a.py'), PosixPath('c.py')], 1)
    """
    paths = [Path(g) for g in given]
    copies = [p for p in paths if COPYISH.search(p.name)]
    return [p for p in paths if not COPYISH.search(p.name)], len(copies)


def targets(root: Path) -> list[Path]:
    """仓库自己那一批被量的件：`scripts/*.py` 与 `src/cli.py`。

    >>> [p.name for p in targets(Path("/nonexistent-x"))]
    ['cli.py']
    """
    return sorted((root / "scripts").glob("*.py")) + [root / "src" / "cli.py"]


def read_one(path: Path) -> tuple[str | None, str]:
    """读一份件 → `(正文, 读不进来时给人看的那句)`。成功时第二项是空串。"""
    if path.is_dir():
        return None, "那是个目录，不是 .py"
    if not path.is_file():
        return None, "文件不在"
    try:
        return path.read_text(encoding="utf-8"), ""
    except OSError as exc:
        return None, f"读不进来：{type(exc).__name__}"
    except UnicodeDecodeError:
        return None, "不是 UTF-8，读不进来"


def report(claims: Sequence[Claim], skip: Counter, unread: Sequence[tuple[str, str]],
           scanned: int, copies: int, holes: Sequence[str], verbose: bool) -> int:
    """印每一处引用 + 结论行，返回退码。"""
    for c in claims:
        print(f"  {'✓' if c.ok else '✗'} {c.file} 说 {c.kind} {c.value}、真值是 {c.truth}"
              + (f" ｜…{c.ctx}…" if c.ctx else ""))
    if verbose:
        for k, v in sorted(skip.items()):
            print(f"  · 跳过 {k}：{v} 处（不扫，也不核）")
    n = sum(1 for c in claims if c.kind != "读不进")
    bad = [c for c in claims if not c.ok and c.kind != "读不进"]
    tail = ("（一处没跳过）" if not skip else
            "（跳过 " + "、".join(f"{k} {v} 处" for k, v in sorted(skip.items())) + "）")
    print(f"\n扫了被量的 {scanned} 个 .py 里的代码散文：查到 {n} 处报数的话，"
          f"{len(bad)} 处对不上{tail}")
    if copies:
        print(f"  另有 {copies} 份文件名像同步盘冲突副本的 .py 没扫 —— 点名它们是 "
              "`stray_names` 的活，不在这里")
    if holes:
        print("真值取不到，这一屏的「对不上」因此不可信：" + "、".join(holes))
        return 2
    if unread:
        for p, why in unread:
            print(f"  · 没读进来：{p} —— {why}")
    if not n:
        print("一处引用都没查到：被量的那些件里没有「N 格」与「默认 N 条」这两种写法。"
              "这不算过 —— 要么判据不咬了，要么量的不是那些件")
        return 2
    return 1 if bad or unread else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="code_claims.py", description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT), help="量哪个仓库（默认本仓库）")
    ap.add_argument("--py", default=None, help="只量点名的这几份 .py（逗号分隔）")
    ap.add_argument("--verbose", action="store_true", help="把跳过的分档也摊开")
    ap.add_argument("--self-test", action="store_true", help="种已知形状的假件，逐格对期望")
    ap.add_argument("--doctest", action="store_true", help="只跑本文件的用例")
    a = ap.parse_args(argv)
    door_rc = arg_door_exit(a, argv)   # 2.80：那一判要读 argv —— 薄门旁边跟了字也点名
    if door_rc is not None:
        return door_rc
    answered = arg_door_answered(a)
    if answered == DOCTEST_FLAG:
        return run_own(sys.modules[__name__])
    if answered == SELF_TEST_FLAG:
        return self_test()
    vals, holes = truth_of()
    root = Path(a.root)
    if a.py is not None:
        all_given = [p.strip() for p in a.py.split(",") if p.strip()]
        if not all_given:
            print("--py 里一个名字都没给（空值或全是空白）：不许退回去量仓库自己")
            return 2
    else:
        all_given = [str(p) for p in targets(root)]
    files, copies = pick_files(all_given)
    if not files:
        print("一个 .py 都没读到：点名的路径全不在或全像冲突副本。这不算过")
        return 2
    claims: list[Claim] = []
    skip: Counter = Counter()
    unread: list[tuple[str, str]] = []
    for f in files:
        src, why = read_one(f)
        if src is None:
            skip["没读进来"] += 1
            unread.append((f.name, why))
            continue
        got, sk = scan_source(src, f.name, vals)
        claims += got
        skip.update(sk)
    return report(claims, skip, unread, len(files) - len(unread), copies, holes, a.verbose)


# ———— 基线：格子里种的是一份**假件**，被量的是它的 docstring ————

L_GRID = '"""`check_doc_cmds` 那 {n格-check_doc_cmds} 格已知好坏的文档。"""'
L_ORPHAN = '"""种了 {n格-unmarked_nums} 格已知形状的文档，跑之前先写期望。"""'
L_DEFAULT = '"""一条命令跑完全部对账：默认{步-默认汉字}条。"""'
L_OFFLINE = '"""默认{步-默认汉字}条 —— {步-离线汉字}条离线尺，`page` 要问一眼进程。"""'


BASELINE: tuple[Cell, ...] = (
    # ———— G 组：这些情形**不许**报错。它们红了就是尺在瞎咬 ————
    Cell("G1_点名格数对", "甲的正主：句里点了主人，数等于那一位的格数",
         0, files=((PY, L_GRID),), argv=("--py", f"{SANDBOX}/{PY}"),
         has=(f"✓ {PY}:模块 说 格 {{n格-check_doc_cmds}}、真值是 check_doc_cmds="
              "{n格-check_doc_cmds}", "0 处对不上")),
    Cell("G2_没主人验集合", "没点名主人：只要那个数属于真值集合就算对",
         0, files=((PY, L_ORPHAN),), argv=("--py", f"{SANDBOX}/{PY}"),
         has=("说 格 {n格-unmarked_nums}、真值是 没点名", "0 处对不上")),
    Cell("G3_默认条数汉字", "乙的正主：`默认十条` 那种汉字写法要认，且要等于现算的步数",
         0, files=((PY, L_DEFAULT),), argv=("--py", f"{SANDBOX}/{PY}"),
         has=("说 默认条数 {步-默认}、真值是 {步-默认}",)),
    Cell("G4_同一句两个数", "一句里「默认几条」与「几条离线尺」各归各的真值",
         0, files=((PY, L_OFFLINE),), argv=("--py", f"{SANDBOX}/{PY}"),
         has=("说 默认条数 {步-默认}", "说 离线条数 {步-离线}", "0 处对不上")),
    Cell("G5_硬换行不断句", "手排折行把「26」与「格」切两行 —— 接回去仍要查到",
         0, files=((PY, '"""数尺那\n{n格-doc_num}\n格继续折的一行"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"),
         has=("说 格 {n格-doc_num}、真值是 没点名",)),
    Cell("G6_doctest不读", "示例里的数是**读数**：核它就把量具的说明书当判据",
         0, files=((PY, '"""真那句 {n格-stray_names} 格。\n\n>>> f()\n999 格"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"),
         has=("查到 1 处", "跳过 doctest 区 1 处")),
    Cell("G7_引号内复述不查", "「四条默认」那种历史措辞必须豁免，否则 2.56 三条追记全红",
         0, files=((PY, '"""那句「{n格-stray_names} 格」是当时的话，真那句 {n格-stray_names} 格。"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"),
         has=("查到 1 处", "跳过 「」内复述 1 处")),
    Cell("G8_冠词不扫", "「这一格／每格／一格都没跑起来」不是数：全篇只有它们时退 2，不是退 0",
         2, files=((PY, '"""跑任何一格之前先问这一条：每一格都可能是那一格。"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"),
         has=("一处引用都没查到", "这不算过")),
    Cell("G9_格式不是格", "「按 3 格式」「4 格局部写法」里那些数不许被当成格数",
         2, files=((PY, '"""输出按 3 格式排，别学 4 格局部写法。"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"), has=("一处引用都没查到",)),
    Cell("G10_引号不在句首", "G7 的那句挪到第二段第二句 —— 18:25 那遍的偏移就在这儿咬人",
         0, files=((PY, '"""先说别的。那句「{n格-stray_names} 格」是当时的话，'
                        '真那句 {n格-stray_names} 格。"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"),
         has=("✓ 假件.py:模块 说 格 {n格-stray_names}", "查到 1 处", "跳过 「」内复述 1 处")),
    Cell("G11_自述用例", "`--doctest` 那一支要报数：2.68 之前它跑掉本件那些用例、印 0 字节、退 0",
         0, argv=("--doctest",),
         has=("合计", "个用例", "0 个失败", "code_claims.py"),
         lacks=("一条用例都没收到", "扫了被量的")),
    # ———— B 组：这些情形**必须**报错。它们绿了就是尺不咬 ————
    Cell("B1_点名点错人", "句里点 `doc_num` 却写未挂尺的格数 —— 这一处是这把尺存在的理由",
         1, files=((PY, '"""`doc_num` 那 {n格-unmarked_nums} 格"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"),
         has=("✗ 假件.py:模块 说 格 {n格-unmarked_nums}、真值是 doc_num={n格-doc_num}",
              "1 处对不上")),
    Cell("B2_数不在真值集", "一个谁的格数都不是的数：红，且要说出真值集合（那颗数现算，见 `truth_of`）",
         1, files=((PY, '"""种了 {谁的都不是} 格"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"), has=("1 处对不上", "只要求属于")),
    Cell("B3_默认条数少一", "明天加一步、今天那句还是旧数 —— 2.55~2.57 那四轮就是这个形状",
         1, files=((PY, '"""默认 {步-默认-1} 条。"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"), has=("✗ 假件.py:模块 说 默认条数 {步-默认-1}",)),
    Cell("B4_离线条数写死", "把 `{步-离线}` 换成抄死的数：现算的与写的对不上就红",
         1, files=((PY, '"""{步-离线-1} 条离线尺"""'),),
         argv=("--py", f"{SANDBOX}/{PY}"),
         has=("说 离线条数 {步-离线-1}、真值是 {步-离线}",)),
    Cell("B5_文件不在", "点名的件读不到要能点名，且不许裸崩",
         2, argv=("--py", f"{SANDBOX}/不在.py"),
         has=("没读进来：不在.py —— 文件不在", "一处引用都没查到"), lacks=("Traceback",)),
    Cell("B6_给的是目录", "同一族另一种坏法：也说人话",
         2, argv=("--py", str(SANDBOX)), has=("那是个目录",), lacks=("Traceback",)),
    Cell("B7_量到一半缺一块", "一份能读、一份不在：那才是 1 —— 量到了，但覆盖缺一块",
         1, files=((PY, L_ORPHAN),), argv=("--py", f"{SANDBOX}/{PY},{SANDBOX}/不在.py"),
         has=("查到 1 处", "没读进来：不在.py", "0 处对不上")),
    Cell("B8_假件没有docstring", "读到件了、可它一句话都没说：那是 2 不是 0",
         2, files=((PY, "def f():\n    return 1\n"),), argv=("--py", f"{SANDBOX}/{PY}"),
         has=("查到 0 处", "一处引用都没查到")),
    Cell("B9_语法不通", "半截代码不许冒充「这个件没话可说」",
         2, files=((PY, '"""说了 {n格-stray_names} 格"""\ndef f(:\n'),),
         argv=("--py", f"{SANDBOX}/{PY}"), has=("第 2 行语法不通", "一处引用都没查到"),
         lacks=("Traceback",)),
    Cell("B10_--py给空串", "参数取坏值时不许退回去量仓库自己",
         2, argv=("--py", "  "), has=("--py 里一个名字都没给",)),
    Cell("B11_副本不扫但要点名", "文件名像同步盘副本：跳过它，但份数必须印在结论行里",
         0, files=((PY, L_ORPHAN), ("假件 2.py", L_ORPHAN)),
         argv=("--py", f"{SANDBOX}/{PY},{SANDBOX}/假件 2.py"),
         has=("查到 1 处", "另有 1 份文件名像同步盘冲突副本的 .py 没扫")),
    Cell("B12_非UTF8假件", "二进制件不许把整屏带走",
         2, bins=("坏件.py",), argv=("--py", f"{SANDBOX}/坏件.py"),
         has=("没读进来：坏件.py —— 不是 UTF-8",), lacks=("Traceback",)),
)


CN_SPEC = re.compile(r"\{([^{}]*汉字)\}")     # `{步-默认汉字}`：值表里存整数，写进格子时换成汉字


def expand_cn(cell: Cell, vals: dict[str, int]) -> Cell:
    """把这一格模板里的 `{…汉字}` 换成 `cn_num(整数)`，其余占位符原样留着。

    为什么不把汉字串塞进值表：`{键}` 的替换只有 `doc_num.resolve` 那一份，而它会算
    `values[key] + 偏移` —— 存字符串就在 `--self-test` 的靶子闸上裸崩（18:28:55 量到的：
    `TypeError: can only concatenate str (not "int") to str`）。抄第二份 `fill` 是 2.58
    刚收掉的那种毛病，所以换成**先展开成字面量**：整数仍然只有一份真值，格子拿到的是它的汉字写法。

    >>> e = Cell("t", "说明", 0, files=((PY, "默认{步-默认汉字}条"),),
    ...          has=("说 默认条数 {步-默认}、真值是 {步-默认}",))
    >>> c = expand_cn(e, {"步-默认": 10})
    >>> c.files[0][1], c.has[0]
    ('默认十条', '说 默认条数 {步-默认}、真值是 {步-默认}')
    >>> from doc_num import fill
    >>> fill(c.has[0], {"步-默认": 10})
    '说 默认条数 10、真值是 10'
    >>> expand_cn(Cell("t", "u", 0), {"步-默认": 10}).argv
    ()
    """
    def sub(t: str) -> str:
        return CN_SPEC.sub(lambda m: cn_num(vals[m.group(1)[:-2]]), t)

    return cell._replace(
        who=sub(cell.who), what=sub(cell.what),
        files=tuple((n, sub(c)) for n, c in cell.files),
        bins=tuple(sub(b) for b in cell.bins),
        copies=tuple(sub(c) for c in cell.copies),
        argv=tuple(sub(a) for a in cell.argv),
        has=tuple(sub(s) for s in cell.has), lacks=tuple(sub(s) for s in cell.lacks))


def run_cell(cell: Cell, base: Path, values: dict[str, int]) -> tuple[str, str, str]:
    """跑一格：返回 `(判决, 为什么, 那一遍的原文)`。判决是 `ok`／`bad`／`崩`。"""
    d = build_cell(cell, base, values)
    argv = [fill(a, values) for a in (cell.argv or ["--py", f"{d}/{PY}"])]
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
    """`--self-test`：往临时目录里种 23 格已知好坏的假件，逐格对**跑之前**写死的期望。

    结论行带着「扫了」那个词（`scripts/selfcheck.py` 的 `conclusion()` 靠它挑句子），
    过的一格一行流水、不符期望的留在最后 —— 与 §2.56~2.59 那四档同形。

    退码：0 = 每格符合；1 = 有格子不符（逐格点名）；2 = 一格都没跑起来，或靶子先不对
    （名字带顿号、格子字面量写歪、`{键}` 点不到真值、沙盒占位符写成花括号）。
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
    vals, holes = truth_of()
    if holes:
        print("真值取不到，基线没有可比的对象：" + "、".join(holes))
        return 2
    values = vals                                   # 值表只存整数：汉字写法在 `expand_cn` 里展开
    cells = [expand_cn(c, values) for c in BASELINE]
    holes2 = unresolvable(cells, values)
    if holes2:
        print("基线要点名却点不到的占位符 —— 改的是基线，不是判据：" + "、".join(holes2))
        return 2
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    with tempfile.TemporaryDirectory(prefix="claims-selftest-") as td:
        base = Path(td)
        for cell in cells:
            verdict, why, text = run_cell(cell, base, values)
            ran += 1
            if verdict != "ok":
                bad += 1
                fails.append((cell, f"{'裸崩 ' if verdict == '崩' else ''}{why}", text))
                continue
            print(f"  ✓ {cell.who:<18} {cell.what}")
        if fails:
            print(f"\n—— 以下 {len(fails)} 格不符期望（每格把自己那一遍的原文摊出来）——")
            for cell, why, text in fails:
                print(f"  ✗ {cell.who:<18} {cell.what}\n      {why}")
                for line in text.strip().splitlines():
                    print(f"      | {line}")
    print(f"\n扫了基线 {len(BASELINE)} 格：{bad} 格不符期望"
          + (" —— 那把尺分得清它对什么" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    # 2.68 之前这里还有一条 `if "--doctest" in sys.argv:`，绕开 argparse 自己拦一遍 ——
    # 于是同一件事有两个入口，而那两个入口量的不是同一个件：这里那个用默认的 `__main__`，
    # `main()` 里那个用 `sys.modules[__name__]`。留一个（`main()` 里那个），少一份漂移的可能。
    raise SystemExit(main(sys.argv[1:]))
