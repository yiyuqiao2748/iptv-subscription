"""一条命令跑完这个项目的全部对账，包括「正在跑的那个页面有没有说谎」。

    ./.venv/bin/python -X utf8 scripts/selfcheck.py                     # 默认七条
    ./.venv/bin/python -X utf8 scripts/selfcheck.py --against /tmp/r226 # 顺手问「报告说的是不是这张表」
    ./.venv/bin/python -X utf8 scripts/selfcheck.py --epg               # 再挂上 EPG 那条（读本地缓存，实测 0.08 秒）
    ./.venv/bin/python -X utf8 scripts/selfcheck.py --port 8799 --skip page

退码：**0** = 真跑的那些全过；**1** = 至少一条不过；**2** = 一条都没真跑起来
（全被跳过 / 解释器起不来 —— 「没查到错」和「没查」不是一件事，这条口径从 2.21 起一路抄下来的）。

为什么现在才串：2.28 和 2.29 两节的「下一步」都写了「不急」，那次判断当时是对的 ——
那几把尺各自都还新，串起来只是把四条命令变成一个黑盒。今天加它有一条新的理由：
**有一类失效只有「问一眼正在跑的进程」才看得见**（2.29 那个「99 个台」），
而我拿眼睛对了一次就不该再对第二次。所以这里真正的增量是 `page` 那一步，
另外八条（`doctests`/`numbers`/`doc-cmds`/`names`/`self-test`/`doc-test` 六条默认，`drift`/`epg` 两条要点名）只是被顺带串进来的。`selfcheck` 这个文件名在 2.27/2.28 里被刻意回避过
（2.21 那把尺会把「文档里出现一个不存在的脚本名」判成漂移）—— 这一节里它是当场做出来的东西。
**2.55 追记**：上面那句「四条默认」与第 3 行的「默认五条」都是加 `names` 之后的数
（默认 = 四条离线尺 + `page`）。`names` 只看文件名那一层，为的是 `.git/` 里那种同步盘冲突副本 ——
加它之前那五把尺一把都不读那里，而 2.54 在同一分钟量到那儿真掉进过三颗。
**2.56 追记**：那两个数又各加一（「四条默认」→ 五条、「默认五条」→ 六条），多的是 `self-test`：
它量的不是仓库，是 `names` 那把尺**还咬不咬得动**。加它之前那条 ✓ 有两种读法（仓库真干净 /
那把尺瞎了），而这一屏分不清 —— 分不清的解决方式不是把话改短，是补一条能分清它的检查。
（上一段追记里引的那两句「四条默认」「默认五条」从此只存在于那段文字里，正文已经不留了。）
**2.57 追记**：再把那两个数各加一（「五条默认」→ 六条、「默认六条」→ 七条），多的是 `doc-test` ——
`self-test` 那个形状原样递给命令尺：`doc-cmds` 那条 ✓ 说的是「143 条命令、0 条对不上」，
这一句同样有几种读法，而它自己一种也分不开（13:34 逐格量到的现状里，有一格它明明印出了
「文档里写了 scripts/nope_g257.py，但 scripts/ 里没有这个文件」，退码却是 2 = 「这把尺瞎了」）。
所以这一节**改了两格的行为**：`off` 没关、以及只有散文点了个不存在的脚本名，从退 2 改成退 1；
今天这批文档的退码不变（改前改后逐字节相同，量在 13:41）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "output"
EPG_CACHE = ROOT / "data" / "cache" / "epg.xml"
STAMP_PHRASE = "生成的那一批"        # 2.29 加在状态页上的那句；没有它=跑的是旧版

# 页面里每一行长这样（`serve_lan._index()` 拼的）：
#   <li><code>http://10.0.0.5:8787/aptv.m3u</code> —— 全量：…（98 个台）
CLAIM = re.compile(r"<code>http://[^<>/]+/(?P<file>[\w.\-]+)</code>\s*——\s*"
                   r"[^<]*?（(?P<n>\d+) 个台）")


def claims(html: str) -> dict[str, int]:
    """状态页**声称**每张表有几个台：{文件名: 台数}。

    只认带台数的那些行。老代码（2.29 之前）那三行诊断表根本没有数，
    它们在这里掉下来 —— 由 `check_page` 那句「一行都没抓到」接住，不许静悄悄通过。

    >>> html = ('<li><code>http://10.0.0.5:8787/aptv.m3u</code> —— 全量（98 个台）'
    ...         '<li><code>http://10.0.0.5:8787/test.m3u</code> —— 极小表（4 个台）')
    >>> claims(html)
    {'aptv.m3u': 98, 'test.m3u': 4}
    >>> claims('<li><code>http://10.0.0.5:8787/a.m3u</code> —— 表（文件不在）')
    {}
    >>> claims('还没有内容')
    {}
    """
    return {m.group("file"): int(m.group("n")) for m in CLAIM.finditer(html)}


def disk_counts(files: list[str]) -> tuple[dict[str, int], list[str]]:
    """磁盘上**实际**有几个台 —— 走 `probe_pack.channel_groups`，不走页面那套代码。

    为什么必须换一条路：这一页的数出自 `serve_lan.channel_count`，
    要拿它自己跟自己对账就永远对得上。这里用另一份实现（`channel_groups`，
    `scripts/doc_num.py` 那个 `aptv:channels` 也走它），两条路撞出同一个数才有信息量。

    第二个返回值是**页面给了个数、磁盘上却没有这个文件**的那些。2.32 起它算失败：
    「页面会写『文件不在』」不构成豁免 —— 那种行压根进不到这里（见 `claims` 只认带台数的行）。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from probe_pack import channel_groups        # 唯一一处 import 放在函数里：为了可数

    got, missing = {}, []
    for name in files:
        p = OUT_DIR / name
        if not p.exists():
            missing.append(name)
            continue
        got[name] = sum(1 for _, urls in channel_groups(p.read_text(encoding="utf-8")) if urls)
    return got, missing


