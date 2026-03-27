@echo off
REM Start HIP Star Search Server

echo Starting HIP Star Search Server...
echo.

set SCRIPT_DIR=%~dp0
set CATALOG=%SCRIPT_DIR%..\data\hip_catalog.csv
set PORT=5002

if not "%1"=="" set CATALOG=%1
if not "%2"=="" set PORT=%2

echo Catalog: %CATALOG%
echo Port: %PORT%
echo.

python "%SCRIPT_DIR%hip_search_server.py" --catalog "%CATALOG%" --port %PORT%

