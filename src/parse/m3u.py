"""m3u / m3u8 播放列表解析。

把上游各种写法的 m3u 解析成统一的 Entry 结构，供后续匹配、检测、输出使用。
解析过程保持宽容：缺属性、属性顺序不同、注释行夹杂都不应导致条目丢失。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator

_ATTR_RE = re.compile(r'([\w][\w-]*)="([^"]*)"')
_DURATION_RE = re.compile(r'^-?[\d.]+')


@dataclass(slots=True)
class Entry:
    """一条频道线路。同一个频道可以有多条 Entry（不同 url）。"""

    name: str                      # 展示名（来自 EXTINF 逗号后的标题，回退到 tvg-name）
    url: str
    tvg_id: str = ""
    tvg_name: str = ""
    logo: str = ""
    group: str = ""
    source: str = ""               # 来自哪个上游（sources.yaml 里的 id）
    seq: int = 0                   # 在上游文件中的原始顺序，用于稳定排序
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Playlist:
    """一个 m3u 文件的解析结果。"""

    entries: list[Entry] = field(default_factory=list)
    x_tvg_url: str = ""            # 头部声明的 EPG 地址
    skipped: int = 0               # 被跳过的畸形行数

    def __len__(self) -> int:
        return len(self.entries)


def _split_attrs_and_title(body: str) -> tuple[str, str]:
    """把 `:-1 tvg-id="x" ... group-title="g",频道名` 切成属性段与标题段。

    属性值一律以 `"` 结束，所以最后一个 `",` 之后就是标题。
    这样能避免标题本身含逗号时被截断。

    上游也有完全不带属性的写法 `#EXTINF:-1 ,CCTV1`（湖南移动/联通源就是这种），
    此时按第一个逗号切分。

    >>> _split_attrs_and_title('-1 tvg-id="hunan" group-title="湖南",湖南卫视')
    ('-1 tvg-id="hunan" group-title="湖南"', '湖南卫视')
    >>> _split_attrs_and_title('-1 ,CCTV1')
    ('-1 ', 'CCTV1')
    """
    idx = body.rfind('",')
    if idx >= 0:
        return body[: idx + 1], body[idx + 2 :]
    idx = body.find(",")
    if idx >= 0:
        return body[:idx], body[idx + 1 :]
    return body, ""


def parse_m3u(text: str, source: str = "") -> Playlist:
    """解析 m3u 文本。

    容错点：
    - `#EXTINF` 缺 tvg-name 时回退用标题，缺标题时回退用 tvg-name
    - `#EXTGRP` 单独成行时作为 group 的补充来源
    - 连续多条注释行（如 `#EXTVLCOPT`）不影响取 url
    """
    playlist = Playlist()
    pending: dict[str, str] | None = None
    extgrp: str = ""
    seq = 0

    def flush(url: str) -> None:
        nonlocal seq
        assert pending is not None
        attrs = pending
        name = attrs.get("title") or attrs.get("tvg-name") or attrs.get("tvg-id") or ""
        if not name or not url:
            playlist.skipped += 1
            return
        known = {"tvg-id", "tvg-name", "tvg-logo", "group-title", "title"}
        playlist.entries.append(
            Entry(
                name=name.strip(),
                url=url.strip(),
                tvg_id=attrs.get("tvg-id", "").strip(),
                tvg_name=attrs.get("tvg-name", "").strip(),
                logo=(attrs.get("tvg-logo") or "").strip(),
                group=(attrs.get("group-title") or extgrp or "").strip(),
                source=source,
                seq=seq,
                extras={k: v for k, v in attrs.items() if k not in known},
            )
        )
        seq += 1

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.upper().startswith("#EXTM3U"):
            if 'x-tvg-url="' in line:
                playlist.x_tvg_url = line.split('x-tvg-url="', 1)[1].split('"', 1)[0]
            continue

        if line.startswith("#EXTINF"):
            body = line[len("#EXTINF") :].lstrip(":")
            attrs_part, title = _split_attrs_and_title(body)
            duration = _DURATION_RE.match(attrs_part)
            attrs = dict(_ATTR_RE.findall(attrs_part))
            if duration and duration.group(0).startswith("-"):
                # 负时长在 IPTV 列表里极常见，不视为错误
                pass
            attrs["title"] = title.strip()
            pending = attrs
            continue

        if line.startswith("#EXTGRP"):
            extgrp = line.split(":", 1)[1].strip() if ":" in line else ""
            continue

        if line.startswith("#"):
            continue

        if pending is None:
            # 没有 EXTINF 裸 url（txt 风格），当作无名条目交给 txt 解析器处理
            playlist.skipped += 1
            continue

        flush(line)
        pending = None
        extgrp = ""

    return playlist


def iter_urls(entries: Iterable[Entry]) -> Iterator[str]:
    """去重后依次产出 url，保持首次出现顺序。"""
    seen: set[str] = set()
    for e in entries:
        if e.url not in seen:
            seen.add(e.url)
            yield e.url
