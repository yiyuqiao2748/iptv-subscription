#!/usr/bin/env python3
"""文档里写下来的命令行与脚本名 —— 还能不能照抄。只跑 `--help`，不做任何实测、不写任何产物。

    .venv/bin/python scripts/check_doc_cmds.py            # 扫默认那两份文档
    .venv/bin/python scripts/check_doc_cmds.py --verbose  # 连每条命令的判定一起打印

为什么值得有这样一个东西：这个项目的失效模式里有一条是「文档说 A、代码做 B」
（计划书 2.19 收口补的三件小事就是为了堵它）。而**能照抄执行的命令行**是文档里最容易漂的一层：
改一个 flag 名，用例照样全绿、报告照样能出，只有照着文档敲命令的人会撞在 `unrecognized arguments` 上。
2026-09-22 加 `--replay` 之后这条尤其现实 —— 计划书 §14 和接入文档里各有一份命令清单，
往后每加一个开关都要跟着改两处，人总会漏。

它查两层：
  * 命令层 —— 长参数（`--xxx`）在不在 `--help` 里、那个脚本 / 子命令还存在吗；
  * 引用层 —— 正文里出现的 `scripts/xxx.py` 名字（哪怕在句子里、不在命令块里）到底有没有这个文件。

例外的写法：一段文字想拿**错的**命令当例子（2.21 讲那个「打错子命令也退 0」的坑时就得写出
`src.cli bulid`），用 `<!-- check-doc-cmds: off -->` / `on` 把那段圈起来 —— 渲染出来看不见，
总结行也会写明有几段被圈掉了，不让这个口子悄悄吞掉整篇文档。

位置参数、参数的取值对不对，它不管 —— 那类漂移要靠用例，不靠这把尺。

退码：**0** = 扫到的每一条都没问题；**1** = 有对不上的；**2** = **一条都没扫到**
（2.32 补的那一格：文档被清空、文件名给错、版式改了让正则落空，三种都是这把尺自己瞎了，
不能让「扫了 0 条、0 条对不上」冒充「查过了、没问题」）。
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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

    没有配对的 `on` 就挖到文末 —— 文档里漏写收尾标记，后果是「这一段以后不查了」，
    而不是「凭空冒出一堆错」；所以数量会在总结里报出来，不能悄悄吞掉。

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
    refs: set[str] = set()
    for doc in paths:
        raw = (ROOT / doc).read_text(encoding="utf-8") if not doc.is_absolute() \
            else doc.read_text(encoding="utf-8")
        skipped += raw.count(SKIP_OFF)
        text = strip_skipped(raw)
        refs |= script_refs(text)
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

    # 引用层：这一层不看命令，只看「文档里提到的脚本文件在不在」。
    # 一个名字可能两层都报（命令里写错、句子里也写错），所以两层的数分开列、不合并成一句。
    scripts = {p.name for p in (ROOT / "scripts").glob("*.py")}
    dead = dead_refs(refs, scripts)
    for name in dead:
        print(f"文档里写了 scripts/{name}，但 scripts/ 里没有这个文件"
              "（打错了还是删了没改文档？）")
    if args.verbose:
        for name in undocumented(scripts, refs):
            print(f"    scripts/{name} 存着，但 {'、'.join(str(p) for p in paths)} 里没提过")
        for d, no, why in miss:
            print(f"    没认出来：{d}:{no}  {why}")
    # 「哪支脚本没进文档」只有把**全套**文档一起扫才有意义：单扫一份的话
    # 另外几份里提到过的一律会被误报成没人知道，那条提醒就成噪音了。
    hidden = undocumented(scripts, refs) if not args.docs else []
    tail = (f"；还有 {len(miss)} 行写了 python 却没认成命令，一条都没查 —— 见 --verbose" if miss
            else "；该查的都查了" if n else "；这一轮一条都没扫到，上面那些 0 全是空的")
    print(f"\n扫了 {n} 条命令、{len(refs)} 个脚本名：{bad} 条命令、{len(dead)} 个脚本名对不上"
          + (f"（另有 {skipped} 段标了 off 的例子没查）" if skipped else "")
          + tail)
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
    return 1 if (bad or dead) else 0


if __name__ == "__main__":
    sys.exit(main())
