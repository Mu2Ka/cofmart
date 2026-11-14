@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\run_local.py" %*
if errorlevel 1 pause
