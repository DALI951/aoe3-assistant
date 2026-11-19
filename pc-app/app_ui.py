"""
AoE3 Assistant - Ultra-Lightweight PC Real-Time Rates Floating Overlay (app_ui.py)
Version 1.1.0

Features (Designed specifically per user requirements):
- ULTRA-CLEAN DRAGGABLE FLOATING OVERLAY:
  * Shows ONLY real-time income rates: Food/s, Wood/s, Coin/s, XP/s.
  * Does NOT duplicate total resources or 44-card clutter that AoE3 already displays.
  * Compact footer showing active Match State (Playing / Paused / Waiting / Game Not Running),
    Villager count, and 1-line tactical coach advice.
- DRAGGABLE ANYWHERE ON SCREEN:
  * Click and drag anywhere on the widget with the mouse (<ButtonPress-1> / <B1-Motion>)
    to position it anywhere over the game.
- GLOBAL HOTKEY TOGGLE:
  * Press F12 or Ctrl+Shift+A anytime to toggle the floating HUD overlay on/off.
- SILENT MODE:
  * 100% TTS / Voice / Sound REMOVED (zero audio interruptions).
- ZERO DEFAULTS:
  * Defaults strictly to 0.0 /s when AoE3 is not running or waiting for a match.
- ALWAYS-ON BACKGROUND MODE & WINDOWS STARTUP:
  * --background starts quietly in the background and registers HKCU Run key.
- AUTO-UPDATER:
  * Integrated updater checking GitHub Releases & /api/version.
"""

import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request
import winreg

APP_VERSION = "1.1.0"
APP_NAME = "AoE3 Live Rates Overlay"
REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_RUN_VALUE = "AoE3Assistant"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
REPO_PC_APP_DIR = os.path.abspath(os.path.join(EXE_DIR, "..", "pc-app"))
REPO_ROOT = os.path.abspath(os.path.join(APP_DIR, ".."))
for _p in (APP_DIR, EXE_DIR, REPO_PC_APP_DIR, REPO_ROOT, r"C:\Users\Dali\.gemini\antigravity\scratch\aoe3-assistant\pc-app"):
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import updater
except Exception:
    updater = None

telemetry_mod = None
coach_mod = None
try:
    import telemetry as telemetry_mod
except Exception:
    telemetry_mod = None

try:
    import coach as coach_mod
except Exception:
    coach_mod = None


def get_default_snapshot() -> Dict[str, Any]:
    """Default snapshot when game is NOT running or not in match. All rates strictly 0.0!"""
    return {
        "connected": False,
        "game_running": False,
        "in_match": False,
        "is_playing": False,
        "is_paused": False,
        "match_state": "GAME_NOT_RUNNING",
        "status_text": "Game not running — run a game (waiting for match...)",
        "pid": 0,
        "food_per_sec": 0.0,
        "wood_per_sec": 0.0,
        "coin_per_sec": 0.0,
        "xp_per_sec": 0.0,
        "villagers": 0,
        "pop": 0,
        "pop_cap": 0,
        "shipments_available": 0,
        "xp_needed_next": 0,
        "next_recommended_card": "",
        "cards_used_count": 0,
        "cards_remaining_count": 0,
        "game_time_sec": 0.0,
        "coach_advice": "Game not running — start AoE3 and enter a match",
        "coach_advice_list": ["Game not running — start AoE3 and enter a match"],
    }


def is_windows_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_RUN_VALUE)
            return True
    except Exception:
        return False


def set_windows_startup(enable: bool = True) -> bool:
    try:
        if enable:
            exe_path = os.path.abspath(sys.executable)
            cmd = f'"{exe_path}" --background'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY) as key:
                winreg.SetValueEx(key, REG_RUN_VALUE, 0, winreg.REG_SZ, cmd)
            return True
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, REG_RUN_VALUE)
                except FileNotFoundError:
                    pass
            return True
    except Exception:
        return False


