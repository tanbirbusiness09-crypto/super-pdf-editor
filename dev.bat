@echo off
setlocal
title PDF Studio - Development
cd /d "%~dp0"

if not exist "api\.venv\Scripts\python.exe" (
  echo Run start.bat once first.
  pause
  exit /b 1
)

start "PDF Studio API" cmd /k ""api\.venv\Scripts\python.exe" -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000"

pushd web
call npm run dev
popd
