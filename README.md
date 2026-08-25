# Studds QC Bluetooth Device Inspection Application

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011%20(64--bit)-blue.svg)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![PyWebView](https://img.shields.io/badge/PyWebView-Edge%20Chromium-orange.svg)](https://pywebview.flowrl.com/)
[![Speech STT](https://img.shields.io/badge/Offline%20STT-Vosk-red.svg)](https://alphacephei.com/vosk/)
[![Database](https://img.shields.io/badge/Database-MySQL%20%2F%20XAMPP-4479A1.svg)](https://www.mysql.com/)

A high-performance, self-contained Windows desktop application designed to automate and standardize Quality Control (QC) testing for Bluetooth-enabled helmets, headsets, and audio devices manufactured by **Studds Accessories Ltd.**

---

## 📑 Table of Contents
1. [System Overview & Architecture](#-system-overview--architecture)
2. [Key Capabilities & Test Modules](#-key-capabilities--test-modules)
3. [Project Directory Structure](#-project-directory-structure)
4. [Technology Stack](#-technology-stack)
5. [End-to-End QC Workflow](#-end-to-end-qc-workflow)
6. [Database Schema & Configuration](#-database-schema--configuration)
7. [Installation & Development Setup](#-installation--development-setup)
8. [Build & Packaging Pipeline](#-build--packaging-pipeline)
9. [Release Promotion Lifecycle](#-release-promotion-lifecycle)
10. [Troubleshooting & Performance Notes](#-troubleshooting--performance-notes)

---

## 🏛️ System Overview & Architecture

The application implements a decoupled, local client-server architecture packaged into a single standalone executable. The frontend runs in a native Microsoft Edge Chromium webview container, communicating via non-blocking HTTP REST calls with a local Python FastAPI backend engine running on port `8765`.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           PyWebView UI Layer                            │
│           (Bootstrap 5 + FontAwesome + Modern JS Dashboard)             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ HTTP REST API / JSON
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

## 🎯 Key Capabilities & Test Modules

### 1. Dual-Stack Bluetooth Scanning & Automated Pairing
- **BLE & Classic Ingestion:** Uses Microsoft Windows WinSDK (`winsdk.windows.devices.bluetooth`) and `bleak` for simultaneous Classic Bluetooth and Bluetooth Low Energy discovery.
- **Hardware Profile Nudging:** Automatically activates Bluetooth Audio Sink (A2DP), Hands-Free Profile (HFP), and Headset Profile (HSP) services via Win32 CAPI (`bthprops.cpl`).
- **Connection Diagnostics:** Measures exact pairing duration and auto-reconnection latency in seconds.

### 2. Stereo Speaker Channel Separation Test
- **Non-Blocking MCI Playback:** Utilizes the native Windows Multimedia API (`winmm.dll`) for ultra-low latency playback without spawning external media players.
- **8.3 Short-Path Support:** Automatically handles file paths with special characters/spaces using Win32 `GetShortPathNameW`.
- **Channel Verification:** Plays dedicated Left Channel and Right Channel audio cues to ensure wiring integrity.

### 3. 100% Offline Microphone Speech Recognition
- **Bundled Vosk Neural Network:** Operates completely offline with zero cloud API dependencies.
- **Dynamic Model Resolution:** Resolves model files across both local development folders and PyInstaller extracted temporary bundles (`sys._MEIPASS`).
- **Voice Command Recognition:** Transcribes captured speech (e.g., *"testing one two three"*) and validates microphone audio clarity in real time.

### 4. Real-Time Physical Button & Volume Sensing
- **Core Audio Endpoint Polling:** Uses `pycaw` and COM `IAudioEndpointVolume` to detect volume adjustment events triggered by physical headset buttons.
- **Win32 Low-Level Keyboard Hook:** Intercepts media key events (`VK_VOLUME_UP`, `VK_VOLUME_DOWN`, `VK_MEDIA_PLAY_PAUSE`) via `SetWindowsHookExW`.

### 5. Centralized Data Ingestion & Native CSV Export
- **MySQL Integration:** Automatically records Operator ID, Helmet Serial Number, MAC Address, individual test statuses, overall PASS/FAIL evaluation, and timestamps into MySQL.
- **Duplicate MAC Validation:** Prevents re-testing already inspected units unless supervisor override is triggered.
- **Native File Dialog Export:** Leverages PyWebView's `DesktopApi` to export customized inspection reports via Windows native Save Dialogs.

---

## 📁 Project Directory Structure

```text
📁 Bluetooth QC Application/
│
├── 📁 Requirements_&_Design/                     # Comprehensive Project Specifications
│   ├── 01_Software_Requirements_Specification.md # Software requirements specification (SRS)
│   ├── 02_System_Architecture_&_Design.md        # Technical architecture, DB schema & threading
│   ├── 03_User_Manual_&_SOP.md                   # Standard Operating Procedure for line operators
│   ├── 04_Environment_&_Deployment_Guide.md      # 3-tier promotion and deployment guide
│   └── bluetooth_mic_detection_optimization_report.md # Deep root-cause analysis for mic detection
│
├── 📁 01_Source_Code/                            # Active Development Environment (Dev DB)
│   ├── desktop_app.py                            # PyWebView application window & startup safety bridge
│   ├── qc_bluetooth_api.py                       # Core FastAPI server (port 8765) & QC orchestration engine
│   ├── Bluetooth_testing.py                      # Bluetooth device scanning & hardware pairing driver
│   ├── button_detector.py                        # CoreAudio endpoint volume & media key detection module
│   ├── mic_test.py                               # Vosk offline speech STT & Windows HFP profile activator
│   ├── speaker_test.py                           # WinMM MCI low-latency stereo sound playback controller
│   ├── studds_qc_inspection.html                 # Responsive Bootstrap 5 operator inspection dashboard
│   ├── db_config.json                            # MySQL connection parameters (Local / Dev DB)
│   ├── db_config.example.json                    # Configuration template for new environments
│   ├── icon - file.ico                           # Application icon asset
│   ├── Stereo sound tiny test with clean channels (mp3cut.net).mp3 # Reference stereo test audio
│   ├── vosk-model/                               # Offline Vosk acoustic & language model directory
│   ├── StuddsQC.spec                             # PyInstaller build specification
│   ├── build.bat                                 # Automated PyInstaller build script
│   └── studds_installer.iss                      # Inno Setup non-admin installer script
│
├── 📁 02_UAT/                                    # User Acceptance Testing Environment (UAT DB)
│   ├── (Identical promoted codebase from 01_Source_Code configured with staging db_config.json)
│   └── Requirements_&_Design/                    # Synchronized documentation for UAT validation
│
├── 📁 03_Production/                             # Verified Live Production Environment (Prod DB)
│   ├── db_config.json                            # Live production database connection settings
│   └── (Promoted production binaries and installers)
│
├── DIRECTORY_STRUCTURE.txt                       # Quick reference architecture text file
└── README.md                                     # Main project documentation (this file)
```

---

## 💻 Technology Stack

| Component | Technology / Library | Purpose |
|---|---|---|
| **UI Shell** | PyWebView + Microsoft Edge Chromium | Native Windows window with modern web rendering |
| **Frontend UI** | HTML5, Bootstrap 5, FontAwesome 6, Vanilla JS | Operator inspection interface, visualizers & overlays |
| **Backend Framework** | FastAPI + Uvicorn (Port 8765) | Async local REST API for testing orchestration |
| **Bluetooth Engine** | `winsdk`, `bleak`, Win32 `bthprops.cpl` CAPI | Dual BLE/Classic scanning, pairing & profile toggling |
| **Audio Playback** | Windows Multimedia API (`winmm.dll` MCI) | Direct L/R stereo channel separation playback |
| **Speech Recognition**| Vosk (`vosk-model`) | 100% offline speech-to-text transcription |
| **Button Sensing** | `pycaw`, `comtypes`, `user32.dll` Keyboard Hook | CoreAudio peak level polling & media key detection |
| **Database** | MySQL / MariaDB via `mysql-connector-python` | Centralized quality control log ingestion |
| **Packaging** | PyInstaller & Inno Setup | Zero-admin standalone executable & setup installer |

---

## 🔄 End-to-End QC Workflow

```text
[1. Operator Login & Helmet Barcode Scan]
                   │
                   ▼
[2. Bluetooth Device Discovery & Pairing]
                   │
                   ▼
[3. Automated Diagnostic & Auto-Reconnect Timing]
                   │
                   ▼
[4. Stereo Speaker Channel Separation Test (L/R)]
                   │
                   ▼
[5. Offline Voice Recognition Test ("Testing 1 2 3")]
                   │
                   ▼
[6. Physical Hardware Button Test (Volume Up/Down)]
                   │
                   ▼
[7. Auto-Record to MySQL & CSV Export Option]
```

1. **Operator Authentication & Unit Identification:**
   - Operator enters their Operator ID.
   - Barcode scanner scans the unique Helmet Serial Number into the dashboard.
2. **Device Discovery & Automated Pairing:**
   - Helmet is set to pairing mode.
   - Operator clicks **Scan Bluetooth Devices**. The system discovers the unit and executes automated pairing.
3. **Diagnostic Phase:**
   - Evaluates signal strength (RSSI), verifies supported profiles (A2DP, HFP, AVRCP), and measures auto-reconnection time.
4. **Speaker Test:**
   - Plays audio through the headset. Operator confirms clear Left and Right channel audio.
5. **Microphone Test:**
   - Operator speaks *"Testing one two three"*. Vosk transcribes the input locally and validates audio capture.
6. **Button Test:**
   - Operator presses physical Volume (+) and Volume (-) buttons. CoreAudio sensors register state changes in real time.
7. **Report Submission:**
   - The inspection record is saved to the central MySQL database and added to daily yield metrics.

---

## 🗄️ Database Schema & Configuration

### Database Name: `studds_qc`
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Configuration (`db_config.json`)
The application looks for `db_config.json` in the same directory as the executable:

```json
{
    "host": "192.168.1.100",
    "port": 3306,
    "user": "qc_user",
    "password": "your_secure_password",
    "database": "studds_qc",
    "connection_timeout": 8
}
```

---

## 🚀 Installation & Development Setup

### Prerequisites
- **Operating System:** Windows 10 (64-bit Build 19041+) or Windows 11
- **Python:** Python 3.10 or 3.11 (64-bit)
- **Database:** MySQL 8.0+ or XAMPP MariaDB

### Local Setup
1. Clone or extract the repository.
2. Open Command Prompt / PowerShell in `01_Source_Code/`:
   ```cmd
   cd "01_Source_Code"
   ```
3. Install required Python packages:
   ```cmd
   pip install pywebview fastapi uvicorn bleak mysql-connector-python winsdk pydantic vosk python-multipart pycaw comtypes pyinstaller
   ```
4. Copy `db_config.example.json` to `db_config.json` and configure your MySQL credentials:
   ```cmd
   copy db_config.example.json db_config.json
   ```
5. Launch the application in development mode:
   ```cmd
   python desktop_app.py
   ```

---

## 📦 Build & Packaging Pipeline

### Step 1: Compile Standalone Executable
Run the automated build script inside the environment folder (`01_Source_Code` or `02_UAT`):

```cmd
build.bat
```

This executes PyInstaller with:
- `--add-data "vosk-model;vosk-model"` (bundles offline Vosk model)
- `--add-data "Stereo sound tiny test with clean channels (mp3cut.net).mp3;."`
- `--add-data "studds_qc_inspection.html;."`
- Collected binaries for `winsdk`, `bleak`, `webview`, `pycaw`, `vosk`, and `comtypes`.
- Output is generated in `dist\StuddsQC.exe`.

### Step 2: Generate No-Admin Setup Installer
1. Open `studds_installer.iss` in **Inno Setup Compiler**.
2. Click **Build > Compile** (or run `ISCC.exe studds_installer.iss`).
3. The generated installer will be saved to:
   ```text
   installer_output\StuddsQC_Setup_v1.0_NoAdmin.exe
   ```
4. **Key Installer Feature:** Configured with `PrivilegesRequired=lowest` to allow direct installation into `%LOCALAPPDATA%\StuddsQC` on factory floor workstations without requiring Windows Administrator credentials.

---

## 🔁 Release Promotion Lifecycle

```text
  [01_Source_Code]  ────────►  [02_UAT]  ────────►  [03_Production]
  (Active Dev DB)             (Staging DB)           (Live Central DB)
```

1. **Development (`01_Source_Code`):** Active feature development, bug fixes, and unit testing against local MySQL instances.
2. **Staging / Validation (`02_UAT`):** Tested by QC supervisors and line leads using test headsets and staging databases.
3. **Production Deployment (`03_Production`):** Verified builds promoted for factory line deployment.
   > [!IMPORTANT]
   > Never overwrite `03_Production/db_config.json` during file promotion to prevent accidental disruption to live database endpoints.

---

## 🛠️ Troubleshooting & Performance Notes

- **Microphone Detection Latency Optimization:**
  - Resolved driver teardown delays by preserving the Windows PnP audio endpoint during auto-reconnect (`toggle_hfp=False`).
  - Added 0ms visual indicators and cached microphone permissions in the UI to eliminate device enumeration freezes.
- **Port Conflict (8765):**
  - If the application fails to start with "Backend Did Not Start", check if port `8765` is in use:
    ```cmd
    netstat -ano | findstr :8765
    ```
- **Windows CoreAudio COM Issues:**
  - If button detection fails to start, verify that the Bluetooth headset is connected as the default Windows Audio Communications device.
- **Startup Error Logging:**
  - If the application encounters any unhandled startup exception, it logs detailed stack traces to `startup_error.log` and displays an explicit Windows Error Dialog.

---

## 📄 License & Proprietary Notice
© Studds Accessories Ltd. All rights reserved. Internal Quality Control Software.
