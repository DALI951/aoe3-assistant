"""
AoE3 Live Telemetry & Russia Coach — Android APK Builder (build_apk.py)
Compiles a standards-compliant, 4-byte zipaligned, V1+V2+V3 signed Android APK
targeting Android 8.0+ (minSdkVersion 26, targetSdkVersion 33) using:
  - Eclipse Adoptium JDK 17 (javac, java, keytool)
  - Android SDK AAPT2 (aapt2.exe)
  - Android D8 Dexer (com.android.tools.r8.D8 from r8.jar)
  - Official Android ApkSigner & ApkVerifier (com.android.apksig from apksig.jar)
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(APP_DIR, ".."))
BUILD_DIR = os.path.join(APP_DIR, "build")
DIST_DIR = os.path.join(ROOT_DIR, "dist")
SERVER_RELEASES_DIR = os.path.join(ROOT_DIR, "server", "releases")

JDK_BIN = r"C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot\bin"
JAVA = os.path.join(JDK_BIN, "java.exe")
JAVAC = os.path.join(JDK_BIN, "javac.exe")
KEYTOOL = os.path.join(JDK_BIN, "keytool.exe")

AAPT2 = r"C:\Users\Dali\.gradle\caches\8.10.2\transforms\e394b1000ce74bbb137c4336273af50e\transformed\aapt2-8.7.3-12006047-windows\aapt2.exe"
ANDROID_JAR = r"C:\Users\Dali\.gradle\caches\8.10.2\transforms\88659d9cdc029f1a0a6f277d91a2957c\transformed\android.jar"
R8_JAR = r"C:\Program Files\Android\Android Studio\plugins\android\lib\r8.jar"
APKSIG_JAR = r"C:\Users\Dali\.gradle\caches\modules-2\files-2.1\com.android.tools.build\apksig\8.7.3\f005788487574c7d6ba23dea63bf8cb3a4f164a6\apksig-8.7.3.jar"
FW_RES_JAR = r"C:\Program Files\Android\Android Studio\plugins\design-tools\resources\layoutlib\data\framework_res.jar"


def run_cmd(cmd, desc):
    print(f"[*] {desc}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[!] ERROR in {desc}:")
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        sys.exit(1)
    return res


def generate_launcher_icon(png_path):
    """Generates a 192x192 gold-and-crimson AoE3 Russia Coach emblem PNG."""
    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    w, h = 192, 192
    cx, cy = w / 2.0, h / 2.0
    raw_rows = bytearray()

    for y in range(h):
        raw_rows.append(0)  # filter type 0
        for x in range(w):
            dx = x - cx
            dy = y - cy
            dist = math.hypot(dx, dy)

            # Rounded square mask
            nx = abs(dx) / (w * 0.44)
            ny = abs(dy) / (h * 0.44)
            super_ellipse = (nx ** 5 + ny ** 5) ** 0.2

            if super_ellipse > 1.04:
                raw_rows.extend((0, 0, 0, 0))
                continue

            # Gold outer border
            if super_ellipse > 0.93:
                raw_rows.extend((245, 185, 66, 255))
                continue

            # Inner dark crimson-navy radial gradient
            t = min(1.0, dist / (w * 0.45))
            r = int(135 * (1 - t) + 14 * t)
            g = int(18 * (1 - t) + 20 * t)
            b = int(32 * (1 - t) + 36 * t)

            # Gold Imperial ring & stylized shield/star motif in center
            ring_d = abs(dist - 58.0)
            shield = (abs(dx) < 34 and -38 < dy < 26 and (abs(dx) + max(0, dy) * 0.85) < 42)
            inner_cross = (abs(dx) < 7 and abs(dy) < 28) or (abs(dy) < 7 and abs(dx) < 28)
            crown_top = (abs(dx) < 22 and -50 <= dy <= -36 and (int(abs(dx)) % 7 < 4))

            if ring_d < 4.2 or crown_top:
                r, g, b = 245, 185, 66
            elif shield:
                if inner_cross:
                    r, g, b = 250, 204, 82
                elif abs(dx) > 28 or dy < -32 or (abs(dx) + max(0, dy) * 0.85) > 36:
                    r, g, b = 245, 185, 66
                else:
                    r, g, b = 185, 24, 48

            raw_rows.extend((r, g, b, 255))

    def make_chunk(chunk_type, data):
        chunk = struct.pack(">I", len(data)) + chunk_type + data
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return chunk + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_rows), 9)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + make_chunk(b"IHDR", ihdr)
        + make_chunk(b"IDAT", idat)
        + make_chunk(b"IEND", b"")
    )
    with open(png_path, "wb") as f:
        f.write(png_bytes)
    print(f"[+] Generated launcher icon: {png_path} ({len(png_bytes)} bytes)")


def build_framework_apk(fw_apk_path):
    """Builds minimal Android framework resource APK (package 'android', ID 0x01) from Android Studio layoutlib."""
    if os.path.isfile(fw_apk_path) and os.path.getsize(fw_apk_path) > 50000:
        print(f"[+] Using cached framework APK: {fw_apk_path}")
        return

    fw_work = os.path.join(BUILD_DIR, "fw_work")
    if os.path.exists(fw_work):
        shutil.rmtree(fw_work)
    res_values = os.path.join(fw_work, "res", "values")
    os.makedirs(res_values, exist_ok=True)

    with zipfile.ZipFile(FW_RES_JAR, "r") as z:
        defined_attrs = set()
        defined_ids = set()
        for fn in ["attrs_manifest.xml", "attrs.xml", "attrs_car.xml", "ids.xml"]:
            data = z.read(f"res/values/{fn}").decode("utf-8")
            root = ET.fromstring(data)
            for el in root.iter():
                if el.tag == "attr" and "name" in el.attrib:
                    defined_attrs.add(el.attrib["name"])
                elif el.tag == "item" and el.attrib.get("type") == "id" and "name" in el.attrib:
                    defined_ids.add(el.attrib["name"])
            with open(os.path.join(res_values, fn), "w", encoding="utf-8") as f:
                f.write(data)

        pub_data = z.read("res/values/public-final.xml").decode("utf-8")
        pub_root = ET.fromstring(pub_data)
        new_pub = ET.Element("resources")
        for el in pub_root:
            if el.tag == "public":
                t = el.attrib.get("type")
                n = el.attrib.get("name")
                if (t == "attr" and n in defined_attrs) or (t == "id" and n in defined_ids):
                    new_pub.append(el)
        ET.ElementTree(new_pub).write(
            os.path.join(res_values, "public.xml"), encoding="utf-8", xml_declaration=True
        )

    manifest_path = os.path.join(fw_work, "AndroidManifest.xml")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="android"/>\n')

    compiled_zip = os.path.join(fw_work, "fw_compiled.zip")
    run_cmd([AAPT2, "compile", "--dir", os.path.join(fw_work, "res"), "-o", compiled_zip], "Compile framework resources")
    run_cmd([AAPT2, "link", "-o", fw_apk_path, "--manifest", manifest_path, compiled_zip], "Link framework.apk")


def zipalign_apk(base_res_apk, classes_dex_path, aligned_apk_path):
    """
    Combines linked resources/manifest/assets from base_res_apk with classes.dex,
    keeping resources.arsc and PNGs uncompressed (ZIP_STORED) and 4-byte aligned.
    """
    entries = []
    with zipfile.ZipFile(base_res_apk, "r") as zin:
        for info in zin.infolist():
            data = zin.read(info.filename)
            is_stored = (
                info.filename == "resources.arsc"
                or info.filename.lower().endswith(".png")
            )
            entries.append((info.filename, data, is_stored))

    with open(classes_dex_path, "rb") as f:
        dex_data = f.read()
    entries.append(("classes.dex", dex_data, False))

    if os.path.exists(aligned_apk_path):
        os.remove(aligned_apk_path)

    with zipfile.ZipFile(aligned_apk_path, "w") as zout:
        for filename, data, is_stored in entries:
            zinfo = zipfile.ZipInfo(filename=filename, date_time=(2026, 1, 1, 0, 0, 0))
            zinfo.external_attr = 0o644 << 16
            if is_stored:
                zinfo.compress_type = zipfile.ZIP_STORED
                current_offset = zout.fp.tell()
                fname_len = len(filename.encode("utf-8"))
                data_start = current_offset + 30 + fname_len
                pad = (4 - (data_start % 4)) % 4
                zinfo.extra = b"\x00" * pad
                zout.writestr(zinfo, data)
            else:
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.extra = b""
                zout.writestr(zinfo, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    # Verify 4-byte alignment of all ZIP_STORED entries
    with open(aligned_apk_path, "rb") as f:
        raw = f.read()
    with zipfile.ZipFile(aligned_apk_path, "r") as zcheck:
        for info in zcheck.infolist():
            if info.compress_type == zipfile.ZIP_STORED:
                hdr_off = info.header_offset
                fn_len, ex_len = struct.unpack("<HH", raw[hdr_off + 26 : hdr_off + 30])
                data_off = hdr_off + 30 + fn_len + ex_len
                assert data_off % 4 == 0, f"Entry {info.filename} not 4-byte aligned (offset {data_off})"
    print(f"[+] Built 4-byte aligned unsigned APK: {aligned_apk_path} ({os.path.getsize(aligned_apk_path)} bytes)")


def sign_and_verify_apk(unsigned_apk, signed_apk):
    """Signs APK with a permanent release keystore using apksig.jar, and verifies it."""
    keystore_dir = os.path.join(APP_DIR, "keystore")
    os.makedirs(keystore_dir, exist_ok=True)
    keystore_path = os.path.join(keystore_dir, "release.jks")
    ks_pass = "aoe3coach123"
    key_alias = "aoe3coach"

    if not os.path.isfile(keystore_path):
        run_cmd(
            [
                KEYTOOL,
                "-genkeypair",
                "-v",
                "-keystore",
                keystore_path,
                "-storetype",
                "JKS",
                "-storepass",
                ks_pass,
                "-keypass",
                ks_pass,
                "-alias",
                key_alias,
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-dname",
                "CN=AoE3 Russia Coach, OU=AoE3Assistant, O=Dali, L=Tunis, ST=Tunis, C=TN",
            ],
            "Generate release signing keystore",
        )

    signer_dir = os.path.join(BUILD_DIR, "signer_tool")
    os.makedirs(signer_dir, exist_ok=True)
    signer_java = os.path.join(signer_dir, "ApkSignTool.java")

    signer_code = """
