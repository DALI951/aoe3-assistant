"""
AoE3 Live Telemetry & Russia Coach — Real-Time Backend Server (server.py) v1.1.0
Listens on 0.0.0.0:8765 (LAN + localhost + remote/tunnel support).

Endpoints:
  - POST /api/telemetry          Receive 1 Hz live memory telemetry from pc-app/telemetry.py
  - GET  /api/state              Return current full game & Russia Coach telemetry snapshot
  - GET  /api/stream             Real-time 1 Hz + instant-push stream (supports BOTH WebSocket and SSE!)
  - GET  /api/version            Self-updater manifest for Windows (.exe / Setup.exe) & Android (.apk)
  - GET  /releases/version.json  Mirror of self-updater manifest
  - GET  /releases/<filename>    Serves AoE3AssistantSetup.exe, AoE3Assistant.exe, AoE3Assistant.apk
  - GET  /api/network            LAN IP, modali.powerpme.com status, and optional Cloudflare Tunnel info
  - POST /api/tunnel/start       Starts an optional local cloudflared tunnel if cloudflared.exe is available
  - GET  /                       Responsive dark-mode AoE3 Russia Coach Web Dashboard (static/index.html)
"""

import argparse
import asyncio
import copy
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from aiohttp import WSMsgType, web

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SERVER_DIR, ".."))
STATIC_DIR = os.path.join(SERVER_DIR, "static")
RELEASES_DIR = os.path.join(SERVER_DIR, "releases")
DIST_DIR = os.path.join(ROOT_DIR, "dist")
ROOT_VERSION_JSON = os.path.join(ROOT_DIR, "version.json")
LOCAL_VERSION_JSON = os.path.join(RELEASES_DIR, "version.json")
CLOUDFLARED_CANDIDATES = [
    os.path.join(ROOT_DIR, "..", "cf-duel-arena", "cloudflared.exe"),
    shutil.which("cloudflared") or "",
]

GITHUB_REPO = "DALI951/aoe3-assistant"
DEFAULT_VERSION_MANIFEST = {
    "version": "1.2.0",
    "exe_version": "1.2.0",
    "apk_version": "1.2.0",
    "tag": "v1.2.0",
    "repo": GITHUB_REPO,
    "repo_url": f"https://github.com/{GITHUB_REPO}",
    "version_json_url": f"https://github.com/{GITHUB_REPO}/releases/latest/download/version.json",
    "github_api_latest": f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
    "exe_url": f"https://github.com/{GITHUB_REPO}/releases/latest/download/AoE3Assistant.exe",
    "setup_url": f"https://github.com/{GITHUB_REPO}/releases/latest/download/AoE3AssistantSetup.exe",
    "apk_url": f"https://github.com/{GITHUB_REPO}/releases/latest/download/AoE3Assistant.apk",
    "local_exe_url": "/releases/AoE3Assistant.exe",
    "local_setup_url": "/releases/AoE3AssistantSetup.exe",
    "local_apk_url": "/releases/AoE3Assistant.apk",
    "release_notes": (
        "v1.1.0 - Zero defaults when game not running, accurate Match State (PLAYING / PAUSED / WAITING_FOR_MATCH / GAME_NOT_RUNNING), "
        "XP/s income rate, accurate used/remaining card count, F12 hotkey, draggable HUD overlay, silent mode (all TTS/sound removed), "
        "and clean uncramped Android layout."
    ),
    "published_at": "2026-11-19T22:00:00Z",
}

