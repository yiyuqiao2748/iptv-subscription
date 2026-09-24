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

用法：

    .venv/bin/python scripts/stray_names.py                 # 扫本仓库（含 .git/）
    .venv/bin/python scripts/stray_names.py --root /tmp/x    # 扫另一棵树（量具、沙盒用）
    .venv/bin/python scripts/stray_names.py --all            # 连「只提醒」那一档也逐条列出来
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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


def find_bad(root: Path) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]], int]:
    """扫一棵树：`(拦得住的[(相对路径, 档说明, 在不在 git 名单里)], 只提醒的, 扫过的名字总数)`。

    相对路径按 `root` 算；`git ls-files` 只在 `root` 是个 git 仓库时问一次，问不动就当不在。
    符号链接指向的目录**不进去**（`.venv/bin/python` 那种链到别处的东西，扫它等于扫别人的仓库），
    但**链子自己的名字照样判** —— 那个名字是这个仓库里的目录项，只是它背后那棵树不是。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as td:
    ...     t = Path(td) / "tree"
    ...     far = Path(td) / "far"
    ...     _ = t.mkdir(); _ = far.mkdir()
    ...     _ = (far / "别人的仓库 2.py").write_text("x", encoding="utf-8")
    ...     _ = (t / "good.py").write_text("x", encoding="utf-8")
    ...     _ = (t / "cache 2").symlink_to(far, target_is_directory=True)
    ...     bad, note, n = find_bad(t)
    ...     ([b[0] for b in bad], n)
    (['cache 2'], 2)
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as td:
    ...     t = Path(td)
    ...     _ = (t / "计划书 2.md").write_text("x", encoding="utf-8")
    ...     _ = (t / "湖南 卫视.m3u").write_text("x", encoding="utf-8")
    ...     _ = (t / "good.py").write_text("x", encoding="utf-8")
    ...     bad, note, n = find_bad(t)
    ...     ([b[0] for b in bad], [x[0] for x in note], n)
    (['计划书 2.md'], ['湖南 卫视.m3u'], 3)
    >>> find_bad(Path("/nonexistent-path-for-doctests"))
    ([], [], 0)
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
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # 链到别处的目录：名字留着判（它是本仓库的一个目录项），背后那棵不进（见 docstring）
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        dirnames[:] = [d for d in dirnames if d not in links]
        rel_dir = os.path.relpath(dirpath, root)
        for name in list(dirnames) + links + filenames:
            total += 1
            rel = name if rel_dir == "." else os.path.join(rel_dir, name)
            tier, why = classify(name)
            if tier == RED:
                in_git = "在 `git ls-files` 的名单里（已经提交进去了）" if rel in tracked else ""
                bad.append((rel.replace(os.sep, "/"), why, in_git))
            elif tier == NOTE:
                note.append((rel.replace(os.sep, "/"), why))
    return sorted(bad), sorted(note), total


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stray_names.py",
                                 description="只看文件名的闸：同步盘冲突副本与看不出来的空白")
    ap.add_argument("--root", default=str(ROOT),
                    help="扫哪棵树（默认本仓库；量具与沙盒指别处）")
    ap.add_argument("--all", action="store_true", help="连「只提醒」那一档也逐条列出来")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"✗ {root} 不是个目录 —— 这一轮什么都没量", file=sys.stderr)
        return 2
    bad, note, n_total = find_bad(root)
    if not n_total:                       # 空目录：结论那行是「没量」，得有一行 ✗ 配得上它
        print(f"✗ {root} 底下一个名字都没有 —— 这一轮什么都没扫，不算通过")
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
    print()
    print(summary(n_total, bad, note, root))
    if not n_total:
        return 2                                        # 一个名字都没扫到 = 没量，不是量干净了
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
