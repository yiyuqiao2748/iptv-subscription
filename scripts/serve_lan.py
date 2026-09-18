"""局域网订阅服务（临时版，P4 会被 deploy/serve.py 取代）。

    python scripts/serve_lan.py                # 默认端口 8787
    python scripts/serve_lan.py --port 8787

起好后在 APTV 里填：http://<本机局域网IP>:8787/hunan.m3u
只绑定 0.0.0.0 的家庭网段，不要做端口映射，不要公网暴露。
"""

from __future__ import annotations

import argparse
import socket
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "output"


class Handler(SimpleHTTPRequestHandler):
    """只放出产物文件，不暴露目录结构。"""

    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".m3u": "application/x-mpegurl; charset=utf-8",
                      ".m3u8": "application/vnd.apple.mpegurl"}

    def do_GET(self) -> None:  # noqa: N802
        name = Path(self.path.split("?")[0].strip("/")).name
        if name not in {"aptv.m3u", "hunan.m3u", "report.md"}:
            self.send_error(404, "只允许下载生成的订阅文件")
            return
        self.path = "/" + name
        super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        print(f"  {self.address_string()} {fmt % args}")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 80))     # 不会真的发包，只是问内核走哪个口
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="在局域网内提供 m3u 订阅")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    if not OUT_DIR.exists():
        print(f"还没有生成产物，先跑：{sys.executable} -m src.cli build", file=sys.stderr)
        return 1

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port),
                                partial(Handler, directory=str(OUT_DIR)))
    ip = lan_ip()
    print(f"局域网订阅地址（Apple TV 与本机需在同一网段）：")
    for f in ("hunan.m3u", "aptv.m3u"):
        print(f"  http://{ip}:{args.port}/{f}")
    print("Ctrl+C 停止。仅本机局域网可达，请勿做端口映射。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
