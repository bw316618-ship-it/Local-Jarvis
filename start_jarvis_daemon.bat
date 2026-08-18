@echo off
title Jarvis

cd /d "%~dp0"

echo ========================================
echo           Starting Jarvis
echo ========================================
echo.

echo [1/2] Starting Jarvis HUD daemon...
start "Jarvis HUD" cmd /k "python jarvis_daemon.py"

timeout /t 2 /nobreak >nul

echo [2/2] Starting Jarvis backend daemon...
start "Jarvis Backend" cmd /k "python jarvis_backend_daemon.py"

echo.
echo ========================================
echo        Jarvis services started
echo ========================================
echo.
echo HUD:     jarvis_daemon.py
echo Backend: jarvis_backend_daemon.py
echo.
echo You can close this launcher window.
pause