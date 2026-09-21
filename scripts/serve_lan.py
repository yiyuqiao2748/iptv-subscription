"""局域网订阅服务：把 data/output 里的 m3u 放给 Apple TV 订阅。

    python scripts/serve_lan.py                 # 默认端口 8787
    python scripts/serve_lan.py --port 8787

起好后在 APTV 里填：http://<本机局域网IP>:8787/hunan.m3u

只放产物文件，不放目录结构；只绑定本机局域网，不做端口映射。
每次有设备来取数据，都会在控制台和 data/logs/requests.log 里留一行，
用来判断「电视到底连上了没有」——这是排查订阅失败的关键证据。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"
LOG_DIR = ROOT / "data" / "logs"
ALLOWED = {"aptv.m3u", "hunan.m3u", "hunan-lean.m3u", "test.m3u",
           "probe-pack.m3u", "report.md"}
PUBLIC_NAMES = {"hunan.m3u": "湖南本地优先",
                "aptv.m3u": "全量：央视 + 卫视 + 湖南"}
DIAG_NAMES = {"probe-pack.m3u": "试播包：每个流主机族挑一条，逐个点开，回报能动哪几个",
              "hunan-lean.m3u": "同一张表去掉台标和 EPG —— 主地址加不上时试它",
              "test.m3u": "只有几个台的极小表 —— 判断是不是表太大/太复杂"}


def count_channels(text: str) -> int:
    """订阅表里有几个不同的台（同名多条线路算一个台）。

    >>> count_channels('#EXTM3U\\n#EXTINF:-1 ,湖南卫视\\nhttp://a/1.m3u8\\n'
    ...                '#EXTINF:-1 ,湖南卫视\\nhttp://a/2.m3u8\\n#EXTINF:-1 ,湖南经视\\nhttp://a/3.m3u8')
    2
    """
    names = {l.split(",", 1)[1] for l in text.splitlines()
             if l.startswith("#EXTINF") and "," in l}
    return len(names)


def refresh_labels() -> None:
    """按当前文件内容把台数填进标签。

    这两个数字曾经硬编码成「39 个台 / 93 个台」，跑一次 --verify 就变成 39 / 90，
    屏幕上留个旧数字比不写更糟 —— 电视订阅排查时人就是靠这些数字对账的。
    先按「（」截一刀再拼，重复调用只会换数字，不会叠出两层括号。
    """
    for name in PUBLIC_NAMES:
        path = OUT_DIR / name
        if not path.exists():
            continue
        n = count_channels(path.read_text(encoding="utf-8"))
        PUBLIC_NAMES[name] = f"{PUBLIC_NAMES[name].split('（')[0]}（{n} 个台）"

_seen_clients: set[str] = set()
_local_ips: set[str] = {"127.0.0.1"}
_log_fh = None


def _is_local(client: str) -> bool:
    return client.startswith(("127.", "localhost")) or client in _local_ips


def _log_line(text: str) -> None:
    """控制台 + 日志文件双写，并强制 flush（否则窗口里看不到实时请求）。"""
    print(text, flush=True)
    if _log_fh is not None:
        try:
            _log_fh.write(text + "\n")
            _log_fh.flush()
        except OSError:
            pass


class Handler(SimpleHTTPRequestHandler):
    """只放出生成的订阅文件；响应头之外的错误文案必须是 ASCII，
    否则 BaseHTTPRequestHandler 用 latin-1 编码状态行会直接抛异常。"""

    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".m3u": "application/x-mpegurl; charset=utf-8",
                      ".m3u8": "application/vnd.apple.mpegurl"}

    def do_GET(self) -> None:  # noqa: N802
        name = Path(self.path.split("?")[0].strip("/")).name
        if self.path.split("?")[0] in ("/", "/index.html"):
            self._index()
            return
        if name not in ALLOWED:
            self.send_error(404, "only generated playlist files are served")
            return
        self.path = "/" + name
        super().do_GET()

    def _index(self) -> None:
        """状态页。IP 一律用 main() 里筛过的候选地址，不能用 lan_ip()：
        挂了代理的机器上 lan_ip() 会返回虚拟网卡地址（实测 172.19.0.1），
        电视照着填是连不上的。"""
        candidates = self.server.candidates
        ip = candidates[0]

        def rows(names: dict[str, str]) -> str:
            return "".join(
                f'<li><code>http://{ip}:{self.server.port}/{n}</code> —— {desc}'
                for n, desc in names.items()
            )

        others = "".join(f"<li><code>{c}</code></li>" for c in candidates[1:])
        body = (
            "<!doctype html><meta charset=utf-8><title>APTV 订阅服务正常</title>"
            "<style>body{font-family:-apple-system;padding:40px;line-height:2}"
            "code{background:#f2f2f7;padding:2px 6px;border-radius:4px}"
            "h2{margin-top:32px}</style>"
            "<h1>✅ 服务已经起来了</h1>"
            "<p>这个页面能打开，说明这台电脑和你在用的设备是通的。"
            "把下面的地址复制到 APTV 的订阅输入框：</p>"
            f"<ul>{rows(PUBLIC_NAMES)}</ul>"
            f"<h2>主地址加不上时，试这两个诊断用的表</h2>"
            f"<ul>{rows(DIAG_NAMES)}</ul>"
            f"<p>哪些台在 Wi-Fi 上必然播不动（只有运营商 IPTV 专网来源），"
            f"看<code>http://{ip}:{self.server.port}/report.md</code>里"
            "「线路的可达范围」那一节。</p>"
            f"<p>本机在这些网段有地址：<code>{ip}</code>"
            f"{others and '、' + '、'.join(candidates[1:])}"
            "。<br>电视的 IP 前三段必须和其中某一个一致；"
            "都不一样就是不在同一网段（比如电脑连了访客网络），填什么地址都没用。</p>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt: str, *args) -> None:
        client = self.address_string()
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        try:
            msg = fmt % args
        except TypeError:
            msg = str(fmt)
        line = f"  [{stamp}] {client} {msg}"
        if client not in _seen_clients:
            _seen_clients.add(client)
            if _is_local(client):
                line += "   （本机自测，可忽略）"
            else:
                line = (f"  ★ 有别的设备连上来了：{client}\n" + line)
        _log_line(line)


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 80))     # 不会真的发包，只是问内核走哪个口
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def local_ipv4s() -> list[str]:
    """列出本机所有像家庭网段的 IPv4，方便确认电视该填哪一个。"""
    out: set[str] = set()
    for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        out.add(ai[4][0])
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for probe in ("192.168.1.1", "10.0.0.1", "172.16.0.1"):
        try:
            s.connect((probe, 80))
            out.add(s.getsockname()[0])
        except OSError:
            pass
    s.close()
    return sorted(ip for ip in out
                  if not ip.startswith(("127.", "169.254."))
                  and not re.match(r"172\.(1[7-9]|2\d|3[01])\.", ip))


def firewall_hint() -> str:
    """问一句本机防火墙状态。拿不到就算了，不影响起服务。

    这里必须分平台：Windows 的 netsh 在 macOS 上不存在，subprocess 拿不到任何输出，
    旧代码就顺着走到「全开着」那个分支，等于对着用户编了一条假消息。
    """
    if sys.platform.startswith("win"):
        cmd, shell = ["netsh", "advfirewall", "show", "allprofiles", "state"], True
    elif sys.platform == "darwin":
        cmd, shell = ["/usr/libexec/ApplicationFirewall/socketfilterfw",
                      "--getglobalstate"], False
    else:
        return "防火墙状态：这台系统不检查（通常没有拦入站的默认策略）"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8, shell=shell)
        text = (r.stdout or "").lower()
    except (OSError, subprocess.SubprocessError):
        return "防火墙状态：没查到（不影响使用）"
    if not text:
        return "防火墙状态：没查到（不影响使用）"

    if sys.platform == "darwin":
        if "disabled" in text:
            return "防火墙状态：已关闭，不会拦电视"
        if "enabled" in text:
            return ("防火墙状态：开着 —— 若电视连不上，去「系统设置 → 网络 → 防火墙」"
                    "里给 Python 放行入站连接")
        return "防火墙状态：没查到（不影响使用）"

    off = text.count("off") + text.count("关闭")
    if off >= 3:
        return "防火墙状态：已关闭，不会拦电视"
    if off:
        return "防火墙状态：部分配置文件开着 —— 若电视连不上，先临时关闭专用网络防火墙"
    return "防火墙状态：全开着 —— 若电视连不上，需要给端口 8787 放行入站规则"


def already_running(port: int) -> bool:
    """端口是否已经有一个活的订阅服务。

    Windows 上 HTTPServer 的 SO_REUSEADDR 允许重复绑定同一个监听端口，
    靠 bind 失败来判断「是不是已经开着了」并不可靠，所以直接问它一句。
    """
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/", timeout=2) as r:
            return b"APTV" in r.read(2048)
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    global _log_fh

    ap = argparse.ArgumentParser(description="在局域网内提供 m3u 订阅")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    if not OUT_DIR.exists():
        print(f"还没有生成产物，先跑：{sys.executable} -m src.cli build", file=sys.stderr)
        return 1

    if already_running(args.port):
        print(f"端口 {args.port} 上已经有一个订阅服务在跑了（可能窗口已经开着）。")
        print("直接用那个窗口里的地址即可；要重启就先关掉那个窗口再双击。")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_fh = (LOG_DIR / "requests.log").open("a", encoding="utf-8")
    _log_line(f"\n=== 起服务 {dt.datetime.now():%Y-%m-%d %H:%M:%S} 端口 {args.port} ===")

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", args.port),
                                    partial(Handler, directory=str(OUT_DIR)))
    except OSError:
        _log_line(f"  端口 {args.port} 已经被占用了 —— 说明服务已经开着，"
                  f"直接用那个窗口里的地址就行，不用再启动一次。")
        if _log_fh:
            _log_fh.close()
        return 0
    httpd.port = args.port                     # _index() 要用
    candidates = local_ipv4s() or [lan_ip()]
    httpd.candidates = candidates              # 状态页要列给电视看的那几个地址
    _local_ips.update(candidates)

    refresh_labels()                           # 屏幕上的台数要跟当前文件一致
    firewall = firewall_hint()                 # 起服务前先问，别在请求中途卡住
    _log_line("=" * 62)
    _log_line("  APTV 局域网订阅服务")
    _log_line("=" * 62)
    for ip in candidates:
        for name, desc in PUBLIC_NAMES.items():
            _log_line(f"  http://{ip}:{args.port}/{name}   # {desc}")
    _log_line("")
    _log_line("  主地址在 APTV 里加不上时，再试这两个诊断用的表：")
    for name, desc in DIAG_NAMES.items():
        _log_line(f"    http://{candidates[0]}:{args.port}/{name}   # {desc}")
    _log_line("")
    _log_line(f"  {firewall}")
    _log_line("  先别做端口映射，这个服务只在家里用。")
    _log_line("  窗口别关。电视来取数据时这里会跳出一行 IP。")
    _log_line("=" * 62)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log_line("\n已停止。")
    finally:
        if _log_fh:
            _log_fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
