#!/usr/bin/env python3
"""递 `--doctest` 给一件脚本时，它有没有顺便去干自己的活。

这一件的存在理由是一段**担心**，不是一条命令。§2.68 的变异机逃掉过一刀 `M16`：把
`analyze_upstream` 的 `if wants_tests:` 改成 `if False:` —— 字面量和那道门都还在，静态那一档
照旧判「走通」，可它一个用例都不答。当时写进边界的理由是「抓它只能**真跑一遍**
`python 那件 --doctest`，而这一族里 `probe_pack` 会写盘、`serve_lan` 会起监听 —— 递 `--doctest`
给它们的语义正好是『去干你自己的活』」。§2.69 真去跑了那两遍，读到的是 argparse 的 usage、
退 2、`data/` 一个字节没动 —— 那句担心是**假的**（计划书里记了改口）。但「假」是拿眼睛对着
屏幕看出来的，下一遍还得再看一次。所以本节把它换成一个读数：`sys.addaudithook`（PEP 578）
在进程里挂一只不收钱的观察者，任何一次写文件、任何一次出门、任何一次起进程都要在它面前过一遍。

跑法（两条规矩都写在 `split_at_target` 那段里）：

    .venv/bin/python scripts/work_guard.py scripts/probe_pack.py --doctest
    .venv/bin/python scripts/work_guard.py --doctest              # 只跑本件这一份用例

* 本件自己的旗排在被量件**前面**；从第一个不像旗的字起，后面全部原样递给被量件。
  否则 `--doctest` 会被两层各认一次：本件跑了自己的用例，被量件反倒没收到旗。
* 只记、不拦。这是设计，不是偷懒：拦下来之后「它没去干活」这句话就有两种读法
  ——「它本来不会」和「它本来会、被我按住了」，而本节要的恰恰是分清这两者。
  护栏因此**不改被量件的行为**，只把退码变成 1：按 2.62 那三档，那是「干成了、但结果有毛病」。

退码（本件这一层，跟被量件的退码分开说）：**0** = 它答了、护栏没记下落在仓库里的动作；
**1** = 有毛病 —— 被量件退非 0，或护栏记下了动作；**2** = 什么都没量到 —— 没指名被量件、
那个路径不存在、或它连跑都没跑起来。

`run_doctests.py --each` 是本件存在的用法：逐件起一个子进程、每件都挂本件，核对
「答没答、用例数跟静态那把尺对不对得上、量的件标签是不是它自己」。
"""

from __future__ import annotations

import argparse
import functools
import os
import pathlib
import runpy
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:      # 为了 import run_doctests（邻居也是这么找邻居的）
    sys.path.insert(0, str(ROOT / "scripts"))

from run_doctests import add_doctest_flag, run_own  # noqa: E402

# 出门这一族：一次连接、一次 DNS、一次 HTTP 请求，全都要在这只眼睛面前过。
NET_EVENTS = frozenset({
    "socket.connect", "socket.connect_ex", "socket.sendto", "socket.create_connection",
    "socket.getaddrinfo", "socket.getnameinfo", "http.client", "urllib.Request",
    "ftplib.FTP", "smtplib.SMTP",
})
# 起进程这一族：`subprocess` 与 `os` 那几条 exec／system／spawn。
PROC_EVENTS = frozenset({
    "subprocess.Popen", "os.system", "os.exec", "os.execv", "os.execve",
    "os.spawn", "os.posix_spawn", "os.startfile",
})
# 这一族要判的是「那个子进程在哪个目录下起」，所以得知道每一族的 `cwd` 摆在第几位。
# 位子是量出来的（03:27:5x 那份 `/tmp/proc_probe270.py`）：`subprocess.Popen` 递出来的是
# `(命令名, argv 那个列表, cwd, env)` 四位，`cwd` 没给时那一位是 `None`。
PROC_CWD: dict[str, int] = {"subprocess.Popen": 2}
# 只有一位、就是那条命令字符串的这一族：它**必然**继承本进程的 cwd，所以「在哪儿起」是已知的。
PROC_INHERITS = frozenset({"os.system"})
# 带路径的动作。`open`／`os.open` 另立一档，因为还要分「读」和「写」。
FS_EVENTS = frozenset({
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.mkdir", "os.makedirs",
    "os.rename", "os.rename2", "os.replace", "os.truncate", "os.chmod", "os.chown",
    "os.link", "os.symlink", "os.utime", "shutil.move", "shutil.copy", "shutil.copy2",
    "shutil.rmtree",
})
OPEN_EVENTS = frozenset({"open", "os.open"})
WATCHED = NET_EVENTS | PROC_EVENTS | FS_EVENTS | OPEN_EVENTS

# 仓库里这几棵树不算「地」：那是环境、缓存和 git 自己的地盘，不是这份代码要交付的状态。
# `data/`、`config/`、`docs/` 全在保护圈里 —— 递 `--doctest` 时动了它们就是去干自己的活了。
CACHE_DIRS = frozenset({".venv", "__pycache__", ".git", ".mypy_cache", ".pytest_cache",
                        ".ruff_cache", ".DS_Store"})

