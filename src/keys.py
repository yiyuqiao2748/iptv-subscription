"""配置里的键名守卫 + 值的形状守卫：写歪一个字母、或者把一格写成两种东西，都不该等于「什么都没改」。

从 2.47 起这里装着两层，因为它们是同一个问题的两半：**这一格里写的是谁**（键名）和
**这一格里写的是个什么东西**（值的形状）。分开装在两个模块里时，`src/parse/local.py`
要读值的形状就得 `import src.cli`，而 `src.cli` 已经 import 了它 —— 循环。
这一层从 `src/cli.py` 原样搬过来（209 行、一个字没改，计划书 §2.47 记着怎么量的）。

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

值的形状是同一个病的另一半，2.44/2.46/2.47 各量了一份配置：`str(x.get("k"))` 那一句
**几乎总能出一个值**，所以「台名排成两条」会变成一串列表字面量进表，`enabled: "false"`
会读成「开」，`priority: 1.5` 会砍成 1。四个助手（`text_value` / `flag_value` /
`order_value` / `date_value`）收的是**值**，不是字典 —— 键名字面量必须留在调用处，
否则下面 `reads()` 那道漂移闸量不到谁在被读（2.44、2.46 各验过一格）。

为什么不是「一律停下来」：配置里本来就有一批**故意写给人看**的键（`note`、`added`、
`version` 的注释位），它们没有代码读是设计，不是漏。一律停下来等于逼人为每句注释开证明。
所以只有「近似命中一个会改行为的键」才致命 —— 那种样子最像笔误，而笔误改的是表上的内容。

上游 m3u 的属性名**不归这里管**：那是别人写的文件，各家自定义属性一大堆
（`user-agent`、`catchup`、`tvg-shift`…），全报出来只会把该看的那一行淹没。
"""

from __future__ import annotations

import difflib
import ast
import datetime as dt
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


_YAML_SHAPE = {"list": "一个列表", "dict": "一个字典（多缩进的那几行被并进来的？）",
               "int": "一个数字", "float": "一个小数", "str": "一行字符串"}
_FLAG_WORDS = {"true": True, "false": False, "yes": True, "no": False,
               "on": True, "off": False, "1": True, "0": False}
# 「没写这一格」和「写了个空值」是两件事，而 `d.get("k")` 把它们都读成 `None`。
# 所以下面这几个助手的调用处传一个哨兵当 `.get()` 的默认值，助手才分得开这两种：
# **没写** = 用默认值，**写了没填** = 停下来问。2.46 量出来的不是哲学：
# `enabled:` 空着在 `config/sources.yaml` 那一侧的老读法里是「关」（那条源整个不进表），
# 在 `config/epg.yaml` 那一侧是「开」—— 同一个空位两种相反下场，猜是不能猜的。
_NOT_SET = object()
# 2.44 那两句原话，原样搬出来当 `text_value()` 的默认值：节目单那几处调用不传参数，
# 报错一个字都不该变（`text_value` 的第三格 doctest 把整句钉住，就是钉这一件事）。
_ADDRESS_ADVICE = ("要写两条就分成 `url` 和 `backup_url`；要在一条里换行写，行首得加 `- `。"
                   "这一格是当地址用的，安静地 str() 一下只会让它冒充成一个能用的："
                   "非空，于是节目单算「启用」，而它又不以 http 开头。")


# 这两个助手**收的是值**（`cfg.get("url")`），不收字典。
# 为什么：让调用方写 `text_value(cfg, "url", …)` 更顺，但那样 `.get("url")` 就从
# `load_epg_config` 的源码里消失了，而 2.42 那道闸量的正是「这段代码里字面读了哪些键」——
# 名单上五格全部会变成「说是行为键却没读它」，闸当场瞎。改成收值，读取留在原处，
# 闸一个字都不用动。（2.44 的改错实验里这一格是反着验的。）
def shape_word(got) -> str:
    """YAML 把那一格读成了什么形状 —— 一句人话；认不出的退回类型名。

    和 `why_dead()` 同一条规矩：宁可旧说法，不编新说法。

    这一格是 2.44 量出来才补的：`epg:` 直接写成一行地址时，报出来的是「读出来是**一个 str**」——
    那句话要人自己去翻译「str = 一行字符串」，而它下面紧跟着的「不是一组键」才是重点。

    >>> shape_word(["a"]), shape_word({"a": 1}), shape_word(8080), shape_word(1.5)
    ('一个列表', '一个字典（多缩进的那几行被并进来的？）', '一个数字', '一个小数')
    >>> shape_word("https://x/e.xml")
    '一行字符串'
    >>> shape_word(b"x")
    '一个 bytes'
    """
    return _YAML_SHAPE.get(type(got).__name__, f"一个 {type(got).__name__}")


