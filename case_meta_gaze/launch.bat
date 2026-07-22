@echo off
chcp 65001 >nul
:: ── Meta Orion Gaze Reels — Windows launcher ──────────────────────────────────
:: Double-click this file to install dependencies and run the prototype.

cd /d "%~dp0"

echo.
echo   ╔══════════════════════════════════════╗
echo   ║   Meta Orion — Gaze Reels Prototype  ║
echo   ╚══════════════════════════════════════╝
echo.

:: ── Check Python 3 ────────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py -3 --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo   ✗  Python 3 not found.
        echo.
        echo   Please install Python 3 from https://www.python.org/downloads/
        echo   Make sure to check "Add Python to PATH" during installation.
        echo   Then double-click this file again.
        echo.
        pause
        exit /b 1
    )
    set PYTHON=py -3
) else (
    set PYTHON=python
)

for /f "tokens=*" %%i in ('%PYTHON% --version') do echo   ✓  %%i found

:: ── Install dependencies ──────────────────────────────────────────────────────
echo   →  Installing dependencies (first run may take ~2 minutes)...
%PYTHON% -m pip install --quiet --upgrade pip
%PYTHON% -m pip install --quiet -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo   ✗  Failed to install dependencies.
    echo      Try running: pip install mediapipe opencv-python numpy Pillow
    pause
    exit /b 1
)

echo   ✓  Dependencies ready.
echo.
echo   ══════════════════════════════════════════
echo    Controls:
echo    * Look at video  →  Play
echo    * Look away      →  Pause
echo    * Close eyes 2s  →  Next reel
echo    * Gaze down 1.5s →  Like / Save menu
echo    * Press Q        →  Quit
echo   ══════════════════════════════════════════
echo.
echo   Starting... (calibration takes ~5 seconds)
echo.

:: ── Launch ────────────────────────────────────────────────────────────────────
%PYTHON% main.py

echo.
pause
