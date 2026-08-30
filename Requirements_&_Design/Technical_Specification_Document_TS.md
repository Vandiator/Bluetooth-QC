# Complete & Plain-English Technical Specification Document (TS)
## Project: Studds QC Bluetooth Device Inspection Application
**Document Reference:** STUDDS-QC-TS-DETAILED-V1.0  
**Target Audience:** Software Engineers, QA Leads, Line Supervisors, IT Technicians, and Non-Technical Stakeholders  
**Status:** Approved & Production Baseline  

---

## 📖 Welcome & How to Read This Document

> **Note for Non-Technical Readers:**  
> This document is written in **simple, plain English**. You do not need a computer science degree or programming experience to understand how this system works. Every file, function, and configuration block is explained with real-world analogies, plain English breakdowns, and exact **"How to Change This"** step-by-step recipes so anyone can modify application settings (like database passwords, test voice phrases, audio tracks, or window sizes) safely.

---

## 📑 Table of Contents
1. [System Architecture in Simple Terms](#1-system-architecture-in-simple-terms)
2. [Project File Map & What Each File Does](#2-project-file-map--what-each-file-does)
3. [Line-by-Line Code Breakdown & Customization Recipes](#3-line-by-line-code-breakdown--customization-recipes)
   - [3.1 `desktop_app.py` (The Application Launcher & Window)](#31-desktop_apppy-the-application-launcher--window)
   - [3.2 `db_config.json` (Database Settings)](#32-db_configjson-database-settings)
   - [3.3 `speaker_test.py` (Speaker Left/Right Audio Player)](#33-speaker_testpy-speaker-leftright-audio-player)
   - [3.4 `mic_test.py` (Offline Speech Recognition Engine)](#34-mic_testpy-offline-speech-recognition-engine)
   - [3.5 `button_detector.py` (Physical Helmet Button Sensor)](#35-button_detectorpy-physical-helmet-button-sensor)
   - [3.6 `Bluetooth_testing.py` (Bluetooth Hardware Drivers)](#36-bluetooth_testingpy-bluetooth-hardware-drivers)
   - [3.7 `qc_bluetooth_api.py` (Core Backend Engine & Database Bridge)](#37-qc_bluetooth_apipy-core-backend-engine--database-bridge)
   - [3.8 `studds_qc_inspection.html` (Frontend User Interface Dashboard)](#38-studds_qc_inspectionhtml-frontend-user-interface-dashboard)
4. [Step-by-Step Recipes: How to Change Common Settings](#4-step-by-step-recipes-how-to-change-common-settings)
   - [Recipe 1: How to Change the Database IP / Password](#recipe-1-how-to-change-the-database-ip--password)
   - [Recipe 2: How to Change the Voice Words the Helmet Listens For](#recipe-2-how-to-change-the-voice-words-the-helmet-listens-for)
   - [Recipe 3: How to Change the Speaker Audio Test Song/Track](#recipe-3-how-to-change-the-speaker-audio-test-songtrack)
   - [Recipe 4: How to Change the Application Window Title or Size](#recipe-4-how-to-change-the-application-window-title-or-size)
   - [Recipe 5: How to Change the Port Number if 8765 is Blocked](#recipe-5-how-to-change-the-port-number-if-8765-is-blocked)
5. [How to Rebuild & Create a New `.exe` Installer](#5-how-to-rebuild--create-a-new-exe-installer)
6. [Troubleshooting & Emergency Fixes](#6-troubleshooting--emergency-fixes)

---

## 1. System Architecture in Simple Terms

Think of the application like a restaurant with 3 main parts:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. THE FRONTEND UI (The Customer Dining Room): `studds_qc_inspection.html`   │
│    - What the operator sees on the screen (buttons, progress bars, tables). │
│    - Runs inside a native Windows window (PyWebView Edge Chromium).         │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Speaks via Internal Web Calls (Port 8765)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. THE BACKEND ENGINE (The Kitchen & Chef): `qc_bluetooth_api.py`           │
│    - Takes orders from the UI, controls the computer's Bluetooth radio,     │
│      plays speaker sound files, listens to the microphone, and checks keys. │
└──────────┬───────────────────┬───────────────────┬───────────────────┬──────┘
           │                   │                   │                   │
           ▼                   ▼                   ▼                   ▼
┌────────────────────┐┌──────────────────┐┌──────────────────┐┌───────────────┐
│ Bluetooth Engine   ││ Vosk Speech AI   ││ Sound Player     ││ Button Sensor │
│ `Bluetooth_        ││ `mic_test.py`    ││ `speaker_test.py`││ `button_      │
│  testing.py`       ││ (Offline STT)    ││ (Left/Right Audio││  detector.py` │
└──────────┬─────────┘└──────────────────┘└──────────────────┘└───────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. THE CENTRAL DATABASE (The Filing Cabinet): MySQL Server                  │
│    - Stores records of every helmet tested: Serial Number, MAC, Date, Pass. │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Project File Map & What Each File Does

| File Name | Plain English Purpose | If you want to change... |
| :--- | :--- | :--- |
| **`desktop_app.py`** | The main ignition key. Starts the backend server and opens the Windows desktop window. | Window dimensions (width/height), title, or startup checks. |
| **`db_config.json`** | The database connection notebook. | Database IP address, username, password, or database name. |
| **`speaker_test.py`** | The audio cassette player. Plays left and right audio cues into the helmet speakers. | Playback speed, audio file path, or sound controls. |
| **`mic_test.py`** | The digital ear. Listens to what the operator says into the helmet microphone completely offline. | Accepted voice test phrases (e.g., *"hello studds"*). |
| **`button_detector.py`** | The button watcher. Detects when Volume Up, Volume Down, or Play buttons are pressed. | Volume detection sensitivity or key codes. |
| **`Bluetooth_testing.py`** | The radio controller. Searches for nearby Bluetooth helmets and pairs with them. | Scan timeout or Bluetooth discovery filters. |
| **`qc_bluetooth_api.py`** | The master orchestrator. Connects the buttons on the screen to the hardware and MySQL. | Test logic, API endpoints, or database columns. |
| **`studds_qc_inspection.html`** | The visual screen. Contains all the HTML, CSS, and JavaScript buttons and visualizers. | Colors, layout, text labels, or screen logo. |
| **`StuddsQC.spec`** | The packaging recipe for PyInstaller to build a standalone single `.exe` file. | Files bundled into the compiled application. |
| **`build.bat`** | The 1-click build script. Run this in Command Prompt to compile the code. | Nothing needed; double-click to compile! |
| **`studds_installer.iss`** | The setup installer builder for Inno Setup. Makes a friendly setup wizard. | Installer icon, destination folder, or version number. |

---

## 3. Line-by-Line Code Breakdown & Customization Recipes

---

### 3.1 `desktop_app.py` (The Application Launcher & Window)

This file is the **entry point** when someone clicks the application icon.

#### Detailed Code Explanation:

```python
# Lines 1-8: Importing required standard libraries
import os             # Works with computer files and folders
import sys            # Accesses Python runtime settings and command line
import threading      # Allows running multiple tasks at the exact same time
import time           # Handles delays, timestamps, and timeouts
import traceback      # Captures full error messages if something crashes
import urllib.request # Performs internal health check calls to the local server
import webview        # Creates the native Microsoft Edge desktop window
import uvicorn        # The fast web server engine that runs our backend API
```
* **Why this is here:** These are the standard tools Python needs to manage files, handle time, run parallel background tasks, and draw a window.

```python
# Lines 14: Granting automatic microphone permissions
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--use-fake-ui-for-media-stream --enable-media-stream"
```
* **What this does:** When a browser accesses a microphone, it usually pops up an annoying *"Do you want to allow this app to use your microphone?"* prompt. This line tells the Edge Chromium engine: *"Always auto-allow the helmet microphone without asking the operator every time."*

```python
# Lines 16-24: Finding where the app is installed
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

current_folder = get_app_dir()
sys.path.insert(0, current_folder)
LOG_PATH = os.path.join(current_folder, "startup_error.log")
```
* **What this does:** It checks whether the code is running as a loose `.py` script or compiled as an `.exe`. It makes sure the computer looks in the right folder for settings and crash logs (`startup_error.log`).

```python
# Lines 27-49: Fatal Error Popup Box
def _show_fatal_error(title: str, message: str) -> None:
    ...
    ctypes.windll.user32.MessageBoxW(0, full_message, title, 0x10) # 0x10 is MB_ICONERROR
```
* **What this does:** If the database crashes or port 8765 is blocked, non-technical users won't see a black terminal screen. This function pops up a standard Windows error dialog box with an **[OK]** button and saves the problem to `startup_error.log`.

```python
# Lines 69-82: Starting the Backend Web Engine
def start_backend_server():
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="error")
```
* **What this does:** Starts the local API server on `127.0.0.1` (your own PC) on port `8765`.
* **How to change the port:** If port `8765` is busy, change `8765` here and in `studds_qc_inspection.html`.

```python
# Lines 102-121: The Native Windows File Save Dialog
class DesktopApi:
    def save_csv(self, filename: str, content: str) -> bool:
        ...
```
* **What this does:** When an inspector clicks **"Export to CSV"**, this triggers the official Windows *"Save As..."* window so they can pick any folder (like Desktop or a USB drive) to save the spreadsheet.

```python
# Lines 136-145: Opening the Desktop Window
    window = webview.create_window(
        title="Studds QC Testing Dashboard",
        url="http://127.0.0.1:8765/",
        width=1100,
        height=800,
        resizable=True,
        js_api=desktop_api
    )
    webview.start()
```
* **What this does:** Opens an 1100x800 pixel window titled *"Studds QC Testing Dashboard"* showing our inspection screen.
* **How to change window size:** Change `width=1100` and `height=800` to whatever size you prefer (e.g., `width=1280, height=900`).

---

### 3.2 `db_config.json` (Database Settings)

This is a simple text configuration file that sits directly beside the application `.exe`. You can open and edit it using **Notepad**.

```json
{
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "studds_qc",
    "connection_timeout": 8
}
```

#### Field-by-Field Breakdown:
1. **`"host"`**: The IP address of the MySQL database server.
   - Use `"localhost"` if MySQL (like XAMPP) is running on the **same computer**.
   - Use `"192.168.1.100"` (or your central server IP) if the database is on a **central factory server**.
2. **`"port"`**: Always `3306` for standard MySQL.
3. **`"user"`**: The database login name (e.g., `"root"` or `"qc_operator"`).
4. **`"password"`**: The database password. If there is no password, leave it empty `""`.
5. **`"database"`**: The database catalog name. Default is `"studds_qc"`.
6. **`"connection_timeout"`**: Number of seconds the app will wait for the database before warning you. Set to `8` seconds.

---

### 3.3 `speaker_test.py` (Speaker Left/Right Audio Player)

This module handles playing sound directly through Windows Multimedia (`winmm.dll`) without opening any external media players.

#### Detailed Code Explanation:

```python
# Lines 22-31: Short-Path Fix for Special Folder Names
def get_short_path_name(long_name: str) -> str:
    ...
    res = kernel32.GetShortPathNameW(long_name, buf, 260)
```
* **Why this is here:** Windows sometimes fails to play audio if the folder path has spaces or brackets (like `C:\Program Files (x86)\Studds`). This converts paths into safe 8.3 format (like `C:\PROGRA~2\Studds`).

```python
# Lines 123-146: Starting the Audio Test
def start_speaker_test(mp3_path: str) -> Dict[str, Any]:
    ...
    err, err_msg = _mci_send(f'open "{short_path}" type mpegvideo alias speaker_mp3')
    err, err_msg = _mci_send("play speaker_mp3")
```
* **What this does:** Commands the soundcard to open the MP3 audio file and start playing immediately.
* **Audio Track Behavior:** The included MP3 track plays sound in the **Left Ear** first, pauses for half a second, then plays sound in the **Right Ear**.

---

### 3.4 `mic_test.py` (Offline Speech Recognition Engine)

This file contains the **artificial intelligence voice recognition engine (Vosk)** that listens to the operator's voice through the helmet microphone. It works **100% offline without the internet**.

#### Detailed Code Explanation:

```python
# Lines 94-115: Loading the Offline Neural Speech Model
VOSK_MODEL_PATH = os.path.join(get_bundle_dir(), "vosk-model")
speech_model = vosk.Model(VOSK_MODEL_PATH)
```
* **What this does:** Loads the offline acoustic language model from the `vosk-model` folder into computer memory.

```python
# Lines 146-149: Target Test Phrases (The Magic Pass Words)
# Define the target phrases to accept as a PASS
target_phrases = ["hello studds", "studds", "testing", "hello"]
passed = any(phrase in transcript for phrase in target_phrases)
```
* **What this does:** When the operator speaks into the helmet, the engine transcribes the words into text. If the operator says **"hello studds"**, **"studds"**, **"testing"**, or **"hello"**, the test automatically **PASSES**!
* **How to change accepted words:** If you want the operator to say *"helmet test pass"*, simply add `"helmet test pass"` to this list:
  ```python
  target_phrases = ["hello studds", "studds", "testing", "hello", "helmet test pass"]
  ```

```python
# Lines 244-256: The Microphone Nudge Helper
async def nudge_mic_device(mac: str, force_toggle: bool = True) -> Dict[str, Any]:
    ...
```
* **What this does:** Sometimes Windows puts Bluetooth helmet microphones into "sleep mode" to save battery. This function sends a gentle electric wake-up nudge to Windows to turn on the Hands-Free Audio Profile (HFP).

---

### 3.5 `button_detector.py` (Physical Helmet Button Sensor)

This file listens for physical buttons pressed on the helmet: **Volume (+)**, **Volume (-)**, and **Play/Pause**.

#### Detailed Code Explanation:

```python
# Lines 64-66: Windows Key Codes for Buttons
VK_VOLUME_DOWN = 0xAE        # Virtual Key Code for Volume Down
VK_VOLUME_UP = 0xAF          # Virtual Key Code for Volume Up
VK_MEDIA_PLAY_PAUSE = 0xB3   # Virtual Key Code for Play/Pause Button
```
* **What this does:** Identifies the exact electronic signals Windows receives when someone presses the volume buttons.

```python
# Lines 203-214: CoreAudio Volume Polling (PyCaw)
current_volume = volume_ctrl.GetMasterVolumeLevelScalar()
if diff > 0.005:
    button_state["volume_up"] = True
    print("Volume Up detected")
elif diff < -0.005:
    button_state["volume_down"] = True
    print("Volume Down detected")
```
* **What this does:** Measures the exact master volume level. If the volume increases by even 0.5%, it turns on the green **Volume Up** light on the screen. If it decreases, it turns on the green **Volume Down** light.

---

### 3.6 `Bluetooth_testing.py` (Bluetooth Hardware Drivers)

This file is responsible for scanning the airwaves for nearby Bluetooth devices and pairing with them.

#### Detailed Code Explanation:
* **`scan_ble_devices()`**: Uses the `bleak` library to search for Bluetooth Low Energy signals.
* **`scan_classic_devices()`**: Uses Windows WinSDK to search for classic audio Bluetooth devices.
* **`pair_device(mac_address)`**: Sends a connection request to the helmet so Windows pairs with it automatically without needing a PIN code.
* **`measure_reconnect_time()`**: Disconnects and reconnects the helmet to time how many seconds it takes to re-establish a link (benchmark quality test).

---

### 3.7 `qc_bluetooth_api.py` (Core Backend Engine & Database Bridge)

This is the largest file in the project. It connects everything together using **FastAPI** web routes.

#### Key API Endpoints & What They Do:

| Endpoint | Method | What Happens Under the Hood |
| :--- | :--- | :--- |
| **`/health`** | `GET` | Quickly answers `"healthy"`. Used by the startup launcher to know the server is ready. |
| **`/scan`** | `GET` | Starts Bluetooth discovery and returns a list of found helmets with signal strength (RSSI). |
| **`/test/{address}`** | `POST` | Pairs the computer with the selected helmet and validates audio profiles. |
| **`/analyze_mic`** | `POST` | Receives voice recording from the browser, runs Vosk STT, and returns the transcript. |
| **`/speaker_test/start`** | `POST` | Plays the stereo audio file into the helmet speakers. |
| **`/button_test/status`** | `GET` | Returns whether Volume Up, Down, or Play buttons were pressed (`true`/`false`). |
| **`/check_duplicate/{mac}`**| `GET` | Queries MySQL to see if this helmet was already tested today. |
| **`/save_report`** | `POST` | Inserts the final test result (Operator ID, Serial Number, MAC, PASS/FAIL) into MySQL. |
| **`/reports`** | `GET` | Loads past inspection history for the table at the bottom of the screen. |

---

### 3.8 `studds_qc_inspection.html` (Frontend User Interface Dashboard)

This single HTML file contains all the **visual buttons, badges, audio visualizers, and tables**.

#### Key Sections:
1. **Header (Lines 1–150):** Shows the Studds logo, operator badge, database status (🟢 Online / 🔴 Offline), and daily pass rate counters.
2. **Left Panel (Lines 151–400):** Serial barcode input box and the Bluetooth device scanner table.
3. **Right Panel (Lines 401–800):** The 3 test boxes:
   - **Speaker Test Box:** Play button and green/red Pass/Fail buttons.
   - **Microphone Test Box:** Live microphone volume meter and speech transcript bubble.
   - **Button Test Box:** Green glowing lights for Vol (+), Vol (-), and Play.
4. **Bottom Panel (Lines 801–1200):** Table showing historical inspection results with an **"Export to CSV"** button.

---

## 4. Step-by-Step Recipes: How to Change Common Settings

Here are straightforward instructions for common changes:

---

### Recipe 1: How to Change the Database IP / Password
1. Open the folder where the application is installed.
2. Find the file named **`db_config.json`**.
3. Right-click it and select **Open with $\rightarrow$ Notepad**.
4. Change the values:
   ```json
   {
       "host": "192.168.1.50",
       "port": 3306,
       "user": "qc_admin",
       "password": "MySecretPassword123",
       "database": "studds_qc",
       "connection_timeout": 8
   }
   ```
5. Click **File $\rightarrow$ Save** and close Notepad.
6. Restart the Studds QC application. That's it!

---

### Recipe 2: How to Change the Voice Words the Helmet Listens For
1. Open `01_Source_Code\mic_test.py` in Notepad or VS Code.
2. Go to **Line 147**.
3. Look for this line:
   ```python
   target_phrases = ["hello studds", "studds", "testing", "hello"]
   ```
4. Add your new words in quotes separated by commas:
   ```python
   target_phrases = ["hello studds", "studds", "testing", "hello", "motorcycle", "pass"]
   ```
5. Save the file.

---

### Recipe 3: How to Change the Speaker Audio Test Song/Track
1. Take your new sound file (must be `.mp3` format).
2. Name it **`Stereo sound tiny test with clean channels.mp3`** (or change the name in `01_Source_Code\qc_bluetooth_api.py` line 180).
3. Place your new MP3 file into `01_Source_Code\`.
4. Rebuild the application using `build.bat` (see Section 5).

---

### Recipe 4: How to Change the Application Window Title or Size
1. Open `01_Source_Code\desktop_app.py`.
2. Go to **Lines 138–142**:
   ```python
   window = webview.create_window(
       title="Studds QC Testing Dashboard",
       url="http://127.0.0.1:8765/",
       width=1100,
       height=800,
       resizable=True,
       js_api=desktop_api
   )
   ```
3. Change `title="Studds QC Testing Dashboard"` to your desired title.
4. Change `width=1100` and `height=800` to your desired window size.
5. Save the file.

---

### Recipe 5: How to Change the Port Number if 8765 is Blocked
If another program on the factory computer uses port 8765:
1. In `01_Source_Code\desktop_app.py`, change `8765` to `8999` on lines 76, 93, 131, and 139.
2. In `01_Source_Code\studds_qc_inspection.html`, search for `8765` and replace it with `8999`.
3. Save both files.

---

## 5. How to Rebuild & Create a New `.exe` Installer

Whenever you modify any Python or HTML code, you can easily generate a fresh standalone `.exe` and setup installer using simple double-clicks:

### Method 1: The 1-Click Direct Double-Click (Easiest Method)

#### Step 1: Create the `.exe` (Double-Click `build.bat`)
1. Open the folder `01_Source_Code` in Windows File Explorer.
2. **Directly double-click on `build.bat`**.
3. A black window will open and automatically bundle all Python code, Vosk neural models, and audio files.
4. Wait 1–2 minutes until it finishes. The newly compiled executable is created at:
   ```text
   01_Source_Code\dist\StuddsQC.exe
   ```

#### Step 2: Create the Setup Installer (Double-Click `studds_installer.iss`)
1. In the same `01_Source_Code` folder, **directly double-click on `studds_installer.iss`** (it will open in Inno Setup Compiler).
2. In the top toolbar, click the green **Run** / **Compile** button (or press `Ctrl + F9`).
3. Inno Setup will package everything into the final setup installer:
   ```text
   01_Source_Code\installer_output\Studds_QC_Setup_v1.0.exe
   ```
4. Double-click this setup file to install the updated app on any factory laptop without needing administrator rights!

---

### Method 2: Via Command Prompt (Alternative)
1. Open the folder `01_Source_Code`.
2. Click inside the top address bar, type **`cmd`**, and press **Enter**.
3. In the Command Prompt window, type:
   ```cmd
   build.bat
   ```
4. Press **Enter** to compile.

---

## 6. Troubleshooting & Emergency Fixes

| Problem Observed | Plain English Cause | Easy Fix |
| :--- | :--- | :--- |
| **Window says "Backend Did Not Start"** | Port 8765 is blocked, or Python libraries are missing. | 1. Open Task Manager and close any duplicate `StuddsQC.exe` processes.<br>2. Open `startup_error.log` in Notepad to see the exact crash line. |
| **Top bar shows 🔴 Database Offline** | `db_config.json` has the wrong password or MySQL is stopped. | 1. Ensure XAMPP or MySQL server is turned ON (running).<br>2. Open `db_config.json` and verify the IP and password. |
| **Microphone test always says "FAIL"** | Operator spoke too softly or model was missing. | 1. Make sure the operator speaks clearly within 5 cm of the mic.<br>2. Verify `vosk-model` folder exists inside the installation directory. |
| **Bluetooth helmet won't appear in list** | Helmet is not in pairing mode or Bluetooth is OFF. | 1. Hold helmet power button for 5 seconds until LED flashes blue/red.<br>2. Verify Windows Bluetooth toggle is switched ON in Windows Settings. |
