"""
AoE3 Assistant Windows Setup Installer (installer/setup_installer.py)
Version 1.1.0

Compiled via PyInstaller into dist/AoE3AssistantSetup.exe.
Features:
- Multi-page Windows Setup Wizard:
    Page 1: Welcome
    Page 2: Destination Folder & Options (Run at Startup, Desktop Shortcut, Start Menu, Launch Service)
    Page 3: Installing (Progress Bar & File Extraction)
    Page 4: Finished
- Silent / In-Place Upgrade mode (--silent, /S, /VERYSILENT, --upgrade, --relaunch, --startup)
- Creates Windows Desktop & Start Menu shortcuts (.lnk) via WScript.Shell
- Registers per-user Windows Startup in HKCU Run key (AoE3Assistant -> "<exe>" --background)
- Registers Windows Uninstall entry in HKCU Add/Remove Programs + generates uninstall.bat
- Supports --self-test for automated verification
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, Optional
import winreg

APP_NAME = "AoE3 Live Rates Overlay & Assistant"
APP_VERSION = "1.3.0"
PUBLISHER = "DALI951 (AoE3 Assistant)"
EXE_FILENAME = "AoE3Assistant.exe"
REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_RUN_VALUE = "AoE3Assistant"
DEFAULT_INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Programs",
    "AoE3Assistant",
)


def get_payload_dir() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, "payload")
        if os.path.isdir(candidate):
            return candidate
        return meipass
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(repo_root, "dist")


def get_embedded_exe_path() -> str:
    p_dir = get_payload_dir()
    candidate = os.path.join(p_dir, EXE_FILENAME)
    if os.path.exists(candidate):
        return candidate
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(repo_root, "dist", EXE_FILENAME)


def get_embedded_version_json() -> Optional[str]:
    p_dir = get_payload_dir()
    candidate = os.path.join(p_dir, "version.json")
    if os.path.exists(candidate):
        return candidate
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    root_v = os.path.join(repo_root, "version.json")
    return root_v if os.path.exists(root_v) else None


def set_windows_startup(exe_path: str, enable: bool = True) -> bool:
    try:
        if enable:
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


def create_windows_shortcut(target_exe: str, shortcut_path: str, description: str = APP_NAME) -> bool:
    try:
        os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
        work_dir = os.path.dirname(target_exe)
        ps_script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{shortcut_path}'); "
            f"$s.TargetPath = '{target_exe}'; "
            f"$s.WorkingDirectory = '{work_dir}'; "
            f"$s.Description = '{description}'; "
            f"$s.IconLocation = '{target_exe},0'; "
            "$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        return os.path.exists(shortcut_path)
    except Exception:
        return False


def register_uninstaller(install_dir: str, target_exe: str) -> str:
    uninstall_bat = os.path.join(install_dir, "uninstall.bat")
    desktop_lnk = os.path.join(os.path.expanduser("~"), "Desktop", "AoE3 Live Rates Overlay.lnk")
    start_menu_dir = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "AoE3 Assistant",
    )

    try:
        with open(uninstall_bat, "w", encoding="utf-8") as f:
            f.write("@echo off\r\n")
            f.write("taskkill /F /IM AoE3Assistant.exe >nul 2>&1\r\n")
            f.write(f'del /F /Q "{desktop_lnk}" >nul 2>&1\r\n')
            f.write(f'rmdir /S /Q "{start_menu_dir}" >nul 2>&1\r\n')
            f.write(
                'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AoE3Assistant" /f >nul 2>&1\r\n'
            )
            f.write(
                'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "AoE3Assistant" /f >nul 2>&1\r\n'
            )
            f.write(f'del /F /Q "{target_exe}" >nul 2>&1\r\n')
    except Exception:
        pass

    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AoE3Assistant"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, target_exe)
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstall_bat}"')
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception:
        pass

    return uninstall_bat


def perform_installation(
    install_dir: str = DEFAULT_INSTALL_DIR,
    create_desktop: bool = True,
    create_start_menu: bool = True,
    enable_startup: bool = True,
    register_arp: bool = True,
    launch_mode: str = "background",  # "none", "foreground", "background"
    log_cb=None,
    progress_cb=None,
) -> Dict[str, Any]:
    def _log(msg: str):
        if callable(log_cb):
            log_cb(msg)

    def _prog(pct: int):
        if callable(progress_cb):
            progress_cb(pct)

    src_exe = get_embedded_exe_path()
    if not os.path.exists(src_exe):
        return {"status": "error", "message": f"Embedded payload not found at {src_exe}"}

    _prog(10)
    _log("Stopping any running AoE3Assistant.exe instances...")
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", EXE_FILENAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        time.sleep(0.3)
    except Exception:
        pass

    _prog(25)
    _log(f"Creating installation directory: {install_dir}")
    os.makedirs(install_dir, exist_ok=True)

    _prog(45)
    dest_exe = os.path.join(install_dir, EXE_FILENAME)
    _log(f"Extracting {EXE_FILENAME} ({os.path.getsize(src_exe) // 1024} KB)...")
    shutil.copy2(src_exe, dest_exe)

    src_ver = get_embedded_version_json()
    if src_ver and os.path.exists(src_ver):
        shutil.copy2(src_ver, os.path.join(install_dir, "version.json"))

    _prog(65)
    shortcuts_created = []
    if create_desktop:
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop_dir):
            d_lnk = os.path.join(desktop_dir, "AoE3 Live Rates Overlay.lnk")
            _log("Creating Desktop shortcut...")
            if create_windows_shortcut(dest_exe, d_lnk):
                shortcuts_created.append(d_lnk)

    if create_start_menu:
        sm_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            "AoE3 Assistant",
        )
        sm_lnk = os.path.join(sm_dir, "AoE3 Live Rates Overlay.lnk")
        _log("Creating Start Menu shortcut...")
        if create_windows_shortcut(dest_exe, sm_lnk):
            shortcuts_created.append(sm_lnk)

    _prog(80)
    if enable_startup:
        _log("Registering in Windows Startup (HKCU Run key)...")
        set_windows_startup(dest_exe, True)

    uninstall_bat = ""
    if register_arp:
        _log("Registering uninstaller in Windows Registry...")
        uninstall_bat = register_uninstaller(install_dir, dest_exe)

    _prog(95)
    if launch_mode == "background":
        _log("Starting AoE3 Assistant background service...")
        try:
            subprocess.Popen([dest_exe, "--background"], cwd=install_dir, close_fds=True)
        except Exception:
            pass
    elif launch_mode == "foreground":
        _log("Launching AoE3 Assistant Overlay...")
        try:
            subprocess.Popen([dest_exe], cwd=install_dir, close_fds=True)
        except Exception:
            pass

    _prog(100)
    _log("Installation complete!")
    return {
        "status": "installed",
        "version": APP_VERSION,
        "install_dir": install_dir,
        "installed_exe": dest_exe,
        "installed_exe_size": os.path.getsize(dest_exe) if os.path.exists(dest_exe) else 0,
        "shortcuts": shortcuts_created,
        "startup_enabled": enable_startup,
        "uninstaller": uninstall_bat,
    }


class StandardMultiPageWizardGUI:
    """Standard 4-Page Windows Setup Wizard GUI."""

    BG_DARK = "#0d1117"
    BG_PANEL = "#161b22"
    GOLD = "#f0c05a"
    GOLD_BRIGHT = "#ffd97d"
    TEXT_MAIN = "#f0f6fc"
    TEXT_MUTED = "#8b949e"
    GREEN = "#3fb950"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION} Setup")
        self.root.geometry("620x450")
        self.root.configure(bg=self.BG_DARK)
        self.root.resizable(False, False)

        # Variables
        self.dir_var = tk.StringVar(value=DEFAULT_INSTALL_DIR)
        self.startup_var = tk.BooleanVar(value=True)
        self.desktop_var = tk.BooleanVar(value=True)
        self.startmenu_var = tk.BooleanVar(value=True)
        self.launch_service_var = tk.BooleanVar(value=True)

        self.current_page = 0
        self.pages = []

        self._build_header()
        self._build_container()
        self._build_footer()

        self._show_page(0)

    def _build_header(self) -> None:
        self.header = tk.Frame(self.root, bg=self.BG_PANEL, padx=20, pady=12)
        self.header.pack(fill=tk.X)

        self.hdr_title = tk.Label(
            self.header,
            text=f"⚔ {APP_NAME} Setup Wizard",
            bg=self.BG_PANEL,
            fg=self.GOLD_BRIGHT,
            font=("Segoe UI", 13, "bold"),
        )
        self.hdr_title.pack(anchor="w")

        self.hdr_sub = tk.Label(
            self.header,
            text=f"Version {APP_VERSION} • Real-time rates floating overlay (F12 toggle) & auto-updater",
            bg=self.BG_PANEL,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 8),
        )
        self.hdr_sub.pack(anchor="w", pady=(2, 0))

    def _build_container(self) -> None:
        self.container = tk.Frame(self.root, bg=self.BG_DARK, padx=24, pady=16)
        self.container.pack(fill=tk.BOTH, expand=True)

        # Page 0: Welcome
        p0 = tk.Frame(self.container, bg=self.BG_DARK)
        tk.Label(
            p0,
            text="Welcome to the AoE3 Assistant Setup Wizard",
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(10, 10))
        tk.Label(
            p0,
            text=(
                "This will install the ultra-lightweight AoE3 Live Rates Overlay & Assistant on your PC.\n\n"
                "Key Features in v1.1.0:\n"
                "• Real-time Food/s, Wood/s, Coin/s, XP/s floating HUD (F12 or Ctrl+Shift+A)\n"
                "• Freely draggable anywhere on screen over your game\n"
                "• 100% Silent Mode (Zero audio or TTS interruptions)\n"
                "• Automatic background service & Windows startup integration\n"
                "• Accurate used card tracking (Cards Used: X / 44)\n\n"
                "Click 'Next' to continue."
            ),
            bg=self.BG_DARK,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 9),
            justify=tk.LEFT,
        ).pack(anchor="w")
        self.pages.append(p0)

        # Page 1: Destination & Options
        p1 = tk.Frame(self.container, bg=self.BG_DARK)
        tk.Label(
            p1,
            text="Select Installation Folder & Options",
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        dir_row = tk.Frame(p1, bg=self.BG_DARK)
        dir_row.pack(fill=tk.X, pady=(0, 12))
        tk.Entry(
            dir_row,
            textvariable=self.dir_var,
            bg=self.BG_PANEL,
            fg=self.TEXT_MAIN,
            insertbackground=self.TEXT_MAIN,
            relief=tk.FLAT,
            font=("Consolas", 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        tk.Button(
            dir_row,
            text="Browse...",
            bg=self.BG_PANEL,
            fg=self.GOLD,
            relief=tk.FLAT,
            padx=10,
            command=self._browse_dir,
        ).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(
            p1,
            text="Setup Preferences:",
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(6, 4))

        for var, lbl in [
            (self.startup_var, "Run at Windows Startup (Always-on background service)"),
            (self.desktop_var, "Create Desktop Shortcut (AoE3 Live Rates Overlay)"),
            (self.startmenu_var, "Create Start Menu Shortcut"),
            (self.launch_service_var, "Start AoE3 Assistant background service immediately after setup"),
        ]:
            tk.Checkbutton(
                p1,
                text=lbl,
                variable=var,
                bg=self.BG_DARK,
                fg=self.TEXT_MAIN,
                selectcolor=self.BG_PANEL,
                activebackground=self.BG_DARK,
                font=("Segoe UI", 9),
            ).pack(anchor="w", pady=2)
        self.pages.append(p1)

        # Page 2: Progress / Extracting
        p2 = tk.Frame(self.container, bg=self.BG_DARK)
        tk.Label(
            p2,
            text="Installing AoE3 Assistant...",
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        self.prog_bar = ttk.Progressbar(p2, mode="determinate")
        self.prog_bar.pack(fill=tk.X, pady=(0, 10))
        self.log_box = tk.Text(
            p2, height=9, bg=self.BG_PANEL, fg=self.TEXT_MUTED, font=("Consolas", 8), relief=tk.FLAT, padx=6, pady=6
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.pages.append(p2)

        # Page 3: Finished
        p3 = tk.Frame(self.container, bg=self.BG_DARK)
        tk.Label(
            p3,
            text="Installation Completed Successfully!",
            bg=self.BG_DARK,
            fg=self.GREEN,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", pady=(15, 10))
        self.finish_desc = tk.Label(
            p3,
            text=(
                f"{APP_NAME} v{APP_VERSION} is installed and ready.\n\n"
                "• Press F12 or Ctrl+Shift+A anytime to toggle the floating rates HUD\n"
                "• Click and drag anywhere on the overlay to position it on screen\n"
                "• The service runs quietly in the background waiting for Age of Empires III\n\n"
                "Click 'Finish' to exit Setup."
            ),
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 9),
            justify=tk.LEFT,
        )
        self.finish_desc.pack(anchor="w")
        self.pages.append(p3)

    def _build_footer(self) -> None:
        self.footer = tk.Frame(self.root, bg=self.BG_PANEL, padx=20, pady=12)
        self.footer.pack(fill=tk.X, side=tk.BOTTOM)

        self.btn_next = tk.Button(
            self.footer,
            text="Next >",
            bg=self.GOLD,
            fg=self.BG_DARK,
            activebackground=self.GOLD_BRIGHT,
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=4,
            relief=tk.FLAT,
            command=self._on_next,
        )
        self.btn_next.pack(side=tk.RIGHT)

        self.btn_back = tk.Button(
            self.footer,
            text="< Back",
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 9),
            padx=12,
            pady=4,
            relief=tk.FLAT,
            command=self._on_back,
        )
        self.btn_back.pack(side=tk.RIGHT, padx=8)

        self.btn_cancel = tk.Button(
            self.footer,
            text="Cancel",
            bg=self.BG_DARK,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 9),
            padx=10,
            pady=4,
            relief=tk.FLAT,
            command=self.root.destroy,
        )
        self.btn_cancel.pack(side=tk.LEFT)

    def _show_page(self, index: int) -> None:
        self.current_page = index
        for idx, p in enumerate(self.pages):
            if idx == index:
                p.pack(fill=tk.BOTH, expand=True)
            else:
                p.pack_forget()

        if index == 0:
            self.btn_back.config(state=tk.DISABLED)
            self.btn_next.config(text="Next >", state=tk.NORMAL)
        elif index == 1:
            self.btn_back.config(state=tk.NORMAL)
            self.btn_next.config(text="Install Now", state=tk.NORMAL)
        elif index == 2:
            self.btn_back.config(state=tk.DISABLED)
            self.btn_next.config(text="Installing...", state=tk.DISABLED)
            self.btn_cancel.config(state=tk.DISABLED)
        elif index == 3:
            self.btn_back.config(state=tk.DISABLED)
            self.btn_next.config(text="Finish", state=tk.NORMAL, bg=self.GREEN, command=self.root.destroy)
            self.btn_cancel.config(state=tk.DISABLED)

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.dir_var.get())
        if chosen:
            self.dir_var.set(chosen)

    def _on_back(self) -> None:
        if self.current_page > 0:
            self._show_page(self.current_page - 1)

    def _on_next(self) -> None:
        if self.current_page == 0:
            self._show_page(1)
        elif self.current_page == 1:
            self._show_page(2)
            self._start_installation()

    def _start_installation(self) -> None:
        target_dir = self.dir_var.get().strip() or DEFAULT_INSTALL_DIR
        l_mode = "background" if self.launch_service_var.get() else "none"

        def _worker():
            res = perform_installation(
                install_dir=target_dir,
                create_desktop=bool(self.desktop_var.get()),
                create_start_menu=bool(self.startmenu_var.get()),
                enable_startup=bool(self.startup_var.get()),
                register_arp=True,
                launch_mode=l_mode,
                log_cb=lambda m: self.root.after(0, lambda: self._append_log(m)),
                progress_cb=lambda p: self.root.after(0, lambda: self.prog_bar.config(value=p)),
            )
            self.root.after(400, lambda: self._on_finish_install(res))

        threading.Thread(target=_worker, daemon=True).start()

    def _append_log(self, msg: str) -> None:
        self.log_box.insert(tk.END, f"> {msg}\n")
        self.log_box.see(tk.END)

    def _on_finish_install(self, res: Dict[str, Any]) -> None:
        if res.get("status") == "installed":
            self._show_page(3)
        else:
            messagebox.showerror("Installation Error", res.get("message", "Setup failed."))
            self._show_page(1)


def run_self_test() -> int:
    src_exe = get_embedded_exe_path()
    exists = os.path.exists(src_exe)
    size = os.path.getsize(src_exe) if exists else 0
    report = {
        "installer": "AoE3AssistantSetup",
        "version": APP_VERSION,
        "default_install_dir": DEFAULT_INSTALL_DIR,
        "embedded_payload_exe": src_exe,
        "payload_exists": exists,
        "payload_size_bytes": size,
        "supports_silent_upgrade": True,
        "supports_windows_startup": True,
        "status": "OK" if exists and size > 100000 else "MISSING_PAYLOAD",
    }
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "OK" else 1


def main() -> int:
    argv = [a for a in sys.argv[1:]]
    silent_raw = any(a.upper() in ("/S", "/SILENT", "/VERYSILENT", "--SILENT", "--UPGRADE") for a in argv)
    clean_argv = [a for a in argv if a.upper() not in ("/S", "/SILENT", "/VERYSILENT")]

    parser = argparse.ArgumentParser(description=f"{APP_NAME} Setup Installer")
    parser.add_argument("--silent", action="store_true", help="Run silent unattended installation")
    parser.add_argument("--upgrade", action="store_true", help="Perform silent in-place upgrade")
    parser.add_argument("--relaunch", action="store_true", help="Launch background service after setup")
    parser.add_argument("--startup", action="store_true", default=True, help="Register in Windows Startup")
    parser.add_argument("--no-shortcuts", action="store_true", help="Skip creating shortcuts")
    parser.add_argument("--install-dir", type=str, default=DEFAULT_INSTALL_DIR, help="Target installation folder")
    parser.add_argument("--self-test", action="store_true", help="Verify installer and exit")
    args, _ = parser.parse_known_args(clean_argv)

    if args.self_test:
        return run_self_test()

    if silent_raw or args.silent or args.upgrade:
        l_mode = "background" if args.relaunch else "none"
        res = perform_installation(
            install_dir=args.install_dir,
            create_desktop=not args.no_shortcuts,
            create_start_menu=not args.no_shortcuts,
            enable_startup=args.startup,
            register_arp=True,
            launch_mode=l_mode,
        )
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") == "installed" else 1

    if getattr(sys, "frozen", False):
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

    root = tk.Tk()
    StandardMultiPageWizardGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