# `os.O_WRONLY | O_RDWR | O_CREAT | O_TRUNC | O_APPEND` 那一套位；读一个都不占。
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

# 每一族事件里 `dir_fd` 摆在第几位（03:12 在这一台上实测的摆法，见 `dir_fds` 那段理由）。
# 名单里没有的事件一律按「没有 fd 位」处理：宁可说不清，也不许把权限位当成描述符。
_FD_SLOTS: dict[str, tuple[int, ...]] = {
    "os.remove": (1,), "os.unlink": (1,), "os.rmdir": (1,),
    "os.mkdir": (2,), "os.makedirs": (2,), "os.chmod": (2,), "os.symlink": (2,),
    "os.utime": (3,), "os.rename": (2, 3), "os.rename2": (2, 3), "os.replace": (2, 3),
}


def open_parts(event: str, args: tuple) -> tuple[object, object]:
    """从一条 open 审计事件里取出（flags, mode）。

    为什么要分这两种摆法：`builtins.open` 发的是 `(路径, 'w', flags)`，
    `os.open` 发的是 `(路径, flags, 权限)` —— 同一个 `flags` 一个在第 3 位、一个在第 2 位。
    03:06 实测过两遍才对上；按一个摆法写死，另一种就会把权限位 `511` 当成 flags
    （`511 & WRITE_FLAGS` 非零 → 每一次 `os.open` 只读都被判成写）。

    >>> open_parts("open", ("a.md", "w", 16778753))
    (16778753, 'w')
    >>> open_parts("os.open", ("a.md", 5, 448))
    (5, 448)
    >>> open_parts("open", ())                                  # 参数比预期少：两个都给 None，不炸
    (None, None)
    """
    if event == "os.open":
        return (args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)
    return (args[2] if len(args) > 2 else None, args[1] if len(args) > 1 else None)


def write_mode(flags: object, mode: object) -> bool:
    """这一次 `open` 是不是要往文件里写。

    两道判据按顺序来：审计事件给的 `flags` 是整数，比字符串准；拿不到时才退回看 mode 串
    （`'w'`／`'a'`／`'x'` 开头，或者带 `'+'`）。两样都没有时**放过** ——
    宁可漏一条，也不许让误报变成「这一遍不干净」。

    >>> write_mode(16778753, "w")                    # 实测值：open('x','w') 递出来的 flags
    True
    >>> write_mode(16777216, "r")                    # 只读（O_EVTONLY）
    False
    >>> write_mode(None, "r+")                       # 拿不到 flags：按 mode 串判
    True
    >>> write_mode(None, "rb")
    False
    >>> write_mode(None, 448)                        # os.open 那种第 3 位是权限，不是 mode 串
    False
    >>> write_mode(1, None)                          # 只有 flags：也够
    True
    """
    if isinstance(flags, int):
        return bool(flags & WRITE_FLAGS)
    return isinstance(mode, str) and (mode[:1] in ("w", "a", "x") or "+" in mode)


def abspath(path: object, cwd: str) -> str:
    """把事件里那个路径摊成绝对路径；摊不动就返回空串（不猜）。

    为什么纯字符串运算、不调 `Path.resolve()`：钩子跑在被量件的动作**之前**，多一次 `stat`
    就多一份扰动；而 `os.path.abspath` 只把 `cwd` 跟字符串接起来（`getcwd` 本身不发审计事件）。
    相对路径落到 `cwd` 上正是想要的：03:04:52 那份普查量到一批「件自己 chdir 进临时目录
    再写文件」的 doctest（`os.remove ('s.yaml', 3)` 那一族），那一遍 `cwd` 是
    `/var/folders/…/T/…`，于是这些相对路径不该算它动了仓库。

    >>> abspath("data/report.md", "/r")
    '/r/data/report.md'
    >>> abspath("/tmp/x/y.md", "/r")
    '/tmp/x/y.md'
    >>> abspath(3, "/r")                                            # 递进来的是 fd，不是路径
    ''
    >>> abspath("", "/r")
    ''
    >>> abspath("a.txt", "")                                        # 连 cwd 都没有：不硬接
    'a.txt'
    """
    if not isinstance(path, (str, bytes, os.PathLike)):
        return ""
    try:
        p = os.fspath(path)
        if isinstance(p, bytes):
            p = p.decode("utf-8", "replace")
    except (TypeError, ValueError):
        return ""
    if not p:
        return ""
    return p if os.path.isabs(p) or not cwd else os.path.join(cwd, p)


_REAL = functools.lru_cache(maxsize=1024)(os.path.realpath)


