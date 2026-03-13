@echo off
REM Update PyMPC asteroid catalog from Minor Planet Center

echo Updating asteroid catalog from MPC...
echo This may take several minutes...
echo.

python pympc_server/pympc_asteroid_server.py --update-only

