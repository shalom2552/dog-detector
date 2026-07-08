"""Launcher window: status display, Start/Open/Stop buttons, and container-sync polls."""

import json
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

from audio import play_sound
from docker_ctl import (compose_down, compose_export, compose_up,
                        container_running, docker_engine_running,
                        export_needed, http_get, open_live_view,
                        start_docker_desktop)
from log import LogManager
from paths import SOUND_URL, STATE_URL, WEB_URL
from widgets import StatusDot, StatusIndicator


class Launcher(tk.Tk):
    BG      = "#1b1f2a"
    CARD    = "#252b3a"
    TEXT    = "#e7eaf0"
    MUTED   = "#8b93a7"
    GREEN   = "#3ecf8e"
    AMBER   = "#f0b429"
    RED     = "#e5484d"
    BTN     = "#323a4d"
    BTN_HOV = "#3d4661"

    def __init__(self):
        super().__init__()
        self.window_width = 400
        self.window_height = 520
        self.title("Dog Detector")
        self.configure(bg=self.BG)
        self.resizable(True, True)
        self._center(self.window_width, self.window_height)

        self.busy = False
        self._build_ui()
        self._log_mgr = LogManager(self, self._log_text)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._stop_poll = False
        self._last_running = False
        self._last_sound_http_err = None
        self._bg(self._poll_loop)
        self._bg(self._sound_poll_loop)

    @staticmethod
    def _bg(fn):
        threading.Thread(target=fn, daemon=True).start()

    def _center(self, w, h):
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        title_f = tkfont.Font(family="Segoe UI Semibold", size=18)
        small_f = tkfont.Font(family="Segoe UI", size=10)
        btn_f   = tkfont.Font(family="Segoe UI", size=11)

        tk.Label(self, text="🐶  Dog Detector", font=title_f,
                 bg=self.BG, fg=self.TEXT).pack(pady=(24, 4))
        tk.Label(self, text="Detection control panel", font=small_f,
                 bg=self.BG, fg=self.MUTED).pack(pady=(0, 8))

        # ── Big status indicator ────────────────────────────────────────────
        self._indicator = StatusIndicator(self, self.BG)
        self._indicator.canvas.pack(pady=(4, 12))
        self._indicator.show_dot(self.RED)

        # ── Status card ─────────────────────────────────────────────────────
        card = tk.Frame(self, bg=self.CARD)
        card.pack(fill="x", padx=24, pady=(0, 20))

        self._dot = StatusDot(card, self.CARD)
        self._dot.canvas.pack(side="left", padx=(16, 10), pady=14)

        self._status_lbl = tk.Label(card, text="Checking…", font=small_f,
                                    bg=self.CARD, fg=self.TEXT)
        self._status_lbl.pack(side="left", pady=14)

        # ── Buttons ─────────────────────────────────────────────────────────
        self.btn_start = self._btn("▶️  Start detector", self._on_start, btn_f)
        self.btn_open  = self._btn("🎥  Open live view", self._on_open,  btn_f)
        self.btn_stop  = self._btn("⏹️  Stop detector",  self._on_stop,  btn_f)
        self.btn_open.configure(state="disabled")
        self.btn_stop.configure(state="disabled")

        # ── Collapsible logs ────────────────────────────────────────────────
        self._logs_open = False
        self.btn_logs = self._btn("▸  Show logs", self._toggle_logs, small_f)

        self._log_frame = tk.Frame(self, bg=self.BG)
        sb = tk.Scrollbar(self._log_frame)
        sb.pack(side="right", fill="y")
        self._log_text = tk.Text(
            self._log_frame, height=12, bg="#11141c", fg="#c5cbd8",
            relief="flat", bd=0, wrap="none", state="disabled",
            font=tkfont.Font(family="Consolas", size=9),
            yscrollcommand=sb.set)
        self._log_text.pack(side="left", fill="both", expand=True)
        sb.configure(command=self._log_text.yview)

    def _btn(self, text, cmd, font):
        b = tk.Button(self, text=text, command=cmd, font=font,
                      bg=self.BTN, fg=self.TEXT, activebackground=self.BTN_HOV,
                      activeforeground=self.TEXT, relief="flat", bd=0,
                      cursor="hand2", height=2)
        b.pack(fill="x", padx=24, pady=5)
        b.bind("<Enter>", lambda e: b.configure(bg=self.BTN_HOV) if str(b["state"]) != "disabled" else None)
        b.bind("<Leave>", lambda e: b.configure(bg=self.BTN))
        return b

    # ── status helpers ──────────────────────────────────────────────────────

    def _set_status(self, color, text):
        self._dot.set_color(color)
        self._status_lbl.configure(text=text)

    def _set_busy(self, on, msg=None):
        self.busy = on
        state = "disabled" if on else "normal"
        for b in (self.btn_start, self.btn_open, self.btn_stop):
            b.configure(state=state)
        if msg:
            self._status_lbl.configure(text=msg)
        if on:
            self._indicator.spin()

    # ── logs panel ────────────────────────────────────────────────────────────

    def _toggle_logs(self):
        self._logs_open = not self._logs_open
        if self._logs_open:
            self.btn_logs.configure(text="▾  Hide logs")
            self._log_frame.pack(fill="both", expand=True, padx=24, pady=(0, 16))
            self.geometry(f"{self.window_width}x{self.window_height + 260}")
        else:
            self.btn_logs.configure(text="▸  Show logs")
            self._log_frame.pack_forget()
            self.geometry(f"{self.window_width}x{self.window_height}")

    # ── button actions ──────────────────────────────────────────────────────

    def _on_start(self):
        if self.busy:
            return
        self._set_busy(True, "Starting Docker…")
        self._log_mgr.clear()
        self._log_mgr.stop_stream()  # kill any stream from a previous run before build output

        def log(line):
            self.after(0, self._log_mgr.append, line)

        def job():
            if not docker_engine_running():
                self.after(0, self._set_status, self.AMBER, "Starting Docker engine…")
                if not start_docker_desktop():
                    self.after(0, self._set_busy, False)
                    self.after(0, self._set_status, self.RED, "Docker won't start — is it installed?")
                    return
            if export_needed():  # first run: .pt not yet exported to ONNX
                self.after(0, self._set_status, self.AMBER, "Exporting model (one-time)…")
                log("=== One-time model export (.pt -> ONNX) ===")
                if not compose_export(log):
                    self.after(0, self._set_busy, False)
                    self.after(0, self._set_status, self.RED, "Model export failed — see logs")
                    return
            self.after(0, self._set_status, self.AMBER, "Building…")
            ok = compose_up(log)
            self.after(0, self._set_busy, False)
            if not ok:
                self.after(0, self._set_status, self.RED, "Failed to start — see logs")

        self._bg(job)

    def _on_stop(self):
        if self.busy:
            return
        self._set_busy(True, "Stopping…")
        self._log_mgr.stop_stream()

        def job():
            ok, _ = compose_down()
            self.after(0, self._log_mgr.append,
                       "=== Container stopped ===" if ok else "Stop failed — check Docker.")
            self.after(0, self._set_busy, False)

        self._bg(job)

    def _on_open(self):
        open_live_view(WEB_URL)

    # ── background threads ────────────────────────────────────────────────────

    def _post(self, fn, *args):
        """Marshal to the tk thread, but never after shutdown (avoids late-TclError)."""
        if self._stop_poll:
            return
        try:
            self.after(0, fn, *args)
        except tk.TclError:
            pass

    def _poll_loop(self):
        while not self._stop_poll:
            if not self.busy:
                running = container_running()
                self._last_running = running
                if running:
                    reachable, status, _ = http_get(STATE_URL, timeout=2)
                    self._post(self._reflect, True, reachable, status == 401)
                else:
                    self._post(self._reflect, False, False)
            time.sleep(3)

    def _sound_poll_loop(self):
        while not self._stop_poll:
            if self._last_running:  # don't poll /sound while the container is stopped
                ok, status, body = http_get(SOUND_URL, timeout=2)
                if ok:
                    self._last_sound_http_err = None
                    try:
                        if json.loads(body).get("pending"):
                            self._bg(self._play_alert)
                    except Exception:
                        pass
                elif status is not None and status != self._last_sound_http_err:
                    self._last_sound_http_err = status  # log once per distinct error, not 1/s
                    self._post(self._log_mgr.append,
                               f"[launcher] /sound poll failed: HTTP {status}"
                               + (" — check APP_USER/APP_PASSWORD in .env" if status == 401 else ""))
            time.sleep(1)

    def _play_alert(self):
        try:
            err = play_sound()
        except Exception as e:  # playback must never kill the poll thread
            err = repr(e)
        if err:
            self._post(self._log_mgr.append, f"[launcher] sound failed: {err}")

    def _reflect(self, running, reachable, auth_failed=False):
        if self.busy:
            return
        if not running:
            self._set_status(self.MUTED, "Stopped")
            self._indicator.show_dot(self.RED)
            self.btn_start.configure(state="normal")
            self.btn_open.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self._log_mgr.stop_stream()
            return
        # Container up: buttons and log stream are identical across readiness states.
        self.btn_start.configure(state="disabled")
        self.btn_open.configure(state="normal")
        self.btn_stop.configure(state="normal")
        self._log_mgr.start_stream()
        if reachable:
            self._set_status(self.GREEN, "Running")
            self._indicator.show_dot(self.GREEN)
        elif auth_failed:
            self._set_status(self.RED, "Auth failed — check APP_USER/APP_PASSWORD in .env")
            self._indicator.show_dot(self.RED)
        else:
            self._set_status(self.AMBER, "Starting up…")  # container up but not ready yet
            self._indicator.spin()

    # ── shutdown ──────────────────────────────────────────────────────────────

    def _on_close(self):
        self._stop_poll = True
        self._log_mgr.stop_stream()
        self._set_busy(True, "Shutting down…")
        self.update()

        def job():
            compose_down()
            self.after(0, self.destroy)

        self._bg(job)
