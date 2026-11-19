"""
AoE3 Assistant Windows Setup Installer (installer/setup_installer.py)
Compiled via PyInstaller into dist/AoE3AssistantSetup.exe.
Features:
- Bundles standalone AoE3Assistant.exe + version.json inside payload/
- Interactive dark-gold GUI Setup Wizard (Tkinter)
- Silent / In-Place Upgrade mode (--silent, /S, /VERYSILENT, --upgrade, --relaunch, --install-dir)
- Creates Windows Desktop & Start Menu shortcuts (.lnk) via WScript.Shell
- Registers per-user Windows Uninstall entry in HKCU + generates uninstall.bat
- Supports --self-test for automated installer verification
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

APP_NAME = "AoE3 Russia Coach Assistant"
APP_VERSION = "1.0.0"
PUBLISHER = "DALI951 (AoE3 Assistant)"
EXE_FILENAME = "AoE3Assistant.exe"
DEFAULT_INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Programs",
    "AoE3Assistant",
)


def get_payload_dir() -> str:
    """Locate bundled payload directory inside PyInstaller _MEIPASS or repo dist/."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, "payload")
        if os.path.isdir(candidate):
            return candidate
        return meipass
    # Development fallback: look in ../dist
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


def create_windows_shortcut(target_exe: str, shortcut_path: str, description: str = APP_NAME) -> bool:
    """Create a standard Windows .lnk shortcut using WScript.Shell via PowerShell."""
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
    """Create uninstall.bat and register AoE3Assistant in HKCU Add/Remove Programs."""
    uninstall_bat = os.path.join(install_dir, "uninstall.bat")
    desktop_lnk = os.path.join(os.path.expanduser("~"), "Desktop", "AoE3 Russia Coach HUD.lnk")
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
    register_arp: bool = True,
    relaunch: bool = False,
    log_cb=None,
) -> Dict[str, Any]:
    """Execute full installation or in-place upgrade of AoE3Assistant.exe."""

    def _log(msg: str):
        if callable(log_cb):
            log_cb(msg)

    src_exe = get_embedded_exe_path()
    if not os.path.exists(src_exe):
        return {
            "status": "error",
            "message": f"Embedded payload not found at {src_exe}",
        }

    _log("Stopping any running AoE3Assistant.exe instances for clean upgrade...")
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", EXE_FILENAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        time.sleep(0.35)
    except Exception:
        pass

    _log(f"Creating installation directory: {install_dir}")
    os.makedirs(install_dir, exist_ok=True)

    dest_exe = os.path.join(install_dir, EXE_FILENAME)
    _log(f"Extracting {EXE_FILENAME} ({os.path.getsize(src_exe) // 1024} KB)...")
    shutil.copy2(src_exe, dest_exe)

    src_ver = get_embedded_version_json()
    if src_ver and os.path.exists(src_ver):
        shutil.copy2(src_ver, os.path.join(install_dir, "version.json"))

    shortcuts_created = []
    if create_desktop:
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop_dir):
            d_lnk = os.path.join(desktop_dir, "AoE3 Russia Coach HUD.lnk")
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
        sm_lnk = os.path.join(sm_dir, "AoE3 Russia Coach HUD.lnk")
        _log("Creating Start Menu shortcut...")
        if create_windows_shortcut(dest_exe, sm_lnk):
            shortcuts_created.append(sm_lnk)

    uninstall_bat = ""
    if register_arp:
        _log("Registering uninstaller in Windows Registry (HKCU)...")
        uninstall_bat = register_uninstaller(install_dir, dest_exe)

    if relaunch and os.path.exists(dest_exe):
        _log("Launching AoE3Assistant.exe...")
        try:
            subprocess.Popen([dest_exe], cwd=install_dir, close_fds=True)
        except Exception:
            pass

    _log("Installation complete!")
    return {
        "status": "installed",
        "version": APP_VERSION,
        "install_dir": install_dir,
        "installed_exe": dest_exe,
        "installed_exe_size": os.path.getsize(dest_exe) if os.path.exists(dest_exe) else 0,
        "shortcuts": shortcuts_created,
        "uninstaller": uninstall_bat,
    }


