# Standard Operating Procedure (SOP) & User Manual
## Studds Bluetooth Helmet Quality Control Inspection

---

## 1. Safety, Prerequisites & Workstation Setup

### 1.1 Equipment Checklist
1. **Workstation PC:** Windows 10/11 64-bit PC with Bluetooth adapter enabled.
2. **Barcode Scanner:** USB / Wireless handheld barcode scanner.
3. **Target Device:** Fully charged Studds Bluetooth Helmet / Intercom Unit.
4. **App Installation:** Ensure the **Studds QC Application** is launched and the top-right indicator shows **Database Connected**.

---

## 2. Standard Inspection Workflow

```text
[1. Operator Login & Helmet Barcode Scan]
                   │
                   ▼
[2. Bluetooth Discovery & Automated Pairing]
                   │
                   ▼
[3. Automated Hardware Diagnostic Check]
                   │
                   ▼
[4. Speaker Channel Separation Test (L/R)]
                   │
                   ▼
[5. Offline Microphone Voice Test]
                   │
                   ▼
[6. Hardware Button & Volume Test]
                   │
                   ▼
[7. Review & Submit QC Inspection Log]
```

---

## 3. Step-by-Step Operator Instructions

### Step 1: Login & Barcode Scanning
1. Open the **Studds QC Inspection** application.
2. Enter your **Operator ID** in the top header section.
3. Scan or type the **Helmet Serial Number barcode** into the serial number field.
4. The system will verify if the serial/MAC was already tested. If a duplicate is detected, a warning banner will appear.

### Step 2: Bluetooth Device Discovery & Pairing
1. Switch the helmet headset into **Bluetooth Pairing Mode** (hold the power button until the indicator LED flashes Red and Blue).
2. On the dashboard, click **Scan Bluetooth Devices**.
3. Locate the device name (e.g., *Studds BT*, *Rydio*, etc.) from the list and click **Pair & Connect**.
4. The system will establish the connection and automatically activate audio and hands-free profiles.

### Step 3: Automated Diagnostic Check
1. The dashboard opens a live diagnostic overlay.
2. The application verifies:
   - Signal Strength (RSSI level)
   - Profile Support (A2DP Audio Sink, HFP Hands-Free, AVRCP Control)
   - Auto-reconnect latency measurement.
3. Once completed, the diagnostic status will show **PASSED**.

### Step 4: Speaker Channel Separation Test
1. Click **Start Speaker Test**.
2. Listen carefully through the helmet speakers:
   - Voice prompt announces: *"Left Channel"* (Audio should ONLY play in the left ear).
   - Voice prompt announces: *"Right Channel"* (Audio should ONLY play in the right ear).
3. If both channels play clearly and separately, click **PASS**. If audio is distorted, missing in one ear, or bleeding, click **FAIL**.

### Step 5: Offline Microphone Voice Test
1. The dashboard will automatically detect the Bluetooth headset microphone.
2. Click **Start Voice Test**.
3. Speak clearly into the helmet microphone: *"Testing one two three"*.
4. Observe the real-time transcript box. When the text matches the spoken phrase and audio clarity is verified, click **PASS**.

### Step 6: Physical Hardware Button Test
1. Click **Start Button Test**.
2. Press the physical **Volume Up (+)** button on the helmet headset — the *Volume Up* indicator card turns green.
3. Press the physical **Volume Down (-)** button — the *Volume Down* indicator card turns green.
4. (Optional) Press the **Play / Pause** button.
5. When all required button indicators illuminate, click **PASS**.

### Step 7: Final Submission
1. Confirm that all test sections display green **PASS** badges.
2. Click **Submit QC Record**.
3. The inspection record is instantly stored in the central database, and the form resets ready for the next helmet.

---

## 4. Supervisor Yield Auditing & CSV Export
1. Click on the **Inspection Reports** tab in the sidebar navigation.
2. Filter records by Date, Operator ID, or Status (`PASS` / `FAIL`).
3. Click **Export CSV** to open the Windows Save Dialog and save the complete quality audit report to a local spreadsheet.
