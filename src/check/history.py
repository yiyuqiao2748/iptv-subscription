"""把每轮实测攒成历史：让「这个主机上一轮全灭」这件事不随 probe.json 被覆盖而消失。

动机很具体。`probe.json` 只存最后一次实测，于是有两种情况在漏：

1. 跑 `build`（不带 `--verify`）时手里一点实测信息都没有，上一轮已经确认整族失效的
   主机（`stream1.freetv.fun` 0/35）又会大摇大摆排到频道第一位，电视上就是超时。
   离线生成不是罕见路径 —— 上游抓取失败、代理抽风、只想改改 `channels.yaml` 重出表，都会走它。
2. 一轮实测说了不算。中转类主机今天 42/42、明天 0/42 都出现过，只凭一次就把谁判死太武断。

所以这里只存「每轮实测的主机汇总」这一份小数据（`data/output/probe-history.jsonl`，
一行一轮），它同时服务两件事：给离线生成当缓存的判据（`dead_streak`），
和给报告算趋势（连着几轮全灭的才建议从 `sources.yaml` 里划掉）。

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


def reputation(runs: list[dict], *, current_egress: str = "") -> dict[str, HostRep]:
    """按主机汇总可信轮次。runs 是历史里按时间正序的轮记录（最新在末尾）。

    >>> r = lambda at, egress, hosts, warns=None: {
    ...     "at": at, "egress": egress, "warnings": warns or [], "hosts": hosts}
    >>> h = lambda name, total, ok: {"host": name, "scope": "public",
    ...                              "total": total, "ok": ok, "best_ms": 300}
    >>> runs = [r("2026-09-20T10:00:00+08:00", "UNICOM",
    ...           [h("dead.one", 3, 0), h("good", 2, 2)]),
    ...         r("2026-09-21T10:00:00+08:00", "UNICOM", [h("dead.one", 3, 0)])]
    >>> rep = reputation(runs + [r("2026-09-21T11:00:00+08:00", "TOKYO",
    ...                            [h("tokyo-only", 9, 0)], ["TUN 已开启"])],
    ...                  current_egress="UNICOM")
    >>> sorted(rep)                       # 东京那轮（体检报警）整个不算判据
    ['dead.one', 'good']
    >>> rep["dead.one"].runs, rep["dead.one"].ok_runs, rep["dead.one"].dead_streak
    (2, 0, 2)
    >>> rep["good"].runs, rep["good"].ok_runs, rep["good"].dead_streak
    (1, 1, 0)
    >>> rep["dead.one"].last_at       # 取最近一轮的数字，不是第一轮
    '2026-09-21T10:00:00+08:00'
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
            a = acc.setdefault(name, {"runs": 0, "ok_runs": 0, "streak": 0})
            a["runs"] += 1
            if int(h.get("ok") or 0) > 0:
                a["ok_runs"] += 1
                a["streak"] = 0                    # 只要活过一次，连续全灭就断了
            else:
                a["streak"] += 1
            a["last"] = {"total": int(h.get("total") or 0),
                         "ok": int(h.get("ok") or 0),
                         "best_ms": int(h.get("best_ms") or 0),
                         "at": str(run.get("at") or "")}
    return {name: HostRep(host=name, runs=a["runs"], ok_runs=a["ok_runs"],
                          total=a["last"]["total"], ok_last=a["last"]["ok"],
                          best_ms=a["last"]["best_ms"], last_at=a["last"]["at"],
                          dead_streak=a["streak"])
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


def load_history(path: Path) -> list[dict]:
    """读 JSONL 历史。文件不存在返回 []，坏行跳过 —— 历史不该让生成失败。

    >>> load_history(Path("/does/not/exist.jsonl"))
    []
    """
    try:
        raw = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    runs = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("hosts") is not None:
            runs.append(obj)
    return runs


def append_run(path: Path, run: dict, *, merge_minutes: int = 30) -> bool:
    """把这一轮实测追加进历史；判定为同一轮的重复跑就替换最后一行。

    返回 True 表示新起了一轮，False 表示合并进了上一轮。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if path.exists() else []
    merged = False
    if lines:
        try:
            prev = json.loads(lines[-1])
        except json.JSONDecodeError:
            prev = None
        if isinstance(prev, dict) and should_merge(str(prev.get("at") or ""),
                                                  str(run.get("at") or ""), merge_minutes):
            lines[-1] = json.dumps(run, ensure_ascii=False)
            merged = True
        else:
            lines.append(json.dumps(run, ensure_ascii=False))
    else:
        lines.append(json.dumps(run, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return not merged