# Exact 44-card "Eco Instant Spam" deck from sp_St. Petersburg_homecity.xml (11 cards per Age I-IV)
ECO_INSTANT_SPAM_CARDS: List[Dict[str, Any]] = [
    # ==================== AGE I (Discovery Age — 11 Cards) ====================
    {
        "index": 0, "slot": 1, "age": 1, "dbid": 3440, "tech": "HCXPDistributivism",
        "name": "Distributivism", "short_desc": "+1.25 Wood/s Trickle", "category": "eco",
        "priority": 100, "used": False, "recommended": True
    },
    {
        "index": 1, "slot": 2, "age": 1, "dbid": 3387, "tech": "HCXPEconomicTheory",
        "name": "Economic Theory", "short_desc": "+10% All Villager Gather", "category": "eco",
        "priority": 95, "used": False, "recommended": False
    },
    {
        "index": 2, "slot": 3, "age": 1, "dbid": 2286, "tech": "HCFurrierTeam",
        "name": "TEAM Furrier", "short_desc": "+15% Hunt & Berry Gather", "category": "eco",
        "priority": 88, "used": False, "recommended": False
    },
    {
        "index": 3, "slot": 4, "age": 1, "dbid": 2573, "tech": "HCShipWoodCrates1",
        "name": "300 Wood", "short_desc": "300 Wood Crates", "category": "crate",
        "priority": 82, "used": False, "recommended": False
    },
    {
        "index": 4, "slot": 5, "age": 1, "dbid": 2572, "tech": "HCShipFoodCrates1",
        "name": "300 Food", "short_desc": "300 Food Crates", "category": "crate",
        "priority": 78, "used": False, "recommended": False
    },
    {
        "index": 5, "slot": 6, "age": 1, "dbid": 1796, "tech": "HCAdvancedTradingPost",
        "name": "Adv. Trading Post", "short_desc": "-35% TP Cost, +HP/Ranged Atk", "category": "upgrade",
        "priority": 75, "used": False, "recommended": False
    },
    {
        "index": 6, "slot": 7, "age": 1, "dbid": 2090, "tech": "HCSawmills",
        "name": "Sawmills", "short_desc": "+15% Wood Gather Rate", "category": "eco",
        "priority": 72, "used": False, "recommended": False
    },
    {
        "index": 7, "slot": 8, "age": 1, "dbid": 2091, "tech": "HCExoticHardwoods",
        "name": "Exotic Hardwoods", "short_desc": "+20% Wood Gather Rate", "category": "eco",
        "priority": 74, "used": False, "recommended": False
    },
    {
        "index": 8, "slot": 9, "age": 1, "dbid": 3388, "tech": "HCXPLandGrab",
        "name": "Land Grab", "short_desc": "-40% Mill & Estate Wood Cost", "category": "eco",
        "priority": 70, "used": False, "recommended": False
    },
    {
        "index": 9, "slot": 10, "age": 1, "dbid": 2094, "tech": "HCFoodSilos",
        "name": "Food Silos", "short_desc": "+15% Mill Food Gather", "category": "eco",
        "priority": 65, "used": False, "recommended": False
    },
    {
        "index": 10, "slot": 11, "age": 1, "dbid": 2101, "tech": "HCRumDistillery",
        "name": "Rum Distillery", "short_desc": "+20% Estate Coin Gather", "category": "eco",
        "priority": 64, "used": False, "recommended": False
    },

    # ==================== AGE II (Colonial Age — 11 Cards) ====================
    {
        "index": 11, "slot": 1, "age": 2, "dbid": 2212, "tech": "HCShipWoodCrates3",
        "name": "700 Wood", "short_desc": "700 Wood Crates (Blockhouse/TC)", "category": "crate",
        "priority": 99, "used": False, "recommended": False
    },
    {
        "index": 12, "slot": 2, "age": 2, "dbid": 2215, "tech": "HCShipCoinCrates3",
        "name": "700 Coin", "short_desc": "700 Coin Crates (Fast Fortress)", "category": "crate",
        "priority": 97, "used": False, "recommended": False
    },
    {
        "index": 13, "slot": 3, "age": 2, "dbid": 2209, "tech": "HCShipFoodCrates3",
        "name": "700 Food", "short_desc": "700 Food Crates (Age Up / Batches)", "category": "crate",
        "priority": 93, "used": False, "recommended": False
    },
    {
        "index": 14, "slot": 4, "age": 2, "dbid": 2035, "tech": "HCMedicine",
        "name": "Medicine", "short_desc": "-15% Settler Batch Train Time", "category": "eco",
        "priority": 91, "used": False, "recommended": False
    },
    {
        "index": 15, "slot": 5, "age": 2, "dbid": 2098, "tech": "HCSpiceTrade",
        "name": "Spice Trade", "short_desc": "+20% Hunt & Berry Gather", "category": "eco",
        "priority": 89, "used": False, "recommended": False
    },
    {
        "index": 16, "slot": 6, "age": 2, "dbid": 2287, "tech": "HCShipStrelets1",
        "name": "13 Strelets", "short_desc": "13 Strelets Light Infantry", "category": "military",
        "priority": 90, "used": False, "recommended": False
    },
    {
        "index": 17, "slot": 7, "age": 2, "dbid": 2297, "tech": "HCShipCossacks4",
        "name": "5 Cossacks", "short_desc": "5 Cossack Hand Cavalry", "category": "military",
        "priority": 94, "used": False, "recommended": False
    },
    {
        "index": 18, "slot": 8, "age": 2, "dbid": 2037, "tech": "HCFencingSchool",
        "name": "Fencing School", "short_desc": "-40% Infantry Train Time (Spam!)", "category": "spam",
        "priority": 96, "used": False, "recommended": False
    },
    {
        "index": 19, "slot": 9, "age": 2, "dbid": 2443, "tech": "HCDuelingSchoolTeam",
        "name": "TEAM Dueling School", "short_desc": "-25% Team Infantry Train Time", "category": "spam",
        "priority": 92, "used": False, "recommended": False
    },
    {
        "index": 20, "slot": 10, "age": 2, "dbid": 2038, "tech": "HCRidingSchool",
        "name": "Riding School", "short_desc": "-40% Cavalry Train Time", "category": "spam",
        "priority": 86, "used": False, "recommended": False
    },
    {
        "index": 21, "slot": 11, "age": 2, "dbid": 2171, "tech": "HCUniqueCombatRussian",
        "name": "Boyars", "short_desc": "+15% Cossack/Strelet/Oprichnik HP&Atk", "category": "upgrade",
        "priority": 95, "used": False, "recommended": False
    },

    # ==================== AGE III (Fortress Age — 11 Cards) ====================
    {
        "index": 22, "slot": 1, "age": 3, "dbid": 2190, "tech": "HCShipCoveredWagons",
        "name": "Covered Wagon", "short_desc": "+1 Town Center Wagon (3-Settler Boom)", "category": "boom",
        "priority": 99, "used": False, "recommended": False
    },
    {
        "index": 23, "slot": 2, "age": 3, "dbid": 2213, "tech": "HCShipWoodCrates4",
        "name": "1000 Wood", "short_desc": "1000 Wood Crates", "category": "crate",
        "priority": 94, "used": False, "recommended": False
    },
    {
        "index": 24, "slot": 3, "age": 3, "dbid": 2216, "tech": "HCShipCoinCrates4",
        "name": "1000 Coin", "short_desc": "1000 Coin Crates", "category": "crate",
        "priority": 95, "used": False, "recommended": False
    },
    {
        "index": 25, "slot": 4, "age": 3, "dbid": 3463, "tech": "HCXPSuvorovReforms",
        "name": "Suvorov Reforms", "short_desc": "Strelets transform into Musketeers!", "category": "spam",
        "priority": 98, "used": False, "recommended": False
    },
    {
        "index": 26, "slot": 5, "age": 3, "dbid": 2291, "tech": "HCStreletsCombatRussian",
        "name": "Strelet Combat", "short_desc": "+15% Strelet HP & Attack", "category": "upgrade",
        "priority": 90, "used": False, "recommended": False
    },
    {
        "index": 27, "slot": 6, "age": 3, "dbid": 2167, "tech": "HCCavalryCombatRussian",
        "name": "Cavalry Combat", "short_desc": "+15% Cavalry HP & Attack", "category": "upgrade",
        "priority": 91, "used": False, "recommended": False
    },
    {
        "index": 28, "slot": 7, "age": 3, "dbid": 2192, "tech": "HCShipFalconets1",
        "name": "2 Falconets", "short_desc": "2 Field Guns (Anti-Infantry Push)", "category": "artillery",
        "priority": 97, "used": False, "recommended": False
    },
    {
        "index": 29, "slot": 8, "age": 3, "dbid": 2634, "tech": "HCShipMusketeersRussian2",
        "name": "11 Musketeers", "short_desc": "11 Russian Musketeers", "category": "military",
        "priority": 89, "used": False, "recommended": False
    },
    {
        "index": 30, "slot": 9, "age": 3, "dbid": 2299, "tech": "HCShipOprichniks2",
        "name": "7 Oprichniks", "short_desc": "7 Raid & Siege Cavalry", "category": "military",
        "priority": 88, "used": False, "recommended": False
    },
    {
        "index": 31, "slot": 10, "age": 3, "dbid": 2041, "tech": "HCRefrigeration",
        "name": "Refrigeration", "short_desc": "+20% Mill Food Gather Rate", "category": "eco",
        "priority": 87, "used": False, "recommended": False
    },
    {
        "index": 32, "slot": 11, "age": 3, "dbid": 2093, "tech": "HCRoyalMint",
        "name": "Royal Mint", "short_desc": "+25% Estate Coin Gather Rate", "category": "eco",
        "priority": 86, "used": False, "recommended": False
    },

    # ==================== AGE IV (Industrial Age — 11 Cards) ====================
    {
        "index": 33, "slot": 1, "age": 4, "dbid": 625, "tech": "HCUnlockFactory",
        "name": "Factory", "short_desc": "Factory Wagon (7.15 Res/s or Heavy Cannon)", "category": "boom",
        "priority": 100, "used": False, "recommended": False
    },
    {
        "index": 34, "slot": 2, "age": 4, "dbid": 3345, "tech": "HCXPIndustrialRevolution",
        "name": "Robber Barons", "short_desc": "2nd Factory Wagon (Double Factory!)", "category": "boom",
        "priority": 99, "used": False, "recommended": False
    },
    {
        "index": 35, "slot": 3, "age": 4, "dbid": 2589, "tech": "HCSpawnStrelet",
        "name": "Sevastopol / Strelet", "short_desc": "Instant Blockhouse / Strelet Spawn", "category": "spam",
        "priority": 96, "used": False, "recommended": False
    },
    {
        "index": 36, "slot": 4, "age": 4, "dbid": 2076, "tech": "HCAdvancedArtillery",
        "name": "Advanced Artillery", "short_desc": "Artillery Upgrades & Fast Train", "category": "artillery",
        "priority": 92, "used": False, "recommended": False
    },
    {
        "index": 37, "slot": 5, "age": 4, "dbid": 2239, "tech": "HCShipCannons1",
        "name": "3 Heavy Cannons", "short_desc": "3 Heavy Cannons (Endgame Push)", "category": "artillery",
        "priority": 98, "used": False, "recommended": False
    },
    {
        "index": 38, "slot": 6, "age": 4, "dbid": 2590, "tech": "HCUnicorne",
        "name": "Unicorne", "short_desc": "Russian Artillery Range & Area Damage", "category": "artillery",
        "priority": 91, "used": False, "recommended": False
    },
    {
        "index": 39, "slot": 7, "age": 4, "dbid": 2635, "tech": "HCShipMusketeersRussian3",
        "name": "17 Musketeers", "short_desc": "17 Russian Musketeers", "category": "military",
        "priority": 90, "used": False, "recommended": False
    },
    {
        "index": 40, "slot": 8, "age": 4, "dbid": 2296, "tech": "HCShipCossacks3",
        "name": "9 Cossacks", "short_desc": "9 Cossack Cavalry", "category": "military",
        "priority": 89, "used": False, "recommended": False
    },
    {
        "index": 41, "slot": 9, "age": 4, "dbid": 3376, "tech": "HCXPShipOprichniks4",
        "name": "13 Oprichniks", "short_desc": "13 Oprichniks (Base Eraser Box)", "category": "military",
        "priority": 93, "used": False, "recommended": False
    },
    {
        "index": 42, "slot": 10, "age": 4, "dbid": 3521, "tech": "HCShipCoinCrates5",
        "name": "1600 Coin", "short_desc": "1600 Coin Crates", "category": "crate",
        "priority": 94, "used": False, "recommended": False
    },
    {
        "index": 43, "slot": 11, "age": 4, "dbid": 2290, "tech": "HCShipStrelets4",
        "name": "33 Strelets", "short_desc": "33 Strelets Mass Army Shipment", "category": "military",
        "priority": 88, "used": False, "recommended": False
    },
]

