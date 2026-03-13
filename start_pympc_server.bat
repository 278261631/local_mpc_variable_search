@echo off
REM Start PyMPC Asteroid Search Server

echo Starting PyMPC Asteroid Search Server...
echo.

set PORT=5001
set WORKERS=4

if not "%1"=="" set PORT=%1
if not "%2"=="" set WORKERS=%2

echo Port: %PORT%
echo Workers: %WORKERS%
echo.

python pympc_server/pympc_asteroid_server.py --port %PORT% --workers %WORKERS%

