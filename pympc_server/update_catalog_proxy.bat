@echo off
REM Update PyMPC asteroid catalog from Minor Planet Center

echo Updating asteroid catalog from MPC...
echo This may take several minutes...
echo.

set SCRIPT_DIR=%~dp0
python "%SCRIPT_DIR%pympc_asteroid_server.py" --update-only