CARD_BY_DBID: Dict[int, Dict[str, Any]] = {c["dbid"]: c for c in ECO_INSTANT_SPAM_CARDS}
CARD_BY_TECH: Dict[str, Dict[str, Any]] = {c["tech"].lower(): c for c in ECO_INSTANT_SPAM_CARDS}
CARD_BY_NAME: Dict[str, Dict[str, Any]] = {c["name"].lower(): c for c in ECO_INSTANT_SPAM_CARDS}

AGE_NAMES = {
    0: ("-", "No Match Active"),
    1: ("I", "Discovery Age"),
    2: ("II", "Colonial Age"),
    3: ("III", "Fortress Age"),
    4: ("IV", "Industrial Age"),
    5: ("V", "Imperial Age"),
}


def get_lan_ip() -> str:
    """Detect primary LAN IPv4 address (e.g., 192.168.1.154)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass
    return "192.168.1.154"


def format_game_time(seconds: float) -> str:
    sec = max(0, int(round(seconds)))
    mins, rem = divmod(sec, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{rem:02d}"
    return f"{mins:02d}:{rem:02d}"


def build_zero_state(port: int = 8765, status_text: str = "Game not running — run a game (waiting for match...)") -> Dict[str, Any]:
    """
    Build clean zero state when game is NOT running or no match is active.
    ALL numeric fields are strictly 0!
    """
    lan_ip = get_lan_ip()
    now_ts = time.time()
    return {
        "connected": False,
        "game_running": False,
        "in_match": False,
        "is_playing": False,
        "is_paused": False,
        "match_state": "GAME_NOT_RUNNING",
        "status_text": status_text,
        "process_name": None,
        "pid": None,
        "player_name": "",
        "civ": "",
        "civ_id": 0,
        "homecity": "",
        "homecity_xml": "",
        "food": 0.0,
        "wood": 0.0,
        "coin": 0.0,
        "food_per_sec": 0.0,
        "wood_per_sec": 0.0,
        "coin_per_sec": 0.0,
        "xp_per_sec": 0.0,
        "pop": 0,
        "pop_cap": 0,
        "pop_headroom": 0,
        "villagers": 0,
        "shipments_available": 0,
        "xp_current": 0.0,
        "xp_needed_next": 0,
        "xp_next_threshold": 0.0,
        "xp_prev_threshold": 0.0,
        "xp_progress_pct": 0.0,
        "next_shipment_number": 0,
        "age": 0,
        "age_roman": "-",
        "age_name": "No Match Active",
        "game_time_sec": 0.0,
        "game_time_formatted": "00:00",
        "in_war": False,
        "war_status": "NO MATCH ACTIVE",
        "unit_loss_count": 0,
        "tc_batch_timer_sec": 0.0,
        "tc_batch_cycle_sec": 53.0,
        "tc_idle_warning": False,
        "tc_status": status_text,
        "deck_name": "",
        "deck_card_count": 0,
        "cards_used_count": 0,
        "cards_remaining_count": 0,
        "cards_used_names": [],
        "cards_unused_names": [],
        "cards": [],
        "recommended_card": None,
        "coach_advice": status_text,
        "alerts": [],
        "history": [],
        "server_info": {
            "lan_ip": lan_ip,
            "port": port,
            "lan_url": f"http://{lan_ip}:{port}",
            "local_url": f"http://127.0.0.1:{port}",
            "remote_domain": "https://modali.powerpme.com",
            "remote_vps_ip": "212.227.215.235",
            "tunnel_url": None,
            "version": "1.1.0",
            "post_count": 0,
        },
        "updated_at": now_ts,
        "updated_iso": datetime.now(timezone.utc).isoformat(),
    }


class TelemetryStore:
    """Thread-safe and async-safe store for live AoE3 telemetry and Russia Coach state."""

    def __init__(self, port: int = 8765):
        self.port = port
        self.lan_ip = get_lan_ip()
        self.state: Dict[str, Any] = build_zero_state(port=port)
        self.history: deque = deque(maxlen=60)
        self.ws_clients: Set[web.WebSocketResponse] = set()
        self.sse_queues: Set[asyncio.Queue] = set()
        self.last_post_ts: float = 0.0
        self.post_count: int = 0
        self.tunnel_url: Optional[str] = os.environ.get("AOE3_TUNNEL_URL")
        self.tunnel_proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def reset_to_not_running(self, status_text: str = "Game not running — run a game (waiting for match...)") -> Dict[str, Any]:
        """Reset state cleanly to zero defaults when game exits or telemetry times out."""
        with self._lock:
            s = build_zero_state(port=self.port, status_text=status_text)
            s["server_info"]["tunnel_url"] = self.tunnel_url
            s["server_info"]["post_count"] = self.post_count
            self.state = s
            self.history.clear()
            return copy.deepcopy(self.state)

    def check_timeout(self) -> bool:
        """Return True if active telemetry has timed out (>20s) and was reset to GAME_NOT_RUNNING."""
        with self._lock:
            if self.last_post_ts > 0 and (time.time() - self.last_post_ts > 20.0):
                if self.state.get("game_running") or self.state.get("in_match"):
                    self.state = build_zero_state(
                        port=self.port,
                        status_text="Game not running — run a game (waiting for match...)",
                    )
                    self.state["server_info"]["tunnel_url"] = self.tunnel_url
                    self.state["server_info"]["post_count"] = self.post_count
                    self.history.clear()
                    return True
        return False

    def _normalize_cards(
        self,
        incoming_cards: Optional[List[Any]],
        age: int,
        in_war: bool,
        recommended_hint: Optional[Any] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], int, int, List[str], List[str]]:
        """
        Normalize 44 cards while computing accurate used vs. remaining card counts.
        """
        base_cards = copy.deepcopy(ECO_INSTANT_SPAM_CARDS)
        used_by_index: Dict[int, bool] = {}
        used_by_dbid: Dict[int, bool] = {}
        used_by_tech: Dict[str, bool] = {}
        rec_tech_or_name: Optional[str] = None
        rec_dbid: Optional[int] = None

        if isinstance(recommended_hint, dict):
            rec_dbid = recommended_hint.get("dbid")
            rec_tech_or_name = (
                recommended_hint.get("tech")
                or recommended_hint.get("code")
                or recommended_hint.get("id")
                or recommended_hint.get("name")
            )
        elif isinstance(recommended_hint, str) and recommended_hint.strip():
            rec_tech_or_name = recommended_hint.strip()

        if isinstance(incoming_cards, list) and len(incoming_cards) > 0:
            for idx, item in enumerate(incoming_cards):
                if isinstance(item, dict):
                    is_used = bool(
                        item.get("used", False)
                        or item.get("sent", False)
                        or item.get("is_used", False)
                        or (item.get("count_sent", 0) or 0) > 0
                        or item.get("state") in ("used", "sent", 1, True)
                    )
                    dbid = item.get("dbid") or item.get("tech_id")
                    tech = (
                        item.get("tech")
                        or item.get("tech_name")
                        or item.get("code")
                        or item.get("id")
                        or ""
                    )
                    if dbid is not None:
                        try:
                            used_by_dbid[int(dbid)] = is_used
                        except Exception:
                            pass
                    if tech:
                        used_by_tech[str(tech).lower()] = is_used
                    used_by_index[idx] = is_used

                    if item.get("recommended"):
                        if dbid is not None:
                            try:
                                rec_dbid = int(dbid)
                            except Exception:
                                pass
                        if tech:
                            rec_tech_or_name = str(tech)
                        elif item.get("name"):
                            rec_tech_or_name = str(item.get("name"))

        # Apply used flags to the 44 canonical Eco Instant Spam cards
        cards_used_names = []
        cards_unused_names = []
        used_count = 0
        for c in base_cards:
            idx = c["index"]
            dbid = c["dbid"]
            tech_lower = c["tech"].lower()
            if dbid in used_by_dbid:
                c["used"] = used_by_dbid[dbid]
            elif tech_lower in used_by_tech:
                c["used"] = used_by_tech[tech_lower]
            elif idx in used_by_index:
                c["used"] = used_by_index[idx]
            c["recommended"] = False

            if c["used"]:
                used_count += 1
                cards_used_names.append(c["name"])
            else:
                cards_unused_names.append(c["name"])

        remaining_count = len(base_cards) - used_count

        # Choose recommended card ONLY from UNUSED cards
        chosen_rec: Optional[Dict[str, Any]] = None
        if rec_dbid is not None and rec_dbid in CARD_BY_DBID:
            for c in base_cards:
                if c["dbid"] == rec_dbid and not c["used"]:
                    chosen_rec = c
                    break
        if chosen_rec is None and rec_tech_or_name:
            key = rec_tech_or_name.lower()
            for c in base_cards:
                if (c["tech"].lower() == key or c["name"].lower() == key or key in c["name"].lower()) and not c["used"]:
                    chosen_rec = c
                    break

        if chosen_rec is None:
            eff_age = max(1, min(4, int(age or 1)))
            candidates = [c for c in base_cards if not c["used"] and c["age"] <= eff_age]
            if not candidates:
                candidates = [c for c in base_cards if not c["used"]]
            if candidates:
                if in_war:
                    mil = [c for c in candidates if c["category"] in ("military", "spam", "artillery", "upgrade")]
                    if mil:
                        candidates = mil
                candidates.sort(key=lambda x: (x["age"] == eff_age, x.get("priority", 50)), reverse=True)
                chosen_rec = candidates[0]

        if chosen_rec is not None:
            chosen_rec["recommended"] = True
            rec_summary = {
                "dbid": chosen_rec["dbid"],
                "tech": chosen_rec["tech"],
                "name": chosen_rec["name"],
                "short_desc": chosen_rec["short_desc"],
                "age": chosen_rec["age"],
                "category": chosen_rec["category"],
                "reason": f"Best available Age {AGE_NAMES.get(chosen_rec['age'], ('I', ''))[0]} card: {chosen_rec['name']} ({chosen_rec['short_desc']})",
            }
        else:
            rec_summary = None

        return base_cards, rec_summary, used_count, remaining_count, cards_used_names, cards_unused_names

    def _normalize_alerts(self, incoming_alerts: Any, state: Dict[str, Any]) -> List[Dict[str, str]]:
        if not state.get("in_match"):
            return []

        if isinstance(incoming_alerts, list) and len(incoming_alerts) > 0:
            normalized = []
            for a in incoming_alerts:
                if isinstance(a, dict):
                    normalized.append({
                        "level": str(a.get("level") or a.get("severity") or "info"),
                        "type": str(a.get("type") or a.get("category") or "coach"),
                        "title": str(a.get("title") or a.get("header") or a.get("message") or "Russia Coach Alert"),
                        "message": str(a.get("message") or a.get("detail") or a.get("text") or a.get("title") or ""),
                    })
                elif isinstance(a, str) and a.strip():
                    txt = a.strip()
                    lvl = "urgent" if any(k in txt.upper() for k in ("WAR", "ATTACK", "LOSS", "IDLE", "SHIPMENT")) else "info"
                    normalized.append({
                        "level": lvl,
                        "type": "coach",
                        "title": txt,
                        "message": txt,
                    })
            if normalized:
                return normalized

        alerts: List[Dict[str, str]] = []
        if state.get("in_war"):
            alerts.append({
                "level": "urgent",
                "type": "war",
                "title": "COMBAT ALERT — Unit Loss / Active Battle Detected!",
                "message": "Pop dropped suddenly! Queue Strelets/Cossack batches from Blockhouse & Stable and call Military Shipment!",
            })
        ships = int(state.get("shipments_available", 0) or 0)
        xp_need = int(round(float(state.get("xp_needed_next", 0) or 0)))
        rec = state.get("recommended_card") or {}
        if ships > 0 and rec:
            alerts.append({
                "level": "urgent",
                "type": "shipment",
                "title": f"{ships} Shipment{'s' if ships > 1 else ''} Ready! ({xp_need} XP needed for next)",
                "message": f"Recommended next card: {rec.get('name', '')} ({rec.get('short_desc', '')}).",
            })
        food = float(state.get("food", 0) or 0)
        age = int(state.get("age", 1) or 1)
        if age == 1 and food >= 800:
            alerts.append({
                "level": "warning",
                "type": "macro",
                "title": f"{food:.0f} Food Banked — Age Up to Colonial Age (800F)!",
                "message": "Click Town Center Age II Politician right now, or spend 270 Food on a 3-Settler batch.",
            })
        elif food >= 270 and state.get("tc_idle_warning"):
            alerts.append({
                "level": "warning",
                "type": "tc",
                "title": "Town Center 3-Settler Batch Ready (270 Food)!",
                "message": "Never let Russian TC go idle — queue a 3-Settler batch (270 Food) immediately.",
            })
        pop = int(state.get("pop", 0) or 0)
        pop_cap = int(state.get("pop_cap", 0) or 0)
        if pop_cap > 0 and (pop_cap - pop <= 5) and pop_cap < 200:
            alerts.append({
                "level": "info",
                "type": "population",
                "title": f"Population {pop}/{pop_cap} ({pop_cap - pop} headroom)",
                "message": "Build a House (100 Wood) soon so your 3-Settler batch or 5-Strelet batch doesn't get housed.",
            })
        return alerts

    def update_telemetry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Merge incoming POST /api/telemetry JSON payload into live state."""
        with self._lock:
            now_ts = time.time()
            self.last_post_ts = now_ts
            self.post_count += 1

            # Determine game running and match status
            game_running = bool(payload.get("game_running", True))
            in_match = bool(payload.get("in_match", False))

            # Case 1: Game not running
            if not game_running:
                status_txt = str(payload.get("status_text") or "Game not running — run a game (waiting for match...)")
                s = build_zero_state(port=self.port, status_text=status_txt)
                s["server_info"]["tunnel_url"] = self.tunnel_url
                s["server_info"]["post_count"] = self.post_count
                self.state = s
                self.history.clear()
                return copy.deepcopy(self.state)

            # Case 2: Game running, but no active match yet
            if not in_match:
                status_txt = str(payload.get("status_text") or "AoE3 running — waiting for a match to start...")
                s = build_zero_state(port=self.port, status_text=status_txt)
                s["connected"] = True
                s["game_running"] = True
                s["in_match"] = False
                s["is_playing"] = False
                s["is_paused"] = False
                s["match_state"] = "WAITING_FOR_MATCH"
                s["status_text"] = status_txt
                s["process_name"] = payload.get("process_name", "age3y.exe")
                s["pid"] = payload.get("pid")
                s["coach_advice"] = status_txt
                s["tc_status"] = "Waiting for match..."
                s["server_info"]["tunnel_url"] = self.tunnel_url
                s["server_info"]["post_count"] = self.post_count
                self.state = s
                self.history.clear()
                return copy.deepcopy(self.state)

            # Case 3: In active match!
            s = copy.deepcopy(self.state)
            s["connected"] = True
            s["game_running"] = True
            s["in_match"] = True
            s["process_name"] = payload.get("process_name", "age3y.exe")
            s["pid"] = payload.get("pid")

            # Match playing / paused state
            is_playing = bool(payload.get("is_playing", True))
            is_paused = bool(payload.get("is_paused", False))
            match_state = str(payload.get("match_state") or ("PAUSED" if is_paused else "PLAYING")).upper()
            if match_state not in ("PLAYING", "PAUSED"):
                match_state = "PAUSED" if is_paused else "PLAYING"
            s["is_playing"] = (match_state == "PLAYING")
            s["is_paused"] = (match_state == "PAUSED")
            s["match_state"] = match_state
            s["status_text"] = payload.get("status_text") or f"In Match — {match_state.capitalize()}"

            # Copy player / civ identity
            s["player_name"] = str(payload.get("player_name") or s.get("player_name") or "dali")
            s["civ"] = str(payload.get("civ") or s.get("civ") or "Russians")
            s["civ_id"] = int(payload.get("civ_id", 12) or 12)
            s["homecity"] = str(payload.get("homecity") or s.get("homecity") or "St. Petersburg")
            s["homecity_xml"] = str(payload.get("homecity_xml") or s.get("homecity_xml") or "sp_St. Petersburg_homecity.xml")

            # Resources & income rates (including xp_per_sec!)
            s["food"] = round(float(payload.get("food", 0.0) or 0.0), 2)
            s["wood"] = round(float(payload.get("wood", 0.0) or 0.0), 2)
            s["coin"] = round(float(payload.get("coin", 0.0) or 0.0), 2)

            s["food_per_sec"] = round(float(payload.get("food_per_sec", 0.0) or 0.0), 2)
            s["wood_per_sec"] = round(float(payload.get("wood_per_sec", 0.0) or 0.0), 2)
            s["coin_per_sec"] = round(float(payload.get("coin_per_sec", 0.0) or 0.0), 2)
            s["xp_per_sec"] = round(float(payload.get("xp_per_sec", 0.0) or 0.0), 2)

            s["pop"] = int(payload.get("pop", 0) or 0)
            s["pop_cap"] = int(payload.get("pop_cap", 0) or 0)
            s["pop_headroom"] = max(0, s["pop_cap"] - s["pop"])
            s["villagers"] = int(payload.get("villagers", 0) or 0)

            s["shipments_available"] = int(payload.get("shipments_available", 0) or 0)
            s["xp_next_threshold"] = round(float(payload.get("xp_next_threshold", 0.0) or 0.0), 1)
            s["xp_prev_threshold"] = round(float(payload.get("xp_prev_threshold", 0.0) or 0.0), 1)

            if "xp_needed_next" in payload and payload["xp_needed_next"] is not None:
                xp_needed = float(payload["xp_needed_next"])
            elif "xp_current" in payload and payload["xp_current"] is not None and s["xp_next_threshold"] > 0:
                xp_needed = max(0.0, s["xp_next_threshold"] - float(payload["xp_current"]))
            else:
                xp_needed = float(s.get("xp_needed_next", 0))

            s["xp_needed_next"] = int(round(xp_needed))
            if "xp_current" in payload and payload["xp_current"] is not None:
                s["xp_current"] = round(float(payload["xp_current"]), 1)
            else:
                s["xp_current"] = round(max(0.0, s["xp_next_threshold"] - xp_needed), 1)

            span = max(1.0, s["xp_next_threshold"] - s["xp_prev_threshold"])
            if s["xp_next_threshold"] > 0:
                gained_in_tier = max(0.0, span - xp_needed)
                s["xp_progress_pct"] = round(min(100.0, max(0.0, (gained_in_tier / span) * 100.0)), 1)
            else:
                s["xp_progress_pct"] = 0.0

            # Age
            raw_age = payload.get("age", 1)
            age_int = 1
            if isinstance(raw_age, (int, float)):
                age_int = max(1, min(5, int(raw_age)))
            elif isinstance(raw_age, str):
                u = raw_age.strip().upper()
                if "IV" in u or "4" in u or "INDUSTRIAL" in u:
                    age_int = 4
                elif "III" in u or "3" in u or "FORTRESS" in u:
                    age_int = 3
                elif "II" in u or "2" in u or "COLONIAL" in u:
                    age_int = 2
                elif "V" in u or "5" in u or "IMPERIAL" in u:
                    age_int = 5
                else:
                    age_int = 1
            s["age"] = age_int
            s["age_roman"], s["age_name"] = AGE_NAMES.get(age_int, ("I", "Discovery Age"))

            s["game_time_sec"] = round(float(payload.get("game_time_sec", 0.0) or 0.0), 3)
            s["game_time_formatted"] = format_game_time(s["game_time_sec"])
            s["in_war"] = bool(payload.get("in_war", False))
            s["war_status"] = (
                f"[{s['match_state']}] ACTIVE WAR — Combat / Unit Loss Detected!"
                if s["in_war"]
                else f"[{s['match_state']}] PEACE — Macro & Settler Batch Phase"
            )

            s["deck_name"] = str(payload.get("deck_name") or "Eco Instant Spam")

            rec_hint = (
                payload.get("recommended_card")
                or payload.get("next_recommended_card")
                or payload.get("recommended")
            )
            cards, rec_summary, used_count, remaining_count, used_names, unused_names = self._normalize_cards(
                payload.get("cards"),
                age=s["age"],
                in_war=s["in_war"],
                recommended_hint=rec_hint,
            )
            s["cards"] = cards
            s["deck_card_count"] = len(cards)
            s["cards_used_count"] = used_count
            s["cards_remaining_count"] = remaining_count
            s["cards_used_names"] = used_names
            s["cards_unused_names"] = unused_names
            s["recommended_card"] = rec_summary

            # Coach advice
            state_prefix = f"[{s['match_state']}] "
            if payload.get("coach_advice"):
                raw_advice = str(payload["coach_advice"])
                if not raw_advice.startswith("["):
                    s["coach_advice"] = state_prefix + raw_advice
                else:
                    s["coach_advice"] = raw_advice
            else:
                card_name = rec_summary['name'] if rec_summary else 'a card'
                if s["in_war"]:
                    s["coach_advice"] = (
                        f"{state_prefix}WAR ALERT! Queue Strelets/Cossacks immediately and send {card_name}. "
                        f"(Cards Used: {used_count}/44)"
                    )
                elif s["shipments_available"] > 0:
                    s["coach_advice"] = (
                        f"{state_prefix}{s['shipments_available']} Shipment ready ({s['xp_needed_next']} XP to next)! "
                        f"Send {card_name}. (Cards Used: {used_count}/44, {remaining_count} remaining)"
                    )
                else:
                    s["coach_advice"] = (
                        f"{state_prefix}Keep Russian TC producing 3-Settler batches (270F). "
                        f"{s['xp_needed_next']} XP needed for next shipment. (Cards Used: {used_count}/44)"
                    )

            s["alerts"] = self._normalize_alerts(payload.get("alerts"), s)

            # Sparkline history
            pt = {
                "t": round(s["game_time_sec"], 1),
                "ts": round(now_ts, 1),
                "food": s["food"],
                "wood": s["wood"],
                "coin": s["coin"],
                "food_per_sec": s["food_per_sec"],
                "wood_per_sec": s["wood_per_sec"],
                "coin_per_sec": s["coin_per_sec"],
                "xp_per_sec": s["xp_per_sec"],
                "pop": s["pop"],
                "villagers": s["villagers"],
            }
            self.history.append(pt)
            s["history"] = list(self.history)

            s["server_info"] = {
                "lan_ip": self.lan_ip,
                "port": self.port,
                "lan_url": f"http://{self.lan_ip}:{self.port}",
                "local_url": f"http://127.0.0.1:{self.port}",
                "remote_domain": "https://modali.powerpme.com",
                "remote_vps_ip": "212.227.215.235",
                "tunnel_url": self.tunnel_url,
                "version": "1.1.0",
                "post_count": self.post_count,
            }
            s["updated_at"] = now_ts
            s["updated_iso"] = datetime.now(timezone.utc).isoformat()

            self.state = s
            return copy.deepcopy(self.state)

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self.state["server_info"]["tunnel_url"] = self.tunnel_url
            return copy.deepcopy(self.state)


