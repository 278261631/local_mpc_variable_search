@echo off
REM Start the Fast PyMPC server in a new window.
REM Usage: start_pympc_fast_server_new_window.bat [PORT] [WORKERS]

set SCRIPT_DIR=%~dp0
start "Fast PyMPC Server" cmd /c ""%SCRIPT_DIR%\start_pympc_fast_server.bat" %*"