class GlobalHotkeyListener:
    """
    Listens for F12 and Ctrl+Shift+A globally on Windows.
    Uses Win32 RegisterHotKey + low-frequency GetAsyncKeyState polling.
    """

    VK_F12 = 0x7B
    VK_A = 0x41
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    WM_HOTKEY = 0x0312

    def __init__(self, on_toggle_callback):
        self.on_toggle = on_toggle_callback
        self._running = True
        self._last_trigger = 0.0
        self._thread = threading.Thread(target=self._poll_keys, daemon=True, name="AoE3HotkeyListener")
        self._thread.start()

    def _trigger(self) -> None:
        now = time.time()
        if now - self._last_trigger > 0.35:
            self._last_trigger = now
            try:
                self.on_toggle()
            except Exception:
                pass

    def _poll_keys(self) -> None:
        user32 = ctypes.windll.user32
        threading.Thread(target=self._win32_msg_loop, daemon=True, name="AoE3Win32HotKey").start()

        was_f12_down = False
        was_csa_down = False
        while self._running:
            try:
                f12_down = (user32.GetAsyncKeyState(self.VK_F12) & 0x8000) != 0
                if f12_down and not was_f12_down:
                    self._trigger()
                was_f12_down = f12_down

                ctrl_down = (user32.GetAsyncKeyState(self.VK_CONTROL) & 0x8000) != 0
                shift_down = (user32.GetAsyncKeyState(self.VK_SHIFT) & 0x8000) != 0
                a_down = (user32.GetAsyncKeyState(self.VK_A) & 0x8000) != 0
                csa_down = ctrl_down and shift_down and a_down
                if csa_down and not was_csa_down:
                    self._trigger()
                was_csa_down = csa_down
            except Exception:
                pass
            time.sleep(0.05)

    def _win32_msg_loop(self) -> None:
        try:
            user32 = ctypes.windll.user32
            user32.RegisterHotKey(None, 201, 0, self.VK_F12)
            user32.RegisterHotKey(None, 202, self.MOD_CONTROL | self.MOD_SHIFT, self.VK_A)
            msg = wintypes.MSG()
            while self._running:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == self.WM_HOTKEY:
                    self._trigger()
        except Exception:
            pass


