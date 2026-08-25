import os
import sys
import time
import ctypes
import threading
from typing import Dict, Any

# Windows Multimedia API (winmm.dll) for native, low-latency MP3 playback
try:
    winmm = ctypes.windll.winmm
    kernel32 = ctypes.windll.kernel32
except Exception:
    winmm = None
    kernel32 = None

_speaker_lock = threading.Lock()
_is_running = False
_play_thread = None
_stop_event = threading.Event()


def get_short_path_name(long_name: str) -> str:
    """Converts a long Windows path (with spaces/parentheses) to 8.3 short path so MCI parses it cleanly."""
    if not kernel32 or not os.path.exists(long_name):
        return long_name
    buf = ctypes.create_unicode_buffer(260)
    res = kernel32.GetShortPathNameW(long_name, buf, 260)
    if res == 0 or res > 260:
        return long_name
    return buf.value


def _mci_send(command: str) -> tuple[int, str]:
    if not winmm:
        return -1, "winmm not available"
    buf = ctypes.create_unicode_buffer(256)
    err = winmm.mciSendStringW(command, buf, 255, 0)
    if err != 0:
        err_buf = ctypes.create_unicode_buffer(256)
        winmm.mciGetErrorStringW(err, err_buf, 255)
        return err, err_buf.value
    return 0, buf.value


def is_running() -> bool:
    global _is_running
    return _is_running


def get_status() -> Dict[str, Any]:
    global _is_running
    if not _is_running:
        return {"running": False, "position_ms": 0, "length_ms": 0, "progress_pct": 0.0}
    
    _, pos_str = _mci_send("status speaker_mp3 position")
    _, len_str = _mci_send("status speaker_mp3 length")
    _, mode_str = _mci_send("status speaker_mp3 mode")

    try:
        pos = int(pos_str) if pos_str.isdigit() else 0
        length = int(len_str) if len_str.isdigit() else 1
        pct = round((pos / max(1, length)) * 100, 1)
    except Exception:
        pos, length, pct = 0, 1, 0.0

    mode = (mode_str or "").lower()
    if mode in ["stopped", ""]:
        _is_running = False

    return {
        "running": _is_running and mode == "playing",
        "mode": mode,
        "position_ms": pos,
        "length_ms": length,
        "progress_pct": pct
    }


def stop_speaker_test() -> Dict[str, Any]:
    global _is_running, _stop_event
    _stop_event.set()
    _mci_send("stop speaker_mp3")
    _mci_send("close speaker_mp3")
    _is_running = False
    return {"status": "STOPPED", "running": False}


def _playback_monitor(mp3_path: str):
    global _is_running, _stop_event
    try:
        _mci_send("close speaker_mp3")  # clean up any previous instance
        short_path = get_short_path_name(mp3_path)
        err, err_msg = _mci_send(f'open "{short_path}" type mpegvideo alias speaker_mp3')
        if err != 0:
            print(f"[SpeakerTest] MCI Open error ({err}): {err_msg}")
            _is_running = False
            return

        err, err_msg = _mci_send("play speaker_mp3")
        if err != 0:
            print(f"[SpeakerTest] MCI Play error ({err}): {err_msg}")
            _mci_send("close speaker_mp3")
            _is_running = False
            return

        _is_running = True

        # Wait until playback finishes or stop is requested
        while not _stop_event.is_set():
            time.sleep(0.15)
            _, mode_str = _mci_send("status speaker_mp3 mode")
            if (mode_str or "").lower() not in ["playing", "paused"]:
                break

    except Exception as e:
        print(f"[SpeakerTest] Playback thread exception: {e}")
    finally:
        _mci_send("stop speaker_mp3")
        _mci_send("close speaker_mp3")
        _is_running = False


def start_speaker_test(mp3_path: str) -> Dict[str, Any]:
    global _is_running, _play_thread, _stop_event

    if not os.path.exists(mp3_path):
        return {"status": "ERROR", "reason": f"Audio file not found: {mp3_path}"}

    with _speaker_lock:
        stop_speaker_test()
        time.sleep(0.2)

        _stop_event.clear()
        _play_thread = threading.Thread(target=_playback_monitor, args=(mp3_path,), daemon=True)
        _play_thread.start()

        # Wait up to 0.5 sec to confirm playback started
        for _ in range(6):
            time.sleep(0.08)
            if _is_running:
                break

        if not _is_running:
            return {"status": "ERROR", "reason": "MCI playback failed to start", "running": False}

    return {"status": "SUCCESS", "running": True}
