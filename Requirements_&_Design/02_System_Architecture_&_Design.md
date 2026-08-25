# System Architecture & Technical Design Document
## Studds QC Bluetooth Device Inspection Application

---

## 1. High-Level Architecture Overview

The Studds QC Desktop Application implements an asynchronous, decoupled client-server architecture hosted locally on the operator's workstation. The system eliminates cloud dependencies for core testing workflows while maintaining central data consolidation via a networked MySQL database.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           PyWebView UI Layer                            │
│           (Bootstrap 5 + FontAwesome + Modern JS Dashboard)             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ HTTP REST API / JSON (Port 8765)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Local Backend (Port 8765)                    │
│                          `qc_bluetooth_api.py`                          │
└────────┬───────────────────┬───────────────────┬──────────────────┬─────┘
         │                   │                   │                  │
         ▼                   ▼                   ▼                  ▼
┌──────────────────┐┌──────────────────┐┌─────────────────┐┌───────────────┐
│  WinSDK & Bleak  ││   Offline Vosk   ││  WinMM MCI API  ││ PyCaw Core    │
│  Bluetooth Stack ││ Speech-to-Text   ││  Audio Playback ││ Audio & Hook  │
│  (BLE & Classic) ││  (16kHz Mono)    ││  (L/R Channels) ││ (Vol/Buttons) │
└────────┬─────────┘└──────────────────┘└─────────────────┘└───────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         MySQL Central Database                          │
│                    `inspection_logs` Ingestion Table                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Process & Threading Model

The application utilizes a multi-threaded architecture orchestrated by `desktop_app.py`:

```text
[Main Process: desktop_app.py]
  │
  ├── Thread 1: FastAPI / Uvicorn Server (Daemon Thread, Port 8765)
  │     ├── Async Event Loop: Request routing, REST handlers, DB operations
  │     ├── Background Worker: Bluetooth scan and diagnostic runner
  │     └── Speech Processing: Vosk model inference pipeline
  │
  ├── Thread 2: PyWebView GUI Main Thread
  │     └── Edge Chromium WebView2 window hosting studds_qc_inspection.html
  │
  └── Thread 3: Hardware Hook & Volume Polling Thread (`button_detector.py`)
        ├── Windows CoreAudio `IAudioEndpointVolume` peak level poller
        └── Win32 `WH_KEYBOARD_LL` low-level message pump
```

### Startup Synchronization Sequence:
1. `desktop_app.py` launches `start_backend_server()` in a background daemon thread.
2. The main thread executes `_wait_for_backend()` polling `http://127.0.0.1:8765/health` up to 10 seconds.
3. Once the health endpoint responds with HTTP 200, PyWebView creates the application window pointed to `http://127.0.0.1:8765/`.
4. If an exception occurs, a native Windows `MessageBoxW` error dialog is rendered and stack traces are written to `startup_error.log`.

---

## 3. Subsystem Detailed Design

### 3.1 Bluetooth Subsystem (`Bluetooth_testing.py` & `qc_bluetooth_api.py`)
- **Dual Radio Scanner:** Classic devices are discovered using `winsdk.windows.devices.bluetooth.BluetoothDevice`, while BLE devices are captured with `bleak.BleakScanner`.
- **Profile Management:** Communicates with Windows Bluetooth API (`bthprops.cpl` CAPI) using `BluetoothSetServiceState` to enable/disable A2DP, HFP, and HSP service GUIDs.
- **Auto-Reconnect Latency Profiler:** Temporarily unpairs/disconnects the unit, triggers reconnection, and measures the elapsed time to calculate reconnect latency.

### 3.2 Offline Speech Recognition Engine (`mic_test.py`)
- **Model Resolution:** Loads the Vosk model from `sys._MEIPASS` when frozen inside a PyInstaller `--onefile` package, or from the local directory when running in development mode.
- **Audio Capture & Analysis:** The frontend captures audio at 16kHz mono WAV format and sends it via `POST /analyze_mic`.
- **Transcription Matching:** Vosk `KaldiRecognizer` generates JSON results containing word-level confidence and final transcribed text.

