@echo off
chcp 65001 >nul
title Trackpad do iPad
cd /d "%~dp0"

if errorlevel 1 (
    echo Nao encontrei a pasta do trackpad.py. Confira o caminho dentro deste .bat.
    pause
    exit /b 1
)
where py >nul 2>nul
if %errorlevel%==0 (
    py trackpad.py
) else (
    python trackpad.py
)
echo.
pause
