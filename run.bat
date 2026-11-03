@echo off
rem ==============================================================================
rem Automated US Market Report Generator - Windows Launcher
rem ==============================================================================

cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ is required but was not found in your PATH.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [INFO] Creating virtual environment in .venv...
    python -m venv .venv
    echo [INFO] Installing required dependencies (one-time setup)...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    .venv\Scripts\python.exe -m pip install -e .
    echo [SUCCESS] Environment ready!
)

if "%~1"=="" (
    echo [INFO] Launching Market Report Generator with auto-open...
    .venv\Scripts\python.exe report.py -O
) else (
    .venv\Scripts\python.exe report.py %*
)
