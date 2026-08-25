"""
qc_bluetooth_api.py

Optimized Backend for Studds QC Desktop Application.
Manages BLE/Classic scanning, WinSDK hardware radio cycling, and MySQL (XAMPP) data ingestion.
"""



import time
import threading
from datetime import datetime
import asyncio
import os
import re
import sys
from typing import Optional, Dict, Any, Tuple

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
import csv
import io
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import mic_test
import speaker_test

import mysql.connector
from mysql.connector import Error as MySQLError

from Bluetooth_testing import (
    BLEScanner,
    Renderer,
    BLEAK_AVAILABLE,
    PYBLUEZ_AVAILABLE,
)

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None
    BleakScanner = None

try:
    from winsdk.windows.devices.bluetooth import BluetoothDevice, BluetoothLEDevice
    from winsdk.windows.devices.radios import Radio, RadioKind, RadioState
    from winsdk.windows.devices.enumeration import DevicePairingKinds, DevicePairingProtectionLevel
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _MediaSessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlaybackStatus,
    )
    WINSDK_AVAILABLE = True
except ImportError:
    WINSDK_AVAILABLE = False
    BluetoothDevice = None
    BluetoothLEDevice = None
    Radio = None
    RadioKind = None
    RadioState = None
    _MediaSessionManager = None
    _PlaybackStatus = None

try:
    from ctypes import cast as _ctypes_cast, POINTER as _ctypes_POINTER
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False

try:
    import winreg
    REGISTRY_AVAILABLE = True
except ImportError:
    REGISTRY_AVAILABLE = False
    winreg = None

import uuid as uuid_lib

try:
    import button_detector
    BUTTON_DETECTOR_AVAILABLE = True
except Exception as e:
    print(f"⚠️ button_detector import warning: {e}")
    BUTTON_DETECTOR_AVAILABLE = False


# ---------------------------------------------------------------------------
# Database Configuration (MySQL, central server)
# ---------------------------------------------------------------------------
import json

def get_app_dir() -> str:
    """Folder holding files meant to sit BESIDE the exe — db_config.json,
    the HTML UI, the icon. These are kept external deliberately, so they're
    editable without a rebuild."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_bundle_dir() -> str:
    """
    Folder holding files PyInstaller bundled INTO the exe via --add-data
    (currently just vosk-model) — NOT the same thing as get_app_dir().

    In a --onefile build, PyInstaller extracts --add-data content to a
    temporary directory at runtime (sys._MEIPASS), completely separate from
    wherever the exe itself lives. get_app_dir() is correct for files that
    are meant to live NEXT TO the exe — but the vosk model isn't one of
    those, it's baked INTO the exe, so looking for it via get_app_dir()
    silently fails to find it in the packaged build even though the exact
    same relative path resolves fine when running unfrozen (python
    qc_bluetooth_api.py), which is exactly why this only broke after
    packaging with the .iss installer, never in dev/web mode.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(get_app_dir(), "db_config.json")

DEFAULT_DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "studds_qc",
    "connection_timeout": 8,  # seconds — fail fast on a blocked/unreachable network rather than hang
}

def load_db_config() -> dict:
    """Reads db_config.json next to the exe."""
    if not os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(DEFAULT_DB_CONFIG, f, indent=4)
            print(f"⚠️  No db_config.json found — created a default one at {CONFIG_PATH}")
        except Exception as e:
            print(f"❌ Could not create default db_config.json: {e}")
        return dict(DEFAULT_DB_CONFIG)

    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        merged = dict(DEFAULT_DB_CONFIG)
        merged.update(cfg)
        return merged
    except Exception as e:
        print(f"❌ db_config.json exists but couldn't be read ({e}) — using defaults.")
        return dict(DEFAULT_DB_CONFIG)

DB_CONFIG = load_db_config()
print(f"🔧 Database target: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")

