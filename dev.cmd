@echo off
where python >nul 2>&1 && (python "%~dp0scripts\dev.py") || (py "%~dp0scripts\dev.py")
if errorlevel 1 pause
