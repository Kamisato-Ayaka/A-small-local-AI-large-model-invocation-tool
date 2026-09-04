@echo off
REM Save and set codepage at very start before any chars are processed
for /f "tokens=2 delims=:" %%i in ('chcp') do set _OLDCP=%%i
chcp 437 >nul

cd /d "%~dp0"

echo ============================================
echo   CodeMate AI - Local AI Assistant
echo   (based on llama.cpp + PyQt5)
echo ============================================
echo.

REM ---------- Check Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    goto :END
)

REM ---------- Check PyQt5 (lightweight check) ----------
python -c "import PyQt5, requests, psutil" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing required packages...
    python -m pip install --quiet PyQt5 requests chardet psutil fastapi uvicorn qrcode Pillow pyngrok
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        goto :END
    )
)

REM ---------- Start App ----------
echo [START] Launching CodeMate AI...
python app.py
if errorlevel 1 (
    echo.
    echo [WARN] App exited with code %errorlevel%.
    goto :END
)

:END
REM Restore original codepage
if defined _OLDCP chcp %_OLDCP% >nul
