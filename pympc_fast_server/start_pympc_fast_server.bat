@echo off
REM Start Fast PyMPC Asteroid Search Server
REM Usage: start_pympc_fast_server.bat [PORT] [WORKERS]

echo Starting Fast PyMPC Asteroid Server...
echo.

set PORT=5001
set WORKERS=8
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
set NO_PROXY=*
set http_proxy=
set https_proxy=
set all_proxy=
set no_proxy=*

python "%SCRIPT_DIR%pympc_fast_server.py" --port %PORT% --workers %WORKERS%
pause
