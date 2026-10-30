@echo off
REM Packs ONLY mods added/changed since your last full pack into modpack_update.tar.gz.
REM Double-click, or drag your mods folder onto this file if you moved it.
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
call :findpy || goto :nopy
%PY% -m whiney.pack_mods --update %*
pause
exit /b

:findpy
where py >nul 2>nul && (set "PY=py" & exit /b 0)
python -c "import sys" >nul 2>nul && (set "PY=python" & exit /b 0)
exit /b 1

:nopy
echo.
echo Python isn't installed (or isn't on PATH).
echo   1. Download it from https://www.python.org/downloads/
echo   2. In the installer, TICK "Add python.exe to PATH" at the bottom.
echo   3. Close this window and run pack_update.bat again.
pause
exit /b 1
