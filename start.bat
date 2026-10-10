@echo off
cd /d "%~dp0"
where py >nul 2>&1 && (py start.py %*) || (python start.py %*)
pause
