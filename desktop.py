"""
IPTV Desktop Launcher
=====================
Windows 桌面版启动器：GUI 主窗口 + 系统托盘 + 激活验证 + 单实例锁。
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
# Theme Colors
# ============================================================
BG = "#1a1a2e"
CARD = "#16213e"
ACCENT = "#e94560"
TEXT = "#eee"
MUTED = "#888"
GREEN = "#0f9b58"


# ============================================================
# Activation Dialog
# ============================================================
def show_activation_dialog() -> bool:
    """Show activation dialog. Returns True if activated."""
    from license import get_machine_code, verify_activation_code, save_activation, is_activated

    if is_activated():
        return True

    dialog = tk.Tk()
    dialog.title("小柚TV - 激活")
    dialog.geometry("420x400")
    dialog.resizable(False, False)
    dialog.configure(bg=BG)
    dialog.eval('tk::PlaceWindow . center')

    result = {"activated": False}

    # Header
    header = tk.Frame(dialog, bg=CARD, height=60)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="📡 小柚TV 频道助手", font=("Microsoft YaHei", 16, "bold"),
             bg=CARD, fg=ACCENT).pack(expand=True)

    # Body
    body = tk.Frame(dialog, bg=BG, padx=24, pady=20)
    body.pack(fill="both", expand=True)

    tk.Label(body, text="欢迎使用小柚TV！", font=("Microsoft YaHei", 12, "bold"),
             bg=BG, fg=TEXT).pack(anchor="w")
    tk.Label(body, text="首次使用需要激活，请将下方机器码发送给卖家获取激活码。",
             font=("Microsoft YaHei", 9), bg=BG, fg=MUTED, wraplength=360).pack(anchor="w", pady=(4, 16))

    # Machine code
    mc = get_machine_code()
    mc_frame = tk.Frame(body, bg=CARD, padx=12, pady=8)
    mc_frame.pack(fill="x", pady=(0, 12))

    tk.Label(mc_frame, text="您的机器码", font=("Microsoft YaHei", 9),
             bg=CARD, fg=MUTED).pack(anchor="w")
    mc_row = tk.Frame(mc_frame, bg=CARD)
    mc_row.pack(fill="x", pady=(4, 0))

    mc_entry = tk.Entry(mc_row, font=("Consolas", 14, "bold"), justify="center",
                        bg="#0d1117", fg="#f0a500", relief="flat", bd=0)
    mc_entry.insert(0, mc)
    mc_entry.config(state="readonly", readonlybackground="#0d1117")
    mc_entry.pack(side="left", fill="x", expand=True, ipady=6)

    def _copy_mc():
        dialog.clipboard_clear()
        dialog.clipboard_append(mc)
        copy_btn.config(text="已复制 ✓")
        dialog.after(1500, lambda: copy_btn.config(text="复制"))

    copy_btn = tk.Button(mc_row, text="复制", command=_copy_mc,
                         font=("Microsoft YaHei", 9), bg="#333", fg=TEXT,
                         relief="flat", padx=10, cursor="hand2")
    copy_btn.pack(side="left", padx=(8, 0))

    # Activation code input
    tk.Label(body, text="请输入激活码", font=("Microsoft YaHei", 9),
             bg=BG, fg=MUTED).pack(anchor="w", pady=(8, 4))

    ac_entry = tk.Entry(body, font=("Consolas", 14), justify="center",
                        bg="#0d1117", fg=TEXT, insertbackground=TEXT,
                        relief="flat", bd=0)
    ac_entry.pack(fill="x", ipady=8)
    ac_entry.focus()

    # Status label
    status_var = tk.StringVar(value="")
    status_label = tk.Label(body, textvariable=status_var, font=("Microsoft YaHei", 9),
                            bg=BG, fg=ACCENT)
    status_label.pack(anchor="w", pady=(6, 0))

    def _activate():
        code = ac_entry.get().strip()
        if not code:
            status_var.set("请输入激活码")
            return
        if verify_activation_code(mc, code):
            save_activation(code)
            result["activated"] = True
            dialog.destroy()
        else:
            status_var.set("激活码错误，请检查后重试")
            ac_entry.config(bg="#2a1a1a")
            dialog.after(1500, lambda: ac_entry.config(bg="#0d1117"))

    # Activate button
    btn_frame = tk.Frame(body, bg=BG)
    btn_frame.pack(fill="x", pady=(16, 0))

    tk.Button(btn_frame, text="  激活  ", command=_activate,
              font=("Microsoft YaHei", 11, "bold"), bg=ACCENT, fg="#fff",
              relief="flat", padx=30, pady=6, cursor="hand2").pack(side="left")

    tk.Button(btn_frame, text="  试用（50频道）  ", command=dialog.destroy,
              font=("Microsoft YaHei", 10), bg="#333", fg=MUTED,
              relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=(12, 0))

    # Bind Enter
    ac_entry.bind("<Return>", lambda e: _activate())

    dialog.mainloop()
    return result["activated"]


# ============================================================
# First Run Guide
# ============================================================
def show_first_run_guide():
    """Show first-run welcome guide. Returns when closed."""
    guide_file = ".first_run_done"
    if os.path.exists(guide_file):
        return

    guide = tk.Tk()
    guide.title("小柚TV - 使用指南")
    guide.geometry("440x450")
    guide.resizable(False, False)
    guide.configure(bg=BG)
    guide.eval('tk::PlaceWindow . center')

    # Header
    header = tk.Frame(guide, bg=CARD, height=60)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="📡 欢迎使用小柚TV！", font=("Microsoft YaHei", 16, "bold"),
             bg=CARD, fg=ACCENT).pack(expand=True)

    # Content
    body = tk.Frame(guide, bg=BG, padx=24, pady=20)
    body.pack(fill="both", expand=True)

    steps = [
        ("1️⃣", "等待频道扫描完成", "首次启动需要几分钟扫描可用频道，以后每 6 小时自动更新。"),
        ("2️⃣", "获取订阅地址", "主界面显示您的订阅地址，复制后添加到 APTV / VLC 等播放器。"),
        ("3️⃣", "在手机/电视上观看", "同一局域网内，用手机或电视打开播放器添加订阅地址即可。"),
        ("4️⃣", "管理面板", "点击「打开面板」可搜索频道、按分类筛选、手动触发更新。"),
    ]

    for icon, title, desc in steps:
        row = tk.Frame(body, bg=CARD, padx=12, pady=8)
        row.pack(fill="x", pady=4)

        tk.Label(row, text=icon, font=("Microsoft YaHei", 16),
                 bg=CARD, fg=TEXT, width=3).pack(side="left", anchor="n")
        info = tk.Frame(row, bg=CARD)
        info.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Label(info, text=title, font=("Microsoft YaHei", 10, "bold"),
                 bg=CARD, fg=TEXT).pack(anchor="w")
        tk.Label(info, text=desc, font=("Microsoft YaHei", 8),
                 bg=CARD, fg=MUTED, wraplength=300, justify="left").pack(anchor="w")

    # Close button
    def _close():
        try:
            with open(guide_file, "w") as f:
                f.write("done")
        except Exception:
            pass
        guide.destroy()

    tk.Button(body, text="  开始使用  ", command=_close,
              font=("Microsoft YaHei", 12, "bold"), bg=ACCENT, fg="#fff",
              relief="flat", padx=40, pady=8, cursor="hand2").pack(pady=(16, 0))

    guide.mainloop()


# ============================================================
# Desktop Window
# ============================================================
class IPTVDesktop:
    """Main GUI window for the IPTV desktop app."""

    def __init__(self, port=8899, update_cb=None, activated=False):
        self.port = port
        self.update_cb = update_cb
        self.activated = activated
        self._tray = None
        self._updating = False

        # --- Tkinter Window ---
        self.root = tk.Tk()
        self.root.title("小柚TV 频道助手")
        self.root.geometry("480x540")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.configure(bg=BG)

        # --- Header ---
        header = tk.Frame(self.root, bg=CARD, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="📡 小柚TV 频道助手", font=("Microsoft YaHei", 14, "bold"),
                 bg=CARD, fg=ACCENT).pack(side="left", padx=16, pady=10)

        self.status_label = tk.Label(header, text="● 启动中...", font=("Microsoft YaHei", 10),
                                      bg=CARD, fg=GREEN)
        self.status_label.pack(side="right", padx=16)

        # --- Activation status (if not activated) ---
        if not activated:
            act_bar = tk.Frame(self.root, bg="#2a1a1a", padx=12, pady=6)
            act_bar.pack(fill="x")
            tk.Label(act_bar, text="⚠ 未激活 — 限 50 个频道",
                     font=("Microsoft YaHei", 9), bg="#2a1a1a", fg="#f85149").pack(side="left")
            tk.Button(act_bar, text="输入激活码", command=self._show_activation,
                      font=("Microsoft YaHei", 9), bg="#333", fg=TEXT,
                      relief="flat", padx=10, cursor="hand2").pack(side="right")

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
        try:
            import urllib.request, json as _json
            url = f"http://localhost:{self.port}/api/stats"
            with urllib.request.urlopen(url, timeout=2) as resp:
                stats = _json.loads(resp.read())

            self.stat_alive.config(text=str(stats.get("alive_channels", 0)))
            self.stat_total.config(text=str(stats.get("total_channels", 0)))
            self.stat_update.config(text=str(stats.get("last_update", "-")))
            self.stat_next.config(text=str(stats.get("next_update", "-")))

            running = stats.get("pipeline_running", False)
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

            import socket as _sock
            hostname = _sock.gethostbyname(_sock.gethostname())
            self.url_var.set(f"http://{hostname}:{self.port}/iptv.m3u")
        except Exception:
            pass
        self.root.after(5000, self._poll_stats)

    def _copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url_var.get())
        self.status_label.config(text="已复制 ✓", fg="#58a6ff")
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

    def _show_activation(self):
        from license import is_activated, get_machine_code, verify_activation_code, save_activation
        act_win = tk.Toplevel(self.root)
        act_win.title("激活")
        act_win.geometry("380x250")
        act_win.resizable(False, False)
        act_win.configure(bg=BG)
        act_win.grab_set()

        mc = get_machine_code()
        tk.Label(act_win, text="机器码: " + mc, font=("Consolas", 12),
                 bg=BG, fg="#f0a500").pack(pady=(20, 4))
        tk.Label(act_win, text="请将机器码发送给卖家获取激活码",
                 font=("Microsoft YaHei", 9), bg=BG, fg=MUTED).pack()

        tk.Label(act_win, text="激活码:", font=("Microsoft YaHei", 10),
                 bg=BG, fg=TEXT).pack(pady=(16, 4))
        ac_entry = tk.Entry(act_win, font=("Consolas", 14), justify="center",
                            bg="#0d1117", fg=TEXT, insertbackground=TEXT, relief="flat")
        ac_entry.pack(ipady=6, padx=40, fill="x")
        ac_entry.focus()

        status = tk.Label(act_win, text="", font=("Microsoft YaHei", 9), bg=BG, fg=ACCENT)
        status.pack(pady=(6, 0))

        def _do_activate():
            code = ac_entry.get().strip()
            if verify_activation_code(mc, code):
                save_activation(code)
                self.activated = True
                status.config(text="激活成功！重启生效", fg=GREEN)
                act_win.after(1500, act_win.destroy)
            else:
                status.config(text="激活码错误")

        ac_entry.bind("<Return>", lambda e: _do_activate())
        tk.Button(act_win, text="确认激活", command=_do_activate,
                  font=("Microsoft YaHei", 10, "bold"), bg=ACCENT, fg="#fff",
                  relief="flat", padx=20, pady=4, cursor="hand2").pack(pady=(12, 0))

    def _tray_notify(self, msg):
        if self._tray:
            try:
                self._tray.notify(msg, "小柚TV")
            except Exception:
                pass

    def _quit(self):
        if self._tray:
            self._tray.stop()
        self.root.destroy()
        os._exit(0)

    def _on_close(self):
        self.root.withdraw()

    def _restore(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()

    def _start_tray(self):
        import pystray
        from pystray import MenuItem as Item

        image = _create_icon_image()
        menu = pystray.Menu(
            Item("打开面板", self._restore, default=True),
            Item("立即更新", lambda i, t: self.root.after(0, self._update_now)),
            pystray.Menu.SEPARATOR,
            Item("退出", lambda i, t: self.root.after(0, self._quit)),
        )
        self._tray = pystray.Icon("小柚TV", image, "小柚TV 频道助手", menu)
        self._tray.run()

    def run(self):
        """Start the desktop app (blocks main thread)."""
        try:
            import socket as _sock
            hostname = _sock.gethostbyname(_sock.gethostname())
            self.url_var.set(f"http://{hostname}:{self.port}/iptv.m3u")
        except Exception:
            pass

        threading.Thread(target=self._start_tray, daemon=True).start()
        self.root.after(2000, self._open_dashboard)
        self.root.mainloop()
