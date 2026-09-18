"""把一条上游线路归位到目标频道 / 分组。

匹配优先级（与 config/channels.yaml 顶部注释一致）：
  1. channels 的 name / aliases 命中 -> 用配置里的标准名与分组
  2. 未命中则看 upstream_group_map，按上游分组整体归类
  3. 都没有 -> 判为未匹配，丢弃并计入报告
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.match.normalize import normalize
from src.parse.m3u import Entry


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
    """加载 channels.yaml 并提供归位查询。"""

    def __init__(self, cfg: dict[str, Any]):
        self.groups: dict[str, dict[str, Any]] = {
            g["id"]: {"title": g["title"], "order": i}
            for i, g in enumerate(cfg.get("groups") or [])
        }
        self.group_map: dict[str, str] = dict(cfg.get("upstream_group_map") or {})
        self.excluded_groups: set[str] = set(cfg.get("excluded_groups") or [])
        self.exclude_res = [re.compile(p, re.I) for p in (cfg.get("exclude_patterns") or [])]

        self.rules: list[ChannelRule] = []
        self._by_key: dict[str, ChannelRule] = {}
        for i, raw in enumerate(cfg.get("channels") or []):
            rule = ChannelRule(
                name=raw["name"],
                group=raw["group"],
                tvg_id=(raw.get("tvg_id") or "").strip(),
                order=i,
            )
            if rule.group not in self.groups:
                raise ValueError(f"频道 {rule.name} 引用了未定义的分组 {rule.group}")
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


def load_index(path: str | Path) -> ChannelIndex:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ChannelIndex(cfg)
