@echo off
REM Runs the app straight from source (no exe build) to try changes quickly.
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
where py >nul 2>nul && (py -m whiney & exit /b)
python -m whiney
