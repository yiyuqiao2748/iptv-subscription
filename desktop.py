"""
IPTV Desktop Launcher
=====================
Windows 桌面版启动器：GUI 主窗口 + 系统托盘 + 单实例锁。
配合 main.py --desktop 模式使用。
"""

import os
import sys
import socket
import threading
import webbrowser
import time
import logging
import tkinter as tk
from tkinter import scrolledtext

logger = logging.getLogger("desktop")

# ============================================================
# Single Instance Lock
# ============================================================
_LOCK_PORT = 53871
_lock_socket = None


def check_single_instance() -> bool:
    global _lock_socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
        return True
    except OSError:
        return False


# ============================================================
# Icon Generator
# ============================================================
def _create_icon_image():
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(240, 136, 62, 255))
    bar_w, gap = 6, 4
    x_start = 16
    for i, h in enumerate([14, 22, 30]):
        x = x_start + i * (bar_w + gap)
        y = size - 14 - h
        draw.rectangle([x, y, x + bar_w, size - 14], fill=(255, 255, 255, 230))
    return img


# ============================================================
# Desktop Window
# ============================================================
class IPTVDesktop:
    """Main GUI window for the IPTV desktop app."""

    def __init__(self, port=8899, update_cb=None):
        self.port = port
        self.update_cb = update_cb
        self._tray = None
        self._updating = False

        # --- Tkinter Window ---
        self.root = tk.Tk()
        self.root.title("IPTV 订阅服务")
        self.root.geometry("480x520")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Dark theme colors
        BG = "#1a1a2e"
        CARD = "#16213e"
        ACCENT = "#e94560"
        TEXT = "#eee"
        MUTED = "#888"
        GREEN = "#0f9b58"

        self.root.configure(bg=BG)

        # --- Header ---
        header = tk.Frame(self.root, bg=CARD, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="📡 IPTV 订阅服务", font=("Microsoft YaHei", 14, "bold"),
                 bg=CARD, fg=TEXT).pack(side="left", padx=16, pady=10)

        self.status_label = tk.Label(header, text="● 启动中...", font=("Microsoft YaHei", 10),
                                      bg=CARD, fg=GREEN)
        self.status_label.pack(side="right", padx=16)

        # --- Stats Card ---
        stats_frame = tk.Frame(self.root, bg=CARD, padx=16, pady=12)
        stats_frame.pack(fill="x", padx=12, pady=(12, 0))

        self.stat_alive = self._stat_row(stats_frame, "可用频道", "-", 0)
        self.stat_total = self._stat_row(stats_frame, "已扫描", "-", 1)
        self.stat_update = self._stat_row(stats_frame, "上次更新", "-", 2)
        self.stat_next = self._stat_row(stats_frame, "下次更新", "-", 3)

        # --- URL Card ---
        url_frame = tk.Frame(self.root, bg=CARD, padx=16, pady=10)
        url_frame.pack(fill="x", padx=12, pady=(8, 0))

        tk.Label(url_frame, text="订阅地址", font=("Microsoft YaHei", 9),
                 bg=CARD, fg=MUTED).pack(anchor="w")

        url_row = tk.Frame(url_frame, bg=CARD)
        url_row.pack(fill="x", pady=(4, 0))

        self.url_var = tk.StringVar(value=f"http://localhost:{port}/iptv.m3u")
        url_entry = tk.Entry(url_row, textvariable=self.url_var, state="readonly",
                             font=("Consolas", 9), bg="#0d1117", fg="#58a6ff",
                             readonlybackground="#0d1117", relief="flat", bd=0)
        url_entry.pack(side="left", fill="x", expand=True, ipady=4)

        tk.Button(url_row, text="复制", command=self._copy_url,
                  font=("Microsoft YaHei", 9), bg="#333", fg=TEXT,
                  relief="flat", padx=12, cursor="hand2").pack(side="left", padx=(6, 0))

        tk.Button(url_row, text="打开面板", command=self._open_dashboard,
                  font=("Microsoft YaHei", 9), bg="#e94560", fg="#fff",
                  relief="flat", padx=12, cursor="hand2").pack(side="left", padx=(6, 0))

        # --- Action Buttons ---
        btn_frame = tk.Frame(self.root, bg=BG, padx=12, pady=8)
        btn_frame.pack(fill="x")

        self.btn_update = tk.Button(btn_frame, text="  立即更新  ", command=self._update_now,
                                    font=("Microsoft YaHei", 10, "bold"),
                                    bg="#e94560", fg="#fff", relief="flat",
                                    padx=20, pady=6, cursor="hand2")
        self.btn_update.pack(side="left", padx=(0, 8))

        tk.Button(btn_frame, text="  退出  ", command=self._quit,
                  font=("Microsoft YaHei", 10),
                  bg="#333", fg=TEXT, relief="flat",
                  padx=20, pady=6, cursor="hand2").pack(side="left")

        # --- Log Area ---
        log_frame = tk.Frame(self.root, bg=CARD, padx=12, pady=8)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        tk.Label(log_frame, text="运行日志", font=("Microsoft YaHei", 9),
                 bg=CARD, fg=MUTED).pack(anchor="w")

        self.log_area = scrolledtext.ScrolledText(
            log_frame, height=10, font=("Consolas", 8),
            bg="#0d1117", fg="#a6accd", insertbackground="#a6accd",
            relief="flat", state="disabled", wrap="word",
        )
        self.log_area.pack(fill="both", expand=True, pady=(4, 0))

        # Redirect logs to the text widget
        self._setup_log_handler()

        # Start polling stats
        self._poll_stats()

    def _stat_row(self, parent, label, value, row):
        frame = tk.Frame(parent, bg="#1a2332", padx=12, pady=6)
        frame.grid(row=row, column=0, sticky="ew", pady=1)
        parent.columnconfigure(0, weight=1)

        tk.Label(frame, text=label, font=("Microsoft YaHei", 9),
                 bg="#1a2332", fg="#888").pack(side="left")
        val_label = tk.Label(frame, text=value, font=("Microsoft YaHei", 10, "bold"),
                             bg="#1a2332", fg="#eee")
        val_label.pack(side="right")
        return val_label

    def _setup_log_handler(self):
        class TkLogHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget

            def emit(self, record):
                msg = self.format(record)
                def _append():
                    self.widget.configure(state="normal")
                    self.widget.insert("end", msg + "\n")
                    self.widget.see("end")
                    self.widget.configure(state="disabled")
                self.widget.after(0, _append)

        handler = TkLogHandler(self.log_area)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                               datefmt="%H:%M:%S"))
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)

    def _poll_stats(self):
        """Poll server stats and update the UI."""
        try:
            import urllib.request, json
            url = f"http://localhost:{self.port}/api/stats"
            with urllib.request.urlopen(url, timeout=2) as resp:
                stats = json.loads(resp.read())

            alive = stats.get("alive_channels", 0)
            total = stats.get("total_channels", 0)
            last = stats.get("last_update", "-")
            nxt = stats.get("next_update", "-")
            running = stats.get("pipeline_running", False)

            self.stat_alive.config(text=str(alive))
            self.stat_total.config(text=str(total))
            self.stat_update.config(text=str(last))
            self.stat_next.config(text=str(nxt))

            if running:
                self.status_label.config(text="● 更新中...", fg="#f0a500")
                self.btn_update.config(state="disabled", text="  更新中...  ")
                self._updating = True
            else:
                self.status_label.config(text="● 运行中", fg="#0f9b58")
                if self._updating:
                    self._updating = False
                    self.btn_update.config(state="normal", text="  立即更新  ")
                    self._tray_notify("频道列表更新完成！")

            # Update URL with actual host
            import socket as _sock
            hostname = _sock.gethostbyname(_sock.gethostname())
            self.url_var.set(f"http://{hostname}:{self.port}/iptv.m3u")

        except Exception:
            pass  # server not ready yet

        self.root.after(5000, self._poll_stats)

    def _copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url_var.get())
        self._flash_btn("已复制 ✓")

    def _flash_btn(self, msg):
        original = self.btn_update.cget("text")
        # no direct flash needed, use status
        self.status_label.config(text=msg, fg="#58a6ff")
        self.root.after(1500, lambda: self.status_label.config(
            text="● 运行中" if not self._updating else "● 更新中...",
            fg="#0f9b58" if not self._updating else "#f0a500"))

    def _open_dashboard(self):
        webbrowser.open(f"http://localhost:{self.port}/")

    def _update_now(self):
        if self.update_cb and not self._updating:
            self._updating = True
            self.btn_update.config(state="disabled", text="  更新中...  ")
            self.status_label.config(text="● 更新中...", fg="#f0a500")
            threading.Thread(target=self.update_cb, daemon=True).start()

    def _tray_notify(self, msg):
        if self._tray:
            try:
                self._tray.notify(msg, "IPTV 订阅")
            except Exception:
                pass

    def _quit(self):
        if self._tray:
            self._tray.stop()
        self.root.destroy()
        os._exit(0)

    def _on_close(self):
        """Minimize to tray instead of closing."""
        self.root.withdraw()

    def _restore(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()

    def _start_tray(self):
        """Start system tray icon in a separate thread."""
        import pystray
        from pystray import MenuItem as Item

        image = _create_icon_image()
        menu = pystray.Menu(
            Item("打开面板", self._restore, default=True),
            Item("立即更新", lambda i, t: self.root.after(0, self._update_now)),
            pystray.Menu.SEPARATOR,
            Item("退出", lambda i, t: self.root.after(0, self._quit)),
        )
        self._tray = pystray.Icon("IPTV订阅", image, "IPTV 订阅服务", menu)
        self._tray.run()

    def run(self):
        """Start the desktop app (blocks main thread)."""
        # Update URL on startup
        try:
            import socket as _sock
            hostname = _sock.gethostbyname(_sock.gethostname())
            self.url_var.set(f"http://{hostname}:{self.port}/iptv.m3u")
        except Exception:
            pass

        # Start tray in background thread
        threading.Thread(target=self._start_tray, daemon=True).start()

        # Auto-open browser
        self.root.after(2000, self._open_dashboard)

        # Run tkinter main loop (blocks)
        self.root.mainloop()