### 3.3 Stereo Audio Playback Engine (`speaker_test.py`)
- **Windows Multimedia (MCI) Engine:** Uses `ctypes.windll.winmm.mciSendStringW` to open, play, pause, and query audio status.
- **8.3 Short Path Resolution:** Converts file paths using `GetShortPathNameW` to prevent MCI parse errors caused by spaces or parentheses in file paths.

### 3.4 Button Sensing Engine (`button_detector.py`)
- **CoreAudio Polling:** Periodically reads `IAudioEndpointVolume.GetMasterVolumeLevelScalar()` to detect hardware volume adjustments.
- **Low-Level Keyboard Hook:** Installs `SetWindowsHookExW` with `WH_KEYBOARD_LL` to intercept `VK_VOLUME_UP` (0xAF), `VK_VOLUME_DOWN` (0xAE), and `VK_MEDIA_PLAY_PAUSE` (0xB3).

---

## 4. REST API Endpoint Catalog

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Backend liveness check (does not hit database) |
| `GET` | `/` | Serves the main HTML inspection dashboard |
| `GET` | `/scan` | Initiates dual BLE and Classic Bluetooth device discovery |
| `POST` | `/test/{address}` | Executes automated pairing, profile validation & reconnect test |
| `GET` | `/test_progress/{address}` | Streams live diagnostic step progress to the UI |
| `POST` | `/analyze_mic` | Accepts uploaded WAV audio and returns Vosk speech transcription |
| `POST` | `/nudge_mic` | Re-engages Windows Bluetooth Audio Gateway service |
| `POST` | `/speaker_test/start` | Starts MCI playback of stereo channel separation audio |
| `POST` | `/speaker_test/stop` | Stops MCI audio playback |
| `GET` | `/speaker_test/status` | Returns current playback position and progress percentage |
| `POST` | `/button_test/start` | Activates CoreAudio volume polling and keyboard hook |
| `POST` | `/button_test/stop` | Deactivates button detection monitoring |
| `GET` | `/button_test/status` | Returns state dictionary for Volume Up, Down, and Play/Pause |
| `GET` | `/check_duplicate/{mac}` | Checks if the given MAC address was already logged in MySQL |
| `POST` | `/save_report` | Inserts complete inspection record into MySQL database |
| `GET` | `/reports` | Retrieves filtered inspection history records from MySQL |
| `GET` | `/reports/export_file` | Generates downloadable CSV inspection yield report |
| `POST` | `/unpair/{address}` | Unpairs and cleans up Bluetooth device registration |
| `POST` | `/exit_app` | Gracefully terminates backend process and UI |

---

## 5. Database Schema Design

### Database: `studds_qc`
### Table: `inspection_logs`

```sql
CREATE TABLE IF NOT EXISTS inspection_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    operator_id VARCHAR(50) NOT NULL,
    helmet_serial_number VARCHAR(100) NOT NULL,
    bt_mac_address VARCHAR(50),
    bt_name VARCHAR(100),
    speaker_test_status ENUM('PASSED', 'FAILED', 'SKIPPED') DEFAULT 'SKIPPED',
    mic_test_status ENUM('PASSED', 'FAILED', 'SKIPPED') DEFAULT 'SKIPPED',
    button_test_status ENUM('PASSED', 'FAILED', 'SKIPPED') DEFAULT 'SKIPPED',
    overall_status ENUM('PASS', 'FAIL') NOT NULL,
    failure_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_serial (helmet_serial_number),
    INDEX idx_mac (bt_mac_address),
    INDEX idx_date (created_at)
);
```

---

## 6. Directory Environment Layout

```text
📁 Bluetooth QC Application/
├── 📁 Requirements_&_Design/       # Technical design, SRS, SOPs, and optimization reports
├── 📁 01_Source_Code/              # Primary Active Development Environment (Dev DB)
├── 📁 02_UAT/                      # User Acceptance Testing Environment (Staging DB)
└── 📁 03_Production/               # Verified Live Production Environment (Prod DB)
```
