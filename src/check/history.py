"""把每轮实测攒成主机履历：让「这个主机上一轮全灭／只有录像」不随 probe.json 被覆盖而消失。

动机很具体。`probe.json` 只存最后一次实测，于是有两种情况在漏：

1. 跑 `build`（不带 `--verify`）时手里一点实测信息都没有，上一轮已经确认整族失效的
   主机（`stream1.freetv.fun` 0/35）又会大摇大摆排到频道第一位，电视上就是超时。
   离线生成不是罕见路径 —— 上游抓取失败、代理抽风、只想改改 `channels.yaml` 重出表，都会走它。
2. 一轮实测说了不算。中转类主机今天 42/42、明天 0/42 都出现过，只凭一次就把谁判死太武断。

所以这里只存「每轮实测的主机汇总」这一份小数据（`data/output/probe-history.jsonl`，
一行一轮），它同时服务两件事：给离线生成当缓存的判据（`dead_streak`），
和给报告算趋势（连着几轮全灭的才建议从 `sources.yaml` 里划掉）。

2.15 又补了第二种「上一轮看清了」的东西：**连得上不等于播得对**。一条线路 L1 通、L2 有分片，
内容却可能是几个小时前就录好的整档节目（`vod`），或者列表永远不动的残留推流（L3 的 `stuck`）。
这类主机在 `--verify` 那一轮是被降过档的，可离线重出一次表，降档知识就整个丢了 ——
和延迟那个坑同一类，而且更坏：超时只会让人困惑，循环录像会让人以为「湖南卫视就是这个」。
于是主机行里多记两个计数（`vod`/`stuck`），判据说「上一轮这个主机一条真直播都没有」。
`stuck` 由 L3 单独回写（`record_roll()`）：主流程只做 L1+L2，因为 L3 每条要等一个间隔。

纪律一条，不能让步：**只信同一测量点、且体检没报警的那些轮**。
代理 TUN 一开，出口变成境外机房、DNS 换成 fake-IP，那轮对国内源全是假阴性
（计划书 2.8/2.10）。这种轮次照样落盘（历史是原始数据，留着好看变化），
但 `trustworthy()` 会把它挡在判据之外，否则东京出口测出来的表会把家里能播的主机全判死。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

# L3 的两个方向：滚起来才算直播，不动或干脆是 ENDLIST 的录像都不算。
# 其余结论（dead / master）说明不了内容，回填时一律忽略。
ROLL_LIVE = "rolling"
ROLL_DEAD = ("stuck", "vod")


@dataclass(slots=True)
class HostRep:
    """一个主机族在可信历史里的履历。"""

    host: str
    runs: int             # 出现过它的可信轮数
    ok_runs: int          # 其中至少有一条线路能播的轮数
    total: int            # 最近一轮里它挂了几条线路
    ok_last: int          # 最近一轮里通了几条
    best_ms: int          # 最近一轮的最好延迟，0 = 没通过过
    last_at: str
    dead_streak: int      # 从最近一轮往回数，连着全灭的轮数
    # 下面三个是 2.15 加的「内容」维度：连得上不等于播得对。
    # 默认 0 是有意的 —— 履历制之前的那些轮没有这两个字段，
    # 不能因为它们没记就回头把人家判成录像台。
    vod_last: int = 0     # 最近一轮里 L2 判为循环录像（vod / master:vod）的条数
    stuck_last: int = 0   # 其中 L3 隔间隔重取后列表不动的条数（L2 看着像直播）
    fake_streak: int = 0  # 连着几轮「通了的全是录像/不动」，一条真直播都没有
    # 2.17 加：这个主机族是哪些上游贡献的（sources.yaml 的 id）。放最后并且给默认值，
    # 老履历里没有这个字段 —— 不能因为 2.16 之前没记来源就把那些轮一笔笔算错。
    srcs: tuple[str, ...] = ()


def should_merge(prev_at: str, new_at: str, minutes: int = 30) -> bool:
    """两轮间隔太短就当成同一轮的重复跑，合并而不是追加。

    不合并的话，调代码时连着跑三次 `build --verify` 会被历史当成「三轮独立观测」，
    一次抖动就被当成三次一致结论 —— 恰恰是历史最想防的那种误判。

    >>> should_merge("2026-09-21T13:00:40+08:00", "2026-09-21T13:12:01+08:00")
    True
    >>> should_merge("2026-09-21T13:00:40+08:00", "2026-09-21T19:00:40+08:00")
    False
    >>> should_merge("乱码", "2026-09-21T13:00:40+08:00")      # 读不懂就不敢合并
    False
    """
    try:
        a = datetime.fromisoformat(prev_at)
        b = datetime.fromisoformat(new_at)
    except (TypeError, ValueError):
        return False
    if a.tzinfo is None or b.tzinfo is None:
        return False
    return abs((b - a).total_seconds()) < minutes * 60


def trustworthy(run: dict, current_egress: str) -> bool:
    """这一轮的数能不能当判据：测量点得是现在这一个，且当时体检没报警。"""
    if not current_egress:
        return False
    if run.get("warnings"):
        return False
    return str(run.get("egress", "")) == current_egress


def current_egress(hint: str, runs: list[dict]) -> str:
    """本轮的测量点是谁。

    正常情况下取 `egress_hint()` 的现测结果。取不到（断网、ipinfo 抽风）时退回
    「最近一轮体检没报警的那次的出口」，而不是干脆不用历史 —— 否则真断网那次
    离线生成反而退回没有判据的状态，把已知失效的主机又摆回第一位。
    退回值只用于比对历史，不会冒充本轮出口写进 probe.json。

    >>> runs = [{"egress": "119.39.40.124 CN", "warnings": []},
    ...         {"egress": "tokyo JP", "warnings": ["TUN 已开启"]}]
    >>> current_egress("1.2.3.4 CN", runs)          # 现测优先
    '1.2.3.4 CN'
    >>> current_egress("", runs)                    # 退回最近一轮可信出口
    '119.39.40.124 CN'
    >>> current_egress("", [{"egress": "tokyo", "warnings": ["TUN"]}])   # 没有可信轮就不猜
    ''
    """
    if hint:
        return hint
    for run in reversed(runs):
        if not run.get("warnings") and run.get("egress"):
            return str(run["egress"])
    return ""


def untrusted_runs(runs: list[dict], *, current_egress: str = "") -> list[dict]:
    """被排除在判据之外的轮次，报告里要说清楚排除了几轮、为什么。

    >>> untrusted_runs([{"egress": "U", "warnings": []}, {"egress": "T", "warnings": []}],
    ...                current_egress="U") == [{"egress": "T", "warnings": []}]
    True
    """
    return [r for r in runs if not trustworthy(r, current_egress)]


def live_count(row: dict) -> int:
    """这一轮里这个主机有几条线路是「真直播」：通了的减去录像和列表不动的。

    >>> live_count({"ok": 3, "vod": 1, "stuck": 0})
    2
    >>> live_count({"ok": 3, "vod": 0, "stuck": 3})      # L2 以为全是直播，L3 验出全不动
    0
    >>> live_count({"ok": 3})                            # 老履历没记内容 → 不猜，按直播算
    3
    >>> live_count({"ok": 2, "vod": 3})                  # 数字对不上也不会给负数
    0
    """
    return max(int(row.get("ok") or 0)
               - int(row.get("vod") or 0)
               - int(row.get("stuck") or 0), 0)


def only_vod(row: dict) -> bool:
    """这一轮里这个主机是不是「通了的全是录像」—— 一条真直播都没出。

    和 `dead_streak` 是两回事：dead 是连不上，这条是连得上、有内容、但内容不是直播。

    >>> only_vod({"ok": 3, "vod": 3, "stuck": 0})
    True
    >>> only_vod({"ok": 3, "vod": 0, "stuck": 3})
    True
    >>> only_vod({"ok": 3, "vod": 1, "stuck": 0})        # 还剩一条是活的，不冤枉整族
    False
    >>> only_vod({"ok": 0, "vod": 0})                    # 整族连不上，归 dead_streak 管
    False
    >>> only_vod({"ok": 42})                             # 没有内容字段：一律不判
    False
    """
    return live_count(row) == 0 and (int(row.get("vod") or 0)
                                     + int(row.get("stuck") or 0)) > 0


def reputation(runs: list[dict], *, current_egress: str = "") -> dict[str, HostRep]:
    """按主机汇总可信轮次。runs 是历史里按时间正序的轮记录（最新在末尾）。

    >>> r = lambda at, egress, hosts, warns=None: {
    ...     "at": at, "egress": egress, "warnings": warns or [], "hosts": hosts}
    >>> h = lambda name, total, ok, **kw: {"host": name, "scope": "public",
    ...                                    "total": total, "ok": ok, "best_ms": 300, **kw}
    >>> runs = [r("2026-09-20T10:00:00+08:00", "UNICOM",
    ...           [h("dead.one", 3, 0), h("good", 2, 2), h("loop.one", 4, 4, vod=4)]),
    ...         r("2026-09-21T10:00:00+08:00", "UNICOM",
    ...           [h("dead.one", 3, 0), h("loop.one", 4, 4, vod=2, stuck=2)])]
    >>> rep = reputation(runs + [r("2026-09-21T11:00:00+08:00", "TOKYO",
    ...                            [h("tokyo-only", 9, 0)], ["TUN 已开启"])],
    ...                  current_egress="UNICOM")
    >>> sorted(rep)                       # 东京那轮（体检报警）整个不算判据
    ['dead.one', 'good', 'loop.one']
    >>> rep["dead.one"].runs, rep["dead.one"].ok_runs, rep["dead.one"].dead_streak
    (2, 0, 2)
    >>> rep["good"].runs, rep["good"].ok_runs, rep["good"].dead_streak
    (1, 1, 0)
    >>> rep["loop.one"].vod_last, rep["loop.one"].stuck_last, rep["loop.one"].fake_streak
    (2, 2, 2)
    >>> rep["good"].vod_last, rep["good"].stuck_last, rep["good"].fake_streak
    (0, 0, 0)
    >>> rep["dead.one"].last_at       # 取最近一轮的数字，不是第一轮
    '2026-09-21T10:00:00+08:00'
    >>> src = [r("2026-09-20T10:00:00+08:00", "UNICOM",
    ...          [h("shared", 3, 0, srcs=["gd", "local"]), h("old", 1, 1)]),
    ...        r("2026-09-21T10:00:00+08:00", "UNICOM",
    ...          [h("shared", 3, 0, srcs=["gd"])])]
    >>> reputation(src, current_egress="UNICOM")["shared"].srcs    # 两轮来的来源取并集
    ('gd', 'local')
    >>> reputation(src, current_egress="UNICOM")["old"].srcs        # 没记就是没记，不猜
    ()
    >>> reputation(runs)              # 不知道现在在哪测的，就一条都不信
    {}
    """
    acc: dict[str, dict] = {}
    for run in runs:
        if not trustworthy(run, current_egress):
            continue
        for h in run.get("hosts") or []:
            name = str(h.get("host") or "")
            if not name:
                continue
            a = acc.setdefault(name, {"runs": 0, "ok_runs": 0, "streak": 0, "fake": 0,
                                      "srcs": set()})
            a["srcs"] |= {str(s) for s in (h.get("srcs") or []) if str(s)}
            a["runs"] += 1
            if int(h.get("ok") or 0) > 0:
                a["ok_runs"] += 1
                a["streak"] = 0                    # 只要活过一次，连续全灭就断了
            else:
                a["streak"] += 1
            # 录像那档同理：这一轮出过一条真直播，连续「只有录像」就断了
            a["fake"] = a["fake"] + 1 if only_vod(h) else 0
            a["last"] = {"total": int(h.get("total") or 0),
                         "ok": int(h.get("ok") or 0),
                         "best_ms": int(h.get("best_ms") or 0),
                         "vod": int(h.get("vod") or 0),
                         "stuck": int(h.get("stuck") or 0),
                         "at": str(run.get("at") or "")}
    return {name: HostRep(host=name, runs=a["runs"], ok_runs=a["ok_runs"],
                          total=a["last"]["total"], ok_last=a["last"]["ok"],
                          best_ms=a["last"]["best_ms"], last_at=a["last"]["at"],
                          dead_streak=a["streak"], vod_last=a["last"]["vod"],
                          stuck_last=a["last"]["stuck"], fake_streak=a["fake"],
                          srcs=tuple(sorted(a["srcs"])))
            for name, a in acc.items()}


def demote_hosts(rep: dict[str, HostRep]) -> frozenset[str]:
    """离线生成时该往后放的主机：最近一轮可信实测里整族连不上。

    只看「上一轮怎么样」，一张主机的死刑不在这儿判 —— 判死刑要 `blacklist()`。
    这一档只用在**没有本轮实测**的线路上：本轮真测出来能播，就以本轮为准。

    >>> rep = {"a": HostRep("a", 1, 0, 3, 0, 0, "2026-09-21", 1),
    ...        "b": HostRep("b", 1, 1, 3, 2, 300, "2026-09-21", 0),
    ...        "c": HostRep("c", 3, 1, 2, 0, 0, "2026-09-21", 1)}
    >>> sorted(demote_hosts(rep))
    ['a', 'c']
    """
    return frozenset(name for name, r in rep.items() if r.dead_streak >= 1)


def fake_hosts(rep: dict[str, HostRep]) -> frozenset[str]:
    """最近一轮可信实测里「通了的全是录像」的主机：离线生成时别让它占第一线。

    和 `demote_hosts()` 分得开是有意的：全灭的主机电视上是超时，只有录像的主机电视上
    **会出画**，而且是几个钟头前的节目 —— 观感上更接近「这台坏了」而不是「这台没信号」，
    所以要单独一档、单独在报告里点名（计划书 2.11 那条 1259 分片的快手 CDN 录像）。
    同样只看上一轮，同样只作用在本轮没实测的线路上。

    这一档在 2026-09-21 那轮履历上是空的（那轮还没有 `vod`/`stuck` 字段，
    `only_vod()` 一律不判），所以加它不会把已经验过的表改出一个字节。

    >>> mk = lambda n, ok, vod, stuck, fs: HostRep(n, 1, 1, ok, ok, 300, "x", 0,
    ...                                            vod_last=vod, stuck_last=stuck,
    ...                                            fake_streak=fs)
    >>> rep = {h.host: h for h in (mk("loop", 3, 3, 0, 1), mk("mixed", 3, 1, 0, 0),
    ...                           mk("live", 3, 0, 0, 0), mk("stuck", 2, 0, 2, 1))}
    >>> sorted(fake_hosts(rep))
    ['loop', 'stuck']
    """
    return frozenset(name for name, r in rep.items() if r.fake_streak >= 1)


def blacklist(rep: dict[str, HostRep], min_runs: int = 2) -> list[HostRep]:
    """可信历史里从来没活过、且被看过至少两轮的家族 —— 建议从候选里划掉。

    要求两轮是故意的：2026-09-21 那天 `cctvtxyh5c.liveplay.myqcloud.com` 那族腾讯云基准
    从全通掉到整族失效，说明「一轮全灭」真的可能只是上游抽风。

    >>> mk = lambda n, runs, ok_runs: HostRep(n, runs, ok_runs, 3, 0, 0, "x", runs)
    >>> rep = {h.host: h for h in (mk("a", 2, 0), mk("b", 1, 0), mk("c", 3, 1), mk("d", 4, 0))}
    >>> [r.host for r in blacklist(rep)]        # 观测轮数多的排前面：最确定的死刑犯第一个被点名
    ['d', 'a']
    """
    return sorted((r for r in rep.values() if r.runs >= min_runs and not r.ok_runs),
                  key=lambda r: (-r.runs, r.host))


@dataclass(slots=True)
class SourceRep:
    """一个上游源在可信轮次里的账面：它贡献的主机族、线路数、通过情况。"""

    source: str
    hosts: int          # 它贡献（或参与贡献）的主机族数
    runs: int           # 这些主机被可信实测看过几轮（取该源下最大的那个值）
    lines: int          # 最近一轮它挂出来的线路数（共用主机会被两个源各算一次，宁粗不假）
    ok_last: int        # 最近一轮这些线路里通了几条
    dead_hosts: int     # 从来没通过过的主机数（不管看过几轮）
    sentenced: int      # 其中看过 ≥min_runs 轮、因此真被判死刑的
    fake_hosts: int     # 通了但整族只出录像/不动的主机数
    best_ms: int        # 该源最快的一条主机族延迟，0 = 没有通过过的
    shared: int         # 与别的源共用的主机族数（判「划掉这个源会不会连带伤到别人」）


def source_reputation(rep: dict[str, HostRep], *, min_runs: int = 2) -> dict[str, SourceRep]:
    """把主机级履历按上游源摊开 —— 「该划掉谁」从主机那一层升到 sources.yaml 那一层。

    2.16 之前这一步根本做不了：`host_summary()` 只记主机，不记这条地址是从哪个源来的，
    于是报告能说出「`stream1.freetv.fun` 0/36 整族失效」，却说不出「这是 `iptv_api_gd` 塞进来的」。
    现在来源跟着履历一起攒（`HostRep.srcs`），2.16 之前那些轮没记，就单列在 `unattributed` 里，
    不拿猜测充数。

    >>> mk = lambda n, runs, ok_runs, srcs, total=3, best=0: HostRep(
    ...     n, runs, ok_runs, total, 1 if ok_runs else 0, best, "x", 0, srcs=tuple(srcs))
    >>> rep = {"a": mk("a", 2, 0, ["gd", "local"]), "b": mk("b", 3, 2, ["gd"], best=420),
    ...        "c": mk("c", 1, 0, ["legacy"]), "d": HostRep("d", 2, 2, 4, 4, 0, "x", 0,
    ...                                                     fake_streak=2, srcs=("gd",))}
    >>> srs = source_reputation(rep, min_runs=2)
    >>> sorted(srs)                       # `local` 也出来了：它和 gd 共用那一族
    ['gd', 'legacy', 'local']
    >>> srs["local"].hosts, srs["local"].shared, srs["local"].sentenced
    (1, 1, 1)
    >>> srs["gd"].hosts, srs["gd"].lines, srs["gd"].ok_last, srs["gd"].runs
    (3, 10, 5, 3)
    >>> srs["gd"].dead_hosts, srs["gd"].sentenced, srs["gd"].fake_hosts, srs["gd"].shared
    (1, 1, 1, 1)
    >>> srs["gd"].best_ms
    420
    >>> srs["legacy"].hosts, srs["legacy"].sentenced       # 只看过一轮，判不了死刑
    (1, 0)
    """
    acc: dict[str, dict] = {}
    for r in rep.values():
        shared = len(r.srcs) > 1
        for src in r.srcs:
            a = acc.setdefault(src, {"hosts": 0, "runs": 0, "lines": 0, "ok_last": 0,
                                     "dead": 0, "sentenced": 0, "fake": 0, "best": 0,
                                     "shared": 0})
            a["hosts"] += 1
            a["runs"] = max(a["runs"], r.runs)
            a["lines"] += r.total
            a["ok_last"] += r.ok_last
            a["best"] = min((x for x in (a["best"], r.best_ms) if x), default=0)
            a["shared"] += 1 if shared else 0
            if not r.ok_runs:
                a["dead"] += 1
                if r.runs >= min_runs:
                    a["sentenced"] += 1
            if r.fake_streak >= 1:
                a["fake"] += 1
    return {src: SourceRep(source=src, hosts=a["hosts"], runs=a["runs"], lines=a["lines"],
                           ok_last=a["ok_last"], dead_hosts=a["dead"], sentenced=a["sentenced"],
                           fake_hosts=a["fake"], best_ms=a["best"], shared=a["shared"])
            for src, a in acc.items()}


def unattributed_hosts(rep: dict[str, HostRep]) -> int:
    """没记下来源的主机族数（2.16 之前那几轮履历的存量）。报告要如实说出这个窟窿有多大。

    >>> rep = {"a": HostRep("a", 1, 1, 2, 2, 0, "x", 0),
    ...        "b": HostRep("b", 1, 1, 2, 2, 0, "x", 0, srcs=("gd",))}
    >>> unattributed_hosts(rep)
    1
    """
    return sum(1 for r in rep.values() if not r.srcs)


# 判「这个源该不该动」的两条线。为什么是这两个数：APTV 只播第一线，一个源的价值
# 就是「它顶上来的东西能用吗」。可用率低于 1/5 的源，排得越靠前越坑电视；
# 而 4/5 以上全通且快到 500ms 以内的，才是应该往前挪的那一类（计划书 2.10 的延迟分档）。
DROP_RATE = 0.2      # 最近一轮可用率低于这个，且死刑族占多数 → 建议调后 / 关掉
KEEP_RATE = 0.8      # 高于这个且够快 → 建议往前挪
# 往前挪和整个关掉都是「拿这个源换别人」的决定，所以它们要比单纯降档多一点证据：
# 一条线路的源哪怕两轮全通，也不够资格挤到别的源前面去（反过来，一条线路两轮全灭
# 也不该建议把整源关掉 —— 那只会被 MIN_EVIDENCE_LINES 降成「调后」这种可逆的建议）。
MIN_EVIDENCE_LINES = 3


@dataclass(slots=True)
class Suggestion:
    """一条能直接抄进 `config/sources.yaml` 的建议。"""

    source: str
    verdict: str          # drop / demote / promote / keep / thin
    from_prio: int
    to_prio: int          # 与 from_prio 相同 = 不动
    why: str
    enabled: bool = True  # False = 建议整源关掉
    confirmed: bool = True    # False = 只有一轮观测，先别动手

    def yaml_lines(self) -> list[str]:
        """抄进 `sources.yaml` 的那几行（含缩进，直接贴到对应 `- id:` 块里）。

        >>> s = Suggestion("gd", "demote", 3, 5, "最近一轮 4/41 能播，11 族两轮以上全灭")
        >>> print("\\n".join(s.yaml_lines()))
            priority: 5        # 3→5：最近一轮 4/41 能播，11 族两轮以上全灭
        >>> s2 = Suggestion("gd", "keep", 3, 3, "最近一轮 30/40 能播、最快 600ms", confirmed=False)
        >>> print("\\n".join(s2.yaml_lines()))
            priority: 3        # 不动：最近一轮 30/40 能播、最快 600ms  ← 只一轮观测，先别动手
        >>> s3 = Suggestion("gd", "drop", 3, 3, "3 轮 0/41 能播，12 族全灭", enabled=False)
        >>> print("\\n".join(s3.yaml_lines()))
            enabled: false     # 3 轮 0/41 能播，12 族全灭
            priority: 3        # 关掉之后这条留着，方便哪天想复测
        """
        if self.enabled is False:
            return [f"    enabled: false     # {self.why}",
                    f"    priority: {self.to_prio}        # 关掉之后这条留着，方便哪天想复测"]
        tag = (f"{self.from_prio}→{self.to_prio}" if self.to_prio != self.from_prio else "不动")
        tail = "" if self.confirmed else "  ← 只一轮观测，先别动手"
        return [f"    priority: {self.to_prio}        # {tag}：{self.why}{tail}"]


def priority_suggestions(srs: dict[str, SourceRep], *,
                         current: dict[str, int], min_runs: int = 2) -> list[Suggestion]:
    """按可信轮次的趋势，给出 `priority` / `enabled` 的调整建议。

    三条纪律：**只建议不改动**（代码永远不自动删源，划源是人做的事，见计划书 §14）；
    **一轮不判死刑**（`runs < min_runs` 一律 `confirmed=False`，因为 2.16 已经见过
    同一批数字在两个出口下差出 11 个主机）；**共用主机不轻判**（一个源死刑族里的主机
    要是别的源也在用，关掉它并不等于那些线路消失，所以只降 priority 不 drop）。

    `current` 传 `sources.yaml` 里现有的 priority（id -> 数字）；没记录按 99 算。

    >>> S = lambda n, runs, lines, ok, dead=0, sent=0, best=0, shared=0: SourceRep(
    ...     n, 1, runs, lines, ok, dead, sent, 0, best, shared)
    >>> srs = {"bad": S("bad", 3, 40, 2, dead=12, sent=11),
    ...        "fast": S("fast", 3, 10, 10, best=180),
    ...        "solo": S("solo", 1, 30, 3),
    ...        "mixed": S("mixed", 2, 40, 30, dead=4, sent=3, best=600, shared=4)}
    >>> cur = {"bad": 3, "fast": 9, "solo": 5, "mixed": 4}
    >>> got = {s.source: s for s in priority_suggestions(srs, current=cur, min_runs=2)}
    >>> (got["bad"].verdict, got["bad"].from_prio, got["bad"].to_prio)
    ('demote', 3, 5)
    >>> (got["fast"].verdict, got["fast"].to_prio, got["fast"].confirmed)
    ('promote', 8, True)
    >>> got["solo"].verdict, got["solo"].confirmed      # 只有一轮：给数不动手
    ('thin', False)
    >>> got["mixed"].verdict                            # 可用率 30/40=0.75，两头都不够，不动
    'keep'
    >>> got["mixed"].to_prio
    4
    >>> at0 = {"local": SourceRep("local", 1, 3, 4, 4, 0, 0, 0, 40, 0)}
    >>> s0 = priority_suggestions(at0, current={"local": 0})[0]
    >>> (s0.verdict, s0.to_prio)     # 手工源已经在最前面（priority 0），不再往前挤
    ('keep', 0)
    >>> dead_all = {"x": SourceRep("x", 5, 3, 20, 0, 5, 5, 0, 0, 0)}
    >>> s = priority_suggestions(dead_all, current={"x": 2})[0]
    >>> (s.verdict, s.enabled, s.to_prio)               # 一条都不通 → 整源关
    ('drop', False, 2)
    >>> tiny = {"y": SourceRep("y", 1, 3, 2, 0, 1, 1, 0, 0, 0)}
    >>> s = priority_suggestions(tiny, current={"y": 2})[0]
    >>> (s.verdict, s.enabled, s.to_prio)   # 只挂过 2 条线路就全灭：降档而已，不建议关源
    ('demote', True, 4)
    >>> fast_two = {"z": SourceRep("z", 1, 3, 2, 2, 0, 0, 0, 40, 0)}
    >>> s = priority_suggestions(fast_two, current={"z": 5})[0]
    >>> (s.verdict, s.to_prio)   # 3 轮 2/2 全通、40ms，但线路太少：不够资格往前挤
    ('keep', 5)
    >>> priority_suggestions({}, current={})
    []
    """
    out: list[Suggestion] = []
    for src, r in sorted(srs.items(), key=lambda kv: (-kv[1].lines, kv[0])):
        cur = int(current.get(src, 99))
        rate = (r.ok_last / r.lines) if r.lines else 0.0
        confirmed = r.runs >= min_runs
        # 「关掉整源」和「往前挪」都是拿这个源换别人的决定，比单纯降档要多一点证据：
        # 只挂过 1~2 条线路的源，两轮全灭也只降档（可逆），两轮全通也不往前挤。
        enough = r.lines >= MIN_EVIDENCE_LINES
        if r.lines and not r.ok_last and enough:
            v, to, en = "drop", cur, False
            why = (f"{r.runs} 轮 {r.ok_last}/{r.lines} 能播，{r.dead_hosts} 族从没通过过"
                   + (f"（其中 {r.sentenced} 族已两轮以上全灭）" if r.sentenced else ""))
        elif rate < DROP_RATE and r.sentenced and not r.shared:
            v, to, en = "demote", cur + 2, True
            why = (f"最近一轮 {r.ok_last}/{r.lines} 能播，{r.sentenced} 族两轮以上全灭"
                   f"（共 {r.runs} 轮观测）")
        elif rate >= KEEP_RATE and r.best_ms and r.best_ms <= 500 and not r.fake_hosts \
                and cur > 1 and enough:
            # cur <= 1 就不往前挪了：手工源 `local` 的 priority 是 0（同条件下它最优先），
            # 再减 1 只会把一个已经在最前面的源挤到别的位置上，方向反了。
            v, to, en = "promote", cur - 1, True
            why = f"{r.runs} 轮里 {r.ok_last}/{r.lines} 能播、最快 {r.best_ms}ms"
        else:
            v, to, en = ("thin" if not confirmed else "keep"), cur, True
            why = (f"最近一轮 {r.ok_last}/{r.lines} 能播、最快 {r.best_ms or '—'}ms"
                   + (f"，{r.dead_hosts} 族没通过过" if r.dead_hosts else ""))
        out.append(Suggestion(source=src, verdict=v, from_prio=cur, to_prio=to, why=why,
                              enabled=en, confirmed=confirmed))
    return out


def run_totals(runs: list[dict], *, current_egress: str = "", limit: int = 10) -> list[dict]:
    """每轮一行趋势：{at, egress, total, ok}，只数可信轮，按时间倒序取最近 limit 轮。

    >>> runs = [{"at": "2026-09-20T10:00:00+08:00", "egress": "U", "warnings": [],
    ...            "hosts": [{"host": "a", "total": 3, "ok": 1}]},
    ...          {"at": "2026-09-21T10:00:00+08:00", "egress": "U", "warnings": [],
    ...            "hosts": [{"host": "a", "total": 3, "ok": 3},
    ...                      {"host": "b", "total": 2, "ok": 0}]},
    ...          {"at": "2026-09-21T11:00:00+08:00", "egress": "T", "warnings": [],
    ...            "hosts": []}]
    >>> out = run_totals(runs, current_egress="U")
    >>> [(r["at"][5:10], f"{r['ok']}/{r['total']}") for r in out]
    [('09-21', '3/5'), ('09-20', '1/3')]
    """
    out = []
    for run in runs:
        if not trustworthy(run, current_egress):
            continue
        hs = run.get("hosts") or []
        out.append({"at": str(run.get("at") or ""),
                    "egress": str(run.get("egress") or ""),
                    "total": sum(int(h.get("total") or 0) for h in hs),
                    "ok": sum(int(h.get("ok") or 0) for h in hs)})
    out.sort(key=lambda r: r["at"], reverse=True)
    return out[:limit]


def adopt_probe(probe: dict) -> dict | None:
    """把旧版 `probe.json`（只有最后一轮）转成一条历史记录，用于首次升级到履历制。

    NAS 上重新部署、或者手动清过 data/output 之后，历史是空的，但 probe.json
    里往往还躺着一轮真数。不补进来的话，那轮的判据就白白丢了。

    >>> adopt_probe({"at": "2026-09-21T13:00:40+08:00", "egress": "U",
    ...              "measurement_warnings": [], "hosts": [{"host": "a", "total": 3, "ok": 0}]})["hosts"]
    [{'host': 'a', 'total': 3, 'ok': 0}]
    >>> adopt_probe({"hosts": []}) is None        # 空表不补，白记一轮
    True
    >>> adopt_probe({}) is None
    True
    >>> adopt_probe({"at": "x", "hosts": [{"host": "a"}]})["warnings"]   # 字段名对齐
    []
    """
    hosts = probe.get("hosts") or []
    if not hosts:
        return None
    return {"at": str(probe.get("at") or ""),
            "egress": str(probe.get("egress") or ""),
            "warnings": list(probe.get("measurement_warnings") or []),
            "hosts": hosts, "adopted": True}


def record_roll(runs: list[dict], verdicts: dict[str, str], *,
                current_egress: str, at: str = "") -> dict:
    """把 L3 的逐条结论回填进最近一轮**可信**实测（就地改 runs）。

    `verdicts` 是 `{线路 url: "rolling" | "stuck" | "vod"}`，只放真拿到内容结论的那些条
    （`dead`/`master` 说明不了内容，别传）。两处落点：

    - `run["rolls"]`：逐条结论。离线重出表时精确惩罚**那一条**线路（`merge_rolls()` 取用），
      不必因为「这台主机还有 35 条是活的」就放过这条已经确认不动的地址。
    - 主机行的 `stuck`：这个主机有几条不动，喂给 `only_vod()` 做整族判断。

    L3 每条要等一个间隔（默认 20 秒），进不了 `build --verify` 的主流程，所以由
    `scripts/verify_lines.py --roll --to-history` 单独跑完再回填。回填目标只能是最近那一轮
    可信实测，而且绝不新建轮次：L3 是对已有实测的补充判据，不是一轮新测量 ——
    新建轮次会把 `run_totals()` 的趋势表污染成「1 条线路的一轮」。

    数字按主机**覆盖**，不累加，所以同一批线路重复回填不会把 `stuck` 越堆越大；
    这一轮没提到的主机一个字都不改 —— 只跑 `hunan.m3u` 的 L3，不该清掉上次
    对 `aptv.m3u` 跑出来的结论。反过来，新一轮 `build --verify` 写出来的主机行里没有
    `stuck`、也没有 `rolls`，等于把 L3 的记忆清零 —— 那是对的：换了时间的观测要重新验。

    测量点不对时一个字都不写：TUN 开着测出的「列表不动」多半是隧道掐了。

    >>> runs = [{"at": "t2", "egress": "U", "warnings": [],
    ...          "hosts": [{"host": "loop", "total": 3, "ok": 3, "vod": 0},
    ...                    {"host": "gone", "total": 3, "ok": 0, "vod": 0}]}]
    >>> v = {"http://loop/1.m3u8": "stuck", "http://loop/2.m3u8": "vod",
    ...      "http://loop/3.m3u8": "dead", "http://new/1.m3u8": "stuck"}
    >>> record_roll(runs, v, current_egress="U", at="t3")["hosts"]
    ['loop']
    >>> [(h["host"], h.get("stuck", 0)) for h in runs[0]["hosts"]]  # 没测过的主机不去动它
    [('loop', 2), ('gone', 0)]
    >>> runs[0]["rolls"]                       # dead 那条没结论，不记；新主机照样记进逐条
    {'http://loop/1.m3u8': 'stuck', 'http://loop/2.m3u8': 'stuck', 'http://new/1.m3u8': 'stuck'}
    >>> record_roll(runs, {"http://loop/1.m3u8": "rolling"}, current_egress="U")["hosts"]
    []
    >>> runs[0]["hosts"][0]["stuck"]           # 这次它滚了，就把 2 覆盖成 0
    0
    >>> record_roll(runs, v, current_egress="TOKYO")["status"]   # 换了出口就不写
    'no-run'
    >>> record_roll([], v, current_egress="U")["status"]
    'no-run'
    """
    target = next((r for r in reversed(runs) if trustworthy(r, current_egress)), None)
    if target is None:
        return {"status": "no-run", "hosts": [], "unknown": [], "checked": 0}
    rows = {str(h.get("host") or ""): h for h in target.get("hosts") or []}
    rolls = dict(target.get("rolls") or {})
    judged: dict[str, list[str]] = {}
    for url, verdict in verdicts.items():
        v = str(verdict or "")
        if v == ROLL_LIVE or v in ROLL_DEAD:
            judged.setdefault(urlsplit(str(url)).hostname or "", []).append(v)
            rolls[url] = ROLL_LIVE if v == ROLL_LIVE else "stuck"
        # 其余（dead/master/乱码）说明不了内容，一个字节都不动
    unknown = sorted(h for h in judged if h not in rows)
    for host, vs in judged.items():
        if host in rows:
            rows[host]["stuck"] = sum(1 for x in vs if x != ROLL_LIVE)
    if judged:
        target["rolls"] = rolls
    if at and judged:
        target["roll_at"] = at
    done = sorted(h for h, vs in judged.items() if h in rows and rows[h]["stuck"])
    return {"status": "ok", "hosts": done, "unknown": unknown,
            "checked": sum(len(vs) for vs in judged.values())}


def merge_rolls(runs: list[dict], *, current_egress: str = "") -> dict[str, str]:
    """可信轮里的逐条 L3 结论，按时间合成一份（后面的轮覆盖前面）。

    >>> runs = [{"at": "t1", "egress": "U", "warnings": [], "hosts": [],
    ...          "rolls": {"http://a/1.m3u8": "stuck", "http://a/2.m3u8": "rolling"}},
    ...         {"at": "t2", "egress": "U", "warnings": [], "hosts": [],
    ...          "rolls": {"http://a/1.m3u8": "rolling"}},
    ...         {"at": "t3", "egress": "T", "warnings": [], "hosts": [],
    ...          "rolls": {"http://a/2.m3u8": "stuck"}}]
    >>> merge_rolls(runs, current_egress="U")
    {'http://a/1.m3u8': 'rolling', 'http://a/2.m3u8': 'rolling'}
    >>> merge_rolls(runs, current_egress="T")        # 东京那一轮里只有 a/2 这一条有结论
    {'http://a/2.m3u8': 'stuck'}
    >>> merge_rolls(runs)                            # 不知道在哪测的，一条都不采信
    {}
    """
    out: dict[str, str] = {}
    for run in runs:
        if not trustworthy(run, current_egress):
            continue
        for url, verdict in (run.get("rolls") or {}).items():
            out[str(url)] = str(verdict)
    return out


def save_history(path: Path, runs: list[dict]) -> None:
    """整份重写履历（回填 L3 之后用）。写不动就抛，让调用方知道没落盘。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs),
                    encoding="utf-8")