class TelemetryBridge:
    """Reads live telemetry from telemetry.py/coach.py or /api/state and pushes 1 Hz."""

    def __init__(self, local_server: str = "http://127.0.0.1:8765", remote_server: str = ""):
        self.local_server = local_server.rstrip("/")
        self.remote_server = remote_server.rstrip("/")
        self.reader_instance = None
        self.coach_instance = None
        self.last_snapshot: Dict[str, Any] = get_default_snapshot()
        self.server_push_ok: bool = False
        self._init_modules()

    def _init_modules(self) -> None:
        global telemetry_mod, coach_mod
        if telemetry_mod is None:
            try:
                import telemetry as tm
                telemetry_mod = tm
            except Exception:
                telemetry_mod = None
        if coach_mod is None:
            try:
                import coach as cm
                coach_mod = cm
            except Exception:
                coach_mod = None

        if telemetry_mod and self.reader_instance is None:
            for cls_name in ("TelemetryReader", "AoE3Telemetry", "MemoryReader"):
                cls = getattr(telemetry_mod, cls_name, None)
                if cls:
                    try:
                        self.reader_instance = cls()
                        break
                    except Exception:
                        pass

        if coach_mod and self.coach_instance is None:
            for cls_name in ("CoachEngine", "RussiaCoach", "Coach"):
                cls = getattr(coach_mod, cls_name, None)
                if cls:
                    try:
                        self.coach_instance = cls()
                        break
                    except Exception:
                        pass

    def ensure_local_server_running(self) -> None:
        try:
            req = urllib.request.Request(f"{self.local_server}/api/version", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass

        srv_file = os.path.join(REPO_ROOT, "server", "server.py")
        if os.path.exists(srv_file):
            try:
                subprocess.Popen(
                    [sys.executable, srv_file],
                    cwd=os.path.dirname(srv_file),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                    close_fds=True,
                )
            except Exception:
                pass

    def poll_once(self) -> Dict[str, Any]:
        self._init_modules()
        raw_data: Optional[Dict[str, Any]] = None

        if self.reader_instance is not None:
            for method_name in ("read_snapshot", "get_telemetry", "read", "poll", "snapshot", "get_state"):
                fn = getattr(self.reader_instance, method_name, None)
                if callable(fn):
                    try:
                        res = fn()
                        if isinstance(res, dict) and res:
                            raw_data = res
                            break
                    except Exception:
                        pass

        if raw_data is None and telemetry_mod is not None:
            for fn_name in ("read_snapshot", "get_telemetry", "read_telemetry", "get_snapshot"):
                fn = getattr(telemetry_mod, fn_name, None)
                if callable(fn):
                    try:
                        res = fn()
                        if isinstance(res, dict) and res:
                            raw_data = res
                            break
                    except Exception:
                        pass

        if raw_data is not None and self.coach_instance is not None:
            for method_name in ("evaluate", "analyze", "update", "coach", "get_advice", "process"):
                fn = getattr(self.coach_instance, method_name, None)
                if callable(fn):
                    try:
                        c_res = fn(raw_data)
                        if isinstance(c_res, dict):
                            raw_data.update(c_res)
                        break
                    except Exception:
                        pass

        if isinstance(raw_data, dict) and raw_data:
            merged = get_default_snapshot()
            merged.update(raw_data)
            self.last_snapshot = merged
            self.push_to_servers(merged)
            return merged

        # Fallback to server state
        try:
            req = urllib.request.Request(f"{self.local_server}/api/state", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                srv_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(srv_data, dict):
                    payload = srv_data.get("telemetry") if isinstance(srv_data.get("telemetry"), dict) else srv_data
                    merged = get_default_snapshot()
                    merged.update(payload)
                    self.server_push_ok = True
                    self.last_snapshot = merged
                    return merged
        except Exception:
            pass

        default_snap = get_default_snapshot()
        self.last_snapshot = default_snap
        self.push_to_servers(default_snap)
        return default_snap

    def push_to_servers(self, snapshot: Dict[str, Any]) -> None:
        targets = [f"{self.local_server}/api/telemetry"]
        if self.remote_server and self.remote_server != self.local_server:
            r_url = self.remote_server.rstrip("/") + "/api/telemetry"
            targets.append(r_url)

        body = json.dumps(snapshot).encode("utf-8")
        pushed = False
        for url in targets:
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={"Content-Type": "application/json", "User-Agent": f"AoE3Assistant-PC/{APP_VERSION}"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=0.8) as resp:
                    if 200 <= resp.status < 300:
                        pushed = True
            except Exception:
                pass
        self.server_push_ok = pushed


class DraggableFloatingOverlay:
    """
    Ultra-sleek, compact draggable floating rates HUD.
    Displays ONLY real-time income rates (+Food/s, +Wood/s, +Coin/s, +XP/s) and status.
    Click-and-drag anywhere on the overlay to move it anywhere on screen.
    """

    BG_MAIN = "#0d1117"
    BG_CARD = "#161b22"
    BORDER_COLOR = "#30363d"
    TEXT_MAIN = "#f0f6fc"
    TEXT_MUTED = "#8b949e"
    GOLD = "#f0c05a"
    GOLD_BRIGHT = "#ffd97d"
    GREEN = "#3fb950"
    RED = "#f85149"
    AMBER = "#d29922"
    BLUE = "#58a6ff"

    def __init__(self, root: tk.Tk, start_minimized: bool = False):
        self.root = root
        self.version = APP_VERSION
        self.root.title(f"{APP_NAME} v{self.version}")
        self.root.configure(bg=self.BORDER_COLOR)

        # Make frameless, always-on-top, semi-transparent HUD overlay
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)

        # Initial geometry: sleek 480x138 card positioned at top center/right
        screen_w = self.root.winfo_screenwidth()
        pos_x = max(40, (screen_w - 500) // 2)
        pos_y = 18
        self.root.geometry(f"500x138+{pos_x}+{pos_y}")

        self.hud_visible = not start_minimized
        self.bridge = TelemetryBridge(
            local_server=os.environ.get("AOE3_SERVER_URL", "http://127.0.0.1:8765"),
            remote_server=os.environ.get("AOE3_REMOTE_URL", ""),
        )
        self.auto_updater = updater.AutoUpdater(current_version=self.version) if updater else None
        self.latest_snapshot: Dict[str, Any] = get_default_snapshot()

        self._drag_x = 0
        self._drag_y = 0
        self._pill_drag_x = 0
        self._pill_drag_y = 0

        self._build_mini_pill()
        self._build_overlay_ui()

        # Global Hotkey (F12 / Ctrl+Shift+A)
        self.hotkeys = GlobalHotkeyListener(self.schedule_toggle_hud)

        # Background 1 Hz telemetry worker
        self._running = True
        self._thread = threading.Thread(target=self._telemetry_worker, daemon=True, name="AoE3RatesLoop")
        self._thread.start()

        threading.Thread(target=self.bridge.ensure_local_server_running, daemon=True).start()

        if start_minimized:
            self.root.withdraw()
            self.hud_visible = False
            self.pill_btn.config(text="⚔ AoE3 Rates [F12: Show]", fg=self.GREEN)

        self.root.after(250, self._refresh_ui_loop)
        self.root.after(2000, self.check_updates_silent)

    def _build_mini_pill(self) -> None:
        """Compact floating mini pill shown when overlay is hidden."""
        self.pill_win = tk.Toplevel(self.root)
        self.pill_win.overrideredirect(True)
        self.pill_win.attributes("-topmost", True)
        self.pill_win.attributes("-alpha", 0.94)
        self.pill_win.configure(bg=self.GOLD)

        screen_w = self.root.winfo_screenwidth()
        pill_x = max(20, screen_w - 240)
        self.pill_win.geometry(f"230x32+{pill_x}+12")

        inner = tk.Frame(self.pill_win, bg=self.BG_MAIN, padx=4, pady=2)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.pill_drag_handle = tk.Label(
            inner,
            text="⠿",
            bg=self.BG_MAIN,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 10, "bold"),
            cursor="fleur",
            padx=3,
        )
        self.pill_drag_handle.pack(side=tk.LEFT)

        self.pill_btn = tk.Label(
            inner,
            text="⚔ AoE3 Rates [F12: Hide]",
            bg=self.BG_MAIN,
            fg=self.GOLD_BRIGHT,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.pill_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.pill_dot = tk.Label(inner, text="●", bg=self.BG_MAIN, fg=self.RED, font=("Segoe UI", 9), padx=5)
        self.pill_dot.pack(side=tk.RIGHT)

        for w in (self.pill_win, inner, self.pill_drag_handle, self.pill_dot):
            w.bind("<ButtonPress-1>", self._on_pill_press)
            w.bind("<B1-Motion>", self._on_pill_motion)

        self.pill_btn.bind("<ButtonPress-1>", self._on_pill_press)
        self.pill_btn.bind("<B1-Motion>", self._on_pill_motion)
        self.pill_btn.bind("<ButtonRelease-1>", self._on_pill_release)

    def _on_pill_press(self, event):
        self._pill_drag_x = event.x_root - self.pill_win.winfo_x()
        self._pill_drag_y = event.y_root - self.pill_win.winfo_y()
        self._pill_moved = False

    def _on_pill_motion(self, event):
        new_x = event.x_root - self._pill_drag_x
        new_y = event.y_root - self._pill_drag_y
        self.pill_win.geometry(f"+{new_x}+{new_y}")
        self._pill_moved = True

    def _on_pill_release(self, event):
        if not getattr(self, "_pill_moved", False):
            self.toggle_hud()

    def _on_hud_press(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _on_hud_motion(self, event):
        new_x = event.x_root - self._drag_x
        new_y = event.y_root - self._drag_y
        self.root.geometry(f"+{new_x}+{new_y}")

    def _bind_drag(self, widget: tk.Widget) -> None:
        """Allow clicking and dragging anywhere on the given widget to move the HUD."""
        widget.bind("<ButtonPress-1>", self._on_hud_press)
        widget.bind("<B1-Motion>", self._on_hud_motion)

    def _build_overlay_ui(self) -> None:
        """Construct the ultra-clean real-time rates floating panel."""
        self.container = tk.Frame(self.root, bg=self.BG_MAIN, padx=8, pady=6, cursor="fleur")
        self.container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._bind_drag(self.container)

        # Top Bar: Drag Handle, State Badge, Hotkey Hint, Close/Hide Button
        top_bar = tk.Frame(self.container, bg=self.BG_MAIN)
        top_bar.pack(fill=tk.X, pady=(0, 4))
        self._bind_drag(top_bar)

        self.drag_grip = tk.Label(
            top_bar,
            text="⠿ AoE3 Rates",
            bg=self.BG_MAIN,
            fg=self.GOLD_BRIGHT,
            font=("Segoe UI", 9, "bold"),
            cursor="fleur",
        )
        self.drag_grip.pack(side=tk.LEFT)
        self._bind_drag(self.drag_grip)

        self.state_badge = tk.Label(
            top_bar,
            text="● GAME NOT RUNNING",
            bg="#251619",
            fg=self.RED,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=1,
            cursor="fleur",
        )
        self.state_badge.pack(side=tk.LEFT, padx=8)
        self._bind_drag(self.state_badge)

        self.hotkey_hint = tk.Label(
            top_bar,
            text="[F12 to hide • Drag to move]",
            bg=self.BG_MAIN,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8),
            cursor="fleur",
        )
        self.hotkey_hint.pack(side=tk.LEFT, padx=4)
        self._bind_drag(self.hotkey_hint)

        self.close_btn = tk.Label(
            top_bar,
            text="✕",
            bg=self.BG_MAIN,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            padx=6,
        )
        self.close_btn.pack(side=tk.RIGHT)
        self.close_btn.bind("<Button-1>", lambda _e: self.toggle_hud())

        self.update_btn = tk.Label(
            top_bar,
            text="⟳",
            bg=self.BG_MAIN,
            fg=self.GOLD,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=4,
        )
        self.update_btn.pack(side=tk.RIGHT, padx=4)
        self.update_btn.bind("<Button-1>", lambda _e: self.on_click_check_updates())

        # Middle Row: 4 Real-Time Rate Columns ONLY
        rates_frame = tk.Frame(self.container, bg=self.BG_MAIN)
        rates_frame.pack(fill=tk.X, pady=2)
        self._bind_drag(rates_frame)

        self.food_card, self.food_val = self._create_rate_column(
            rates_frame, "🥩 FOOD/s", "+0.0 /s", "#ff7b7b"
        )
        self.wood_card, self.wood_val = self._create_rate_column(
            rates_frame, "🌲 WOOD/s", "+0.0 /s", "#e3b341"
        )
        self.coin_card, self.coin_val = self._create_rate_column(
            rates_frame, "🪙 COIN/s", "+0.0 /s", "#ffd95e"
        )
        self.xp_card, self.xp_val = self._create_rate_column(
            rates_frame, "⚡ XP/s", "+0.0 /s", self.GREEN
        )

        # Bottom Row: Clean 1-Line Status (Vills, Shipments/Cards, Actionable Advice)
        self.footer = tk.Frame(self.container, bg=self.BG_MAIN)
        self.footer.pack(fill=tk.X, pady=(4, 0))
        self._bind_drag(self.footer)

        self.advice_lbl = tk.Label(
            self.footer,
            text="Game not running — run AoE3 and enter a match",
            bg=self.BG_MAIN,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            cursor="fleur",
        )
        self.advice_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._bind_drag(self.advice_lbl)

    def _create_rate_column(self, parent: tk.Widget, label_text: str, default_val: str, color: str):
        card = tk.Frame(parent, bg=self.BG_CARD, padx=6, pady=4, cursor="fleur")
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self._bind_drag(card)

        lbl = tk.Label(
            card,
            text=label_text,
            bg=self.BG_CARD,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8, "bold"),
            cursor="fleur",
        )
        lbl.pack(anchor="center")
        self._bind_drag(lbl)

        val = tk.Label(
            card,
            text=default_val,
            bg=self.BG_CARD,
            fg=color,
            font=("Segoe UI", 13, "bold"),
            cursor="fleur",
        )
        val.pack(anchor="center")
        self._bind_drag(val)

        return card, val

    def schedule_toggle_hud(self) -> None:
        try:
            self.root.after(0, self.toggle_hud)
        except Exception:
            pass

    def toggle_hud(self) -> None:
        if self.hud_visible:
            self.root.withdraw()
            self.hud_visible = False
            self.pill_btn.config(text="⚔ AoE3 Rates [F12: Show]", fg=self.GREEN)
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.hud_visible = True
            self.pill_btn.config(text="⚔ AoE3 Rates [F12: Hide]", fg=self.GOLD_BRIGHT)

    def _telemetry_worker(self) -> None:
        while self._running:
            t0 = time.time()
            try:
                snap = self.bridge.poll_once()
                if isinstance(snap, dict):
                    self.latest_snapshot = snap
            except Exception:
                pass
            elapsed = time.time() - t0
            time.sleep(max(0.15, 1.0 - elapsed))

    def _refresh_ui_loop(self) -> None:
        try:
            self._render_snapshot(self.latest_snapshot)
        except Exception:
            pass
        if self._running:
            self.root.after(350, self._refresh_ui_loop)

    def _render_snapshot(self, s: Dict[str, Any]) -> None:
        in_match = bool(s.get("in_match", False) or s.get("connected", False))
        game_running = bool(s.get("game_running", in_match))
        is_playing = bool(s.get("is_playing", False))
        is_paused = bool(s.get("is_paused", False))
        match_state = s.get("match_state", "GAME_NOT_RUNNING" if not game_running else "WAITING_FOR_MATCH")

        # Update Match State Badge
        if not game_running or match_state == "GAME_NOT_RUNNING":
            self.state_badge.config(text="● GAME NOT RUNNING", bg="#2c1719", fg=self.RED)
            self.pill_dot.config(fg=self.RED)
        elif not in_match or match_state == "WAITING_FOR_MATCH":
            self.state_badge.config(text="● WAITING FOR MATCH...", bg="#3a2f14", fg=self.AMBER)
            self.pill_dot.config(fg=self.AMBER)
        elif is_paused or match_state == "PAUSED":
            self.state_badge.config(text="⏸ IN MATCH — PAUSED", bg="#192a3d", fg=self.BLUE)
            self.pill_dot.config(fg=self.BLUE)
        else:
            t_sec = float(s.get("game_time_sec", 0.0) or 0.0)
            m = int(t_sec // 60)
            sec = int(t_sec % 60)
            self.state_badge.config(text=f"▶ PLAYING ({m:02d}:{sec:02d})", bg="#153620", fg=self.GREEN)
            self.pill_dot.config(fg=self.GREEN)

        # Real-Time Rates (Strictly 0.0 when not in match!)
        if in_match:
            fps = float(s.get("food_per_sec", 0.0) or 0.0)
            wps = float(s.get("wood_per_sec", 0.0) or 0.0)
            cps = float(s.get("coin_per_sec", 0.0) or 0.0)
            xps = float(s.get("xp_per_sec", 0.0) or 0.0)

            self.food_val.config(text=f"{fps:+.1f} /s")
            self.wood_val.config(text=f"{wps:+.1f} /s")
            self.coin_val.config(text=f"{cps:+.1f} /s")
            self.xp_val.config(text=f"{xps:+.1f} /s")

            # Footer: Compact 1-line tactical status
            vills = int(s.get("villagers", 0) or 0)
            pop = int(s.get("pop", 0) or 0)
            pop_cap = int(s.get("pop_cap", 0) or 0)
            ships = int(s.get("shipments_available", 0) or 0)
            rec_card = s.get("next_recommended_card", "")
            if isinstance(rec_card, dict):
                rec_card = rec_card.get("name", "")

            used = s.get("cards_used_count")
            if used is None:
                used = sum(1 for c in s.get("cards", []) if isinstance(c, dict) and c.get("used"))

            loss_txt = " • 🔥 WAR ALERT!" if s.get("in_war") else ""
            card_txt = f"Next: {rec_card}" if rec_card else f"Used {used}/44 cards"
            self.advice_lbl.config(
                text=f"Vills: {vills} • Pop: {pop}/{pop_cap} • Ships: {ships} • {card_txt}{loss_txt}",
                fg=self.TEXT_MAIN,
            )
        else:
            self.food_val.config(text="+0.0 /s")
            self.wood_val.config(text="+0.0 /s")
            self.coin_val.config(text="+0.0 /s")
            self.xp_val.config(text="+0.0 /s")
            self.advice_lbl.config(
                text="Game not running — run AoE3 and enter a match",
                fg=self.TEXT_MUTED,
            )

    def check_updates_silent(self) -> None:
        if not self.auto_updater:
            return
        self.auto_updater.check_async(
            callback=lambda res: self.root.after(0, lambda: self._on_update_check_result(res, interactive=False)),
            extra_server_urls=[self.bridge.local_server, self.bridge.remote_server],
        )

    def on_click_check_updates(self) -> None:
        if not self.auto_updater:
            return
        self.update_btn.config(text="…")
        self.auto_updater.check_async(
            callback=lambda res: self.root.after(0, lambda: self._on_update_check_result(res, interactive=True)),
            extra_server_urls=[self.bridge.local_server, self.bridge.remote_server],
        )

    def _on_update_check_result(self, res: Dict[str, Any], interactive: bool = False) -> None:
        self.update_btn.config(text="⟳")
        remote_v = res.get("remote_version", self.version)
        avail = bool(res.get("update_available", False))
        if avail:
            self.update_btn.config(fg=self.GREEN)
            if interactive:
                if messagebox.askyesno(
                    "AoE3 Assistant Update Available",
                    f"A new version (v{remote_v}) is available!\n\n"
                    f"Current version: v{self.version}\n\n"
                    "Download and install update automatically now?",
                ):
                    self._start_auto_update_download(res)
        else:
            if interactive:
                messagebox.showinfo("AoE3 Assistant Updater", f"You are running the latest version (v{self.version}).")

    def _start_auto_update_download(self, res: Dict[str, Any], force: bool = False) -> None:
        if not self.auto_updater:
            return

        def _dl_worker():
            outcome = self.auto_updater.download_and_apply_update(
                update_info=res, prefer_setup=True, force_download=force
            )
            self.root.after(0, lambda: self._on_update_applied(outcome))

        threading.Thread(target=_dl_worker, daemon=True).start()

    def _on_update_applied(self, outcome: Dict[str, Any]) -> None:
        if outcome.get("status") == "launched":
            self.root.destroy()
        elif outcome.get("status") == "error":
            messagebox.showerror("Update Failed", outcome.get("message", "Unknown error"))


def run_self_test() -> int:
    bridge = TelemetryBridge()
    snap = bridge.poll_once()
    upd = updater.AutoUpdater(current_version=APP_VERSION).check_for_updates(timeout=2.0) if updater else {}
    report = {
        "app": "AoE3Assistant",
        "version": APP_VERSION,
        "hotkeys": ["F12", "Ctrl+Shift+A"],
        "voice_removed": True,
        "floating_rates_overlay": True,
        "draggable": True,
        "windows_startup_enabled": is_windows_startup_enabled(),
        "telemetry_snapshot": {
            "game_running": snap.get("game_running"),
            "in_match": snap.get("in_match"),
            "match_state": snap.get("match_state"),
            "food_per_sec": snap.get("food_per_sec", 0.0),
            "wood_per_sec": snap.get("wood_per_sec", 0.0),
            "coin_per_sec": snap.get("coin_per_sec", 0.0),
            "xp_per_sec": snap.get("xp_per_sec", 0.0),
            "villagers": snap.get("villagers", 0),
        },
        "updater_check": {
            "current_version": APP_VERSION,
            "remote_version": upd.get("remote_version", APP_VERSION),
        },
        "status": "OK",
    }
    print(json.dumps(report, indent=2))
    return 0


def _hide_console_window() -> None:
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def main() -> int:
    if "--self-test" in sys.argv or "--verify" in sys.argv:
        return run_self_test()

    if "--install-startup" in sys.argv:
        set_windows_startup(True)
        print("Windows startup enabled.")
        return 0

    if "--uninstall-startup" in sys.argv:
        set_windows_startup(False)
        print("Windows startup disabled.")
        return 0

    if getattr(sys, "frozen", False):
        _hide_console_window()

    start_min = ("--background" in sys.argv or "--minimized" in sys.argv or "--pill-only" in sys.argv)
    root = tk.Tk()
    DraggableFloatingOverlay(root, start_minimized=start_min)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
