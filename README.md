# AoE3 Live Telemetry & Russia Coach (`aoe3-assistant`)

Real-time memory telemetry, live Russia (**"Eco Instant Spam"**) coaching engine, toggleable & draggable PC HUD overlay, responsive Web Dashboard, and native clean Android Companion APK for **Age of Empires III: The Asian Dynasties (Complete Collection - `age3y.exe`)**.

---

## What's New in v1.1.0

- **Zero Defaults When Inactive**: Numeric fields strictly reset to `0` when `age3y.exe` is not running or not in an active match (no stale/hardcoded values).
- **Match State Detection**: Explicit status tracking: `GAME_NOT_RUNNING` ("Game not running — run a game"), `WAITING_FOR_MATCH`, `PLAYING` ("In Match — Playing"), or `PAUSED` ("In Match — Paused").
- **XP/s Metric**: Computes live XP gather rate (`xp_per_sec`) alongside Food/s, Wood/s, and Coin/s.
- **Accurate Used Cards Tracking**: Directly reads tech state and shipment history from memory (`cards_used_count`, `cards_remaining_count`).
- **Completely Silent**: Removed all voice/TTS/sound callouts across PC HUD, Web UI, and Android APK.
- **F12 Toggle Hotkey**: Switched global toggle hotkey from `F8` to **`F12`** (plus `Ctrl+Shift+A`).
- **Draggable Floating Overlay**: Compact pill bar and expanded HUD can be freely dragged anywhere on screen with the mouse.
- **Always-On Startup Background Service**: Supports running silently at Windows boot (`--background`), auto-streaming whenever `age3y.exe` launches.
- **Standard Windows Setup Installer**: Multi-page installer wizard with options for Windows Startup, desktop shortcuts, and uninstaller.
- **Clean Spacious Android Companion App**: Redesigned mobile layout focused on clear high-visibility resources, rates, population, and match state.

---

## Architecture & Components

### 1. Strictly Read-Only Live Telemetry (`pc-app/telemetry.py`)
- Strictly uses `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION` (zero game writes, zero hooks, zero anti-cheat trigger).
- **Instant `<1ms` Static Pointer Chain + `<0.25s` Vtable Scan Fallback**:
  - Primary chain: `g_game = *(0x00400000 + 0x00866234)` (`0x00C66234`) -> `BWorld = *(g_game + 0x13C)` -> `players_array = *(BWorld + 0x58)` -> `BPlayer`.
  - Vtable scan fallback: `BHomeCity` (`vtable 0x00BA3B20` -> `+0x08` `BPlayer`) and `BDeck` (`vtable 0x00BA3B14`).
- **XOR-Obfuscated Resource & XP Decryption (`0x00C6DF14` static 8-DWORD XOR key table)**:
  - `*(BPlayer + 0x230)` points to the live `uint32[8]` XOR-encoded resource array:
    - `[0]` Coin (`+0x00 ^ 0x2848AC4F`)
    - `[1]` Wood (`+0x04 ^ 0x94F83A35`)
    - `[2]` Food (`+0x08 ^ 0x8BD84C3F`)
    - `[5]` Current Match XP (`+0x14 ^ 0xF9ABC42A`)
  - **XP Calculation**:
    - `xp_next_threshold = float32(*(BPlayer + 0x480))`
    - `xp_prev_threshold = float32(*(BPlayer + 0x484))`
    - `xp_needed_next = round(xp_next_threshold - xp_current)`

### 2. Russia Coach Engine (`pc-app/coach.py`)
- Evaluates Russian Town Center 3-Settler batch heartbeat (`270 Food` / `53s` timer).
- Monitors combat/unit losses and unspent shipments.
- Suggests unused cards from the 44-card `Eco Instant Spam` deck.

### 3. PC Companion App & Setup Installer (`pc-app/app_ui.py`, `installer/setup_installer.py`)
- Freely draggable Tkinter HUD overlay with **`F12`** and **`Ctrl+Shift+A`** hotkeys.
- Windows Startup registration (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- Standalone portable `dist/AoE3Assistant.exe` and standard installer wizard `dist/AoE3AssistantSetup.exe`.

### 4. Telemetry Server & Web Dashboard (`server/server.py`, `server/static/index.html`)
- Runs on port `8765` (`http://127.0.0.1:8765`, `http://192.168.1.154:8765`).
- Streams live telemetry over SSE/WebSocket and serves download mirrors.

### 5. Android Companion App (`android-app/`, `dist/AoE3Assistant.apk`)
- Clean, non-cramped UI designed for mobile screens showing live resources, income/s, pop/villagers, and match state.
- In-app self-updater checking GitHub Releases.

---

## Downloads (GitHub Releases `v1.1.0`)

- **Release Metadata (`version.json`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/version.json`
- **Windows Setup Installer (`AoE3AssistantSetup.exe`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3AssistantSetup.exe`
- **Windows Portable App (`AoE3Assistant.exe`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3Assistant.exe`
- **Android Companion APK (`AoE3Assistant.apk`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3Assistant.apk`