def resolve_release_file(filename: str) -> Optional[str]:
    """
    Locate a release artifact (<filename>) in server/releases/ or ../dist/ or ../.
    If found in ../dist/ and newer/missing in server/releases/, mirrors it to server/releases/.
    """
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name in (".", ".."):
        return None

    os.makedirs(RELEASES_DIR, exist_ok=True)
    release_target = os.path.join(RELEASES_DIR, safe_name)
    dist_candidate = os.path.join(DIST_DIR, safe_name)
    root_candidate = os.path.join(ROOT_DIR, safe_name)

    if os.path.isfile(dist_candidate):
        try:
            if (
                not os.path.isfile(release_target)
                or os.path.getmtime(dist_candidate) > os.path.getmtime(release_target)
                or os.path.getsize(dist_candidate) != os.path.getsize(release_target)
            ):
                shutil.copy2(dist_candidate, release_target)
        except Exception:
            return dist_candidate

    if os.path.isfile(release_target):
        return release_target
    if os.path.isfile(dist_candidate):
        return dist_candidate
    if safe_name == "version.json" and os.path.isfile(ROOT_VERSION_JSON):
        return ROOT_VERSION_JSON
    if os.path.isfile(root_candidate):
        return root_candidate
    return None


def build_version_manifest(request: Optional[web.Request] = None, store: Optional[TelemetryStore] = None) -> Dict[str, Any]:
    """Build the version manifest for GET /api/version and GET /releases/version.json."""
    manifest = copy.deepcopy(DEFAULT_VERSION_MANIFEST)

    for candidate in (ROOT_VERSION_JSON, LOCAL_VERSION_JSON):
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    manifest.update(loaded)
            except Exception:
                pass

    lan_ip = store.lan_ip if store else get_lan_ip()
    port = store.port if store else 8765
    base_url = f"http://{lan_ip}:{port}"
    if request is not None:
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme or "http")
        host = request.headers.get("X-Forwarded-Host", request.host or f"{lan_ip}:{port}")
        base_url = f"{scheme}://{host}"

    manifest["mirror_base_url"] = base_url
    manifest["mirror_version_json_url"] = f"{base_url}/releases/version.json"
    manifest["mirror_exe_url"] = f"{base_url}/releases/AoE3Assistant.exe"
    manifest["mirror_setup_url"] = f"{base_url}/releases/AoE3AssistantSetup.exe"
    manifest["mirror_apk_url"] = f"{base_url}/releases/AoE3Assistant.apk"

    assets_status = {}
    for fname in ("AoE3AssistantSetup.exe", "AoE3Assistant.exe", "AoE3Assistant.apk", "version.json"):
        path = resolve_release_file(fname)
        if path and os.path.isfile(path):
            assets_status[fname] = {
                "available_locally": True,
                "size_bytes": os.path.getsize(path),
                "local_url": f"/releases/{fname}",
                "mirror_url": f"{base_url}/releases/{fname}",
            }
        else:
            assets_status[fname] = {
                "available_locally": False,
                "size_bytes": 0,
                "local_url": f"/releases/{fname}",
                "mirror_url": f"{base_url}/releases/{fname}",
            }
    manifest["local_assets"] = assets_status
    return manifest


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as ex:
            resp = ex
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS, HEAD"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, Cache-Control, X-Requested-With"
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


