@echo off
title Medicare Healthcare Portal
echo =========================================================
echo  🏥 STARTING MEDICARE HEALTHCARE & MYSQL PORTAL
echo =========================================================

echo [*] Initializing MySQL Database Engine (Port 3307)...
tasklist /fi "imagename eq mysqld.exe" | findstr /i "mysqld.exe" >nul
if %errorlevel% neq 0 (
    echo [*] Starting local XAMPP MySQL daemon...
    start "" /b "C:\xampp\mysql\bin\mysqld.exe" --defaults-file="C:\xampp\mysql\bin\my.ini" --standalone
    timeout /t 2 /nobreak >nul
)
echo [✓] MySQL Engine is ready!

echo.
echo [*] Launching Medicare Web Application...
cd /d "C:\Users\shahs\OneDrive\Desktop\Medicare"
python run.py
if %errorlevel% neq 0 (
    echo.
    echo [*] Retrying with Python launcher 'py'...
    py run.py
)
pause
