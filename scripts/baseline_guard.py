"""几把「基线尺」共用的一道小闸：格子名不许带顿号或换行（计划书 §2.58）。

为什么单独一个文件：基线的最后一行长这样 —— 「不符的格：B1_数写错、B7_混合格」。
它用 `、".join(...)` 拼，**顿号就是那一行的分隔符**，所以名字里带顿号的格子会让那一行
自己分不开。13:47 那遍（计划书 §2.57 踩的第 2 条）被自己咬过一口：一格名字里有一颗顿号，
读输出的脚本把一格数成两格，那一轮「判错 3 处」里有一处是这件事。

那时候只有命令尺装了这道闸，`stray_names`（§2.56 那 15 格）没有 —— 它今天名字干净是**巧合**，
不是闸。这一节把第三种读法（`doc_num` 那一档）加进来时，顺手把闸挪到共用的地方：
三把尺都问一句，别各写一份、也别让下一把尺再抄一遍注释。

    ./.venv/bin/python -X utf8 scripts/baseline_guard.py     # 跑它自己的用例

退码（2.68 起按那三档）：**0** = 收到的用例全过；**1** = 有用例失败；
**2** = 一条用例都没收到 —— 这一档以前退 0，屏幕上还是 0 字节，跟「全过」同形。
"""
from __future__ import annotations

from typing import Iterable, Sequence

SEPARATOR = "、"


def sep_names(names: Iterable[str]) -> list[str]:
    """挑出带了分隔符或换行的格子名（原样返回，顺序不变）。

    >>> sep_names(["B1_数写错", "B2_混合格"])
    []
    >>> sep_names(["B1_好", "B2_坏、带顿号"])
    ['B2_坏、带顿号']
    >>> sep_names(["带\\n换行"])
    ['带\\n换行']
    >>> sep_names([])                                   # 空的进、空的出：不替你报错
    []
    """
    return [n for n in names if SEPARATOR in n or "\n" in n]


def guard(names: Sequence[str], label: str = "格子名") -> str | None:
    """把上面那一句变成一句人话；干净时返回 `None`，让调用方继续往下跑。

    返回值就是要印出去的那一行 —— **谁**起的名字、为什么不许，都写在里面。
    点名那些名字时用「／」而不是顿号：这一句自己也在数同一件事，
    用顿号分就又是同一个病。

    >>> guard(["B1_数写错", "B7_混合格"]) is None
    True
    >>> guard(["B1_好", "坏、名"], label="文档名")
    '文档名里不许有顿号或换行：那一行「不符的格」靠顿号分，分不开等于没有 —— 坏、名'
    >>> guard(["甲、坏", "乙\\n坏"])
    '格子名里不许有顿号或换行：那一行「不符的格」靠顿号分，分不开等于没有 —— 甲、坏／乙\\n坏'
    """
    hit = sep_names(names)
    if not hit:
        return None
    return (f"{label}里不许有顿号或换行：那一行「不符的格」靠顿号分，"
            f"分不开等于没有 —— {'／'.join(hit)}")


if __name__ == "__main__":
    # 这两个 import 为什么写在块里而不是顶上：`baseline_guard` 是被别人 import 的那一个
    # （命令尺、数尺、报数尺都 import 它），顶上一个邻居都不认才干净。
    # 2.68 之前这里是 `raise SystemExit(doctest.testmod(verbose=False).failed)`：
    # 跑掉 7 条用例、印 0 字节、退 0 —— 和「一条都没收到」完全同形。
    # 顶上那两个 import（`doctest`、`sys`）跟着这一支一起搬进来了：`sys` 本来就没别处在用。
    import sys

    from run_doctests import run_own
    raise SystemExit(run_own(sys.modules["__main__"]))