import com.android.apksig.ApkSigner;
import com.android.apksig.ApkVerifier;
import java.io.File;
import java.io.FileInputStream;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class ApkSignTool {
    public static void main(String[] args) throws Exception {
        File ksFile = new File(args[0]);
        String ksPass = args[1];
        String alias = args[2];
        File inApk = new File(args[3]);
        File outApk = new File(args[4]);

        KeyStore ks = KeyStore.getInstance("PKCS12");
        try (FileInputStream fis = new FileInputStream(ksFile)) {
            ks.load(fis, ksPass.toCharArray());
        }
        PrivateKey privateKey = (PrivateKey) ks.getKey(alias, ksPass.toCharArray());
        Certificate[] chain = ks.getCertificateChain(alias);
        List<X509Certificate> certs = new ArrayList<>();
        for (Certificate c : chain) {
            certs.add((X509Certificate) c);
        }

        ApkSigner.SignerConfig signerConfig = new ApkSigner.SignerConfig.Builder(
                "AOE3COACH", privateKey, certs).build();

        if (outApk.exists()) {
            outApk.delete();
        }

        ApkSigner signer = new ApkSigner.Builder(Collections.singletonList(signerConfig))
                .setInputApk(inApk)
                .setOutputApk(outApk)
                .setMinSdkVersion(26)
                .setV1SigningEnabled(true)
                .setV2SigningEnabled(true)
                .setV3SigningEnabled(true)
                .build();
        signer.sign();

        ApkVerifier verifier = new ApkVerifier.Builder(outApk)
                .setMinCheckedPlatformVersion(18)
                .build();
        ApkVerifier.Result result = verifier.verify();
        System.out.println("APK_VERIFIED=" + result.isVerified());
        System.out.println("V1_VERIFIED=" + result.isVerifiedUsingV1Scheme());
        System.out.println("V2_VERIFIED=" + result.isVerifiedUsingV2Scheme());
        System.out.println("V3_VERIFIED=" + result.isVerifiedUsingV3Scheme());
        if (!result.isVerified()) {
            for (ApkVerifier.IssueWithParams err : result.getErrors()) {
                System.err.println("VERIFY_ERR: " + err);
            }
            System.exit(2);
        }
    }
}
"""
    with open(signer_java, "w", encoding="utf-8") as f:
        f.write(signer_code.strip() + "\n")

    run_cmd([JAVAC, "-cp", APKSIG_JAR, "-d", signer_dir, signer_java], "Compile ApkSignTool")
    os.makedirs(os.path.dirname(signed_apk), exist_ok=True)
    cp_sep = ";" if os.name == "nt" else ":"
    res = run_cmd(
        [
            JAVA,
            "-cp",
            f"{signer_dir}{cp_sep}{APKSIG_JAR}",
            "ApkSignTool",
            keystore_path,
            ks_pass,
            key_alias,
            unsigned_apk,
            signed_apk,
        ],
        "Sign & Verify APK (V1+V2+V3)",
    )
    print(res.stdout.strip())


def main():
    os.makedirs(BUILD_DIR, exist_ok=True)
    os.makedirs(DIST_DIR, exist_ok=True)

    # 1. Generate Launcher Icon
    icon_path = os.path.join(APP_DIR, "res", "drawable", "ic_launcher.png")
    generate_launcher_icon(icon_path)

    # 2. Build Android framework.apk for AAPT2 linking
    fw_apk = os.path.join(BUILD_DIR, "framework.apk")
    build_framework_apk(fw_apk)

    # 3. Compile app resources with AAPT2
    compiled_res_zip = os.path.join(BUILD_DIR, "compiled_res.zip")
    if os.path.exists(compiled_res_zip):
        os.remove(compiled_res_zip)
    run_cmd(
        [AAPT2, "compile", "--dir", os.path.join(APP_DIR, "res"), "-o", compiled_res_zip],
        "Compile app resources with AAPT2",
    )

    # 4. Link resources, AndroidManifest.xml, and assets/ with AAPT2
    gen_dir = os.path.join(BUILD_DIR, "gen")
    if os.path.exists(gen_dir):
        shutil.rmtree(gen_dir)
    os.makedirs(gen_dir, exist_ok=True)
    base_res_apk = os.path.join(BUILD_DIR, "base_res.apk")
    if os.path.exists(base_res_apk):
        os.remove(base_res_apk)

    run_cmd(
        [
            AAPT2,
            "link",
            "-o",
            base_res_apk,
            "--manifest",
            os.path.join(APP_DIR, "AndroidManifest.xml"),
            "-I",
            fw_apk,
            "-A",
            os.path.join(APP_DIR, "assets"),
            "--java",
            gen_dir,
            "--min-sdk-version",
            "21",
            "--target-sdk-version",
            "33",
            "--version-code",
            "3",
            "--version-name",
            "1.2.0",
            compiled_res_zip,
        ],
        "Link APK resources, manifest & assets with AAPT2",
    )

    # 5. Compile Java sources (MainActivity.java + generated R.java) with javac
    classes_dir = os.path.join(BUILD_DIR, "classes")
    if os.path.exists(classes_dir):
        shutil.rmtree(classes_dir)
    os.makedirs(classes_dir, exist_ok=True)

    r_java = os.path.join(gen_dir, "com", "dali", "aoe3assistant", "R.java")
    main_java = os.path.join(APP_DIR, "src", "com", "dali", "aoe3assistant", "MainActivity.java")

    run_cmd(
        [
            JAVAC,
            "--release",
            "8",
            "-encoding",
            "UTF-8",
            "-cp",
            ANDROID_JAR,
            "-d",
            classes_dir,
            r_java,
            main_java,
        ],
        "Compile Java sources with javac",
    )

    # 6. Convert compiled .class files to classes.dex using D8 (from r8.jar)
    dex_dir = os.path.join(BUILD_DIR, "dex")
    if os.path.exists(dex_dir):
        shutil.rmtree(dex_dir)
    os.makedirs(dex_dir, exist_ok=True)

    class_files = []
    for root, _, files in os.walk(classes_dir):
        for fn in files:
            if fn.endswith(".class"):
                class_files.append(os.path.join(root, fn))

    run_cmd(
        [
            JAVA,
            "-cp",
            R8_JAR,
            "com.android.tools.r8.D8",
            "--min-api",
            "26",
            "--lib",
            ANDROID_JAR,
            "--output",
            dex_dir,
        ]
        + class_files,
        "Compile Dalvik bytecode (classes.dex) with D8",
    )

    classes_dex = os.path.join(dex_dir, "classes.dex")
    assert os.path.isfile(classes_dex), "classes.dex was not generated!"

    # 7. Merge classes.dex into APK and 4-byte zipalign uncompressed entries
    unsigned_aligned_apk = os.path.join(BUILD_DIR, "unsigned_aligned.apk")
    zipalign_apk(base_res_apk, classes_dex, unsigned_aligned_apk)

    # 8. Sign APK (V1+V2+V3) and verify with ApkVerifier
    dist_apk = os.path.join(DIST_DIR, "AoE3Assistant.apk")
    sign_and_verify_apk(unsigned_aligned_apk, dist_apk)

    # 9. Verify badging with AAPT2
    badging = run_cmd([AAPT2, "dump", "badging", dist_apk], "Verify APK badging with AAPT2")
    print(badging.stdout.strip())

    # 10. Copy to server/releases/AoE3Assistant.apk if server/releases exists
    if os.path.isdir(os.path.join(ROOT_DIR, "server")):
        os.makedirs(SERVER_RELEASES_DIR, exist_ok=True)
        rel_apk = os.path.join(SERVER_RELEASES_DIR, "AoE3Assistant.apk")
        shutil.copy2(dist_apk, rel_apk)
        print(f"[+] Mirrored signed APK to: {rel_apk}")

    # 11. Clean intermediate build directory
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    print(f"\n[SUCCESS] Built and verified signed Android APK: {dist_apk} ({os.path.getsize(dist_apk)} bytes)")


if __name__ == "__main__":
    main()
