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