class SetupWizardGUI:
    """Interactive Tkinter Setup Wizard for AoE3AssistantSetup.exe."""

    BG_DARK = "#0e131a"
    BG_PANEL = "#161f2c"
    GOLD = "#f0c05a"
    GOLD_BRIGHT = "#ffd97d"
    TEXT_MAIN = "#f3f6fa"
    TEXT_MUTED = "#98a6b8"
    GREEN = "#35d07f"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION} Setup")
        self.root.geometry("600x430")
        self.root.configure(bg=self.BG_DARK)
        self.root.resizable(False, False)

        header = tk.Frame(self.root, bg=self.BG_PANEL, padx=18, pady=14)
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text=f"⚔ {APP_NAME} Setup Wizard",
            bg=self.BG_PANEL,
            fg=self.GOLD_BRIGHT,
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")

        tk.Label(
            header,
            text=f"Version {APP_VERSION} • Live AoE3 Telemetry, Russia Coach HUD (F8 Toggle) & Auto-Updater",
            bg=self.BG_PANEL,
            fg=self.TEXT_MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self.root, bg=self.BG_DARK, padx=20, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Installation Folder (supports clean install & in-place upgrade):",
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")

        dir_row = tk.Frame(body, bg=self.BG_DARK)
        dir_row.pack(fill=tk.X, pady=(4, 12))

        self.dir_var = tk.StringVar(value=DEFAULT_INSTALL_DIR)
        self.dir_entry = tk.Entry(
            dir_row,
            textvariable=self.dir_var,
            bg=self.BG_PANEL,
            fg=self.TEXT_MAIN,
            insertbackground=self.TEXT_MAIN,
            relief=tk.FLAT,
            font=("Consolas", 9),
        )
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        tk.Button(
            dir_row,
            text="Browse...",
            bg=self.BG_PANEL,
            fg=self.GOLD,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=10,
            command=self._browse_dir,
        ).pack(side=tk.LEFT, padx=(6, 0))

        self.desktop_var = tk.BooleanVar(value=True)
        self.startmenu_var = tk.BooleanVar(value=True)
        self.launch_var = tk.BooleanVar(value=True)

        for var, label in [
            (self.desktop_var, "Create Desktop shortcut (AoE3 Russia Coach HUD)"),
            (self.startmenu_var, "Create Start Menu shortcut"),
            (self.launch_var, "Launch AoE3 Russia Coach HUD immediately after setup"),
        ]:
            tk.Checkbutton(
                body,
                text=label,
                variable=var,
                bg=self.BG_DARK,
                fg=self.TEXT_MAIN,
                selectcolor=self.BG_PANEL,
                activebackground=self.BG_DARK,
                font=("Segoe UI", 9),
            ).pack(anchor="w", pady=2)

        self.log_box = tk.Text(
            body,
            height=6,
            bg=self.BG_PANEL,
            fg=self.TEXT_MUTED,
            relief=tk.FLAT,
            font=("Consolas", 8),
            padx=8,
            pady=6,
        )
        self.log_box.pack(fill=tk.BOTH, expand=True, pady=(10, 4))
        self._append_log(f"Ready to install {APP_NAME} v{APP_VERSION}.")

        footer = tk.Frame(self.root, bg=self.BG_PANEL, padx=18, pady=10)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        self.install_btn = tk.Button(
            footer,
            text="Install / Upgrade Now",
            bg=self.GOLD,
            fg=self.BG_DARK,
            activebackground=self.GOLD_BRIGHT,
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=5,
            cursor="hand2",
            command=self._start_install,
        )
        self.install_btn.pack(side=tk.RIGHT)

        tk.Button(
            footer,
            text="Cancel",
            bg=self.BG_DARK,
            fg=self.TEXT_MAIN,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=12,
            pady=5,
            command=self.root.destroy,
        ).pack(side=tk.RIGHT, padx=8)

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.dir_var.get())
        if chosen:
            self.dir_var.set(chosen)

    def _append_log(self, msg: str) -> None:
        self.log_box.insert(tk.END, f"> {msg}\n")
        self.log_box.see(tk.END)

    def _start_install(self) -> None:
        self.install_btn.config(text="Installing...", state=tk.DISABLED)
        target_dir = self.dir_var.get().strip() or DEFAULT_INSTALL_DIR

        def _worker():
            res = perform_installation(
                install_dir=target_dir,
                create_desktop=bool(self.desktop_var.get()),
                create_start_menu=bool(self.startmenu_var.get()),
                register_arp=True,
                relaunch=bool(self.launch_var.get()),
                log_cb=lambda m: self.root.after(0, lambda: self._append_log(m)),
            )
            self.root.after(0, lambda: self._on_finished(res))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_finished(self, res: Dict[str, Any]) -> None:
        if res.get("status") == "installed":
            self.install_btn.config(text="Finish", bg=self.GREEN, state=tk.NORMAL, command=self.root.destroy)
            messagebox.showinfo(
                "Installation Complete",
                f"{APP_NAME} v{APP_VERSION} has been installed to:\n{res.get('install_dir')}\n\n"
                "Press F8 or Ctrl+Shift+A anytime in-game to toggle the Coach HUD!",
            )
        else:
            self.install_btn.config(text="Retry Install", state=tk.NORMAL)
            messagebox.showerror("Setup Error", res.get("message", "Installation failed."))


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
        "status": "OK" if exists and size > 100000 else "MISSING_PAYLOAD",
    }
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "OK" else 1


def main() -> int:
    # Support standard Windows installer flags (/S, /VERYSILENT) as well as argparse flags
    argv = [a for a in sys.argv[1:]]
    silent_raw = any(a.upper() in ("/S", "/SILENT", "/VERYSILENT", "--SILENT", "--UPGRADE") for a in argv)
    clean_argv = [a for a in argv if a.upper() not in ("/S", "/SILENT", "/VERYSILENT")]

    parser = argparse.ArgumentParser(description=f"{APP_NAME} Setup Installer")
    parser.add_argument("--silent", action="store_true", help="Run silent unattended installation")
    parser.add_argument("--upgrade", action="store_true", help="Perform silent in-place upgrade")
    parser.add_argument("--relaunch", action="store_true", help="Launch AoE3Assistant.exe after setup")
    parser.add_argument("--no-shortcuts", action="store_true", help="Skip creating Desktop/Start Menu shortcuts")
    parser.add_argument("--install-dir", type=str, default=DEFAULT_INSTALL_DIR, help="Target installation folder")
    parser.add_argument("--self-test", action="store_true", help="Verify embedded payload and exit")
    args, _ = parser.parse_known_args(clean_argv)

    if args.self_test:
        return run_self_test()

    if silent_raw or args.silent or args.upgrade:
        res = perform_installation(
            install_dir=args.install_dir,
            create_desktop=not args.no_shortcuts,
            create_start_menu=not args.no_shortcuts,
            register_arp=True,
            relaunch=args.relaunch,
        )
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") == "installed" else 1

    if getattr(sys, "frozen", False):
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

    root = tk.Tk()
    SetupWizardGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