def under(path: str, base: str) -> str | None:
    """`path` 在 `base` 这棵树里 → 给出树下的那截（空串＝就是根本身）；不在 → `None`。

    **两种拼法都试**，因为同一棵树可以有两张脸：`/tmp` 跟它的真身 `/private/tmp`。
    03:31 那份变异探针（`/tmp/mut270.py`）正是从这张脸上逃掉的 —— 它在仓库里 `os.mkdir`，
    递的是 `/tmp/clean267/…`，而护栏手里的 `ROOT` 是 `__file__` resolve 出来的
    `/private/tmp/clean267`，字面比出来是「不在仓库里」。**只看一张脸的尺子会漏，会安静地漏。**
    代价是每条落不上的事件多一次 `realpath`（`lru_cache` 兜着：一件的 doctest 反复在同一棵
    树下动手，那一遍只查一次盘）。

    >>> under("/r/data/x.md", "/r")
    'data/x.md'
    >>> under("/r", "/r")                                            # 根本身：在，且树下那截是空
    ''
    >>> under("/rx/docs", "/r") is None                              # 少一个分隔符就串门了
    True
    >>> under("/tmp/x", "/r") is None
    True
    >>> under(os.path.realpath("/tmp"), "/tmp")                      # 两张脸：认得出是同一棵树
    ''
    """
    for cand, b in ((os.path.normpath(path), os.path.normpath(base)),
                    (_REAL(path), _REAL(base))):
        if cand == b:
            return ""
        if cand.startswith(b + os.sep):
            return cand[len(b) + 1:]
    return None


def protected(path: object, root: str, cwd: str) -> bool:
    """这个路径是不是「仓库里的真东西」。

    在 `root` 之下、且路上没经过 `.venv`／`__pycache__` 那几棵缓存树才算。临时目录不算：
    `TemporaryDirectory` 那一族沙盒正是 doctest **该**写文件的地方 —— 03:37:55 那份普查
    （`/tmp/census270.py`，18 件接了门的各起一个子进程）量到 244 条这类动作，
    落在仓库里的 0 条，全在临时目录和件自己 chdir 进去的沙盒里。
    「落在仓库里的 0 条」这个数就是这一整套保护圈的第一个读数。

    >>> protected("data/report.md", "/r", "/r")
    True
    >>> protected("/r/config/sources.yaml", "/r", "/tmp")           # 绝对路径，跟 cwd 无关
    True
    >>> protected("x.yaml", "/r", "/private/tmp/T/abc")             # 沙盒里的相对路径：不算
    False
    >>> protected("/r/.venv/lib/site.py", "/r", "/r")               # 环境本身
    False
    >>> protected("/r/src/__pycache__/cli.cpython-312.pyc", "/r", "/r")
    False
    >>> protected("/r/.git/HEAD", "/r", "/r")                       # git 自己的地盘
    False
    >>> protected("/r/docs/x.md", "/r", "/r")
    True
    >>> protected("/tmp/x/y.md", "/r", "/r")
    False
    >>> protected("", "/r", "/r")                                   # 摊不动的也算「不知道」
    False
    >>> protected("/rx/docs/x.md", "/r", "/r")     # 前缀像但不是那一棵树：不算（少个分隔符就串门）
    False
    >>> protected("/r", "/r", "/r")        # 仓库根本身：算（子进程「在这个目录下起」就是这种形状）
    True
    >>> protected("x", "/r", "/r")         # 相对路径落在 root 上：算
    True
    >>> protected(os.path.realpath("/tmp"), "/tmp", "/tmp")   # 拿真身拼、base 拿别名：也算（见 `under`）
    True
    """
    p = abspath(path, cwd)
    if not p:
        return False
    rel = under(p, root)
    if rel is None:
        return False
    return not any(part in CACHE_DIRS for part in rel.split(os.sep))


def proc_where(event: str, args: tuple, cwd: str) -> str:
    """这一条起进程的事件，那个子进程会在哪个目录下跑；**说不清则空串**（不猜）。

    三种已知：`PROC_CWD` 里那一族给了 `cwd` 就用它、那一位是 `None` 就是继承本进程的；
    `PROC_INHERITS` 里那一族必然继承。名单之外的（`os.spawn`／`os.execv`／`os.startfile`
    那几族）一律空串 —— 它们的参数摆法本件没量过，而「不知道」跟「在仓库外」在屏幕上
    必须是两个形状（本件处处守的那条「两种 0 不同形」，2.62）。

    >>> proc_where("subprocess.Popen", ("git", ["git", "ls"], "/T/tmpabc", None), "/r")
    '/T/tmpabc'
    >>> proc_where("subprocess.Popen", ("git", ["git", "ls"], None, None), "/r")
    '/r'
    >>> proc_where("subprocess.Popen", ("git", ["git", "ls"], "sub", None), "/r")  # 相对 cwd
    '/r/sub'
    >>> proc_where("os.system", (b"true",), "/r")
    '/r'
    >>> proc_where("os.spawn", ("x",), "/r")                          # 摆法没量过：不猜
    ''
    >>> proc_where("subprocess.Popen", ("/bin/ls",), "/r")     # 位数不够（换了 Python 的版本）
    ''
    """
    if event in PROC_INHERITS:
        return cwd
    slot = PROC_CWD.get(event)
    if slot is None or len(args) <= slot:
        return ""
    given = args[slot]
    return cwd if given is None else abspath(given, cwd)


