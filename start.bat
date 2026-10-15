@echo off
setlocal
title TheBlueBook Scraper - Setup
echo ========================================
echo   TheBlueBook.com Scraper - Setup
echo ========================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install it from https://www.python.org/downloads/
    pause
    exit /b
)

if not exist venv (
    echo [1/4] Creating virtual environment...
    python -m venv venv
) else (
    echo [1/4] Virtual environment already exists, skipping creation.
)

echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat

echo [3/4] Installing dependencies ^(this may take a minute^)...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Dependency installation failed. Check your internet connection.
    pause
    exit /b
)

echo.
echo [4/4] Launching scraper...
echo ----------------------------------------
echo.
python scraper.py

echo.
echo ----------------------------------------
echo Finished. Results saved to results.csv ^(if any data was found^).
echo Press any key to exit.
pause >nul