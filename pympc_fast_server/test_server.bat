@echo off
echo Waiting for server on port 5001...
timeout /t 3 /nobreak >nul
echo.
echo === health ===
curl.exe -s "http://127.0.0.1:5001/health"
echo.
echo === info ===
curl.exe -s "http://127.0.0.1:5001/info"
echo.
echo === search ===
curl.exe -s "http://127.0.0.1:5001/search?ra=88.79&dec=7.41&epoch=60000&radius=300"
echo.
pause
