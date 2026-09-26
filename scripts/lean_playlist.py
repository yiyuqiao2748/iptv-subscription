"""把订阅表压成「裸表」：去掉台标和 EPG 声明，只留频道名 + 流地址。

用途只有一个：APTV 添加订阅失败时，判断是不是 App 在导入阶段去抓
x-tvg-url 的节目单或几十张台标图片超时导致的，而不是网络不通。

    python scripts/lean_playlist.py                    # 生成 data/output/hunan-lean.m3u
    python scripts/lean_playlist.py --in aptv.m3u --limit 5
    python scripts/lean_playlist.py --self-test        # 不问表，只问这一支还咬得动吗（种 12 格）

退码（**2.62 立的那三档**，2.65 起这一支也照同一口径）：**0** = 压出来一份非空的裸表、也写进去了；
**1** = 干成了事、但结果有毛病（压完一条线路都没有 / `--in` 与 `--out` 指的是同一个件 /
`--limit` 取了负数）；**2** = 这一跑什么都没干成（源表读不进来、或者那份东西写不出去）。

为什么这一支要单独有退码口径：它是这一树里**会写文件**的那几支之一，而「写没写成」看电视的人
查不出来。2.65 之前它一共 82 行，只挡了「源表不在」那一种（那句会印「找不到 …先跑…」，退 1）；
**四种**坏法摊的是 traceback、退码一色 1（读两种：指到目录 14 行、非 UTF-8 12 行；写两种：
目标目录不在 13 行、目标是个目录 13 行 —— 22:40:00 与 22:40:28 拿 `git archive HEAD` 那份旧件
逐种量出来的，行数是一屏的行数、不是猜的）；另有**三种**坏法穿的是「成功」那件衣服：压完是空表、
表里只有注释、`--limit` 取负，三种都照样写盘、照样印「已生成 …（0 条线路…）」、照样退 0，
磁盘上留下一份一行的空裸表（同一遍量到的）。最疼的是第四种：`--in` 与 `--out` 写成同一个件时
它**把源表原地盖掉**（那一遍实测：文件还在、7 行、`tvg-logo` 已经没了）而屏幕上是一句「已生成」。
这一支专门用来诊断「APTV 导入不动」，所以它自己说谎最疼：
拿一份空裸表去导入失败，看的人会以为问题在 App。

只 import 标准库那一条不是讲究，是依赖：`src/cli.py` 的 `load_lean_fn()` 按文件路径把这里的
`lean()` 捞进 `build`（那句 docstring 写着「只保留一份实现」），而它只对「文件不在」留了后路 ——
**顶层 import 失败是往上抛的**，而 `python -m src.cli` 跑的时候 `scripts/` 不在 `sys.path` 上。
所以借邻居（`doc_num.read_doc`、`baseline_guard.guard`）一律写在函数里面，那一格钉在
`loads_like_cli()` 的 doctest 上（它就在一个把 `scripts/` 剔掉的 `sys.path` 里 exec 本件）。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

from run_doctests import (DOCTEST_FLAG, SELF_TEST_FLAG, add_doctest_flag,   # noqa: E402
                          arg_door_answered, arg_door_exit, run_own)
# `--doctest` 那一旗的口径只有一份（§2.69）；2.79 起「这一遍答哪一扇」也只有一份

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"

_ATTR_LOGO = re.compile(r'\s+tvg-logo="[^"]*"')
_ATTR_EPG = re.compile(r'^#EXTM3U\s+x-tvg-url="[^"]*"')


def lean(text: str, *, limit: int = 0) -> str:
    """去掉台标与 EPG 声明；limit>0 时只保留前 N 个频道（含其全部线路）。

    >>> out = lean('#EXTM3U x-tvg-url="http://a/epg.gz"\\n'
    ...            '#EXTINF:-1 tvg-logo="http://l.png" group-title="g",湖南卫视\\n'
    ...            'http://s/1.m3u8\\n', limit=1)
    >>> '#EXTM3U\\n' in out and 'tvg-logo' not in out and 'x-tvg-url' not in out
    True
    """
    kept: list[str] = []
    seen: list[str] = []
    skip = False                       # 当前这条线路要不要整条丢掉
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            kept.append("#EXTM3U")
            continue
        if line.startswith("#EXTINF"):
            name = line.split(",", 1)[1] if "," in line else ""
            if limit and name not in seen:
                if len(seen) >= limit:
                    skip = True        # 已经攒够 N 个台，新台整条（含地址行）不要
                    continue
                seen.append(name)
            skip = False
            kept.append(_ATTR_LOGO.sub("", line))
            continue
        if line.startswith("#"):
            continue                   # 其它注释行（#EXTGRP 等）一并丢掉
        if skip:
            continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def n_lines(text: str) -> int:
    """这份表里有几条 `#EXTINF`（= 几条线路）。屏幕上那句「N 条线路」数的是它。

    >>> n_lines('#EXTM3U\\n#EXTINF:-1 a,湖南卫视\\nhttp://s/1\\n#EXTINF:-1 b,湖南卫视\\nhttp://s/2\\n')
    2
    >>> n_lines('#EXTM3U\\n')
    0
    """
    return sum(1 for line in text.splitlines() if line.startswith("#EXTINF"))


def same_file(a: Path, b: Path) -> bool:
    """两个路径指的是不是同一个件 —— 允许其中一个是「还没打算存在」的（那种不可能相等）。

    为什么不比字符串：`--in ./x.m3u --out x.m3u`、`--out ./子/../x.m3u` 写法不同、是同一个件，
    而那正是会把源表盖掉的一种。为什么不 `resolve()` 就完事：`strict=False` 在 3.6+ 才默认宽松，
    而这里连"路径不存在"都不该抛 —— 那一档由 `read_doc` 说人话。

    >>> import pathlib as _p
    >>> same_file(_p.Path("/x/a.m3u"), _p.Path("/x/a.m3u"))
    True
    >>> same_file(_p.Path("/x/a.m3u"), _p.Path("/x/b.m3u"))
    False
    """
    try:
        return a.resolve() == b.resolve()
    except OSError:                    # 极端坏路径：认不出就当不重合，让后面那步去说为什么
        return False


def why_cant_write(dst: Path, e: OSError) -> str:
    """写不出去的那一句为什么：三种 `OSError` 三种修法，不许洗成同一句「写失败」。

    >>> from errno import ENOENT
    >>> why_cant_write(Path("/x/y.m3u"), FileNotFoundError(ENOENT, "no such file"))
    '那个目录不在（这一支不替你建目录）'
    >>> why_cant_write(Path("/x/y.m3u"), PermissionError(13, "denied"))
    '那个地址不让写'
    >>> why_cant_write(Path("/x/y.m3u"), IsADirectoryError(21, "is a directory"))
    '那是一个目录，不是文件'
    >>> why_cant_write(Path("/x/y.m3u"), OSError(28, "no space"))     # 第四种：不认识的说原文
    '写不下去：OSError(28)：no space'

    最后一格不抄 `str(OSError)` 整串（不同解释器对它的拼法不一样，钉死它等于把用例绑在版本上），
    也不带 `dst`（那是调用那一行印的）；这一档要的只是**它不冒充前面那三种**。
    """
    if isinstance(e, FileNotFoundError):
        return "那个目录不在（这一支不替你建目录）"
    if isinstance(e, PermissionError):
        return "那个地址不让写"
    if isinstance(e, IsADirectoryError):
        return "那是一个目录，不是文件"
    return f"写不下去：{type(e).__name__}({e.errno})：{e.strerror}"


def resolve_io(src_arg: str, dst_arg: str) -> tuple[Path, Path]:
    """把那两个参数换成真路径：相对名字算在 `data/output/` 底下，绝对路径原样认。

    为什么单独一层：2.65 之前只有 `--in` 走 `OUT_DIR / args.src`，`--out` 也一样拼 ——
    pathlib 拼绝对路径时后者赢，所以「给绝对路径」今天碰巧能用，但它是**巧合不是行为**，
    而基线那一套沙盒全靠绝对路径（不碰真的 `data/output/`）。这一层把巧合写成行为。

    >>> src, dst = resolve_io("hunan.m3u", "")
    >>> src.name, dst.name
    ('hunan.m3u', 'hunan-lean.m3u')
    >>> src, dst = resolve_io("/tmp/g/表.m3u", "/tmp/g/裸.m3u")
    >>> str(src), str(dst)
    ('/tmp/g/表.m3u', '/tmp/g/裸.m3u')
    >>> resolve_io("/tmp/g/表.m3u", "隔壁.m3u")[1].parent.name
    'output'
    """
    src = Path(src_arg)
    src = src if src.is_absolute() else OUT_DIR / src
    if dst_arg:
        return src, Path(dst_arg) if Path(dst_arg).is_absolute() else OUT_DIR / dst_arg
    return src, src.parent / f"{src.stem}-lean.m3u"


def already_under_output(src_arg: str) -> bool:
    """那个 `--in` 是不是自己已经带了 `data/output/` —— 相对名字是**从那张表底下**算的，会拼两遍。

    为什么单管这一种：22:20:55 拿 `--in data/output/aptv.m3u` 真跑了一遍，屏幕上印的是
    `.../data/output/data/output/aptv.m3u —— 文件不在`。这不算判错（它确实不在），但那个仓库根
    相对写法是**照着别的支的手册抄过来最自然的一种**（`verify_lines.py` 就收仓库根相对路径），
    而这一树的路径里带空格，那半截重复在人眼里根本跳不出来 —— 于是人去翻 `data/output/`，
    翻不到那个文件，然后怀疑表没建。这一档不改路径、不多读一次盘，只是**把已经踩到的坑说破**。

    >>> already_under_output("data/output/aptv.m3u")
    True
    >>> already_under_output("./data/output//aptv.m3u")
    True
    >>> already_under_output("aptv.m3u")
    False
    >>> already_under_output("/tmp/g/data/output/aptv.m3u")     # 绝对路径：不拼，也就不重复
    False
    """
    p = Path(src_arg)
    if p.is_absolute():
        return False
    parts = [seg for seg in p.parts if seg not in (".", "")]
    return tuple(parts[:2]) == ("data", "output")


def outcome(read_why: str, write_why: str, kept_lines: int) -> tuple[int, str]:
    """这一跑退几、那句话怎么说 —— 纯函数，为的是这一档能当场对（2.62 的三档）。

    `read_why`／`write_why` 是 `doc_num.read_doc` 与写盘那一步回来的「为什么」（空串 = 没事）。

    >>> outcome("", "", 3)
    (0, '')
    >>> outcome("那是个目录，不是文档", "", 0)
    (2, '源表读不进来')
    >>> outcome("", "那个目录不在（这一支不替你建目录）", 0)
    (2, '没写出去')
    >>> outcome("", "", 0)
    (1, '压完是空的')

    **读那一档优先**，而且这不是随口排的：读不进来时压根走不到写，`write_why` 必然是空的；
    反过来「读到了、写不出去」是真会同时只剩一个的，所以先问读、再问写、最后才问那个 0。
    三种各说各话就是这一支的全部目的 —— 2.65 之前这四种坏法**共用一个退码 1**，
    其中「什么都没干成」那两种还穿着 traceback。
    """
    if read_why:
        return 2, "源表读不进来"
    if write_why:
        return 2, "没写出去"
    if not kept_lines:
        return 1, "压完是空的"
    return 0, ""


def loads_like_cli() -> str:
    """像 `src/cli.py:load_lean_fn()` 那样按文件路径把本件捞一遍，返回那句为什么（`""` = 没事）。

    为什么要有这一格：cli 那一处 `exec_module` 只对「文件不在」留了后路，**顶层 import 抛出来
    会把整条 `build` 打断** —— 而它跑的时候 `scripts/` 不在 `sys.path` 上（`python -m src.cli`
    的 `sys.path[0]` 是仓库根）。所以本件的顶层只许 import 标准库。这一条以前只是「我知道」，
    2.65 把它写成一个函数、由下面那两行 doctest 钉住：哪天有人在顶层加一句 `from doc_num import …`，
    红的是这条 doctest，而不是用户那一次 `build`。

    >>> loads_like_cli()
    ''
    >>> "顶层 import 只能引标准库" if loads_like_cli() else "本件在裸 sys.path 下能 exec，且 lean 可用"
    '本件在裸 sys.path 下能 exec，且 lean 可用'
    """
    import importlib
    import importlib.util

    saved = list(sys.path)
    try:
        sys.path[:] = [p for p in sys.path if Path(p).name != "scripts"]
        spec = importlib.util.spec_from_file_location("lean_playlist_bare", Path(__file__))
        if spec is None or spec.loader is None:
            return "本件连 spec 都取不出来"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)              # 顶层 import 失败就在这一行抛
    except Exception as e:                        # noqa: BLE001 - 要的就是「抛了」这一件事
        return f"{type(e).__name__}: {e}"
    finally:
        sys.path[:] = saved
    return "" if callable(getattr(mod, "lean", None)) else "捞回来的件里没有可调用的 lean()"


# ———————————————————————————— 下面这一整块是「量这一支自己」的基线（2.65） ————————————————————————————

HEADER = '#EXTM3U x-tvg-url="https://e.erw.cc/e.xml.gz"\n'
BODY_2CH = (HEADER
            + '#EXTINF:-1 tvg-logo="http://l/1.png" group-title="g",湖南卫视\nhttp://a/1.m3u8\n'
            + '#EXTINF:-1 tvg-logo="http://l/2.png" group-title="g",湖南卫视\nhttp://a/2.m3u8\n'
            + '#EXTINF:-1 tvg-logo="http://l/3.png" group-title="g",CCTV-10科教\nhttp://b/3.m3u8\n')
NON_UTF8 = b"#EXTM3U\n" + bytes([0x80, 0x81, 0x41])

FIXTURES: tuple[tuple[str, str], ...] = (
    ("好表.m3u", BODY_2CH),
    ("空表.m3u", ""),
    ("注释表.m3u", "#EXTM3U\n#EXTGRP:g\n"),
    ("源表.m3u", BODY_2CH),                   # 壬格拿来验「同一个件」，它必须一字不差地活着
)


class Cell(NamedTuple):
    """一格基线：沙盒里种什么、用什么参数问它、期望屏幕上出现什么、不许出现什么。

    与 `epg_check` 那一套同名同义，只多两格**对磁盘**的判据：这一支是会写文件的，
    「屏幕上说了人话」与「磁盘上真没动」是两件事 ——

    * `absent`：跑完之后这些件**不许存在**（那些「什么都没干成」的档，最要紧的一条就是别留下半成品）；
    * `keep`：跑完之后这些件必须还是这个内容（壬格拿它钉「源表没被盖掉」）。
    """
    who: str
    what: str
    rc: int
    files: tuple[tuple[str, str], ...] = ()
    dirs: tuple[str, ...] = ()
    bins: tuple[str, ...] = ()
    argv: tuple[str, ...] = ()
    has: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()
    once: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    keep: tuple[tuple[str, str], ...] = ()


def argv_io(*rest: str, src: str = "好表.m3u", dst: str = "出.m3u") -> tuple[str, ...]:
    """拼一格用的 argv。`src`／`dst` 做成**关键字**参数（`epg_check` 那一遍踩过的位置参数坑）。

    >>> print(" ".join(argv_io()))
    --in {T}/好表.m3u --out {T}/出.m3u
    >>> print(" ".join(argv_io("--limit", "1", dst="两份.m3u")))
    --in {T}/好表.m3u --out {T}/两份.m3u --limit 1
    """
    return ("--in", f"{{T}}/{src}", "--out", f"{{T}}/{dst}", *rest)


BASELINE: tuple[Cell, ...] = (
    # ———— 甲／子：两种常态读数（全压、只压第一个台），退的都是 0 ————
    Cell("甲_正常压一张表", "常态：三个台压完还是三个台，退 0 且那句印的是**写进去的**份数",
         0, argv=argv_io(),
         has=("已生成 <T>/出.m3u（3 条线路，无台标、无 EPG 声明）",),
         lacks=("Traceback", "没有写", "tvg-logo", "x-tvg-url")),
    Cell("子_limit只留第一个台", "`--limit 1` 留的是**台**：第一个台的两条线路都该在",
         0, argv=argv_io("--limit", "1", dst="裸-限1.m3u"),
         has=("已生成 <T>/裸-限1.m3u（2 条线路，无台标、无 EPG 声明）",),
         lacks=("Traceback", "CCTV-10科教", "没有写")),
    # ———— 乙／丙：读进来了、压完是空的。2.65 之前这两格都写盘、都印「已生成…0 条」、都退 0 ————
    Cell("乙_源表是空的", "0 字节的表：那不是「生成了 0 条线路的裸表成功」，是没干成事",
         1, argv=argv_io(src="空表.m3u"),
         has=("没有写", "压完一条线路都没有"),
         lacks=("已生成", "Traceback"), absent=("出.m3u",)),
    Cell("丙_只有注释没有一个台", "表不是空文件、可读进来一个 `#EXTINF` 都没有：同一种坏法",
         1, argv=argv_io(src="注释表.m3u"),
         has=("压完一条线路都没有",), lacks=("已生成", "文件不在", "Traceback"),
         absent=("出.m3u",)),
    # ———— 丁／戊／己：源表读不进来。三种说法只有一份（借 `doc_num.read_doc`），退的都是 2 ————
    Cell("丁_源指到目录", "`--in` 指到目录：2.65 之前摊 `IsADirectoryError` 整段 traceback、退 1",
         2, dirs=("子目录",), argv=argv_io(src="子目录"),
         has=("源表读不进来：<T>/子目录 —— 那是个目录，不是文档",),
         lacks=("Traceback", "IsADirectoryError", "已生成", "文件不在"),
         absent=("出.m3u",)),
    Cell("戊_源不是UTF-8", "第二种：改个名没用，所以那句也不许写成「那是个目录」",
         2, bins=("坏码.m3u",), argv=argv_io(src="坏码.m3u"),
         has=("源表读不进来：<T>/坏码.m3u —— 读不出来：",),
         lacks=("那是个目录", "文件不在", "Traceback", "UnicodeDecodeError", "已生成"),
         absent=("出.m3u",)),
    Cell("己_源根本不在", "第三种（2.65 之前唯一会说人话的一格）：退码从 1 挪到 2，因为它什么都没量到",
         2, argv=argv_io(src="没这个.m3u"),
         has=("源表读不进来：<T>/没这个.m3u —— 文件不在", "先跑"),
         lacks=("那是个目录", "读不出来：", "Traceback", "还有另一种可能"), absent=("出.m3u",)),
    Cell("寅_in自己带了目录前缀", "相对名字是从 data/output/ 底下算的，再带一段就拼成两遍（22:20:55 真踩到）",
         2, argv=("--in", "data/output/没这个.m3u", "--out", "{T}/出.m3u"),
         has=("而给出的那个自己已经带了这一段（data/output/没这个.m3u）",
              "写成 `--in 没这个.m3u` 或直接给绝对路径"),
         lacks=("那是个目录", "读不出来：", "Traceback", "已生成"), absent=("出.m3u",)),
    # ———— 庚／辛：读到了、写不出去。修法与「读不进来」两回事，所以各说各话 ————
    Cell("庚_out指到没有的目录", "写在最后一刻塌掉：这一支不替你建目录，但要说清是没建",
         2, argv=argv_io(dst="没有的目录/出.m3u"),
         has=("写不出去：<T>/没有的目录/出.m3u —— 那个目录不在",),
         lacks=("FileNotFoundError", "Traceback", "已生成", "源表读不进来")),
    Cell("辛_out指的是个目录", "同一档第二种：`--out` 写成了一个已经存在的目录名",
         2, dirs=("出.m3u",), argv=argv_io(),
         has=("写不出去：<T>/出.m3u —— 那是一个目录，不是文件",),
         lacks=("IsADirectoryError", "Traceback", "已生成", "那个目录不在")),
    # ———— 壬／丑：用法本身有毛病。这两格退 1（干了、但那一跑不该干），一格都不许碰磁盘 ————
    Cell("壬_in与out同一个件", "以前这一格会把源表**原地盖掉**（台标与节目单声明全没），还退 0",
         1, argv=argv_io(src="源表.m3u", dst="源表.m3u"),
         has=("--in 与 --out 指的是同一个件",),
         lacks=("已生成", "Traceback", "源表读不进来"),
         keep=(("源表.m3u", BODY_2CH),)),
    Cell("丑_limit是负数", "`--limit -1` 以前的效果是「一个台都不留」而屏幕上看不出来",
         1, argv=argv_io("--limit", "-1"),
         has=("--limit 取到 -1",),
         lacks=("已生成", "压完一条线路都没有", "Traceback"), absent=("出.m3u",)),
)


def run_cell(cell: Cell, base: Path) -> tuple[str, str, str]:
    """把一格种进一个**新**沙盒、跑真的 `main()`，回来对屏幕**和对磁盘**。

    对磁盘这一半是这一支独有的：它写文件，所以「说了人话」不等于「没留下东西」——
    那两种坏法（该没写的没写、该活着的活着）屏幕上一样好看。
    """
    from doc_num import hide_tmp, read_doc            # 只在函数里借：见模块开头那段

    for rel, body in FIXTURES + tuple(cell.files):
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body.replace("{T}", str(base)), encoding="utf-8")
    for rel in cell.dirs:
        (base / rel).mkdir(parents=True, exist_ok=True)
    for rel in cell.bins:
        (base / rel).write_bytes(NON_UTF8)
    argv = [a.replace("{T}", str(base)) for a in cell.argv]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
    except Exception as e:                            # noqa: BLE001 - 尺自己炸了不许冒充「没过」
        return "bad", f"跑这一格时抛了 {type(e).__name__}: {e}", ""
    text = hide_tmp(buf.getvalue(), base)
    good, why = check_cell(cell, rc, text)
    if good:                                          # 屏幕对了才轮到磁盘：错了先说屏幕
        good, why = check_disk(cell, base)
    return ("ok", "", text) if good else ("bad", why, text)


def check_cell(cell: Cell, rc: int, text: str) -> tuple[bool, str]:
    """这一格对上了没有：退码、该出现的句子、不该出现的句子、只许出现一次的句子。"""
    if rc != cell.rc:
        return False, f"退码：期望 {cell.rc}，实际 {rc}"
    for s in cell.has:
        if s not in text:
            return False, f"屏幕上没有那句：{s}"
    for s in cell.lacks:
        if s in text:
            return False, f"多说了那句：{s} —— 误伤"
    for s in cell.once:
        if text.count(s) != 1:
            return False, f"那句出现了 {text.count(s)} 次，期望恰好 1 次：{s}"
    return True, ""


def check_disk(cell: Cell, base: Path) -> tuple[bool, str]:
    """跑完之后磁盘对不对：`absent` 那些件不许存在，`keep` 那些件必须还是原样。"""
    from doc_num import read_doc                      # 同 `run_cell`：只有一份读法
    for rel in cell.absent:
        if (base / rel).exists():
            return False, f"这一档什么都没干成，磁盘上却留下了 {rel}"
    for rel, want in cell.keep:
        got, why = read_doc(base / rel)
        if got != want:
            return False, f"{rel} 被改过了（{why or '内容不同'}）：期望原样留着"
    return True, ""


def sloppy_cells(cells: tuple[Cell, ...]) -> list[str]:
    """格子自己写歪的地方（占位符串错位、同一句又 `has` 又 `lacks`、一句都没钉）。"""
    out: list[str] = []
    for c in cells:
        if any("{T}" in s for s in c.has + c.lacks + c.once):
            out.append(f"{c.who}：`has` 里写了 `{{T}}`，argv 才用这个占位符，"
                       "屏幕上的路径要写 `<T>`")
        if set(c.has) & set(c.lacks):
            out.append(f"{c.who}：同一句既是 `has` 又是 `lacks`，这一格永远不可能过")
        if not (c.has or c.lacks or c.once):
            out.append(f"{c.who}：这一格一句都没钉，只比退码 —— 那是「跑过一遍」不是「量过一件事」")
        if set(c.absent) & {rel for rel, _ in c.keep}:
            out.append(f"{c.who}：同一个件又 `absent` 又 `keep`，磁盘上那一半永远不可能过")
    return out


def self_test(cells: tuple[Cell, ...] | None = None) -> int:
    """`--self-test`：每格一个**新**沙盒，逐格对期望（屏幕 ＋ 磁盘）。

    退码：0 = 每格都符合期望；1 = 有格子不符（逐格点名）；2 = 一格都没跑起来，或基线自己写歪了。
    """
    from baseline_guard import guard as guard_names

    cells = BASELINE if cells is None else cells
    bad_names = guard_names([c.who for c in cells])
    if bad_names:
        print(bad_names)
        return 2
    sloppy = sloppy_cells(cells)
    if sloppy:
        print("基线自己有格子写歪了，改的是基线、不是判据：\n  " + "\n  ".join(sloppy))
        return 2
    ran = bad = 0
    fails: list[tuple[Cell, str, str]] = []
    for cell in cells:
        with tempfile.TemporaryDirectory(prefix="lean-playlist-selftest-") as td:
            verdict, why, text = run_cell(cell, Path(td))
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
          + (" —— 那把尺还咬得动" if ran and not bad else " —— 上面逐格点名了"))
    if bad:
        print("不符的格：" + "、".join(c.who for c, _, _ in fails))
    if not ran:
        print("一格都没跑起来：临时目录建不起来。这不算过")
        return 2
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成不带台标/EPG 的裸订阅表")
    ap.add_argument("--in", dest="src", default="hunan.m3u",
                    help="压哪张表（相对 data/output/，也可以给绝对路径）")
    ap.add_argument("--out", dest="dst", default="",
                    help="写到哪（默认 <源表名>-lean.m3u；不许与 --in 同一个件）")
    ap.add_argument("--limit", type=int, default=0, help="只保留前 N 个频道，0=全部")
    ap.add_argument("--self-test", action="store_true",
                    help="不问表，只问这一支自己还咬得动吗：往临时沙盒里种基线那 12 格，逐格对")
    add_doctest_flag(ap)
    args = ap.parse_args(argv)
    door_rc = arg_door_exit(args)      # 2.79：两扇一起递时不再静默，那句门口话与收集器同一份
    if door_rc is not None:
        return door_rc
    answered = arg_door_answered(args)

    if answered == DOCTEST_FLAG:
        return run_own(sys.modules[__name__])   # 2.69：先答说明书，一张表都不读
    if answered == SELF_TEST_FLAG:
        return self_test()

    src, dst = resolve_io(args.src, args.dst)

    # —— 先问用法，再碰磁盘：`--limit` 取负以前是「安静地什么都不留」，
    #    而 `--in` 与 `--out` 同一个件以前会把源表原地盖掉 —— 这两件都不该等到读完了才发现。
    if args.limit < 0:
        print(f"--limit 取到 {args.limit}：这一档留的是「前 {args.limit} 个台」，"
              f"那就是一个台都不留。要全部就别加这个参数（0 = 全部）", file=sys.stderr)
        return 1
    if same_file(src, dst):
        print(f"--in 与 --out 指的是同一个件（{src}）：这一支的全部用处是从那张表**另压一份**，"
              "照这么写会把源表原地盖成裸表（台标与节目单声明都会没）。换一个 --out。",
              file=sys.stderr)
        return 1

    from doc_num import read_doc                      # 只有一份读法（2.44 立的规矩）

    text, read_why = read_doc(src)
    rc, _ = outcome(read_why, "", 0)
    if read_why:
        print(f"源表读不进来：{src} —— {read_why}；没有压、也没有写任何东西。", file=sys.stderr)
        if read_why == "文件不在":
            print("   这一支不负责出表：先跑 python -m src.cli build 把 data/output/ 里那几张表建起来",
                  file=sys.stderr)
            if already_under_output(args.src):
                print(f"   还有另一种可能：`--in` 收的相对名字是**从 data/output/ 底下**算的，"
                      f"而给出的那个自己已经带了这一段（{args.src}），拼出来就成了两遍。"
                      f"写成 `--in {Path(args.src).name}` 或直接给绝对路径", file=sys.stderr)
        return rc

    out = lean(text or "", limit=args.limit)
    kept = n_lines(out)
    # 压完一条线路都没有：**一行盘都没写过**就退。这一支最不该留下的是那份空裸表 ——
    # 2.65 之前它先 `write_text` 再 `unlink`，中间那一下被 Ctrl-C 或被别的进程拿着，
    # 磁盘上就是一份长得像成功的空表；「什么都没干成」那一档不该在磁盘上留过任何东西。
    if not kept:
        rc, _ = outcome("", "", kept)
        print(f"压完一条线路都没有（读进来 {len(text.splitlines())} 行，压完只剩表头那一行）："
              f"没有写 {dst} —— 拿一张空表去试 APTV 导入，"
              "只会看不出是 App 的问题还是表的问题", file=sys.stderr)
        return rc

    write_why = ""
    try:
        dst.write_text(out, encoding="utf-8")
    except OSError as e:
        write_why = why_cant_write(dst, e)
    rc, _ = outcome("", write_why, kept)
    if write_why:
        print(f"写不出去：{dst} —— {write_why}", file=sys.stderr)
        return rc
    # 那句「N 条线路」数的是**内存里刚压出来那份**，不是回头再读一遍磁盘（2.65 拆掉的第二处裸读：
    # 同一个数、少一次 IO、少一个崩口）。
    print(f"已生成 {dst}（{kept} 条线路，无台标、无 EPG 声明）")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
