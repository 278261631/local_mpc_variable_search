@echo off
REM Performance test for different catalog sizes

echo ASTAP Variable Star Search Server - Performance Test
echo.

echo ========================================
echo Test 1: Small catalog (variable_stars.csv - mag 11)
echo ========================================
start /B python astap_variable_search_server.py --catalog data/variable_stars.csv --port 5001
timeout /t 5 /nobreak >nul
curl -s "http://localhost:5001/info"
echo.
curl -s "http://localhost:5001/search?ra=88.79&dec=7.41&radius=60" | findstr query_time_ms
echo.
taskkill /F /FI "WINDOWTITLE eq *python*" >nul 2>&1
timeout /t 2 /nobreak >nul

echo.
echo ========================================
echo Test 2: Medium catalog (variable_stars_13.csv - mag 13)
echo ========================================
start /B python astap_variable_search_server.py --catalog data/variable_stars_13.csv --port 5002
timeout /t 5 /nobreak >nul
curl -s "http://localhost:5002/info"
echo.
curl -s "http://localhost:5002/search?ra=88.79&dec=7.41&radius=60" | findstr query_time_ms
echo.
taskkill /F /FI "WINDOWTITLE eq *python*" >nul 2>&1
timeout /t 2 /nobreak >nul

echo.
echo ========================================
echo Test 3: Large catalog (variable_stars_15.csv - mag 15)
echo ========================================
start /B python astap_variable_search_server.py --catalog data/variable_stars_15.csv --port 5003
timeout /t 10 /nobreak >nul
curl -s "http://localhost:5003/info"
echo.
curl -s "http://localhost:5003/search?ra=88.79&dec=7.41&radius=60" | findstr query_time_ms
echo.
taskkill /F /FI "WINDOWTITLE eq *python*" >nul 2>&1

echo.
echo Performance test completed

