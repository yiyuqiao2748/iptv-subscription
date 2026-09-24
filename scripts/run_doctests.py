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
"""

from __future__ import annotations

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


def main(argv: list[str]) -> int:
    for p in (str(ROOT), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)

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
        flag = "✗" if result.failed else "·"
        print(f"{flag} {name:<24} {result.attempted} 个用例"
              + (f"，失败 {result.failed}" if result.failed else ""))

    if attempted == 0:
        print("\n✗ 收集到 0 个用例 —— 这不算通过，八成是遍历写歪了。")
        return 1
    print(f"\n合计 {attempted} 个用例，{failed} 个失败（{len(names)} 个模块）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
