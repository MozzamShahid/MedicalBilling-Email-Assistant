@echo off
rem Double-click to start the CRM at http://localhost:8000 (works even when PowerShell scripts are blocked).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
