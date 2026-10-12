@echo off
cd /d "%~dp0"
echo Starting Fast PyMPC Asteroid Server...
python pympc_fast_server.py --workers 8 --port 5001
pause
