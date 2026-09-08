@echo off

echo Starting GeoSentinel AI...

start "GeoSentinel Backend" cmd /k "cd /d "%~dp0backend" && call .venv\Scripts\activate.bat && uvicorn app:app --reload --port 8000"

timeout /t 3 /nobreak >nul

start "GeoSentinel Frontend" cmd /k "cd /d "%~dp0frontend" && npm.cmd run dev"

timeout /t 5 /nobreak >nul

start http://localhost:5173

echo GeoSentinel AI has been launched.