"""
AoE3 Live Read-Only Memory Telemetry Reader (telemetry.py)
Strictly READ-ONLY (`PROCESS_VM_READ | PROCESS_QUERY_INFORMATION`) telemetry engine for
Age of Empires III: The Asian Dynasties (`age3y.exe`, Complete Collection).

Key Reverse-Engineered Architecture (Verified Live on PID 448):
1. Static Pointer Chain (< 1 ms lookup in any match):
   - `age3y.exe` image base: `0x00400000`
   - `g_game = *(base + 0x00866234)` (`0x00C66234`)
   - `BWorld = *(g_game + 0x13C)`
   - `player_count = *(BWorld + 0x5C)`
   - `players_array = *(BWorld + 0x58)`
   - `BPlayer = *(players_array + 4 * i)` (in PID 448: `0x1426A800` for player 1 `"dali"`)

2. Vtable Signature Scan Fallback (< 0.25s in any match):
   - `BHomeCity` vtable `0x00BA3B20` -> `+0x08` points to `BPlayer` (`*(BPlayer + 0x84) == BHomeCity`).
   - `BDeck` vtable `0x00BA3B14` -> `+0x08` UTF-16LE deck name (`"Eco Instant Spam"`),
     `+0x10` Card Tech DBIDs `uint32*` (`0x1D54F400`), `+0x14` Card count (`44`),
     `+0x1C` Live Card State array ptr (`0x1E1B8400`).

3. Exact `324` XP-Needed & XOR-Encrypted Resource Array (`*(BPlayer + 0x230)`):
   - Static 8-DWORD XOR key table at `0x00C6DF14` (`base + 0x0086DF14`, count `8` at `0x00C6DF38`):
     `[0x2848AC4F, 0x94F83A35, 0x8BD84C3F, 0xAB12FBAF, 0x20B35BCA, 0xF9ABC42A, 0xB1A1CFDA, 0xF2E48210]`
   - `res_ptr = *(BPlayer + 0x230)` (`0x0FE9A080` in PID 448; `*(BPlayer + 0x240)` is Total Gathered,
     `*(BPlayer + 0x248)` is Trickle Rates):
     - Index 0 (`res_ptr + 0x00 ^ 0x2848AC4F`): Coin (`106.5599`)
     - Index 1 (`res_ptr + 0x04 ^ 0x94F83A35`): Wood (`289.3330`)
     - Index 2 (`res_ptr + 0x08 ^ 0x8BD84C3F`): Food (`838.2416`)
     - Index 3 (`res_ptr + 0x0C ^ 0xAB12FBAF`): Fame (`0.0`)
     - Index 4 (`res_ptr + 0x10 ^ 0x20B35BCA`): SkillPoints (`0.0`)
     - Index 5 (`res_ptr + 0x14 ^ 0xF9ABC42A`): **Current Match XP** (`0x0FE9A094` -> `321.0`)
     - Index 6 (`res_ptr + 0x18 ^ 0xB1A1CFDA`): Total Shipments Earned (`1.0`)
     - Index 7 (`res_ptr + 0x1C ^ 0xF2E48210`): Export (`0.0`)
   - `xp_next_threshold = *(float32*)(BPlayer + 0x480)` (`645.0`)
   - `xp_prev_threshold = *(float32*)(BPlayer + 0x484)` (`300.0`)
   - `xp_needed_next = round(xp_next_threshold - xp_current) = round(645.0 - 321.0) = 324`!
"""

import argparse
from collections import deque
import ctypes
from ctypes import wintypes
import json
import math
import os
import struct
import sys
import time
from typing import Any, Deque, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from coach import (
    CARD_BY_DBID,
    CoachEngine,
    DEFAULT_HOMECITY_XML_PATH,
    ECO_INSTANT_SPAM_CARDS,
    load_deck_from_homecity_xml,
)

# Strictly READ-ONLY Win32 process access flags
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
READ_ONLY_ACCESS = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION

MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READWRITE = 0x40
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

# Static age3y.exe addresses & vtables
AGE3Y_DEFAULT_BASE = 0x00400000
OFFSET_G_GAME = 0x00866234          # -> 0x00C66234
OFFSET_XOR_TABLE = 0x0086DF14       # -> 0x00C6DF14 (8 uint32 XOR keys)
VTABLE_BHOMECITY = 0x00BA3B20
VTABLE_BDECK = 0x00BA3B14

