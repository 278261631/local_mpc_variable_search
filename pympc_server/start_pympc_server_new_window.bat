@echo off
REM Start PyMPC server from repository root

set SCRIPT_DIR=%~dp0
start "PyMPC Server" cmd /c ""%SCRIPT_DIR%\start_pympc_server.bat" %*"
