@echo off
setlocal

chcp 65001 >nul
set "ROOT=%~dp0"

echo Starting Xiaohei ERP development services...
echo.
echo Root: %ROOT%
echo API:  http://127.0.0.1:8000
echo Web:  http://localhost:3000
echo.
echo Note: this script starts API and Web only. It does not start the worker,
echo so queued Takealot submission tasks will not be processed by this launcher.
echo.

start "Xiaohei ERP API" cmd /k "cd /d ""%ROOT%"" && npm run dev:api"
start "Xiaohei ERP Web" cmd /k "cd /d ""%ROOT%"" && npm run dev:web"

echo Startup commands have been opened in separate windows.
echo Close those windows, or press Ctrl+C inside them, to stop the services.
echo.
pause
