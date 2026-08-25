# Environment Architecture & Deployment Guide
## Studds QC Bluetooth Device Inspection Application

---

## 1. Multi-Tier Environment Organization

The application uses an isolated 3-tier folder structure designed for structured development, staging validation, and live factory floor deployment:

```text
📁 Bluetooth QC Application/
│
├── 📁 Requirements_&_Design/       # Technical specs, architecture docs, SOPs, optimization reports
│
├── 📁 01_Source_Code/              # Tier 1: Active Development Environment (Dev DB)
│   ├── desktop_app.py
│   ├── qc_bluetooth_api.py
│   ├── Bluetooth_testing.py
│   ├── button_detector.py
│   ├── mic_test.py
│   ├── speaker_test.py
│   ├── studds_qc_inspection.html
│   ├── db_config.json              # Configured for Local / Dev MySQL
│   ├── vosk-model/
│   ├── build.bat
│   └── studds_installer.iss
│
├── 📁 02_UAT/                      # Tier 2: User Acceptance Testing (Staging DB)
│   ├── (Promoted code from 01_Source_Code)
│   ├── db_config.json              # Configured for Staging / UAT MySQL
│   └── Requirements_&_Design/
│
└── 📁 03_Production/               # Tier 3: Live Production Environment (Prod DB)
    ├── db_config.json              # Configured for Live Production Central MySQL
    └── (Verified release packages & installers)
```

---

## 2. Environment Configuration (`db_config.json`)

The database connection parameters are externalized in `db_config.json` next to the executable. This allows administrators to update database hosts and credentials without recompiling the application binary.

### Example `db_config.json`:
```json
{
    "host": "192.168.1.100",
    "port": 3306,
    "user": "qc_admin",
    "password": "your_secure_password",
    "database": "studds_qc",
    "connection_timeout": 8
}
```

> [!CAUTION]
> **CRITICAL CODE PROMOTION RULE:**
> When promoting updated `.py` scripts or `.html` dashboard files between environments (`01_Source_Code` ➔ `02_UAT` ➔ `03_Production`), **NEVER overwrite the target environment's `db_config.json`**. Each environment must retain its isolated database endpoint.

---

## 3. Build & Packaging Instructions

### Step 1: Compile Standalone Executable via PyInstaller
1. Open PowerShell or Command Prompt.
2. Navigate to the desired environment directory:
   ```cmd
   cd "01_Source_Code"
   ```
3. Run the automated build script:
   ```cmd
   build.bat
   ```
4. The script:
   - Installs required Python dependencies (`pyinstaller`, `pywebview`, `fastapi`, `uvicorn`, `bleak`, `mysql-connector-python`, `winsdk`, `vosk`, `pycaw`, `comtypes`).
   - Bundles the offline Vosk speech model, reference MP3 test audio, and HTML UI into `dist\StuddsQC.exe`.

### Step 2: Compile Non-Admin Setup Installer via Inno Setup
1. Launch **Inno Setup Compiler**.
2. Open `studds_installer.iss`.
3. Click **Compile** (or run `ISCC.exe studds_installer.iss`).
4. Output installer is generated in:
   ```text
   installer_output\StuddsQC_Setup_v1.0_NoAdmin.exe
   ```

---

## 4. Factory Floor Workstation Deployment

1. Copy `StuddsQC_Setup_v1.0_NoAdmin.exe` to a USB drive or local network share.
2. Run the installer on the target factory workstation PC.
3. **No Administrator Rights Needed:**
   - The installer installs directly into `%LOCALAPPDATA%\StuddsQC` because `PrivilegesRequired=lowest` is configured in `studds_installer.iss`.
   - Creates a Start Menu shortcut and an optional Desktop shortcut.
4. Verify that `db_config.json` in `%LOCALAPPDATA%\StuddsQC` points to the correct production MySQL database server.
5. Launch **Studds QC Inspection** from the desktop shortcut.
