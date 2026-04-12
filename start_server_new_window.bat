@echo off
REM Start variable star server in a new window

set SCRIPT_DIR=%~dp0
start "Variable Star Server" cmd /c ""%SCRIPT_DIR%start_server.bat" %*"
