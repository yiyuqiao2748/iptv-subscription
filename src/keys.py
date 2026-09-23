"""配置里的键名守卫：写歪一个字母，不该等于「什么都没改」。

起因是 2026-09-23 把五份配置逐个字面过了一遍（计划书 2.39）。三个加载器清一色是
`raw.get("...")`，键名写歪就是拿默认值，一声不吭 —— 而**默认值恰好是最容易骗人的那个答案**：
`enabled` 拼错 = 这条源还开着，`priority` 拼错 = 退回按写下来的先后，
顶层 `channels:` 拼错 = 一份名单都不读。当天离线复现（只喂临时文件，不碰 `config/`）：

    sources.yaml  `enable: false`   → 那条源照样进表，[('a', True), ('b', True)]
    sources.yaml  `prority: 1`      → 优先级静默变回 2，等于按顺序排
    epg.yaml      `enabledd: false` → 节目单照旧挂着，enabled=True
    sources_local `tvg-idd: "81"`   → 对上的台拿到空 tvg-id，一条提示都没有

四种都不会让表少东西 —— 少的是**一个本该发生的改变**，所以人在表上看不出来。
这一层把这件事办到：认不出的键要么停下来说清楚，要么印一行警告，不许静默走默认值。

为什么不是「一律停下来」：配置里本来就有一批**故意写给人看**的键（`note`、`added`、
`version` 的注释位），它们没有代码读是设计，不是漏。一律停下来等于逼人为每句注释开证明。
所以只有「近似命中一个会改行为的键」才致命 —— 那种样子最像笔误，而笔误改的是表上的内容。

上游 m3u 的属性名**不归这里管**：那是别人写的文件，各家自定义属性一大堆
（`user-agent`、`catchup`、`tvg-shift`…），全报出来只会把该看的那一行淹没。
"""

from __future__ import annotations

import difflib
import ast
import inspect
import textwrap

# 差多少算「像是笔误」。0.6 是试出来的：`enable`/`enabled`、`prority`/`priority`、
# `chanels`/`channels` 落在这一侧，`owner`、`note2` 这种真没人读的键落在另一侧。
CUTOFF = 0.6


def unknown_keys(raw: dict, known) -> list[str]:
    """`raw` 里那些不在 `known` 名单上的键，按它们在文件里出现的顺序给出来。

    只做字面比对，不猜「它是想写谁」—— 猜是 `find_unknown()` 的事。分开是因为
    猜不中也要有话可说（下面那格 `owner`），而这份列表本身不该管结论。

    >>> unknown_keys({"url": "x", "note": "这句给人看"}, ["url"])
    ['note']
    >>> unknown_keys({"url": "x"}, ["url"])
    []
    >>> unknown_keys({2026: "年份当键"}, ["url"])     # YAML 里裸数字键也照样点出来
    ['2026']
    """
    allow = {str(k) for k in known}
    return [str(k) for k in raw if str(k) not in allow]


def nearest(key: str, candidates) -> str:
    """这个键最像是从 `candidates` 里哪一个抄歪了；差得远就不硬认（返回空串）。

    宁可漏认一个笔误，也不要指错方向：报「`owner` 像是 `url`」会把人赶到错的那行去修。

    大小写单独处理一下：`difflib` 是按字符算相似的，`URL` 和 `url` 在它眼里**一分都不像**，
    于是这类笔误只能安静地走默认值 —— 而 YAML 里 `URL:` 和 `url:` 是两个键。

    >>> nearest("prority", ["enabled", "priority", "url"])
    'priority'
    >>> nearest("enable", ["enabled", "priority", "url"])
    'enabled'
    >>> nearest("chanels", ["version", "channels"])
    'channels'
    >>> nearest("owner", ["enabled", "priority", "url"])      # 不是笔误，是真的没人读
    ''
    >>> nearest("URL", ["name", "url"])
    'url'
    >>> nearest("Expires", ["name", "url", "expires"])
    'expires'
    """
    pool = [str(c) for c in candidates]
    folded = {c.lower(): c for c in pool}
    low = key.lower()
    if low in folded and key != folded[low]:
        return folded[low]
    hits = (difflib.get_close_matches(key, pool, n=1, cutoff=CUTOFF)
            or difflib.get_close_matches(low, list(folded), n=1, cutoff=CUTOFF))
    if not hits:
        return ""
    hit = hits[0]
    return folded.get(hit.lower(), hit)


