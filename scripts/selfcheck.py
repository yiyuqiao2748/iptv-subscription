"""一条命令跑完这个项目的全部对账，包括「正在跑的那个页面有没有说谎」。

    ./.venv/bin/python -X utf8 scripts/selfcheck.py                     # 默认十五条
    ./.venv/bin/python -X utf8 scripts/selfcheck.py --against /tmp/r226 # 顺手问「报告说的是不是这张表」
    ./.venv/bin/python -X utf8 scripts/selfcheck.py --epg               # 再挂上 EPG 那条（读本地缓存，实测 0.08 秒）
    ./.venv/bin/python -X utf8 scripts/selfcheck.py --port 8799 --skip page

退码：**0** = 真跑的那些全过；**1** = 至少一条不过；**2** = 一条都没真跑起来
（全被跳过 / 解释器起不来 —— 「没查到错」和「没查」不是一件事，这条口径从 2.21 起一路抄下来的）。

为什么现在才串：2.28 和 2.29 两节的「下一步」都写了「不急」，那次判断当时是对的 ——
那几把尺各自都还新，串起来只是把四条命令变成一个黑盒。今天加它有一条新的理由：
**有一类失效只有「问一眼正在跑的进程」才看得见**（2.29 那个「99 个台」），
而我拿眼睛对了一次就不该再对第二次。所以这里真正的增量是 `page` 那一步，
另外十六条（`doctests`/`numbers`/`doc-cmds`/`names`/`self-test`/`doc-test`/`num-test`
/`unmarked`/`um-test`/`claims`/`claims-test`/`drift-test`/`epg-test`/`lean-test` 十四条默认，
`drift`/`epg` 两条要点名）只是被顺带串进来的。`selfcheck` 这个文件名在 2.27/2.28 里被刻意回避过
（2.21 那把尺会把「文档里出现一个不存在的脚本名」判成漂移）—— 这一节里它是当场做出来的东西。
**2.55 追记**：上面那句「四条默认」与第 3 行的「默认五条」都是加 `names` 之后的数，
当时那句写的是「默认 = 四条离线尺 + `page`」。`names` 只看文件名那一层，为的是 `.git/` 里那种同步盘冲突副本 ——
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
**2.58 追记（这一遍补的）**：那一节加了 `num-test`，第 3 行的「七条」跟着推成「八条」，
`check_page` 与 `steps` 那两句说明书也各改了一次 —— 唯独上面那份名单没动（它还写着「六条默认」）。
漏的是文档不是代码，而这一树里没有一把尺读得到它：`doc-cmds` 只扫那三篇文档，`numbers` 只看
文档里挂了标记的数，`doctests` 会跑说明书里的例子、可它一个字都不读例子外面的那些字。
所以「写在代码里的话」那一层当时是量不到的 —— 那一句到 2.60 为止成立：那一节装了第一把读它的尺
（`scripts/code_claims.py`），这一屏因此多了 `claims` 与 `claims-test` 两条。
上面那份名单这一遍已按第十条补齐。
**2.59 追记**：再加两条 `unmarked` 与 `um-test`，当时那句写的是「默认十条 = 九条离线尺 + `page`」。
`unmarked` 跟前面几条不是一类：别的都在回答「有没有毛病」，它只回答「还有多少个数一把尺都没看过」。
所以那条 ✓ 里**没有**「没问题」的意思 —— 候选点几条都不改退码，那口单一开始就写在
`scripts/unmarked_nums.py` 第一段。既然它报的是处数，那把尺自己也得有人问一句还咬不咬得动
（2.56 那个理由第四次管用），于是它的 `--self-test` 跟着挂上，成一比一的那对
（2.59 那一遍种的是 22 个格子；2.67 起 30 格）。
**2.60 追记**：再把那两个数各加二 —— 多的是 `claims` 与 `claims-test`，第五把「量那把尺」的尺
（`scripts/code_claims.py` 读 .py 的 docstring，2.60 那遍 22 个格子、2.68 起 23 格）。2.60 那一遍的口径是「默认十二条 = 十一条离线尺」
加 `page`。这一节的顺序是反的，值得记下来：先加两条步骤，才有人来报上面那两句里哪几个字变了 ——
18:32:30 那一遍 `claims` 自己数出 6 处对不上，全部出自这一个原因（第 3 行的注释、2.59 那句、
`check_page` 与 `steps` 各自那份说明书）。放在以前那四轮里，这 6 处是人拿着日志逐条改的。
它自己那 22 个格子也是这么被咬的：加进第 22 个格子（`G10_引号不在句首`）之后第一遍，红的就是它自己说明书里
那句「种 21 格」—— 一把量散文的尺第一处抓到的是它自己，这一条算它 work 的证据，不算它意外。
**2.64 追记**：那两个数再加二 —— 多的是 `drift-test` 与 `epg-test`，第六、七把「量那把尺」的尺
（`scripts/table_drift.py` 9 格、`scripts/epg_check.py` 14 格）。当时的口径写成「默认十四条 = 十三条离线尺
加 `page`」。这一遍是 2.60 那一节第一次**替我干活**：两条步骤装完，我还没回头数说明书里有几句旧话，
`claims` 自己数出 6 处对不上，两种各有各的来路 ——
4 处是这一遍改出来的旧话（第 3 行那句「默认十二条」、2.60 追记里那两个数、`check_page` 与
`steps` 各自说明书里那句「十一条离线尺」），2 处是 `epg_check` 的说明书里那两句「种 14 格」被报成
「没点名，只要求属于 15/22/26/29」—— 因为 `code_claims.ALIASES` 那张表里根本没有这两把尺。
放在以前那四轮里，前 4 处是人拿着日志逐条改的，而后 2 处**连逐条都对不出来**：读的人会以为
14 是一个凭空的数，其实它是刚装好的那把尺的真实格数。补上两个别名之后 `claims` 退 0
（那一遍印的是「查到 21 处报数的话，0 处对不上」—— 这个分母是跟着散文长的，21:48:17 那一遍它已经是 25）。
后 2 处不是回忆：21:51:26 拿一份 /tmp 副本把那两个别名删掉重跑，红回来的正是它们
（`epg_check.py:模块`、`epg_check.py:no_network`，另加这一段追记自己写的「9 格」「14 格」两处，一共 4 处）。
**2.65 追记**：那两个数各再加一 —— 多的是 `lean-test`（`scripts/lean_playlist.py` 12 格，
第八把配对尺，守的是 `build` 主路上那支**会写文件**的生产件，不是尺）。这一遍是 2.60 那把尺
**第二次**替我干活，而且抓到的正是上一段那种我自己看不见的旧话：这一步装完、我一个字都没回头数，
`claims` 数出 **4 处**对不上，全在这一件里 —— 第 3 行那句「默认十四条」、`check_page` 说明书里那句
「十三条离线尺」、`steps` 说明书里那一句的两处（「默认十四条」与「十三条离线尺」，同一句它报两笔）。
4 这一半不是顺手数的：22:35:42 与 22:35:55 两遍拿一份内存副本把那四处话**改回**装 `lean-test`
之前的样子、跑真的 `code_claims.py`，报的正是这四笔（`selfcheck.py:模块`、`selfcheck.py:check_page`、
`selfcheck.py:steps` ×2），退 1；那份副本当场还原（逐字节相同），改对之后的那一遍是 22:35:10 量的：
26 处 0 对不上、退 0。
其中 2.64 那段追记里的「默认十四条 = 十三条离线尺」这一处值得单说：它**不该被改成新的数**，
那是篡改那一节的现场；改法是给它套上「」，让它从「今天的一句口径」变成「引用过的一句旧话」，
`claims` 认得这个区别（`QUOTE` 那一条）。
上面那句「十四条默认」它读不到 —— 那是 `SC_DEFAULT` 要「默认」在「条」前面的代价，
所以那半句从头到尾是我自己数着改的，没人量（记在 2.65 的「边界」里）。
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
from typing import Callable, Sequence

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

    这一条量的那一层，是那十四条离线尺（`doctests`/`numbers`/`doc-cmds`/`names`/`self-test`
    /`doc-test`/`num-test`/`unmarked`/`um-test`/`claims`/`claims-test`
    /`drift-test`/`epg-test`/`lean-test`）加上两条要点名的（`drift`/`epg`）
    全都读不到的 ——
    它们量的是磁盘上躺着的东西（`self-test`、`doc-test`、`num-test`、`um-test`、`claims-test`、
    `drift-test`、`epg-test`、`lean-test` 量的是那八把尺自己，量的仍然是它们种进临时目录的那些格子，不是正在跑的进程）。
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


KEEP = 14             # 失败那一格最多摊几行 —— 再多就不是「看一眼」而是刷屏了
CALLOUT = "✗"         # 这几把尺点名的行都以它开头（`stray_names`、`run_doctests` 都是）


def clip(lines: list[str], keep: int = KEEP) -> tuple[list[str], list[str]]:
    """只摊末尾 `keep` 行，**但被截掉的那些必须自己报出来**。

    立这一格的来由不是「屏幕不好看」，是一个读数对不上的现场：2.60 收笔那一遍
    `stray_names.py` 单跑印 22 行非空、点名 7 条，同一份输出进这一屏只剩最后 14 行 ——
    屏幕上只有 4 条，被挤掉的 `.git/index 4` 的名字行没了、它那半句说明还在，
    结论那行还写着「上面逐条点名了」。**那个 7 是真的，那 4 条也是真的，只有「逐条」是假的。**
    一个不知道被截过的读日志的人会就此认为尺子在撒谎，或者认为屏幕上那就是全部。

    补的话分三种形状，各钉一条用例：① 只要截了就报截几行；② 被截的行里有几条是点名行
    （数 `CALLOUT` 开头的，这是「少了多少条」而不是「少了几行」）；③ 摊出来的第一行如果
    是缩进的，它是**上一条的说明**不是主语 —— 那句「它在 `.git/` 里」没有主语，得说出来。

    >>> kept, notes = clip([f"✗ 第 {i} 条" for i in range(1, 20)] + ["扫了 19 条"], 14)
    >>> len(kept), kept[0], kept[-1]
    (14, '✗ 第 7 条', '扫了 19 条')
    >>> for n in notes: print(n)
    这一格只摊了末尾 14 行，前面 6 行没显示 —— 单跑那条命令看全部
    被截掉的 6 行里有 6 条是点名的行 —— 上面这一屏少了 6 条

    ②那一条不是每次都有：被截的全是续行时它不该冒出来（①③照样在 —— 这一例正好把三条的
    分工程摊开：②数的是**少了几条名字**，不是少了几行）。
    >>> _, notes = clip(["扫了 20 条"] + ["    都是续行"] * 20, 6)
    >>> for n in notes: print(n)
    这一格只摊了末尾 6 行，前面 15 行没显示 —— 单跑那条命令看全部
    这里第一行是半句：它说的是被截掉的那 15 行里的某一条

    ③就是 2.60 那一屏的形状：点名行与它的说明行成对，截在中间时留下没有主语的说明。
    >>> kept, notes = clip(["✗ 名字 A", "    它为什么坏"] * 8 + ["扫了 8 个名字"], 6)
    >>> kept[0]
    '    它为什么坏'
    >>> for n in notes: print(n)
    这一格只摊了末尾 6 行，前面 11 行没显示 —— 单跑那条命令看全部
    被截掉的 11 行里有 6 条是点名的行 —— 上面这一屏少了 6 条
    这里第一行是半句：它说的是被截掉的那 11 行里的某一条

    没截的时候什么都不补 —— 这一格不许在没有信息的时候说话。
    >>> clip(["a", "b"], 14)
    (['a', 'b'], [])
    """
    if len(lines) <= keep:
        return list(lines), []
    dropped, kept = lines[:-keep], lines[-keep:]
    n = len(dropped)
    notes = [f"这一格只摊了末尾 {keep} 行，前面 {n} 行没显示 —— 单跑那条命令看全部"]
    callouts = sum(1 for l in dropped if l.lstrip().startswith(CALLOUT))
    if callouts:
        notes.append(f"被截掉的 {n} 行里有 {callouts} 条是点名的行 —— 上面这一屏少了 {callouts} 条")
    if kept[0][:1] in (" ", "\t"):
        notes.append(f"这里第一行是半句：它说的是被截掉的那 {n} 行里的某一条")
    return kept, notes


def run_script(argv: list[str], *, timeout: float = 900.0) -> tuple[str, str]:
    """跑一条现成的命令（同一个解释器），把退码翻译成判定 + 那句结论。

    这里刻意不 `import` 那些脚本再调 `main()`：那会把它们的 `sys.exit` 语义、
    参数默认值和「谁是主实现」全都糊在一起。几条尺各自有退出码口径，串起来的那条只管收。

    过了 = 只印 stdout 里那句结论；**没过 = 把 stdout + stderr 末尾一起摊出来**，
    因为 `table_drift` 那类工具的「找不到」是往 stderr 说的，失败时不该只看到半句。
    末尾是 `KEEP` 行，多的截掉 —— 但**截了多少、少了几个名字，由 `clip` 补在后面**：
    2.60 收笔那一遍量到这一格把 `names` 的 7 条点名截成 4 条，屏幕上孤零零剩半句说明，
    而结论还写着「上面逐条点名了」（那一遍的 `a5e660af…` 那一屏第 12 行就是那半句）。
    """
    r = subprocess.run([sys.executable, "-X", "utf8"] + argv, cwd=ROOT,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode == 0:
        return "pass", conclusion(r.stdout or "")
    both = [x for x in ((r.stdout or "") + (r.stderr or "")).strip().splitlines() if x.strip()]
    kept, notes = clip(both)
    detail = "\n".join([f"      {l}" for l in kept] + [f"        · {n}" for n in notes])
    return "fail", f"退 {r.returncode}\n{detail or '      （没有任何输出）'}"


def steps(args: argparse.Namespace) -> list[tuple[str, str, Callable[[], tuple[str, str]]]]:
    """这一轮要跑哪些检查：(名字, 给人看的那句, 怎么跑)。

    默认十五条 —— 十四条离线尺（`doctests`/`numbers`/`doc-cmds`/`names`/`self-test`/`doc-test`
    /`num-test`/`unmarked`/`um-test`/`claims`/`claims-test`/`drift-test`/`epg-test`/`lean-test`）
    + 那条只有
    「问一眼正在跑的进程」才做得到的 `page`。`drift` 和 `epg` 要人点名，各有一条实在的理由：
    `drift` 得先有另一份表放在那儿（没有就是 2，不该混进这一屏）；
    `epg` 回答的不是「说的和算的是不是一回事」，而是「现在这份节目单对我们有几个台有用」——
    那是体检项，不是对账项（它只要 0.08 秒，慢不是它不默认挂上的原因）。
    `names`（2.55）是**默认挂上**的：它量的是同步盘刚塞进来那一分钟里才会有的东西，
    点名才跑等于每次都要先记得它存在，而那种「记得」正是这一节要省掉的。
    `self-test`（2.56）跟着它一起默认挂上，理由不是「顺手」而是**那条 ✓ 自己说不清自己**：
    仓库今天 0 颗，`names` 的退 0 既可能是干净也可能是那把尺瞎了，只有往临时树里种过名字
    才知道它咬得动 —— 所以它跟 `names` 是一对，缺一个另一个就不能读。
    `num-test`（2.58）是第三把：`numbers` 说「比了 74 处：全部对得上」，那句话同样有两种读法。
    14:26 那遍探针（22 个格子）还量出它带着一种比 2.57 更狠的错法：点名的两篇里有一篇不在时，
    它把另一篇比出来的成绩**一个字都不印**，只留一句「点名的文档不在」；同一遍还量到
    `--docs` 指到目录或非 UTF-8 的文件会裸崩。那一格现在由 `B7`／`B8`／`B9` 三格钉着。
    `doc-test`（2.57）是同一个理由递给命令尺的那一半：`doc-cmds` 说「143 条命令、0 条对不上」
    （正文之前那遍是 146 条，16:59:08；本节正文落盘之后是 149 条，17:37:04 在 `/tmp` 那份
    干净副本里单跑，两遍都是 0 条对不上），
    这句话同样分不清「文档真干净」与「那几层判据整层不咬」，而 13:34 量到的现状里它连
    「自己找到了东西」都能报成「自己瞎了」（那一格现在由 `B9`/`B13` 两格钉住）。
    它跑 1.15 秒（35 格、一共 18 次 `--help` 子进程、6 个目标 —— 每一格各起一遍那一档，
    一个目标被问几次取决于它出现在几格里，这一层没有缓存；2.66 加格子之前这一句写的是
    「12 次、6 个目标 —— 同一个目标只问一遍」，后半句是错的，本节把它换成量出来的那句。
    09-24 23:45:38—:42 单跑三遍 1.15／1.15／1.17；同一档在 `selfcheck` 进程里那一遍
    1.24—1.32 秒（23:47:23—:27 三遍，连解释器启动一起算，其余各条全 `--skip`），
    换的是这一屏上那条 ✓ 能不能读。
    `unmarked`（2.59）是这一屏上**唯一一条不回答「有没有毛病」的**：它报的是「文档里还有多少个
    数一把尺都没看过」，点几条候选都不改退码（16:19:57 那遍 `um_1.log`：甲 74、乙 109、丙 481、跳过 236，
    配平 900 = 900；那 74 处与 `numbers` 报的是同一批位置，两把尺对不上就直接退 2，
    这句话里的「甲」因此不是一个凭空的数）。它默认挂上，是因为「比了 74 处：全部对得上」只覆盖
    挂了标记的那些处 —— 分母另外那一块（同一句里 24 和 0 挂了、1 和 14 没挂，
    或正文复述上面那个 39）以前没人报，读的人便以为 74 就是文档里数的全体。
    它跑 0.05—0.06 秒（16:19 那三遍 0.09／0.05／0.05，`um_time_1`—`_3.log`；17:08:43 又三遍
    0.06／0.05／0.06，`tt_um_1`—`_3.log`），后两遍输出逐字节相同
    （与 16:11 那遍只差在点名行里键的先后 —— 那一行刚改了排序）。
    `um-test` 是它的配对（30 格、0.19 秒，2.67 加格子之后 00:36:03 实测三遍 0.19／0.19／0.19，
    与它 2.59 那一版的三遍 0.16／0.16／0.15（17:08:43，`tt_st_1`—`_3.log`）同量级；
    「16:29 三遍 0.17／0.15／0.15」
    那一组只在屏幕上、没落盘，本节不收）：那几行数出自一套
    分桶判据，判据整层不咬时数会照报、只是报成另一个样 —— 第四把这样配对的尺，与前那三把同一笔账。
    `drift-test` 与 `epg-test`（2.64）是那两把尺的第六、七次配对，理由和前五把**不一样**：
    `names`／`numbers`／`doc-cmds`／`unmarked`／`claims` 本身默认就在这屏上，所以「正查那条绿、基线那条红」
    是一句能落地的话；而 `drift` 要人给 `--against`、`epg` 要人给 `--epg`，默认那一屏上根本没有它们 ——
    于是这两条基线是这一屏上关于那两把尺**唯一**的一条证据，红了也没有别的 ✓ 可以废。
    正因为这样，`dispositions()` 给这两条各配一句、却**不配**那句 `*-green`（同一格由 doctest 钉着）。
    它们各跑 0.06—0.07 秒（21:39:46 那一遍实测各三遍：table_drift 0.07／0.07／0.06，
    epg_check 0.07／0.07／0.07，连解释器启动一起算），
    加起来 0.13 秒换这两把尺从今天起「改坏了会响」。
    `lean-test`（2.65）是第八把配对，但**它守的不是尺**：前七把的量对象全在仓库里有一步正查
    （或者像 `drift`/`epg` 那样要点名），而 `lean_playlist` 这一支在这屏上连一步都没有 ——
    它是 `build` 主路上的生产件（`src/cli.py:load_lean_fn()` 按文件路径把它的 `lean()` 捞过去），
    平时只在被调用那一刻才说话。所以这一条同样是「唯一的一条证据」，红了没有别的 ✓ 可以废，
    `dispositions()` 也不给它配 `*-green`（第四格由 doctest 钉着）。它多出来的那一半是**磁盘**：
    这一支会写文件，所以那 12 格里除了屏幕上的句子，还钉着「该没写的没写」（`absent`）与
    「源表还在」（`keep`）—— 2.63/2.64 那两把尺摊的是崩溃冒充判定，这一支摊的是更疼的一种：
    一份压坏的空表躺在 `data/output/` 里，长得像成功。跑 0.06—0.14 秒（22:31:40 实测三遍
    0.14／0.07／0.06，第一遍是缓存冷的；同一分钟对照：epg_check 0.08、table_drift 0.06）。
    `--skip` 与「跑不了」是两回事：前者是人不让跑（这一条直接不出现），
    后者会自己变成一条 `·` 判定出现在结果里（那个数要能对上）。

    >>> ns = argparse.Namespace(port=8787, against="", epg=False, skip=[])
    >>> [n for n, _, _ in steps(ns)]
    ['doctests', 'numbers', 'doc-cmds', 'names', 'self-test', 'doc-test', 'num-test', \
'unmarked', 'um-test', 'claims', 'claims-test', 'drift-test', 'epg-test', 'lean-test', 'page']
    >>> ns = argparse.Namespace(port=8787, against="/tmp/r226", epg=True, skip=["page"])
    >>> [n for n, _, _ in steps(ns)]
    ['doctests', 'numbers', 'doc-cmds', 'names', 'self-test', 'doc-test', 'num-test', \
'unmarked', 'um-test', 'claims', 'claims-test', 'drift-test', 'epg-test', 'lean-test', 'drift', 'epg']
    >>> ns = argparse.Namespace(port=8787, against="", epg=False, skip=["page", "numbers"])
    >>> [n for n, _, _ in steps(ns)]
    ['doctests', 'doc-cmds', 'names', 'self-test', 'doc-test', 'num-test', 'unmarked', \
'um-test', 'claims', 'claims-test', 'drift-test', 'epg-test', 'lean-test']
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
        ("doc-test", "命令尺自己还咬得动吗（往临时文件里种 35 格文档）",
         lambda: run_script(["scripts/check_doc_cmds.py", "--self-test"])),
        ("num-test", "数尺自己还咬得动吗（往临时目录里种 26 格文档）",
         lambda: run_script(["scripts/doc_num.py", "--self-test"])),
        ("unmarked", "文档里写了数却没挂标记的地方（只报数，不拦候选）",
         lambda: run_script(["scripts/unmarked_nums.py"])),
        ("um-test", "那把报数的尺自己还咬得动吗（往临时目录里种 30 格文档）",
         lambda: run_script(["scripts/unmarked_nums.py", "--self-test"])),
        ("claims", "写在代码里的那些话，报的数对不对（只读 .py 的 docstring，不跑它们）",
         lambda: run_script(["scripts/code_claims.py"])),
        ("claims-test", "那把读散文的尺自己还咬得动吗（往临时目录里种 23 格假件）",
         lambda: run_script(["scripts/code_claims.py", "--self-test"])),
        ("drift-test", "比表那把尺自己还咬得动吗（往临时沙盒里种 9 格表）",
         lambda: run_script(["scripts/table_drift.py", "--self-test"])),
        ("epg-test", "节目单那把尺自己还咬得动吗（往临时沙盒里种 14 格表、单、配置）",
         lambda: run_script(["scripts/epg_check.py", "--self-test"])),
        ("lean-test", "压裸表那一支自己还咬得动吗（往临时沙盒里种 12 格表）",
         lambda: run_script(["scripts/lean_playlist.py", "--self-test"])),
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


