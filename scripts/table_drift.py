"""回答一句话：`report.md` 说的那张表，还是不是电视上正在订阅的那张表。

为什么要有这个检查（计划书 2.27）：报告里的「第一线主机集中度」和「换第二条线路救得回来吗」
都只描述**它生成时那张表**。而 `data/output/aptv.m3u` 是订阅进电视的那一份 ——
我改了排序、换了节目单对账、上游抽风之后重出一遍，报告读起来仍然像在同一张表上说话。
2.26 那天为了确认这件事，手工 `diff` 了一次（结论：线路序列逐字节相同，差异全在 `tvg-id`），
一次性的手工比对不构成保障 —— 同样的问题值得随时能问第二遍。

它不生成任何东西：**只读两份已经存在的表**。所以标准用法是两行，
第二行的 `/tmp/r226` 由第一行产出（`--replay` 本轮不联网测任何东西，产物另指，
`data/output/` 一个字都不动）：

    ./.venv/bin/python -X utf8 -m src.cli build --replay --out /tmp/r226
    ./.venv/bin/python -X utf8 scripts/table_drift.py --against /tmp/r226

同一套东西顺手还能答另一问：**试播包旧没旧**（它是从那张表派生出来的）。
先 `probe_pack.py --in /tmp/r226/aptv.m3u --out /tmp/p227/probe-pack.m3u` 从重出那份表再跑一遍包，然后：

    ./.venv/bin/python -X utf8 scripts/table_drift.py --against /tmp/p227 --files probe-pack.m3u

退出码：**0 = 两张表是同一张表**（线路级一字不差）；**1 = 换表了**，
并把换了谁点名（第一线换了算最重，台多了/少了次之，只动第 2、3 条线再次之）；
2 = 一张都没比成或参数不对 —— 跳过的那些**不算一致**，「全跳过 + 报绿」是这种检查最坏的失败方式。
属性差异（`tvg-id`、`tvg-logo`、头部那行节目单地址）**不算换表**，
但一定写出来：它解释的是「那几百行 diff 到底是什么」，不是可以忽略的噪声。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from probe_pack import channel_groups                        # noqa: E402


def diff_tables(a: list[tuple[str, list[str]]],
                b: list[tuple[str, list[str]]]) -> dict:
    """两张表按「台名顺序 + 每台的线路序列」比，只答一件事：线路级换没换。

    为什么按位置比而不是按台名建索引：同名不同 id 的两个桶在电视上是两个台
    （`channel_groups` 的分组口径就是照 APTV 抄的），按台名建 dict 会把它们并成一个，
    恰好把「多出来一个台」这种漂移读成没变。顺序本身就是表的一部分 —— APTV 里那是两个频道位。

    只在一侧出现的台进 `added` / `removed`，不再逐条比线路（位置都错开了，比出来的「第 3 条不同」没意义）。
    每个台的两条线路**数**可以不一样长（`--max-lines` 改大就是这种），多出来/少掉的条数记进
    `extra_a` / `extra_b` —— 不记的话「每台从 3 条加到 6 条」这种漂移会被逐条比对整个看不见。

    >>> d = diff_tables([("湖南卫视", ["http://a/1", "http://b/2"]),
    ...                  ("经视", ["http://c/3"])],
    ...                 [("湖南卫视", ["http://a/1", "http://b/2"]),
    ...                  ("经视", ["http://c/3"])])
    >>> (d["lines_same"], d["lines_a"], d["channels_a"], d["name_seq_same"])
    (True, 3, 2, True)
    >>> # 第一线换了：最重手，电视上默认播的就不是同一条流了
    >>> d2 = diff_tables([("湖南卫视", ["http://a/1"])], [("湖南卫视", ["http://x/9"])])
    >>> (d2["lines_same"], d2["first_changes"], d2["line_changes"])
    (False, [('湖南卫视', 'http://a/1', 'http://x/9')], [('湖南卫视', 1, 'http://a/1', 'http://x/9')])
    >>> # 只动备选线路也算换表（判分面没变，但报告说「这张表有几条备选」时说的不是同一张）
    >>> db = diff_tables([("湖南卫视", ["http://a/1", "http://b/2"])],
    ...                  [("湖南卫视", ["http://a/1", "http://z/8"])])
    >>> (db["first_changes"], db["alt_changes"], db["alt_channels"])
    ([], 1, 1)
    >>> # 加宽：一条地址都没换，只是每个台多留了几条 —— 仍然是换表，但要说清换了什么
    >>> dw = diff_tables([("湖南卫视", ["http://a/1"])],
    ...                  [("湖南卫视", ["http://a/1", "http://b/2", "http://c/3"])])
    >>> (dw["lines_same"], dw["line_changes"], dw["extra_b"], dw["alt_channels"])
    (False, [], 2, 1)
    >>> # 多个台 / 少个台：位置从那里开始全错，就不逐条比了
    >>> d3 = diff_tables([("甲", ["http://a/1"])], [("甲", ["http://a/1"]), ("乙", ["http://b/2"])])
    >>> (d3["lines_same"], d3["added"], d3["removed"], d3["line_changes"])
    (False, ['乙'], [], [])
    >>> # 同名不同 id 是两个台：这里两份都是两个「湖南卫视」，位置比出来就是两条独立记录
    >>> d4 = diff_tables([("湖南卫视", ["http://a/1"]), ("湖南卫视", ["http://b/2"])],
    ...                  [("湖南卫视", ["http://a/1"])])
    >>> (d4["channels_a"], d4["channels_b"], d4["lines_same"])
    (2, 1, False)
    """
    out = {"channels_a": len(a), "channels_b": len(b),
           "lines_a": sum(len(u) for _, u in a), "lines_b": sum(len(u) for _, u in b),
           "names_a": [n for n, _ in a], "names_b": [n for n, _ in b],
           "line_changes": [], "first_changes": [], "alt_changes": 0, "alt_channels": 0,
           "extra_a": 0, "extra_b": 0, "added": [], "removed": []}
    out["name_seq_same"] = out["names_a"] == out["names_b"]
    if out["name_seq_same"]:
        for (n, ua), (_, ub) in zip(a, b):
            alt_hit = len(ua) != len(ub)          # 条数不等也算「这个台的备选部分变了」
            for i, (x, y) in enumerate(zip(ua, ub), 1):
                if x == y:
                    continue
                out["line_changes"].append((n, i, x, y))
                if i == 1:
                    out["first_changes"].append((n, x, y))
                else:
                    out["alt_changes"] += 1
                    alt_hit = True
            short = min(len(ua), len(ub))
            out["extra_a"] += len(ua) - short
            out["extra_b"] += len(ub) - short
            out["alt_channels"] += 1 if alt_hit else 0
    else:
        kb = {n for n, _ in b}
        ka = {n for n, _ in a}
        out["added"] = [n for n in out["names_b"] if n not in ka]
        out["removed"] = [n for n in out["names_a"] if n not in kb]
    out["lines_same"] = (out["name_seq_same"] and not out["line_changes"]
                         and out["lines_a"] == out["lines_b"])
    return out


def strip_attrs(line: str) -> str:
    """去掉 `tvg-id` / `tvg-logo` 这两个「我们这层写进去的」属性，看这行还剩什么。

    为什么单摘这两个：它们是 P3（EPG 对齐）的产物，换一份节目单就会整批变，
    而它们**不改变能播的内容**。其余属性（`group-title`、台名）变了就是分组/命名真的动了。

    >>> strip_attrs('#EXTINF:-1 tvg-id="81" tvg-logo="https://x/y.png" group-title="📍 湖南",湖南卫视')
    '#EXTINF:-1 group-title="📍 湖南",湖南卫视'
    >>> strip_attrs('#EXTINF:-1 tvg-id="湖南卫视",湖南卫视')     # 只剩 id：去掉就是干净的一行
    '#EXTINF:-1 ,湖南卫视'
    """
    out = line
    for key in ("tvg-id", "tvg-logo"):
        pre, _, rest = out.partition(f'{key}="')
        if rest:
            out = pre + rest.partition('"')[2]
    return " ".join(out.split())


def attribute_delta(a_text: str, b_text: str) -> dict:
    """那几百行 `diff` 到底是什么：把**行级**差异按「谁改的」分类。

    分四类是因为只有一类要紧：`lines`（线路本身，`http` 开头）变了才叫换表；
    `ids` 是 EPG 对账换写法，`other_attrs` 是分组/台名，`header` 是头部那行节目单地址。
    行数不等时多出来的那段整体算 `other_attrs` 并记在 `len_diff`，不假装对齐得上一一归类。

    >>> a = ('#EXTM3U x-tvg-url="http://old/e.xml.gz"\\n'
    ...      '#EXTINF:-1 tvg-id="x",湖南卫视\\nhttp://a/1\\n')
    >>> b = ('#EXTM3U x-tvg-url="http://new/e.xml.gz"\\n'
    ...      '#EXTINF:-1 tvg-id="81",湖南卫视\\nhttp://a/1\\n')
    >>> attribute_delta(a, b)                                   # 只有头部和 tvg-id 动了
    {'lines': 0, 'ids': 1, 'other_attrs': 0, 'header': 1, 'len_diff': 0}
    >>> # 台名（逗号后面那段）变了不算属性噪声 —— 那是分组/命名真的动了
    >>> attribute_delta('#EXTINF:-1 tvg-id="1",湖南卫视\\n', '#EXTINF:-1 tvg-id="1",湖南卫视HD\\n')['other_attrs']
    1
    >>> attribute_delta('#EXTINF:-1 tvg-id="1",湖南卫视\\nhttp://a/1\\n',
    ...                 '#EXTINF:-1 tvg-id="1",湖南卫视\\nhttp://b/1\\n')['lines']
    1
    """
    la, lb = a_text.splitlines(), b_text.splitlines()
    d = {"lines": 0, "ids": 0, "other_attrs": 0, "header": 0, "len_diff": abs(len(la) - len(lb))}
    for x, y in zip(la, lb):
        if x == y:
            continue
        if x.startswith("http") or y.startswith("http"):
            d["lines"] += 1
        elif x.startswith("#EXTM3U") or y.startswith("#EXTM3U"):
            d["header"] += 1
        elif strip_attrs(x) == strip_attrs(y):
            d["ids"] += 1
        else:
            d["other_attrs"] += 1
    return d


def verdict(name: str, d: dict, att: dict) -> str:
    """一张表一行话：先给结论，再给那几百行差异的解释。

    措辞故意分成两种开头（「同一张表」/「**换表了**」），因为这一行的唯一用途就是
    让人决定「报告里那些数还作不作数」。属性差异跟在后面，不当结论也不藏起来。
    换表那半边还要分清新是哪一种：**第一线换了**才影响电视上默认播的东西，
    备选条数变了（比如 `--max-lines` 从 3 加到 6）动的是「有没有退路」那一层。

    >>> D = {"lines_same": True, "channels_a": 98, "channels_b": 98, "lines_a": 226, "lines_b": 226,
    ...      "line_changes": [], "first_changes": [], "alt_changes": 0, "alt_channels": 0,
    ...      "extra_a": 0, "extra_b": 0, "added": [], "removed": []}
    >>> print(verdict("aptv.m3u", D, {"lines": 0, "ids": 187, "other_attrs": 0,
    ...                               "header": 1, "len_diff": 0}))
    aptv.m3u：同一张表 —— 226 条线路一字不差；另有 187 行只是 tvg-id／tvg-logo 变了（节目单对账换了写法，能播的东西没换），头部节目单地址变了 1 行
    >>> d2 = dict(D, lines_same=False, first_changes=[("湖南卫视", "http://a/1", "http://b/2")],
    ...           line_changes=[("湖南卫视", 1, "http://a/1", "http://b/2")])
    >>> print(verdict("hunan.m3u", d2, {"lines": 2, "ids": 0, "other_attrs": 0, "header": 0,
    ...                                  "len_diff": 0}))
    hunan.m3u：**换表了** —— 1 个台的第一线换了（湖南卫视：`http://a/1` → `http://b/2`）
    >>> # 只动第 2、3 条线：还是换表，但不说成「默认播的变了」
    >>> only_bak = dict(D, lines_same=False, alt_changes=1, alt_channels=1,
    ...                 line_changes=[("湖南卫视", 2, "http://a/2", "http://b/9")])
    >>> print(verdict("hunan.m3u", only_bak, {"lines": 1, "ids": 0, "other_attrs": 0,
    ...                                       "header": 0, "len_diff": 0}))
    hunan.m3u：**换表了** —— 1 个台的第 2 条及以后不同（换地址 1 处、多 0 条、少 0 条）
    >>> # 加宽（`--max-lines` 3 → 6）：一条地址没换，但每个台多出三条 —— 这是那种最容易读错的
    >>> wide = dict(D, lines_same=False, lines_b=452, alt_channels=98, extra_b=226)
    >>> print(verdict("hunan.m3u", wide, {"lines": 0, "ids": 0, "other_attrs": 0, "header": 0,
    ...                                   "len_diff": 226}))
    hunan.m3u：**换表了** —— 98 个台的第 2 条及以后不同（换地址 0 处、多 226 条、少 0 条）
    >>> "多了 1 个台：新台" in verdict("hunan.m3u", dict(D, lines_same=False, added=["新台"]),
    ...                                {"lines": 1, "ids": 0, "other_attrs": 0, "header": 0,
    ...                                 "len_diff": 0})
    True
    """
    if d["lines_same"]:
        tail = ""
        if att["ids"]:
            tail += (f"；另有 {att['ids']} 行只是 tvg-id／tvg-logo 变了"
                     "（节目单对账换了写法，能播的东西没换）")
        if att["header"]:
            tail += f"，头部节目单地址变了 {att['header']} 行"
        if att["other_attrs"]:
            tail += f"；还有 {att['other_attrs']} 行分组/台名也动了"
        return f"{name}：同一张表 —— {d['lines_a']} 条线路一字不差{tail}"
    bits = []
    if d["first_changes"]:
        ex = "、".join(f"{n}：`{x}` → `{y}`" for n, x, y in d["first_changes"][:3])
        bits.append(f"{len(d['first_changes'])} 个台的第一线换了（{ex}"
                    + ("…）" if len(d["first_changes"]) > 3 else "）"))
    if d.get("alt_changes") or d.get("alt_channels"):
        bits.append(f"{d['alt_channels']} 个台的第 2 条及以后不同"
                    f"（换地址 {d.get('alt_changes', 0)} 处、"
                    f"多 {d.get('extra_b', 0)} 条、少 {d.get('extra_a', 0)} 条）")
    if d["added"]:
        bits.append(f"多了 {len(d['added'])} 个台：" + "、".join(d["added"][:5]))
    if d["removed"]:
        bits.append(f"少了 {len(d['removed'])} 个台：" + "、".join(d["removed"][:5]))
    if not bits:
        bits.append(f"台数或顺序对不上（{d['channels_a']} 个台 / {d['lines_a']} 条 ↔ "
                    f"{d['channels_b']} 个台 / {d['lines_b']} 条）")
    return f"{name}：**换表了** —— " + "；".join(bits)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="比对两张已生成的表：报告说的是不是电视上那张")
    ap.add_argument("--against", required=True, metavar="目录",
                    help="离线重出的那份表所在的目录（`build --replay --out /tmp/…` 的产物）")
    ap.add_argument("--dir", default=str(OUT_DIR),
                    help="基准目录，默认 data/output（订阅进电视的那批产物）")
    ap.add_argument("--files", default="aptv.m3u,hunan.m3u",
                    help="比哪几张表，逗号分隔；两边都有这个文件名才比")
    args = ap.parse_args(argv)

    b_dir, a_dir = Path(args.against), Path(args.dir)
    if not b_dir.is_dir():
        print(f"找不到 {b_dir}：先跑 ./.venv/bin/python -X utf8 -m src.cli build --replay --out {b_dir}",
              file=sys.stderr)
        return 2
    drift = checked = 0
    skipped: list[str] = []
    for fn in [f.strip() for f in args.files.split(",") if f.strip()]:
        pa, pb = a_dir / fn, b_dir / fn
        if not pa.exists() or not pb.exists():
            print(f"{fn}：跳过（{pa if not pa.exists() else pb} 不在）")
            skipped.append(fn)
            continue
        ta, tb = pa.read_text(encoding="utf-8"), pb.read_text(encoding="utf-8")
        d = diff_tables(channel_groups(ta), channel_groups(tb))
        att = attribute_delta(ta, tb)
        if att["len_diff"]:
            d["lines_same"] = False       # 行数都不等，别信「同一张表」
        print(verdict(fn, d, att))
        checked += 1
        if not d["lines_same"]:
            drift += 1
    if not checked:
        # 一张都没比成功，就不能说「完全一致」—— 那是最容易在自动化里蒙混过关的一种假绿
        sys.stdout.flush()            # 不然这行会插到上面那几条「跳过」前面，读起来像先报错再干活
        print(f"一张表都没比成（`--against` 那个目录里没有 {args.files} 中的任何一个）", file=sys.stderr)
        return 2
    if drift:
        print(f"\n{drift} 张表和基准不是一张表 —— 报告里那些「集中度」「换线路」的数，"
              "说的已经不是电视上这份了，按新表重读一遍再据此决定。")
        return 1
    print("\n线路级完全一致：报告里那些数说的就是这一张表。"
          "（它不判断线路好坏，也不产生新表 —— 上面那句「同一张表」只到今天这两份文件为止。）"
          + (f" 没比的：{'、'.join(skipped)}" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
