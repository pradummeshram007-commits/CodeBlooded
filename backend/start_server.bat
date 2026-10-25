@echo off
:: ============================================================
:: ODIN Backend Server — Start Script
:: Runs the FastAPI server on port 8000
:: ============================================================

cd /d "%~dp0\.."

:: Kill any existing instance on port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    echo Killing existing process %%a on port 8000...
    taskkill /F /PID %%a >nul 2>&1
)

:: Load .env if it exists
if exist .env (
    echo Loading environment from .env...
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

echo.
echo  ██████╗ ██████╗ ██╗███╗   ██╗
echo  ██╔═══██╗██╔══██╗██║████╗  ██║
echo  ██║   ██║██║  ██║██║██╔██╗ ██║
echo  ██║   ██║██║  ██║██║██║╚██╗██║
echo  ╚██████╔╝██████╔╝██║██║ ╚████║
echo   ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝
echo.
echo  ODIN Backend API Server v2.4-CORP
echo  THOR + NORNS endpoints starting...
echo  API URL: http://localhost:8000
echo  Docs:    http://localhost:8000/docs
echo.
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload --log-level info
