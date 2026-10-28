@echo off
REM Start the fast variable star search server.
REM Usage: start_varstar_fast_server.bat [PORT] [CATALOG]

setlocal
set SCRIPT_DIR=%~dp0
set PORT=5000
set CATALOG=%SCRIPT_DIR%..\data\variable_stars_15.csv

if not "%1"=="" set PORT=%1
if not "%2"=="" set CATALOG=%2

echo Catalog: %CATALOG%
echo Port:    %PORT%
echo.

python "%SCRIPT_DIR%varstar_fast_server.py" --catalog "%CATALOG%" --port %PORT%
