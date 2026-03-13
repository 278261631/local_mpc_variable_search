@echo off
REM Start ASTAP Variable Star Search Server

echo Starting ASTAP Variable Star Search Server...
echo.

set SCRIPT_DIR=%~dp0
set CATALOG=%SCRIPT_DIR%data\variable_stars_15.csv
set PORT=5000

if not "%1"=="" set CATALOG=%1
if not "%2"=="" set PORT=%2

echo Catalog: %CATALOG%
echo Port: %PORT%
echo.

python "%SCRIPT_DIR%astap_variable_search_server.py" --catalog "%CATALOG%" --port %PORT%

