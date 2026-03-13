@echo off
REM Update PyMPC asteroid catalog from Minor Planet Center

echo Updating asteroid catalog from MPC...
echo This may take several minutes...
echo.

set SCRIPT_DIR=%~dp0
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set NO_PROXY=*
set http_proxy=
set https_proxy=
set all_proxy=
set no_proxy=*
python "%SCRIPT_DIR%pympc_asteroid_server.py" --update-only

