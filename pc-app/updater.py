"""
AoE3 Assistant PC Auto-Updater (updater.py)
Checks GitHub Releases and the AoE3 Assistant Server (/api/version) for updates,
downloads the latest AoE3AssistantSetup.exe or AoE3Assistant.exe, and performs
in-place or silent installer upgrades.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

CURRENT_VERSION = "1.2.0"
GITHUB_REPO = "DALI951/aoe3-assistant"
REPO_URL = f"https://github.com/{GITHUB_REPO}"
VERSION_JSON_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/version.json"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
DEFAULT_EXE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/AoE3Assistant.exe"
DEFAULT_SETUP_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/AoE3AssistantSetup.exe"
DEFAULT_LOCAL_SERVER = "http://127.0.0.1:8765"


def parse_version(v_str: str) -> Tuple[int, ...]:
    """Convert a version string like 'v1.0.0' or '1.2.3' into an integer tuple."""
    if not v_str:
        return (0, 0, 0)
    cleaned = str(v_str).strip().lstrip("vV").split("-")[0]
    parts = []
    for p in cleaned.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer_version(remote_v: str, local_v: str = CURRENT_VERSION) -> bool:
    """Return True if remote_v is strictly newer than local_v."""
    try:
        return parse_version(remote_v) > parse_version(local_v)
    except Exception:
        return False


class AutoUpdater:
    """Manages version checks and self-updating for AoE3 Assistant PC."""

    def __init__(self, current_version: str = CURRENT_VERSION, server_url: str = DEFAULT_LOCAL_SERVER):
        self.current_version = current_version
        self.server_url = (server_url or DEFAULT_LOCAL_SERVER).rstrip("/")
        self.last_check_result: Optional[Dict] = None

    def _fetch_json(self, url: str, timeout: float = 4.5) -> Optional[Dict]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"AoE3Assistant-PC/{self.current_version}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)

    def _normalize_manifest(self, data: Dict, source_url: str) -> Dict:
        # Handle GitHub API /releases/latest format vs version.json format
        if "tag_name" in data and "assets" in data:
            tag = data.get("tag_name", "v1.0.0")
            remote_ver = tag.lstrip("vV") or "1.0.0"
            exe_url = DEFAULT_EXE_URL
            setup_url = DEFAULT_SETUP_URL
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                dl = asset.get("browser_download_url", "")
                if name == "AoE3Assistant.exe" and dl:
                    exe_url = dl
                elif name == "AoE3AssistantSetup.exe" and dl:
                    setup_url = dl
            notes = data.get("body") or f"GitHub Release {tag}"
        else:
            remote_ver = (
                data.get("exe_version")
                or data.get("version")
                or data.get("tag", "1.0.0").lstrip("vV")
            )
            exe_url = data.get("exe_url") or DEFAULT_EXE_URL
            setup_url = data.get("setup_url") or DEFAULT_SETUP_URL
            # Resolve relative URLs if returned from local server
            if exe_url.startswith("/") and source_url.startswith("http"):
                base = source_url.split("/api/")[0].split("/releases/")[0]
                exe_url = base + exe_url
            if setup_url.startswith("/") and source_url.startswith("http"):
                base = source_url.split("/api/")[0].split("/releases/")[0]
                setup_url = base + setup_url
            notes = data.get("release_notes") or f"AoE3 Assistant v{remote_ver}"

        newer = is_newer_version(remote_ver, self.current_version)
        return {
            "checked": True,
            "current_version": self.current_version,
            "remote_version": str(remote_ver),
            "update_available": newer,
            "exe_url": exe_url,
            "setup_url": setup_url,
            "version_json_url": VERSION_JSON_URL,
            "github_api_latest": GITHUB_API_LATEST,
            "release_notes": notes,
            "source": source_url,
            "error": None,
        }

    def check_for_updates(
        self,
        extra_server_urls: Optional[List[str]] = None,
        timeout: float = 4.5,
    ) -> Dict:
        """
        Check GitHub Releases and local/remote server /api/version endpoints.
        Always returns a structured dict with update status and download URLs.
        """
        candidates: List[str] = []
        if extra_server_urls:
            for s in extra_server_urls:
                if s and s.strip():
                    base = s.strip().rstrip("/")
                    candidates.append(f"{base}/api/version")
        if self.server_url:
            candidates.append(f"{self.server_url}/api/version")
            candidates.append(f"{self.server_url}/releases/version.json")

        candidates.extend([VERSION_JSON_URL, GITHUB_API_LATEST])

        seen = set()
        ordered_urls = []
        for u in candidates:
            if u not in seen:
                seen.add(u)
                ordered_urls.append(u)

        errors = []
        best_result: Optional[Dict] = None

        for url in ordered_urls:
            try:
                data = self._fetch_json(url, timeout=timeout)
                if isinstance(data, dict):
                    res = self._normalize_manifest(data, url)
                    if res["update_available"]:
                        self.last_check_result = res
                        return res
                    if best_result is None:
                        best_result = res
            except Exception as exc:
                errors.append(f"{url}: {exc}")

        if best_result is not None:
            self.last_check_result = best_result
            return best_result

        # Fallback to local version.json if offline or release not yet uploaded
        local_candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "version.json"),
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "version.json"),
        ]
        for lf in local_candidates:
            if os.path.exists(lf):
                try:
                    with open(lf, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    res = self._normalize_manifest(data, f"file://{os.path.abspath(lf)}")
                    self.last_check_result = res
                    return res
                except Exception:
                    pass

        fallback = {
            "checked": False,
            "current_version": self.current_version,
            "remote_version": self.current_version,
            "update_available": False,
            "exe_url": DEFAULT_EXE_URL,
            "setup_url": DEFAULT_SETUP_URL,
            "version_json_url": VERSION_JSON_URL,
            "github_api_latest": GITHUB_API_LATEST,
            "release_notes": "Up to date (offline fallback).",
            "source": "fallback",
            "error": "; ".join(errors[:2]) if errors else None,
        }
        self.last_check_result = fallback
        return fallback

    def check_async(
        self,
        callback: Callable[[Dict], None],
        extra_server_urls: Optional[List[str]] = None,
    ) -> threading.Thread:
        """Run check_for_updates in a background daemon thread and invoke callback(result)."""

        def _worker():
            res = self.check_for_updates(extra_server_urls=extra_server_urls)
            try:
                callback(res)
            except Exception:
                pass

        t = threading.Thread(target=_worker, daemon=True, name="AoE3UpdaterCheck")
        t.start()
        return t

    def download_and_apply_update(
        self,
        update_info: Optional[Dict] = None,
        prefer_setup: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        force_download: bool = False,
    ) -> Dict:
        """
        Download the update binary (Setup installer or standalone EXE) and launch it.
        If prefer_setup is True, downloads AoE3AssistantSetup.exe and launches it with
        --silent --relaunch. Otherwise downloads AoE3Assistant.exe and swaps via a helper bat.
        """
        info = update_info or self.last_check_result or self.check_for_updates()
        if not info.get("update_available") and not force_download:
            return {
                "status": "up_to_date",
                "message": f"Already running latest version v{self.current_version}.",
            }

        target_url = info.get("setup_url") if prefer_setup else info.get("exe_url")
        if not target_url:
            target_url = DEFAULT_SETUP_URL if prefer_setup else DEFAULT_EXE_URL

        update_dir = os.path.join(tempfile.gettempdir(), "AoE3Assistant_Update")
        os.makedirs(update_dir, exist_ok=True)
        filename = "AoE3AssistantSetup.exe" if prefer_setup else "AoE3Assistant_Update.exe"
        dest_path = os.path.join(update_dir, filename)

        try:
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": f"AoE3Assistant-PC/{self.current_version}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", "0") or "0")
                downloaded = 0
                with open(dest_path, "wb") as out_f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
        except Exception as exc:
            # Try local server fallback URL if GitHub download failed
            fallback_url = (
                f"{self.server_url}/releases/{'AoE3AssistantSetup.exe' if prefer_setup else 'AoE3Assistant.exe'}"
            )
            try:
                req = urllib.request.Request(
                    fallback_url,
                    headers={"User-Agent": f"AoE3Assistant-PC/{self.current_version}"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    with open(dest_path, "wb") as out_f:
                        out_f.write(resp.read())
            except Exception:
                return {
                    "status": "error",
                    "message": f"Download failed from {target_url}: {exc}",
                }

        if not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1024:
            return {
                "status": "error",
                "message": "Downloaded update file is invalid or empty.",
            }

        try:
            if prefer_setup:
                subprocess.Popen(
                    [dest_path, "--silent", "--relaunch"],
                    close_fds=True,
                )
            else:
                current_exe = os.path.abspath(sys.executable)
                bat_path = os.path.join(update_dir, "apply_update.bat")
                with open(bat_path, "w", encoding="utf-8") as bf:
                    bf.write("@echo off\r\n")
                    bf.write("timeout /t 2 /nobreak >nul\r\n")
                    bf.write(f'copy /Y "{dest_path}" "{current_exe}" >nul\r\n')
                    bf.write(f'start "" "{current_exe}"\r\n')
                subprocess.Popen(
                    ["cmd.exe", "/c", bat_path],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                    close_fds=True,
                )
            return {
                "status": "launched",
                "path": dest_path,
                "message": f"Update downloaded to {dest_path} and launched.",
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Failed to launch update binary: {exc}",
            }


def check_for_updates(server_url: str = DEFAULT_LOCAL_SERVER) -> Dict:
    """Module-level convenience wrapper."""
    return AutoUpdater(server_url=server_url).check_for_updates()


if __name__ == "__main__":
    updater = AutoUpdater()
    res = updater.check_for_updates()
    print(json.dumps(res, indent=2))