def text_value(got, *, where: str, key: str, what: str = "一串地址",
               advice: str = _ADDRESS_ADVICE) -> str:
    """配置里那一格取成一句字符串；不是字符串就停下来，别 `str()` 成一个看着能用的样子。

    `config/epg.yaml` 的 `url:` 后面直接换行缩进，YAML 就把它读成**列表**，而 2.44 之前
    两处读法都是同一句 `str(cfg.get("url") or "").strip()` —— 列表被洗成 `"['a', 'b']"`：
    非空（于是 `enabled` 判成 True），又不以 http 开头（于是 `epg_header_url()` 交出空串）。
    当场跑出来的后果不在屏幕上，在表的第一行：出表退 0、那行写着
    「节目单（缓存（epg.xml），['a', 'b']）」，而 `aptv.m3u`/`hunan.m3u` 头部的
    `x-tvg-url` **整行没了** —— 电视从此没有节目单可拉，这个数还跟出口、网络都没关系。

    认不出来的类型退回类型名（和 `why_dead()` 同一个规矩：宁可旧说法，不编新说法）。

    这一层**不分**「没写这一格」和「写了个空值」（`flag_value`、`order_value` 分了）：
    两种读出来都是空串，交给调用方那句「缺 `url` / 缺 `id`」，而那句话对两种情况都说得准。
    开关那一格说不准 —— `enabled:` 空着到底是开还是关，只能问人，所以那里停。

    `what`/`advice` 是 2.46 加的两个参数，为的是让 `config/sources.yaml` 的 `url`、`id`
    共用这一层而**不必共用同一句建议**：那一份的 `url` 挂两条地址的修法和节目单不是一回事，
    而 `id` 根本不是地址。两个默认值就是 2.44 那两句原话，所以节目单那几处一个字都没变
    （下面第三格整句打出来，就是钉这一件事）。

    >>> text_value("  https://x/e.xml  ", where="epg 段", key="url")
    'https://x/e.xml'
    >>> text_value(None, where="epg 段", key="url")     # 没写这一格 / `url:` 空着：交给默认值
    ''
    >>> try:
    ...     text_value(["a", "b"], where="epg 段", key="url")
    ... except ValueError as e:
    ...     print(str(e))
    epg 段 的 `url` 读出来是一个列表（['a', 'b']），不是一串地址 —— 要写两条就分成 `url` 和 `backup_url`；要在一条里换行写，行首得加 `- `。这一格是当地址用的，安静地 str() 一下只会让它冒充成一个能用的：非空，于是节目单算「启用」，而它又不以 http 开头。
    >>> try:
    ...     text_value(20260923, where="epg 段", key="cache")
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    epg 段 的 `cache` 读出来是一个数字（20260923），不是一串地址
    >>> try:
    ...     text_value({"a": 1}, where="epg 段", key="url")
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    epg 段 的 `url` 读出来是一个字典（多缩进的那几行被并进来的？）（{'a': 1}），不是一串地址
    >>> try:                                   # 2.46：`id` 那一格不是地址，换成一句人话
    ...     text_value(123, where="第 1 条源", key="id", what="一串文字", advice="给它加引号")
    ... except ValueError as e:
    ...     print(str(e))
    第 1 条源 的 `id` 读出来是一个数字（123），不是一串文字 —— 给它加引号
    """
    if got is None:
        return ""
    if isinstance(got, str):
        return got.strip()
    raise ValueError(f"{where} 的 `{key}` 读出来是{shape_word(got)}（{got!r}），不是{what} —— {advice}")