def find_unknown(raw: dict, *, where: str, known, notes: dict[str, str] | None = None):
    """把 `raw` 里认不出的键分成「致命」和「只警告」两摞整句。

    `notes` 是 `known` 的一个子集：那些键一改，表上就有东西跟着变。值是**一句接在
    「它管的是」后面的话**，说它管的是什么 —— 这句话要出现在报错里，让人明白为什么这个
    拼错值得停下来。

    返回 `(致命的话, 警告的话)`。纯函数、不抛也不印，所以两摞各测各的；
    连「notes 里的键不在 known 名单上」这种**自己写歪**也在这里当场炸出来 ——
    那是代码的错（行为键从没人读了），不该混在给人看的配置话里，所以抛 `KeyError`。

    >>> notes = {"enabled": "这条源参不参与出表"}
    >>> known = ["enabled", "id", "url", "note"]
    >>> find_unknown({"enable": False}, where="第 1 条源", known=known, notes=notes)
    (['第 1 条源：`enable` 我们不读，最像是 `enabled` 写歪了 —— 它管的是这条源参不参与出表'], [])
    >>> find_unknown({"id": "a", "owner": "y"}, where="第 1 条源", known=known, notes=notes)
    ([], ['第 1 条源：`owner` 没人读，也不像现有哪个键写歪 —— 确认一下是不是漏写了'])
    >>> find_unknown({"url": "x", "note2": "y"}, where="第 1 条源", known=known)
    ([], ['第 1 条源：`note2` 没人读，倒是有个点像 `note` —— 确认一下是不是漏写了'])
    >>> find_unknown({"id": "a"}, where="第 1 条源", known=known, notes=notes)
    ([], [])
    >>> try:
    ...     find_unknown({}, where="x", known=["id"], notes={"prio": "谁排前面"})
    ... except KeyError as e:
    ...     print("自己写歪了" if "prio" in str(e) else str(e))
    自己写歪了
    """
    notes = notes or {}
    allow = [str(k) for k in known]
    undeclared = [k for k in notes if k not in allow]
    if undeclared:
        raise KeyError(f"notes 里的 {' 和 '.join(undeclared)} 不在 known 名单上 —— "
                       "要么它不该算行为键，要么代码早就不读它了，先把这两份对齐")
    fatal: list[str] = []
    warns: list[str] = []
    for key in unknown_keys(raw, allow):
        hit = nearest(key, allow)
        if hit in notes:
            fatal.append(f"{where}：`{key}` 我们不读，最像是 `{hit}` 写歪了 —— "
                         f"它管的是{notes[hit]}")
        elif hit:
            warns.append(f"{where}：`{key}` 没人读，倒是有个点像 `{hit}` —— 确认一下是不是漏写了")
        else:
            warns.append(f"{where}：`{key}` 没人读，也不像现有哪个键写歪 —— 确认一下是不是漏写了")
    return fatal, warns


def check_keys(raw: dict, *, where: str, known, notes: dict[str, str] | None = None) -> list[str]:
    """`find_unknown()` 的落地版：致命的那摞就地抛，警告的话交给调用方去印。

    为什么致命的选择抛而不是印一行：出表一旦过了这一层，五份产物就都写下去了，
    而「源没关掉」在表上是看不出来的 —— 项目里同类判断一直是宁可停下让人先修配置
    （`load_sources` 缺 `url`、`channels` 空列表都这么办，计划书 2.36/2.37）。

    >>> known = ["enabled", "id", "url", "note"]
    >>> notes = {"enabled": "这条源参不参与出表", "id": "缓存文件名与报告里的源名"}
    >>> check_keys({"id": "a"}, where="第 1 条源", known=known, notes=notes)
    []
    >>> check_keys({"url": "x", "note2": "y"}, where="第 1 条源", known=known)
    ['第 1 条源：`note2` 没人读，倒是有个点像 `note` —— 确认一下是不是漏写了']
    >>> try:
    ...     check_keys({"enable": False, "owner": "y"}, where="第 1 条源",
    ...                known=known, notes=notes)
    ... except ValueError as e:
    ...     print(str(e))
    第 1 条源：`enable` 我们不读，最像是 `enabled` 写歪了 —— 它管的是这条源参不参与出表

    注意上面那格：致命的和警告的同时存在时，只抛致命的（先修那一行，再跑一次，
    警告自然会出来）。一次说完会把两件事搅在一起，人反而不知道先动哪个。
    """
    fatal, warns = find_unknown(raw, where=where, known=known, notes=notes)
    if fatal:
        raise ValueError("\n".join(fatal))
    return warns


