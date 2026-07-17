@echo off
setlocal
rem Launch relative to this file so the repository works from any location.
where pyw.exe >nul 2>&1
if errorlevel 1 (
    echo Python launcher not found. Install Python 3.10 or newer first.
    exit /b 1
)
start "" pyw.exe -3 "%~dp0vdm.py"
