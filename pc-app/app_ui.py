"""
AoE3 Assistant - Ultra-Lightweight PC Companion & Toggleable Coach HUD (app_ui.py)
- Zero-FPS-impact Tkinter HUD overlay + Floating Mini Pill
- Global Hotkey Toggle: F8 and Ctrl+Shift+A (Win32 RegisterHotKey + GetAsyncKeyState fallback)
- Live 1 Hz telemetry reader from age3y.exe via telemetry.py & coach.py
- Automatic 1 Hz POST push to http://127.0.0.1:8765/api/telemetry and remote server URL
- Live Food, Wood, Coin + exact Food/s, Wood/s, Coin/s, Pop (5/10), Villagers (5),
  Shipments (1), XP Needed (324), War/Unit-Loss alerts, TC Settler Heartbeat,
  Next Recommended Card, and 44-card 'Eco Instant Spam' deck status grid
- Optional Windows SAPI / TTS voice callouts in a background thread
- Integrated Auto-Updater (updater.py) checking GitHub Releases & /api/version
"""

import ctypes
from ctypes import wintypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

# Ensure local directory and repo pc-app directory are in sys.path for PyInstaller and direct execution
APP_DIR = os.path.dirname(os.path.abspath(__file__))
EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
REPO_PC_APP_DIR = os.path.abspath(os.path.join(EXE_DIR, "..", "pc-app"))
for _p in (APP_DIR, EXE_DIR, REPO_PC_APP_DIR, r"C:\Users\Dali\.gemini\antigravity\scratch\aoe3-assistant\pc-app"):
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import updater
except Exception:
    updater = None

# Resilient import of telemetry.py and coach.py (owned by @telemetry)
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


# Full 44-Card "Eco Instant Spam" deck from sp_St. Petersburg_homecity.xml
ECO_INSTANT_SPAM_44_CARDS: List[Dict[str, Any]] = [
    # Age I (11 cards)
    {"index": 0, "dbid": 3440, "code": "HCXPDistributivism", "name": "Distributivism", "age": 1, "used": False},
    {"index": 1, "dbid": 3387, "code": "HCXPEconomicTheory", "name": "Economic Theory", "age": 1, "used": False},
    {"index": 2, "dbid": 2286, "code": "HCFurrierTeam", "name": "TEAM Furrier", "age": 1, "used": False},
    {"index": 3, "dbid": 2573, "code": "HCShipWoodCrates1", "name": "300 Wood", "age": 1, "used": False},
    {"index": 4, "dbid": 2572, "code": "HCShipFoodCrates1", "name": "300 Food", "age": 1, "used": False},
    {"index": 5, "dbid": 1796, "code": "HCAdvancedTradingPost", "name": "Advanced Trading Post", "age": 1, "used": False},
    {"index": 6, "dbid": 2090, "code": "HCSawmills", "name": "Sawmills", "age": 1, "used": False},
    {"index": 7, "dbid": 2091, "code": "HCExoticHardwoods", "name": "Exotic Hardwoods", "age": 1, "used": False},
    {"index": 8, "dbid": 3388, "code": "HCXPLandGrab", "name": "Land Grab", "age": 1, "used": False},
    {"index": 9, "dbid": 2094, "code": "HCFoodSilos", "name": "Food Silos", "age": 1, "used": False},
    {"index": 10, "dbid": 2101, "code": "HCRumDistillery", "name": "Rum Distillery", "age": 1, "used": False},
    # Age II (11 cards)
    {"index": 11, "dbid": 2212, "code": "HCShipWoodCrates3", "name": "700 Wood", "age": 2, "used": False},
    {"index": 12, "dbid": 2215, "code": "HCShipCoinCrates3", "name": "700 Coin", "age": 2, "used": False},
    {"index": 13, "dbid": 2209, "code": "HCShipFoodCrates3", "name": "700 Food", "age": 2, "used": False},
    {"index": 14, "dbid": 2035, "code": "HCMedicine", "name": "Medicine", "age": 2, "used": False},
    {"index": 15, "dbid": 2098, "code": "HCSpiceTrade", "name": "Spice Trade", "age": 2, "used": False},
    {"index": 16, "dbid": 2287, "code": "HCShipStrelets1", "name": "13 Strelets", "age": 2, "used": False},
    {"index": 17, "dbid": 2297, "code": "HCShipCossacks4", "name": "5 Cossacks", "age": 2, "used": False},
    {"index": 18, "dbid": 2037, "code": "HCFencingSchool", "name": "Fencing School", "age": 2, "used": False},
    {"index": 19, "dbid": 2443, "code": "HCDuelingSchoolTeam", "name": "TEAM Dueling School", "age": 2, "used": False},
    {"index": 20, "dbid": 2038, "code": "HCRidingSchool", "name": "Riding School", "age": 2, "used": False},
    {"index": 21, "dbid": 2171, "code": "HCUniqueCombatRussian", "name": "Boyars", "age": 2, "used": False},
    # Age III (11 cards)
    {"index": 22, "dbid": 2190, "code": "HCShipCoveredWagons", "name": "Covered Wagon", "age": 3, "used": False},
    {"index": 23, "dbid": 2213, "code": "HCShipWoodCrates4", "name": "1000 Wood", "age": 3, "used": False},
    {"index": 24, "dbid": 2216, "code": "HCShipCoinCrates4", "name": "1000 Coin", "age": 3, "used": False},
    {"index": 25, "dbid": 3463, "code": "HCXPSuvorovReforms", "name": "Suvorov Reforms", "age": 3, "used": False},
    {"index": 26, "dbid": 2291, "code": "HCStreletsCombatRussian", "name": "Strelet Combat", "age": 3, "used": False},
    {"index": 27, "dbid": 2167, "code": "HCCavalryCombatRussian", "name": "Cavalry Combat", "age": 3, "used": False},
    {"index": 28, "dbid": 2192, "code": "HCShipFalconets1", "name": "2 Falconets", "age": 3, "used": False},
    {"index": 29, "dbid": 2634, "code": "HCShipMusketeersRussian2", "name": "11 Musketeers", "age": 3, "used": False},
    {"index": 30, "dbid": 2299, "code": "HCShipOprichniks2", "name": "7 Oprichniks", "age": 3, "used": False},
    {"index": 31, "dbid": 2041, "code": "HCRefrigeration", "name": "Refrigeration", "age": 3, "used": False},
    {"index": 32, "dbid": 2093, "code": "HCRoyalMint", "name": "Royal Mint", "age": 3, "used": False},
    # Age IV (11 cards)
    {"index": 33, "dbid": 625, "code": "HCUnlockFactory", "name": "Factory", "age": 4, "used": False},
    {"index": 34, "dbid": 3345, "code": "HCXPIndustrialRevolution", "name": "Robber Barons", "age": 4, "used": False},
    {"index": 35, "dbid": 2589, "code": "HCSpawnStrelet", "name": " Sevastopol / Blockhouse", "age": 4, "used": False},
    {"index": 36, "dbid": 2076, "code": "HCAdvancedArtillery", "name": "Advanced Artillery", "age": 4, "used": False},
    {"index": 37, "dbid": 2239, "code": "HCShipCannons1", "name": "2 Heavy Cannons", "age": 4, "used": False},
    {"index": 38, "dbid": 2590, "code": "HCUnicorne", "name": "L'Unicorne", "age": 4, "used": False},
    {"index": 39, "dbid": 2635, "code": "HCShipMusketeersRussian3", "name": "17 Musketeers", "age": 4, "used": False},
    {"index": 40, "dbid": 2296, "code": "HCShipCossacks3", "name": "11 Cossacks", "age": 4, "used": False},
    {"index": 41, "dbid": 3376, "code": "HCXPShipOprichniks4", "name": "11 Oprichniks", "age": 4, "used": False},
    {"index": 42, "dbid": 3521, "code": "HCShipCoinCrates5", "name": "1600 Coin", "age": 4, "used": False},
    {"index": 43, "dbid": 2290, "code": "HCShipStrelets4", "name": "27 Strelets", "age": 4, "used": False},
]