def dispositions(fails: Sequence[str]) -> list[tuple[str, str]]:
    """红的那几条各自配的那句「这话该怎么读」—— 抽成纯函数，是为了让它**能被点着跑**。

    为什么值得单独一个函数：这些句子以前只在 `main()` 里就地 `print`，于是它们只在
    「某条尺真的红了」的时候才存在。而这一屏上最难读的就是那几句 —— 15:17 那一遍整屏
    有五条不过，屏幕走到 `num-test` 那一句时崩在 `NameError: name 'oks' is not defined`
    上，后面的处置句一句没印：**那个分支从本节写下它起就没被跑过**，变量名写错没有任何
    东西会响（2.58「边界」里那条「量具的输出是证据、量具的说明书不是」，这一条是它的实物）。
    抽出来之后每种组合都能在下面这些用例里点一次，代价是零。

    返回 `(这句的钥匙, 要印的那句)`。钥匙只给用例看，印出去的还是原来那些字。

    >>> dispositions([])
    []
    >>> [k for k, _ in dispositions(["page"])]
    ['page']
    >>> [k for k, _ in dispositions(["numbers"])]           # 那条要配的是「先重算」
    ['recount']
    >>> [k for k, _ in dispositions(["drift", "num-test"])]
    ['recount', 'num-test', 'num-test/numbers-green']
    >>> # 配对那四句：同一把尺的 `*-test` 红、正查的那条绿 —— 只有这一种意思
    >>> [k for k, _ in dispositions(["self-test"])]
    ['self-test', 'self-test/names-green']
    >>> [k for k, _ in dispositions(["self-test", "names"])]     # 两红：各有一句，只少了配对那句
    ['names', 'self-test']
    >>> [k for k, _ in dispositions(["num-test", "numbers"])]    # numbers 红另配「先重算」那句
    ['recount', 'num-test']
    >>> [k for k, _ in dispositions(["doc-test", "doc-cmds"])]
    ['doc-test']
    >>> [k for k, _ in dispositions(["unmarked"])]           # 它红只有一种意思：有一篇没读到
    ['unmarked']
    >>> [k for k, _ in dispositions(["unmarked", "numbers"])]
    ['recount', 'unmarked']
    >>> [k for k, _ in dispositions(["um-test"])]            # 报数的那条也配一对（2.56 那个形状）
    ['um-test', 'um-test/unmarked-green']
    >>> [k for k, _ in dispositions(["um-test", "unmarked"])]     # 两红：各一句，只少配对那句
    ['unmarked', 'um-test']
    >>> # 新配的那两条（2.64）**故意不配** `*-green` 那句：正查那条默认根本不在这屏上
    >>> [k for k, _ in dispositions(["drift-test"])]
    ['drift-test']
    >>> [k for k, _ in dispositions(["epg-test", "drift-test"])]
    ['drift-test', 'epg-test']
    >>> # 2.65 那一条同一层，且它连「正查那条」都没有：`lean_playlist` 不是尺，是主路上的生产件
    >>> [k for k, _ in dispositions(["lean-test"])]
    ['lean-test']
    >>> [k for k, _ in dispositions(["epg-test", "drift-test", "lean-test"])]
    ['drift-test', 'epg-test', 'lean-test']
    >>> # 一句都不许是空的：钥匙配上就得真有字要印
    >>> all(t.strip() for _, t in dispositions(
    ...     ["page", "names", "self-test", "num-test", "doc-test", "unmarked", "um-test",
    ...      "drift", "drift-test", "epg-test", "claims-test", "lean-test"]))
    True
    >>> [k for k, _ in dispositions(["page", "names", "self-test", "num-test", "doc-test"])]
    ['page', 'names', 'self-test', 'num-test', 'num-test/numbers-green', 'doc-test', \
'doc-test/doc-cmds-green']
    """
    f = set(fails)
    out: list[tuple[str, str]] = []
    if f & {"numbers", "drift"}:
        out.append(("recount",
                    "如果报的是 `numbers` 或 `drift`：先跑 `table_drift` 再跑 `doc_num`，"
                    "数对不上多半是「该重抄」而不是「算错了」（2.27 → 2.28 那个顺序）。"))
    if "page" in f:
        out.append(("page",
                    "`page` 那条跟上面那些不是一类：它说的是**正在跑的那个进程**，"
                    "磁盘上的东西全对也不会让它自己变好 —— 要么重启服务，要么 `--skip page`。"))
    if "names" in f:
        out.append(("names",
                    "`names` 那条说的也不是内容，是**名字**：它点出来的那些是同步盘刚掉进来的东西。"
                    "\n           别在这条命令里顺手 `rm` —— 先 `diff` 一下，确认没用了再搬出仓库（2.55）。"))
    if "self-test" in f:
        out.append(("self-test",
                    "`self-test` 那条红**不是说仓库里掉进了冲突副本**：那 15 格名字是它自己种在临时目录里的，"
                    "\n           跑完就回收。它说的是那把尺的判据变了或者它的措辞变了 —— "
                    "先看它点的是哪一格，再 `git log -p scripts/stray_names.py`（2.56）。"))
        if "names" not in f:
            out.append(("self-test/names-green",
                        "`names` 绿、`self-test` 红 —— 这个组合只有一种意思：**那把尺自己咬不动了**，"
                        "\n           上面那条 `names` 的 ✓ 这一轮不能读（真仓库 0 颗到底是干净还是瞎，"
                        "全靠这一条分开）。"))
    if "num-test" in f:
        out.append(("num-test",
                    "`num-test` 那条红**不是说文档里的数抄错了**：那 26 份文档是它自己种的临时件，"
                    "仓库里那两篇它一个字没读。它说的是数尺的判据或者措辞变了 —— "
                    "先看它点的是 `G` 组（误伤）还是 `B` 组（该红没红），再 `git log -p scripts/doc_num.py`（2.58）。"))
        if "numbers" not in f:
            out.append(("num-test/numbers-green",
                        "`numbers` 绿、`num-test` 红 —— 同一个意思的另一半：**那句「74 处全部对得上」"
                        "这一轮不能读**，\n           它可能是文档真对得上，也可能是那层判据整层不咬 —— "
                        "26 格只点到 153 个键里的 10 个，那就是这一句的价钱（2.58 边界第 1 条）。"))
    if "unmarked" in f:
        # 这一条最贵的误读有两个方向：红的时候以为「文档里有数没挂」（它一辈子不为那件事红），
        # 绿的时候以为「数都挂全了」（它量的是分母，不是对错）。两句都写在这一条里。
        out.append(("unmarked",
                    "`unmarked` 那条红**不是说文档里有数没挂标记** —— 那件事它永远不报红，"
                    "\n           候选点几条都不改退码（2.59 的口径）。它红只有一种意思：**有一篇没读到**，"
                    "\n           于是这一屏上甲乙丙那些处数只盖住了读到的那几篇。"
                    "\n           反过来它绿也不读成「数都挂全了」：它报的是分母，不是判决。"))
    if "um-test" in f:
        out.append(("um-test",
                    "`um-test` 那条红也**不是说文档里有数没挂**：那 22 份文档是它自己种的临时件，"
                    "\n           跑完就回收，仓库里那两篇它一个字没读。它说的是分桶的判据或者措辞变了 —— "
                    "先看它点的是 `G` 组（误伤）还是 `B` 组（该红没红），再 `git log -p scripts/unmarked_nums.py`（2.59）。"))
        if "unmarked" not in f:
            out.append(("um-test/unmarked-green",
                        "`unmarked` 绿、`um-test` 红 —— 上面那几行数（甲 74、乙 109、丙 481）"
                        "\n           **这一轮不能读**：它们出自一把自己承认咬不动的尺。"
                        "\n           而 `numbers` 那句「比了 74 处」不受牵连，那是另一把尺量的。"))
    if "doc-test" in f:
        # 这一句要挡住的是那种最贵的误读：以为 `doc-test` 在说「文档里有一条命令写错了」。
        # 那是 `doc-cmds` 的活；这一条扫的是它自己种的 25 份临时文档，跟仓库里那三篇无关。
        out.append(("doc-test",
                    "`doc-test` 那条红也**不是说文档里有命令写错了**：那 25 份文档是它自己种的临时件，"
                    "\n           跑完就回收，仓库里那三篇它一个字没读。它说的是命令尺的判据或者措辞变了 —— "
                    "先看它点的是 `G` 组（误伤）还是 `B` 组（该红没红），再 `git log -p scripts/check_doc_cmds.py`（2.57）。"))
        if "doc-cmds" not in f:
            out.append(("doc-test/doc-cmds-green",
                        "`doc-cmds` 绿、`doc-test` 红 —— 同一个意思的另一半：**那句「0 条对不上」这一轮不能读**，"
                        "\n           它可能是文档真干净，也可能是那几层判据整层不咬（16:59:08 那遍 `pre_cmds.log`："
                        "146 条命令、0 条对不上，另有 2 行写了那个解释器却没认成命令、一条都没查）。"))
    if "drift-test" in f:
        # 这一条**不配**那句 `drift 绿、drift-test 红`：`drift` 默认根本不跑（要人给 `--against`），
        # 说「上面那条 ✓ 这一轮不能读」是替一条不在这一屏上的条目说话 —— 2.29／2.44 那种
        # 「话说得比它量的范围大」，只不过这次说的人是我自己。
        out.append(("drift-test",
                    "`drift-test` 那条红**不是说电视上那张表换了**：那 9 张表是它自己种在临时目录里的，"
                    "\n           跑完就回收，`data/output/` 它一个字没读。它说的是比表那把尺的判据或措辞变了 —— "
                    "\n           而这一屏默认并不跑 `drift` 本身（它要人给 `--against`），所以这一条是这一屏上"
                    "关于那把尺**唯一**的一条证据：红了先 `git log -p scripts/table_drift.py`（2.64）。"))
    if "epg-test" in f:
        out.append(("epg-test",
                    "`epg-test` 那条红也**不是说节目单配不上台了**：那 14 格表、单、配置是它自己种的临时件，"
                    "\n           `data/output/` 与 `data/cache/` 它一个字没读，而且那一档一个请求都不许发"
                    "（发不出去才当场算红）。它说的是这把尺的判据或措辞变了，"
                    "\n           跟 `drift-test` 同一层：这一屏默认也不跑 `epg` 本身，所以它是唯一那条证据（2.64）。"))
    if "lean-test" in f:
        # 同样**不配** `*-green`：`lean_playlist` 在这屏上根本没有正查那一步（它是 `build` 主路上的件，
        # 只有被调用那一刻才说话），所以「上面那条 ✓ 这一轮不能读」在这里连指谁都指不到。
        out.append(("lean-test",
                    "`lean-test` 那条红**不是说 `data/output/` 里那几张表坏了**：那 12 格是它自己种在"
                    "\n           临时沙盒里的，跑完就回收，仓库里那些真表它一个字没读、也一个字没写过。"
                    "\n           它说的是压裸表那一支的判据或措辞变了 —— 它与前七把配对不是一类：被量的这一支"
                    "是 `build` 主路上的生产件，它的本职就是写出一份表，所以那 12 格除屏幕之外还钉着磁盘"
                    "（该没写的没写、源表还在）。"
                    "\n           红了先 `git log -p scripts/lean_playlist.py`；`build` 那条主路今天不受影响（2.65）。"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="selfcheck.py", description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8787, help="订阅服务在哪个端口（默认 8787）")
    ap.add_argument("--against", default="", help="顺手跑 table_drift：那份表所在的目录")
    ap.add_argument("--epg", action="store_true", help="把 EPG 那条也挂上（只读本地缓存）")
    ap.add_argument("--skip", action="append", default=[],
                    help="跳过某一步，可重复：page / numbers / doc-cmds / doctests / names / "
                         "self-test / doc-test / num-test / unmarked / um-test / claims / claims-test / "
                         "drift-test / epg-test / lean-test / drift / epg")
    args = ap.parse_args(argv)

    plan = steps(args)
    if not plan:
        print("一条检查都没剩下（全 --skip 了）—— 这不算通过。", file=sys.stderr)
        return 2

    table = next((OUT_DIR / n for n in ("aptv.m3u",) if (OUT_DIR / n).exists()), None)
    stamp = (dt.datetime.fromtimestamp(table.stat().st_mtime).strftime("%m-%d %H:%M")
             if table else "没有产物")
    # 首行为什么带上解释器：15:14 那遍我用了系统的 `python3`（3.9.6），三把读文档的尺同时
    # 退 1、屏幕上一片 traceback，而那一行只写着时间 —— 分不清「仓库坏了」还是「跑错人了」。
    # `run_script` 用的是 `sys.executable`，所以这一行报的就是上面那些尺真正用的那一个。
    print(f"自检 · {dt.datetime.now():%m-%d %H:%M} · 在用的这批表：{stamp}"
          f" · 跑它的解释器：{sys.version.split()[0]}\n")

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
    # 那些「这话该怎么读」全在 `dispositions()` 里（上面那条用例把它每条组合都点了一遍）。
    # `main()` 这里只管印 —— 以前是就地 `print`，于是那十句只在「某条尺恰好红了」的那一遍
    # 里存在过，写错一个变量名不会有人知道（15:14 那遍就是这么崩的，见 2.58 踩的第 11 条）。
    for _, line in dispositions(fails):
        print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