def proc_name(args: tuple) -> str:
    """那一条命令叫什么（给人看的那两个字）。

    >>> proc_name(("git", ["git", "ls-files", "-z"], "/T/x", None))
    'git'
    >>> proc_name((b"true",))                                          # os.system 那位是 bytes
    'true'
    >>> proc_name((["run", "x"],))                                     # 第 0 位本身是个列表
    "['run', 'x']"
    >>> proc_name(())
    ''
    """
    if not args:
        return ""
    first = args[0]
    return first.decode("utf-8", "replace") if isinstance(first, bytes) else str(first)


def proc_args(event: str, args: tuple) -> list[object]:
    """那条命令**自己写在参数里**的「像路径的字」（`argv` 摊平一层；`cwd` 那一位归 `proc_where`）。

    为什么要挑「带分隔符的」而不是什么都试：argv 里什么字都有（`-z`、`80`、`--doctest`），
    而 `protected` 会把不带斜杠的字接到 `cwd` 上 —— 一个 `-z` 能被接成「仓库里的一个文件」，
    那是**凭空造出来的警报**。分隔符这道门槛不很高，但它保证屏幕上那句路径是命令里**写出来的**。
    `env` 那一位（一个 dict）只摊到键名：环境变量名里没有斜杠，所以它天然不进这一列。
    `os.system` 那一族递的是整条 shell 字符串（bytes）：它进来，于是
    `cat /repo/x` 这种「藏在字符串里的路径」也照样认得 —— 代价是一句 `echo hi` 会被当成
    一个叫 `echo hi` 的相对路径去比，比不上，不响。

    >>> proc_args("subprocess.Popen", ("git", ["git", "-C", "/r/data", "add"], "/T/x", None))
    ['/r/data']
    >>> proc_args("subprocess.Popen", ("/bin/echo", ["/bin/echo", "hi"], None, None))
    ['/bin/echo']
    >>> proc_args("os.system", (b"cat /r/x",))
    [b'cat /r/x']
    >>> proc_args("subprocess.Popen", ("/bin/sh", ["/bin/sh", "-c", "true"], "/T", {"PATH": "/x"}))
    ['/bin/sh']
    """
    skip = PROC_CWD.get(event)
    items: list[object] = []
    for i, a in enumerate(args):
        if i == skip:
            continue
        items.extend(a if isinstance(a, (list, tuple)) else [a])
    out: list[object] = []
    for a in items:
        # 去重保序：第 0 位那个可执行文件跟 `argv[0]` 十有八九是同一个字，留两份只碍读
        if a in out or not (isinstance(a, (bytes, os.PathLike))
                            or (isinstance(a, str) and "/" in a)):
            continue
        out.append(a)
    return out


def proc_note(event: str, args: tuple, root: str, cwd: str) -> str:
    """起进程这一族该说成哪一句；在沙盒里起的、或说不清在哪里的，返回空串（只进账、不上屏）。

    为什么必须有这一层：03:27 头一遍 `--each` 把 `scripts/stray_names.py` 判成「它去干了
    自己的活：起进程 git ×5」，而那 5 个 git 全跑在 `TemporaryDirectory` 里造的假仓库上 ——
    那正是它的 doctest **该**做的事。把「起了个进程」直接当成「动了仓库」，护栏就会把每一件
    干净的沙盒测试读成嫌疑人，而这一整套判据的价值恰恰在「只有真动手才响」。
    判两样：那个子进程**在哪儿起**（在仓库里 → 它一抬脚就踩在真东西上），
    以及那条命令**有没有点名的路径在仓库里**（`git -C /repo` 那种，cwd 在沙盒也照样动得到，
    走 `proc_args` 那一层，所以 `cat /repo/x` 藏在 shell 字符串里也认得）。

    >>> T = "/private/tmp/T/tmpabc"
    >>> proc_note("subprocess.Popen", ("git", ["git", "ls-files", "-z"], T, None), "/r", "/r")
    ''
    >>> proc_note("subprocess.Popen", ("git", ["git", "status"], None, None), "/r", "/r")
    '起进程 git（在 /r 这儿起的）'
    >>> proc_note("subprocess.Popen", ("git", ["git", "-C", "/r/data", "add"], T, None), "/r", T)
    '起进程 git 点了仓库里的路径 /r/data'
    >>> proc_note("os.system", (b"true",), "/r", "/r")
    '起进程 true（在 /r 这儿起的）'
    >>> proc_note("os.execv", ("/r/bin/x", []), "/r", T)     # 摆法没量过：宁可不说
    ''
    """
    where = proc_where(event, args, cwd)
    if not where:
        return ""
    name = proc_name(args)
    if protected(where, root, cwd):
        return f"起进程 {name}（在 {where} 这儿起的）"
    for tok in proc_args(event, args):
        if protected(tok, root, cwd):
            return f"起进程 {name} 点了仓库里的路径 {abspath(tok, cwd)}"
    return ""


