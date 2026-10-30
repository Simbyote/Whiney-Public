@echo off
REM Builds dist\Whiney.exe (run on the maintainer's PC, with Vortex closed)
REM 1. Snapshots this PC's Skyrim setup into _packinfo\
REM 2. Bakes it, pack_config.json and the app into one windowed exe
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
call :findpy || goto :nopy

echo Installing/updating build tools...
%PY% -m pip install --quiet -r requirements-build.txt || goto :err

echo.
echo Snapshotting your Skyrim setup...
%PY% -m whiney --snapshot || goto :err

echo.
echo Building the exe (takes a minute)...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
%PY% -m PyInstaller --noconfirm --onefile --windowed --clean --name Whiney --icon assets\icon.ico ^
  --paths src --collect-submodules whiney ^
  --add-data "_packinfo;_packinfo" --add-data "pack_config.json;." --add-data "assets\icon.ico;assets" ^
  --add-data "release\README.txt;." ^
  --collect-all customtkinter --collect-all gdown --copy-metadata gdown --hidden-import psutil ^
  src\whiney\__main__.py || goto :err

echo.
echo Built: dist\Whiney.exe
echo Upload that one file to the shared Drive (zipping it first helps with browser warnings).
pause
exit /b 0

:findpy
where py >nul 2>nul && (set "PY=py" & exit /b 0)
python -c "import sys" >nul 2>nul && (set "PY=python" & exit /b 0)
exit /b 1

:nopy
echo.
echo Python isn't installed (or isn't on PATH).
echo   1. Download it from https://www.python.org/downloads/
echo   2. In the installer, TICK "Add python.exe to PATH" at the bottom.
echo   3. Close this window and run build.bat again.
pause
exit /b 1

:err
echo.
echo Build failed. Scroll up for the error.
pause
exit /b 1
