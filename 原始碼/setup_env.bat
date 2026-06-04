@echo off
cd /d "%~dp0"

echo ============================================
echo  BMS FW Validation - Environment Setup
echo ============================================
echo.

REM ---- 1. Locate Python 3.10+ (prefer py launcher, newest first; skip MS Store stub & old versions) ----
set "PYEXE="
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    if not defined PYEXE py -%%V -c "import sys" >nul 2>nul && set "PYEXE=py -%%V"
)
if not defined PYEXE python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul && set "PYEXE=python"
if defined PYEXE goto :py_ok
echo [ERROR] Python 3.10+ not found. Install from https://www.python.org/downloads/
echo         During install, check "Add Python to PATH".
echo         (Note: the Microsoft Store "python" stub does not count.)
pause
exit /b 1
:py_ok
echo        Using Python: %PYEXE%

echo [1/4] Creating Python virtual environment "venv-ai" ...
if exist "venv-ai\Scripts\python.exe" (
    echo        venv-ai already exists, skipping.
) else (
    %PYEXE% -m venv venv-ai
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo [2/4] Installing Python packages from requirements.txt ...
"venv-ai\Scripts\python.exe" -m pip install --upgrade pip
"venv-ai\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Python package installation failed.
    pause
    exit /b 1
)

echo.
echo [3/4] Checking Node.js / pnpm ...
where pnpm >nul 2>nul
if errorlevel 1 (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [WARN] Node.js / npm not found. Install Node.js first: https://nodejs.org/
        echo        Then re-run this script.
        pause
        exit /b 1
    )
    echo        pnpm not found, installing it via npm ...
    call npm install -g pnpm
    if errorlevel 1 (
        echo [ERROR] pnpm install failed. Run manually: npm install -g pnpm
        pause
        exit /b 1
    )
)

echo.
echo [4/4] Installing frontend packages (pnpm install) ...
pushd frontend
call pnpm install
if errorlevel 1 (
    echo [ERROR] Frontend package installation failed.
    popd
    pause
    exit /b 1
)
popd

echo.
echo ============================================
echo  Setup complete!
echo  Next steps:
echo    - Run build_exe.bat   : build the EXE
echo    - Run start.bat       : dev mode (backend + frontend)
echo ============================================
pause
