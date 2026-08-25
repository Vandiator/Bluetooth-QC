# Software Requirements Specification (SRS)
## Studds QC Bluetooth Device Inspection Application

---

## 1. Introduction

### 1.1 Purpose
This Software Requirements Specification (SRS) document details the functional, operational, and non-functional requirements for the **Studds QC Bluetooth Device Inspection Application**. The application is designed to automate and standardize the end-to-end quality control (QC) inspection routine for Bluetooth-enabled motorcycle helmets, audio headsets, and intercom accessories manufactured by **Studds Accessories Ltd.**

### 1.2 Scope
The application provides a standalone, offline-capable desktop inspection station running on Windows 10/11 64-bit workstations. It integrates:
- **Local Application Host:** PyWebView wrapping the Microsoft Edge Chromium runtime.
- **REST Backend Engine:** Asynchronous FastAPI server (`qc_bluetooth_api.py`) running locally on port `8765`.
- **Bluetooth Stack:** Microsoft Windows WinSDK Bluetooth APIs and `bleak` for dual Classic Bluetooth and BLE discovery, pairing, and service profiling.
- **Audio Playback Engine:** Windows Multimedia API (`winmm.dll` MCI) for stereo L/R channel separation testing.
- **Speech Recognition Engine:** Offline Vosk acoustic and language model for real-time speech-to-text verification.
- **Hardware Button Sensor:** CoreAudio endpoint volume level monitoring (`pycaw`) and low-level keyboard hook (`user32.dll`) for physical button detection.
- **Data Ingestion Layer:** Central MySQL server logging with duplicate MAC checking and native CSV export capabilities.

### 1.3 Target Audience
- **QC Line Operators & Inspectors:** Factory floor personnel conducting inspections.
- **QC Supervisors & Quality Engineers:** Personnel monitoring daily yield metrics and reviewing failed unit logs.
- **IT & Automation Engineers:** System administrators deploying, maintaining, and updating the application across workstation clusters.

---

## 2. Product Functions & Detailed Requirements

### 2.1 Operator Login & Barcode Scanning
- **REQ-AUTH-01:** The system shall prompt the operator for an **Operator ID** prior to initiating any testing routines.
- **REQ-BARCODE-01:** The system shall accept helmet serial number input via barcode scanner emulation (keyboard wedge) or manual input.
- **REQ-DUP-01:** Upon serial/MAC entry, the system shall query `/check_duplicate/{mac_address}` to verify whether the unit has previously been inspected and flag duplicate submissions.

### 2.2 Dual Bluetooth Scanning & Pairing
- **REQ-BT-01 (Dual Scanning):** The system shall simultaneously scan for Classic Bluetooth devices (using Windows WinSDK) and Bluetooth Low Energy devices (using Bleak).
- **REQ-BT-02 (Discovery Rendering):** Discovered devices shall be rendered with Signal Strength Indicator (RSSI), Device Name, and MAC Address.
- **REQ-BT-03 (Automated Pairing):** The system shall pair with the selected Bluetooth unit without requiring manual PIN entry dialogs where standard pairing protocols apply.
- **REQ-BT-04 (Diagnostic Profile Validation):** The system shall inspect and report supported Bluetooth profiles:
  - Audio Sink (A2DP: `0000110b-0000-1000-8000-00805f9b34fb`)
  - Hands-Free Profile (HFP: `0000111e-0000-1000-8000-00805f9b34fb`)
  - Headset Profile (HSP: `00001108-0000-1000-8000-00805f9b34fb`)
  - Audio/Video Remote Control Profile (AVRCP)
- **REQ-BT-05 (Reconnect Benchmark):** The system shall measure and log the auto-reconnection duration (in seconds) after pairing.

### 2.3 Audio Speaker Channel Separation Test
- **REQ-SPK-01 (MCI Playback):** The system shall play stereo channel separation audio using the native Windows MCI interface (`winmm.dll`) to ensure sub-10ms response times.
- **REQ-SPK-02 (Channel Isolation):** The playback asset shall clearly play audio through the **Left Channel**, pause, and then play through the **Right Channel**.
- **REQ-SPK-03 (Operator Evaluation):** The operator shall record a result of `PASSED`, `FAILED`, or `SKIPPED`.

