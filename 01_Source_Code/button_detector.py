"""
button_detector.py

Standalone Button Recognition Utility for Windows Bluetooth Headsets & Media Keys.

Recognizes physical button presses:
  - Play / Pause (via Windows SMTC media session playback status & Low-Level Keyboard Hook)
  - Volume Up / Down (via CoreAudio volume change monitoring using pycaw & Low-Level Keyboard Hook)

Requirements (install if missing):
  pip install pycaw winsdk comtypes

Usage:
  python button_detector.py
  python button_detector.py --device "Rydio"
"""

import sys
import time
import asyncio
import threading
import argparse
from typing import Optional, Dict, Any

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# --- CoreAudio setup (pycaw) ---
try:
    from ctypes import cast as _ctypes_cast, POINTER as _ctypes_POINTER
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False

# --- Windows SDK setup (winsdk) ---
try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _MediaSessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlaybackStatus,
    )
    WINSDK_AVAILABLE = True
except ImportError:
    WINSDK_AVAILABLE = False
    _MediaSessionManager = None
    _PlaybackStatus = None

# --- Global Detection State ---
button_state: Dict[str, bool] = {
    "play_pause": False,
    "volume_up": False,
    "volume_down": False,
}
_state_lock = threading.Lock()
_monitoring_active: bool = False
_hook_thread_started: bool = False
_monitor_thread: Optional[threading.Thread] = None


# ============================================================================
# 1. Win32 Low-Level Keyboard Hook (ctypes)
# ============================================================================
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_PLAY_PAUSE = 0xB3

_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104

_hook_proc_ref = None
_keyboard_hook_handle = None

