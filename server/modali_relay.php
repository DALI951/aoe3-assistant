<?php
/**
 * AoE3 Live Telemetry & Russia Coach — Remote VPS Relay for modali.powerpme.com (212.227.215.235)
 * Drop this file on Apache 2.4.58 (Ubuntu) at /var/www/html/aoe3/index.php (or api.php)
 * to allow pc-app/telemetry.py to push live telemetry to https://modali.powerpme.com/aoe3/api/telemetry
 * and phones outside the LAN to read https://modali.powerpme.com/aoe3/api/state.
 */
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Methods: GET, POST, OPTIONS");
header("Access-Control-Allow-Headers: Content-Type, Authorization, X-App-Secret");

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$stateFile = __DIR__ . '/telemetry_state.json';
$uri = $_SERVER['REQUEST_URI'] ?? '/';

if ($_SERVER['REQUEST_METHOD'] === 'POST' && (strpos($uri, 'telemetry') !== false || isset($_GET['telemetry']))) {
    $raw = file_get_contents('php://input');
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) {
        $decoded['relay_host'] = 'modali.powerpme.com';
        $decoded['relay_timestamp'] = microtime(true);
        file_put_contents($stateFile, json_encode($decoded, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), LOCK_EX);
        header("Content-Type: application/json");
        echo json_encode(["status" => "ok", "relay" => "modali.powerpme.com"]);
        exit;
    }
    http_response_code(400);
    header("Content-Type: application/json");
    echo json_encode(["status" => "error", "message" => "Invalid JSON payload"]);
    exit;
}

if (strpos($uri, 'version') !== false || isset($_GET['version'])) {
    header("Content-Type: application/json");
    echo json_encode([
        "version" => "1.0.0",
        "exe_version" => "1.0.0",
        "apk_version" => "1.0.0",
        "tag" => "v1.0.0",
        "repo" => "DALI951/aoe3-assistant",
        "version_json_url" => "https://github.com/DALI951/aoe3-assistant/releases/latest/download/version.json",
        "exe_url" => "https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3Assistant.exe",
        "setup_url" => "https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3AssistantSetup.exe",
        "apk_url" => "https://github.com/DALI951/aoe3-assistant/releases/latest/download/AoE3Assistant.apk"
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

header("Content-Type: application/json");
if (file_exists($stateFile)) {
    readfile($stateFile);
} else {
    echo json_encode(["status" => "waiting_for_telemetry", "relay" => "modali.powerpme.com"]);
}
