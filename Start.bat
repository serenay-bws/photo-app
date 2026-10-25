@echo off
rem Dubbelklik dit bestand op Windows om Fotostudio te starten.
setlocal
cd /d "%~dp0"
title Fotostudio
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>nul && goto run
echo.
echo   Eenmalige installatie (kan een paar minuten duren)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
where uv >nul 2>nul || goto fail

:run
uv run --no-dev python -m app
if errorlevel 1 goto fail
goto :eof

:fail
echo.
echo   Er ging iets mis. Maak een screenshot van dit venster als je hulp vraagt.
pause
