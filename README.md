# AoE3 Live Telemetry & Russia Coach (`aoe3-assistant`)

Real-time memory telemetry, live Russia (**"Eco Instant Spam"**) coaching engine, toggleable PC HUD overlay, responsive Web Dashboard, and native signed Android Companion APK for **Age of Empires III: The Asian Dynasties (Complete Collection - `age3y.exe`)**.

---

## Architecture & Components

### 1. Strictly Read-Only Live Telemetry (`pc-app/telemetry.py`)
- Uses `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION` only (zero memory writes, zero hooks, zero FPS impact).
- **Instant `<1ms` Static Pointer Chain + `<0.25s` Vtable Scan Fallback**:
  - Primary chain: `g_game = *(0x00400000 + 0x00866234)` (`0x00C66234`) -> `BWorld = *(g_game + 0x13C)` -> `players_array = *(BWorld + 0x58)` -> `BPlayer`.
  - Vtable scan fallback: `BHomeCity` (`vtable 0x00BA3B20` -> `+0x08` `BPlayer`) and `BDeck` (`vtable 0x00BA3B14`).
- **XOR-Obfuscated Resource & XP Decryption (`0x00C6DF14` static 8-DWORD XOR key table)**:
  - `*(BPlayer + 0x230)` points to the live `uint32[8]` XOR-encoded resource array:
    - `[0]` Coin (`+0x00 ^ 0x2848AC4F`) -> `106.56`
    - `[1]` Wood (`+0x04 ^ 0x94F83A35`) -> `289.33`
    - `[2]` Food (`+0x08 ^ 0x8BD84C3F`) -> `838.24`
    - `[5]` **Current Match XP (`+0x14 ^ 0xF9ABC42A`)** -> `321.0` (`float32`)
  - **Exact `324` XP-Needed Formula**:
    - `xp_next_threshold = float32(*(BPlayer + 0x480))` = `645.0`
    - `xp_prev_threshold = float32(*(BPlayer + 0x484))` = `300.0`
    - `xp_needed_next = round(xp_next_threshold - xp_current) = round(645.0 - 321.0) = 324`
- Reads live **Food, Wood, Coin**, exact **`food_per_sec`, `wood_per_sec`, `coin_per_sec`** (filtering sudden training spends like `-270f` and shipment crate spikes), **Population (`5/10`)**, **Villagers (`5`)**, **Available Shipments (`1`)**, **Current XP (`321.0`) & XP Needed (`324`)**, and all **44 cards** in **`Eco Instant Spam`** across Ages I–IV (cross-referenced with `sp_St. Petersburg_homecity.xml`).

### 2. Real-Time Russia Coach Engine (`pc-app/coach.py`)
- **TC 3-Settler Batch Heartbeat**: Tracks Russian 3-Settler batch training (`270 Food` / `53s` heartbeat) and alerts when the Town Center is idle.
- **War & Unit-Loss Detection**: Detects sudden population drops and raises combat alerts.
- **Resource Floating & Shipment Alerts**: Flags unspent shipments and macro imbalances.
- **Next Recommended Card**: Recommends the optimal card from the 44-card `Eco Instant Spam` deck for the current Age and economy state (e.g., *Distributivism*, *Boyars*, *5 Cossacks*, *2 Blockhouses*, *Factories*).

### 3. Toggleable PC Companion HUD, Portable EXE & Setup Installer (`pc-app/app_ui.py`, `pc-app/updater.py`, `installer/setup_installer.py`)
- Lightweight Tkinter HUD overlay + top-right floating pill (`⚔ AoE3 Coach [F8: Hide/Show]`).
- Global hotkey toggle via **`F8`** and **`Ctrl+Shift+A`**.
- Optional non-blocking Windows SAPI / TTS voice callouts for urgent alerts.
- Built-in auto-updater (`updater.py`) checking `/api/version` and GitHub Releases (`DALI951/aoe3-assistant`).
- Packaged into:
  - `dist/AoE3Assistant.exe` (Standalone Portable Executable)
  - `dist/AoE3AssistantSetup.exe` (Windows Setup Installer with Desktop/Start Menu shortcuts & `--silent` upgrade support)

### 4. Real-Time Telemetry Server & Web Dashboard (`server/server.py`, `server/static/index.html`)
- Runs on `0.0.0.0:8765` (Localhost `http://127.0.0.1:8765`, LAN `http://192.168.1.154:8765`, plus `server/modali_relay.php` for `https://modali.powerpme.com` VPS relay & optional `POST /api/tunnel/start` Cloudflare Tunnel).
- Endpoints:
  - `POST /api/telemetry` — ingests 1 Hz telemetry snapshots
  - `GET /api/state` — returns latest full telemetry & coaching state
  - `GET /api/stream` — unified 1 Hz WebSocket (`ws://`) & Server-Sent Events (`text/event-stream`) stream
  - `GET /api/version` & `/releases/<filename>` — self-update manifest and local binary mirror

### 5. Native Signed Android Companion App (`android-app/`, `dist/AoE3Assistant.apk`)
- V1 + V2 + V3 signed Android APK (`com.dali.aoe3assistant`, API 26–33).
- Pre-configured with LAN (`http://192.168.1.154:8765`) and remote (`https://modali.powerpme`) quick-switcher chips.
- Displays live resources, gather rates, Pop `5/10`, Villagers `5`, Shipments `1`, `324 XP needed`, War/TC alerts, 44-card `Eco Instant Spam` grid, Android TTS voice alerts, and built-in **APK Self-Updater** via Android `DownloadManager`.

---

## Downloads & Auto-Update URLs (GitHub Releases `v1.0.0`)

- **Release Metadata (`version.json`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/version.json`
- **Windows Setup Installer (`AoE3AssistantSetup.exe`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3AssistantSetup.exe`
- **Windows Portable App (`AoE3Assistant.exe`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3Assistant.exe`
- **Android Companion APK (`AoE3Assistant.apk`)**: `https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3Assistant.apk`
