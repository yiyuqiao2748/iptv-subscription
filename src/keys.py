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
