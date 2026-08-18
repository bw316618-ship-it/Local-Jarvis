@echo off
title Jarvis

cd /d "%~dp0"

echo ========================================
echo           Starting Jarvis
echo ========================================
echo.

echo Starting Jarvis (HUD + device backend, one shared runtime)...
start "Jarvis" cmd /k "python jarvis_backend_daemon.py"

echo.
echo ========================================
echo        Jarvis service started
echo ========================================
echo.
echo jarvis_backend_daemon.py starts BOTH the graphical HUD and the
echo phone/PC device-pairing backend, sharing one Jarvis runtime, so
echo there's only ever one assistant to talk to.
echo.
echo Do not also run jarvis_daemon.py alongside this -- that would start
echo a second, separate Jarvis with its own memory/state that the HUD
echo and paired devices here would NOT share.
echo.
echo You can close this launcher window.
pause