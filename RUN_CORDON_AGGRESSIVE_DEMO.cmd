@echo off
setlocal
cd /d "%~dp0"
python RUN_CORDON_AGGRESSIVE_OFFLINE.py demo
set "CODE=%ERRORLEVEL%"
echo.
echo Exit code: %CODE%. This is an OFFLINE SYNTHETIC test, not a Visum calibration.
pause
exit /b %CODE%