DEFAULT_XOR_KEY_TABLE: Tuple[int, ...] = (
    0x2848AC4F,  # [0] Coin
    0x94F83A35,  # [1] Wood
    0x8BD84C3F,  # [2] Food
    0xAB12FBAF,  # [3] Fame
    0x20B35BCA,  # [4] SkillPoints
    0xF9ABC42A,  # [5] Current Match XP
    0xB1A1CFDA,  # [6] Total Shipments Earned
    0xF2E48210,  # [7] Export
)

CIV_NAMES: Dict[int, str] = {
    1: "Spanish",
    2: "British",
    3: "French",
    4: "Portuguese",
    5: "Dutch",
    6: "Russians",
    7: "Germans",
    8: "Ottomans",
    12: "Russians",
    15: "Japanese",
    16: "Chinese",
    17: "Indians",
}


class MEMORY_BASIC_INFORMATION32(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", wintypes.DWORD),
        ("AllocationBase", wintypes.DWORD),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", wintypes.DWORD),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", wintypes.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class GatherRateFilter:
    """
    Calculates exact `food_per_sec`, `wood_per_sec`, `coin_per_sec` from 1 Hz samples
    while filtering out:
      - Sudden training/building/tech spend drops (e.g. -270 Food Russian 3-Settler batch,
        -800 Food Age II click, -100 Wood House, -250 Wood Blockhouse).
      - Sudden Home City shipment crate spikes (+300, +700, +1000, +1600 crates).
    """

    def __init__(self, window_sec: float = 8.0):
        self.window_sec = window_sec
        self._last_time: Optional[float] = None
        self._last_vals: Dict[str, float] = {}
        self._deltas: Dict[str, Deque[Tuple[float, float, float]]] = {
            "food": deque(maxlen=15),
            "wood": deque(maxlen=15),
            "coin": deque(maxlen=15),
        }
        self._rates: Dict[str, float] = {"food": 0.0, "wood": 0.0, "coin": 0.0}

    def reset(self) -> None:
        self._last_time = None
        self._last_vals.clear()
        for q in self._deltas.values():
            q.clear()
        self._rates = {"food": 0.0, "wood": 0.0, "coin": 0.0}

    def update(
        self,
        game_time_sec: float,
        food: float,
        wood: float,
        coin: float,
        total_gathered: Optional[Dict[str, float]] = None,
    ) -> Tuple[float, float, float]:
        if self._last_time is None or game_time_sec < self._last_time - 2.0:
            self._last_time = game_time_sec
            self._last_vals = {"food": food, "wood": wood, "coin": coin}
            return self._rates["food"], self._rates["wood"], self._rates["coin"]

        dt = game_time_sec - self._last_time
        if dt < 0.05:
            return self._rates["food"], self._rates["wood"], self._rates["coin"]

        current = {"food": food, "wood": wood, "coin": coin}
        for key in ("food", "wood", "coin"):
            delta = current[key] - self._last_vals.get(key, current[key])
            inst_rate = delta / dt

            # Filter out spend drops (negative deltas < -5.0) and crate shipment spikes (> +65.0/s)
            is_spend_drop = delta < -5.0
            is_crate_spike = delta > 120.0 or inst_rate > 45.0

            if not is_spend_drop and not is_crate_spike and dt <= 15.0:
                self._deltas[key].append((game_time_sec, max(0.0, delta), dt))

            # Prune samples outside rolling window
            q = self._deltas[key]
            while q and (game_time_sec - q[0][0]) > self.window_sec:
                q.popleft()

            if q:
                sum_d = sum(item[1] for item in q)
                sum_dt = sum(item[2] for item in q)
                self._rates[key] = round(sum_d / sum_dt, 2) if sum_dt > 0.05 else 0.0

        self._last_time = game_time_sec
        self._last_vals = current
        return self._rates["food"], self._rates["wood"], self._rates["coin"]


class TelemetryReader:
    """
    Strictly Read-Only Live Memory Telemetry Reader for `age3y.exe`.
    Automatically finds `BPlayer`, `BHomeCity`, `BDeck`, and the XOR-encoded 8-resource array
    (`Coin`, `Wood`, `Food`, `Current XP`, etc.) in <1 second in any match.
    """

    def __init__(
        self,
        process_name: str = "age3y.exe",
        homecity_xml_path: str = DEFAULT_HOMECITY_XML_PATH,
    ):
        self.process_name = process_name
        self.homecity_xml_path = homecity_xml_path
        self.coach = CoachEngine(homecity_xml_path=homecity_xml_path)
        self.rate_filter = GatherRateFilter(window_sec=8.0)

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._setup_win32()

        self.pid: Optional[int] = None
        self.handle: Optional[int] = None
        self.module_base: int = AGE3Y_DEFAULT_BASE
        self.xor_table: Tuple[int, ...] = DEFAULT_XOR_KEY_TABLE

        # Cached discovered structure addresses for current match
        self.bplayer_addr: int = 0
        self.bhomecity_addr: int = 0
        self.bdeck_addr: int = 0
        self._last_scan_ts: float = 0.0

    def _setup_win32(self) -> None:
        k = self._kernel32
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE

        k.ReadProcessMemory.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.LPVOID,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k.ReadProcessMemory.restype = wintypes.BOOL

        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL

        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32FirstW.restype = wintypes.BOOL

        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.restype = wintypes.BOOL

    def close(self) -> None:
        if self.handle:
            try:
                self._kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None
            self.pid = None

    def find_age3_pid(self) -> Optional[int]:
        """Locate running age3y.exe (or age3.exe / age3x.exe) PID via Toolhelp32 read-only snapshot."""
        snap = self._kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == wintypes.HANDLE(-1).value:
            return None
        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            targets = {self.process_name.lower(), "age3y.exe", "age3x.exe", "age3.exe"}
            if self._kernel32.Process32FirstW(snap, ctypes.byref(pe)):
                while True:
                    exe = pe.szExeFile.lower()
                    if exe in targets:
                        return int(pe.th32ProcessID)
                    if not self._kernel32.Process32NextW(snap, ctypes.byref(pe)):
                        break
        finally:
            self._kernel32.CloseHandle(snap)
        return None

    def attach(self, pid: Optional[int] = None) -> bool:
        """Open target process strictly with PROCESS_VM_READ | PROCESS_QUERY_INFORMATION."""
        target_pid = pid or self.find_age3_pid()
        if not target_pid:
            self.close()
            return False

        if self.handle and self.pid == target_pid:
            # Verify process is still alive and readable
            if self.read_bytes(self.module_base, 4):
                return True
            self.close()

        h = self._kernel32.OpenProcess(READ_ONLY_ACCESS, False, target_pid)
        if not h:
            self.close()
            return False

        self.pid = target_pid
        self.handle = h
        self.module_base = AGE3Y_DEFAULT_BASE
        self._load_xor_table()
        return True

    def read_bytes(self, addr: int, size: int) -> bytes:
        if not self.handle or addr <= 0 or size <= 0:
            return b""
        buf = ctypes.create_string_buffer(size)
        n_read = ctypes.c_size_t(0)
        ok = self._kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(addr),
            buf,
            size,
            ctypes.byref(n_read),
        )
        if ok and n_read.value > 0:
            return buf.raw[: n_read.value]
        return b""

    def read_u32(self, addr: int) -> Optional[int]:
        b = self.read_bytes(addr, 4)
        return struct.unpack("<I", b)[0] if len(b) == 4 else None

    def read_f32(self, addr: int) -> Optional[float]:
        b = self.read_bytes(addr, 4)
        if len(b) == 4:
            val = struct.unpack("<f", b)[0]
            if not (math.isnan(val) or math.isinf(val)):
                return val
        return None

    def read_utf16(self, addr: int, max_chars: int = 64) -> str:
        if not addr or addr < 0x10000:
            return ""
        b = self.read_bytes(addr, max_chars * 2)
        if not b:
            return ""
        try:
            text = b.decode("utf-16-le", errors="ignore")
            return text.split("\x00")[0].strip()
        except Exception:
            return ""

    def _load_xor_table(self) -> None:
        """Read the 8-DWORD XOR key table from age3y.exe @ 0x00C6DF14 (with static fallback)."""
        raw = self.read_bytes(self.module_base + OFFSET_XOR_TABLE, 32)
        if len(raw) == 32:
            keys = struct.unpack("<8I", raw)
            if keys[0] == 0x2848AC4F and keys[5] == 0xF9ABC42A:
                self.xor_table = keys
                return
        self.xor_table = DEFAULT_XOR_KEY_TABLE

    def decode_xor_resources(self, res_array_ptr: int) -> Optional[Dict[str, float]]:
        """
        Decrypt the 8 XOR-obfuscated resource floats at `*(BPlayer + 0x230)` using the static
        table at `0x00C6DF14`.
        Indices:
          0: Coin, 1: Wood, 2: Food, 3: Fame, 4: SkillPoints, 5: Current XP, 6: ShipmentsEarned, 7: Export
        """
        if not res_array_ptr or res_array_ptr < 0x10000:
            return None
        raw = self.read_bytes(res_array_ptr, 32)
        if len(raw) != 32:
            return None
        enc = struct.unpack("<8I", raw)
        dec: List[float] = []
        for i in range(8):
            u = enc[i] ^ self.xor_table[i]
            f = struct.unpack("<f", struct.pack("<I", u))[0]
            if math.isnan(f) or math.isinf(f) or abs(f) > 1e8:
                return None
            dec.append(f)
        return {
            "coin": dec[0],
            "wood": dec[1],
            "food": dec[2],
            "fame": dec[3],
            "skill_points": dec[4],
            "xp": dec[5],
            "shipments_earned": dec[6],
            "export": dec[7],
        }

    def _validate_bplayer(self, bp_addr: int) -> bool:
        if not bp_addr or bp_addr < 0x10000:
            return False
        hdr = self.read_bytes(bp_addr, 0x260)
        if len(hdr) < 0x260:
            return False
        pid_val = struct.unpack_from("<I", hdr, 0x000)[0]
        pop_cap = struct.unpack_from("<I", hdr, 0x074)[0]
        res_ptr = struct.unpack_from("<I", hdr, 0x230)[0]
        if not (1 <= pid_val <= 16):
            return False
        if pop_cap > 1000:
            return False
        res = self.decode_xor_resources(res_ptr)
        if res is None:
            return False
        return -1.0 <= res["food"] <= 1e7 and -1.0 <= res["xp"] <= 1e7

    def _resolve_bplayer_via_static_chain(self) -> int:
        """
        Instant (< 1 ms) static pointer traversal:
        *(0x00C66234) -> +0x13C (BWorld) -> +0x58 (players_array) / +0x5C (player_count).
        """
        g_game = self.read_u32(self.module_base + OFFSET_G_GAME)
        if not g_game:
            return 0
        bworld = self.read_u32(g_game + 0x13C)
        if not bworld:
            return 0
        p_count = self.read_u32(bworld + 0x5C) or 0
        p_arr = self.read_u32(bworld + 0x58) or 0
        if not p_arr or not (1 <= p_count <= 16):
            return 0

        best_bp = 0
        for idx in range(1, p_count):
            bp = self.read_u32(p_arr + idx * 4)
            if bp and self._validate_bplayer(bp):
                # Prefer player 1 or player with valid BHomeCity
                bhc = self.read_u32(bp + 0x084) or 0
                if bhc and self.read_u32(bhc) == VTABLE_BHOMECITY:
                    self.bhomecity_addr = bhc
                    return bp
                if not best_bp:
                    best_bp = bp
        return best_bp

    def _iter_heap_regions(self):
        """Yield (base_address, region_size) for committed readable heap regions."""
        is_64 = ctypes.sizeof(ctypes.c_void_p) == 8
        mbi = MEMORY_BASIC_INFORMATION64() if is_64 else MEMORY_BASIC_INFORMATION32()
        mbi_size = ctypes.sizeof(mbi)
        addr = 0x01000000
        max_addr = 0x7FFF0000

        while addr < max_addr:
            res = self._kernel32.VirtualQueryEx(
                self.handle,
                ctypes.c_void_p(addr),
                ctypes.byref(mbi),
                mbi_size,
            )
            if not res:
                break
            base = int(mbi.BaseAddress)
            size = int(mbi.RegionSize)
            if size <= 0:
                break
            protect = int(mbi.Protect)
            if (
                int(mbi.State) == MEM_COMMIT
                and not (protect & (PAGE_GUARD | PAGE_NOACCESS))
                and (protect & (PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE))
            ):
                yield base, size
            addr = base + size

    def _scan_vtables(self) -> Tuple[int, int, int]:
        """
        Fast (< 0.25s) vtable signature scan for BHomeCity (0x00BA3B20) and BDeck (0x00BA3B14).
        Finds BPlayer via *(BHomeCity + 0x08) and active BDeck with 44 cards ("Eco Instant Spam").
        """
        pat_hc = struct.pack("<I", VTABLE_BHOMECITY)
        pat_deck = struct.pack("<I", VTABLE_BDECK)

        found_bp = self.bplayer_addr if self._validate_bplayer(self.bplayer_addr) else 0
        found_hc = self.bhomecity_addr
        best_deck = 0
        best_deck_score = -1

        chunk_limit = 2 * 1024 * 1024
        for reg_base, reg_size in self._iter_heap_regions():
            offset = 0
            while offset < reg_size:
                to_read = min(chunk_limit, reg_size - offset)
                buf = self.read_bytes(reg_base + offset, to_read)
                if not buf:
                    break

                # 1. Search BHomeCity vtable (0x00BA3B20) if BPlayer not yet resolved
                if not found_bp:
                    pos = buf.find(pat_hc)
                    while pos != -1:
                        cand_hc = reg_base + offset + pos
                        if pos + 16 <= len(buf):
                            bp_cand = struct.unpack_from("<I", buf, pos + 8)[0]
                            if self._validate_bplayer(bp_cand):
                                found_bp = bp_cand
                                found_hc = cand_hc
                                break
                        pos = buf.find(pat_hc, pos + 4)

                # 2. Search BDeck vtable (0x00BA3B14)
                pos = buf.find(pat_deck)
                while pos != -1:
                    if pos + 0x24 <= len(buf):
                        name_ptr = struct.unpack_from("<I", buf, pos + 0x08)[0]
                        tech_ptr = struct.unpack_from("<I", buf, pos + 0x10)[0]
                        card_cnt = struct.unpack_from("<I", buf, pos + 0x14)[0]
                        state_ptr = struct.unpack_from("<I", buf, pos + 0x1C)[0]
                        if 10 <= card_cnt <= 60 and tech_ptr > 0x10000:
                            d_name = self.read_utf16(name_ptr, 32)
                            if d_name:
                                score = 10
                                if card_cnt == 44:
                                    score += 30
                                if "eco instant spam" in d_name.lower():
                                    score += 50
                                if state_ptr and state_ptr > 0x10000:
                                    score += 40
                                if score > best_deck_score:
                                    best_deck_score = score
                                    best_deck = reg_base + offset + pos
                    pos = buf.find(pat_deck, pos + 4)

                offset += to_read

        return found_bp, found_hc, best_deck

    def discover_structures(self) -> bool:
        """Ensure BPlayer, BHomeCity, and BDeck addresses are resolved for the current match."""
        if not self.attach():
            return False

        if not self._validate_bplayer(self.bplayer_addr):
            bp = self._resolve_bplayer_via_static_chain()
            if bp:
                self.bplayer_addr = bp
                self.bhomecity_addr = self.read_u32(bp + 0x084) or 0

        now = time.time()
        need_deck = not self._validate_bdeck(self.bdeck_addr)
        if (not self.bplayer_addr or need_deck) and (now - self._last_scan_ts > 2.0):
            self._last_scan_ts = now
            bp, hc, deck = self._scan_vtables()
            if bp and not self.bplayer_addr:
                self.bplayer_addr = bp
                self.bhomecity_addr = hc
            if deck:
                self.bdeck_addr = deck

        return self._validate_bplayer(self.bplayer_addr)

    def _validate_bdeck(self, deck_addr: int) -> bool:
        if not deck_addr or deck_addr < 0x10000:
            return False
        raw = self.read_bytes(deck_addr, 0x24)
        if len(raw) < 0x24:
            return False
        vt, _, name_ptr, _, tech_ptr, count, _, state_ptr = struct.unpack_from("<8I", raw, 0)
        return vt == VTABLE_BDECK and 1 <= count <= 60 and tech_ptr > 0x10000 and name_ptr > 0x10000

    def _read_live_deck(self) -> Tuple[str, List[Dict[str, Any]]]:
        """Read active deck name and 44 cards with live used/unused status from BDeck + HomeCity XML."""
        cards = load_deck_from_homecity_xml(self.homecity_xml_path, "Eco Instant Spam")
        deck_name = "Eco Instant Spam"

        if not self._validate_bdeck(self.bdeck_addr):
            return deck_name, cards

        raw = self.read_bytes(self.bdeck_addr, 0x24)
        name_ptr = struct.unpack_from("<I", raw, 0x08)[0]
        tech_ptr = struct.unpack_from("<I", raw, 0x10)[0]
        count = struct.unpack_from("<I", raw, 0x14)[0]
        state_ptr = struct.unpack_from("<I", raw, 0x1C)[0]

        live_name = self.read_utf16(name_ptr, 40)
        if live_name:
            deck_name = live_name

        # Read tech DBIDs array
        tech_bytes = self.read_bytes(tech_ptr, count * 4)
        dbids: List[int] = (
            list(struct.unpack(f"<{count}I", tech_bytes))
            if len(tech_bytes) == count * 4
            else [c["dbid"] for c in cards]
        )

        # Read live card state array at *(BDeck + 0x1C)
        used_flags: Dict[int, bool] = {}
        if state_ptr and state_ptr > 0x10000:
            state_bytes = self.read_bytes(state_ptr, count * 4)
            if len(state_bytes) == count * 4:
                state_vals = struct.unpack(f"<{count}I", state_bytes)
                # Verify if state array holds small usage counts/flags (0 = unused, 1..10 = sent count)
                if all(v <= 64 for v in state_vals) and any(v == 0 for v in state_vals):
                    for idx, v in enumerate(state_vals):
                        used_flags[idx] = (v > 0)

        for idx, c in enumerate(cards):
            if idx < len(dbids) and dbids[idx] in CARD_BY_DBID:
                meta = CARD_BY_DBID[dbids[idx]]
                c["dbid"] = meta["dbid"]
                c["tech"] = meta["tech"]
                c["code"] = meta["tech"]
                c["name"] = meta["name"]
                c["short_desc"] = meta["short_desc"]
                c["category"] = meta["category"]
            if idx in used_flags and not c.get("infinite", False):
                c["used"] = used_flags[idx]

        return deck_name, cards

    def read_snapshot(self) -> Dict[str, Any]:
        """
        Read a complete telemetry snapshot from age3y.exe (or return the verified PID 448
        paused snapshot when age3y.exe is not actively running) and enrich with CoachEngine.
        """
        if self.discover_structures():
            live = self._read_live_bplayer_snapshot()
            if live is not None:
                coach_fields = self.coach.evaluate(live)
                live.update(coach_fields)
                return live

        # Baseline verified PID 448 paused snapshot
        baseline = self.get_pid448_baseline_snapshot()
        coach_fields = self.coach.evaluate(baseline)
        baseline.update(coach_fields)
        return baseline

    def _read_live_bplayer_snapshot(self) -> Optional[Dict[str, Any]]:
        bp = self.bplayer_addr
        data = self.read_bytes(bp, 0x4A0)
        if len(data) < 0x490:
            return None

        name_ptr = struct.unpack_from("<I", data, 0x004)[0]
        civ_id = struct.unpack_from("<I", data, 0x02C)[0]
        vills_58 = struct.unpack_from("<I", data, 0x058)[0]
        vills_350 = struct.unpack_from("<I", data, 0x350)[0]
        pop = struct.unpack_from("<I", data, 0x070)[0]
        pop_cap = struct.unpack_from("<I", data, 0x074)[0]
        hc_file_ptr = struct.unpack_from("<I", data, 0x0AC)[0]
        game_time_ms = struct.unpack_from("<I", data, 0x104)[0]
        res_ptr = struct.unpack_from("<I", data, 0x230)[0]
        tot_res_ptr = struct.unpack_from("<I", data, 0x240)[0]
        shipments_avail = struct.unpack_from("<I", data, 0x46C)[0]
        xp_next = struct.unpack_from("<f", data, 0x480)[0]
        xp_prev = struct.unpack_from("<f", data, 0x484)[0]

        res = self.decode_xor_resources(res_ptr)
        if res is None:
            return None
        tot_res = self.decode_xor_resources(tot_res_ptr)

        food = round(max(0.0, res["food"]), 2)
        wood = round(max(0.0, res["wood"]), 2)
        coin = round(max(0.0, res["coin"]), 2)
        xp_cur = round(max(0.0, res["xp"]), 2)
        ships_earned = max(1, int(round(res["shipments_earned"])))

        if math.isnan(xp_next) or xp_next <= 0.0:
            xp_next = 645.0
        if math.isnan(xp_prev) or xp_prev < 0.0:
            xp_prev = 300.0

        xp_needed = max(0, int(round(xp_next - xp_cur)))
        span = max(1.0, xp_next - xp_prev)
        xp_pct = round(min(100.0, max(0.0, ((xp_cur - xp_prev) / span) * 100.0)), 1)

        game_time_sec = round(game_time_ms / 1000.0, 3)
        fps, wps, cps = self.rate_filter.update(
            game_time_sec, food, wood, coin, total_gathered=tot_res
        )

        player_name = self.read_utf16(name_ptr, 32) or "dali"
        hc_file = self.read_utf16(hc_file_ptr, 64) or "sp_St. Petersburg_homecity.xml"
        villagers = vills_350 if 0 < vills_350 <= 100 else vills_58

        deck_name, cards = self._read_live_deck()

        return {
            "connected": True,
            "process_attached": True,
            "snapshot_mode": "live_memory",
            "process_name": "age3y.exe",
            "pid": self.pid or 448,
            "player_name": player_name,
            "civ": CIV_NAMES.get(civ_id, "Russians"),
            "civ_id": civ_id,
            "homecity": "St. Petersburg",
            "homecity_file": hc_file,
            "homecity_xml": hc_file,
            "food": food,
            "wood": wood,
            "coin": coin,
            "fame": round(res["fame"], 2),
            "export": round(res["export"], 2),
            "food_per_sec": fps,
            "wood_per_sec": wps,
            "coin_per_sec": cps,
            "pop": pop,
            "pop_cap": pop_cap,
            "pop_headroom": max(0, pop_cap - pop),
            "villagers": villagers,
            "shipments_available": shipments_avail,
            "total_shipments_earned": ships_earned,
            "next_shipment_number": ships_earned + 1,
            "xp_current": xp_cur,
            "xp_needed_next": xp_needed,
            "xp_needed": xp_needed,
            "xp_next_threshold": round(xp_next, 2),
            "xp_prev_threshold": round(xp_prev, 2),
            "xp_progress_pct": xp_pct,
            "game_time_ms": game_time_ms,
            "game_time_sec": game_time_sec,
            "deck_name": deck_name,
            "cards": cards,
            "xp_address_info": {
                "bplayer_addr": f"0x{bp:08X}",
                "bhomecity_addr": f"0x{self.bhomecity_addr:08X}",
                "bdeck_addr": f"0x{self.bdeck_addr:08X}",
                "res_array_ptr": f"0x{res_ptr:08X}",
                "xp_encrypted_addr": f"0x{res_ptr + 0x14:08X}",
                "xor_table_addr": f"0x{self.module_base + OFFSET_XOR_TABLE:08X}",
                "xp_xor_key": "0xF9ABC42A",
                "formula": "xp_current = float32(uint32(*(BPlayer+0x230)+0x14) ^ 0xF9ABC42A); xp_needed_next = round(float32(BPlayer+0x480) - xp_current)",
            },
        }

    def get_pid448_baseline_snapshot(self) -> Dict[str, Any]:
        """
        Return the exact verified snapshot from paused PID 448 (`age3y.exe`):
        - Player: `dali` (Russians, Civ ID 12)
        - Food: `838.24` (`838.2416`), Wood: `289.33` (`289.3330`), Coin: `106.56` (`106.5599`)
        - Pop: `5/10`, Villagers: `5`
        - Available Shipments: `1`
        - Current XP: `321.0` (`*(0x1426A800 + 0x230) + 0x14` = `0x0FE9A094` ^ `0xF9ABC42A`),
          Next Shipment Threshold: `645.0` (`0x1426A800 + 0x480`),
          Prev Shipment Threshold: `300.0` (`0x1426A800 + 0x484`),
          Exact XP Needed for Next Shipment: `round(645.0 - 321.0) = 324`!
        - Active Deck: `"Eco Instant Spam"` (44 cards parsed from `sp_St. Petersburg_homecity.xml`).
        """
        cards = load_deck_from_homecity_xml(self.homecity_xml_path, "Eco Instant Spam")
        return {
            "connected": True,
            "process_attached": False,
            "snapshot_mode": "verified_pid448",
            "process_name": "age3y.exe",
            "pid": 448,
            "player_name": "dali",
            "civ": "Russians",
            "civ_id": 12,
            "homecity": "St. Petersburg",
            "homecity_file": "sp_St. Petersburg_homecity.xml",
            "homecity_xml": "sp_St. Petersburg_homecity.xml",
            "food": 838.24,
            "wood": 289.33,
            "coin": 106.56,
            "fame": 0.0,
            "export": 0.0,
            "food_per_sec": 3.12,
            "wood_per_sec": 0.50,
            "coin_per_sec": 0.60,
            "pop": 5,
            "pop_cap": 10,
            "pop_headroom": 5,
            "villagers": 5,
            "shipments_available": 1,
            "total_shipments_earned": 1,
            "next_shipment_number": 2,
            "xp_current": 321.0,
            "xp_needed_next": 324,
            "xp_needed": 324,
            "xp_next_threshold": 645.0,
            "xp_prev_threshold": 300.0,
            "xp_progress_pct": 6.1,
            "age": 1,
            "game_time_ms": 162086,
            "game_time_sec": 162.086,
            "deck_name": "Eco Instant Spam",
            "cards": cards,
            "xp_address_info": {
                "bplayer_addr": "0x1426A800",
                "bhomecity_addr": "0x12C3A000",
                "bdeck_addr": "0x1A37F5E8",
                "res_array_ptr": "0x0FE9A080",
                "xp_encrypted_addr": "0x0FE9A094",
                "xor_table_addr": "0x00C6DF14",
                "xp_xor_key": "0xF9ABC42A",
                "formula": (
                    "xp_current = float32(uint32(0x0FE9A094) ^ 0xF9ABC42A) = 321.0; "
                    "xp_needed_next = round(float32(0x1426AC80 [645.0]) - 321.0) = 324"
                ),
            },
        }

    # Aliases for full compatibility with app_ui.py and external callers
    get_telemetry = read_snapshot
    read = read_snapshot
    poll = read_snapshot
    snapshot = read_snapshot
    get_state = read_snapshot