def load_history(path: Path, *, problems: list[str] | None = None) -> list[dict]:
    """读 JSONL 历史。文件不存在返回 []，坏行跳过 —— 历史不该让生成失败。

    但**跳过要能说出来**：一份读不出行的履历，效果就是那张表的排序悄悄少了
    「整族失效往后压、上一轮延迟补位」这两判据，台数一个字不变（2.32 量过同族：
    什么都没量到也算过）。履历只影响排序、不像少一个源那样直接少台，
    所以这里报一句就往下走，不拦。`problems` 是给人打印的句子列表，调用方传一个空列表：

    >>> load_history(Path("/does/not/exist.jsonl"))
    []

    缺文件不算问题（首轮本来就没有），坏行才算：

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "h.jsonl"
    ...     _ = p.write_text("这不是 JSON\\n"
    ...                      '{"at": "x", "hosts": [{"host": "a"}]}\\n'
    ...                      '{"at": "y", "没有 hosts 这个字段": 1}\\n', encoding="utf-8")
    ...     got: list[str] = []
    ...     runs = load_history(p, problems=got)
    ...     len(runs), len(got), got[0].split("：")[0], got[0].split("：")[1]
    (1, 1, 'h.jsonl 里 3 行只采用 1 轮', '第 1 行不是 JSON、1 行没有 hosts 字段，不算一轮')

    整个文件不是 UTF-8：也归到 problems 里，不崩栈。

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "bin.jsonl"
    ...     _ = p.write_bytes(b"\\xff\\xfe not utf-8")
    ...     got = []
    ...     load_history(p, problems=got), got[0].split("（")[1].split("）")[0]
    ([], 'invalid start byte')

    不传 `problems` 时行为和以前一样（拿不到原因，但也不炸）：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "one.jsonl"
    ...     _ = p.write_text('{"at": "x", "hosts": []}\\n', encoding="utf-8")
    ...     len(load_history(p))
    1
    """
    path = Path(path)
    runs: list[dict] = []
    note = problems if problems is not None else []
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return runs                                   # 首轮没有履历，正常
    except (OSError, UnicodeDecodeError) as e:
        # UnicodeDecodeError 没有 strerror（它是 ValueError 那一支），所以取 reason。
        why = getattr(e, "strerror", None) or getattr(e, "reason", None) or type(e).__name__
        note.append(f"{path.name} 读不进来（{why}）—— 本轮不拿履历降档、也不补位")
        return runs
    bad_json: list[str] = []
    no_hosts = 0
    for i, line in enumerate(raw):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad_json.append(f"第 {i + 1} 行不是 JSON")
            continue
        if isinstance(obj, dict) and obj.get("hosts") is not None:
            runs.append(obj)
        else:
            no_hosts += 1
    drops = list(bad_json[:3])
    if len(bad_json) > 3:
        drops.append(f"另有 {len(bad_json) - 3} 行同样不是 JSON")
    if no_hosts:
        drops.append(f"{no_hosts} 行没有 hosts 字段，不算一轮")
    if drops:
        note.append(f"{path.name} 里 {len(raw)} 行只采用 {len(runs)} 轮：" + "、".join(drops))
    return runs


