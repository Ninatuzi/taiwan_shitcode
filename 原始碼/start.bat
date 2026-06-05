@echo off
echo Starting BMS FW Validation Tool...

start "Backend" cmd /k "cd /d %~dp0 && .\venv-ai\Scripts\uvicorn.exe backend.main:app --reload --port 7003 --host 0.0.0.0"

timeout /t 2 /nobreak >nul

start "Frontend" cmd /k "cd /d %~dp0\frontend && pnpm dev"

timeout /t 3 /nobreak >nul

start "" "http://localhost:5173"