def dir_fds(event: str, args: tuple) -> list[int]:
    """这条事件里有没有「目录描述符」。有，那个相对路径就是相对**那个目录**、不是相对 cwd。

    位子是量出来的，不是查表查来的：03:12:0x 在这一台上一遍扫过 `os.remove`／`os.rmdir`／
    `os.mkdir`／`os.chmod`／`os.utime`／`os.rename`／`shutil.rmtree`，各事件的参数摆法是
    `(路径, …, dir_fd)`；`shutil.rmtree` 那一条第二位是个函数不是整数，所以它天然不会被误认。

    为什么这一条值得单独立一个函数：它挡的是一批**假警报**。03:11:22 头一遍跑
    `work_guard.py src/cli.py --doctest`，护栏报了 27 条「落在仓库里的 `os.remove`」
    （`s.yaml`、`probe.json`、`bad.json` 那一串），看名字像是件真的在动仓库。实际是
    `TemporaryDirectory` 收尾时 `shutil.rmtree` 走的那条 fd 安全路径：
    `os.unlink(entry.name, dir_fd=topfd)` —— 传进来的就是光一个文件名，
    拿 `cwd` 去接它，接出来的是 `/tmp/clean267/s.yaml`。
    认不出 dir_fd 的护栏会把每一件干净的临时清理都读成「它去干活了」。

    >>> dir_fds("os.remove", ("s.yaml", 3))                       # rmtree 那条实测形状
    [3]
    >>> dir_fds("os.remove", ("/var/T/x/probe.json", -1))          # -1 = 「就是相对 cwd」
    []
    >>> dir_fds("os.mkdir", ("dd", 511, -1))                       # 中间那个 511 是权限，不是 fd
    []
    >>> dir_fds("os.mkdir", ("d3", 511, 3))
    [3]
    >>> dir_fds("shutil.rmtree", ("d2", None))                     # 第二位是函数：不算
    []
    >>> dir_fds("os.rename", ("a", "b", -1, 4))
    [4]
    >>> dir_fds("open", ("a", "w", 16778753))                      # 这一族没有 fd 位
    []
    """
    slots = _FD_SLOTS.get(event, ())
    out = []
    for i in slots:
        if len(args) > i and isinstance(args[i], int) and args[i] >= 0:
            out.append(args[i])
    return out


def unclear_tag(event: str, args: tuple) -> str:
    """事件名后面要不要跟一个问号（= 这一条本件**说不清**落在哪儿）。

    为什么不静默放过：这一族的取舍是「看不见就说看不见」。把 27 条带 dir_fd 的
    `os.remove` 当成「在仓库外」直接抹掉，屏幕上那句「落在仓库里 0 条」就少了一个前提 ——
    而那个前提正是本节要给人复核的东西。
    03:37:55 那份普查里 `src/cli.py` 看见 136 条动作、其中 27 条带 dir_fd，就是这么露出来的。

    >>> unclear_tag("os.remove", ("s.yaml", 3))
    'os.remove?'
    >>> unclear_tag("os.remove", ("/var/T/x/probe.json", -1))
    'os.remove'
    >>> unclear_tag("socket.connect", ("<s>", ("1.2.3.4", 80)))     # 没有路径的这一族：不加问号
    'socket.connect'
    >>> unclear_tag("subprocess.Popen", ("git", ["git"], "/T/x", None))    # cwd 那一位量过：说得清
    'subprocess.Popen'
    >>> unclear_tag("os.execv", ("/r/bin/x", []))                  # 摆法没量过：这一条说不清
    'os.execv?'
    """
    if event in OPEN_EVENTS or event in NET_EVENTS:
        return event
    if event in PROC_EVENTS:
        # 说得清「在哪儿起」才不加问号：`proc_where` 递一个占位的 cwd，它返回空串就是摆法没量过
        return event if proc_where(event, args, "/") else event + "?"
    return event + ("?" if dir_fds(event, args) else "")