def check_version(raw: dict, *, where: str) -> None:
    """给 `version` 一个真职责：只认 1，别的值停下来。

    在这之前它是五份配置里各写一遍、谁都不读的客套话（计划书 2.32 点过一次）。
    留着不丢人，丢人的是「写了 2，代码照 1 读」—— 那才是这个字段唯一拦得住的事：
    哪天配置真要换版本，别让代码装作没看见。没写这个键放过（可选的新文件常不写）。

    >>> check_version({}, where="config/x.yaml") is None
    True
    >>> check_version({"version": 1}, where="config/x.yaml") is None
    True
    >>> check_version({"version": "1"}, where="config/x.yaml") is None   # YAML 写成字符串也算
    True
    >>> try:
    ...     check_version({"version": 2}, where="config/x.yaml")
    ... except ValueError as e:
    ...     print("拦下了" if "只认 1" in str(e) else "没拦")
    拦下了
    """
    got = raw.get("version")
    if got is None or str(got).strip() == "1":
        return
    raise ValueError(f"{where} 的 `version` 是 {got!r}，这份代码只认 1 —— 它按 v1 那种形状读"
                     "（键名、层级都是），版本对不上时安静地照旧读，"
                     "出错的地方会跑到表上而不是这里")


def reads(src: str) -> set[str]:
    """那段代码里以**字面量**读到的键名：`d.get("k")` 和 `d["k"]`，只算读、不算写。

    只认字面量是因为这一层要问的就是「名单和代码说的是同一批名字吗」，
    而 `d[k]`（键名是个变量）问不出是谁。赋值那一侧也不算 —— `info["url"] = x` 是造一个
    内部字典，不是读配置；字典字面量里的键名（`{"url": x}`）同理。

    >>> sorted(reads('def f(d):\\n    return d.get("a") + d["b"]'))
    ['a', 'b']
    >>> sorted(reads('def f(d):\\n    d["a"] = 1'))          # 写进去的不算读
    []
    >>> sorted(reads('def f(d):\\n    return {"a": 1, "b": d["b"]}'))
    ['b']
    >>> sorted(reads('def f(d, k):\\n    return d[k]'))      # 变量当键：问不出是谁
    []
    >>> sorted(reads('def f(d):\\n    return d.get("x", {})["y"]'))
    ['x', 'y']
    >>> sorted(reads('    def f(d):\\n        return d["a"]'))    # 方法那种带缩进的源码也吃得下
    ['a']
    >>> try:
    ...     reads('def f(:')                     # 键名都取不出来，不能装作「这个函数没读键」
    ...     print("咽下去了")
    ... except SyntaxError:
    ...     print("读不进源码就原样抛，让调用方去撞")
    读不进源码就原样抛，让调用方去撞
    """
    tree = ast.parse(textwrap.dedent(src))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            out.add(node.args[0].value)
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            out.add(node.slice.value)
    return out


