@echo off
REM Test HIP Star Search Web Service

echo Testing HIP Star Search Server...
echo.

set HOST=localhost
set PORT=5002

echo [1] Health check
curl.exe -s "http://%HOST%:%PORT%/health"
echo.
echo.

echo [2] Catalog info
curl.exe -s "http://%HOST%:%PORT%/info"
echo.
echo.

echo [3] Search around Betelgeuse
curl.exe -s "http://%HOST%:%PORT%/search?ra=88.79&dec=7.41&radius=120&top=10"
echo.
echo.

echo [4] Search with magnitude limit
curl.exe -s "http://%HOST%:%PORT%/search?ra=279.23&dec=38.78&radius=180&max_mag=8&top=10"
echo.
echo.

echo Test completed