def flag_value(got, *, where: str, key: str, default: bool = True) -> bool:
    """`enabled` 那一类：只认「是/否」那几种写法，别拿 Python 的真假去猜人的意思。

    同一句 `bool(cfg.get("enabled", True))` 在 2.44 之前会把 `enabled: "false"` 读成
    **真** —— 引号一打，「关掉节目单」这件事就反了。而这正是这个项目反复钉的那一种：
    `enabled` 写歪等于没写（2.39），而 `enabled: "false"` 比写歪更糟，它长得完全正确。

    YAML 自己认的 `yes`/`no`/`on`/`off` 到 pyyaml 手里已经是布尔了；这里补的是**人加了引号**、
    或者写成 `0`/`1` 的那几种。认不出来的照样停下来 —— 「到底开没开」不该有个模糊答案。

    `None` 和 `_NOT_SET` 在 2.46 之前是同一件事（都走「交给默认值」），量过才发现不是：
    没写这一格 = 按默认，写了 `enabled:` 而后面空着 = 一个谁都没填过的格子，
    而老读法在两份配置里把它猜成相反的两个意思（`_NOT_SET` 上面那段记着是哪两种）。

    >>> flag_value(False, where="epg 段", key="enabled")
    False
    >>> flag_value("false", where="epg 段", key="enabled")      # 加引号的那个：照人的意思办
    False
    >>> flag_value("TRUE", where="epg 段", key="enabled")
    True
    >>> flag_value(_NOT_SET, where="epg 段", key="enabled")      # 没写这一格 = 默认开
    True
    >>> flag_value(_NOT_SET, where="epg 段", key="enabled", default=False)
    False
    >>> flag_value(0, where="epg 段", key="enabled")             # 裸数字：只有 0/1 算话
    False
    >>> try:                                 # 2.46：写了个空值，不猜
    ...     flag_value(None, where="epg 段", key="enabled")
    ... except ValueError as e:
    ...     print(str(e))
    epg 段 的 `enabled` 写了却没填值 —— 开关这一格要的是 `true` 或 `false`，空着既不算是也不算是否
    >>> try:
    ...     flag_value("off-ish", where="epg 段", key="enabled")
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[1])
    这一格是个开关，而 bool('false') 是真：加引号反而关不掉，写成一个认不出的词更不能替你猜
    """
    if got is _NOT_SET:
        return default
    if got is None:
        raise ValueError(f"{where} 的 `{key}` 写了却没填值 —— "
                         "开关这一格要的是 `true` 或 `false`，空着既不算是也不算是否")
    if isinstance(got, bool):
        return got
    if isinstance(got, int) and got in (0, 1):
        return bool(got)
    if isinstance(got, str) and got.strip().lower() in _FLAG_WORDS:
        return _FLAG_WORDS[got.strip().lower()]
    raise ValueError(f"{where} 的 `{key}` 是 {got!r}，是/否之外的写法认不了 —— "
                     "这一格是个开关，而 bool('false') 是真：加引号反而关不掉，"
                     "写成一个认不出的词更不能替你猜")