def why_event(event: str, args: tuple, root: str, cwd: str) -> str:
    """这一条事件要是动了保护圈里的东西，该说成哪一句；没动（或不是这三族）返回空串。

    分三族是因为三族要问的不是一回事：写文件问路径，出门问地址，起进程问命令。
    每一句都带着**是谁**：只报「有 2 条动作」的话，下一个读的人还得自己加钩子去找。

    >>> why_event("open", ("data/report.md", "w", 16778753), "/r", "/r")
    '写 data/report.md'
    >>> why_event("os.open", ("/r/config/sources.yaml", 5, 448), "/r", "/r")
    '写 /r/config/sources.yaml'
    >>> why_event("open", ("/r/config/sources.yaml", "r", 16777216), "/r", "/r")
    ''
    >>> why_event("os.remove", ("b.m3u", -1), "/r", "/private/tmp/T/x")    # 沙盒里删自己的临时件
    ''
    >>> why_event("os.remove", ("/r/data/probe.json", -1), "/r", "/r")
    'os.remove /r/data/probe.json'
    >>> why_event("os.rename", ("/r/data/a", "/r/data/b", -1, -1), "/r", "/r")
    '改名 /r/data/a -> /r/data/b'
    >>> why_event("socket.connect", ("<sock>", ("203.0.113.9", 80)), "/r", "/r")
    "出门 socket.connect ('<sock>', ('203.0.113.9', 80))"
    >>> why_event("subprocess.Popen", ("git", ["git", "ls-files"], "/T/x", None), "/r", "/r")
    ''
    >>> why_event("subprocess.Popen", ("git", ["git", "status"], None, None), "/r", "/r")
    '起进程 git（在 /r 这儿起的）'
    >>> why_event("import", ("src.cli",), "/r", "/r")               # 不在三族里：不收
    ''
    >>> why_event("os.mkdir", ("/private/tmp/T/abc", 511, -1), "/r", "/private/tmp/T/abc")
    ''
    """
    if event in NET_EVENTS:
        return f"出门 {event} {str(args)[:120]}"
    if event in PROC_EVENTS:
        return proc_note(event, args, root, cwd)
    if event in OPEN_EVENTS:
        flags, mode = open_parts(event, args)
        if not write_mode(flags, mode) or not protected(args[0] if args else "", root, cwd):
            return ""
        return f"写 {args[0]}"
    if event in FS_EVENTS:
        paths = [a for a in args if isinstance(a, (str, bytes, os.PathLike))]
        if dir_fds(event, args) and not all(os.path.isabs(os.fspath(p)) for p in paths):
            return ""                  # 相对一个目录描述符：接在 cwd 上会接出错位（见 `dir_fds`）
        if any(protected(p, root, cwd) for p in paths):
            verb = ("改名" if event in ("os.rename", "os.rename2", "os.replace")
                    else event)
            return verb + " " + " -> ".join(str(p) for p in paths[:2])
    return ""


def census_note(hits: list[tuple[str, str]]) -> str:
    """这只眼睛一共看见了些什么（一句短话）。

    为什么必须有这一句：`findings_of` 是空的，可以来自两件完全相反的事 ——
    被量件真的什么都没干，或者我的 `WATCHED` 名单写歪了、一条都没往里递。
    03:37:55 那份普查正是靠「记下了 244 条、其中落在仓库里 0 条」这两个数同时在场，
    才读得出那个 0 是真的 0。

    >>> census_note([])
    '一条这类动作都没看见'
    >>> census_note([("os.mkdir", ""), ("os.mkdir", "写 /r/d"), ("socket.connect", "出门 x")])
    '看见 3 条（os.mkdir 2、socket.connect 1）'
    """
    if not hits:
        return "一条这类动作都没看见"
    tally = Counter(e for e, _ in hits)
    order = sorted(tally, key=lambda k: (-tally[k], k))
    return (f"看见 {len(hits)} 条（"
            + "、".join(f"{k} {tally[k]}" for k in order) + "）")


def findings_of(hits: list[tuple[str, str]]) -> list[str]:
    """从这本账里挑出「落在仓库里的那些话」。

    >>> findings_of([("os.mkdir", ""), ("open", "写 /r/data/report.md")])
    ['写 /r/data/report.md']
    >>> findings_of([])
    []
    """
    return [why for _, why in hits if why]


def unclear_of(hits: list[tuple[str, str]]) -> int:
    """本件「说不清在哪儿」的那几条有多少（带 `dir_fd` 的相对路径，见 `dir_fds`）。

    >>> unclear_of([("os.remove?", ""), ("os.mkdir", "")])
    1
    >>> unclear_of([])
    0
    """
    return sum(1 for e, _ in hits if e.endswith("?"))