async def broadcast_state(store: TelemetryStore, snapshot: Optional[Dict[str, Any]] = None) -> None:
    """Push current telemetry snapshot to all active WebSocket and SSE clients."""
    data = snapshot or store.get_snapshot()
    payload_str = json.dumps(data, ensure_ascii=False)

    # 1. Push to WebSocket clients
    dead_ws = []
    for ws in list(store.ws_clients):
        if ws.closed:
            dead_ws.append(ws)
            continue
        try:
            await ws.send_str(payload_str)
        except Exception:
            dead_ws.append(ws)
    for ws in dead_ws:
        store.ws_clients.discard(ws)

    # 2. Push to SSE queues
    for q in list(store.sse_queues):
        try:
            if q.full():
                try:
                    q.get_nowait()
                except Exception:
                    pass
            q.put_nowait(payload_str)
        except Exception:
            store.sse_queues.discard(q)


async def handle_index(request: web.Request) -> web.Response:
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        return web.Response(text=html, content_type="text/html", charset="utf-8")
    return web.Response(text="AoE3 Russia Coach Server v1.1.0 Running", content_type="text/plain")


async def handle_post_telemetry(request: web.Request) -> web.Response:
    store: TelemetryStore = request.app["store"]
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return web.json_response({"status": "error", "message": "Expected JSON object"}, status=400)
    except Exception as exc:
        return web.json_response({"status": "error", "message": f"Invalid JSON: {exc}"}, status=400)

    snapshot = store.update_telemetry(payload)
    await broadcast_state(store, snapshot)
    return web.json_response({
        "status": "ok",
        "match_state": snapshot.get("match_state", "GAME_NOT_RUNNING"),
        "updated_at": snapshot["updated_at"],
        "post_count": store.post_count,
        "ws_clients": len(store.ws_clients),
        "sse_clients": len(store.sse_queues),
    })


