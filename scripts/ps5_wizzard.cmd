@echo off
rem Starts the PS5 build wizard (ps5_wizzard.ps1) past the default execution policy. The ZIP files go to the current folder.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ps5_wizzard.ps1"
if errorlevel 1 pause
