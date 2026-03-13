@echo off
REM Start PyMPC Asteroid Search Server

echo Starting PyMPC Asteroid Search Server...
echo.

set PORT=5001
set WORKERS=4
set SCRIPT_DIR=%~dp0

if not "%1"=="" set PORT=%1
if not "%2"=="" set WORKERS=%2

echo Port: %PORT%
echo Workers: %WORKERS%
echo.

REM Disable proxy variables for this process and children
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set NO_PROXY=
set http_proxy=
set https_proxy=
set all_proxy=
set no_proxy=

python "%SCRIPT_DIR%pympc_asteroid_server.py" --port %PORT% --workers %WORKERS%

