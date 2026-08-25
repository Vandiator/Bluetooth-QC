@echo off
REM ============================================================
REM Studds QC Desktop App - Build Script
REM ============================================================

echo 1. Installing all required Python dependencies...
REM Added 'vosk' and 'python-multipart' for offline speech recognition
REM Added 'pycaw' and 'comtypes' for button test volume detection (Core Audio endpoint level polling)
python -m pip install pyinstaller pywebview fastapi uvicorn bleak mysql-connector-python winsdk pydantic vosk python-multipart pycaw comtypes --quiet
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install Python packages.
    echo Check your internet connection or Python path.
    pause
    exit /b 1
)

echo.
echo 2. Cleaning old build files and Building StuddsQC.exe ...
echo (This will take a few minutes as it bundles the offline speech model)
echo.

pyinstaller --name "StuddsQC" --onefile ^
  --clean ^
  --add-data "vosk-model;vosk-model" ^
  --add-data "Stereo sound tiny test with clean channels (mp3cut.net).mp3;." ^
  --add-data "studds_qc_inspection.html;." ^
  --hidden-import=mic_test ^
  --hidden-import=speaker_test ^
  --hidden-import=webview ^
  --hidden-import=webview.platforms.edgechromium ^
  --hidden-import=uvicorn.logging ^
  --hidden-import=uvicorn.loops ^
  --hidden-import=uvicorn.loops.auto ^
  --hidden-import=uvicorn.protocols ^
  --hidden-import=uvicorn.protocols.http ^
  --hidden-import=uvicorn.protocols.http.auto ^
  --hidden-import=uvicorn.protocols.websockets ^
  --hidden-import=uvicorn.protocols.websockets.auto ^
  --hidden-import=uvicorn.lifespan ^
  --hidden-import=uvicorn.lifespan.on ^
  --collect-all winsdk ^
  --collect-all bleak ^
  --collect-all webview ^
  --collect-all mysql.connector ^
  --collect-all mysql.connector.plugins ^
  --collect-all vosk ^
  --collect-all pycaw ^
  --collect-all comtypes ^
  --hidden-import=mysql.connector.locales.eng ^
  desktop_app.py

if not exist "dist\StuddsQC.exe" (
    echo.
    echo ============================================================
    echo PyInstaller failed. Scroll up to see the error.
    echo ============================================================
    pause
    exit /b 1
)

echo.
echo ============================================================
echo SUCCESS: dist\StuddsQC.exe generated successfully!
echo.
echo You can now close this window and compile your Inno Setup 
echo installer again.
echo ============================================================
pause