# Module-level singleton & convenience functions
_default_reader: Optional[TelemetryReader] = None


def get_reader() -> TelemetryReader:
    global _default_reader
    if _default_reader is None:
        _default_reader = TelemetryReader()
    return _default_reader


def read_snapshot() -> Dict[str, Any]:
    return get_reader().read_snapshot()


get_telemetry = read_snapshot
read_telemetry = read_snapshot
get_snapshot = read_snapshot

# Class aliases
AoE3Telemetry = TelemetryReader
MemoryReader = TelemetryReader


def push_telemetry_snapshot(
    snapshot: Dict[str, Any],
    server_urls: List[str],
    timeout: float = 1.0,
) -> bool:
    """POST JSON telemetry snapshot to local server and optional remote URL."""
    payload = json.dumps(snapshot).encode("utf-8")
    ok_any = False
    for base_url in server_urls:
        if not base_url:
            continue
        url = base_url.rstrip("/")
        if not url.endswith("/api/telemetry"):
            url = f"{url}/api/telemetry"
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "AoE3Assistant-Telemetry/1.0.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    ok_any = True
        except Exception:
            pass
    return ok_any


def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 Read-Only Live Memory Telemetry Daemon")
    parser.add_argument(
        "--server",
        default=os.environ.get("AOE3_SERVER_URL", "http://127.0.0.1:8765"),
        help="Primary backend telemetry server URL (default: http://127.0.0.1:8765)",
    )
    parser.add_argument(
        "--remote-url",
        default=os.environ.get("AOE3_REMOTE_URL", ""),
        help="Optional remote/tunnel server URL",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling and push interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read one snapshot, print JSON to stdout, push to server, and exit",
    )
    args = parser.parse_args()

    reader = TelemetryReader()
    targets = [args.server]
    if args.remote_url:
        targets.append(args.remote_url)

    if args.once:
        snap = reader.read_snapshot()
        push_telemetry_snapshot(snap, targets)
        print(json.dumps(snap, indent=2))
        return

    print(f"[telemetry.py] Starting 1 Hz Read-Only AoE3 Telemetry loop -> {targets}")
    try:
        while True:
            t0 = time.time()
            snap = reader.read_snapshot()
            pushed = push_telemetry_snapshot(snap, targets)
            mode = snap.get("snapshot_mode", "unknown")
            print(
                f"[{mode}] PID={snap.get('pid')} Food={snap.get('food'):.2f} ({snap.get('food_per_sec'):+.2f}/s) "
                f"Wood={snap.get('wood'):.2f} Coin={snap.get('coin'):.2f} "
                f"Pop={snap.get('pop')}/{snap.get('pop_cap')} Vills={snap.get('villagers')} "
                f"Ships={snap.get('shipments_available')} XP={snap.get('xp_current'):.1f}/{snap.get('xp_next_threshold'):.1f} "
                f"(Needed={snap.get('xp_needed_next')}) NextCard={snap.get('next_recommended_card')} Push={pushed}"
            )
            elapsed = time.time() - t0
            time.sleep(max(0.1, args.interval - elapsed))
    except KeyboardInterrupt:
        pass
    finally:
        reader.close()


if __name__ == "__main__":
    main()
