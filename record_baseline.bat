@echo off
REM One-time: remembers what's in the full pack you ALREADY uploaded, without re-packing.
REM Only use if your mods haven't changed since you made that modpack.tar.gz.
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (echo Python isn't installed. Get it from python.org, tick "Add python.exe to PATH". & pause & exit /b 1)
%PY% -m whiney.pack_mods --baseline %*
pause