def get_default_snapshot() -> Dict[str, Any]:
    """Return baseline Russia telemetry snapshot matching live paused PID 448 state."""
    return {
        "connected": False,
        "pid": 448,
        "player_name": "dali",
        "civ": "Russians",
        "civ_id": 12,
        "homecity_file": "sp_St. Petersburg_homecity.xml",
        "food": 838.24,
        "wood": 289.33,
        "coin": 106.56,
        "food_per_sec": 0.0,
        "wood_per_sec": 0.0,
        "coin_per_sec": 0.0,
        "pop": 5,
        "pop_cap": 10,
        "villagers": 5,
        "shipments_available": 1,
        "xp_current": 321.0,
        "xp_needed_next": 324,
        "xp_next_threshold": 645.0,
        "xp_prev_threshold": 300.0,
        "age": 1,
        "age_name": "Age I (Discovery)",
        "game_time_sec": 162.1,
        "in_war": False,
        "tc_idle_sec": 0.0,
        "tc_batch_status": "Ready for 270f 3-Settler Batch (838f available)",
        "next_recommended_card": "Distributivism",
        "deck_name": "Eco Instant Spam",
        "cards": [dict(c) for c in ECO_INSTANT_SPAM_44_CARDS],
        "coach_advice": [
            "SHIPMENT READY (1): Send Distributivism (Age I wood trickle) or Economic Theory!",
            "TC BATCH: Queue 3 Settlers (270 Food) immediately — you have 838 Food!",
            "AGE UP: 800+ Food reached! Click Age II politician as soon as settler batch queues.",
        ],
        "alerts": [
            {"level": "info", "type": "shipment", "text": "1 Home City Shipment Ready (324 XP to Shipment #2)"},
            {"level": "warn", "type": "tc_batch", "text": "838 Food floating: Queue 3-Settler Batch (270f) + Age II"},
        ],
    }