async def handle_get_state(request: web.Request) -> web.Response:
    store: TelemetryStore = request.app["store"]
    if store.check_timeout():
        await broadcast_state(store)
    return web.json_response(store.get_snapshot())


async def handle_stream(request: web.Request) -> web.StreamResponse:
    """
    Unified real-time 1 Hz + event-driven stream endpoint (/api/stream, /api/ws, /api/sse).
    - If request contains 'Upgrade: websocket', upgrades to a WebSocket stream.
    - Otherwise serves a standard Server-Sent Events (text/event-stream) stream.
    """
    store: TelemetryStore = request.app["store"]
    upgrade = request.headers.get("Upgrade", "").lower()

    if upgrade == "websocket":
        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)
        store.ws_clients.add(ws)
        try:
            await ws.send_str(json.dumps(store.get_snapshot(), ensure_ascii=False))
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    if msg.data.strip().lower() == "ping":
                        await ws.send_str(json.dumps({"type": "pong", "ts": time.time()}))
                    else:
                        try:
                            incoming = json.loads(msg.data)
                            if isinstance(incoming, dict) and "food" in incoming:
                                snap = store.update_telemetry(incoming)
                                await broadcast_state(store, snap)
                        except Exception:
                            pass
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            store.ws_clients.discard(ws)
        return ws

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await resp.prepare(request)

    q: asyncio.Queue = asyncio.Queue(maxsize=5)
    store.sse_queues.add(q)
    try:
        initial = json.dumps(store.get_snapshot(), ensure_ascii=False)
        await resp.write(f"data: {initial}\n\n".encode("utf-8"))
        while True:
            payload_str = await q.get()
            await resp.write(f"data: {payload_str}\n\n".encode("utf-8"))
    except (asyncio.CancelledError, ConnectionResetError, Exception):
        pass
    finally:
        store.sse_queues.discard(q)
    return resp