# 合并那一行会被一起换掉、而本轮的 `run` 里根本没有的键 —— 都是**别的工具事后补进去的观测**。
# 换掉它们是 2.15 定过的规矩（「换了时间的观测要重新验」），这一节不推翻；
# 要改的是「换掉了却没人说」。`cleared` 这个出参就是说那句话用的。
_SIDE_CHANNELS = ("rolls", "srcs_note", "adopted")

# 默认窗口。30 分钟这个数写在 2.9 那阵，那时候「调代码时连着跑三次算一轮」是它防的事；
# 现在多了一个写入口（`scripts/verify_lines.py --to-history` 回填 L3），于是
# 「隔几分钟再补跑一次」和「这是两次独立观测」开始共用同一个 30 分钟 —— 做成开关，
# 0 = 每跑一次算一轮（`should_merge` 里 `< 0` 天然永不合并）。默认值照旧。
MERGE_WINDOW_MIN = 30


def append_run(path: Path, run: dict, *, merge_minutes: int = MERGE_WINDOW_MIN,
               cleared: list[str] | None = None) -> bool:
    """把这一轮实测追加进历史；判定为同一轮的重复跑就**整行替换**最后一行。

    返回 True 表示新起了一轮，False 表示合并进了上一轮。

    三件事都在这一节量过（`/tmp/repro_append.py`）：

    1. **合并会把旁路补记一起擦掉。** 那一行不止 `build` 在写：
       `scripts/verify_lines.py` 回填 `rolls`（L3：分片窗口动不动），
       `scripts/backfill_srcs.py` 补 `srcs_note`。上一行带着 2 条 `rolls`、
       隔 5 分钟再跑一次，那两个键就不见了。按 2.15 的规矩这是**对的** ——
       换了时刻的观测不能拿旧的顶上；但原来 stdout 只说「与上一轮同一时段，已合并」，
       不说「顺带清掉了 N 条 L3 结论」，而 `rolls` 要再等一个干净出口才回得来。
       所以加了 `cleared`：调用方传一个列表，这里把被换掉的键名和条数装进去。
    2. **这份文件是整份重写的**，所以读不进来时绝不能当「没有旧行」往下写 ——
       那等于清空履历。抛一句人话，并且一个字节都不碰原文件。
    3. `merge_minutes=0` 表示「每跑一次算一轮」，这时旁路补记自然全部留在原位。

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "h.jsonl"
    ...     a = {"at": "2026-09-21T13:00:40+08:00", "hosts": [{"host": "x"}],
    ...          "rolls": {"http://x/1": "stuck", "http://x/2": "moving"},
    ...          "srcs_note": "事后补记", "adopted": True}
    ...     got: list[str] = []
    ...     _ = append_run(p, a)
    ...     b = {"at": "2026-09-21T13:10:00+08:00", "hosts": [{"host": "x", "ok": 1}]}
    ...     merged = append_run(p, b, cleared=got)
    ...     rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    ...     merged, len(rows), sorted(rows[0])
    (False, 1, ['at', 'hosts'])

    清掉了哪几样，说得出来（数字取自被换掉的那一行，不是本轮的）：

    >>> got
    ['rolls 2 条 L3 结论', 'srcs_note', 'adopted']

    同一个窗口里但声明「每跑一次算一轮」，就谁也不会被顶掉：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "h.jsonl"
    ...     _ = append_run(p, {"at": "2026-09-21T13:00:40+08:00", "hosts": [],
    ...                        "rolls": {"u": "stuck"}})
    ...     kept: list[str] = []
    ...     new = append_run(p, {"at": "2026-09-21T13:10:00+08:00", "hosts": []},
    ...                      merge_minutes=0, cleared=kept)
    ...     rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    ...     new, len(rows), rows[0].get("rolls"), kept
    (True, 2, {'u': 'stuck'}, [])

    隔得够久自然新起一轮，旧行一个字不动：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "h.jsonl"
    ...     _ = append_run(p, {"at": "2026-09-21T13:00:40+08:00", "hosts": [],
    ...                        "rolls": {"u": "moving"}})
    ...     new = append_run(p, {"at": "2026-09-21T19:00:40+08:00", "hosts": []})
    ...     rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    ...     new, len(rows), rows[0].get("rolls")
    (True, 2, {'u': 'moving'})

    履历读不进来时抛话、且不碰那个文件（里面还有真测量）：

    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = Path(d) / "h.jsonl"
    ...     _ = p.write_bytes(b"\\xff\\xfe not utf-8 at all")
    ...     before = p.read_bytes()
    ...     try:
    ...         append_run(p, {"at": "2026-09-21T13:00:40+08:00", "hosts": []})
    ...     except RuntimeError as e:
    ...         print(str(e).split("：")[0], "｜文件原样", p.read_bytes() == before)
    履历 h.jsonl 读不进来（invalid start byte） ｜文件原样 True
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if cleared is None:
        cleared = []
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            why = getattr(e, "strerror", None) or getattr(e, "reason", None) or type(e).__name__
            raise RuntimeError(f"履历 {path.name} 读不进来（{why}）：这份文件是整份重写的，"
                               f"读不到就不动它 —— 先把它挪开或修好，否则这一轮测完也存不下") from e
        lines = [l for l in raw.splitlines() if l.strip()]
    else:
        lines = []
    merged = False
    if lines:
        try:
            prev = json.loads(lines[-1])
        except json.JSONDecodeError:
            prev = None
        if isinstance(prev, dict) and should_merge(str(prev.get("at") or ""),
                                                  str(run.get("at") or ""), merge_minutes):
            for k in _SIDE_CHANNELS:
                if k in prev and k not in run:
                    n = len(prev[k]) if isinstance(prev[k], dict) else ""
                    cleared.append(f"{k} {n} 条 L3 结论" if k == "rolls" else str(k))
            lines[-1] = json.dumps(run, ensure_ascii=False)
            merged = True
        else:
            lines.append(json.dumps(run, ensure_ascii=False))
    else:
        lines.append(json.dumps(run, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return not merged