def _start_keyboard_hook() -> None:
    global _keyboard_hook_handle, _hook_proc_ref
    if not sys.platform.startswith("win"):
        return

    try:
        import ctypes
        from ctypes import wintypes

        HHOOK = ctypes.c_void_p
        USER32 = ctypes.windll.user32
        KERNEL32 = ctypes.windll.kernel32

        USER32.SetWindowsHookExW.restype = HHOOK
        USER32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
        USER32.CallNextHookEx.restype = wintypes.LPARAM
        USER32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        USER32.UnhookWindowsHookEx.restype = wintypes.BOOL
        USER32.UnhookWindowsHookEx.argtypes = [HHOOK]
        KERNEL32.GetModuleHandleW.restype = wintypes.HMODULE
        KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
            ]

        CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        def low_level_keyboard_proc(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                try:
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    vk = kb.vkCode
                    if _monitoring_active:
                        with _state_lock:
                            if vk == VK_MEDIA_PLAY_PAUSE:
                                button_state["play_pause"] = True
                                print("🎵 [Keyboard Hook] Detected: Play/Pause")
                            elif vk == VK_VOLUME_UP:
                                button_state["volume_up"] = True
                                print("🔊 [Keyboard Hook] Detected: Volume Up")
                            elif vk == VK_VOLUME_DOWN:
                                button_state["volume_down"] = True
                                print("🔉 [Keyboard Hook] Detected: Volume Down")
                except Exception:
                    pass
            return USER32.CallNextHookEx(_keyboard_hook_handle, nCode, wParam, lParam)

        _hook_proc_ref = CMPFUNC(low_level_keyboard_proc)
        h_mod = KERNEL32.GetModuleHandleW(None)
        _keyboard_hook_handle = USER32.SetWindowsHookExW(
            _WH_KEYBOARD_LL, _hook_proc_ref, h_mod, 0
        )

        if not _keyboard_hook_handle:
            print("⚠️ Keyboard hook failed to register.")
            return

        # Win32 Message Loop to keep hook alive
        msg = wintypes.MSG()
        while USER32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            USER32.TranslateMessage(ctypes.byref(msg))
            USER32.DispatchMessageW(ctypes.byref(msg))

    except Exception as e:
        print(f"❌ Keyboard hook thread error: {e}")


# ============================================================================
# 2. Audio Endpoint & Media Status Polling (pycaw + winsdk)
# ============================================================================
def _activate_endpoint_volume(device_obj):
    target = device_obj if hasattr(device_obj, "Activate") else getattr(device_obj, "_dev", None)
    if target is None or not hasattr(target, "Activate"):
        raise AttributeError(f"No Activate capability on {device_obj!r}")
    interface = target.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return _ctypes_cast(interface, _ctypes_POINTER(IAudioEndpointVolume))

def _find_speaker_endpoint(target_device_name: Optional[str] = None):
    """
    Safely retrieves the active default speaker endpoint, or target matching endpoint.
    """
    if not PYCAW_AVAILABLE:
        return None, "None"
    try:
        if target_device_name:
            for dev in AudioUtilities.GetAllDevices():
                friendly = dev.FriendlyName or ""
                if target_device_name.lower() in friendly.lower():
                    return _activate_endpoint_volume(dev), friendly
        
        default_dev = AudioUtilities.GetSpeakers()
        friendly = getattr(default_dev, "FriendlyName", "Default Speakers")
        return _activate_endpoint_volume(default_dev), friendly
    except Exception:
        return None, "Unknown"


async def monitor_buttons_loop(target_device_name: Optional[str] = None):
    if PYCAW_AVAILABLE:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass

    last_volume = None
    last_playback_status = None
    volume_ctrl = None
    endpoint_name = "Default Speakers"
    smtc_warned = False

    print(f"🎧 Monitor loop active.")

    while _monitoring_active:
        try:
            # --- Volume monitoring via pycaw ---
            if PYCAW_AVAILABLE and _monitoring_active:
                try:
                    if volume_ctrl is None:
                        volume_ctrl, endpoint_name = _find_speaker_endpoint(target_device_name)

                    if volume_ctrl:
                        current_volume = volume_ctrl.GetMasterVolumeLevelScalar()
                        if last_volume is not None:
                            diff = current_volume - last_volume
                            if diff > 0.005:
                                with _state_lock:
                                    button_state["volume_up"] = True
                                print(f"🔊 [Bluetooth / Audio Endpoint: '{endpoint_name}'] Volume Up detected ({last_volume:.2f} -> {current_volume:.2f})")
                            elif diff < -0.005:
                                with _state_lock:
                                    button_state["volume_down"] = True
                                print(f"🔉 [Bluetooth / Audio Endpoint: '{endpoint_name}'] Volume Down detected ({last_volume:.2f} -> {current_volume:.2f})")
                        last_volume = current_volume
                except Exception:
                    volume_ctrl = None  # Re-acquire handle if audio device changes or reconnects

            # --- Media Play/Pause monitoring via SMTC ---
            if WINSDK_AVAILABLE and _MediaSessionManager and _monitoring_active:
                try:
                    manager = await _MediaSessionManager.request_async()
                    session = manager.get_current_session()
                    if session is not None:
                        info = session.get_playback_info()
                        status = info.playback_status
                        if last_playback_status is not None and status != last_playback_status:
                            if status in (_PlaybackStatus.PLAYING, _PlaybackStatus.PAUSED):
                                with _state_lock:
                                    button_state["play_pause"] = True
                                print(f"🎵 [Media Session] Play/Pause detected via Bluetooth ({last_playback_status.name} -> {status.name})")
                        last_playback_status = status
                    else:
                        if not smtc_warned:
                            print("💡 Tip for Play/Pause: No active media session found on Windows. Play YouTube or music in browser/Spotify to test Play/Pause!")
                            smtc_warned = True
                except Exception:
                    pass

        except Exception as e:
            print(f"❌ Monitor loop error: {e}")

        await asyncio.sleep(0.3)


# ============================================================================
# 3. Main Runner & Lifecycle Management
# ============================================================================
def _run_monitor_thread(target_device_name: Optional[str] = None) -> None:
    """Worker thread running the asyncio monitor loop."""
    try:
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.ole32.CoInitializeEx(None, 0x0)
            except Exception:
                pass
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(monitor_buttons_loop(target_device_name))
    except Exception as e:
        print(f"❌ Button monitor thread error: {e}")



def start_button_detector(target_device_name: Optional[str] = None) -> None:
    """Starts button detection background threads and resets states."""
    global _monitoring_active, _hook_thread_started, _monitor_thread
    reset_button_state()
    _monitoring_active = True

    if not _hook_thread_started:
        _hook_thread_started = True
        threading.Thread(target=_start_keyboard_hook, daemon=True).start()

    if _monitor_thread is None or not _monitor_thread.is_alive():
        _monitor_thread = threading.Thread(target=_run_monitor_thread, args=(target_device_name,), daemon=True)
        _monitor_thread.start()


def stop_button_detector() -> None:
    """Stops the button monitoring loop."""
    global _monitoring_active
    _monitoring_active = False


def get_button_state() -> Dict[str, Any]:
    """Returns a snapshot of currently detected button states."""
    with _state_lock:
        st = dict(button_state)
    all_detected = st["play_pause"] and st["volume_up"] and st["volume_down"]
    return {
        "active": _monitoring_active,
        "buttons": st,
        "all_detected": all_detected,
    }


def reset_button_state() -> None:
    """Resets all button detection flags to False."""
    with _state_lock:
        button_state["play_pause"] = False
        button_state["volume_up"] = False
        button_state["volume_down"] = False


def main():
    parser = argparse.ArgumentParser(description="Standalone Bluetooth & Media Key Button Detector")
    parser.add_argument("--device", type=str, default=None, help="Name or substring of the headset to monitor (e.g. --device Studds)")
    args = parser.parse_args()

    print("==================================================")
    print("      STUDDS Bluetooth Button Recognition Tool     ")
    print("==================================================")
    print(f"Pycaw Available:   {PYCAW_AVAILABLE}")
    print(f"WinSDK Available:  {WINSDK_AVAILABLE}")
    print("Listening for physical button presses (Play/Pause, Volume Up, Volume Down)...")
    print("Press Ctrl+C to stop.\n")

    start_button_detector(args.device)

    try:
        while True:
            time.sleep(0.5)
            st = get_button_state()
            if st["all_detected"]:
                print("✅ ALL BUTTONS DETECTED SUCCESSFULLY!")
                break
    except KeyboardInterrupt:
        print("\nStopped button detector. Exiting...")
    finally:
        stop_button_detector()

if __name__ == "__main__":
    main()
