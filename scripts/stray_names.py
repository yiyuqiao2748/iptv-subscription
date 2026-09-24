#!/usr/bin/env python3
"""问一件仓库里所有尺子都不问的事：**这个文件名本身像不像一次事故**。

为什么要有这一把（2.54 收尾时量到的）：那一轮里同步盘往工作区塞了四颗冲突副本 ——
`scripts/check_doc_cmds 2.py` 与 `.git/` 里三份 `index 2/3/4`。前一颗是**两道现有闸在同一分钟各撞一次**
才被看见的（`run_doctests` 拒绝数用例、`check_doc_cmds` 说「这支脚本文档里没提过」），
后三颗**至今没有任何一把尺看得见**：五把尺读的是 `src/**.py`、文档、`data/output/`、四张表、
正在跑的页面，没有一个读 `.git/` 里的目录项。而冲突副本真正咬人的方式恰恰是名字：
它把旧内容原样留在旁边一份，谁的 glob 宽一点，谁就把两份都算进分母。

这一把只看名字，**不看内容、不改名字、不删东西**（它是一台只读的尺）。它分两档：

* **拦（退 1）**：三种形状 —— 名字以「 数字」结尾（同步盘冲突副本的样子）、
  首尾有空白、名字里带全角空格/制表/换行。前一种会悄悄改分母，后两种会让「照抄这行命令」这件事
  在终端里断掉，而且肉眼看不出来。
* **只提醒（不改退码）**：名字里有空格，但不是「 数字」结尾（`湖南 卫视.m3u` 那种是合法名字）。

三个设计上的取舍，都写在这里而不是藏在代码里：

1. **`.git/` 要扫。** 冲突副本最爱落在那儿（`index`、`FETCH_HEAD`、`*..lock`），而那里恰恰是
   现有全部尺子的盲区。代价是这一把的输出会讲到 git 的内部文件 —— 所以那颗如果**在 `git ls-files`
   的名单里**（已经提交进去了）会额外标一句，因为那已经不是「刚才掉进来一颗」了。
2. **`.venv/` 也扫，但只提醒。** 依赖自带的名字里可能有空格，那不是这个仓库的事故；
   而 `.venv/` 里真掉进一颗冲突副本仍然值得说，所以那一档不关掉、只降级。
3. **一颗都没扫到 ≠ 这把尺没坏。** 名单为空而**总名字数也为 0** 是「指错目录了或者那是个空目录」，
   那种退 2（2.32 那一族：什么都没量到不算过）。这一条是**被自己的量具量出来的**：
   第一版只在 `--root` 不是目录时退 2，空目录走到「0 个拦得住」那句话上、退 0 ——
   结论行明明写着「这不算过」，退码却是绿的。`C2` 那一格钉的就是它。

退码：**0** 干净；**1** 有拦得住的名字；**2** 一个名字都没扫到（`--root` 不是目录，或者那是个空目录）。
`--self-test` 那一档另有退码口径，见下面「回归基线」那段。

用法：

    .venv/bin/python scripts/stray_names.py                 # 扫本仓库（含 .git/）
    .venv/bin/python scripts/stray_names.py --root /tmp/x    # 扫另一棵树（量具、沙盒用）
    .venv/bin/python scripts/stray_names.py --all            # 连「只提醒」那一档也逐条列出来
    .venv/bin/python scripts/stray_names.py --by-dir         # 那个总数按顶层目录拆开
    .venv/bin/python scripts/stray_names.py --self-test      # 往临时树里种名字，问这把尺还咬得动吗

## 回归基线（`--self-test`）：这把尺今天 0 颗，可「0 颗」有两种意思

2.55 收尾时的状态是：本仓库**扫了 782 个名字，0 个拦得住**。那句 ✓ 有两种读法 ——
仓库真的干净，或者这把尺瞎了。它退 2 那一档只挡住了「一个名字都没扫到」，挡不住
「扫了 782 个但一条判据都不认」。所以这一节把 2.55 那份沙盒（15 格、每格先写期望）
搬进仓库，成为每轮自检顺手跑的一遍：**它不是又一把量仓库的尺，它是量那把尺的**。

规则很简单：每格声明「种什么名字、该退几、结论里的名字数、必须说哪几句、不许说哪几句」，
`--self-test` 在临时目录里种出来（`tempfile.TemporaryDirectory`，跑完自己回收，
仓库与 `data/output/` 一个字节都不碰），跑一遍真的 `main()`，再逐格比对。四种不符分开报，
因为它们**修法不一样**：退码错（判据）、少了那句话（处置提示）、多了那句话（误伤）、
名字数错（种失败了或者 `walk` 瞎了）。

四条口径写在这里：

1. **期望先于运行。** 下面那张表的 `rc` / `has` / `lacks` / `scanned` 是 2.55 那 15 格的
   实测结果抄过来的（那一轮每格都是跑之前先写期望），所以本节的「第一遍就红」才是量具的错，
   不是期望被事后改过。
2. **两格的 `scanned` 留空。** 它们要一棵真的 git 仓库（`.git/index 2` 与「已经提交进去了」
   那两格），而 `git init` 拉出来的 `.git/` 里有 30 来个名字、随 git 版本变 ——
   在那两格上钉死一个数，等于让这把尺去量 git 的版本号。
3. **一格里同时钉正反两半。** `R9` 那格种两颗（一颗进了 `git ls-files` 名单、一颗没进），
   要求那句「已经提交进去了」**恰好出现一次** —— 只要求「出现」的话，把交叉核查改成
   「每颗都说」也能蒙过这一格。
4. **临时目录名从输出里抹掉再印。** 2.55 踩的第 7 条：结论行里带着绝对路径，于是
   「两遍逐字节相同」必须先 `sed` 归一，而那条归一规则没有东西钉着。这里改成
   由代码抹（`hide_tmp`），并且给它钉了用例 —— 规则从此是**被测对象的一部分**，不是命令行的手艺。

`--self-test` 的退码：**0** 每格都符合期望；**1** 至少一格不符；**2** 一格都没跑起来
（`BASELINE` 被清空、临时目录建不出来、或者全被跳过 —— 还是 2.32 那一族）。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:      # 为了 import `baseline_guard`（2.58 共用的那道闸）
    sys.path.insert(0, str(ROOT / "scripts"))
from baseline_guard import guard as guard_names  # noqa: E402
from run_doctests import add_doctest_flag, run_own   # noqa: E402  `--doctest` 那一旗的口径只有一份

# 「 数字」结尾：`计划书 2.md` 的 stem 是 `计划书 2`，`index 3` 的 stem 就是它自己，两种都要认。
CONFLICT = re.compile(r" \d+$")
# 肉眼看不出来、但对 shell 与补全很不友好的空白
ODD_SPACE = re.compile(r"[\u3000\t\r\n\f\v]")
# 下载/编辑器留下的临时件：它们出现在仓库里几乎总是忘删，而且名字一定带空格或波浪号
JUNK_PREFIX = "~$"

RED = "red"
NOTE = "note"


def classify(name: str) -> tuple[str | None, str]:
    """这个**文件/目录名**属于哪一档：`(档, 给人看的那句)`，档是 `red` / `note` / None。

    只看名字，所以它可以被逐条钉住（下面每一格都是一颗真掉进过本仓库或能掉进来的名字）。

    >>> classify("check_doc_cmds 2.py")
    ('red', '名字以「 数字」结尾：这是同步盘的冲突副本形状')
    >>> classify("index 3")
    ('red', '名字以「 数字」结尾：这是同步盘的冲突副本形状')
    >>> classify("计划书 10.md")            # 两位数也一样
    ('red', '名字以「 数字」结尾：这是同步盘的冲突副本形状')
    >>> classify("湖南 卫视.m3u")           # 中间有空格是合法名字，只提醒
    ('note', '名字里有空格（不是冲突副本那种形状），照抄进终端要加引号')
    >>> classify("启动电视订阅服务.command")
    (None, '')
    >>> classify("a\u3000b.py")             # 全角空格
    ('red', '名字里带全角空格或制表/换行：看不出来，补全和脚本都会跟它过不去')
    >>> classify("a.py ")                   # 尾巴一个空格：`ls` 看不出来
    ('red', '名字首尾有空白：它在终端里会被吃掉一半')
    >>> classify("~$计划书.docx")           # Office 的锁文件
    ('red', '编辑器留下的临时件（名字以 `~$` 开头）：它通常不该进仓库')
    >>> classify("")                        # 空名字不是文件，是调用方传错了
    (None, '')
    """
    if not name:
        return None, ""
    stem, ext = os.path.splitext(name)
    if CONFLICT.search(stem) or CONFLICT.search(name):
        return RED, "名字以「 数字」结尾：这是同步盘的冲突副本形状"
    if ODD_SPACE.search(name):
        return RED, "名字里带全角空格或制表/换行：看不出来，补全和脚本都会跟它过不去"
    if name != name.strip():
        return RED, "名字首尾有空白：它在终端里会被吃掉一半"
    if name.startswith(JUNK_PREFIX):
        return RED, "编辑器留下的临时件（名字以 `~$` 开头）：它通常不该进仓库"
    if " " in name:
        return NOTE, "名字里有空格（不是冲突副本那种形状），照抄进终端要加引号"
    return None, ""


def find_bad(root: Path) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], int,
                                 dict[str, int]]:
    """扫一棵树：`(拦得住的[(相对路径, 档说明, 在不在 git 名单里)], 只提醒的, 扫过的名字总数, 按顶层目录的数)`。

    相对路径按 `root` 算；`git ls-files` 只在 `root` 是个 git 仓库时问一次，问不动就当不在。
    符号链接指向的目录**不进去**（`.venv/bin/python` 那种链到别处的东西，扫它等于扫别人的仓库），
    但**链子自己的名字照样判** —— 那个名字是这个仓库里的目录项，只是它背后那棵树不是。

    最后那个字典（`--by-dir`）是为「总数会自己动」准备的：2.55 记的是 782，本节量到 792，
    差的 10 颗**必须能一句话拆开**，不然下一次数再跳，人只能重写一遍临时脚本去数
    （本节真的写了，见 2.56 踩的第 1 条）。根目录里那些名字的顶层记作 `(根)`。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as td:
    ...     t = Path(td) / "tree"
    ...     far = Path(td) / "far"
    ...     _ = t.mkdir(); _ = far.mkdir()
    ...     _ = (far / "别人的仓库 2.py").write_text("x", encoding="utf-8")
    ...     _ = (t / "good.py").write_text("x", encoding="utf-8")
    ...     _ = (t / "cache 2").symlink_to(far, target_is_directory=True)
    ...     bad, note, n, tops = find_bad(t)
    ...     ([b[0] for b in bad], n, tops)
    (['cache 2'], 2, {'(根)': 2})
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as td:
    ...     t = Path(td)
    ...     _ = (t / "计划书 2.md").write_text("x", encoding="utf-8")
    ...     _ = (t / "湖南 卫视.m3u").write_text("x", encoding="utf-8")
    ...     _ = (t / "good.py").write_text("x", encoding="utf-8")
    ...     bad, note, n, tops = find_bad(t)
    ...     ([b[0] for b in bad], [x[0] for x in note], n, tops)
    (['计划书 2.md'], ['湖南 卫视.m3u'], 3, {'(根)': 3})
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as td:
    ...     t = Path(td)
    ...     _ = (t / "sub").mkdir(); _ = (t / "sub" / "a.py").write_text("x", encoding="utf-8")
    ...     _ = (t / "b.py").write_text("x", encoding="utf-8")
    ...     find_bad(t)[2], find_bad(t)[3]
    (3, {'(根)': 2, 'sub': 1})
    >>> find_bad(Path("/nonexistent-path-for-doctests"))
    ([], [], 0, {})
    """
    tracked = set()
    try:
        r = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                           text=True, timeout=30)
        if r.returncode == 0:
            tracked = {p for p in r.stdout.split("\0") if p}
    except Exception:                                  # 不是仓库、没装 git、超时：都按「问不出来」
        pass
    bad: list[tuple[str, str, str]] = []
    note: list[tuple[str, str]] = []
    tops: dict[str, int] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # 链到别处的目录：名字留着判（它是本仓库的一个目录项），背后那棵不进（见 docstring）
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        dirnames[:] = [d for d in dirnames if d not in links]
        rel_dir = os.path.relpath(dirpath, root)
        top = "(根)" if rel_dir == "." else rel_dir.split(os.sep)[0]
        for name in list(dirnames) + links + filenames:
            total += 1
            tops[top] = tops.get(top, 0) + 1
            rel = name if rel_dir == "." else os.path.join(rel_dir, name)
            tier, why = classify(name)
            if tier == RED:
                in_git = "在 `git ls-files` 的名单里（已经提交进去了）" if rel in tracked else ""
                bad.append((rel.replace(os.sep, "/"), why, in_git))
            elif tier == NOTE:
                note.append((rel.replace(os.sep, "/"), why))
    return sorted(bad), sorted(note), total, tops


def by_dir(tops: dict[str, int]) -> str:
    """把「按顶层目录」那份分解排成一行（多的在前，同样多的按名字排）。

    >>> by_dir({".git": 601, "(根)": 13, "src": 44})
    '`.git` 601、`src` 44、`(根)` 13'
    >>> by_dir({})
    '（一个名字都没有）'
    >>> by_dir({"a": 2, "b": 2, "c": 1})
    '`a` 2、`b` 2、`c` 1'
    """
    if not tops:
        return "（一个名字都没有）"
    items = sorted(tops.items(), key=lambda kv: (-kv[1], kv[0]))
    return "、".join(f"`{k}` {v}" for k, v in items)



HOW = (
    "怎么处理：**别顺手删**。它可能是同步盘从另一台机器捞回来的改动 —— 先看它比现在这份多了什么\n"
    "            （`diff` 一下），确认没用了再搬出仓库（搬进 `/tmp`，不是搬进隔壁目录：\n"
    "            隔壁目录它一样会被 glob 到，也只有 `run_doctests` 那一把、且只在它是 `.py` 时看得见）。"
)


def summary(n_total: int, bad: list, note: list, root: Path) -> str:
    """那一行结论（`selfcheck` 靠「扫了」这个词认它）。

    >>> summary(780, [], [], Path("/tmp/x"))
    '扫了 780 个名字（含 `.git/` 与 `.venv/`）：0 个拦得住、0 个只是提醒；该查的都查了'
    >>> summary(10, [("a 2.py", "…", "")], [("b c.py", "…")], Path("/tmp/x"))
    '扫了 10 个名字（含 `.git/` 与 `.venv/`）：1 个拦得住、1 个只是提醒 —— 上面逐条点名了'
    >>> summary(0, [], [], Path("/tmp/x"))
    '一个名字都没扫到：/tmp/x 不是个目录，或者它是空的。这不算过'
    """
    if not n_total:
        return f"一个名字都没扫到：{root} 不是个目录，或者它是空的。这不算过"
    tail = "；该查的都查了" if not bad else " —— 上面逐条点名了"
    return (f"扫了 {n_total} 个名字（含 `.git/` 与 `.venv/`）："
            f"{len(bad)} 个拦得住、{len(note)} 个只是提醒{tail}")


# ---------------------------------------------------------------------------
# 回归基线（`--self-test`）：口径与四条取舍都写在模块 docstring 里
# ---------------------------------------------------------------------------

OUT = "OUT"          # 种在被扫那棵树**之外**的链接目标：`os.walk` 不该进去


class Cell(NamedTuple):
    """一格期望：种什么、该退几、必须说哪几句、不许说哪几句。"""

    who: str                                  # 格子名（沿用 2.55 那张表的编号）
    what: str                                 # 这一格在钉什么
    plant: tuple[str, ...] = ()               # 要种的名字（见 `split_item`）
    sub: str = ""                             # 只扫树里的这个子路径（"" = 整棵树）
    repo: bool = False                         # 先 `git init`（要一颗真的 `.git/`）
    track: str = ""                            # 并且把这一颗 `git add` 进名单
    args: tuple[str, ...] = ()                # 额外的命令行参数
    rc: int = 0
    scanned: int | None = None                # 结论里那个「扫了 N 个名字」；None = 这一格不钉数
    has: tuple[str, ...] = ()                 # 必须出现（至少一次）
    once: tuple[str, ...] = ()                # 必须**恰好**出现一次
    lacks: tuple[str, ...] = ()               # 必须不出现


BASELINE: tuple[Cell, ...] = (
    Cell("R1_.py 冲突副本", "2.54 真撞过的那一颗：同目录两份都被 glob 到",
         ("scripts/check_doc_cmds.py", "scripts/check_doc_cmds 2.py", "README.md"),
         rc=1, scanned=4,
         has=("名字以「 数字」结尾", "<tmp>/tree/scripts/check_doc_cmds 2.py", "别顺手删"),
         lacks=("它在 `.git/` 里", "它在 `.venv/` 里", "已经提交进去了")),
    Cell("R2_.git 里没扩展名那颗", "现有五把尺的盲区：那里没人读",
         ("README.md", ".git/index 2"), repo=True,
         rc=1, has=("它在 `.git/` 里", "一把都不读这里", "名字以「 数字」结尾"),
         lacks=("已经提交进去了",)),
    Cell("R3_全角空格", "肉眼看不出来的空白", ("a\u3000b.py", "good.py"),
         rc=1, scanned=2, has=("看不出来，补全和脚本",),
         lacks=("名字里有空格（不是冲突副本",)),
    Cell("R4_尾巴一个空格", "`ls` 里根本看不见", ("c.py ", "good.py"),
         rc=1, scanned=2, has=("名字首尾有空白",), lacks=("只提醒",)),
    Cell("R5_Office 锁文件", "编辑器忘删的临时件", ("~$计划书.docx", "计划书.md"),
         rc=1, scanned=2, has=("编辑器留下的临时件",)),
    Cell("R6_中间有空格的合法名字", "不许误伤：它进退码就是错",
         ("湖南 卫视.m3u", "aptv.m3u"), args=("--all",),
         rc=0, scanned=2, has=("只提醒（没算进退码）", "湖南 卫视.m3u", "该查的都查了"),
         lacks=("✗", "名字以「 数字」结尾")),
    Cell("R7_.venv 里的一颗", "那棵树现有尺子一把都不进去",
         (".venv/pyvenv.cfg", ".venv/lib/site.py 2"),
         rc=1, scanned=4, has=("它在 `.venv/` 里", "整个删掉重装")),
    Cell("R8_目录名以「 数字」结尾", "同步盘连目录一起复制", ("data 2/", "data/x.py"),
         rc=1, scanned=3, has=("<tmp>/tree/data 2", "名字以「 数字」结尾")),
    Cell("R9_已经提交进去的那颗", "改它要走一次提交，不是一次 rm",
         ("notes 2.md", "scratch 3"), repo=True, track="notes 2.md",
         rc=1, has=("已经提交进去了", "要走一次提交"), once=("已经提交进去了",)),
    Cell("R10_制表符", "同 R3 另一条分支", ("a\tb.py",),
         rc=1, scanned=1, has=("看不出来，补全和脚本",)),
    Cell("R11_符号链接自己的名字", "链子的名字是本仓库的目录项，背后那棵不是",
         ("good.py", "cache 2||OUT", "out/别人的仓库 2.py"),
         rc=1, scanned=2, has=("名字以「 数字」结尾",),
         lacks=("别人的仓库 2.py",)),
    Cell("C1_一棵干净树", "误伤对照组：全仓 0 颗时该说的话",
         ("a.py", "b.md", "sub/", "sub/c.py"),
         rc=0, scanned=4, has=("0 个拦得住、0 个只是提醒", "该查的都查了"),
         lacks=("✗", "只提醒", "怎么处理")),
    Cell("C2_一个名字都没有", "「没量」≠「没查到错」（2.32 那一族）",
         (), rc=2, has=("底下一个名字都没有", "这不算过"), lacks=("该查的都查了",)),
    Cell("C3_符号链接指向的大树", "扫本仓库不等于扫别人",
         ("real.py", "link||OUT", "out/别人的 2.py"),
         rc=0, scanned=2, has=("0 个拦得住", "该查的都查了"), lacks=("✗", "别人的")),
    Cell("C4_--root 指的不是目录", "指错地方也不能算过",
         ("note.txt",), sub="note.txt", rc=2, has=("不是个目录", "这一轮什么都没量")),
)


def split_item(item: str) -> tuple[str, str, str, bool]:
    """把一条种植说明拆成 `(种类, 相对路径, 链接目标, 在外面那棵里吗)`。

    结尾 `/` = 目录；含 `||` = 符号链接（`名字||目标`，目标写 `OUT` 指到外面那棵树）；
    前缀 `out/` = 种在被扫的那棵树**之外**（那是「别人的仓库」，`os.walk` 不该进去）。

    >>> split_item("a.py")
    ('file', 'a.py', '', False)
    >>> split_item("data 2/")
    ('dir', 'data 2', '', False)
    >>> split_item("out/inner/")
    ('dir', 'inner', '', True)
    >>> split_item("out/别人的 2.py")
    ('file', '别人的 2.py', '', True)
    >>> split_item("cache 2||OUT")
    ('link', 'cache 2', 'OUT', False)
    """
    rel, target = item, ""
    if "||" in rel:
        rel, _, target = rel.partition("||")
    outside = rel.startswith("out/")
    if outside:
        rel = rel[len("out/"):]
    kind = "link" if target else ("dir" if rel.endswith("/") else "file")
    return kind, rel.rstrip("/") if kind == "dir" else rel, target, outside


def plant(base: Path, cell: Cell) -> tuple[bool, str]:
    """照一格的说明种一棵临时树。`git` 起不来时返回 `(False, 原因)` —— 那一格算「没验成」，不算过。"""
    tree, out = base / "tree", base / "out"
    tree.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    if cell.repo:
        r = subprocess.run(["git", "init", "-q"], cwd=tree, capture_output=True, text=True)
        if r.returncode:
            return False, f"`git init` 退 {r.returncode}：{(r.stderr or '').strip()[:70]}"
    for item in cell.plant:
        kind, rel, target, outside = split_item(item)
        p = (out if outside else tree) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if kind == "link":
            p.symlink_to(out if target == OUT else tree / target, target_is_directory=True)
        elif kind == "dir":
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.write_text("x\n", encoding="utf-8")
    if cell.track:
        r = subprocess.run(["git", "add", "--", cell.track], cwd=tree,
                           capture_output=True, text=True)
        if r.returncode:
            return False, f"`git add` 退 {r.returncode}：{(r.stderr or '').strip()[:70]}"
    return True, ""


def hide_tmp(text: str, base: Path) -> str:
    """把临时目录名抹成 `<tmp>` 再印 —— 不然两遍输出必然不同（2.55 踩的第 7 条）。

    这条归一规则由**代码**做、并且钉了用例，所以它不再是「比之前先跑一把 `sed`」那种手艺。

    >>> from pathlib import Path
    >>> hide_tmp("✗ /var/folders/xx/T/g256_abcd/tree/a 2.py\\n扫了 3 个名字",
    ...          Path("/var/folders/xx/T/g256_abcd"))
    '✗ <tmp>/tree/a 2.py\\n扫了 3 个名字'
    >>> hide_tmp("没有路径", Path("/tmp/x"))
    '没有路径'
    """
    return text.replace(str(base), "<tmp>")


def check_cell(cell: Cell, rc: int, text: str) -> tuple[bool, str]:
    """这一格符合期望吗：`(符合, 不符的那句)`。四种不符分开报，因为**修法不一样**。

    顺序是定过的：退码排第一（尺崩了或者判据错了，后面那些句子怎么都是白说），
    然后「少了那句」、「多说了那句」（一个是指据/处置提示没落地，一个是误伤），
    再「恰好一次」（正反两半一起钉，见 `R9`），最后才是名字数（种失败或 `walk` 瞎了）。

    >>> c = Cell("T", "试", rc=1, scanned=2, has=("名字以「 数字」结尾",),
    ...          once=("已经提交进去了",), lacks=("它在 `.venv/` 里",))
    >>> good = "✗ a 2.py\\n    名字以「 数字」结尾\\n    已经提交进去了\\n扫了 2 个名字\\n"
    >>> check_cell(c, 1, good)
    (True, '')
    >>> check_cell(c, 0, good)
    (False, '退码：期望 1，实际 0')
    >>> check_cell(c, 1, good.replace("名字以「 数字」结尾", "别的话"))
    (False, '少了那句：名字以「 数字」结尾')
    >>> check_cell(c, 1, good + "它在 `.venv/` 里\\n")
    (False, '多说了那句：它在 `.venv/` 里 —— 误伤')
    >>> check_cell(c, 1, good + "已经提交进去了\\n")
    (False, '那句出现了 2 次，期望恰好 1 次：已经提交进去了')
    >>> check_cell(c, 1, good.replace("扫了 2 个名字", "扫了 9 个名字"))
    (False, '扫到的名字数：期望 2，实际那句不是')
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
    if cell.scanned is not None and f"扫了 {cell.scanned} 个名字" not in text:
        return False, f"扫到的名字数：期望 {cell.scanned}，实际那句不是"
    return True, ""