def order_value(got, *, where: str, key: str, default: int) -> int:
    """`priority` 那一类：要一个整数，越小越靠前；认不出来就停下来，别 `int()` 出一个数继续跑。

    `int(s.get("priority", i + 1))` 是这三格里最安静的一处，因为它**几乎总能出一个数**：
    `priority: 1.5` 砍成 1，`priority: true` 也算 1（2.46 实测），`priority: 前三` 抛的那句是
    `invalid literal for int() with base 10: '前三'` —— 一路 ValueError 被 `cmd_build` 接住了，
    屏幕上剩下这句英文，而它说的是「int() 失败」，不是「你把序号写成了中文」。
    更糟的是 `priority:` 空着：`int(None)` 是 **TypeError**，不在接住的那两种里 ——
    实测退 1、stdout 一个字都没有、`--out` 那个目录根本没建，屏幕上只有一段 traceback。

    收 `_NOT_SET`（没写这一格）时退回**书写顺序**，那是这份配置自己的规矩（`priority` 的
    注释写着「默认按本节书写顺序」），不是猜。带引号的 `"2"` 认：它和 `2` 是同一个数，
    这里没有「加引号就反了」那件事（那是开关那一格，见 `flag_value`）。

    >>> order_value(_NOT_SET, where="第 1 条源", key="priority", default=4)     # 没写 = 书写顺序
    4
    >>> order_value(2, where="第 1 条源", key="priority", default=4)
    2
    >>> order_value("2", where="第 1 条源", key="priority", default=4)           # 带引号的同一个数
    2
    >>> order_value(" -3 ", where="第 1 条源", key="priority", default=4)        # 手工源那种负数也认
    -3
    >>> try:
    ...     order_value(1.5, where="第 1 条源", key="priority", default=4)
    ... except ValueError as e:
    ...     print(str(e))
    第 1 条源 的 `priority` 是 1.5，是一个小数 —— 这一格是排序用的整数，而 `int(1.5)` 会把它砍成 1：安静地换掉你写的那个数，第一线是谁就跟着变了
    >>> try:                              # `priority: true` 老读法算 1，因为它「是个数」
    ...     order_value(True, where="第 1 条源", key="priority", default=4)
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    第 1 条源 的 `priority` 是 True，不是一个整数
    >>> try:
    ...     order_value("前三", where="第 1 条源", key="priority", default=4)
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    第 1 条源 的 `priority` 是 '前三'，不是一个整数（读出来是一行字符串）
    >>> try:
    ...     order_value(None, where="第 1 条源", key="priority", default=4)
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    第 1 条源 的 `priority` 写了却没填值
    """
    if got is _NOT_SET:
        return default
    if got is None:
        raise ValueError(f"{where} 的 `{key}` 写了却没填值 —— "
                         "这一格要的是整数（越小越靠前），空着不算「按默认」：`int(None)` 是 TypeError，"
                         "而它不在 `cmd_build` 接住的那两种里，整场出表连一句人话都不会有")
    if isinstance(got, bool):
        raise ValueError(f"{where} 的 `{key}` 是 {got!r}，不是一个整数 —— 排序权重得写数字"
                         "（`priority: 3`），而 `int(True)` 是 1：老读法把它当成「排第一」")
    if isinstance(got, int):
        return got
    if isinstance(got, str) and got.strip().lstrip("-+").isdigit():
        return int(got.strip())
    if isinstance(got, float):
        raise ValueError(f"{where} 的 `{key}` 是 {got!r}，是一个小数 —— 这一格是排序用的整数，"
                         f"而 `int({got})` 会把它砍成 {int(got)}：安静地换掉你写的那个数，"
                         "第一线是谁就跟着变了")
    raise ValueError(f"{where} 的 `{key}` 是 {got!r}，不是一个整数（读出来是{shape_word(got)}） —— "
                     "这一格要写排序用的整数（`priority: 3`，越小越靠前）")


