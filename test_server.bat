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

REM RA=100.596374, DEC=1.352195

curl -s http://localhost:5000/search?ra=100.596374^&dec=1.352195^&radius=60

REM 变星1: 名称=Gaia DR3 3125888880340416768, 类型=DSCT|GDOR|SXPHE, RA=100.592770, DEC=1.357650, 像素距离=10.2px
curl -s http://localhost:5000/search?ra=100.592770^&dec=1.357650^&radius=60
REM 变星2: 名称=NSVS 12517695, 类型=M, RA=100.596090, DEC=1.352420, 像素距离=1.4px
curl -s http://localhost:5000/search?ra=100.596090^&dec=1.352420^&radius=60