### 2.4 Offline Microphone & Speech Recognition Test
- **REQ-MIC-01 (Offline Operation):** Speech recognition shall execute 100% offline using the bundled Vosk neural model (`vosk-model`).
- **REQ-MIC-02 (Fast Detection & 0ms Indicator):** The UI shall display an immediate loading spinner on 0ms tick upon completing diagnostics and maintain cached media permissions.
- **REQ-MIC-03 (Voice Command Verification):** The system shall capture 16kHz mono audio input and transcribe test phrases (e.g., *"testing one two three"*), displaying live confidence and transcript output.
- **REQ-MIC-04 (Audio Gateway Nudge):** The system shall automatically invoke `/nudge_mic` to activate the Windows Bluetooth Audio Gateway service if the headset microphone endpoint is dormant.

### 2.5 Physical Button & Volume Control Test
- **REQ-BTN-01 (Volume Event Sensing):** The system shall detect physical Volume Up (+) and Volume Down (-) button presses via Windows CoreAudio `IAudioEndpointVolume` peak level change polling.
- **REQ-BTN-02 (Media Key Hook):** The system shall detect Play/Pause and Media Track buttons using a low-level keyboard hook (`WH_KEYBOARD_LL`).
- **REQ-BTN-03 (Visual Feedback):** The dashboard shall display live green indicators when button actuation events are detected.

### 2.6 Central Data Persistence & Export
- **REQ-DATA-01 (MySQL Storage):** The application shall persist inspection records to the MySQL `inspection_logs` table.
- **REQ-DATA-02 (Connection Resilience):** The system shall handle database disconnections gracefully, maintaining a visual indicator in the top navbar and writing error logs if connection fails.
- **REQ-DATA-03 (CSV Export):** The system shall support exporting filtered inspection yield reports to CSV via native Windows Save Dialog (`DesktopApi.save_csv`).

---

## 3. External Interface Requirements

### 3.1 Hardware Interfaces
- **Target Device:** Studds Bluetooth Helmet Headset / Intercom Module.
- **Workstation Host:** Windows PC with built-in or USB Bluetooth 4.2 / 5.0+ adapter.
- **Peripheral Devices:** 1D/2D Barcode Scanner (USB / HID Keyboard Wedge).

### 3.2 Software Interfaces
- **Microsoft Windows WinSDK (C++ / WinRT COM):** `winsdk.windows.devices.bluetooth`, `winsdk.windows.devices.radios`.
- **Windows CoreAudio:** `pycaw`, `comtypes`.
- **Windows Multimedia API:** `winmm.dll` MCI commands.
- **Offline STT Engine:** Vosk API (`vosk.Model`, `vosk.KaldiRecognizer`).
- **Database Engine:** MySQL 8.0+ / MariaDB via `mysql-connector-python`.

---

## 4. Non-Functional Requirements

### 4.1 Performance & Responsiveness
- **Local API Latency:** REST endpoints (`/scan`, `/health`, `/analyze_mic`) shall respond in $< 50\text{ ms}$ under normal workstation conditions.
- **Speech STT Latency:** Offline Vosk speech processing for a 3-second audio sample shall complete in $< 800\text{ ms}$.
- **Startup Time:** The desktop application window shall open and verify backend health within 3 seconds.

### 4.2 Reliability & Fault Tolerance
- **Offline Autonomy:** Core Bluetooth, audio, microphone, and button tests shall function without an active internet connection.
- **Startup Exception Safety:** Startup failures shall display a native Windows MessageBox (`MB_ICONERROR`) and append stack traces to `startup_error.log`.

### 4.3 Security & Installation Privileges
- **Zero Administrator Rights Required:** The application installer shall install into `{localappdata}\StuddsQC` with `PrivilegesRequired=lowest`, allowing non-privileged factory operator accounts to install and run the application.
- **External Configuration:** Database credentials shall be stored in external `db_config.json`, isolating secrets from the compiled binary.