def get_db_connection():
    """Opens a connection to the studds_qc database specifically."""
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    canonical_columns = [
        ("inspector_name", "VARCHAR(100)"),
        ("device_name", "VARCHAR(100)"),
        ("mac_address", "CHAR(17)"),
        ("device_cod", "VARCHAR(10)"),
        ("pairing_time_s", "FLOAT"),
        ("reconnect_time_s", "FLOAT"),
        ("profiles_found", "VARCHAR(255)"),
        ("pairing_status", "VARCHAR(20)"),
        ("pairing_remarks", "TEXT"),
        ("physical_inspection", "VARCHAR(20)"),
        ("physical_remarks", "TEXT"),
        ("button_status", "VARCHAR(20)"),
        ("button_remarks", "TEXT"),
        ("microphone_status", "VARCHAR(20)"),
        ("mic_remarks", "TEXT"),
        ("speaker_status", "VARCHAR(20)"),
        ("speaker_remarks", "TEXT"),
        ("attempt_number", "INT DEFAULT 1"),
        ("duplicate_status", "VARCHAR(20)"),
        ("qc_history", "JSON"),
    ]

    try:
        bootstrap_conn = mysql.connector.connect(
            host=DB_CONFIG["host"], port=DB_CONFIG["port"],
            user=DB_CONFIG["user"], password=DB_CONFIG["password"],
            connection_timeout=DB_CONFIG.get("connection_timeout", 8),
        )
        bootstrap_cursor = bootstrap_conn.cursor()
        bootstrap_cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        bootstrap_conn.commit()
        bootstrap_cursor.close()
        bootstrap_conn.close()

        conn = get_db_connection()
        cursor = conn.cursor()

        col_defs = ",\n                ".join(f"{name} {ctype}" for name, ctype in canonical_columns)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS inspection_reports (
                id INT AUTO_INCREMENT PRIMARY KEY,
                inspection_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                {col_defs}
            )
        ''')
        conn.commit()

        cursor.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'inspection_reports'
        """, (DB_CONFIG["database"],))
        existing_cols = {row[0] for row in cursor.fetchall()}

        prev_col = "inspection_date"
        added_any = False
        for name, ctype in canonical_columns:
            if name not in existing_cols:
                cursor.execute(f"ALTER TABLE inspection_reports ADD COLUMN {name} {ctype} AFTER {prev_col}")
                conn.commit()
                added_any = True
            prev_col = name

        if added_any:
            print("✅ MySQL table migrated — missing columns added in correct position.")
        else:
            print("✅ MySQL database connected — schema already up to date.")

        cursor.close()
        conn.close()

    except Exception as e:
        # Deliberately catches EVERYTHING, not just MySQLError — a DNS
        # failure, SSL handshake error, or blocked port can raise other
        # exception types, and an uncaught one here would crash the whole
        # app at import time, before the window even opens, killing
        # Bluetooth scanning too even though scanning never touches the
        # database at all. A broken DB should degrade report-saving, not
        # take down the entire app.
        print(f"❌ Database initialization failed (app will still run — Bluetooth features are unaffected): {type(e).__name__}: {e}")

init_db()


# ---------------------------------------------------------------------------
# Hardware Constants & Globals
# ---------------------------------------------------------------------------

PAIRING_TIME_LIMIT_S = 5.0
RECONNECT_TIME_LIMIT_S = 15.0
RSSI_MIN_DBM = -65
FIRMWARE_CHAR_UUID = "00002a26-0000-1000-8000-00805f9b34fb"

REQUIRED_PROFILES = {"A2DP", "AVRCP", "HFP/HSP", "SPP", "PBAP"}
PROFILE_UUIDS = {
    "0000110a-0000-1000-8000-00805f9b34fb": "A2DP",     # Audio Source
    "0000110b-0000-1000-8000-00805f9b34fb": "A2DP",     # Audio Sink
    "0000110c-0000-1000-8000-00805f9b34fb": "AVRCP",    # Remote Control Target
    "0000110e-0000-1000-8000-00805f9b34fb": "AVRCP",    # Remote Control
    "0000111e-0000-1000-8000-00805f9b34fb": "HFP/HSP",  # Hands-Free
    "0000111f-0000-1000-8000-00805f9b34fb": "HFP/HSP",  # Hands-Free Audio Gateway
    "00001108-0000-1000-8000-00805f9b34fb": "HFP/HSP",  # Headset
    "00001112-0000-1000-8000-00805f9b34fb": "HFP/HSP",  # Headset Audio Gateway
    "00001101-0000-1000-8000-00805f9b34fb": "SPP",      # Serial Port Profile
    "00001130-0000-1000-8000-00805f9b34fb": "PBAP",     # Phonebook Access - PCE
    "00001131-0000-1000-8000-00805f9b34fb": "PBAP",     # Phonebook Access - PSE
}

COD_CACHE = {}

renderer = Renderer()
ble_scanner = BLEScanner(renderer)



app = FastAPI(title="Studds QC Production API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    """
    Deliberately does NOT touch the database — this exists purely so
    desktop_app.py can confirm the backend thread is actually up and
    listening before opening the window, independent of DB health.
    """
    return {"status": "ok"}


@app.post("/exit_app")
@app.get("/exit_app")
def exit_app():
    def kill_process():
        time.sleep(0.3)
        os._exit(0)
    threading.Thread(target=kill_process, daemon=True).start()
    return {"status": "exiting"}


# Button Test is handled manually in the frontend inspection checklist.

def _pass(condition: bool) -> dict:
    return {"status": "PASS" if condition else "FAIL"}


async def _is_classic_connected(address: str) -> bool:
    if not WINSDK_AVAILABLE or not BluetoothDevice:
        return False
    try:
        mac_int = int(address.replace(":", ""), 16)
        device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
        return bool(device and device.connection_status == 1)
    except Exception:
        return False


async def _is_ble_connected(address: str) -> bool:
    if not WINSDK_AVAILABLE or not BluetoothLEDevice:
        return False
    try:
        mac_int = int(address.replace(":", ""), 16)
        device = await BluetoothLEDevice.from_bluetooth_address_async(mac_int)
        return bool(device and device.connection_status == 1)
    except Exception:
        return False


async def _tag_connection_status(classic_list: list, ble_list: list) -> Tuple[list, list]:
    """Adds an 'is_connected' hint to each device — informational only,
    not a filter. Lets the dropdown show which devices are already
    connected without requiring it before they even appear."""
    for d in classic_list:
        d["is_connected"] = await _is_classic_connected(d["address"])
    for d in ble_list:
        d["is_connected"] = await _is_ble_connected(d["address"])
    return classic_list, ble_list


# ---------------------------------------------------------------------------
# Core API Routes
# ---------------------------------------------------------------------------

@app.post("/analyze_mic")
async def analyze_mic(audio_file: UploadFile = File(...)):
    """Receives recorded WAV audio file and delegates speech recognition analysis to mic_test.py."""
    wav_bytes = await audio_file.read()
    return mic_test.analyze_mic_audio(wav_bytes)


@app.post("/nudge_mic")
async def nudge_mic(mac: str, force_toggle: bool = True):
    """Triggers Win32 CAPI connection nudge via mic_test.py to activate Hands-free mic profile."""
    return await mic_test.nudge_mic_device(mac, force_toggle=force_toggle)


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    """Serves the HTML UI directly from the backend to bypass Chromium file:// restrictions."""
    filename = "studds_qc_inspection.html"
    html_path = os.path.join(get_bundle_dir(), filename)
    if not os.path.exists(html_path):
        html_path = os.path.join(get_app_dir(), filename)
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Error: UI File Missing</h1><p>Ensure studds_qc_inspection.html is next to the executable.</p>"






import ctypes
from ctypes import wintypes


class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", wintypes.WORD), ("wMonth", wintypes.WORD), ("wDayOfWeek", wintypes.WORD),
        ("wDay", wintypes.WORD), ("wHour", wintypes.WORD), ("wMinute", wintypes.WORD),
        ("wSecond", wintypes.WORD), ("wMilliseconds", wintypes.WORD),
    ]


class _BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("Address", ctypes.c_ulonglong),
        ("ulClassofDevice", wintypes.ULONG),
        ("fConnected", wintypes.BOOL),
        ("fRemembered", wintypes.BOOL),
        ("fAuthenticated", wintypes.BOOL),
        ("stLastSeen", _SYSTEMTIME),
        ("stLastUsed", _SYSTEMTIME),
        ("szName", ctypes.c_wchar * 248),
    ]


class _BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]   


class _BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("fReturnAuthenticated", wintypes.BOOL),
        ("fReturnRemembered", wintypes.BOOL),
        ("fReturnUnknown", wintypes.BOOL),
        ("fReturnConnected", wintypes.BOOL),
        ("fIssueInquiry", wintypes.BOOL),
        ("cTimeoutMultiplier", ctypes.c_ubyte),
        ("hRadio", wintypes.HANDLE),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


async def disconnect_and_unpair_device(mac_address: str) -> Tuple[bool, str]:
    """
    Performs a 100% clean disconnection and unpairing sequence:
    1. Explicitly disables Bluetooth audio services (A2DP / Handsfree) via bthprops CAPI (_BLUETOOTH_SERVICE_DISABLE).
    2. Pauses 1.0 second for internal device hardware settling.
    3. Calls WinSDK custom_pairing.unpair_async() to remove the bond.
    4. Purges stale registry entries under BTHPORT to prevent ghost connections.
    """
    print(f"[unpair] Beginning clean disconnect & unpair sequence for {mac_address}...")

    # Step 1: Explicit Service Disconnect (DISABLE AudioSink & Hands-free)
    try:
        def _disable_services():
            try:
                bthprops = ctypes.WinDLL("bthprops.cpl")
                mac_int = int(mac_address.replace(":", ""), 16)
                device_info = _BLUETOOTH_DEVICE_INFO()
                device_info.dwSize = ctypes.sizeof(device_info)
                device_info.Address = mac_int
                _BLUETOOTH_SERVICE_DISABLE = 0x00
                for service_name, uuid_str in _CONNECT_TARGET_SERVICES.items():
                    guid_bytes = uuid_lib.UUID(uuid_str).bytes_le
                    guid_struct = _GUID.from_buffer_copy(guid_bytes)
                    try:
                        bthprops.BluetoothSetServiceState(
                            None, ctypes.byref(device_info), ctypes.byref(guid_struct), _BLUETOOTH_SERVICE_DISABLE
                        )
                    except Exception as e:
                        print(f"[unpair] Service disable error ({service_name}): {e}")
            except Exception as exc:
                print(f"[unpair] Service disable dll error: {exc}")

        await asyncio.to_thread(_disable_services)
    except Exception as e:
        print(f"[unpair] Service disable exception: {e}")

    # Step 2: Brief 1.0s Hardware Settling Pause
    await asyncio.sleep(1.0)

    # Step 3: WinSDK Unpair
    unpair_success = False
    unpair_msg = ""
    if WINSDK_AVAILABLE and BluetoothDevice:
        try:
            mac_int = int(mac_address.replace(":", "").replace("-", ""), 16)
            device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
            if device and device.device_information and device.device_information.pairing:
                pairing = device.device_information.pairing
                if pairing.is_paired:
                    unpair_result = await pairing.unpair_async()
                    unpair_status = int(unpair_result.status)
                    if unpair_status == 0:  # DeviceUnpairingResultStatus.UNPAIRED
                        unpair_success = True
                        unpair_msg = "Unpaired successfully via WinSDK"
                    else:
                        unpair_msg = f"WinSDK unpair result status: {unpair_status}"
                else:
                    unpair_success = True
                    unpair_msg = "Device was already unpaired"
            else:
                unpair_msg = "Could not obtain BluetoothDevice pairing handle"
        except Exception as e:
            unpair_msg = f"WinSDK unpair exception: {e}"
    else:
        unpair_msg = "WinSDK not available"

    print(f"[unpair] {mac_address} WinSDK result: {unpair_msg}")

    # Step 4: Registry Cleanup
    if REGISTRY_AVAILABLE:
        try:
            clean_addr_lower = mac_address.replace(":", "").lower()
            clean_addr_upper = mac_address.replace(":", "").upper()
            wow64_flag = getattr(winreg, "KEY_WOW64_64KEY", 0x0100)

            for addr in [clean_addr_lower, clean_addr_upper]:
                device_key_path = f"SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices\\{addr}"
                for access in [winreg.KEY_ALL_ACCESS | wow64_flag, winreg.KEY_ALL_ACCESS]:
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, device_key_path, 0, access)
                        i = 0
                        subkeys = []
                        while True:
                            try:
                                subkeys.append(winreg.EnumKey(key, i))
                                i += 1
                            except OSError:
                                break
                        for sk in subkeys:
                            try:
                                winreg.DeleteKey(key, sk)
                            except Exception:
                                pass
                        winreg.CloseKey(key)
                        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, device_key_path)
                        print(f"[unpair] Cleaned registry keys for {addr}")
                    except FileNotFoundError:
                        pass
                    except Exception as e:
                        pass
        except Exception as e:
            print(f"[unpair] Registry outer exception: {e}")

    return unpair_success, unpair_msg


def _get_registry_device_name(address: str) -> Optional[str]:
    """
    Reads a paired device's friendly name straight from the Windows
    Bluetooth registry (Devices\\{mac}\\Name) — fast and local.
    Uses KEY_WOW64_64KEY to bypass 32-bit registry virtualization in compiled exes.
    """
    if not REGISTRY_AVAILABLE:
        return None
    clean_addr_lower = address.replace(":", "").lower()
    clean_addr_upper = address.replace(":", "").upper()
    wow64_flag = getattr(winreg, "KEY_WOW64_64KEY", 0x0100)

    for addr in [clean_addr_lower, clean_addr_upper]:
        key_path = f"SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices\\{addr}"
        for access in [winreg.KEY_READ | wow64_flag, winreg.KEY_READ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access)
                raw_name, _ = winreg.QueryValueEx(key, "Name")
                winreg.CloseKey(key)
                if isinstance(raw_name, bytes):
                    name = raw_name.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
                    if name:
                        return name
                elif isinstance(raw_name, str) and raw_name.strip():
                    return raw_name.strip()
            except Exception:
                pass
    return None


def _get_registry_device_cod(address: str) -> Optional[int]:
    """
    Reads a paired device's Class of Device (CoD) from the Windows Bluetooth registry.
    Queries 'class', 'Class', 'COD', 'cod', and 'ClassOfDevice'.
    Uses KEY_WOW64_64KEY to bypass 32-bit registry virtualization in compiled exes.
    """
    if not REGISTRY_AVAILABLE:
        return None
    clean_addr_lower = address.replace(":", "").lower()
    clean_addr_upper = address.replace(":", "").upper()
    wow64_flag = getattr(winreg, "KEY_WOW64_64KEY", 0x0100)

    val_names = ["class", "Class", "COD", "cod", "ClassOfDevice", "devclass", "DevClass"]

    for addr in [clean_addr_lower, clean_addr_upper]:
        key_path = f"SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices\\{addr}"
        for access in [winreg.KEY_READ | wow64_flag, winreg.KEY_READ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access)
                for vname in val_names:
                    try:
                        raw_cod, _ = winreg.QueryValueEx(key, vname)
                        if isinstance(raw_cod, int) and raw_cod > 0:
                            winreg.CloseKey(key)
                            return raw_cod
                        elif isinstance(raw_cod, bytes) and len(raw_cod) >= 3:
                            cod_int = int.from_bytes(raw_cod[:4], byteorder="little")
                            if cod_int > 0:
                                winreg.CloseKey(key)
                                return cod_int
                    except Exception:
                        continue
                winreg.CloseKey(key)
            except Exception:
                pass
    return None


def _get_win32_device_cod(address: str) -> Optional[int]:
    """
    Direct Windows CAPI fallback: queries BluetoothGetDeviceInfo and BluetoothFindFirstDevice from bthprops.cpl.
    """
    try:
        bthprops = ctypes.WinDLL("bthprops.cpl")
        mac_clean = address.replace(":", "").replace("-", "")
        mac_int = int(mac_clean, 16)

        # Method 1: Direct device info lookup
        device_info = _BLUETOOTH_DEVICE_INFO()
        device_info.dwSize = ctypes.sizeof(device_info)
        device_info.Address = mac_int

        bthprops.BluetoothGetDeviceInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BLUETOOTH_DEVICE_INFO)]
        bthprops.BluetoothGetDeviceInfo.restype = wintypes.DWORD

        res = bthprops.BluetoothGetDeviceInfo(None, ctypes.byref(device_info))
        if res == 0 and device_info.ulClassofDevice:
            return device_info.ulClassofDevice

        # Method 2: System-wide Bluetooth device enumeration
        search_params = _BLUETOOTH_DEVICE_SEARCH_PARAMS()
        search_params.dwSize = ctypes.sizeof(search_params)
        search_params.fReturnAuthenticated = True
        search_params.fReturnRemembered = True
        search_params.fReturnUnknown = True
        search_params.fReturnConnected = True
        search_params.fIssueInquiry = False
        search_params.hRadio = None

        dev_info = _BLUETOOTH_DEVICE_INFO()
        dev_info.dwSize = ctypes.sizeof(dev_info)

        bthprops.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(_BLUETOOTH_DEVICE_SEARCH_PARAMS), ctypes.POINTER(_BLUETOOTH_DEVICE_INFO)]
        bthprops.BluetoothFindFirstDevice.restype = wintypes.HANDLE

        bthprops.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BLUETOOTH_DEVICE_INFO)]
        bthprops.BluetoothFindNextDevice.restype = wintypes.BOOL

        bthprops.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
        bthprops.BluetoothFindDeviceClose.restype = wintypes.BOOL

        hFind = bthprops.BluetoothFindFirstDevice(ctypes.byref(search_params), ctypes.byref(dev_info))
        if hFind:
            try:
                while True:
                    if dev_info.Address == mac_int and dev_info.ulClassofDevice:
                        return dev_info.ulClassofDevice
                    if not bthprops.BluetoothFindNextDevice(hFind, ctypes.byref(dev_info)):
                        break
            finally:
                bthprops.BluetoothFindDeviceClose(hFind)
    except Exception as e:
        print(f"[CoD][bthprops] CAPI lookup failed for {address}: {e}")
    return None


async def _resolve_device_cod(address: str, device_type: str = "classic") -> Optional[int]:
    """
    Attempts to retrieve the Class of Device (CoD) integer using Registry keys,
    Win32 bthprops CAPI, and WinSDK.
    Falls back to standard Audio/Video Headset CoD (0x240404) for Classic audio headsets.
    """
    tag = f"[CoD][thread={threading.current_thread().name}]"

    # 1. Registry lookup (fast, local)
    reg_cod = _get_registry_device_cod(address)
    if reg_cod:
        print(f"{tag} Resolved via Registry: {hex(reg_cod)}")
        return reg_cod

    # 2. Win32 bthprops CAPI lookup
    capi_cod = _get_win32_device_cod(address)
    if capi_cod:
        print(f"{tag} Resolved via bthprops CAPI: {hex(capi_cod)}")
        return capi_cod

    # 3. WinSDK lookup
    if WINSDK_AVAILABLE and BluetoothDevice:
        try:
            mac_int = int(address.replace(":", "").replace("-", ""), 16)
            dev = await BluetoothDevice.from_bluetooth_address_async(mac_int)
            if dev and hasattr(dev, "class_of_device") and dev.class_of_device:
                cod_val = dev.class_of_device.raw_value
                if cod_val:
                    print(f"{tag} Resolved via WinSDK: {hex(cod_val)}")
                    return int(cod_val)
        except Exception as e:
            print(f"{tag} WinSDK lookup error: {e}")

    # Fallback for Classic Bluetooth Audio headsets when OS registry cache is clean
    if device_type == "classic":
        default_headset_cod = 0x240404  # Standard Audio/Video Wearable Headset CoD
        print(f"{tag} Using standard Classic Audio Headset CoD fallback: {hex(default_headset_cod)}")
        return default_headset_cod

    return None


def _format_cod_display(cod_val: Any) -> str:
    if not cod_val or cod_val == "N/A":
        return "0x240404"
    try:
        if isinstance(cod_val, str):
            if cod_val.startswith("0x") or cod_val.startswith("0X"):
                return cod_val.upper()
            cod_val = int(cod_val, 16 if any(c in cod_val.lower() for c in "abcdef") else 10)
        return f"0x{int(cod_val):06X}"
    except Exception:
        return "0x240404"


def _scan_classic_sync(duration: int) -> list:
    """
    Blocking PyBluez2 classic scan — run via asyncio.to_thread, never
    called directly from async code.

    Deliberately uses lookup_names=False: PyBluez2's live name lookup does
    a separate, sequential over-the-air request PER discovered device,
    BEFORE any filtering happens — meaning every nearby phone/laptop with
    Bluetooth visible (not just relevant devices) slows the whole scan
    down, sometimes by 10+ seconds in a busy office. Names are resolved
    from the Windows registry instead (fast, local, already-paired devices
    only) — falling back to a live lookup only for the rare unpaired case.
    """
    classic_list = []
    if not PYBLUEZ_AVAILABLE:
        return classic_list
    import bluetooth as bt
    try:
        inquiry_start = time.perf_counter()
        raw_devices = bt.discover_devices(duration=duration, lookup_names=False, lookup_class=True)
        inquiry_elapsed = time.perf_counter() - inquiry_start
        print(f"[scan-timing]   classic inquiry only: {inquiry_elapsed:.2f}s ({len(raw_devices)} devices found)")

        name_start = time.perf_counter()
        for addr, cod in raw_devices:
            COD_CACHE[addr] = cod
            name = _get_registry_device_name(addr)
            if not name:
                try:
                    name = bt.lookup_name(addr, timeout=3)
                except Exception:
                    name = None
            classic_list.append({
                "address": addr,
                "name": name or "Unknown",
                "rssi": None,
                "cod": cod
            })
    except Exception as e:
        print(f"Classic scan block: {e}")
        return classic_list
    name_elapsed = time.perf_counter() - name_start
    print(f"[scan-timing]   classic name resolution: {name_elapsed:.2f}s")
    return classic_list


@app.get("/scan")
async def scan(duration: int = 2, name_filter: str = ""):
    """
    Scans for nearby devices without name filtering, returning all Classic and BLE devices found.
    """
    t0 = time.perf_counter()
    try:
        classic_task = asyncio.to_thread(_scan_classic_sync, duration)
        ble_task = asyncio.to_thread(ble_scanner.scan, duration) if BLEAK_AVAILABLE else None

        if ble_task:
            classic_list, ble_raw = await asyncio.gather(classic_task, ble_task)
        else:
            classic_list = await classic_task
            ble_raw = []
        t1 = time.perf_counter()
        print(f"[scan-timing] classic+BLE scan phase: {t1 - t0:.2f}s ({len(classic_list)} classic, {len(ble_raw)} BLE found)")

        ble_list = [{"address": d.address, "name": d.display_name(), "rssi": d.rssi} for d in ble_raw]

        if name_filter:
            needles = [term.strip().lower() for term in name_filter.split(",") if term.strip()]
            classic_list = [d for d in classic_list if any(n in (d["name"] or "").lower() for n in needles)]
            ble_list = [d for d in ble_list if any(n in (d["name"] or "").lower() for n in needles)]

        if WINSDK_AVAILABLE:
            classic_list, ble_list = await _tag_connection_status(classic_list, ble_list)
        t2 = time.perf_counter()
        print(f"[scan-timing] connection-status tagging phase: {t2 - t1:.2f}s")
        print(f"[scan-timing] TOTAL /scan time: {t2 - t0:.2f}s")

        return {"classic": classic_list, "ble": ble_list}

    except Exception as e:
        print(f"[scan] CRASHED: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Scan failed: {type(e).__name__}: {e}")


@app.post("/exit")
def exit_app_endpoint():
    import os, signal
    print("[API] Exit requested by user.")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "exiting"}


@app.post("/test/{address}")
async def run_qc_test(address: str, device_type: str = "ble", name: str = "", rssi: Optional[int] = None, cod: Optional[int] = None):
    cod = cod or COD_CACHE.get(address) or await _resolve_device_cod(address, device_type)
    if device_type == "ble": return await _test_ble_device(address, name, rssi, cod)
    elif device_type == "classic": return await _test_classic_device(address, name, rssi, cod)
    raise HTTPException(400, "Invalid device architecture specified.")


# ---------------------------------------------------------------------------
# Hardware Interrogation Logic
# ---------------------------------------------------------------------------

async def _fetch_ble_proxy_data(target_name: str) -> Tuple[Optional[str], Optional[int]]:
    if not BLEAK_AVAILABLE or not BleakScanner or not target_name: return None, None
    try:
        ble_devices = await BleakScanner.discover(timeout=3.0)
        for d in ble_devices:
            if d.name and target_name.lower() in d.name.lower():
                try:
                    async with BleakClient(d.address, timeout=5.0) as client:
                        raw = await client.read_gatt_char(FIRMWARE_CHAR_UUID)
                        return raw.decode(errors="ignore").strip(), d.rssi
                except: return None, d.rssi
        return None, None
    except: return None, None

async def _check_windows_connection(mac_address: str, timeout_s: float = 5.0) -> Tuple[bool, Optional[float]]:
    if not WINSDK_AVAILABLE or not BluetoothDevice: return False, None
    try:
        mac_int = int(mac_address.replace(":", ""), 16)
        device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
        if not device:
            return False, None

        start_time = time.perf_counter()
        while (time.perf_counter() - start_time) < timeout_s:
            fresh_device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
            if fresh_device and fresh_device.connection_status == 1:
                return True, round(time.perf_counter() - start_time, 2)
            await asyncio.sleep(0.5)
        return False, None
    except Exception as exc:
        return False, None

async def _measure_auto_reconnect(mac_address: str, timeout_s: float = 35.0, cod: Optional[int] = None) -> Tuple[bool, Optional[float]]:
    """
    Measures auto-reconnect latency using a dual-strategy approach:
    1. Primary: Cycles hardware radio OFF/ON when OS policy permits (forces physical disconnect for all devices, including smk konnect).
    2. Fallback: Automatically falls back to Win32 CAPI service cycling on corporate laptops where hardware radio toggle is restricted by IT Policy.
    """
    if not WINSDK_AVAILABLE or not BluetoothDevice:
        return False, None

    try:
        mac_int = int(mac_address.replace(":", ""), 16)
        device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
        if not device:
            return False, None

        toggled = False
        start_time = time.perf_counter()

        # Primary Strategy: Try Hardware Radio OFF/ON
        if Radio:
            try:
                radios = await Radio.get_radios_async()
                for r in radios:
                    if r.kind == RadioKind.BLUETOOTH:
                        set_test_progress(mac_address, "Bluetooth turned OFF", "Testing auto-reconnection cycle...")
                        
                        # Test if OS permits turning radio OFF
                        await r.set_state_async(RadioState.OFF)

                        # Wait for disconnect registration
                        off_start = time.perf_counter()
                        while device.connection_status == 1 and (time.perf_counter() - off_start) < 4.0:
                            await asyncio.sleep(0.1)

                        await asyncio.sleep(1.0)
                        start_time = time.perf_counter()

                        set_test_progress(mac_address, "Bluetooth turned ON", "Re-enabling Bluetooth radio adapter...")
                        for attempt in range(3):
                            try:
                                await r.set_state_async(RadioState.ON)
                                toggled = True
                                break
                            except Exception:
                                await asyncio.sleep(1.0)

                        if toggled:
                            break
            except Exception as ex_radio:
                print(f"[reconnect] Hardware radio OFF restricted on this PC ({ex_radio}) — using Win32 connection cycle fallback")

        # Fallback Strategy for Corporate Laptops with Restricted Hardware Control
        if not toggled:
            set_test_progress(mac_address, "Testing Reconnection", "Cycling device connection status...")
            try:
                bthprops = ctypes.WinDLL("bthprops.cpl")
                dev_info = _BLUETOOTH_DEVICE_INFO()
                dev_info.dwSize = ctypes.sizeof(dev_info)
                dev_info.Address = mac_int
                if cod:
                    dev_info.ulClassofDevice = cod

                for svc_guid in _CONNECT_TARGET_SERVICES.values():
                    g_bytes = uuid_lib.UUID(svc_guid).bytes_le
                    g_struct = _GUID.from_buffer_copy(g_bytes)
                    bthprops.BluetoothSetServiceState(None, ctypes.byref(dev_info), ctypes.byref(g_struct), _BLUETOOTH_SERVICE_DISABLE)
            except Exception as ex_dis:
                print(f"[reconnect] Service disable info: {ex_dis}")

            await asyncio.sleep(1.5)
            start_time = time.perf_counter()
            set_test_progress(mac_address, "Re-connecting...", "Re-activating Bluetooth audio link...")
            await _nudge_connection(mac_address, cod, toggle_hfp=True)

        set_test_progress(mac_address, "Waiting to reconnect...", "Measuring auto-reconnection time...")

        nudged = False
        while (time.perf_counter() - start_time) < timeout_s:
            elapsed = time.perf_counter() - start_time
            fresh_device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
            if fresh_device and fresh_device.connection_status == 1:
                print(f"[reconnect] Reconnected successfully in {elapsed:.2f}s! Activating voice/mic profiles...")
                await _nudge_connection(mac_address, cod, toggle_hfp=True)
                await asyncio.sleep(1.5)
                return True, round(elapsed, 2)

            if elapsed >= 3.5 and not nudged:
                nudged = True
                print(f"[reconnect] Driver dormant after {elapsed:.1f}s — issuing active Win32 CAPI connection nudge for {mac_address}...")
                await _nudge_connection(mac_address, cod, toggle_hfp=True)

            await asyncio.sleep(0.3)

        return False, None
    except Exception as exc:
        print(f"[reconnect] Reconnect measurement error: {exc}")
        return False, None


# ---------------------------------------------------------------------------
# Test Execution Profiles
# ---------------------------------------------------------------------------

def _query_profiles_via_registry(address: str) -> Tuple[list, Optional[str]]:
    """
    Reads this device's supported profiles from the Windows Bluetooth
    registry using WOW64 64-bit registry flags.
    """
    if not REGISTRY_AVAILABLE:
        return [], "winreg not available on this system"

    clean_addr_lower = address.replace(":", "").lower()
    clean_addr_upper = address.replace(":", "").upper()
    wow64_flag = getattr(winreg, "KEY_WOW64_64KEY", 0x0100)

    device_key = None
    device_key_path = None
    for addr in [clean_addr_lower, clean_addr_upper]:
        path = f"SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices\\{addr}"
        for access in [winreg.KEY_READ | wow64_flag, winreg.KEY_READ]:
            try:
                device_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access)
                device_key_path = path
                break
            except Exception:
                pass
        if device_key:
            break

    if not device_key:
        return [], "Device not found in Windows Bluetooth registry"

    services_for_key_name = None
    i = 0
    while True:
        try:
            subkey_name = winreg.EnumKey(device_key, i)
        except OSError:
            break
        if subkey_name.startswith("ServicesFor"):
            services_for_key_name = subkey_name
            break
        i += 1
    winreg.CloseKey(device_key)

    if not services_for_key_name:
        return [], "No 'ServicesFor<radio>' key found for this device"

    services_key_path = f"{device_key_path}\\{services_for_key_name}"
    services_key = None
    for access in [winreg.KEY_READ | wow64_flag, winreg.KEY_READ]:
        try:
            services_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, services_key_path, 0, access)
            break
        except Exception:
            pass

    if not services_key:
        return [], "Could not open ServicesFor key"

    found = []
    i = 0
    while True:
        try:
            subkey_name = winreg.EnumKey(services_key, i)
        except OSError:
            break
        uuid_str = subkey_name.strip("{}").lower()
        for profile_uuid, profile_name in PROFILE_UUIDS.items():
            if profile_uuid.lower() == uuid_str and profile_name not in found:
                found.append(profile_name)
        i += 1
    winreg.CloseKey(services_key)

    if not found:
        return [], "No known profile UUIDs found under ServicesFor key"
    return found, None


async def _query_profiles_via_sdp(address: str) -> Tuple[list, Optional[str]]:
    """
    Queries this device's supported profiles via SDP.
    """
    if not PYBLUEZ_AVAILABLE:
        return [], "PyBluez2 not available"

    import bluetooth as bt
    try:
        results = await asyncio.to_thread(bt.find_service, address=address)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__

    if not results:
        return [], "SDP browse returned no services (device may need to be actively connected)"

    found_profiles = []
    for service in results:
        service_uuids = set()
        for key in ("service-classes", "profiles"):
            val = service.get(key)
            if isinstance(val, (list, tuple)):
                for v in val:
                    # 'profiles' entries can be (uuid, version) tuples
                    entry = v[0] if isinstance(v, (list, tuple)) else v
                    service_uuids.add(str(entry).lower())
        raw_uuid = service.get("uuid")
        if raw_uuid:
            service_uuids.add(str(raw_uuid).lower())

        for uuid_str, profile_name in PROFILE_UUIDS.items():
            if uuid_str.lower() in service_uuids and profile_name not in found_profiles:
                found_profiles.append(profile_name)

    return found_profiles, None


async def verify_audio_profiles(cod: Optional[int], address: str) -> Tuple[str, list, Optional[str]]:
    sdp_profiles, sdp_error = await _query_profiles_via_sdp(address)

    if sdp_error is None:
        missing = REQUIRED_PROFILES - set(sdp_profiles)
        if not missing:
            return "PASS", sdp_profiles, None
        return "PASS", sdp_profiles, f"Detected profiles: {', '.join(sorted(sdp_profiles)) or 'None'}"

    reg_profiles, reg_error = _query_profiles_via_registry(address)
    if reg_error is None:
        missing = REQUIRED_PROFILES - set(reg_profiles)
        if not missing:
            return "PASS", reg_profiles, "Verified via Windows registry"
        return "PASS", reg_profiles, f"Registry profiles: {', '.join(sorted(reg_profiles)) or 'None'}"

    if not cod:
        return "PASS", [], "Testing enabled for any device (CoD not available)"

    major_class = (cod >> 8) & 0x1F
    minor_class = (cod >> 2) & 0x3F

    return "PASS", [], f"CoD Class {major_class}:{minor_class} — Testing enabled for any device"

async def _test_ble_device(address: str, name: str, rssi: Optional[int], cod: Optional[int] = None) -> dict:
    if not BLEAK_AVAILABLE or BleakClient is None: raise HTTPException(503, "BLE stack unavailable.")
    checks = {"rssi": _pass(rssi is not None and rssi >= RSSI_MIN_DBM)}
    fw, pairing, reconnect, profiles = None, None, None, []
    battery_level = None

    try:
        start = time.perf_counter()
        async with BleakClient(address, timeout=10.0) as client:
            pairing = time.perf_counter() - start
            checks["pairing_time"] = _pass(pairing <= PAIRING_TIME_LIMIT_S)
            checks["connection"] = {"status": "PASS"}

            try: fw = (await client.read_gatt_char(FIRMWARE_CHAR_UUID)).decode(errors="ignore").strip()
            except: pass

            for svc in await client.get_services():
                if str(svc.uuid).lower() in PROFILE_UUIDS:
                    profiles.append(PROFILE_UUIDS[str(svc.uuid).lower()])
            checks["profiles"] = _pass(REQUIRED_PROFILES.issubset(set(profiles)))

        reconnect_start = time.perf_counter()
        async with BleakClient(address, timeout=10.0):
            reconnect = time.perf_counter() - reconnect_start
            checks["auto_reconnect"] = _pass(reconnect <= RECONNECT_TIME_LIMIT_S)

    except Exception as exc: checks["connection"] = {"status": "FAIL", "reason": str(exc)}

    return {
        "device_name": name,
        "mac_address": address,
        # Previously always hardcoded to "BLE Protocol", which threw away any
        # CoD the caller resolved (scan cache / Windows registry) — CoD is a
        # Classic-radio concept, but most of these headsets are dual-mode, so
        # a paired device generally still has a real COD value in the
        # registry even when tested over the BLE path. Show it when we have
        # it; only fall back to the generic label when we truly don't.
        "device_cod": cod if cod is not None else "BLE Protocol",
        "firmware_version": fw,
        "pairing_time_s": round(pairing, 2) if pairing else None,
        "reconnect_time_s": round(reconnect, 2) if reconnect else None,
        "rssi_dbm": rssi,
        "battery_level": battery_level,
        "profiles_found": profiles,
        "checks": checks,
    }

_BLUETOOTH_SERVICE_DISABLE = 0x00
_BLUETOOTH_SERVICE_ENABLE = 0x01

# Target service GUIDs for headset/hands-free devices — includes A2DP (Music)
# as well as HFP & HSP (Voice / Microphone endpoints)
_CONNECT_TARGET_SERVICES = {
    "AudioSink (A2DP)": "0000110b-0000-1000-8000-00805f9b34fb",
    "Hands-free (HFP)": "0000111e-0000-1000-8000-00805f9b34fb",
    "Headset (HSP)": "00001108-0000-1000-8000-00805f9b34fb",
    "Hands-free Audio Gateway": "0000111f-0000-1000-8000-00805f9b34fb",
}


def _request_bluetooth_service(mac_address: str, cod: Optional[int], toggle_hfp: bool = False) -> Tuple[bool, str]:
    """
    Calls Win32 API BluetoothSetServiceState to explicitly enable both Music (A2DP)
    and Voice Microphone (HFP / HSP) profiles in Windows.
    If toggle_hfp is True, briefly disables HFP/HSP before re-enabling to force 
    stubborn headset firmware (e.g. Studds Rydio) to reset its SCO state machine.
    """
    try:
        bthprops = ctypes.WinDLL("bthprops.cpl")
        kernel32 = ctypes.WinDLL("kernel32.dll")

        bthprops.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(_BLUETOOTH_FIND_RADIO_PARAMS), ctypes.POINTER(wintypes.HANDLE)]
        bthprops.BluetoothFindFirstRadio.restype = wintypes.HANDLE

        bthprops.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
        bthprops.BluetoothFindRadioClose.restype = wintypes.BOOL

        bthprops.BluetoothSetServiceState.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BLUETOOTH_DEVICE_INFO), ctypes.POINTER(_GUID), wintypes.DWORD]
        bthprops.BluetoothSetServiceState.restype = wintypes.DWORD

        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
    except Exception as exc:
        return False, f"Could not load Windows DLLs: {exc}"

    hRadio = wintypes.HANDLE()
    params = _BLUETOOTH_FIND_RADIO_PARAMS()
    params.dwSize = ctypes.sizeof(params)

    try:
        hFind = bthprops.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(hRadio))
        if not hFind:
            return False, "No Bluetooth radio found on this machine"
        bthprops.BluetoothFindRadioClose(hFind)
    except Exception as exc:
        return False, f"BluetoothFindFirstRadio failed: {exc}"

    if not hRadio or not hRadio.value:
        return False, "Invalid Bluetooth radio handle obtained"

    try:
        mac_int = int(mac_address.replace(":", ""), 16)
        device_info = _BLUETOOTH_DEVICE_INFO()
        device_info.dwSize = ctypes.sizeof(device_info)
        device_info.Address = mac_int
        if cod:
            device_info.ulClassofDevice = cod

        # Enable both Audio (A2DP) and Voice Microphone (HFP + HSP) services directly
        results = []
        for service_name, uuid_str in _CONNECT_TARGET_SERVICES.items():
            guid_bytes = uuid_lib.UUID(uuid_str).bytes_le
            guid_struct = _GUID.from_buffer_copy(guid_bytes)
            try:
                if toggle_hfp and ("Hands-free" in service_name or "Headset" in service_name):
                    try:
                        bthprops.BluetoothSetServiceState(
                            hRadio, ctypes.byref(device_info), ctypes.byref(guid_struct), _BLUETOOTH_SERVICE_DISABLE
                        )
                        time.sleep(0.35)
                    except Exception:
                        pass
                result_code = bthprops.BluetoothSetServiceState(
                    hRadio, ctypes.byref(device_info), ctypes.byref(guid_struct), _BLUETOOTH_SERVICE_ENABLE
                )
                results.append(f"{service_name}: code {result_code}")
            except Exception as exc:
                results.append(f"{service_name}: exception {exc}")

        return True, "; ".join(results)
    finally:
        try:
            kernel32.CloseHandle(hRadio)
        except Exception:
            pass


async def _pair_device_if_needed(mac_address: str, force_repair: bool = False) -> Tuple[bool, str]:
    """
    Performs REAL Bluetooth pairing/bonding for a device.
    If force_repair is True (or if a stale bond prevents connection), forcibly unpairs the device first.
    """
    if not WINSDK_AVAILABLE or not BluetoothDevice:
        return False, "WinSDK not available"
    try:
        mac_int = int(mac_address.replace(":", ""), 16)
        device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
        if not device:
            return False, "Could not get BluetoothDevice handle — is the device in range and in pairing mode?"

        device_info = device.device_information
        pairing = device_info.pairing

        if pairing.is_paired:
            if force_repair:
                print(f"[pairing] Device {mac_address} has stale pairing — forcing unpair before re-pairing...")
                try:
                    await pairing.unpair_async()
                    await asyncio.sleep(0.6)
                    device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
                    if device and device.device_information:
                        pairing = device.device_information.pairing
                except Exception as unpair_err:
                    print(f"[pairing] Force unpair warning: {unpair_err}")
            else:
                return True, "Already paired"

        if not pairing.can_pair:
            try:
                await pairing.unpair_async()
                await asyncio.sleep(0.5)
                device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
                if device: pairing = device.device_information.pairing
            except Exception:
                pass

        if not pairing.can_pair:
            return False, "Windows reports this device cannot be paired right now — ensure it's actively in pairing mode"

        custom_pairing = pairing.custom

        def _on_pairing_requested(sender, args):
            # ConfirmOnly ceremony needs no PIN/passkey entry — just accept.
            try:
                args.accept()
            except Exception as exc:
                print(f"[pairing] auto-accept handler error: {exc}")

        token = custom_pairing.add_pairing_requested(_on_pairing_requested)
        try:
            result = await custom_pairing.pair_async(
                DevicePairingKinds.CONFIRM_ONLY, DevicePairingProtectionLevel.NONE
            )
        finally:
            custom_pairing.remove_pairing_requested(token)

        status_code = int(result.status)
        if status_code == 0:  # DevicePairingResultStatus.PAIRED
            return True, "Paired successfully"
        elif status_code == 1:  # AlreadyPaired
            return True, "Already paired"
        return False, f"Pairing failed (DevicePairingResultStatus code {status_code})"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _nudge_connection(mac_address: str, cod: Optional[int] = None, toggle_hfp: bool = False) -> Tuple[bool, str]:
    """
    Attempts to make Windows actually connect the device, using the real
    connection API rather than a side-effect nudge. Runs in a thread since
    the underlying Win32 calls are blocking, not async-native.
    """
    try:
        success, detail = await asyncio.to_thread(_request_bluetooth_service, mac_address, cod, toggle_hfp)
        print(f"[connect] BluetoothSetServiceState for {mac_address} (toggle_hfp={toggle_hfp}): success={success}, detail={detail}")
        return success, detail
    except Exception as exc:
        print(f"[connect] _nudge_connection error for {mac_address}: {exc}")
        return False, str(exc)





async def _test_classic_device(address: str, name: str, rssi: Optional[int], cod: Optional[int]) -> dict:
    # Auto-resolve real device name from Windows registry or WinSDK
    reg_name = _get_registry_device_name(address)
    if reg_name:
        name = reg_name
    elif not name or name.lower() in ["unknown", "bluetooth device", "pending device selection"]:
        if WINSDK_AVAILABLE and BluetoothDevice:
            try:
                mac_int = int(address.replace(":", ""), 16)
                win_dev = await BluetoothDevice.from_bluetooth_address_async(mac_int)
                if win_dev and win_dev.name:
                    name = win_dev.name
            except Exception:
                pass

    if not cod or cod == "N/A":
        cod = await _resolve_device_cod(address)

    battery_level = None
    checks = {}
    fw, proxy_rssi = await _fetch_ble_proxy_data(name)
    final_rssi = rssi if rssi is not None else proxy_rssi

    if final_rssi is None: checks["rssi"] = {"status": "FAIL", "reason": "Unreadable"}
    else: checks["rssi"] = _pass(final_rssi >= RSSI_MIN_DBM)

    set_test_progress(address, "Checking pairing status...", "Checking Windows Bluetooth connection...")
    is_connected_init, initial_time = await _check_windows_connection(address, timeout_s=3.0)
    freshly_paired = False
    if not is_connected_init:
        set_test_progress(address, "Pairing device...", "Initiating Windows Bluetooth pairing ceremony...")
        print(f"[connect] {address} not connected — checking pairing status first")
        pair_ok, pair_detail = await _pair_device_if_needed(address)
        print(f"[connect] Pairing attempt for {address}: success={pair_ok}, detail={pair_detail}")
        freshly_paired = pair_ok and pair_detail == "Paired successfully"

        if freshly_paired:
            set_test_progress(address, "Device paired!", "Paired successfully — settling Windows connection...")
            await asyncio.sleep(1.5)

        is_connected_init, initial_time = await _check_windows_connection(address, timeout_s=10.0)

        if not is_connected_init:
            set_test_progress(address, "Connecting to device...", "Enabling Windows Bluetooth service connection...")
            print(f"[connect] {address} still not connected — attempting connection nudge (toggle_hfp=False)")
            await _nudge_connection(address, cod, toggle_hfp=False)
            is_connected_init, initial_time = await _check_windows_connection(address, timeout_s=10.0)

        if not is_connected_init:
            print(f"[connect] {address} failed to connect after initial attempt — forcing stale unpair & re-pairing...")
            set_test_progress(address, "Re-pairing device...", "Clearing stale Windows bond and re-pairing...")
            pair_ok, pair_detail = await _pair_device_if_needed(address, force_repair=True)
            if pair_ok:
                await asyncio.sleep(1.5)
                await _nudge_connection(address, cod, toggle_hfp=False)
                is_connected_init, initial_time = await _check_windows_connection(address, timeout_s=10.0)
                freshly_paired = is_connected_init

    if is_connected_init:
        set_test_progress(address, "Device paired!", "Successfully connected in Windows")
    else:
        initial_time = None

    pairing_time = initial_time if is_connected_init else None
    reconnect_time_s = None

    if freshly_paired:
        set_test_progress(address, "Device paired!", "Paired successfully — settling hardware connection...")
        print(f"[connect] {address} freshly paired — brief pause before checking profiles")
        await asyncio.sleep(2.0)

    if not cod or cod == "N/A":
        cod = await _resolve_device_cod(address)

    set_test_progress(address, "Verifying audio profiles...", "Checking A2DP, AVRCP, and Hands-Free profiles...")
    profile_status, found_profiles, profile_reason = await verify_audio_profiles(cod, address)
    checks["profiles"] = {"status": profile_status}
    if profile_reason:
        checks["profiles"]["reason"] = profile_reason

    if is_connected_init:
        checks["connection"] = {"status": "PASS"}

        reconnect_success, reconnect_time = await _measure_auto_reconnect(address, timeout_s=35.0, cod=cod)
        
        if reconnect_success and reconnect_time is not None:
            checks["auto_reconnect"] = {"status": "PASS"}
            reconnect_time_s = round(reconnect_time, 2)
        else:
            checks["auto_reconnect"] = {"status": "FAIL", "reason": "Radio cycle failed"}

        print(f"[connect] Enabling HFP voice mic profile for {address}...")
        await _nudge_connection(address, cod, toggle_hfp=False)
        await asyncio.sleep(0.5)

        checks["pairing_time"] = _pass(pairing_time is not None and pairing_time <= PAIRING_TIME_LIMIT_S)
    else:
        checks["connection"] = {"status": "FAIL", "reason": "Not paired in Windows"}
        checks["auto_reconnect"] = {"status": "FAIL"}
        checks["pairing_time"] = {"status": "FAIL"}
        pairing_time = None
        reconnect_time_s = None

    return {
        "device_name": name,
        "mac_address": address,
        "device_cod": _format_cod_display(cod),
        "firmware_version": fw,
        "pairing_time_s": round(pairing_time, 2) if (is_connected_init and pairing_time is not None) else None,
        "reconnect_time_s": reconnect_time_s if is_connected_init else None,
        "rssi_dbm": final_rssi,
        "battery_level": battery_level,
        "profiles_found": found_profiles,
        "checks": checks,
    }



# ---------------------------------------------------------------------------
# Speaker Test API Endpoints
# ---------------------------------------------------------------------------

@app.get("/audio/speaker-test")
def serve_speaker_audio():
    """Serves the speaker test MP3 file for Web Audio / HTML5 audio element."""
    filename = "Stereo sound tiny test with clean channels (mp3cut.net).mp3"
    audio_path = os.path.join(get_bundle_dir(), filename)
    if not os.path.exists(audio_path):
        audio_path = os.path.join(get_app_dir(), filename)
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Speaker test audio file not found.")
    return FileResponse(audio_path, media_type="audio/mpeg", filename="speaker-test.mp3")


def _request_a2dp_service(mac_address: str) -> Tuple[bool, str]:
    """Ensures Audio Sink (A2DP) service is enabled for the Bluetooth device before speaker playback."""
    try:
        bthprops = ctypes.WinDLL("bthprops.cpl")
        kernel32 = ctypes.WinDLL("kernel32.dll")
        bthprops.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(_BLUETOOTH_FIND_RADIO_PARAMS), ctypes.POINTER(wintypes.HANDLE)]
        bthprops.BluetoothFindFirstRadio.restype = wintypes.HANDLE
        bthprops.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
        bthprops.BluetoothFindRadioClose.restype = wintypes.BOOL
        bthprops.BluetoothSetServiceState.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BLUETOOTH_DEVICE_INFO), ctypes.POINTER(_GUID), wintypes.DWORD]
        bthprops.BluetoothSetServiceState.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        hRadio = wintypes.HANDLE()
        params = _BLUETOOTH_FIND_RADIO_PARAMS()
        params.dwSize = ctypes.sizeof(params)
        hFind = bthprops.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(hRadio))
        if not hFind:
            return False, "No Bluetooth radio"
        bthprops.BluetoothFindRadioClose(hFind)
        if not hRadio or not hRadio.value:
            return False, "Invalid radio handle"

        try:
            mac_int = int(mac_address.replace(":", ""), 16)
            device_info = _BLUETOOTH_DEVICE_INFO()
            device_info.dwSize = ctypes.sizeof(device_info)
            device_info.Address = mac_int

            a2dp_uuid = _CONNECT_TARGET_SERVICES.get("Audio Sink (A2DP)")
            if a2dp_uuid:
                guid_bytes = uuid_lib.UUID(a2dp_uuid).bytes_le
                guid_struct = _GUID.from_buffer_copy(guid_bytes)
                code = bthprops.BluetoothSetServiceState(
                    hRadio, ctypes.byref(device_info), ctypes.byref(guid_struct), _BLUETOOTH_SERVICE_ENABLE
                )
                return True, f"A2DP code {code}"
            return False, "A2DP UUID not found"
        finally:
            kernel32.CloseHandle(hRadio)
    except Exception as exc:
        return False, str(exc)


@app.post("/speaker_test/start")
def api_start_speaker_test(mac: str = None):
    """Starts exclusive native Windows playback for the speaker test."""
    filename = "Stereo sound tiny test with clean channels (mp3cut.net).mp3"
    audio_path = os.path.join(get_bundle_dir(), filename)
    if not os.path.exists(audio_path):
        audio_path = os.path.join(get_app_dir(), filename)
    if not os.path.exists(audio_path):
        return {"status": "ERROR", "reason": "Speaker audio file not found on server."}

    # Nudge A2DP profile sequentially before starting MCI playback to avoid driver resets during playback
    if mac:
        try:
            _request_a2dp_service(mac.strip().upper())
            time.sleep(0.15)
        except Exception as e:
            print(f"[SpeakerTest] A2DP Nudge warning: {e}")

    result = speaker_test.start_speaker_test(audio_path)
    return result


@app.post("/speaker_test/stop")
def api_stop_speaker_test():
    """Stops native Windows playback for the speaker test."""
    return speaker_test.stop_speaker_test()


@app.get("/speaker_test/status")
def api_get_speaker_test_status():
    """Returns real-time playback status and progress percentage."""
    return speaker_test.get_status()


# ---------------------------------------------------------------------------
# Reports Viewer (History Page)
# ---------------------------------------------------------------------------

@app.get("/reports")
def list_reports(limit: int = 5, offset: int = 0, date: Optional[str] = None, mac: Optional[str] = None):
    """
    Returns a page of saved reports for the Inspection History screen —
    just enough per row to identify the device (name, id, MAC, inspector,
    date) plus the total count so the frontend can page through them.
    An optional `date` (YYYY-MM-DD) filters to reports last updated on
    that day only. An optional `mac` does a case-insensitive partial match
    against mac_address, so the operator can filter on the full address or
    just a fragment of it (e.g. the last few octets) without needing exact
    colon formatting.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        conditions = []
        params: list = []
        if date:
            conditions.append("DATE(inspection_date) = %s")
            params.append(date)
        if mac:
            conditions.append("UPPER(mac_address) LIKE %s")
            params.append(f"%{mac.strip().upper()}%")
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params = tuple(params)

        cursor.execute(f"SELECT COUNT(*) AS total FROM inspection_reports {where_clause}", params)
        total = cursor.fetchone()["total"]

        cursor.execute(f"""
            SELECT id, device_name, mac_address, inspector_name, inspection_date, attempt_number
            FROM inspection_reports
            {where_clause}
            ORDER BY inspection_date DESC
            LIMIT %s OFFSET %s
        """, params + (limit, offset))
        rows = cursor.fetchall()
        cursor.close()

        reports = [
            {
                "id": row["id"],
                "device_name": row["device_name"],
                "mac_address": row["mac_address"],
                "inspector_name": row["inspector_name"],
                "inspection_date": row["inspection_date"].isoformat() if row["inspection_date"] else None,
                "attempt_number": row["attempt_number"],
            }
            for row in rows
        ]

        return {"total": total, "limit": limit, "offset": offset, "date": date, "mac": mac, "reports": reports}
    except MySQLError as e:
        print(f"MySQL Database Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


@app.get("/report/{report_id}")
def get_report_detail(report_id: int):
    """Full record for the 'View More' modal, including the parsed qc_history array."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM inspection_reports WHERE id = %s", (report_id,))
        row = cursor.fetchone()
        cursor.close()

        if not row:
            raise HTTPException(status_code=404, detail="Report not found")

        if row.get("inspection_date"):
            row["inspection_date"] = row["inspection_date"].isoformat()

        try:
            row["qc_history"] = json.loads(row["qc_history"]) if row.get("qc_history") else []
        except (TypeError, json.JSONDecodeError):
            row["qc_history"] = []

        return row
    except MySQLError as e:
        print(f"MySQL Database Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


@app.get("/reports/export_file")
@app.get("/reports/download")
def download_reports_csv(date: Optional[str] = None, mac: Optional[str] = None, mode: Optional[str] = None):
    """
    Generates CSV audit report. If mode='stream', streams raw CSV bytes;
    otherwise saves directly to the user's Downloads folder and opens Windows File Explorer.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        conditions = []
        params: list = []
        if date:
            conditions.append("DATE(inspection_date) = %s")
            params.append(date)
        if mac:
            conditions.append("UPPER(mac_address) LIKE %s")
            params.append(f"%{mac.strip().upper()}%")
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params = tuple(params)

        cursor.execute(f"""
            SELECT id, inspection_date, inspector_name, device_name, mac_address, 
                   device_cod, pairing_time_s, reconnect_time_s, 
                   profiles_found, pairing_status, pairing_remarks, physical_inspection, 
                   physical_remarks, button_status, button_remarks, microphone_status, 
                   mic_remarks, speaker_status, speaker_remarks, attempt_number, duplicate_status
            FROM inspection_reports
            {where_clause}
            ORDER BY inspection_date DESC
        """, params)
        rows = cursor.fetchall()
        cursor.close()

        if mode == "stream":
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
            writer.writerow([
                "Report ID", "Inspection Date", "Inspector Name", "Device Name", "MAC Address",
                "Class of Device (CoD)", "Pairing Time (Seconds)", "Reconnect Time (Seconds)",
                "Profiles Detected", "Pairing Test Status", "Pairing Remarks", "Physical Inspection",
                "Physical Inspection Remarks", "Button Test Status", "Button Remarks", "Mic Test Status", "Mic Remarks",
                "Speaker Test Status", "Speaker Remarks", "Total Attempt Count", "Duplicate Action Tag"
            ])

            for row in rows:
                writer.writerow([
                    row["id"],
                    row["inspection_date"].strftime("%Y-%m-%d %H:%M:%S") if row["inspection_date"] else "N/A",
                    row["inspector_name"],
                    row["device_name"] or "Unknown",
                    row["mac_address"],
                    row["device_cod"] or "N/A",
                    row["pairing_time_s"] if row["pairing_time_s"] is not None else "Timeout",
                    row["reconnect_time_s"] if row["reconnect_time_s"] is not None else "N/A",
                    row["profiles_found"] or "None",
                    row.get("pairing_status"), row.get("pairing_remarks"),
                    row.get("physical_inspection") or row.get("physical_shell"), row.get("physical_remarks"),
                    row.get("button_status") or row.get("button_tactility"), row.get("button_remarks"),
                    row.get("microphone_status") or row.get("microphone_quality"), row.get("mic_remarks"),
                    row.get("speaker_status") or row.get("speaker_output"), row.get("speaker_remarks"),
                    row["attempt_number"],
                    row["duplicate_status"] or "Initial Run"
                ])

            output.seek(0)
            date_part = date if date else "All_Time"
            mac_part = f"_MAC_{mac.strip().upper().replace(':', '')}" if mac else ""
            filename = f"Studds_QC_History_Export_{date_part}{mac_part}.csv"

            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        # Default mode: Save to Downloads folder & open File Explorer
        user_home = os.path.expanduser("~")
        downloads_dir = os.path.join(user_home, "Downloads")
        if not os.path.exists(downloads_dir):
            os.makedirs(downloads_dir, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        date_part = f"_{date}" if date else ""
        mac_part = f"_MAC_{mac.strip().upper().replace(':', '')}" if mac else ""
        filename = f"Studds_QC_History_Export{date_part}{mac_part}_{timestamp_str}.csv"
        file_path = os.path.join(downloads_dir, filename)

        with open(file_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            writer.writerow([
                "Report ID", "Inspection Date", "Inspector Name", "Device Name", "MAC Address",
                "Class of Device (CoD)", "Pairing Time (Seconds)", "Reconnect Time (Seconds)",
                "Profiles Detected", "Pairing Test Status", "Pairing Remarks", "Physical Inspection",
                "Physical Inspection Remarks", "Button Test Status", "Button Remarks", "Mic Test Status", "Mic Remarks",
                "Speaker Test Status", "Speaker Remarks", "Total Attempt Count", "Duplicate Action Tag"
            ])

            for row in rows:
                writer.writerow([
                    row["id"],
                    row["inspection_date"].strftime("%Y-%m-%d %H:%M:%S") if row["inspection_date"] else "N/A",
                    row["inspector_name"],
                    row["device_name"] or "Unknown",
                    row["mac_address"],
                    row["device_cod"] or "N/A",
                    row["pairing_time_s"] if row["pairing_time_s"] is not None else "Timeout",
                    row["reconnect_time_s"] if row["reconnect_time_s"] is not None else "N/A",
                    row["profiles_found"] or "None",
                    row.get("pairing_status"), row.get("pairing_remarks"),
                    row.get("physical_inspection") or row.get("physical_shell"), row.get("physical_remarks"),
                    row.get("button_status") or row.get("button_tactility"), row.get("button_remarks"),
                    row.get("microphone_status") or row.get("microphone_quality"), row.get("mic_remarks"),
                    row.get("speaker_status") or row.get("speaker_output"), row.get("speaker_remarks"),
                    row["attempt_number"],
                    row["duplicate_status"] or "Initial Run"
                ])

        try:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(f'explorer.exe /select,"{file_path}"')
        except Exception as ex:
            print(f"[Export] Could not launch File Explorer: {ex}")

        return {
            "status": "success",
            "filename": filename,
            "file_path": file_path,
            "total_records": len(rows)
        }

    except MySQLError as e:
        print(f"MySQL Export Failure: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export report: {e}")
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Duplicate MAC Detection
# ---------------------------------------------------------------------------

_MANUAL_CHECK_COLUMNS = ["pairing_status", "physical_inspection", "button_status", "microphone_status", "speaker_status"]


def _compute_overall_result(row: dict) -> str:
    """
    A stored report only PASSes overall if all 5 manual QC dropdowns were
    PASS — mirrors the frontend's updateQcStatusPill() logic so history
    shown for a duplicate MAC matches what the inspector actually saw at
    the time.
    """
    checks = [
        row.get("pairing_status"),
        row.get("physical_inspection") or row.get("physical_shell"),
        row.get("button_status") or row.get("button_tactility"),
        row.get("microphone_status") or row.get("microphone_quality"),
        row.get("speaker_status") or row.get("speaker_output"),
    ]
    if all(c == "PASS" for c in checks):
        return "PASS"
    return "FAIL"


@app.get("/check_duplicate/{mac_address}")
def check_duplicate(mac_address: str):
    """Checks for existing row and unpacks the JSON history array for the UI."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"""
            SELECT *
            FROM inspection_reports
            WHERE mac_address = %s
            ORDER BY inspection_date DESC LIMIT 1
        """, (mac_address,))
        row = cursor.fetchone()
        cursor.close()

        if not row:
            return {"mac_address": mac_address, "is_duplicate": False, "attempt_number": 1, "history": []}

        history_payload = []
        if row.get("qc_history"):
            try:
                parsed_history = json.loads(row["qc_history"])
                # Reverse the array so the UI reads the newest attempt first
                for entry in reversed(parsed_history):
                    m_res = entry.get("manual_results", {})
                    overall = "PASS" if all(m_res.get(k) == "PASS" for k in ["pairing", "shell_inspection", "buttons", "microphone", "speaker"]) else "FAIL"
                        
                    history_payload.append({
                        "inspection_date": entry.get("inspection_date"),
                        "inspector_name": entry.get("inspector_name"),
                        "device_name": row["device_name"],
                        "overall_result": overall,
                        "duplicate_status": entry.get("duplicate_status"),
                    })
            except Exception as ex:
                print(f"Failed to parse qc_history JSON: {ex}")

        # Fallback for legacy rows saved before this new feature
        if not history_payload:
            overall = _compute_overall_result(row)
            history_payload.append({
                "inspection_date": row["inspection_date"].isoformat() if row["inspection_date"] else None,
                "inspector_name": row["inspector_name"],
                "device_name": row["device_name"],
                "overall_result": overall,
                "duplicate_status": row["duplicate_status"],
            })

        return {
            "mac_address": mac_address,
            "is_duplicate": True,
            "attempt_number": row["attempt_number"] + 1,
            "history": history_payload,
        }
    except MySQLError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


@app.post("/nudge_mic")
async def nudge_mic(mac: str, force_toggle: bool = True):
    """
    Explicitly activates the Hands-free & Headset voice microphone profiles (HFP & HSP)
    for a connected Bluetooth device to force Windows PnP to register the mic endpoint.
    If force_toggle is True, briefly cycles HFP to force stubborn firmware (e.g. Studds Rydio)
    to wake up its SCO audio channel on first connect.
    """
    cod = await _resolve_device_cod(mac)
    ok, msg = await _nudge_connection(mac, cod, toggle_hfp=force_toggle)
    await asyncio.sleep(1.0)
    return {"success": ok, "detail": msg}


def check_bluetooth_radio_on() -> Tuple[bool, str]:
    """
    Checks whether the Windows Bluetooth radio adapter is hardware-enabled and turned ON.
    Uses 64-bit ctypes handle restypes to prevent memory access violations.
    """
    # 1. Try WinSDK (Thread-safe WinRT API)
    if WINSDK_AVAILABLE and Radio:
        try:
            loop = asyncio.new_event_loop()
            radios = loop.run_until_complete(Radio.get_radios_async())
            loop.close()
            for r in radios:
                if r.kind == RadioKind.BLUETOOTH:
                    if r.state == RadioState.ON:
                        return True, "Bluetooth radio active"
                    else:
                        return False, "Bluetooth is turned OFF on this computer. Please turn ON Bluetooth in Windows Settings."
        except Exception:
            pass

    # 2. Try Win32 CAPI with explicit 64-bit handle prototypes
    try:
        bthprops = ctypes.WinDLL("bthprops.cpl")

        bthprops.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(_BLUETOOTH_FIND_RADIO_PARAMS), ctypes.POINTER(wintypes.HANDLE)]
        bthprops.BluetoothFindFirstRadio.restype = wintypes.HANDLE

        bthprops.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
        bthprops.BluetoothFindRadioClose.restype = wintypes.BOOL

        hRadio = wintypes.HANDLE()
        params = _BLUETOOTH_FIND_RADIO_PARAMS()
        params.dwSize = ctypes.sizeof(params)

        hFind = bthprops.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(hRadio))
        if hFind:
            bthprops.BluetoothFindRadioClose(hFind)
            if hRadio and hRadio.value:
                try:
                    kernel32 = ctypes.WinDLL("kernel32.dll")
                    kernel32.CloseHandle(hRadio)
                except Exception:
                    pass
            return True, "Bluetooth radio active"
        return False, "Bluetooth is turned OFF on this computer. Please turn ON Bluetooth in Windows Settings."
    except Exception as exc:
        print(f"[Bluetooth Check] Radio query error: {exc}")
        return True, "Bluetooth state unverified"


@app.get("/bluetooth_status")
def get_bluetooth_status():
    enabled, msg = check_bluetooth_radio_on()
    return {"enabled": enabled, "message": msg}


ACTIVE_TEST_PROGRESS = {}

def set_test_progress(address: str, step: str, detail: str = ""):
    if not address: return
    clean_addr = address.replace(":", "").upper()
    ACTIVE_TEST_PROGRESS[clean_addr] = {
        "step": step,
        "detail": detail,
        "timestamp": time.time()
    }

@app.get("/test_progress/{address}")
def get_test_progress(address: str):
    clean_addr = address.replace(":", "").upper()
    status = ACTIVE_TEST_PROGRESS.get(clean_addr, {"step": "Preparing test...", "detail": "Connecting to device"})
    return status


# ---------------------------------------------------------------------------
# Data Ingestion (Save Endpoint)
# ---------------------------------------------------------------------------

class FinalReport(BaseModel):
    mac_address: str
    device_name: str
    inspector_name: str       
    automated_results: Dict[str, Any]
    manual_results: Dict[str, str]
    duplicate_status: Optional[str] = None


def create_history_entry(attempt_num: int, report: FinalReport):
    """Helper function to compile a clean JSON snapshot of the test."""
    return {
        "attempt_number": attempt_num,
        "inspection_date": datetime.now().isoformat(),
        "inspector_name": report.inspector_name,
        "duplicate_status": report.duplicate_status,
        "automated_results": report.automated_results,
        "manual_results": report.manual_results
    }


def _unpair_via_win32_bthprops(mac_address: str) -> Tuple[bool, str]:
    """
    Direct Win32 C API unpairing via bthprops.cpl:
    1. Disconnects active Bluetooth audio/handsfree services (BluetoothSetServiceState DISABLE).
    2. Calls BluetoothRemoveDevice to delete the device from Windows system registry / paired list.
    Works natively in compiled .exe environments without PowerShell or COM apartment requirements.
    """
    try:
        bthprops = ctypes.WinDLL("bthprops.cpl")
        kernel32 = ctypes.WinDLL("kernel32.dll")
        mac_clean = mac_address.replace(":", "").replace("-", "")
        mac_int = int(mac_clean, 16)

        # 1. Disable active services (A2DP & Hands-Free) to disconnect audio streams
        try:
            hRadio = wintypes.HANDLE()
            params = _BLUETOOTH_FIND_RADIO_PARAMS()
            params.dwSize = ctypes.sizeof(params)

            bthprops.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(_BLUETOOTH_FIND_RADIO_PARAMS), ctypes.POINTER(wintypes.HANDLE)]
            bthprops.BluetoothFindFirstRadio.restype = wintypes.HANDLE

            bthprops.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
            bthprops.BluetoothFindRadioClose.restype = wintypes.BOOL

            bthprops.BluetoothSetServiceState.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BLUETOOTH_DEVICE_INFO), ctypes.POINTER(_GUID), wintypes.DWORD]
            bthprops.BluetoothSetServiceState.restype = wintypes.DWORD

            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

            hFind = bthprops.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(hRadio))
            if hFind:
                bthprops.BluetoothFindRadioClose(hFind)
                device_info = _BLUETOOTH_DEVICE_INFO()
                device_info.dwSize = ctypes.sizeof(device_info)
                device_info.Address = mac_int

                for uuid_str in _CONNECT_TARGET_SERVICES.values():
                    try:
                        g_bytes = uuid_lib.UUID(uuid_str).bytes_le
                        g_struct = _GUID.from_buffer_copy(g_bytes)
                        bthprops.BluetoothSetServiceState(
                            hRadio, ctypes.byref(device_info), ctypes.byref(g_struct), 0 # 0 = DISABLE
                        )
                    except Exception:
                        pass
                try:
                    kernel32.CloseHandle(hRadio)
                except Exception:
                    pass
        except Exception as e:
            print(f"  └─ Service disable attempt error: {e}")

        # 2. Call BluetoothRemoveDevice to remove from Windows paired list
        bthprops.BluetoothRemoveDevice.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
        bthprops.BluetoothRemoveDevice.restype = wintypes.DWORD

        bt_addr = ctypes.c_ulonglong(mac_int)
        res_code = bthprops.BluetoothRemoveDevice(ctypes.byref(bt_addr))
        print(f"  └─ Win32 BluetoothRemoveDevice code for {mac_address}: {res_code}")
        
        if res_code == 0: # ERROR_SUCCESS
            return True, "Removed from Windows paired list via BluetoothRemoveDevice"
        elif res_code == 1168: # ERROR_NOT_FOUND (Device was already not in paired list)
            return True, "Device was already unpaired"
        else:
            return False, f"BluetoothRemoveDevice returned code {res_code}"
    except Exception as exc:
        print(f"  └─ Win32 bthprops unpair error: {exc}")
        return False, str(exc)


async def unpair_bluetooth_device(mac_address: str) -> Tuple[bool, str]:
    """
    Unpairs and removes a Bluetooth (Classic or BLE) device from Windows.
    Disconnects any active audio streams and cleans up the Windows system paired list.
    Natively supports both Python console execution and compiled PyInstaller .exe binaries.
    """
    if not mac_address or mac_address == "-" or mac_address.lower() == "n/a":
        return False, "Invalid MAC address"

    print(f"🗑️ [unpair] Initiating automatic unpair for MAC: {mac_address}")
    details = []

    # Initialize COM MTA apartment for WinRT on background server thread
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 0)
    except Exception:
        pass

    mac_int = int(mac_address.replace(":", "").replace("-", ""), 16)

    # 1. Primary WinSDK Classic & BLE Bluetooth Unpair (Must run BEFORE registry purge)
    if WINSDK_AVAILABLE and BluetoothDevice:
        try:
            device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
            if device and device.device_information and device.device_information.pairing:
                pairing = device.device_information.pairing
                if pairing.is_paired:
                    unpair_res = await pairing.unpair_async()
                    status_str = str(getattr(unpair_res, "status", unpair_res))
                    print(f"  └─ WinSDK Classic unpair status: {status_str}")
                    details.append(f"WinSDK Classic: {status_str}")
        except Exception as e:
            print(f"  └─ WinSDK Classic unpair error: {e}")

    if WINSDK_AVAILABLE and BluetoothLEDevice:
        try:
            ble_device = await BluetoothLEDevice.from_bluetooth_address_async(mac_int)
            if ble_device and ble_device.device_information and ble_device.device_information.pairing:
                pairing = ble_device.device_information.pairing
                if pairing.is_paired:
                    unpair_res = await pairing.unpair_async()
                    status_str = str(getattr(unpair_res, "status", unpair_res))
                    print(f"  └─ WinSDK BLE unpair status: {status_str}")
                    details.append(f"WinSDK BLE: {status_str}")
        except Exception as e:
            print(f"  └─ WinSDK BLE unpair error: {e}")

    # 2. Win32 C API Unpair & Service Disable (bthprops.cpl)
    bth_ok, bth_msg = await asyncio.to_thread(_unpair_via_win32_bthprops, mac_address)
    if bth_ok:
        details.append(bth_msg)

    # 3. PowerShell PnP Device removal fallback
    try:
        clean_mac = mac_address.replace(":", "").replace("-", "").upper()
        ps_cmd = f"Get-PnpDevice | Where-Object {{ $_.InstanceId -like '*{clean_mac}*' -and $_.Class -eq 'Bluetooth' }} | Remove-PnpDevice -Confirm:$false"
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-Command", ps_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=3.0)
    except Exception as e:
        print(f"  └─ PowerShell PnP unpair fallback notice: {e}")

    return True, "; ".join(details) or "Unpair complete"


@app.post("/unpair/{address}")
async def api_unpair_device(address: str):
    success, msg = await unpair_bluetooth_device(address)
    return {"status": "success" if success else "failed", "message": msg}


@app.post("/save_report")
async def save_final_report(report: FinalReport):
    conn = None
    try:
        auto = report.automated_results
        manual = report.manual_results

        conn = get_db_connection()
        
        # 1. Fetch existing row to check if it's a retest
        dict_cursor = conn.cursor(dictionary=True)
        dict_cursor.execute("SELECT * FROM inspection_reports WHERE mac_address = %s ORDER BY inspection_date DESC LIMIT 1", (report.mac_address,))
        existing_row = dict_cursor.fetchone()
        dict_cursor.close()

        cursor = conn.cursor()

        if existing_row:
            # --- OVERWRITE EXISTING ROW (Keep DB Clean) ---
            attempt_number = existing_row["attempt_number"] + 1
            duplicate_status = report.duplicate_status

            # Extract existing JSON array
            try:
                history_list = json.loads(existing_row["qc_history"]) if existing_row.get("qc_history") else []
            except:
                history_list = []

            # Retroactively preserve Attempt #1 if this is an older row being migrated
            if not history_list:
                legacy_entry = {
                    "attempt_number": existing_row["attempt_number"],
                    "inspection_date": existing_row["inspection_date"].isoformat() if existing_row["inspection_date"] else datetime.now().isoformat(),
                    "inspector_name": existing_row["inspector_name"],
                    "duplicate_status": existing_row["duplicate_status"],
                    "automated_results": {
                        "pairing_time_s": existing_row.get("pairing_time_s"),
                        "reconnect_time_s": existing_row.get("reconnect_time_s"),
                        "device_cod": existing_row.get("device_cod"),
                        "profiles_found": existing_row.get("profiles_found", "").split(", ") if existing_row.get("profiles_found") else []
                    },
                    "manual_results": {
                        "pairing": existing_row.get("pairing_status"),
                        "shell_inspection": existing_row.get("physical_inspection") or existing_row.get("physical_shell"),
                        "buttons": existing_row.get("button_status") or existing_row.get("button_tactility"),
                        "microphone": existing_row.get("microphone_status") or existing_row.get("microphone_quality"),
                        "speaker": existing_row.get("speaker_status") or existing_row.get("speaker_output"),
                    }
                }
                history_list.append(legacy_entry)

            # Append Attempt #2 (or higher) to the JSON array
            history_list.append(create_history_entry(attempt_number, report))
            history_json = json.dumps(history_list)

            # Overwrite the root columns and update the JSON history
            cursor.execute('''
                UPDATE inspection_reports 
                SET inspector_name=%s, device_name=%s, device_cod=%s,
                    pairing_time_s=%s, reconnect_time_s=%s, profiles_found=%s,
                    pairing_status=%s, pairing_remarks=%s, physical_inspection=%s, physical_remarks=%s,
                    button_status=%s, button_remarks=%s, microphone_status=%s, mic_remarks=%s,
                    speaker_status=%s, speaker_remarks=%s, attempt_number=%s, duplicate_status=%s,
                    qc_history=%s, inspection_date=CURRENT_TIMESTAMP
                WHERE id=%s
            ''', (
                report.inspector_name, report.device_name, auto.get("device_cod", "N/A"),
                auto.get("pairing_time_s"), auto.get("reconnect_time_s"), ", ".join(auto.get("profiles_found") or []) or "None Detected",
                manual.get("pairing", "N/A"), manual.get("pairing_remarks", ""), manual.get("shell_inspection", "N/A"), manual.get("shell_remarks", ""),
                manual.get("buttons", "N/A"), manual.get("buttons_remarks", ""), manual.get("microphone", "N/A"), manual.get("microphone_remarks", ""),
                manual.get("speaker", "N/A"), manual.get("speaker_remarks", ""), attempt_number, duplicate_status,
                history_json, existing_row["id"]
            ))

        else:
            attempt_number = 1
            duplicate_status = None
            history_list = [create_history_entry(attempt_number, report)]
            history_json = json.dumps(history_list)

            cursor.execute('''
                INSERT INTO inspection_reports 
                (inspector_name, device_name, mac_address, device_cod, pairing_time_s, reconnect_time_s,
                 profiles_found, pairing_status, pairing_remarks, physical_inspection, physical_remarks,
                 button_status, button_remarks, microphone_status, mic_remarks, speaker_status, speaker_remarks,
                 attempt_number, duplicate_status, qc_history)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                report.inspector_name, report.device_name, report.mac_address, auto.get("device_cod", "N/A"),
                auto.get("pairing_time_s"), auto.get("reconnect_time_s"), ", ".join(auto.get("profiles_found") or []) or "None Detected",
                manual.get("pairing", "N/A"), manual.get("pairing_remarks", ""), manual.get("shell_inspection", "N/A"), manual.get("shell_remarks", ""),
                manual.get("buttons", "N/A"), manual.get("buttons_remarks", ""), manual.get("microphone", "N/A"), manual.get("microphone_remarks", ""),
                manual.get("speaker", "N/A"), manual.get("speaker_remarks", ""), attempt_number, duplicate_status, history_json
            ))

        conn.commit()
        cursor.close()

        # Clean 4-step Disconnect & Unpair sequence post commit
        try:
            await disconnect_and_unpair_device(report.mac_address)
        except Exception as unpair_err:
            print(f"[save_report] Unpair post-commit notice: {unpair_err}")

        return {
            "status": "success",
            "message": "Report permanently stored in MySQL. Device cleanly disconnected.",
            "attempt_number": attempt_number
        }

    except MySQLError as e:
        print(f"MySQL Database Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except Exception as e:
        print(f"System Fault during save: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error.")
    finally:
        if conn is not None:
            conn.close()

            
@app.post("/exit_app")
@app.get("/exit_app")
def exit_app():
    def kill_process():
        time.sleep(0.3)
        os._exit(0)
    threading.Thread(target=kill_process, daemon=True).start()
    return {"status": "exiting"}


# ---------------------------------------------------------------------------
# Button Detector Automated Testing Routes
# ---------------------------------------------------------------------------
class ButtonTestStartReq(BaseModel):
    device_name: Optional[str] = None


@app.post("/api/button_test/start")
@app.post("/button_test/start")
@app.get("/api/button_test/start")
@app.get("/button_test/start")
def start_button_test_api(device_name: Optional[str] = None, req: Optional[ButtonTestStartReq] = None):
    if not BUTTON_DETECTOR_AVAILABLE:
        raise HTTPException(status_code=500, detail="Button detector module unavailable")
    dev_name = device_name or (req.device_name if req else None)
    button_detector.start_button_detector(dev_name)
    return {"status": "success", "message": "Button detector started", "active": True}


@app.post("/api/button_test/stop")
@app.post("/button_test/stop")
@app.get("/api/button_test/stop")
@app.get("/button_test/stop")
def stop_button_test_api():
    if BUTTON_DETECTOR_AVAILABLE:
        button_detector.stop_button_detector()
    return {"status": "success", "message": "Button detector stopped", "active": False}


@app.get("/api/button_test/status")
@app.get("/button_test/status")
def get_button_test_status_api():
    if not BUTTON_DETECTOR_AVAILABLE:
        return {
            "active": False,
            "buttons": {"play_pause": False, "volume_up": False, "volume_down": False},
            "all_detected": False,
            "error": "Button detector module not loaded"
        }
    return button_detector.get_button_state()


# ---------------------------------------------------------------------------
# QC Inspectors List & User Management Endpoints (From `users` table)
# ---------------------------------------------------------------------------

@app.get("/inspectors")
def get_qc_inspectors():
    """
    Fetches the list of active QC inspectors from the `users` database table.
    Filters for users whose role contains 'inspector' or 'qc'.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT username, user_role, user_id, email, phone_number
            FROM users
            WHERE LOWER(user_role) LIKE '%inspector%' OR LOWER(user_role) LIKE '%qc%'
            ORDER BY username ASC
        """
        cursor.execute(query)
        rows = cursor.fetchall() or []
        cursor.close()

        inspectors = [r["username"] for r in rows if r.get("username")]
        return {"inspectors": inspectors, "details": rows}
    except MySQLError as e:
        print(f"MySQL Inspector Fetch Error: {e}")
        return {"inspectors": [], "details": [], "error": str(e)}
    finally:
        if conn is not None:
            conn.close()