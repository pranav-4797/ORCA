@echo off
title ORCA - one-click launcher
REM ============================================================
REM  ORCA one-click launcher (Windows)
REM  Double-click this file. It starts the Vite dev server,
REM  which auto-spawns the FastAPI backend on :8000 if it is
REM  not already running, then opens http://localhost:3000.
REM  Close this window (or Ctrl+C) to stop BOTH servers.
REM ============================================================

cd /d "%~dp0ORCA UI"

where npm >nul 2>nul
if errorlevel 1 (
  echo [ORCA] npm not found in PATH. Install Node.js first.
  pause
  exit /b 1
)

if not exist node_modules (
  echo [ORCA] First run - installing frontend dependencies...
  call npm install
  if errorlevel 1 (
    echo [ORCA] npm install failed. Check your internet connection.
    pause
    exit /b 1
  )
)

echo.
echo  ==============================================
REM   Backend needs ORCA_Backend\.env with GROQ_API_KEY
REM   for full LLM answers; without it the app still
REM   runs in degraded (template-answer) mode.
echo  ==============================================
echo.

REM Vite opens the browser itself once the dev server is ready,
REM and its config spawns the backend on :8000 automatically.
call npm run dev -- --open

echo.
echo  ORCA stopped.
pause