def drift(fn_src: str, *more_src: str, known, notes) -> list[str]:
    """手写的键名单和读它的那几段代码之间漂了多少；空列表 = 没漂。

    2.39 那道闸的弹药全是手写的 `*_KEYS` / `*_NOTES`，而「名单 == 代码读的那批键」
    这件事当时只写在注释里（`src/parse/local.py` 顶上那句就是这样一个承诺）。
    这一层把那个承诺变成能跑的东西。两个方向分开问，因为坏法不一样：

    ① **代码读了、名单上没写**：以后有人加一个读取忘了补名单，第一个被撞响的是
       他自己的真配置 —— 那个合法键会被念成「没人读」，而它写歪时闸根本拦不住
       （不在 `known` 里就谈不上「像是谁写歪了」）。方向是**喊错人**。
    ② **名单上说是行为键、这几段代码却没读它**：那这个键写歪照样静默 —— 正是这个模块
       要治的那一种。闸自己带着它睡觉比不装更坏，因为它会让人以为已经管住了。

    两个方向量的都是**传进来的那几段代码**，不是整个模块：拿 `/tmp` 那份副本试过，
    把 `load_sources` 里那句 `s.get("priority", i + 1)` 改成不读配置（而 `cmd_build` 里
    还有一处 `s.get("priority")` 读的是解析好的内部字典），按「整个模块」量就是 0 失败 ——
    名字还在、读它的代码已经搬走或没了，那种漂恰好是②要抓的那种。
    所以真要把读它的代码搬到另一个函数去，就把那个函数一起传进来（可变参数就是为这个留的）。

    `known` 里那些**写给人看**的键（`note`、`added`）不进 `notes`，所以②不管它们：
    没人读是设计，不是漂（2.39 复核过的那半条）。

    一条都没读到时不许报「没漂」，要报「没量到」—— 2.32 那一格讲的就是这个：
    一把尺什么都没量到还退 0，会把「没查」读成「查过并且是干净的」。

    >>> known = ["id", "url", "enabled", "note"]
    >>> notes = {"enabled": "这条源参不参与出表", "url": "去哪儿抓这份列表"}
    >>> ok = 'def f(s):\\n    return s["url"] if s.get("enabled", True) else s.get("note", "")'
    >>> drift(ok, known=known, notes=notes)
    []
    >>> late = 'def f(s):\\n    return s["url"] and s.get("enabled", True) and s.get("priority", 1)'
    >>> drift(late, known=known, notes=notes)          # 名单漏了 priority 那一格
    ['读了却没写进名单：`priority` —— 配置里照实写它会被念成「没人读」，写歪了更拦不住；补进那份 *_KEYS（顺手把算不算行为键也定了）']
    >>> more = dict(notes, probe="它进不进 --verify 实测")
    >>> drift(ok, known=known, notes=more)             # 名单多了一格：没人读的行为键
    ['名单上说是行为键、这几段代码却没读它：`probe` —— 它写歪就等于没写，先弄清是不该算行为键还是读它的那段代码已经没了']
    >>> drift('def f(s):\\n    return 1', known=known, notes=notes)   # 什么都没量到
    ['那段代码里一条字面量键读取都没有 —— 闸没量到东西，别把这一格读成「名单和代码对得上」']

    几段代码一起量（读它的代码分在两处时就这么传）：

    >>> a = 'def f(s):\\n    return s.get("url")'
    >>> b = 'def g(s):\\n    return s["enabled"]'
    >>> drift(a, b, known=known, notes=notes)
    []
    >>> drift(a, known=known, notes=notes)            # 少传一段，②就该响
    ['名单上说是行为键、这几段代码却没读它：`enabled` —— 它写歪就等于没写，先弄清是不该算行为键还是读它的那段代码已经没了']
    """
    used: set[str] = set()
    for src in (fn_src, *more_src):
        used |= reads(src)
    if not used:
        return ["那段代码里一条字面量键读取都没有 —— 闸没量到东西，"
                "别把这一格读成「名单和代码对得上」"]
    out: list[str] = []
    undeclared = sorted(used - {str(k) for k in known})
    if undeclared:
        out.append(f"读了却没写进名单：{' '.join(f'`{k}`' for k in undeclared)} —— "
                   "配置里照实写它会被念成「没人读」，写歪了更拦不住；"
                   "补进那份 *_KEYS（顺手把算不算行为键也定了）")
    dead = [k for k in notes if k not in used]
    if dead:
        out.append(f"名单上说是行为键、这几段代码却没读它："
                   f"{' '.join(f'`{k}`' for k in dead)} —— "
                   "它写歪就等于没写，先弄清是不该算行为键还是读它的那段代码已经没了")
    return out


def drift_of(fn, *more, known, notes) -> list[str]:
    """`drift()` 的取样版：那几段代码的源码自己去取，只问一句「漂没漂」。

    五处加载器各自的用例就是这一句 —— 名单写在那段代码旁边，而这条用例保证
    「旁边」不只是排版上的旁边。用法：`drift_of(load_sources, known=..., notes=...)`，
    读它的代码若在两处，就 `drift_of(f, g, ...)`。

    >>> drift_of(check_version, known=["version"], notes={})
    []
    >>> drift_of(check_version, known=["version"], notes={"url": "去哪儿抓这份列表"})
    ['名单上说是行为键、这几段代码却没读它：`url` —— 它写歪就等于没写，先弄清是不该算行为键还是读它的那段代码已经没了']
    >>> drift_of(unknown_keys, known=["known"], notes={})   # 这个函数自己不读字面量键
    ['那段代码里一条字面量键读取都没有 —— 闸没量到东西，别把这一格读成「名单和代码对得上」']
    >>> drift_of(check_version, unknown_keys, known=["version", "raw"], notes={})  # 两段一起
    []
    """
    return drift(inspect.getsource(fn), *(inspect.getsource(f) for f in more),
                 known=known, notes=notes)
