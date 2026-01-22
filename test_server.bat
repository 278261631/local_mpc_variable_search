@echo off
REM Test ASTAP Variable Star Search Web Service

echo Testing ASTAP Variable Star Search Server
echo.

echo [1] Health check
curl -s http://localhost:5000/health
echo.
echo.

echo [2] Catalog info
curl -s http://localhost:5000/info
echo.
echo.

echo [3] Search Betelgeuse (alf_Ori) - RA=88.79 DEC=7.41
curl -s http://localhost:5000/search?ra=88.79^&dec=7.41^&radius=60
echo.
echo.

echo [4] Search Vega (alf_Lyr) - RA=279.23 DEC=38.78
curl -s http://localhost:5000/search?ra=279.23^&dec=38.78^&radius=120
echo.
echo.

echo [5] Wide search with magnitude limit
curl -s http://localhost:5000/search?ra=120.5^&dec=-12.3^&radius=3600^&max_mag=10^&top=10
echo.
echo.

echo [6] Empty result test
curl -s http://localhost:5000/search?ra=0^&dec=0^&radius=1
echo.
echo.

echo Test completed

