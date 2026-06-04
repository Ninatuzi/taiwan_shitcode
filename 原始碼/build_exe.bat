@echo off
cd /d "%~dp0"

echo ============================================
echo  BMS FW Validation - Build EXE
echo ============================================
echo.

REM ---- Precheck: environment must be set up ----
if not exist "venv-ai\Scripts\pyinstaller.exe" (
    echo [ERROR] venv-ai or pyinstaller not found.
    echo         Please run setup_env.bat first.
    pause
    exit /b 1
)

echo [1/3] Rebuilding frontend (pnpm build) ...
pushd frontend
call pnpm build
if errorlevel 1 (
    echo [ERROR] Frontend build failed.
    popd
    pause
    exit /b 1
)
popd

echo.
echo [2/3] Packaging with PyInstaller ...
"venv-ai\Scripts\pyinstaller.exe" app_gui.spec --distpath dist_exe_gui --workpath build_tmp_gui --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller packaging failed.
    pause
    exit /b 1
)

set "EXE=dist_exe_gui\BMS-FW-Validation\BMS-FW-Validation.exe"
if not exist "%EXE%" (
    echo [ERROR] Build finished but %EXE% not found.
    pause
    exit /b 1
)

echo.
echo [3/3] Copying .env ...
if exist ".env" (
    copy /Y ".env" "dist_exe_gui\BMS-FW-Validation\.env" >nul
    echo        .env copied to output folder.
) else (
    echo [WARN] .env not found. The built app will miss the AI key.
    echo        Manually place a .env containing ANTHROPIC_API_KEY into:
    echo        dist_exe_gui\BMS-FW-Validation\
)

echo.
echo ============================================
echo  Build complete!
echo  Output folder : %~dp0dist_exe_gui\BMS-FW-Validation\
echo  Executable    : BMS-FW-Validation.exe
echo  (Copy the WHOLE folder to run on another PC.)
echo ============================================
pause