def guard_line(hits: list[tuple[str, str]], rc: int | None) -> str:
    """护栏这一遍收尾要印的那一句。

    三条分支在屏幕上必须长得不一样，因为那三种读法要办的事相反：
    「什么都没看见」是该往下走，「看见了但都在沙盒里」也是该往下走但知道得更多，
    而「被量件根本没跑起来」时那句「它没干活」是**不能说的**。
    「说不清在哪儿」那一截单独印：它是这句「落在仓库里 0 条」的前提，得让人能复核。

    >>> guard_line([], 0)
    '护栏：一条这类动作都没看见、落在仓库里 0 条（被量件退 0）'
    >>> guard_line([("os.mkdir", ""), ("os.mkdir", "")], 0)
    '护栏：看见 2 条（os.mkdir 2）、落在仓库里 0 条（被量件退 0）'
    >>> guard_line([("os.remove?", ""), ("os.mkdir", "")], 0)
    '护栏：看见 2 条（os.mkdir 1、os.remove? 1）、说不清在哪儿 1 条、落在仓库里 0 条（被量件退 0）'
    >>> guard_line([("open", "写 /r/data/report.md")], 1)
    '护栏：看见 1 条（open 1）、落在仓库里 1 条：写 /r/data/report.md（被量件退 1）'
    >>> guard_line([], None)
    '护栏：一条都没看见 —— 可被量件根本没跑起来，这一句读不出「它没干活」'
    """
    if rc is None:
        return ("护栏：一条都没看见 —— 可被量件根本没跑起来，"
                "这一句读不出「它没干活」")
    found = findings_of(hits)
    head = f"护栏：{census_note(hits)}"
    n = unclear_of(hits)
    if n:
        head += f"、说不清在哪儿 {n} 条"
    head += f"、落在仓库里 {len(found)} 条"
    if found:
        head += "：" + "、".join(found)
    return head + f"（被量件退 {rc}）"


def brief_target(target: str) -> str:
    """给人看的被量件名字：在仓库里就给相对路径，不在就给原样。

    为什么：这一句要能被抄进履历，而 `/tmp/clean267/…` 那一串前缀在两棵不同的树里不一样
    —— 上一节就踩过「同一份正文在干净副本和原位读出来不是一个数」。

    >>> brief_target(str(ROOT / "scripts" / "x.py"))
    'scripts/x.py'
    >>> brief_target("scripts/x.py")
    'scripts/x.py'
    >>> brief_target("/tmp/other/x.py")
    '/tmp/other/x.py'
    """
    try:
        return str(pathlib.Path(target).resolve().relative_to(ROOT))
    except (OSError, ValueError):
        return str(target)


def run(target: str, argv: tuple[str, ...] = ()) -> tuple[int | None, list[tuple[str, str]]]:
    """在护栏底下把 `target` 当 `__main__` 跑一遍，返回（它的退码，护栏那本账）。

    为什么是 `runpy.run_path` 而不是 `subprocess`：本节要的是**同一个进程里**的审计事件；
    起子进程得再挂一遍钩子、还得跨进程把账递回来。而「每件一个进程」这件事本来就由
    `--each` 那一层负责（钩子装上就摘不下来，一遍量两件必须分进程）。

    两条关于 `sys.path` 的规矩，方向相反，都得说清楚：

    * **补**：`runpy.run_path` 不把脚本所在目录放进 `sys.path[0]`（那是解释器自己启动时才做的），
      于是 03:01:15 头一遍量到 `ModuleNotFoundError: No module named 'run_doctests'` ——
      那些件平时靠「脚本目录就是 `sys.path[0]`」互相引用。所以本件替它补上那一级。
    * **不补**：本件自己为了 import `run_doctests` 而插进 `sys.path` 的那两级（仓库根、
      `scripts/`），在跑被量件之前**要拿掉**。不拿掉就是我在替它补它自己没补的路：
      03:10:23 头一遍量到的正是这件事 —— `src/check/scope.py` 那样只有绝对导入
      （`from src.keys import …`）的纯库，照文档敲 `python src/check/scope.py --doctest`
      会 traceback 退 1（§2.69 记过这一档），而在补了仓库根的护栏底下它**安静地退 0**。
      那一句「退 0」读起来像「它没去干活」，实际是「它压根没跑起来、而我替它把路铺平了」。
      拿掉之后它回到 `跑不起来` → 退 2（什么都没量到），跟屏幕上的形状一致。

    退码按 `SystemExit.code` 摊平：`None` 是「它说它不干了、算 0」，字符串是「它喊了一嗓子、
    算 1」；**跑之前就炸了**（导入失败、语法错）记成 `None` —— 交给 `main` 落到退 2 那一档。

    这一句没法在这里给 doctest：它跑的是**真的另一件脚本**，要往屏幕上印东西。
    盯着它的是 `--each` 那一层（`run_doctests.each_verdict`）和 03:1x 那几遍实测。
    """
    hits = install()
    path = pathlib.Path(target)
    saved = list(sys.path)
    sys.argv = [target, *argv]
    mine = {str(ROOT), str(ROOT / "scripts"), ""}
    try:
        sys.path[:] = [str(path.parent.resolve())] + [p for p in saved if p not in mine]
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as e:
        code = e.code
        rc = 0 if code is None else code if isinstance(code, int) else 1
        return rc, hits
    except BaseException as e:                  # 件自己炸了：那是「没答上」，不是「它没干活」
        print(f"✗ 跑不起来：{type(e).__name__}: {e}", file=sys.stderr)
        return None, hits
    finally:
        sys.path[:] = saved
    return 0, hits