async def handle_get_version(request: web.Request) -> web.Response:
    store: TelemetryStore = request.app["store"]
    manifest = build_version_manifest(request=request, store=store)
    return web.json_response(manifest)


async def handle_release_download(request: web.Request) -> web.StreamResponse:
    filename = request.match_info.get("filename", "")
    if filename == "version.json":
        return await handle_get_version(request)

    path = resolve_release_file(filename)
    if not path or not os.path.isfile(path):
        manifest = build_version_manifest(request=request, store=request.app["store"])
        if filename == "AoE3Assistant.exe":
            raise web.HTTPFound(manifest["exe_url"])
        if filename == "AoE3AssistantSetup.exe":
            raise web.HTTPFound(manifest["setup_url"])
        if filename == "AoE3Assistant.apk":
            raise web.HTTPFound(manifest["apk_url"])
        return web.json_response(
            {"status": "not_found", "filename": filename, "message": f"{filename} not found in releases/ or dist/"},
            status=404,
        )

    ext = os.path.splitext(filename)[1].lower()
    if ext == ".apk":
        ctype = "application/vnd.android.package-archive"
    elif ext == ".exe":
        ctype = "application/vnd.microsoft.portable-executable"
    elif ext == ".json":
        ctype = "application/json"
    else:
        ctype = "application/octet-stream"

    headers = {
        "Content-Disposition": f'attachment; filename="{os.path.basename(path)}"',
        "Access-Control-Allow-Origin": "*",
    }
    return web.FileResponse(path=path, headers=headers, chunk_size=262144)


