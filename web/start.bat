@echo off
cd /d "%~dp0"
echo Starting AssetWise Web...

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found.
    echo Please install from https://nodejs.org/
    pause
    exit /b 1
)

if not exist ".env.local" (
    copy .env.local.example .env.local
)

if not exist "node_modules" (
    echo Running npm install...
    npm install
)

echo.
echo Open http://localhost:3000 in your browser.
echo Press Ctrl+C to stop.
echo.
npm run dev
pause