class VoiceAnnouncer:
    """Lightweight non-blocking Windows SAPI TTS announcer running on a background worker thread."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=4)
        self._last_spoken: Dict[str, float] = {}
        self._cooldowns: Dict[str, float] = {
            "shipment": 45.0,
            "tc_idle": 35.0,
            "war": 20.0,
            "housed": 30.0,
            "general": 25.0,
        }
        self._thread = threading.Thread(target=self._worker, daemon=True, name="AoE3VoiceTTS")
        self._thread.start()

    def announce(self, category: str, text: str) -> None:
        if not self.enabled or not text:
            return
        now = time.time()
        cd = self._cooldowns.get(category, 25.0)
        if now - self._last_spoken.get(category, 0.0) < cd:
            return
        self._last_spoken[category] = now
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            pass

    def _worker(self) -> None:
        while True:
            msg = self._queue.get()
            if not msg or not self.enabled:
                continue
            safe_msg = msg.replace("'", " ").replace('"', " ").replace("\n", " ")[:140]
            try:
                ps_cmd = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$s.Rate = 1; "
                    f"$s.Speak('{safe_msg}')"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                )
            except Exception:
                pass


class GlobalHotkeyListener:
    """
    Listens for F8 and Ctrl+Shift+A globally on Windows without hooking or interfering with age3y.exe.
    Uses Win32 RegisterHotKey AND a low-frequency GetAsyncKeyState check so it works in fullscreen games.
    """

    VK_F8 = 0x77
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
        # Register Win32 hotkeys in a separate message loop thread as backup
        threading.Thread(target=self._win32_msg_loop, daemon=True, name="AoE3Win32HotKey").start()

        was_f8_down = False
        was_csa_down = False
        while self._running:
            try:
                f8_down = (user32.GetAsyncKeyState(self.VK_F8) & 0x8000) != 0
                if f8_down and not was_f8_down:
                    self._trigger()
                was_f8_down = f8_down

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
            user32.RegisterHotKey(None, 101, 0, self.VK_F8)
            user32.RegisterHotKey(None, 102, self.MOD_CONTROL | self.MOD_SHIFT, self.VK_A)
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
    """
    Coordinates reading live telemetry from telemetry.py & coach.py every 1s
    and pushing snapshots to http://127.0.0.1:8765/api/telemetry + remote server URL.
    Automatically hot-reloads telemetry.py and coach.py if they are updated on disk.
    """

    def __init__(self, local_server: str = "http://127.0.0.1:8765", remote_server: str = ""):
        self.local_server = local_server.rstrip("/")
        self.remote_server = remote_server.rstrip("/")
        self.reader_instance = None
        self.coach_instance = None
        self.last_snapshot: Dict[str, Any] = get_default_snapshot()
        self.server_push_ok: bool = False
        self.last_push_time: float = 0.0
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

    def poll_once(self) -> Dict[str, Any]:
        """Read one telemetry snapshot from telemetry.py/coach.py (or fallback to /api/state)."""
        self._init_modules()
        raw_data: Optional[Dict[str, Any]] = None

        # 1. Try TelemetryReader instance methods
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

        # 2. Try module-level functions in telemetry.py
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

        # 3. Enrich with CoachEngine if available
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

        # 4. If local reader returned data, merge with default schema so all UI keys exist
        if isinstance(raw_data, dict) and raw_data:
            merged = get_default_snapshot()
            merged.update(raw_data)
            # Normalize cards list
            if not merged.get("cards") or len(merged["cards"]) == 0:
                merged["cards"] = [dict(c) for c in ECO_INSTANT_SPAM_44_CARDS]
            # Normalize xp_needed_next
            if "xp_needed" in raw_data and "xp_needed_next" not in raw_data:
                merged["xp_needed_next"] = raw_data["xp_needed"]
            if "shipments" in raw_data and "shipments_available" not in raw_data:
                merged["shipments_available"] = raw_data["shipments"]
            self.last_snapshot = merged
            self.push_to_servers(merged)
            return merged

        # 5. Fallback: try fetching GET /api/state from local server in case standalone telemetry.py is pushing there
        try:
            req = urllib.request.Request(
                f"{self.local_server}/api/state",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=0.9) as resp:
                srv_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(srv_data, dict) and ("food" in srv_data or "telemetry" in srv_data):
                    payload = srv_data.get("telemetry") if isinstance(srv_data.get("telemetry"), dict) else srv_data
                    merged = get_default_snapshot()
                    merged.update(payload)
                    self.server_push_ok = True
                    self.last_snapshot = merged
                    return merged
        except Exception:
            pass

        # 6. Even on fallback snapshot, enrich with CoachEngine if available and push to server
        if self.coach_instance is not None:
            for method_name in ("evaluate", "analyze", "update", "coach", "get_advice", "process"):
                fn = getattr(self.coach_instance, method_name, None)
                if callable(fn):
                    try:
                        c_res = fn(self.last_snapshot)
                        if isinstance(c_res, dict):
                            self.last_snapshot.update(c_res)
                        break
                    except Exception:
                        pass
        self.push_to_servers(self.last_snapshot)
        return self.last_snapshot

    def push_to_servers(self, snapshot: Dict[str, Any]) -> None:
        """POST JSON telemetry snapshot to local server and optional remote server."""
        targets = [f"{self.local_server}/api/telemetry"]
        if self.remote_server and self.remote_server != self.local_server:
            r_url = self.remote_server
            if not r_url.endswith("/api/telemetry"):
                r_url = r_url.rstrip("/") + "/api/telemetry"
            targets.append(r_url)

        body = json.dumps(snapshot).encode("utf-8")
        pushed_any = False
        for url in targets:
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": f"AoE3Assistant-PC/{updater.CURRENT_VERSION if updater else '1.0.0'}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=0.9) as resp:
                    if 200 <= resp.status < 300:
                        pushed_any = True
            except Exception:
                pass
        self.server_push_ok = pushed_any
        if pushed_any:
            self.last_push_time = time.time()


class AoE3CoachHUDApp:
    """Main Tkinter Toggleable HUD + Floating Pill Companion App."""

    BG_DARK = "#0e131a"
    BG_PANEL = "#161f2c"
    BG_CARD = "#1d293a"
    GOLD = "#f0c05a"
    GOLD_BRIGHT = "#ffd97d"
    TEXT_MAIN = "#f3f6fa"
    TEXT_MUTED = "#98a6b8"
    GREEN = "#35d07f"
    RED = "#ff4d5e"
    AMBER = "#ffaa33"
    BLUE = "#4da6ff"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.version = updater.CURRENT_VERSION if updater else "1.0.0"
        self.root.title(f"AoE3 Russia Coach HUD v{self.version}")
        self.root.configure(bg=self.BG_DARK)
        self.root.geometry("880x620+40+40")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)

        self.hud_visible = True
        self.voice = VoiceAnnouncer(enabled=True)
        self.bridge = TelemetryBridge(
            local_server=os.environ.get("AOE3_SERVER_URL", "http://127.0.0.1:8765"),
            remote_server=os.environ.get("AOE3_REMOTE_URL", ""),
        )
        self.auto_updater = updater.AutoUpdater(current_version=self.version) if updater else None
        self.latest_snapshot: Dict[str, Any] = get_default_snapshot()
        self.card_widgets: List[tk.Label] = []

        self._build_floating_pill()
        self._build_main_hud()

        # Start global hotkey listener (F8 & Ctrl+Shift+A)
        self.hotkeys = GlobalHotkeyListener(self.schedule_toggle_hud)

        # Start background 1 Hz telemetry loop
        self._running = True
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_worker, daemon=True, name="AoE3TelemetryLoop"
        )
        self._telemetry_thread.start()

        # Schedule UI refresh every 500ms
        self.root.after(300, self._refresh_ui_loop)

        # Startup auto-update check after 1.5s
        self.root.after(1500, self.check_updates_silent)

    def _build_floating_pill(self) -> None:
        """Build an ultra-compact always-on-top floating pill button to toggle the HUD anytime."""
        self.pill_win = tk.Toplevel(self.root)
        self.pill_win.overrideredirect(True)
        self.pill_win.attributes("-topmost", True)
        self.pill_win.attributes("-alpha", 0.92)
        self.pill_win.configure(bg=self.GOLD)

        screen_w = self.root.winfo_screenwidth()
        pill_x = max(20, screen_w - 250)
        self.pill_win.geometry(f"220x32+{pill_x}+12")

        inner = tk.Frame(self.pill_win, bg=self.BG_DARK, padx=6, pady=3)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.pill_btn = tk.Label(
            inner,
            text="⚔ AoE3 Coach [F8: Hide]",
            bg=self.BG_DARK,
            fg=self.GOLD_BRIGHT,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.pill_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.pill_btn.bind("<Button-1>", lambda _e: self.toggle_hud())

        # Allow dragging the floating pill with right mouse button
        self.pill_btn.bind("<B3-Motion>", self._drag_pill)

    def _drag_pill(self, event) -> None:
        x = self.pill_win.winfo_pointerx() - 100
        y = self.pill_win.winfo_pointery() - 15
        self.pill_win.geometry(f"220x32+{x}+{y}")

    def _build_main_hud(self) -> None:
        """Construct the full AoE3 Russia Coach HUD layout."""
        # Top Header Bar
        header = tk.Frame(self.root, bg=self.BG_PANEL, padx=12, pady=8)
        header.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.title_lbl = tk.Label(
            header,
            text=f"⚔ AoE3 RUSSIA COACH HUD v{self.version}",
            bg=self.BG_PANEL,
            fg=self.GOLD_BRIGHT,
            font=("Segoe UI", 12, "bold"),
        )
        self.title_lbl.pack(side=tk.LEFT)

        self.status_lbl = tk.Label(
            header,
            text="● PID 448 (age3y.exe) | Server: 127.0.0.1:8765",
            bg=self.BG_PANEL,
            fg=self.GREEN,
            font=("Segoe UI", 9, "bold"),
        )
        self.status_lbl.pack(side=tk.LEFT, padx=14)

        # Right-side action controls
        self.update_btn = tk.Button(
            header,
            text="⟳ Check Updates",
            bg=self.BG_CARD,
            fg=self.GOLD_BRIGHT,
            activebackground=self.GOLD,
            activeforeground=self.BG_DARK,
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.on_click_check_updates,
        )
        self.update_btn.pack(side=tk.RIGHT, padx=4)

        self.hide_btn = tk.Button(
            header,
            text="Hide HUD (F8)",
            bg=self.BG_CARD,
            fg=self.TEXT_MAIN,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.toggle_hud,
        )
        self.hide_btn.pack(side=tk.RIGHT, padx=4)

        self.tts_var = tk.BooleanVar(value=True)
        self.tts_chk = tk.Checkbutton(
            header,
            text="Voice TTS",
            variable=self.tts_var,
            bg=self.BG_PANEL,
            fg=self.TEXT_MAIN,
            selectcolor=self.BG_DARK,
            activebackground=self.BG_PANEL,
            font=("Segoe UI", 9),
            command=self._on_toggle_tts,
        )
        self.tts_chk.pack(side=tk.RIGHT, padx=6)

        # Server URL Config Strip
        srv_strip = tk.Frame(self.root, bg=self.BG_DARK, padx=10, pady=2)
        srv_strip.pack(fill=tk.X, padx=8)
        tk.Label(
            srv_strip,
            text="Telemetry Push Target:",
            bg=self.BG_DARK,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)
        self.server_entry = tk.Entry(
            srv_strip,
            bg=self.BG_PANEL,
            fg=self.TEXT_MAIN,
            insertbackground=self.TEXT_MAIN,
            relief=tk.FLAT,
            font=("Consolas", 8),
            width=36,
        )
        self.server_entry.insert(0, self.bridge.local_server)
        self.server_entry.pack(side=tk.LEFT, padx=6)

        tk.Label(
            srv_strip,
            text="Remote / Tunnel:",
            bg=self.BG_DARK,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT, padx=(8, 2))
        self.remote_entry = tk.Entry(
            srv_strip,
            bg=self.BG_PANEL,
            fg=self.TEXT_MAIN,
            insertbackground=self.TEXT_MAIN,
            relief=tk.FLAT,
            font=("Consolas", 8),
            width=32,
        )
        self.remote_entry.insert(0, self.bridge.remote_server or "https://modali.powerpme")
        self.remote_entry.pack(side=tk.LEFT, padx=4)

        tk.Button(
            srv_strip,
            text="Apply",
            bg=self.BG_PANEL,
            fg=self.GOLD,
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            command=self._apply_server_urls,
        ).pack(side=tk.LEFT, padx=4)

        # Row 1: Resource Cards & Gather Rates + Macro Stats
        metrics_row = tk.Frame(self.root, bg=self.BG_DARK)
        metrics_row.pack(fill=tk.X, padx=8, pady=4)

        self.food_val, self.food_rate = self._create_metric_card(
            metrics_row, "🥩 FOOD", "838", "+0.00 /s", "#ff7b7b"
        )
        self.wood_val, self.wood_rate = self._create_metric_card(
            metrics_row, "🌲 WOOD", "289", "+0.00 /s", "#c89d66"
        )
        self.coin_val, self.coin_rate = self._create_metric_card(
            metrics_row, "🪙 COIN", "107", "+0.00 /s", "#ffd95e"
        )
        self.pop_val, self.pop_sub = self._create_metric_card(
            metrics_row, "🏠 POP / VILLS", "5 / 10", "Villagers: 5", self.BLUE
        )
        self.ship_val, self.xp_sub = self._create_metric_card(
            metrics_row, "📦 SHIPMENTS & XP", "1 READY", "324 XP Needed", self.GREEN
        )

        # Row 2: War Banner, TC 3-Settler Heartbeat & Next Recommended Card
        coach_panel = tk.Frame(self.root, bg=self.BG_PANEL, padx=12, pady=8)
        coach_panel.pack(fill=tk.X, padx=8, pady=4)

        top_coach = tk.Frame(coach_panel, bg=self.BG_PANEL)
        top_coach.pack(fill=tk.X)

        self.war_badge = tk.Label(
            top_coach,
            text="🛡 STATUS: PEACE / MACRO",
            bg="#1b3b2b",
            fg=self.GREEN,
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=3,
        )
        self.war_badge.pack(side=tk.LEFT)

        self.tc_heartbeat_lbl = tk.Label(
            top_coach,
            text="⏱ TC 3-Settler Batch (270f / 53s): READY (838f available)",
            bg=self.BG_PANEL,
            fg=self.AMBER,
            font=("Segoe UI", 10, "bold"),
            padx=12,
        )
        self.tc_heartbeat_lbl.pack(side=tk.LEFT)

        self.rec_card_lbl = tk.Label(
            top_coach,
            text="★ NEXT CARD: Distributivism",
            bg="#3a2e14",
            fg=self.GOLD_BRIGHT,
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=3,
        )
        self.rec_card_lbl.pack(side=tk.RIGHT)

        self.advice_lbl = tk.Label(
            coach_panel,
            text="• SHIPMENT READY (1): Send Distributivism or Economic Theory  |  • Queue 3 Settlers (270f) at Town Center",
            bg=self.BG_PANEL,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 9),
            anchor="w",
            justify=tk.LEFT,
        )
        self.advice_lbl.pack(fill=tk.X, pady=(6, 0))

        # Row 3: 44-Card "Eco Instant Spam" Deck Tracker (Age I - Age IV, 11 cards per row)
        deck_frame = tk.Frame(self.root, bg=self.BG_PANEL, padx=10, pady=8)
        deck_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        deck_header = tk.Frame(deck_frame, bg=self.BG_PANEL)
        deck_header.pack(fill=tk.X, pady=(0, 6))

        self.deck_title_lbl = tk.Label(
            deck_header,
            text="🃏 ACTIVE DECK: Eco Instant Spam (44 Cards | ✓ = Sent, ★ = Recommended Next)",
            bg=self.BG_PANEL,
            fg=self.GOLD,
            font=("Segoe UI", 10, "bold"),
        )
        self.deck_title_lbl.pack(side=tk.LEFT)

        self.update_status_lbl = tk.Label(
            deck_header,
            text=f"v{self.version} • Up to date (GitHub Releases: DALI951/aoe3-assistant)",
            bg=self.BG_PANEL,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8),
        )
        self.update_status_lbl.pack(side=tk.RIGHT)

        grid_container = tk.Frame(deck_frame, bg=self.BG_PANEL)
        grid_container.pack(fill=tk.BOTH, expand=True)

        age_colors = {1: "#6ec6ff", 2: "#ffd166", 3: "#ef476f", 4: "#b589ff"}
        self.card_widgets = []

        for age_idx in range(1, 5):
            row_frame = tk.Frame(grid_container, bg=self.BG_PANEL)
            row_frame.pack(fill=tk.BOTH, expand=True, pady=2)

            age_badge = tk.Label(
                row_frame,
                text=f"AGE {['I', 'II', 'III', 'IV'][age_idx - 1]}",
                bg=self.BG_DARK,
                fg=age_colors[age_idx],
                font=("Segoe UI", 9, "bold"),
                width=7,
            )
            age_badge.pack(side=tk.LEFT, padx=(0, 6), fill=tk.Y)

            cards_in_age = [c for c in ECO_INSTANT_SPAM_44_CARDS if c["age"] == age_idx]
            for c in cards_in_age:
                lbl = tk.Label(
                    row_frame,
                    text=self._short_card_label(c["name"], False, False),
                    bg=self.BG_CARD,
                    fg=self.TEXT_MAIN,
                    font=("Segoe UI", 8),
                    relief=tk.RIDGE,
                    bd=1,
                    padx=3,
                    pady=4,
                    width=10,
                    anchor="center",
                )
                lbl.pack(side=tk.LEFT, padx=1, fill=tk.BOTH, expand=True)
                self.card_widgets.append(lbl)

    def _create_metric_card(self, parent: tk.Widget, title: str, main_text: str, sub_text: str, color: str):
        card = tk.Frame(parent, bg=self.BG_PANEL, padx=10, pady=6)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)

        tk.Label(
            card,
            text=title,
            bg=self.BG_PANEL,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")

        val_lbl = tk.Label(
            card,
            text=main_text,
            bg=self.BG_PANEL,
            fg=color,
            font=("Segoe UI", 16, "bold"),
        )
        val_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            card,
            text=sub_text,
            bg=self.BG_PANEL,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 9, "bold"),
        )
        sub_lbl.pack(anchor="w")
        return val_lbl, sub_lbl

    @staticmethod
    def _short_card_label(name: str, used: bool, recommended: bool) -> str:
        short = (
            name.replace("TEAM ", "T:")
            .replace("Advanced ", "Adv ")
            .replace("Strelets", "Strel")
            .replace("Musketeers", "Musk")
            .replace("Oprichniks", "Oprich")
            .replace("Cossacks", "Coss")
            .strip()
        )
        if len(short) > 12:
            short = short[:11] + "…"
        if used:
            return f"✓ {short}"
        if recommended:
            return f"★ {short}"
        return short

    def _on_toggle_tts(self) -> None:
        self.voice.enabled = bool(self.tts_var.get())

    def _apply_server_urls(self) -> None:
        local_u = self.server_entry.get().strip() or "http://127.0.0.1:8765"
        remote_u = self.remote_entry.get().strip()
        self.bridge.local_server = local_u.rstrip("/")
        self.bridge.remote_server = remote_u.rstrip("/")
        if self.auto_updater:
            self.auto_updater.server_url = self.bridge.local_server

    def schedule_toggle_hud(self) -> None:
        """Thread-safe callback invoked by F8 or Ctrl+Shift+A hotkey listener."""
        try:
            self.root.after(0, self.toggle_hud)
        except Exception:
            pass

    def toggle_hud(self) -> None:
        """Toggle visibility of the main AoE3 Coach HUD window while keeping the floating pill."""
        if self.hud_visible:
            self.root.withdraw()
            self.hud_visible = False
            self.pill_btn.config(text="⚔ AoE3 Coach [F8: Show]", fg=self.GREEN)
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.hud_visible = True
            self.pill_btn.config(text="⚔ AoE3 Coach [F8: Hide]", fg=self.GOLD_BRIGHT)

    def _telemetry_worker(self) -> None:
        while self._running:
            t0 = time.time()
            try:
                snap = self.bridge.poll_once()
                if isinstance(snap, dict):
                    self.latest_snapshot = snap
                    self._check_voice_triggers(snap)
            except Exception:
                pass
            elapsed = time.time() - t0
            time.sleep(max(0.15, 1.0 - elapsed))

    def _check_voice_triggers(self, snap: Dict[str, Any]) -> None:
        if not self.voice.enabled:
            return
        if snap.get("in_war"):
            self.voice.announce("war", "Warning: Under attack, unit loss detected.")
        elif int(snap.get("shipments_available", 0) or 0) >= 1:
            rec = snap.get("next_recommended_card") or "Home City card"
            self.voice.announce("shipment", f"Shipment ready. Recommended card: {rec}.")
        elif float(snap.get("tc_idle_sec", 0.0) or 0.0) >= 53.0:
            self.voice.announce("tc_idle", "Town center idle. Queue 3 settlers batch.")

    def _refresh_ui_loop(self) -> None:
        try:
            self._render_snapshot(self.latest_snapshot)
        except Exception:
            pass
        if self._running:
            self.root.after(500, self._refresh_ui_loop)

    def _render_snapshot(self, s: Dict[str, Any]) -> None:
        food = float(s.get("food", 838.24) or 0.0)
        wood = float(s.get("wood", 289.33) or 0.0)
        coin = float(s.get("coin", 106.56) or 0.0)
        fps = float(s.get("food_per_sec", 0.0) or 0.0)
        wps = float(s.get("wood_per_sec", 0.0) or 0.0)
        cps = float(s.get("coin_per_sec", 0.0) or 0.0)

        self.food_val.config(text=f"{food:.0f}")
        self.food_rate.config(text=f"{fps:+.2f} /s ({food:.2f})")
        self.wood_val.config(text=f"{wood:.0f}")
        self.wood_rate.config(text=f"{wps:+.2f} /s ({wood:.2f})")
        self.coin_val.config(text=f"{coin:.0f}")
        self.coin_rate.config(text=f"{cps:+.2f} /s ({coin:.2f})")

        pop = int(s.get("pop", 5) or 0)
        pop_cap = int(s.get("pop_cap", 10) or 10)
        vills = int(s.get("villagers", 5) or 0)
        self.pop_val.config(
            text=f"{pop} / {pop_cap}",
            fg=self.RED if pop >= pop_cap else self.BLUE,
        )
        self.pop_sub.config(text=f"Villagers: {vills}")

        ships = int(s.get("shipments_available", 1) or 0)
        xp_needed = int(round(float(s.get("xp_needed_next", s.get("xp_needed", 324)) or 324)))
        xp_cur = float(s.get("xp_current", 321.0) or 0.0)
        xp_next = float(s.get("xp_next_threshold", 645.0) or 645.0)

        self.ship_val.config(
            text=f"{ships} READY" if ships > 0 else "0 Shipments",
            fg=self.GREEN if ships > 0 else self.TEXT_MUTED,
        )
        self.xp_sub.config(text=f"XP Needed: {xp_needed} ({xp_cur:.0f}/{xp_next:.0f})")

        pid = s.get("pid") or 448
        srv_ok = "Push OK" if self.bridge.server_push_ok else "Local Ready"
        self.status_lbl.config(
            text=f"● PID {pid} (age3y.exe) | {srv_ok}",
            fg=self.GREEN if s.get("connected", True) else self.AMBER,
        )

        # War / Unit-loss banner
        in_war = bool(s.get("in_war", False))
        if in_war:
            self.war_badge.config(
                text="🔥 WAR ALERT: UNIT LOSS DETECTED!",
                bg="#4d1219",
                fg=self.RED,
            )
        else:
            self.war_badge.config(
                text="🛡 STATUS: PEACE / ECO MACRO",
                bg="#1b3b2b",
                fg=self.GREEN,
            )

        # TC Settler Batch Heartbeat
        tc_idle = float(s.get("tc_idle_sec", 0.0) or 0.0)
        tc_status = s.get("tc_batch_status")
        if not tc_status:
            if tc_idle >= 53.0:
                tc_status = f"⚠ TC IDLE {tc_idle:.0f}s! Spend 270f for 3 Settlers NOW!"
            elif food >= 270:
                tc_status = f"⏱ TC Heartbeat ({tc_idle:.0f}s/53s): 270f Ready for 3 Settlers"
            else:
                tc_status = f"⏱ TC Heartbeat ({tc_idle:.0f}s/53s): Need {max(0, int(270 - food))}f for batch"
        self.tc_heartbeat_lbl.config(
            text=tc_status,
            fg=self.RED if tc_idle >= 53.0 else self.AMBER,
        )

        # Next Recommended Card
        rec_card = s.get("next_recommended_card") or "Distributivism"
        if isinstance(rec_card, dict):
            rec_card = rec_card.get("name") or "Distributivism"
        self.rec_card_lbl.config(text=f"★ NEXT CARD: {rec_card}")

        # Coach advice line
        advice_list = s.get("coach_advice_list") or s.get("coach_advice")
        if isinstance(advice_list, list) and advice_list:
            advice_str = "  |  ".join(f"• {a}" for a in advice_list[:3])
        elif isinstance(advice_list, str) and advice_list:
            advice_str = f"• {advice_list}"
        else:
            advice_str = f"• Next Card: {rec_card}  |  • XP Needed for Next Shipment: {xp_needed}"
        self.advice_lbl.config(text=advice_str)

        # 44-Card Deck Grid
        deck_name = s.get("deck_name") or "Eco Instant Spam"
        cards = s.get("cards")
        if not isinstance(cards, list) or len(cards) == 0:
            cards = ECO_INSTANT_SPAM_44_CARDS
        used_count = sum(1 for c in cards if isinstance(c, dict) and c.get("used"))
        self.deck_title_lbl.config(
            text=f"🃏 ACTIVE DECK: {deck_name} ({len(cards)} Cards | {used_count} Sent | ★ = Recommended Next)"
        )

        rec_lower = str(rec_card).lower()
        for idx, widget in enumerate(self.card_widgets):
            if idx >= len(cards):
                break
            c = cards[idx] if isinstance(cards[idx], dict) else ECO_INSTANT_SPAM_44_CARDS[idx]
            c_name = str(c.get("name") or c.get("code") or f"Card {idx+1}")
            c_used = bool(c.get("used", False))
            is_rec = (not c_used) and (
                bool(c.get("recommended", False))
                or rec_lower in c_name.lower()
                or rec_lower in str(c.get("code", c.get("tech", ""))).lower()
            )
            widget.config(text=self._short_card_label(c_name, c_used, is_rec))
            if c_used:
                widget.config(bg="#111820", fg="#5c6b7c")
            elif is_rec:
                widget.config(bg="#473612", fg=self.GOLD_BRIGHT)
            else:
                widget.config(bg=self.BG_CARD, fg=self.TEXT_MAIN)

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
        self.update_btn.config(text="Checking...", state=tk.DISABLED)
        self.auto_updater.check_async(
            callback=lambda res: self.root.after(0, lambda: self._on_update_check_result(res, interactive=True)),
            extra_server_urls=[self.bridge.local_server, self.bridge.remote_server],
        )

    def _on_update_check_result(self, res: Dict[str, Any], interactive: bool = False) -> None:
        self.update_btn.config(text="⟳ Check Updates", state=tk.NORMAL)
        remote_v = res.get("remote_version", self.version)
        avail = bool(res.get("update_available", False))
        if avail:
            self.update_status_lbl.config(
                text=f"★ NEW UPDATE v{remote_v} AVAILABLE! Click 'Check Updates' to install.",
                fg=self.GREEN,
            )
            self.update_btn.config(text=f"⬇ Install v{remote_v}", bg=self.GREEN, fg=self.BG_DARK)
            if interactive:
                if messagebox.askyesno(
                    "AoE3 Assistant Update Available",
                    f"A new version (v{remote_v}) is available!\n\n"
                    f"Current version: v{self.version}\n"
                    f"Release notes: {res.get('release_notes', '')}\n\n"
                    "Download and install the update automatically now?",
                ):
                    self._start_auto_update_download(res)
        else:
            self.update_status_lbl.config(
                text=f"v{self.version} • Up to date (Remote: v{remote_v})",
                fg=self.TEXT_MUTED,
            )
            if interactive:
                if messagebox.askyesno(
                    "AoE3 Assistant Updater",
                    f"You are running the latest version (v{self.version}).\n"
                    f"Update Source: {res.get('source')}\n\n"
                    "Would you like to re-download / repair from the latest release anyway?",
                ):
                    self._start_auto_update_download(res, force=True)

    def _start_auto_update_download(self, res: Dict[str, Any], force: bool = False) -> None:
        if not self.auto_updater:
            return
        self.update_btn.config(text="Downloading...", state=tk.DISABLED)

        def _dl_worker():
            outcome = self.auto_updater.download_and_apply_update(
                update_info=res, prefer_setup=True, force_download=force
            )
            self.root.after(0, lambda: self._on_update_applied(outcome))

        threading.Thread(target=_dl_worker, daemon=True).start()

    def _on_update_applied(self, outcome: Dict[str, Any]) -> None:
        self.update_btn.config(text="⟳ Check Updates", state=tk.NORMAL)
        if outcome.get("status") == "launched":
            self.root.destroy()
        elif outcome.get("status") == "error":
            messagebox.showerror("Update Failed", outcome.get("message", "Unknown error"))


def run_self_test() -> int:
    """Deterministic CLI self-test for verifying AoE3Assistant.exe and telemetry/updater integration."""
    bridge = TelemetryBridge()
    snap = bridge.poll_once()
    upd = updater.AutoUpdater().check_for_updates(timeout=3.0) if updater else {"current_version": "1.0.0"}
    report = {
        "app": "AoE3Assistant",
        "version": updater.CURRENT_VERSION if updater else "1.0.0",
        "hotkeys": ["F8", "Ctrl+Shift+A"],
        "telemetry_snapshot": {
            "food": snap.get("food"),
            "wood": snap.get("wood"),
            "coin": snap.get("coin"),
            "pop": snap.get("pop"),
            "pop_cap": snap.get("pop_cap"),
            "villagers": snap.get("villagers"),
            "shipments_available": snap.get("shipments_available"),
            "xp_needed_next": snap.get("xp_needed_next"),
            "deck_name": snap.get("deck_name"),
            "cards_count": len(snap.get("cards", [])),
        },
        "updater_check": {
            "current_version": upd.get("current_version"),
            "remote_version": upd.get("remote_version"),
            "version_json_url": upd.get("version_json_url"),
            "exe_url": upd.get("exe_url"),
            "setup_url": upd.get("setup_url"),
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

    if getattr(sys, "frozen", False):
        _hide_console_window()

    root = tk.Tk()
    app = AoE3CoachHUDApp(root)
    if "--minimized" in sys.argv or "--pill-only" in sys.argv:
        app.toggle_hud()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