def fetch_page(port: int, timeout: float = 4.0) -> str:
    """取本机那个订阅服务的首页原文。

    必须绕过系统代理：这台机器上代理是全局 TUN，走它去取 `127.0.0.1` 会拿到假答案
    （`serve_lan.already_running()` 从一开始就是这么写的，这里照抄那一招）。
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/", timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def page_verdict(html: str, disk: dict[str, int], gone: list[str]) -> tuple[str, str]:
    """把「页面说的话」和「磁盘上的表」摆一起 —— 判定逻辑全在这里，IO 不在。

    三种结果分开说，因为**下一步要做的事不一样**：服务没起（`check_page` 给 skip）、
    跑的是旧版（重启就完事）、数对不上（那是 bug，得改代码）。
    「一行带台数的都没抓到」算失败而不是通过：那要么是老版式、要么是版式改了，
    两种情况下这一步都没量到东西 —— **「没查到错」和「没查」不是一件事**。

    `gone` 那一格是 2.32 补的，以前它叫「不是错」，理由写的是「页面会写『文件不在』」——
    那句话把两件事混成一件了：`claims()` 只认带「（N 个台）」的行，页面真写「文件不在」
    时根本进不到这一层。所以能落进 `gone` 的只剩一个意思：**页面还在为一个磁盘上没有的
    文件报数**，那正是 2.29 立这一条要抓的化石，不能算过。

    >>> disk, miss = {"aptv.m3u": 98, "test.m3u": 4}, []
    >>> # 页面行长这样，所以样例也照它的样子拼（`row` = 一行）
    >>> row = lambda f, s: f'<li><code>http://10.0.0.5:8787/{f}</code> —— {s}'
    >>> stamp = "上面那两张表是 09-21 21:18 生成的那一批"
    >>> page_verdict(row("aptv.m3u", "全量（98 个台）") + row("test.m3u", "极小表（4 个台）") + stamp,
    ...              disk, miss)
    ('pass', '2/2 行的台数与磁盘一致')
    >>> v, why = page_verdict(row("aptv.m3u", "全量（99 个台）") + row("test.m3u", "极小（4 个台）") + stamp,
    ...                       disk, miss)
    >>> v, why
    ('fail', 'aptv.m3u：页面说 99，磁盘上是 98；1/2 行的台数与磁盘一致')
    >>> # 2.29 之前那一版：数碰巧是对的，但那句生成时间还没有 → 这个进程是旧的，不能算过
    >>> v, why = page_verdict(row("aptv.m3u", "全量（98 个台）"), disk, miss)
    >>> v, why
    ('fail', '1/1 行的台数与磁盘一致；这一页还没有 2.29 那句生成时间 —— 跑着的是**旧版**，它上面的台数是起服务那一刻抄的化石：关掉窗口、重新双击一次')
    >>> # 真·老版：诊断表那三行只有名字没有数，抓到的那一条又对不上
    >>> v, why = page_verdict(row("aptv.m3u", "全量（99 个台）"), disk, miss)
    >>> v, why.split("；")[0]
    ('fail', 'aptv.m3u：页面说 99，磁盘上是 98')
    >>> page_verdict(row("hunan.m3u", "湖南本地优先（文件不在）"), disk, [])[0]
    'fail'
    >>> # 页面给着数、磁盘上这个文件已经没了 —— 化石，2.32 起算不过
    >>> v, why = page_verdict(row("aptv.m3u", "全量（98 个台）") + row("b.m3u", "另一张（7 个台）") + stamp,
    ...                       {"aptv.m3u": 98}, ["b.m3u"])
    >>> v, why
    ('fail', 'b.m3u：页面说 7 个台，可磁盘上已经没有这个文件了；1/2 行的台数与磁盘一致')
    """
    said = claims(html)
    if not said:
        return "fail", ("那一页上一行带台数的都没抓到 —— 老版式（2.29 之前诊断表只有名字）"
                        "还是版式改了？这一层什么都没量到，不算通过")
    bad = [f"{f}：页面说 {n}，磁盘上是 {disk[f]}" for f, n in sorted(said.items())
           if f in disk and disk[f] != n]
    ghosts = [f"{f}：页面说 {n} 个台，可磁盘上已经没有这个文件了"
              for f, n in sorted(said.items()) if f in gone]
    parts = bad + ghosts + [f"{len(said) - len(bad) - len(ghosts)}/{len(said)} 行的台数与磁盘一致"]
    if STAMP_PHRASE not in html:
        parts.append("这一页还没有 2.29 那句生成时间 —— 跑着的是**旧版**，"
                     "它上面的台数是起服务那一刻抄的化石：关掉窗口、重新双击一次")
    return ("pass" if not bad and not ghosts and STAMP_PHRASE in html else "fail"), "；".join(parts)


def check_page(port: int) -> tuple[str, str]:
    """问一眼正在跑的那个页面：它声称的台数对不对、它是不是 2.29 那一版。

    这一条是那八条离线尺（`doctests`/`numbers`/`doc-cmds`/`names`/`self-test`/`doc-test`/`drift`/`epg`）
    唯一量不到的那层 —— 它们全在量磁盘上躺着的东西（`self-test`、`doc-test` 量的是那两把尺自己，
    量的仍然是磁盘上那 15 格名字，不是正在跑的进程）。
    取页面必须绕过系统代理：TUN 开着时走代理去取 `127.0.0.1` 会拿到假答案。
    """
    try:
        html = fetch_page(port)
    except (OSError, urllib.error.URLError) as e:
        return "skip", (f"端口 {port} 上没有订阅服务（{type(e).__name__}）—— "
                        "这一步量的是「正在跑的那个进程」，它不在就没得量；"
                        "双击 启动电视订阅服务.command 再跑一次")
    if "APTV" not in html:
        return "fail", f"端口 {port} 有东西在听，但那不是这个服务（页面里连 APTV 都没有）"
    said = claims(html)
    disk, gone = disk_counts(list(said))
    return page_verdict(html, disk, gone)


# 各把尺的收尾句长得不一样，但都带这几个词之一。挑不到就印最后一行（不许印空）。
# 「照抄」是 2.45 加的：命令尺那句「带着…那个钟、能照抄来量的 21 条：18 条会退 1…」是
# **另外一行**，这个词不在名单上的时候，selfcheck 里印出来的永远是那句「0 条对不上；该查的都查了」
# —— 也就是把这一节新装的那一层发现原样藏起来。两边各钉了一格用例（那边在 `clock_summary`）。
CONCLUSION = ("合计", "比了", "扫了", "线路级", "同一张表", "换表了", "结论", "照抄")


def conclusion(stdout: str) -> str:
    """从一屏输出里挑出那句「结论」，而不是随便一行噪音。

    为什么要挑：`run_doctests` 跑负例（2.21 那个「打错子命令」的演示）时，被调方会
    直接往 stderr 印一句 「未知的子命令 'bulid'」，它比结论行更靠后 ——
    第一版我拿「最后一行」当结论，那条 ✓ 底下印的就是它，读起来像出了事。
    这一层只认 stdout，再按上面那批词挑一句。

    >>> conclusion("· 模块 a\\n合计 645 个用例，0 个失败（22 个模块）\\n")
    '合计 645 个用例，0 个失败（22 个模块）'
    >>> conclusion("第 1 行\\n第 2 行")                 # 一个词都没撞上：印最后一行
    '第 2 行'
    >>> conclusion("\\n \\n")
    '（没有任何输出）'
    >>> conclusion("扫了 141 条命令：0 条对不上；该查的都查了\\n"
    ...            "带着那个钟、能照抄来量的 21 条：18 条会退 1\\n")
    '带着那个钟、能照抄来量的 21 条：18 条会退 1'
    """
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    if not lines:
        return "（没有任何输出）"
    for line in reversed(lines):
        if any(w in line for w in CONCLUSION):
            return line
    return lines[-1]


def run_script(argv: list[str], *, timeout: float = 900.0) -> tuple[str, str]:
    """跑一条现成的命令（同一个解释器），把退码翻译成判定 + 那句结论。

    这里刻意不 `import` 那些脚本再调 `main()`：那会把它们的 `sys.exit` 语义、
    参数默认值和「谁是主实现」全都糊在一起。几条尺各自有退出码口径，串起来的那条只管收。

    过了 = 只印 stdout 里那句结论；**没过 = 把 stdout + stderr 末尾一起摊出来**，
    因为 `table_drift` 那类工具的「找不到」是往 stderr 说的，失败时不该只看到半句。
    """
    r = subprocess.run([sys.executable, "-X", "utf8"] + argv, cwd=ROOT,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode == 0:
        return "pass", conclusion(r.stdout or "")
    both = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    detail = "\n".join(f"      {l}" for l in [x for x in both if x.strip()][-14:])
    return "fail", f"退 {r.returncode}\n{detail or '      （没有任何输出）'}"


def steps(args: argparse.Namespace) -> list[tuple[str, str, Callable[[], tuple[str, str]]]]:
    """这一轮要跑哪些检查：(名字, 给人看的那句, 怎么跑)。

    默认七条 —— 六条离线尺（`doctests`/`numbers`/`doc-cmds`/`names`/`self-test`/`doc-test`）+ 那条只有
    「问一眼正在跑的进程」才做得到的 `page`。`drift` 和 `epg` 要人点名，各有一条实在的理由：
    `drift` 得先有另一份表放在那儿（没有就是 2，不该混进这一屏）；
    `epg` 回答的不是「说的和算的是不是一回事」，而是「现在这份节目单对我们有几个台有用」——
    那是体检项，不是对账项（它只要 0.08 秒，慢不是它不默认挂上的原因）。
    `names`（2.55）是**默认挂上**的：它量的是同步盘刚塞进来那一分钟里才会有的东西，
    点名才跑等于每次都要先记得它存在，而那种「记得」正是这一节要省掉的。
    `self-test`（2.56）跟着它一起默认挂上，理由不是「顺手」而是**那条 ✓ 自己说不清自己**：
    仓库今天 0 颗，`names` 的退 0 既可能是干净也可能是那把尺瞎了，只有往临时树里种过名字
    才知道它咬得动 —— 所以它跟 `names` 是一对，缺一个另一个就不能读。
    `doc-test`（2.57）是同一个理由递给命令尺的那一半：`doc-cmds` 说「143 条命令、0 条对不上」，
    这句话同样分不清「文档真干净」与「那几层判据整层不咬」，而 13:34 量到的现状里它连
    「自己找到了东西」都能报成「自己瞎了」（那一格现在由 `B9`/`B13` 两格钉住）。
    它跑 0.6 秒（25 格、一共 11 次 `--help` 子进程、6 个目标 —— 同一个目标只问一遍；
    14:07 实测三遍 0.56／0.58／0.60，这一档在 `selfcheck` 里那一遍是 0.58 秒），
    换的是这一屏上那条 ✓ 能不能读。
    `--skip` 与「跑不了」是两回事：前者是人不让跑（这一条直接不出现），
    后者会自己变成一条 `·` 判定出现在结果里（那个数要能对上）。

    >>> ns = argparse.Namespace(port=8787, against="", epg=False, skip=[])
    >>> [n for n, _, _ in steps(ns)]
    ['doctests', 'numbers', 'doc-cmds', 'names', 'self-test', 'doc-test', 'page']
    >>> ns = argparse.Namespace(port=8787, against="/tmp/r226", epg=True, skip=["page"])
    >>> [n for n, _, _ in steps(ns)]
    ['doctests', 'numbers', 'doc-cmds', 'names', 'self-test', 'doc-test', 'drift', 'epg']
    >>> ns = argparse.Namespace(port=8787, against="", epg=False, skip=["page", "numbers"])
    >>> [n for n, _, _ in steps(ns)]
    ['doctests', 'doc-cmds', 'names', 'self-test', 'doc-test']
    """
    out: list[tuple[str, str, Callable[[], tuple[str, str]]]] = [
        ("doctests", "全项目的逻辑样例（改过逻辑先看这条）",
         lambda: run_script(["scripts/run_doctests.py"])),
        ("numbers", "文档里抄来的那些数还算不算数",
         lambda: run_script(["scripts/doc_num.py"])),
        ("doc-cmds", "文档里的命令还能不能照抄",
         lambda: run_script(["scripts/check_doc_cmds.py"])),
        ("names", "文件名本身像不像一次事故（含 `.git/`）",
         lambda: run_script(["scripts/stray_names.py"])),
        ("self-test", "那把尺自己还咬得动吗（往临时树里种 15 格名字）",
         lambda: run_script(["scripts/stray_names.py", "--self-test"])),
        ("doc-test", "命令尺自己还咬得动吗（往临时文件里种 25 格文档）",
         lambda: run_script(["scripts/check_doc_cmds.py", "--self-test"])),
        ("page", "正在跑的那个页面声称的台数", lambda: check_page(args.port)),
    ]
    if args.against:
        out.append(("drift", "报告说的是不是眼前这张表",
                    lambda: run_script(["scripts/table_drift.py", "--against", args.against])))
    if args.epg:
        cache = str(EPG_CACHE.relative_to(ROOT))
        out.append(("epg", f"节目单配得上几个台（只读 {cache}，不抓网）",
                    lambda: epg_offline(cache)))
    return [(n, w, f) for n, w, f in out if n not in args.skip]


def epg_offline(cache: str) -> tuple[str, str]:
    """EPG 那条走**本地缓存**，不抓网。

    为什么要挑明：`epg_check.py` 不给参数时会去取候选地址（那是实测，出口不对就白测），
    这一条只想在离线自检里回答一句「现在这张表配上节目单的有几个台」。
    缓存不在就跳过 —— 别为了跑完一条检查去抓外网（计划书 2.18：什么时候联网由人定）。
    """
    if not EPG_CACHE.exists():
        return "skip", f"{EPG_CACHE.relative_to(ROOT)} 不在，这一步要读的就是它"
    return run_script(["scripts/epg_check.py", cache])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="selfcheck.py", description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8787, help="订阅服务在哪个端口（默认 8787）")
    ap.add_argument("--against", default="", help="顺手跑 table_drift：那份表所在的目录")
    ap.add_argument("--epg", action="store_true", help="把 EPG 那条也挂上（只读本地缓存）")
    ap.add_argument("--skip", action="append", default=[],
                    help="跳过某一步，可重复：page / numbers / doc-cmds / doctests / names / "
                         "self-test / doc-test / drift / epg")
    args = ap.parse_args(argv)

    plan = steps(args)
    if not plan:
        print("一条检查都没剩下（全 --skip 了）—— 这不算通过。", file=sys.stderr)
        return 2

    table = next((OUT_DIR / n for n in ("aptv.m3u",) if (OUT_DIR / n).exists()), None)
    stamp = (dt.datetime.fromtimestamp(table.stat().st_mtime).strftime("%m-%d %H:%M")
             if table else "没有产物")
    print(f"自检 · {dt.datetime.now():%m-%d %H:%M} · 在用的这批表：{stamp}\n")

    ran = failed = 0
    skips: list[str] = []
    fails: list[str] = []
    for name, what, fn in plan:
        try:
            verdict, detail = fn()
        except Exception as e:                       # 炸了也算「跑过了但不过」，不许吞
            verdict, detail = "fail", f"{type(e).__name__}: {e}"
        if verdict == "skip":
            skips.append(name)
        else:
            ran += 1
        if verdict == "fail":
            failed += 1
            fails.append(name)
        mark = {"pass": "✓", "fail": "✗", "skip": "·"}[verdict]
        print(f"  {mark} {name:<9} {what}")
        print(f"           {detail}")

    print(f"\n真跑了 {ran} 条、跳过 {len(skips)} 条、不过 {failed} 条"
          + (f"（跳过的：{'、'.join(skips)}）" if skips else "")
          + ("" if ran else " —— 一条都没真跑起来，这不算通过"))
    if not ran:
        return 2
    if {"numbers", "drift"} & set(fails):
        print("如果报的是 `numbers` 或 `drift`：先跑 `table_drift` 再跑 `doc_num`，"
              "数对不上多半是「该重抄」而不是「算错了」（2.27 → 2.28 那个顺序）。")
    if "page" in fails:
        print("`page` 那条跟上面那些不是一类：它说的是**正在跑的那个进程**，"
              "磁盘上的东西全对也不会让它自己变好 —— 要么重启服务，要么 `--skip page`。")
    if "names" in fails:
        print("`names` 那条说的也不是内容，是**名字**：它点出来的那些是同步盘刚掉进来的东西。"
              "\n           别在这条命令里顺手 `rm` —— 先 `diff` 一下，确认没用了再搬出仓库（2.55）。")
    if "self-test" in fails:
        print("`self-test` 那条红**不是说仓库里掉进了冲突副本**：那 15 格名字是它自己种在临时目录里的，"
              "\n           跑完就回收。它说的是那把尺的判据变了或者它的措辞变了 —— "
              "先看它点的是哪一格，再 `git log -p scripts/stray_names.py`（2.56）。")
        if "names" not in fails:
            print("`names` 绿、`self-test` 红 —— 这个组合只有一种意思：**那把尺自己咬不动了**，"
                  "\n           上面那条 `names` 的 ✓ 这一轮不能读（真仓库 0 颗到底是干净还是瞎，"
                  "全靠这一条分开）。")
    if "doc-test" in fails:
        # 这一句要挡住的是那种最贵的误读：以为 `doc-test` 在说「文档里有一条命令写错了」。
        # 那是 `doc-cmds` 的活；这一条扫的是它自己种的 25 份临时文档，跟仓库里那三篇无关。
        print("`doc-test` 那条红也**不是说文档里有命令写错了**：那 25 份文档是它自己种的临时件，"
              "\n           跑完就回收，仓库里那三篇它一个字没读。它说的是命令尺的判据或者措辞变了 —— "
              "先看它点的是 `G` 组（误伤）还是 `B` 组（该红没红），再 `git log -p scripts/check_doc_cmds.py`（2.57）。")
        if "doc-cmds" not in fails:
            print("`doc-cmds` 绿、`doc-test` 红 —— 同一个意思的另一半：**那句「0 条对不上」这一轮不能读**，"
                  "\n           它可能是文档真干净，也可能是那几层判据整层不咬（143 条一条都没查中）。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