async def handle_network_info(request: web.Request) -> web.Response:
    store: TelemetryStore = request.app["store"]
    cf_bin = next((p for p in CLOUDFLARED_CANDIDATES if p and os.path.isfile(p)), None)
    return web.json_response({
        "lan_ip": store.lan_ip,
        "port": store.port,
        "lan_url": f"http://{store.lan_ip}:{store.port}",
        "local_url": f"http://127.0.0.1:{store.port}",
        "modali_powerpme": {
            "domain": "modali.powerpme.com",
            "dns_a_record": "212.227.215.235",
            "server": "Apache/2.4.58 (Ubuntu)",
            "https_url": "https://modali.powerpme.com",
            "relay_script": os.path.join(SERVER_DIR, "modali_relay.php"),
        },
        "cloudflared_available": bool(cf_bin),
        "cloudflared_path": cf_bin,
        "tunnel_url": store.tunnel_url,
        "ws_clients": len(store.ws_clients),
        "sse_clients": len(store.sse_queues),
        "post_count": store.post_count,
    })


async def handle_start_tunnel(request: web.Request) -> web.Response:
    store: TelemetryStore = request.app["store"]
    if store.tunnel_url:
        return web.json_response({"status": "already_running", "tunnel_url": store.tunnel_url})

    cf_bin = next((p for p in CLOUDFLARED_CANDIDATES if p and os.path.isfile(p)), None)
    if not cf_bin:
        return web.json_response(
            {"status": "unavailable", "message": "cloudflared.exe not found on this machine"},
            status=404,
        )

    def _spawn_tunnel():
        try:
            proc = subprocess.Popen(
                [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{store.port}", "--no-autoupdate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            store.tunnel_proc = proc
            pattern = re.compile(r"(https://[a-zA-Z0-9\-]+\.trycloudflare\.com)")
            for line in iter(proc.stdout.readline, ""):
                m = pattern.search(line)
                if m:
                    store.tunnel_url = m.group(1)
                    break
        except Exception:
            pass

    t = threading.Thread(target=_spawn_tunnel, daemon=True)
    t.start()
    for _ in range(25):
        await asyncio.sleep(0.25)
        if store.tunnel_url:
            break

    return web.json_response({
        "status": "ok" if store.tunnel_url else "starting",
        "tunnel_url": store.tunnel_url,
    })


async def heartbeat_broadcaster(app: web.Application) -> None:
    """1 Hz background loop broadcasting live state and enforcing 5s telemetry timeout."""
    store: TelemetryStore = app["store"]
    try:
        while True:
            await asyncio.sleep(1.0)
            timed_out = store.check_timeout()
            if timed_out or store.ws_clients or store.sse_queues:
                await broadcast_state(store)
    except asyncio.CancelledError:
        pass


async def on_startup(app: web.Application) -> None:
    app["heartbeat_task"] = asyncio.create_task(heartbeat_broadcaster(app))


async def on_cleanup(app: web.Application) -> None:
    task = app.get("heartbeat_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    store: TelemetryStore = app["store"]
    if store.tunnel_proc and store.tunnel_proc.poll() is None:
        try:
            store.tunnel_proc.terminate()
        except Exception:
            pass


def create_app(port: int = 8765) -> web.Application:
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(RELEASES_DIR, exist_ok=True)
    store = TelemetryStore(port=port)

    app = web.Application(middlewares=[cors_middleware], client_max_size=16 * 1024 * 1024)
    app["store"] = store
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    app.router.add_post("/api/telemetry", handle_post_telemetry)
    app.router.add_get("/api/telemetry", handle_get_state)
    app.router.add_get("/api/state", handle_get_state)
    app.router.add_get("/api/stream", handle_stream)
    app.router.add_get("/api/ws", handle_stream)
    app.router.add_get("/api/sse", handle_stream)
    app.router.add_get("/api/version", handle_get_version)
    app.router.add_get("/api/network", handle_network_info)
    app.router.add_post("/api/tunnel/start", handle_start_tunnel)
    app.router.add_get("/releases/version.json", handle_get_version)
    app.router.add_get("/releases/{filename}", handle_release_download)
    app.router.add_static("/static/", path=STATIC_DIR, name="static")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 Live Telemetry & Russia Coach Server v1.1.0")
    parser.add_argument("--host", default=os.environ.get("AOE3_SERVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AOE3_SERVER_PORT", "8765")))
    args = parser.parse_args()

    lan_ip = get_lan_ip()
    print("=" * 72, flush=True)
    print(f" AoE3 Live Telemetry & Russia Coach Server v1.1.0", flush=True)
    print(f" Listening on:   http://{args.host}:{args.port}", flush=True)
    print(f" Local URL:      http://127.0.0.1:{args.port}", flush=True)
    print(f" LAN URL:        http://{lan_ip}:{args.port}", flush=True)
    print(f" Remote Domain:  https://modali.powerpme.com (212.227.215.235)", flush=True)
    print("=" * 72, flush=True)

    app = create_app(port=args.port)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
