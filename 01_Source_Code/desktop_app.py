import os
import sys
import threading
import time
import traceback
import urllib.request
import webview
import uvicorn

# ====================================================================
# MAGIC FIX: Force the Chromium engine to automatically grant microphone 
# permissions without looking for a missing "Allow" popup.
# ====================================================================
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--use-fake-ui-for-media-stream --enable-media-stream"

def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

current_folder = get_app_dir()
sys.path.insert(0, current_folder)

LOG_PATH = os.path.join(current_folder, "startup_error.log")


def _show_fatal_error(title: str, message: str) -> None:
    """
    Every startup failure gets logged to disk AND shown in a real, visible
    Windows message box. This exists because a --onefile build launched by
    double-click has no console a user will ever see in time — a daemon
    thread that dies, or an exception during import, previously vanished
    completely: the window either never opened or opened against a dead
    backend, with zero indication why. That's exactly what happened on the
    second laptop.
    """
    full_message = f"{message}\n\nFull details written to:\n{LOG_PATH}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{message}\n")
    except Exception:
        pass  # even if logging itself fails, still try to show the box

    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, full_message, title, 0x10)  # MB_ICONERROR
    except Exception:
        print(full_message)  # last resort if ctypes itself fails


# --- Import the backend defensively ---
# This runs on the MAIN thread, before the background server thread is even
# created. qc_bluetooth_api.py's own init_db() now catches its own DB
# errors internally and never raises, but this wrapper stays as a second,
# unconditional safety net: if ANYTHING else goes wrong while loading the
# backend module (missing dependency, bad config file, etc.), the person
# gets a real error message instead of a window that silently never opens.
try:
    import button_detector
    from qc_bluetooth_api import app
except Exception:
    _show_fatal_error(
        "Studds QC — Startup Failed",
        "The app failed to start while loading the backend.\n\n" + traceback.format_exc()
    )
    sys.exit(1)


def start_backend_server():
    """Starts the FastAPI engine in the background — any crash here is now
    logged and shown, not silently swallowed by the daemon thread dying."""
    try:
        # "error" (not "critical") so unhandled exceptions actually print
        # to the console — "critical" was silently swallowing every crash
        # traceback, which is exactly why /scan failures were invisible.
        uvicorn.run(app, host="127.0.0.1", port=8765, log_level="error")
    except Exception:
        _show_fatal_error(
            "Studds QC — Backend Crashed",
            "The local QC server stopped unexpectedly.\n\n" + traceback.format_exc()
        )


def _wait_for_backend(timeout_s: float = 10.0) -> bool:
    """
    Polls /health (which deliberately never touches the database) before
    opening the window, so a backend that never comes up shows a clear
    error instead of a window pointed at a dead server.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


class DesktopApi:
    def save_csv(self, filename: str, content: str) -> bool:
        """
        Opens native Windows Save File Dialog to export CSV reports directly to user chosen path.
        """
        try:
            file_types = ('CSV Files (*.csv)', 'All files (*.*)')
            if webview.windows and len(webview.windows) > 0:
                result = webview.windows[0].create_file_dialog(
                    webview.SAVE_DIALOG, save_filename=filename, file_types=file_types
                )
                if result:
                    save_path = result if isinstance(result, str) else result[0]
                    with open(save_path, "w", encoding="utf-8-sig") as f:
                        f.write(content)
                    return True
        except Exception as e:
            print(f"Error saving CSV via Desktop API: {e}")
        return False


if __name__ == "__main__":
    server_thread = threading.Thread(target=start_backend_server, daemon=True)
    server_thread.start()

    if not _wait_for_backend(timeout_s=10.0):
        _show_fatal_error(
            "Studds QC — Backend Did Not Start",
            "The local QC server didn't respond within 10 seconds.\n\n"
            "Common causes: port 8765 already in use by another program, "
            "or something else crashed during startup."
        )
        sys.exit(1)

    desktop_api = DesktopApi()
    window = webview.create_window(
        title="Studds QC Testing Dashboard",
        url="http://127.0.0.1:8765/",
        width=1100,
        height=800,
        resizable=True,
        js_api=desktop_api
    )

    webview.start()