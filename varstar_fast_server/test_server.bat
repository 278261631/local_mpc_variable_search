@echo off
set PORT=5000
if not "%1"=="" set PORT=%1

echo Waiting for server on port %PORT%...
timeout /t 3 /nobreak >nul
echo.
echo === health ===
curl.exe -s "http://127.0.0.1:%PORT%/health"
echo.
echo === info ===
curl.exe -s "http://127.0.0.1:%PORT%/info"
echo.
echo === search (alf_Ori, 60 arcsec) ===
curl.exe -s "http://127.0.0.1:%PORT%/search?ra=88.79&dec=7.41&radius=60"
echo.
echo === search (max_mag=8, top=20) ===
curl.exe -s "http://127.0.0.1:%PORT%/search?ra=88.79&dec=7.41&radius=300&max_mag=8&top=20"
echo.
echo === batch ===
curl.exe -s -X POST "http://127.0.0.1:%PORT%/search_batch" -H "Content-Type: application/json" -d "{\"queries\":[{\"ra\":88.79,\"dec\":7.41},{\"ra\":279.23,\"dec\":38.78}],\"radius\":120}"
echo.
pause
