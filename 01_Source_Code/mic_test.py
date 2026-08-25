"""
mic_test.py

Standalone Microphone Testing & Offline Speech Recognition Module for Studds QC.
Handles Vosk model loading, WAV audio transcript analysis, and Windows Bluetooth
voice microphone profile (HFP/HSP) nudging.
"""

import os
import sys
import time
import io
import wave
import json
import ctypes
from ctypes import wintypes
import uuid as uuid_lib
from typing import Dict, Any, Optional

try:
    from winsdk.windows.devices.bluetooth import BluetoothDevice
    WINSDK_AVAILABLE = True
except ImportError:
    WINSDK_AVAILABLE = False
    BluetoothDevice = None

try:
    import vosk
    VOSK_AVAILABLE = True
except ImportError:
    vosk = None
    VOSK_AVAILABLE = False


# Win32 CAPI Structures & Constants for Bluetooth Profile Management
_BLUETOOTH_SERVICE_DISABLE = 0
_BLUETOOTH_SERVICE_ENABLE = 1

_CONNECT_TARGET_SERVICES = {
    "Audio Sink (A2DP)": "0000110b-0000-1000-8000-00805f9b34fb",
    "Hands-free (HFP)": "0000111e-0000-1000-8000-00805f9b34fb",
    "Headset (HSP)": "00001108-0000-1000-8000-00805f9b34fb",
}


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


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


COD_CACHE: Dict[str, int] = {}


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_bundle_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", get_app_dir())
    return os.path.dirname(os.path.abspath(__file__))


# Load Vosk Offline Speech Model
VOSK_MODEL_PATH = os.path.join(get_bundle_dir(), "vosk-model")
speech_model = None

if VOSK_AVAILABLE:
    if not os.path.exists(VOSK_MODEL_PATH):
        print(f"❌ Vosk model folder not found at {VOSK_MODEL_PATH} — mic test will report ERROR.")
    else:
        vosk.SetLogLevel(-1)  # Hide verbose terminal logs
        last_error = None
        for attempt in range(1, 4):
            try:
                speech_model = vosk.Model(VOSK_MODEL_PATH)
                print(f"✅ Vosk offline speech model loaded successfully (attempt {attempt}).")
                break
            except Exception as e:
                last_error = e
                print(f"⚠️ Vosk model load attempt {attempt}/3 failed: {type(e).__name__}: {e}")
                time.sleep(1.5)
        if speech_model is None:
            print(f"❌ Vosk model load failed after 3 attempts: {last_error}")


def analyze_mic_audio(wav_bytes: bytes) -> Dict[str, Any]:
    """
    Analyzes raw WAV audio bytes sent from the frontend using the Vosk offline speech model.
    Accepts mono 16-bit PCM audio at 8kHz, 16kHz, 32kHz, 44.1kHz, or 48kHz.
    Returns status 'PASS', 'FAIL', or 'ERROR' along with the transcribed speech.
    """
    if not VOSK_AVAILABLE or not speech_model:
        return {"status": "ERROR", "reason": "Offline speech model not loaded."}

    try:
        wf = wave.open(io.BytesIO(wav_bytes), "rb")

        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() not in [8000, 16000, 32000, 44100, 48000]:
            return {"status": "ERROR", "reason": "Invalid audio format."}

        rec = vosk.KaldiRecognizer(speech_model, wf.getframerate())
        rec.SetWords(False)

        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            rec.AcceptWaveform(data)

        result_json = json.loads(rec.FinalResult())
        transcript = result_json.get("text", "").lower()

        print(f"[Mic Test] Heard: '{transcript}'")

        # Define the target phrases to accept as a PASS
        target_phrases = ["hello studds", "studds", "testing", "hello"]
        passed = any(phrase in transcript for phrase in target_phrases)

        return {
            "status": "PASS" if passed else "FAIL",
            "transcript": transcript
        }
    except Exception as e:
        print(f"[Mic Test] Backend parsing error: {e}")
        return {"status": "ERROR", "reason": str(e)}


async def _resolve_device_cod(address: str) -> Optional[int]:
    """Resolves Class of Device (COD) for a Bluetooth MAC address."""
    if address in COD_CACHE:
        return COD_CACHE[address]
    if WINSDK_AVAILABLE and BluetoothDevice:
        try:
            mac_int = int(address.replace(":", ""), 16)
            device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
            if device and device.class_of_device:
                cod_val = device.class_of_device.raw_value
                COD_CACHE[address] = cod_val
                return cod_val
        except Exception:
            pass
    return None


async def _nudge_connection(mac_address: str, cod: Optional[int] = None, toggle_hfp: bool = True) -> tuple[bool, str]:
    """Issues Win32 CAPI service state calls to force Windows PnP to activate HFP & HSP voice mic profiles."""
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
                        time.sleep(0.15)
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


async def nudge_mic_device(mac: str, force_toggle: bool = True) -> Dict[str, Any]:
    """
    Explicitly activates Hands-free & Headset voice microphone profiles (HFP & HSP)
    for a connected Bluetooth device MAC address to force Windows PnP to register the mic endpoint.
    """
    try:
        cod = await _resolve_device_cod(mac)
        ok, msg = await _nudge_connection(mac, cod, toggle_hfp=force_toggle)
        return {"success": ok, "detail": msg}
    except Exception as e:
        print(f"[Mic Test] Nudge mic error: {e}")
        return {"success": False, "detail": str(e)}
