@echo off
REM Test ASTAP Variable Star Search Web Service using wget

echo Testing ASTAP Variable Star Search Server with wget
echo.

echo [1] Health check
wget -q -O - http://localhost:5000/health
echo.
echo.

echo [2] Catalog info
wget -q -O - http://localhost:5000/info
echo.
echo.

echo [3] Search Betelgeuse - save to file
wget -q -O betelgeuse_result.json "http://localhost:5000/search?ra=88.79&dec=7.41&radius=60"
type betelgeuse_result.json
echo.
echo.

echo [4] Search with parameters
wget -q -O - "http://localhost:5000/search?ra=279.23&dec=38.78&radius=120&top=5"
echo.
echo.

echo Test completed
if exist betelgeuse_result.json del betelgeuse_result.json

