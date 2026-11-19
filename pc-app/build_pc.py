"""
AoE3 Assistant PC Build & Packaging Script (pc-app/build_pc.py)
1. Compiles standalone portable executable: dist/AoE3Assistant.exe via PyInstaller
2. Compiles Windows Setup Installer executable: dist/AoE3AssistantSetup.exe via PyInstaller
   (bundling dist/AoE3Assistant.exe and version.json inside payload/)
3. Mirrors built binaries into server/releases/ for local /releases/ self-update hosting
4. Runs automated verification (--self-test) on both executables.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PC_APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(PC_APP_DIR, ".."))
INSTALLER_DIR = os.path.join(REPO_ROOT, "installer")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
BUILD_WORK_DIR = os.path.join( tempfile.gettempdir(), "aoe3_pyinstaller_build")
SERVER_RELEASES_DIR = os.path.join(REPO_ROOT, "server", "releases")


def run_pyinstaller(cmd_args):
    cmd = [sys.executable, "-m", "PyInstaller"] + cmd_args
    print(f"[build_pc] Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=REPO_ROOT)
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {res.returncode}")


def build_portable_exe() -> str:
    os.makedirs(DIST_DIR, exist_ok=True)
    app_ui_path = os.path.join(PC_APP_DIR, "app_ui.py")
    version_json = os.path.join(REPO_ROOT, "version.json")

    work_dir = os.path.join(BUILD_WORK_DIR, "app")
    spec_dir = os.path.join(BUILD_WORK_DIR, "spec_app")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(spec_dir, exist_ok=True)

    args = [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "AoE3Assistant",
        "--distpath",
        DIST_DIR,
        "--workpath",
        work_dir,
        "--specpath",
        spec_dir,
        "--paths",
        PC_APP_DIR,
        "--hidden-import",
        "updater",
        "--hidden-import",
        "tkinter",
        "--hidden-import",
        "tkinter.ttk",
        "--hidden-import",
        "tkinter.messagebox",
    ]

    if os.path.exists(version_json):
        args.extend(["--add-data", f"{version_json};."])

    # Include telemetry.py and coach.py if present in pc-app/
    for mod_name in ("telemetry", "coach"):
        mod_file = os.path.join(PC_APP_DIR, f"{mod_name}.py")
        if os.path.exists(mod_file):
            print(f"[build_pc] Bundling {mod_name}.py into AoE3Assistant.exe")
            args.extend(["--hidden-import", mod_name])
            args.extend(["--add-data", f"{mod_file};."])

    args.append(app_ui_path)
    run_pyinstaller(args)

    exe_path = os.path.join(DIST_DIR, "AoE3Assistant.exe")
    if not os.path.exists(exe_path):
        raise FileNotFoundError(f"Expected output {exe_path} not found!")
    print(f"[build_pc] Built portable EXE: {exe_path} ({os.path.getsize(exe_path):,} bytes)")
    return exe_path


def build_setup_installer(portable_exe_path: str) -> str:
    setup_script = os.path.join(INSTALLER_DIR, "setup_installer.py")
    version_json = os.path.join(REPO_ROOT, "version.json")

    work_dir = os.path.join(BUILD_WORK_DIR, "setup")
    spec_dir = os.path.join(BUILD_WORK_DIR, "spec_setup")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(spec_dir, exist_ok=True)

    args = [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "AoE3AssistantSetup",
        "--distpath",
        DIST_DIR,
        "--workpath",
        work_dir,
        "--specpath",
        spec_dir,
        "--add-data",
        f"{portable_exe_path};payload",
        "--hidden-import",
        "tkinter",
        "--hidden-import",
        "tkinter.filedialog",
        "--hidden-import",
        "tkinter.messagebox",
    ]

    if os.path.exists(version_json):
        args.extend(["--add-data", f"{version_json};payload"])

    args.append(setup_script)
    run_pyinstaller(args)

    setup_exe_path = os.path.join(DIST_DIR, "AoE3AssistantSetup.exe")
    if not os.path.exists(setup_exe_path):
        raise FileNotFoundError(f"Expected output {setup_exe_path} not found!")
    print(f"[build_pc] Built Setup Installer EXE: {setup_exe_path} ({os.path.getsize(setup_exe_path):,} bytes)")
    return setup_exe_path


def mirror_to_server_releases(portable_exe: str, setup_exe: str) -> None:
    try:
        os.makedirs(SERVER_RELEASES_DIR, exist_ok=True)
        shutil.copy2(portable_exe, os.path.join(SERVER_RELEASES_DIR, "AoE3Assistant.exe"))
        shutil.copy2(setup_exe, os.path.join(SERVER_RELEASES_DIR, "AoE3AssistantSetup.exe"))
        print(f"[build_pc] Mirrored EXEs to {SERVER_RELEASES_DIR}")
    except Exception as exc:
        print(f"[build_pc] Note: could not mirror to server/releases: {exc}")


def verify_executables(portable_exe: str, setup_exe: str) -> None:
    print("[build_pc] Verifying AoE3Assistant.exe --self-test ...")
    r1 = subprocess.run([portable_exe, "--self-test"], capture_output=True, text=True, timeout=25)
    print(r1.stdout)
    if r1.returncode != 0:
        raise RuntimeError(f"AoE3Assistant.exe --self-test failed: {r1.stderr}")

    print("[build_pc] Verifying AoE3AssistantSetup.exe --self-test ...")
    r2 = subprocess.run([setup_exe, "--self-test"], capture_output=True, text=True, timeout=25)
    print(r2.stdout)
    if r2.returncode != 0:
        raise RuntimeError(f"AoE3AssistantSetup.exe --self-test failed: {r2.stderr}")


def main() -> int:
    t0 = time.time()
    portable_exe = build_portable_exe()
    setup_exe = build_setup_installer(portable_exe)
    mirror_to_server_releases(portable_exe, setup_exe)
    verify_executables(portable_exe, setup_exe)
    print(f"[build_pc] SUCCESS in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
