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

from src.keys import check_keys, check_version
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
        for i, g in enumerate(groups):
            if not isinstance(g, dict) or not g.get("id") or not g.get("title"):
                raise ValueError(f"groups 第 {i + 1} 条不是「id + title」那种字典（现在读到的："
                                 f"{str(g)[:40] if isinstance(g, dict) else type(g).__name__}）")
            for warn in check_keys(g, where=f"groups 第 {i + 1} 条", known=GROUP_KEYS,
                                   notes=GROUP_NOTES):
                print(f"⚠️ {warn}", file=sys.stderr)
        self.groups: dict[str, dict[str, Any]] = {
            g["id"]: {"title": g["title"], "order": i}
            for i, g in enumerate(groups)
        }
        self.group_map: dict[str, str] = dict(cfg.get("upstream_group_map") or {})
        self.excluded_groups: set[str] = set(cfg.get("excluded_groups") or [])
        self.exclude_res = [re.compile(p, re.I) for p in (cfg.get("exclude_patterns") or [])]

        raw_channels = cfg.get("channels") or []
        if not isinstance(raw_channels, list):
            raise ValueError(f"channels 读出来是 {type(raw_channels).__name__}，应该是列表")
        if not raw_channels:
            raise ValueError("channels 一条规则都没有 —— 表上的台全部来自这份名单，"
                             "沿用它等于出一张空表")
        self.rules: list[ChannelRule] = []
        self._by_key: dict[str, ChannelRule] = {}
        for i, raw in enumerate(raw_channels):
            if not isinstance(raw, dict):
                raise ValueError(f"channels 第 {i + 1} 条不是字典（是 {type(raw).__name__}）")
            missing = [k for k in ("name", "group") if not str(raw.get(k) or "").strip()]
            if missing:
                raise ValueError(f"channels 第 {i + 1} 条缺 {' 和 '.join(missing)}"
                                 f"（现在只有 {sorted(raw)}），补上再出表")
            for warn in check_keys(raw, where=f"channels 第 {i + 1} 条（{raw['name']}）",
                                   known=RULE_KEYS, notes=RULE_NOTES):
                print(f"⚠️ {warn}", file=sys.stderr)
            rule = ChannelRule(
                name=raw["name"],
                group=raw["group"],
                tvg_id=(raw.get("tvg_id") or "").strip(),
                order=i,
            )
            if rule.group not in self.groups:
                raise ValueError(f"频道 {rule.name}（channels 第 {i + 1} 条）引用了未定义的分组 "
                                 f"{rule.group} —— groups 里现在有："
                                 f"{'、'.join(self.groups) or '一个分组都没定义'}")
            for alias in [rule.name, *(raw.get("aliases") or [])]:
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
