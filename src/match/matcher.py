"""把一条上游线路归位到目标频道 / 分组。

匹配优先级（与 config/channels.yaml 顶部注释一致）：
  1. channels 的 name / aliases 命中 -> 用配置里的标准名与分组
  2. 未命中则看 upstream_group_map，按上游分组整体归类
  3. 都没有 -> 判为未匹配，丢弃并计入报告
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from src.keys import (_NOT_SET, check_keys, check_version, shape_word, str_list_value,
                      str_map_value, text_value)
from src.match.normalize import normalize
from src.parse.m3u import Entry

# 这份表允许的键（`src/keys.py` 的守卫用）。写成一份配置一段，是因为「谁被读」是读它
# 的那段代码的事 —— 放远了就会漂：漂掉的不是注释，是「改了这行到底有没有生效」。
CHANNELS_TOP_KEYS = ["version", "groups", "upstream_group_map", "excluded_groups",
                     "exclude_patterns", "channels"]
CHANNELS_TOP_NOTES = {
    "channels": "表上有哪几个台、每个台认哪些名字",
    "groups": "有哪几组、组与组在订阅里的先后",
    "upstream_group_map": "名单没写到的上游分组，整组归给谁",
    "excluded_groups": "哪些上游分组一律不要",
    "exclude_patterns": "名字带这些词的条目一律不要",
}
GROUP_KEYS = ["id", "title"]
GROUP_NOTES = {
    "id": "channels 靠它引用这一组（写歪就是「引用了未定义的分组」）",
    "title": "电视上那一组显示成什么名",
}
RULE_KEYS = ["name", "group", "aliases", "tvg_id"]
RULE_NOTES = {
    "name": "这条规则管的是哪个台",
    "group": "它归到哪一组",
    "aliases": "上游那些花名认不认得它 —— 少一个别名就安静地少对上一批线路",
    "tvg_id": "电子节目单把它对到谁",
}

# 2.48：每格单独一句「怎么改」（§2.46/§2.47 各记过一次：抄一句通用建议等于把人赶到错的那一行）。
# 这一族的坏法与 `sources.yaml` 不同：代码不 `str()` 洗值，而是**把值直接交给 stdlib 遍历**
# （`for p in patterns`、`set(groups)`、`*aliases`、`unicodedata.normalize`），
# 所以一行字符串会被逐字符摊开、一个数字会当场崩、一个 0 会被说成「缺这一格」。
# 下面每一句都带着普查里量到的那个后果，不写「请检查格式」。
_ALIASES_ADVICE = ("这一格是上游可能出现的其他写法，得写成列表（`aliases: [湖南经视, 经视]`，"
                   "或者一行一条 `- 湖南经视`）。2.48 实测：`aliases: 湖南经视` 会被逐个字符读，"
                   "于是 湖/南/经/视 四个单字进了匹配表 —— 归一化后只剩一个「湖」的上游条目"
                   "会被并进这个台，而本来那个别名反而没人认得（表上只是少了几条线路，看不出来）")
_PATTERNS_ADVICE = ("这一格是名称黑名单，每一条是一段正则片段，得写成列表（`exclude_patterns: [测试, STB]`，"
                    "或一行一条）。2.48 实测：`exclude_patterns: STB` 会被逐个字符读成 "
                    "`S`、`T`、`B` 三条正则，于是名字里带任何一个 s/t/b 的上游条目一律被丢掉"
                    "（`CCTV-5试验` 含 `T` 也算命中），而屏幕上什么都不会说")
_EXCLUDED_ADVICE = ("这一格是「整组丢掉」的上游分组名，得写成列表（一行一条 `- 🕘️更新时间`）。"
                    "2.48 实测：写成一行会被逐个字符读成六个字符（含 emoji 的变体选择符），"
                    "于是那一条伪频道不再被丢掉，会跟着上游整组进表")
_MAP_ADVICE = ("这一格是「上游分组名: 本文件的分组 id」的一对一，得写成缩进的对（"
               "`📺央视频道: cctv` 一行一对）。2.48 实测：键写成数字永远匹配不上"
               "（那一组的台安静地不进表），值写成两条则是构造通过、用到那一刻才崩")
_NAME_ADVICE = ("这一格是这个台的标准名，表上显示的就是它，得写成一行文字（`name: 湖南卫视`）。"
                "它是拿去匹配的那把钥匙：2.48 实测 `name:` 排成两条时老读法直接崩在 "
                "`normalize()` 上（一段 traceback，`cmd_build` 接不住），而 R08 量到 `name: 0` "
                "会被说成「缺 name」—— 明明写了，只是不是文字")
_GROUP_ADVICE = ("这一格是 `groups` 里定义过的分组 id（`group: hunan_local`），得写成一行文字。"
                 "2.48 实测 `group: 0` 会被说成「缺 group」（其实写了），R10 量到排成两条 "
                 "会崩在「这一组在不在 groups 里」那一步 —— 而这一句本来要说的只是 id 对不对得上")
_TVG_ADVICE = ("这一格是电子节目单里这个台的名字（`tvg_id: hunan`），得写成一行文字；"
               "留空就是沿用上游那个 id（这份文件顶部写着这条规矩）。2.48 实测：写成数字"
               "或两条时老读法崩在 `.strip()` 上，而 `0123` 那种带前导零的会被 YAML 按八进制读成 83")
_ID_ADVICE = ("这一格是分组的内部名字，`channels` 靠它引用这一组，得写成一行文字（`id: hunan_local`）。"
              "2.48 实测：写成两条会当场崩在「拿它当字典的键」那一步（unhashable），"
              "G02 量到 `id: 0` 会被说成「这条不是 id+title 那种字典」—— 它是那种字典，只是这一格写歪了")
_TITLE_ADVICE = ("这一格是电视上那一组显示出来的名字，得写成一行文字（`title: \"📍 湖南本地\"`）。"
                 "2.48 实测 `title: 123` 一路无人拦，最后原样写进每张表的 `group-title` 里")


@dataclass(slots=True)
class ChannelRule:
    name: str
    group: str
    tvg_id: str
    keys: set[str] = field(default_factory=set)
    order: int = 0


@dataclass(slots=True)
class MatchResult:
    group: str          # groups.id
    name: str           # 输出用的标准频道名
    tvg_id: str
    matched_by: str     # alias | group-map
    order: int          # 组内排序用


class ChannelIndex:
    """加载 channels.yaml 并提供归位查询。

    一个小配置表就够说明三条规则（别名命中 > 整组映射 > 丢弃）：

    >>> cfg = {
    ...     "groups": [{"id": "cctv", "title": "📺 央视"}],
    ...     "upstream_group_map": {"📺央视频道": "cctv"},
    ...     "excluded_groups": ["🕘️更新时间"],
    ...     "exclude_patterns": ["测试"],
    ...     "channels": [
    ...         {"name": "CCTV-5体育", "group": "cctv", "aliases": ["CCTV-5"]},
    ...         {"name": "CCTV-5+赛事", "group": "cctv", "tvg_id": "CCTV-5+", "aliases": ["CCTV-5+"]},
    ...     ],
    ... }
    >>> idx = ChannelIndex(cfg)

    带加号和不带加号是两个台，各归各的标准名：

    >>> idx.resolve(Entry(name="CCTV-5+", url="u", group="📺央视频道")).name
    'CCTV-5+赛事'
    >>> idx.resolve(Entry(name="CCTV5", url="u")).name
    'CCTV-5体育'

    tvg_id 写死了就不跟着上游走，没写死的沿用上游的：

    >>> idx.resolve(Entry(name="CCTV5+", url="u")).tvg_id
    'CCTV-5+'
    >>> idx.resolve(Entry(name="CCTV-5", url="u", tvg_id="CCTV-5")).tvg_id
    'CCTV-5'

    名单里没有的，只有整组映射能接住；映射也没有就丢弃：

    >>> idx.resolve(Entry(name="CCTV-3", url="u", group="📺央视频道")).matched_by
    'group-map'
    >>> idx.resolve(Entry(name="CCTV-3", url="u")) is None
    True
    >>> idx.is_excluded(Entry(name="湖南卫视测试", url="u"))
    True
    >>> idx.is_excluded(Entry(name="湖南卫视", url="u", group="🕘️更新时间"))
    True

    键名写歪停下来（2.39）。这一份最疼的一种是 `alias` 少了那个 s：规则照建、台照出，
    只是那批花名再也没人认得 —— 报告里显示成「这个台只有 1 条线路」，看着像上游就没给。
    `name` / `group` 漏写由前面那句「缺 name」接住（它会把读到的键列出来），
    守卫管的是这种**写了、但写歪了才安静**的。

    >>> bad = {"channels": [{"name": "湖南卫视", "group": "weisheng",
    ...                      "alias": ["湖南卫视高清"]}],
    ...        "groups": [{"id": "weisheng", "title": "🌏 卫视"}]}
    >>> try:
    ...     ChannelIndex(bad)
    ... except ValueError as e:
    ...     print(str(e))
    channels 第 1 条（湖南卫视）：`alias` 我们不读，最像是 `aliases` 写歪了 —— 它管的是上游那些花名认不认得它 —— 少一个别名就安静地少对上一批线路

    顶层 `channel:` 少了 s 以前是「一条规则都没有」—— 那句话现在还在，但守卫先说得更准。

    >>> try:
    ...     ChannelIndex({"channel": [{"name": "湖南卫视", "group": "weisheng"}]})
    ... except ValueError as e:
    ...     print("`channel`" in str(e) and "最像是" in str(e))
    True

    值的形状（2.48）。这一族和 `sources.yaml` 那一种不一样：这里没有 `str()` 洗值，
    代码把值直接交给 stdlib 遍历（`for p in patterns`、`set(groups)`、`*aliases`），
    所以「少写一个方括号」不是洗成一个假字符串，而是**逐字符摊开**。
    下面三格就是普查里那三格零告警的（`/tmp/c248.py` 的 C02 / C06 / R01）：

    >>> def one(**kw):                 # 一份什么都对的底本，只换要问的那一格
    ...     cfg = {"groups": [{"id": "g", "title": "G"}],
    ...            "channels": [{"name": "湖南卫视", "group": "g", "aliases": ["湖南经视"]}]}
    ...     cfg.update(kw)
    ...     return cfg
    >>> def err(cfg):                  # 拿到那句人话；没报错就返回空串，断言照样是红的
    ...     try:
    ...         ChannelIndex(cfg)
    ...     except ValueError as e:
    ...         return str(e)
    ...     return ""
    >>> def diag(cfg):                 # 只要「诊断」那半句。「怎么改」那半句里会出现
    ...     return err(cfg).split(" —— ")[0]   # 「缺 name」这种词，拿整句去断言会把
    ...                                        # 「已经不说它了」断成「还在说它」——
    ...                                        # 这一格是第一遍跑红才暴露的（见 §2.48 记的那条）
    >>> "读成 3 条 ['S', 'T', 'B']" in err(one(exclude_patterns="STB"))   # 一条黑名单变三条单字正则
    True
    >>> "读成 6 条 ['🕘', '️', '更', '新', '时', '间']" in err(one(excluded_groups="🕘️更新时间"))
    True
    >>> print(err(one(channels=[{"name": "湖南卫视", "group": "g", "aliases": "湖南经视"}]))
    ...       .split(" —— ")[0])
    channels 第 1 条 的 `aliases` 读出来是一行字符串（'湖南经视'），不是一条一条列出来的名单

    「没写这一格」「写了没填」「排成一个空列表」在老读法里是同一件事（`or []`），
    现在分开：没写 = 没有，空列表 = 显式的「一条都不要」，写了没填 = 停下来问
    （这一格合并的前提和 2.47 的 `expires` 一样，是**文件里写着的话** ——
    `config/channels.yaml` 那句 `# ---- 名称黑名单，命中即丢 ----` 说的是命中即丢，
    空列表按字面就是「谁都不丢」，而「写了没填」不是任何人表过态的意思）。

    >>> "没填" in err(one(exclude_patterns=None))
    True
    >>> ChannelIndex(one(exclude_patterns=[])).exclude_res
    []
    >>> "exclude_patterns" in err(one())                        # 整格没写：一句话都没有
    False

    坏正则也在这格上（`测试(` 那种）：老读法抛的是 `re.error`，一段没有「第几条」的崩栈。

    >>> print(err(one(exclude_patterns=["测试("])).split("——")[0].strip())
    频道配置 的 `exclude_patterns` 第 1 条 '测试(' 不是一段能用的正则片段（missing ), unterminated subpattern，位置 2）

    一对一那格（`upstream_group_map`）两侧都问：键写成数字永远匹配不上（普查 C14），
    值排成两条更阴 —— 构造通过，**用到那一刻**才崩（普查 C10，崩在匹配算完之后）。

    >>> "第 1 对的键" in err(one(upstream_group_map={123: "g"}))
    True
    >>> "第 1 对的值" in err(one(upstream_group_map={"📺央视频道": ["g", "h"]}))
    True

    误诊那一族（普查 G02 / R08 / R09）：写了、但不是文字，以前统一报「缺这一格」。

    >>> "缺 name" in diag(one(channels=[{"name": 0, "group": "g"}]))
    False
    >>> "读出来是一个数字（0）" in diag(one(channels=[{"name": 0, "group": "g"}]))
    True
    >>> "缺 group" in diag(one(channels=[{"name": "x", "group": 0}]))
    False
    >>> "缺 group" in diag(one(channels=[{"name": "x"}]))         # 真漏写的还报「缺」，那句没动
    True

    「这是谁」那一半（`what`）也要每格各说一句 —— 只断言「怎么改」会在 `name` 这格漏掉：
    改错实验 M10 把 `name` 的 `what=` 摘掉后，九格断言全绿（那句还带着自己的 advice，
    只是「不是…」后面跟的是默认的「一串文字」）。这一格是 M10 逼出来的。

    >>> "不是一个台的名字" in err(one(channels=[{"name": ["a", "b"], "group": "g"}]))
    True
    >>> "不是电子节目单里这个台的名字" in err(one(channels=[{"name": "x", "group": "g", "tvg_id": ["a"]}]))
    True
    >>> "不是一个分组 id（`groups` 里定义过的那种" in err(one(channels=[{"name": "x", "group": 0}]))
    True
    >>> "不是一个分组 id（一行文字）" in err(one(groups=[{"id": ["a"], "title": "T"}]))
    True
    >>> "不是电视上那一组显示的名字" in err(one(groups=[{"id": "g", "title": 1}]))
    True

    `groups` 那一条「写了、但是空的」仍旧报「缺」，只是这一句要报得出缺的是哪一半、
    两个都缺时说得清是两个（普查 G03：以前 `title:` 空着会被上面那句误诊卡住）。

    >>> "groups 第 1 条缺 title" in diag(one(groups=[{"id": "g", "title": ""}]))
    True
    >>> "缺 id 和 title" in err(one(groups=[{"id": "", "title": None}]))
    True

    九个「怎么改」各说一句，而且每一句都在被钉住的通路上（2.47 那条规矩：
    只有走得到的分支才算量过）：

    >>> probes = [(one(exclude_patterns="STB"), _PATTERNS_ADVICE),
    ...           (one(excluded_groups="x"), _EXCLUDED_ADVICE),
    ...           (one(channels=[{"name": "x", "group": "g", "aliases": "y"}]), _ALIASES_ADVICE),
    ...           (one(upstream_group_map="g"), _MAP_ADVICE),
    ...           (one(channels=[{"name": ["a", "b"], "group": "g"}]), _NAME_ADVICE),
    ...           (one(channels=[{"name": "x", "group": 0}]), _GROUP_ADVICE),
    ...           (one(channels=[{"name": "x", "group": "g", "tvg_id": ["a"]}]), _TVG_ADVICE),
    ...           ({"groups": [{"id": ["a"], "title": "T"}],
    ...            "channels": [{"name": "x", "group": "g"}]}, _ID_ADVICE),
    ...           ({"groups": [{"id": "g", "title": 1}],
    ...            "channels": [{"name": "x", "group": "g"}]}, _TITLE_ADVICE)]
    >>> [advice[:8] in err(cfg) for cfg, advice in probes]
    [True, True, True, True, True, True, True, True, True]
    >>> len({advice for _, advice in probes})                    # 九句互不相同，不是一句通用建议
    9

    真在用的那一份过得过这道闸（闸不能只挡临时字典；96 个台、181 个匹配键）：

    >>> real = Path(__file__).resolve().parents[2] / "config" / "channels.yaml"
    >>> live = load_index(real)
    >>> len(live.rules), sum(len(r.keys) for r in live.rules), live.group_title("hunan_local")
    (96, 181, '📍 湖南本地')

    三份名单和 `__init__` 读的那批键对得上吗（2.42）—— 这份配置的名单是三层的
    （顶层 / `groups` 每条 / `channels` 每条），所以并成一次问。

    >>> from src.keys import drift_of
    >>> drift_of(ChannelIndex.__init__, known=CHANNELS_TOP_KEYS + GROUP_KEYS + RULE_KEYS,
    ...          notes={**CHANNELS_TOP_NOTES, **GROUP_NOTES, **RULE_NOTES})
    []
    """

    def __init__(self, cfg: dict[str, Any]):
        # 这份配置决定表上**有哪些台**，所以它读不成形状就不能往下走。
        # 以前只信它是对的：顶层写成列表 → `AttributeError: 'list' object has no
        # attribute 'get'`，一条规则漏写 group → 裸 `KeyError: 'group'`，
        # 整份是空的 → 静默 0 条规则、出一张空表（2.37 逐个实测）。
        if cfg is None:
            raise ValueError("这份配置是空的（或者只有注释）—— 表上的台全部来自 channels，"
                             "一条规则都没有就一个台都没有")
        if not isinstance(cfg, dict):
            raise ValueError(f"配置读出来是 {type(cfg).__name__}，不是「groups: / channels:」"
                             "那种结构，这一份不能当频道配置用")
        check_version(cfg, where="频道配置")
        for warn in check_keys(cfg, where="频道配置", known=CHANNELS_TOP_KEYS,
                               notes=CHANNELS_TOP_NOTES):
            print(f"⚠️ {warn}", file=sys.stderr)
        groups = cfg.get("groups") or []
        if not isinstance(groups, list):
            raise ValueError(f"groups 读出来是 {type(groups).__name__}，应该是列表")
        # 2.48：这一层以前只有一个问题 ——「是不是 id + title 那种字典」，于是三种不同的事
        # 挤进同一句话：`id: 0`（写了，但不是文字）、`title:`（写了没填）、整条不是字典。
        # 前两种被说成「不是那种字典」是**误诊**（普查 G02/G04），第三种才是。现在分开问。
        checked: list[tuple[str, str]] = []
        for i, g in enumerate(groups):
            at = f"groups 第 {i + 1} 条"
            if not isinstance(g, dict):
                raise ValueError(f"{at}不是「id + title」那种字典（现在读到的："
                                 f"{type(g).__name__}）")
            for warn in check_keys(g, where=at, known=GROUP_KEYS, notes=GROUP_NOTES):
                print(f"⚠️ {warn}", file=sys.stderr)
            gid = text_value(g.get("id"), where=at, key="id",
                             what="一个分组 id（一行文字）", advice=_ID_ADVICE)
            title = text_value(g.get("title"), where=at, key="title",
                               what="电视上那一组显示的名字（一行文字）", advice=_TITLE_ADVICE)
            if not gid or not title:
                lack = " 和 ".join(n for n, v in (("id", gid), ("title", title)) if not v)
                raise ValueError(f"{at}缺 {lack}（现在读到的：{str(g)[:40]}）—— "
                                 "groups 这一层每条都得有 id 和 title")
            checked.append((gid, title))
        self.groups: dict[str, dict[str, Any]] = {
            gid: {"title": title, "order": i}
            for i, (gid, title) in enumerate(checked)
        }
        # 这三格都是「一条一条列出来」的名单，老读法一个形状都不问，直接把值交给 stdlib 遍历
        # （`dict(...)`、`set(...)`、`for p in ...`），所以写成一行会被逐个字符读 ——
        # 普查 C02/C06/C14 三格量的都是这个，而且全部零告警。理由在每句 advice 里。
        self.group_map: dict[str, str] = str_map_value(
            cfg.get("upstream_group_map", _NOT_SET), where="频道配置",
            key="upstream_group_map", advice=_MAP_ADVICE)
        self.excluded_groups: set[str] = set(str_list_value(
            cfg.get("excluded_groups", _NOT_SET), where="频道配置",
            key="excluded_groups", advice=_EXCLUDED_ADVICE))
        self.exclude_res = []
        for j, pat in enumerate(str_list_value(
                cfg.get("exclude_patterns", _NOT_SET), where="频道配置",
                key="exclude_patterns", advice=_PATTERNS_ADVICE), 1):
            # 形状之外还有一层：这一格的每一条是**正则**，`测试(` 那种坏正则老读法当场抛
            # `re.error`（普查 C11：`error: missing ), unterminated subpattern`，
            # 一段没有文件名、没有「第几条」的崩栈）。
            try:
                self.exclude_res.append(re.compile(pat, re.I))
            except re.error as e:
                raise ValueError(f"频道配置 的 `exclude_patterns` 第 {j} 条 {pat!r} "
                                 f"不是一段能用的正则片段（{e.msg}，位置 {e.pos}）—— "
                                 "这一格按正则匹配，坏一条会让整份名单读不进去；"
                                 "若只想要「名字里带这几个字」，写成普通字就行，别带 ( ) [ ] 这些") from e

        raw_channels = cfg.get("channels") or []
        if not isinstance(raw_channels, list):
            raise ValueError(f"channels 读出来是 {type(raw_channels).__name__}，应该是列表")
        if not raw_channels:
            raise ValueError("channels 一条规则都没有 —— 表上的台全部来自这份名单，"
                             "沿用它等于出一张空表")
        self.rules: list[ChannelRule] = []
        self._by_key: dict[str, ChannelRule] = {}
        for i, raw in enumerate(raw_channels):
            at = f"channels 第 {i + 1} 条"
            if not isinstance(raw, dict):
                raise ValueError(f"{at}不是字典（是 {type(raw).__name__}）")
            # 2.48：这四格以前一个形状都不问，值直接交给 stdlib 用 ——
            # `name`/`aliases` 进 `normalize()` 与 `*` 展开（普查 R01/R03/R04/R06/R07 五种崩法），
            # `tvg_id` 进 `.strip()`（R11/R12），`group` 进 `in self.groups`（R10 unhashable），
            # 而 0 那种「写了但不是文字」全被说成「缺这一格」（R08/R09）。
            # `tvg_id` 与 `aliases` 各有一处合并：留空 = 沿用上游的 id（这份文件顶部写着），
            # 整格没写 = 没有别名（真配置里就有一两条这么写）—— 两种都不是错。
            name = text_value(raw.get("name"), where=at, key="name",
                              what="一个台的名字（一行文字）", advice=_NAME_ADVICE)
            group = text_value(raw.get("group"), where=at, key="group",
                               what="一个分组 id（`groups` 里定义过的那种，一行文字）",
                               advice=_GROUP_ADVICE)
            tvg = text_value(raw.get("tvg_id"), where=at, key="tvg_id",
                             what="电子节目单里这个台的名字（一行文字）", advice=_TVG_ADVICE)
            aliases = str_list_value(raw.get("aliases", _NOT_SET), where=at, key="aliases",
                                     advice=_ALIASES_ADVICE)
            missing = [k for k, v in (("name", name), ("group", group)) if not v]
            if missing:
                raise ValueError(f"{at}缺 {' 和 '.join(missing)}"
                                 f"（现在只有 {sorted(raw)}），补上再出表")
            for warn in check_keys(raw, where=f"{at}（{name}）",
                                   known=RULE_KEYS, notes=RULE_NOTES):
                print(f"⚠️ {warn}", file=sys.stderr)
            rule = ChannelRule(
                name=name,
                group=group,
                tvg_id=tvg,
                order=i,
            )
            if rule.group not in self.groups:
                raise ValueError(f"频道 {rule.name}（channels 第 {i + 1} 条）引用了未定义的分组 "
                                 f"{rule.group} —— groups 里现在有："
                                 f"{'、'.join(self.groups) or '一个分组都没定义'}")
            for alias in [rule.name, *aliases]:
                key = normalize(alias)
                if key:
                    rule.keys.add(key)
                    exist = self._by_key.get(key)
                    if exist and exist.name != rule.name:
                        raise ValueError(f"别名 {alias!r} 同时指向 {exist.name} 和 {rule.name}")
            self.rules.append(rule)
            self._by_key.update(dict.fromkeys(rule.keys, rule))

    # ---- 查询 ----

    def is_excluded(self, entry: Entry) -> bool:
        if entry.group in self.excluded_groups:
            return True
        text = f"{entry.name} {entry.tvg_name}"
        return any(rx.search(text) for rx in self.exclude_res)

    def resolve(self, entry: Entry) -> MatchResult | None:
        """尝试归位。返回 None 表示不纳入输出。"""
        if self.is_excluded(entry):
            return None

        for probe in (entry.name, entry.tvg_name, entry.tvg_id):
            rule = self._by_key.get(normalize(probe))
            if rule:
                return MatchResult(
                    group=rule.group,
                    name=rule.name,
                    tvg_id=rule.tvg_id or entry.tvg_id or rule.name,
                    matched_by="alias",
                    order=rule.order,
                )

        target = self.group_map.get(entry.group)
        if target:
            return MatchResult(
                group=target,
                name=entry.name,
                tvg_id=entry.tvg_id or entry.name,
                matched_by="group-map",
                order=self.groups[target]["order"] * 1000 + entry.seq,
            )

        return None

    def group_title(self, group_id: str) -> str:
        return self.groups[group_id]["title"]

    def lacking_groups(self, needed: Iterable[str]) -> list[str]:
        """返回 `needed` 里这份配置没定义的分组，顺序照 `needed`。

        `build` 用它提前问一句「hunan.m3u 要的那几个分组在不在」——
        不在就要在**写盘之前**说，而不是盖完 aptv.m3u 再崩在 `group_title()`（2.37）。

        >>> idx = ChannelIndex({"groups": [{"id": "a", "title": "A"}],
        ...                     "channels": [{"name": "x", "group": "a"}]})
        >>> idx.lacking_groups(["a"])
        []
        >>> idx.lacking_groups(["a", "hunan_local", "changsha"])
        ['hunan_local', 'changsha']
        >>> idx.lacking_groups([])
        []
        """
        return [g for g in needed if g not in self.groups]


def load_index(path: str | Path) -> ChannelIndex:
    """读一份频道配置，坏形状一律抛 `ValueError`（带文件名的那句人话），不抛裸崩栈。

    两条来路都在这里收口：文件本身读不进来（不在、是目录、不是 UTF-8）原来是裸 `OSError`，
    现在换成同样的 `ValueError`；内容读进来了但不是那个结构，交给 `ChannelIndex` 判。
    统一成 `ValueError` 是有意的 —— 调用方只管接一种，就不会有一种形状漏出去变成崩栈。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "c.yaml"
    ...     _ = p.write_text("groups:\\n  - {id: hunan, title: 湖南}\\n"
    ...                      "channels:\\n  - {name: 湖南卫视, group: hunan}\\n", encoding="utf-8")
    ...     idx = load_index(p)
    ...     len(idx.rules), idx.group_title("hunan")
    (1, '湖南')

    空文件、顶层是列表、漏写字段、没写 channels —— 一律 `ValueError`，不是裸崩栈：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     shapes = (("空文件", ""), ("顶层是列表", "- a"), ("漏写 group", "channels:\\n"
    ...               "  - {name: x}"), ("没写 channels", "groups: []"))
    ...     for name, body in shapes:
    ...         p = Path(d) / (name + ".yaml")
    ...         _ = p.write_text(body, encoding="utf-8")
    ...         try:
    ...             load_index(p)
    ...             print(name, "不报")
    ...         except ValueError:
    ...             print(name, "ValueError")
    ...         except Exception as e:                       # noqa: BLE001
    ...             print(name, "还是崩栈", type(e).__name__)
    空文件 ValueError
    顶层是列表 ValueError
    漏写 group ValueError
    没写 channels ValueError

    句子是给人看的，带着第几条和现在读到的是什么：

    >>> try:
    ...     ChannelIndex({"channels": [{"name": "x"}]})
    ... except ValueError as e:
    ...     print(e)
    channels 第 1 条缺 group（现在只有 ['name']），补上再出表
    >>> try:
    ...     ChannelIndex({"groups": [{"id": "a", "title": "A"}],
    ...                   "channels": [{"name": "x", "group": "b"}]})
    ... except ValueError as e:
    ...     print(e)
    频道 x（channels 第 1 条）引用了未定义的分组 b —— groups 里现在有：a

    连文件都没摸到（不在、是目录）也说人话 —— 原来这里是 `[Errno 2] No such file or
    directory: '/…/channels.yaml'`，那句 errno 是给日志看的，不是给出表的人看的：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     for name, arg in (("不在", Path(d) / "gone.yaml"), ("是目录", Path(d))):
    ...         try:
    ...             load_index(arg)
    ...         except ValueError as e:
    ...             print(name, str(e).split(" —— ")[0])
    不在 这份频道配置不在
    是目录 这份频道配置读不进来（Is a directory）
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ValueError(f"这份频道配置不在 —— {p} 这个路径下没有这个文件") from e
    except UnicodeDecodeError as e:
        raise ValueError(f"这份频道配置不是 UTF-8 文本（{e.reason}），读不了 —— {p}") from e
    except OSError as e:
        why = getattr(e, "strerror", None) or type(e).__name__
        raise ValueError(f"这份频道配置读不进来（{why}） —— {p}") from e
    try:
        cfg = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"这份频道配置不是能读的 YAML"
                         f"（{str(e).strip().splitlines()[0]}） —— {p}") from e
    return ChannelIndex(cfg)