def run_cell(cell: Cell, base: Path) -> tuple[str, str, str]:
    """跑一格：`(判定, 给人看的那句, 抹过临时路径的原文)`，判定是 `ok` / `bad` / `skip`。

    走的是真的 `main()`（不是又一遍 `find_bad`）：退码、结论行、那几句处置提示，
    全都是这一格要看的东西 —— 只调 `find_bad` 就把 `main()` 那三层输出绕开了。
    """
    ok, why = plant(base, cell)
    if not ok:
        return "skip", f"种不出来，这一格没验成：{why}", ""
    target = (base / "tree" / cell.sub) if cell.sub else base / "tree"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(target), *cell.args])
    except Exception as e:                        # 尺自己炸了算「跑过但不过」，不许吞
        return "bad", f"跑这一格时抛了 {type(e).__name__}: {e}", ""
    text = hide_tmp(buf.getvalue(), base)
    good, why = check_cell(cell, rc, text)
    return ("ok", "", text) if good else ("bad", why, text)


def self_test(cells: tuple[Cell, ...] | None = None) -> int:
    """`--self-test` 那一档：每一格种进一棵临时树、跑一遍这把尺、逐格对期望。

    结论行带着「扫了」那个词（`selfcheck.conclusion()` 靠它挑句子）。
    **顺序是定过的**：过的一格一行先流水，不符期望的那些**留在最后**——
    因为 `selfcheck.run_script()` 失败时只摊出末尾 14 行，把 ✗ 排在 15 行 ✓ 中间，
    那条 ✗ 到了人眼前就只剩一个「退 1」。
    """
    cells = BASELINE if cells is None else cells
    knames = guard_names([c.who for c in cells])
    if knames:
        # 2.57 说过这一档「名字干净是巧合不是闸」—— 闸现在有了，判据在三把尺共用的那个文件里。
        print(knames)
        return 2
    ran = bad = skipped = 0
    fails: list[tuple[Cell, str, str]] = []
    misses: list[tuple[Cell, str]] = []
    for cell in cells:
        with tempfile.TemporaryDirectory(prefix="stray-names-selftest-") as td:
            verdict, why, text = run_cell(cell, Path(td))
        if verdict == "skip":
            skipped += 1
            misses.append((cell, why))
            continue
        ran += 1
        if verdict == "bad":
            bad += 1
            fails.append((cell, why, text))
            continue
        print(f"  ✓ {cell.who:<26} {cell.what}")
    for cell, why in misses:
        print(f"  · {cell.who:<26} {cell.what}\n      {why}")
    if fails:
        print(f"\n—— 以下 {len(fails)} 格不符期望（每格把自己那一遍的原文摊出来）——")
        for cell, why, text in fails:
            print(f"  ✗ {cell.who:<26} {cell.what}\n      {why}")
            for line in text.strip().splitlines():
                print(f"      | {line}")
    tail = f"（另有 {skipped} 格没验成：临时树里起不了 git）" if skipped else ""
    print(f"\n扫了基线 {len(cells)} 格：{bad} 格不符期望"
          + (" —— 那把尺还咬得动" if ran and not bad else " —— 上面逐格点名了") + tail)
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：`BASELINE` 是空的，或者临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stray_names.py",
                                 description="只看文件名的闸：同步盘冲突副本与看不出来的空白")
    ap.add_argument("--root", default=str(ROOT),
                    help="扫哪棵树（默认本仓库；量具与沙盒指别处）")
    ap.add_argument("--all", action="store_true", help="连「只提醒」那一档也逐条列出来")
    ap.add_argument("--self-test", action="store_true",
                    help="不扫仓库：往临时树里种 2.55 那 15 格名字，问这把尺还咬得动吗（2.56）")
    ap.add_argument("--by-dir", action="store_true",
                    help="把总数按顶层目录拆开印（总数会自己动，拆开才知道是谁动的）")
    add_doctest_flag(ap)
    args = ap.parse_args(argv)

    if args.doctest:
        return run_own(sys.modules[__name__])   # 2.69：先答说明书，一个目录都不扫
    if args.self_test:
        return self_test()

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"✗ {root} 不是个目录 —— 这一轮什么都没量", file=sys.stderr)
        return 2
    bad, note, n_total, tops = find_bad(root)
    if not n_total:                       # 空目录：结论那行是「没量」，得有一行 ✗ 配得上它
        print(f"✗ {root} 底下一个名字都没有 —— 这一轮什么都没扫，不算通过")
        if args.by_dir:
            print(f"按顶层目录：{by_dir(tops)}")
        print()
        print(summary(n_total, bad, note, root))
        return 2
    for rel, why, in_git in bad:
        print(f"✗ {root / rel}")
        print(f"    {why}")
        if in_git:
            print(f"    而且它 {in_git}：改名或删掉都要走一次提交，不是一次 `rm`")
        top = rel.split("/")[0]
        if top == ".git":
            print("    它在 `.git/` 里：仓库那五把尺（doctests / 数字 / 命令 / 漂移 / 页面）"
                  "一把都不读这里，所以这一条只有这把尺看得到")
        elif top == ".venv":
            print("    它在 `.venv/` 里：那棵树整个删掉重装就干净了，别去动单个文件")
    if bad:
        print(f"\n{HOW}")
    if note:
        head = f"只提醒（没算进退码）：{len(note)} 个名字里有空格"
        if args.all:
            print(head)
            for rel, _ in note:
                print(f"    · {root / rel}")
        else:
            print(head + " —— 加 --all 逐条看")
    if args.by_dir:
        print(f"按顶层目录：{by_dir(tops)}")
    print()
    print(summary(n_total, bad, note, root))
    if not n_total:
        return 2                                        # 一个名字都没扫到 = 没量，不是量干净了
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
