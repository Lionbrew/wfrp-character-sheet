@echo off
title Build WFRP4e Standalone EXE
color 0A
echo.
echo  ============================================================
echo   WFRP4e Character Sheet - Build Standalone EXE
echo  ============================================================
echo.

:: ── Find Python ──────────────────────────────────────────────────────────────
set PYTHON=
set PIP=

:: Try 'python' command
python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python
    goto :found_python
)

:: Try 'python3' command
python3 --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python3
    goto :found_python
)

:: Try the Python launcher 'py'
py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py
    goto :found_python
)

:: Search common install locations
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
    "C:\Program Files\Python310\python.exe"
) do (
    if exist %%P (
        set PYTHON=%%P
        goto :found_python
    )
)

echo  ERROR: Python not found.
echo.
echo  Please install Python from https://www.python.org/downloads/
echo  During installation, tick "Add Python to PATH".
echo  Then run this script again.
echo.
pause
exit /b 1

:found_python
echo  Found Python: %PYTHON%

:: ── Find pip ─────────────────────────────────────────────────────────────────
:: Always use "python -m pip" which works even when pip.exe isn't in PATH
%PYTHON% -m pip --version >nul 2>&1
if not errorlevel 1 (
    set PIP=%PYTHON% -m pip
    goto :found_pip
)

echo  pip not found, attempting to install it...
%PYTHON% -m ensurepip --upgrade >nul 2>&1
%PYTHON% -m pip --version >nul 2>&1
if not errorlevel 1 (
    set PIP=%PYTHON% -m pip
    goto :found_pip
)

echo  ERROR: pip could not be found or installed.
echo  Try running:  %PYTHON% -m ensurepip
pause
exit /b 1

:found_pip
echo  Found pip: %PIP%
echo.

:: ── Install PyInstaller and pypdf ─────────────────────────────────────────────
echo  Installing PyInstaller and pypdf...
%PIP% install pyinstaller pypdf --quiet --upgrade
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install packages.
    echo  Try running this manually:
    echo    %PYTHON% -m pip install pyinstaller pypdf
    echo.
    pause
    exit /b 1
)
echo  Packages installed!
echo.

:: ── Run PyInstaller ───────────────────────────────────────────────────────────
echo  Building standalone exe (takes 1-2 minutes)...
echo.

%PYTHON% -m PyInstaller ^
    --onefile ^
    --noconsole ^
    --name "WFRP Character Sheet" ^
    --add-data "index.html;." ^
    --add-data "WFRP4_Fillable_Character_Sheet_Autofill.pdf;." ^
    --hidden-import pypdf ^
    --hidden-import pypdf._reader ^
    --hidden-import pypdf._writer ^
    --hidden-import pypdf.generic ^
    --hidden-import pypdf.filters ^
    --hidden-import pypdf.constants ^
    wfrp_app.py

if errorlevel 1 (
    echo.
    echo  ERROR: Build failed. See output above for details.
    echo.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   SUCCESS!
echo.
echo   Your standalone exe is ready:
echo   dist\WFRP Character Sheet.exe
echo.
echo   Copy that file anywhere - it needs no installation.
echo  ============================================================
echo.

:: Open the dist folder so user can find the exe
explorer dist

pause
