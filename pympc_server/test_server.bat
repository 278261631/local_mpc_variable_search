@echo off
REM Test PyMPC Asteroid Server with curl

echo Testing PyMPC Asteroid Server...
echo.

set HOST=localhost
set PORT=5001

echo 1. Health check:
curl.exe -s "http://%HOST%:%PORT%/health"
echo.
echo.

echo 2. Server info:
curl.exe -s "http://%HOST%:%PORT%/info"
echo.
echo.

echo 3. Single search (epoch 60700):
curl.exe -s "http://%HOST%:%PORT%/search?ra=88.79&dec=7.41&epoch=60700&radius=300"
echo.
echo.

echo 4. Search with magnitude limit:
curl.exe -s "http://%HOST%:%PORT%/search?ra=120.5&dec=-12.3&epoch=60700&radius=600&max_mag=18"
echo.
echo.

echo 5. Single search (MJD 61111.72467592593, radius 36 arcsec):
curl.exe -s "http://%HOST%:%PORT%/search?ra=110.284428216144&dec=17.966352318820668&epoch=61111.72467592593&radius=36.0"
echo.

curl.exe "http://localhost:5001/search?ra=333.76386876150417&dec=-14.206817474659415&epoch=61111.72467592593&radius=30.0&max_mag=20"

curl.exe -s "http://localhost:5001/search?ra=93.77911570823565&dec=17.317754905956306&epoch=61111.71299768519&radius=36.0"



curl.exe -s "http://localhost:5001/search?ra=84.99053848514775&dec=23.39787486566993&epoch=61111.71430555556&radius=36.0"

curl.exe -s "http://localhost:5001/search?ra=84.01320594826623&dec=24.430126124764744&epoch=61111.71430555556&radius=36.0"