def install(root: str = str(ROOT)) -> list[tuple[str, str]]:
    """挂上这只眼睛，返回它那一本账：每条是一个 `(事件名, 落在仓库里的话)`。

    为什么不拦：见模块开头那条「只记、不拦」。为什么不写成全局变量：审计钩子**装上就摘不下来**
    （`sys` 没有 `removeaudithook`），要在一遍里量两件就得各拿一本账 —— 把账递出来是唯一
    不掉牙的写法（2.68 那句「`mod` 必须点名递进来」是同一族）。

    钩子里那句 `except Exception: return` 是本件最重要的一行：判据自己炸了（事件参数形状
    跟预期不一样、路径里混进奇怪的字节）时**不许改变被量件的行为**。
    漏一条比扰动一遍好，代价由 `census_note` 那一句兜着 —— 名单写歪会连着「看见 0 条」一起露出来。

    >>> seen = install("/r")                     # 递一棵假仓库：只验形状，不动真东西
    >>> len(seen)                                # 刚挂上时是空的
    0
    >>> with open(os.devnull, "r"):              # 读一个不在保护圈里的东西：不记账（也不该记）
    ...     pass
    >>> [h for h in seen if h[1]]
    []
    """
    hits: list[tuple[str, str]] = []

    def hook(event: str, args) -> None:
        if event not in WATCHED:
            return
        try:
            a = tuple(args)
            if event in OPEN_EVENTS:
                flags, mode = open_parts(event, a)
                if not write_mode(flags, mode):
                    return                       # 只读的 open：一次都不记（import 一个件就有一次）
            hits.append((unclear_tag(event, a), why_event(event, a, root, os.getcwd())))
        except Exception:                        # 判据炸了不许碰被量件（见上面那段）
            return

    sys.addaudithook(hook)
    return hits


def split_at_target(argv: list[str]) -> tuple[list[str], list[str]]:
    """把「本件的旗」和「递给被量件的那些字」切开。

    规矩只有一条：从第一个不像旗的字起，后面全部归被量件。

    >>> split_at_target(["--doctest"])
    (['--doctest'], [])
    >>> split_at_target(["scripts/probe_pack.py", "--doctest"])
    ([], ['scripts/probe_pack.py', '--doctest'])
    >>> split_at_target(["--doctest", "x.py", "--to-history", "--doctest"])
    (['--doctest'], ['x.py', '--to-history', '--doctest'])
    >>> split_at_target([])                                             # 谁都没给：两半都空
    ([], [])

    为什么要切而不是 `parse_known_args`：那一招会把被量件的 `--doctest` 先认下来
    （那正是本件自己认的那面旗），于是「递给 probe_pack 的那一句」在到达它之前就被上一层
    吃掉了 —— 同一族病：2.68 那句「`testmod()` 不点名就量了调用方」。
    """
    for i, a in enumerate(argv):
        if not a.startswith("-"):
            return argv[:i], argv[i:]
    return argv, []


def parser() -> argparse.ArgumentParser:
    """本件自己的把握关：只有 `--doctest` 一旗（挂进 parser 是 2.69 那条：文档尺会拿
    `--help` 核对每一条写进文档的长参数）。

    >>> p = parser()
    >>> p.parse_args(["--doctest"]).doctest
    True
    >>> p.parse_args([]).doctest
    False
    """
    ap = argparse.ArgumentParser(
        prog="work_guard.py",
        description="在护栏底下跑一件脚本，报它有没有去干自己的活（本件的旗排在被量件前面）")
    add_doctest_flag(ap)
    return ap


def verdict_code(rc: int | None, found: list[str]) -> int:
    """把「被量件怎么样」和「护栏看见了什么」收成 2.62 那三档。

    >>> verdict_code(0, [])                                      # 全对且全读到
    0
    >>> verdict_code(0, ["写 /r/data/x"])                        # 它跑对了，可它动了仓库
    1
    >>> verdict_code(2, [])                                      # 它自己退 2：结果有毛病
    1
    >>> verdict_code(None, [])                                   # 根本没跑起来 = 什么都没量到
    2
    """
    if rc is None:
        return 2
    return 1 if (found or rc) else 0


def main(argv: list[str]) -> int:
    """`--doctest` 在本件的旗位上就跑本件自己的用例，否则跑被量件。

    这里故意不给 doctest：这一句是入口，要它说话得跑到屏幕上（`--each` 那一层量的就是屏幕）。
    """
    head, tail = split_at_target(argv)
    args = parser().parse_args(head)
    if args.doctest:
        return run_own(sys.modules[__name__])
    if not tail:
        print("✗ 没指名被量件。用法：work_guard.py 那件.py --doctest"
              "（本件自己的旗要排在被量件前面）", file=sys.stderr)
        return 2
    target = tail[0]
    if not pathlib.Path(target).is_file():
        print(f"✗ 被量件不存在：{target} —— 这一遍什么都没量到", file=sys.stderr)
        return 2
    rc, hits = run(target, tuple(tail[1:]))
    found = findings_of(hits)
    print(guard_line(hits, rc))
    return verdict_code(rc, found)


if __name__ == "__main__":
    rc = main(sys.argv[1:])
    raise SystemExit(rc)
