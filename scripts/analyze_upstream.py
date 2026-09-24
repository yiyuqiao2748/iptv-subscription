"""开发期工具：摸清上游 m3u 的真实结构，为 config/channels.yaml 提供依据。

用法：
    python scripts/analyze_upstream.py [m3u路径或URL ...]
    python scripts/analyze_upstream.py --doctest    # 跑它自己的用例

默认分析 调研样本/iptv-api_gd_result.m3u。
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows 控制台默认 GBK，打印分组名里的 emoji 会直接抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.parse.m3u import parse_m3u  # noqa: E402

DEFAULT = ROOT / "调研样本" / "iptv-api_gd_result.m3u"
KEYWORDS = ("湖南", "长沙", "金鹰", "株洲", "湘潭", "岳阳", "衡阳", "常德",
            "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "邵阳", "湘西")


def load(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        import urllib.request

        req = urllib.request.Request(path_or_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    return Path(path_or_url).read_text(encoding="utf-8", errors="replace")


def split_flag(argv: list[str]) -> tuple[bool, list[str]]:
    r"""把 `--doctest` 从「要分析的表」里分出去 —— 它不是一个文件路径。

    09-25 01:31:36 实测过没有这一支的时候会发生什么：`--doctest` 被当成一份 m3u 递进
    `load`，摊出 **1151 字节的 `FileNotFoundError` traceback、退 1**。而 1 在这个项目里
    写着「量到了、结果有毛病」（2.62 那三档），于是这一条命令凭空指控了一份不存在的表。
    同一种病在 `lean_playlist`（2.65）与 `epg_check`／`table_drift`（2.63）上都量过。

    >>> split_flag(["a.m3u", "--doctest", "b.m3u"])
    (True, ['a.m3u', 'b.m3u'])
    >>> split_flag(["a.m3u"])
    (False, ['a.m3u'])
    >>> split_flag([])
    (False, [])
    >>> split_flag(["--doctest"])          # 只有开关：剩下的路要交给用例那一条
    (True, [])
    """
    rest = [a for a in argv if a != "--doctest"]
    return len(rest) != len(argv), rest


def read_note(target: str, err: OSError) -> str:
    """读不到一份表时的那一句人话。

    >>> read_note("没有这份.m3u", FileNotFoundError(2, "No such file"))
    '读不到 没有这份.m3u：[Errno 2] No such file'
    """
    return f"读不到 {target}：{err}"


def tally(read: int, missed: int) -> int:
    """读了 N 份、漏了 M 份，该退几 —— 按 2.62 那三档。

    >>> tally(3, 0)     # 全读到
    0
    >>> tally(0, 2)     # 一份都没读到：什么都没量到
    2
    >>> tally(1, 1)     # 读到一份、漏掉一份：干成了事，但结果有毛病
    1
    """
    if not read:
        return 2 if missed else 0
    return 1 if missed else 0


def main(argv: list[str]) -> int:
    r"""把几份 m3u 的结构摊成一屏：条目数、分组、含湖南地名的、重复 url。

    这一件是开发期工具，09-25 之前**一条用例都没有** —— 而收集器那一行
    `· analyze_upstream 0 个用例` 和旁边的 `· src.cli 174 个用例` 长得一模一样（2.68）。
    下面头一格拿一份手写的表跑它自己，钉的是三处最容易写错的：分组要按**条数**排、
    同一条 url 被两个频道名复用只算 1 处重复、畸形行要进 `跳过` 而不是把整轮带走。
    第二格钉的是「递进去的表读不到」那一档：它以前是一段 traceback。

    >>> import contextlib, io, tempfile
    >>> from pathlib import Path
    >>> m3u = "\n".join([
    ...     "#EXTM3U",
    ...     '#EXTINF:-1 tvg-name="c1" group-title="央视",CCTV1', "http://e/a.ts",
    ...     '#EXTINF:-1 tvg-name="c2" group-title="卫视",湖南卫视', "http://e/b.ts",
    ...     '#EXTINF:-1 tvg-name="c2" group-title="卫视",湖南卫视', "http://e/a.ts",
    ...     "不是条目的一行", ""])
    >>> d = tempfile.TemporaryDirectory()
    >>> p = Path(d.name) / "样本.m3u"; _ = p.write_text(m3u, encoding="utf-8")
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):
    ...     rc = main([str(p)])
    >>> rc
    0
    >>> [l for l in buf.getvalue().splitlines() if "条目 " in l or "重复 url" in l]
    ['条目 3 条，跳过 1 行，EPG=无', '--- 重复 url 数：1（同一条线路被多个频道名复用）']
    >>> ls = buf.getvalue().splitlines()            # 分组那一档：2 条的那个排在 1 条的前面
    >>> ls.index('      2  卫视') < ls.index('      1  央视')
    True
    >>> _ = d.cleanup()
    >>> buf = io.StringIO()
    >>> with contextlib.redirect_stdout(buf):
    ...     rc = main(["这一份表不存在.m3u"])
    >>> rc                                          # 一份都没读到：什么都没量到，不是「都对」
    2
    >>> buf.getvalue().startswith("读不到 ") and "Traceback" not in buf.getvalue()
    True
    """
    targets = argv or [str(DEFAULT)]
    read = missed = 0
    for target in targets:
        try:
            text = load(target)
        except OSError as err:                      # 路径、权限、目录 —— 一律一句人话，不摊栈
            print(read_note(target, err))
            missed += 1
            continue
        read += 1
        pl = parse_m3u(text, source=Path(target).stem)
        print(f"\n{'=' * 60}\n{target}\n条目 {len(pl)} 条，跳过 {pl.skipped} 行，EPG={pl.x_tvg_url or '无'}")

        groups = Counter(e.group for e in pl.entries)
        print(f"\n--- 分组（共 {len(groups)} 个）---")
        for g, n in groups.most_common():
            print(f"  {n:5d}  {g or '(无分组)'}")

        by_group: dict[str, set[str]] = defaultdict(set)
        for e in pl.entries:
            by_group[e.group].add(e.name)

        print("\n--- 含湖南地名的条目：名称 -> 所属分组 ---")
        hits: dict[str, list[str]] = defaultdict(list)
        for name, grp in [(e.name, e.group) for e in pl.entries]:
            if any(k in name for k in KEYWORDS):
                hits[name].append(grp)
        for name in sorted(hits):
            print(f"  {name:<16} {sorted(set(hits[name]))}")

        print("\n--- 央视/卫视频道组内的名称（前 40）---")
        for g in by_group:
            if "央视" in g or "卫视" in g:
                names = sorted(by_group[g])
                print(f"  [{g}] 共 {len(names)} 个频道名：")
                print("    " + "、".join(names[:40]))

        urls = Counter(e.url for e in pl.entries)
        print(f"\n--- 重复 url 数：{sum(1 for c in urls.values() if c > 1)}（同一条线路被多个频道名复用）")
    return tally(read, missed)


if __name__ == "__main__":
    # `--doctest` 不是一份表：先把它分出去，剩下的才交给 `main`（2.68，见 `split_flag` 那段实测）。
    wants_tests, tables = split_flag(sys.argv[1:])
    if wants_tests:
        from run_doctests import run_own
        raise SystemExit(run_own(sys.modules["__main__"]))
    raise SystemExit(main(tables))
