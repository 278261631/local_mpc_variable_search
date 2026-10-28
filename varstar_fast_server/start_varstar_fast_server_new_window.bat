@echo off
REM Start the fast variable star search server in its own console window.
REM Usage: start_varstar_fast_server_new_window.bat [PORT] [CATALOG]

set SCRIPT_DIR=%~dp0
start "Fast VarStar Server" cmd /c ""%SCRIPT_DIR%\start_varstar_fast_server.bat" %*"