# 日期这一层是 2.47 补的，来自 `config/sources_local.yaml` 的 `expires`：五格里只有它
# 「写坏了不丢东西」—— 丢的是一次本该发生的停用。老读法 `str(raw.get("expires") or "")`
# 后面紧跟着 `if exp:`，于是**认不出来**（没补零 / 带时刻 / 排成两条 / 写成 `true`）
# 全都读成同一句话：「这条线路永不过期」。27 格普查里最狠的一格是
# `expires: 2026-01-05 12:00:00` —— 那是一个已经过去 8 个月的日子，老读法印一句
# 「按未过期处理」就把它放进了表。
def date_value(got, *, where: str, key: str) -> str:
    """`expires` 那一类：要么是一个日期，要么这一格不算数；认不出来就停下来，别按「永不过期」放过。

    交给调用方的一律是 `YYYY-MM-DD` 那种字符串（`is_expired()` 的入参形状因此一个字都没改），
    而 YAML 自己把补零的日期变成 `date` 对象、把带时刻的变成 `datetime` —— 那两种都读得出
    人来意，就地取那一天，不要求人补引号。

    **这一格是 2.46 那条「没写 / 写了没填 要分开」的例外，而且是那份配置自己定的规矩**：
    `config/sources_local.yaml` 第 18 行写着「expires 有效期，留空表示不限」，
    而真配置那一条就是 `expires: ""`（第一版 `date_value` 按「写了没填就停下来」处理，
    当场把家里唯一那条手工线路从表里删掉了 —— 计划书 §2.47 记着这一格）。
    所以「没写」「空着」「`null`」「一对引号」四种读法在这里合并成一个意思：不设停用日。
    合并的前提是这句话**写在文件里**，不是猜出来的：换一份没这么写的配置，这一格不能照抄。

    >>> date_value(_NOT_SET, where="第 1 条", key="expires")      # 整格没写 = 不设停用日
    ''
    >>> date_value(None, where="第 1 条", key="expires")          # 写了没填：这份文件说算「不限」
    ''
    >>> date_value("", where="第 1 条", key="expires")            # 真配置用的就是这一种
    ''
    >>> date_value("  ", where="第 1 条", key="expires")          # 引号里塞了空格，同一件事
    ''
    >>> date_value("2026-12-31", where="第 1 条", key="expires")
    '2026-12-31'
    >>> date_value(" 2026-12-31 ", where="第 1 条", key="expires")    # 首尾空白不是另一件事
    '2026-12-31'
    >>> date_value(dt.date(2026, 1, 5), where="第 1 条", key="expires")   # YAML 自己变的 date
    '2026-01-05'
    >>> date_value(dt.datetime(2026, 1, 5, 12, 0), where="第 1 条", key="expires")  # 带时刻：取那天
    '2026-01-05'
    >>> date_value("20260105", where="第 1 条", key="expires")     # 3.11 起 ISO 紧凑写法也认
    '2026-01-05'
    >>> try:                                    # 没补零：3.12 的 fromisoformat 也不认
    ...     date_value("2026-1-5", where="第 1 条", key="expires")
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    第 1 条 的 `expires` 是 '2026-1-5'，读不出一个日期
    >>> try:                          # 写成人话：老读法印一句告警，然后永远进表
    ...     date_value("停用前看一眼", where="第 1 条", key="expires")
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    第 1 条 的 `expires` 是 '停用前看一眼'，读不出一个日期
    >>> try:                                    # 开关当日期：老读法 str(True) 得 'True'
    ...     date_value(True, where="第 1 条", key="expires")
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    第 1 条 的 `expires` 是 True，是一个开关，不是一个日期
    >>> try:                              # 排成两条：老读法洗成 "[datetime.date(...), ...]"
    ...     date_value([dt.date(2026, 1, 5), dt.date(2026, 12, 31)],
    ...                where="第 1 条", key="expires")
    ... except ValueError as e:
    ...     print(str(e).split(" —— ")[0])
    第 1 条 的 `expires` 读出来是一个列表（[datetime.date(2026, 1, 5), datetime.date(2026, 12, 31)]），不是一个日期
    >>> try:                              # 裸数字：不猜它是 2026 年 1 月 5 日还是别的
    ...     date_value(20260105, where="第 1 条", key="expires")
    ... except ValueError as e:
    ...     print("要写成人话" if "`YYYY-MM-DD`" in str(e) else str(e))
    要写成人话
    """
    if got is _NOT_SET or got is None or (isinstance(got, str) and not got.strip()):
        # 「没写」与「写了没填」在这里合并，是那份文件的第 18 行说的，不是猜的（见上面那段）
        return ""
    if isinstance(got, bool):
        raise ValueError(f"{where} 的 `{key}` 是 {got!r}，是一个开关，不是一个日期 —— "
                         "停用日要写 `YYYY-MM-DD`；这条线路若是停用，就写成已经过去的那一天，"
                         "或者把它从名单里删掉")
    if isinstance(got, dt.datetime):
        return got.date().isoformat()
    if isinstance(got, dt.date):
        return got.isoformat()
    if isinstance(got, str):
        text = got.strip()
        for parse in (dt.date.fromisoformat, dt.datetime.fromisoformat):
            try:
                parsed = parse(text)
            except ValueError:
                continue
            return parsed.date().isoformat() if isinstance(parsed, dt.datetime) else parsed.isoformat()
        raise ValueError(f"{where} 的 `{key}` 是 {text!r}，读不出一个日期 —— 这一格认 `YYYY-MM-DD`"
                         "（月、日各写两位，`2026-1-5` 那种没补零的读不出），"
                         "而老读法在这里只印一句「按未过期处理」，等于把已经过去的日子当成没写")
    raise ValueError(f"{where} 的 `{key}` 读出来是{shape_word(got)}（{got!r}），不是一个日期 —— "
                     "一格里只放一个停用日（`YYYY-MM-DD`，比如 `expires: 2026-12-31`）；"
                     "裸数字请先想清楚是不是要它当文字，排成两条那是要写两件事，分开写")


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
