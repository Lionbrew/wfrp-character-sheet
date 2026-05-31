@echo off
title WFRP4e Character Sheet
color 0A

echo.
echo  ============================================================
echo   WFRP4e Character Sheet — Starting...
echo  ============================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not in PATH.
    echo.
    echo  Please install Python from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Check if pypdf is installed, install if missing
python -c "import pypdf" >nul 2>&1
if errorlevel 1 (
    echo  Installing required package: pypdf...
    echo  (This only happens once)
    echo.
    pip install pypdf
    if errorlevel 1 (
        echo.
        echo  ERROR: Failed to install pypdf.
        echo  Please run this command manually:  pip install pypdf
        echo.
        pause
        exit /b 1
    )
    echo.
    echo  Package installed successfully!
    echo.
)

:: Launch the app
echo  Launching WFRP4e Character Sheet...
echo.
python "%~dp0wfrp_app.py"

if errorlevel 1 (
    echo.
    echo  The application exited with an error.
    pause
)
